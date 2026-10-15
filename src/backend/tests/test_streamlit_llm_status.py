"""Acceptance tests for #372: the v2 UI shows each result's llm_status_label.

Owner ruling 2026-10-14 (option c): "the front end needs to read from the
backend ... do not duplicate data as it is messy". The legacy UI is out of scope
(owner ruling: v2 only).

Contract:

* The backend sends ``llm_status_label`` with every analysis (see the #372
  section of ``test_main_endpoints``). The v2 results view renders that string,
  HTML-escaped, and nothing else: it never maps ``llm_status`` to copy itself,
  and never renders the raw ``llm_status`` token.
* A label that is missing, not a string, blank, or carries a control, format,
  line or paragraph separator character is not trusted: the result shows a
  visible error state (``st.error``) and no status copy at all, so it can never
  read as a success. Backend labels never contain those characters
  (``test_llm_status_copy.TestLabelContract``), so this only fires on a broken
  or forged response.
* ``src/webapp`` holds no copy of the label text and never loads the backend's
  ``app`` package or ``llm_status_copy.py``. Checked statically (every file,
  every fragment) and by running the UI under an audit hook.

Runs the real script through Streamlit's AppTest, reusing the #133 fixtures.
"""
from __future__ import annotations

import ast
import html
import json
import re
import secrets
import subprocess
import sys
import textwrap
import unicodedata
from pathlib import Path
from typing import Any, Iterator

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_auth_ratelimit import BACKEND_DIR, CHILD_TIMEOUT_S
from tests.test_llm_status_copy import (
    _EM_DASH,
    _V2_FORBIDDEN,
    HOSTILE_VALUES,
    MODULE_NAME,
    MODULE_PATH,
    OK,
    RAW_MARKER,
    UNKNOWN,
    copy_module,
    fallback_members,
    label,
    members,
    visible_text_variants,
)
from tests.test_streamlit_backend_auth import (  # noqa: F401  (fixtures are used by name)
    APPTEST_TIMEOUT_S,
    REVIEWER_IP,
    UNREACHABLE_BACKEND,
    V2_PATH,
    _Recorder,
    _results_state,
    _tree_text,
    fake_context,
    recorder,
    ui_env,
)

# The API field the backend sends (LIB-API, #372). Contract name, not config.
LABEL_FIELD = "llm_status_label"
WEBAPP_DIR = V2_PATH.parent
BACKEND_PACKAGE_DIR = BACKEND_DIR / "app"
_ABSENT = object()

# Proto types whose body Streamlit renders as markdown (and as HTML when
# allow_html is set). Raw markup in a label must never reach one of these.
_MARKDOWN_PROTOS = {"Markdown", "Alert"}
# Characters that forge structure in a markdown/HTML sink: a blank line ends an
# HTML block (CommonMark), bidi and zero-width controls disguise text.
_UNTRUSTED_CATEGORIES = {"Cc", "Cf", "Zl", "Zp", "Cs"}


def _apptest(status: Any = _ABSENT, shown: Any = _ABSENT) -> AppTest:
    at = AppTest.from_file(str(V2_PATH), default_timeout=APPTEST_TIMEOUT_S)
    at.session_state["view"] = "results"
    state = _results_state()
    if status is not _ABSENT:
        state["llm_status"] = status
    if shown is not _ABSENT:
        state[LABEL_FIELD] = shown
    at.session_state["analysis_result"] = state
    return at


def _run(at: AppTest) -> str:
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return "\n".join(_tree_text(at._tree))


def _shows(rendered: str, text: str) -> bool:
    return any(v in rendered for v in visible_text_variants(text))


def _protos(node: Any, seen: set[int] | None = None) -> Iterator[Any]:
    seen = set() if seen is None else seen
    if id(node) in seen:
        return
    seen.add(id(node))
    proto = getattr(node, "proto", None)
    if proto is not None and hasattr(proto, "DESCRIPTOR"):
        yield proto
    children = getattr(node, "children", None)
    if isinstance(children, dict):
        for child in children.values():
            yield from _protos(child, seen)


def _markdown_bodies(at: AppTest) -> list[str]:
    return [p.body for p in _protos(at._tree) if p.DESCRIPTOR.name in _MARKDOWN_PROTOS]


def _error_texts(at: AppTest) -> list[str]:
    return [str(e.value) for e in at.error]


def _status_copy_shown(rendered: str) -> list[str]:
    """Every backend label (and the rules-only marker) that appears on the page."""
    texts = [label(m) for m in members()] + [copy_module().RULES_ONLY_MARKER]
    return [t for t in texts if _shows(rendered, t)]


def _escape(text: str) -> str:
    return text.encode("unicode_escape").decode("ascii")[:80]


@pytest.fixture
def ui(ui_env: str, recorder: _Recorder, fake_context: None) -> None:
    # No network: every export download the results view makes is recorded.
    return None


# ---------------------------------------------------------------------------
# The label from the backend is shown, exactly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", members())
def test_v2_result_shows_the_backend_label_for_each_status(ui: None, status: str) -> None:
    at = _apptest(status, label(status))
    rendered = _run(at)
    shown = label(status)
    assert _shows(rendered, shown), status
    others = [m for m in members() if m != status and label(m) not in shown and _shows(rendered, label(m))]
    assert others == [], status
    # A trusted label is not an error.
    assert _error_texts(at) == []


def test_v2_result_shows_what_the_backend_sent_not_its_own_mapping(ui: None) -> None:
    # The label is a per-run value no mapping can hold, next to a success token.
    # Shown verbatim, and the UI's own idea of "ok" is nowhere: it reads the
    # backend field and computes nothing from llm_status.
    sentinel = f"Backend sent {secrets.token_hex(8)}"
    rendered = _run(_apptest(OK, sentinel))
    assert _shows(rendered, sentinel)
    assert not _shows(rendered, label(OK))


def test_v2_result_shows_the_backend_label_even_when_the_token_differs(ui: None) -> None:
    # Single source: whatever the token says, the page shows the backend's label.
    unknown_token_label = label(UNKNOWN)
    rendered = _run(_apptest(fallback_members()[0], unknown_token_label))
    assert _shows(rendered, unknown_token_label)
    assert not _shows(rendered, label(fallback_members()[0]))


_MARKUP_LABELS = [
    ("script", f"<script>{RAW_MARKER}</script>"),
    ("bold", f"<b>{RAW_MARKER}</b>"),
    ("img-onerror", f'<img src=x onerror="alert(1)">{RAW_MARKER}'),
    ("close-div", f"</div><div style='color:green'>{RAW_MARKER}"),
    ("entity", f"&lt;b&gt;{RAW_MARKER}"),
    ("quote-attr", f'"><a href="javascript:alert(1)">{RAW_MARKER}</a>'),
]


@pytest.mark.parametrize("text", [v for _, v in _MARKUP_LABELS], ids=[i for i, _ in _MARKUP_LABELS])
def test_v2_result_label_is_html_escaped(ui: None, text: str) -> None:
    at = _apptest(OK, text)
    rendered = _run(at)
    escaped = (html.escape(text), html.escape(text, quote=False))
    assert any(e in rendered for e in escaped), "label not shown HTML-escaped"
    # The raw markup never reaches a markdown or HTML sink.
    assert [b for b in _markdown_bodies(at) if text in b] == []


# ---------------------------------------------------------------------------
# An untrusted label is a visible error, never status copy
# ---------------------------------------------------------------------------

# Not a usable label: absent, non-strings (including a list or dict that wraps
# the success label), and blank strings.
_BAD_LABELS: list[tuple[str, Any]] = [
    ("missing", _ABSENT),
    ("none", None),
    ("int", 1),
    ("bool", True),
    ("float", 0.0),
    ("bytes", b"label"),
    ("list-of-ok", ["__OK__"]),
    ("dict-of-ok", {"text": "__OK__"}),
    ("empty", ""),
    ("space", " "),
    ("whitespace", " \t "),
]


def _bad_label(value: Any) -> Any:
    # Built at run time: the success label comes from the copy module.
    if isinstance(value, list):
        return [label(OK)]
    if isinstance(value, dict):
        return {"text": label(OK)}
    return value


def _assert_error_state(at: AppTest, rendered: str) -> None:
    errors = _error_texts(at)
    assert errors, "no visible error state"
    assert _status_copy_shown(rendered) == [], "status copy shown for an untrusted label"
    assert RAW_MARKER not in rendered
    for text in errors:
        assert _EM_DASH not in text  # LIB-VOICE V6
        assert _V2_FORBIDDEN.findall(text) == []  # LIB-VOICE V2


@pytest.mark.parametrize("status", [OK, UNKNOWN, fallback_members()[0]])
@pytest.mark.parametrize("value", [v for _, v in _BAD_LABELS], ids=[i for i, _ in _BAD_LABELS])
def test_v2_result_with_unusable_label_shows_error_state(ui: None, value: Any, status: str) -> None:
    at = _apptest(status, _bad_label(value))
    _assert_error_state(at, _run(at))


@pytest.mark.parametrize("value", [v for _, v in HOSTILE_VALUES], ids=[i for i, _ in HOSTILE_VALUES])
def test_v2_result_with_hostile_status_and_no_label_shows_error_state(ui: None, value: Any) -> None:
    # A response that dropped the label: the UI must not fall back to reading
    # (or echoing) the token, whatever it holds.
    at = _apptest(value)
    _assert_error_state(at, _run(at))


def _structure_breakers() -> list[str]:
    """Generated: every BMP character in an untrusted category, plus every
    character str.splitlines breaks on, plus sampled lone surrogates."""
    chars = {
        chr(cp)
        for cp in range(0x10000)
        if unicodedata.category(chr(cp)) in _UNTRUSTED_CATEGORIES - {"Cs"}
    }
    chars |= {c for c in map(chr, range(0x10000)) if len(f"a{c}b".splitlines()) > 1}
    chars |= {chr(cp) for cp in (0xD800, 0xDBFF, 0xDC00, 0xDFFF)}
    return sorted(chars)


def test_v2_result_label_with_structure_breaking_character_shows_error_state(ui: None) -> None:
    breakers = _structure_breakers()
    wrong: list[str] = []
    for ch in breakers:
        # The character sits between a success label and markup a breakout
        # would render: the page must show neither.
        forged = f"{label(OK)}{ch}{ch}<b>{RAW_MARKER}</b>"
        at = _apptest(OK, forged)
        at.run()
        if at.exception:
            wrong.append(f"{_escape(ch)}: exception")
            continue
        rendered = "\n".join(_tree_text(at._tree))
        if not _error_texts(at) or _status_copy_shown(rendered) or RAW_MARKER in rendered:
            wrong.append(_escape(ch))
    print(f"structure-breaking label characters rendered: {len(breakers)}")
    assert wrong == []


def test_v2_structure_breaker_table_has_both_polarities() -> None:
    # Contract test for the generated table: it holds every line-break kind and
    # bidi/zero-width controls, and no character a real label uses.
    breakers = set(_structure_breakers())
    for must in ("\n", "\r", "\x0b", "\x0c", "\x1c", "\x85", " ", " ", "‮", "​", "﻿", "\x00"):
        assert must in breakers, _escape(must)
    for m in members():
        assert not set(label(m)) & breakers, m


def test_v2_result_with_huge_label_renders(ui: None) -> None:
    # Size: a huge label must not crash the page.
    huge = RAW_MARKER * 100_000
    at = _apptest(OK, huge)
    _run(at)


# ---------------------------------------------------------------------------
# The raw llm_status token is never rendered (green today as a guard)
# ---------------------------------------------------------------------------
# "ok", "disabled" and "unknown" are not asserted absent: proto field names and
# ordinary page copy contain those words. The fallback tokens and RAW_MARKER
# values are distinctive.

_RAW_STATUS_CASES = [(i, v) for i, v in HOSTILE_VALUES if isinstance(v, str) and RAW_MARKER in v]


@pytest.mark.parametrize("status", fallback_members())
def test_v2_result_never_renders_the_status_token(ui: None, status: str) -> None:
    rendered = _run(_apptest(status, label(status)))
    assert status not in rendered


@pytest.mark.parametrize("value", [v for _, v in _RAW_STATUS_CASES], ids=[i for i, _ in _RAW_STATUS_CASES])
def test_v2_result_never_echoes_a_hostile_status(ui: None, value: str) -> None:
    rendered = _run(_apptest(value, label(UNKNOWN)))
    assert RAW_MARKER not in rendered


# ---------------------------------------------------------------------------
# No duplication: src/webapp holds no copy and loads no backend code
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    return " ".join(text.casefold().split()).strip(" .")


def _label_fragments() -> set[str]:
    """Each label, the rules-only marker, and each clause of a label (split at
    the colon), normalised. A clause of fewer than three words is too generic to
    flag."""
    texts = [label(m) for m in members()] + [copy_module().RULES_ONLY_MARKER]
    out = {_norm(t) for t in texts}
    for t in texts:
        out |= {_norm(p) for p in t.split(":") if len(_norm(p).split()) >= 3}
    return out


def _file_texts(path: Path) -> list[str]:
    raw = path.read_bytes().decode("utf-8", errors="replace")
    texts = [raw]
    if path.suffix == ".py":
        tree = ast.parse(raw, filename=path.name)
        texts += [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        # f-string pieces joined, so a label split across placeholders is found.
        texts += [
            "".join(v.value for v in n.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
            for n in ast.walk(tree)
            if isinstance(n, ast.JoinedStr)
        ]
    return texts


def _webapp_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def _restated_copy(root: Path) -> list[tuple[str, str]]:
    frags = _label_fragments()
    found = []
    for path in _webapp_files(root):
        for text in _file_texts(path):
            norm = _norm(text)
            found += [(path.name, f) for f in frags if f in norm]
    return sorted(set(found))


# Text references to the copy module in any file type (a path or a module
# name). Python imports of the backend package are checked on the AST. A
# comment that cites backend source is not a load; the audit-hook probe below
# is the behavioural check for loads the text can hide.
_BACKEND_REFERENCES = re.compile(r"llm_status_copy", re.IGNORECASE)


def _backend_references(root: Path) -> list[tuple[str, str]]:
    found = []
    for path in _webapp_files(root):
        raw = path.read_bytes().decode("utf-8", errors="replace")
        found += [(path.name, m.group(0)) for m in _BACKEND_REFERENCES.finditer(raw)]
        if path.suffix == ".py":
            tree = ast.parse(raw, filename=path.name)
            for n in ast.walk(tree):
                names = []
                if isinstance(n, ast.Import):
                    names = [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.module:
                    names = [n.module]
                found += [(path.name, f"import {x}") for x in names if x == "app" or x.startswith("app.")]
    return sorted(set(found))


def test_webapp_restates_no_label_text() -> None:
    files = _webapp_files(WEBAPP_DIR)
    assert V2_PATH in files, "v2 UI not scanned"
    assert _restated_copy(WEBAPP_DIR) == [], "label text must come from the backend response only"


def test_webapp_references_no_backend_module_or_file() -> None:
    assert _backend_references(WEBAPP_DIR) == []


# Positive and negative controls for both scanners: each finds a planted copy
# or a planted backend load, and finds nothing in clean files.
_PLANTED = {
    "full-label": ("restated", lambda: f"STATUS = {label(OK)!r}\n"),
    "concatenated": ("restated", lambda: "S = (" + " ".join(repr(w + " ") for w in label(UNKNOWN).split()) + ")\n"),
    "fragment-casefold": ("restated", lambda: f"S = {label(fallback_members()[0]).split(':')[1].upper()!r}\n"),
    "marker-in-markdown": ("restated", lambda: f"# {copy_module().RULES_ONLY_MARKER}\n"),
    "f-string-split": ("restated", lambda: "x = 1\nS = f'" + label(OK).replace(":", ":{x}") + "'\n"),
    "import-app": ("backend", lambda: "from app.llm_status_copy import llm_status_label\n"),
    "import-app-bare": ("backend", lambda: "import app\n"),
    "load-by-path": ("backend", lambda: "P = '../backend/app/llm_status_copy.py'\n"),
    "load-by-name": ("backend", lambda: "import importlib\nM = importlib.import_module('app.' + 'llm_status_copy')\n"),
    "clean": ("clean", lambda: "TITLE = 'Policy Reviewer'\nimport html, requests\n"),
}


@pytest.mark.parametrize("case", list(_PLANTED))
def test_webapp_scanners_find_planted_copies(tmp_path: Path, case: str) -> None:
    kind, body = _PLANTED[case]
    (tmp_path / "planted.py").write_text(body(), encoding="utf-8")
    restated, backend = _restated_copy(tmp_path), _backend_references(tmp_path)
    if kind == "restated":
        assert restated != []
    elif kind == "backend":
        assert backend != []
    else:
        assert restated == [] and backend == []


# Behaviour: run the UI (intake and results views) in a fresh, isolated
# interpreter under an audit hook, and record every file it opens and every
# module it imports. Nothing may come from the backend package.
_PROBE = textwrap.dedent(
    """
    import json, os, sys
    script, backend_pkg, module_path, module_name, state, reviewer_ip, backend_url = sys.argv[1:8]
    backend_pkg = os.path.realpath(backend_pkg)
    module_path = os.path.realpath(module_path)
    stem = os.path.splitext(os.path.basename(module_path))[0]
    touched = []

    def hook(event, args):
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            try:
                path = os.path.realpath(os.fsdecode(args[0]))
            except Exception:
                return
            if path == backend_pkg or path.startswith(backend_pkg + os.sep) or stem in path:
                touched.append(path)
        elif event == "import":
            name = str(args[0])
            if name == "app" or name.startswith("app.") or stem in name:
                touched.append("import " + name)

    sys.addaudithook(hook)
    os.environ["API_BASE_URL"] = backend_url
    from types import SimpleNamespace
    import requests, streamlit
    from streamlit.testing.v1 import AppTest

    response = requests.Response()
    response.status_code = 200
    response._content = b'{"id": "stub", "findings": []}'
    response.headers["Content-Type"] = "application/json"
    requests.sessions.Session.request = lambda self, method, url, **kw: response
    streamlit.context = SimpleNamespace(ip_address=reviewer_ip, headers={})

    for view in ("intake", "results"):
        at = AppTest.from_file(script, default_timeout=60)
        if view == "results":
            at.session_state["view"] = "results"
            at.session_state["analysis_result"] = json.loads(state)
        at.run()
        assert not at.exception, [e.value for e in at.exception]
    loaded = [m for m in sys.modules if m == "app" or m.startswith("app.") or m == module_name or stem in m]
    print(json.dumps({"touched": sorted(set(touched)), "loaded": sorted(loaded)}))
    """
)


def _probe(script: Path) -> dict[str, list[str]]:
    state = {**_results_state(), "llm_status": OK, LABEL_FIELD: f"Backend sent {secrets.token_hex(8)}"}
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            _PROBE,
            str(script),
            str(BACKEND_PACKAGE_DIR),
            str(MODULE_PATH),
            MODULE_NAME,
            json.dumps(state),
            REVIEWER_IP,
            UNREACHABLE_BACKEND,
        ],
        capture_output=True,
        text=True,
        timeout=CHILD_TIMEOUT_S,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_v2_ui_loads_nothing_from_the_backend_when_run() -> None:
    seen = _probe(V2_PATH)
    assert seen == {"touched": [], "loaded": []}


_PLANTED_LOADERS = {
    "by-path": "import importlib.util\n"
    "spec = importlib.util.spec_from_file_location('copy_probe', {module_path!r})\n"
    "mod = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(mod)\n",
    "by-import": "import sys\nsys.path.insert(0, {backend_dir!r})\nimport {module_name}\n",
    "by-read": "open({module_path!r}, encoding='utf-8').read()\n",
}


@pytest.mark.parametrize("case", list(_PLANTED_LOADERS))
def test_v2_load_probe_detects_a_planted_backend_load(tmp_path: Path, case: str) -> None:
    # Positive control: the audit-hook probe sees each way a UI could load the
    # backend copy, so the empty result above means something.
    script = tmp_path / "planted_ui.py"
    script.write_text(
        "import streamlit as st\n"
        + _PLANTED_LOADERS[case].format(
            module_path=str(MODULE_PATH), backend_dir=str(BACKEND_DIR), module_name=MODULE_NAME
        )
        + "st.write('planted')\n",
        encoding="utf-8",
    )
    seen = _probe(script)
    assert seen["touched"] or seen["loaded"], seen
