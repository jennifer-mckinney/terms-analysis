#!/usr/bin/env bash
# check-roadmap-ssot.sh (#156, plan A5)
#
# The BRD "Implementation Roadmap" section is the project's single roadmap.
# This check fails unless all of the following hold:
#
#   todo-file             todo_path is absent, or a regular file (not a
#                         symlink, not under a symlinked directory) that is
#                         valid UTF-8, has no NUL byte and fits max_doc_bytes.
#   todo-sprint-heading   if todo_path exists, its first ATX heading (outside
#                         code fences and HTML comments) contains the word
#                         sprint_keyword and an ISO date range
#                         YYYY-MM-DD <to|-|..|en dash|em dash> YYYY-MM-DD, with
#                         real dates, start <= end, and no control, format,
#                         line/paragraph-separator or unassigned characters.
#   todo-roadmap-link     if todo_path exists, it has an inline markdown link
#                         to the BRD's roadmap anchor, e.g.
#                         [roadmap](BRD_Terms_Policies_Reviewer.md#implementation-roadmap)
#                         (relative to todo_path, optional "./", optional title).
#   brd-file              brd_path exists and passes the same file checks.
#   brd-roadmap-section   brd_path has exactly one roadmap_heading (outside
#                         code fences and HTML comments).
#   brd-roadmap-checked   that section (up to the next heading of the same or a
#                         higher level) has >= min_checked_boxes checked GFM
#                         task items ("- [x]", "* [X]", "1. [x]"). Boxes in other
#                         sections, code fences, HTML comments or prose are not
#                         counted.
#   stray-todo-reference  git grep finds no tracked reference to todo_path in
#                         reference_scope, unless todo_path is a valid sprint
#                         list (todo-file, todo-sprint-heading and
#                         todo-roadmap-link all hold).
#
# Every value above lives in .claude/governance/roadmap-ssot.conf (F13). The
# roadmap anchor is derived from roadmap_heading, never configured twice.
#
# Usage: check-roadmap-ssot.sh [REPO_ROOT]   (default: the git toplevel)
#
# Exit codes:
#   0  every condition holds; stdout carries "ROADMAP-SSOT OK" with counts
#   1  one or more conditions fail; stderr has one "FAIL [<id>]" line per
#      violated condition, then "ROADMAP-SSOT FAIL: <n> violation(s)"
#   2  the check could not run: usage, repo root, config, git error, git
#      timeout or git output cap ("ROADMAP-SSOT ERROR [<id>]")
#
# Messages never contain absolute paths or raw bytes from the checked files.

set -euo pipefail

readonly CONFIG_REL=".claude/governance/roadmap-ssot.conf"

# F7: GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE and friends could point git at a
# different repository from the one being checked. Drop every GIT_* variable.
for _var in $(compgen -e); do
    case "${_var}" in GIT_*) unset "${_var}" ;; esac
done
unset _var

if [ "$#" -gt 1 ]; then
    echo "ROADMAP-SSOT ERROR [usage]: expected at most one argument, the repo root" >&2
    exit 2
fi
for _tool in git python3; do
    if ! command -v "${_tool}" >/dev/null 2>&1; then
        echo "ROADMAP-SSOT ERROR [usage]: ${_tool} is required but not on PATH" >&2
        exit 2
    fi
done
unset _tool

if [ "$#" -eq 1 ]; then
    ROOT="$1"
else
    if ! ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
        echo "ROADMAP-SSOT ERROR [usage]: not inside a git work tree; pass the repo root" >&2
        exit 2
    fi
fi

# -I: isolated mode, so nothing in the cwd or env can shadow a stdlib import.
exec python3 -I - "${ROOT}" "${CONFIG_REL}" <<'PY'
from __future__ import annotations

import datetime
import os
import posixpath
import re
import select
import stat
import subprocess
import sys
import time
import unicodedata
from typing import Iterator, NoReturn

EXIT_OK, EXIT_VIOLATION, EXIT_ERROR = 0, 1, 2
TAG = "ROADMAP-SSOT"

PATH_KEYS = ("todo_path", "brd_path")
INT_KEYS = (
    "min_checked_boxes",
    "max_doc_bytes",
    "git_timeout_seconds",
    "max_git_output_bytes",
    "max_listed_hits",
    "max_message_chars",
)
REQUIRED_KEYS = frozenset(PATH_KEYS + INT_KEYS + ("roadmap_heading", "sprint_keyword", "reference_scope"))

SEGMENT_RE = re.compile(r"[A-Za-z0-9._-]+")
POSINT_RE = re.compile(r"[1-9][0-9]{0,8}")
CONFIG_HEADING_RE = re.compile(r"(#{1,6}) ([!-~](?:[ -~]*[!-~])?)")
WORD_RE = re.compile(r"[A-Za-z]+")
KEY_RE = re.compile(r"[a-z_]+")

# CommonMark line endings: CRLF, lone CR, LF. Nothing else ends a line, so a
# U+2028 or NEL inside a heading stays inside that heading and is rejected.
LINE_SPLIT_RE = re.compile(r"\r\n|\r|\n")
FENCE_OPEN_RE = re.compile(r" {0,3}(`{3,}|~{3,})")
ATX_RE = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*?))??(?:[ \t]+#+)?[ \t]*\Z")
SETEXT_RE = re.compile(r" {0,3}(=+|-+)[ \t]*\Z")
LIST_ITEM_RE = re.compile(r"[ \t]*(?:[-*+]|[0-9]{1,9}[.)])[ \t]")
TASK_RE = re.compile(r"[ \t]*(?:[-*+]|[0-9]{1,9}[.)])[ \t]+\[([ xX])\](?:[ \t]|\Z)")
DATE = r"([0-9]{4})-([0-9]{2})-([0-9]{2})"
DATE_RANGE_RE = re.compile(
    r"(?<![0-9])" + DATE + r"[ \t]*(?:to|\.\.|-|–|—)[ \t]*" + DATE + r"(?![0-9])"
)
# Unicode categories never allowed in the sprint heading: control, format
# (zero-width, bidi), surrogate, private use, unassigned, line and paragraph
# separators.
FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})


class CheckError(Exception):
    """The check cannot run (exit 2)."""

    def __init__(self, ident: str, message: str) -> None:
        super().__init__(message)
        self.ident = ident
        self.message = message


def die(err: CheckError) -> NoReturn:
    print(f"{TAG} ERROR [{err.ident}]: {err.message}", file=sys.stderr)
    sys.exit(EXIT_ERROR)


def safe(text: str, limit: int) -> str:
    """Printable ASCII only, truncated: never echo raw bytes (F2, F8)."""
    out = "".join(c if " " <= c <= "~" else "?" for c in text)
    return out if len(out) <= limit else out[:limit] + "..."


def check_rel_path(key: str, value: str) -> str:
    segments = value.split("/")
    for seg in segments:
        if seg in ("", ".", "..") or not SEGMENT_RE.fullmatch(seg):
            raise CheckError("config", f"{key} must be a repo-relative path of [A-Za-z0-9._-] segments")
    return value


def load_config(root: str, config_rel: str) -> dict[str, object]:
    path = os.path.join(root, config_rel)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise CheckError("config", f"{config_rel} is missing")
    except OSError:
        raise CheckError("config", f"{config_rel} cannot be read")
    if not stat.S_ISREG(st.st_mode):
        raise CheckError("config", f"{config_rel} must be a regular file, not a symlink or directory")
    try:
        with open(path, "rb") as fh:
            blob = fh.read()
    except OSError:
        raise CheckError("config", f"{config_rel} cannot be read")
    try:
        text = blob.decode("ascii")
    except UnicodeDecodeError:
        raise CheckError("config", f"{config_rel} must be ASCII")
    raw: dict[str, str] = {}
    for number, line in enumerate(text.split("\n"), 1):
        if any(not (" " <= c <= "~") for c in line):
            raise CheckError("config", f"{config_rel} line {number} has a control character")
        if not line.strip() or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not KEY_RE.fullmatch(key):
            raise CheckError("config", f"{config_rel} line {number} is not key=value")
        if key not in REQUIRED_KEYS:
            raise CheckError("config", f"{config_rel} line {number}: unknown key {key}")
        if key in raw:
            raise CheckError("config", f"{config_rel} line {number}: duplicate key {key}")
        raw[key] = value
    missing = sorted(REQUIRED_KEYS - set(raw))
    if missing:
        raise CheckError("config", f"{config_rel} is missing key(s): {', '.join(missing)}")

    cfg: dict[str, object] = {}
    for key in PATH_KEYS:
        cfg[key] = check_rel_path(key, raw[key])
    if cfg["todo_path"] == cfg["brd_path"]:
        raise CheckError("config", "todo_path and brd_path must differ")
    for key in INT_KEYS:
        if not POSINT_RE.fullmatch(raw[key]):
            raise CheckError("config", f"{key} must be a positive integer")
        cfg[key] = int(raw[key])
    match = CONFIG_HEADING_RE.fullmatch(raw["roadmap_heading"])
    if not match:
        raise CheckError("config", "roadmap_heading must be '#'x1-6, one space, then printable ASCII text")
    cfg["heading_level"] = len(match.group(1))
    cfg["heading_text"] = match.group(2)
    anchor = re.sub(r"[^a-z0-9 _-]", "", match.group(2).lower()).replace(" ", "-")
    if not anchor:
        raise CheckError("config", "roadmap_heading has no text to derive an anchor from")
    cfg["anchor"] = anchor
    if not WORD_RE.fullmatch(raw["sprint_keyword"]):
        raise CheckError("config", "sprint_keyword must be ASCII letters only")
    cfg["sprint_keyword"] = raw["sprint_keyword"]
    scope = raw["reference_scope"].split(" ")
    cfg["reference_scope"] = [check_rel_path("reference_scope", item) for item in scope]
    return cfg


def resolve_root(arg: str) -> str:
    if not arg:
        raise CheckError("usage", "the repo root argument is empty")
    if not os.path.isdir(arg):
        raise CheckError("usage", "the repo root is not a directory")
    root = os.path.realpath(arg)
    # Cheap pre-check so a wrong root is reported as such, not as a missing
    # config; verify_toplevel() confirms it with git once the caps are loaded.
    if not os.path.lexists(os.path.join(root, ".git")):
        raise CheckError("usage", "the repo root is not the top of a git work tree (no .git)")
    return root


def verify_toplevel(root: str, timeout: int, cap: int) -> None:
    """F7: the root must be the top of its own work tree, not a subdirectory."""
    code, out = run_bounded(["git", "-C", root, "rev-parse", "--show-toplevel"], timeout, cap)
    if code != 0:
        raise CheckError("usage", "the repo root is not inside a git work tree")
    top = out.decode("utf-8", "surrogateescape").rstrip("\n")
    if os.path.realpath(top) != root:
        raise CheckError("usage", "the repo root is not the top of its git work tree")


def read_doc(root: str, rel: str, cap: int) -> tuple[str | None, str | None]:
    """Return (text, None), (None, None) if absent, or (None, problem)."""
    current = root
    parts = rel.split("/")
    for index, part in enumerate(parts):
        current = os.path.join(current, part)
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            return None, None
        except OSError:
            return None, "cannot be inspected"
        if stat.S_ISLNK(st.st_mode):
            return None, "is or sits under a symlink; it must be a regular file inside the repo"
        last = index == len(parts) - 1
        if not last and not stat.S_ISDIR(st.st_mode):
            return None, "has a parent that is not a directory"
        if last and not stat.S_ISREG(st.st_mode):
            return None, "is not a regular file"
    try:
        with open(current, "rb") as fh:
            blob = fh.read(cap + 1)
    except OSError:
        return None, "cannot be read"
    if len(blob) > cap:
        return None, f"is larger than max_doc_bytes={cap}"
    if b"\x00" in blob:
        return None, "contains a NUL byte"
    try:
        return blob.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "is not valid UTF-8"


def content_lines(text: str) -> Iterator[tuple[int, str]]:
    """Lines that markdown renders as content: not in fences or HTML comments."""
    fence: str | None = None
    in_comment = False
    for number, line in enumerate(LINE_SPLIT_RE.split(text), 1):
        if fence is not None:
            close = re.fullmatch(r" {0,3}(`{3,}|~{3,})[ \t]*", line)
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= len(fence):
                fence = None
            continue
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        opened = FENCE_OPEN_RE.match(line)
        if opened:
            fence = opened.group(1)
            continue
        comment = re.match(r" {0,3}<!--", line)
        if comment:
            if "-->" not in line[comment.end():]:
                in_comment = True
            continue
        yield number, line


def headings(text: str) -> Iterator[tuple[int, int, str]]:
    """(line number, level, text) for ATX and setext headings in content."""
    previous: str | None = None
    for number, line in content_lines(text):
        atx = ATX_RE.match(line)
        if atx:
            yield number, len(atx.group(1)), atx.group(2) or ""
            previous = None
            continue
        setext = SETEXT_RE.match(line)
        if (
            setext
            and previous is not None
            and previous.strip()
            and not LIST_ITEM_RE.match(previous)
        ):
            yield number, 1 if setext.group(1)[0] == "=" else 2, previous.strip()
        previous = line


def valid_date(year: str, month: str, day: str) -> datetime.date | None:
    try:
        return datetime.date(int(year), int(month), int(day))
    except ValueError:
        return None


def sprint_heading_ok(heading: str, keyword: str) -> bool:
    if any(unicodedata.category(c) in FORBIDDEN_CATEGORIES for c in heading):
        return False
    if not re.search(r"(?<![A-Za-z])" + re.escape(keyword) + r"(?![A-Za-z])", heading):
        return False
    for match in DATE_RANGE_RE.finditer(heading):
        start = valid_date(*match.group(1, 2, 3))
        end = valid_date(*match.group(4, 5, 6))
        if start is not None and end is not None and start <= end:
            return True
    return False


def run_bounded(cmd: list[str], timeout: int, cap: int) -> tuple[int, bytes]:
    """Run a git command with a total deadline and a stdout byte cap (F6)."""
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        raise CheckError("git", "git could not be started")
    assert proc.stdout is not None
    deadline = time.monotonic() + timeout
    buf = bytearray()
    try:
        fd = proc.stdout.fileno()
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise CheckError("git-timeout", f"git ran longer than git_timeout_seconds={timeout}")
            ready, _, _ = select.select([fd], [], [], left)
            if not ready:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > cap:
                raise CheckError("git-output", f"git printed more than max_git_output_bytes={cap}")
        try:
            code = proc.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise CheckError("git-timeout", f"git ran longer than git_timeout_seconds={timeout}")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
    return code, bytes(buf)


def stray_references(root: str, cfg: dict[str, object], config_rel: str) -> list[tuple[str, int]]:
    # The config itself names todo_path, so it is excluded from the search;
    # literal magic keeps glob characters in any path from widening the match.
    cmd = [
        "git",
        "-c", "core.quotePath=true",
        "-c", "core.fsmonitor=false",
        "-c", "submodule.recurse=false",
        "-c", "grep.fallbackToNoIndex=false",
        "-C", root,
        "grep", "-I", "-c", "-F", "-e", str(cfg["todo_path"]), "--",
        *[str(p) for p in cfg["reference_scope"]],  # type: ignore[attr-defined]
        f":(top,literal,exclude){config_rel}",
    ]
    code, out = run_bounded(cmd, int(cfg["git_timeout_seconds"]), int(cfg["max_git_output_bytes"]))  # type: ignore[call-overload]
    if code == 1 and not out:
        return []
    if code != 0:
        raise CheckError("git", f"git grep failed with exit {code}")
    hits: list[tuple[str, int]] = []
    for line in out.decode("utf-8", "replace").splitlines():
        name, sep, count = line.rpartition(":")
        if not sep or not count.isdigit():
            raise CheckError("git", "git grep printed an unexpected line")
        hits.append((name, int(count)))
    if not hits:
        raise CheckError("git", "git grep reported a match but printed none")
    return hits


def main(argv: list[str]) -> int:
    root = resolve_root(argv[1])
    cfg = load_config(root, argv[2])
    verify_toplevel(root, int(cfg["git_timeout_seconds"]), int(cfg["max_git_output_bytes"]))  # type: ignore[call-overload]
    limit = int(cfg["max_message_chars"])  # type: ignore[call-overload]
    todo_rel = str(cfg["todo_path"])
    brd_rel = str(cfg["brd_path"])
    heading_line = "#" * int(cfg["heading_level"]) + " " + str(cfg["heading_text"])  # type: ignore[call-overload]
    link_target = posixpath.relpath(brd_rel, posixpath.dirname(todo_rel) or ".") + "#" + str(cfg["anchor"])
    violations: list[tuple[str, str]] = []

    # ---- todo_path: absent, or a dated sprint list that links the roadmap ----
    todo_text, todo_problem = read_doc(root, todo_rel, int(cfg["max_doc_bytes"]))  # type: ignore[call-overload]
    todo_state = "absent"
    if todo_problem is not None:
        violations.append(("todo-file", f"{todo_rel} {todo_problem}. Delete it, or make it a plain sprint-list file."))
        todo_state = "invalid"
    elif todo_text is not None:
        todo_state = "sprint-list"
        first = next(headings(todo_text), None)
        if first is None or not sprint_heading_ok(first[2], str(cfg["sprint_keyword"])):
            where = "has no heading" if first is None else f"line {first[0]}: first heading is not a dated sprint heading"
            violations.append((
                "todo-sprint-heading",
                f"{todo_rel} {where}. Delete {todo_rel} (the BRD roadmap is the roadmap) or start it with "
                f"'# {cfg['sprint_keyword']} YYYY-MM-DD to YYYY-MM-DD' (plain text, real dates, start <= end).",
            ))
            todo_state = "invalid"
        link_re = re.compile(
            r"\]\((?:\./)?" + re.escape(link_target) + r"(?:[ \t]+\"[^\"]*\")?\)"
        )
        if not any(link_re.search(line) for _, line in content_lines(todo_text)):
            violations.append((
                "todo-roadmap-link",
                f"{todo_rel} has no markdown link to {link_target}. Add [roadmap]({link_target}), "
                "outside code fences and HTML comments.",
            ))
            todo_state = "invalid"

    # ---- brd_path: one roadmap section with checked boxes ----
    checked = unchecked = 0
    brd_text, brd_problem = read_doc(root, brd_rel, int(cfg["max_doc_bytes"]))  # type: ignore[call-overload]
    if brd_problem is not None or brd_text is None:
        problem = brd_problem or "is missing"
        violations.append(("brd-file", f"{brd_rel} {problem}. The BRD roadmap is the single roadmap; restore it."))
    else:
        level = int(cfg["heading_level"])  # type: ignore[call-overload]
        found = [
            (number, lvl) for number, lvl, text in headings(brd_text)
            if lvl == level and text == cfg["heading_text"]
        ]
        if len(found) != 1:
            violations.append((
                "brd-roadmap-section",
                f"{brd_rel} has {len(found)} '{heading_line}' heading(s); exactly 1 is required "
                "(outside code fences and HTML comments).",
            ))
        else:
            start = found[0][0]
            end = None
            for number, lvl, _ in headings(brd_text):
                if number > start and lvl <= level:
                    end = number
                    break
            for number, line in content_lines(brd_text):
                if number <= start or (end is not None and number >= end):
                    continue
                task = TASK_RE.match(line)
                if task:
                    if task.group(1) == " ":
                        unchecked += 1
                    else:
                        checked += 1
            minimum = int(cfg["min_checked_boxes"])  # type: ignore[call-overload]
            if checked < minimum:
                violations.append((
                    "brd-roadmap-checked",
                    f"{brd_rel} '{heading_line}' has checked={checked} unchecked={unchecked}; "
                    f"min_checked_boxes={minimum}. Tick the roadmap items that have shipped.",
                ))

    # ---- references to todo_path in reference_scope ----
    hits = stray_references(root, cfg, argv[2])
    total = sum(count for _, count in hits)
    if hits and todo_state != "sprint-list":
        cap = int(cfg["max_listed_hits"])  # type: ignore[call-overload]
        named = ", ".join(f"{safe(name, limit)} ({count})" for name, count in hits[:cap])
        more = f", and {len(hits) - cap} more file(s)" if len(hits) > cap else ""
        violations.append((
            "stray-todo-reference",
            f"{total} reference(s) to {todo_rel} in {' '.join(cfg['reference_scope'])}: "  # type: ignore[arg-type]
            f"{named}{more}. Point them at {brd_rel}#{cfg['anchor']}, or make {todo_rel} a valid sprint list.",
        ))

    if violations:
        for ident, message in violations:
            print(f"FAIL [{ident}]: {message}", file=sys.stderr)
        print(f"{TAG} FAIL: {len(violations)} violation(s)", file=sys.stderr)
        return EXIT_VIOLATION
    print(
        f"{TAG} OK: roadmap checked={checked} unchecked={unchecked}; "
        f"todo={todo_state}; references={total}"
    )
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except CheckError as err:
        die(err)
PY
