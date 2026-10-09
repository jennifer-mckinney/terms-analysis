"""Shared fixtures for the weekly wiring audit tests (card #224, ADR 0002).

Not a test module (no ``test_`` prefix). The four ``test_wiring_audit_*.py``
files import it as ``tests.wiring_audit_support``.

The contract these tests pin for the code under ``scripts/audit/``
(design gate, docs section 2; every name below is used by at least one test):

* ``scripts/audit/config.json``: the ONE config file (design s.2 "Config";
  the brief's ``.github/wiring-audit/config.json`` is superseded by the
  design's path). Loaded only through ``scripts/audit/config.py``
  ``load_config(path) -> dict``, which raises ``ConfigError`` (a
  ``ValueError`` subclass) naming the offending key. Repo-relative paths in
  it (``leak_scan_script``, ``leak_scan_patterns``, ``personal_path_patterns``,
  ``canary_fixture``) resolve against the audited checkout (``--repo``).
* ``inventory.py``: ``main(argv) -> int``; CLI ``--repo DIR --config FILE``
  prints JSON ``{"modules": [{"path": ..., "custom_id": ..., ...}], ...}``.
* ``submit.py``: ``main(argv, *, http=None, env=None) -> int``; CLI
  ``--repo DIR --config FILE --artifact FILE``.
* ``collect.py``: ``main(argv, *, http=None, env=None) -> int``; CLI
  ``--config FILE --artifact FILE``.
* ``http(method, url, headers, body) -> (status, body_bytes)``: the one
  injectable transport (default: stdlib urllib). It may raise ``OSError``.
* Each of inventory/submit/collect exposes ``EXIT_CODES: dict[str, int]``;
  a name means the same number in every module (one table, F10).
* Time comes from ``time.sleep`` / ``time.monotonic`` / ``time.time``, which
  the tests replace with a fake clock (no real waiting).
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[3]
AUDIT_DIR = REPO_ROOT / "scripts" / "audit"
CONFIG_PATH = AUDIT_DIR / "config.json"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
SUBMIT_WORKFLOW = WORKFLOW_DIR / "wiring-audit-submit.yml"
COLLECT_WORKFLOW = WORKFLOW_DIR / "wiring-audit-collect.yml"

SECRET_NAME = "WIRING_AUDIT_API_KEY"  # ADR 0002 condition 4
# Assembled so this tracked file holds no secret-shaped literal.
FAKE_KEY = "sk-" + "ant-" + "TESTCANARY-" + "q7Zp" * 6
FAKE_GH_TOKEN = "ghs_" + "TESTGHTOKEN" + "x9" * 8
TEST_REPO = "example-owner/example-repo"
BATCH_ID = "msgbatch_01TESTWIRINGAUDIT"
CUSTOM_ID_RE = re.compile(r"[a-zA-Z0-9_-]{1,64}")  # Batches API custom_id rule

# Home roots are assembled at runtime (#145: no tracked home paths).
HOME_LINE_PATH = "/" + "Users" + "/someone-private/secret-notes"
PYTEST_TMP_LEAK = "pytest-" + "of-" + "someuser"  # evidence-leak-regex pytest-tmp
TILDE_DOCS_DIR = "~" + "/Docu" + "ments"  # personal-path-patterns row 3

CANARY_MARKER = "CANARY_MARKER_7f3a91"
CANARY_SYMBOL = "canary_unwired_entry"

# The model-output contract (design s.2 "Prompt").
KINDS = ("unwired_entry_point", "zero_caller_public", "self_skipping_test", "workflow_never_runs", "other")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


# --- loading the code under test ---------------------------------------------


def load_audit_module(name: str) -> ModuleType | None:
    """Load scripts/audit/<name>.py by path, or None when it does not exist.

    A missing module must turn its tests red through an assertion, not a
    collection-time ImportError that hides every other test in the file.
    """
    path = AUDIT_DIR / f"{name}.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"wiring_audit_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(name: str) -> ModuleType:
    module = load_audit_module(name)
    assert module is not None, f"scripts/audit/{name}.py does not exist (card #224 not implemented)"
    return module


def real_config() -> dict[str, Any]:
    """The shipped config, read as plain JSON (tests read values, never restate them)."""
    assert CONFIG_PATH.is_file(), "scripts/audit/config.json does not exist (card #224 not implemented)"
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def write_config(tmp: Path, **overrides: Any) -> tuple[Path, dict[str, Any]]:
    """A copy of the shipped config with explicit overrides, written to tmp."""
    cfg = copy.deepcopy(real_config())
    cfg.update(overrides)
    path = tmp / "wiring-audit-config.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path, cfg


def exit_code(module: ModuleType, name: str) -> int:
    codes = getattr(module, "EXIT_CODES", None)
    assert isinstance(codes, dict), f"{module.__name__}: EXIT_CODES table missing"
    assert name in codes, f"{module.__name__}: EXIT_CODES has no {name!r}"
    return codes[name]


# --- fixture git repositories --------------------------------------------------

_GIT_ENV_DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_CONFIG_PARAMETERS")


def git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_DROP}
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        }
    )
    return env


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-c", "core.excludesFile=" + os.devnull, "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        env=git_env(),
        capture_output=True,
        check=True,
        timeout=60,
    )


def make_repo(
    root: Path,
    files: dict[str, str | bytes],
    *,
    untracked: dict[str, str | bytes] | None = None,
    symlinks: dict[str, str] | None = None,
) -> Path:
    """git init + commit `files` (forced past any ignore rule) and `symlinks`."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    for rel, target in (symlinks or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, p)
    if files or symlinks:
        git(root, "add", "-f", "--", *files, *(symlinks or {}))
        git(root, "commit", "-q", "-m", "fixture")
    for rel, content in (untracked or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return root


def governance_files(cfg: dict[str, Any]) -> dict[str, bytes]:
    """The real leak scanner and pattern files, at the config's repo-relative paths."""
    out: dict[str, bytes] = {}
    for key in ("leak_scan_script", "leak_scan_patterns", "personal_path_patterns"):
        rel = cfg[key]
        out[rel] = (REPO_ROOT / rel).read_bytes()
    return out


def canary_source(extra: str = "") -> str:
    return (
        f'"""Synthetic canary module ({CANARY_MARKER}): a public entry point nothing calls."""\n'
        f"def {CANARY_SYMBOL}() -> int:\n    return 1\n" + extra
    )


def module_source(marker: str, symbol: str) -> str:
    return f'"""Module {marker}."""\n\n\ndef {symbol}() -> str:\n    return "{marker}"\n'


STD_MODULES = {
    "src/backend/app/alpha.py": ("ALPHA_MARKER_51c2", "alpha_fn"),
    "src/backend/app/beta.py": ("BETA_MARKER_09ae", "beta_main"),
}


def audit_repo(
    tmp: Path,
    cfg: dict[str, Any],
    *,
    extra: dict[str, str | bytes] | None = None,
    canary: str | None = None,
    untracked: dict[str, str | bytes] | None = None,
    symlinks: dict[str, str] | None = None,
    modules: dict[str, tuple[str, str]] | None = None,
) -> Path:
    files: dict[str, str | bytes] = dict(governance_files(cfg))
    for rel, (marker, symbol) in (STD_MODULES if modules is None else modules).items():
        files[rel] = module_source(marker, symbol)
    files[cfg["canary_fixture"]] = canary_source() if canary is None else canary
    files.update(extra or {})
    return make_repo(tmp / "repo", files, untracked=untracked, symlinks=symlinks)


# --- network guard and the fake transport --------------------------------------


class NetworkUsed(AssertionError):
    pass


def ban_network(monkeypatch: Any) -> list[str]:
    """Make any real socket/urllib use record a hit and raise."""
    import socket
    import urllib.request

    hits: list[str] = []

    def _refuse(*args: Any, **kwargs: Any) -> Any:
        hits.append(repr(args)[:200])
        raise NetworkUsed("real network call attempted in a wiring-audit test")

    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(urllib.request, "urlopen", _refuse)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _refuse)
    return hits


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000.0
        self.sleeps = 0

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.now += max(float(seconds), 0.001)

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.now


def install_clock(monkeypatch: Any) -> FakeClock:
    clock = FakeClock()
    monkeypatch.setattr(time, "sleep", clock.sleep)
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    monkeypatch.setattr(time, "time", clock.time)
    return clock


class Call:
    def __init__(self, method: str, url: str, headers: Any, body: Any) -> None:
        self.method = method.upper()
        self.url = url
        self.path = urlsplit(url).path
        self.query = urlsplit(url).query
        self.headers = {str(k).lower(): str(v) for k, v in dict(headers or {}).items()}
        self.body = body if isinstance(body, (bytes, type(None))) else str(body).encode("utf-8")

    def json(self) -> Any:
        return json.loads(self.body or b"null")

    @property
    def is_anthropic(self) -> bool:
        return self.path.startswith("/v1/")

    @property
    def is_github(self) -> bool:
        return self.path.startswith("/repos/")


Handler = Callable[[Call], "tuple[int, bytes]"]


def jbytes(obj: Any) -> bytes:
    return json.dumps(obj).encode("utf-8")


class FakeHTTP:
    """Records every call; answers from routes (method, path regex) or 599."""

    MAX_CALLS = 5000

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.routes: list[tuple[str, re.Pattern[str], Handler]] = []
        self.unexpected: list[str] = []
        self.on_call: list[Callable[[Call], None]] = []

    def route(self, method: str, pattern: str, handler: Handler) -> None:
        self.routes.append((method.upper(), re.compile(pattern), handler))

    def __call__(self, method: str, url: str, headers: Any = None, body: Any = None) -> tuple[int, bytes]:
        call = Call(method, url, headers, body)
        self.calls.append(call)
        for hook in self.on_call:
            hook(call)
        if len(self.calls) > self.MAX_CALLS:
            self.unexpected.append("call budget exhausted (unbounded loop?)")
            return 599, b'{"type":"error","error":{"type":"api_error","message":"fake budget"}}'
        for m, rx, handler in reversed(self.routes):
            if m == call.method and rx.fullmatch(call.path):
                return handler(call)
        self.unexpected.append(f"{call.method} {call.path}")
        return 599, b'{"type":"error","error":{"type":"api_error","message":"unrouted"}}'

    def find(self, method: str, pattern: str) -> list[Call]:
        rx = re.compile(pattern)
        return [c for c in self.calls if c.method == method.upper() and rx.fullmatch(c.path)]

    def outbound_text(self) -> str:
        """Every byte that left the process, decoded, plus JSON string leaves."""
        parts: list[str] = []
        for c in self.calls:
            parts.append(c.url)
            parts.extend(c.headers.values())
            if c.body:
                parts.append(c.body.decode("utf-8", "replace"))
                with contextlib.suppress(ValueError):
                    parts.extend(string_leaves(c.json()))
        return "\n".join(parts)


def string_leaves(obj: Any) -> Iterable[str]:
    stack = [obj]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            stack.extend(node.keys())
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


# --- Anthropic batch simulation --------------------------------------------------

COUNT_TOKENS = r"/v1/messages/count_tokens"
BATCHES = r"/v1/messages/batches"
BATCH = r"/v1/messages/batches/[^/]+"
RESULTS = r"/v1/messages/batches/[^/]+/results"
CANCEL = r"/v1/messages/batches/[^/]+/cancel"
ISSUES = r"/repos/[^/]+/[^/]+/issues"


def batch_object(status: str, counts: dict[str, int] | None = None, *, batch_id: str = BATCH_ID) -> dict[str, Any]:
    base = {"processing": 0, "succeeded": 0, "errored": 0, "canceled": 0, "expired": 0}
    base.update(counts or {})
    ended = status == "ended"
    return {
        "id": batch_id,
        "type": "message_batch",
        "processing_status": status,
        "request_counts": base,
        "created_at": "2026-10-05T02:00:00Z",
        "expires_at": "2026-10-06T02:00:00Z",
        "ended_at": "2026-10-05T03:00:00Z" if ended else None,
        "cancel_initiated_at": None,
        "archived_at": None,
        "results_url": f"https://api.anthropic.com/v1/messages/batches/{batch_id}/results" if ended else None,
    }


def route_submit(fake: FakeHTTP, *, tokens: int = 1000, create_status: int = 200) -> None:
    fake.route("POST", COUNT_TOKENS, lambda c: (200, jbytes({"input_tokens": tokens})))

    def create(call: Call) -> tuple[int, bytes]:
        if create_status != 200:
            return create_status, jbytes({"type": "error", "error": {"type": "api_error", "message": "boom"}})
        n = len(call.json().get("requests", []))
        return 200, jbytes(batch_object("in_progress", {"processing": n}))

    fake.route("POST", BATCHES, create)
    fake.route("POST", CANCEL, lambda c: (200, jbytes(batch_object("canceling"))))
    fake.route("GET", BATCH, lambda c: (200, jbytes(batch_object("ended", {"canceled": 1}))))
    fake.route("DELETE", BATCH, lambda c: (200, jbytes({"id": BATCH_ID, "type": "message_batch_deleted"})))


def created_requests(fake: FakeHTTP) -> list[dict[str, Any]]:
    creates = fake.find("POST", BATCHES)
    assert len(creates) == 1, f"expected exactly one batch create, saw {len(creates)}"
    reqs = creates[0].json()["requests"]
    assert isinstance(reqs, list)
    return reqs


def request_text(req: dict[str, Any]) -> str:
    return "\n".join(string_leaves(req.get("params", {})))


def run_main(module: ModuleType, argv: list[str], **kwargs: Any) -> tuple[int, str]:
    """Run module.main in-process; return (exit code, stdout + stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = module.main(argv, **kwargs)
        except SystemExit as exc:  # argparse or an explicit sys.exit
            rc = exc.code if isinstance(exc.code, int) else 1
    return rc, out.getvalue() + err.getvalue()


def audit_env(tmp: Path, **extra: str) -> dict[str, str]:
    env = {
        SECRET_NAME: FAKE_KEY,
        "GITHUB_STEP_SUMMARY": str(tmp / "step-summary.md"),
        "GITHUB_REPOSITORY": TEST_REPO,
        "GITHUB_SHA": "0" * 40,
        "PATH": os.environ.get("PATH", ""),
    }
    env.update(extra)
    return env


def summary_text(tmp: Path) -> str:
    p = tmp / "step-summary.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def finding_key(module_path: str, kind: str, symbol: str, repo: str = TEST_REPO) -> str:
    """Design s.2: sha256(f"{repo}|{module}|{kind}|{symbol}")[:16]."""
    return hashlib.sha256(f"{repo}|{module_path}|{kind}|{symbol}".encode("utf-8")).hexdigest()[:16]


def marker(key: str) -> str:
    return f"<!-- wiring-audit:{key} -->"


def lines_outside_fences(markdown: str) -> list[str]:
    """CommonMark-ish: a ``` or ~~~ run of N opens; a run of >= N same chars closes."""
    outside: list[str] = []
    fence: tuple[str, int] | None = None
    for line in markdown.split("\n"):
        stripped = line.lstrip(" ")
        m = re.match(r"(`{3,}|~{3,})", stripped)
        if fence is None:
            if m and len(line) - len(stripped) <= 3:
                fence = (m.group(1)[0], len(m.group(1)))
                continue
            outside.append(line)
        elif m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1] and stripped.strip() == m.group(1):
            fence = None
    return outside


def forbidden_chars(text: str, *, allow: str = "\n\t") -> list[str]:
    bad = []
    for ch in text:
        if ch in allow:
            continue
        if unicodedata.category(ch) in {"Cc", "Cf", "Cs", "Zl", "Zp", "Co", "Cn"}:
            bad.append(f"U+{ord(ch):04X}")
    return bad


def longest_run(text: str, ch: str) -> int:
    best = cur = 0
    for c in text:
        cur = cur + 1 if c == ch else 0
        best = max(best, cur)
    return best


def python_exe() -> str:
    return sys.executable


def copy_into(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
