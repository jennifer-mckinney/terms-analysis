#!/usr/bin/env python3
"""Compact pytest output summarizer.

Reads pytest stdout (via stdin or --input) and emits one of:

    PASS: N tests in Xs
    FAIL: F failed / P passed
    <node_id> :: <one-line summary>
    ...

Also handles:
    ERROR: <short reason>   (collection error / exit 2)

Exit codes mirror the parsed result:
    0 = all pass
    1 = one or more test failures
    2 = collection error or unparseable output
    3 = reserved (unknown scope, used by verify.sh, not here)

Design notes:
    Compact output is what makes a Critic agent's verification cheap. The
    verbose form of pytest is deliberately kept out of the summary. Full logs
    live in the caller's stderr redirect if needed.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# Match the pytest short-test-summary block header, e.g.:
#   =========================== short test summary info ============================
SHORT_SUMMARY_HEADER = re.compile(r"^=+\s*short test summary info\s*=+\s*$")

# Match a FAILED / ERROR line in the short summary block, e.g.:
#   FAILED tests/test_x.py::TestY::test_z - AssertionError: expected 1 got 2
FAILURE_LINE = re.compile(
    r"^(FAILED|ERROR)\s+(?P<node>[^\s]+)(?:\s+-\s+(?P<reason>.*))?$"
)

# Match the final summary line, e.g.:
#   ======= 777 passed, 3 warnings in 12.34s =======
#   ======= 2 failed, 775 passed in 12.34s =======
#   ======= 1 error in 0.10s =======
FINAL_LINE = re.compile(
    r"^=*\s*"
    r"(?P<body>.*?)"
    r"\s+in\s+(?P<seconds>[0-9.]+)s"
    r"\s*=*\s*$"
)

# Individual token match inside the final line body, e.g. "777 passed", "2 failed"
COUNT_TOKEN = re.compile(r"(?P<n>\d+)\s+(?P<kind>passed|failed|error|errors|skipped|xfailed|xpassed|warnings|deselected)")


@dataclass
class Summary:
    """Parsed pytest result."""

    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    seconds: float | None = None
    failures: list[tuple[str, str]] = field(default_factory=list)
    parse_error: str | None = None

    @property
    def total(self) -> int:
        # Total = executed non-skipped; skipped are reported separately.
        return self.passed + self.failed + self.errors


def parse(lines: Iterable[str]) -> Summary:
    """Parse pytest -q output into a Summary."""

    summary = Summary()
    in_short_summary = False

    all_lines = list(lines)
    for raw in all_lines:
        line = raw.rstrip("\n")

        # Track short summary block boundary; failure lines only inside it.
        if SHORT_SUMMARY_HEADER.match(line):
            in_short_summary = True
            continue

        if in_short_summary:
            m = FAILURE_LINE.match(line)
            if m:
                node = m.group("node")
                reason = (m.group("reason") or "").strip()
                # Collapse newlines and cap length to keep summary compact.
                reason = reason.replace("\r", " ").replace("\t", " ")
                if len(reason) > 200:
                    reason = reason[:197] + "..."
                summary.failures.append((node, reason or "(no reason parsed)"))

    # Locate final summary line by scanning bottom-up.
    for raw in reversed(all_lines):
        line = raw.rstrip("\n").strip()
        m = FINAL_LINE.search(line)
        if not m:
            continue
        summary.seconds = float(m.group("seconds"))
        body = m.group("body")
        for tok in COUNT_TOKEN.finditer(body):
            n = int(tok.group("n"))
            kind = tok.group("kind")
            if kind == "passed":
                summary.passed = n
            elif kind == "failed":
                summary.failed = n
            elif kind in ("error", "errors"):
                summary.errors = n
            elif kind == "skipped":
                summary.skipped = n
        break

    if summary.seconds is None and not summary.failures:
        summary.parse_error = "no pytest summary line found"

    return summary


def render(summary: Summary) -> tuple[str, int]:
    """Return (compact_text, exit_code)."""

    if summary.parse_error:
        return f"ERROR: {summary.parse_error}", 2

    if summary.errors > 0 and summary.passed == 0 and summary.failed == 0:
        # Pure collection error path.
        header = f"ERROR: {summary.errors} collection error(s)"
        body_lines = [f"{n} :: {r}" for n, r in summary.failures]
        return "\n".join([header, *body_lines]).rstrip(), 2

    if summary.failed == 0 and summary.errors == 0:
        secs = f"{summary.seconds:.2f}s" if summary.seconds is not None else "?s"
        return f"PASS: {summary.passed} tests in {secs}", 0

    header = f"FAIL: {summary.failed} failed / {summary.passed} passed"
    if summary.errors:
        header += f" / {summary.errors} error(s)"
    body_lines = [f"{n} :: {r}" for n, r in summary.failures]
    return "\n".join([header, *body_lines]).rstrip(), 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Read pytest output from this file. Default: stdin.",
    )
    args = parser.parse_args(argv)

    if args.input:
        text = args.input.read_text(encoding="utf-8", errors="replace").splitlines()
    else:
        text = sys.stdin.read().splitlines()

    summary = parse(text)
    out, code = render(summary)
    print(out)
    return code


if __name__ == "__main__":
    sys.exit(main())
