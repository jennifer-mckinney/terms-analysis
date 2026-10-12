"""Acceptance tests for #36 (GAP-002): ``GET /exports/analysis/{analysis_id}.json``.

Owner ruling (2026-10-12), "Add .json, keep alias":

* ``GET /exports/analysis/{analysis_id}.json`` is the PRD 7.3.11 (F5.2) contract;
* the extensionless ``GET /exports/analysis/{analysis_id}`` stays as an alias that
  returns the same response;
* ``GET /exports/analysis/{analysis_id}.pdf`` keeps working and is never shadowed.

Why it is broken today: the v2 UI requests ``<id>.json``, which matches only the
extensionless route, with ``analysis_id="<id>.json"``, so the lookup 404s.

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

Red today (fail because the ``.json`` route does not exist): the ``.json`` export
body, the OpenAPI registration, the equivalent-spelling parity, the one-suffix
rule, the authenticated ``.json`` export, and the v2 UI JSON export contract.
Green today (regression guards): the alias, the unknown-ID 404 shape (the alias
already answers ``<unknown>.json`` with the same 404), the PDF route, the hostile
ID table, auth and rate limit parity, and the v2 UI PDF export.
"""

# Fixtures imported from sibling test modules are requested by parameter name,
# which linters read as redefinitions of the import (F811).
# ruff: noqa: F811

from __future__ import annotations

import json
import secrets
import sys
import unicodedata
from typing import Any, NamedTuple
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
import pytest
import requests
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

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

KEY_HEADER = API_KEY_HEADER.decode("ascii")

# Hostile ID size: below httpx's 64 KiB URL cap so the request reaches the app.
HUGE_ID_LEN = 60_000

# Unicode categories whose code points can forge structure in a path segment
# (QUALITY-BAR R2). Cs (lone surrogates) cannot be UTF-8 encoded; they are sent
# as their surrogatepass bytes, which the server decodes as U+FFFD.
HOSTILE_CATEGORIES = ("Cc", "Cf", "Zl", "Zp")
LONE_SURROGATES = (0xD800, 0xDBFF, 0xDC00, 0xDFFF)


def _path(template: str, ident: str) -> str:
    return template.format(id=ident)


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
    assert (got.status_code, got.headers.get("content-type"), got.content) == (
        want.status_code,
        want.headers.get("content-type"),
        want.content,
    )


# ---------------------------------------------------------------------------
# 1, 2: the .json route returns what the alias returns
# ---------------------------------------------------------------------------


def test_export_json_route_returns_alias_response_for_stored_analysis(
    app_client: TestClient, db_session: Any
) -> None:
    # RED today: "<id>.json" is looked up as a literal ID by the alias and 404s.
    row = _insert_analysis(db_session, name="JSON Route Export")
    alias = app_client.get(_path(ALIAS, row.id))
    assert alias.status_code == 200
    assert alias.json() == json.loads(row.result_json)

    resp = app_client.get(_path(JSON_ROUTE, row.id))

    assert resp.status_code == 200, f".json export returned {resp.status_code}: {resp.text[:120]}"
    _same_response(resp, alias)


def test_export_json_route_is_registered_in_openapi() -> None:
    # RED today. The ruling registers the PRD path as a route, so it is served in the
    # OpenAPI document (and the README endpoint table check) rather than being a
    # suffix stripped inside the alias handler.
    paths = app.openapi()["paths"]
    assert JSON_ROUTE_TEMPLATE in paths, sorted(p for p in paths if p.startswith("/exports/"))
    assert "get" in paths[JSON_ROUTE_TEMPLATE]


def test_export_alias_still_returns_stored_analysis(app_client: TestClient, db_session: Any) -> None:
    # Green today (regression guard): the extensionless alias keeps working.
    row = _insert_analysis(db_session, name="Alias Export")
    resp = app_client.get(_path(ALIAS, row.id))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    assert resp.json() == json.loads(row.result_json)


# ---------------------------------------------------------------------------
# 3: unknown ID
# ---------------------------------------------------------------------------


def test_export_json_unknown_id_404_matches_alias(app_client: TestClient) -> None:
    # Green today: the alias already answers "<unknown>.json" with this 404. Guards
    # that the new route keeps the same shape (no new detail text, no echoed ID).
    unknown = str(uuid4())
    alias = app_client.get(_path(ALIAS, unknown))
    resp = app_client.get(_path(JSON_ROUTE, unknown))
    assert alias.status_code == 404
    _same_response(resp, alias)
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
    per_category, generated = _generated_hostile_vectors()
    assert all(per_category.values()), per_category
    rows = list(HOSTILE_SUFFIX_ROWS) + generated + [("huge-id", "a" * HUGE_ID_LEN + ".json")]
    print(f"hostile export vectors: {len(rows)} ({len(generated)} generated, per category {per_category})")

    wrong: list[tuple[str, int, str]] = []
    for label, template in rows:
        resp = app_client.get("/exports/analysis/" + template.format(id=row.id))
        same = (resp.status_code, resp.headers.get("content-type"), resp.content) == (
            want.status_code,
            want.headers.get("content-type"),
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
    # RED today. Starlette's greedy [^/]+ hands "<u>.json" to the .json route for
    # "<u>.json.json"; a handler that strips ".json" repeatedly would serve <u>.
    u = str(uuid4())
    plain = _insert_with_id(db_session, u)
    json_named = _insert_with_id(db_session, f"{u}.json")
    pdf_named = _insert_with_id(db_session, f"{u}.pdf")
    assert json.loads(plain.result_json) != json.loads(json_named.result_json)

    resp = app_client.get(f"/exports/analysis/{u}.json.json")
    assert resp.status_code == 200, resp.text[:120]
    assert resp.json() == json.loads(json_named.result_json)

    resp = app_client.get(f"/exports/analysis/{u}.pdf.json")
    assert resp.status_code == 200, resp.text[:120]
    assert resp.headers["content-type"] != PDF_CONTENT_TYPE
    assert resp.json() == json.loads(pdf_named.result_json)

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
    # RED today: each spelling already reaches the PDF route, but the JSON spelling
    # falls through to the alias as a literal ID. Parity, not a pin: if a later card
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


def test_export_json_with_valid_key_matches_alias(railway: Any, db_override: Any) -> None:
    # RED today: the deployed (railway, keyed) path the v2 UI uses.
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
) -> list[_Forwarded]:
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
    return forwarded


def test_v2_ui_export_urls_resolve_to_backend_routes(
    monkeypatch: pytest.MonkeyPatch, railway: Any, db_override: Any, fake_context: None
) -> None:
    # RED today: the v2 "Download JSON" call gets a 404 from the backend.
    s = railway()
    row = _insert_analysis(db_override)
    with client_at(CLIENT_PEER) as backend:
        alias = backend.get(_path(ALIAS, row.id), headers={KEY_HEADER: s.api_key})
        calls = _drive_v2_results(monkeypatch, backend, row.id, s.api_key)
    exports = [f for f in calls if f.path.startswith("/exports/")]
    assert exports, "the v2 results view made no export call (export bar not wired)"
    unresolved = sorted({(f.path.replace(row.id, "<id>"), f.status) for f in exports if f.status != 200})
    assert unresolved == [], f"export URLs the v2 UI builds do not resolve: {unresolved}"
    json_exports = [f.body for f in exports if f.content_type == alias.headers["content-type"]]
    assert json_exports == [alias.content]


def test_v2_ui_pdf_export_url_resolves_to_pdf_route(
    monkeypatch: pytest.MonkeyPatch, railway: Any, db_override: Any, fake_context: None
) -> None:
    # Green today (positive control for the harness above): the PDF button works.
    s = railway()
    row = _insert_analysis(db_override)
    with client_at(CLIENT_PEER) as backend:
        calls = _drive_v2_results(monkeypatch, backend, row.id, s.api_key)
    pdfs = [f for f in calls if f.content_type == PDF_CONTENT_TYPE]
    assert [(f.status, f.body[: len(PDF_MAGIC)]) for f in pdfs] == [(200, PDF_MAGIC)]
