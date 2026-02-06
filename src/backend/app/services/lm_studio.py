from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import httpx

from ..config import settings
from .prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger("uvicorn.error")


class LmStudioClient:
    def __init__(self) -> None:
        base_url = settings.lm_studio_base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        self._base_url = base_url
        self._model = settings.lm_studio_model
        self._timeout = settings.request_timeout_s

    async def analyze(
        self,
        numbered_text: str,
        jurisdictions: list[str],
        rule_findings: list[dict],
    ) -> Optional[Dict[str, Any]]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_user_prompt(
                    numbered_text=numbered_text,
                    jurisdictions=jurisdictions,
                    rule_findings=rule_findings,
                ),
            },
        ]
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 1200,
        }
        endpoint = f"{self._base_url}/chat/completions"
        logger.info("LM Studio request: endpoint=%s model=%s", endpoint, self._model)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(endpoint, json=payload)
                logger.info(
                    "LM Studio response: status=%s bytes=%s",
                    response.status_code,
                    len(response.content),
                )
                response.raise_for_status()
                try:
                    response_data = response.json()
                except ValueError as exc:
                    logger.warning("LM Studio response JSON decode failed: %s", exc)
                    return None
                try:
                    content = response_data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as exc:
                    logger.warning("LM Studio response missing content: %s", exc)
                    return None
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            logger.warning(
                "LM Studio HTTP %s: %s",
                exc.response.status_code,
                body[:300].replace("\n", "\\n"),
            )
            return None
        except httpx.HTTPError as exc:
            logger.warning("LM Studio HTTP error: %s", exc)
            return None

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning(
                "LM Studio content not JSON (len=%s): %s",
                len(content) if isinstance(content, str) else 0,
                exc,
            )
            return None
