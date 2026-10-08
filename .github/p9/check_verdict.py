#!/usr/bin/env python3
"""P9 review gate (terms-analysis#191).

Run as the last step of each job in .github/workflows/p9-review.yml, after
the reviewer has written p9-verdict.json. The job passes only when the file
is exactly the verdict contract with verdict PASS and an empty findings list.

Contract (written by the reviewer, see .github/p9/*.md):
    {"verdict": "PASS" | "FAIL",
     "findings": [{"severity": ..., "title": ..., "file": ..., "line": ...}]}

Exit codes:
    0  PASS with zero findings (prints "P9 verdict: PASS, 0 findings")
    1  the reviewer reported FAIL, or listed findings
    2  the file is missing, unreadable, not JSON, or off the contract

Standard library only, so the step needs nothing installed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

EXIT_PASS = 0
EXIT_REJECTED = 1
EXIT_INVALID = 2

VERDICTS = frozenset({"PASS", "FAIL"})
FINDING_FIELDS = ("severity", "title", "file", "line")
# Finding text comes from a model that read untrusted PR content; it is shown
# in the Actions log one finding per line, so each field is cut to this size.
MAX_FIELD_CHARS = 200


class InvalidVerdict(Exception):
    """The verdict file cannot be trusted as a reviewer decision."""


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise InvalidVerdict(f"duplicate key(s): {', '.join(_clean(k) for k in duplicates)}")
    return dict(pairs)


def _clean(value: object) -> str:
    """One printable line: control, format and separator characters become '?'."""
    text = "".join(ch if ch.isprintable() else "?" for ch in str(value))
    return text[:MAX_FIELD_CHARS]


def load(path: Path) -> dict[str, object]:
    """Read and validate the verdict file, or raise InvalidVerdict."""
    if not path.is_file():
        raise InvalidVerdict(f"{path.name} was not written by the reviewer")
    try:
        doc = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except InvalidVerdict:
        raise
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise InvalidVerdict(f"{path.name} is not valid JSON ({type(exc).__name__})") from None
    verdict = doc.get("verdict") if isinstance(doc, dict) else None
    findings = doc.get("findings") if isinstance(doc, dict) else None
    if (
        not isinstance(verdict, str)
        or verdict not in VERDICTS
        or not isinstance(findings, list)
        or not all(isinstance(item, dict) for item in findings)
    ):
        raise InvalidVerdict(
            f"{path.name} does not match the verdict contract "
            '{"verdict": "PASS"|"FAIL", "findings": [{...}]}'
        )
    return doc


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_verdict.py <p9-verdict.json>", file=sys.stderr)
        return EXIT_INVALID
    try:
        doc = load(Path(argv[1]))
    except InvalidVerdict as exc:
        print(f"P9 verdict: invalid: {exc}", file=sys.stderr)
        return EXIT_INVALID
    verdict = doc["verdict"]
    findings = doc["findings"]
    if verdict == "PASS" and not findings:
        print("P9 verdict: PASS, 0 findings")
        return EXIT_PASS
    print(f"P9 verdict: {verdict}, {len(findings)} finding(s)", file=sys.stderr)
    for item in findings:
        severity, title, file, line = (_clean(item.get(key, "?")) for key in FINDING_FIELDS)
        print(f"  - [{severity}] {title} ({file}:{line})", file=sys.stderr)
    return EXIT_REJECTED


if __name__ == "__main__":
    sys.exit(main(sys.argv))
