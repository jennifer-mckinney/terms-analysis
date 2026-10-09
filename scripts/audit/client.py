"""HTTP and reporting helpers shared by submit.py and collect.py (card #224, ADR 0002).

* ``urllib_transport``: the default ``http(method, url, headers, body)``, stdlib
  urllib only (condition 9), bounded in time and size (F6), no proxies and no
  redirects (a redirect would carry the key to another host, F7).
* ``Api``: one place that adds credentials, encodes JSON, retries a GET (or
  another idempotent call) once on a transient status, and turns every
  transport or protocol problem into ``ApiFailure`` with a message that holds
  no key, header or raw response bytes (F8).
* ``cancel_poll_delete``: the retention path of condition 8, used by the submit
  job after a failure and by the collect job for a batch that never ended.
* ``Reporter``: ``::error`` annotations, plain log lines and the job summary.
"""
from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Callable

Transport = Callable[[str, str, dict[str, str], "bytes | None"], "tuple[int, bytes]"]

BATCH_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9_.:-]")


class ApiFailure(Exception):
    """An API call failed; ``str()`` is safe to print."""


def safe_token(value: Any, limit: int = 64) -> str:
    """An untrusted identifier rendered with an allowlist and a length cap (F2, F8)."""
    return _SAFE_TOKEN.sub("_", str(value))[:limit] or "_"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # urllib then raises HTTPError for the 3xx, which we report


def urllib_transport(timeout: float, max_bytes: int) -> Transport:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def send(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with opener.open(request, timeout=timeout) as response:
                status = int(getattr(response, "status", None) or response.getcode())
                data = response.read(max_bytes + 1)
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) != len(data) <= max_bytes:
                    raise OSError("response body shorter or longer than its Content-Length")
        except urllib.error.HTTPError as exc:
            status = exc.code
            data = exc.read(max_bytes + 1) if exc.fp is not None else b""
        except http.client.HTTPException as exc:  # e.g. IncompleteRead: not an OSError
            raise OSError(f"HTTP protocol error: {type(exc).__name__}") from None
        if len(data) > max_bytes:
            raise OSError("response larger than max_response_bytes")
        return status, data

    return send


def _error_type(body: bytes) -> str:
    try:
        doc = json.loads(body.decode("utf-8"))
        return safe_token(doc["error"]["type"])
    except (ValueError, KeyError, TypeError, AttributeError):
        return "unparsed"


class Api:
    """JSON over one transport, with credentials for exactly one service."""

    def __init__(self, http: Transport, base_url: str, headers: dict[str, str], cfg: dict[str, Any],
                 service: str) -> None:
        self.http = http
        self.base_url = base_url
        self.headers = headers
        self.retry_statuses = frozenset(cfg["retry_statuses"])
        self.backoff = cfg["retry_backoff_seconds"]
        self.service = service

    def call(self, method: str, path: str, payload: Any = None, *, retry: bool = False,
             ok: tuple[int, ...] = (200,)) -> bytes:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = dict(self.headers)
        if body is not None:
            headers["content-type"] = "application/json"
        attempts = 2 if retry else 1
        what = f"{self.service} {method} {path.split('?', 1)[0]}"
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                status, data = self.http(method, self.base_url + path, headers, body)
            except (OSError, ValueError) as exc:  # TimeoutError and URLError are OSErrors
                if last:
                    raise ApiFailure(f"{what} failed: {type(exc).__name__}") from None
                time.sleep(self.backoff)
                continue
            if status in ok:
                return data
            if last or status not in self.retry_statuses:
                raise ApiFailure(f"{what} returned HTTP {int(status)} ({_error_type(data)})")
            time.sleep(self.backoff)
        raise ApiFailure(f"{what} failed")  # unreachable: the loop returns or raises

    def json(self, method: str, path: str, payload: Any = None, **kwargs: Any) -> Any:
        data = self.call(method, path, payload, **kwargs)
        try:
            return json.loads(data.decode("utf-8"))
        except (ValueError, RecursionError):
            raise ApiFailure(f"{self.service} {method} returned a body that is not JSON") from None


def anthropic_api(http: Transport, cfg: dict[str, Any], key: str) -> Api:
    headers = {"x-api-key": key, "anthropic-version": cfg["api_version"], "user-agent": cfg["user_agent"]}
    return Api(http, cfg["api_base_url"], headers, cfg, "anthropic")


def batch_path(batch_id: str, suffix: str = "") -> str:
    if not BATCH_ID_RE.fullmatch(batch_id):
        raise ApiFailure("refusing to use a malformed batch id")
    return f"/v1/messages/batches/{batch_id}{suffix}"


def processing_status(doc: Any) -> str:
    if not isinstance(doc, dict) or not isinstance(doc.get("processing_status"), str):
        raise ApiFailure("anthropic batch object has no processing_status")
    return doc["processing_status"]


def retrieve(api: Api, batch_id: str) -> dict[str, Any]:
    doc = api.json("GET", batch_path(batch_id), retry=True)
    processing_status(doc)
    return doc


def delete_batch(api: Api, batch_id: str) -> None:
    api.call("DELETE", batch_path(batch_id), retry=True)


class CancelTimeout(Exception):
    """A cancelled batch did not reach ``ended`` within cancel_timeout_seconds."""


def cancel_and_wait(api: Api, batch_id: str, cfg: dict[str, Any], log: Callable[[str], None]) -> None:
    """Cancel, then poll until ``ended`` (bounded); raise CancelTimeout when the bound trips."""
    try:
        api.call("POST", batch_path(batch_id, "/cancel"), retry=True)
    except ApiFailure as exc:  # an already-ended batch refuses cancel; the poll decides
        log(f"cancel request not accepted ({exc}); polling the batch status")
    deadline = time.monotonic() + cfg["cancel_timeout_seconds"]
    while True:
        try:
            if processing_status(api.json("GET", batch_path(batch_id), retry=True)) == "ended":
                return
        except ApiFailure as exc:
            log(f"status poll failed ({exc})")
        if time.monotonic() >= deadline:
            raise CancelTimeout(batch_id)
        time.sleep(cfg["poll_interval_seconds"])


class Reporter:
    """Annotations and summary lines; never prints a credential or raw untrusted bytes."""

    def __init__(self, env: dict[str, str], codes: dict[str, int]) -> None:
        self.summary_path = env.get("GITHUB_STEP_SUMMARY", "")
        self.codes = codes

    @staticmethod
    def _escape(text: str) -> str:
        return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")

    def error(self, name: str, message: str) -> int:
        print(f"::error title=wiring-audit::{name}: {self._escape(message)}", flush=True)
        try:
            self.summary(f"**{name}**: {message}")
        except OSError:
            pass  # best effort: the annotation above already carries the failure
        return self.codes[name]

    def log(self, message: str) -> None:
        print(f"wiring-audit: {message}", flush=True)

    def summary(self, line: str) -> None:
        """Append one line to the job summary; raises OSError if the file cannot be written."""
        if not self.summary_path:
            return
        with open(self.summary_path, "a", encoding="utf-8") as handle:
            handle.write(line.replace("\r", " ") + "\n")
