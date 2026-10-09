#!/usr/bin/env python3
"""Normalising local-path leak matcher for docs/evidence/ (issue #91).

ONE implementation shared by .githooks/pre-commit (check 4, staged blobs) and
scripts/governance/scan-evidence-leaks.sh (CI tip scan and --range scan).

Grumpy round 5 / whack-a-mole rule: encoded spellings of a path used to be
added to one ERE as extra alternatives, round after round. Instead, every line
is now DECODED before matching, and a short canonical pattern set is matched
against the decoded text:

  1. NUL bytes are stripped (UTF-16 text and binary blobs are scanned too).
  2. Up to MAX_PASSES rounds of
       * URL percent-decoding (hex is case-insensitive: %2F and %2f),
       * JSON / backslash unescaping of \\/ , \\\\ , \\uXXXX and \\xHH, and
       * stripping every Unicode format character (general category Cf,
         derived from unicodedata: zero-width space / joiners, BOM, soft
         hyphen, bidi embeddings / overrides / isolates, tag characters ...),
         raw or just decoded, so an invisible character inside a path cannot
         split it (#192 Copilot),
     stopping early once a round changes nothing. Double-encoded forms such
     as %252F or \\\\/ therefore decode too.
  3. Any remaining backslash is folded to "/" (Windows C:\\Users\\<name>).
  4. The text is case-folded, so patterns are written in lower case.

The canonical text is always UTF-8 BYTES held one per character (latin-1),
the form scan_bytes produces: percent escapes decode to bytes, and a
\\uXXXX escape (a JSON surrogate pair combined into one code point first)
decodes to the UTF-8 bytes of its code point, so every transport of the
same character reaches the Cf strip and the patterns in the same form.

A line that starts with a compressed or archived container signature
(CONTAINER_SIGNATURES) is reported as the pseudo-pattern "opaque-container"
without being decoded: its contents cannot be read, so it is refused rather
than attested clean (#91 r8, security F1).

Patterns live in .claude/governance/evidence-leak-regex.txt, one per line as
"<name><TAB><python regex>[<TAB><context>]". A context names a check in
CONTEXTS that every regex hit must also pass (see _in_absolute_path for the
only one, "absolute-path", #91 r7). Test vectors live in
.claude/governance/leak-vectors.tsv and are enforced by
src/backend/tests/test_leak_scan_vectors.py.

CLI (grep-compatible so the shell callers keep their exit-code handling):

    leak_scan.py PATTERN_FILE [INPUT]      INPUT defaults to stdin ("-")

Prints one "<line number>:<pattern name>" per matching line. A clean scan
prints exactly one "CLEAN <lines scanned>" line instead (positive
attestation, #91 security r6): the shell callers accept exit 1 as "no leak"
ONLY together with that sentinel, because Python itself also exits 1 when it
dies before main() runs (syntax error, failed import, LEAK_SCAN_PYTHON=false).
Exit: 0 = at least one leak, 1 = no leak, 2 = usage / pattern / read error or
ANY unexpected internal error (fail closed, #91 security r6: a crash must
never look like "no leak").
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path
from bisect import bisect_right
from typing import BinaryIO, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import unquote

MAX_PASSES = 3

# Only these escapes are undone. Other backslash sequences (\n, \U ...) are
# left alone so a Windows home path whose account name starts with "n" is not
# mangled before the backslash fold in step 3.
# #192 Copilot: a JSON surrogate pair (\uD8xx\uDCxx, how ensure_ascii writes
# an astral character such as a Cf tag character) is matched as ONE escape so
# it decodes to its real code point, not two lone surrogates.
_ESCAPE = re.compile(
    r"\\(?:u([dD][89abAB][0-9a-fA-F]{2})\\u([dD][c-fC-F][0-9a-fA-F]{2})"
    r"|u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2})|([/\\]))"
)

# #192 Copilot thread: Unicode format characters (category Cf) are invisible,
# so one inside a home path ("/Us<ZWSP>ers/...") hid it from every pattern.
# The set is derived from the running interpreter's Unicode database, never
# listed by hand, so a new Cf code point is covered without a code change.
# Mapped to None for str.translate (one linear pass).
_STRIPPED_CATEGORY = "Cf"
_CF_TABLE: Dict[int, None] = {
    code: None for code in range(sys.maxunicode + 1) if unicodedata.category(chr(code)) == _STRIPPED_CATEGORY
}

# (name, compiled regex, context or None). A context is built once per
# canonical line; its is_leak(offset) says whether a regex hit is a leak.
Pattern = Tuple[str, "re.Pattern[str]", Optional[Callable[[str], "_Runs"]]]

# --- "absolute-path" context (#91 r7: security F1 + grumpy finding 1) -----
#
# Rule: a home-root hit is a leak when it sits inside a LOCAL ABSOLUTE PATH,
# however deep (/System/Volumes/Data/Users/<n>, /var/home/<n>, //wsl$/x/home/
# <n>, d:/backup/users/<n>, /Volumes/Macintosh HD/Users/<n>). A path is
# absolute when its run contains an anchor at or before the hit.
#   run    = text back to the nearest hard delimiter (or line start). Spaces do
#            NOT end a run, so a volume name with a space stays one path.
#            #91 r8 (grumpy 1 / security F6): a ":", "=" or "," with a path
#            character on BOTH sides is inside a token, not a delimiter
#            (host:8501/..., /srv/a:b/..., /data/run=1/..., My,Drive/...), and
#            a bracketed IPv6 authority (//[::1]) is one token, so neither can
#            split an absolute path into an unanchored, "relative" tail.
#   anchor = the first character of a path token, not preceded by an ASCII
#            path character ([a-z0-9_.~$-]; a UTF-16 BOM or other byte is a
#            boundary): "/", "~/", one or more dots then "/" ("./", "../",
#            ".../"), or "$NAME/" / "${NAME}/". #91 r8 (grumpy 3): a bare "$",
#            "~" or "." (shell prompt, sentence end, ellipsis) is NOT an anchor.
# Single exemption: an http(s) URL on a public DNS host (dotted, alphabetic
# TLD that is not a special-use or private name in _PRIVATE_TLDS, not
# localhost, so not an IP or a local server; an optional :port), with only
# unreserved path segments before the hit (github.com/users/<login>,
# example.com/en/home/).
# A relative path such as api/users/<id> or src/home/page has no anchor, so it
# is not a home root.
_HARD_DELIMITERS = "\"'`()[]{}<>=,;|:"
_RUN = re.compile("[^" + re.escape(_HARD_DELIMITERS) + "]+")
_PATH_CHAR = "a-z0-9_.~$-"
# Same-length masks applied to a private copy of the line before the run index
# is built, so offsets into the canonical text are unchanged.
_SOFT_DELIMITER = re.compile(f"(?<=[{_PATH_CHAR}])[:=,](?=[{_PATH_CHAR}])")
_IPV6_AUTHORITY = re.compile(r"(?<=//)\[[0-9a-f:.%]*\]")
_ANCHOR = re.compile(f"(?<![{_PATH_CHAR}])(?:/|~/|\\.+/|\\$\\{{?[a-z_]+\\}}?/)")
_SCHEME = re.compile(r"(?<![\w+.-])https?:\Z")
_PUBLIC_URL = re.compile(
    r"//(?!(?:[a-z0-9-]+\.)*localhost(?![a-z0-9-]))(?:[a-z0-9-]+\.)+([a-z]{2,})(?:_[0-9]{1,5})?(?=/|\Z)"
    r"((?:/[a-z0-9._~-]*)*)"
)
# #91 r8 (grumpy 4 / security F7): special-use and private-network names
# (RFC 6761 / 6762 / 8375 / 2606 and common LAN suffixes). A host under one of
# these is a local machine, never a public site, so it gets no exemption.
_PRIVATE_TLDS = frozenset(
    {"local", "lan", "internal", "localdomain", "arpa", "corp", "home", "intranet", "test", "invalid", "example"}
)


def _mask(text: str) -> str:
    """Hide in-token delimiters from the run splitter (same length as text)."""
    text = _IPV6_AUTHORITY.sub(lambda m: "_" * len(m.group(0)), text)
    return _SOFT_DELIMITER.sub("_", text)


class _Runs:
    """Per-line run index, built once so a line with many hits stays linear."""

    def __init__(self, text: str) -> None:
        self.starts: List[int] = []
        self.ends: List[int] = []
        self.anchor: List[int] = []  # first anchor offset per run, or -1
        self.url_path: List[Tuple[int, int]] = []  # exempt [start, end] or (-1, -1)
        text = _mask(text)
        for run in _RUN.finditer(text):
            start, end = run.span()
            self.starts.append(start)
            self.ends.append(end)
            first = _ANCHOR.search(text, start, end)
            self.anchor.append(first.start() if first else -1)
            exempt = (-1, -1)
            if _SCHEME.search(text[max(0, start - 7):start]):
                url = _PUBLIC_URL.match(text, start, end)
                if url and url.group(1) not in _PRIVATE_TLDS:
                    exempt = url.span(2)
            self.url_path.append(exempt)

    def is_leak(self, pos: int) -> bool:
        """True when offset pos lies inside a local absolute path."""
        index = bisect_right(self.starts, pos) - 1
        if index < 0 or pos >= self.ends[index]:
            return True  # not inside any run: cannot happen for a "/" hit; fail closed
        anchor = self.anchor[index]
        if anchor < 0 or anchor > pos:
            return False  # relative path: no anchor at or before the hit
        low, high = self.url_path[index]
        return not (low <= pos <= high)


CONTEXTS: Dict[str, Callable[[str], "_Runs"]] = {"absolute-path": _Runs}


def _utf8_bytes(text: str) -> str:
    """The UTF-8 bytes of text, one latin-1 character per byte.

    surrogatepass keeps a lone surrogate escape lossless (it is not Cf).
    """
    return text.encode("utf-8", "surrogatepass").decode("latin-1")


def _unescape(text: str) -> str:
    def repl(match: "re.Match[str]") -> str:
        high, low, hex4, hex2, literal = match.groups()
        if high is not None:
            code = 0x10000 + ((int(high, 16) - 0xD800) << 10) + (int(low, 16) - 0xDC00)
            return _utf8_bytes(chr(code))
        if hex4 is not None:
            return _utf8_bytes(chr(int(hex4, 16)))
        if hex2 is not None:
            return chr(int(hex2, 16))  # \xHH names one byte
        return literal

    return _ESCAPE.sub(repl, text)


def _strip_cf(text: str) -> str:
    """Drop every Cf code point from byte-form text (see module docstring).

    The bytes are decoded as UTF-8 with surrogateescape, so invalid sequences
    (binary, UTF-16, a lone 0xAD byte) round-trip unchanged and only a real
    encoded Cf character is removed. Linear: one decode, translate, encode.
    A character above U+00FF is not byte form: encode raises (fail closed).
    """
    decoded = text.encode("latin-1").decode("utf-8", "surrogateescape")
    stripped = decoded.translate(_CF_TABLE)
    if len(stripped) == len(decoded):
        return text
    return stripped.encode("utf-8", "surrogateescape").decode("latin-1")


def normalise(text: str) -> str:
    """Decode one line into the canonical form the patterns are written for."""
    text = text.replace("\x00", "")
    for _ in range(MAX_PASSES):
        # latin-1 keeps every byte value lossless; the patterns are ASCII.
        decoded = _strip_cf(_unescape(unquote(text, encoding="latin-1")))
        if decoded == text:
            break
        text = decoded
    return text.replace("\\", "/").lower()


# --- vector placeholder tokens (#192, #145 Part A) --------------------------
#
# .claude/governance/leak-vectors.tsv is tracked, and the tracked tree must not
# contain a literal home path (test_tracked_tree_has_no_home_paths). Its
# samples therefore spell each home root (or the bare root word, WORD_*) as a
# "<<NAME>>" token, and this table is the ONLY place the tokens are expanded
# (expand_vector_tokens). Each value is the exact text it stands for, byte for
# byte; no value ends in a path separator, so this source file is not a
# home-path leak either.
VECTOR_TOKENS: Dict[str, str] = {
    "USERS": "/Users",
    "USERSUPPER": "/USERS",  # case-variant vector
    "HOME": "/home",
    "WINUSERS": "C:\\Users",
    "WINUSERSESC": "C:\\\\Users",  # JSON-escaped Windows root
    "TILDE": "~",
    "ENVHOME": "$HOME",
    "ENVHOMEBR": "${HOME}",
    # Word-level tokens: the bare root word, for samples where the separator
    # in front of it is itself the vector (URL-encoded, JSON-escaped, dashed
    # slugs, UNC and URL paths). Values hold no separator at all.
    "WORD_USERS": "Users",
    "WORD_USERS_LOWER": "users",
    "WORD_USERS_UPPER": "USERS",
    "WORD_HOME": "home",
}
_VECTOR_TOKEN = re.compile(r"<<([^<>]*)>>")


def expand_vector_tokens(text: str) -> str:
    """Expand every "<<NAME>>" token in a leak-vectors.tsv field.

    Fails closed (ValueError) on an unknown token name and on any "<<" or ">>"
    left outside a well-formed token (unterminated or nested), so a typo can
    never turn a block vector into an inert string. The error names the token
    only in ASCII-escaped, truncated form.
    """
    outside = _VECTOR_TOKEN.sub("", text)
    if "<<" in outside or ">>" in outside:
        raise ValueError("malformed vector token: '<<' or '>>' outside a <<NAME>> token")

    def repl(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name not in VECTOR_TOKENS:
            raise ValueError(f"unknown vector token <<{ascii(name)[1:-1][:40]}>>")
        return VECTOR_TOKENS[name]

    return _VECTOR_TOKEN.sub(repl, text)


def load_patterns(path: Path) -> List[Pattern]:
    """Parse the pattern SSoT. Raises ValueError on any malformed line."""
    patterns: List[Pattern] = []
    seen = set()
    # #192 fix r2: split on "\n" only (splitlines() also splits on U+2028, VT,
    # FF, NEL...). A trailing "\r" is stripped so CRLF files still load.
    for number, raw in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if raw.endswith("\r"):
            raw = raw[:-1]
        # Structural allowlist: only TAB and printable ASCII (0x20-0x7E) on every
        # line, comments included. Anything else (format, control, bidi,
        # non-ASCII) can glue to a column or hide a pattern. Fail closed; name
        # the code point, never echo the raw character.
        for char in raw:
            if char != "\t" and not (0x20 <= ord(char) <= 0x7E):
                raise ValueError(
                    f"{path}:{number}: character U+{ord(char):04X} is not allowed in the pattern file"
                )
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        name, sep, rest = raw.partition("\t")
        regex, _, context_name = rest.partition("\t")
        name = name.strip()
        if not sep or not name or not regex:
            raise ValueError(f"{path}:{number}: expected '<name><TAB><regex>[<TAB><context>]'")
        context: Optional[Callable[[str], "_Runs"]] = None
        if context_name:
            if context_name not in CONTEXTS:
                raise ValueError(f"{path}:{number}: unknown context {context_name!r} for {name!r}")
            context = CONTEXTS[context_name]
        if name in seen:
            raise ValueError(f"{path}:{number}: duplicate pattern name {name!r}")
        if regex != regex.lower():
            raise ValueError(f"{path}:{number}: pattern {name!r} must be lower case (input is case-folded)")
        try:
            compiled = re.compile(regex)
        except (re.error, RecursionError, OverflowError, MemoryError) as exc:
            # #91 security r6: a deeply nested or oversized pattern raises
            # RecursionError / MemoryError, not re.error. Every compile
            # failure is the "bad pattern file" path (exit 2).
            raise ValueError(f"{path}:{number}: bad regex for {name!r}: {exc!r}") from exc
        seen.add(name)
        patterns.append((name, compiled, context))
    if not patterns:
        raise ValueError(f"{path}: no patterns")
    return patterns


def match_line(line: str, patterns: Sequence[Pattern]) -> List[str]:
    """Names of every pattern that matches the normalised line.

    ``line`` is raw bytes decoded as latin-1 (what scan_bytes passes), so a
    UTF-8 name is matched byte-wise by the \x80-\xff classes in the SSoT.
    """
    canonical = normalise(line)
    names: List[str] = []
    for name, regex, context in patterns:
        if context is None:
            if regex.search(canonical):
                names.append(name)
        else:
            line_context = None
            for hit in regex.finditer(canonical):
                line_context = line_context or context(canonical)
                if line_context.is_leak(hit.start()):
                    names.append(name)
                    break
    return names


# --- opaque containers (#91 r8, security F1) --------------------------------
#
# The matcher reads the text layer only. A compressed or archived payload
# (.docx / .xlsx / .zip, .gz, .bz2, .xz, .zst, .7z, PDF) hides every path
# inside it, so scanning it would attest CLEAN for bytes nobody could read.
# Fail closed: a line that STARTS with one of these signatures is reported as
# the pseudo-pattern OPAQUE_CONTAINER, so the hook refuses it and CI goes red.
# "Starts a line" covers both a whole file (line 1) and the --range stream,
# where git log -p --text emits an added binary blob as "+<bytes>" lines.
# Signatures are written without NUL bytes because NULs are stripped first.
# Evidence must be committed as plain text; extract it before committing.
OPAQUE_CONTAINER = "opaque-container"
CONTAINER_SIGNATURES: Dict[str, bytes] = {
    "zip": b"PK\x03\x04",  # .zip, .docx, .xlsx, .pptx, .jar (local file header)
    "zip-empty": b"PK\x05\x06",  # end-of-central-directory first (empty archive)
    "zip-spanned": b"PK\x07\x08",  # spanned / split archive marker
    "gzip": b"\x1f\x8b\x08",
    "bzip2": b"BZh",  # followed by a level digit and the block magic, see below
    "xz": b"\xfd7zXZ",  # "\xfd7zXZ\x00" with the NUL stripped
    "zstd": b"\x28\xb5\x2f\xfd",
    "7z": b"7z\xbc\xaf\x27\x1c",
    "pdf": b"%PDF-",
}
_CONTAINER_LINE = re.compile(
    b"\\A(?:"
    + b"|".join(
        # bzip2 is pinned to "BZh<1-9>1AY&SY" so prose starting "BZh" is text.
        re.escape(sig) + (rb"[1-9]1AY&SY" if name == "bzip2" else rb"[0-9]\.[0-9]" if name == "pdf" else b"")
        for name, sig in CONTAINER_SIGNATURES.items()
    )
    + b")"
)


def scan_bytes(data: bytes, patterns: Sequence[Pattern]) -> List[Tuple[int, str]]:
    """(1-based line number, first matching pattern name) for each leaking line.

    A line that starts with a container signature is reported as
    OPAQUE_CONTAINER (fail closed, see CONTAINER_SIGNATURES).
    """
    hits: List[Tuple[int, str]] = []
    for number, raw in enumerate(data.replace(b"\x00", b"").split(b"\n"), 1):
        if _CONTAINER_LINE.match(raw):
            hits.append((number, OPAQUE_CONTAINER))
            continue
        names = match_line(raw.decode("latin-1"), patterns)
        if names:
            hits.append((number, names[0]))
    return hits


def _read(source: str, stdin: BinaryIO) -> bytes:
    if source == "-":
        return stdin.read()
    return Path(source).read_bytes()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Never lets an exception escape (fail closed)."""
    try:
        return _main(argv)
    except Exception as exc:  # noqa: BLE001 - deliberate catch-all
        # #91 security r6: Python exits 1 on an uncaught exception, and 1
        # means "no leak" to every caller. Any unexpected error (including
        # RecursionError and MemoryError, both Exception subclasses) is exit 2.
        print(f"leak_scan: internal error: {exc!r}", file=sys.stderr)
        return 2


def _main(argv: Optional[Sequence[str]]) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) not in (1, 2):
        print("usage: leak_scan.py PATTERN_FILE [INPUT|-]", file=sys.stderr)
        return 2
    try:
        patterns = load_patterns(Path(args[0]))
    except (OSError, ValueError) as exc:
        print(f"leak_scan: {exc}", file=sys.stderr)
        return 2
    try:
        data = _read(args[1] if len(args) == 2 else "-", sys.stdin.buffer)
    except OSError as exc:
        print(f"leak_scan: cannot read input: {exc}", file=sys.stderr)
        return 2
    hits = scan_bytes(data, patterns)
    for number, name in hits:
        print(f"{number}:{name}")
    if hits:
        return 0
    # Positive attestation: callers require this sentinel with exit 1. The
    # count matches scan_bytes' line numbering.
    scanned = len(data.replace(b"\x00", b"").split(b"\n"))
    print(f"CLEAN {scanned}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
