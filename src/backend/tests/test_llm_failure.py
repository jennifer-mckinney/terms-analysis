"""HR5: any failure of the LLM step falls back to rule-only findings.

HR5: "LLM failures MUST fall back to rule-only findings with reduced
confidence". The whole LLM step (model selection, prompt build, request
encoding, the HTTP call, response parsing AND validation of the answer's
shape) sits behind ONE boundary in ``LocalAIClient.analyze()``. Every
non-cancellation exception there returns ``None`` (rules-only), with the
stage and exception type logged and no message or document text.
Cancellation still propagates.

Issue #91 r12 security F2: a lone surrogate in the legal context or the
document raised ``UnicodeEncodeError`` while httpx encoded the body.
Issue #91 F2 round security M1: a JSON object answer with wrong field types
(``"findings": null``, ``"overall_confidence": "high"``, a lone surrogate in
``summary``) passed ``analyze()`` and then raised out of ``analyze_text`` or
the response serialiser (a 500). ``analyze()`` must return either ``None``
or an answer ``analyze_text`` can use unchecked.

The HTTP layer is real httpx with a ``MockTransport`` (``localai_http``), so
the request body is encoded by the same code that raises in production.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from typing import Any, Callable, Dict, List, Optional, get_args

import httpx
import pytest

from app import schemas
from app.schemas import AnalysisPayload
from app.services import analyzer as analyzer_module
from app.services import localai as localai_module
from app.services.analyzer import analyze_text
from app.services.localai import LocalAIClient

_LOGGER_NAME = "uvicorn.error"
_DOC = "We sell personal information and use automated decision-making."
_JURISDICTIONS = ["US-CA", "GDPR"]
_GOOD_LLM_CONTENT = {"summary": "ok", "overall_confidence": 0.9, "findings": []}


def _ok_response(content: Any = None, raw: Any = None) -> httpx.Response:
    """A chat-completions response whose message content is ``raw`` (JSON text,
    or any non-string value to model a malformed ``content`` field)."""
    text = raw if raw is not None else json.dumps(content or _GOOD_LLM_CONTENT)
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


@pytest.fixture
def localai_http(monkeypatch) -> Callable[[Callable[[httpx.Request], httpx.Response]], List[httpx.Request]]:
    """Route LocalAIClient's httpx.AsyncClient through an httpx MockTransport.

    Call it with a responder; it returns the list of requests the responder
    received (empty means the request was never sent).
    """
    real_client = httpx.AsyncClient

    def _install(respond: Callable[[httpx.Request], httpx.Response]) -> List[httpx.Request]:
        sent: List[httpx.Request] = []

        def _record(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return respond(request)

        def _factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = httpx.MockTransport(_record)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", _factory)
        return sent

    return _install


def _chunk(text: str = "Article 17 erasure", section: str = "Article 17") -> Dict[str, Any]:
    return {"text": text, "section": section, "jurisdiction": "GDPR", "law": "gdpr", "status": "in_force"}


def _analyze(
    numbered_text: str = "0001| We sell your data.",
    legal_context: Optional[List[dict]] = None,
) -> Optional[Dict[str, Any]]:
    return asyncio.run(
        LocalAIClient().analyze(
            numbered_text=numbered_text,
            jurisdictions=["GDPR"],
            rule_findings=[],
            legal_context=legal_context,
        )
    )


def _fallback_records(caplog) -> List[logging.LogRecord]:
    return [r for r in caplog.records if "falling back to rules-only" in r.getMessage()]


# ---------------------------------------------------------------------------
# Answers the LLM can return. Raw JSON text, as it arrives in ``content``.
# ---------------------------------------------------------------------------

_VALID_FINDING: Dict[str, Any] = {
    "category": "data_sharing",
    "severity": "High",
    "confidence": 0.85,
    "excerpt": "We sell personal information",
    "explanation": "Sells data.",
    "jurisdictions": ["GDPR"],
    "evidence": {"line_start": 1, "line_end": 1, "legal_basis": ["GDPR Art. 6"]},
}

# Security M1: every row must make analyze() return None (rules-only). The
# whole answer is rejected; no field of it may be used.
_MALFORMED_ANSWERS: Dict[str, Any] = {
    # Not a JSON object at all.
    "content-list": "[1, 2]",
    "content-null": "null",
    "content-str": '"just text"',
    "content-int": "5",
    # ``content`` itself is not a string (a mutant returning an empty
    # "success" answer for non-string content must fail).
    "content-not-a-string": 7,
    # findings is not a list.
    "findings-null": '{"summary": "ok", "findings": null}',
    "findings-int": '{"summary": "ok", "findings": 5}',
    "findings-bool": '{"findings": true}',
    "findings-str": '{"findings": "abc"}',
    "findings-object": '{"findings": {"a": 1}}',
    # overall_confidence is not a finite number.
    "confidence-str": '{"findings": [], "summary": "ok", "overall_confidence": "high"}',
    "confidence-list": '{"findings": [], "overall_confidence": [1]}',
    # A JSON boolean is not a number (lax float coercion gives 1.0), and
    # "1_0" is not a plain numeric string (it would coerce to 10.0).
    "confidence-bool": '{"findings": [], "summary": "ok", "overall_confidence": true}',
    "confidence-underscore-str": '{"findings": [], "summary": "ok", "overall_confidence": "1_0"}',
    "confidence-nan": '{"findings": [], "summary": "ok", "overall_confidence": NaN}',
    "confidence-inf": '{"findings": [], "summary": "ok", "overall_confidence": Infinity}',
    "confidence-neg-inf": '{"findings": [], "summary": "ok", "overall_confidence": -Infinity}',
    # summary is not a string.
    "summary-object": '{"findings": [], "summary": {"a": 1}}',
    "summary-int": '{"findings": [], "summary": 7}',
    # A string that is not valid UTF-8 (lone surrogate via a JSON escape).
    "summary-lone-surrogate": '{"findings": [], "summary": "x\\ud800"}',
    "finding-lone-surrogate": json.dumps(
        {"summary": "ok", "findings": [{**_VALID_FINDING, "explanation": "MARK"}]}
    ).replace("MARK", "x\\udfff"),
}

# Allow rows: well-typed answers are returned with their fields intact.
_VALID_ANSWERS: Dict[str, Dict[str, Any]] = {
    "full": {**_GOOD_LLM_CONTENT, "findings": [_VALID_FINDING]},
    "empty-findings": _GOOD_LLM_CONTENT,
    "null-optionals": {"findings": [], "summary": None, "overall_confidence": None},
    "astral-summary": {"findings": [], "summary": "ok \U0001F600", "overall_confidence": 0.0},
    "confidence-one": {"findings": [], "summary": "ok", "overall_confidence": 1},
    # Numeric string: schema validation coerces it, so the returned value must
    # be the validated float, not the raw parsed string (kills mutant M8).
    "confidence-numeric-string": {"findings": [], "summary": "ok", "overall_confidence": "0.9"},
}

# Allow rows whose returned value is the schema-coerced one, not the raw input.
_COERCED_CONFIDENCE: Dict[str, float] = {"confidence-numeric-string": 0.9}


def _rules_only_baseline(monkeypatch) -> Any:
    async def _none(self, **kwargs: Any):
        return None

    with monkeypatch.context() as patch:
        patch.setattr(LocalAIClient, "analyze", _none)
        patch.setattr(analyzer_module, "_retrieve_legal_context", _fake_lookup([], False))
        return asyncio.run(analyze_text(_DOC, _JURISDICTIONS))


def _fake_lookup(chunks: List[Dict[str, Any]], grounded: bool):
    async def _lookup(query, client, jurisdictions):
        return chunks, grounded

    return _lookup


class _NovelError(Exception):
    """An exception type no handler list could have anticipated."""


def _raise(exc: BaseException) -> Callable[[httpx.Request], httpx.Response]:
    def _respond(request: httpx.Request) -> httpx.Response:
        raise exc

    return _respond


# ---------------------------------------------------------------------------
# HR5 end to end: analyze_text returns rule-only findings, reduced confidence
# ---------------------------------------------------------------------------

_FALLBACK_CASES = [
    "llm-returns-none",
    "surrogate-in-legal-text",
    "surrogate-in-legal-section",
    "transport-raises-novel",
    "transport-raises-typeerror",
    *[f"answer-{name}" for name in _MALFORMED_ANSWERS],
]


@pytest.mark.parametrize("case", _FALLBACK_CASES)
def test_analyze_text_falls_back_to_rules(monkeypatch, localai_http, case):
    baseline = _rules_only_baseline(monkeypatch)
    lookup = _fake_lookup([_chunk()], True)
    if case == "llm-returns-none":
        async def fake_analyze(self, numbered_text, jurisdictions, rule_findings, legal_context=None):
            return None

        monkeypatch.setattr(LocalAIClient, "analyze", fake_analyze)
    elif case == "surrogate-in-legal-text":
        lookup = _fake_lookup([_chunk(text="t\ud800")], True)
        localai_http(lambda request: _ok_response())
    elif case == "surrogate-in-legal-section":
        lookup = _fake_lookup([_chunk(section="Art\udfff 1")], True)
        localai_http(lambda request: _ok_response())
    elif case.startswith("transport-raises"):
        localai_http(_raise(_NovelError("x") if case.endswith("novel") else TypeError("x")))
    else:
        raw = _MALFORMED_ANSWERS[case.removeprefix("answer-")]
        localai_http(lambda request: _ok_response(raw=raw))
    monkeypatch.setattr(analyzer_module, "_retrieve_legal_context", lookup)

    result = asyncio.run(analyze_text(_DOC, _JURISDICTIONS))
    payload = result.payload
    if not case.startswith("surrogate-in-legal"):
        # The response serialises (no lone surrogate, no NaN reached it).
        # The surrogate-in-legal cases bypass the KB's own validator (the
        # fake lookup hands the chunk straight to the analyzer), so their
        # citations can't serialise; the KB rejects such chunks at load.
        json.loads(payload.model_dump_json())
    # Rule-only findings: the same categories the rules-only path produces.
    categories = {finding.category for finding in payload.findings}
    assert {"Sale/Share", "ADM"} <= categories
    assert categories == {f.category for f in baseline.payload.findings}
    assert payload.summary is None
    # Reduced confidence: the rules-only factor applies, exactly as for the
    # documented fallback (LLM returned None).
    assert payload.confidence == pytest.approx(baseline.payload.confidence)
    assert payload.confidence < 1.0


def test_localai_unreachable_returns_none(monkeypatch, caplog):
    class UnreachableClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", UnreachableClient)

    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        result = asyncio.run(LocalAIClient().analyze("text", ["US-CA"], []))

    assert result is None
    # The kept httpx.HTTPError handler logged it, not the generic boundary.
    assert any(r.getMessage().startswith("LocalAI HTTP error") for r in caplog.records)
    assert _fallback_records(caplog) == []


# ---------------------------------------------------------------------------
# Response parsing and validation are inside the boundary (security M1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(_MALFORMED_ANSWERS))
def test_analyze_unusable_response_returns_none(localai_http, caplog, name):
    raw = _MALFORMED_ANSWERS[name]
    localai_http(lambda request: _ok_response(raw=raw))
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        assert _analyze() is None
    records = _fallback_records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert message.startswith("LocalAI response parse failed")
    # The log line is encodable and quotes no part of the answer.
    message.encode("utf-8")
    assert "high" not in message and "abc" not in message


@pytest.mark.parametrize("name", list(_VALID_ANSWERS))
def test_analyze_valid_answer_is_returned(localai_http, name):
    content = _VALID_ANSWERS[name]
    localai_http(lambda request: _ok_response(content))
    result = _analyze()
    assert result is not None
    assert result["findings"] == content["findings"]
    assert result.get("summary") == content["summary"]
    expected = _COERCED_CONFIDENCE.get(name, content["overall_confidence"])
    assert result.get("overall_confidence") == expected


# ---------------------------------------------------------------------------
# Request encoding: hostile strings in each input that reaches the body
# ---------------------------------------------------------------------------


# The last entry is an UNJOINED pair: two code points, not U+1F600.
_SURROGATES = ["\ud800", "\udfff", "\ude00\ud83d", chr(0xD83D) + chr(0xDE00)]


@pytest.mark.parametrize("surrogate", _SURROGATES)
@pytest.mark.parametrize("where", ["legal_text", "legal_section", "numbered_text"])
def test_analyze_surrogate_in_request_returns_none_and_sends_nothing(localai_http, caplog, where, surrogate):
    sent = localai_http(lambda request: _ok_response())
    kwargs: Dict[str, Any] = {"legal_context": [_chunk()]}
    if where == "legal_text":
        kwargs["legal_context"] = [_chunk(text=f"t{surrogate}t")]
    elif where == "legal_section":
        kwargs["legal_context"] = [_chunk(section=f"Art{surrogate} 1")]
    else:
        kwargs["numbered_text"] = f"0001| We sell{surrogate} your data."
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        result = _analyze(**kwargs)
    assert result is None
    assert sent == [], "a request that can't be encoded must never be sent"
    records = _fallback_records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert "UnicodeEncodeError" in message
    # No document or corpus text in the log, and the log line is encodable.
    message.encode("utf-8")
    assert "We sell" not in message and "erasure" not in message


def test_analyze_valid_astral_character_is_sent_and_parsed(localai_http):
    # Control: a real astral character (one code point) is valid UTF-8.
    sent = localai_http(lambda request: _ok_response())
    result = _analyze(legal_context=[_chunk(text="emoji \U0001F600 here")])
    assert result == _GOOD_LLM_CONTENT
    assert len(sent) == 1
    assert "\U0001F600".encode("utf-8") in sent[0].content


def test_analyze_nul_in_context_is_sent(localai_http):
    # Control: NUL is valid UTF-8 and JSON-escapable; it isn't an LLM failure.
    sent = localai_http(lambda request: _ok_response())
    result = _analyze(legal_context=[_chunk(text="a\x00b")], numbered_text="0001| a\x00b")
    assert result == _GOOD_LLM_CONTENT
    assert len(sent) == 1
    assert b"\\u0000" in sent[0].content


# ---------------------------------------------------------------------------
# The boundary is structural: any non-cancellation exception falls back
# ---------------------------------------------------------------------------


_RAISED = [
    UnicodeEncodeError("utf-8", "\ud800", 0, 1, "surrogates not allowed"),
    TypeError("Object of type bytes is not JSON serializable"),
    ValueError("Out of range float values are not JSON compliant"),
    OverflowError("int too large"),
    RecursionError("maximum recursion depth exceeded"),
    RuntimeError("event loop is closed"),
    KeyError("choices"),
    AttributeError("'list' object has no attribute 'get'"),
    _NovelError("never seen before"),
]


@pytest.mark.parametrize("exc", _RAISED, ids=lambda e: type(e).__name__)
def test_analyze_any_exception_from_the_http_step_returns_none(localai_http, caplog, exc):
    localai_http(_raise(exc))
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        assert _analyze(legal_context=[_chunk()]) is None
    records = _fallback_records(caplog)
    assert len(records) == 1
    assert type(exc).__name__ in records[0].getMessage()
    assert records[0].exc_info is None


@pytest.mark.parametrize("exc", _RAISED[:3], ids=lambda e: type(e).__name__)
def test_analyze_any_exception_from_request_serialisation_returns_none(monkeypatch, localai_http, exc):
    # The serialiser itself raising (not the transport) is part of the step.
    # The prompt payload holds only strings, so the serialiser is patched;
    # monkeypatch's default raising=True makes an httpx rename fail loudly.
    sent = localai_http(lambda request: _ok_response())

    def _bad_dumps(*args: Any, **kwargs: Any) -> str:
        raise exc

    monkeypatch.setattr(httpx._content, "json_dumps", _bad_dumps)
    assert _analyze() is None
    assert sent == []


@pytest.mark.parametrize("exc", _RAISED[-3:], ids=lambda e: type(e).__name__)
def test_analyze_any_exception_from_model_selection_returns_none(monkeypatch, localai_http, caplog, exc):
    def _raise_on_select(text: str) -> str:
        raise exc

    monkeypatch.setattr(localai_module, "_select_model", _raise_on_select)
    sent = localai_http(lambda request: _ok_response())
    with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
        assert _analyze() is None
    assert sent == []
    # Grumpy F2-round NIT 4: the fallback log names the stage that failed.
    records = _fallback_records(caplog)
    assert len(records) == 1
    assert records[0].getMessage().startswith("LocalAI model selection failed")


def test_analyze_cancellation_propagates(localai_http):
    # CancelledError is how asyncio stops a task; swallowing it would hang
    # shutdown and timeouts, so it is the one failure that must not fall back.
    localai_http(_raise(asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        _analyze()


# ---------------------------------------------------------------------------
# Issue #195: AnalysisPayload.llm_status says WHY there is no LLM answer
# ---------------------------------------------------------------------------
#
# Every HR5 fallback used to look the same, so "LocalAI is down" could not be
# told apart from "our own code makes every LLM call fall back". The status
# is a closed set (``schemas.LLMStatus``), one value per outcome:
#
#   ok                        an answer arrived and passed schemas.LLMAnswer
#   fallback_llm_unreachable  no HTTP response at all (connect error, any
#                             timeout, dropped connection): LocalAI is down
#   fallback_llm_invalid      a 2xx response whose answer failed parsing or
#                             LLMAnswer validation: the model misbehaved
#   fallback_llm_error        anything else inside the boundary: a non-2xx
#                             reply, model selection, prompt build, request
#                             encoding, an unforeseen exception. This is the
#                             "always falls back" bug class #195 is about.
#   disabled                  the LLM step was not run (quick mode)
#
# The schema default (for rows stored before the field existed) must be a
# value no fresh analysis ever reports, so a legacy row never claims "ok".
#
# Every vector runs the REAL LocalAIClient.analyze() over httpx MockTransport,
# so the tests don't constrain how the client hands the outcome back.

# Hostile text in an exception message: absolute path, line breaks of every
# kind, a bidi override. None of it may reach the payload.
_HOSTILE_EXC_TEXT = "/opt/victim/secret\r\n\u2028\u2029\x85\u202eFORGED llm_status=ok"

# httpx errors raised before any response exists. Generated from httpx's own
# hierarchy so a new TransportError subclass is covered without editing here.
def _transport_error_types() -> List[type]:
    found = [
        obj
        for obj in vars(httpx).values()
        if isinstance(obj, type) and issubclass(obj, httpx.TransportError)
    ]
    return sorted(set(found), key=lambda t: t.__name__)


Setup = Callable[[Any, Any], List[httpx.Request]]


def _respond_with(respond: Callable[[httpx.Request], httpx.Response]) -> Setup:
    def _setup(monkeypatch, localai_http) -> List[httpx.Request]:
        return localai_http(respond)

    return _setup


def _raising(exc: BaseException) -> Setup:
    return _respond_with(_raise(exc))


def _status_reply(code: int) -> Setup:
    return _respond_with(lambda request: httpx.Response(code, text="upstream says no"))


def _patched_stage(attr: str) -> Setup:
    def _setup(monkeypatch, localai_http) -> List[httpx.Request]:
        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError(_HOSTILE_EXC_TEXT)

        monkeypatch.setattr(localai_module, attr, _boom)
        return localai_http(lambda request: _ok_response())

    return _setup


def _surrogate_in_legal_context(monkeypatch, localai_http) -> List[httpx.Request]:
    monkeypatch.setattr(analyzer_module, "_retrieve_legal_context", _fake_lookup([_chunk(text="t\ud800")], True))
    return localai_http(lambda request: _ok_response())


# status -> {case id -> setup}. ``disabled`` vectors run in quick mode.
_STATUS_VECTORS: Dict[str, Dict[str, Setup]] = {
    "ok": {
        **{f"valid-{name}": _respond_with(lambda r, c=content: _ok_response(c)) for name, content in _VALID_ANSWERS.items()},
        # LLMAnswer takes findings as List[Any]; items that fail Finding are
        # skipped one by one. The answer itself was valid, so this is "ok".
        "valid-findings-all-unparseable": _respond_with(
            lambda r: _ok_response({"findings": [{"bogus": 1}, 7, None], "summary": "s", "overall_confidence": 0.5})
        ),
        # The answer can't choose the status: an extra key is not a signal.
        "valid-answer-forges-status": _respond_with(
            lambda r: _ok_response({**_GOOD_LLM_CONTENT, "llm_status": "fallback_llm_unreachable"})
        ),
        # Control: NUL in the legal context is valid UTF-8 and is sent.
        "nul-in-legal-context": lambda mp, http: (
            mp.setattr(analyzer_module, "_retrieve_legal_context", _fake_lookup([_chunk(text="a\x00b")], True)),
            http(lambda request: _ok_response()),
        )[1],
    },
    "fallback_llm_unreachable": {
        f"transport-{t.__name__}": _raising(t(_HOSTILE_EXC_TEXT)) for t in _transport_error_types()
    },
    "fallback_llm_invalid": {
        **{f"answer-{name}": _respond_with(lambda r, raw=raw: _ok_response(raw=raw)) for name, raw in _MALFORMED_ANSWERS.items()},
        "answer-not-json": _respond_with(lambda r: _ok_response(raw="I think the policy is fine.")),
        "answer-2mb-garbage": _respond_with(lambda r: _ok_response(raw="{" + "x" * (2 * 1024 * 1024))),
        "answer-malformed-forges-ok": _respond_with(lambda r: _ok_response(raw='{"findings": null, "llm_status": "ok"}')),
        "body-not-json": _respond_with(lambda r: httpx.Response(200, text="<html>proxy page</html>")),
        "body-no-choices": _respond_with(lambda r: httpx.Response(200, json={})),
        "body-choices-empty": _respond_with(lambda r: httpx.Response(200, json={"choices": []})),
    },
    "fallback_llm_error": {
        **{f"http-{code}": _status_reply(code) for code in (400, 404, 500, 503)},
        "transport-raises-novel": _raising(_NovelError(_HOSTILE_EXC_TEXT)),
        "transport-raises-typeerror": _raising(TypeError(_HOSTILE_EXC_TEXT)),
        "request-encoding-surrogate": _surrogate_in_legal_context,
        "model-selection-raises": _patched_stage("_select_model"),
        "prompt-build-raises": _patched_stage("build_user_prompt"),
    },
    "disabled": {
        "quick-mode": _respond_with(lambda request: _ok_response()),
    },
}

_FALLBACK_STATUSES = ("fallback_llm_unreachable", "fallback_llm_invalid", "fallback_llm_error")
_VECTOR_IDS = [(status, case) for status, cases in _STATUS_VECTORS.items() for case in cases]


def _run_vector(monkeypatch, localai_http, status: str, case: str):
    monkeypatch.setattr(analyzer_module, "_retrieve_legal_context", _fake_lookup([_chunk()], True))
    sent = _STATUS_VECTORS[status][case](monkeypatch, localai_http)
    mode = "quick" if status == "disabled" else "full"
    result = asyncio.run(analyze_text(_DOC, _JURISDICTIONS, mode=mode))
    return result.payload, sent


def test_llm_status_vectors_cover_every_emitted_status():
    # Contract (F10): every value of the schema Literal except the legacy
    # default has at least one vector here, and every vector names a real
    # value. A new status without a test, or a test for a removed status,
    # fails here.
    statuses = set(get_args(schemas.LLMStatus))
    legacy_default = AnalysisPayload.model_fields["llm_status"].default
    assert legacy_default in statuses, "the default must itself be a valid LLMStatus"
    assert legacy_default not in _STATUS_VECTORS, (
        "the legacy default must differ from every status a fresh analysis reports"
    )
    assert set(_STATUS_VECTORS) | {legacy_default} == statuses
    assert all(_STATUS_VECTORS[s] for s in _STATUS_VECTORS)
    # httpx really has transport errors to generate from (no empty family).
    assert len(_STATUS_VECTORS["fallback_llm_unreachable"]) >= 8
    print(f"llm_status vectors: {len(_VECTOR_IDS)}")


@pytest.mark.parametrize("status,case", _VECTOR_IDS, ids=[f"{s}:{c}" for s, c in _VECTOR_IDS])
def test_llm_status_names_the_llm_outcome(monkeypatch, localai_http, status, case):
    payload, sent = _run_vector(monkeypatch, localai_http, status, case)
    assert payload.llm_status == status
    assert payload.model_dump()["llm_status"] == status
    # The status is a fixed token: no exception text reaches the payload.
    assert "victim" not in payload.model_dump_json(exclude={"legal_context"})
    if status == "disabled":
        assert sent == [], "quick mode must not call the LLM"
    elif case.startswith(("transport-", "http-", "valid-", "answer-", "body-")):
        assert len(sent) == 1, "the vector must reach the HTTP layer to mean what it says"


@pytest.mark.parametrize(
    "status,case",
    [(s, c) for s, c in _VECTOR_IDS if s in _FALLBACK_STATUSES],
    ids=[f"{s}:{c}" for s, c in _VECTOR_IDS if s in _FALLBACK_STATUSES],
)
def test_llm_status_fallback_agrees_with_hr5_confidence_reduction(monkeypatch, localai_http, status, case):
    # HR5: a fallback status and the rules-only result always come together:
    # the same findings and the same reduced confidence as the documented
    # rules-only path, no summary, and review_required driven by the
    # configured threshold (read from the analyzer's settings, never restated).
    baseline = _rules_only_baseline(monkeypatch)
    payload, _ = _run_vector(monkeypatch, localai_http, status, case)
    assert payload.llm_status == status
    assert payload.summary is None
    assert payload.confidence == pytest.approx(baseline.payload.confidence)
    assert {f.category for f in payload.findings} == {f.category for f in baseline.payload.findings}
    assert payload.review_required is (payload.confidence < analyzer_module.settings.review_threshold)
    assert payload.status == ("needs_review" if payload.review_required else "completed")


def test_llm_status_fallback_with_threshold_above_confidence_needs_review(monkeypatch, localai_http):
    # Override the threshold through config so the fallback must be reviewed.
    baseline = _rules_only_baseline(monkeypatch)
    threshold = min(1.0, baseline.payload.confidence + 0.01)
    monkeypatch.setattr(analyzer_module, "settings", dataclasses.replace(analyzer_module.settings, review_threshold=threshold))
    payload, _ = _run_vector(monkeypatch, localai_http, "fallback_llm_unreachable", "transport-ConnectError")
    assert payload.llm_status == "fallback_llm_unreachable"
    assert payload.review_required is True
    assert payload.status == "needs_review"


def test_llm_status_ok_is_not_the_rules_only_result(monkeypatch, localai_http):
    # Positive control for the agreement test: an ok answer with a summary is
    # not given the rules-only confidence reduction.
    baseline = _rules_only_baseline(monkeypatch)
    payload, _ = _run_vector(monkeypatch, localai_http, "ok", "valid-full")
    assert payload.llm_status == "ok"
    assert payload.summary == _VALID_ANSWERS["full"]["summary"]
    assert payload.confidence != pytest.approx(baseline.payload.confidence)


def test_llm_status_set_on_every_batch_document(monkeypatch, localai_http):
    monkeypatch.setattr(analyzer_module, "_retrieve_legal_context", _fake_lookup([], False))
    localai_http(_raise(httpx.ConnectError(_HOSTILE_EXC_TEXT)))
    docs = [(_DOC, "a", None, None), (_DOC, "b", None, None)]
    payloads, _ = asyncio.run(analyzer_module.analyze_batch_documents(docs, None, _JURISDICTIONS))
    assert [p.llm_status for p in payloads] == ["fallback_llm_unreachable"] * len(docs)
    quick, _ = asyncio.run(analyzer_module.analyze_batch_documents(docs, None, _JURISDICTIONS, mode="quick"))
    assert [p.llm_status for p in quick] == ["disabled"] * len(docs)
