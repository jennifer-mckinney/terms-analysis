from __future__ import annotations

"""Spec-conformance acceptance tests for issue #91 (G0-2), P9 round 2.

The legal KB must stop being silently ungrounded: every ``POST /analyze``
response carries a ``legal_grounding`` boolean that distinguishes
"no index / retrieval broken" (False) from "index loaded, nothing relevant"
(True), and the failure paths log loudly instead of returning ``[]`` quietly.

Lead decisions encoded here (from P9 round 1: grumpy #1-#4, security F2;
the owner may override them later):
  * NEW field ``legal_grounding_authoritative: bool``. It is True only when
    the analysis is grounded AND a relevance floor is configured AND at least
    one returned citation's ``status`` is on the allowlist {"in_force"}
    (fail closed: null, unknown, "not_yet_in_force" and "placeholder" are
    never authoritative). ``legal_grounding`` itself means only "retrieval
    ran against a loaded index"; it says nothing about authority.
  * ``settings.legal_kb_min_score`` defaults to None (floor disabled, loud
    startup WARNING). While it is None, NO_MATCH is unreachable and
    ``legal_grounding_authoritative`` is forced False.
  * Citation ``status`` is normalised to lower case; placeholder corpus files
    (``# Status: PLACEHOLDER``) yield exactly ``"placeholder"``.
  * "No match" means every candidate scored below the configurable minimum
    relevance ``settings.legal_kb_min_score``. A zero-norm query embedding is
    an embedding failure (ERROR, ungrounded), not a no-match.
  * A retrieval return that is not a typed ``RetrievalResult`` (e.g. a plain
    list) is treated as ungrounded.

Cases:
  (a)  index files absent -> 200, legal_grounding False, zero legal citations,
       WARNING naming the missing path
  (b)  real index, non-zero query embedding, every candidate below
       legal_kb_min_score -> grounded True, legal_context == []
  (b2) zero-norm query embedding -> grounded False, typed ERROR logged
  (c)  retrieval raises -> typed error logged, legal_grounding False, no 500
  (d)  quick mode -> field present and False
  (e)  index built from a real data/legal_corpus/ file (all PLACEHOLDER)
       -> grounded True, every citation status == "placeholder",
       not authoritative
  (f)  in_force chunk + floor configured (-0.99, drops nothing in practice; -1 is rejected at load) -> authoritative
       True
  (f2) same in_force chunk, NO floor configured -> authoritative False
  (f3) chunk with no Status line (null) + floor set -> authoritative False
  (f4) not_yet_in_force chunk + floor set -> authoritative False
  (g)  KB retrieve() returns a plain [] -> ungrounded
  (h)  LEGAL_KB_MIN_SCORE=-1 (and other out-of-range values) -> ValueError at
       settings load, so a misconfigured floor fails startup
Every case also asserts ``legal_grounding_authoritative`` where it is False.

All index paths point at ``tmp_path``; case (e) copies the real corpus file
into ``tmp_path`` so the repo's data/ dir is never written. The LLM call
(``LocalAIClient.analyze``) is stubbed to capture the ``legal_context`` the
analyzer hands it and to return None (rules-only fallback), so no network is
touched.
"""

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from app.config import settings
from app.services import legal_kb as legal_kb_module
from app.services.legal_kb import LegalKnowledgeBase
from app.services.localai import LocalAIClient


# Long enough to clear any paste-length gate; deliberately contains none of
# the toy-embedding topic words, so the query embeds to the zero vector
# (used by (a), (b2), (c), (d), (g)).
_POLICY_TEXT = (
    "We collect your name, email address and usage information when you use "
    "the service. We share information with service providers who help us "
    "operate the platform. You may contact us at any time with questions "
    "about this policy. We may update this policy from time to time and will "
    "post the revised version on this page."
)

# Mentions only "retention": a non-zero query embedding orthogonal to the
# erasure/consent chunks of _write_corpus (used by (b)).
_RETENTION_POLICY_TEXT = _POLICY_TEXT + (
    " Our data retention schedule keeps records only as long as needed."
)

# Mentions "consent": matches the consent chunks of the real GDPR placeholder
# file and of the non-placeholder fixture (used by (e), (f)).
_CONSENT_POLICY_TEXT = _POLICY_TEXT + (
    " We ask for your consent before sending marketing messages."
)

# Toy embedding space, mirroring tests/test_legal_kb.py: one dimension per
# topic keyword. Text containing none of them embeds to the zero vector.
_TOPICS = ["erasure", "consent", "retention"]

# Real shipped corpus file; every file under data/legal_corpus/ is PLACEHOLDER.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_REAL_GDPR_FILE = _REPO_ROOT / "data" / "legal_corpus" / "eu" / "gdpr.txt"


def _toy_embed(text: str) -> List[float]:
    lowered = text.lower()
    return [1.0 if topic in lowered else 0.0 for topic in _TOPICS]


@pytest.fixture
def kb_paths(tmp_path):
    """Point every legal-KB path at tmp_path and restore the originals after."""
    names = ("legal_corpus_dir", "legal_kb_index_path", "legal_kb_metadata_path")
    originals = {name: getattr(settings, name) for name in names}
    corpus_dir = tmp_path / "legal_corpus"
    index_path = tmp_path / "legal_kb.npy"
    metadata_path = tmp_path / "legal_kb_metadata.json"
    # Settings is a frozen dataclass; existing tests patch it the same way.
    object.__setattr__(settings, "legal_corpus_dir", corpus_dir)
    object.__setattr__(settings, "legal_kb_index_path", index_path)
    object.__setattr__(settings, "legal_kb_metadata_path", metadata_path)
    try:
        yield corpus_dir, index_path, metadata_path
    finally:
        for name, value in originals.items():
            object.__setattr__(settings, name, value)


@pytest.fixture
def min_score():
    """Set ``settings.legal_kb_min_score`` for one test and restore it after.

    Pass ``None`` to explicitly disable the floor (the shipped default).

    The attribute may not exist yet on the frozen Settings dataclass, so it is
    set with object.__setattr__ and removed again if it was absent.
    """
    sentinel = object()
    original = getattr(settings, "legal_kb_min_score", sentinel)

    def _set(value: Optional[float]) -> None:
        object.__setattr__(settings, "legal_kb_min_score", value)

    try:
        yield _set
    finally:
        if original is sentinel:
            if "legal_kb_min_score" in vars(settings):
                object.__delattr__(settings, "legal_kb_min_score")
        else:
            object.__setattr__(settings, "legal_kb_min_score", original)


@pytest.fixture
def fresh_kb(monkeypatch):
    """Replace the module-level singleton so no cached matrix leaks across tests."""
    kb = LegalKnowledgeBase()
    monkeypatch.setattr(legal_kb_module, "_legal_kb", kb)
    return kb


@pytest.fixture
def captured_llm(monkeypatch):
    """Stub the LLM and toy embeddings; record the legal_context the analyzer passes."""
    calls: List[Dict[str, Any]] = []

    async def fake_analyze(self, *args, **kwargs):
        calls.append(kwargs)
        return None  # rules-only fallback

    async def fake_embed(self, text, model=None):
        return _toy_embed(text)

    monkeypatch.setattr(LocalAIClient, "analyze", fake_analyze)
    monkeypatch.setattr(LocalAIClient, "embed", fake_embed)
    return calls


def _write_corpus(corpus_dir, status: Optional[str] = None) -> None:
    """Write a tiny GDPR corpus file with erasure and consent sections.

    ``status`` becomes the ``# Status:`` header; None omits the line entirely.
    """
    directory = corpus_dir / "eu"
    directory.mkdir(parents=True, exist_ok=True)
    status_line = f"# Status: {status}\n" if status is not None else ""
    (directory / "gdpr.txt").write_text(
        "# Jurisdiction: GDPR\n"
        "# Law: gdpr\n"
        "# Source: test-fixture\n"
        f"{status_line}"
        "# Effective Date: 2024-01-01\n\n"
        "## Article 17 — Right to erasure\n"
        "The data subject has the right to erasure of personal data.\n\n"
        "## Article 7 — Conditions for consent\n"
        "Consent must be freely given and specific.\n",
        encoding="utf-8",
    )


def _build_index(corpus_dir, index_path, metadata_path) -> int:
    """Build a real index through the module's own build API (toy embeds)."""
    built = asyncio.run(LegalKnowledgeBase().build(LocalAIClient(), corpus_dir))
    assert built > 0 and index_path.exists() and metadata_path.exists()
    return built


def _post(app_client, mode: str = "full", text: str = _POLICY_TEXT):
    return app_client.post(
        "/analyze",
        json={"text": text, "jurisdictions": ["GDPR"], "mode": mode},
    )


def _passed_legal_context(calls: List[Dict[str, Any]]) -> List[Any]:
    assert calls, "analyzer never reached the LLM call in full mode"
    return calls[-1].get("legal_context") or []


def _assert_not_authoritative(body: Dict[str, Any]) -> None:
    assert "legal_grounding_authoritative" in body, (
        "response is missing the legal_grounding_authoritative field"
    )
    assert body["legal_grounding_authoritative"] is False


def _typed_kb_error_logged(records, min_level: int) -> bool:
    """True if a record at >= min_level identifies a typed LegalKBError."""
    for r in records:
        if r.levelno < min_level:
            continue
        exc_type = r.exc_info[0] if r.exc_info else None
        if exc_type is not None and issubclass(exc_type, legal_kb_module.LegalKBError):
            return True
        if "LegalKB" in r.getMessage() and "Error" in r.getMessage():
            return True
    return False


# ── (a) index files absent ──────────────────────────────────────────────────
def test_legal_grounding_analyze_a_index_absent_ungrounded_and_warns(
    app_client, kb_paths, fresh_kb, captured_llm, caplog
):
    _, index_path, metadata_path = kb_paths
    assert not index_path.exists() and not metadata_path.exists()
    caplog.set_level(logging.WARNING)

    response = _post(app_client)

    assert response.status_code == 200
    body = response.json()
    assert "legal_grounding" in body, "response is missing the legal_grounding field"
    assert body["legal_grounding"] is False
    _assert_not_authoritative(body)
    # Zero legal citations: nothing retrieved was handed to the LLM, and the
    # response does not surface any retrieved legal context.
    assert _passed_legal_context(captured_llm) == []
    assert body.get("legal_context", []) == []
    # A WARNING must name the missing path so operators can tell "no index"
    # from "no relevant law".
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(
        str(index_path) in r.getMessage() or str(metadata_path) in r.getMessage()
        for r in warnings
    ), f"no WARNING naming the missing index path; got {[r.getMessage() for r in warnings]}"


# ── (b) real index, every candidate below the relevance floor ───────────────
def test_legal_grounding_analyze_b_all_candidates_below_min_score_grounded(
    app_client, kb_paths, fresh_kb, captured_llm, min_score
):
    corpus_dir, index_path, metadata_path = kb_paths
    _write_corpus(corpus_dir)
    _build_index(corpus_dir, index_path, metadata_path)
    # The query embeds to a genuine non-zero vector ("retention"), so this is
    # not the zero-norm branch: the index was searched and every chunk
    # (erasure / consent) has cosine 0, below the floor.
    assert any(_toy_embed("GDPR " + _RETENTION_POLICY_TEXT[:500]))
    min_score(0.5)

    response = _post(app_client, text=_RETENTION_POLICY_TEXT)

    assert response.status_code == 200
    body = response.json()
    assert "legal_grounding" in body, "response is missing the legal_grounding field"
    # The index loaded; it simply held nothing relevant to this document.
    assert body["legal_grounding"] is True
    assert body.get("legal_context", None) == [], (
        "candidates below legal_kb_min_score must not be returned as citations"
    )
    assert _passed_legal_context(captured_llm) == []
    _assert_not_authoritative(body)


# ── (b2) zero-norm query embedding is an error, not a no-match ──────────────
def test_legal_grounding_analyze_b2_zero_norm_query_is_error_ungrounded(
    app_client, kb_paths, fresh_kb, captured_llm, caplog
):
    corpus_dir, index_path, metadata_path = kb_paths
    _write_corpus(corpus_dir)
    _build_index(corpus_dir, index_path, metadata_path)
    # _POLICY_TEXT contains no topic word: the query embeds to [0, 0, 0].
    assert not any(_toy_embed("GDPR " + _POLICY_TEXT[:500]))
    caplog.set_level(logging.WARNING)

    response = _post(app_client)

    assert response.status_code == 200
    body = response.json()
    assert "legal_grounding" in body, "response is missing the legal_grounding field"
    assert body["legal_grounding"] is False, (
        "a zero-norm query embedding means the embedder is broken; it must not "
        "be reported as grounded"
    )
    assert body.get("legal_context", []) == []
    assert _passed_legal_context(captured_llm) == []
    _assert_not_authoritative(body)
    assert _typed_kb_error_logged(caplog.records, logging.ERROR), (
        "no ERROR identifying a typed LegalKBError for the zero-norm query; got "
        f"{[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )


# ── (c) retrieval raises ────────────────────────────────────────────────────
def test_legal_grounding_analyze_c_retrieval_error_typed_and_ungrounded(
    app_client, kb_paths, fresh_kb, captured_llm, monkeypatch, caplog
):
    class _Boom(RuntimeError):
        pass

    async def exploding_retrieve(self, *args, **kwargs):
        raise _Boom("simulated retrieval failure")

    # Patched at the internal retrieval boundary so the public retrieve()
    # wrapper (and whatever typed-error handling it grows) is exercised.
    monkeypatch.setattr(LegalKnowledgeBase, "_retrieve", exploding_retrieve)
    caplog.set_level(logging.WARNING)

    response = _post(app_client)

    assert response.status_code == 200, "retrieval failure must not surface as a 500"
    body = response.json()
    assert "legal_grounding" in body, "response is missing the legal_grounding field"
    assert body["legal_grounding"] is False
    _assert_not_authoritative(body)
    # "Typed error logged": the log record must identify the error type,
    # either via exc_info or by naming the exception class in the message.
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(
        (r.exc_info and r.exc_info[0] is not None and issubclass(r.exc_info[0], _Boom))
        or "_Boom" in r.getMessage()
        for r in warnings
    ), f"no typed error logged; got {[r.getMessage() for r in warnings]}"


# ── (d) quick mode ──────────────────────────────────────────────────────────
def test_legal_grounding_analyze_d_quick_mode_field_false(app_client, kb_paths, fresh_kb, captured_llm):
    response = _post(app_client, mode="quick")

    assert response.status_code == 200
    body = response.json()
    assert "legal_grounding" in body, "response is missing the legal_grounding field"
    assert body["legal_grounding"] is False
    _assert_not_authoritative(body)


# ── (e) real placeholder corpus file: grounded but not authoritative ────────
def test_legal_grounding_analyze_e_real_placeholder_corpus_not_authoritative(
    app_client, kb_paths, fresh_kb, captured_llm, min_score
):
    corpus_dir, index_path, metadata_path = kb_paths
    assert _REAL_GDPR_FILE.is_file(), f"shipped corpus file missing: {_REAL_GDPR_FILE}"
    assert "# Status: PLACEHOLDER" in _REAL_GDPR_FILE.read_text(encoding="utf-8")
    # Copy (never write into data/) so the index is built from the real file.
    (corpus_dir / "eu").mkdir(parents=True)
    shutil.copy(_REAL_GDPR_FILE, corpus_dir / "eu" / "gdpr.txt")
    _build_index(corpus_dir, index_path, metadata_path)
    # Low floor so the consent passages clear it whatever the default is.
    min_score(0.1)

    response = _post(app_client, text=_CONSENT_POLICY_TEXT)

    assert response.status_code == 200
    body = response.json()
    assert body["legal_grounding"] is True
    citations = body.get("legal_context", [])
    assert citations, "a matching query against a loaded index returned no citations"
    statuses = [c.get("status") for c in citations]
    assert all(s == "placeholder" for s in statuses), (
        f"placeholder corpus citations must carry status 'placeholder'; got {statuses}"
    )
    _assert_not_authoritative(body)


# ── (f) in_force chunk + floor configured -> authoritative ─────────────────
def test_legal_grounding_analyze_f_in_force_chunk_with_floor_is_authoritative(
    app_client, kb_paths, fresh_kb, captured_llm, min_score
):
    corpus_dir, index_path, metadata_path = kb_paths
    _write_corpus(corpus_dir, status="in_force")
    _build_index(corpus_dir, index_path, metadata_path)
    min_score(-0.99)  # floor configured, drops nothing in practice

    response = _post(app_client, text=_CONSENT_POLICY_TEXT)

    assert response.status_code == 200
    body = response.json()
    assert body["legal_grounding"] is True
    citations = body.get("legal_context", [])
    assert citations, "a matching query against a loaded index returned no citations"
    assert any(c.get("status") == "in_force" for c in citations)
    assert "legal_grounding_authoritative" in body, (
        "response is missing the legal_grounding_authoritative field"
    )
    assert body["legal_grounding_authoritative"] is True


def _grounded_with_status(app_client, kb_paths, status, floor, min_score):
    """Build an index whose chunks carry ``status`` and POST; return the body."""
    corpus_dir, index_path, metadata_path = kb_paths
    _write_corpus(corpus_dir, status=status)
    _build_index(corpus_dir, index_path, metadata_path)
    min_score(floor)
    response = _post(app_client, text=_CONSENT_POLICY_TEXT)
    assert response.status_code == 200
    body = response.json()
    assert body["legal_grounding"] is True
    assert body.get("legal_context"), "expected citations from the loaded index"
    return body


# ── (f2) in_force but no floor configured -> never authoritative ────────────
def test_legal_grounding_analyze_f2_in_force_without_floor_not_authoritative(
    app_client, kb_paths, fresh_kb, captured_llm, min_score
):
    body = _grounded_with_status(app_client, kb_paths, "in_force", None, min_score)
    assert any(c.get("status") == "in_force" for c in body["legal_context"])
    _assert_not_authoritative(body)


# ── (f3) null status (no Status line) + floor -> fails closed ───────────────
def test_legal_grounding_analyze_f3_null_status_not_authoritative(
    app_client, kb_paths, fresh_kb, captured_llm, min_score
):
    body = _grounded_with_status(app_client, kb_paths, None, -0.99, min_score)
    assert all(c.get("status") is None for c in body["legal_context"])
    _assert_not_authoritative(body)


# ── (f4) not_yet_in_force + floor -> not authoritative ──────────────────────
def test_legal_grounding_analyze_f4_not_yet_in_force_not_authoritative(
    app_client, kb_paths, fresh_kb, captured_llm, min_score
):
    body = _grounded_with_status(app_client, kb_paths, "not_yet_in_force", -0.99, min_score)
    assert all(c.get("status") == "not_yet_in_force" for c in body["legal_context"])
    _assert_not_authoritative(body)


# ── (g) untyped retrieve() return is ungrounded ─────────────────────────────
def test_legal_grounding_analyze_g_plain_list_retrieve_is_ungrounded(
    app_client, kb_paths, fresh_kb, captured_llm, monkeypatch
):
    async def plain_list_retrieve(self, *args, **kwargs):
        return []  # no RetrievalStatus: cannot tell "ran" from "not wired"

    monkeypatch.setattr(LegalKnowledgeBase, "retrieve", plain_list_retrieve)

    response = _post(app_client)

    assert response.status_code == 200
    body = response.json()
    assert "legal_grounding" in body, "response is missing the legal_grounding field"
    assert body["legal_grounding"] is False, (
        "a retrieve() result without a RetrievalStatus must be treated as ungrounded"
    )
    assert body.get("legal_context", []) == []
    _assert_not_authoritative(body)


# ── (h) LEGAL_KB_MIN_SCORE=-1 is rejected at settings load ──────────────────
@pytest.mark.parametrize("raw", ["-1", "-1.0", "-1.5", "1.01", "nan", "inf", "abc"])
def test_legal_grounding_settings_h_invalid_floor_fails_at_load(monkeypatch, raw):
    from app.config import Settings

    monkeypatch.setenv("LEGAL_KB_MIN_SCORE", raw)
    with pytest.raises(ValueError, match=r"LEGAL_KB_MIN_SCORE must be .*\(-1, 1\]"):
        Settings()


@pytest.mark.parametrize("raw,expected", [("-0.99", -0.99), ("0", 0.0), ("1", 1.0)])
def test_legal_grounding_settings_h_boundary_floor_accepted(monkeypatch, raw, expected):
    from app.config import Settings

    monkeypatch.setenv("LEGAL_KB_MIN_SCORE", raw)
    assert Settings().legal_kb_min_score == expected
