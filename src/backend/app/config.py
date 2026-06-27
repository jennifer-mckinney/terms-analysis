from __future__ import annotations

from dataclasses import dataclass, field
import os
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
    # Backward-compatibility aliases for older code/tests.
    lm_studio_base_url: str = os.getenv(
        "LM_STUDIO_BASE_URL",
        os.getenv("LOCALAI_BASE_URL", "http://localhost:8080/v1"),
    )

    # Apertus 8B Instruct (Swiss AI Initiative — EPFL/ETH Zurich/CSCS, 1,000+ languages)
    # Download: https://huggingface.co/swiss-ai/Apertus-8B-Instruct-2509-GGUF
    model_world: str = os.getenv("MODEL_WORLD", "apertus-8b-instruct")
    lm_studio_model: str = os.getenv(
        "LM_STUDIO_MODEL",
        os.getenv("MODEL_WORLD", "apertus-8b-instruct"),
    )

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

    # ── Core settings ────────────────────────────────────────────────────────
    database_url: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{_data_dir() / 'terms_analysis.db'}",
    )
    review_threshold: float = float(os.getenv("REVIEW_THRESHOLD", "0.80"))
    request_timeout_s: float = float(os.getenv("LM_REQUEST_TIMEOUT_S", "60"))
    max_input_chars: int = int(os.getenv("MAX_INPUT_CHARS", "20000"))
    # 10 MB default upload limit (H5)
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    allowed_origins: List[str] = field(
        default_factory=lambda: _split_env_list(
            "ALLOWED_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000",
        )
    )
    watchlist_refresh_seconds: int = int(os.getenv("WATCHLIST_REFRESH_SECONDS", "0"))


settings = Settings()
