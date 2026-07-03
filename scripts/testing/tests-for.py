#!/usr/bin/env python3
"""tests-for.py - Map a changed file or directory to the pytest node IDs it likely affects.

Usage:
    scripts/testing/tests-for.py <path> [<path> ...]

Output:
    One pytest node ID per line (file path relative to src/backend/, or scope
    shortcut suitable for feeding directly to verify.sh via xargs).

Strategy:
    1. Static mapping table for app modules to test files (curated from a
       recursive grep of test imports). This is the primary path.
    2. Fallback: for any unrecognized file, grep imports of the module name
       across src/backend/tests/ and return matching test files.
    3. For test files or directories, echo them back so this tool composes.

Exit codes:
    0    Mapping succeeded (even if empty; empty output means no known tests).
    2    Bad input path.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Repo root is two levels above this file: scripts/testing/tests-for.py
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "src" / "backend"
TESTS_DIR = BACKEND_DIR / "tests"

# Static mapping: app module (relative to src/backend/) -> list of test files
# (relative to src/backend/). Built from actual `from app.X import Y` scans.
STATIC_MAP: dict[str, list[str]] = {
    "app/services/analyzer.py": [
        "tests/test_analyzer.py",
        "tests/test_irp.py",
        "tests/test_services.py",
        "tests/test_all.py",
        "tests/test_main_endpoints.py",
        "tests/test_regressions_pr34.py",
        "tests/test_audit_phase1_fixes.py",
        "tests/test_llm_failure.py",
        "tests/test_database_and_main_coverage.py",
    ],
    "app/services/rules.py": [
        "tests/test_rules.py",
        "tests/test_enhancements.py",
        "tests/test_all.py",
        "tests/test_irp.py",
        "tests/test_analyzer.py",
        "tests/test_audit_phase1_fixes.py",
    ],
    "app/services/validation.py": [
        "tests/test_validation.py",
    ],
    "app/services/ingest.py": [
        "tests/test_ingest.py",
        "tests/test_services.py",
        "tests/test_all.py",
    ],
    "app/services/localai.py": [
        "tests/test_llm_failure.py",
        "tests/test_services.py",
        "tests/test_all.py",
        "tests/test_legal_kb.py",
        "tests/test_analyzer.py",
    ],
    "app/services/embedding.py": [
        "tests/test_services.py",
        "tests/test_all.py",
    ],
    "app/services/legal_kb.py": [
        "tests/test_legal_kb.py",
    ],
    "app/services/diffing.py": [
        "tests/test_snapshots_and_diffs.py",
    ],
    "app/services/prompts.py": [
        "tests/test_prompts.py",
    ],
    "app/services/context.py": [
        "tests/test_context.py",
    ],
    "app/services/inference.py": [
        "tests/test_inference.py",
        "tests/test_regressions_pr34.py",
    ],
    "app/main.py": [
        "tests/test_main_endpoints.py",
        "tests/test_database_and_main_coverage.py",
        "tests/test_audit_phase1_fixes.py",
        "tests/test_regressions_pr34.py",
    ],
    "app/models.py": [
        "tests/test_main_endpoints.py",
        "tests/test_database_and_main_coverage.py",
        "tests/test_watchlist_merge.py",
        "tests/test_snapshots_and_diffs.py",
        "tests/test_all.py",
    ],
    "app/schemas.py": [
        "tests/test_all.py",
        "tests/test_audit_phase1_fixes.py",
        "tests/test_context.py",
        "tests/test_database_and_main_coverage.py",
        "tests/test_enhancements.py",
        "tests/test_inference.py",
        "tests/test_regressions_pr34.py",
        "tests/test_services.py",
        "tests/test_validation.py",
    ],
    "app/database.py": [
        "tests/test_database_and_main_coverage.py",
        "tests/test_main_endpoints.py",
    ],
    "app/config.py": [
        "tests/test_all.py",
        "tests/test_services.py",
        "tests/test_legal_kb.py",
    ],
}


IMPORT_PATTERN = re.compile(r"from\s+app(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+\s+import|import\s+app(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+")


def _rel_to_backend(p: Path) -> str | None:
    """Return path relative to src/backend/ or None if outside."""
    try:
        return str(p.resolve().relative_to(BACKEND_DIR))
    except ValueError:
        return None


def _rel_to_repo(p: Path) -> str | None:
    try:
        return str(p.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return None


def _module_name_for(rel_backend_path: str) -> str | None:
    """Convert 'app/services/rules.py' -> 'app.services.rules'."""
    if not rel_backend_path.endswith(".py"):
        return None
    stem = rel_backend_path[:-3]
    return stem.replace("/", ".")


def _grep_fallback(module_name: str) -> list[str]:
    """Grep all test files for imports referencing the given module name."""
    hits: list[str] = []
    if not TESTS_DIR.is_dir():
        return hits
    for test_file in sorted(TESTS_DIR.glob("test_*.py")):
        try:
            text = test_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Very cheap check first, then anchor.
        if module_name in text:
            for line in text.splitlines():
                if module_name in line and (line.lstrip().startswith("from ") or line.lstrip().startswith("import ")):
                    rel = _rel_to_backend(test_file)
                    if rel:
                        hits.append(rel)
                    break
    return hits


def resolve(path_arg: str) -> list[str]:
    """Resolve one input path into a list of test node IDs."""
    p = Path(path_arg)
    if not p.exists():
        # Allow module-style input, e.g. "app/services/rules.py".
        candidate = BACKEND_DIR / path_arg
        if candidate.exists():
            p = candidate
        else:
            return []

    resolved = p.resolve()

    # Case 1: already a test file or under tests/ directory.
    if TESTS_DIR in resolved.parents or resolved == TESTS_DIR:
        if resolved.is_dir():
            return [str(f.relative_to(BACKEND_DIR)) for f in sorted(resolved.glob("test_*.py"))]
        rel = _rel_to_backend(resolved)
        return [rel] if rel else []

    # Case 2: a source file under src/backend/app/.
    rel_backend = _rel_to_backend(resolved)
    if rel_backend and rel_backend.startswith("app/"):
        if resolved.is_dir():
            # For a directory like app/services/, aggregate mapped tests for
            # every .py under it.
            aggregated: list[str] = []
            for py in sorted(resolved.rglob("*.py")):
                rb = _rel_to_backend(py)
                if not rb:
                    continue
                aggregated.extend(STATIC_MAP.get(rb, []))
                if rb not in STATIC_MAP:
                    mod = _module_name_for(rb)
                    if mod:
                        aggregated.extend(_grep_fallback(mod))
            # de-dupe preserving order
            seen: set[str] = set()
            out: list[str] = []
            for x in aggregated:
                if x not in seen:
                    seen.add(x)
                    out.append(x)
            return out

        if rel_backend in STATIC_MAP:
            return list(STATIC_MAP[rel_backend])

        # Fallback: import-based grep.
        mod = _module_name_for(rel_backend)
        if mod:
            return _grep_fallback(mod)
        return []

    # Case 3: something outside src/backend. Nothing to map.
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="+",
        help="One or more file paths or directories (absolute or repo-relative).",
    )
    args = parser.parse_args(argv)

    all_hits: list[str] = []
    seen: set[str] = set()
    for path_arg in args.paths:
        for hit in resolve(path_arg):
            if hit not in seen:
                seen.add(hit)
                all_hits.append(hit)

    for h in all_hits:
        print(h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
