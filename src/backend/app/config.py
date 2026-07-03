from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[3]


def _split_env_list(name: str, default: str) -> List[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _data_dir() -> Path:
    default_dir = REPO_ROOT / "data"
    target = Path(os.getenv("TERMS_ANALYSIS_DATA_DIR", str(default_dir)))
    target.mkdir(parents=True, exist_ok=True)
    return target


@dataclass(frozen=True)
class Settings:
    # ── Inference backend ────────────────────────────────────────────────────
    # LocalAI (Apache 2.0, zero VC — https://localai.io)
    localai_base_url: str = os.getenv("LOCALAI_BASE_URL", "http://localhost:8080/v1")

    # Apertus 8B Instruct (Swiss AI Initiative — EPFL/ETH Zurich/CSCS, 1,000+ languages)
    # Download: https://huggingface.co/swiss-ai/Apertus-8B-Instruct-2509-GGUF
    model_world: str = os.getenv("MODEL_WORLD", "apertus-8b-instruct")

    # EuroLLM 22B Instruct (EU Horizon Europe / EuroHPC, 35 languages, EU legal corpus)
    # Download: https://huggingface.co/utter-project/EuroLLM-22B-Instruct-GGUF
    model_eu: str = os.getenv("MODEL_EU", "eurollm-22b-instruct")

    # Language routing: these ISO 639-1 codes route to EuroLLM; all others → Apertus
    eu_language_codes: List[str] = field(
        default_factory=lambda: _split_env_list(
            "EU_LANGUAGE_CODES",
            "bg,cs,da,de,el,en,es,et,fi,fr,ga,hr,hu,it,lt,lv,mt,nl,pl,pt,ro,sk,sl,sv",
        )
    )
    language_detection_enabled: bool = (
        os.getenv("LANGUAGE_DETECTION_ENABLED", "true").lower() == "true"
    )

    # ── Embedding ensemble ───────────────────────────────────────────────────
    # BM25 + Apertus mean-pool + EuroLLM mean-pool fused via Reciprocal Rank Fusion
    rrf_k: int = int(os.getenv("RRF_K", "60"))

    # ── Legal knowledge base (RAG) ──────────────────────────────────────────
    # Source corpus: data/legal_corpus/<jurisdiction>/<law>.txt (see .claude/skills/legal-kb)
    # Vector index: plain numpy matrix, exact exhaustive cosine search — no
    # FAISS (Meta-origin, excluded by the project's dependency no-go list;
    # unnecessary at this corpus size anyway).
    legal_corpus_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("LEGAL_CORPUS_DIR", str(_data_dir() / "legal_corpus"))
        )
    )
    legal_kb_index_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("LEGAL_KB_INDEX_PATH", str(_data_dir() / "legal_kb.npy"))
        )
    )
    legal_kb_metadata_path: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "LEGAL_KB_METADATA_PATH", str(_data_dir() / "legal_kb_metadata.json")
            )
        )
    )
    legal_kb_top_k: int = int(os.getenv("LEGAL_KB_TOP_K", "5"))

    # ── Core settings ────────────────────────────────────────────────────────
    database_url: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{_data_dir() / 'terms_analysis.db'}",
    )
    review_threshold: float = float(os.getenv("REVIEW_THRESHOLD", "0.80"))
    request_timeout_s: float = float(os.getenv("LM_REQUEST_TIMEOUT_S", "60"))
    # URL fetch timeout is deliberately separate from LLM inference timeout.
    # A remote website that hangs must not consume the full LLM budget; keeping
    # the two independent lets ops tune them per constraint. Audit finding
    # tracked via PRD §5 open question resolved in Phase 2 remediation.
    # INVARIANT: url_fetch_timeout_s <= request_timeout_s. URL fetch is the leading step of any URL-analyze flow;
    # the LLM budget consumes the remainder. Reviewer P9 grumpy-F4.
    url_fetch_timeout_s: float = float(os.getenv("LM_URL_FETCH_TIMEOUT_S", "30"))
    max_input_chars: int = int(os.getenv("MAX_INPUT_CHARS", "50000"))
    # 10 MB default upload limit (H5)
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    allowed_origins: List[str] = field(
        default_factory=lambda: _split_env_list(
            "ALLOWED_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000",
        )
    )
    watchlist_refresh_seconds: int = int(os.getenv("WATCHLIST_REFRESH_SECONDS", "0"))
    # Optional API key for endpoint authentication.  Set API_KEY env var in
    # production.  Empty string disables auth (default: disabled for local dev).
    api_key: str = os.getenv("API_KEY", "")
    # Maximum pages to process per PDF when OCR is involved.
    max_pdf_pages: int = int(os.getenv("MAX_PDF_PAGES", "100"))


settings = Settings()
