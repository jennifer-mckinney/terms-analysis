"""Acceptance tests for #135: CORS allowlist for the Railway domain (never ``*``).

Anchor: plan D10 consequence 2. ``main.py`` installs ``CORSMiddleware`` with
``allow_credentials=True`` and ``allow_origins=settings.allowed_origins``, so a ``*``
entry is a credentialed wildcard: Starlette then echoes ANY requesting origin on a
preflight, with ``Access-Control-Allow-Credentials: true``.

Contract the implementation must meet (lead ruling: reject with ``ValueError`` at
``Settings`` construction, in ``__post_init__``, like the #133 validators, so both
import and ``dataclasses.replace`` fail closed):

* every entry of ``allowed_origins`` (env ``ALLOWED_ORIGINS``) is one serialised
  origin, ``scheme://host[:port]``, in ASCII, exactly as a browser sends it in the
  ``Origin`` header: no ``*`` anywhere, no path (not even ``/``), query, fragment,
  userinfo, whitespace, control or format characters, and a numeric port if any;
* the scheme is ``https``; ``http`` is allowed only for the loopback hosts
  ``localhost``, ``127.0.0.1`` and ``[::1]``;
* the list form is checked as given (no silent stripping); the env form keeps
  ``_split_env_list`` (comma split, edge whitespace stripped, empty items dropped);
* the value is a sequence of ``str`` and cannot be widened in place after
  validation (the middleware holds the same object);
* the error names ``allowed_origins`` / ``ALLOWED_ORIGINS`` and never echoes raw
  control, format or separator characters or a huge value.

Not decided here (left to the implementation): whether an empty list is valid (it
closes CORS, which a Streamlit-only deployment does not need), upper-case input and
``127.0.0.0/8`` loopback addresses other than ``127.0.0.1``.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config
from tests.test_auth_ratelimit import BACKEND_DIR, CHILD_TIMEOUT_S, _child_env, _child_key

FIELD_RE = r"(?i)allowed_origins"
ENV_VAR = "ALLOWED_ORIGINS"

# Test data, not configuration: origins under reserved or example names.
RAILWAY = "https://terms.up.railway.app"
EVIL = "https://evil.example"
VALID_REMOTE = "https://a.example"

# ---------------------------------------------------------------------------
# Vectors: (family, entry, allowed). Every family has both outcomes (contract test).
# ---------------------------------------------------------------------------

ORIGIN_VECTORS: list[tuple[str, str, bool]] = [
    # Wildcards, alone or embedded.
    ("wildcard", "*", False),
    ("wildcard", "https://*.up.railway.app", False),
    ("wildcard", "https://*", False),
    ("wildcard", RAILWAY, True),
    # https is required for every non-loopback host.
    ("remote-scheme", "http://x.up.railway.app", False),
    ("remote-scheme", "http://terms.up.railway.app:8080", False),
    ("remote-scheme", "http://0.0.0.0:8000", False),
    ("remote-scheme", "http://[::]:8000", False),
    ("remote-scheme", "http://192.168.1.10:8501", False),
    ("remote-scheme", "http://[::2]:8000", False),
    ("remote-scheme", "https://terms.up.railway.app:8443", True),
    ("remote-scheme", VALID_REMOTE, True),
    # http only for loopback; look-alike hosts are remote.
    ("loopback-http", "http://localhost", True),
    ("loopback-http", "http://localhost:8501", True),
    ("loopback-http", "http://127.0.0.1:8000", True),
    ("loopback-http", "http://[::1]", True),
    ("loopback-http", "http://[::1]:8000", True),
    ("loopback-http", "https://localhost:8443", True),
    ("loopback-http", "http://localhost.evil.example", False),
    ("loopback-http", "http://127.0.0.1.evil.example", False),
    ("loopback-http", "http://evil.example#@localhost", False),
    ("loopback-http", "http://0x7f.0.0.1", False),
    ("loopback-http", "http://2130706433", False),
    ("loopback-http", "http://::1", False),
    ("loopback-http", "http://[::1", False),
    # Shape: one serialised origin and nothing else.
    ("shape", "https://a.example/", False),
    ("shape", "https://a.example/path", False),
    ("shape", "https://a.example?q=1", False),
    ("shape", "https://a.example#frag", False),
    ("shape", "https://user@a.example", False),
    ("shape", "https://user:pw@a.example", False),
    ("shape", "https://terms.up.railway.app@evil.example", False),
    ("shape", "a.example", False),
    ("shape", "//a.example", False),
    ("shape", "https:a.example", False),
    ("shape", "https://", False),
    ("shape", "https:///a.example", False),
    ("shape", "https://a.example:", False),
    ("shape", "https://a.example:abc", False),
    ("shape", "https://a.example:99999", False),
    ("shape", "", False),
    ("shape", "   ", False),
    ("shape", " https://a.example", False),
    ("shape", "https://a.example ", False),
    ("shape", "https://a.example:8443", True),
    # Non-http(s) schemes, including the opaque "null" origin.
    ("scheme", "null", False),
    ("scheme", "file://", False),
    ("scheme", "file:///etc/passwd", False),
    ("scheme", "ftp://a.example", False),
    ("scheme", "ws://localhost:8000", False),
    ("scheme", "wss://a.example", False),
    ("scheme", "javascript:alert(1)", False),
    ("scheme", "data:text/html,x", False),
    ("scheme", VALID_REMOTE, True),
    # Structure forgery and look-alikes: ASCII only, one origin per entry.
    ("forgery", "https://terms.up.railway.аpp", False),  # Cyrillic a
    ("forgery", "ｈｔｔｐｓ://terms.up.railway.app", False),  # fullwidth
    ("forgery", RAILWAY + "\r\nX-Evil: 1", False),
    ("forgery", RAILWAY + "\n", False),
    ("forgery", RAILWAY + " ", False),
    ("forgery", RAILWAY + "\x85", False),
    ("forgery", RAILWAY + "\x00", False),
    ("forgery", "https://terms​.up.railway.app", False),
    ("forgery", "https://‮ppa.yawliar.pu.smret", False),
    ("forgery", RAILWAY + "\ud800", False),
    ("forgery", VALID_REMOTE + "," + EVIL, False),
    ("forgery", "https://[terms.up.railway.app]", False),
    ("forgery", "https://xn--80ak6aa92e.com", True),  # punycode is ASCII
]

ALLOWED = [v for _f, v, ok in ORIGIN_VECTORS if ok]
REJECTED = [pytest.param(v, id=f"{f}:{v!r}"[:80]) for f, v, ok in ORIGIN_VECTORS if not ok]
ALLOWED_PARAMS = [pytest.param(v, id=f"{f}:{v!r}"[:80]) for f, v, ok in ORIGIN_VECTORS if ok]


def _replace(origins: Any) -> config.Settings:
    return dataclasses.replace(config.settings, allowed_origins=origins)


def _preflight_headers(origin: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-api-key",
    }


def _run(code: str, tmp_path: Path, *args: str, origins: str | bytes | None, **env: str) -> subprocess.CompletedProcess:
    """Fresh interpreter with ALLOWED_ORIGINS exactly as given (None means unset)."""
    child_env: dict[str, Any] = _child_env(tmp_path, **env)
    child_env.pop(ENV_VAR, None)
    if origins is not None:
        child_env[ENV_VAR] = origins
    return subprocess.run(
        [sys.executable, "-c", code, *args],
        cwd=BACKEND_DIR,
        env=child_env,
        capture_output=True,
        timeout=CHILD_TIMEOUT_S,
    )


def _text(raw: bytes) -> str:
    return raw.decode("utf-8", "backslashreplace")


def _railway_env() -> dict[str, str]:
    return {"DEPLOY_ENV": "railway", "API_KEY": _child_key()}


# Runs the real app in a child and reports the CORS headers per requested origin.
PREFLIGHT_CHILD = """
import json, sys
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app, client=("127.0.0.1", 50000))
out = {}
for origin in sys.argv[1:]:
    r = client.options("/analyze", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-api-key",
    })
    out[origin] = [r.headers.get("access-control-allow-origin"),
                   r.headers.get("access-control-allow-credentials")]
print(json.dumps(out))
"""


# ---------------------------------------------------------------------------
# Card tests (issue #135 test spec)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["*", " * ", f"{VALID_REMOTE},*", f"*,{VALID_REMOTE}"])
def test_wildcard_origin_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(ENV_VAR, value)
    with pytest.raises(ValueError, match=FIELD_RE) as exc:
        config.Settings()
    # Message honesty: the refusal names the wildcard as the reason.
    assert "*" in str(exc.value) or "wildcard" in str(exc.value).lower()


@pytest.mark.parametrize("value", ["http://example.up.railway.app", f"{RAILWAY},http://x.up.railway.app"])
def test_non_https_remote_origin_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(ENV_VAR, value)
    with pytest.raises(ValueError, match=FIELD_RE) as exc:
        config.Settings()
    assert "https" in str(exc.value).lower()


def test_railway_origin_allowed(tmp_path: Path) -> None:
    """Green today (positive control): the real app echoes an allowed https origin only."""
    proc = _run(PREFLIGHT_CHILD, tmp_path, RAILWAY, EVIL, origins=RAILWAY, **_railway_env())
    assert proc.returncode == 0, _text(proc.stderr)[-2000:]
    out = json.loads(_text(proc.stdout).strip().splitlines()[-1])
    assert out[RAILWAY] == [RAILWAY, "true"]
    assert out[EVIL][0] is None


# ---------------------------------------------------------------------------
# Vectors through dataclasses.replace (construction after import)
# ---------------------------------------------------------------------------


def test_origin_vectors_contract() -> None:
    families: dict[str, set[bool]] = {}
    for family, _value, ok in ORIGIN_VECTORS:
        families.setdefault(family, set()).add(ok)
    lacking = sorted(f for f, outcomes in families.items() if outcomes != {True, False})
    assert not lacking, f"families without both an allowed and a rejected vector: {lacking}"


@pytest.mark.parametrize("entry", REJECTED)
def test_rejected_origin_fails_closed_on_replace(entry: str) -> None:
    with pytest.raises(ValueError, match=FIELD_RE):
        _replace([entry])


@pytest.mark.parametrize("entry", REJECTED)
def test_rejected_origin_mixed_into_valid_list_fails_closed(entry: str) -> None:
    # Every entry is checked, wherever it sits in the list.
    for origins in ([RAILWAY, entry], [entry, RAILWAY], [RAILWAY, entry, VALID_REMOTE]):
        with pytest.raises(ValueError, match=FIELD_RE):
            _replace(origins)


@pytest.mark.parametrize("entry", ALLOWED_PARAMS)
def test_allowed_origin_accepted_unchanged(entry: str) -> None:
    """Green today (positive control)."""
    assert list(_replace([entry]).allowed_origins) == [entry]


def test_all_allowed_vectors_accepted_together_and_as_tuple() -> None:
    """Green today (positive control): a list or a tuple of valid origins."""
    assert list(_replace(list(ALLOWED)).allowed_origins) == ALLOWED
    assert list(_replace(tuple(ALLOWED)).allowed_origins) == ALLOWED


@pytest.mark.parametrize(
    "origins",
    [
        pytest.param(VALID_REMOTE, id="bare-str"),
        pytest.param("*", id="bare-str-wildcard"),
        pytest.param([None], id="none-entry"),
        pytest.param([VALID_REMOTE.encode()], id="bytes-entry"),
        pytest.param([1], id="int-entry"),
        pytest.param(None, id="none"),
        pytest.param({VALID_REMOTE: True}, id="dict"),
    ],
)
def test_allowed_origins_must_be_a_sequence_of_str(origins: Any) -> None:
    # A bare str would reach CORSMiddleware, where `"*" in allow_origins` is a
    # substring test and membership is per character.
    with pytest.raises(ValueError, match=FIELD_RE):
        _replace(origins)


def test_many_origins_every_entry_checked() -> None:
    many = [f"https://site{i}.example" for i in range(30_000)]
    assert len(_replace(many).allowed_origins) == len(many)  # green today
    with pytest.raises(ValueError, match=FIELD_RE):
        _replace(many + ["*"])


# ---------------------------------------------------------------------------
# Generated hostile characters (QUALITY-BAR R2)
# ---------------------------------------------------------------------------

_HOSTILE_CATEGORIES = ("Cc", "Cf", "Zl", "Zp", "Zs")
_LONE_SURROGATES = ("\ud800", "\udbff", "\udc00", "\udfff")


def _hostile_chars() -> list[str]:
    chars = [chr(cp) for cp in range(0x110000) if unicodedata.category(chr(cp)) in _HOSTILE_CATEGORIES]
    return chars + list(_LONE_SURROGATES)


def _inject(ch: str) -> list[str]:
    return [
        ch + RAILWAY,
        RAILWAY + ch,
        "https://" + ch + "terms.up.railway.app",
        "https://ter" + ch + "ms.up.railway.app",
        "https" + ch + "://terms.up.railway.app",
        RAILWAY + ":84" + ch + "43",
    ]


def test_generated_hostile_characters_rejected() -> None:
    _replace([RAILWAY])  # the base origin itself is valid
    cases = [entry for ch in _hostile_chars() for entry in _inject(ch)]
    accepted = []
    for entry in cases:
        try:
            _replace([entry])
        except ValueError:
            continue
        accepted.append(entry)
    print(f"generated hostile origin cases: {len(cases)}")
    assert not accepted, (
        f"{len(accepted)} of {len(cases)} hostile entries accepted, e.g. "
        f"{[e.encode('unicode_escape') for e in accepted[:5]]}"
    )


# ---------------------------------------------------------------------------
# Output safety and message honesty (F8)
# ---------------------------------------------------------------------------

_UNSAFE_CATEGORIES = ("Cc", "Cf", "Cs", "Zl", "Zp")
HUGE_PATH = "/" + "a" * (2 * 1024 * 1024)


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(RAILWAY + "\r\nX-Evil: 1", id="crlf"),
        pytest.param(RAILWAY + "\x00", id="nul"),
        pytest.param("https://‮ppa.yawliar.pu.smret", id="bidi"),
        pytest.param(RAILWAY + " ", id="line-separator"),
        pytest.param(RAILWAY + "\x1b[31m", id="ansi-escape"),
        pytest.param(RAILWAY + "\ud800", id="lone-surrogate"),
        pytest.param(RAILWAY + HUGE_PATH, id="2mb-path"),
    ],
)
def test_rejection_message_is_safe(entry: str) -> None:
    with pytest.raises(ValueError, match=FIELD_RE) as exc:
        _replace([entry])
    msg = str(exc.value)
    unsafe = sorted({f"U+{ord(c):04X}" for c in msg if unicodedata.category(c) in _UNSAFE_CATEGORIES})
    assert not unsafe, f"raw unsafe characters in the error message: {unsafe}"
    msg.encode("utf-8")  # strict: a lone surrogate in the message would raise here
    assert HUGE_PATH not in msg and len(msg) < len(HUGE_PATH)


# ---------------------------------------------------------------------------
# Environment: Settings construction and import fail closed (F13)
# ---------------------------------------------------------------------------

ENV_REJECTED = [
    pytest.param("*", id="star"),
    pytest.param(f"{VALID_REMOTE},*", id="star-mixed"),
    pytest.param("http://x.up.railway.app", id="http-remote"),
    pytest.param(f"{RAILWAY},null", id="null-mixed"),
    pytest.param("file://", id="file"),
    pytest.param(f"{RAILWAY}/", id="trailing-slash"),
    pytest.param(f"{RAILWAY}​", id="zero-width-space"),
]


@pytest.mark.parametrize("value", ENV_REJECTED)
def test_bad_origin_env_fails_closed_at_settings_construction(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(ENV_VAR, value)
    with pytest.raises(ValueError, match=FIELD_RE):
        config.Settings()


def _env_example_origins() -> str:
    lines = (config.REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    values = [ln.split("=", 1)[1] for ln in lines if ln.startswith(f"{ENV_VAR}=")]
    assert len(values) == 1, f".env.example must set {ENV_VAR} exactly once"
    return values[0]


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="unset-default"),
        pytest.param("env-example", id="env-example"),
        pytest.param(RAILWAY, id="railway"),
        pytest.param(f"{RAILWAY}, http://localhost:8501 ,http://[::1]:8501", id="railway-plus-loopback"),
    ],
)
def test_origin_env_positive_controls(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    """Green today: the default, the documented example and a Railway deployment load."""
    if value is None:
        monkeypatch.delenv(ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(ENV_VAR, _env_example_origins() if value == "env-example" else value)
    s = config.Settings()
    assert len(s.allowed_origins) >= 1


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("*", id="star"),
        pytest.param("http://x.up.railway.app", id="http-remote"),
        pytest.param(RAILWAY.encode() + b"\xff", id="invalid-utf8"),
    ],
)
def test_bad_origin_env_fails_closed_at_import(tmp_path: Path, value: str | bytes) -> None:
    proc = _run("import app.config", tmp_path, origins=value, DEPLOY_ENV="local", BACKEND_HOST="127.0.0.1")
    assert proc.returncode != 0, f"import succeeded with {ENV_VAR}={value!r}"
    assert ENV_VAR.lower() in _text(proc.stderr).lower()
    assert b"\xff" not in proc.stderr


def test_default_origins_load_at_import(tmp_path: Path) -> None:
    """Green today (positive control): ALLOWED_ORIGINS unset starts."""
    proc = _run("import app.config", tmp_path, origins=None, DEPLOY_ENV="local", BACKEND_HOST="127.0.0.1")
    assert proc.returncode == 0, _text(proc.stderr)[-2000:]


@pytest.mark.parametrize("value", ["*", f"{VALID_REMOTE},*"])
def test_wildcard_env_never_serves_credentialed_preflight(tmp_path: Path, value: str) -> None:
    # The real app must refuse to start; today it echoes any origin with credentials.
    proc = _run(PREFLIGHT_CHILD, tmp_path, EVIL, origins=value, **_railway_env())
    assert proc.returncode != 0, f"app started with {ENV_VAR}={value!r} and answered {_text(proc.stdout).strip()}"
    assert ENV_VAR.lower() in _text(proc.stderr).lower()


# ---------------------------------------------------------------------------
# The live app (in process, default settings from conftest)
# ---------------------------------------------------------------------------


def test_configured_origins_preflight_echoed(app_client: TestClient) -> None:
    """Green today (positive control): every configured origin gets its own echo."""
    for origin in config.settings.allowed_origins:
        resp = app_client.options("/analyze", headers=_preflight_headers(origin))
        assert resp.headers.get("access-control-allow-origin") == origin
        assert resp.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.parametrize("origin", [EVIL, "null", "http://localhost.evil.example"])
def test_unlisted_origin_gets_no_allow_origin(app_client: TestClient, origin: str) -> None:
    """Green today (control): preflight and simple request from an unlisted origin."""
    assert origin not in config.settings.allowed_origins
    pre = app_client.options("/analyze", headers=_preflight_headers(origin))
    assert "access-control-allow-origin" not in pre.headers
    simple = app_client.get("/health", headers={"Origin": origin})
    assert "access-control-allow-origin" not in simple.headers


def test_live_allowlist_cannot_be_widened_after_validation(app_client: TestClient) -> None:
    # Indirection: CORSMiddleware keeps a reference to settings.allowed_origins, so an
    # in-place append to a validated list widens CORS without any validation.
    origins = config.settings.allowed_origins
    try:
        origins.append(EVIL)  # type: ignore[union-attr]
        mutated = True
    except (AttributeError, TypeError):
        mutated = False
    try:
        resp = app_client.options("/analyze", headers=_preflight_headers(EVIL))
        assert "access-control-allow-origin" not in resp.headers, "appended origin was served"
    finally:
        if mutated:
            origins.remove(EVIL)  # type: ignore[union-attr]
