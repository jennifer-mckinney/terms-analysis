"""The ONE config loader for the weekly wiring audit (card #224, ADR 0002).

Every tunable value (model, prices, budget, globs, caps, timeouts, labels,
prompt text, patterns) lives in ``scripts/audit/config.json`` and reaches the
code only through ``load_config`` (DEV-FUNDAMENTALS F13). The loader fails
closed: a missing file, malformed JSON, a duplicated key, a missing key, an
unknown key or a bad value raises ``ConfigError`` naming the key.

The pattern files the audit shares with the governance hooks
(``personal-path-patterns.txt``, ``evidence-leak-regex.txt``) are loaded here
too, so there is one loader for everything the audit reads as configuration.

``EXIT_CODES`` is the one exit-code table (F10): inventory, submit and collect
each expose the subset they can return, with the same number for a name in
every module. Exit 1 is deliberately unused, so an uncaught crash (which
Python reports as 1) is never mistaken for a documented outcome.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Callable

# One table, every module (F10). 2, 3 and 10-16 were fixed by the design gate.
EXIT_CODES: dict[str, int] = {
    "OK": 0,
    "BUDGET_EXCEEDED": 2,
    "NO_MODULES": 3,
    "CONFIG": 4,
    "MISSING_SECRET": 5,
    "LEAK": 6,
    "LEAK_SCAN_ERROR": 7,
    "PRICES_STALE": 8,
    "ARTIFACT_INVALID": 9,
    "BATCH_NOT_ENDED": 10,
    "PARTIAL": 11,
    "MISSING_OR_DUP": 12,
    "TRUNCATED_OR_REFUSED": 13,
    "SCHEMA": 14,
    "API_ERROR": 15,
    "DELETE_FAILED": 16,
    "CANARY_MISSING": 17,
    "SUBMIT_FAILED_AFTER_CREATE": 18,
    "CANCEL_TIMEOUT": 19,
    "HANDOFF_STALE": 20,
    "NO_HANDOFF": 21,
}

# Vendor API contracts, not tunables: the Batches API custom_id rule and the
# GitHub issue-title limit. They bound what config may ask for.
CUSTOM_ID_RE = re.compile(r"[a-zA-Z0-9_-]{1,64}")
GITHUB_TITLE_LIMIT = 256

_PRICE_KEYS = frozenset({"input", "output", "cache_read", "cache_write"})
_SCHEDULE_KEYS = frozenset({"submit", "collect"})
_CRON_FIELD = re.compile(r"[0-9*/,-]+")
_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_API_VERSION_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_KIND_RE = re.compile(r"[a-z][a-z_]{0,63}")
_SEVERITY_RE = re.compile(r"[A-Z]{1,16}")
_LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._ /-]{0,49}")
_UA_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,63}")
_HTTPS_BASE_RE = re.compile(r"https://[a-z0-9.-]+(?::[0-9]{1,5})?")
_GLOB_RE = re.compile(r"[A-Za-z0-9_.*?/~-]+")
_PATH_SEGMENT_RE = re.compile(r"[A-Za-z0-9_.-]+")
_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")

# Placeholders each prompt template may use, and those it must use.
SYSTEM_PLACEHOLDERS = frozenset({"kinds", "severities", "max_findings"})
USER_PLACEHOLDERS = frozenset({"path", "facts", "source"})
USER_REQUIRED = frozenset({"path", "facts", "source"})


class ConfigError(ValueError):
    """The config (or a pattern file it names) is missing or invalid."""


# --- value checks ------------------------------------------------------------------


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _positive_int(value: Any) -> bool:
    return _is_int(value) and value > 0


def _positive_number(value: Any) -> bool:
    return _is_number(value) and value > 0


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != "" and value == value.strip()


def _str_list(value: Any, item: Callable[[Any], bool], *, allow_empty: bool = False) -> bool:
    return (isinstance(value, list) and (allow_empty or len(value) > 0)
            and all(item(v) for v in value) and len(set(value)) == len(value))


def _matches(rx: re.Pattern[str]) -> Callable[[Any], bool]:
    return lambda v: isinstance(v, str) and rx.fullmatch(v) is not None


def is_safe_relpath(value: Any) -> bool:
    """A repo-relative POSIX path with no traversal, absolute root or odd bytes."""
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        return False
    parts = PurePosixPath(value).parts
    return (len(parts) > 0 and "/".join(parts) == value
            and all(p not in (".", "..") and _PATH_SEGMENT_RE.fullmatch(p) for p in parts))


def _iso_date(value: Any) -> bool:
    if not isinstance(value, str) or not _ISO_DATE_RE.fullmatch(value):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _prices(value: Any) -> bool:
    return (isinstance(value, dict) and set(value) == _PRICE_KEYS
            and all(_is_number(v) and v >= 0 for v in value.values()))


def _schedule(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != _SCHEDULE_KEYS:
        return False
    for cron in value.values():
        if not isinstance(cron, str):
            return False
        fields = cron.split(" ")
        if len(fields) != 5 or not all(_CRON_FIELD.fullmatch(f) for f in fields):
            return False
    return True


def _regex_list(value: Any) -> bool:
    if not _str_list(value, _nonempty_str):
        return False
    for pattern in value:
        try:
            rx = re.compile(pattern)
        except re.error:
            return False
        if rx.search("") is not None:  # a pattern that matches nothing-at-all matches everything
            return False
    return True


def _template(allowed: frozenset[str], required: frozenset[str]) -> Callable[[Any], bool]:
    def check(value: Any) -> bool:
        if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
            return False
        used = set(_PLACEHOLDER_RE.findall("\n".join(value)))
        return used <= allowed and required <= used
    return check


def _status_list(value: Any) -> bool:
    return _str_list(value, lambda v: _is_int(v) and 400 <= v <= 599)


# Every key the shipped config carries, with its check. A key in the file but
# not here is unknown (rejected); a key here but not in the file is missing.
_CHECKS: dict[str, Callable[[Any], bool]] = {
    "model": _matches(_MODEL_RE),
    "max_tokens": _positive_int,
    "api_version": _matches(_API_VERSION_RE),
    "api_base_url": _matches(_HTTPS_BASE_RE),
    "github_api_url": _matches(_HTTPS_BASE_RE),
    "github_api_version": _matches(_API_VERSION_RE),
    "user_agent": _matches(_UA_RE),
    "budget_ceiling_usd": _positive_number,
    "prices_usd_per_mtok": _prices,
    "price_review_by": _iso_date,
    "module_globs": lambda v: _str_list(v, _matches(_GLOB_RE)),
    "exclude_globs": lambda v: _str_list(v, _matches(_GLOB_RE)),
    "max_module_chars": _positive_int,
    "max_listed_references": _positive_int,
    "finding_kinds": lambda v: _str_list(v, _matches(_KIND_RE)),
    "severities": lambda v: _str_list(v, _matches(_SEVERITY_RE)),
    "max_findings_per_module": _positive_int,
    "card_threshold": lambda v: isinstance(v, str),
    "card_mode": lambda v: v in ("summary", "cards"),
    "max_cards_per_run": _positive_int,
    "max_field_chars": _positive_int,
    "max_title_chars": lambda v: _positive_int(v) and v <= GITHUB_TITLE_LIMIT,
    "max_issue_body_chars": _positive_int,
    "labels": lambda v: _str_list(v, _matches(_LABEL_RE)),
    "issue_page_size": lambda v: _positive_int(v) and v <= 100,
    "max_issue_pages": _positive_int,
    "schedule": _schedule,
    "canary_fixture": is_safe_relpath,
    "canary_expected_kind": lambda v: isinstance(v, str),
    "leak_scan_script": is_safe_relpath,
    "leak_scan_patterns": is_safe_relpath,
    "personal_path_patterns": is_safe_relpath,
    "secret_patterns": _regex_list,
    "system_prompt": _template(SYSTEM_PLACEHOLDERS, frozenset()),
    "user_prompt": _template(USER_PLACEHOLDERS, USER_REQUIRED),
    "http_timeout_seconds": _positive_number,
    "max_response_bytes": _positive_int,
    "retry_statuses": _status_list,
    "retry_backoff_seconds": _positive_number,
    "poll_interval_seconds": _positive_number,
    "cancel_timeout_seconds": _positive_int,
    "stale_handoff_days": _positive_int,
    "subprocess_timeout_seconds": _positive_number,
    "max_subprocess_output_bytes": _positive_int,
}


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ConfigError(f"config key {key!r} appears twice")
        out[key] = value
    return out


def load_config(path: str | Path) -> dict[str, Any]:
    """Read, validate and return the audit config; raise ConfigError on any defect."""
    name = Path(path).name  # F8: messages name the file, never its absolute path
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read config file {name}: {type(exc).__name__}") from None
    try:
        data = json.loads(text, object_pairs_hook=_reject_duplicates)
    except ConfigError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ConfigError(f"config file {name} is not valid JSON: {type(exc).__name__}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"config file {name} must hold a JSON object")
    unknown = sorted(set(data) - set(_CHECKS))
    if unknown:
        raise ConfigError(f"unknown config key(s): {', '.join(map(repr, unknown))}")
    missing = [key for key in _CHECKS if key not in data]
    if missing:
        raise ConfigError(f"missing config key(s): {', '.join(missing)}")
    for key, check in _CHECKS.items():
        if not check(data[key]):
            raise ConfigError(f"config key {key!r} has an invalid value")
    _cross_checks(data)
    return data


def _cross_checks(cfg: dict[str, Any]) -> None:
    if cfg["card_threshold"] not in cfg["severities"]:
        raise ConfigError("config key 'card_threshold' must be one of 'severities' (exact case)")
    if cfg["canary_expected_kind"] not in cfg["finding_kinds"]:
        raise ConfigError("config key 'canary_expected_kind' must be one of 'finding_kinds'")
    # Three model-written fields per card must leave room for the fixed template.
    if cfg["max_field_chars"] * 4 > cfg["max_issue_body_chars"]:
        raise ConfigError("config key 'max_field_chars' is too large for 'max_issue_body_chars'")
    if cfg["poll_interval_seconds"] > cfg["cancel_timeout_seconds"]:
        raise ConfigError("config key 'poll_interval_seconds' exceeds 'cancel_timeout_seconds'")


def severity_rank(cfg: dict[str, Any], severity: str) -> int:
    """Position of a severity in the configured lowest-to-highest order."""
    return list(cfg["severities"]).index(severity)


def render_template(lines: list[str], values: dict[str, str]) -> str:
    """Fill {placeholders} in ONE pass, so a value can never inject another placeholder."""
    return _PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], "\n".join(lines))


# --- pattern files shared with the governance hooks ---------------------------------


def repo_file(repo: Path, rel: str, key: str) -> Path:
    """Resolve a config-named repo-relative file; it must be a regular file inside the repo."""
    root = repo.resolve()
    path = (root / rel).resolve()
    if root not in path.parents or not path.is_file():
        raise ConfigError(f"config key {key!r}: {rel} is not a file in the audited checkout")
    return path


def _pattern_lines(path: Path, key: str) -> list[str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"config key {key!r}: cannot read {path.name}: {type(exc).__name__}") from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ConfigError(f"config key {key!r}: {path.name} is not UTF-8") from None
    return [line for line in text.split("\n") if line.strip() and not line.startswith("#")]


def strip_format_chars(text: str) -> str:
    """Remove Unicode format characters (category Cf), as the governance matchers do."""
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def load_personal_patterns(repo: Path, cfg: dict[str, Any]) -> list[re.Pattern[str]]:
    """personal-path-patterns.txt: one regex per line, case-insensitive, never empty."""
    key = "personal_path_patterns"
    path = repo_file(repo, cfg[key], key)
    out: list[re.Pattern[str]] = []
    for line in _pattern_lines(path, key):
        try:
            rx = re.compile(line, re.IGNORECASE)
        except re.error:
            raise ConfigError(f"config key {key!r}: {path.name} holds an invalid pattern") from None
        if rx.search("") is not None:
            raise ConfigError(f"config key {key!r}: {path.name} holds a pattern matching empty text")
        out.append(rx)
    if not out:
        raise ConfigError(f"config key {key!r}: {path.name} holds no patterns")
    return out


def load_leak_patterns(repo: Path, cfg: dict[str, Any]) -> list[re.Pattern[str]]:
    """evidence-leak-regex.txt rows ``name<TAB>regex[<TAB>context]``, matched case-folded.

    Used only to REDACT model text before it is filed; a context row is applied
    without its context check, which redacts more, never less.
    """
    key = "leak_scan_patterns"
    path = repo_file(repo, cfg[key], key)
    out: list[re.Pattern[str]] = []
    for line in _pattern_lines(path, key):
        fields = line.split("\t")
        if len(fields) not in (2, 3) or not fields[1]:
            raise ConfigError(f"config key {key!r}: {path.name} has a malformed row")
        try:
            out.append(re.compile(fields[1]))
        except re.error:
            raise ConfigError(f"config key {key!r}: {path.name} holds an invalid pattern") from None
    if not out:
        raise ConfigError(f"config key {key!r}: {path.name} holds no patterns")
    return out


def matches_personal_path(text: str, patterns: list[re.Pattern[str]]) -> bool:
    canonical = strip_format_chars(text)
    return any(rx.search(canonical) for rx in patterns)
