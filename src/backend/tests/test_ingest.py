import asyncio

import httpx
import pytest

from app.services.ingest import extract_text_from_bytes, fetch_url_text


def test_extracts_html_text():
    html = b"<html><body><h1>Title</h1><p>Policy text here.</p></body></html>"
    text = extract_text_from_bytes("policy.html", "text/html", html)
    assert "Title" in text
    assert "Policy text here." in text


def test_extracts_rtf_text():
    rtf = b"{\\rtf1\\ansi This is \\b bold\\b0 text.}"
    text = extract_text_from_bytes("policy.rtf", "application/rtf", rtf)
    assert "This is" in text
    assert "bold" in text
    assert "text." in text


def _patch_transport(monkeypatch, handler):
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


def test_fetch_url_text_rejects_redirect_to_blocked_address(monkeypatch):
    """A public URL that 302s to a link-local/metadata address must not be followed."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "93.184.216.34":
            return httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
            )
        raise AssertionError(f"blocked redirect target was followed: {request.url}")

    _patch_transport(monkeypatch, handler)

    with pytest.raises(ValueError):
        asyncio.run(fetch_url_text("http://93.184.216.34/policy"))


def test_fetch_url_text_follows_redirect_to_allowed_address(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "93.184.216.34" and request.url.path == "/policy":
            return httpx.Response(302, headers={"location": "http://93.184.216.35/final"})
        if request.url.host == "93.184.216.35" and request.url.path == "/final":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"Final policy text.",
            )
        raise AssertionError(f"unexpected request: {request.url}")

    _patch_transport(monkeypatch, handler)

    text = asyncio.run(fetch_url_text("http://93.184.216.34/policy"))
    assert "Final policy text." in text


def test_fetch_url_text_caps_redirect_chain_length(monkeypatch):
    """An infinite redirect loop stops at the configured cap
    (``settings.url_fetch_max_redirects``) with an honest "too many
    redirects" error, after exactly cap + 1 requests (CodeQL py/full-ssrf)."""
    max_redirects = _setting("url_fetch_max_redirects")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://93.184.216.34/loop"})

    _patch_transport(monkeypatch, handler)

    err = _contract("UrlFetchError")
    with pytest.raises(err) as info:
        asyncio.run(fetch_url_text("http://93.184.216.34/loop"))
    assert info.value.reason == "redirects"
    assert len(seen) == max_redirects + 1


# ---------------------------------------------------------------------------
# SSRF-safe fetch contract (CodeQL alert #5, py/full-ssrf, ingest.fetch_url_text)
#
# Interface the implementation must provide (app.services.ingest):
#   UrlFetchError(ValueError)        .reason in FETCH_REASONS | UNSAFE_REASONS
#   UnsafeUrlError(UrlFetchError)    .reason in UNSAFE_REASONS (policy refusal)
#   fetch_url_text(url) -> str       reads limits from the module-level
#                                    ``settings`` at call time
# Config keys (app.config.Settings, validated at construction, fail closed):
#   url_fetch_allowed_schemes, url_fetch_blocked_networks,
#   url_fetch_max_redirects, url_fetch_max_bytes, url_fetch_timeout_s
# DNS goes through socket.getaddrinfo (faked here); the request handed to the
# transport is addressed to the validated IP literal, with the original
# hostname in the Host header and, for https, in extensions["sni_hostname"].
# No test in this block touches the real network.
# ---------------------------------------------------------------------------

import dataclasses
import ipaddress
import math
import socket
import time
import unicodedata

from app.config import Settings
from app.services import ingest

UNSAFE_REASONS = frozenset({"malformed", "scheme", "userinfo", "host", "address"})
FETCH_REASONS = frozenset({"redirects", "size", "timeout", "dns", "connect", "status"})

PUBLIC_V4 = "93.184.216.34"
PUBLIC_V4_B = "93.184.216.35"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"
LEAK = b"SSRF-LEAK"


def _contract(name):
    obj = getattr(ingest, name, None)
    if obj is None:
        pytest.fail(f"contract missing: app.services.ingest.{name} is not implemented")
    return obj


def _setting(name):
    if not hasattr(ingest.settings, name):
        pytest.fail(f"contract missing: config key Settings.{name} is not defined")
    return getattr(ingest.settings, name)


def _override(monkeypatch, **changes):
    """Override limits through the config object itself (never restate them)."""
    for key in changes:
        _setting(key)
    monkeypatch.setattr(ingest, "settings", dataclasses.replace(ingest.settings, **changes))


class FakeResolver:
    """Stands in for socket.getaddrinfo. ``table`` maps a lowercase ASCII
    hostname to a list of IP strings, or to a list of such lists consumed one
    per call (to model DNS rebinding)."""

    def __init__(self):
        self.table = {}
        self.calls = []
        self.delay = 0.0

    @staticmethod
    def _key(host):
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        host = str(host).rstrip(".").lower()
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            pass
        return host

    def __call__(self, host, port=None, *args, **kwargs):
        key = self._key(host)
        self.calls.append(key)
        if self.delay:
            time.sleep(self.delay)
        entry = self.table.get(key)
        if entry is None:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        if entry and isinstance(entry[0], list):
            answers = entry[min(self.calls.count(key), len(entry)) - 1]
        else:
            answers = entry
        out = []
        for ip in answers:
            if ":" in ip:
                out.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, port or 0, 0, 0)))
            else:
                out.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0)))
        return out


class FakeOrigin:
    """Records every request the fetcher sends. Unknown routes answer 200 with
    a LEAK marker so a fetch that should have been refused is visible."""

    def __init__(self):
        self.routes = {}
        self.requests = []

    async def handler(self, request):
        self.requests.append(request)
        route = self.routes.get((request.url.host, request.url.path))
        if route is None:
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=LEAK)
        result = route(request)
        if not isinstance(result, httpx.Response):
            result = await result
        return result


def _text(body=b"Policy text.", status=200, headers=None):
    hdrs = {"content-type": "text/plain"}
    hdrs.update(headers or {})
    return lambda request: httpx.Response(status, headers=hdrs, content=body)


def _redirect(location, status=302):
    return lambda request: httpx.Response(status, headers={"location": location})


@pytest.fixture(autouse=True)
def resolver(monkeypatch):
    fake = FakeResolver()
    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return fake


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    async def refuse(self, request):
        raise AssertionError(f"real network attempted: {request.url!r}")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)


@pytest.fixture
def origin(monkeypatch):
    fake = FakeOrigin()
    _patch_transport(monkeypatch, fake.handler)
    return fake


def _fetch(url):
    return asyncio.run(fetch_url_text(url))


def _expect(exc_name, reasons, url):
    err = _contract(exc_name)
    with pytest.raises(err) as info:
        _fetch(url)
    assert info.value.reason in reasons, f"{url!r}: reason {info.value.reason!r}"
    return info.value


def _assert_clean_message(exc, *hostile):
    msg = str(exc)
    assert msg and len(msg) <= 300, f"message length {len(msg)}"
    assert "Traceback" not in msg and "invalid literal" not in msg
    bad = [c for c in msg if unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"}]
    assert not bad, f"raw control/format characters in message: {bad!r}"
    for fragment in hostile:
        assert fragment not in msg, f"untrusted fragment echoed: {fragment!r}"


# ---- config: loaded through Settings, validated, fail closed ---------------

URL_FETCH_KEYS = (
    "url_fetch_allowed_schemes",
    "url_fetch_blocked_networks",
    "url_fetch_max_redirects",
    "url_fetch_max_bytes",
    "url_fetch_timeout_s",
)


def test_url_fetch_config_keys_load_and_are_well_formed():
    for key in URL_FETCH_KEYS:
        _setting(key)
    s = ingest.settings
    assert s.url_fetch_allowed_schemes and set(s.url_fetch_allowed_schemes) <= {"http", "https"}
    assert s.url_fetch_blocked_networks
    for net in s.url_fetch_blocked_networks:
        ipaddress.ip_network(net)
    assert isinstance(s.url_fetch_max_redirects, int) and s.url_fetch_max_redirects >= 0
    assert isinstance(s.url_fetch_max_bytes, int) and s.url_fetch_max_bytes >= 1
    assert math.isfinite(s.url_fetch_timeout_s) and s.url_fetch_timeout_s > 0


@pytest.mark.parametrize(
    "key,value",
    [
        ("url_fetch_max_redirects", -1),
        ("url_fetch_max_bytes", 0),
        ("url_fetch_max_bytes", -5),
        ("url_fetch_timeout_s", 0.0),
        ("url_fetch_timeout_s", -1.0),
        ("url_fetch_timeout_s", float("nan")),
        ("url_fetch_timeout_s", float("inf")),
        ("url_fetch_allowed_schemes", []),
        ("url_fetch_allowed_schemes", ["file"]),
        ("url_fetch_allowed_schemes", ["http", "gopher"]),
        ("url_fetch_blocked_networks", []),
        ("url_fetch_blocked_networks", ["not-a-cidr"]),
        ("url_fetch_blocked_networks", ["10.0.0.0/33"]),
    ],
)
def test_bad_url_fetch_config_fails_closed_at_load(key, value):
    _setting(key)
    with pytest.raises(ValueError):
        dataclasses.replace(ingest.settings, **{key: value})


@pytest.mark.parametrize(
    "key,value",
    [
        ("url_fetch_max_redirects", 0),
        ("url_fetch_max_bytes", 1),
        ("url_fetch_allowed_schemes", ["https"]),
        ("url_fetch_blocked_networks", ["10.0.0.0/8"]),
    ],
)
def test_good_url_fetch_config_overrides_load(key, value):
    _setting(key)
    replaced = dataclasses.replace(ingest.settings, **{key: value})
    assert isinstance(replaced, Settings)


def test_url_fetch_timeout_above_request_timeout_fails_closed():
    """config.py INVARIANT: url_fetch_timeout_s <= request_timeout_s (the
    fetch is the leading step of a URL analysis; the LLM budget gets the
    rest). Enforced at construction, from either side, at the boundary; a
    NaN LLM budget must not make the comparison silently pass."""
    _setting("url_fetch_timeout_s")
    _setting("request_timeout_s")
    s = ingest.settings
    limit = s.request_timeout_s
    # Boundary: equal is allowed (positive control).
    assert dataclasses.replace(s, url_fetch_timeout_s=limit).url_fetch_timeout_s == limit
    # One representable step above the LLM budget is refused.
    with pytest.raises(ValueError, match="request_timeout_s"):
        dataclasses.replace(s, url_fetch_timeout_s=math.nextafter(limit, math.inf))
    with pytest.raises(ValueError, match="request_timeout_s"):
        dataclasses.replace(s, url_fetch_timeout_s=limit * 2)
    # Lowering the LLM budget under the fetch deadline is refused too.
    with pytest.raises(ValueError, match="request_timeout_s"):
        dataclasses.replace(s, request_timeout_s=s.url_fetch_timeout_s / 2)
    with pytest.raises(ValueError, match="request_timeout_s"):
        dataclasses.replace(s, request_timeout_s=float("nan"))


# ---- scheme, userinfo, malformed -------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.test/x",
        "gopher://example.test:70/_GET",
        "data:text/plain,hello",
        "javascript:alert(1)",
        "dict://example.test:11211/stat",
        "ldap://example.test/",
        "jar:http://example.test/a.jar!/",
        "//example.test/x",
        "example.test/x",
        "",
    ],
)
def test_fetch_rejects_non_http_schemes(url, resolver, origin):
    resolver.table["example.test"] = [PUBLIC_V4]
    _expect("UnsafeUrlError", {"scheme"}, url)
    assert origin.requests == []


def test_fetch_honours_allowed_schemes_from_config(monkeypatch, origin):
    _override(monkeypatch, url_fetch_allowed_schemes=["https"])
    origin.routes[(PUBLIC_V4, "/p")] = _text()
    _expect("UnsafeUrlError", {"scheme"}, f"http://{PUBLIC_V4}/p")
    assert origin.requests == []
    assert _fetch(f"https://{PUBLIC_V4}/p") == "Policy text."


@pytest.mark.parametrize(
    "url,reasons",
    [
        ("http://user@example.test/", {"userinfo"}),
        ("http://user:pass@example.test/", {"userinfo"}),
        ("http://@example.test/", {"userinfo"}),
        ("http://:@example.test/", {"userinfo"}),
        ("http://example.test@169.254.169.254/", {"userinfo"}),
        ("http://example.test\\@169.254.169.254/", {"userinfo", "malformed"}),
        ("http://example.test%40169.254.169.254/", {"userinfo", "host", "malformed"}),
    ],
)
def test_fetch_rejects_userinfo(url, reasons, resolver, origin):
    resolver.table["example.test"] = [PUBLIC_V4]
    _expect("UnsafeUrlError", reasons, url)
    assert origin.requests == []


def _generated_hostile_chars():
    chars = [
        chr(cp)
        for cp in range(0x110000)
        if unicodedata.category(chr(cp)) in {"Cc", "Cf", "Zl", "Zp"}
    ]
    chars += ["\ud800", "\udbff", "\udc00", "\udfff"]  # lone surrogates (Cs)
    return chars


def test_fetch_rejects_control_format_and_surrogate_chars_anywhere(resolver, origin):
    """Generated over every Cc/Cf/Zl/Zp code point plus lone surrogates, in the
    host and in the path. urlparse silently strips TAB/CR/LF, so the check must
    run on the raw string."""
    resolver.table["example.test"] = [PUBLIC_V4]
    err = _contract("UnsafeUrlError")
    chars = _generated_hostile_chars()
    failures = []

    async def run_all():
        for ch in chars:
            for url in (f"http://exa{ch}mple.test/p", f"http://example.test/p{ch}q"):
                try:
                    await fetch_url_text(url)
                    failures.append((url, "accepted"))
                except err as exc:
                    if exc.reason != "malformed":
                        failures.append((url, exc.reason))
                except Exception as exc:  # wrong type is a failure, not a crash
                    failures.append((url, type(exc).__name__))

    asyncio.run(run_all())
    print(f"generated hostile URLs: {len(chars) * 2}")
    assert not failures, f"{len(failures)} not refused as malformed, first: {failures[:5]!r}"
    assert origin.requests == []


@pytest.mark.parametrize("space", [chr(cp) for cp in range(0x110000) if unicodedata.category(chr(cp)) == "Zs"])
def test_fetch_rejects_space_separators_in_host(space, resolver, origin):
    resolver.table["example.test"] = [PUBLIC_V4]
    _expect("UnsafeUrlError", {"malformed", "host"}, f"http://exa{space}mple.test/")
    assert origin.requests == []


# ---- addresses ---------------------------------------------------------------

BLOCKED_IPS = [
    "127.0.0.1",
    "127.255.255.254",
    "10.0.0.1",
    "10.255.255.255",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.0.1",
    "192.168.255.255",
    "169.254.169.254",
    "169.254.0.1",
    "100.64.0.1",
    "100.127.255.254",
    "0.0.0.0",
    "0.1.2.3",
    "224.0.0.1",
    "255.255.255.255",
    "::1",
    "::",
    "fc00::1",
    "fd00::1",
    "fd12:3456:789a::1",
    "fe80::1",
    "::ffff:127.0.0.1",
    "::ffff:169.254.169.254",
    "::ffff:10.0.0.1",
    "::ffff:7f00:1",
    "::127.0.0.1",
    "64:ff9b::7f00:1",
    "2002:7f00:1::1",
    "2002:a9fe:a9fe::1",
]


def _literal(ip):
    return f"[{ip}]" if ":" in ip else ip


@pytest.mark.parametrize("ip", BLOCKED_IPS)
def test_fetch_rejects_blocked_ip_literal(ip, origin):
    _expect("UnsafeUrlError", {"address"}, f"http://{_literal(ip)}/latest/meta-data/")
    assert origin.requests == []


@pytest.mark.parametrize("ip", BLOCKED_IPS)
def test_fetch_rejects_hostname_resolving_to_blocked_ip(ip, resolver, origin):
    resolver.table["internal.test"] = [ip]
    _expect("UnsafeUrlError", {"address"}, "http://internal.test/")
    assert origin.requests == []


def test_fetch_rejects_when_any_of_many_answers_is_blocked(resolver, origin):
    many = [str(ipaddress.ip_address(PUBLIC_V4) + i) for i in range(1000)]
    resolver.table["mixed.test"] = many + ["10.0.0.5"]
    _expect("UnsafeUrlError", {"address"}, "http://mixed.test/")
    assert origin.requests == []


def test_fetch_rejects_host_with_no_answers_as_dns_failure(resolver, origin):
    resolver.table["empty.test"] = []
    exc = _expect("UrlFetchError", {"dns"}, "http://empty.test/")
    assert not isinstance(exc, _contract("UnsafeUrlError"))
    assert origin.requests == []


def test_fetch_unknown_host_is_dns_failure_not_a_crash(origin):
    exc = _expect("UrlFetchError", {"dns"}, "http://no-such-host.test/")
    _assert_clean_message(exc, "no-such-host.test")
    assert origin.requests == []


@pytest.mark.parametrize(
    "host",
    [
        "2130706433",
        "0x7f000001",
        "0X7F000001",
        "017700000001",
        "0177.0.0.1",
        "0177.0000.0000.0001",
        "0x7f.0.0.1",
        "0x7f.0x0.0x0.0x1",
        "127.1",
        "127.0.1",
        "0",
        "0x0",
        "3232235777",
        "2852039166",
        "0xa9fea9fe",
        "0251.0376.0251.0376",
        "169.254.43518",
        "127.0.0.1.",
    ],
)
def test_fetch_rejects_numeric_host_encodings(host, resolver, origin):
    """Non-canonical numeric hosts are refused by syntax. The fake resolver
    answers PUBLIC for them, so only a syntactic check can catch them."""
    resolver.table[host.rstrip(".").lower()] = [PUBLIC_V4]
    _expect("UnsafeUrlError", {"host", "address"}, f"http://{host}/")
    assert origin.requests == []


@pytest.mark.parametrize(
    "host",
    [
        "１２７.０.０.１",  # fullwidth digits -> 127.0.0.1
        "169。254。169。254",  # ideographic full stops
        "169．254．169．254",  # fullwidth full stops
        "①②⑦.0.0.1",  # circled digits
        "%31%32%37.0.0.1",  # percent-encoded host
        "127.0.0.1%00.example.test",
        "a" * 64 + ".test",  # label over 63 octets
        ".".join(["a" * 63] * 4) + ".test",  # name over 253 octets
        # Short id: the raw value would make a ~2 MB node id and a 2 MB line
        # in the CI -v log.
        pytest.param("a" * 2_000_000 + ".test", id="2MB-host"),
    ],
)
def test_fetch_rejects_lookalike_encoded_and_oversized_hosts(host, resolver, origin):
    exc = _expect("UnsafeUrlError", {"host", "address", "malformed"}, f"http://{host}/")
    _assert_clean_message(exc, host[:40] if len(host) > 40 else host)
    assert origin.requests == []


def test_blocked_networks_are_read_from_config(monkeypatch, origin):
    origin.routes[(PUBLIC_V4, "/p")] = _text()
    assert _fetch(f"http://{PUBLIC_V4}/p") == "Policy text."
    extra = list(_setting("url_fetch_blocked_networks")) + ["93.184.216.0/24"]
    _override(monkeypatch, url_fetch_blocked_networks=extra)
    _expect("UnsafeUrlError", {"address"}, f"http://{PUBLIC_V4}/p")
    assert len(origin.requests) == 1


def test_every_configured_blocked_network_is_enforced(origin):
    nets = [ipaddress.ip_network(n) for n in _setting("url_fetch_blocked_networks")]
    err = _contract("UnsafeUrlError")
    escaped = []
    for net in nets:
        for ip in (net.network_address, net.broadcast_address):
            try:
                _fetch(f"http://{_literal(str(ip))}/")
                escaped.append(str(ip))
            except err as exc:
                if exc.reason != "address":
                    escaped.append(f"{ip}:{exc.reason}")
    assert not escaped, escaped
    assert origin.requests == []


# ---- positive controls + IP pinning (DNS rebinding) --------------------------

@pytest.mark.parametrize(
    "url,host_header,pinned_ip,path",
    [
        (f"http://{PUBLIC_V4}/terms", PUBLIC_V4, PUBLIC_V4, "/terms"),
        (f"http://[{PUBLIC_V6}]/terms", f"[{PUBLIC_V6}]", PUBLIC_V6, "/terms"),
        ("http://example.test/terms", "example.test", PUBLIC_V4, "/terms"),
        ("HTTP://Example.TEST/terms", "example.test", PUBLIC_V4, "/terms"),
        ("http://0x7f.example.test/terms", "0x7f.example.test", PUBLIC_V4, "/terms"),
        ("http://bücher.example/terms", "xn--bcher-kva.example", PUBLIC_V4, "/terms"),
        ("https://example.test:8443/terms", "example.test:8443", PUBLIC_V4, "/terms"),
    ],
)
def test_public_url_is_fetched_and_pinned_to_checked_ip(url, host_header, pinned_ip, path, resolver, origin):
    for name in ("example.test", "0x7f.example.test", "xn--bcher-kva.example"):
        resolver.table[name] = [PUBLIC_V4]
    origin.routes[(pinned_ip, path)] = _text()
    assert _fetch(url) == "Policy text."
    assert len(origin.requests) == 1
    sent = origin.requests[0]
    assert sent.url.host == pinned_ip
    assert sent.headers["host"].lower() == host_header.lower()


def test_dns_rebinding_cannot_swap_the_checked_ip(resolver, origin):
    """First answer is public, every later answer is loopback. The request
    must go to the IP that was checked, never to a second lookup's answer."""
    resolver.table["rebind.test"] = [[PUBLIC_V4], ["127.0.0.1"]]
    origin.routes[(PUBLIC_V4, "/policy")] = _text()
    assert _fetch("http://rebind.test/policy") == "Policy text."
    assert [r.url.host for r in origin.requests] == [PUBLIC_V4]
    assert origin.requests[0].headers["host"] == "rebind.test"


def _refuse_connect(request):
    raise httpx.ConnectError("connection refused to 10.9.8.7", request=request)


@pytest.mark.parametrize(
    "answers",
    [
        pytest.param([PUBLIC_V4, PUBLIC_V4_B], id="v4-then-v4"),
        pytest.param([PUBLIC_V6, PUBLIC_V4], id="v6-then-v4"),
    ],
)
def test_connect_failure_falls_back_to_the_next_checked_address(answers, resolver, origin):
    """Every resolved address passed the blocklist, so a connect failure on
    the first must fall back to the next one: still pinned to a checked IP,
    still carrying the original Host header, and with no second lookup (a
    re-resolution would reopen DNS rebinding)."""
    first, second = answers
    resolver.table["multi.test"] = answers
    origin.routes[(first, "/p")] = _refuse_connect
    origin.routes[(second, "/p")] = _text()
    try:
        text = _fetch("http://multi.test/p")
    except _contract("UrlFetchError") as exc:
        pytest.fail(
            f"no fallback to the second checked address: reason {exc.reason!r}, "
            f"hosts tried {[r.url.host for r in origin.requests]!r}"
        )
    assert text == "Policy text."
    assert [r.url.host for r in origin.requests] == [first, second]
    assert origin.requests[-1].headers["host"] == "multi.test"
    assert resolver.calls == ["multi.test"]


def test_redirect_reuses_the_address_that_connected_not_the_first_answer(resolver, origin):
    """The pin is the address that actually connected. First answer refuses
    every connect, the second connects and redirects to the same host, and a
    second lookup would rebind to loopback. The redirect hop must go to the
    second (connected) address, with one lookup and no other address tried."""
    first, second = PUBLIC_V4, PUBLIC_V4_B
    resolver.table["multi.test"] = [[first, second], ["127.0.0.1"]]
    origin.routes[(first, "/start")] = _refuse_connect
    origin.routes[(first, "/final")] = _refuse_connect
    origin.routes[(second, "/start")] = _redirect("/final")
    origin.routes[(second, "/final")] = _text(b"Final policy text.")
    try:
        text = _fetch("http://multi.test/start")
    except (_contract("UrlFetchError"), _contract("UnsafeUrlError")) as exc:
        pytest.fail(
            f"redirect hop not sent to the connected address: reason {exc.reason!r}, "
            f"tried {[(r.url.host, r.url.path) for r in origin.requests]!r}, "
            f"lookups {resolver.calls!r}"
        )
    assert text == "Final policy text."
    assert [(r.url.host, r.url.path) for r in origin.requests] == [
        (first, "/start"),
        (second, "/start"),
        (second, "/final"),
    ]
    assert origin.requests[-1].headers["host"] == "multi.test"
    assert resolver.calls == ["multi.test"]


@pytest.mark.parametrize(
    "error",
    [httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError, httpx.WriteError],
    ids=lambda e: e.__name__,
)
def test_only_a_connect_error_falls_back_to_the_next_address(error, resolver, origin):
    """A failure after the connection exists (read, write, protocol) is not a
    reason to try another address: the hop fails once, as a clean connect
    error, and the second checked address is never contacted."""
    first, second = PUBLIC_V4, PUBLIC_V4_B
    resolver.table["multi.test"] = [first, second]

    def fail_after_connect(request):
        raise error("broken stream from 10.9.8.7", request=request)

    origin.routes[(first, "/p")] = fail_after_connect
    origin.routes[(second, "/p")] = _text(LEAK)
    exc = _expect("UrlFetchError", {"connect"}, "http://multi.test/p")
    assert not isinstance(exc, _contract("UnsafeUrlError"))
    assert [r.url.host for r in origin.requests] == [first]
    assert resolver.calls == ["multi.test"]
    _assert_clean_message(exc, "10.9.8.7", "multi.test", "broken stream")


def test_connect_failure_on_every_address_is_one_clean_connect_error(resolver, origin):
    """Fallback still fails closed: when every checked address refuses, each
    is tried once, in order, and the outcome is a clean connect error."""
    answers = [PUBLIC_V4, PUBLIC_V4_B]
    resolver.table["multi.test"] = answers
    for ip in answers:
        origin.routes[(ip, "/p")] = _refuse_connect
    exc = _expect("UrlFetchError", {"connect"}, "http://multi.test/p")
    assert not isinstance(exc, _contract("UnsafeUrlError"))
    assert [r.url.host for r in origin.requests] == answers
    _assert_clean_message(exc, "10.9.8.7", "multi.test")


def test_connect_fallback_over_many_answers_stays_inside_the_deadline(short_deadline, resolver, origin):
    """Hostile size: 1000 public answers that all refuse. Fallback must not
    turn into an unbounded loop; the total deadline (or exhaustion) ends it
    with a typed error well inside the outer budget."""
    many = [str(ipaddress.ip_address(PUBLIC_V4) + i) for i in range(1000)]
    resolver.table["many.test"] = many
    for ip in many:
        origin.routes[(ip, "/p")] = _refuse_connect
    exc, elapsed = _timed("http://many.test/p", short_deadline + 2.0)
    assert isinstance(exc, _contract("UrlFetchError")) and exc.reason in {"connect", "timeout"}, exc
    assert elapsed < short_deadline + 1.5
    assert all(r.url.host in many for r in origin.requests)


@pytest.mark.parametrize(
    "answers",
    [
        pytest.param([PUBLIC_V4, "10.0.0.1"], id="public-then-private"),
        pytest.param(["10.0.0.1", PUBLIC_V4], id="private-then-public"),
        pytest.param([PUBLIC_V4, PUBLIC_V4_B, "::ffff:169.254.169.254"], id="mapped-metadata-last"),
    ],
)
def test_private_answer_anywhere_refuses_before_any_connect(answers, resolver, origin):
    """Inverse of the fallback: one blocked answer anywhere in the set refuses
    the whole host before any connect attempt, even when the first answer is
    public and refuses to connect (a fallback must never reach the private one)."""
    resolver.table["multi.test"] = answers
    for ip in answers:
        origin.routes[(ip, "/p")] = _refuse_connect
    exc = _expect("UnsafeUrlError", {"address"}, "http://multi.test/p")
    assert origin.requests == []
    _assert_clean_message(exc, "10.0.0.1", "169.254", "multi.test")


def test_https_pin_keeps_hostname_for_sni_and_cert_check(resolver, origin):
    resolver.table["secure.test"] = [PUBLIC_V4]
    origin.routes[(PUBLIC_V4, "/p")] = _text()
    assert _fetch("https://secure.test/p") == "Policy text."
    sent = origin.requests[0]
    assert sent.url.scheme == "https" and sent.url.host == PUBLIC_V4
    assert sent.extensions.get("sni_hostname") == "secure.test"
    assert sent.headers["host"] == "secure.test"


# ---- redirects ---------------------------------------------------------------

REDIRECT_TARGETS = [
    ("http://169.254.169.254/latest/meta-data/", "UnsafeUrlError", {"address"}),
    ("http://internal.test/admin", "UnsafeUrlError", {"address"}),
    ("http://[::ffff:127.0.0.1]/", "UnsafeUrlError", {"address"}),
    ("file:///etc/passwd", "UnsafeUrlError", {"scheme"}),
    ("gopher://example.test/_x", "UnsafeUrlError", {"scheme"}),
    ("http://user@example.test/", "UnsafeUrlError", {"userinfo"}),
    ("http://2130706433/", "UnsafeUrlError", {"host", "address"}),
    ("//169.254.169.254/x", "UnsafeUrlError", {"address"}),
    # httpx itself refuses a Location with a raw LF (RemoteProtocolError)
    # before the fetcher sees it, so only "refused, cleanly" is pinned here.
    ("http://exa\nmple.test/", "UrlFetchError", {"malformed", "redirects", "connect"}),
]


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("target,exc_name,reasons", REDIRECT_TARGETS)
def test_every_redirect_hop_is_revalidated(status, target, exc_name, reasons, resolver, origin):
    resolver.table["example.test"] = [PUBLIC_V4]
    resolver.table["internal.test"] = ["10.0.0.5"]
    resolver.table["2130706433"] = [PUBLIC_V4]
    origin.routes[(PUBLIC_V4, "/start")] = _redirect(target, status)
    exc = _expect(exc_name, reasons, "http://example.test/start")
    assert len(origin.requests) == 1
    _assert_clean_message(exc, "169.254", "10.0.0.5", "internal.test", "/etc/passwd")


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("location", ["/final", "http://example.test/final"], ids=["relative", "absolute-same-host"])
def test_relative_redirect_keeps_original_host_and_pin(status, location, resolver, origin):
    """A same-host redirect reuses the pinned address and never re-resolves:
    the resolver rebinds to loopback on any second lookup (DNS rebinding)."""
    resolver.table["example.test"] = [[PUBLIC_V4], ["127.0.0.1"]]
    origin.routes[(PUBLIC_V4, "/start")] = _redirect(location, status)
    origin.routes[(PUBLIC_V4, "/final")] = _text(b"Final policy text.")
    assert _fetch("http://example.test/start") == "Final policy text."
    assert resolver.calls == ["example.test"]
    assert [r.url.host for r in origin.requests] == [PUBLIC_V4, PUBLIC_V4]
    final = origin.requests[-1]
    assert (final.url.host, final.url.path, final.headers["host"]) == (PUBLIC_V4, "/final", "example.test")


def test_cross_host_redirect_is_resolved_and_pinned_separately(resolver, origin):
    resolver.table["example.test"] = [PUBLIC_V4]
    resolver.table["other.test"] = [[PUBLIC_V4_B], ["127.0.0.1"]]
    origin.routes[(PUBLIC_V4, "/start")] = _redirect("https://other.test/final")
    origin.routes[(PUBLIC_V4_B, "/final")] = _text(b"Other policy.")
    assert _fetch("http://example.test/start") == "Other policy."
    final = origin.requests[-1]
    assert final.url.host == PUBLIC_V4_B
    assert final.headers["host"] == "other.test"
    assert final.extensions.get("sni_hostname") == "other.test"


def _chain(origin, hops):
    for i in range(hops):
        origin.routes[(PUBLIC_V4, f"/r{i}")] = _redirect(f"/r{i + 1}")
    origin.routes[(PUBLIC_V4, f"/r{hops}")] = _text(b"End of chain.")


def test_redirect_chain_exactly_at_cap_succeeds(origin):
    cap = _setting("url_fetch_max_redirects")
    _chain(origin, cap)
    assert _fetch(f"http://{PUBLIC_V4}/r0") == "End of chain."
    assert len(origin.requests) == cap + 1


def test_redirect_chain_one_over_cap_fails(origin):
    cap = _setting("url_fetch_max_redirects")
    _chain(origin, cap + 1)
    exc = _expect("UrlFetchError", {"redirects"}, f"http://{PUBLIC_V4}/r0")
    assert len(origin.requests) == cap + 1
    _assert_clean_message(exc)


def test_redirect_cap_zero_from_config_refuses_first_redirect(monkeypatch, origin):
    _override(monkeypatch, url_fetch_max_redirects=0)
    _chain(origin, 1)
    _expect("UrlFetchError", {"redirects"}, f"http://{PUBLIC_V4}/r0")
    assert len(origin.requests) == 1


def test_redirect_without_location_is_an_error(origin):
    origin.routes[(PUBLIC_V4, "/p")] = lambda request: httpx.Response(302)
    _expect("UrlFetchError", {"redirects"}, f"http://{PUBLIC_V4}/p")


# ---- size --------------------------------------------------------------------

class _CountingBody:
    def __init__(self, total, chunk=16, delay=0.0):
        self.total, self.chunk, self.delay, self.pulled = total, chunk, delay, 0

    async def __aiter__(self):
        while self.pulled < self.total:
            # Always yield to the loop, as a real socket read would, so a
            # missing cap fails on the deadline instead of spinning forever.
            await asyncio.sleep(self.delay)
            n = min(self.chunk, self.total - self.pulled)
            self.pulled += n
            yield b"x" * n


@pytest.fixture
def small_cap(monkeypatch):
    _override(monkeypatch, url_fetch_max_bytes=64)
    return 64


def test_body_exactly_at_size_cap_is_accepted(small_cap, origin):
    origin.routes[(PUBLIC_V4, "/p")] = _text(b"y" * small_cap)
    assert _fetch(f"http://{PUBLIC_V4}/p") == "y" * small_cap


def test_body_one_byte_over_size_cap_is_rejected(small_cap, origin):
    origin.routes[(PUBLIC_V4, "/p")] = _text(b"y" * (small_cap + 1))
    exc = _expect("UrlFetchError", {"size"}, f"http://{PUBLIC_V4}/p")
    _assert_clean_message(exc)


def test_declared_oversize_is_rejected_before_reading_body(small_cap, origin):
    body = _CountingBody(small_cap * 1000)
    origin.routes[(PUBLIC_V4, "/p")] = lambda request: httpx.Response(
        200, headers={"content-length": str(small_cap * 1000)}, content=body
    )
    _expect("UrlFetchError", {"size"}, f"http://{PUBLIC_V4}/p")
    assert body.pulled == 0


def test_undeclared_stream_is_cut_off_at_cap(small_cap, origin):
    body = _CountingBody(small_cap * 10_000, chunk=16)  # finite, so a missing cap returns instead of hanging
    origin.routes[(PUBLIC_V4, "/p")] = lambda request: httpx.Response(200, content=body)
    _expect("UrlFetchError", {"size"}, f"http://{PUBLIC_V4}/p")
    assert body.pulled <= small_cap + body.chunk


@pytest.mark.parametrize("value", ["abc", "-1", "1e3", "0x40", "1, 2", "99999999999999999999999999"])
def test_invalid_or_absurd_content_length_is_a_clean_error(value, small_cap, origin):
    origin.routes[(PUBLIC_V4, "/p")] = _text(b"ok", headers={"content-length": value})
    exc = _expect("UrlFetchError", {"size"}, f"http://{PUBLIC_V4}/p")
    _assert_clean_message(exc, value)


@pytest.mark.parametrize(
    "zeros",
    [
        pytest.param(8, id="8-leading-zeros"),
        pytest.param(10_000, id="10k-leading-zeros"),
    ],
)
@pytest.mark.parametrize("size", ["one-byte", "at-cap"])
def test_content_length_with_leading_zeros_is_read_by_value(zeros, size, small_cap, origin):
    """Content-Length is 1*DIGIT (RFC 9110): leading zeros do not change the
    value, so "00000001" is 1 byte, not "more digits than the cap". The 10k
    form also proves the value is never int()-ed raw (CPython refuses int()
    of a string over 4300 digits)."""
    n = 1 if size == "one-byte" else small_cap
    value = "0" * zeros + str(n)
    assert len(value) > len(str(small_cap))  # the digit-count shortcut would refuse it
    body = b"y" * n
    origin.routes[(PUBLIC_V4, "/p")] = _text(body, headers={"content-length": value})
    try:
        text = _fetch(f"http://{PUBLIC_V4}/p")
    except _contract("UrlFetchError") as exc:
        pytest.fail(f"declared length {n} with leading zeros refused: reason {exc.reason!r}")
    assert text == body.decode()


@pytest.mark.parametrize("zeros", [8, 10_000], ids=["8-leading-zeros", "10k-leading-zeros"])
def test_content_length_with_leading_zeros_over_cap_is_still_refused(zeros, small_cap, origin):
    body = _CountingBody(small_cap + 1)
    value = "0" * zeros + str(small_cap + 1)
    origin.routes[(PUBLIC_V4, "/p")] = lambda request: httpx.Response(
        200, headers={"content-length": value}, content=body
    )
    exc = _expect("UrlFetchError", {"size"}, f"http://{PUBLIC_V4}/p")
    assert body.pulled == 0
    _assert_clean_message(exc, value[-40:])


# ---- time --------------------------------------------------------------------

@pytest.fixture
def short_deadline(monkeypatch):
    _override(monkeypatch, url_fetch_timeout_s=0.2)
    return 0.2


def _timed(url, budget):
    async def go():
        start = time.monotonic()
        try:
            await asyncio.wait_for(fetch_url_text(url), budget)
        except asyncio.TimeoutError:
            return None, time.monotonic() - start
        except Exception as exc:  # the fetcher's own error is the outcome under test
            return exc, time.monotonic() - start
        return "returned", time.monotonic() - start

    return asyncio.run(go())


def test_total_deadline_trips_on_slow_drip_body(short_deadline, origin):
    body = _CountingBody(10_000, chunk=1, delay=short_deadline / 10)
    origin.routes[(PUBLIC_V4, "/p")] = lambda request: httpx.Response(200, content=body)
    exc, elapsed = _timed(f"http://{PUBLIC_V4}/p", short_deadline + 2.0)
    assert isinstance(exc, _contract("UrlFetchError")) and exc.reason == "timeout", exc
    assert elapsed < short_deadline + 1.5  # outer budget is short_deadline + 2.0


def test_total_deadline_trips_on_hanging_server(short_deadline, origin):
    async def hang(request):
        await asyncio.sleep(30)
        return httpx.Response(200)

    origin.routes[(PUBLIC_V4, "/p")] = hang
    exc, elapsed = _timed(f"http://{PUBLIC_V4}/p", short_deadline + 2.0)
    assert isinstance(exc, _contract("UrlFetchError")) and exc.reason == "timeout", exc
    assert elapsed < short_deadline + 1.5  # outer budget is short_deadline + 2.0


def test_total_deadline_covers_slow_dns(short_deadline, resolver, origin):
    resolver.table["slow.test"] = [PUBLIC_V4]
    resolver.delay = short_deadline * 5
    exc, elapsed = _timed("http://slow.test/p", short_deadline + 2.0)
    assert isinstance(exc, _contract("UrlFetchError")) and exc.reason == "timeout", exc
    assert elapsed < short_deadline + 1.5  # outer budget is short_deadline + 2.0
    assert origin.requests == []


# ---- errors are typed, honest and clean --------------------------------------

def test_transport_failure_is_a_clean_connect_error(origin):
    def boom(request):
        raise httpx.ConnectError("connection refused to 10.9.8.7", request=request)

    origin.routes[(PUBLIC_V4, "/p")] = boom
    exc = _expect("UrlFetchError", {"connect"}, f"http://{PUBLIC_V4}/p")
    _assert_clean_message(exc, "10.9.8.7")


def test_refusal_messages_name_the_true_cause(resolver, origin):
    resolver.table["example.test"] = [PUBLIC_V4]
    unsafe = _contract("UnsafeUrlError")
    messages = {}
    for reason, url in [
        ("scheme", "file:///etc/passwd"),
        ("userinfo", "http://user@example.test/"),
        ("address", "http://169.254.169.254/"),
        ("malformed", "http://exa‮mple.test/"),
    ]:
        with pytest.raises(unsafe) as info:
            _fetch(url)
        assert info.value.reason == reason
        _assert_clean_message(info.value, "‮", "/etc/passwd")
        messages[reason] = str(info.value)
    assert len(set(messages.values())) == len(messages), messages


def test_analyze_url_redirect_to_internal_host_is_400_and_clean(app_client, resolver, origin):
    resolver.table["example.test"] = [PUBLIC_V4]
    resolver.table["internal.test"] = ["10.0.0.5"]
    origin.routes[(PUBLIC_V4, "/terms")] = _redirect("http://internal.test/admin")
    response = app_client.post("/analyze/url", json={"url": "http://example.test/terms"})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert isinstance(detail, str) and "Traceback" not in detail
    assert "10.0.0.5" not in detail and "internal.test" not in detail
    assert len(origin.requests) == 1


def test_analyze_url_bad_content_length_is_400_without_parser_internals(app_client, origin):
    origin.routes[(PUBLIC_V4, "/terms")] = _text(b"ok", headers={"content-length": "abc"})
    response = app_client.post("/analyze/url", json={"url": f"http://{PUBLIC_V4}/terms"})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "invalid literal" not in detail and "abc" not in detail
