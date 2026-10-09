from __future__ import annotations

"""
Legal knowledge base (RAG) — retrieves relevant statute/regulation passages
to augment LLM prompts with citable legal context.

Architecture:
  Corpus   — data/legal_corpus/<jurisdiction>/<law>.txt (see .claude/skills/legal-kb)
  Chunking — reuses embedding.py::chunk_text, preserving "## Article/Section N —
             Title" boundaries where present so each chunk stays citable.
  Dense    — Apertus embeddings via LocalAIClient.embed(), L2-normalized and
             persisted as a plain numpy matrix. Similarity is exact cosine
             (normalized dot product) computed exhaustively over the
             jurisdiction-filtered pool — no approximate/ANN index (FAISS was
             considered and rejected: it is Meta-origin, which the project's
             own dependency no-go list excludes, and at this corpus size
             exhaustive search costs nothing).
  Sparse   — BM25 (rank_bm25, via embedding.py::bm25_scores) over the same
             pool, for exact citation/defined-term matches.
  Fusion   — Reciprocal Rank Fusion (embedding.py::rrf_fuse), same k as the
             document-chunk ensemble.

Retrieval never raises to the caller: analyze_text() must never be blocked by
legal-KB availability (same fallback philosophy as embedding.py/localai.py,
HR5 "degrade, don't crash"). Unlike the original blanket ``except: return []``,
every result now carries a ``RetrievalStatus`` (issue #91) so callers can tell
"no index" (NO_INDEX), "index searched, nothing relevant" (NO_MATCH) and
"retrieval broke" (ERROR) apart from a grounded hit (OK).
"""

import json
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yaml

from ..config import settings
from ..exceptions import CorpusMismatchError
from ..schemas import AUTHORITATIVE_STATUSES as _SCHEMA_AUTHORITATIVE_STATUSES
from ..schemas import PLACEHOLDER_STATUS as _SCHEMA_PLACEHOLDER_STATUS
from ..schemas import is_valid_utf8 as _is_valid_utf8
from ..schemas import normalise_jurisdiction, normalise_section_title
from .embedding import bm25_scores, chunk_text, rrf_fuse
from .localai import LocalAIClient

logger = logging.getLogger("uvicorn.error")

_SECTION_HEADER = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_META_LINE = re.compile(r"^#\s*([\w ]+):\s*(.+)$")

# Placeholder-status chunks must always carry this warning into the LLM
# prompt — see build_user_prompt() in prompts.py. Defined in schemas (shared
# with prompts.py without an import cycle) and re-exported here.
PLACEHOLDER_STATUS = _SCHEMA_PLACEHOLDER_STATUS

# The ONLY corpus statuses that count as authoritative law (allowlist, fails
# closed). Defined in schemas (round 8, security F3: one allowlist for the
# analyzer flag and the prompt labels) and re-exported here.
AUTHORITATIVE_STATUSES = _SCHEMA_AUTHORITATIVE_STATUSES

# Round 8 (security F10): chunk metadata keys exposed through LegalCitation.
# Each must be a string or null; anything else would fail response
# validation (a 500), so the index is rejected as corrupt at load instead.
_STRING_METADATA_KEYS = ("jurisdiction", "law", "section", "status")


def _section_is_unsafe(section: str) -> bool:
    """True when a (normalised) section holds a control or line-break character.

    Round 10 (security F2): every boundary ``str.splitlines`` honours is a
    control character (Cc) or U+2028 / U+2029 (Zl / Zp). Brackets are no
    longer rejected here: round 11 maps them to parentheses in
    ``schemas.normalise_section_title`` first, so a real title such as
    "Article 6 [Lawfulness]" builds and loads. prompts.py renders headers so
    they can't be forged regardless (its INVARIANT); this is defence in depth.
    """
    return any(unicodedata.category(ch) in ("Cc", "Zl", "Zp") for ch in section)


def _validate_chunks(chunks: Any, source: Path) -> List[Dict[str, Any]]:
    """Return ``chunks`` if every entry is a well-typed chunk, else raise.

    Raises LegalKBIndexCorruptError (retrieve() maps it to ERROR, so the
    analysis degrades to ungrounded instead of returning a 500) when the
    metadata is not a list, an entry is not a dict, ``text`` is not a string,
    or a ``_STRING_METADATA_KEYS`` value is neither a string nor null, any
    string key or value is not valid UTF-8 (round 12, ``_is_valid_utf8``), or
    ``section`` holds a control / line-break character (``_section_is_unsafe``).
    Messages name the chunk and field, never the offending value, so they
    stay encodable and safe to log.

    Round 11: the ONE validation, run by build() on each parsed corpus file
    before anything is embedded or written, and by _load() and
    load_from_bundle(). It also normalises each ``section`` through
    ``schemas.normalise_section_title`` (brackets to parentheses, format
    characters stripped), so build and load agree on every title. The
    returned chunks are copies; the input is not mutated.
    """
    if not isinstance(chunks, list):
        raise LegalKBIndexCorruptError(
            f"Legal KB metadata at {source} is a {type(chunks).__name__}, expected a list"
        )
    validated: List[Dict[str, Any]] = []
    for number, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            raise LegalKBIndexCorruptError(
                f"Legal KB metadata at {source}: chunk {number} is a {type(chunk).__name__}, expected an object"
            )
        if not isinstance(chunk.get("text"), str):
            raise LegalKBIndexCorruptError(
                f"Legal KB metadata at {source}: chunk {number} has no string 'text'"
            )
        for key in _STRING_METADATA_KEYS:
            value = chunk.get(key)
            if value is not None and not isinstance(value, str):
                raise LegalKBIndexCorruptError(
                    f"Legal KB metadata at {source}: chunk {number} field {key!r} is a "
                    f"{type(value).__name__}, expected a string or null"
                )
        # Round 12 (security F2): every string key and value, not a list of
        # known fields, because file-level corpus metadata ("# Source:", ...)
        # is copied into every chunk and any of it can reach a response.
        for key, value in chunk.items():
            if isinstance(key, str) and not _is_valid_utf8(key):
                raise LegalKBIndexCorruptError(
                    f"Legal KB metadata at {source}: chunk {number} has a key that is "
                    "not valid UTF-8 (lone surrogate)"
                )
            if isinstance(value, str) and not _is_valid_utf8(value):
                raise LegalKBIndexCorruptError(
                    f"Legal KB metadata at {source}: chunk {number} field {key!r} is "
                    "not valid UTF-8 (lone surrogate)"
                )
        section = chunk.get("section")
        if section is not None:
            section = normalise_section_title(section)
            if _section_is_unsafe(section):
                raise LegalKBIndexCorruptError(
                    f"Legal KB metadata at {source}: chunk {number} field 'section' holds a "
                    "control / line-break character"
                )
            chunk = {**chunk, "section": section}
        validated.append(chunk)
    return validated


class RetrievalStatus(str, Enum):
    """Outcome of one legal-KB retrieval (issue #91).

    OK        -- index loaded, retrieval ran, at least one chunk returned.
    NO_MATCH  -- index loaded, retrieval ran, every candidate scored below
                 ``settings.legal_kb_min_score``. Unreachable while that floor
                 is unset (None = disabled, the default until calibrated).
    NO_INDEX  -- index/metadata files absent (or empty): retrieval never ran.
    ERROR     -- index present but unusable, or retrieval raised.
    """

    OK = "ok"
    NO_MATCH = "no_match"
    NO_INDEX = "no_index"
    ERROR = "error"

    @property
    def grounded(self) -> bool:
        """True only when an index loaded and retrieval actually ran."""
        return self in (RetrievalStatus.OK, RetrievalStatus.NO_MATCH)


@dataclass(frozen=True)
class RetrievalResult:
    """Retrieved chunks plus the ``RetrievalStatus`` that produced them.

    Issue #91 round-1 (grumpy F5): this used to subclass ``list`` with a
    defaulted ``status=NO_MATCH``. That was fail-open twice over: a bare
    ``RetrievalResult()`` claimed to be grounded, and slicing / ``list()`` /
    ``+`` silently returned plain lists with no status, while
    ``RetrievalResult(status=ERROR) == []`` made ERROR and NO_MATCH compare
    equal. It is now a frozen value object rather than a list, so the status
    can never be dropped by a copy and is never compared away: ``status`` is
    a required field with no default, and callers read ``.chunks`` explicitly.
    The container is immutable (``chunks`` is stored as a tuple); the chunk
    dicts inside it are fresh copies built per retrieve() call, not shared
    with the index.
    """

    chunks: Tuple[Dict[str, Any], ...]
    status: RetrievalStatus

    def __post_init__(self) -> None:
        # Accept any iterable of chunks (e.g. a list) but store a tuple so the
        # frozen dataclass really is immutable.
        object.__setattr__(self, "chunks", tuple(self.chunks))
        if not isinstance(self.status, RetrievalStatus):
            raise TypeError(
                f"RetrievalResult.status must be a RetrievalStatus, got {type(self.status).__name__}"
            )

    @property
    def grounded(self) -> bool:
        return self.status.grounded


def relevance_floor_disabled() -> bool:
    """True when ``settings.legal_kb_min_score`` is unset (floor disabled)."""
    return settings.legal_kb_min_score is None


def warn_if_relevance_floor_disabled() -> bool:
    """Log the owner-mandated startup WARNING when the floor is disabled.

    Issue #91 round-2 owner ruling ("Disabled + loud"): with no floor, RRF
    always returns top-k passages, so "no relevant law" (NO_MATCH) cannot be
    reported and legal_grounding_authoritative is forced False. Returns True
    when the warning was logged. Called once from ``main.lifespan``.
    """
    if not relevance_floor_disabled():
        return False
    logger.warning(
        "Legal KB relevance floor disabled (LEGAL_KB_MIN_SCORE unset, uncalibrated): "
        "NO_MATCH cannot be reported and legal_grounding_authoritative is forced False"
    )
    return True


class LegalKBError(Exception):
    """Base class for typed legal-KB retrieval failures."""


class LegalKBIndexMissingError(LegalKBError):
    """Index or metadata file is absent; carries the missing paths."""

    def __init__(self, missing: List[Path]) -> None:
        self.missing = missing
        super().__init__(
            "Legal KB index not found: " + ", ".join(str(p) for p in missing)
        )


class LegalKBIndexEmptyError(LegalKBError):
    """Index files exist and load but hold zero chunks (grumpy F6).

    Kept distinct from LegalKBIndexMissingError so operators are not told a
    file on disk is missing; retrieve() still maps it to NO_INDEX because a
    zero-row index cannot ground anything.
    """

    def __init__(self, index_path: Path) -> None:
        self.index_path = index_path
        super().__init__(f"Legal KB index at {index_path} has 0 chunks")


class LegalKBIndexCorruptError(LegalKBError):
    """Index files exist but cannot be loaded or disagree with each other."""


class LegalKBRetrievalError(LegalKBError):
    """Index loaded but the retrieval step itself could not complete."""


def _parse_corpus_file(path: Path) -> List[Dict[str, Any]]:
    """Parse one data/legal_corpus/<jurisdiction>/<law>.txt file into chunks.

    Leading "# Key: Value" lines are file-level metadata applied to every
    chunk (including a "# Status: PLACEHOLDER" line, if present, which must
    survive into every chunk so retrieval callers can flag non-authoritative
    text — see prompts.py::build_user_prompt). Each "## Article/Section N —
    Title" block becomes one or more chunks (split via chunk_text if it
    exceeds the chunk window); files without section headers are chunked as
    a single block.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    meta: Dict[str, str] = {}
    body_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            body_start = i + 1
            continue
        m = _META_LINE.match(line)
        if m:
            meta[m.group(1).strip().lower()] = m.group(2).strip()
            body_start = i + 1
        else:
            break
    body = "\n".join(lines[body_start:])

    sections = _SECTION_HEADER.split(body)
    chunks: List[Dict[str, Any]] = []

    if len(sections) <= 1:
        for _, chunk in chunk_text(body):
            cleaned = chunk.strip()
            if cleaned:
                chunks.append({"text": cleaned, "section": None, **meta})
        return chunks

    # re.split on a capturing "^## (.+)$" yields
    # [preamble, title_1, text_1, title_2, text_2, ...]
    for i in range(1, len(sections), 2):
        title = sections[i].strip()
        section_text = sections[i + 1].strip() if i + 1 < len(sections) else ""
        if not section_text:
            continue
        for _, chunk in chunk_text(section_text, chunk_size=1000, overlap=150):
            cleaned = chunk.strip()
            if cleaned:
                chunks.append({"text": f"{title}\n{cleaned}", "section": title, **meta})
    return chunks


# Sentinel for ``LegalKnowledgeBase._loaded_from`` when the matrix came from
# load_from_bundle() rather than the configured settings paths.
_BUNDLE_SOURCE: Tuple[str, str] = ("<bundle>", "<bundle>")


def _iter_corpus_files(corpus_dir: Path) -> List[Path]:
    if not corpus_dir.is_dir():
        return []
    return sorted(corpus_dir.glob("*/*.txt"))


def _normalize(vector: List[float]) -> Optional[np.ndarray]:
    array = np.array(vector, dtype="float32")
    norm = np.linalg.norm(array)
    if norm == 0:
        return None
    return array / norm


class LegalKnowledgeBase:
    """Exact (exhaustive, non-approximate) search over an embedded legal corpus."""

    def __init__(self) -> None:
        self._matrix: Optional[np.ndarray] = None  # shape (n_chunks, dim), L2-normalized
        self._chunks: List[Dict[str, Any]] = []
        # Where the cached matrix came from: settings paths, _BUNDLE_SOURCE, or None.
        self._loaded_from: Optional[Tuple[str, str]] = None

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    async def build(
        self, client: LocalAIClient, corpus_dir: Optional[Path] = None
    ) -> int:
        """Chunk + embed the corpus, persist the vector matrix + metadata to disk.

        Returns the number of chunks indexed (0 if the corpus directory is
        empty or the embedding endpoint is unreachable).

        Raises LegalKBIndexCorruptError, naming the corpus file and chunk,
        when a parsed chunk fails ``_validate_chunks`` (round 11, grumpy
        MEDIUM / security F2): every file is validated before the first
        embedding call, so an invalid corpus writes no index and leaves any
        existing one untouched. The CLI turns this into exit status 1.
        """
        directory = corpus_dir or settings.legal_corpus_dir
        chunks: List[Dict[str, Any]] = []
        for file_path in _iter_corpus_files(directory):
            try:
                parsed = _parse_corpus_file(file_path)
            except UnicodeDecodeError as exc:
                # Round 12 (security F2): undecodable bytes fail the build
                # through the same error the CLI reports, not a traceback.
                raise LegalKBIndexCorruptError(
                    f"Legal KB corpus file {file_path} is not valid UTF-8 "
                    f"(byte offset {exc.start})"
                ) from exc
            chunks.extend(_validate_chunks(parsed, file_path))

        if not chunks:
            logger.warning("No legal corpus files found under %s", directory)
            return 0

        vectors: List[np.ndarray] = []
        kept_chunks: List[Dict[str, Any]] = []
        for chunk in chunks:
            embedding = await client.embed(chunk["text"], model=settings.model_world)
            if embedding is None:
                continue
            normalized = _normalize(embedding)
            if normalized is None:
                continue
            vectors.append(normalized)
            kept_chunks.append(chunk)

        if not vectors:
            logger.warning("Embedding endpoint unreachable — legal KB index not built")
            return 0

        matrix = np.stack(vectors).astype("float32")

        settings.legal_kb_index_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(settings.legal_kb_index_path, matrix)
        settings.legal_kb_metadata_path.write_text(
            json.dumps(kept_chunks, indent=2), encoding="utf-8"
        )

        self._matrix = matrix
        self._chunks = kept_chunks
        self._loaded_from = (
            str(settings.legal_kb_index_path),
            str(settings.legal_kb_metadata_path),
        )
        logger.info("Legal KB built: %d chunks from %s", len(kept_chunks), directory)
        return len(kept_chunks)

    def _load(self) -> None:
        """Load the on-disk index, raising a typed error when it can't be used.

        Returns normally once an index is loaded (grumpy F10: the old ``bool``
        return was always True and ignored). Raises LegalKBIndexMissingError
        if either file is absent and LegalKBIndexCorruptError if the files
        exist but are unreadable or inconsistent. A cached matrix is reused
        only if it came from a bundle or from the currently configured paths,
        so a changed ``settings.legal_kb_index_path`` can't serve stale data.
        """
        index_path = settings.legal_kb_index_path
        metadata_path = settings.legal_kb_metadata_path
        current_source: Tuple[str, str] = (str(index_path), str(metadata_path))
        if self._matrix is not None and self._loaded_from in (
            _BUNDLE_SOURCE,
            current_source,
        ):
            return
        self._matrix = None
        self._chunks = []
        self._loaded_from = None

        missing = [p for p in (index_path, metadata_path) if not p.exists()]
        if missing:
            raise LegalKBIndexMissingError(missing)
        try:
            matrix = np.load(index_path, allow_pickle=False)
            chunks = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # ValueError covers numpy format errors and json.JSONDecodeError.
            raise LegalKBIndexCorruptError(
                f"Failed to load legal KB index {index_path}: {exc}"
            ) from exc
        chunks = _validate_chunks(chunks, metadata_path)
        if matrix.ndim != 2 or matrix.shape[0] != len(chunks):
            raise LegalKBIndexCorruptError(
                f"Legal KB index/metadata mismatch at {index_path} "
                f"(matrix shape {matrix.shape}, "
                f"{len(chunks)} chunks)"
            )
        self._matrix = matrix
        self._chunks = chunks
        self._loaded_from = current_source

    def load_from_bundle(
        self,
        bundle_dir: Path,
        expected_chunker_version: Optional[str] = None,
        expected_embedder_model: Optional[str] = None,
        expected_embedder_revision: Optional[str] = None,
    ) -> None:
        """Load corpus from an ingester-produced bundle directory.

        Reads MANIFEST.yaml, validates version fields against expected values,
        then loads ``index/legal_kb.npy`` + ``index/legal_kb_metadata.json``
        into ``self._matrix`` and ``self._chunks``.

        Raises:
            FileNotFoundError: if MANIFEST.yaml, legal_kb.npy, or
                legal_kb_metadata.json are absent from ``bundle_dir``.
            CorpusMismatchError: if a version field in the MANIFEST does not
                match the corresponding ``expected_*`` argument, or if the
                row count of the loaded matrix does not match the metadata
                chunk count.
            LegalKBIndexCorruptError: if the metadata is not a list of
                well-typed chunks (see ``_validate_chunks``).
        """
        manifest_path = bundle_dir / "MANIFEST.yaml"
        if not manifest_path.exists():
            logger.error("MANIFEST.yaml missing from bundle at %s", bundle_dir)
            raise FileNotFoundError("MANIFEST.yaml not found in bundle directory")

        manifest: Dict[str, Any] = yaml.safe_load(
            manifest_path.read_text(encoding="utf-8")
        )

        # Guard against an empty or non-dict MANIFEST (e.g. empty file yields None)
        if not isinstance(manifest, dict):
            raise CorpusMismatchError(
                dimension="manifest_structure",
                expected="dict",
                actual=type(manifest).__name__,
            )

        # Validate version fields against caller expectations when provided.
        # Use `is not None` rather than truthiness so that callers can pass
        # the empty string "" as an expected value without skipping the check.
        if expected_chunker_version is not None and manifest.get("chunker_version") != expected_chunker_version:
            raise CorpusMismatchError(
                dimension="chunker_version",
                expected=expected_chunker_version,
                actual=str(manifest.get("chunker_version", "<key missing>")),
            )
        if expected_embedder_model is not None and manifest.get("embedder_model") != expected_embedder_model:
            raise CorpusMismatchError(
                dimension="embedder_model",
                expected=expected_embedder_model,
                actual=str(manifest.get("embedder_model", "<key missing>")),
            )
        if expected_embedder_revision is not None and manifest.get("embedder_revision") != expected_embedder_revision:
            raise CorpusMismatchError(
                dimension="embedder_revision",
                expected=expected_embedder_revision,
                actual=str(manifest.get("embedder_revision", "<key missing>")),
            )

        index_path = bundle_dir / "index" / "legal_kb.npy"
        metadata_path = bundle_dir / "index" / "legal_kb_metadata.json"

        if not index_path.exists():
            logger.error("index/legal_kb.npy missing from bundle at %s", bundle_dir)
            raise FileNotFoundError("index/legal_kb.npy not found in bundle directory")
        if not metadata_path.exists():
            logger.error("index/legal_kb_metadata.json missing from bundle at %s", bundle_dir)
            raise FileNotFoundError("index/legal_kb_metadata.json not found in bundle directory")

        # allow_pickle=False enforces safe numeric-only deserialization (no object arrays)
        matrix = np.load(index_path, allow_pickle=False)
        # Round 12 (security F2): undecodable bytes or invalid JSON are a
        # corrupt index, as in _load(), not a raw decode error.
        try:
            raw_chunks = json.loads(metadata_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise LegalKBIndexCorruptError(
                f"Legal KB metadata at {metadata_path} is not valid UTF-8 JSON "
                f"({type(exc).__name__})"
            ) from exc
        # Round 8 (security F10): same chunk validation as _load().
        chunks: List[Dict[str, Any]] = _validate_chunks(raw_chunks, metadata_path)

        # Guard against a mismatch between the persisted matrix row count and
        # the metadata list length — both must agree for retrieval to be safe.
        if matrix.shape[0] != len(chunks):
            raise CorpusMismatchError(
                dimension="chunk_count",
                expected=str(len(chunks)),
                actual=str(matrix.shape[0]),
            )

        # Embeddings must be float32; other dtypes indicate a corrupt or
        # incompatible bundle (e.g. produced by a different pipeline version).
        if matrix.dtype != np.float32:
            raise CorpusMismatchError(
                dimension="matrix_dtype",
                expected="float32",
                actual=str(matrix.dtype),
            )

        self._matrix = matrix
        self._chunks = chunks
        self._loaded_from = _BUNDLE_SOURCE
        logger.info(
            "Legal KB loaded from bundle: %d chunks from %s", len(chunks), bundle_dir
        )

    async def retrieve(
        self,
        query: str,
        client: LocalAIClient,
        jurisdictions: Optional[List[str]] = None,
        top_k: Optional[int] = None,
    ) -> RetrievalResult:
        """Return top-k relevant legal chunks plus a ``RetrievalStatus``.

        Never raises: a missing index yields NO_INDEX (WARNING naming the
        missing paths), an empty index yields NO_INDEX (WARNING naming the
        index and its 0 chunks), an unusable index or a failing retrieval step
        (including a zero-norm query embedding) yields ERROR (logged with the
        exception type and exc_info), and a loaded index whose candidates all
        fall below ``settings.legal_kb_min_score`` yields NO_MATCH. Callers
        must treat legal-KB context as optional, never load-bearing for
        analyze_text() (HR5).
        """
        try:
            chunks = await self._retrieve(query, client, jurisdictions, top_k)
        except LegalKBIndexMissingError as exc:
            logger.warning(
                "Legal KB index missing (%s) — analysis will run without legal grounding",
                ", ".join(str(p) for p in exc.missing),
            )
            return RetrievalResult((), status=RetrievalStatus.NO_INDEX)
        except LegalKBIndexEmptyError as exc:
            logger.warning(
                "Legal KB index at %s has 0 chunks — analysis will run without legal grounding",
                exc.index_path,
            )
            return RetrievalResult((), status=RetrievalStatus.NO_INDEX)
        except Exception as exc:
            logger.error(
                "Legal KB retrieval failed with %s: %s — analysis will run "
                "without legal grounding",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return RetrievalResult((), status=RetrievalStatus.ERROR)

        status = RetrievalStatus.OK if chunks else RetrievalStatus.NO_MATCH
        return RetrievalResult(chunks, status=status)

    async def _retrieve(
        self,
        query: str,
        client: LocalAIClient,
        jurisdictions: Optional[List[str]],
        top_k: Optional[int],
    ) -> List[Dict[str, Any]]:
        # Round 8 (grumpy 6): validate top-k before anything else. A k < 1
        # used to return no chunks (NO_MATCH, "grounded, no relevant law")
        # with the floor disabled, and a negative slice silently dropped the
        # last candidates. retrieve() maps the ValueError to ERROR.
        k = settings.legal_kb_top_k if top_k is None else top_k
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise ValueError(f"legal KB top_k must be an integer >= 1, got {k!r}")
        # Raises LegalKBIndexMissingError / LegalKBIndexCorruptError; retrieve()
        # maps those to NO_INDEX / ERROR.
        self._load()
        # Grumpy F7: snapshot the loaded index into locals before the first
        # await. A concurrent _load()/build() on this singleton could otherwise
        # reset or swap self._matrix / self._chunks during client.embed(),
        # leaving ``pool`` indices pointing into a different corpus (wrong
        # citations) or at None (AttributeError). Everything below reads only
        # these locals.
        matrix = self._matrix
        chunks = self._chunks
        if not chunks:
            # Grumpy F6: a zero-row index is reported as empty, not missing.
            raise LegalKBIndexEmptyError(settings.legal_kb_index_path)

        if jurisdictions:
            # Round 8: the shared normaliser (schemas.normalise_jurisdiction),
            # so the filter and the authoritative check compare the same form
            # and a null jurisdiction can't raise.
            wanted = {normalise_jurisdiction(j) for j in jurisdictions} - {None}
            pool = [
                i
                for i, c in enumerate(chunks)
                if normalise_jurisdiction(c.get("jurisdiction")) in wanted
            ]
            if not pool:
                # Fallback chunks are, by construction, for jurisdictions that
                # were NOT requested: schemas.passage_label_keys labels them
                # out of (or unknown) jurisdiction in the prompt and they never make the
                # analysis authoritative (round 8, security F2).
                logger.warning(
                    "No legal KB chunks match jurisdictions=%s — searching full corpus "
                    "(results are out of jurisdiction, never authoritative)",
                    jurisdictions,
                )
                pool = list(range(len(chunks)))
        else:
            pool = list(range(len(chunks)))

        # The failures below used to return [] (indistinguishable from "no
        # relevant law"); they now raise so retrieve() reports ERROR.
        query_embedding = await client.embed(query, model=settings.model_world)
        if query_embedding is None:
            raise LegalKBRetrievalError("embedding endpoint returned no query vector")
        query_vec = _normalize(query_embedding)
        if query_vec is None:
            # Grumpy F1: the query is never empty (jurisdiction codes + up to
            # 500 chars of document), so a working embedder never returns a
            # zero vector. A zero-norm vector means the embedder is broken or
            # degenerate; reporting it as NO_MATCH would claim "grounded, no
            # relevant law" for a dead embedder. Treat it as a failure.
            raise LegalKBRetrievalError("embedding endpoint returned a zero-norm query vector")

        if query_vec.shape[0] != matrix.shape[1]:
            raise LegalKBRetrievalError(
                f"embedding dimension mismatch (query={query_vec.shape[0]}, "
                f"index={matrix.shape[1]}) — index likely stale for the "
                "current embedding model"
            )

        # Exact (exhaustive) cosine similarity over the full jurisdiction-filtered
        # pool — no top-K truncation before filtering/fusion, so relevant chunks
        # in a minority jurisdiction can't be silently dropped.
        dense_scores = (matrix[pool] @ query_vec).tolist()

        # Grumpy F1(b): relevance floor on dense cosine, applied before fusion.
        # RRF scores are rank-based and always positive, so without a floor a
        # loaded index always returns k chunks and NO_MATCH is unreachable.
        # Candidates strictly below the floor are dropped; if none survive the
        # index was searched and nothing relevant matched (NO_MATCH).
        # Owner ruling 2026-10-07: None = floor disabled (uncalibrated), so
        # every candidate is kept and NO_MATCH cannot be reported; the startup
        # WARNING (main.lifespan) and the authoritative gate (analyzer) say so.
        floor = settings.legal_kb_min_score
        if floor is not None:
            kept = [(idx, score) for idx, score in zip(pool, dense_scores) if score >= floor]
            if not kept:
                logger.info(
                    "Legal KB: all %d candidates scored below legal_kb_min_score=%s — no relevant passages",
                    len(pool),
                    floor,
                )
                return []
            pool = [idx for idx, _ in kept]
            dense_scores = [score for _, score in kept]

        pool_texts = [chunks[idx]["text"] for idx in pool]
        bm25 = bm25_scores(query, pool_texts)
        fused = rrf_fuse([dense_scores, bm25], k=settings.rrf_k)

        ranked = sorted(zip(pool, fused), key=lambda pair: pair[1], reverse=True)[:k]

        return [{**chunks[idx], "score": score} for idx, score in ranked]


_legal_kb = LegalKnowledgeBase()


def get_legal_kb() -> LegalKnowledgeBase:
    return _legal_kb


async def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build the legal knowledge base index")
    parser.add_argument("action", choices=["index"], help="Action to perform")
    parser.add_argument(
        "--jurisdiction",
        default="all",
        help=(
            "Present for CLI compatibility with .claude/skills/legal-kb/SKILL.md; "
            "the index is always rebuilt from the full corpus directory since a "
            "full rebuild is simplest/correct at this corpus size."
        ),
    )
    parser.parse_args()

    kb = get_legal_kb()
    client = LocalAIClient()
    try:
        count = await kb.build(client)
    except LegalKBIndexCorruptError as exc:
        # Round 11: an invalid corpus fails the build loudly (stderr, exit 1)
        # instead of writing an index the server would refuse at load.
        print(f"Legal KB build failed, no index written: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Indexed {count} legal KB chunks from {settings.legal_corpus_dir}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
