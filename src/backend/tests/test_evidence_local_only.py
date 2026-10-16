"""Acceptance tests for terms-analysis #367: docs/evidence/ stays local only.

Card scope (issue #367):

1. Untrack the 9 files under docs/evidence/ (``git ls-files docs/evidence`` empty).
2. ``.gitignore`` ignores docs/evidence/ (any extension, any depth).
3. ``.claude/governance/required-gitignore.txt`` lists it, so the pre-commit
   hook (check 1) and the gitignore-enforcement workflow both require it.
4. The CI evidence-leak-scan job stays as the backstop for force-adds.
5. No doc or agent brief in the repo tells agents to commit evidence.
6. (#125, owner 2026-10-15 "Teach CI the waiver") the range step skips
   exactly the full commit ids in the monorepo conf's waived_history_commits,
   and fails closed on a malformed waiver.

Behaviour over text: the hook cases run the real ``.githooks/pre-commit`` and
the CI cases run the real ``run:`` steps of the workflows, through the #145
harness in ``test_precommit_guards`` (reused, not copied). ``git
check-ignore`` and ``git add -A`` run in a throwaway repo holding only the
repo's tracked ``.gitignore`` files, with the global excludes file disabled,
so a developer's local excludes can never make these tests pass (F7).

F13: required patterns are read from the required-gitignore SSoT. The one
literal, ``EVIDENCE_DIR``, is the value the card names; a cross-check pins the
hook and the scanner to the same directory (F10).

Governance manifest: the coder's edit to required-gitignore.txt changes a file
hashed in ``.claude/_governance-manifest.json``. No test here touches or checks
the manifest; the regen needs owner approval.
"""
# Fixtures imported from the #145 harness are requested by parameter name,
# which linters read as redefinitions of the import (F811).
# ruff: noqa: F811

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from tests.test_monorepo_import import (  # noqa: F401  (real_repo is a fixture)
    CONFIG_REL,
    WAIVER_KEY,
    ConfigError,
    Repo,
    load_config,
    parse_config,
    real_repo,
)
from tests.test_precommit_guards import (  # noqa: F401  (sandbox is a fixture)
    GITIGNORE_FILE,
    GOV_DIR,
    HOOK_TIMEOUT_S,
    LEAK,
    REFUSED,
    REPO_ROOT,
    REQUIRED_GITIGNORE_FILE,
    SCRIPTS_DIR,
    _ci_tree,
    _copy_tracked,
    _env,
    _err,
    _git,
    _install,
    _load_ssot_lines,
    _run_hook,
    _run_workflow,
    _stage,
    _write,
    sandbox,
)

# The directory the card names. Cross-checked against the hook and the scanner.
EVIDENCE_DIR = "docs/evidence/"

# The 9 files the card lists as still tracked on main.
CARD_TRACKED_FILES = (
    "01-app-homepage.png",
    "2026-10-07-g0-5-r2-red.txt",
    "2026-10-07-g0-5-red.txt",
    "2026-10-07-g0-6-red.txt",
    "phase5d_flow1_for_child.png",
    "phase5d_flow1b_for_child_stop_variant.png",
    "phase5d_flow2_for_work.png",
    "phase5d_intake_clean.png",
    "phase5d_intake_default.png",
)

HOOK_FILE = REPO_ROOT / ".githooks" / "pre-commit"
SCANNER_FILE = REPO_ROOT / "scripts" / "governance" / "scan-evidence-leaks.sh"
CI_FILE = REPO_ROOT / ".github" / "workflows" / "ci.yml"
EVIDENCE_JOB = "evidence-scan"
# The check name LIB-PRINCIPLES lists for branch protection; renaming it
# silently drops a (planned) required check.
EVIDENCE_JOB_NAME = "Evidence leak scan (docs/evidence)"
MISSING_PATTERN_MSG = "missing required pattern: `{}`"


def _strip_cf(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def _under_evidence(path: str) -> bool:
    """True when a repo path sits under docs/evidence/.

    Case-folded (macOS checkouts are case-insensitive, so Docs/Evidence/ is
    the same folder), NFC-normalised and with Cf characters removed.
    """
    norm = unicodedata.normalize("NFC", _strip_cf(path)).casefold()
    return norm.startswith(EVIDENCE_DIR.casefold())


UNDER_EVIDENCE_VECTORS = [
    ("docs/evidence/a.md", True),
    ("docs/evidence/sub/dir/a.png", True),
    ("Docs/Evidence/a.md", True),
    ("DOCS/EVIDENCE/A.TXT", True),
    ("docs/evi​dence/a.md", True),
    ("docs/evidence⁠/a.md", True),
    ("docs/evidence.md", False),
    ("docs/evidence-archive/a.md", False),
    ("src/docs/evidence/a.md", False),
    ("docs/plans/evidence.md", False),
]


@pytest.mark.parametrize("path,expected", UNDER_EVIDENCE_VECTORS, ids=[ascii(p) for p, _ in UNDER_EVIDENCE_VECTORS])
def test_under_evidence_classifier_vectors(path: str, expected: bool) -> None:
    """Green today: the classifier the tracked-tree tests rely on."""
    assert _under_evidence(path) is expected


def test_under_evidence_vectors_have_both_outcomes() -> None:
    assert {e for _, e in UNDER_EVIDENCE_VECTORS} == {True, False}


# ==========================================================================
# 1. Nothing under docs/evidence/ is tracked (index or HEAD tree)
# ==========================================================================
def _git_paths(*args: str) -> list[str]:
    raw = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, check=True,
                         timeout=HOOK_TIMEOUT_S).stdout
    return [os.fsdecode(rec) for rec in raw.split(b"\0") if rec]


TRACKED_SOURCES = {
    "index": ("ls-files", "-z"),
    "head-tree": ("ls-tree", "-r", "-z", "--name-only", "HEAD"),
}


@pytest.mark.parametrize("source", TRACKED_SOURCES.keys())
def test_nothing_tracked_under_docs_evidence(source: str) -> None:
    """Red today: the 9 card files are tracked in the index and in HEAD."""
    paths = _git_paths(*TRACKED_SOURCES[source])
    assert paths, f"git {source} listed no files: the check would attest nothing"
    offenders = sorted(p for p in paths if _under_evidence(p))
    assert offenders == [], f"{len(offenders)} path(s) under {EVIDENCE_DIR} tracked in {source}: {offenders[:10]}"


@pytest.mark.parametrize("name", CARD_TRACKED_FILES)
def test_card_file_is_untracked(name: str) -> None:
    """Red today, one per file the card lists."""
    rel = EVIDENCE_DIR + name
    assert _git_paths("ls-files", "-z", "--", rel) == [], f"{rel} is still tracked"
    assert _git_paths("ls-tree", "-r", "-z", "--name-only", "HEAD", "--", rel) == [], f"{rel} is still in HEAD"


# ==========================================================================
# 2. .gitignore ignores docs/evidence/ (check-ignore and `git add -A`)
# ==========================================================================
IGNORED_SAMPLES = [
    EVIDENCE_DIR + "x.md",
    EVIDENCE_DIR + "x.txt",
    EVIDENCE_DIR + "x.png",
    EVIDENCE_DIR + "x.log",  # green today (*.log)
    EVIDENCE_DIR + "X.PNG",
    EVIDENCE_DIR + "noext",
    EVIDENCE_DIR + ".hidden.md",
    EVIDENCE_DIR + "-n.md",  # option-like name
    EVIDENCE_DIR + "2026-10-12 status.md",
    EVIDENCE_DIR + "café-résumé.md",
    EVIDENCE_DIR + "line\nbreak.md",
    EVIDENCE_DIR + "sub/deep/x.md",
]
# Must stay NOT ignored: the entry is anchored to the repo root and the folder
# name, so it cannot swallow siblings or other "evidence" folders.
NOT_IGNORED_SAMPLES = [
    "docs/evidence.md",
    "docs/evidence-archive/x.md",
    "src/docs/evidence/x.md",
    "docs/research/evidence/x.md",
    "docs/plans/x.md",
]


def _ignore_repo(tmp_path: Path) -> Path:
    """Throwaway repo with every tracked .gitignore and nothing else."""
    repo = tmp_path / "ign"
    repo.mkdir()
    _git(repo, "init", "-q")
    rels = _git_paths("ls-files", "-z", "--", ":(glob)**/.gitignore")
    assert ".gitignore" in rels, "root .gitignore is not tracked"
    for rel in rels:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, repo / rel)
    for rel in IGNORED_SAMPLES + NOT_IGNORED_SAMPLES:
        _write(repo, rel, "sample\n")
    return repo


def _git_local(repo: Path, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    # core.excludesFile=devnull: the default XDG ignore file is read even with
    # GIT_CONFIG_GLOBAL unset, and would let a local exclude fake a pass (F7).
    return subprocess.run(["git", "-c", "core.excludesFile=" + os.devnull, *args], cwd=repo, env=_env(),
                          input=stdin, capture_output=True, timeout=HOOK_TIMEOUT_S)


def _ignore_matches(repo: Path, paths: list[str]) -> dict[str, str | None]:
    """path -> 'source:line:pattern' of the ignoring rule, or None."""
    stdin = b"".join(os.fsencode(p) + b"\0" for p in paths)
    proc = _git_local(repo, "check-ignore", "--no-index", "-v", "-n", "-z", "--stdin", stdin=stdin)
    assert proc.returncode in (0, 1), _err(proc)
    fields = proc.stdout.split(b"\0")
    assert fields[-1] == b"" and (len(fields) - 1) % 4 == 0, "unparseable check-ignore output"
    out: dict[str, str | None] = {}
    for i in range(0, len(fields) - 1, 4):
        src, line, pat, path = fields[i:i + 4]
        ignored = bool(src) and not pat.startswith(b"!")
        out[os.fsdecode(path)] = f"{os.fsdecode(src)}:{os.fsdecode(line)}:{os.fsdecode(pat)}" if ignored else None
    assert sorted(out) == sorted(paths), "check-ignore did not answer for every path"
    return out


@pytest.mark.parametrize("path", IGNORED_SAMPLES, ids=[ascii(p) for p in IGNORED_SAMPLES])
def test_check_ignore_matches_evidence_sample(tmp_path: Path, path: str) -> None:
    """Red today for every sample except *.log: only *.log is ignored."""
    match = _ignore_matches(_ignore_repo(tmp_path), [path])[path]
    assert match is not None, f"{ascii(path)} is not ignored by the repo .gitignore files"


@pytest.mark.parametrize("path", NOT_IGNORED_SAMPLES)
def test_check_ignore_does_not_overreach(tmp_path: Path, path: str) -> None:
    """Green today (control): the entry must not swallow neighbouring paths."""
    assert _ignore_matches(_ignore_repo(tmp_path), [path])[path] is None, f"{path} is ignored"


def test_git_add_all_stages_no_evidence(tmp_path: Path) -> None:
    """Card impact: `git add -A` cannot stage local evidence. Red today."""
    repo = _ignore_repo(tmp_path)
    proc = _git_local(repo, "add", "-A")
    assert proc.returncode == 0, _err(proc)
    staged = [os.fsdecode(p) for p in _git_local(repo, "diff", "--cached", "--name-only", "-z").stdout.split(b"\0") if p]
    # Positive attestation: the control file was staged, so `add -A` did run.
    assert "docs/plans/x.md" in staged, f"control file not staged: {staged}"
    leaked = sorted(ascii(p) for p in staged if _under_evidence(p))
    assert leaked == [], f"git add -A staged {len(leaked)} evidence file(s): {leaked}"


# ==========================================================================
# 3. The required-gitignore SSoT requires it; hook and workflow enforce it
# ==========================================================================
def test_required_gitignore_ssot_lists_evidence_dir() -> None:
    """Red today: the SSoT both enforcers read does not list the entry."""
    assert EVIDENCE_DIR in _load_ssot_lines(REQUIRED_GITIGNORE_FILE)


def _gitignore_with(line: str | None) -> str:
    """The real .gitignore with every docs/evidence line replaced by `line`."""
    kept = [raw for raw in GITIGNORE_FILE.read_text(encoding="utf-8").splitlines()
            if EVIDENCE_DIR.rstrip("/") not in raw.casefold()]
    if line is not None:
        kept.append(line)
    return "\n".join(kept) + "\n"


# Lines that do NOT satisfy the requirement: the enforcers match exact lines.
HOSTILE_GITIGNORE_LINES: dict[str, str | None] = {
    "absent": None,
    "commented": "# " + EVIDENCE_DIR,
    "negated": "!" + EVIDENCE_DIR,
    "no-trailing-slash": EVIDENCE_DIR.rstrip("/"),
    "indented": "  " + EVIDENCE_DIR,
    "trailing-cr": EVIDENCE_DIR + "\r",
    "nbsp-suffix": EVIDENCE_DIR + " ",
    "line-separator-suffix": EVIDENCE_DIR + " ",
    "zwsp-inside": EVIDENCE_DIR[:8] + "​" + EVIDENCE_DIR[8:],
    "fullwidth-solidus": EVIDENCE_DIR.replace("/", "／", 1),
}
HOSTILE_CHARS = ("\r", " ", " ", "​", "／")


def _assert_missing_refusal(out: str) -> None:
    assert MISSING_PATTERN_MSG.format(EVIDENCE_DIR) in out, f"no missing-pattern refusal: {out[-600:]!r}"
    echoed = [ascii(c) for c in HOSTILE_CHARS if c in out]
    assert echoed == [], f"refusal echoes raw hostile characters {echoed} (F2/F8)"


def _clean_stage(repo: Path) -> None:
    _write(repo, "c.md", "clean\n")
    _stage(repo, "c.md")


@pytest.mark.parametrize("line", HOSTILE_GITIGNORE_LINES.values(), ids=HOSTILE_GITIGNORE_LINES.keys())
def test_precommit_refuses_gitignore_without_evidence_dir(sandbox: Path, line: str | None) -> None:
    """Red today: check 1 does not require the entry, so the hook exits 0."""
    (sandbox / ".gitignore").write_text(_gitignore_with(line), encoding="utf-8", newline="")
    _clean_stage(sandbox)
    proc = _run_hook(sandbox)
    assert proc.returncode == REFUSED, f"hook accepted .gitignore line {ascii(line)}: {_err(proc)[-600:]!r}"
    _assert_missing_refusal(_err(proc))


def test_precommit_accepts_exact_evidence_line(sandbox: Path) -> None:
    """Green today (positive control): the exact entry passes check 1."""
    (sandbox / ".gitignore").write_text(_gitignore_with(EVIDENCE_DIR), encoding="utf-8")
    _clean_stage(sandbox)
    proc = _run_hook(sandbox)
    assert proc.returncode == 0, _err(proc)[-600:]


def test_installed_hook_blocks_real_commit_without_evidence_dir(sandbox: Path) -> None:
    """F12: the requirement bites through the installed hooksPath. Red today."""
    _install(sandbox)
    (sandbox / ".gitignore").write_text(_gitignore_with(None), encoding="utf-8")
    _write(sandbox, "doc.md", "clean\n")
    _stage(sandbox, ".gitignore", ".claude", ".githooks", "scripts", "doc.md")
    proc = _git(sandbox, "commit", "-q", "-m", "drop evidence ignore", check=False)
    assert proc.returncode != 0, "commit without the docs/evidence/ entry went through"
    assert _git(sandbox, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode != 0, "a commit was created"
    _assert_missing_refusal(_err(proc))


@pytest.mark.parametrize("line", HOSTILE_GITIGNORE_LINES.values(), ids=HOSTILE_GITIGNORE_LINES.keys())
def test_ci_gitignore_workflow_refuses_without_evidence_dir(tmp_path: Path, line: str | None) -> None:
    """Red today: the workflow's presence step does not require the entry."""
    ok, log = _run_workflow(_ci_tree(tmp_path, {".gitignore": _gitignore_with(line)}))
    assert not ok, f"gitignore-enforcement passed .gitignore line {ascii(line)}"
    _assert_missing_refusal(log)


def test_ci_gitignore_workflow_accepts_exact_evidence_line(tmp_path: Path) -> None:
    """Green today (positive control)."""
    ok, log = _run_workflow(_ci_tree(tmp_path, {".gitignore": _gitignore_with(EVIDENCE_DIR)}))
    assert ok, log[-2000:]


# ==========================================================================
# 4. Backstop: the CI evidence-leak-scan job still runs and still bites
# ==========================================================================
_EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


def _ci() -> dict[str, Any]:
    return yaml.safe_load(CI_FILE.read_text(encoding="utf-8"))


def test_ci_evidence_scan_job_is_pinned() -> None:
    """Green today: the job exists, keeps its check name and cannot be skipped."""
    ci = _ci()
    on = ci.get("on", ci.get(True))
    assert on["pull_request"]["branches"] == ["main"], on
    job = ci["jobs"][EVIDENCE_JOB]
    assert job["name"] == EVIDENCE_JOB_NAME
    assert "if" not in job and "continue-on-error" not in job, "evidence-scan job can be skipped"
    gated = [s.get("name") for s in job["steps"] if "if" in s or "continue-on-error" in s]
    assert gated == [], f"evidence-scan steps can be skipped: {gated}"


TIP_SCAN_RUN = 'bash scripts/governance/scan-evidence-leaks.sh "${GITHUB_WORKSPACE}"'


def _run_evidence_job(tree: Path, ctx: dict[str, str], *, tip: bool = True) -> list[tuple[str, int, str]]:
    """Run the real `run:` steps of ci.yml's evidence-scan job in `tree`.
    tip=False drops the tip-scan step (the real checkout has untracked evidence)."""
    def resolve(m: re.Match[str]) -> str:
        assert m.group(1) in ctx, f"evidence-job harness: unsupported expression {m.group(1)!r}"
        return ctx[m.group(1)]

    run_steps = [s for s in _ci()["jobs"][EVIDENCE_JOB]["steps"] if "run" in s]
    assert len(run_steps) >= 2, f"evidence-scan has {len(run_steps)} run step(s); tip and range scans expected"
    if not tip:
        run_steps = [s for s in run_steps if s["run"].strip() != TIP_SCAN_RUN]
    results: list[tuple[str, int, str]] = []
    for step in run_steps:
        env = _env({"GITHUB_WORKSPACE": str(tree), "GITHUB_ACTIONS": "true", "CI": "true"})
        for k, v in (step.get("env") or {}).items():
            env[k] = _EXPR.sub(resolve, str(v))
        proc = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", _EXPR.sub(resolve, step["run"])],
                              cwd=tree, env=env, capture_output=True, timeout=HOOK_TIMEOUT_S)
        results.append((str(step.get("name")), proc.returncode, _err(proc)))
        if proc.returncode != 0:  # Actions stops the job at the first failing step
            break
    return results


def _scan_repo(tmp_path: Path, files: dict[str, bytes]) -> Path:
    tree = tmp_path / "ci"
    tree.mkdir()
    shutil.copy2(GITIGNORE_FILE, tree / ".gitignore")
    _copy_tracked(GOV_DIR, tree)
    _copy_tracked(SCRIPTS_DIR, tree)
    for rel, data in files.items():
        _write(tree, rel, data)
    _git(tree, "init", "-q")
    _git(tree, "add", "-f", "-A")
    _commit(tree, "base")
    return tree


def _commit(tree: Path, msg: str) -> str:
    _git(tree, "-c", "core.hooksPath=" + os.devnull, "commit", "-q", "--allow-empty", "-m", msg)
    return _git(tree, "rev-parse", "HEAD").stdout.decode().strip()


def _pr_ctx(base: str, head: str) -> dict[str, str]:
    return {
        "github.event_name": "pull_request",
        "github.event.pull_request.base.sha": base,
        "github.event.pull_request.head.sha": head,
        "github.event.before": "",
        "github.sha": head,
    }


FORCE_ADDED = {
    "md": ("cd " + LEAK + "\n").encode(),
    "txt": ("E " + LEAK + "/app.py\n").encode(),
    "png": b"\x89PNG\r\n\x1a\n\x00\x00" + LEAK.encode() + b"\x00\n",
}


@pytest.mark.parametrize("ext", FORCE_ADDED.keys())
def test_ci_evidence_scan_blocks_force_added_leak(tmp_path: Path, ext: str) -> None:
    """Green today: a force-added evidence file with a home path fails the tip scan."""
    tree = _scan_repo(tmp_path, {})
    base = _git(tree, "rev-parse", "HEAD").stdout.decode().strip()
    rel = f"{EVIDENCE_DIR}run.{ext}"
    _write(tree, rel, FORCE_ADDED[ext])
    _git(tree, "add", "-f", "--", rel)
    head = _commit(tree, "force-add evidence")
    results = _run_evidence_job(tree, _pr_ctx(base, head))
    # The tip step itself must bite (the range step is a second, separate net).
    assert len(results) == 1, f"tip step did not stop the job: {results}"
    name, rc, out = results[0]
    assert rc == 1, f"step {name!r} rc={rc}: {out[-600:]!r}"
    assert f"LEAK: {rel} " in out, f"refusal does not name {rel}: {out[-600:]!r}"
    assert LEAK not in out, "CI output re-leaks the home path (F8)"


def test_ci_evidence_scan_range_catches_leak_added_then_removed(tmp_path: Path) -> None:
    """Green today: the range step catches a force-add scrubbed before the tip."""
    tree = _scan_repo(tmp_path, {})
    base = _git(tree, "rev-parse", "HEAD").stdout.decode().strip()
    rel = EVIDENCE_DIR + "run.md"
    _write(tree, rel, FORCE_ADDED["md"])
    _git(tree, "add", "-f", "--", rel)
    leak_sha = _commit(tree, "leak")
    _git(tree, "rm", "-q", "--", rel)
    head = _commit(tree, "scrub")
    results = _run_evidence_job(tree, _pr_ctx(base, head))
    assert results[0][1] == 0, results[0]  # the tip is clean
    name, rc, out = results[-1]
    assert rc == 1, f"step {name!r} rc={rc}: {out[-600:]!r}"
    assert f"LEAK (history): {leak_sha[:7]} {rel}" in out, out[-600:]
    assert LEAK not in out, "CI output re-leaks the home path (F8)"


def test_ci_evidence_scan_passes_on_card_untrack(tmp_path: Path) -> None:
    """Green today (positive control): the #367 change itself keeps the job green.

    Base tracks clean evidence; the PR commit untracks it and the CI checkout
    then has no docs/evidence/ at all. Both steps pass with honest counts.
    """
    files = {EVIDENCE_DIR + n: b"clean <repo>/x\n" for n in ("a.txt", "b.png")}
    tree = _scan_repo(tmp_path, files)
    base = _git(tree, "rev-parse", "HEAD").stdout.decode().strip()
    _git(tree, "rm", "-q", "-r", "--cached", "--", EVIDENCE_DIR)
    shutil.rmtree(tree / EVIDENCE_DIR)  # a fresh CI checkout has no untracked files
    head = _commit(tree, "untrack evidence")
    results = _run_evidence_job(tree, _pr_ctx(base, head))
    assert [rc for _, rc, _ in results] == [0] * len(results), results
    assert "no docs/evidence/ directory; scanned 0 files" in results[0][2], results[0][2]
    assert "1 commit(s) touching docs/evidence/, 0 added line(s)" in results[-1][2], results[-1][2]


# --------------------------------------------------------------------------
# 4b. #125: the range step honours waived_history_commits, exactly
# --------------------------------------------------------------------------
# PR 1 imports ingester history in which three commits added a local path
# under docs/evidence/. The conf lists their full ids; the range step must skip
# exactly those commits, name each one it skipped (no silent pass, F5), still
# fail every other leaking commit, and refuse a waiver it cannot parse.
RANGE_CLEAN = "no local machine paths"  # the scanner's range success sentinel
IMPORT_GUARD_PY = SCRIPTS_DIR / "governance" / "import_guard.py"


def _push_ctx(base: str, head: str) -> dict[str, str]:
    return {
        "github.event_name": "push",
        "github.event.pull_request.base.sha": "",
        "github.event.pull_request.head.sha": "",
        "github.event.before": base,
        "github.sha": head,
    }


EVENT_CTX = {"pull_request": _pr_ctx, "push": _push_ctx}


TIP_KEY = "ingester_tip"  # the pinned import every waived commit must sit under


def _conf_with(waiver: list[bytes] | None, tip: str | None = None) -> bytes:
    """The real conf with its waiver line(s) replaced; None drops the key.

    `tip` re-pins ingester_tip (a sandbox has none of the real ids); every
    other key keeps the real conf's value."""
    lines = [ln for ln in (REPO_ROOT / CONFIG_REL).read_bytes().split(b"\n")
             if not ln.startswith(WAIVER_KEY.encode() + b"=")]
    if tip is not None:
        key = TIP_KEY.encode() + b"="
        assert sum(ln.startswith(key) for ln in lines) == 1, f"{CONFIG_REL} has no single {TIP_KEY}"
        lines = [key + tip.encode() if ln.startswith(key) else ln for ln in lines]
    body = b"\n".join(ln for ln in lines if ln) + b"\n"
    return body + b"".join(WAIVER_KEY.encode() + b"=" + w + b"\n" for w in (waiver or []))


def _filler(n: int) -> list[str]:
    """n full ids that name no commit in any sandbox (derived, not literals)."""
    return [hashlib.sha1(f"filler-{i}".encode()).hexdigest() for i in range(n)]


ConfBuilder = Callable[[dict[str, str], str], "bytes | None"]
TIP = "@tip"  # label of the last commit before the conf commit (the sandbox import tip)


def _waiving(*labels: str) -> ConfBuilder:
    """The real conf, waiving the commits of `labels` by full id, with
    ingester_tip pinned to the sandbox import tip (every step under it)."""
    return lambda shas, base: _conf_with([" ".join(shas[label] for label in labels).encode()], shas[TIP])


def _waiver_history(tmp_path: Path, steps: list[str], conf: ConfBuilder) -> tuple[Path, str, dict[str, str]]:
    """Sandbox history: base, one commit per step, a tip scrub, then the conf.

    "leak:<file>" adds docs/evidence/<file> with a home path; "clean:<file>"
    adds it with clean text; "scrub" removes docs/evidence/; "side" makes a
    commit off HEAD that HEAD never reaches (an unmerged tip); "chain:<n>"
    adds n empty commits in one fast-import and records their ids, space
    separated, under its label. A "#n" suffix
    makes a repeated step a distinct label. shas[TIP] is the commit before the
    conf commit. `conf(shas, base)` gives the head's conf bytes (None deletes
    the file); the PR head carries it, as in PR 1. Returns (tree, base,
    {label: full sha}).
    """
    tree = _scan_repo(tmp_path, {})
    base = _head(tree)
    shas: dict[str, str] = {}
    for step in steps:
        assert step not in shas, f"duplicate step label {step}"
        kind, _, name = step.partition(":")
        if kind == "chain":
            shas[step] = " ".join(_chain(tree, int(name.split("#")[0])))
            continue
        if kind.startswith("side"):
            shas[step] = _git(tree, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", step).stdout.decode().strip()
            continue
        if kind.startswith("scrub"):
            _git(tree, "rm", "-q", "-r", "--", EVIDENCE_DIR)
        else:
            rel = EVIDENCE_DIR + name.split("#")[0]
            _write(tree, rel, FORCE_ADDED["md"] if kind == "leak" else b"clean <repo>/x\n")
            _git(tree, "add", "-f", "--", rel)
        shas[step] = _commit(tree, step)
    if _git(tree, "ls-files", "--", EVIDENCE_DIR).stdout:
        _git(tree, "rm", "-q", "-r", "--", EVIDENCE_DIR)
        _commit(tree, "scrub tip")
    shas[TIP] = _head(tree)
    data = conf(shas, base)
    if data is None:
        _git(tree, "rm", "-q", "--", CONFIG_REL)
    else:
        _write(tree, CONFIG_REL, data)
        _git(tree, "add", "-f", "--", CONFIG_REL)
    _commit(tree, "conf")
    return tree, base, shas


def _chain(tree: Path, n: int) -> list[str]:
    """n empty commits on the current branch, in one fast-import (F6: size
    without n processes). Same tree as HEAD, so the checkout is unchanged."""
    branch = _git(tree, "symbolic-ref", "HEAD").stdout.decode().strip()
    parent = _head(tree)
    stream = "".join(
        f"commit {branch}\nmark :{i + 1}\ncommitter t <t@example.invalid> 0 +0000\ndata 6\nchain\n"
        + (f"from {parent}\n" if i == 0 else "") + "\n"
        for i in range(n))
    marks = tree.parent / "chain.marks"
    subprocess.run(["git", "-C", str(tree), "fast-import", "--quiet", f"--export-marks={marks}"],
                   input=stream.encode(), check=True, capture_output=True)
    ids: dict[int, str] = {}
    for ln in marks.read_text().splitlines():
        mark, sha = ln.split(" ")
        ids[int(mark[1:])] = sha
    assert len(ids) == n and _head(tree) == ids[n], "fast-import did not extend the branch"
    return [ids[i + 1] for i in range(n)]


def _head(tree: Path) -> str:
    return _git(tree, "rev-parse", "HEAD").stdout.decode().strip()


def _range_out(results: list[tuple[str, int, str]]) -> tuple[int, str]:
    assert results and all(rc == 0 for _, rc, _ in results[:-1]), results
    return results[-1][1], results[-1][2]


def _assert_safe(out: str) -> None:
    assert LEAK not in out, "CI output re-leaks the home path (F8)"
    bad = sorted({ch for ch in out if not (" " <= ch <= "~" or ch == "\n")})
    assert bad == [], f"raw non-printable characters in CI output: {[ascii(c) for c in bad]}"


@pytest.mark.parametrize("event", EVENT_CTX)
def test_ci_range_skips_a_waived_commit(tmp_path: Path, event: str) -> None:
    """RED today: the only leaking commit is waived by full id, so the range
    step passes with its clean sentinel and names the commit it skipped."""
    tree, base, shas = _waiver_history(tmp_path, ["leak:run.md", "scrub"], _waiving("leak:run.md"))
    rc, out = _range_out(_run_evidence_job(tree, EVENT_CTX[event](base, _head(tree))))
    assert rc == 0, f"waived commit still fails the range step (rc={rc}): {out[-600:]!r}"
    assert RANGE_CLEAN in out, out[-600:]
    assert shas["leak:run.md"][:7] in out, f"range step does not name the waived commit: {out[-600:]!r}"
    _assert_safe(out)


@pytest.mark.parametrize("order", ["unwaived-first", "unwaived-last"])
def test_ci_range_still_fails_an_unwaived_leak(tmp_path: Path, order: str) -> None:
    """RED today (the waived commit is still reported): waiving one commit
    skips it and leaves every other leaking commit in the range failing,
    before or after it."""
    waived, other = ["leak:waived.md", "scrub#1"], ["leak:other.md", "scrub#2"]
    steps = other + waived if order == "unwaived-first" else waived + other
    tree, base, shas = _waiver_history(tmp_path, steps, _waiving("leak:waived.md"))
    rc, out = _range_out(_run_evidence_job(tree, _pr_ctx(base, _head(tree))))
    assert rc == 1, f"rc={rc}: {out[-600:]!r}"
    assert f"LEAK (history): {shas['leak:other.md'][:7]} {EVIDENCE_DIR}other.md" in out, out[-600:]
    assert f"LEAK (history): {shas['leak:waived.md'][:7]} " not in out, "waived commit still reported"
    assert RANGE_CLEAN not in out
    _assert_safe(out)


def test_ci_range_waiver_does_not_cover_a_replayed_line(tmp_path: Path) -> None:
    """RED today (the waived commit is still reported): the waiver names a
    commit, not a line; a later commit re-adding the same leaking line to the
    same file still fails."""
    steps = ["leak:run.md", "scrub", "leak:run.md#again", "scrub#again"]
    tree, base, shas = _waiver_history(tmp_path, steps, _waiving("leak:run.md"))
    rc, out = _range_out(_run_evidence_job(tree, _pr_ctx(base, _head(tree))))
    assert rc == 1, f"rc={rc}: {out[-600:]!r}"
    assert f"LEAK (history): {shas['leak:run.md#again'][:7]} {EVIDENCE_DIR}run.md" in out, out[-600:]
    assert f"LEAK (history): {shas['leak:run.md'][:7]} " not in out, "waived commit still reported"


def test_ci_range_waives_among_many_entries(tmp_path: Path) -> None:
    """RED today (F6, size): the waived id buried among thousands of other
    waived full ids, before and after it, is still matched and skipped. The
    others are real commits under ingester_tip, so the bound waiver accepts
    every one (a made-up id would rightly fail closed)."""
    steps = ["chain:1000#a", "leak:run.md", "chain:1000#b", "scrub"]
    def conf(shas: dict[str, str], base: str) -> bytes:
        ids = [shas["chain:1000#a"], shas["leak:run.md"], shas["chain:1000#b"]]
        return _conf_with([" ".join(ids).encode()], shas[TIP])

    tree, base, shas = _waiver_history(tmp_path, steps, conf)
    rc, out = _range_out(_run_evidence_job(tree, _pr_ctx(base, _head(tree))))
    assert rc == 0 and RANGE_CLEAN in out, f"rc={rc}: {out[-600:]!r}"
    assert shas["leak:run.md"][:7] in out
    _assert_safe(out)


# name -> waiver line(s) built from (subject commit, another full id). Every
# entry is malformed: a short or prefix id, a revision expression, a bad
# separator, a hostile character or a duplicate. Built from the commits under
# test, so a prefix-matching or lenient reader would waive the subject.
def _malformed_waivers(s: str, o: str) -> dict[str, list[bytes]]:
    e = str.encode
    return {
        "short-7": [e(s[:7])],
        "short-12": [e(s[:12])],
        "prefix-39": [e(s[:39])],
        "uppercase": [e(s.upper())],
        "hex-41": [e(s + "0")],
        "sha256-length": [e(s + "0" * 24)],
        "caret-rev": [e("^" + s)],
        "rev-range": [e(f"{o}..{s}")],
        "symbolic-head": [b"HEAD"],
        "glob": [b"*"],
        "double-space": [e(f"{s}  {o}")],
        "leading-space": [e(f" {s}")],
        "trailing-space": [e(f"{s} ")],
        "comma": [e(f"{s},{o}")],
        "tab": [e(f"{s}\t{o}")],
        "cr": [e(f"{s}\r")],
        "nul": [e(f"{s}\0")],
        "nbsp": [f"{s}\u00a0{o}".encode()],
        "zwsp": [f"{s}\u200b".encode()],
        "bom": [f"\ufeff{s}".encode()],
        "cyrillic-a": [f"{s[:-1]}\u0430".encode()],
        "fullwidth-digit": [f"{s[:-1]}\uff10".encode()],
        "lone-surrogate": [f"{s}\ud800".encode("utf-8", "surrogatepass")],
        "invalid-utf8": [e(s) + b"\xff"],
        "duplicate-id": [e(f"{s} {s}")],
        "duplicate-key": [e(s), e(o)],
    }


MALFORMED_NAMES = tuple(_malformed_waivers("0" * 40, "1" * 40))
VALID_WAIVERS = {
    "single": lambda s, o: [s.encode()],
    "two": lambda s, o: [f"{o} {s}".encode()],
    "many": lambda s, o: [" ".join(_filler(50) + [s]).encode()],
}


def _import_guard() -> Any:
    spec = importlib.util.spec_from_file_location("import_guard_for_125_waiver", IMPORT_GUARD_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # its dataclasses resolve their module by name
    spec.loader.exec_module(mod)
    return mod


def test_waiver_vectors_contract(tmp_path: Path) -> None:
    """Contract, green today: both conf readers refuse every malformed vector
    and accept every valid one, on the conf's own waived ids (F13: read, not
    restated), so the CI step has a reader to agree with."""
    cfg = load_config()
    assert cfg.waived_history_commits, f"{CONFIG_REL} waives nothing; PR 1 needs its waiver"
    s, o = cfg.waived_history_commits[0], cfg.app_anchor
    guard = _import_guard()
    assert set(MALFORMED_NAMES).isdisjoint(VALID_WAIVERS) and MALFORMED_NAMES and VALID_WAIVERS
    bad = _malformed_waivers(s, o)
    assert tuple(bad) == MALFORMED_NAMES
    for name, lines in bad.items():
        data = _conf_with(lines)
        with pytest.raises(ConfigError):
            parse_config(data)
        (tmp_path / "c.conf").write_bytes(data)
        with pytest.raises(guard.Refusal):
            guard.load_conf(tmp_path / "c.conf")
    for name, build in VALID_WAIVERS.items():
        data = _conf_with(build(s, o))
        assert s in parse_config(data).waived_history_commits, name
        (tmp_path / "c.conf").write_bytes(data)
        assert guard.load_conf(tmp_path / "c.conf") is not None, name


@pytest.mark.parametrize("subject", ["leaking", "clean"])
@pytest.mark.parametrize("name", MALFORMED_NAMES)
def test_ci_range_refuses_a_malformed_waiver(tmp_path: Path, name: str, subject: str) -> None:
    """Fail closed. On a leaking range (green today) a short, prefix or
    look-alike id must not waive the leak; on a clean range (RED today) the
    step must still fail and name the key or the conf, never pass a conf it
    cannot parse."""
    step = "leak:run.md" if subject == "leaking" else "clean:run.md"
    def conf(shas: dict[str, str], base: str) -> bytes:
        return _conf_with(_malformed_waivers(shas[step], base)[name], shas[TIP])

    tree, base, _ = _waiver_history(tmp_path, [step, "scrub"], conf)
    results = _run_evidence_job(tree, _pr_ctx(base, _head(tree)))
    rc, out = results[-1][1], "".join(o for _, _, o in results)
    assert rc != 0, f"[{name}] malformed waiver accepted: {out[-600:]!r}"
    assert RANGE_CLEAN not in out, f"[{name}] range reported clean"
    if subject == "clean":  # the refusal says what to fix: the key, or the conf file
        assert WAIVER_KEY in out or CONFIG_REL in out, f"[{name}] refusal names neither: {out[-600:]!r}"
    _assert_safe(out)


@pytest.mark.parametrize("conf", ["key-missing", "key-empty", "file-missing"])
def test_ci_range_without_a_waiver_waives_nothing(tmp_path: Path, conf: str) -> None:
    """Green today: no key, an empty key or no conf at all waives nothing;
    the leaking commit fails the range step."""
    def build(shas: dict[str, str], base: str) -> bytes | None:
        return {"key-missing": _conf_with(None, shas[TIP]), "key-empty": _conf_with([b""], shas[TIP]),
                "file-missing": None}[conf]

    tree, base, shas = _waiver_history(tmp_path, ["leak:run.md", "scrub"], build)
    rc, out = _range_out(_run_evidence_job(tree, _pr_ctx(base, _head(tree))))
    assert rc != 0 and RANGE_CLEAN not in out, f"[{conf}] rc={rc}: {out[-600:]!r}"
    if conf != "file-missing":
        assert f"LEAK (history): {shas['leak:run.md'][:7]} {EVIDENCE_DIR}run.md" in out, out[-600:]
    assert LEAK not in out


@pytest.mark.parametrize("conf", ["key-missing", "key-empty"])
def test_ci_range_without_a_waiver_passes_a_clean_range(tmp_path: Path, conf: str) -> None:
    """Green today (positive control): an absent or empty waiver is not an
    error; a clean range still passes with its sentinel."""
    def build(shas: dict[str, str], base: str) -> bytes:
        return _conf_with(None if conf == "key-missing" else [b""], shas[TIP])

    tree, base, _ = _waiver_history(tmp_path, ["clean:run.md", "scrub"], build)
    results = _run_evidence_job(tree, _pr_ctx(base, _head(tree)))
    assert [rc for _, rc, _ in results] == [0] * len(results), results
    assert RANGE_CLEAN in results[-1][2]


# Lead ruling 2026-10-15 (concern 1): the PR head carries the conf, so a
# waiver is bound to the pinned import. A waived id counts only if it is
# ingester_tip or an ancestor of it, and ingester_tip is in the scanned range.
# A waived id outside the pinned history fails closed and is named; a PR can
# waive its own commit only by re-pinning ingester_tip, which the import guard
# and review see.
OUTSIDE_PIN = {
    # name -> (steps, waived labels); ingester_tip is pinned at "scrub#1"
    "pr-leak-with-import": (["leak:imported.md", "scrub#1", "leak:pr.md", "scrub#2"],
                            ("leak:imported.md", "leak:pr.md")),
    "pr-leak-alone": (["clean:imported.md", "scrub#1", "leak:pr.md", "scrub#2"], ("leak:pr.md",)),
    "pr-clean-commit": (["clean:imported.md", "scrub#1", "clean:pr.md", "scrub#2"],
                        ("clean:imported.md", "clean:pr.md")),
}


@pytest.mark.parametrize("name", OUTSIDE_PIN)
def test_ci_range_refuses_a_waiver_outside_the_pinned_import(tmp_path: Path, name: str) -> None:
    """RED today: a commit authored in the PR range, after ingester_tip,
    listed in the waiver fails closed (rc != 0, no clean sentinel) and is
    named, whether or not it leaks. Without the ancestry check a PR could
    waive its own leak."""
    steps, waived = OUTSIDE_PIN[name]
    def conf(shas: dict[str, str], base: str) -> bytes:
        return _conf_with([" ".join(shas[label] for label in waived).encode()], shas["scrub#1"])

    tree, base, shas = _waiver_history(tmp_path, steps, conf)
    outside = shas[waived[-1]]
    results = _run_evidence_job(tree, _pr_ctx(base, _head(tree)))
    rc, out = results[-1][1], "".join(o for _, _, o in results)
    assert rc != 0, f"[{name}] waiver outside ingester_tip accepted: {out[-600:]!r}"
    assert RANGE_CLEAN not in out, f"[{name}] range reported clean"
    assert outside[:7] in out, f"[{name}] refusal does not name {outside[:7]}: {out[-600:]!r}"
    _assert_safe(out)


@pytest.mark.parametrize("missing", ["waived-id", "ingester-tip"])
def test_ci_range_refuses_a_waiver_naming_no_commit(tmp_path: Path, missing: str) -> None:
    """RED today: a well-formed full id that names no object in the clone,
    as a waived commit or as ingester_tip, fails closed on a clean range and
    is named; it never waives anything."""
    ghost = _filler(1)[0]
    def conf(shas: dict[str, str], base: str) -> bytes:
        if missing == "waived-id":
            return _conf_with([f"{shas['clean:run.md']} {ghost}".encode()], shas[TIP])
        return _conf_with([shas["clean:run.md"].encode()], ghost)

    tree, base, _ = _waiver_history(tmp_path, ["clean:run.md", "scrub"], conf)
    results = _run_evidence_job(tree, _pr_ctx(base, _head(tree)))
    rc, out = results[-1][1], "".join(o for _, _, o in results)
    assert rc != 0, f"[{missing}] unresolvable id accepted: {out[-600:]!r}"
    assert RANGE_CLEAN not in out, f"[{missing}] range reported clean"
    assert ghost[:7] in out, f"[{missing}] refusal does not name {ghost[:7]}: {out[-600:]!r}"
    _assert_safe(out)


def test_ci_range_does_not_waive_under_an_unmerged_tip(tmp_path: Path) -> None:
    """Green today (guard): ingester_tip pinned to a commit the PR head never
    reaches is not in the scanned range, so its ancestors are not waived; the
    leaking commit still fails the range step. Without the in-range check a
    re-pin to an unmerged side commit would waive the leak."""
    steps = ["leak:run.md", "side", "scrub"]
    def conf(shas: dict[str, str], base: str) -> bytes:
        return _conf_with([shas["leak:run.md"].encode()], shas["side"])

    tree, base, shas = _waiver_history(tmp_path, steps, conf)
    head = _head(tree)
    assert _git(tree, "merge-base", "--is-ancestor", shas["side"], head, check=False).returncode == 1
    results = _run_evidence_job(tree, _pr_ctx(base, head))
    rc, out = results[-1][1], "".join(o for _, _, o in results)
    assert rc != 0 and RANGE_CLEAN not in out, f"unmerged ingester_tip waived the leak: {out[-600:]!r}"
    assert shas["leak:run.md"][:7] in out, out[-600:]
    _assert_safe(out)


def test_ci_range_passes_on_this_repo_with_the_conf_waiver(real_repo: Repo) -> None:
    """RED today (091f29b-class failure): the real range step, over the PR-1
    import (app_anchor..HEAD, both from git and the conf), passes, and names
    every waived commit. The ids are read from the conf, never restated."""
    cfg = load_config()
    assert cfg.waived_history_commits, f"{CONFIG_REL} waives nothing"
    head = _git(REPO_ROOT, "rev-parse", "HEAD").stdout.decode().strip()
    for sha in cfg.waived_history_commits:  # every waived id is a real commit in the range
        assert _git(REPO_ROOT, "merge-base", "--is-ancestor", sha, head, check=False).returncode == 0, sha
        assert _git(REPO_ROOT, "merge-base", "--is-ancestor", sha, cfg.app_anchor, check=False).returncode == 1, sha
        assert _git(REPO_ROOT, "merge-base", "--is-ancestor", sha, cfg.ingester_tip, check=False).returncode == 0, sha
    # the pinned import itself is in the scanned range (lead ruling 2026-10-15)
    assert _git(REPO_ROOT, "merge-base", "--is-ancestor", cfg.ingester_tip, head, check=False).returncode == 0
    assert _git(REPO_ROOT, "merge-base", "--is-ancestor", cfg.ingester_tip, cfg.app_anchor, check=False).returncode == 1
    results = _run_evidence_job(REPO_ROOT, _pr_ctx(cfg.app_anchor, head), tip=False)
    rc, out = _range_out(results)
    assert rc == 0, f"range step rc={rc}: {out[-800:]!r}"
    assert RANGE_CLEAN in out, out[-800:]
    missing = [sha[:7] for sha in cfg.waived_history_commits if sha[:7] not in out]
    assert missing == [], f"range step does not name waived commit(s) {missing}"
    _assert_safe(out)


def test_evidence_dir_is_one_value_across_guards() -> None:
    """F10, green today: hook check 4 and the scanner name the card's folder."""
    hook = re.findall(r'^EVIDENCE_PREFIX="([^"]*)"$', HOOK_FILE.read_text(encoding="utf-8"), re.M)
    assert hook == [EVIDENCE_DIR], hook
    scanner = re.findall(r'^EVIDENCE_DIR="\$\{ROOT\}/([^"]*)"$', SCANNER_FILE.read_text(encoding="utf-8"), re.M)
    assert [s + "/" for s in scanner] == [EVIDENCE_DIR], scanner
    assert EVIDENCE_DIR.rstrip("/") in EVIDENCE_JOB_NAME


# ==========================================================================
# 5. No repo doc or agent brief tells agents to commit evidence
# ==========================================================================
# Agent-facing docs: library, rules, skills, governance notes, plans, specs,
# READMEs. Evidence itself is excluded (it is never tracked after this card).
DOC_PATHSPECS = (
    ":(glob).claude/**/*.md",
    ":(glob).claude/**/*.txt",
    ":(glob).github/**/*.md",
    ":(glob)docs/**/*.md",
    ":(glob)scripts/**/*.md",
    ":(glob)automations/**/*.md",
    ":(glob)*.md",
    ":(exclude,glob)docs/evidence/**",
)

COMMIT_EVIDENCE_PATTERNS = {
    "commit-red-run": re.compile(r"\bcommit(?:s|ted|ting)?\s+(?:the\s+|a\s+|your\s+|its\s+)?red\s+(?:run|log|test\s+log|output)\b"),
    "committed-as-evidence": re.compile(
        r"\bcommit(?:s|ted|ting)?\s+(?:it\s+|them\s+)?(?:as|to|into|under|in)\s+docs/evidence\b"),
    "commit-evidence": re.compile(r"\bcommit(?:s|ted|ting)?\s+(?:the\s+|all\s+|your\s+|any\s+|its\s+)?evidence(?![\w-])"),
    "stage-evidence": re.compile(r"\bgit\s+add\s+(?:-\S+\s+)*docs/evidence\b"),
    "evidence-tracked": re.compile(r"\bdocs/evidence/?\s+(?:is|are|stays?|remains?)\s+(?:tracked|committed|versioned)\b"),
}
# "never commit evidence", "do not commit the red run", "don't ...".
_NEGATED = re.compile(r"\b(?:never|not|don[’']?t|no|without)\s+(?:\S+\s+)?$")
_MARKDOWN = re.compile(r"[`*_]")


def _normalise_doc(text: str) -> str:
    text = _strip_cf(unicodedata.normalize("NFKC", text))
    text = _MARKDOWN.sub("", text)
    return re.sub(r"\s+", " ", text).casefold()  # every line break kind, too


def commit_evidence_hits(text: str) -> list[str]:
    norm = _normalise_doc(text)
    hits: list[str] = []
    for name, pat in COMMIT_EVIDENCE_PATTERNS.items():
        for m in pat.finditer(norm):
            if _NEGATED.search(norm[max(0, m.start() - 40):m.start()]):
                continue
            hits.append(f"{name}: {ascii(m.group(0)[:80])}")
    return hits


COMMIT_EVIDENCE_BLOCK = [
    ("commit-red-run", "Commit the red run alongside its tests."),
    ("commit-red-run", "commit the\nred run"),
    ("commit-red-run", "**Commit** the `red log` with the tests"),
    ("commit-red-run", "commit the red run"),
    ("committed-as-evidence", "The red log is committed as docs/evidence/x.txt"),
    ("committed-as-evidence", "committed under `docs/evidence/`"),
    ("commit-evidence", "Commit evidence as plain text."),
    ("commit-evidence", "com​mit the evidence"),
    ("commit-evidence", "ＣＯＭＭＩＴ evidence"),
    ("stage-evidence", "git add docs/evidence/red.log"),
    ("stage-evidence", "git add -f docs/evidence/"),
    ("evidence-tracked", "docs/evidence/ is tracked in git"),
]
COMMIT_EVIDENCE_ALLOW = [
    ("commit-red-run", "Do not commit the red run."),
    ("commit-red-run", "the red run is logged locally"),
    ("committed-as-evidence", "never committed as docs/evidence files"),
    ("committed-as-evidence", "committed as a fix"),
    ("commit-evidence", "Never commit evidence."),
    ("commit-evidence", "Don’t commit evidence"),
    ("commit-evidence", "the evidence-scan job scans every commit in the range"),
    ("commit-evidence", "commit the evidence-scan job"),
    ("stage-evidence", "git add src/ docs/plans/"),
    ("evidence-tracked", "docs/evidence/ is untracked"),
    ("evidence-tracked", "docs/evidence/ is gitignored"),
]


@pytest.mark.parametrize("name,text", COMMIT_EVIDENCE_BLOCK, ids=[f"{n}:{ascii(t)}" for n, t in COMMIT_EVIDENCE_BLOCK])
def test_commit_evidence_matcher_blocks(name: str, text: str) -> None:
    assert any(h.startswith(name + ":") for h in commit_evidence_hits(text)), commit_evidence_hits(text)


@pytest.mark.parametrize("name,text", COMMIT_EVIDENCE_ALLOW, ids=[f"{n}:{ascii(t)}" for n, t in COMMIT_EVIDENCE_ALLOW])
def test_commit_evidence_matcher_allows(name: str, text: str) -> None:
    assert commit_evidence_hits(text) == []


def test_commit_evidence_vectors_cover_every_pattern() -> None:
    names = set(COMMIT_EVIDENCE_PATTERNS)
    assert {n for n, _ in COMMIT_EVIDENCE_BLOCK} == names
    assert {n for n, _ in COMMIT_EVIDENCE_ALLOW} == names


def test_no_doc_tells_agents_to_commit_evidence() -> None:
    """Red today: .claude/governance/evidence-leak-regex.txt says "Commit evidence as plain text."."""
    docs = _git_paths("ls-files", "-z", "--", *DOC_PATHSPECS)
    assert ".claude/CLAUDE.md" in docs, f"doc corpus missed the project CLAUDE.md ({len(docs)} files)"
    offenders = []
    for rel in docs:
        hits = commit_evidence_hits((REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace"))
        offenders += [f"{rel}: {h}" for h in hits]
    assert offenders == [], "docs still tell agents to commit evidence:\n" + "\n".join(offenders)
