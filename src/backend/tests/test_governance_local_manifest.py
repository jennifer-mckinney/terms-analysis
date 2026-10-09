"""Acceptance tests for terms-analysis #200 (G0-6 security regen, finding 5).

Card: the tracked `.claude/_governance-manifest.json` must not publish the
sha256 / size of the owner's private `$HOME/...` files. The `$HOME` entries
move to an UNTRACKED local manifest (gitignored). `verify-hashes.sh`
verifies the local manifest when present and reports it SKIPPED (never
"passed") when absent. `regen-manifest.sh` writes both.

Behaviour over text: every case except the tracked-manifest check runs the
real `scripts/governance/*.sh` inside a throwaway git repo with a fake HOME.
Paths are resolved before any env is altered (AGENT-LANES probes).

Contract values pinned from the card (not product config):
* LOCAL_MANIFEST_REL: the card's local manifest name.
* SKIP_SENTINEL: the wording verify prints when the local manifest is absent.
* CARD_HOME_PATHS: the two private files the card names.
The repo-file list is NOT restated: it is read from the tracked manifest.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TRACKED_MANIFEST_REL = ".claude/_governance-manifest.json"
LOCAL_MANIFEST_REL = ".claude/_governance-manifest.local.json"
LOCAL_MANIFEST_NAME = Path(LOCAL_MANIFEST_REL).name
SKIP_SENTINEL = "LOCAL MANIFEST SKIPPED"
HOME_PREFIX = "$HOME/"
CARD_HOME_PATHS = ("$HOME/.claude/CLAUDE.md", "$HOME/.claude/library/PEAS.md")
GOV_SCRIPTS_REL = "scripts/governance"
GOV_CONFIG_REL = ".claude/governance"

# verify-hashes.sh documented exit codes (scripts/governance/README.md).
EXIT_OK, EXIT_DRIFT, EXIT_MANIFEST, EXIT_MISSING = 0, 1, 2, 3
TIMEOUT_S = 60  # harness bound, not product config


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _tracked_manifest_paths() -> list[str]:
    data = json.loads((REPO_ROOT / TRACKED_MANIFEST_REL).read_text(encoding="utf-8"))
    return [e["path"] for e in data["entries"]]


def _repo_paths() -> list[str]:
    """Repo-relative governance files, derived from the tracked manifest."""
    paths = [p for p in _tracked_manifest_paths() if not p.startswith(HOME_PREFIX)]
    assert paths, "tracked manifest has no repo entries; nothing to verify"
    return paths


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entry(rel: str, path: Path) -> dict[str, object]:
    return {
        "path": rel,
        "sha256": _sha(path),
        "size_bytes": path.stat().st_size,
        "recorded_at": "2026-10-10T00:00:00Z",
        "note": "test fixture",
    }


def _write_manifest(dest: Path, entries: list[dict[str, object]]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps({"schema_version": 1, "generated_at": "2026-10-10T00:00:00Z",
                    "note": "test fixture", "entries": entries}, indent=2) + "\n",
        encoding="utf-8",
    )


def _home_file(home: Path, mpath: str) -> Path:
    return home / mpath[len(HOME_PREFIX):]


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.repo = root / "repo"
        self.home = root / "home"
        self.repo.mkdir()
        self.home.mkdir()
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.home),
            "LANG": "C.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
        }

    @property
    def tracked(self) -> Path:
        return self.repo / TRACKED_MANIFEST_REL

    @property
    def local(self) -> Path:
        return self.repo / LOCAL_MANIFEST_REL

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=self.repo,
                              env=self.env, capture_output=True, text=True,
                              check=True, timeout=TIMEOUT_S)

    def run(self, script: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(self.repo / GOV_SCRIPTS_REL / script), *args],
                              cwd=self.repo, env=self.env, capture_output=True,
                              text=True, timeout=TIMEOUT_S)

    def write_tracked_repo_only(self) -> None:
        _write_manifest(self.tracked, [_entry(p, self.repo / p) for p in _repo_paths()])

    def write_local(self) -> None:
        _write_manifest(self.local, [_entry(p, _home_file(self.home, p)) for p in CARD_HOME_PATHS])


@pytest.fixture
def sb(tmp_path: Path) -> Sandbox:
    s = Sandbox(tmp_path)
    shutil.copytree(REPO_ROOT / GOV_SCRIPTS_REL, s.repo / GOV_SCRIPTS_REL,
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO_ROOT / GOV_CONFIG_REL, s.repo / GOV_CONFIG_REL)
    shutil.copy2(REPO_ROOT / ".gitignore", s.repo / ".gitignore")
    for rel in _repo_paths():
        dest = s.repo / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dest)
    for mpath in CARD_HOME_PATHS:
        f = _home_file(s.home, mpath)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"private fixture for {mpath}\n", encoding="utf-8")
    s.git("init", "-q")
    return s


def _out(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stdout + proc.stderr


def _assert_no_leak(sb: Sandbox, text: str) -> None:
    """F8: no absolute HOME path and no Python traceback in any message."""
    assert str(sb.home) not in text, "output leaks the absolute HOME path"
    assert "Traceback" not in text, f"crash, not an honest message:\n{text}"


# --------------------------------------------------------------------------
# 1. tracked manifest publishes no $HOME entry
# --------------------------------------------------------------------------
def test_tracked_manifest_has_no_home_entries() -> None:
    home = [p for p in _tracked_manifest_paths() if p.startswith(HOME_PREFIX)]
    assert home == [], f"tracked manifest publishes private-file entries: {home}"


def test_tracked_manifest_note_does_not_advertise_home_entries() -> None:
    data = json.loads((REPO_ROOT / TRACKED_MANIFEST_REL).read_text(encoding="utf-8"))
    assert HOME_PREFIX not in json.dumps(data), "tracked manifest still mentions $HOME/ paths"


# --------------------------------------------------------------------------
# 2. local manifest present: verified, drift detected, named in output
# --------------------------------------------------------------------------
def test_verify_with_local_manifest_ok_names_it(sb: Sandbox) -> None:
    sb.write_tracked_repo_only()
    sb.write_local()
    proc = sb.run("verify-hashes.sh")
    out = _out(proc)
    assert proc.returncode == EXIT_OK, out
    assert LOCAL_MANIFEST_NAME in out, f"output does not name the local manifest:\n{out}"
    assert SKIP_SENTINEL not in out, out
    _assert_no_leak(sb, out)


@pytest.mark.parametrize("mpath", CARD_HOME_PATHS)
def test_verify_with_local_manifest_detects_home_drift(sb: Sandbox, mpath: str) -> None:
    sb.write_tracked_repo_only()
    sb.write_local()
    with _home_file(sb.home, mpath).open("a", encoding="utf-8") as fh:
        fh.write("drift\n")
    proc = sb.run("verify-hashes.sh")
    out = _out(proc)
    assert proc.returncode == EXIT_DRIFT, out
    assert mpath in out, f"drift line does not name {mpath}:\n{out}"
    _assert_no_leak(sb, out)


def test_verify_with_local_manifest_home_file_missing_exits_3(sb: Sandbox) -> None:
    sb.write_tracked_repo_only()
    sb.write_local()
    _home_file(sb.home, CARD_HOME_PATHS[0]).unlink()
    proc = sb.run("verify-hashes.sh")
    out = _out(proc)
    assert proc.returncode == EXIT_MISSING, out
    assert CARD_HOME_PATHS[0] in out, out
    _assert_no_leak(sb, out)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"{not json", id="malformed-json"),
        pytest.param(b"", id="empty-file"),
        pytest.param(b'{"schema_version": 1, "entries": []}\n', id="zero-entries"),
        pytest.param(b"\xff\xfe\x00bad", id="invalid-utf8"),
    ],
)
def test_verify_bad_local_manifest_fails_closed(sb: Sandbox, body: bytes) -> None:
    """F4/F5/F13: an unusable local manifest is never a silent pass."""
    sb.write_tracked_repo_only()
    sb.local.parent.mkdir(parents=True, exist_ok=True)
    sb.local.write_bytes(body)
    proc = sb.run("verify-hashes.sh")
    out = _out(proc)
    assert proc.returncode == EXIT_MANIFEST, out
    assert LOCAL_MANIFEST_NAME in out, out
    _assert_no_leak(sb, out)


@pytest.mark.parametrize(
    "sep",
    ["\n", "\r", " ", "\u0085", "|", "\x00"],
    ids=["LF", "CR", "LS", "NEL", "pipe", "NUL"],
)
def test_verify_local_entry_path_cannot_forge_a_second_entry(sb: Sandbox, sep: str) -> None:
    """F1/A: a path carrying a line break or the `|` delimiter must not be
    split into a forged, self-verifying entry; the manifest is rejected."""
    sb.write_tracked_repo_only()
    target = _repo_paths()[0]
    forged = {
        "path": f"{HOME_PREFIX}nonexistent{sep}{target}",
        "sha256": _sha(sb.repo / target),
        "size_bytes": (sb.repo / target).stat().st_size,
        "recorded_at": "2026-10-10T00:00:00Z",
        "note": "forged",
    }
    _write_manifest(sb.local, [forged])
    proc = sb.run("verify-hashes.sh")
    out = _out(proc)
    assert proc.returncode == EXIT_MANIFEST, out
    _assert_no_leak(sb, out)


# --------------------------------------------------------------------------
# 3. local manifest absent: SKIPPED, exit 0, count = repo entries only
# --------------------------------------------------------------------------
@pytest.mark.parametrize("home_files_present", [True, False], ids=["home-present", "home-empty"])
def test_verify_without_local_manifest_reports_skipped(sb: Sandbox, home_files_present: bool) -> None:
    sb.write_tracked_repo_only()
    if not home_files_present:
        shutil.rmtree(sb.home / ".claude")
    proc = sb.run("verify-hashes.sh")
    out = _out(proc)
    assert proc.returncode == EXIT_OK, out
    assert SKIP_SENTINEL in out, f"absent local manifest not reported as skipped:\n{out}"
    n_repo = len(_repo_paths())
    assert f"HASHES OK: {n_repo} files verified" in out, out
    for mpath in CARD_HOME_PATHS:
        assert mpath not in out.replace(SKIP_SENTINEL, ""), out
    _assert_no_leak(sb, out)


def test_verify_without_local_manifest_still_catches_repo_drift(sb: Sandbox) -> None:
    """Positive control (green today): SKIPPED must not mask tracked drift."""
    sb.write_tracked_repo_only()
    target = sb.repo / _repo_paths()[0]
    target.write_bytes(target.read_bytes() + b"drift\n")
    proc = sb.run("verify-hashes.sh")
    assert proc.returncode == EXIT_DRIFT, _out(proc)


def test_verify_tracked_manifest_with_zero_entries_fails(sb: Sandbox) -> None:
    """Positive control (green today): did-nothing is never success (F5)."""
    _write_manifest(sb.tracked, [])
    sb.write_local()
    proc = sb.run("verify-hashes.sh")
    assert proc.returncode == EXIT_MANIFEST, _out(proc)


# --------------------------------------------------------------------------
# 4. regen --yes writes both manifests, split by prefix; local is gitignored
# --------------------------------------------------------------------------
def _load_paths(path: Path) -> list[str]:
    return [e["path"] for e in json.loads(path.read_text(encoding="utf-8"))["entries"]]


def test_regen_splits_tracked_and_local(sb: Sandbox) -> None:
    proc = sb.run("regen-manifest.sh", "--yes")
    out = _out(proc)
    assert proc.returncode == 0, out
    _assert_no_leak(sb, out)
    tracked = _load_paths(sb.tracked)
    assert sorted(tracked) == sorted(_repo_paths()), tracked
    assert sb.local.is_file(), f"regen did not write {LOCAL_MANIFEST_REL}"
    local_data = json.loads(sb.local.read_text(encoding="utf-8"))
    local = [e["path"] for e in local_data["entries"]]
    assert sorted(local) == sorted(CARD_HOME_PATHS), local
    for e in local_data["entries"]:
        f = _home_file(sb.home, e["path"])
        assert e["sha256"] == _sha(f) and e["size_bytes"] == f.stat().st_size, e
    for path in (sb.tracked, sb.local):
        assert str(sb.home) not in path.read_text(encoding="utf-8"), f"{path.name} leaks absolute HOME"
    roundtrip = sb.run("verify-hashes.sh")
    assert roundtrip.returncode == EXIT_OK, _out(roundtrip)
    assert LOCAL_MANIFEST_NAME in _out(roundtrip), _out(roundtrip)


def test_local_manifest_is_gitignored(sb: Sandbox) -> None:
    sb.local.parent.mkdir(parents=True, exist_ok=True)
    sb.local.write_text("{}\n", encoding="utf-8")
    proc = subprocess.run(["git", "check-ignore", "-q", "--", LOCAL_MANIFEST_REL], cwd=sb.repo,
                          env=sb.env, capture_output=True, timeout=TIMEOUT_S)
    assert proc.returncode == 0, f"{LOCAL_MANIFEST_REL} is not ignored by .gitignore"


# --------------------------------------------------------------------------
# 5. the local manifest is never tracked after a regen
# --------------------------------------------------------------------------
def test_local_manifest_never_tracked_after_regen(sb: Sandbox) -> None:
    proc = sb.run("regen-manifest.sh", "--yes")
    assert proc.returncode == 0, _out(proc)
    assert sb.local.is_file(), f"regen did not write {LOCAL_MANIFEST_REL}"
    sb.git("add", "-A")
    sb.git("commit", "-q", "-m", "regen")
    listed = sb.git("ls-files").stdout.splitlines()
    assert TRACKED_MANIFEST_REL in listed, listed
    assert LOCAL_MANIFEST_REL not in listed, "local manifest became tracked"


def test_real_repo_does_not_track_local_manifest() -> None:
    """Positive control (green today): guard on the real tree."""
    out = subprocess.run(["git", "ls-files", "--", LOCAL_MANIFEST_REL], cwd=REPO_ROOT,
                         capture_output=True, text=True, check=True, timeout=TIMEOUT_S).stdout
    assert out == "", out
