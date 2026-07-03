"""Structural tests for scripts/testing/pytest-summary.py.

These do not exercise the real pytest suite; they feed synthetic pytest-style
output and assert the compact summary format holds.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
SCRIPT_PATH = HERE.parent / "pytest-summary.py"


def _load_module():
    """Load pytest-summary.py by path (its name isn't a valid identifier)."""
    spec = importlib.util.spec_from_file_location("pytest_summary", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["pytest_summary"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


def test_pass_line_format(mod):
    text = """
.................
=============================== 777 passed, 3 warnings in 12.34s ===============================
""".splitlines()
    summary = mod.parse(text)
    out, code = mod.render(summary)
    assert code == 0
    assert out == "PASS: 777 tests in 12.34s"


def test_fail_line_format(mod):
    text = """
F...F
=========================== short test summary info ============================
FAILED tests/test_x.py::TestY::test_z - AssertionError: expected 1 got 2
FAILED tests/test_a.py::test_b - ValueError: bad input
=========================== 2 failed, 775 passed in 8.10s ============================
""".splitlines()
    summary = mod.parse(text)
    out, code = mod.render(summary)
    assert code == 1
    lines = out.splitlines()
    assert lines[0] == "FAIL: 2 failed / 775 passed"
    assert lines[1].startswith("tests/test_x.py::TestY::test_z :: AssertionError")
    assert lines[2].startswith("tests/test_a.py::test_b :: ValueError")


def test_collection_error(mod):
    text = """
=========================== short test summary info ============================
ERROR tests/test_broken.py - ImportError: no module named foo
=========================== 1 error in 0.10s =============================
""".splitlines()
    summary = mod.parse(text)
    out, code = mod.render(summary)
    assert code == 2
    assert out.startswith("ERROR: 1 collection error")
    assert "tests/test_broken.py :: ImportError" in out


def test_parse_error_when_no_summary_line(mod):
    text = ["random noise", "no summary here"]
    summary = mod.parse(text)
    out, code = mod.render(summary)
    assert code == 2
    assert out.startswith("ERROR:")


def test_long_reason_truncated(mod):
    long_reason = "AssertionError: " + ("x" * 400)
    text = [
        "=========================== short test summary info ============================",
        f"FAILED tests/foo.py::test_bar - {long_reason}",
        "=========================== 1 failed in 0.01s ============================",
    ]
    summary = mod.parse(text)
    assert len(summary.failures) == 1
    node, reason = summary.failures[0]
    assert node == "tests/foo.py::test_bar"
    assert reason.endswith("...")
    assert len(reason) <= 200
