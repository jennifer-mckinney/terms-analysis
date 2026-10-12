#!/usr/bin/env python3
"""Check the architecture decision records in docs/adr (#161, #327).

Usage: check-adrs.py [REPO_ROOT]

REPO_ROOT defaults to the repository that holds this script, never the cwd.
CI runs this script through src/backend/tests/test_adrs.py, which also pins
the contract below.

Config: .claude/governance/adr-policy.conf under REPO_ROOT. One key=value per
line; '#' comment lines and blank lines are ignored; every key in CONFIG_KEYS
is required exactly once. A missing file, an unknown, duplicate, empty or
malformed key, a non-ASCII byte, a path that is absolute or contains '..', or
a value outside its type fails closed (exit 2, id "config").

ADRs: every entry of adr_dir except index_file. Each must be named
<number_digits ASCII digits>-<slug>.md with slug [a-z0-9-]+, else
adr-filename; a misnamed entry is not numbered or indexed.

Parsing: lines split on LF only (one trailing CR is ignored). Text inside
code fences and HTML comments is not structure. The header is everything
before the first level-2 heading. Header fields are bullets
"- **Key:** value". A line with any character outside printable ASCII is
never a field or a heading, so invisible or look-alike characters and
Unicode line breaks cannot forge one.

Exit codes and output (all output is printable ASCII; files are named
relative to adr_dir, with any other character escaped; nothing read from a
checked file is echoed apart from its name):
  0  stdout "ADR-CHECK OK: <n> ADR(s)", n = ADR files checked.
  1  stderr one "FAIL [<id>]: <message>" line per violation, then
     "ADR-CHECK FAIL: <n> violation(s)". Ids:
       adr-file             not a regular file (symlink), invalid UTF-8, NUL,
                            or over max_doc_bytes (also the index file); such
                            a file is not parsed further
       adr-filename         misnamed entry (see above)
       adr-title            first line is not "# ADR <number>: <title>" with
                            the filename's number
       adr-number-duplicate two ADRs share a number
       adr-number-gap       the distinct numbers are not exactly 1..max
       adr-section          a required_sections level-2 heading is missing
       adr-status           no Status field, or its first word is not in
                            statuses
       adr-approval         Status first word in approval_statuses and the
                            header mentions hard_requirement_prefix followed
                            by an ASCII digit, with no Approved-by field
                            holding a configured approver as a whole token
                            (tokens split on whitespace, ',' and ';')
       adr-index            index_file missing, an ADR not linked from it
                            (inline link "](<file>)"), or a link to an
                            ADR-named file that does not exist
       adr-none             adr_dir holds no ADR
  2  stderr "ADR-CHECK ERROR [<id>]: <message>", ids usage, root, config,
     adr-dir (adr_dir missing, not a directory, a symlink, or outside the
     root), internal (an unexpected exception; no traceback is printed).
"""
from __future__ import annotations

import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

CONFIG_REL = ".claude/governance/adr-policy.conf"
CONFIG_KEYS = (
    "adr_dir",
    "index_file",
    "number_digits",
    "required_sections",
    "statuses",
    "approval_statuses",
    "hard_requirement_prefix",
    "approvers",
    "max_doc_bytes",
)
EXIT_OK, EXIT_VIOLATION, EXIT_ERROR = 0, 1, 2
STATUS_FIELD, APPROVED_FIELD = "Status", "Approved-by"

# Allowlists for config values (F1). Every pattern is anchored by fullmatch
# and has no nested quantifier, so matching is linear.
_KEY_LINE = re.compile(r"([a-z_]+)=(.*)", re.ASCII)
_POSITIVE_INT = re.compile(r"[1-9][0-9]*", re.ASCII)
_PATH_PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*", re.ASCII)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9-]*", re.ASCII)
_HANDLE = re.compile(r"@[A-Za-z0-9][A-Za-z0-9-]*", re.ASCII)
_PREFIX = re.compile(r"[A-Za-z]+", re.ASCII)

_PRINTABLE = re.compile(r"[ -~]*", re.ASCII)
_FIELD = re.compile(r"- \*\*([A-Za-z][A-Za-z-]*):\*\*(.*)", re.ASCII)
_LINK = re.compile(r"\]\((?:\./)?([^()\s]+)\)", re.ASCII)
_TOKEN_SPLIT = re.compile(r"[\s,;]+", re.ASCII)


class CheckError(Exception):
    """A fail-closed error that ends the run with exit 2."""

    def __init__(self, ident: str, message: str) -> None:
        super().__init__(message)
        self.ident = ident
        self.message = message


@dataclass(frozen=True)
class Policy:
    adr_dir: str
    index_file: str
    digits: int
    sections: tuple[str, ...]
    statuses: tuple[str, ...]
    approval_statuses: tuple[str, ...]
    hr_prefix: str
    approvers: tuple[str, ...]
    max_doc_bytes: int

    @property
    def index_name(self) -> str:
        return self.index_file.rsplit("/", 1)[-1]


# --------------------------------------------------------------------------
# output: one renderer for every name that reaches the terminal (F2)
# --------------------------------------------------------------------------
def render(text: str) -> str:
    """Printable-ASCII form of a name: every other character is escaped."""
    out = []
    for ch in text:
        if " " <= ch <= "~" and ch != "\\":
            out.append(ch)
        elif ch == "\\":
            out.append("\\\\")
        elif ord(ch) <= 0xFF:
            out.append(f"\\x{ord(ch):02x}")
        elif ord(ch) <= 0xFFFF:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(f"\\U{ord(ch):08x}")
    return "".join(out)


# --------------------------------------------------------------------------
# config (F13): the only place policy values come from
# --------------------------------------------------------------------------
def _relative_path(key: str, value: str) -> str:
    # Each part must start with a letter, digit or '_', so '', '.', '..' and
    # a leading '/' (an empty first part) are all refused by the allowlist.
    if not all(_PATH_PART.fullmatch(part) for part in value.split("/")):
        raise CheckError("config", f"{key} must be a relative path without '..'")
    return value


def _words(key: str, value: str, pattern: re.Pattern[str]) -> tuple[str, ...]:
    words = tuple(value.split(" "))
    if not value or not all(pattern.fullmatch(w) for w in words):
        raise CheckError("config", f"{key} must be a space-separated list of valid entries")
    if len(set(words)) != len(words):
        raise CheckError("config", f"{key} lists an entry twice")
    return words


def _positive_int(key: str, value: str) -> int:
    if not _POSITIVE_INT.fullmatch(value):
        raise CheckError("config", f"{key} must be a positive integer")
    return int(value)


def load_policy(root: Path) -> Policy:
    path = root / CONFIG_REL
    try:
        data = path.read_bytes()
    except OSError:
        raise CheckError("config", f"{CONFIG_REL} is missing or unreadable") from None
    if any(b > 0x7E or (b < 0x20 and b not in (0x0A, 0x0D)) for b in data):
        raise CheckError("config", f"{CONFIG_REL} must be printable ASCII")
    raw: dict[str, str] = {}
    for number, line in enumerate(data.decode("ascii").split("\n"), start=1):
        line = line[:-1] if line.endswith("\r") else line
        if not line.strip() or line.startswith("#"):
            continue
        match = _KEY_LINE.fullmatch(line)
        if not match:
            raise CheckError("config", f"{CONFIG_REL} line {number} is not key=value")
        key, value = match.groups()
        if key not in CONFIG_KEYS:
            raise CheckError("config", f"{CONFIG_REL} line {number} has an unknown key")
        if key in raw:
            raise CheckError("config", f"{CONFIG_REL} sets {key} twice")
        if not value:
            raise CheckError("config", f"{CONFIG_REL} {key} is empty")
        raw[key] = value
    missing = [key for key in CONFIG_KEYS if key not in raw]
    if missing:
        raise CheckError("config", f"{CONFIG_REL} lacks {', '.join(missing)}")

    adr_dir = _relative_path("adr_dir", raw["adr_dir"])
    index_file = _relative_path("index_file", raw["index_file"])
    if index_file.rsplit("/", 1)[0] != adr_dir or "/" not in index_file:
        raise CheckError("config", "index_file must be a file directly inside adr_dir")
    statuses = _words("statuses", raw["statuses"], _WORD)
    approval_statuses = _words("approval_statuses", raw["approval_statuses"], _WORD)
    if not set(approval_statuses) <= set(statuses):
        raise CheckError("config", "approval_statuses must be listed in statuses")
    prefix = raw["hard_requirement_prefix"]
    if not _PREFIX.fullmatch(prefix):
        raise CheckError("config", "hard_requirement_prefix must be ASCII letters")
    return Policy(
        adr_dir=adr_dir,
        index_file=index_file,
        digits=_positive_int("number_digits", raw["number_digits"]),
        sections=_words("required_sections", raw["required_sections"], _WORD),
        statuses=statuses,
        approval_statuses=approval_statuses,
        hr_prefix=prefix,
        approvers=_words("approvers", raw["approvers"], _HANDLE),
        max_doc_bytes=_positive_int("max_doc_bytes", raw["max_doc_bytes"]),
    )


# --------------------------------------------------------------------------
# reading one document: regular file, bounded, strict UTF-8 (F6, F7)
# --------------------------------------------------------------------------
def read_doc(path: Path, limit: int) -> tuple[str | None, str]:
    """(text, "") on success, else (None, reason). Never follows a symlink."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None, "is not a regular file (symlink or unreadable)"
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None, "is not a regular file"
        chunks, size = [], 0
        while size <= limit:
            chunk = os.read(fd, limit + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
    except OSError:
        return None, "could not be read"
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) > limit:
        return None, "is larger than max_doc_bytes"
    if b"\x00" in data:
        return None, "contains a NUL byte"
    try:
        # strict UTF-8 rejects overlong forms and encoded surrogates
        return data.decode("utf-8", "strict"), ""
    except UnicodeDecodeError:
        return None, "is not valid UTF-8"


def structural_lines(text: str) -> list[str | None]:
    """Lines (LF split, one trailing CR dropped) with code fences and HTML
    comments removed. A fenced line becomes None; comment text is cut out of
    its line. Linear in the input size."""
    out: list[str | None] = []
    in_fence = in_comment = False
    for line in text.split("\n"):
        if line.endswith("\r"):
            line = line[:-1]
        if not in_comment and line.lstrip(" ").startswith(("```", "~~~")):
            in_fence = not in_fence
            out.append(None)
            continue
        if in_fence:
            out.append(None)
            continue
        kept, pos = [], 0
        while pos <= len(line):
            if in_comment:
                end = line.find("-->", pos)
                if end < 0:
                    break
                in_comment, pos = False, end + 3
            else:
                start = line.find("<!--", pos)
                if start < 0:
                    kept.append(line[pos:])
                    break
                kept.append(line[pos:start])
                in_comment, pos = True, start + 4
        out.append("".join(kept))
    return out


def is_printable(line: str) -> bool:
    return _PRINTABLE.fullmatch(line) is not None


def level2_heading(line: str | None) -> str | None:
    if line is None or not line.startswith("## ") or not is_printable(line):
        return None
    return line[3:].strip()


# --------------------------------------------------------------------------
# per-ADR checks
# --------------------------------------------------------------------------
def check_adr(policy: Policy, name: str, number: int, text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    shown = render(name)
    raw_lines = text.split("\n")
    first = raw_lines[0][:-1] if raw_lines[0].endswith("\r") else raw_lines[0]
    title = re.fullmatch(rf"# ADR ([0-9]{{{policy.digits}}}): \S.*", first, re.ASCII)
    if not (is_printable(first) and title and int(title.group(1)) == number):
        found.append(("adr-title", f"{shown}: first line must be '# ADR "
                      f"{number:0{policy.digits}d}: <title>' in printable ASCII"))

    lines = structural_lines(text)
    headings: set[str] = set()
    header_end = len(lines)
    for index, line in enumerate(lines):
        heading = level2_heading(line)
        if heading is not None:
            headings.add(heading)
            header_end = min(header_end, index)
    for section in policy.sections:
        if section not in headings:
            found.append(("adr-section", f"{shown}: missing level-2 heading '## {section}'"))

    fields: dict[str, str] = {}
    for line in lines[:header_end]:
        if line is None or not is_printable(line):
            continue
        match = _FIELD.fullmatch(line)
        if match:
            fields.setdefault(match.group(1), match.group(2).strip())

    status_words = fields.get(STATUS_FIELD, "").split()
    status = status_words[0] if status_words else ""
    if status not in policy.statuses:
        found.append(("adr-status", f"{shown}: '- **{STATUS_FIELD}:**' first word must be one of "
                      f"{', '.join(policy.statuses)}"))

    # The mention test reads the raw header lines, comments included, so a
    # hard requirement hidden in a comment still demands approval (fail closed).
    header_raw = "\n".join(raw_lines[:header_end])
    mentions_hr = re.search(re.escape(policy.hr_prefix) + "[0-9]", header_raw) is not None
    if status in policy.approval_statuses and mentions_hr:
        tokens = set(_TOKEN_SPLIT.split(fields.get(APPROVED_FIELD, "")))
        if not tokens & set(policy.approvers):
            found.append(("adr-approval", f"{shown}: {status} ADR amends a hard requirement but no "
                          f"'- **{APPROVED_FIELD}:**' field names a configured approver"))
    return found


def check_index(policy: Policy, text: str, adr_names: list[str],
                name_re: re.Pattern[str]) -> list[tuple[str, str]]:
    linked: set[str] = set()
    for line in structural_lines(text):
        if line is not None:
            linked.update(_LINK.findall(line))
    found = [("adr-index", f"{render(name)} is not linked from {render(policy.index_name)}")
             for name in adr_names if name not in linked]
    existing = set(adr_names)
    found += [("adr-index", f"{render(policy.index_name)} links {render(target)}, which does not exist")
              for target in sorted(linked) if name_re.fullmatch(target) and target not in existing]
    return found


def check_numbers(policy: Policy, numbered: dict[int, list[str]]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    width = policy.digits
    for number in sorted(numbered):
        if len(numbered[number]) > 1:
            names = ", ".join(render(n) for n in sorted(numbered[number]))
            found.append(("adr-number-duplicate", f"number {number:0{width}d} is used by {names}"))
    present = sorted(numbered)
    if not present:
        return found
    problems = []
    if present[0] < 1:
        problems.append(f"unexpected {present[0]:0{width}d}")
    # Missing numbers as ranges between neighbours: linear in the file count,
    # however large the highest number is.
    gaps, previous = [], 0
    for number in present:
        if number > previous + 1:
            low, high = previous + 1, number - 1
            gaps.append(f"{low:0{width}d}" if low == high else f"{low:0{width}d}-{high:0{width}d}")
        previous = max(previous, number)
    if gaps:
        problems.append(f"missing {', '.join(gaps)}")
    if problems:
        found.append(("adr-number-gap",
                      "numbers must run from 1 to the highest without gaps; " + "; ".join(problems)))
    return found


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def run(argv: list[str]) -> int:
    if len(argv) > 2:
        raise CheckError("usage", "usage: check-adrs.py [REPO_ROOT]")
    root = Path(argv[1]) if len(argv) == 2 else Path(__file__).resolve().parents[2]
    if not root.is_dir():
        raise CheckError("root", "REPO_ROOT does not exist or is not a directory")
    policy = load_policy(root)

    adr_path = root / policy.adr_dir
    if adr_path.is_symlink() or not adr_path.is_dir():
        raise CheckError("adr-dir", f"{policy.adr_dir} is missing, a symlink or not a directory")
    real_root, real_dir = os.path.realpath(root), os.path.realpath(adr_path)
    if os.path.commonpath([real_root, real_dir]) != real_root:
        raise CheckError("adr-dir", f"{policy.adr_dir} resolves outside REPO_ROOT")

    name_re = re.compile(rf"([0-9]{{{policy.digits}}})-[a-z0-9-]+\.md", re.ASCII)
    try:
        entries = sorted(os.listdir(adr_path))
    except OSError:
        raise CheckError("adr-dir", f"{policy.adr_dir} could not be listed") from None

    found: list[tuple[str, str]] = []
    numbered: dict[int, list[str]] = {}
    adr_names: list[str] = []
    for name in entries:
        if name == policy.index_name:
            continue
        match = name_re.fullmatch(name)
        if not match:
            found.append(("adr-filename", f"{render(name)} must be named "
                          f"<{policy.digits} digits>-<slug [a-z0-9-]>.md"))
            continue
        number = int(match.group(1))
        numbered.setdefault(number, []).append(name)
        adr_names.append(name)
        text, reason = read_doc(adr_path / name, policy.max_doc_bytes)
        if text is None:
            found.append(("adr-file", f"{render(name)} {reason}"))
            continue
        found += check_adr(policy, name, number, text)

    if not adr_names:
        found.append(("adr-none", f"{policy.adr_dir} holds no ADR"))
    found += check_numbers(policy, numbered)

    index_path = adr_path / policy.index_name
    if not index_path.is_symlink() and not index_path.exists():
        found.append(("adr-index", f"{render(policy.index_name)} is missing"))
    else:
        text, reason = read_doc(index_path, policy.max_doc_bytes)
        if text is None:
            found.append(("adr-file", f"{render(policy.index_name)} {reason}"))
        else:
            found += check_index(policy, text, adr_names, name_re)

    if found:
        for ident, message in found:
            print(f"FAIL [{ident}]: {message}", file=sys.stderr)
        print(f"ADR-CHECK FAIL: {len(found)} violation(s)", file=sys.stderr)
        return EXIT_VIOLATION
    print(f"ADR-CHECK OK: {len(adr_names)} ADR(s)")
    return EXIT_OK


def main() -> int:
    # One boundary (F4): every failure ends in exit 2 with a fixed message,
    # never a traceback or an absolute path (F8).
    try:
        return run(sys.argv)
    except CheckError as err:
        print(f"ADR-CHECK ERROR [{err.ident}]: {err.message}", file=sys.stderr)
    except Exception as err:  # noqa: BLE001 - the fail-closed boundary
        print(f"ADR-CHECK ERROR [internal]: unexpected {type(err).__name__}", file=sys.stderr)
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
