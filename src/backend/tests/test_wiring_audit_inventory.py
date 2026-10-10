"""Weekly wiring audit: config loader and inventory builder (card #224, ADR 0002).

ADR 0002 condition numbers are in brackets on every test ([C1] .. [C9]).
The interface pinned here is described in ``tests/wiring_audit_support.py``.

[C1] The inventory is ``git ls-files`` filtered by the configured module
globs, minus the denylist (data/**, .env*, docs/evidence/**, .git/**,
virtualenvs, databases, cassettes) and minus every path or line matching
``.claude/governance/personal-path-patterns.txt``. Test files stay eligible.
It is deterministic, and zero modules is a loud failure before any network.
[F13] Everything tunable comes from ``scripts/audit/config.json`` through one
loader that fails closed on a missing key or a bad value.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

import pytest

from tests.wiring_audit_support import (
    CONFIG_PATH,
    CUSTOM_ID_RE,
    HOME_LINE_PATH,
    TILDE_DOCS_DIR,
    AUDIT_DIR,
    canary_source,
    exit_code,
    git_env,
    governance_files,
    load_audit_module,
    make_repo,
    module_source,
    python_exe,
    real_config,
    require,
    write_config,
)

RUN_TIMEOUT = 120

# Keys the brief and the design (s.2 "Config") put in config, not code.
REQUIRED_KEYS = (
    "model",
    "max_tokens",
    "api_version",
    "budget_ceiling_usd",
    "prices_usd_per_mtok",
    "price_review_by",
    "module_globs",
    "exclude_globs",
    "max_module_chars",
    "card_threshold",
    "card_mode",
    "max_cards_per_run",
    "max_field_chars",
    "labels",
    "schedule",
    "canary_fixture",
    "canary_expected_kind",
    "leak_scan_script",
    "leak_scan_patterns",
    "personal_path_patterns",
    "cancel_timeout_seconds",
    "stale_handoff_days",  # PR #282 ruling 1: a hand-off older than this is refused
)

# Exit-code numbers the design gate fixed (s.2 budget + result contract).
DESIGN_EXIT_CODES = {
    "BUDGET_EXCEEDED": 2,
    "NO_MODULES": 3,
    "BATCH_NOT_ENDED": 10,
    "PARTIAL": 11,
    "MISSING_OR_DUP": 12,
    "TRUNCATED_OR_REFUSED": 13,
    "SCHEMA": 14,
    "API_ERROR": 15,
    "DELETE_FAILED": 16,
}
REQUIRED_EXIT_NAMES = {
    "inventory": {"OK", "CONFIG", "NO_MODULES"},
    "submit": {
        "OK", "CONFIG", "NO_MODULES", "MISSING_SECRET", "LEAK", "LEAK_SCAN_ERROR", "PRICES_STALE",
        "BUDGET_EXCEEDED", "API_ERROR", "SUBMIT_FAILED_AFTER_CREATE", "CANCEL_TIMEOUT", "DELETE_FAILED",
    },
    "collect": {
        "OK", "CONFIG", "MISSING_SECRET", "ARTIFACT_INVALID", "BATCH_NOT_ENDED", "PARTIAL", "MISSING_OR_DUP",
        "TRUNCATED_OR_REFUSED", "SCHEMA", "CANARY_MISSING", "API_ERROR", "DELETE_FAILED", "CANCEL_TIMEOUT",
        "HANDOFF_STALE", "NO_HANDOFF",  # PR #282 ruling 1
    },
}


# --- helpers -----------------------------------------------------------------------


def _run_inventory(repo: Path, cfg_path: Path, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    require("inventory")
    return subprocess.run(
        [python_exe(), "-I", str(AUDIT_DIR / "inventory.py"), "--repo", str(repo), "--config", str(cfg_path)],
        cwd=repo,
        env=git_env() if env is None else env,
        capture_output=True,
        timeout=RUN_TIMEOUT,
    )


def _modules(proc: subprocess.CompletedProcess[bytes]) -> list[dict[str, Any]]:
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-2000:]
    doc = json.loads(proc.stdout)
    assert isinstance(doc, dict) and isinstance(doc.get("modules"), list)
    return doc["modules"]


def _paths(proc: subprocess.CompletedProcess[bytes]) -> list[str]:
    return [m["path"] for m in _modules(proc)]


def _golden_repo(tmp: Path, cfg: dict[str, Any]) -> Path:
    files: dict[str, str | bytes] = dict(governance_files(cfg))
    files.update(
        {
            cfg["canary_fixture"]: canary_source(),
            "README.md": "# fixture\n",
            "src/backend/app/main.py": module_source("MAIN_MARKER", "create_app")
            + f'LOCAL_HINT = "{HOME_LINE_PATH}"\nAFTER_HOME_LINE = "KEPT_LINE_MARKER"\n',
            "src/backend/app/services/rules.py": module_source("RULES_MARKER", "evaluate"),
            "src/backend/tests/test_rules.py": "from app.services import rules\n\ndef test_x():\n    assert rules\n",
            "tests/test_api.py": "def test_root():\n    assert True\n",
            "src/backend/tests/fixtures/cassettes/recorded_client.py": "RECORDED = 'CASSETTE_MARKER'\n",
            "src/backend/tests/fixtures/cassettes/gdpr.yaml": "interactions: []  # CASSETTE_MARKER\n",
            "src/backend/.venv/lib/python3.14/site-packages/pkg/mod.py": "VENV_MARKER = 1\n",
            f"src/{TILDE_DOCS_DIR}/leak.py": "PERSONAL_PATH_MARKER = 1\n",
            "scripts/install_helper.py": module_source("HELPER_MARKER", "helper"),
            ".github/board-sync/board_sync.py": module_source("BOARD_MARKER", "plan"),
            ".github/workflows/ci.yml": "name: ci\non: [push]\njobs: {}\n",
            "data/legal_corpus/importer.py": "from app.services import rules  # DENIED_CALLER_MARKER\n",
            "data/legal_corpus/gdpr.txt": "Article 1 DENIED_DATA_MARKER\n",
            "docs/evidence/notes.py": "import rules  # EVIDENCE_MARKER\n",
            "docs/guide.md": "guide\n",
            ".env": "API_KEY=SECRET_ENV_MARKER\n",
            ".env.local": "X=SECRET_ENV_MARKER\n",
            "src/backend/data/terms.db": b"SQLite format 3\x00DB_MARKER",
        }
    )
    untracked = {
        "src/backend/app/untracked_leak.py": "from app.services.rules import evaluate  # UNTRACKED_MARKER\n",
    }
    return make_repo(tmp / "repo", files, untracked=untracked)


# Expected module list for the fixture checkout under the SHIPPED config.
# A widened or narrowed glob changes this list and must be a reviewed change.
GOLDEN_PATHS = [
    ".github/board-sync/board_sync.py",
    ".github/workflows/ci.yml",
    "scripts/governance/leak_scan.py",
    "scripts/install_helper.py",
    "src/backend/app/main.py",
    "src/backend/app/services/rules.py",
    "src/backend/tests/test_rules.py",
    "tests/test_api.py",
]
DENIED_MARKERS = (
    "CASSETTE_MARKER",
    "VENV_MARKER",
    "PERSONAL_PATH_MARKER",
    "DENIED_CALLER_MARKER",
    "DENIED_DATA_MARKER",
    "EVIDENCE_MARKER",
    "SECRET_ENV_MARKER",
    "DB_MARKER",
    "UNTRACKED_MARKER",
    "someone-private",
)


# --- config loader [F13, C5, C7] ------------------------------------------------------------------


def test_shipped_config_loads_through_the_one_loader() -> None:
    config = require("config")
    raw = real_config()
    loaded = config.load_config(CONFIG_PATH)
    for key in REQUIRED_KEYS:
        assert key in raw, f"shipped config lacks {key}"
        assert loaded[key] == raw[key], key


def test_shipped_config_starts_in_summary_card_mode() -> None:
    # [C7] the first run, and every run until the owner flips it, files ONE summary issue.
    assert real_config()["card_mode"] == "summary"


def _cron_offset_seconds(cron: str) -> int:
    """Seconds into the week of a weekly 'M H * * D' cron; anything else fails the test."""
    fields = cron.split()
    assert len(fields) == 5 and fields[2:4] == ["*", "*"], cron
    minute, hour, dow = (int(fields[0]), int(fields[1]), int(fields[4]))
    return ((dow % 7) * 24 + hour) * 3600 + minute * 60


def test_shipped_stale_handoff_days_covers_the_submit_to_collect_gap() -> None:
    # Ruling 1: this week's hand-off is never stale when collect runs on schedule,
    # and the value is a positive whole number of days read from config.
    cfg = real_config()
    days = cfg["stale_handoff_days"]
    assert isinstance(days, int) and not isinstance(days, bool) and days > 0
    week = 7 * 24 * 3600
    gap = (_cron_offset_seconds(cfg["schedule"]["collect"]) - _cron_offset_seconds(cfg["schedule"]["submit"])) % week
    assert days * 24 * 3600 > gap


def test_shipped_config_price_review_date_is_iso() -> None:
    # [C5] stale prices fail closed; the shipped date must parse as ISO.
    import datetime as dt

    dt.date.fromisoformat(real_config()["price_review_by"])


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_config_loader_rejects_a_missing_key(tmp_path: Path, key: str) -> None:
    config = require("config")
    raw = real_config()
    raw.pop(key)
    path = tmp_path / "c.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(config.ConfigError) as info:
        config.load_config(path)
    assert key in str(info.value)
    assert issubclass(config.ConfigError, ValueError)


def test_every_shipped_key_is_required(tmp_path: Path) -> None:
    # No silently optional knob: removing ANY shipped key fails at load.
    config = require("config")
    raw = real_config()
    for key in raw:
        reduced = {k: v for k, v in raw.items() if k != key}
        path = tmp_path / f"c-{key}.json"
        path.write_text(json.dumps(reduced), encoding="utf-8")
        with pytest.raises(config.ConfigError):
            config.load_config(path)


BAD_VALUES = [
    ("model", ""),
    ("model", 5),
    ("model", "claude\nforged: line"),
    ("max_tokens", 0),
    ("max_tokens", -1),
    ("max_tokens", "1500"),
    ("max_tokens", True),
    ("max_tokens", 1.5),
    ("api_version", ""),
    ("budget_ceiling_usd", -0.01),
    ("budget_ceiling_usd", "1.00"),
    ("budget_ceiling_usd", math.inf),
    ("budget_ceiling_usd", math.nan),
    ("prices_usd_per_mtok", {"input": 1.0}),
    ("prices_usd_per_mtok", {"input": -1.0, "output": 5.0, "cache_read": 0.1}),
    ("prices_usd_per_mtok", "1/5"),
    ("price_review_by", "2026-13-01"),
    ("price_review_by", "soon"),
    ("price_review_by", 20261231),
    ("module_globs", []),
    ("module_globs", "src/**/*.py"),
    ("exclude_globs", "data/**"),
    ("max_module_chars", 0),
    ("card_threshold", "BOGUS"),
    ("card_threshold", "medium"),
    ("card_mode", "flood"),
    ("card_mode", "Summary"),
    ("max_cards_per_run", 0),
    ("max_cards_per_run", -1),
    ("max_field_chars", 0),
    ("labels", "wiring-audit"),
    ("schedule", "0 2 * * 1"),
    ("schedule", {"submit": "0 2 * * 1"}),
    ("canary_fixture", "../outside.py"),
    ("canary_fixture", "/etc/passwd"),
    ("canary_expected_kind", "not_a_kind"),
    ("leak_scan_script", "../../evil.py"),
    ("leak_scan_patterns", "/tmp/patterns.txt"),
    ("personal_path_patterns", ""),
    ("cancel_timeout_seconds", 0),
    ("cancel_timeout_seconds", "600"),
    ("stale_handoff_days", 0),
    ("stale_handoff_days", -1),
    ("stale_handoff_days", "8"),
    ("stale_handoff_days", True),
    ("stale_handoff_days", 1.5),
    ("stale_handoff_days", None),
]


def test_bad_value_table_covers_every_required_key() -> None:
    # Table contract: every key has at least one fail-closed row.
    assert {k for k, _ in BAD_VALUES} == set(REQUIRED_KEYS)


@pytest.mark.parametrize(("key", "value"), BAD_VALUES, ids=[f"{k}={v!r}"[:60] for k, v in BAD_VALUES])
def test_config_loader_rejects_a_bad_value(tmp_path: Path, key: str, value: Any) -> None:
    config = require("config")
    raw = real_config()
    raw[key] = value
    path = tmp_path / "c.json"
    path.write_text(json.dumps(raw), encoding="utf-8")  # NaN/Infinity written as JSON extensions
    with pytest.raises(config.ConfigError) as info:
        config.load_config(path)
    assert key in str(info.value)


@pytest.mark.parametrize(
    "content",
    [b"", b"not json", b"[]", b'{"model": "x"', "﻿{}".encode("utf-8")],
    ids=["empty", "not-json", "list", "truncated", "bom-empty-object"],
)
def test_config_loader_rejects_malformed_files(tmp_path: Path, content: bytes) -> None:
    config = require("config")
    path = tmp_path / "c.json"
    path.write_bytes(content)
    with pytest.raises(config.ConfigError):
        config.load_config(path)


def test_config_loader_rejects_unknown_keys_and_missing_files(tmp_path: Path) -> None:
    config = require("config")
    raw = real_config()
    raw["surprise_knob"] = 1
    path = tmp_path / "c.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(config.ConfigError) as info:
        config.load_config(path)
    assert "surprise_knob" in str(info.value)
    with pytest.raises(config.ConfigError):
        config.load_config(tmp_path / "absent.json")


def test_config_error_message_has_no_absolute_path(tmp_path: Path) -> None:
    # [F8] messages name the key, not the runner's absolute path.
    config = require("config")
    with pytest.raises(config.ConfigError) as info:
        config.load_config(tmp_path / "absent.json")
    assert str(tmp_path) not in str(info.value)


# --- exit-code table [C6, F10] -------------------------------------------------------------------


def test_exit_code_tables_are_one_contract() -> None:
    seen: dict[str, int] = {}
    for name, required in REQUIRED_EXIT_NAMES.items():
        module = require(name)
        codes = getattr(module, "EXIT_CODES", None)
        assert isinstance(codes, dict), f"{name}.EXIT_CODES missing"
        assert required <= set(codes), f"{name}: missing {sorted(required - set(codes))}"
        assert codes["OK"] == 0
        values = list(codes.values())
        assert len(values) == len(set(values)), f"{name}: duplicate exit numbers"
        for code_name, number in codes.items():
            assert isinstance(number, int) and not isinstance(number, bool)
            assert code_name == "OK" or 1 <= number <= 125, (name, code_name, number)
            assert seen.setdefault(code_name, number) == number, f"{code_name} differs across modules"
            if code_name in DESIGN_EXIT_CODES:
                assert number == DESIGN_EXIT_CODES[code_name], (code_name, number)


# --- inventory [C1] -------------------------------------------------------------------------------


def test_inventory_matches_the_golden_list_for_a_known_checkout(tmp_path: Path) -> None:
    cfg_path, cfg = write_config(tmp_path)
    repo = _golden_repo(tmp_path, cfg)
    paths = _paths(_run_inventory(repo, cfg_path))
    assert paths == GOLDEN_PATHS
    assert cfg["canary_fixture"] not in paths  # [C6] the canary is not a repository module


def test_inventory_never_carries_denied_untracked_or_personal_content(tmp_path: Path) -> None:
    cfg_path, cfg = write_config(tmp_path)
    repo = _golden_repo(tmp_path, cfg)
    proc = _run_inventory(repo, cfg_path)
    text = proc.stdout.decode("utf-8", "replace")
    leaked = [m for m in DENIED_MARKERS if m in text]
    assert leaked == []
    for path in _paths(proc):
        for fragment in ("data/", "docs/evidence/", "untracked_leak", ".env", ".venv/", "cassettes/", TILDE_DOCS_DIR):
            assert fragment not in path, (fragment, path)


DENY_FILES = [
    "data/app.db",
    "data/legal_corpus/a.txt",
    "data/tools/loader.py",
    ".env",
    ".env.local",
    ".env.example",
    "src/backend/.env",
    "docs/evidence/log.txt",
    "docs/evidence/run.py",
    ".venv/lib/python3.14/site-packages/x.py",
    "src/backend/.venv/lib/m.py",
    "venv/lib/python3.14/site-packages/pkg/m.py",
    "app.db",
    "src/backend/terms.db",
    "tests/fixtures/cassettes/a.yaml",
    "src/backend/tests/fixtures/cassettes/b.json",
    f"src/{TILDE_DOCS_DIR}/leak.py",
]
ALLOW_FILES = [
    "README.md",
    "docs/guide.md",
    "src/app.py",
    "src/backend/tests/test_app.py",
    "tests/test_x.py",
    "src/backend/tests/conftest.py",
    "src/environment.py",
    "src/database.py",
]


def test_denylist_holds_even_when_the_globs_match_everything(tmp_path: Path) -> None:
    # [C1] the denylist is a control of its own, not a side effect of narrow globs.
    cfg_path, cfg = write_config(tmp_path, module_globs=["**/*"])
    files: dict[str, str | bytes] = dict(governance_files(cfg))
    files[cfg["canary_fixture"]] = canary_source()
    for rel in DENY_FILES + ALLOW_FILES:
        files[rel] = f"# {rel}\nx = 1\n"
    repo = make_repo(tmp_path / "repo", files)
    paths = set(_paths(_run_inventory(repo, cfg_path)))
    assert paths & set(DENY_FILES) == set()
    assert set(ALLOW_FILES) <= paths  # positive control: tests and look-alike names stay
    assert cfg["canary_fixture"] not in paths


def test_personal_path_lines_are_dropped_but_the_rest_of_the_module_stays(tmp_path: Path) -> None:
    cfg_path, cfg = write_config(tmp_path)
    repo = _golden_repo(tmp_path, cfg)
    text = _run_inventory(repo, cfg_path).stdout.decode("utf-8", "replace")
    assert "someone-private" not in text
    assert "src/backend/app/main.py" in text


def test_symlinks_never_pull_in_untracked_or_outside_content(tmp_path: Path) -> None:
    # [F7] verify the object acted on: a tracked symlink must not smuggle its target.
    cfg_path, cfg = write_config(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("ABS_LINK_MARKER = 1\n", encoding="utf-8")
    files: dict[str, str | bytes] = dict(governance_files(cfg))
    files[cfg["canary_fixture"]] = canary_source()
    files["src/backend/app/ok.py"] = module_source("OK_MARKER", "ok")
    repo = make_repo(
        tmp_path / "repo",
        files,
        untracked={"outside_secret.txt": "REL_LINK_MARKER = 1\n"},
        symlinks={
            "src/backend/app/rel_link.py": "../../../outside_secret.txt",
            "src/backend/app/abs_link.py": str(outside / "secret.py"),
        },
    )
    proc = _run_inventory(repo, cfg_path)
    text = proc.stdout.decode("utf-8", "replace")
    assert "src/backend/app/ok.py" in _paths(proc)
    assert "ABS_LINK_MARKER" not in text
    assert "REL_LINK_MARKER" not in text
    assert str(outside) not in text


def test_git_environment_cannot_redirect_the_inventory(tmp_path: Path) -> None:
    # [F7] GIT_DIR / GIT_WORK_TREE in the environment must not swap the audited tree.
    cfg_path, cfg = write_config(tmp_path)
    repo = _golden_repo(tmp_path, cfg)
    other = make_repo(tmp_path / "other", {"src/backend/app/other_repo.py": "OTHER_REPO_MARKER = 1\n"})
    baseline = _run_inventory(repo, cfg_path)
    env = git_env()
    env.update({"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)})
    redirected = _run_inventory(repo, cfg_path, env=env)
    assert b"OTHER_REPO_MARKER" not in redirected.stdout
    assert redirected.returncode == baseline.returncode == 0
    assert redirected.stdout == baseline.stdout


# Ruling 2 (PR #282): the child env is an allowlist. Values assembled so no
# secret-shaped literal is tracked; the unrelated name proves "allowlist", not
# "denylist of two names".
CHILD_ENV_SECRETS = {
    "WIRING_AUDIT_API_KEY": "sk-" + "ant-" + "CHILDENVLEAK-" + "k3" * 8,
    "GITHUB_TOKEN": "ghs_" + "CHILDENVLEAK" + "t5" * 8,
    "WIRING_AUDIT_UNRELATED_VAR": "UNRELATED_" + "CHILDENV_MARKER",
}


def test_git_env_is_an_allowlist_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    inventory = require("inventory")
    for name, value in CHILD_ENV_SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GIT_DIR", "/nonexistent-redirect")  # [F7] still dropped
    env = inventory.git_env()
    # Compare names only: a failure must never print the child env (F8).
    leaked = sorted(name for name, value in CHILD_ENV_SECRETS.items()
                    if name in env or any(value in v for v in env.values()))
    assert leaked == []
    assert env.get("GIT_DIR") is None
    assert env.get("PATH") == os.environ["PATH"]  # positive control: git is still found


def test_inventory_is_byte_identical_across_runs(tmp_path: Path) -> None:
    cfg_path, cfg = write_config(tmp_path)
    repo = _golden_repo(tmp_path, cfg)
    first = _run_inventory(repo, cfg_path)
    env = git_env()
    env.update({"LC_ALL": "C", "LANG": "C", "TZ": "Pacific/Kiritimati"})
    os.utime(repo / "src/backend/app/main.py", (1, 1))
    second = _run_inventory(repo, cfg_path, env=env)
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    assert len(first.stdout) > 0


HOSTILE_NAMES = [
    "src/backend/app/naïve.py",
    "src/backend/app/has space.py",
    "src/backend/app/a-b.py",
    "src/backend/app/a_b.py",
    "src/backend/app/a.b.py",
    "src/backend/app/" + "x" * 200 + ".py",
]
CONTROL_NAMES = [
    "src/backend/app/bidi‮yp.evil.py",
    "src/backend/app/new\nline.py",
    "src/backend/app/zero​width.py",
]


def test_custom_ids_are_valid_unique_and_paths_exact_for_hostile_names(tmp_path: Path) -> None:
    # [C1, F1] custom_id ^[a-zA-Z0-9_-]{1,64}$, unique; a path is never C-quoted or mangled.
    cfg_path, cfg = write_config(tmp_path)
    files: dict[str, str | bytes] = dict(governance_files(cfg))
    files[cfg["canary_fixture"]] = canary_source()
    for rel in HOSTILE_NAMES + CONTROL_NAMES:
        files[rel] = "x = 1\n"
    repo = make_repo(tmp_path / "repo", files)
    modules = _modules(_run_inventory(repo, cfg_path))
    ids = [m["custom_id"] for m in modules]
    assert all(isinstance(i, str) and CUSTOM_ID_RE.fullmatch(i) for i in ids), ids
    assert len(ids) == len(set(ids))
    nfc = {unicodedata.normalize("NFC", p) for p in HOSTILE_NAMES + CONTROL_NAMES} | set(governance_files(cfg))
    got = {unicodedata.normalize("NFC", m["path"]) for m in modules}
    assert got <= nfc, sorted(got - nfc)
    assert {unicodedata.normalize("NFC", p) for p in HOSTILE_NAMES} <= got  # plain hostile names are kept


@pytest.mark.parametrize("case", ["no-matching-files", "only-denied-files", "globs-match-nothing"])
def test_zero_modules_is_a_loud_failure(tmp_path: Path, case: str) -> None:
    # [C6, F5] "did nothing" never exits 0.
    inventory = require("inventory")
    overrides: dict[str, Any] = {"module_globs": ["src/**/*.py"]}
    files: dict[str, str | bytes] = {}
    if case == "only-denied-files":
        files = {"src/backend/.venv/lib/m.py": "x = 1\n", f"src/{TILDE_DOCS_DIR}/p.py": "x = 1\n"}
    if case == "globs-match-nothing":
        files = {"src/backend/app/main.py": "x = 1\n"}
        overrides["module_globs"] = ["nomatch/**/*.py"]
    cfg_path, cfg = write_config(tmp_path, **overrides)
    base: dict[str, str | bytes] = dict(governance_files(cfg))
    base[cfg["canary_fixture"]] = canary_source()
    base.update(files)
    repo = make_repo(tmp_path / "repo", base)
    proc = _run_inventory(repo, cfg_path)
    assert proc.returncode == exit_code(inventory, "NO_MODULES")
    assert b"NO_MODULES" in proc.stdout + proc.stderr


def test_inventory_with_a_bad_config_fails_closed(tmp_path: Path) -> None:
    inventory = require("inventory")
    cfg_path, cfg = write_config(tmp_path)
    repo = _golden_repo(tmp_path, cfg)
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    proc = _run_inventory(repo, bad)
    assert proc.returncode == exit_code(inventory, "CONFIG")
    assert b'"modules"' not in proc.stdout  # no inventory on a bad config
    assert b"CONFIG" in proc.stdout + proc.stderr


def test_support_loader_reports_missing_modules_as_none(tmp_path: Path) -> None:
    # Guards the harness itself: a missing module is None, never an ImportError.
    assert load_audit_module("does_not_exist_for_sure") is None
