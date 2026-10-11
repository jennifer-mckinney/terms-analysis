"""Acceptance tests for #133 on the Streamlit side (ruling 6, sec H2 and M4).

Both UIs ``run.sh`` can start are covered: v2 (default) and the legacy v1 UI
(``STREAMLIT_UI=v1``, PR #296 review round 2). A UI that sends no key 401s on every
backend call once ``API_KEY`` is set.

Contract each UI must meet (names are the test author's proposal; see the #133 tests
evidence note):

* ``BACKEND_API_KEY`` (environment, server side) is sent as ``X-API-Key`` on every
  backend call: ``/infer``, ``/analyze``, ``/analyze/url``, ``/analyze/file`` and the
  three export downloads.
* ``BACKEND_CLIENT_IP_HEADER`` (environment) names the header that carries the
  reviewer's address, taken from ``st.context`` (the server-side view of the
  connection), never from query parameters, session state or a browser-supplied
  header of the same name.
* The key is never rendered: not in an element, an error, a warning or an exception
  shown on the page, even when the HTTP library rejects it.
"""

from __future__ import annotations

import importlib.util
import secrets
import sys
import unicodedata
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest
import requests
import streamlit
from streamlit.testing.v1 import AppTest

V2_PATH = Path(__file__).resolve().parents[2] / "webapp" / "app_streamlit_v2.py"
# run.sh: STREAMLIT_UI=v1 starts this file (the legacy UI).
LEGACY_PATH = V2_PATH.with_name("app_streamlit_legacy.py")
KEY_ENV = "BACKEND_API_KEY"
HEADER_ENV = "BACKEND_CLIENT_IP_HEADER"
IDENTITY_HEADER = "X-Client-IP"
REVIEWER_IP = "203.0.113.7"  # RFC 5737 documentation address
SPOOFED_IP = "198.51.100.66"
UNREACHABLE_BACKEND = "http://127.0.0.1:9"  # discard port: connection refused
APPTEST_TIMEOUT_S = 60
EXPORT_PATHS = (".pdf", ".json", "analyses.csv")


def _key() -> str:
    # Generated per run; hex never matches the evidence leak patterns.
    return secrets.token_hex(24)


class _Recorder:
    """Stands in for every requests call (requests.get/post and any Session use)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record(self, method: str, url: str, **kwargs: Any) -> Any:
        headers = {str(k).lower(): v for k, v in (kwargs.get("headers") or {}).items()}
        self.calls.append({"method": method.upper(), "url": url, "headers": headers, "kwargs": kwargs})
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"{}"
        resp.json.return_value = {"id": "stub", "findings": []}
        return resp


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()

    def fake_request(self: Any, method: str, url: str, **kwargs: Any) -> Any:
        return rec.record(method, url, **kwargs)

    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)
    return rec


@pytest.fixture
def ui_env(monkeypatch: pytest.MonkeyPatch) -> str:
    key = _key()
    monkeypatch.setenv(KEY_ENV, key)
    monkeypatch.setenv(HEADER_ENV, IDENTITY_HEADER)
    monkeypatch.setenv("API_BASE_URL", UNREACHABLE_BACKEND)
    return key


def _load_ui(path: Path = V2_PATH) -> ModuleType:
    name = f"_ui_under_test_{secrets.token_hex(4)}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def _fake_st(attacker_key: str) -> MagicMock:
    fake = MagicMock()
    fake.context = SimpleNamespace(
        ip_address=REVIEWER_IP,
        headers={"X-Forwarded-For": REVIEWER_IP, IDENTITY_HEADER: SPOOFED_IP, "X-API-Key": attacker_key},
    )
    fake.query_params = {"api_key": attacker_key, "X-API-Key": attacker_key}
    fake.session_state = {"api_key": attacker_key, "backend_api_key": attacker_key}
    return fake


def _assert_authenticated(call: dict[str, Any], key: str) -> None:
    headers = call["headers"]
    assert headers.get("x-api-key") == key, (
        f"{call['method']} {call['url']} sent no X-API-Key from {KEY_ENV} (ruling 6)"
    )
    assert headers.get(IDENTITY_HEADER.lower()) == REVIEWER_IP, (
        f"{call['method']} {call['url']} did not send the reviewer address in {IDENTITY_HEADER}"
    )
    assert key not in call["url"], "the key must never travel in the URL"
    params = call["kwargs"].get("params") or {}
    assert key not in repr(params) and key not in repr(call["kwargs"].get("json"))


ANALYZE_CASES = [
    pytest.param({"url": "https://example.com/terms", "text": None, "file": None}, "/analyze/url", id="url"),
    pytest.param({"url": None, "text": "We share data.", "file": None}, "/analyze", id="text"),
    pytest.param(
        {"url": None, "text": None, "file": ("p.txt", b"We share data.", "text/plain")},
        "/analyze/file",
        id="file",
    ),
]


@pytest.mark.parametrize("inputs,path", ANALYZE_CASES)
def test_call_analyze_sends_key_and_client_identity(
    ui_env: str, recorder: _Recorder, inputs: dict[str, Any], path: str
) -> None:
    v2 = _load_ui()
    v2.st = _fake_st(_key())
    v2.call_analyze(context=[], jurisdictions=[], doc_type=None, industry=None, **inputs)
    posted = [c for c in recorder.calls if c["url"].endswith(path)]
    assert len(posted) == 1, [c["url"] for c in recorder.calls]
    _assert_authenticated(posted[0], ui_env)


def test_call_infer_sends_key_and_client_identity(ui_env: str, recorder: _Recorder) -> None:
    v2 = _load_ui()
    v2.st = _fake_st(_key())
    v2.call_infer("https://example.com/terms", None)
    posted = [c for c in recorder.calls if c["url"].endswith("/infer")]
    assert len(posted) == 1
    _assert_authenticated(posted[0], ui_env)


def _results_state() -> dict[str, Any]:
    return {
        "id": "abc",
        "name": "Stub Policy",
        "status": "completed",
        "findings": [],
        "grade": "A",
        "risk_score": 2.0,
        "confidence": 0.9,
        "summary": "Stub summary.",
        "document_text": "Stub policy text.",
    }


def _results_apptest() -> AppTest:
    at = AppTest.from_file(str(V2_PATH), default_timeout=APPTEST_TIMEOUT_S)
    at.session_state["view"] = "results"
    at.session_state["analysis_result"] = _results_state()
    return at


@pytest.fixture
def fake_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        streamlit,
        "context",
        SimpleNamespace(
            ip_address=REVIEWER_IP,
            headers={"X-Forwarded-For": REVIEWER_IP, IDENTITY_HEADER: SPOOFED_IP},
        ),
    )


def test_export_downloads_send_key_and_client_identity(
    ui_env: str, recorder: _Recorder, fake_context: None
) -> None:
    at = _results_apptest()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    exports = [c for c in recorder.calls if "/exports/" in c["url"]]
    assert sorted(any(c["url"].split("?")[0].endswith(p) for c in exports) for p in EXPORT_PATHS) == [True] * 3
    for call in exports:
        _assert_authenticated(call, ui_env)


def test_ui_without_backend_key_still_calls_backend(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    # Positive control (green today): the local developer setup with no key works.
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.delenv(HEADER_ENV, raising=False)
    monkeypatch.setenv("API_BASE_URL", UNREACHABLE_BACKEND)
    v2 = _load_ui()
    v2.st = _fake_st(_key())
    assert v2.call_infer(None, "We share data.") == {"id": "stub", "findings": []}
    assert len(recorder.calls) == 1
    # Nothing browser-supplied is forwarded as a credential or identity.
    assert "x-api-key" not in recorder.calls[0]["headers"]
    assert IDENTITY_HEADER.lower() not in recorder.calls[0]["headers"]


# ---------------------------------------------------------------------------
# The key is never rendered (ruling 9, sec M4). Green today as a guard: these hold
# while the UI sends no key, and must keep holding once it does. The key carries a
# trailing newline so that the HTTP library rejects it as a header value; the
# rejection message quotes the value, and the UI renders transport errors.
# ---------------------------------------------------------------------------


@pytest.fixture
def hostile_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = _key() + "\n"
    monkeypatch.setenv(KEY_ENV, key)
    monkeypatch.setenv(HEADER_ENV, IDENTITY_HEADER)
    monkeypatch.setenv("API_BASE_URL", UNREACHABLE_BACKEND)
    return key


def _tree_text(node: Any, seen: set[int] | None = None) -> Iterator[str]:
    seen = set() if seen is None else seen
    if id(node) in seen:
        return
    seen.add(id(node))
    proto = getattr(node, "proto", None)
    if proto is not None:
        yield str(proto)
    for attr in ("value", "body", "label", "message"):
        try:
            value = getattr(node, attr, None)
        except Exception:  # some element properties raise outside their widget type
            continue
        if isinstance(value, str):
            yield value
    children = getattr(node, "children", None)
    if isinstance(children, dict):
        for child in children.values():
            yield from _tree_text(child, seen)


def test_key_never_rendered_on_results_page(hostile_key: str, fake_context: None) -> None:
    at = _results_apptest()
    at.run()
    rendered = "\n".join(_tree_text(at._tree))
    rendered += "\n".join(str(e.value) for e in at.exception)
    for secret in (hostile_key, hostile_key.strip()):
        assert secret not in rendered


def test_key_never_rendered_when_analysis_fails(hostile_key: str) -> None:
    try:
        v2 = _load_ui()
    except Exception as exc:  # refusing a malformed key at import is acceptable
        assert hostile_key.strip() not in str(exc)
        return
    v2.st = _fake_st(_key())
    for inputs, _ in ((c.values[0], c.values[1]) for c in ANALYZE_CASES):
        v2.call_analyze(context=[], jurisdictions=[], doc_type=None, industry=None, **inputs)
    v2.call_infer("https://example.com/terms", None)
    shown = repr(v2.st.mock_calls)
    assert hostile_key.strip() not in shown


# ---------------------------------------------------------------------------
# Legacy UI (run.sh STREAMLIT_UI=v1), PR #296 review round 2 (MEDIUM): it sent no
# X-API-Key, so every backend call 401'd once API_KEY was set. Same contract as v2.
# ---------------------------------------------------------------------------


def _load_legacy() -> ModuleType:
    return _load_ui(LEGACY_PATH)


@pytest.mark.parametrize("inputs,path", ANALYZE_CASES)
def test_legacy_analyze_sends_key_and_client_identity(
    ui_env: str, recorder: _Recorder, inputs: dict[str, Any], path: str
) -> None:
    legacy = _load_legacy()
    legacy.st = _fake_st(_key())
    legacy.analyze_document(**inputs)
    posted = [c for c in recorder.calls if c["url"].endswith(path)]
    assert len(posted) == 1, [c["url"] for c in recorder.calls]
    _assert_authenticated(posted[0], ui_env)


def _legacy_export_apptest() -> AppTest:
    at = AppTest.from_file(str(LEGACY_PATH), default_timeout=APPTEST_TIMEOUT_S)
    at.session_state["findings"] = [
        {"title": "Stub", "severity": "high", "category": "Data", "excerpt": "We share data.", "confidence": 0.9}
    ]
    at.session_state["last_result"] = {"id": "abc", "findings": []}
    return at


def test_legacy_export_download_sends_key_and_client_identity(
    ui_env: str, recorder: _Recorder, fake_context: None
) -> None:
    at = _legacy_export_apptest()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    exports = [c for c in recorder.calls if "/exports/" in c["url"]]
    # "Did nothing" guard: the export tab must actually have called the backend.
    assert [c["url"].split("?")[0].endswith(".pdf") for c in exports] == [True], exports
    for call in exports:
        _assert_authenticated(call, ui_env)


def test_legacy_ui_without_backend_key_still_calls_backend(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder
) -> None:
    # Positive control (green today): the local developer setup with no key works
    # and sends no X-API-Key header at all.
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.delenv(HEADER_ENV, raising=False)
    monkeypatch.setenv("API_BASE_URL", UNREACHABLE_BACKEND)
    legacy = _load_legacy()
    legacy.st = _fake_st(_key())
    assert legacy.analyze_document(text="We share data.") == {"id": "stub", "findings": []}
    assert len(recorder.calls) == 1
    assert "x-api-key" not in recorder.calls[0]["headers"]
    assert IDENTITY_HEADER.lower() not in recorder.calls[0]["headers"]


def test_legacy_key_never_rendered_when_analysis_fails(hostile_key: str) -> None:
    try:
        legacy = _load_legacy()
    except Exception as exc:  # refusing a malformed key at import is acceptable
        assert hostile_key.strip() not in str(exc)
        return
    legacy.st = _fake_st(_key())
    for inputs, _ in ((c.values[0], c.values[1]) for c in ANALYZE_CASES):
        legacy.analyze_document(**inputs)
    shown = repr(legacy.st.mock_calls)
    assert hostile_key.strip() not in shown


def test_legacy_key_never_rendered_on_export_tab(hostile_key: str, fake_context: None) -> None:
    at = _legacy_export_apptest()
    at.run()
    rendered = "\n".join(_tree_text(at._tree))
    rendered += "\n".join(str(e.value) for e in at.exception)
    for secret in (hostile_key, hostile_key.strip()):
        assert secret not in rendered


# Hostile backend credentials in the environment (attack list A: structure forgery,
# encoding, look-alikes). Generated, not listed (QUALITY-BAR R2): every code point in
# Unicode categories Cc, Cf, Zs, Zl and Zp (all line breaks, bidi and zero-width
# controls, every space), every str.splitlines() breaker, the surrogateescape range
# os.environ uses for invalid UTF-8 bytes, and the non-ASCII letters NFKC folds to an
# ASCII letter. NUL is excluded only because no environment can hold it. For the
# header name, every printable ASCII character outside the RFC 9110 tchar set is
# added. v2 refuses these before any request with a fixed message naming the
# variable; the legacy UI must do the same (fail closed, no value echoed).
_HOSTILE_CATEGORIES = {"Cc", "Cf", "Zs", "Zl", "Zp"}
_RFC9110_TCHAR = set("!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def _generated_hostile_chars() -> tuple[str, ...]:
    chars = {chr(c) for c in range(1, 0x110000) if unicodedata.category(chr(c)) in _HOSTILE_CATEGORIES}
    chars |= {ch for ch in map(chr, range(1, 0x110000)) if len(("a" + ch + "b").splitlines()) > 1}
    chars |= {chr(c) for c in range(0xDC80, 0xDD00)}  # os.fsdecode of bytes 0x80-0xFF
    chars |= {
        chr(c)
        for c in range(0x80, 0x10000)
        if (folded := unicodedata.normalize("NFKC", chr(c))).isascii() and folded.isalpha()
    }
    return tuple(sorted(chars))


HOSTILE_CHARS = _generated_hostile_chars()
HEADER_NAME_ONLY_CHARS = tuple(ch for ch in map(chr, range(0x20, 0x7F)) if ch not in _RFC9110_TCHAR)
UI_PATHS = [pytest.param(V2_PATH, id="v2"), pytest.param(LEGACY_PATH, id="legacy")]


def _ui_analyze(ui: ModuleType, path: Path) -> Any:
    if path == LEGACY_PATH:
        return ui.analyze_document(text="We share data.")
    return ui.call_analyze(
        context=[], jurisdictions=[], doc_type=None, industry=None, url=None, text="We share data.", file=None
    )


@pytest.mark.parametrize("ui_path", UI_PATHS)
@pytest.mark.parametrize("env_name", [KEY_ENV, HEADER_ENV])
def test_ui_refuses_hostile_backend_credentials_before_any_request(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder, ui_path: Path, env_name: str
) -> None:
    monkeypatch.setenv("API_BASE_URL", UNREACHABLE_BACKEND)
    base = {KEY_ENV: _key(), HEADER_ENV: IDENTITY_HEADER}
    chars = HOSTILE_CHARS + (HEADER_NAME_ONLY_CHARS if env_name == HEADER_ENV else ())
    # Each character both inside the value and trailing it (the classic "\n" tail).
    cases = [(ch, base[env_name][:4] + ch + base[env_name][4:]) for ch in chars]
    cases += [(ch, base[env_name] + ch) for ch in chars]
    checked = 0
    for suffix, hostile in cases:
        monkeypatch.setenv(KEY_ENV, base[KEY_ENV])
        monkeypatch.setenv(HEADER_ENV, base[HEADER_ENV])
        monkeypatch.setenv(env_name, hostile)
        recorder.calls.clear()
        try:
            ui = _load_ui(ui_path)
        except Exception as exc:  # refusing at import is acceptable, without the value
            assert hostile not in str(exc) and base[env_name] not in str(exc)
            checked += 1
            continue
        ui.st = _fake_st(_key())
        assert _ui_analyze(ui, ui_path) is None, f"{env_name} with {suffix!r}: request not refused"
        assert recorder.calls == [], f"{env_name} with {suffix!r} reached the HTTP layer"
        shown = repr(ui.st.mock_calls)
        assert ui.st.error.called, f"{env_name} with {suffix!r}: no error shown"
        assert hostile not in shown and base[env_name] not in shown
        assert env_name in shown, "message honesty: the error names the variable to fix"
        checked += 1
    assert checked == len(cases)


@pytest.mark.parametrize("ui_path", UI_PATHS)
def test_ui_sends_key_without_identity_header_when_header_unconfigured(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder, ui_path: Path
) -> None:
    # Key set, BACKEND_CLIENT_IP_HEADER unset (a deployment without a trusted proxy):
    # the key still goes out, and no identity header is invented from browser input.
    key = _key()
    monkeypatch.setenv(KEY_ENV, key)
    monkeypatch.delenv(HEADER_ENV, raising=False)
    monkeypatch.setenv("API_BASE_URL", UNREACHABLE_BACKEND)
    ui = _load_ui(ui_path)
    ui.st = _fake_st(_key())
    _ui_analyze(ui, ui_path)
    assert len(recorder.calls) == 1, [c["url"] for c in recorder.calls]
    headers = recorder.calls[0]["headers"]
    assert headers.get("x-api-key") == key, f"{ui_path.name} sent no X-API-Key from {KEY_ENV}"
    assert IDENTITY_HEADER.lower() not in headers
    assert REVIEWER_IP not in repr(headers) and SPOOFED_IP not in repr(headers)
