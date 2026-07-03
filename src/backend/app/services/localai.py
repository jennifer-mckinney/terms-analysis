from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

import httpx

from ..config import settings
from .prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger("uvicorn.error")

try:
    from langdetect import detect as _langdetect, LangDetectException

    _LANGDETECT_AVAILABLE = True
except ImportError:
    _LANGDETECT_AVAILABLE = False
    logger.warning(
        "langdetect not installed — language routing disabled; all documents → Apertus"
    )


def _detect_language(text: str) -> Optional[str]:
    """
    Detect the primary language of text.
    Returns an ISO 639-1 code or None if detection fails.
    Samples the first 2,000 characters for speed.
    """
    if not _LANGDETECT_AVAILABLE:
        return None
    try:
        return _langdetect(text[:2000])
    except Exception:
        return None


def _select_model(text: str) -> str:
    """
    Route to EuroLLM for EU official languages, Apertus for everything else.

    EuroLLM 22B Instruct — EU Horizon/EuroHPC consortium, 35 languages,
    explicitly trained on Europarl, ECHR, and EU regulatory corpora.

    Apertus 8B Instruct — Swiss AI Initiative (EPFL/ETH Zurich/CSCS),
    1,000+ languages, 15T tokens, 100% renewable compute.
    """
    if not settings.language_detection_enabled:
        return settings.model_world

    lang = _detect_language(text)
    if lang and lang in settings.eu_language_codes:
        logger.debug("Language detected: %s → EuroLLM (EU legal specialist)", lang)
        return settings.model_eu

    logger.debug("Language detected: %s → Apertus (world model)", lang)
    return settings.model_world


@runtime_checkable
class LLMClient(Protocol):
    """
    Protocol for LLM backend clients.
    Implementations: LocalAIClient (production).
    """

    async def analyze(
        self,
        numbered_text: str,
        jurisdictions: List[str],
        rule_findings: List[dict],
        legal_context: Optional[List[dict]] = None,
    ) -> Optional[Dict[str, Any]]: ...


class LocalAIClient:
    """
    LocalAI inference client routing to Apertus or EuroLLM.

    Model provenance:
      Apertus 8B  — EPFL + ETH Zurich + CSCS (Swiss national public institutions)
                    Apache 2.0, trained from scratch, 1,000+ languages
      EuroLLM 22B — EU Horizon Europe + EuroHPC Joint Undertaking + ERC
                    Apache 2.0, trained from scratch, 35 languages, EU legal corpus

    No corporate governance. No VC funding. No data leaves the machine.
    """

    def __init__(self) -> None:
        base_url = settings.localai_base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        self._base_url = base_url
        self._timeout = settings.request_timeout_s

    async def analyze(
        self,
        numbered_text: str,
        jurisdictions: List[str],
        rule_findings: List[dict],
        legal_context: Optional[List[dict]] = None,
    ) -> Optional[Dict[str, Any]]:
        model = _select_model(numbered_text)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_user_prompt(
                    numbered_text=numbered_text,
                    jurisdictions=jurisdictions,
                    rule_findings=rule_findings,
                    legal_context=legal_context,
                ),
            },
        ]
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 1200,
        }
        endpoint = f"{self._base_url}/chat/completions"
        logger.info("LocalAI request: endpoint=%s model=%s", endpoint, model)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(endpoint, json=payload)
                logger.info(
                    "LocalAI response: status=%s bytes=%s",
                    response.status_code,
                    len(response.content),
                )
                response.raise_for_status()
                try:
                    response_data = response.json()
                except ValueError as exc:
                    logger.warning("LocalAI response JSON decode failed: %s", exc)
                    return None
                try:
                    content = response_data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as exc:
                    logger.warning("LocalAI response missing content: %s", exc)
                    return None
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            logger.warning(
                "LocalAI HTTP %s: %s",
                exc.response.status_code,
                body[:300].replace("\n", "\\n"),
            )
            return None
        except httpx.HTTPError as exc:
            logger.warning("LocalAI HTTP error: %s", exc)
            return None

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning(
                "LocalAI content not JSON (len=%s): %s",
                len(content) if isinstance(content, str) else 0,
                exc,
            )
            return None

    async def embed(
        self, text: str, model: Optional[str] = None
    ) -> Optional[List[float]]:
        """
        Get a dense embedding vector via LocalAI's /embeddings endpoint.
        Used by the embedding ensemble (embedding.py) for chunk ranking.
        """
        selected = model or settings.model_world
        endpoint = f"{self._base_url}/embeddings"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    endpoint, json={"model": selected, "input": text}
                )
                response.raise_for_status()
                data = response.json()
                return data["data"][0]["embedding"]
        except Exception as exc:
            logger.warning("LocalAI embed error (model=%s): %s", selected, exc)
            return None
