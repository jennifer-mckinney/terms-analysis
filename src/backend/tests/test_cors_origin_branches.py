"""Coder unit tests for the #135 origin validator branches.

``test_cors_policy.py`` (the acceptance file) rejects most hostile entries at the
https or shape check, so the host and port checks behind them are exercised here:
each branch has a rejected and an accepted vector, and the reason is pinned.
"""

from __future__ import annotations

import dataclasses

import pytest

from app import config

LABEL_63 = "a" * 63

# (branch, entry, expected reason fragment or None when accepted)
BRANCH_VECTORS: list[tuple[str, str, str | None]] = [
    ("ipv6-invalid", "https://[::1:]", "invalid IPv6 address"),
    ("ipv6-invalid", "https://[:::]", "invalid IPv6 address"),
    ("ipv6-invalid", "https://[2001:db8::1]", None),
    ("ipv6-canonical", "https://[0:0:0:0:0:0:0:1]", "canonical form"),
    ("ipv6-canonical", "https://[2001:db8:0::1]", "canonical form"),
    ("ipv6-canonical", "http://[::1]:8000", None),
    ("dns-name", "https://-a.example", "invalid host name"),
    ("dns-name", "https://a-.example", "invalid host name"),
    ("dns-name", "https://-.example", "invalid host name"),
    ("dns-name", f"https://{'a' * 64}.example", "invalid host name"),
    ("dns-name", "https://" + ".".join([LABEL_63] * 4), "invalid host name"),  # 255 chars
    ("dns-name", f"https://{LABEL_63}.example", None),
    ("dns-name", "https://a-b.example", None),
    ("numeric-host", "https://0x7f.0.0.1", "canonical dotted IPv4"),
    ("numeric-host", "https://2130706433", "canonical dotted IPv4"),
    ("numeric-host", "https://1.2.3", "canonical dotted IPv4"),
    ("numeric-host", "https://192.0.2.010", "canonical dotted IPv4"),
    ("numeric-host", "https://a.0x", "canonical dotted IPv4"),
    ("numeric-host", "https://192.0.2.10", None),
    ("numeric-host", "https://a.example1", None),
    ("port-range", "https://a.example:65536", "port above 65535"),
    ("port-range", "https://a.example:65535", None),
    ("default-port", "https://a.example:443", "default port"),
    ("default-port", "http://localhost:80", "default port"),
    ("default-port", "http://localhost:443", None),
    ("default-port", "https://a.example:80", None),
    ("case", "https://A.example", "lower-case ASCII"),
    ("case", "HTTPS://a.example", "lower-case ASCII"),
    ("case", "http://LOCALHOST:8501", "lower-case ASCII"),
    ("case", "https://a.example", None),
    ("scheme", "ws://localhost:8000", "must use https"),
    ("scheme", "https://localhost", None),
]


def _replace(origins: object) -> config.Settings:
    return dataclasses.replace(config.settings, allowed_origins=origins)


def test_branch_vectors_contract() -> None:
    outcomes: dict[str, set[bool]] = {}
    for branch, _entry, reason in BRANCH_VECTORS:
        outcomes.setdefault(branch, set()).add(reason is None)
    lacking = sorted(b for b, seen in outcomes.items() if seen != {True, False})
    assert not lacking, f"branches without both an accepted and a rejected vector: {lacking}"


@pytest.mark.parametrize(
    ("entry", "reason"),
    [pytest.param(e, r, id=f"{b}:{e}"[:80]) for b, e, r in BRANCH_VECTORS],
)
def test_branch_vector(entry: str, reason: str | None) -> None:
    if reason is None:
        assert _replace([entry]).allowed_origins == (entry,)
        return
    with pytest.raises(ValueError) as exc:
        _replace([entry])
    msg = str(exc.value)
    assert msg.startswith("allowed_origins (ALLOWED_ORIGINS) entry 1 "), msg
    assert reason in msg
    assert entry not in msg  # the value is never echoed


def test_error_names_the_failing_entry_position() -> None:
    with pytest.raises(ValueError, match=r"^allowed_origins \(ALLOWED_ORIGINS\) entry 3 contains '\*'"):
        _replace(["https://a.example", "http://localhost", "*"])


def test_empty_list_is_valid_and_closes_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _replace([]).allowed_origins == ()
    monkeypatch.setenv("ALLOWED_ORIGINS", " , ,")
    assert config.Settings().allowed_origins == ()


def test_stored_value_is_a_copy_of_the_callers_list() -> None:
    caller = ["https://a.example"]
    s = _replace(caller)
    caller.append("*")
    assert s.allowed_origins == ("https://a.example",)


def test_live_settings_hold_a_tuple() -> None:
    assert isinstance(config.settings.allowed_origins, tuple)
