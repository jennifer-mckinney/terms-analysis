"""Acceptance tests for #133 on the Streamlit v2 side (ruling 6, sec H2 and M4).

Contract the UI must meet (names are the test author's proposal; see the #133 tests
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
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest
import requests
import streamlit
from streamlit.testing.v1 import AppTest

V2_PATH = Path(__file__).resolve().parents[2] / "webapp" / "app_streamlit_v2.py"
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


def _load_v2() -> ModuleType:
    name = f"_v2_under_test_{secrets.token_hex(4)}"
    spec = importlib.util.spec_from_file_location(name, V2_PATH)
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
    v2 = _load_v2()
    v2.st = _fake_st(_key())
    v2.call_analyze(context=[], jurisdictions=[], doc_type=None, industry=None, **inputs)
    posted = [c for c in recorder.calls if c["url"].endswith(path)]
    assert len(posted) == 1, [c["url"] for c in recorder.calls]
    _assert_authenticated(posted[0], ui_env)


def test_call_infer_sends_key_and_client_identity(ui_env: str, recorder: _Recorder) -> None:
    v2 = _load_v2()
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
    v2 = _load_v2()
    v2.st = _fake_st(_key())
    assert v2.call_infer(None, "We share data.") == {"id": "stub", "findings": []}


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
        v2 = _load_v2()
    except Exception as exc:  # refusing a malformed key at import is acceptable
        assert hostile_key.strip() not in str(exc)
        return
    v2.st = _fake_st(_key())
    for inputs, _ in ((c.values[0], c.values[1]) for c in ANALYZE_CASES):
        v2.call_analyze(context=[], jurisdictions=[], doc_type=None, industry=None, **inputs)
    v2.call_infer("https://example.com/terms", None)
    shown = repr(v2.st.mock_calls)
    assert hostile_key.strip() not in shown
