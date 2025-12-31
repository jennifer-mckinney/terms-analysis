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
    lm_studio_base_url: str = os.getenv(
        "LM_STUDIO_BASE_URL", "http://192.168.1.7:1234/v1"
    )
    lm_studio_model: str = os.getenv(
        "LM_STUDIO_MODEL", "qwen3-vl-4b-instruct-mlx"
    )
    database_url: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{_data_dir() / 'terms_analysis.db'}",
    )
    review_threshold: float = float(os.getenv("REVIEW_THRESHOLD", "0.80"))
    request_timeout_s: float = float(os.getenv("LM_REQUEST_TIMEOUT_S", "60"))
    max_input_chars: int = int(os.getenv("MAX_INPUT_CHARS", "20000"))
    allowed_origins: List[str] = field(
        default_factory=lambda: _split_env_list(
            "ALLOWED_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000",
        )
    )
    watchlist_refresh_seconds: int = int(
        os.getenv("WATCHLIST_REFRESH_SECONDS", "0")
    )


settings = Settings()
