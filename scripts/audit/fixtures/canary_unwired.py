"""Index rebuild command for the clause cache (wiring-audit canary fixture).

This file is the canary of the weekly wiring audit (ADR 0002 condition 6). It
is never imported, never run and never part of the inventory: the submitter
sends it as one extra request in every batch, and the collect job fails the
run unless the model reports its known defect. The defect is deliberate: a
command-line entry point that no workflow, script, test or other module
invokes. Do not wire it up, and do not add callers or tests for it.
"""
from __future__ import annotations

import argparse


def rebuild_clause_cache(argv: list[str] | None = None) -> int:
    """Parse the options and report how many cache shards would be rebuilt."""
    parser = argparse.ArgumentParser(description="Rebuild the clause cache shards.")
    parser.add_argument("--shards", type=int, default=4, help="number of shards to rebuild")
    args = parser.parse_args(argv)
    print(f"would rebuild {args.shards} clause cache shards")
    return 0


if __name__ == "__main__":
    raise SystemExit(rebuild_clause_cache())
