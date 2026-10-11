"""Acceptance tests for #133: API key enforcement and rate limiting.

Binding inputs: the #133 design ruling (owner decisions O1-O3, lead rulings 1-13) and
the security design review (C1, C2, H1-H4, M1-M5). Where the issue text and the ruling
disagree, the ruling wins (keys of 32+ characters, named rate fields instead of
``RATE_LIMIT=5/minute``, per-client identity instead of per-key, unset ``DEPLOY_ENV``
is not local, in-process limiter with no new dependency).

Test contract the implementation must meet (the tests below rely on these names):

Settings (``app/config.py``), validated in ``__post_init__`` so both import and
``dataclasses.replace`` fail closed:

=================================  ===============================  ==========================
field                              environment variable             rule
=================================  ===============================  ==========================
``deploy_env``                     ``DEPLOY_ENV``                   allowlist ``local`` /
                                                                    ``railway``; unset means
                                                                    not local; any other set
                                                                    value raises
``api_key``                        ``API_KEY``                      required unless the local
                                                                    opt-in holds; printable
                                                                    ASCII, no edge whitespace,
                                                                    ``repr=False``
``api_key_min_length``             ``API_KEY_MIN_LENGTH``           int, default >= 32
``bind_host``                      ``BACKEND_HOST``                 local opt-in needs loopback
``rate_limit_pre_auth``            ``RATE_LIMIT_PRE_AUTH``          by peer address, before auth
``rate_limit_per_client``          ``RATE_LIMIT_PER_CLIENT``        after auth, LLM routes, by
                                                                    client identity
``rate_limit_per_key``             ``RATE_LIMIT_PER_KEY``           after auth, LLM routes,
                                                                    ceiling across clients
``rate_limit_health``              ``RATE_LIMIT_HEALTH``            ``/health`` only, own bucket
``rate_limit_max_tracked_clients`` ``RATE_LIMIT_MAX_TRACKED_CLIENTS``  cap on every store
``rate_limit_ipv6_prefix``         ``RATE_LIMIT_IPV6_PREFIX``       1..128, default 64
``trusted_proxy_cidrs``            ``RATE_LIMIT_TRUSTED_PROXY_CIDRS``  tuple of CIDRs, never
                                                                    ``0.0.0.0/0`` or ``::/0``
``client_identity_header``         ``RATE_LIMIT_CLIENT_IP_HEADER``  both or neither with CIDRs
``forwarded_allow_ips``            ``FORWARDED_ALLOW_IPS``          ``*`` anywhere is refused
``max_concurrent_analyses``        ``MAX_CONCURRENT_ANALYSES``      int >= 1
``max_batch_items``                ``MAX_BATCH_ITEMS``              int >= 1 and <= the N of
                                                                    every rate a batch item is
                                                                    charged to (per-client,
                                                                    per-key); PR #296 r2
=================================  ===============================  ==========================

Rates are ``"<N>/<second|minute|hour|day>"`` with N a positive ASCII integer.

Runtime (``app/security.py``):

* one global dependency replaces ``main._verify_api_key``;
* the lifespan builds the limiter from the settings current at that moment and stores
  it at ``app.state.rate_limiter``; it has ``store_sizes() -> dict[str, int]``;
* the limiter reads time through the module attribute ``app.security.monotonic``;
* 401 body ``{"detail": "Invalid or missing API key"}``; 429 body
  ``{"detail": "Rate limit exceeded"}`` with an integer ``Retry-After`` in ``[1, period]``;
  503 when the settings in force are invalid at request time.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import hmac
import importlib
import ipaddress
import json
import logging
import os
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config
from app import main
from app.database import get_db
from app.main import app
from app.schemas import AnalysisPayload
from app.services.analyzer import AnalysisResult

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Fields #133 adds to Settings, with the ruling that requires each one.
REQUIRED_FIELDS: dict[str, str] = {
    "deploy_env": "ruling 2",
    "api_key_min_length": "rulings 2 and 10",
    "bind_host": "ruling 2",
    "rate_limit_pre_auth": "rulings 5 and 10",
    "rate_limit_per_client": "rulings 5, 10 and 11",
    "rate_limit_per_key": "rulings 5 and 10",
    "rate_limit_health": "ruling 8",
    "rate_limit_max_tracked_clients": "ruling 5",
    "rate_limit_ipv6_prefix": "rulings 6 and 10",
    "trusted_proxy_cidrs": "ruling 6",
    "client_identity_header": "ruling 6",
    "forwarded_allow_ips": "ruling 6",
    "max_concurrent_analyses": "rulings 5 and 10",
    "max_batch_items": "rulings 7 and 10",
}

# Environment variables a child process must not inherit from the test run.
_CHILD_SCRUB = (
    "DEPLOY_ENV",
    "API_KEY",
    "API_KEY_MIN_LENGTH",
    "BACKEND_HOST",
    "FORWARDED_ALLOW_IPS",
    "MAX_CONCURRENT_ANALYSES",
    "MAX_BATCH_ITEMS",
)

# Rates that /analyze/batch charges one token per item (security.batch_admission).
# A batch larger than any of these limits can never be admitted (PR #296 r2).
BATCH_CHARGED_RATES = ("rate_limit_per_client", "rate_limit_per_key")

# Spec of the rate format (not configuration): seconds per period unit.
PERIOD_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}

# Addresses from the documentation and shared-address ranges (RFC 5737, RFC 6598,
# RFC 3849). The trusted proxy stands in for the railtail node.
PROXY_CIDR = "100.64.0.0/10"
PROXY_PEER = "100.64.0.5"
IDENTITY_HEADER = "X-Client-IP"
UNTRUSTED_PEER = "198.51.100.9"
CLIENT_PEER = "203.0.113.10"

ANALYZE_BODY = {"text": "We collect personal data and share it with partners.", "jurisdictions": []}
LOOPBACK = ("127.0.0.1", 50000)
CHILD_TIMEOUT_S = 90
UVICORN_EXIT_TIMEOUT_S = 30
PROMPT_S = 3.0


# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------


def _require_fields(names: list[str] | tuple[str, ...]) -> None:
    have = {f.name for f in dataclasses.fields(config.Settings)}
    missing = sorted(set(names) - have)
    if missing:
        detail = ", ".join(f"{m} ({REQUIRED_FIELDS.get(m, 'test contract')})" for m in missing)
        pytest.fail(
            f"Settings has no field(s) {detail}. #133 must add them to app/config.py "
            "and validate them in __post_init__.",
            pytrace=False,
        )


def build_settings(**overrides: Any) -> config.Settings:
    """``dataclasses.replace`` on the live settings, failing clearly on missing fields.

    A batch is charged one token per item to every rate in ``BATCH_CHARGED_RATES``,
    so ``max_batch_items`` may not exceed any of their limits (PR #296 r2). A test
    that lowers one of those rates without naming ``max_batch_items`` gets the cap
    fitted down to the lowest limit; a test that names it gets exactly its value.
    """
    _require_fields(list(overrides))
    if "max_batch_items" not in overrides:
        parsed = [
            config.parse_rate(overrides.get(name, getattr(config.settings, name)))
            for name in BATCH_CHARGED_RATES
        ]
        # A malformed rate is the validator's to refuse; leave the cap alone then.
        if all(p is not None for p in parsed):
            fitted = min([config.settings.max_batch_items] + [p[0] for p in parsed if p])
            if fitted != config.settings.max_batch_items:
                overrides["max_batch_items"] = fitted
    return dataclasses.replace(config.settings, **overrides)


def _min_len() -> int:
    _require_fields(["api_key_min_length"])
    return config.settings.api_key_min_length


def new_key(extra: int = 8) -> str:
    """A generated hex key, comfortably above the configured minimum length."""
    length = _min_len() + extra
    return secrets.token_hex(length)[:length]


def rate(n: int, unit: str = "minute") -> str:
    return f"{n}/{unit}"


def _install(monkeypatch: pytest.MonkeyPatch, security: Any, new: config.Settings) -> None:
    monkeypatch.setattr(config, "settings", new)
    monkeypatch.setattr(main, "settings", new)
    if hasattr(security, "settings"):
        monkeypatch.setattr(security, "settings", new)


@pytest.fixture
def security() -> Any:
    try:
        return importlib.import_module("app.security")
    except ModuleNotFoundError as exc:
        if exc.name == "app.security":
            pytest.fail(
                "app/security.py does not exist yet (ruling 1: the limiter and the one "
                "global auth dependency live there).",
                pytrace=False,
            )
        raise


@pytest.fixture
def configure(monkeypatch: pytest.MonkeyPatch, security: Any) -> Callable[..., config.Settings]:
    """Install validated settings on every module that reads them."""

    def _apply(**overrides: Any) -> config.Settings:
        new = build_settings(**overrides)
        _install(monkeypatch, security, new)
        return new

    return _apply


@pytest.fixture
def railway(configure: Callable[..., config.Settings]) -> Callable[..., config.Settings]:
    """Settings for the exposed deployment: railway, a generated key, plus overrides."""

    def _apply(**overrides: Any) -> config.Settings:
        base: dict[str, Any] = {"deploy_env": "railway", "api_key": new_key()}
        base.update(overrides)
        return configure(**base)

    return _apply


def _trusted_proxy(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "trusted_proxy_cidrs": (PROXY_CIDR,),
        "client_identity_header": IDENTITY_HEADER,
    }
    base.update(overrides)
    return base


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch, security: Any) -> dict[str, float]:
    if not hasattr(security, "monotonic"):
        pytest.fail(
            "Test contract: the limiter must read time through app.security.monotonic "
            "so the window can be driven without sleeping.",
            pytrace=False,
        )
    state = {"now": 10_000.0}
    monkeypatch.setattr(security, "monotonic", lambda: state["now"])
    return state


@pytest.fixture
def db_override(db_session: Any) -> Any:
    def _override() -> Any:
        yield db_session

    app.dependency_overrides[get_db] = _override
    yield db_session
    app.dependency_overrides.pop(get_db, None)


def _fake_payload(source_url: str | None = None) -> AnalysisPayload:
    return AnalysisPayload(
        id=str(uuid4()),
        name="Stub Policy",
        doc_type="Privacy Policy",
        source_url=source_url,
        document_text="Stub policy text.",
        line_offsets=[0],
        status="completed",
        review_required=False,
        confidence=0.9,
        risk_score=2.0,
        grade="A",
        created_at=datetime.now(timezone.utc),
        findings=[],
        summary="Stub summary.",
    )


@pytest.fixture
def stubs(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Replace the LLM and network work behind the analysis routes."""
    analyze_text = AsyncMock(
        side_effect=lambda *a, **k: AnalysisResult(payload=_fake_payload(), issues=[])
    )
    fetch = AsyncMock(return_value="Stub policy text fetched for the batch.")
    batch = AsyncMock(
        side_effect=lambda documents, *a, **k: (
            [_fake_payload(source_url=d[2]) for d in documents],
            [],
        )
    )
    monkeypatch.setattr(main, "analyze_text", analyze_text)
    monkeypatch.setattr(main, "fetch_url_text", fetch)
    monkeypatch.setattr(main, "analyze_batch_documents", batch)
    return SimpleNamespace(analyze_text=analyze_text, fetch=fetch, batch=batch)


def client_at(host: str, port: int = 40000) -> TestClient:
    return TestClient(app, client=(host, port))


def _limiter() -> Any:
    limiter = getattr(app.state, "rate_limiter", None)
    if limiter is None or not callable(getattr(limiter, "store_sizes", None)):
        pytest.fail(
            "Test contract: the lifespan must store the limiter at app.state.rate_limiter "
            "with a store_sizes() -> dict[str, int] method.",
            pytrace=False,
        )
    return limiter


def _assert_429(resp: httpx.Response, period: int) -> None:
    assert resp.status_code == 429, resp.text
    assert resp.json() == {"detail": "Rate limit exceeded"}
    retry = resp.headers.get("retry-after", "")
    assert retry.isascii() and retry.isdigit(), f"Retry-After must be integer seconds, got {retry!r}"
    assert 1 <= int(retry) <= period


async def asgi_call(
    method: str,
    path: str,
    *,
    headers: list[tuple[bytes, bytes]] | tuple = (),
    client: tuple[str, int] | None = (CLIENT_PEER, 40000),
    body: bytes = b"",
    query: bytes = b"",
) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    """Drive the ASGI app with raw header bytes (no client-side validation)."""
    raw_headers = [(b"host", b"testserver")]
    if body:
        raw_headers += [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]
    raw_headers += list(headers)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query,
        "root_path": "",
        "headers": raw_headers,
        "client": client,
        "server": ("testserver", 80),
    }
    sent_body = False
    never = asyncio.Event()
    messages: list[dict] = []

    async def receive() -> dict:
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": body, "more_body": False}
        await never.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    payload = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], list(start.get("headers", [])), payload


def drive(scenario: Callable[[], Awaitable[Any]]) -> Any:
    """Run ``scenario`` inside the app lifespan on a fresh event loop."""

    async def _main() -> Any:
        async with app.router.lifespan_context(app):
            return await scenario()

    return asyncio.run(_main())


ANALYZE_RAW = json.dumps(ANALYZE_BODY).encode()


def _child_env(tmp_path: Path, **env: str) -> dict[str, str]:
    base = {
        k: v
        for k, v in os.environ.items()
        if k not in _CHILD_SCRUB and not k.startswith("RATE_LIMIT_")
    }
    base["TERMS_ANALYSIS_DATA_DIR"] = str(tmp_path)
    base.update(env)
    return base


def _run_child(code: str, tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        env=_child_env(tmp_path, **env),
        capture_output=True,
        text=True,
        timeout=CHILD_TIMEOUT_S,
    )


def _tail(text: str, lines: int = 3) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def _child_key() -> str:
    # The child computes its own minimum, so use a length well above the floor.
    return secrets.token_hex(48)


# ---------------------------------------------------------------------------
# Fail-closed startup: Settings construction (rulings 2, 3, 6, 10; sec C1, M3)
# ---------------------------------------------------------------------------

NOT_ALLOWLISTED_DEPLOY_ENVS = [
    pytest.param("", id="empty"),
    pytest.param("Local", id="title-case"),
    pytest.param("LOCAL", id="upper-case"),
    pytest.param(" local", id="leading-space"),
    pytest.param("local ", id="trailing-space"),
    pytest.param("local\n", id="trailing-newline"),
    pytest.param("local\x00", id="nul"),
    pytest.param("local​", id="zero-width-space"),
    pytest.param("lоcal", id="cyrillic-o-lookalike"),
    pytest.param("dev", id="dev"),
    pytest.param("production", id="production"),
    pytest.param("railway ", id="railway-trailing-space"),
]


@pytest.mark.parametrize("deploy_env", NOT_ALLOWLISTED_DEPLOY_ENVS)
@pytest.mark.parametrize("with_key", [False, True], ids=["no-key", "valid-key"])
def test_startup_refuses_unknown_deploy_env(deploy_env: str, with_key: bool) -> None:
    key = new_key() if with_key else ""
    with pytest.raises(ValueError, match=r"(?i)deploy_env"):
        build_settings(deploy_env=deploy_env, api_key=key, bind_host="127.0.0.1")


@pytest.mark.parametrize("bind_host", ["0.0.0.0", "::", "100.64.1.2", "192.168.1.10", ""])
def test_local_opt_in_refuses_non_loopback_bind_without_key(bind_host: str) -> None:
    with pytest.raises(ValueError, match=r"(?i)api_key|bind|backend_host"):
        build_settings(deploy_env="local", api_key="", bind_host=bind_host)


def test_railway_refuses_empty_key() -> None:
    with pytest.raises(ValueError, match=r"(?i)api_key"):
        build_settings(deploy_env="railway", api_key="", bind_host="127.0.0.1")


def _weak_keys() -> list[Any]:
    # Built lazily inside the test (the length comes from config), labelled here.
    return [
        "one-char",
        "all-spaces",
        "one-short",
        "non-ascii",
        "leading-space",
        "trailing-space",
        "leading-tab",
        "nul",
        "newline",
        "carriage-return",
        "zero-width-space",
        "del",
        "lone-surrogate",
    ]


def _make_weak_key(kind: str) -> str:
    n = _min_len()
    good = secrets.token_hex(n)[:n]
    return {
        "one-char": "x",
        "all-spaces": " " * n,
        "one-short": good[: n - 1],
        "non-ascii": "é" * n,
        "leading-space": " " + good,
        "trailing-space": good + " ",
        "leading-tab": "\t" + good,
        "nul": good + "\x00",
        "newline": good + "\n",
        "carriage-return": good + "\r",
        "zero-width-space": good + "​",
        "del": good + "\x7f",
        "lone-surrogate": good + "\ud800",
    }[kind]


@pytest.mark.parametrize("kind", _weak_keys())
def test_startup_refuses_weak_key(kind: str) -> None:
    weak = _make_weak_key(kind)
    with pytest.raises(ValueError, match=r"(?i)api_key") as excinfo:
        build_settings(deploy_env="railway", api_key=weak)
    message = str(excinfo.value)
    # Output safety: the message names the field, never echoes the secret.
    if len(weak.strip()) >= 8:
        assert weak.strip() not in message
        assert weak.strip()[2:-2] not in message


def test_key_of_exactly_min_length_is_accepted() -> None:
    n = _min_len()
    key = secrets.token_hex(n)[:n]
    s = build_settings(deploy_env="railway", api_key=key)
    assert s.api_key == key


def test_printable_ascii_punctuation_key_is_accepted() -> None:
    n = _min_len()
    key = (secrets.token_hex(n) + "!#$%&()*+,-./:;<=>?@[]^_{|}~")[-n - 4 :]
    assert build_settings(deploy_env="railway", api_key=key).api_key == key


def test_local_opt_in_with_loopback_bind_starts_without_key() -> None:
    for host in ("127.0.0.1", "::1"):
        s = build_settings(deploy_env="local", api_key="", bind_host=host)
        assert s.api_key == ""


def test_default_min_key_length_meets_ruling_floor(tmp_path: Path) -> None:
    # Ruling 2: keys are at least 32 ASCII characters. The default must not undercut it.
    proc = _run_child(
        "from app.config import settings; print(settings.api_key_min_length)",
        tmp_path,
        DEPLOY_ENV="local",
        BACKEND_HOST="127.0.0.1",
    )
    assert proc.returncode == 0, f"child failed: {_tail(proc.stderr)}"
    assert int(proc.stdout.strip().splitlines()[-1]) >= 32


def test_settings_repr_does_not_contain_key() -> None:
    key = secrets.token_hex(40)
    s = dataclasses.replace(config.settings, api_key=key)
    assert key not in repr(s)
    assert key not in str(s)


# Table-driven config validation (F13: a bad value fails closed at load).
GOOD_RATES = ["1/second", "5/minute", "100/hour", "1000/day"]
BAD_RATES = [
    "0/minute",
    "-1/second",
    "+5/minute",
    " 5/minute",
    "5/minute\n",
    "5 / minute",
    "5/fortnight",
    "abc",
    "",
    "5/",
    "/minute",
    "5/minute/x",
    "1e3/minute",
    "1.5/minute",
    "nan/minute",
    "５/minute",  # fullwidth digit five: int() accepts it
    "٥/minute",  # Arabic-Indic digit five
    "1５/minute",  # ASCII lead digit, fullwidth tail: a \d regex accepts it
    "5٥/minute",  # ASCII lead digit, Arabic-Indic tail
    None,
    5,
]
RATE_FIELDS = (
    "rate_limit_pre_auth",
    "rate_limit_per_client",
    "rate_limit_per_key",
    "rate_limit_health",
)
INT_FIELD_TABLE: dict[str, tuple[list[Any], list[Any]]] = {
    "max_concurrent_analyses": ([1, 4], [0, -1, True, "3", 1.5, None]),
    "max_batch_items": ([1, 25], [0, -1, True, "3", 1.5, None]),
    "rate_limit_max_tracked_clients": ([1, 10000], [0, -1, True, "3", 1.5, None]),
    "rate_limit_ipv6_prefix": ([48, 64, 128], [0, -1, 129, True, "64", 64.0, None]),
    "api_key_min_length": ([], [0, -1, True, "32", 1.5, None]),
}
FORWARDED_GOOD = ["", "127.0.0.1", "100.64.0.5"]
FORWARDED_BAD = ["*", "127.0.0.1,*", " * ", "127.0.0.1, *", "*\n"]
CIDRS_BAD = [
    ("0.0.0.0/0",),
    ("::/0",),
    (PROXY_CIDR, "0.0.0.0/0"),
    ("not-a-cidr",),
    ("10.0.0.0/33",),
    ("",),
]
HEADER_NAMES_GOOD = [IDENTITY_HEADER, "X-Reviewer-Ip"]
HEADER_NAMES_BAD = [
    "X-Client-IP\r\nX-Evil: 1",
    "X Client IP",
    "X-Client:IP",
    "X-API-Key",
    "x-api-key",
    "X-Clíent-IP",
    "X-Client-IP\x00",
]


def _rate_rows() -> list[Any]:
    rows = []
    for name in RATE_FIELDS:
        rows += [pytest.param(name, v, True, id=f"{name}-good-{v}") for v in GOOD_RATES]
        rows += [pytest.param(name, v, False, id=f"{name}-bad-{v!r}") for v in BAD_RATES]
    return rows


def _int_rows() -> list[Any]:
    rows = []
    for name, (goods, bads) in INT_FIELD_TABLE.items():
        rows += [pytest.param(name, v, True, id=f"{name}-good-{v!r}") for v in goods]
        rows += [pytest.param(name, v, False, id=f"{name}-bad-{v!r}") for v in bads]
    return rows


def _valid_base() -> dict[str, Any]:
    return {"deploy_env": "railway", "api_key": new_key()}


@pytest.mark.parametrize("field_name,value,ok", _rate_rows())
def test_rate_limit_format_is_validated(field_name: str, value: Any, ok: bool) -> None:
    if ok:
        assert getattr(build_settings(**_valid_base(), **{field_name: value}), field_name) == value
    else:
        with pytest.raises(ValueError, match=rf"(?i){field_name}"):
            build_settings(**_valid_base(), **{field_name: value})


@pytest.mark.parametrize("field_name,value,ok", _int_rows())
def test_int_limits_are_validated(field_name: str, value: Any, ok: bool) -> None:
    if ok:
        assert getattr(build_settings(**_valid_base(), **{field_name: value}), field_name) == value
    else:
        with pytest.raises(ValueError, match=rf"(?i){field_name}"):
            build_settings(**_valid_base(), **{field_name: value})


def test_validation_tables_have_positive_and_negative_rows() -> None:
    # Contract: every validated family has at least one accepted and one refused value.
    assert GOOD_RATES and BAD_RATES
    for name, (goods, bads) in INT_FIELD_TABLE.items():
        assert bads, name
        # api_key_min_length's positive row is the shipped default (see the floor test).
        assert goods or name == "api_key_min_length", name
    assert FORWARDED_GOOD and FORWARDED_BAD
    assert CIDRS_BAD and HEADER_NAMES_GOOD and HEADER_NAMES_BAD
    assert set(RATE_FIELDS) | set(INT_FIELD_TABLE) <= set(REQUIRED_FIELDS)


@pytest.mark.parametrize("value", FORWARDED_BAD)
def test_startup_refuses_forwarded_allow_ips_star(value: str) -> None:
    with pytest.raises(ValueError, match=r"(?i)forwarded_allow_ips"):
        build_settings(**_valid_base(), forwarded_allow_ips=value)


@pytest.mark.parametrize("value", FORWARDED_GOOD)
def test_forwarded_allow_ips_without_star_is_accepted(value: str) -> None:
    assert build_settings(**_valid_base(), forwarded_allow_ips=value).forwarded_allow_ips == value


@pytest.mark.parametrize("cidrs", CIDRS_BAD, ids=repr)
def test_trusted_proxy_cidrs_refuse_catch_all_and_garbage(cidrs: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match=r"(?i)trusted_proxy_cidrs"):
        build_settings(**_valid_base(), **_trusted_proxy(trusted_proxy_cidrs=cidrs))


def test_identity_header_and_proxy_cidrs_are_both_or_neither() -> None:
    with pytest.raises(ValueError, match=r"(?i)client_identity_header|trusted_proxy_cidrs"):
        build_settings(**_valid_base(), trusted_proxy_cidrs=(), client_identity_header=IDENTITY_HEADER)
    with pytest.raises(ValueError, match=r"(?i)client_identity_header|trusted_proxy_cidrs"):
        build_settings(**_valid_base(), trusted_proxy_cidrs=(PROXY_CIDR,), client_identity_header="")
    s = build_settings(**_valid_base(), trusted_proxy_cidrs=(), client_identity_header="")
    assert s.trusted_proxy_cidrs == () and s.client_identity_header == ""


@pytest.mark.parametrize("name", HEADER_NAMES_BAD, ids=repr)
def test_identity_header_name_is_validated(name: str) -> None:
    with pytest.raises(ValueError, match=r"(?i)client_identity_header"):
        build_settings(**_valid_base(), **_trusted_proxy(client_identity_header=name))


@pytest.mark.parametrize("name", HEADER_NAMES_GOOD)
def test_identity_header_name_positive_control(name: str) -> None:
    s = build_settings(**_valid_base(), **_trusted_proxy(client_identity_header=name))
    assert s.client_identity_header == name


# ---------------------------------------------------------------------------
# Fail-closed startup in a fresh process (import time and uvicorn; sec C1, M3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bind", [None, "0.0.0.0"], ids=["bind-unset", "bind-all"])
def test_startup_refuses_empty_key_when_deploy_env_unset(tmp_path: Path, bind: str | None) -> None:
    env = {} if bind is None else {"BACKEND_HOST": bind}
    proc = _run_child("import app.config", tmp_path, **env)
    assert proc.returncode != 0, "import succeeded with DEPLOY_ENV unset and no API_KEY"
    assert "API_KEY" in proc.stderr


def test_startup_refuses_forwarded_allow_ips_star_from_env(tmp_path: Path) -> None:
    key = _child_key()
    proc = _run_child(
        "import app.config", tmp_path, DEPLOY_ENV="railway", API_KEY=key, FORWARDED_ALLOW_IPS="*"
    )
    assert proc.returncode != 0, "import succeeded with FORWARDED_ALLOW_IPS=*"
    assert "FORWARDED_ALLOW_IPS" in proc.stderr.upper()
    assert key not in proc.stderr and key not in proc.stdout


@pytest.mark.parametrize(
    "var,value,name",
    [
        ("RATE_LIMIT_PER_CLIENT", "abc", "RATE_LIMIT_PER_CLIENT"),
        ("RATE_LIMIT_PRE_AUTH", "0/minute", "RATE_LIMIT_PRE_AUTH"),
        ("MAX_BATCH_ITEMS", "abc", "MAX_BATCH_ITEMS"),
        ("MAX_CONCURRENT_ANALYSES", "0", "MAX_CONCURRENT_ANALYSES"),
        ("RATE_LIMIT_IPV6_PREFIX", "129", "RATE_LIMIT_IPV6_PREFIX"),
        ("API_KEY_MIN_LENGTH", "0", "API_KEY_MIN_LENGTH"),
    ],
)
def test_bad_env_value_fails_closed_at_import(tmp_path: Path, var: str, value: str, name: str) -> None:
    proc = _run_child(
        "import app.config", tmp_path, DEPLOY_ENV="local", BACKEND_HOST="127.0.0.1", **{var: value}
    )
    assert proc.returncode != 0, f"import succeeded with {var}={value!r}"
    # Message honesty: the error names the variable or field so the operator can fix it.
    assert name.lower() in proc.stderr.lower() or name in proc.stderr


@pytest.mark.parametrize(
    "env",
    [
        pytest.param({"DEPLOY_ENV": "local", "BACKEND_HOST": "127.0.0.1"}, id="local-loopback-no-key"),
        pytest.param({"DEPLOY_ENV": "railway"}, id="railway-with-key"),
        pytest.param({}, id="deploy-env-unset-with-key"),
    ],
)
def test_startup_positive_controls(tmp_path: Path, env: dict[str, str]) -> None:
    if env.get("DEPLOY_ENV") != "local":
        env = {**env, "API_KEY": _child_key()}
    proc = _run_child("import app.config", tmp_path, **env)
    assert proc.returncode == 0, f"legitimate config refused: {_tail(proc.stderr)}"


def test_uvicorn_refuses_to_serve_without_key_outside_local(tmp_path: Path) -> None:
    # --lifespan off: a check that lives only in lifespan would be skipped (sec M3).
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--lifespan",
            "off",
        ],
        cwd=BACKEND_DIR,
        env=_child_env(tmp_path, DEPLOY_ENV="railway"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        rc = proc.wait(timeout=UVICORN_EXIT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        pytest.fail(
            "uvicorn kept serving with DEPLOY_ENV=railway and no API_KEY "
            "(ruling 2: a missing key outside local aborts startup)."
        )
    assert rc != 0


_DOCS_PROBE = """
import json
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app, client=("203.0.113.40", 4000)) as c:
    print(json.dumps({p: c.get(p).status_code for p in ("/docs", "/redoc", "/openapi.json")}))
"""


def test_docs_routes_absent_or_protected_outside_local(tmp_path: Path) -> None:
    proc = _run_child(_DOCS_PROBE, tmp_path, DEPLOY_ENV="railway", API_KEY=_child_key())
    assert proc.returncode == 0, f"probe failed: {_tail(proc.stderr)}"
    codes = json.loads(proc.stdout.strip().splitlines()[-1])
    assert all(code in (401, 404) for code in codes.values()), codes


def test_docs_routes_served_to_local_loopback(db_override: Any) -> None:
    # Positive control (green today): the local developer still gets the docs.
    with TestClient(app, client=LOOPBACK) as c:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert c.get(path).status_code == 200, path


# ---------------------------------------------------------------------------
# Local opt-in exemption at request time (ruling 2, sec C1)
# ---------------------------------------------------------------------------


@pytest.fixture
def local_noauth(configure: Callable[..., config.Settings]) -> config.Settings:
    return configure(deploy_env="local", api_key="", bind_host="127.0.0.1")


@pytest.mark.parametrize("peer", ["127.0.0.1", "::1", "127.8.9.10"])
def test_local_noauth_serves_loopback_peer(local_noauth: Any, db_override: Any, peer: str) -> None:
    with client_at(peer) as c:
        assert c.get("/analyses").status_code == 200


@pytest.mark.parametrize("peer", ["100.64.1.2", "192.168.1.10", "testclient", "0.0.0.0"])
def test_local_noauth_rejects_non_loopback_peer(local_noauth: Any, db_override: Any, peer: str) -> None:
    with client_at(peer) as c:
        resp = c.get("/analyses", headers={"Host": "localhost"})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid or missing API key"}


def test_local_noauth_rejects_missing_peer(local_noauth: Any, db_override: Any) -> None:
    async def scenario() -> int:
        status, _, _ = await asgi_call("GET", "/analyses", client=None)
        return status

    assert drive(scenario) == 401


@pytest.mark.parametrize(
    "header,value",
    [
        ("X-Forwarded-For", "1.2.3.4"),
        ("X-Forwarded-For", ""),
        ("x-forwarded-for", "127.0.0.1"),
        ("Forwarded", "for=1.2.3.4"),
        ("X-Real-IP", "1.2.3.4"),
    ],
)
def test_local_noauth_rejects_forwarded_request(
    local_noauth: Any, db_override: Any, header: str, value: str
) -> None:
    with client_at("127.0.0.1") as c:
        assert c.get("/analyses", headers={header: value}).status_code == 401


def test_railway_mode_loopback_peer_still_needs_key(railway: Any, db_override: Any) -> None:
    # railtail on the same host makes the peer 127.0.0.1; only DEPLOY_ENV=local exempts.
    railway()
    with client_at("127.0.0.1") as c:
        assert c.get("/analyses", headers={"Host": "localhost"}).status_code == 401


# ---------------------------------------------------------------------------
# Key handling at request time (rulings 3, 4, 9; sec M2, M3, M4)
# ---------------------------------------------------------------------------


def test_valid_key_passes_and_wrong_key_fails(railway: Any, db_override: Any) -> None:
    s = railway()
    with client_at(CLIENT_PEER) as c:
        assert c.get("/analyses", headers={"X-API-Key": s.api_key}).status_code == 200
        assert c.get("/analyses", headers={"x-api-key": s.api_key}).status_code == 200
        for wrong in (s.api_key[:-1], s.api_key + "x", s.api_key.upper() + "!", ""):
            resp = c.get("/analyses", headers={"X-API-Key": wrong})
            assert resp.status_code == 401
            assert resp.json() == {"detail": "Invalid or missing API key"}
        assert c.get("/analyses").status_code == 401


@pytest.mark.parametrize("param", ["api_key", "x-api-key", "X-API-Key", "key"])
def test_query_param_key_rejected(railway: Any, db_override: Any, param: str) -> None:
    s = railway()
    with client_at(CLIENT_PEER) as c:
        assert c.get("/analyses", params={param: s.api_key}).status_code == 401


HOSTILE_KEY_BYTES = [
    pytest.param(b"\xe9\xe9", id="latin1-non-ascii"),
    pytest.param("é".encode() * 20, id="utf8-non-ascii"),
    pytest.param(b"\xff\xfe\xfd", id="invalid-utf8"),
    pytest.param(b"\xed\xa0\x80", id="encoded-lone-surrogate"),
    pytest.param(b"abc\x00def", id="nul"),
    pytest.param(b"abc\r\nX-Evil: 1", id="crlf"),
    pytest.param(b"A" * 65536, id="64k"),
    pytest.param(b"", id="empty"),
]


@pytest.mark.parametrize("value", HOSTILE_KEY_BYTES)
def test_non_ascii_key_header_is_401_not_500(railway: Any, db_override: Any, value: bytes) -> None:
    railway()

    async def scenario() -> int:
        status, _, _ = await asgi_call("GET", "/analyses", headers=[(b"x-api-key", value)])
        return status

    assert drive(scenario) == 401


def test_valid_key_with_trailing_whitespace_bytes_is_401(railway: Any, db_override: Any) -> None:
    s = railway()

    async def scenario() -> list[int]:
        out = []
        for raw in (s.api_key.encode() + b" ", b" " + s.api_key.encode(), s.api_key.encode() + b"\x00"):
            status, _, _ = await asgi_call("GET", "/analyses", headers=[(b"x-api-key", raw)])
            out.append(status)
        status, _, _ = await asgi_call("GET", "/analyses", headers=[(b"x-api-key", s.api_key.encode())])
        out.append(status)
        return out

    assert drive(scenario) == [401, 401, 401, 200]


def test_key_compare_uses_fixed_length_bytes(
    railway: Any, db_override: Any, monkeypatch: pytest.MonkeyPatch, security: Any
) -> None:
    calls: list[tuple[type, type, int, int]] = []
    real = hmac.compare_digest

    def spy(a: Any, b: Any) -> bool:
        calls.append((type(a), type(b), len(a), len(b)))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    monkeypatch.setattr(secrets, "compare_digest", spy)
    if hasattr(security, "compare_digest"):
        monkeypatch.setattr(security, "compare_digest", spy)
    s = railway()
    lengths: set[int] = set()
    with client_at(CLIENT_PEER) as c:
        for presented in (s.api_key, s.api_key[:-1], "short", s.api_key * 2):
            calls.clear()
            c.get("/analyses", headers={"X-API-Key": presented})
            assert calls, "the key check must go through hmac.compare_digest"
            for ta, tb, la, lb in calls:
                assert ta is bytes and tb is bytes, (ta, tb)
                assert la == lb
                lengths.add(la)
    # Fixed-length digests: the compared length never depends on the presented key.
    assert len(lengths) == 1


INVALID_AT_REQUEST_TIME = [
    pytest.param({"deploy_env": "railway", "api_key": ""}, id="railway-empty-key"),
    pytest.param({"deploy_env": "railway", "api_key": "short"}, id="railway-short-key"),
    pytest.param({"deploy_env": "dev", "api_key": ""}, id="unknown-env-empty-key"),
]


@pytest.mark.parametrize("state", INVALID_AT_REQUEST_TIME)
def test_dependency_fails_closed_without_lifespan(
    state: dict[str, str], monkeypatch: pytest.MonkeyPatch, security: Any, db_override: Any
) -> None:
    _require_fields(list(state))
    bad = dataclasses.replace(config.settings)
    for name, value in state.items():
        object.__setattr__(bad, name, value)  # bypass validation, as a bug elsewhere would
    _install(monkeypatch, security, bad)
    c = TestClient(app, client=(CLIENT_PEER, 40000))  # no lifespan
    for path in ("/analyses", "/health"):
        resp = c.get(path)
        assert resp.status_code == 503, (path, resp.status_code)


# ---------------------------------------------------------------------------
# /health (ruling 8, sec M5)
# ---------------------------------------------------------------------------


def test_health_exempt_from_auth(railway: Any) -> None:
    s = railway()
    with client_at(CLIENT_PEER) as c:
        for headers in ({}, {"X-API-Key": "wrong"}, {"X-API-Key": s.api_key}):
            resp = c.get("/health", headers=headers)
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}


def test_health_body_is_static_locally() -> None:
    # Positive control (green today): no version, model or corpus details.
    with TestClient(app, client=LOOPBACK) as c:
        assert c.get("/health").json() == {"status": "ok"}


def test_health_flood_does_not_limit_analyze(railway: Any, stubs: Any, db_override: Any) -> None:
    n = 3
    s = railway(
        rate_limit_health=rate(n),
        rate_limit_pre_auth=rate(n),
        rate_limit_per_client=rate(n),
        rate_limit_per_key=rate(n),
    )
    with client_at(CLIENT_PEER) as c:
        for _ in range(n):
            assert c.get("/health").status_code == 200
        _assert_429(c.get("/health"), PERIOD_SECONDS["minute"])
        resp = c.post("/analyze", json=ANALYZE_BODY, headers={"X-API-Key": s.api_key})
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Rate limits (rulings 5, 6, 9, 10, 11; sec H1, H2, H4, M4)
# ---------------------------------------------------------------------------


def test_429_has_retry_after_and_fixed_body(railway: Any, stubs: Any, db_override: Any) -> None:
    n = 2
    s = railway(rate_limit_per_client=rate(n))
    with client_at(CLIENT_PEER) as c:
        hdr = {"X-API-Key": s.api_key}
        assert [c.post("/analyze", json=ANALYZE_BODY, headers=hdr).status_code for _ in range(n)] == [200] * n
        _assert_429(c.post("/analyze", json=ANALYZE_BODY, headers=hdr), PERIOD_SECONDS["minute"])
    assert stubs.analyze_text.await_count == n


def test_rate_limit_window_resets(railway: Any, stubs: Any, db_override: Any, clock: dict) -> None:
    n = 2
    s = railway(rate_limit_per_client=rate(n, "hour"))
    hdr = {"X-API-Key": s.api_key}
    with client_at(CLIENT_PEER) as c:
        for _ in range(n):
            assert c.post("/analyze", json=ANALYZE_BODY, headers=hdr).status_code == 200
        _assert_429(c.post("/analyze", json=ANALYZE_BODY, headers=hdr), PERIOD_SECONDS["hour"])
        clock["now"] += PERIOD_SECONDS["hour"] + 1
        assert c.post("/analyze", json=ANALYZE_BODY, headers=hdr).status_code == 200


def test_rate_limit_isolates_clients_behind_trusted_proxy(
    railway: Any, stubs: Any, db_override: Any
) -> None:
    # Ruling 11: the issue's per-key-not-global test, as per-client identity under T2.
    n = 3
    s = railway(rate_limit_per_client=rate(n), **_trusted_proxy())
    with client_at(PROXY_PEER) as c:
        a = {"X-API-Key": s.api_key, IDENTITY_HEADER: "203.0.113.1"}
        b = {"X-API-Key": s.api_key, IDENTITY_HEADER: "203.0.113.2"}
        for _ in range(n):
            assert c.post("/analyze", json=ANALYZE_BODY, headers=a).status_code == 200
        _assert_429(c.post("/analyze", json=ANALYZE_BODY, headers=a), PERIOD_SECONDS["minute"])
        assert c.post("/analyze", json=ANALYZE_BODY, headers=b).status_code == 200


def test_per_key_ceiling_applies_across_clients(railway: Any, stubs: Any, db_override: Any) -> None:
    n = 3
    s = railway(rate_limit_per_key=rate(n), **_trusted_proxy())
    with client_at(PROXY_PEER) as c:
        codes = [
            c.post(
                "/analyze",
                json=ANALYZE_BODY,
                headers={"X-API-Key": s.api_key, IDENTITY_HEADER: f"203.0.113.{i + 1}"},
            ).status_code
            for i in range(n + 1)
        ]
    assert codes == [200] * n + [429]


def test_client_ip_header_ignored_from_untrusted_peer(railway: Any, stubs: Any, db_override: Any) -> None:
    n = 3
    s = railway(rate_limit_per_client=rate(n), **_trusted_proxy())
    with client_at(UNTRUSTED_PEER) as c:
        codes = [
            c.post(
                "/analyze",
                json=ANALYZE_BODY,
                headers={"X-API-Key": s.api_key, IDENTITY_HEADER: f"203.0.113.{i + 1}"},
            ).status_code
            for i in range(n + 1)
        ]
    assert codes == [200] * n + [429]


@pytest.mark.parametrize(
    "header,template",
    [
        ("X-Forwarded-For", "10.9.0.{i}, 203.0.113.1"),
        ("X-Forwarded-For", "10.9.0.{i}"),
        ("Forwarded", "for=10.9.0.{i}"),
        ("X-Real-IP", "10.9.0.{i}"),
    ],
)
@pytest.mark.parametrize("peer", [UNTRUSTED_PEER, PROXY_PEER])
def test_forwarding_headers_do_not_rotate_bucket(
    railway: Any, stubs: Any, db_override: Any, header: str, template: str, peer: str
) -> None:
    n = 3
    s = railway(rate_limit_per_client=rate(n), **_trusted_proxy())
    with client_at(peer) as c:
        codes = []
        for i in range(n + 1):
            headers = {"X-API-Key": s.api_key, header: template.format(i=i + 1)}
            if peer == PROXY_PEER:
                headers[IDENTITY_HEADER] = "203.0.113.50"
            codes.append(c.post("/analyze", json=ANALYZE_BODY, headers=headers).status_code)
    assert codes == [200] * n + [429]


def test_client_ip_header_ignored_without_valid_key(railway: Any, db_override: Any) -> None:
    railway(**_trusted_proxy())
    with client_at(PROXY_PEER) as c:
        resp = c.get("/analyses", headers={"X-API-Key": "wrong", IDENTITY_HEADER: "203.0.113.1"})
        assert resp.status_code == 401
        before = dict(_limiter().store_sizes())
        for i in range(50):
            c.get(
                "/analyses",
                headers={"X-API-Key": secrets.token_hex(20), IDENTITY_HEADER: f"203.0.113.{i + 2}"},
            )
        assert dict(_limiter().store_sizes()) == before


HOSTILE_IDENTITY = [
    pytest.param(b"evil", id="not-an-ip"),
    pytest.param(b"203.0.113.1, 203.0.113.2", id="comma-list"),
    pytest.param(b"203.0.113.1\r\nX-API-Key: x", id="crlf"),
    pytest.param(b"", id="empty"),
    pytest.param(b" ", id="space"),
    pytest.param(b"9" * 10000, id="10k"),
    pytest.param("٢٠٣.٠.١١٣.١".encode(), id="arabic-digits"),
    pytest.param("２０３.０.１１３.１".encode(), id="fullwidth-digits"),
    pytest.param(b"fe80::1%eth0", id="scoped-v6"),
    pytest.param(b"203.0.113.1:8080", id="with-port"),
    pytest.param(b"\xff\xfe", id="invalid-utf8"),
    pytest.param(b"203.0.113.1\x00", id="nul"),
]


@pytest.mark.parametrize("value", HOSTILE_IDENTITY)
def test_hostile_identity_header_never_500(
    railway: Any, stubs: Any, db_override: Any, value: bytes
) -> None:
    s = railway(**_trusted_proxy())

    async def scenario() -> tuple[int, bytes]:
        status, _, body = await asgi_call(
            "POST",
            "/analyze",
            headers=[(b"x-api-key", s.api_key.encode()), (IDENTITY_HEADER.lower().encode(), value)],
            client=(PROXY_PEER, 40000),
            body=ANALYZE_RAW,
        )
        return status, body

    status, body = drive(scenario)
    assert status < 500, status
    assert s.api_key.encode() not in body


def test_garbage_identity_values_do_not_mint_buckets(
    railway: Any, stubs: Any, db_override: Any
) -> None:
    n = 3
    s = railway(rate_limit_per_client=rate(n), **_trusted_proxy())
    garbage = [f"evil-{i}".encode() for i in range(n)] + [b"", b"203.0.113.1, 203.0.113.2", b"x" * 300]

    async def scenario() -> list[int]:
        out = []
        for value in garbage:
            status, _, _ = await asgi_call(
                "POST",
                "/analyze",
                headers=[(b"x-api-key", s.api_key.encode()), (IDENTITY_HEADER.lower().encode(), value)],
                client=(PROXY_PEER, 40000),
                body=ANALYZE_RAW,
            )
            out.append(status)
        return out

    codes = drive(scenario)
    assert sum(1 for code in codes if code == 200) <= n, codes
    assert all(code < 500 for code in codes), codes


@pytest.mark.parametrize("via", ["peer", "identity-header"])
def test_ipv6_same_64_shares_bucket(railway: Any, stubs: Any, db_override: Any, via: str) -> None:
    n = 3
    s = railway(rate_limit_per_client=rate(n), **_trusted_proxy())
    addrs = [f"2001:db8:1:2::{i + 1}" for i in range(n + 1)]

    def send(c: TestClient, addr: str) -> int:
        headers = {"X-API-Key": s.api_key}
        if via == "identity-header":
            headers[IDENTITY_HEADER] = addr
        return c.post("/analyze", json=ANALYZE_BODY, headers=headers).status_code

    with client_at(PROXY_PEER if via == "identity-header" else addrs[0]):
        codes = []
        for addr in addrs:
            peer = PROXY_PEER if via == "identity-header" else addr
            codes.append(send(client_at(peer), addr))
        other = "2001:db8:1:3::1"
        other_code = send(client_at(PROXY_PEER if via == "identity-header" else other), other)
    assert codes == [200] * n + [429]
    assert other_code == 200


def test_ipv6_prefix_comes_from_config(railway: Any, stubs: Any, db_override: Any) -> None:
    n = 3
    s = railway(rate_limit_per_client=rate(n), rate_limit_ipv6_prefix=48)
    peers = [f"2001:db8:1:{i + 1:x}::1" for i in range(n + 1)]
    with client_at(peers[0]):
        codes = [
            client_at(p).post("/analyze", json=ANALYZE_BODY, headers={"X-API-Key": s.api_key}).status_code
            for p in peers
        ]
    assert codes == [200] * n + [429]


def test_ipv4_mapped_shares_bucket(railway: Any, stubs: Any, db_override: Any) -> None:
    n = 3
    s = railway(rate_limit_per_client=rate(n))
    hdr = {"X-API-Key": s.api_key}
    with client_at("::ffff:203.0.113.1") as mapped:
        codes = [mapped.post("/analyze", json=ANALYZE_BODY, headers=hdr).status_code for _ in range(n)]
        codes.append(client_at("203.0.113.1").post("/analyze", json=ANALYZE_BODY, headers=hdr).status_code)
    assert codes == [200] * n + [429]


def test_unauthenticated_flood_is_rate_limited_pre_auth(railway: Any, db_override: Any) -> None:
    n = 4
    railway(rate_limit_pre_auth=rate(n))
    with client_at(UNTRUSTED_PEER) as c:
        codes = [c.get("/analyses", headers={"X-API-Key": secrets.token_hex(20)}).status_code for _ in range(n)]
        codes.append(c.get("/analyses").status_code)
        last = c.get("/analyses", headers={"X-API-Key": secrets.token_hex(20)})
    assert codes == [401] * n + [429]
    _assert_429(last, PERIOD_SECONDS["minute"])


def test_invalid_keys_create_no_buckets(railway: Any, db_override: Any) -> None:
    railway()
    with client_at(UNTRUSTED_PEER) as c:
        assert c.get("/analyses", headers={"X-API-Key": secrets.token_hex(20)}).status_code == 401
        before = dict(_limiter().store_sizes())
        for _ in range(300):
            c.get("/analyses", headers={"X-API-Key": secrets.token_hex(20)})
        assert dict(_limiter().store_sizes()) == before


def test_bad_key_flood_does_not_drain_valid_client(railway: Any, stubs: Any, db_override: Any) -> None:
    n = 3
    s = railway(rate_limit_per_key=rate(n), rate_limit_per_client=rate(n))
    with client_at(CLIENT_PEER) as victim:
        attacker = client_at(UNTRUSTED_PEER)
        for _ in range(n + 2):
            attacker.post("/analyze", json=ANALYZE_BODY, headers={"X-API-Key": s.api_key[:-1] + "!"})
        resp = victim.post("/analyze", json=ANALYZE_BODY, headers={"X-API-Key": s.api_key})
    assert resp.status_code == 200


@pytest.mark.parametrize("mode", ["peers-valid-key", "peers-bad-key", "identities-valid-key"])
def test_ip_store_is_bounded(railway: Any, stubs: Any, db_override: Any, mode: str) -> None:
    cap = 50
    s = railway(rate_limit_max_tracked_clients=cap, **_trusted_proxy())
    good = s.api_key.encode()

    async def scenario() -> tuple[dict[str, int], int]:
        for i in range(cap * 4):
            addr = str(ipaddress.ip_address("198.18.0.0") + i)
            if mode == "identities-valid-key":
                headers = [(b"x-api-key", good), (IDENTITY_HEADER.lower().encode(), addr.encode())]
                peer = PROXY_PEER
            else:
                key = good if mode == "peers-valid-key" else secrets.token_hex(20).encode()
                headers = [(b"x-api-key", key)]
                peer = addr
            await asgi_call("POST", "/analyze", headers=headers, client=(peer, 40000), body=ANALYZE_RAW)
        sizes = dict(_limiter().store_sizes())
        status, _, _ = await asgi_call(
            "POST",
            "/analyze",
            headers=[(b"x-api-key", good)],
            client=("203.0.113.250", 40000),
            body=ANALYZE_RAW,
        )
        return sizes, status

    sizes, newcomer = drive(scenario)
    assert sizes and all(v <= cap for v in sizes.values()), sizes
    assert max(sizes.values()) == cap, f"no store reached the cap; is the limiter tracking? {sizes}"
    # At the cap the store evicts; a new legitimate client is still served.
    assert newcomer == 200


def test_cors_exposes_retry_after(railway: Any, stubs: Any, db_override: Any) -> None:
    s = railway(rate_limit_per_client=rate(1))
    origin = s.allowed_origins[0]
    hdr = {"X-API-Key": s.api_key, "Origin": origin}
    with client_at(CLIENT_PEER) as c:
        assert c.post("/analyze", json=ANALYZE_BODY, headers=hdr).status_code == 200
        resp = c.post("/analyze", json=ANALYZE_BODY, headers=hdr)
    assert resp.status_code == 429
    exposed = [h.strip().lower() for h in resp.headers.get("access-control-expose-headers", "").split(",")]
    assert "retry-after" in exposed


# ---------------------------------------------------------------------------
# /analyze/batch (ruling 7, sec H3)
# ---------------------------------------------------------------------------


def _batch(k: int) -> dict:
    return {"items": [{"url": f"https://example.com/policy-{i}"} for i in range(k)]}


def test_batch_rejects_over_max_items(railway: Any, stubs: Any, db_override: Any) -> None:
    s = railway()
    cap = s.max_batch_items
    hdr = {"X-API-Key": s.api_key}
    with client_at(CLIENT_PEER) as c:
        assert c.post("/analyze/batch", json=_batch(cap + 1), headers=hdr).status_code == 422
        assert stubs.fetch.await_count == 0 and stubs.batch.await_count == 0
        assert c.post("/analyze/batch", json=_batch(cap), headers=hdr).status_code == 200


def _batch_size() -> int:
    _require_fields(["max_batch_items"])
    k = min(config.settings.max_batch_items, 3)
    if k < 2:
        pytest.fail("max_batch_items default is below 2; the cost test needs a batch of at least 2")
    return k


def test_batch_consumes_one_token_per_item(railway: Any, stubs: Any, db_override: Any) -> None:
    k = _batch_size()
    s = railway(rate_limit_per_client=rate(k))
    hdr = {"X-API-Key": s.api_key}
    with client_at(CLIENT_PEER) as c:
        assert c.post("/analyze/batch", json=_batch(k), headers=hdr).status_code == 200
        _assert_429(c.post("/analyze", json=ANALYZE_BODY, headers=hdr), PERIOD_SECONDS["minute"])


def test_batch_larger_than_remaining_budget_is_429_without_work(
    railway: Any, stubs: Any, db_override: Any
) -> None:
    # The cap may not exceed the per-client limit (PR #296 r2), so the budget is
    # made short by spending one token first, not by a limit below the batch size.
    k = _batch_size()
    s = railway(rate_limit_per_client=rate(k), max_batch_items=k)
    hdr = {"X-API-Key": s.api_key}
    with client_at(CLIENT_PEER) as c:
        assert c.post("/analyze", json=ANALYZE_BODY, headers=hdr).status_code == 200
        resp = c.post("/analyze/batch", json=_batch(k), headers=hdr)
    _assert_429(resp, PERIOD_SECONDS["minute"])
    assert stubs.fetch.await_count == 0
    assert stubs.batch.await_count == 0


@pytest.mark.parametrize("unit", list(PERIOD_SECONDS))
@pytest.mark.parametrize("fits", [True, False], ids=["cap-equals-limit", "cap-one-above-limit"])
@pytest.mark.parametrize("field_name", BATCH_CHARGED_RATES)
def test_batch_cap_above_a_per_item_rate_is_refused_at_load(
    field_name: str, fits: bool, unit: str
) -> None:
    """Contract (PR #296 r2, HIGH): a batch is charged one token per item to every
    rate in BATCH_CHARGED_RATES, in a fixed window that holds N tokens whatever its
    unit. A cap above any N makes a full batch a guaranteed 429, so Settings must
    refuse it at load, naming MAX_BATCH_ITEMS and the rate's variable. A cap equal
    to N is the boundary and is accepted. Only ``field_name`` is tight here; the
    other charged rate sits one above, so the refusal is attributable."""
    n = config.settings.max_batch_items
    overrides: dict[str, Any] = {
        name: rate(n if name == field_name else n + 1, unit) for name in BATCH_CHARGED_RATES
    }
    overrides["max_batch_items"] = n if fits else n + 1
    if fits:
        s = build_settings(**_valid_base(), **overrides)
        assert s.max_batch_items == n and getattr(s, field_name) == rate(n, unit)
        return
    base = _valid_base()
    with pytest.raises(ValueError) as caught:
        build_settings(**base, **overrides)
    message = str(caught.value)
    assert "MAX_BATCH_ITEMS" in message, message
    assert field_name.upper() in message, f"message must name the rate to fix: {message}"
    assert base["api_key"] not in message


_SHIPPED_BATCH_FIELDS = (
    "rate_limit_pre_auth",
    *BATCH_CHARGED_RATES,
    "max_batch_items",
    "max_concurrent_analyses",
)


def test_shipped_defaults_admit_a_full_batch(
    tmp_path: Path, railway: Any, stubs: Any, db_override: Any
) -> None:
    """Contract (PR #296 r2, HIGH): with every limit at its shipped default (no
    RATE_LIMIT_* / MAX_* variables set), one client's first batch of exactly
    max_batch_items items is admitted (200), not rate-limited. The defaults are read
    from a child import with those variables scrubbed, because conftest raises the
    rates for the rest of the suite; the child must also accept its own defaults."""
    names = json.dumps(list(_SHIPPED_BATCH_FIELDS))
    proc = _run_child(
        "import json\nfrom app import config\n"
        f"print(json.dumps({{n: getattr(config.settings, n) for n in {names}}}))",
        tmp_path,
        DEPLOY_ENV="railway",
        API_KEY=_child_key(),
    )
    assert proc.returncode == 0, f"shipped defaults refused at import: {_tail(proc.stderr)}"
    defaults = json.loads(proc.stdout.strip().splitlines()[-1])
    s = railway(**defaults)
    assert s.max_batch_items == defaults["max_batch_items"]
    with client_at(CLIENT_PEER) as c:
        resp = c.post(
            "/analyze/batch", json=_batch(s.max_batch_items), headers={"X-API-Key": s.api_key}
        )
    assert resp.status_code == 200, (
        f"a full batch of MAX_BATCH_ITEMS={s.max_batch_items} under the shipped "
        f"RATE_LIMIT_PER_CLIENT={s.rate_limit_per_client} got {resp.status_code}"
    )
    assert stubs.batch.await_count == 1


# ---------------------------------------------------------------------------
# Concurrency cap on LLM routes (ruling 5, sec H1)
# ---------------------------------------------------------------------------


def _held_scenario(
    s: config.Settings, monkeypatch: pytest.MonkeyPatch, extra: Callable[[httpx.AsyncClient], Awaitable[httpx.Response]]
) -> Callable[[], Awaitable[tuple[Any, list[Any], int]]]:
    cap = s.max_concurrent_analyses

    async def scenario() -> tuple[Any, list[Any], int]:
        release = asyncio.Event()
        all_in = asyncio.Event()
        entered = 0

        async def slow(*a: Any, **k: Any) -> AnalysisResult:
            nonlocal entered
            entered += 1
            if entered >= cap:
                all_in.set()
            await release.wait()
            return AnalysisResult(payload=_fake_payload(), issues=[])

        monkeypatch.setattr(main, "analyze_text", slow)
        transport = httpx.ASGITransport(app=app, client=(CLIENT_PEER, 40000))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            hdr = {"X-API-Key": s.api_key}
            held = [
                asyncio.create_task(ac.post("/analyze", json=ANALYZE_BODY, headers=hdr))
                for _ in range(cap)
            ]
            outcome: Any
            try:
                await asyncio.wait_for(all_in.wait(), timeout=10)
                outcome = await asyncio.wait_for(extra(ac), timeout=PROMPT_S)
            except TimeoutError:
                outcome = "queued"
            finally:
                release.set()
                results = await asyncio.gather(*held, return_exceptions=True)
            after = await ac.post("/analyze", json=ANALYZE_BODY, headers=hdr)
        return outcome, results, after.status_code

    return scenario


def test_concurrency_cap_rejects_extra_analysis_promptly(
    railway: Any, stubs: Any, db_override: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = railway(max_concurrent_analyses=2)

    async def extra(ac: httpx.AsyncClient) -> httpx.Response:
        return await ac.post("/analyze", json=ANALYZE_BODY, headers={"X-API-Key": s.api_key})

    outcome, held, after = drive(_held_scenario(s, monkeypatch, extra))
    assert outcome != "queued", "the extra /analyze waited behind the cap instead of a prompt 429"
    _assert_429(outcome, PERIOD_SECONDS["minute"] * 60)
    assert [r.status_code for r in held] == [200] * s.max_concurrent_analyses
    assert after == 200, "the cap must be released when requests finish"


def test_concurrency_cap_is_shared_with_batch(
    railway: Any, stubs: Any, db_override: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = railway(max_concurrent_analyses=1)

    async def extra(ac: httpx.AsyncClient) -> httpx.Response:
        return await ac.post("/analyze/batch", json=_batch(1), headers={"X-API-Key": s.api_key})

    outcome, _, _ = drive(_held_scenario(s, monkeypatch, extra))
    assert outcome != "queued", "/analyze/batch waited behind the cap instead of a prompt 429"
    assert outcome.status_code == 429
    assert stubs.batch.await_count == 0


# ---------------------------------------------------------------------------
# The key never leaks (ruling 9, sec M4, H4)
# ---------------------------------------------------------------------------


def _walk(obj: Any, seen: set[int], depth: int = 0) -> Any:
    if id(obj) in seen or depth > 8:
        return
    seen.add(id(obj))
    yield obj
    if isinstance(obj, (str, bytes, bytearray, int, float, bool, type(None))):
        return
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            yield from _walk(k, seen, depth + 1)
            yield from _walk(v, seen, depth + 1)
        return
    if isinstance(obj, (list, tuple, set, frozenset)) or type(obj).__name__ in ("deque", "OrderedDict"):
        for item in list(obj):
            yield from _walk(item, seen, depth + 1)
        return
    attrs = getattr(obj, "__dict__", None)
    if isinstance(attrs, dict):
        yield from _walk(attrs, seen, depth + 1)
    for slot in getattr(type(obj), "__slots__", ()) or ():
        if hasattr(obj, slot):
            yield from _walk(getattr(obj, slot), seen, depth + 1)


def test_key_never_in_logs_or_bodies(
    railway: Any,
    stubs: Any,
    db_override: Any,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    security: Any,
) -> None:
    caplog.set_level(logging.DEBUG)
    s = railway(rate_limit_per_client=rate(1))
    key = s.api_key
    typo = key[:-1] + ("0" if key[-1] != "0" else "1")
    responses: list[httpx.Response] = []
    with client_at(CLIENT_PEER) as c:
        responses.append(c.post("/analyze", json=ANALYZE_BODY, headers={"X-API-Key": key}))
        responses.append(c.post("/analyze", json=ANALYZE_BODY, headers={"X-API-Key": typo}))
        responses.append(c.post("/analyze", json=ANALYZE_BODY, headers={"X-API-Key": key}))
        responses.append(c.get("/analyses", params={"api_key": key}))
        limiter = _limiter()
        for value in _walk(limiter, set()):
            if isinstance(value, str):
                assert key not in value and typo not in value
            elif isinstance(value, (bytes, bytearray)):
                assert key.encode() not in value and typo.encode() not in value
    assert [r.status_code for r in responses] == [200, 401, 429, 401]
    bad = dataclasses.replace(config.settings)
    object.__setattr__(bad, "api_key", "")
    _install(monkeypatch, security, bad)
    responses.append(TestClient(app, client=(CLIENT_PEER, 40000)).get("/analyses", headers={"X-API-Key": key}))
    assert responses[-1].status_code == 503
    # The test's own HTTP client logs request URLs (one carries the key on purpose);
    # only server-side records count.
    server_log = "\n".join(
        r.getMessage() for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))
    )
    for secret in (key, typo, key[:12], hashlib.sha256(key.encode()).hexdigest()):
        assert secret not in server_log
        for r in responses:
            assert secret not in r.text
            assert all(secret not in v for v in r.headers.values())


# --- PR #296 r2 finding 3: the FastAPI floor the routes rely on -------------
#
# main.py declares ``Depends(..., scope="function")`` so the admission slot is
# released when the endpoint returns, not after the response streams. FastAPI
# added the ``scope`` parameter in 0.121.0: verified by inspecting
# ``fastapi/param_functions.py`` in the published wheels (0.120.4, the last
# 0.120.x release, has no ``scope`` parameter; 0.121.0 has it). A bare
# ``fastapi`` requirement lets a cached or older resolver install a release on
# which every guarded route fails at import with a TypeError.
LAST_FASTAPI_WITHOUT_DEPENDS_SCOPE = "0.120.4"
_LOWER_BOUND_OPS = {">=", ">", "==", "~=", "==="}


def _ci_test_requirement_lines() -> list[tuple[str, str]]:
    """(source, requirement line) for everything the CI test job installs.

    Read from ci.yml rather than restated, and following nested ``-r`` files,
    so a new requirements file in the install step is covered automatically.
    """
    import shlex

    import yaml

    repo = BACKEND_DIR.parents[1]
    doc = yaml.safe_load((repo / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    runs = [s.get("run", "") for s in doc["jobs"]["test"]["steps"]]
    install = [r for r in runs if "pip install" in r]
    assert install, "ci.yml test job has no pip install step"
    lines: list[tuple[str, str]] = []
    pending: list[Path] = []
    for script in install:
        tokens = shlex.split(script.replace("\\\n", " "))
        prev = ""
        for tok in tokens:
            if prev in {"-r", "--requirement"}:
                pending.append(repo / tok)
            elif tok[:1].isalpha() and tok not in {"pip", "install"}:
                lines.append(("ci.yml", tok))  # inline requirement, e.g. pytest-cov
            prev = tok
    seen: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        assert path.is_file(), f"ci.yml installs a missing requirements file: {path.name}"
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line.startswith(("-r ", "--requirement ")):
                pending.append(path.parent / line.split(None, 1)[1])
            elif line and not line.startswith("-"):
                lines.append((str(path.relative_to(repo)), line))
    return lines


def test_ci_requirements_pin_fastapi_at_or_above_depends_scope() -> None:
    from packaging.requirements import Requirement
    from packaging.version import Version

    import fastapi

    floor = Version(LAST_FASTAPI_WITHOUT_DEPENDS_SCOPE)
    reqs = [(src, Requirement(line)) for src, line in _ci_test_requirement_lines()]
    fastapi_reqs = [(src, r) for src, r in reqs if r.name.lower() == "fastapi"]
    # Did-nothing guard: the parse must actually find the dependency.
    assert fastapi_reqs, "no fastapi requirement found in the files the CI test job installs"
    for src, req in fastapi_reqs:
        bounds = [Version(s.version) for s in req.specifier if s.operator in _LOWER_BOUND_OPS]
        assert any(b > floor for b in bounds), (
            f"{src}: '{req}' has no lower bound above {floor}; main.py uses "
            "Depends(scope=...), which FastAPI added in the next minor release"
        )
        for probe in (floor, Version("0.120.0"), Version("0.100.0"), Version("0.1.0")):
            assert probe not in req.specifier, f"{src}: '{req}' still admits fastapi {probe}"
        # The pin must not be impossible: the version CI resolves today satisfies it.
        assert req.specifier.contains(fastapi.__version__, prereleases=True), (
            f"{src}: '{req}' excludes the installed fastapi {fastapi.__version__}"
        )
