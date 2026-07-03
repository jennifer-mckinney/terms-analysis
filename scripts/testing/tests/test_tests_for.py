"""Structural tests for scripts/testing/tests-for.py.

Verifies static mapping resolves for known app modules and that unknown paths
under src/backend/app fall through to the import-grep fallback.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
SCRIPT_PATH = HERE.parent / "tests-for.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("tests_for", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["tests_for"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


def test_static_map_hits_analyzer(mod):
    hits = mod.resolve("src/backend/app/services/analyzer.py")
    assert "tests/test_analyzer.py" in hits
    assert "tests/test_irp.py" in hits


def test_static_map_hits_rules(mod):
    hits = mod.resolve("src/backend/app/services/rules.py")
    assert "tests/test_rules.py" in hits
    assert "tests/test_enhancements.py" in hits


def test_static_map_hits_watchlist_related(mod):
    hits = mod.resolve("src/backend/app/models.py")
    assert "tests/test_watchlist_merge.py" in hits


def test_test_file_input_echoes_back(mod):
    hits = mod.resolve("src/backend/tests/test_analyzer.py")
    assert hits == ["tests/test_analyzer.py"]


def test_unknown_path_returns_empty(mod):
    hits = mod.resolve("README.md")
    assert hits == []


def test_directory_input_aggregates(mod):
    hits = mod.resolve("src/backend/app/services")
    # Should include a broad set of test files, at least analyzer + rules + inference.
    assert "tests/test_analyzer.py" in hits
    assert "tests/test_rules.py" in hits
    assert "tests/test_inference.py" in hits
