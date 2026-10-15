from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
from pathlib import Path

import httpx
import numpy as np
import pytest

import sys

from app.config import settings
from app.services.legal_kb import (
    LegalKBError,
    LegalKBIndexCorruptError,
    LegalKnowledgeBase,
    RetrievalStatus,
    _main,
    _parse_corpus_file,
)
from app.services.localai import LocalAIClient


# Toy embedding space: 3 dims, one per "topic" keyword. Lets tests assert
# retrieval ranks the topically-relevant chunk first without a real LLM.
_TOPICS = ["erasure", "consent", "retention"]


def _toy_embed(text: str) -> list[float]:
    lowered = text.lower()
    return [1.0 if topic in lowered else 0.0 for topic in _TOPICS] or [1.0, 0.0, 0.0]


@pytest.fixture
def patched_paths(tmp_path, monkeypatch):
    corpus_dir = tmp_path / "legal_corpus"
    index_path = tmp_path / "legal_kb.npy"
    metadata_path = tmp_path / "legal_kb_metadata.json"
    object.__setattr__(settings, "legal_corpus_dir", corpus_dir)
    object.__setattr__(settings, "legal_kb_index_path", index_path)
    object.__setattr__(settings, "legal_kb_metadata_path", metadata_path)
    yield corpus_dir, index_path, metadata_path


@pytest.fixture
def toy_client(monkeypatch):
    async def fake_embed(self, text, model=None):
        return _toy_embed(text)

    monkeypatch.setattr(LocalAIClient, "embed", fake_embed)
    return LocalAIClient()


def _write_corpus_file(corpus_dir, jurisdiction: str, law: str, body: str) -> None:
    directory = corpus_dir / jurisdiction
    directory.mkdir(parents=True, exist_ok=True)
    header = (
        f"# Jurisdiction: {jurisdiction.upper()}\n"
        f"# Law: {law}\n"
        "# Source: test-fixture\n"
        "# Effective Date: 2024-01-01\n\n"
    )
    (directory / f"{law}.txt").write_text(header + body, encoding="utf-8")


def test_parse_corpus_file_splits_sections(tmp_path):
    _write_corpus_file(
        tmp_path,
        "eu",
        "gdpr",
        "## Article 17 — Right to erasure\n"
        "The data subject has the right to erasure of personal data.\n\n"
        "## Article 7 — Conditions for consent\n"
        "Consent must be freely given and specific.\n",
    )
    chunks = _parse_corpus_file(tmp_path / "eu" / "gdpr.txt")
    assert len(chunks) == 2
    assert all(c["jurisdiction"] == "EU" for c in chunks)
    sections = {c["section"] for c in chunks}
    assert "Article 17 — Right to erasure" in sections
    assert "Article 7 — Conditions for consent" in sections


def test_parse_corpus_file_without_sections_is_single_chunk(tmp_path):
    _write_corpus_file(tmp_path, "eu", "gdpr", "Plain body with no section headers.")
    chunks = _parse_corpus_file(tmp_path / "eu" / "gdpr.txt")
    assert len(chunks) == 1
    assert chunks[0]["section"] is None


def test_retrieve_is_no_index_when_no_index_built(patched_paths, toy_client):
    kb = LegalKnowledgeBase()
    result = asyncio.run(kb.retrieve("erasure of personal data", toy_client))
    assert result.chunks == ()
    assert result.status is RetrievalStatus.NO_INDEX


def test_build_and_retrieve_ranks_relevant_chunk_first(patched_paths, toy_client):
    corpus_dir, _, _ = patched_paths
    _write_corpus_file(
        corpus_dir,
        "eu",
        "gdpr",
        "## Article 17 — Right to erasure\n"
        "The data subject has the right to obtain erasure of personal data.\n\n"
        "## Article 7 — Conditions for consent\n"
        "Consent must be freely given, specific, and unambiguous.\n",
    )

    kb = LegalKnowledgeBase()
    count = asyncio.run(kb.build(toy_client))
    assert count == 2
    assert kb.chunk_count == 2

    result = asyncio.run(kb.retrieve("right to erasure", toy_client, top_k=2))
    assert result.status is RetrievalStatus.OK
    assert len(result.chunks) >= 1
    assert "erasure" in result.chunks[0]["text"].lower()


def test_retrieve_filters_by_jurisdiction(patched_paths, toy_client):
    corpus_dir, _, _ = patched_paths
    _write_corpus_file(
        corpus_dir,
        "eu",
        "gdpr",
        "## Article 17 — Right to erasure\nThe data subject has erasure rights.\n",
    )
    _write_corpus_file(
        corpus_dir,
        "us-ca",
        "ccpa",
        "## Section 1798.105 — Right to delete\nConsumers have erasure rights too.\n",
    )

    kb = LegalKnowledgeBase()
    asyncio.run(kb.build(toy_client))

    results = asyncio.run(
        kb.retrieve("erasure rights", toy_client, jurisdictions=["US-CA"], top_k=5)
    ).chunks
    assert results
    assert all(r["jurisdiction"] == "US-CA" for r in results)


def test_build_persists_index_and_metadata_to_disk(patched_paths, toy_client):
    corpus_dir, index_path, metadata_path = patched_paths
    _write_corpus_file(
        corpus_dir,
        "eu",
        "gdpr",
        "## Article 17 — Right to erasure\nData subjects have erasure rights.\n",
    )

    kb = LegalKnowledgeBase()
    asyncio.run(kb.build(toy_client))

    assert index_path.exists()
    assert metadata_path.exists()

    # A fresh instance should be able to load the persisted index/metadata.
    reloaded = LegalKnowledgeBase()
    result = asyncio.run(reloaded.retrieve("erasure rights", toy_client))
    assert reloaded.chunk_count == 1
    assert result.status is RetrievalStatus.OK
    assert result.chunks


@pytest.mark.parametrize(
    "corpus_body",
    [
        pytest.param(None, id="empty-dir"),
        # (c) of #181: a corpus file exists but parses to zero chunks.
        pytest.param("# Jurisdiction: EU\n# Law: gdpr\n", id="metadata-only-file"),
    ],
)
def test_build_raises_for_empty_corpus_dir(patched_paths, toy_client, corpus_body):
    """#181 / F5: a build that indexes nothing is an explicit error state, not
    a 0 return the CLI prints as "Indexed 0". The error is not the "corrupt"
    type: an empty corpus is not a corrupt one (honest typing, F8)."""
    corpus_dir, index_path, metadata_path = patched_paths
    corpus_dir.mkdir(parents=True)
    if corpus_body is not None:
        (corpus_dir / "eu").mkdir()
        (corpus_dir / "eu" / "gdpr.txt").write_text(corpus_body, encoding="utf-8")
    kb = LegalKnowledgeBase()
    with pytest.raises(LegalKBError) as info:
        asyncio.run(kb.build(toy_client))
    assert not isinstance(info.value, LegalKBIndexCorruptError)
    assert kb.chunk_count == 0
    assert not index_path.exists()
    assert not metadata_path.exists()


def test_retrieve_is_error_when_embedding_endpoint_unreachable(
    patched_paths, monkeypatch
):
    corpus_dir, _, _ = patched_paths
    _write_corpus_file(
        corpus_dir, "eu", "gdpr", "## Article 17 — Erasure\nErasure rights text.\n"
    )

    async def working_embed(self, text, model=None):
        return _toy_embed(text)

    monkeypatch.setattr(LocalAIClient, "embed", working_embed)
    kb = LegalKnowledgeBase()
    built = asyncio.run(kb.build(LocalAIClient()))
    assert built == 1

    async def broken_embed(self, text, model=None):
        return None

    monkeypatch.setattr(LocalAIClient, "embed", broken_embed)
    result = asyncio.run(kb.retrieve("anything", LocalAIClient()))
    assert result.chunks == ()
    assert result.status is RetrievalStatus.ERROR


def test_retrieve_filters_by_jurisdiction_using_schema_codes(patched_paths, toy_client):
    # Regression test for issue #14: corpus files must use the canonical
    # Jurisdiction codes (GDPR, PIPEDA), not directory-style names (EU, Canada) —
    # otherwise the jurisdiction filter silently falls back to the full corpus.
    corpus_dir, _, _ = patched_paths
    directory = corpus_dir / "eu"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "gdpr.txt").write_text(
        "# Jurisdiction: GDPR\n# Law: GDPR\n# Source: test\n# Effective Date: 2024-01-01\n\n"
        "## Article 17 — Right to erasure\nData subjects have erasure rights.\n",
        encoding="utf-8",
    )
    canada_dir = corpus_dir / "canada"
    canada_dir.mkdir(parents=True, exist_ok=True)
    (canada_dir / "pipeda.txt").write_text(
        "# Jurisdiction: PIPEDA\n# Law: PIPEDA\n# Source: test\n# Effective Date: 2024-01-01\n\n"
        "## Principle 5 — Retention\nOrganizations must retain data appropriately.\n",
        encoding="utf-8",
    )

    kb = LegalKnowledgeBase()
    asyncio.run(kb.build(toy_client))

    results = asyncio.run(
        kb.retrieve("erasure rights", toy_client, jurisdictions=["GDPR"], top_k=5)
    ).chunks
    assert results
    assert all(r["jurisdiction"] == "GDPR" for r in results)

    results = asyncio.run(
        kb.retrieve("retention", toy_client, jurisdictions=["PIPEDA"], top_k=5)
    ).chunks
    assert results
    assert all(r["jurisdiction"] == "PIPEDA" for r in results)


def test_retrieve_falls_back_to_full_corpus_when_jurisdiction_pool_empty(
    patched_paths, toy_client, caplog
):
    corpus_dir, _, _ = patched_paths
    _write_corpus_file(
        corpus_dir, "eu", "gdpr", "## Article 17 — Erasure\nErasure rights text.\n"
    )
    kb = LegalKnowledgeBase()
    asyncio.run(kb.build(toy_client))

    # No chunk has jurisdiction "US-TX" — pool is empty, should fall back to
    # searching everything rather than silently returning nothing, but must
    # log a warning so this isn't a silent behavior.
    with caplog.at_level("WARNING"):
        results = asyncio.run(
            kb.retrieve("erasure", toy_client, jurisdictions=["US-TX"], top_k=5)
        ).chunks
    assert results
    assert any("US-TX" in r.message for r in caplog.records)


def test_retrieve_embedding_dimension_mismatch_is_error(patched_paths, toy_client):
    # Grumpy F8: list equality ignored .status, so the old ``result == []``
    # would also have passed for a wrong NO_MATCH. Assert the status itself.
    corpus_dir, _, _ = patched_paths
    _write_corpus_file(
        corpus_dir, "eu", "gdpr", "## Article 17 — Erasure\nErasure rights text.\n"
    )
    kb = LegalKnowledgeBase()
    asyncio.run(kb.build(toy_client))

    class WrongDimClient:
        async def embed(self, text, model=None):
            return [1.0, 0.0, 0.0, 0.0, 0.0]  # 5 dims vs. the 3-dim index built above

    result = asyncio.run(kb.retrieve("erasure", WrongDimClient()))
    assert result.chunks == ()
    assert result.status is RetrievalStatus.ERROR
    assert result.grounded is False


def test_load_raises_and_retrieve_reports_error_on_corrupted_index(
    patched_paths, toy_client
):
    # Issue #91: _load() now raises a typed error instead of returning False,
    # and retrieve() reports ERROR (not a silent, status-less []).
    _, index_path, metadata_path = patched_paths
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(b"not a valid numpy file")
    metadata_path.write_text("also not valid json", encoding="utf-8")

    kb = LegalKnowledgeBase()
    with pytest.raises(LegalKBIndexCorruptError):
        kb._load()
    result = asyncio.run(kb.retrieve("anything", toy_client))
    assert result.chunks == ()
    assert result.status is RetrievalStatus.ERROR


def test_parse_corpus_file_propagates_placeholder_status(tmp_path):
    directory = tmp_path / "eu"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "gdpr.txt").write_text(
        "# Jurisdiction: GDPR\n"
        "# Law: GDPR\n"
        "# Status: PLACEHOLDER\n"
        "# Source: test\n\n"
        "## Article 17 — Erasure\nSample text.\n",
        encoding="utf-8",
    )
    chunks = _parse_corpus_file(directory / "gdpr.txt")
    assert len(chunks) == 1
    assert chunks[0]["status"] == "PLACEHOLDER"


# --- #181: the index CLI never reports "did nothing" as success --------------
#
# Exit-code contract (QUALITY-BAR 2, F5): 0 means chunks were indexed and the
# count is printed. A build that indexed nothing exits 1, the CLI's existing
# build-failure status, with a stderr message naming the cause. Each cause has
# its own message family. An honest message matches its own family and no
# other (an empty corpus is never blamed on the embedder, F8). The phrases come
# from the card ("0 chunks after parsing") and from the reasons build() and
# _normalize() already log.
_INDEX_FAILURE_EXIT = 1
_CAUSE_PATTERNS = {
    "no-corpus-files": re.compile(r"no legal corpus files", re.IGNORECASE),
    "zero-chunks": re.compile(r"\b0 chunks after parsing\b", re.IGNORECASE),
    "embedder-unreachable": re.compile(r"embedding endpoint unreachable", re.IGNORECASE),
    "no-usable-embeddings": re.compile(r"zero-norm|non-finite", re.IGNORECASE),
}

_SECTIONED_BODY = (
    "## Article 7 — Consent\nConsent text.\n\n## Article 17 — Erasure\nErasure text.\n"
)


def _str_line_breaks() -> str:
    """Every code point str.splitlines() breaks on, generated, not listed."""
    return "".join(
        chr(cp)
        for cp in range(0x110000)
        if not 0xD800 <= cp <= 0xDFFF and len(f"a{chr(cp)}b".splitlines()) == 2
    )


def _str_whitespace() -> str:
    return "".join(
        chr(cp) for cp in range(0x110000) if not 0xD800 <= cp <= 0xDFFF and chr(cp).isspace()
    )


def _run_index_cli(monkeypatch, capsys) -> tuple[object, str, str]:
    """Run the real `index` entry point; return (exit code, stdout, stderr).

    A normal return is exit 0. Any exception other than SystemExit propagates
    and errors the test: a traceback is not an acceptable failure mode.
    """
    monkeypatch.setattr(sys, "argv", ["legal_kb.py", "index", "--jurisdiction", "all"])
    code: object = 0
    try:
        asyncio.run(_main())
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _set_corpus_dir(path: Path) -> None:
    object.__setattr__(settings, "legal_corpus_dir", path)


def _route_http(monkeypatch, handler) -> None:
    """Send every httpx.AsyncClient through ``handler`` (no network, T6)."""
    original_init = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)


def _raise(exc_type):
    def handler(request):
        raise exc_type("embedder down", request=request)

    return handler


def _corpus_absent(tmp_path, corpus_dir):
    return None


def _corpus_empty_dir(tmp_path, corpus_dir):
    corpus_dir.mkdir(parents=True)


def _corpus_path_is_file(tmp_path, corpus_dir):
    corpus_dir.write_text("not a directory\n", encoding="utf-8")


def _corpus_files_at_wrong_depth(tmp_path, corpus_dir):
    # _iter_corpus_files reads <dir>/<jurisdiction>/<law>.txt only.
    corpus_dir.mkdir(parents=True)
    (corpus_dir / "gdpr.txt").write_text(_SECTIONED_BODY, encoding="utf-8")
    (corpus_dir / "eu").mkdir()
    (corpus_dir / "eu" / "gdpr.md").write_text(_SECTIONED_BODY, encoding="utf-8")
    (corpus_dir / "eu" / "deep").mkdir()
    (corpus_dir / "eu" / "deep" / "gdpr.txt").write_text(_SECTIONED_BODY, encoding="utf-8")


def _corpus_symlink_to_empty_dir(tmp_path, corpus_dir):
    target = tmp_path / "real_empty_corpus"
    target.mkdir()
    corpus_dir.symlink_to(target, target_is_directory=True)


def _corpus_dangling_symlink(tmp_path, corpus_dir):
    corpus_dir.symlink_to(tmp_path / "nowhere", target_is_directory=True)


def _corpus_file_with(body):
    def setup(tmp_path, corpus_dir):
        (corpus_dir / "eu").mkdir(parents=True)
        (corpus_dir / "eu" / "gdpr.txt").write_text(body, encoding="utf-8")

    return setup


_VALID_CORPUS = _corpus_file_with(_SECTIONED_BODY)

# (id, cause family, corpus setup, embed fake or None, HTTP handler or None).
# With an HTTP handler the REAL LocalAIClient.embed runs against a
# MockTransport, so the "unreachable" rows exercise the client's own failure
# mapping rather than a stub that returns None.
_INDEX_FAILURE_CASES = [
    # (a) empty corpus: nothing to read, including indirection via symlinks.
    ("empty-corpus-dir", "no-corpus-files", _corpus_empty_dir, _toy_embed, None),
    ("missing-corpus-dir", "no-corpus-files", _corpus_absent, _toy_embed, None),
    ("corpus-path-is-a-file", "no-corpus-files", _corpus_path_is_file, _toy_embed, None),
    ("files-at-wrong-depth", "no-corpus-files", _corpus_files_at_wrong_depth, _toy_embed, None),
    ("symlink-to-empty-dir", "no-corpus-files", _corpus_symlink_to_empty_dir, _toy_embed, None),
    ("dangling-symlink", "no-corpus-files", _corpus_dangling_symlink, _toy_embed, None),
    # (c) zero chunks after parsing: files exist but hold no indexable text.
    ("empty-file", "zero-chunks", _corpus_file_with(""), _toy_embed, None),
    (
        "metadata-only-file",
        "zero-chunks",
        _corpus_file_with("# Jurisdiction: EU\n# Law: gdpr\n# Source: test\n"),
        _toy_embed,
        None,
    ),
    (
        "empty-sections-file",
        "zero-chunks",
        _corpus_file_with("## Article 1 — A\n\n## Article 2 — B\n \t\n"),
        _toy_embed,
        None,
    ),
    (
        "line-breaks-and-whitespace-only-file",
        "zero-chunks",
        _corpus_file_with(_str_line_breaks() + _str_whitespace()),
        _toy_embed,
        None,
    ),
    # (b) unreachable embedder.
    ("embed-returns-none", "embedder-unreachable", _VALID_CORPUS, lambda text: None, None),
    ("http-connect-error", "embedder-unreachable", _VALID_CORPUS, None, httpx.ConnectError),
    ("http-read-timeout", "embedder-unreachable", _VALID_CORPUS, None, httpx.ReadTimeout),
    ("http-503", "embedder-unreachable", _VALID_CORPUS, None, 503),
    # The endpoint answered, but with nothing usable: not "unreachable" (F8).
    (
        "every-embedding-zero-norm",
        "no-usable-embeddings",
        _VALID_CORPUS,
        lambda text: [0.0, 0.0, 0.0],
        None,
    ),
    (
        "every-embedding-non-finite",
        "no-usable-embeddings",
        _VALID_CORPUS,
        lambda text: [float("nan"), 1.0, 0.0],
        None,
    ),
]


def _arrange_embedder(monkeypatch, embed, http) -> None:
    if http is None:
        monkeypatch.setattr(LocalAIClient, "embed", _embed_returning_fn(embed))
    elif isinstance(http, int):
        _route_http(monkeypatch, lambda request: httpx.Response(http))
    else:
        _route_http(monkeypatch, _raise(http))


def _embed_returning_fn(fn):
    async def embed(self, text, model=None):
        return fn(text)

    return embed


def _assert_failure_output_is_safe(err: str, tmp_path: Path) -> None:
    """F8 / attack list A: no absolute path, no raw control or line-break
    characters beyond the single trailing newline print() adds."""
    for root in {str(tmp_path), os.path.realpath(tmp_path), str(Path.home())}:
        assert root not in err, "stderr leaks an absolute path"
    body = err[:-1] if err.endswith("\n") else err
    bad = sorted(
        {f"U+{ord(ch):04X}" for ch in body if unicodedata.category(ch) in {"Cc", "Cf", "Zl", "Zp"}}
    )
    assert bad == [], f"stderr carries raw control/format/line-break characters {bad}"


def test_index_failure_table_covers_every_cause_family():
    """Contract: every cause family has a positive row (its own) and negative
    rows (other families' messages it must not match); and each card case
    (a) empty corpus, (b) unreachable embedder, (c) zero chunks is present."""
    families = [family for _, family, _, _, _ in _INDEX_FAILURE_CASES]
    assert set(families) == set(_CAUSE_PATTERNS)
    for family in _CAUSE_PATTERNS:
        assert families.count(family) >= 1
        assert len(families) - families.count(family) >= 1
    for card_case in ("no-corpus-files", "embedder-unreachable", "zero-chunks"):
        assert card_case in families


@pytest.mark.parametrize(
    "case_id,family,setup,embed,http",
    _INDEX_FAILURE_CASES,
    ids=[row[0] for row in _INDEX_FAILURE_CASES],
)
def test_cli_index_did_nothing_exits_nonzero_with_cause(
    patched_paths, monkeypatch, capsys, tmp_path, case_id, family, setup, embed, http
):
    """#181: (a) empty corpus, (b) unreachable embedder, (c) zero chunks after
    parsing each exit 1 with a message naming that cause, print no "Indexed"
    success line, and leave any existing index byte-for-byte untouched."""
    corpus_dir, index_path, metadata_path = patched_paths
    index_path.write_bytes(b"previous index")
    metadata_path.write_bytes(b"previous metadata")
    setup(tmp_path, corpus_dir)
    _arrange_embedder(monkeypatch, embed, http)

    code, out, err = _run_index_cli(monkeypatch, capsys)

    assert code == _INDEX_FAILURE_EXIT, f"exit {code!r}; stdout={out!r}"
    assert "Indexed" not in out
    assert _CAUSE_PATTERNS[family].search(err), f"{family} cause missing: {err!r}"
    others = [name for name, rx in _CAUSE_PATTERNS.items() if name != family and rx.search(err)]
    assert others == [], f"message also claims {others}: {err!r}"
    _assert_failure_output_is_safe(err, tmp_path)
    assert index_path.read_bytes() == b"previous index"
    assert metadata_path.read_bytes() == b"previous metadata"


def test_cli_index_three_card_causes_have_distinct_messages(
    patched_paths, monkeypatch, capsys, tmp_path
):
    """Card acceptance: (a), (b) and (c) each produce a DISTINCT stderr."""
    corpus_dir, _, _ = patched_paths
    rows = {row[0]: row for row in _INDEX_FAILURE_CASES}
    messages = {}
    for case_id in ("empty-corpus-dir", "embed-returns-none", "metadata-only-file"):
        _, _, setup, embed, http = rows[case_id]
        case_dir = tmp_path / case_id / corpus_dir.name
        case_dir.parent.mkdir()
        _set_corpus_dir(case_dir)
        setup(case_dir.parent, case_dir)
        _arrange_embedder(monkeypatch, embed, http)
        code, _, err = _run_index_cli(monkeypatch, capsys)
        assert code == _INDEX_FAILURE_EXIT, f"{case_id}: exit {code!r}"
        messages[case_id] = err.strip()
    assert all(messages.values()), messages
    assert len(set(messages.values())) == 3, messages


def test_cli_index_hostile_corpus_dir_name_is_not_echoed_raw(
    patched_paths, monkeypatch, capsys, tmp_path
):
    """Attack list A (structure forgery, output safety): the corpus directory
    comes from config/env. A name holding any line break, C0/C1 control, or
    Cf (bidi, zero-width) character must not reach stderr raw, and must not
    forge an "Indexed" success line. Names are generated per category."""
    monkeypatch.setattr(LocalAIClient, "embed", _embed_returning_fn(_toy_embed))
    hostile = [
        chr(cp)
        for cp in range(0x110000)
        if unicodedata.category(chr(cp)) in {"Cc", "Cf", "Zl", "Zp"}
        and chr(cp) not in {"\x00", "/"}  # not representable in a file name
    ]
    print(f"generated {len(hostile)} hostile corpus dir names")
    assert len(hostile) > 200
    failures = []
    for number, ch in enumerate(hostile):
        corpus_dir = tmp_path / f"n{number}" / f"corpus{ch}Indexed 9 legal KB chunks{ch}"
        corpus_dir.mkdir(parents=True)
        _set_corpus_dir(corpus_dir)
        code, out, err = _run_index_cli(monkeypatch, capsys)
        if code != _INDEX_FAILURE_EXIT or "Indexed" in out:
            failures.append((f"U+{ord(ch):04X}", code))
            continue
        try:
            _assert_failure_output_is_safe(err, tmp_path)
        except AssertionError as exc:
            failures.append((f"U+{ord(ch):04X}", str(exc)))
    assert failures == [], f"{len(failures)}/{len(hostile)} names: {failures[:5]}"


@pytest.mark.parametrize("via_symlink", [False, True], ids=["direct", "via-symlink"])
def test_cli_main_indexes_corpus_and_prints_count(
    patched_paths, monkeypatch, capsys, tmp_path, via_symlink
):
    """Green control (#181): a real non-empty build exits 0 and reports the
    exact count it wrote, also when the configured corpus dir is a symlink."""
    corpus_dir, _, metadata_path = patched_paths
    if via_symlink:
        target = tmp_path / "real_corpus"
        _VALID_CORPUS(tmp_path, target)
        corpus_dir.symlink_to(target, target_is_directory=True)
    else:
        _VALID_CORPUS(tmp_path, corpus_dir)
    monkeypatch.setattr(LocalAIClient, "embed", _embed_returning_fn(_toy_embed))

    code, out, err = _run_index_cli(monkeypatch, capsys)

    assert code in (0, None), f"exit {code!r}; stderr={err!r}"
    written = len(json.loads(metadata_path.read_text(encoding="utf-8")))
    assert written == 2  # two sections in _SECTIONED_BODY
    assert f"Indexed {written} legal KB chunks" in out
    assert [name for name, rx in _CAUSE_PATTERNS.items() if rx.search(err)] == []


def test_cli_main_rejects_invalid_action(monkeypatch):
    """argparse validation still runs even though the parsed args aren't
    bound to a variable (only "index" is a valid CLI action)."""
    monkeypatch.setattr(sys, "argv", ["legal_kb.py", "not-a-real-action"])

    with pytest.raises(SystemExit):
        asyncio.run(_main())


# --- G0-6 (#177): build() and _load() degraded paths -------------------------


def test_build_raises_and_writes_nothing_when_every_embedding_fails(
    patched_paths, monkeypatch
):
    """An unreachable embedding endpoint must raise (an explicit error state,
    #181 / F5) and write no index files, so the caller can tell "not built"
    apart from a successful build."""
    corpus_dir, index_path, metadata_path = patched_paths
    _write_corpus_file(
        corpus_dir, "eu", "gdpr", "## Article 17 — Erasure\nErasure rights text.\n"
    )

    async def unreachable_embed(self, text, model=None):
        return None

    monkeypatch.setattr(LocalAIClient, "embed", unreachable_embed)
    kb = LegalKnowledgeBase()
    with pytest.raises(LegalKBError) as info:
        asyncio.run(kb.build(LocalAIClient()))
    assert not isinstance(info.value, LegalKBIndexCorruptError)
    assert kb.chunk_count == 0
    assert not index_path.exists()
    assert not metadata_path.exists()


@pytest.mark.parametrize(
    "bad_vector",
    [
        pytest.param([0.0, 0.0, 0.0], id="zero"),
        # Round 3 (CI review MEDIUM, ref #91): a non-finite embedding used to
        # normalise to an all-NaN row and be written into the index.
        pytest.param([float("nan"), 0.0, 1.0], id="nan"),
        pytest.param([float("inf"), 1.0, 0.0], id="pos-inf"),
        pytest.param([1.0, float("-inf"), 0.0], id="neg-inf"),
        pytest.param([1e39, 0.0, 0.0], id="float32-overflow"),
    ],
)
def test_build_skips_chunks_whose_embedding_is_a_zero_vector(
    patched_paths, monkeypatch, bad_vector
):
    """A zero or non-finite vector cannot be L2-normalized; that chunk is
    dropped while the others are still indexed and persisted, and no NaN or
    inf row ever reaches the on-disk matrix."""
    corpus_dir, index_path, metadata_path = patched_paths
    _write_corpus_file(
        corpus_dir,
        "eu",
        "gdpr",
        "## Article 7 — Consent\nConsent text.\n\n## Article 99 — Misc\nOther text.\n",
    )

    async def partial_embed(self, text, model=None):
        # "Misc" chunk gets the degenerate embedding; the consent chunk is valid.
        return list(bad_vector) if "Misc" in text else _toy_embed(text)

    monkeypatch.setattr(LocalAIClient, "embed", partial_embed)
    kb = LegalKnowledgeBase()
    assert asyncio.run(kb.build(LocalAIClient())) == 1
    persisted = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert [c["section"] for c in persisted] == ["Article 7 — Consent"]
    matrix = np.load(index_path)
    assert matrix.shape[0] == 1
    assert np.isfinite(matrix).all()


def test_load_rejects_index_whose_row_count_disagrees_with_metadata(
    patched_paths, toy_client
):
    """A 2-row matrix next to 1 metadata entry is a stale/mixed bundle: _load()
    must refuse it and retrieve() must return no context.

    Issue #91: _load() raises a typed error instead of returning False, and
    retrieve() reports ERROR (not a silent, status-less [])."""
    _, index_path, metadata_path = patched_paths
    index_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(index_path, np.eye(2, 3, dtype="float32"))
    metadata_path.write_text(
        json.dumps([{"text": "only one", "section": None, "jurisdiction": "EU"}]),
        encoding="utf-8",
    )

    kb = LegalKnowledgeBase()
    with pytest.raises(LegalKBIndexCorruptError, match="index/metadata mismatch"):
        kb._load()
    assert kb.chunk_count == 0
    result = asyncio.run(kb.retrieve("erasure", toy_client))
    assert result.chunks == ()
    assert result.status is RetrievalStatus.ERROR
