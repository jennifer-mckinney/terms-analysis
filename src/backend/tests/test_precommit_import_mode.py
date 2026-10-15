"""Acceptance tests for terms-analysis #384: one-shot import mode in the hook.

Owner ruling (2026-10-15): design Option A. The pre-commit hook lets exactly
one commit through without the TA-root check 1: the #125 relocation commit in
the detached `reloc` worktree. Import mode needs ALL of
  * HEAD == the conf's `ingester_tip` (full SHA, exact),
  * HEAD's only root == the conf's `ingester_root_commit`,
  * the tree `git write-tree` builds from the index being committed has
    `T:<ingester_prefix>` == `<tip>^{tree}` and nothing outside the prefix.
The conf is read from the HOOK checkout (`HOOK_ROOT`, from BASH_SOURCE with
`cd -P`), never from the committing worktree; a missing conf never grants
anything. In import mode check 1 is skipped and checks 4 and 5 still run with
the hook checkout's assets, so the imported tree meets TA's tree guard.
A proof that starts (HEAD == tip) and then fails refuses hard; it does not fall
through to the normal path (design section 1).

Every case is a real `git commit` in a temporary sandbox, run through an
ABSOLUTE `core.hooksPath` to the sandbox TA checkout's `.githooks` (ruling 3).
Pins are sandbox SHAs written into a copy of the real conf, so neither the
tests nor the hook carry the real pins (F13). Design section 3 IDs (T1-T16)
and mutations (M1-M9) are named in the docstrings.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from tests.test_precommit_guards import (
    CRASH_MARKERS,
    GITIGNORE_FILE,
    GOV_DIR,
    HOOK_TIMEOUT_S,
    HOOKS_DIR,
    PATTERNS_FILE,
    REPO_ROOT,
    REQUIRED_GITIGNORE_FILE,
    SCRIPTS_DIR,
    _copy_tracked,
    _env,
    _git,
    _graveyard_dirs,
    _home_patterns,
    _leaks,
    home,
)

CONF_FILE = GOV_DIR / "monorepo-layout.conf"
CONF_REL = CONF_FILE.relative_to(REPO_ROOT).as_posix()
REQUIRED_REL = REQUIRED_GITIGNORE_FILE.relative_to(REPO_ROOT).as_posix()
PATTERNS_REL = PATTERNS_FILE.relative_to(REPO_ROOT).as_posix()
# The hook's check 1 message (today's normal path) for a missing SSoT. Its
# presence proves the normal path ran; its absence (with a refusal) proves the
# import path refused hard instead of falling through.
SSOT_MISSING = "required-gitignore SSoT missing"
REASON_HOME = "home-path"
REASON_ENV = ".env"
REASON_GRAVEYARD = "graveyard"
OFF = ("-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false")
_ATTEST = re.compile(r"(?m)^(?:pre-commit: )?(?:\S+: )?IMPORT ([0-9a-f]{40}) ([0-9a-f]{40})\s*$")


# ---------------------------------------------------------------------------
# Conf helpers: the real conf is the template; only the pins are replaced.
# ---------------------------------------------------------------------------
def _real_conf() -> str:
    if not CONF_FILE.is_file():
        pytest.fail(
            f"{CONF_REL} is not on this branch: #384 import mode reads the pins from the "
            "hook checkout (design section 1 step 2), so the conf must be tracked on main"
        )
    return CONF_FILE.read_text(encoding="ascii")


def _conf_value(text: str, key: str) -> str:
    hits = [ln[len(key) + 1:] for ln in text.split("\n") if ln.startswith(key + "=")]
    assert len(hits) == 1, f"conf key {key!r} appears {len(hits)} times"
    return hits[0]


def _with(text: str, **kv: str) -> str:
    lines = text.split("\n")
    for key, value in kv.items():
        idx = [i for i, ln in enumerate(lines) if ln.startswith(key + "=")]
        assert len(idx) == 1, f"conf key {key!r} appears {len(idx)} times"
        lines[idx[0]] = f"{key}={value}"
    return "\n".join(lines)


def _set_line(text: str, key: str, line: str | None) -> str:
    """Replace (or drop, when line is None) the one `key=` line verbatim."""
    lines = text.split("\n")
    idx = [i for i, ln in enumerate(lines) if ln.startswith(key + "=")]
    assert len(idx) == 1, f"conf key {key!r} appears {len(idx)} times"
    if line is None:
        del lines[idx[0]]
    else:
        lines[idx[0]] = line
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sandbox: an ingester repo (3 commits) and a TA repo whose .githooks is wired
# by absolute path; `reloc` is a detached worktree of TA at the ingester tip.
# ---------------------------------------------------------------------------
@dataclass
class World:
    tmp: Path
    ing: Path
    ta: Path
    tip: str
    root: str
    tip_tree: str
    prefix: str
    conf: str  # the sandbox conf text committed in the TA hook checkout


def _write(repo: Path, rel: str, data: bytes | str, mode: int | None = None) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    if mode is not None:
        path.chmod(mode)


def _rev(repo: Path, spec: str) -> str:
    return _git(repo, "rev-parse", "--verify", "-q", spec).stdout.decode().strip()


def _build(tmp: Path, tip_extra: dict[str, bytes | str] | None = None) -> World:
    real = _real_conf()
    prefix = _conf_value(real, "ingester_prefix")
    ing = tmp / "ing"
    ing.mkdir()
    _git(ing, "init", "-q")
    commits: list[dict[str, bytes | str]] = [
        {"README.md": "ingester\n", ".gitignore": "*.pyc\n", "pyproject.toml": '[project]\nname = "ing"\n'},
        {".claude/settings.json": "{}\n", "src/pkg/__init__.py": "", "src/pkg/deep/mod.py": "X = 1\n",
         "docs/adr/001-x.md": "# ADR\n"},
        {"tests/test_x.py": "def test_x():\n    assert True\n", "a/b/c.txt": "c\n", **(tip_extra or {})},
    ]
    for i, files in enumerate(commits):
        for rel, data in files.items():
            _write(ing, rel, data)
        if i == 1:
            _write(ing, ".githooks/pre-commit", "#!/bin/sh\nexit 0\n", 0o755)
        _git(ing, "add", "-A", "-f")
        _git(ing, *OFF, "commit", "-q", "-m", f"ing {i}")
    tip, root, tip_tree = _rev(ing, "HEAD"), _rev(ing, "HEAD~2"), _rev(ing, "HEAD^{tree}")

    ta = tmp / "ta"
    ta.mkdir()
    _git(ta, "init", "-q")
    shutil.copy2(GITIGNORE_FILE, ta / ".gitignore")
    for src in (GOV_DIR, HOOKS_DIR, SCRIPTS_DIR):
        _copy_tracked(src, ta)
    (ta / CONF_REL).unlink(missing_ok=True)
    _git(ta, "add", "-A", "-f")
    _git(ta, *OFF, "commit", "-q", "-m", "ta base")
    conf = _with(real, ingester_tip=tip, ingester_root_commit=root, app_anchor=_rev(ta, "HEAD"))
    _write(ta, CONF_REL, conf)
    _git(ta, "add", "-f", "--", CONF_REL)
    _git(ta, *OFF, "commit", "-q", "-m", "ta conf")
    _git(ta, "config", "core.hooksPath", str(ta / ".githooks"))
    _git(ta, "fetch", "-q", "--no-tags", str(ing), "HEAD")
    return World(tmp, ing, ta, tip, root, tip_tree, prefix, conf)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return _build(tmp_path)


def _reloc(w: World, at: str | None = None, prefix: str | None = None,
           skip: tuple[str, ...] = (), name: str = "reloc") -> Path:
    """The #125 relocation: detached worktree at `at`, every entry moved."""
    r = w.tmp / name
    _git(w.ta, "worktree", "add", "-q", "--detach", str(r), at or w.tip)
    dest = prefix or w.prefix
    (r / dest).mkdir(parents=True, exist_ok=True)
    for raw in _git(r, "ls-tree", "-z", "--name-only", "HEAD").stdout.split(b"\0"):
        entry = os.fsdecode(raw)
        if entry and entry not in skip:
            _git(r, "mv", "--", entry, f"{dest}/{entry}")
    return r


def _count(repo: Path) -> int:
    return len([x for x in _git(repo, "ls-files", "-z").stdout.split(b"\0") if x])


def _linked_ta(w: World, name: str = "tawt") -> Path:
    wt = w.tmp / name
    _git(w.ta, "worktree", "add", "-q", "-b", name, str(wt))
    return wt


def _commit(cwd: Path, *args: str, pre: tuple[str, ...] = (),
            env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *pre, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "relocate", *args],
        cwd=cwd, env=env or _env(), capture_output=True, timeout=HOOK_TIMEOUT_S,
    )


def _out(proc: subprocess.CompletedProcess[bytes]) -> bytes:
    return proc.stdout + proc.stderr


def _assert_imported(w: World, repo: Path, proc: subprocess.CompletedProcess[bytes], n: int) -> None:
    """AC1: the commit lands, carries exactly the tip tree, and says why."""
    text = _out(proc).decode("utf-8", "replace")
    assert proc.returncode == 0, f"relocation commit refused: {text[-800:]!r}"
    assert _rev(repo, "HEAD^") == w.tip, "the relocation commit's parent is not the pinned tip"
    assert _rev(repo, f"HEAD:{w.prefix}") == w.tip_tree, "HEAD:<prefix> differs from <tip>^{tree}"
    head_tree = _rev(repo, "HEAD^{tree}")
    att = [m.groups() for m in _ATTEST.finditer(text)]
    assert att and all(t == w.tip and tree in (w.tip_tree, head_tree) for t, tree in att), (
        f"no exact 'IMPORT <tip> <tree>' attestation line: {text[-800:]!r}"
    )
    assert f"CLEAN {n}" in text.splitlines(), (
        f"check 5 did not attest the {n} relocated index entries (Option A): {text[-800:]!r}"
    )


def _assert_refused(w: World, repo: Path, proc: subprocess.CompletedProcess[bytes], head_before: str,
                    mode: str, *, attest_ok: bool = False, crash_ok: bool = False) -> str:
    """A refusal: no commit, a clean message, and the path that refused.

    mode "normal": the unchanged TA path ran (check 1's SSoT message).
    mode "import": the import proof refused hard (mentions import, no SSoT).
    mode "any":    either, as long as nothing landed.
    """
    raw = _out(proc)
    text = raw.decode("utf-8", "replace")
    assert proc.returncode != 0, f"commit was accepted: {text[-800:]!r}"
    assert _rev(repo, "HEAD") == head_before, "HEAD moved although the hook refused"
    bad = sorted({b for b in raw if not (0x20 <= b <= 0x7E or b in (0x0A, 0x09))})
    assert bad == [], f"hook output carries raw bytes {bad[:8]}: {text[-400:]!r}"
    for p in {str(w.tmp), os.path.realpath(w.tmp), str(REPO_ROOT)}:
        assert p not in text, f"hook output prints an absolute path: {text[-600:]!r}"
    assert not _leaks(text, _home_patterns()), f"hook output contains a home path: {text[-600:]!r}"
    if not attest_ok:
        assert not _ATTEST.search(text), f"refused commit still claims import mode: {text[-600:]!r}"
    if not crash_ok:
        assert [m for m in CRASH_MARKERS if m in text] == [], f"refusal came from a crash: {text[-600:]!r}"
    if mode == "normal":
        assert SSOT_MISSING in text, f"the normal TA path did not run: {text[-600:]!r}"
    elif mode == "import":
        assert "import" in text.lower(), f"refusal does not say import mode refused: {text[-600:]!r}"
        assert SSOT_MISSING not in text, f"import proof fell through to the normal path: {text[-600:]!r}"
    else:
        assert mode == "any", mode
    return text


# ---------------------------------------------------------------------------
# AC1: the relocation commit goes through.
# ---------------------------------------------------------------------------
def test_t1_clean_relocation_commit_passes_with_attestation(world: World) -> None:
    """T1 (kills M2, M7, M9-as-not-import): clean reloc commit lands."""
    r = _reloc(world)
    n = _count(r)
    _assert_imported(world, r, _commit(r), n)


def test_t1b_runner_home_lines_in_tip_pass(tmp_path: Path) -> None:
    """T1b, ruling 4: the ADR-016 and test runner-home lines do not block AC1."""
    users_runner = "/" + "Users" + "/" + "runner"
    home_runner = "/" + "home" + "/" + "runner"
    w = _build(tmp_path, tip_extra={
        "docs/adr/016-runners.md": (
            "Hosted runner home is `" + users_runner + "`.\n"
            "mkdir: " + users_runner + ": Permission denied\n"
            "AGENT_TOOLSDIRECTORY=" + users_runner + "/hostedtoolcache\n"
        ),
        "tests/test_runner_tmp.py": 'TMP = "' + home_runner + '/work/_temp"\n',
    })
    r = _reloc(w)
    _assert_imported(w, r, _commit(r), _count(r))


def test_symlinked_hooks_path_still_finds_hook_checkout(world: World) -> None:
    """HOOK_ROOT uses `cd -P`: a symlinked hooksPath resolves to the checkout."""
    link = world.tmp / "hooks-link"
    link.symlink_to(world.ta / ".githooks", target_is_directory=True)
    _git(world.ta, "config", "core.hooksPath", str(link))
    r = _reloc(world)
    _assert_imported(world, r, _commit(r), _count(r))


# ---------------------------------------------------------------------------
# AC2: TA commits never get the exemption.
# ---------------------------------------------------------------------------
def _drop_required(repo: Path) -> None:
    _git(repo, "rm", "-q", "--", REQUIRED_REL)


def test_t2_ta_worktree_without_conf_keeps_fail_closed(world: World) -> None:
    """T2 (kills M3): deleting the governance file still refuses on the TA path."""
    (world.ta / CONF_REL).unlink()
    wt = _linked_ta(world)
    _drop_required(wt)
    before = _rev(wt, "HEAD")
    _assert_refused(world, wt, _commit(wt), before, "normal")


def test_t3_ta_worktree_with_conf_keeps_fail_closed(world: World) -> None:
    """T3: a valid conf does not exempt a TA commit (HEAD != tip)."""
    wt = _linked_ta(world)
    _drop_required(wt)
    before = _rev(wt, "HEAD")
    _assert_refused(world, wt, _commit(wt), before, "normal")


def test_t4_conf_pinning_a_ta_commit_refuses_on_root(world: World) -> None:
    """T4: tip mis-pinned to TA HEAD; the sole-root proof refuses hard."""
    wt = _linked_ta(world)
    before = _rev(wt, "HEAD")
    _write(world.ta, CONF_REL, _with(world.conf, ingester_tip=before))
    _drop_required(wt)
    _assert_refused(world, wt, _commit(wt), before, "import")


def _roots(repo: Path) -> list[str]:
    return _git(repo, "rev-list", "--max-parents=0", "HEAD").stdout.decode().split()


def _root_only_case(w: World, roots: str) -> tuple[str, str]:
    """(tip, ingester_root_commit) for the conf; only the root proof is false.

    ta-rooted: a TA-rooted commit carrying the ingester tip's exact tree.
    two-roots: the same tree with both the ingester tip and TA HEAD as parents.
    root-mispinned: the real tip, but the conf names another ingester commit.
    """
    ta_head = _rev(w.ta, "HEAD")
    if roots == "root-mispinned":
        return w.tip, _rev(w.ing, "HEAD~1")
    parents = ["-p", ta_head] if roots == "ta-rooted" else ["-p", w.tip, "-p", ta_head]
    made = _git(w.ta, "commit-tree", w.tip_tree, *parents, "-m", f"foreign tip ({roots})")
    return made.stdout.decode().strip(), w.root


@pytest.mark.parametrize("roots", ["ta-rooted", "two-roots", "root-mispinned"])
def test_t4b_root_proof_alone_refuses(world: World, roots: str) -> None:
    """T4b (kills deleting the root proof): HEAD == conf tip and the staged tree
    is exactly the tip tree under the prefix, but HEAD's roots are not the one
    pinned ingester_root_commit. The refusal must come from the root proof."""
    tip, root = _root_only_case(world, roots)
    _write(world.ta, CONF_REL, _with(world.conf, ingester_tip=tip, ingester_root_commit=root))
    r = _reloc(world, at=tip, name=f"reloc-{roots}")
    # Fixture: every proof except the root proof holds.
    assert _rev(r, "HEAD") == tip and _rev(r, "HEAD^{tree}") == world.tip_tree
    staged = _git(r, "write-tree").stdout.decode().strip()
    assert _rev(r, f"{staged}:{world.prefix}") == world.tip_tree, "fixture: prefix tree differs"
    names = [p for p in _git(r, "ls-tree", "-r", "-z", "--name-only", staged).stdout.split(b"\0") if p]
    assert names and all(os.fsdecode(p).startswith(world.prefix + "/") for p in names), (
        "fixture: the staged tree has entries outside the prefix"
    )
    found = _roots(r)
    assert found != [root], "fixture: the root proof would hold"
    assert len(found) == (2 if roots == "two-roots" else 1), found
    text = _assert_refused(world, r, _commit(r), tip, "import")
    assert "ingester_root_commit" in text, f"refusal does not name the root proof: {text[-600:]!r}"


def _merged_ta(w: World) -> Path:
    """A TA branch after #125's unrelated-histories merge (two roots)."""
    r = _reloc(w)
    _git(r, *OFF, "commit", "-q", "-m", "reloc (hook off)")
    reloc_commit = _rev(r, "HEAD")
    wt = _linked_ta(w)
    _git(wt, *OFF, "merge", "-q", "--no-edit", "--allow-unrelated-histories", reloc_commit)
    return wt


def test_t5_after_merge_ta_commit_keeps_fail_closed(world: World) -> None:
    """T5 (kills M1): containing the ingester root is not identity."""
    wt = _merged_ta(world)
    _drop_required(wt)
    before = _rev(wt, "HEAD")
    _assert_refused(world, wt, _commit(wt), before, "normal")


def test_t5b_after_merge_prefix_only_tree_is_not_import(world: World) -> None:
    """T5b (kills M1): even a tree equal to the tip's needs HEAD == tip."""
    wt = _merged_ta(world)
    outside = [os.fsdecode(p) for p in _git(wt, "ls-files", "-z").stdout.split(b"\0")
               if p and not os.fsdecode(p).startswith(world.prefix + "/")]
    assert outside, "fixture: merged TA branch has no TA paths"
    _git(wt, "rm", "-q", "-r", "--", *outside)
    before = _rev(wt, "HEAD")
    _assert_refused(world, wt, _commit(wt), before, "normal")


# ---------------------------------------------------------------------------
# AC1 identity: only the byte-identical tip tree under the prefix.
# ---------------------------------------------------------------------------
def _stage(repo: Path, rel: str, data: str) -> None:
    _write(repo, rel, data)
    _git(repo, "add", "-f", "--", rel)


def test_t6_extra_file_outside_prefix_refused(world: World) -> None:
    """T6 (kills M4, M5): T:<prefix> matches, but something sits outside it."""
    r = _reloc(world)
    _stage(r, "stray.txt", "x\n")
    _assert_refused(world, r, _commit(r), world.tip, "import")


def test_t7_changed_content_refused(world: World) -> None:
    """T7 (kills M4): one relocated file's content differs from the tip."""
    r = _reloc(world)
    _stage(r, f"{world.prefix}/README.md", "changed\n")
    _assert_refused(world, r, _commit(r), world.tip, "import")


def test_t8_unmoved_entry_refused(world: World) -> None:
    """T8 (kills M4): one top-level entry left where it was."""
    r = _reloc(world, skip=("a",))
    _assert_refused(world, r, _commit(r), world.tip, "import")


def test_t8b_deleted_file_inside_prefix_refused(world: World) -> None:
    r = _reloc(world)
    # -f: the path is staged by the relocation, so plain rm refuses.
    _git(r, "rm", "-q", "-f", "--", f"{world.prefix}/a/b/c.txt")
    _assert_refused(world, r, _commit(r), world.tip, "import")


def test_t8c_mode_only_change_refused(world: World) -> None:
    r = _reloc(world)
    _git(r, "update-index", "--chmod=+x", "--", f"{world.prefix}/README.md")
    _assert_refused(world, r, _commit(r), world.tip, "import")


def test_t8d_extra_file_inside_prefix_refused(world: World) -> None:
    r = _reloc(world)
    _stage(r, f"{world.prefix}/extra.txt", "x\n")
    _assert_refused(world, r, _commit(r), world.tip, "import")


@pytest.mark.parametrize("which", ["sibling", "parent"])
def test_t9_wrong_prefix_refused(world: World, which: str) -> None:
    """T9: relocated under another prefix than the conf names."""
    assert "/" in world.prefix, "fixture: the conf prefix has a parent segment"
    wrong = world.prefix + "2" if which == "sibling" else world.prefix.rsplit("/", 1)[0]
    r = _reloc(world, prefix=wrong)
    _assert_refused(world, r, _commit(r), world.tip, "import")


def test_t10_worktree_at_tip_parent_takes_normal_path(world: World) -> None:
    """T10: HEAD != tip, so the normal path refuses (no root .gitignore SSoT)."""
    r = _reloc(world, at=world.tip + "^")
    before = _rev(r, "HEAD")
    _assert_refused(world, r, _commit(r), before, "normal")


def test_t11_missing_conf_in_hook_checkout_takes_normal_path(world: World) -> None:
    """T11 (kills M3): no conf, no exemption; today's refusal stands."""
    (world.ta / CONF_REL).unlink()
    r = _reloc(world)
    _assert_refused(world, r, _commit(r), world.tip, "normal")


def test_t13_conf_planted_in_reloc_is_ignored(world: World) -> None:
    """T13 (kills M2, M7): the committing worktree cannot supply the conf."""
    (world.ta / CONF_REL).unlink()
    r = _reloc(world)
    _write(r, CONF_REL, world.conf)
    _assert_refused(world, r, _commit(r), world.tip, "normal")


def test_t13b_reloc_conf_cannot_override_hook_conf(world: World) -> None:
    """T13b (kills M2, M7): hook conf pins tip^, reloc plants the real tip."""
    _write(world.ta, CONF_REL, _with(world.conf, ingester_tip=_rev(world.ing, "HEAD^")))
    r = _reloc(world)
    _write(r, CONF_REL, world.conf)
    _assert_refused(world, r, _commit(r), world.tip, "normal")


# ---------------------------------------------------------------------------
# T12: the conf loader fails closed (F13); legitimate layouts still load.
# ---------------------------------------------------------------------------
ConfMaker = Callable[[str, World], bytes]


def _enc(text: str) -> bytes:
    return text.encode("utf-8")


def _last_digit(tip: str) -> str:
    return tip[:-1] + ("0" if tip[-1] != "0" else "1")


def _reordered(text: str, w: World) -> bytes:
    lines = text.split("\n")
    keys = [ln for ln in lines if ln and not ln.startswith("#")]
    rest = [ln for ln in lines if not ln or ln.startswith("#")]
    return _enc("\n".join(rest + keys[::-1]) + "\n")


def _padded(text: str, w: World) -> bytes:
    out = []
    for ln in text.split("\n"):
        out += ["", "# extra comment", ln] if ln and not ln.startswith("#") else [ln]
    return _enc("\n".join(out))


CONF_ROWS: list[tuple[str, str, ConfMaker]] = [
    ("positive", "unchanged", lambda t, w: _enc(t)),
    ("positive", "keys-reordered", _reordered),
    ("positive", "extra-comments-and-blanks", _padded),
    ("negative", "tip-abbreviated", lambda t, w: _enc(_with(t, ingester_tip=w.tip[:12]))),
    ("negative", "tip-uppercase", lambda t, w: _enc(_with(t, ingester_tip=w.tip.upper()))),
    ("negative", "tip-last-digit-changed", lambda t, w: _enc(_with(t, ingester_tip=_last_digit(w.tip)))),
    ("negative", "duplicate-tip-same-value", lambda t, w: _enc(t + f"\ningester_tip={w.tip}\n")),
    ("negative", "unknown-key", lambda t, w: _enc(t + "\ningester_extra=1\n")),
    ("negative", "missing-root", lambda t, w: _enc(_set_line(t, "ingester_root_commit", None))),
    ("negative", "missing-prefix", lambda t, w: _enc(_set_line(t, "ingester_prefix", None))),
    ("negative", "key-wrong-case", lambda t, w: _enc(_set_line(t, "ingester_tip", f"Ingester_tip={w.tip}"))),
    ("negative", "spaced-assignment", lambda t, w: _enc(_set_line(t, "ingester_tip", f"ingester_tip = {w.tip}"))),
    ("negative", "non-ascii-comment", lambda t, w: _enc("# café\n" + t)),
    ("negative", "non-ascii-after-tip", lambda t, w: _enc(_with(t, ingester_tip=w.tip + "é"))),
    ("negative", "nul-in-comment", lambda t, w: _enc("# a\0b\n" + t)),
    ("negative", "crlf-file", lambda t, w: _enc(t.replace("\n", "\r\n"))),
    ("negative", "utf8-bom", lambda t, w: _enc("﻿" + t)),
    ("negative", "zero-width-in-tip", lambda t, w: _enc(_with(t, ingester_tip=w.tip[:20] + "​" + w.tip[20:]))),
    ("negative", "line-separator", lambda t, w: _enc("# a b\n" + t)),
    ("negative", "invalid-utf8", lambda t, w: b"# \xff\n" + _enc(t)),
    ("negative", "tip-leading-space", lambda t, w: _enc(_with(t, ingester_tip=" " + w.tip))),
    ("negative", "tip-trailing-space", lambda t, w: _enc(_with(t, ingester_tip=w.tip + " "))),
    ("negative", "tip-inline-comment", lambda t, w: _enc(_with(t, ingester_tip=w.tip + " # pinned"))),
    ("negative", "huge-tip", lambda t, w: _enc(_with(t, ingester_tip=w.tip + "0" * 2_000_000))),
    ("negative", "prefix-empty", lambda t, w: _enc(_with(t, ingester_prefix=""))),
    ("negative", "prefix-dotdot", lambda t, w: _enc(_with(t, ingester_prefix=w.prefix.split("/")[0] + "/../" + w.prefix))),
    ("negative", "prefix-absolute", lambda t, w: _enc(_with(t, ingester_prefix="/" + w.prefix))),
    ("negative", "prefix-trailing-slash", lambda t, w: _enc(_with(t, ingester_prefix=w.prefix + "/"))),
    ("negative", "prefix-dot", lambda t, w: _enc(_with(t, ingester_prefix="."))),
    ("negative", "prefix-double-slash", lambda t, w: _enc(_with(t, ingester_prefix=w.prefix.replace("/", "//", 1)))),
    ("negative", "prefix-dot-segment", lambda t, w: _enc(_with(t, ingester_prefix="./" + w.prefix))),
    ("negative", "root-equals-tip", lambda t, w: _enc(_with(t, ingester_root_commit=w.tip))),
]


# Negative rows whose conf is well formed but pins another tip: they load, so
# an ordinary commit still passes. Every other negative row is malformed.
WELL_FORMED_NEGATIVE_ROWS = frozenset({"tip-last-digit-changed"})


def test_conf_rows_contract() -> None:
    kinds = {k for k, _, _ in CONF_ROWS}
    assert kinds == {"positive", "negative"}, kinds
    ids = [i for _, i, _ in CONF_ROWS]
    assert len(ids) == len(set(ids))
    negatives = {i for k, i, _ in CONF_ROWS if k == "negative"}
    assert WELL_FORMED_NEGATIVE_ROWS < negatives, WELL_FORMED_NEGATIVE_ROWS - negatives


@pytest.mark.parametrize("kind,row_id,make", CONF_ROWS, ids=[i for _, i, _ in CONF_ROWS])
def test_t12_conf_loader(world: World, kind: str, row_id: str, make: ConfMaker) -> None:
    """T12 (kills M6, and "malformed == absent"): a malformed conf never yields
    import mode, and it refuses an ordinary commit that passes without a conf."""
    _write(world.ta, CONF_REL, make(world.conf, world))
    r = _reloc(world)
    proc = _commit(r)
    if kind == "positive":
        _assert_imported(world, r, proc, _count(r))
        return
    text = _assert_refused(world, r, proc, world.tip, "any")
    cap = int(_conf_value(_real_conf(), "max_message_chars"))
    assert "0" * (cap + 1) not in text, "the refusal quotes more than max_message_chars of conf input"
    # The same ordinary TA commit (check 1 allows it) under this conf, then
    # with the conf absent: malformed must refuse, absent must pass.
    _stage(world.ta, "docs/note.md", "hello\n")
    before = _rev(world.ta, "HEAD")
    ordinary = _commit(world.ta)
    if row_id in WELL_FORMED_NEGATIVE_ROWS:
        _assert_ordinary_pass(world.ta, ordinary, _count(world.ta))
        return
    otext = _assert_refused(world, world.ta, ordinary, before, "any")
    assert SSOT_MISSING not in otext, f"refused by check 1, not by the conf: {otext[-600:]!r}"
    assert CONF_REL in otext, f"the refusal does not name the malformed conf: {otext[-600:]!r}"
    assert "0" * (cap + 1) not in otext, "the refusal quotes more than max_message_chars of conf input"
    (world.ta / CONF_REL).unlink()
    _assert_ordinary_pass(world.ta, _commit(world.ta), _count(world.ta))


# ---------------------------------------------------------------------------
# T14 / M8: Option A keeps check 5 on the imported tree (HOOK_ROOT assets).
# ---------------------------------------------------------------------------
def _t14_cases() -> list[tuple[str, dict[str, bytes | str], str, str]]:
    leak = home()
    grave = _graveyard_dirs()[0]
    return [
        ("home-path", {"docs/notes.md": "see " + leak + "\n"}, REASON_HOME, leak),
        ("dotenv", {".env": "TOKEN=placeholder-body\n"}, REASON_ENV, "placeholder-body"),
        ("graveyard", {grave + "kept.txt": "graveyard-body\n"}, REASON_GRAVEYARD, "graveyard-body\n"),
    ]


@pytest.mark.parametrize("case", range(3), ids=["home-path", "dotenv", "graveyard"])
def test_t14_tree_guard_still_runs_in_import_mode(tmp_path: Path, case: int) -> None:
    """T14 (kills M8): an identical-but-dirty tip tree is refused by check 5."""
    _cid, extra, reason, content = _t14_cases()[case]
    w = _build(tmp_path, tip_extra=extra)
    r = _reloc(w)
    text = _assert_refused(w, r, _commit(r), w.tip, "any", attest_ok=True)
    assert SSOT_MISSING not in text, f"refused by the normal path, not by check 5: {text[-600:]!r}"
    assert reason in text and re.search(r"(?m)REFUSED [0-9]+$", text), text[-600:]
    assert content not in text, "check 5 echoes the refused content"


def test_f8_tree_guard_config_error_in_import_mode_prints_no_absolute_path(world: World) -> None:
    """F8: HOOK_ROOT assets are absolute; a config error must not print them."""
    pat = world.ta / PATTERNS_REL
    pat.write_bytes(pat.read_bytes().replace(b"\n", b"\r\n"))
    r = _reloc(world)
    text = _assert_refused(world, r, _commit(r), world.tip, "any", attest_ok=True)
    assert "config" in text, f"the config failure is not named: {text[-600:]!r}"


# ---------------------------------------------------------------------------
# T15: other ways to commit the same tree.
# ---------------------------------------------------------------------------
def test_t15_pathspec_commit_all_passes(world: World) -> None:
    r = _reloc(world)
    _assert_imported(world, r, _commit(r, "--", "."), _count(r))


def test_t15_pathspec_commit_prefix_only_refused(world: World) -> None:
    """`commit -- <prefix>` leaves the old top-level entries in the temp index."""
    r = _reloc(world)
    _assert_refused(world, r, _commit(r, "--", world.prefix), world.tip, "import")


def test_t15_pathspec_commit_uses_temp_index_content(world: World) -> None:
    """Proves write-tree honours GIT_INDEX_FILE: an unstaged edit rides along."""
    r = _reloc(world)
    (r / world.prefix / "README.md").write_text("edited after staging\n", encoding="utf-8")
    _assert_refused(world, r, _commit(r, "--", "."), world.tip, "import")


@pytest.mark.parametrize("cwd", ["tmp", "ta"])
def test_t15_git_dash_c_from_other_cwd_passes(world: World, cwd: str) -> None:
    r = _reloc(world)
    where = world.tmp if cwd == "tmp" else world.ta
    _assert_imported(world, r, _commit(where, pre=("-C", str(r))), _count(r))


def test_t15_git_dash_c_with_outside_file_refused(world: World) -> None:
    r = _reloc(world)
    _stage(r, "stray.txt", "x\n")
    _assert_refused(world, r, _commit(world.tmp, pre=("-C", str(r))), world.tip, "import")


def test_t15_git_dir_and_work_tree_env_passes(world: World) -> None:
    r = _reloc(world)
    gitdir = _git(r, "rev-parse", "--absolute-git-dir").stdout.decode().strip()
    env = _env({"GIT_DIR": gitdir, "GIT_WORK_TREE": str(r)})
    _assert_imported(world, r, _commit(world.tmp, env=env), _count(r))


# ---------------------------------------------------------------------------
# T16: ordinary commits are unchanged.
# ---------------------------------------------------------------------------
def _assert_ordinary_pass(repo: Path, proc: subprocess.CompletedProcess[bytes], n: int) -> None:
    text = _out(proc).decode("utf-8", "replace")
    assert proc.returncode == 0, f"ordinary commit refused: {text[-800:]!r}"
    assert not _ATTEST.search(text), f"an ordinary commit claimed import mode: {text[-600:]!r}"
    assert f"CLEAN {n}" in text.splitlines(), text[-600:]


@pytest.mark.parametrize("conf", ["sandbox", "real"])
def test_t16_ordinary_ta_commit_passes(world: World, conf: str) -> None:
    if conf == "real":
        _write(world.ta, CONF_REL, _real_conf())
    _stage(world.ta, "docs/note.md", "hello\n")
    _git(world.ta, "add", "-f", "--", CONF_REL)
    _assert_ordinary_pass(world.ta, _commit(world.ta), _count(world.ta))


def test_t16_ordinary_commit_in_linked_worktree_passes(world: World) -> None:
    wt = _linked_ta(world)
    _stage(wt, "docs/note.md", "hello\n")
    _assert_ordinary_pass(wt, _commit(wt), _count(wt))


def test_t16_first_commit_on_unborn_head_passes(world: World) -> None:
    fresh = world.tmp / "fresh"
    fresh.mkdir()
    _git(fresh, "init", "-q")
    shutil.copy2(GITIGNORE_FILE, fresh / ".gitignore")
    for src in (GOV_DIR, HOOKS_DIR, SCRIPTS_DIR):
        _copy_tracked(src, fresh)
    _write(fresh, CONF_REL, world.conf)
    _git(fresh, "config", "core.hooksPath", str(fresh / ".githooks"))
    _git(fresh, "add", "-A", "-f")
    _assert_ordinary_pass(fresh, _commit(fresh), _count(fresh))


# ---------------------------------------------------------------------------
# M9: the import helper failing is a refusal, never a silent verdict.
# The hook's interpreter (`python3`, or LEAK_SCAN_PYTHON) is faked on PATH;
# tree_guard.py and leak_scan.py calls are passed to the real interpreter.
# ---------------------------------------------------------------------------
FAKE_MODES = {
    "exit-1": "exit 1",
    "exit-0-silent": "exit 0",
    "killed": "kill -9 $$",
    "traceback": 'echo "Traceback (most recent call last):" >&2; exit 2',
    "bare-import": "echo IMPORT; exit 0",
    "forged-sentinel-rc1": 'echo "IMPORT {tip} {tree}"; exit 1',
    "sentinel-then-junk": 'echo "IMPORT {tip} {tree}"; echo junk; exit 0',
    "not-import-rc2": "echo NOT-IMPORT; exit 2",
    "delegate": 'exec "{py}" "$@"',
}


def _fake_python(w: World, mode: str) -> dict[str, str]:
    fakebin = w.tmp / "fakebin"
    fakebin.mkdir(exist_ok=True)
    body = FAKE_MODES[mode].format(tip=w.tip, tree=w.tip_tree, py=sys.executable)
    script = fakebin / "python3"
    script.write_text(
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do case "$a" in *tree_guard.py|*leak_scan.py) '
        f'exec "{sys.executable}" "$@";; esac; done\n'
        f"{body}\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env = _env({"PATH": str(fakebin) + os.pathsep + os.environ.get("PATH", "")})
    env.pop("LEAK_SCAN_PYTHON", None)
    return env


@pytest.mark.parametrize("setup", ["reloc_clean", "reloc_extra", "ta_ordinary"])
@pytest.mark.parametrize("mode", sorted(FAKE_MODES))
def test_m9_import_helper_failure_refuses(world: World, mode: str, setup: str) -> None:
    """M9: only rc 0 with an exact last line counts; anything else refuses."""
    env = _fake_python(world, mode)
    if setup == "ta_ordinary":
        repo = world.ta
        _stage(repo, "docs/note.md", "hello\n")
    else:
        repo = _reloc(world)
        if setup == "reloc_extra":
            _stage(repo, "stray.txt", "x\n")
    before = _rev(repo, "HEAD")
    proc = _commit(repo, env=env)
    if mode == "delegate" and setup == "reloc_clean":
        _assert_imported(world, repo, proc, _count(repo))
        return
    if mode == "delegate" and setup == "ta_ordinary":
        _assert_ordinary_pass(repo, proc, _count(repo))
        return
    text = _assert_refused(world, repo, proc, before, "any", attest_ok=True, crash_ok=True)
    if setup == "reloc_clean":
        assert SSOT_MISSING not in text, (
            f"helper failure fell through to the normal path ({mode}): {text[-600:]!r}"
        )
