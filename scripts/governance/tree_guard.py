#!/usr/bin/env python3
"""Tree guard shared by `.githooks/pre-commit` and `gitignore-enforcement.yml`.

Cards: #145 (home paths, nested graveyard, .env look-alikes) and #236 (Part B).
One scanner for both enforcers (F10): the hook runs it on the index being
committed, CI runs it on the checked-out commit's index. Both read the index
with `git ls-files -s -z` and the blobs with `git cat-file --batch`, so the
object that gets committed is the object that is scanned (F7), never the
working-tree copy.

Usage (from the repository root):
    tree_guard.py <personal-path-patterns file> <required-gitignore file>

Checks, per index entry (gitlinks skipped; a symlink's blob is its target):
  home-path  the blob, or the path name itself, matches a pattern row of the
             personal-path config after ANSI escapes and Unicode Cf characters
             are removed (case-insensitive).
  graveyard  a path segment run equals a directory entry of the
             required-gitignore SSoT (an entry ending in "/"), at any depth.
  .env       the basename is a .env look-alike (case folded, Cf and combining
             marks dropped, any non-ASCII letter counted as a homoglyph) and
             not on the exact allowlist.

Output never echoes file content (F8). Path names are printed escaped
(non-printable and non-ASCII characters as \\x/\\u/\\U escapes); a path name
that itself matches a home-path pattern is withheld.

Exit codes, each with a sentinel last line so a crash cannot pass as either:
  0  "CLEAN <entries scanned>"
  1  one "<path>: <reason>[, <reason>]" line per offender, then "REFUSED <n>"
  2  error: unusable config ("<config>: config: <why>") or internal error
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

REASON_HOME = "home-path"
REASON_GRAVEYARD = "graveyard"
REASON_ENV = ".env"
REASON_CONFIG = "config"

# Pre-existing allowlist, moved here from the hook and the workflow so both
# enforcers read one value (F10). No config file holds it yet (F13 card).
ENV_ALLOWLIST = frozenset({".env.example", ".env.sample", ".env.template"})

GITLINK_MODE = "160000"
BOM = b"\xef\xbb\xbf"

# ANSI escapes are stripped before matching, so a conceal sequence such as
# ESC[8m cannot glue a letter onto a home path and defeat a boundary. Each
# alternative begins with a distinct character and no quantifier spans an ESC,
# so the scan is linear. A lone ESC is removed as well.
_ANSI = re.compile(
    "\x1b(?:\\[[0-?]*[ -/]*[@-~]|\\][^\x07\x1b]*(?:\x07|\x1b\\\\)|[@-Z\\\\-_])?"
    "|\x9b[0-?]*[ -/]*[@-~]"
)
# A .env look-alike after folding: a dot, then e/n/v where any non-ASCII
# character also counts (Cyrillic and other homoglyphs), then an optional
# ".suffix". Over-blocks three-character non-ASCII dotfiles (fail closed).
_ENV_SKELETON = re.compile(r"\.(?:e|[^\x00-\x7f])(?:n|[^\x00-\x7f])(?:v|[^\x00-\x7f])(?:\..*)?", re.DOTALL)
_DROP_CATEGORIES = frozenset({"Cf", "Mn", "Me"})


class ConfigError(Exception):
    """A config file is unusable; the guard fails closed (exit 2)."""


def load_home_patterns(path: str) -> list[re.Pattern[str]]:
    """Load the personal-path pattern rows; fail closed on anything ambiguous.

    Same contract as the Part A loader in test_precommit_guards.py: no BOM,
    no CR, edge whitespace is an error (checked before the comment test, so an
    indented "#" is an error, not a comment), at least one row, every row
    compiles case-insensitively and none matches the empty string.
    """
    p = Path(path)
    if not p.is_file():
        raise ConfigError("missing")
    data = p.read_bytes()
    if data.startswith(BOM):
        raise ConfigError("UTF-8 BOM")
    if b"\r" in data:
        raise ConfigError("CR line ending")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError("not UTF-8") from exc
    rows: list[str] = []
    for raw in text.split("\n"):
        if not raw.strip():
            continue
        if raw != raw.strip():
            raise ConfigError("line has edge whitespace")
        if raw.startswith("#"):
            continue
        rows.append(raw)
    if not rows:
        raise ConfigError("no patterns")
    out: list[re.Pattern[str]] = []
    for row in rows:
        try:
            pat = re.compile(row, re.IGNORECASE)
        except (re.error, RecursionError) as exc:
            raise ConfigError("pattern does not compile") from exc
        if pat.search(""):
            raise ConfigError("pattern matches the empty string")
        out.append(pat)
    return out


def load_graveyard_dirs(path: str) -> list[tuple[str, ...]]:
    """Directory entries of the required-gitignore SSoT, as casefolded segments.

    Same line rules as hook check 1 (trim, skip blanks and comments). An entry
    is a graveyard directory when it ends in "/" and has no glob or negation
    character; "docs/evidence/" becomes ("docs", "evidence").
    """
    p = Path(path)
    if not p.is_file():
        raise ConfigError("missing")
    try:
        text = p.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError("not UTF-8") from exc
    dirs: list[tuple[str, ...]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not line.endswith("/") or any(c in line for c in "*?[]!\\"):
            continue
        segs = tuple(s.casefold() for s in line.strip("/").split("/") if s)
        if segs:
            dirs.append(segs)
    if not dirs:
        raise ConfigError("no directory entries")
    return dirs


def _strip_cf(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def has_home_path(text: str, patterns: list[re.Pattern[str]]) -> bool:
    """Match the Cf-stripped text both with and without ANSI escapes removed.

    Stripping alone could over-consume: ESC "[" with a "/" intermediate byte
    swallows the slash and first letter of a home root. Raw alone misses a
    conceal sequence glued to the root. A hit in either view is a leak.
    """
    raw = _strip_cf(text)
    views = (raw, _ANSI.sub("", raw)) if ("\x1b" in raw or "\x9b" in raw) else (raw,)
    return any(p.search(v) for v in views for p in patterns)


def in_graveyard(path: str, dirs: list[tuple[str, ...]]) -> bool:
    """True when a run of directory segments equals a graveyard entry.

    The last segment is the file name, so it never counts as a directory.
    Segment equality, not substring: "venv_notes/" is not "venv/".
    """
    parts = [s.casefold() for s in path.split("/")][:-1]
    for d in dirs:
        n = len(d)
        for i in range(len(parts) - n + 1):
            if tuple(parts[i:i + n]) == d:
                return True
    return False


def is_env_lookalike(basename: str) -> bool:
    if basename in ENV_ALLOWLIST:
        return False
    folded = "".join(ch for ch in basename if unicodedata.category(ch) not in _DROP_CATEGORIES)
    return _ENV_SKELETON.fullmatch(folded.casefold()) is not None


def escape_name(name: str) -> str:
    """Printable ASCII stays; everything else (and backslash) is escaped (F2)."""
    out: list[str] = []
    for ch in name:
        cp = ord(ch)
        if 0x20 <= cp < 0x7F and ch != "\\":
            out.append(ch)
        elif cp <= 0xFF:
            out.append(f"\\x{cp:02x}")
        elif cp <= 0xFFFF:
            out.append(f"\\u{cp:04x}")
        else:
            out.append(f"\\U{cp:08x}")
    return "".join(out)


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def index_entries() -> list[tuple[str, str, str]]:
    """(mode, sha, path) for every index entry, read NUL-delimited."""
    out: list[tuple[str, str, str]] = []
    for rec in _git("ls-files", "-s", "-z").split(b"\0"):
        if not rec:
            continue
        meta, raw_path = rec.split(b"\t", 1)
        mode, sha, _stage = meta.decode("ascii").split(" ")
        out.append((mode, sha, os.fsdecode(raw_path)))
    return out


class BlobReader:
    """One `git cat-file --batch` process; request/response, one blob at a time."""

    def __init__(self) -> None:
        self._proc = subprocess.Popen(
            ["git", "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )

    def read(self, sha: str) -> bytes:
        assert self._proc.stdin is not None and self._proc.stdout is not None
        self._proc.stdin.write(sha.encode("ascii") + b"\n")
        self._proc.stdin.flush()
        header = self._proc.stdout.readline().split()
        if len(header) != 3 or header[1] != b"blob":
            raise RuntimeError("unexpected cat-file header")
        size = int(header[2])
        data = self._proc.stdout.read(size)
        if len(data) != size or self._proc.stdout.read(1) != b"\n":
            raise RuntimeError("short cat-file read")
        return data

    def close(self) -> None:
        # Every exit path: close stdin so git exits, then make sure it is gone.
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
            self._proc.wait(timeout=10)
        except Exception:
            self._proc.kill()
            self._proc.wait()


def scan(patterns_file: str, required_file: str) -> tuple[int, list[str]]:
    """Return (entries scanned, offender lines). Raises ConfigError."""
    try:
        patterns = load_home_patterns(patterns_file)
    except ConfigError as exc:
        raise ConfigError(f"{patterns_file}: {REASON_CONFIG}: {exc}") from exc
    try:
        graveyard = load_graveyard_dirs(required_file)
    except ConfigError as exc:
        raise ConfigError(f"{required_file}: {REASON_CONFIG}: {exc}") from exc

    entries = index_entries()
    offenders: list[str] = []
    verdicts: dict[str, bool] = {}  # sha -> leaks; identical blobs scanned once
    withheld = 0
    reader = BlobReader()
    try:
        for mode, sha, path in entries:
            reasons: list[str] = []
            name_leaks = has_home_path(path, patterns)
            if mode != GITLINK_MODE:
                if sha not in verdicts:
                    text = reader.read(sha).decode("utf-8", "replace")
                    verdicts[sha] = has_home_path(text, patterns)
                if verdicts[sha] or name_leaks:
                    reasons.append(REASON_HOME)
            elif name_leaks:
                reasons.append(REASON_HOME)
            if in_graveyard(path, graveyard):
                reasons.append(REASON_GRAVEYARD)
            if is_env_lookalike(path.rsplit("/", 1)[-1]):
                reasons.append(REASON_ENV)
            if reasons:
                if name_leaks:
                    withheld += 1
                    shown = f"[path name withheld #{withheld}]"
                else:
                    shown = escape_name(path)
                offenders.append(f"{shown}: {', '.join(reasons)}")
    finally:
        reader.close()
    return len(entries), offenders


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"tree guard: expected 2 arguments, got {len(argv)}", file=sys.stderr)
        return 2
    try:
        count, offenders = scan(argv[0], argv[1])
    except ConfigError as exc:
        print(str(exc))
        return 2
    except Exception as exc:  # fail closed on anything unexpected (F4)
        print(f"tree guard: internal error: {type(exc).__name__}")
        return 2
    if offenders:
        for line in offenders:
            print(line)
        print(f"REFUSED {len(offenders)}")
        return 1
    print(f"CLEAN {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
