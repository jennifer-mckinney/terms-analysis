from __future__ import annotations

import hashlib
import json
import logging
import os
import traceback
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

import httpx

from ..config import settings
from ..schemas import LLMAnswer, LLMStatus
from .prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger("uvicorn.error")

# Hex chars of a SHA-256 kept in log fingerprints. A fixed log-format width
# (enough to group repeats, too short to be a content oracle), not a tunable.
_FINGERPRINT_HEX_CHARS = 12

try:
    from langdetect import detect as _langdetect

    _LANGDETECT_AVAILABLE = True
except ImportError:
    _LANGDETECT_AVAILABLE = False
    logger.warning(
        "langdetect not installed — language routing disabled; all documents → Apertus"
    )


def _traceback_fingerprint(exc: BaseException) -> Tuple[str, str]:
    """Content-free description of where ``exc`` was raised.

    Issue #91 round 3 (grumpy #2 reconciled with security's no-document-text-
    in-logs rule): a bare ``exc_info=True`` would log the exception message,
    which can quote document text or a legal passage. This returns only the
    exception type names and the ``file:function:line`` frames of the whole
    cause/context chain (basenames, so no local directory layout either), plus
    a short stable SHA-256 of that string so repeats of the same bug group
    together in logs. No message, no source line, no locals.
    """
    parts: List[str] = []
    seen: set = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        frames = ">".join(
            f"{os.path.basename(f.filename)}:{f.name}:{f.lineno}"
            for f in traceback.extract_tb(current.__traceback__)
        )
        parts.append(f"{type(current).__name__}@{frames or '-'}")
        current = current.__cause__ or current.__context__
    chain = " <- ".join(parts)
    digest = hashlib.sha256(chain.encode("utf-8")).hexdigest()[
        :_FINGERPRINT_HEX_CHARS
    ]
    return chain, digest


# Name of the response-parsing stage of LocalAIClient.analyze(). A failure in
# this stage is an invalid answer (#195); the name also appears in the log.
_PARSE_STAGE = "response parse"
def _log_http_error(label: str, exc: httpx.HTTPError) -> None:
    """Log an httpx failure without any server-controlled text (issue #194).

    The one renderer for LocalAI HTTP failures, shared by the chat and embed
    paths. A status error logs the status code, the body byte length and a
    short SHA-256 prefix of the body: never the body, and never ``str(exc)``,
    which quotes the server's reason phrase. Any other httpx error logs its
    exception type name only. No ``exc_info``.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        body = exc.response.content
        logger.warning(
            "%s HTTP %s: body_bytes=%d sha256=%s",
            label,
            exc.response.status_code,
            len(body),
            hashlib.sha256(body).hexdigest()[:_FINGERPRINT_HEX_CHARS],
        )
    else:
        logger.warning("%s HTTP error: %s", label, type(exc).__name__)


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
        # Issue #195: why the last analyze() call returned None. Set only on
        # the fallback path, from a fixed token per failure class (never from
        # exception text or the model's answer). None after a validated
        # answer. The analyzer derives "ok" from the returned answer itself
        # and only reads this to name the kind of fallback.
        self.fallback_reason: Optional[LLMStatus] = None

    async def analyze(
        self,
        numbered_text: str,
        jurisdictions: List[str],
        rule_findings: List[dict],
        legal_context: Optional[List[dict]] = None,
    ) -> Optional[Dict[str, Any]]:
        # Issue #91 round 12 (security F2, HR5): ONE boundary around the whole
        # LLM step: model selection, prompt build, request encoding, the HTTP
        # call and response parsing, including validation of the answer
        # against ``schemas.LLMAnswer`` (F2 round, security M1). A lone
        # surrogate in the legal context or the document used to raise
        # UnicodeEncodeError while httpx encoded the body, which no handler
        # listed, so analyze_text failed instead of degrading. Any Exception
        # now returns None (rules-only); a list of types can't be complete.
        # CancelledError and other BaseExceptions still propagate, so
        # cancellation and shutdown keep working.
        # ``stage`` names where the failure happened in the fallback log.
        stage = "model selection"
        self.fallback_reason = None
        try:
            model = _select_model(numbered_text)
            stage = "prompt build"
            user_prompt = build_user_prompt(
                numbered_text=numbered_text,
                jurisdictions=jurisdictions,
                rule_findings=rule_findings,
                legal_context=legal_context,
            )
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 1200,
            }
            endpoint = f"{self._base_url}/chat/completions"
            stage = "request"
            logger.info("LocalAI request: endpoint=%s model=%s", endpoint, model)
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(endpoint, json=payload)
                logger.info(
                    "LocalAI response: status=%s bytes=%s",
                    response.status_code,
                    len(response.content),
                )
                response.raise_for_status()
            stage = _PARSE_STAGE
            content = response.json()["choices"][0]["message"]["content"]
            # One model checks the whole answer (object, field types, finite
            # confidence, valid UTF-8). A mismatch raises here, inside the
            # boundary, so analyze_text only ever sees a validated answer.
            answer = LLMAnswer.model_validate(json.loads(content))
            return answer.model_dump()
        except httpx.HTTPStatusError as exc:
            # A reply arrived but not a 2xx: LocalAI is up, the call is wrong.
            self.fallback_reason = "fallback_llm_error"
            body = exc.response.text
            logger.warning(
                "LocalAI HTTP %s: %s",
                exc.response.status_code,
                body[:300].replace("\n", "\\n"),
            )
            return None
        except httpx.HTTPError as exc:
            # Issue #195: only a TransportError means no response came back
            # (connect error, any timeout, dropped connection). Other httpx
            # errors (decoding, redirects, bad URL) are not an outage.
            self.fallback_reason = (
                "fallback_llm_unreachable"
                if isinstance(exc, httpx.TransportError)
                else "fallback_llm_error"
            )
            logger.warning("LocalAI HTTP error: %s", exc)
        except httpx.HTTPError as exc:
            # Issue #194: the error body is untrusted (it can echo prompt,
            # document or legal-passage text); log status/length/fingerprint
            # or the type name only.
            _log_http_error("LocalAI", exc)
            return None
        except Exception as exc:
            # Issue #195: a failure while parsing or validating a 2xx answer
            # means the model misbehaved; any other stage is our own error.
            self.fallback_reason = (
                "fallback_llm_invalid" if stage == _PARSE_STAGE else "fallback_llm_error"
            )
            # Round 3: log the cause (type + content-free frame chain + hash)
            # so a deterministic bug is diagnosable, never the message, which
            # can quote document or corpus text (or hold a lone surrogate).
            chain, digest = _traceback_fingerprint(exc)
            logger.warning(
                "LocalAI %s failed (%s, fingerprint=%s, frames=%s); "
                "falling back to rules-only",
                stage,
                type(exc).__name__,
                digest,
                chain,
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
        except httpx.HTTPError as exc:
            # Issue #194 / #285: same content-free logging as the chat path.
            _log_http_error(f"LocalAI embed (model={selected})", exc)
            return None
        except Exception as exc:
            # Issue #194 / #285: a parse error's message can quote the
            # response body; log the exception type name only.
            logger.warning(
                "LocalAI embed error (model=%s): %s", selected, type(exc).__name__
            )
            return None
