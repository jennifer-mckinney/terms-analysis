"""Acceptance tests for #133 on the batch CLI (``scripts/batch_analyze.py``).

PR #296 review: the backend now requires ``X-API-Key`` on every route, and the
two Streamlit UIs send it (``_backend_headers``), but ``batch_analyze.py`` sent
only ``Content-Type``, so every run 401s against a backend with a key.

Contract, mirroring the UI one (``test_streamlit_backend_auth.py``):

* the key comes from the same environment variable the UIs read (taken from the
  UI sources, not restated here) and travels only in the header the backend
  checks (``app.security.API_KEY_HEADER``), exactly once;
* unset or empty means keyless local mode: no key header at all;
* a key holding anything other than printable, non-space ASCII is refused
  before any request with a message naming the variable, never the value;
* the key never appears in the ``SystemExit`` message or on stderr, including
  on HTTP 401 and when the server reflects it back; a 401 names the variable
  to fix (message honesty).

No network: ``urllib.request.urlopen`` is replaced by a recorder in every test.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import secrets
import sys
import unicodedata
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterator

import pytest

from app.security import API_KEY_HEADER, UNAUTHORIZED_DETAIL

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "batch_analyze.py"
WEBAPP_DIR = BACKEND_DIR.parent / "webapp"
UI_SOURCES = (WEBAPP_DIR / "app_streamlit_v2.py", WEBAPP_DIR / "app_streamlit_legacy.py")
# The header the backend's auth dependency reads, as urllib will send it.
KEY_HEADER = API_KEY_HEADER.decode("ascii").lower()
API_BASE = "http://127.0.0.1:9"  # never contacted: urlopen is replaced


def _ui_key_env_name() -> str:
    """BACKEND_API_KEY_ENV as both UIs define it (one contract for every client).

    Parsed, not imported: importing a Streamlit app runs it. Both UIs must agree,
    so the CLI cannot drift from either.
    """
    names = set()
    for src in UI_SOURCES:
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and [getattr(t, "id", None) for t in node.targets] == ["BACKEND_API_KEY_ENV"]
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                names.add(node.value.value)
    assert len(names) == 1, f"UIs disagree on, or lack, BACKEND_API_KEY_ENV: {names}"
    return names.pop()


KEY_ENV = _ui_key_env_name()


def _key() -> str:
    # Generated per run; hex never matches the evidence leak patterns.
    return secrets.token_hex(24)


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._buf = io.BytesIO(body)

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _Recorder:
    """Stands in for urllib.request.urlopen and keeps every Request it is given."""

    def __init__(self) -> None:
        self.requests: list[urllib.request.Request] = []
        self.error: Callable[[urllib.request.Request], Exception] | None = None

    def __call__(self, req: Any, *args: Any, **kwargs: Any) -> _FakeResponse:
        assert isinstance(req, urllib.request.Request), "the CLI must pass a Request"
        self.requests.append(req)
        if self.error is not None:
            raise self.error(req)
        return _FakeResponse(json.dumps({"items": []}).encode("utf-8"))

    def key_values(self, req: urllib.request.Request) -> list[str]:
        """Every value sent under the key header (any capitalisation)."""
        return [v for k, v in req.header_items() if k.lower() == KEY_HEADER]


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(urllib.request, "urlopen", rec)
    return rec


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(KEY_ENV, raising=False)


def _load_cli() -> ModuleType:
    """Fresh module object, loaded after the test has set the environment."""
    spec = importlib.util.spec_from_file_location("batch_analyze_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def run_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorder: _Recorder, clean_env: None
) -> Iterator[Callable[[], tuple[int, Path]]]:
    in_csv = tmp_path / "in.csv"
    in_csv.write_text("name,url,jurisdiction\nA,https://example.com/tos,\n", encoding="utf-8")
    out_csv = tmp_path / "out.csv"

    def _run() -> tuple[int, Path]:
        cli = _load_cli()
        monkeypatch.setattr(
            sys, "argv", ["batch_analyze.py", "--input", str(in_csv), "--output", str(out_csv), "--api", API_BASE]
        )
        return cli.main(), out_csv

    yield _run


# ── sends the key ────────────────────────────────────────────────────────────


def test_batch_sends_backend_key_in_api_key_header(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder, run_cli: Callable[[], tuple[int, Path]]
) -> None:
    key = _key()
    monkeypatch.setenv(KEY_ENV, key)
    rc, out = run_cli()
    assert rc == 0 and out.exists()
    assert len(recorder.requests) == 1
    req = recorder.requests[0]
    assert recorder.key_values(req) == [key], "key must travel once, in the header the backend checks"
    # Only in the header: not in the URL or the body.
    assert key not in req.full_url
    assert key.encode("ascii") not in (req.data or b"")
    assert req.get_header("Content-type") == "application/json"


def test_batch_sends_key_with_every_printable_non_space_ascii_char(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder, run_cli: Callable[[], tuple[int, Path]]
) -> None:
    # Boundary positive control: 0x21 and 0x7E are the edges the UIs allow.
    key = "".join(map(chr, range(0x21, 0x7F)))
    monkeypatch.setenv(KEY_ENV, key)
    rc, _ = run_cli()
    assert rc == 0
    assert recorder.key_values(recorder.requests[0]) == [key]


def test_batch_reads_key_at_call_time_not_import_time(
    monkeypatch: pytest.MonkeyPatch, recorder: _Recorder, clean_env: None
) -> None:
    # Same as the UIs' _backend_headers: the environment at call time decides.
    cli = _load_cli()
    key = _key()
    monkeypatch.setenv(KEY_ENV, key)
    cli.call_batch_endpoint(API_BASE, {"items": []})
    assert recorder.key_values(recorder.requests[0]) == [key]


# ── keyless local mode ───────────────────────────────────────────────────────


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
def test_batch_without_key_sends_no_key_header(
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
    run_cli: Callable[[], tuple[int, Path]],
    value: str | None,
) -> None:
    if value is not None:
        monkeypatch.setenv(KEY_ENV, value)
    rc, out = run_cli()
    assert rc == 0 and out.exists()
    assert len(recorder.requests) == 1
    assert recorder.key_values(recorder.requests[0]) == []


# ── hostile keys: refused before any request ─────────────────────────────────

# Generated, not listed (QUALITY-BAR R2), same families as the UI test: every
# code point in Cc, Cf, Zs, Zl and Zp (line breaks, bidi and zero-width
# controls, every space incl. U+0020), every str.splitlines() breaker, the
# surrogateescape range os.environ uses for invalid UTF-8 bytes, and the
# non-ASCII letters NFKC folds to an ASCII letter. NUL is excluded only because
# no environment can hold it (os.environ raises ValueError).
_HOSTILE_CATEGORIES = {"Cc", "Cf", "Zs", "Zl", "Zp"}


def _generated_hostile_chars() -> tuple[str, ...]:
    chars = {chr(c) for c in range(1, 0x110000) if unicodedata.category(chr(c)) in _HOSTILE_CATEGORIES}
    chars |= {ch for ch in map(chr, range(1, 0x110000)) if len(("a" + ch + "b").splitlines()) > 1}
    chars |= {chr(c) for c in range(0xDC80, 0xDD00)}  # os.fsdecode of bytes 0x80-0xFF
    chars |= {
        chr(c)
        for c in range(0x80, 0x10000)
        if (folded := unicodedata.normalize("NFKC", chr(c))).isascii() and folded.isalpha()
    }
    return tuple(sorted(chars))


HOSTILE_CHARS = _generated_hostile_chars()


def test_hostile_char_table_has_every_family() -> None:
    # Contract for the generated table: each family is present, none is allowed.
    for must in ("\r", "\n", "\x7f", " ", "\u2028", "\u2029", "\u0085", "\u202e", "\u200b", "\udcff", "\uff21"):
        assert must in HOSTILE_CHARS, repr(must)
    assert not any(0x21 <= ord(ch) <= 0x7E for ch in HOSTILE_CHARS)


def test_batch_refuses_hostile_key_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
    run_cli: Callable[[], tuple[int, Path]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = _key()
    # Each character inside the value and trailing it (the classic "\n" tail),
    # plus values made of nothing but one hostile character (not "unset").
    cases = [base[:4] + ch + base[4:] for ch in HOSTILE_CHARS]
    cases += [base + ch for ch in HOSTILE_CHARS]
    whole = ("\n", "\r\n", " ", "\t", "\u2028")
    cases += list(whole)
    checked = 0
    for hostile in cases:
        monkeypatch.setenv(KEY_ENV, hostile)
        recorder.requests.clear()
        with pytest.raises(SystemExit) as exc_info:
            run_cli()
        msg = str(exc_info.value.code)
        err = capsys.readouterr().err
        assert recorder.requests == [], f"{hostile!r}: reached the HTTP layer"
        assert exc_info.value.code not in (0, None), f"{hostile!r}: refusal must exit non-zero"
        assert KEY_ENV in msg, f"{hostile!r}: message must name the variable to fix"
        for leak in {hostile, hostile.strip(), base} - {""}:
            if leak.strip():
                assert leak not in msg and leak not in err, f"{hostile!r}: value echoed"
        checked += 1
    assert checked == len(cases) == 2 * len(HOSTILE_CHARS) + len(whole)
    print(f"generated hostile key cases: {checked}")


def test_batch_hostile_key_does_not_write_output(
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
    run_cli: Callable[[], tuple[int, Path]],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(KEY_ENV, _key() + "\r\nX-Injected: 1")
    with pytest.raises(SystemExit):
        run_cli()
    assert recorder.requests == []
    # Fail closed: no summary CSV is written after a refusal.
    assert not (tmp_path / "out.csv").exists()


# ── the key never leaks in errors ────────────────────────────────────────────


def _http_error(status: int, body: bytes) -> Callable[[urllib.request.Request], Exception]:
    def make(req: urllib.request.Request) -> Exception:
        return urllib.error.HTTPError(req.full_url, status, "error", Message(), io.BytesIO(body))

    return make


def _reflecting_body(req: urllib.request.Request) -> bytes:
    # A misconfigured proxy that echoes request headers back in its error body.
    return json.dumps({"detail": UNAUTHORIZED_DETAIL, "echo": dict(req.header_items())}).encode("utf-8")


@pytest.mark.parametrize("reflect", [False, True], ids=["backend-401", "reflecting-401"])
def test_batch_401_never_leaks_key_and_names_variable(
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
    run_cli: Callable[[], tuple[int, Path]],
    capsys: pytest.CaptureFixture[str],
    reflect: bool,
) -> None:
    key = _key()
    monkeypatch.setenv(KEY_ENV, key)

    def make(req: urllib.request.Request) -> Exception:
        body = _reflecting_body(req) if reflect else json.dumps({"detail": UNAUTHORIZED_DETAIL}).encode()
        return _http_error(401, body)(req)

    recorder.error = make
    with pytest.raises(SystemExit) as exc_info:
        run_cli()
    msg = str(exc_info.value.code)
    err = capsys.readouterr().err
    assert len(recorder.requests) == 1
    assert recorder.key_values(recorder.requests[0]) == [key], "a 401 must come from a request that carried the key"
    assert key not in msg and key not in err
    assert "401" in msg
    # Honesty: a 401 tells the operator which variable to fix.
    assert KEY_ENV in msg


@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_batch_other_http_errors_never_leak_reflected_key(
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
    run_cli: Callable[[], tuple[int, Path]],
    capsys: pytest.CaptureFixture[str],
    status: int,
) -> None:
    key = _key()
    monkeypatch.setenv(KEY_ENV, key)
    recorder.error = lambda req: _http_error(status, _reflecting_body(req))(req)
    with pytest.raises(SystemExit) as exc_info:
        run_cli()
    msg = str(exc_info.value.code)
    # Precondition, so the leak check is not vacuous: the key was sent.
    assert recorder.key_values(recorder.requests[0]) == [key]
    assert str(status) in msg
    assert key not in msg and key not in capsys.readouterr().err


def test_batch_network_error_never_leaks_key(
    monkeypatch: pytest.MonkeyPatch,
    recorder: _Recorder,
    run_cli: Callable[[], tuple[int, Path]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    key = _key()
    monkeypatch.setenv(KEY_ENV, key)
    recorder.error = lambda req: urllib.error.URLError(f"refused, headers={dict(req.header_items())}")
    with pytest.raises(SystemExit) as exc_info:
        run_cli()
    assert recorder.key_values(recorder.requests[0]) == [key]
    assert key not in str(exc_info.value.code) and key not in capsys.readouterr().err
