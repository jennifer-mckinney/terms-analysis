#!/usr/bin/env python3
"""Import-mode proof for `.githooks/pre-commit` (terms-analysis #384).

Owner ruling 2026-10-15, design Option A. The hook lets exactly one commit
skip check 1 (the TA-root .gitignore SSoT): the #125 relocation commit, made
in a detached worktree at the ingester tip, that moves the whole ingester tree
under the pinned prefix. This helper decides whether the commit being made is
that commit. Import mode needs ALL of:

  * HEAD == `ingester_tip` (full SHA, exact);
  * HEAD's history has exactly one root commit, `ingester_root_commit`;
  * the tree `git write-tree` builds from the index being committed (it
    honours GIT_INDEX_FILE, so `git commit <paths>` is covered) holds only the
    prefix path, and `T:<ingester_prefix>` == `<ingester_tip>^{tree}`.

The conf is `.claude/governance/monorepo-layout.conf` of the HOOK checkout;
the hook passes its absolute path, never the committing worktree's copy.

Usage (cwd = the committing worktree, git environment inherited):
    import_guard.py <monorepo-layout.conf of the hook checkout>

Output is stdout only; the LAST line is the verdict:
  rc 0, "NOT-IMPORT"                  no conf, unborn HEAD or HEAD != tip:
                                      the hook runs its normal path
  rc 0, "IMPORT <tip> <tree>"         every proof holds
  rc 1, reason lines, "IMPORT-REFUSED" a malformed conf, or HEAD == tip and a
                                      proof failed (refuse hard, no fall-through)
  rc 2, "IMPORT-REFUSED"              internal error
The hook treats anything else (other rc, other last line, a signal) as a
refusal. Messages never print an absolute path or a conf value longer than
`max_message_chars`; git stderr is discarded (F8).

Second mode, the bound waiver (#125, owner 2026-10-15 "Teach CI the waiver";
lead ruling 2026-10-15), used by `scan-evidence-leaks.sh --range R --waiver`:
    import_guard.py --range-waiver <monorepo-layout.conf> <REV-RANGE>
(cwd = the checkout being scanned). The same strict loader reads the conf.
A waived commit is skipped only when it is in REV-RANGE, `ingester_tip` is in
REV-RANGE, and the commit is `ingester_tip` or an ancestor of it; so a PR
cannot waive its own commit without re-pinning `ingester_tip`. A range with
no waived id in it (every PR after the import) leaves the waiver inactive;
once one is in it, every waived id must also name a commit in the clone.
  rc 0, "WAIVED <sha>" per skipped commit, then "WAIVER-OK <n>"
                                      (no conf or an empty waiver: "WAIVER-OK 0")
  rc 1, reason lines, "WAIVER-REFUSED" a malformed conf, or a waived id that
                                      fails the binding (each one named)
  rc 2, "WAIVER-REFUSED"              internal error
"""
from __future__ import annotations

import os
import re
import selectors
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

VERDICT_NOT_IMPORT = "NOT-IMPORT"
VERDICT_IMPORT = "IMPORT"
VERDICT_REFUSED = "IMPORT-REFUSED"
CONF_LABEL = ".claude/governance/monorepo-layout.conf (hook checkout)"
WAIVER_MODE = "--range-waiver"
WAIVER_CONF_LABEL = ".claude/governance/monorepo-layout.conf (scanned checkout)"
VERDICT_WAIVED = "WAIVED"
VERDICT_WAIVER_OK = "WAIVER-OK"
VERDICT_WAIVER_REFUSED = "WAIVER-REFUSED"

# The conf schema (key names and value shapes) is code; the values are config.
SHA_KEYS = ("ingester_tip", "ingester_root_commit", "app_anchor")
INT_KEYS = ("git_timeout_seconds", "max_git_output_bytes", "max_message_chars")
PATH_KEYS = ("ingester_prefix",)
PATH_LIST_KEYS = ("follow_probe_paths",)
URL_KEYS = ("ingester_remote_url",)
REQUIRED_KEYS = frozenset(SHA_KEYS + INT_KEYS + PATH_KEYS + PATH_LIST_KEYS + URL_KEYS)
# Read by the #125 evidence-scan pre-flight, not by import mode; accepted here
# so the shared conf loads. Missing or empty is allowed; otherwise
# space-separated full 40-hex SHAs, no duplicates (same rule as the pre-flight).
WAIVER_KEY = "waived_history_commits"
SHA_LIST_KEYS = (WAIVER_KEY,)
KNOWN_KEYS = REQUIRED_KEYS | frozenset(SHA_LIST_KEYS)

_SHA40 = re.compile(r"[0-9a-f]{40}")
_OBJECT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_KEY = re.compile(r"[a-z][a-z_]*")
_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")
# Up to 12 digits keeps every value an ordinary int; zero is not a usable cap.
_POSITIVE_INT = re.compile(r"[1-9][0-9]{0,11}")
_URL = re.compile(r"https://[!-~]+")
_READ_CHUNK = 65536
_TREE_MODE = b"040000"


class Refusal(Exception):
    """A proof failed or the conf is unusable: the hook must refuse."""


@dataclass(frozen=True)
class Conf:
    tip: str
    root: str
    prefix: tuple[str, ...]
    timeout_s: int
    max_output: int
    max_chars: int
    # waived_history_commits, in conf order; empty when the key is absent or empty.
    waived: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Conf loader: strict, fail closed (F13). Messages name the key and the line,
# never the value, so a hostile value cannot reach the terminal.
# ---------------------------------------------------------------------------
def _valid_path(value: str) -> bool:
    segs = value.split("/")
    return all(_SEGMENT.fullmatch(s) and s not in (".", "..") for s in segs)


def _check_value(key: str, value: str) -> bool:
    if key in SHA_KEYS:
        return _SHA40.fullmatch(value) is not None
    if key in INT_KEYS:
        return _POSITIVE_INT.fullmatch(value) is not None
    if key in PATH_KEYS:
        return _valid_path(value)
    if key in PATH_LIST_KEYS:
        items = value.split(" ")
        return all(_valid_path(i) for i in items)
    if key in SHA_LIST_KEYS:
        if not value:
            return True
        shas = value.split(" ")
        return all(_SHA40.fullmatch(s) for s in shas) and len(set(shas)) == len(shas)
    return _URL.fullmatch(value) is not None


def load_conf(path: Path, label: str = CONF_LABEL) -> Conf | None:
    """None when the file is absent (no exemption); Refusal when malformed.

    `label` names the conf in messages (the hook's or the scanned checkout's)."""
    if not os.path.lexists(path):
        return None
    if not path.is_file():
        raise Refusal(f"{label} is not a regular file")
    data = path.read_bytes()
    # Printable ASCII and LF only: rejects CR, BOM, NUL, tabs, non-ASCII,
    # invalid UTF-8 and invisible characters in one rule (allowlist).
    if any(not (0x20 <= b <= 0x7E or b == 0x0A) for b in data):
        raise Refusal(f"{label} has a byte outside printable ASCII")
    values: dict[str, str] = {}
    for number, line in enumerate(data.decode("ascii").split("\n"), start=1):
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not _KEY.fullmatch(key):
            raise Refusal(f"{label} line {number} is not key=value")
        if key not in KNOWN_KEYS:
            raise Refusal(f"{label} line {number} has an unknown key")
        if key in values:
            raise Refusal(f"{label} line {number} repeats key {key}")
        if not _check_value(key, value):
            raise Refusal(f"{label} line {number} has a malformed {key}")
        values[key] = value
    missing = sorted(REQUIRED_KEYS - values.keys())
    if missing:
        raise Refusal(f"{label} lacks key(s) {', '.join(missing)}")
    if values["ingester_root_commit"] == values["ingester_tip"]:
        raise Refusal(f"{label} pins the same commit as root and tip")
    return Conf(
        tip=values["ingester_tip"],
        root=values["ingester_root_commit"],
        prefix=tuple(values["ingester_prefix"].split("/")),
        timeout_s=int(values["git_timeout_seconds"]),
        max_output=int(values["max_git_output_bytes"]),
        max_chars=int(values["max_message_chars"]),
        waived=tuple(values[WAIVER_KEY].split(" ")) if values.get(WAIVER_KEY) else (),
    )


# ---------------------------------------------------------------------------
# git calls: one deadline and one output cap each (conf values), stderr
# discarded, the child killed and reaped on every exit path.
# ---------------------------------------------------------------------------
def _git(conf: Conf, *args: str) -> tuple[int, bytes]:
    proc = subprocess.Popen(
        ["git", *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    assert proc.stdout is not None
    deadline = time.monotonic() + conf.timeout_s
    chunks: list[bytes] = []
    total = 0
    sel = selectors.DefaultSelector()
    try:
        sel.register(proc.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Refusal(f"import check: git {args[0]} timed out")
            if not sel.select(remaining):
                continue
            chunk = os.read(proc.stdout.fileno(), _READ_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > conf.max_output:
                raise Refusal(f"import check: git {args[0]} output exceeds the cap")
            chunks.append(chunk)
        try:
            rc = proc.wait(timeout=max(deadline - time.monotonic(), 0.001))
        except subprocess.TimeoutExpired as exc:
            raise Refusal(f"import check: git {args[0]} timed out") from exc
    finally:
        sel.close()
        proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return rc, b"".join(chunks)


def _object_id(conf: Conf, *args: str) -> str | None:
    rc, out = _git(conf, *args)
    text = out.decode("ascii", "replace").strip()
    if rc != 0 or not _OBJECT_ID.fullmatch(text):
        return None
    return text


def _head(conf: Conf) -> str | None:
    """HEAD's commit id; None on an unborn branch; Refusal if unreadable."""
    head = _object_id(conf, "rev-parse", "--verify", "-q", "HEAD^{commit}")
    if head is not None:
        return head
    # An unborn branch: HEAD is a symbolic ref to a branch with no commit.
    rc, _ = _git(conf, "symbolic-ref", "-q", "HEAD")
    if rc == 0:
        return None
    raise Refusal("import check: cannot read HEAD")


def _tree_entries(conf: Conf, tree: str) -> list[tuple[bytes, bytes, bytes]]:
    rc, out = _git(conf, "ls-tree", "-z", tree)
    if rc != 0:
        raise Refusal("import check: cannot list the tree being committed")
    entries: list[tuple[bytes, bytes, bytes]] = []
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, _, name = rec.partition(b"\t")
        fields = meta.split(b" ")
        if len(fields) != 3:
            raise Refusal("import check: unexpected git ls-tree output")
        entries.append((fields[0], fields[2], name))
    return entries


def prove(conf: Conf) -> str:
    """Return the committed tree id when every proof holds; Refusal otherwise.

    Only called when HEAD == tip, so every failure here is a hard refusal.
    """
    rc, out = _git(conf, "rev-list", "--max-parents=0", "HEAD")
    if rc != 0:
        raise Refusal("import check: cannot list the root commits of HEAD")
    if out.split() != [conf.root.encode("ascii")]:
        raise Refusal(
            "import check: HEAD is the pinned ingester tip, but its history does not have "
            "exactly one root, the pinned ingester_root_commit"
        )
    tip_tree = _object_id(conf, "rev-parse", "--verify", "-q", f"{conf.tip}^{{tree}}")
    tree = _object_id(conf, "write-tree")
    if tip_tree is None or tree is None:
        raise Refusal("import check: cannot build the tree being committed (unmerged entries?)")
    current = tree
    for depth, seg in enumerate(conf.prefix, start=1):
        entries = _tree_entries(conf, current)
        if len(entries) != 1 or entries[0][0] != _TREE_MODE or entries[0][2] != seg.encode("ascii"):
            shown = "/".join(conf.prefix[:depth])[: conf.max_chars]
            raise Refusal(
                "import check: the tree being committed must hold only "
                f"{shown}/ at that level; it holds other entries"
            )
        current = entries[0][1].decode("ascii")
    if current != tip_tree:
        raise Refusal(
            "import check: the tree under ingester_prefix differs from the pinned ingester tip's tree"
        )
    return tree


def decide(conf_path: Path) -> tuple[int, list[str]]:
    try:
        conf = load_conf(conf_path)
    except Refusal as exc:
        return 1, [f"import check: {exc}; every commit is refused until it is fixed", VERDICT_REFUSED]
    if conf is None:
        return 0, [VERDICT_NOT_IMPORT]
    try:
        head = _head(conf)
        if head != conf.tip:
            return 0, [VERDICT_NOT_IMPORT]
        tree = prove(conf)
    except Refusal as exc:
        return 1, [str(exc)[: conf.max_chars], VERDICT_REFUSED]
    return 0, [f"{VERDICT_IMPORT} {conf.tip} {tree}"]


# ---------------------------------------------------------------------------
# Bound waiver for the CI range scan (#125). Every git call is bounded by the
# conf's own deadline and output cap; every refusal names the full id.
# ---------------------------------------------------------------------------
def _commit_set(conf: Conf, *revs: str) -> set[str]:
    rc, out = _git(conf, "rev-list", "--end-of-options", *revs)
    if rc != 0:
        raise Refusal("waiver check: git rev-list failed for the scanned range or ingester_tip")
    return set(out.decode("ascii", "replace").split())


def _bind_waiver(conf: Conf, rev_range: str) -> tuple[list[str], list[str]]:
    """(waived ids to skip, refusal lines). Refusals name every failing id."""
    scanned = _commit_set(conf, rev_range)
    inside = [w for w in conf.waived if w in scanned]
    outside = [w for w in conf.waived if w not in scanned]
    if not inside:
        # Inactive: the range holds no waived commit (every PR after the
        # import), so nothing is skipped and nothing needs binding.
        return [], []
    refusals: list[str] = []
    # Active waiver: an id outside the range skips nothing, but a typo or a
    # ghost id still fails closed. One git call for all of them; per-id
    # lookups only to name a failure.
    if outside and _git(conf, "rev-list", "--no-walk", "--end-of-options", *outside)[0] != 0:
        for w in outside:
            if _object_id(conf, "rev-parse", "--verify", "-q", f"{w}^{{commit}}") is None:
                refusals.append(f"waiver check: {WAIVER_KEY} entry {w} names no commit in this clone")
        if not refusals:
            refusals.append(f"waiver check: cannot resolve the {WAIVER_KEY} entries outside the scanned range")
    if _object_id(conf, "rev-parse", "--verify", "-q", f"{conf.tip}^{{commit}}") != conf.tip:
        refusals += [
            f"waiver check: {WAIVER_KEY} entry {w} refused: ingester_tip {conf.tip} names no commit"
            for w in inside
        ]
    elif conf.tip not in scanned:
        refusals += [
            f"waiver check: {WAIVER_KEY} entry {w} refused: ingester_tip {conf.tip} is not in the scanned range"
            for w in inside
        ]
    else:
        pinned = _commit_set(conf, conf.tip)
        refusals += [
            f"waiver check: {WAIVER_KEY} entry {w} refused: not ingester_tip or an ancestor of it"
            for w in inside
            if w not in pinned
        ]
    return inside, [line[: conf.max_chars] for line in refusals]


def decide_waiver(conf_path: Path, rev_range: str) -> tuple[int, list[str]]:
    try:
        conf = load_conf(conf_path, WAIVER_CONF_LABEL)
    except Refusal as exc:
        return 1, [f"waiver check: {exc}; the range scan fails closed until it is fixed", VERDICT_WAIVER_REFUSED]
    if conf is None or not conf.waived:
        return 0, [f"{VERDICT_WAIVER_OK} 0"]
    try:
        skip, refusals = _bind_waiver(conf, rev_range)
    except Refusal as exc:
        return 1, [str(exc)[: conf.max_chars], VERDICT_WAIVER_REFUSED]
    if refusals:
        return 1, [*refusals, VERDICT_WAIVER_REFUSED]
    return 0, [*(f"{VERDICT_WAIVED} {w}" for w in skip), f"{VERDICT_WAIVER_OK} {len(skip)}"]


def _terminate(signum: int, _frame: object) -> None:
    # Turn SIGTERM/SIGHUP into SystemExit so the finally blocks kill git.
    raise SystemExit(128 + signum)


def main(argv: list[str]) -> int:
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGHUP, _terminate)
    if argv[:1] == [WAIVER_MODE]:
        if len(argv) != 3:
            print(f"waiver check: expected {WAIVER_MODE} CONF REV-RANGE, got {len(argv)} argument(s)")
            print(VERDICT_WAIVER_REFUSED)
            return 2
        try:
            rc, lines = decide_waiver(Path(argv[1]), argv[2])
        except Exception as exc:  # fail closed on anything unexpected (F4)
            print(f"waiver check: internal error: {type(exc).__name__}")
            print(VERDICT_WAIVER_REFUSED)
            return 2
        for line in lines:
            print(line)
        return rc
    if len(argv) != 1:
        print(f"import check: expected 1 argument, got {len(argv)}")
        print(VERDICT_REFUSED)
        return 2
    try:
        rc, lines = decide(Path(argv[0]))
    except Exception as exc:  # fail closed on anything unexpected (F4)
        print(f"import check: internal error: {type(exc).__name__}")
        print(VERDICT_REFUSED)
        return 2
    for line in lines:
        print(line)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
