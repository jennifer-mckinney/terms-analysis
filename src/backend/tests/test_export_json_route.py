"""Acceptance tests for #36 (GAP-002): ``GET /exports/analysis/{analysis_id}.json``.

Owner rulings (2026-10-12), "Add .json, keep alias", then "we need a schema
version field and pretty formatting" (replaces "same response"):

* ``GET /exports/analysis/{analysis_id}.json`` is the PRD 7.3.11 (F5.2) contract;
* the extensionless ``GET /exports/analysis/{analysis_id}`` stays as an alias that
  shares its handler: both answer byte-identically;
* the body is the stored analysis, unchanged, plus one top-level ``schema_version``
  whose value is ``app.schemas.EXPORT_SCHEMA_VERSION`` (one constant, read here,
  never restated);
* the body is ``json.dumps(..., indent=2)`` output (either ``ensure_ascii`` choice),
  served as ``application/json`` with ``Content-Disposition: attachment;
  filename="analysis-<id>.json"``; the filename stays a safe RFC 6266 quoted-string
  for any stored ID;
* error responses (404, 401, 429) are unchanged: compact, no Content-Disposition;
* ``GET /exports/analysis/{analysis_id}.pdf`` keeps working and is never shadowed.

Route matching the expectations rely on (Starlette ``compile_path``): a path
parameter uses the ``str`` convertor ``[^/]+``, which is greedy, and the pattern is
anchored with ``$``. Starlette matches against the percent-decoded path and decodes
invalid UTF-8 as U+FFFD (so does uvicorn). Consequences pinned below:

* ``<id>.json.json`` reaches the ``.json`` route with ``analysis_id="<id>.json"``:
  exactly ONE suffix is removed, never repeatedly;
* ``<id>.pdf.json`` reaches the ``.json`` route (``analysis_id="<id>.pdf"``) and is
  never a PDF; ``<id>.json.pdf`` reaches the PDF route (``analysis_id="<id>.json"``);
* the suffix match is case-sensitive: ``<id>.JSON`` is the alias with that literal ID;
* ``$`` in Python also matches before ONE trailing ``\\n``, so ``<id>.pdf%0A`` already
  serves the PDF today. The ``.json`` route must behave the same as ``.pdf`` for
  that and the other equivalent spellings (parity test, not a pin of the quirk).

Red until the export body is versioned, pretty-printed and served as an
attachment: the export body tests, the schema version constant, the
Content-Disposition tests and the v2 UI JSON export. Every routing, error-path,
auth and rate-limit test is a regression guard.
"""

# Fixtures imported from sibling test modules are requested by parameter name,
# which linters read as redefinitions of the import (F811).
# ruff: noqa: F811

from __future__ import annotations

import json
import re
import secrets
import sys
import unicodedata
from typing import Any, NamedTuple
from urllib.parse import quote, unquote, urlsplit
from uuid import uuid4

import httpx
import pytest
import requests
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from app import schemas as app_schemas
from app.main import app
from app.models import Analysis as AnalysisModel
from app.security import API_KEY_HEADER, UNAUTHORIZED_DETAIL
from tests.test_auth_ratelimit import (  # noqa: F401  (pytest fixtures are used by name)
    CLIENT_PEER,
    PERIOD_SECONDS,
    UNTRUSTED_PEER,
    _assert_429,
    client_at,
    configure,
    db_override,
    railway,
    rate,
    security,
)
from tests.test_main_endpoints import _insert_analysis
from tests.test_streamlit_backend_auth import (  # noqa: F401  (fake_context is a fixture)
    APPTEST_TIMEOUT_S,
    HEADER_ENV,
    KEY_ENV,
    V2_PATH,
    _results_state,
    fake_context,
)

# The routes under test. These are the API contract itself (PRD 7.3.11), not config.
ALIAS = "/exports/analysis/{id}"
JSON_ROUTE = ALIAS + ".json"
PDF_ROUTE = ALIAS + ".pdf"
JSON_ROUTE_TEMPLATE = "/exports/analysis/{analysis_id}.json"
PDF_CONTENT_TYPE = "application/pdf"
PDF_MAGIC = b"%PDF"
JSON_CONTENT_TYPE = "application/json"

# PRD F5.2 contract names. The VALUE of the version lives in app.schemas only (F13).
SCHEMA_KEY = "schema_version"
SCHEMA_VERSION_ATTR = "EXPORT_SCHEMA_VERSION"
DISPOSITION = "content-disposition"
PRETTY_INDENT = 2  # PRD F5.2 technical note: json.dumps(indent=2)

KEY_HEADER = API_KEY_HEADER.decode("ascii")

# Hostile ID size: below httpx's 64 KiB URL cap so the request reaches the app.
HUGE_ID_LEN = 60_000

# Unicode categories whose code points can forge structure in a path segment
# (QUALITY-BAR R2). Cs (lone surrogates) cannot be UTF-8 encoded; they are sent
# as their surrogatepass bytes, which the server decodes as U+FFFD.
HOSTILE_CATEGORIES = ("Cc", "Cf", "Zl", "Zp")
LONE_SURROGATES = (0xD800, 0xDBFF, 0xDC00, 0xDFFF)

# #351: the generated set depends on the interpreter's Unicode tables, so assert a
# floor instead of an exact count (today: 722 on Python 3.14).
MIN_GENERATED_VECTORS = 500

# Non-ASCII text stored in the analysis, to prove the body round-trips as UTF-8
# whichever ensure_ascii setting the handler picks.
NON_ASCII_NAME = "Política de privacidad — 東京 \U0001f600"
NON_ASCII_TEXT = "Nous partageons vos données « avec » des tiers   שלום."


def _path(template: str, ident: str) -> str:
    return template.format(id=ident)


def _schema_version() -> str:
    """The one export schema version, read from the app (never restated here)."""
    value = getattr(app_schemas, SCHEMA_VERSION_ATTR, None)
    assert isinstance(value, str) and re.fullmatch(r"\d+\.\d+", value), (
        f"app.schemas.{SCHEMA_VERSION_ATTR} must hold the PRD F5.2 export schema "
        f"version as MAJOR.MINOR; got {type(value).__name__}"
    )
    return value


def _assert_carries(resp: httpx.Response, row: AnalysisModel) -> dict[str, Any]:
    """Additivity: every stored field is present with its stored value."""
    body = resp.json()
    stored = json.loads(row.result_json)
    changed = sorted(k for k in stored if k not in body or body[k] != stored[k])
    assert changed == [], f"export dropped or changed stored fields: {changed}"
    return body


def _assert_export_of(resp: httpx.Response, row: AnalysisModel) -> None:
    """The F5.2 body: the stored analysis plus exactly one field, schema_version."""
    body = _assert_carries(resp, row)
    added = sorted(set(body) - set(json.loads(row.result_json)))
    assert added == [SCHEMA_KEY], f"export must add only {SCHEMA_KEY!r}; added {added}"
    assert body[SCHEMA_KEY] == _schema_version()


def _assert_pretty(resp: httpx.Response) -> None:
    """Byte-equal to json.dumps(indent=2) of its own content, either ensure_ascii."""
    parsed = json.loads(resp.content.decode("utf-8"))
    candidates = {
        json.dumps(parsed, indent=PRETTY_INDENT, ensure_ascii=ascii_only).encode("utf-8")
        for ascii_only in (True, False)
    }
    assert resp.content in candidates, "export body is not json.dumps(indent=2) output"
    lines = resp.content.split(b"\n")
    assert len(lines) > 2, "export body is not multi-line"
    indent = b" " * PRETTY_INDENT
    assert lines[1].startswith(indent) and not lines[1].startswith(indent + b" ")


def _assert_compact_error(resp: httpx.Response) -> None:
    """Error responses stay as they were: one line, no attachment header."""
    assert b"\n" not in resp.content, "error body was pretty-printed"
    assert DISPOSITION not in resp.headers, "error response carries Content-Disposition"


# RFC 6266 attachment with a quoted-string filename and an optional RFC 5987
# filename*. The quoted filename may hold no '"' and no '\' at all: the owner
# ruling is that no quote from the ID ever reaches the header.
_DISPOSITION_RE = re.compile(
    r'attachment; filename="([^"\\]*)"'
    r"(?:; filename\*=UTF-8''((?:[A-Za-z0-9!#$&+.^_`|~-]|%[0-9A-Fa-f]{2})+))?"
)
_UNSAFE_FILENAME_CHARS = frozenset('/\\"')


def _assert_safe_disposition(resp: httpx.Response) -> str:
    """One RFC 6266 attachment header, printable ASCII, whose filenames are safe."""
    raw = [v for k, v in resp.headers.raw if k.lower() == DISPOSITION.encode()]
    assert len(raw) == 1, f"expected one Content-Disposition header, got {len(raw)}"
    assert all(0x20 <= b <= 0x7E for b in raw[0]), "Content-Disposition holds a control or non-ASCII byte"
    match = _DISPOSITION_RE.fullmatch(raw[0].decode("ascii"))
    assert match, "Content-Disposition is not attachment; filename=\"...\" (RFC 6266)"
    names = [match.group(1)]
    if match.group(2):
        names.append(unquote(match.group(2), errors="strict"))
    for name in names:
        assert name.startswith("analysis-") and name.endswith(".json"), "filename lost its analysis-*.json shape"
        bad = [
            f"U+{ord(ch):04X}"
            for ch in name
            if ch in _UNSAFE_FILENAME_CHARS or unicodedata.category(ch) in HOSTILE_CATEGORIES + ("Cs",)
        ]
        assert bad == [], f"unsafe characters in the filename: {bad}"
    return raw[0].decode("ascii")


def _alias_404(c: TestClient) -> httpx.Response:
    """The alias's answer for an ID that was never stored: the 404 shape to match."""
    resp = c.get(_path(ALIAS, str(uuid4())))
    assert resp.status_code == 404, resp.text
    return resp


def _router_404(c: TestClient, ident: str) -> httpx.Response:
    """The router's answer for a path no route matches (an extra path segment)."""
    resp = c.get(f"/exports/analysis/{ident}/json")
    assert resp.status_code == 404, resp.text
    return resp


def _insert_with_id(db: Any, ident: str) -> AnalysisModel:
    """A stored analysis whose primary key is ``ident`` (IDs are free-form strings)."""
    row = _insert_analysis(db)
    row.id = ident
    db.commit()
    db.refresh(row)
    return row


def _same_response(got: httpx.Response, want: httpx.Response) -> None:
    def shape(r: httpx.Response) -> tuple[int, str | None, str | None, bytes]:
        return (r.status_code, r.headers.get("content-type"), r.headers.get(DISPOSITION), r.content)

    assert shape(got) == shape(want)


# ---------------------------------------------------------------------------
# 1, 2: the .json route and the alias serve the F5.2 export, byte-identically
# ---------------------------------------------------------------------------


def test_export_json_route_returns_alias_response_for_stored_analysis(
    app_client: TestClient, db_session: Any
) -> None:
    # RED until the body carries schema_version (round 2: was exact equality).
    row = _insert_analysis(db_session, name="JSON Route Export")
    alias = app_client.get(_path(ALIAS, row.id))
    assert alias.status_code == 200
    _assert_export_of(alias, row)

    resp = app_client.get(_path(JSON_ROUTE, row.id))

    assert resp.status_code == 200, f".json export returned {resp.status_code}: {resp.text[:120]}"
    _same_response(resp, alias)


def test_export_schema_version_is_one_major_minor_constant() -> None:
    # RED until app.schemas defines the constant. The tests read the value from
    # there, so the contract version is stated once (F13).
    assert _schema_version()


@pytest.mark.parametrize("template", [pytest.param(ALIAS, id="alias"), pytest.param(JSON_ROUTE, id="json")])
def test_export_body_is_pretty_printed_utf8(app_client: TestClient, db_session: Any, template: str) -> None:
    # RED until the handler serves json.dumps(indent=2). Non-ASCII stored text
    # must survive either ensure_ascii choice.
    row = _insert_analysis(db_session, name=NON_ASCII_NAME, document_text=NON_ASCII_TEXT)
    resp = app_client.get(_path(template, row.id))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == JSON_CONTENT_TYPE
    _assert_pretty(resp)
    body = json.loads(resp.content.decode("utf-8"))
    assert (body["name"], body["document_text"]) == (NON_ASCII_NAME, NON_ASCII_TEXT)
    _assert_export_of(resp, row)


@pytest.mark.parametrize("template", [pytest.param(ALIAS, id="alias"), pytest.param(JSON_ROUTE, id="json")])
def test_export_is_an_attachment_named_after_the_analysis(
    app_client: TestClient, db_session: Any, template: str
) -> None:
    # RED until the handler sets Content-Disposition (PRD F5.2 technical note).
    row = _insert_analysis(db_session)
    resp = app_client.get(_path(template, row.id))
    assert resp.status_code == 200
    assert _assert_safe_disposition(resp) == f'attachment; filename="analysis-{row.id}.json"'


# Stored IDs that are valid (they export with 200 today) but would break or forge
# a header if copied into it raw. Path separators cannot be in an ID ([^/]+), and
# "." / ".." are dot-segments the client normalises away.
UNUSUAL_STORED_IDS: tuple[tuple[str, str], ...] = (
    ("dquote", 'a"b'),
    ("backslash", "a\\b"),
    ("param-forgery", 'a"; filename="evil.exe'),
    ("rfc5987-forgery", "x\"; filename*=UTF-8''evil.exe"),
    ("crlf-header-injection", "a\r\nSet-Cookie: x=1"),
    ("cr", "a\rb"),
    ("lf", "a\nb"),
    ("nul", "a\x00b"),
    ("tab", "a\tb"),
    ("del", "a\x7fb"),
    ("rlo-extension-spoof", "a‮nosj.exe"),
    ("line-separator", "a b"),
    ("latin-1", "café"),
    ("cjk", "東京"),
    ("astral", "a\U0001f600b"),
    # A literal "%" that must not be decoded into the filename. Starlette's
    # TestClient unquotes the path a second time, so "a%22b" would reach the
    # server as 'a"b' (the dquote row); "%zz" is no escape and survives both.
    ("percent-literal", "a%zz%b"),
    ("semicolon-space", "a; b"),
    ("leading-dot", ".a"),
    ("trailing-dot", "a."),
    ("long", "a" * 2_000),
)


def test_export_disposition_is_safe_for_unusual_ids(app_client: TestClient, db_session: Any) -> None:
    # RED until the header exists; then it must stay one safe RFC 6266 header for
    # every stored ID, on both routes, and never a 500.
    generated = [
        (f"U+{cp:04X}", f"a{chr(cp)}b")
        for cp in range(sys.maxunicode + 1)
        if unicodedata.category(chr(cp)) in HOSTILE_CATEGORIES
    ]
    assert {unicodedata.category(ident[1]) for _, ident in generated} == set(HOSTILE_CATEGORIES)
    # The table already names some a{c}b IDs (CR, LF, NUL, ...); store each ID once.
    named = {ident for _, ident in UNUSUAL_STORED_IDS}
    cases = UNUSUAL_STORED_IDS + tuple((label, ident) for label, ident in generated if ident not in named)
    assert len({ident for _, ident in cases}) == len(cases)
    rows = [(label, _insert_with_id(db_session, ident)) for label, ident in cases]

    wrong: list[tuple[str, str, str]] = []
    for label, row in rows:
        for template in (ALIAS, JSON_ROUTE):
            resp = app_client.get(_path(template, quote(row.id, safe="")))
            try:
                assert resp.status_code == 200, f"status {resp.status_code}"
                _assert_safe_disposition(resp)
                _assert_carries(resp, row)
            except AssertionError as exc:
                wrong.append((label, template, str(exc).splitlines()[0][:80]))
    assert wrong == [], f"{len(wrong)} of {2 * len(rows)} unusual-ID exports failed, first: {wrong[:5]}"


def test_export_json_route_is_registered_in_openapi() -> None:
    # Green (regression guard). The ruling registers the PRD path as a route, so it is served in the
    # OpenAPI document (and the README endpoint table check) rather than being a
    # suffix stripped inside the alias handler.
    paths = app.openapi()["paths"]
    assert JSON_ROUTE_TEMPLATE in paths, sorted(p for p in paths if p.startswith("/exports/"))
    assert "get" in paths[JSON_ROUTE_TEMPLATE]


def test_export_alias_still_returns_stored_analysis(app_client: TestClient, db_session: Any) -> None:
    # RED until the body carries schema_version (round 2: was exact equality with
    # the stored analysis). The alias keeps working and stays application/json.
    row = _insert_analysis(db_session, name="Alias Export")
    resp = app_client.get(_path(ALIAS, row.id))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == JSON_CONTENT_TYPE
    _assert_export_of(resp, row)


# ---------------------------------------------------------------------------
# 3: unknown ID
# ---------------------------------------------------------------------------


def test_export_json_unknown_id_404_matches_alias(app_client: TestClient) -> None:
    # Green (regression guard): the same 404 on both routes, no echoed ID, and the
    # error path is not pretty-printed and is not an attachment.
    unknown = str(uuid4())
    alias = app_client.get(_path(ALIAS, unknown))
    resp = app_client.get(_path(JSON_ROUTE, unknown))
    assert alias.status_code == 404
    _same_response(resp, alias)
    _assert_compact_error(resp)
    assert unknown not in resp.text


# ---------------------------------------------------------------------------
# 4: .pdf is not shadowed
# ---------------------------------------------------------------------------


def test_export_pdf_route_still_reaches_pdf_handler(app_client: TestClient, db_session: Any) -> None:
    # Green today (regression guard): neither the .json route nor the alias may
    # capture "<id>.pdf". reportlab is a hard requirement (requirements.txt), so
    # this never skips.
    row = _insert_analysis(db_session)
    resp = app_client.get(_path(PDF_ROUTE, row.id))
    assert resp.status_code == 200, resp.text[:120]
    assert resp.headers["content-type"] == PDF_CONTENT_TYPE
    assert resp.content[: len(PDF_MAGIC)] == PDF_MAGIC

    missing = app_client.get(_path(PDF_ROUTE, str(uuid4())))
    _same_response(missing, _alias_404(app_client))


# ---------------------------------------------------------------------------
# 5: extra dots and hostile IDs are deterministic and never 500
# ---------------------------------------------------------------------------

# (label, path template) -> the alias 404. Each row's expected route is in the label.
HOSTILE_SUFFIX_ROWS: tuple[tuple[str, str], ...] = (
    ("json-json->json-route-id-<id>.json", "{id}.json.json"),
    ("pdf-json->json-route-id-<id>.pdf", "{id}.pdf.json"),
    ("json-pdf->pdf-route-id-<id>.json", "{id}.json.pdf"),
    ("double-dot->json-route-id-<id>.", "{id}..json"),
    ("bare-suffix->alias-id-.json", ".json"),
    ("upper-ext->alias", "{id}.JSON"),
    ("mixed-ext->alias", "{id}.Json"),
    ("fullwidth-full-stop->alias", "{id}%EF%BC%8Ejson"),
    ("one-dot-leader->alias", "{id}%E2%80%A4json"),
    ("overlong-utf8-dot->alias", "{id}%C0%AEjson"),
    ("invalid-utf8->json-route", "{id}%FF.json"),
    ("nul-before-suffix->json-route", "{id}%00.json"),
    ("nul-after-suffix->alias", "{id}.json%00"),
    ("cr-after-suffix->alias", "{id}.json%0D"),
    ("crlf-after-suffix->alias", "{id}.json%0D%0A"),
    ("query-string->json-route-404-for-unknown", "{id}.json.json?analysis_id={id}"),
)


def _generated_hostile_vectors() -> tuple[dict[str, int], list[tuple[str, str]]]:
    """Every Cc/Cf/Zl/Zp code point and four lone surrogates, at three positions.

    The one excluded vector, LF after ``.json``, is the Starlette ``$`` case and is
    covered by the parity test below.
    """
    per_category: dict[str, int] = {c: 0 for c in HOSTILE_CATEGORIES + ("Cs",)}
    encoded: list[tuple[str, str]] = []
    for cp in range(sys.maxunicode + 1):
        category = unicodedata.category(chr(cp))
        if category in HOSTILE_CATEGORIES:
            encoded.append((f"U+{cp:04X}", quote(chr(cp), safe="")))
            per_category[category] += 1
    for cp in LONE_SURROGATES:
        encoded.append((f"U+{cp:04X}", quote(chr(cp).encode("utf-8", "surrogatepass"), safe="")))
        per_category["Cs"] += 1
    vectors: list[tuple[str, str]] = []
    for label, enc in encoded:
        vectors.append((f"{label}-before", "{id}" + enc + ".json"))
        vectors.append((f"{label}-inside", "{id}.js" + enc + "on"))
        if enc != "%0A":
            vectors.append((f"{label}-after", "{id}.json" + enc))
    return per_category, vectors


def test_export_json_hostile_ids_are_deterministic_404s(app_client: TestClient, db_session: Any) -> None:
    # Green today and after the fix: every row names an ID that is not stored, so
    # whichever route Starlette picks (named in the row label) answers with the
    # alias's 404, byte for byte. Never 500, never a PDF, never the raw ID echoed.
    row = _insert_analysis(db_session)
    want = _alias_404(app_client)
    _assert_compact_error(want)
    per_category, generated = _generated_hostile_vectors()
    assert all(per_category.values()), per_category
    assert len(generated) > MIN_GENERATED_VECTORS, (len(generated), per_category)
    rows = list(HOSTILE_SUFFIX_ROWS) + generated + [("huge-id", "a" * HUGE_ID_LEN + ".json")]

    wrong: list[tuple[str, int, str]] = []
    for label, template in rows:
        resp = app_client.get("/exports/analysis/" + template.format(id=row.id))
        same = (resp.status_code, resp.headers.get("content-type"), resp.headers.get(DISPOSITION), resp.content) == (
            want.status_code,
            want.headers.get("content-type"),
            None,
            want.content,
        )
        if not same:
            wrong.append((label, resp.status_code, resp.text[:60].replace(row.id, "<id>")))
    assert wrong == []


def test_export_json_encoded_slash_is_router_404(app_client: TestClient, db_session: Any) -> None:
    # Green today: %2F decodes to "/", which no export route accepts ([^/]+), so the
    # router answers, exactly as for any extra path segment.
    row = _insert_analysis(db_session)
    resp = app_client.get(f"/exports/analysis/{row.id}%2Fjson")
    _same_response(resp, _router_404(app_client, row.id))


def test_export_json_suffix_removes_exactly_one_extension(app_client: TestClient, db_session: Any) -> None:
    # Green (regression guard). Starlette's greedy [^/]+ hands "<u>.json" to the
    # .json route for "<u>.json.json"; a handler that strips ".json" repeatedly
    # would serve <u>. Row identity is checked by additivity (round 2: was exact
    # equality with the stored analysis).
    u = str(uuid4())
    plain = _insert_with_id(db_session, u)
    json_named = _insert_with_id(db_session, f"{u}.json")
    pdf_named = _insert_with_id(db_session, f"{u}.pdf")
    assert json.loads(plain.result_json) != json.loads(json_named.result_json)

    resp = app_client.get(f"/exports/analysis/{u}.json.json")
    assert resp.status_code == 200, resp.text[:120]
    _assert_carries(resp, json_named)

    resp = app_client.get(f"/exports/analysis/{u}.pdf.json")
    assert resp.status_code == 200, resp.text[:120]
    assert resp.headers["content-type"] != PDF_CONTENT_TYPE
    _assert_carries(resp, pdf_named)

    # Positive control (green today): the PDF route already strips exactly one.
    resp = app_client.get(f"/exports/analysis/{u}.json.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == PDF_CONTENT_TYPE


# Spellings the router treats as "<id>.<ext>" (percent-decoded dot, FastAPI's
# trailing-slash redirect, Starlette's "$" before one trailing LF).
EQUIVALENT_SPELLINGS = (
    pytest.param("{id}%2E{ext}", id="percent-encoded-dot"),
    pytest.param("{id}.{ext}/", id="trailing-slash-redirect"),
    pytest.param("{id}.{ext}%0A", id="trailing-lf-dollar-anchor"),
)


@pytest.mark.parametrize("template", EQUIVALENT_SPELLINGS)
def test_export_json_route_matches_like_pdf_route(
    app_client: TestClient, db_session: Any, template: str
) -> None:
    # Green (regression guard): each spelling reaches the PDF route, so the JSON
    # spelling must reach the .json route too. Parity, not a pin: if a later card
    # refuses one of these spellings for every route, both sides change together.
    row = _insert_analysis(db_session)
    alias = app_client.get(_path(ALIAS, row.id))
    pdf = app_client.get("/exports/analysis/" + template.format(id=row.id, ext="pdf"))
    resp = app_client.get("/exports/analysis/" + template.format(id=row.id, ext="json"))

    assert resp.status_code == pdf.status_code, (resp.status_code, pdf.status_code)
    if pdf.status_code == 200:
        assert pdf.headers["content-type"] == PDF_CONTENT_TYPE
        _same_response(resp, alias)


# ---------------------------------------------------------------------------
# 6: auth and rate limit apply to .json exactly as to the alias (#133)
# ---------------------------------------------------------------------------


def test_export_json_without_valid_key_matches_alias(railway: Any, db_override: Any) -> None:
    # Green today (regression guard). Known and unknown IDs alike get the 401, so
    # neither route is an existence oracle without a key.
    s = railway()
    row = _insert_analysis(db_override)
    bad_keys = ({}, {KEY_HEADER: secrets.token_hex(20)}, {KEY_HEADER: s.api_key[:-1]})
    with client_at(CLIENT_PEER) as c:
        for ident in (row.id, str(uuid4())):
            for headers in bad_keys:
                for template in (JSON_ROUTE, ALIAS, PDF_ROUTE):
                    resp = c.get(_path(template, ident), headers=headers)
                    assert resp.status_code == 401, (template, resp.status_code)
                    assert resp.json() == {"detail": UNAUTHORIZED_DETAIL}
                    _assert_compact_error(resp)


def test_export_json_with_valid_key_matches_alias(railway: Any, db_override: Any) -> None:
    # Green (regression guard): the deployed (railway, keyed) path the v2 UI uses.
    s = railway()
    row = _insert_analysis(db_override)
    with client_at(CLIENT_PEER) as c:
        alias = c.get(_path(ALIAS, row.id), headers={KEY_HEADER: s.api_key})
        resp = c.get(_path(JSON_ROUTE, row.id), headers={KEY_HEADER: s.api_key})
    assert alias.status_code == 200
    assert resp.status_code == 200, resp.text[:120]
    _same_response(resp, alias)


@pytest.mark.parametrize(
    ("drain", "probe"),
    [pytest.param(ALIAS, JSON_ROUTE, id="alias-drains-json"), pytest.param(JSON_ROUTE, ALIAS, id="json-drains-alias")],
)
def test_export_json_shares_pre_auth_limit_with_alias(
    railway: Any, db_override: Any, drain: str, probe: str
) -> None:
    # Green today (regression guard): one peer bucket covers both spellings, so
    # alternating between them buys no extra unauthenticated attempts.
    n = 4
    railway(rate_limit_pre_auth=rate(n))
    ident = str(uuid4())
    with client_at(UNTRUSTED_PEER) as c:
        codes = [c.get(_path(drain, ident)).status_code for _ in range(n)]
        last = c.get(_path(probe, ident))
    assert codes == [401] * n
    _assert_429(last, PERIOD_SECONDS["minute"])
    _assert_compact_error(last)


# ---------------------------------------------------------------------------
# 7: the URL the v2 UI builds resolves (AppTest, no Streamlit server)
# ---------------------------------------------------------------------------


class _Forwarded(NamedTuple):
    method: str
    path: str
    status: int
    content_type: str
    body: bytes


def _drive_v2_results(
    monkeypatch: pytest.MonkeyPatch, backend: TestClient, analysis_id: str, key: str
) -> tuple[AppTest, list[_Forwarded]]:
    """Render the v2 results view and send its HTTP calls to the real backend app."""
    base = "http://backend.invalid"
    monkeypatch.setenv("API_BASE_URL", base)
    monkeypatch.setenv(KEY_ENV, key)
    monkeypatch.delenv(HEADER_ENV, raising=False)
    forwarded: list[_Forwarded] = []

    def forward(self: Any, method: str, url: str, **kwargs: Any) -> requests.Response:
        parts = urlsplit(url)
        assert f"{parts.scheme}://{parts.netloc}" == base, "the UI called a host other than API_BASE"
        target = parts.path + (f"?{parts.query}" if parts.query else "")
        got = backend.request(method, target, headers=kwargs.get("headers"), params=kwargs.get("params"))
        forwarded.append(
            _Forwarded(method.upper(), parts.path, got.status_code, got.headers.get("content-type", ""), got.content)
        )
        out = requests.Response()
        out.status_code = got.status_code
        out._content = got.content
        out.headers.update(got.headers)
        out.url = url
        return out

    monkeypatch.setattr(requests.sessions.Session, "request", forward)
    at = AppTest.from_file(str(V2_PATH), default_timeout=APPTEST_TIMEOUT_S)
    at.session_state["view"] = "results"
    at.session_state["analysis_result"] = {**_results_state(), "id": analysis_id}
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at, forwarded


def test_v2_ui_export_urls_resolve_to_backend_routes(
    monkeypatch: pytest.MonkeyPatch, railway: Any, db_override: Any, fake_context: None
) -> None:
    # RED until the export is pretty-printed: the UI must be driven with, and
    # offer for download, the indented F5.2 body without a warning.
    s = railway()
    row = _insert_analysis(db_override)
    with client_at(CLIENT_PEER) as backend:
        alias = backend.get(_path(ALIAS, row.id), headers={KEY_HEADER: s.api_key})
        at, calls = _drive_v2_results(monkeypatch, backend, row.id, s.api_key)
    exports = [f for f in calls if f.path.startswith("/exports/")]
    assert exports, "the v2 results view made no export call (export bar not wired)"
    unresolved = sorted({(f.path.replace(row.id, "<id>"), f.status) for f in exports if f.status != 200})
    assert unresolved == [], f"export URLs the v2 UI builds do not resolve: {unresolved}"
    json_exports = [f.body for f in exports if f.content_type == JSON_CONTENT_TYPE]
    assert json_exports == [alias.content]
    _assert_pretty(alias)
    assert [w.value for w in at.warning] == [], "the export bar showed a warning"
    # The media URL suffix comes from the button's mime type.
    json_buttons = [b for b in at.get("download_button") if b.proto.url.endswith(".json")]
    assert len(json_buttons) == len(json_exports), "the JSON export did not become a download button"


def test_v2_ui_pdf_export_url_resolves_to_pdf_route(
    monkeypatch: pytest.MonkeyPatch, railway: Any, db_override: Any, fake_context: None
) -> None:
    # Green today (positive control for the harness above): the PDF button works.
    s = railway()
    row = _insert_analysis(db_override)
    with client_at(CLIENT_PEER) as backend:
        _, calls = _drive_v2_results(monkeypatch, backend, row.id, s.api_key)
    pdfs = [f for f in calls if f.content_type == PDF_CONTENT_TYPE]
    assert [(f.status, f.body[: len(PDF_MAGIC)]) for f in pdfs] == [(200, PDF_MAGIC)]
