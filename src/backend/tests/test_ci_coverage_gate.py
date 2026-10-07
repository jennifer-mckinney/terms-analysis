"""G0-6 acceptance tests: the CI coverage gate must be exact (issue #177).

pytest-cov rounds the measured total to ``cov_precision`` (default 0) before
comparing it with ``--cov-fail-under``. With the floor at 98, any total in
[97.50, 98.00) is rounded up to 98 and the job exits 0 while the summary line
prints "FAIL Required test coverage of 98% not reached". These tests pin the
gate so that the printed verdict and the exit code cannot disagree.

(a) Contract: the CI pytest command keeps the owner floor (98) and sets a
    precision of at least 2, either on the command line or in a coverage
    config file under ``src/backend``.
(b) Behaviour: the exact coverage flags from ``ci.yml`` (plus any backend
    pytest/coverage config) run against a throwaway package measured at
    97.5x% must exit non-zero.
"""
from __future__ import annotations

import configparser
import io
import os
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import coverage
import yaml

# Repo layout: src/backend/tests/<this file>
BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# Owner-ruled floor (issue #177): unchanged at 98.
OWNER_FLOOR = "98"
MIN_PRECISION = 2

# Config files under src/backend that pytest or coverage.py may read.
_CONFIG_FILES = (".coveragerc", "setup.cfg", "tox.ini", "pyproject.toml", "pytest.ini")


def _ci_coverage_tokens() -> list[str]:
    """Return the shell tokens of the CI step that runs pytest with coverage.

    Fails loudly if no such step exists, so a renamed or deleted step cannot
    make the contract test pass vacuously.
    """
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    matches: list[str] = []
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            run = step.get("run") or ""
            if "pytest" in run and "--cov" in run:
                matches.append(run)
    assert len(matches) == 1, (
        f"expected exactly one pytest+coverage step in {CI_WORKFLOW.name}, found {len(matches)}"
    )
    # Join shell line continuations before tokenising.
    return shlex.split(matches[0].replace("\\\n", " "))


def _cov_flags(tokens: list[str]) -> list[str]:
    """Extract the pytest-cov flags (``--cov*``) from the CI command tokens."""
    flags: list[str] = []
    it = iter(tokens)
    for tok in it:
        if tok.startswith("--cov"):
            if "=" not in tok and tok != "--cov":
                # Space-separated value form, e.g. ``--cov-precision 2``.
                flags.extend([tok, next(it)])
            else:
                flags.append(tok)
    return flags


def _flag_value(flags: list[str], name: str) -> str | None:
    """Return the last value given for ``name`` in either ``a=b`` or ``a b`` form."""
    value: str | None = None
    for i, tok in enumerate(flags):
        if tok.startswith(name + "="):
            value = tok.split("=", 1)[1]
        elif tok == name and i + 1 < len(flags):
            value = flags[i + 1]
    return value


def _config_precision() -> int | None:
    """Return the coverage ``[report] precision`` configured under src/backend, if any."""
    rc = BACKEND_DIR / ".coveragerc"
    for path, section in (
        (rc, "report"),
        (BACKEND_DIR / "setup.cfg", "coverage:report"),
        (BACKEND_DIR / "tox.ini", "coverage:report"),
    ):
        if path.is_file():
            parser = configparser.ConfigParser()
            parser.read(path, encoding="utf-8")
            if parser.has_option(section, "precision"):
                return parser.getint(section, "precision")
    pyproject = BACKEND_DIR / "pyproject.toml"
    if pyproject.is_file():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        report = data.get("tool", {}).get("coverage", {}).get("report", {})
        if "precision" in report:
            return int(report["precision"])
    return None


def test_ci_coverage_command_is_exact() -> None:
    """(a) CI keeps fail-under=98 and compares at precision >= 2."""
    flags = _cov_flags(_ci_coverage_tokens())

    assert _flag_value(flags, "--cov-fail-under") == OWNER_FLOOR, (
        f"CI must keep the owner floor --cov-fail-under={OWNER_FLOOR}; flags={flags}"
    )

    cli_precision = _flag_value(flags, "--cov-precision")
    precision = int(cli_precision) if cli_precision is not None else _config_precision()
    assert precision is not None and precision >= MIN_PRECISION, (
        "CI coverage gate rounds the total before comparing: set --cov-precision="
        f"{MIN_PRECISION} (or coverage [report] precision >= {MIN_PRECISION}); "
        f"got precision={precision}, flags={flags}"
    )


def _write_throwaway_package(root: Path) -> None:
    """Create ``app`` with 84 statements of which exactly 2 are missed (97.62%).

    The package is named ``app`` so the CI flag ``--cov=app`` applies verbatim.
    """
    pkg = root / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    # 1 def + 79 assignments + 1 return = 81 executed statements for covered().
    body = "\n".join(f"    v{i} = {i}" for i in range(79))
    (pkg / "mod.py").write_text(
        "def covered():\n"
        f"{body}\n"
        "    return v0\n"
        "\n"
        "\n"
        "def uncovered():\n"  # def line executes at import: 82 executed.
        "    a = 1\n"  # missed
        "    return a\n",  # missed -> 84 statements, 2 missed
        encoding="utf-8",
    )
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_mod.py").write_text(
        "from app.mod import covered\n\n\ndef test_covered():\n    assert covered() == 0\n",
        encoding="utf-8",
    )


def test_gate_fails_below_floor_with_repo_flags(tmp_path: Path) -> None:
    """(b) The repo's exact coverage flags exit non-zero at a 97.5x% total."""
    flags = _cov_flags(_ci_coverage_tokens())
    assert "--cov=app" in flags, f"expected --cov=app in CI flags; flags={flags}"

    # Mirror backend pytest/coverage configuration so config-based precision counts.
    copied = False
    for name in _CONFIG_FILES:
        src = BACKEND_DIR / name
        if src.is_file():
            shutil.copy(src, tmp_path / name)
            copied = copied or name == "pytest.ini"
    if not copied:
        (tmp_path / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")

    _write_throwaway_package(tmp_path)

    # Strip coverage/pytest-cov env from any enclosing coverage run, and any
    # PYTHONPATH that could import the real ``app`` instead of the throwaway one.
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("COV_CORE_", "COVERAGE_")) and k != "PYTHONPATH"
    }
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *flags, "tests"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = result.stdout + result.stderr

    # Precondition: the fixture really measured in [97.50, 98.00); otherwise the
    # assertion below would not be testing the rounding window.
    cov = coverage.Coverage(data_file=str(tmp_path / ".coverage"))
    cov.load()
    total = cov.report(file=io.StringIO(), include=[str(tmp_path / "app" / "*")])
    assert 97.5 <= total < 98.0, f"fixture total {total:.2f} outside [97.50, 98.00)\n{output}"

    assert "1 passed" in output, f"throwaway suite did not run as expected\n{output}"
    assert result.returncode != 0, (
        f"coverage gate exited 0 at {total:.2f}% with fail-under={OWNER_FLOOR}: "
        "rounding lets a below-floor total pass\n"
        f"flags={flags}\n{output[-1500:]}"
    )
    # The non-zero exit must be the coverage gate itself, not an unrelated
    # failure; the floor comes from the explicit CI --cov-fail-under flag, not
    # from .coveragerc. pytest-cov prints "FAIL Required test coverage of 98%
    # not reached. Total coverage: 97.xx%" with precision 2.
    assert f"Required test coverage of {OWNER_FLOOR}% not reached" in output, (
        f"non-zero exit was not the coverage gate\n{output[-1500:]}"
    )
