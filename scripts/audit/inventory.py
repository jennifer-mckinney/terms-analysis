#!/usr/bin/env python3
"""Inventory builder for the weekly wiring audit (card #224, ADR 0002 condition 1).

A pure function of the checkout:

* candidates come from ``git ls-files`` only (never a directory walk), so an
  untracked file can never reach a prompt; symlinks and submodules are
  skipped, and a path whose parent is a symlink is refused when read;
* a candidate is kept when it matches a configured module glob, matches no
  exclude glob (the ADR denylist), is not the canary fixture, has only
  printable characters in its path, and its path matches no personal-path
  pattern; test files stay eligible;
* every line of a kept module that matches a personal-path pattern is
  replaced by a placeholder before anything else reads it;
* entry points come from ``ast``; callers, tests and workflows are the other
  kept modules that import the module or name its file (a token scan over
  kept modules only, so excluded files never contribute).

CLI: ``inventory.py --repo DIR --config FILE`` prints the inventory as sorted,
byte-stable JSON (paths and facts, no file content). Exit codes come from the
one table in config.py: OK, CONFIG, NO_MODULES ("did nothing" is never 0).
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import unicodedata
from pathlib import Path
from types import ModuleType
from typing import Any


def _sibling(name: str) -> ModuleType:
    """Load scripts/audit/<name>.py by path (python3 -I drops the script dir from sys.path)."""
    key = f"wiring_audit_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, Path(__file__).with_name(f"{name}.py"))
    if spec is None or spec.loader is None:
        raise ImportError(name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


config = _sibling("config")
ConfigError = config.ConfigError

EXIT_CODES = {name: config.EXIT_CODES[name] for name in ("OK", "CONFIG", "NO_MODULES")}

_REGULAR_MODES = frozenset({"100644", "100755"})
_PRINTABLE_PATH_CATEGORIES = frozenset("LMNPS")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_IMPORT_LINE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import\s+(.+)|import\s+(.+))$")
_SLUG_UNSAFE = re.compile(r"[^A-Za-z0-9]+")
_ROUTE_DECORATORS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "route",
                               "websocket", "command", "callback", "group"})
_PERSONAL_PLACEHOLDER = "[line removed by the wiring audit: personal path]"


class InventoryError(Exception):
    """The checkout could not be enumerated (git failed, timed out or overflowed)."""


class Module:
    """One audited file: identity, sanitised text and the facts the prompt carries.

    A plain class, not a dataclass: the tests load this file by path without
    registering it in sys.modules, which dataclasses require.
    """

    def __init__(self, *, path: str, custom_id: str, text: str, truncated_text: str, truncated: bool,
                 sha256: str, entry_points: list[str], syntax_error: bool) -> None:
        self.path = path
        self.custom_id = custom_id
        self.text = text  # sanitised, personal-path lines removed, NOT truncated
        self.truncated_text = truncated_text
        self.truncated = truncated
        self.sha256 = sha256
        self.entry_points = entry_points
        self.syntax_error = syntax_error
        self.callers: list[str] = []
        self.tests: list[str] = []
        self.workflows: list[str] = []

    def facts(self) -> dict[str, Any]:
        """What the prompt and the CLI report about a module (no file content)."""
        return {
            "path": self.path,
            "custom_id": self.custom_id,
            "sha256": self.sha256,
            "chars": len(self.text),
            "truncated": self.truncated,
            "entry_points": self.entry_points,
            "syntax_error": self.syntax_error,
            "callers": self.callers,
            "tests": self.tests,
            "workflows": self.workflows,
        }


# --- globs ---------------------------------------------------------------------------


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a path glob: ``**/`` spans directories, ``*`` and ``?`` stay inside one."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:[^/]*/)*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out), re.DOTALL)


def _compile_globs(patterns: list[str]) -> list[re.Pattern[str]]:
    return [glob_to_regex(p) for p in patterns]


def _any_match(rxs: list[re.Pattern[str]], path: str) -> bool:
    return any(rx.fullmatch(path) for rx in rxs)


# --- bounded subprocess (F6) -----------------------------------------------------------


def run_bounded(argv: list[str], *, cwd: Path | None, env: dict[str, str], stdin: bytes | None,
                timeout: float, cap: int) -> tuple[int, bytes, bytes]:
    """Run argv without a shell; kill it on timeout; refuse output over the cap."""
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(input=stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise InventoryError(f"{Path(argv[1] if argv[0] == sys.executable else argv[0]).name} "
                             f"timed out after {timeout}s") from None
    except BaseException:
        proc.kill()
        proc.communicate()
        raise
    if len(out) > cap or len(err) > cap:
        raise InventoryError("subprocess output exceeded max_subprocess_output_bytes")
    return proc.returncode, out, err


def git_env() -> dict[str, str]:
    """The caller's environment minus every GIT_* override (F7: no redirection)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0",
                "LC_ALL": "C"})
    return env


def tracked_files(repo: Path, cfg: dict[str, Any]) -> list[str]:
    """Regular tracked files (stage 0) from ``git ls-files``; never a directory walk."""
    if not (repo / ".git").exists():
        raise InventoryError("--repo is not the top of a git checkout")
    argv = ["git", "-C", str(repo), "-c", "core.quotepath=off", "-c", "core.fsmonitor=false",
            "ls-files", "-z", "-s", "--"]
    try:
        rc, out, _ = run_bounded(argv, cwd=repo, env=git_env(), stdin=None,
                                 timeout=cfg["subprocess_timeout_seconds"],
                                 cap=cfg["max_subprocess_output_bytes"])
    except OSError as exc:
        raise InventoryError(f"git could not be run: {type(exc).__name__}") from None
    if rc != 0:
        raise InventoryError(f"git ls-files exited {rc}")
    paths: list[str] = []
    for entry in out.split(b"\0"):
        if not entry:
            continue
        meta, _, raw_path = entry.partition(b"\t")
        fields = meta.split(b" ")
        if len(fields) != 3 or fields[2] != b"0" or fields[0].decode("ascii", "replace") not in _REGULAR_MODES:
            continue  # symlink (120000), submodule (160000) or a conflict stage
        try:
            paths.append(raw_path.decode("utf-8"))
        except UnicodeDecodeError:
            print("wiring-audit: skipped a tracked path that is not UTF-8", file=sys.stderr)
    return sorted(paths)


def _printable_path(path: str) -> bool:
    return all(ch == " " or unicodedata.category(ch)[0] in _PRINTABLE_PATH_CATEGORIES for ch in path)


# --- content ---------------------------------------------------------------------------


def read_regular_file(repo: Path, rel: str, limit: int) -> bytes | None:
    """Read at most ``limit`` bytes of repo/rel, refusing any symlink on the way (F7)."""
    root = repo.resolve()
    full = root / rel
    try:
        if os.path.realpath(full) != str(full):
            return None  # a parent directory is a symlink, or the file is
        st = os.lstat(full)
        if not stat.S_ISREG(st.st_mode):
            return None
        fd = os.open(full, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    with os.fdopen(fd, "rb") as handle:
        return handle.read(limit)


def sanitise_text(raw: bytes) -> str:
    """UTF-8 with replacement; LF line ends; no NUL or other C0/C1 controls except tab."""
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    return "".join(ch for ch in text
                   if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cs"))


def drop_personal_lines(text: str, patterns: list[re.Pattern[str]]) -> str:
    return "\n".join(_PERSONAL_PLACEHOLDER if config.matches_personal_path(line, patterns) else line
                     for line in text.split("\n"))


def truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n[truncated by the wiring audit: {len(text) - limit} characters omitted]", True


def custom_id_for(path: str) -> str:
    slug = _SLUG_UNSAFE.sub("-", path).strip("-")[:48] or "module"
    return f"{slug}_{hashlib.sha256(path.encode('utf-8')).hexdigest()[:12]}"


def _decorator_name(node: ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return ""


def python_facts(text: str) -> tuple[list[str], bool]:
    """(entry points, syntax_error) via ast; never raises."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return [], True
    entries: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for deco in getattr(node, "decorator_list", []):
                if _decorator_name(deco) in _ROUTE_DECORATORS:
                    entries.add(f"route:{node.name}")
        elif isinstance(node, ast.If):
            test = node.test
            if (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
                    and test.left.id == "__name__"):
                entries.add("__main__")
    try:
        walked = list(ast.walk(tree))
    except RecursionError:
        walked = []
    for node in walked:
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_parser" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            entries.add(f"subcommand:{node.args[0].value[:64]}")
    return sorted(entries), False


def _is_test_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"
            or "/tests/" in f"/{path}")


def _imported_names(text: str) -> set[str]:
    """Every dotted-name component an import line in ``text`` mentions."""
    names: set[str] = set()
    for line in text.split("\n"):
        m = _IMPORT_LINE.match(line)
        if not m:
            continue
        for chunk in (m.group(1), m.group(2), m.group(3)):
            if chunk:
                names.update(_IDENT.findall(chunk))
    return names


def link_references(modules: list[Module], limit: int) -> None:
    """Fill callers / tests / workflows from the other KEPT modules only."""
    imports = {m.path: _imported_names(m.text) for m in modules}
    for mod in modules:
        base = mod.path.rsplit("/", 1)[-1]
        stem = base.rsplit(".", 1)[0]
        callers = []
        for other in modules:
            if other.path == mod.path:
                continue
            if (mod.path.endswith(".py") and stem in imports[other.path]) or base in other.text:
                callers.append(other.path)
        mod.callers = callers[:limit]
        mod.tests = [p for p in callers if _is_test_path(p)][:limit]
        mod.workflows = [p for p in callers if p.startswith(".github/workflows/")][:limit]


def load_module(repo: Path, path: str, cfg: dict[str, Any], personal: list[re.Pattern[str]]) -> Module | None:
    limit = cfg["max_module_chars"]
    raw = read_regular_file(repo, path, limit * 4 + 4)
    if raw is None:
        return None
    text = drop_personal_lines(sanitise_text(raw), personal)
    shown, truncated = truncate(text, limit)
    entries, bad = python_facts(text) if path.endswith(".py") else ([], False)
    return Module(path=path, custom_id=custom_id_for(path), text=text, truncated_text=shown,
                  truncated=truncated, sha256=hashlib.sha256(raw).hexdigest(), entry_points=entries,
                  syntax_error=bad)


class Inventory:
    def __init__(self, modules: list[Module], canary: Module) -> None:
        self.modules = modules
        self.canary = canary


def build_inventory(repo: Path, cfg: dict[str, Any]) -> Inventory:
    """The audited modules plus the canary, linked; raises InventoryError / ConfigError."""
    repo = repo.resolve()
    personal = config.load_personal_patterns(repo, cfg)
    include = _compile_globs(cfg["module_globs"])
    exclude = _compile_globs(cfg["exclude_globs"])
    canary_path = cfg["canary_fixture"]
    modules: list[Module] = []
    for path in tracked_files(repo, cfg):
        if path == canary_path or not _printable_path(path):
            continue
        if not _any_match(include, path) or _any_match(exclude, path):
            continue
        if config.matches_personal_path(path, personal):
            continue
        mod = load_module(repo, path, cfg, personal)
        if mod is not None:
            modules.append(mod)
    canary = load_module(repo, canary_path, cfg, personal)
    if canary is None:
        raise ConfigError("config key 'canary_fixture': the canary fixture is not a regular file")
    link_references(modules + [canary], cfg["max_listed_references"])
    ids = [m.custom_id for m in modules] + [canary.custom_id]
    if len(set(ids)) != len(ids) or not all(config.CUSTOM_ID_RE.fullmatch(i) for i in ids):
        raise InventoryError("custom_id collision or invalid custom_id")
    return Inventory(modules=modules, canary=canary)


def inventory_json(inv: Inventory) -> str:
    doc = {"module_count": len(inv.modules), "modules": [m.facts() for m in inv.modules]}
    return json.dumps(doc, sort_keys=True, indent=1, ensure_ascii=True) + "\n"


# --- CLI ---------------------------------------------------------------------------------


def workflow_escape(text: str) -> str:
    """Encode a message for a GitHub workflow command (one line, % CR LF escaped)."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def fail(name: str, message: str, codes: dict[str, int]) -> int:
    print(f"::error title=wiring-audit::{name}: {workflow_escape(message)}", flush=True)
    return codes[name]


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error, which is BUDGET_EXCEEDED here; use CONFIG instead."""

    def error(self, message: str) -> Any:  # type: ignore[override]
        raise ConfigError(f"usage: {message}")


def make_parser(description: str) -> argparse.ArgumentParser:
    return _Parser(description=description)


def main(argv: list[str] | None = None) -> int:
    try:
        parser = make_parser("Print the wiring-audit inventory for a checkout.")
        parser.add_argument("--repo", required=True)
        parser.add_argument("--config", required=True)
        args = parser.parse_args(argv)
        cfg = config.load_config(args.config)
        inv = build_inventory(Path(args.repo), cfg)
    except ConfigError as exc:
        return fail("CONFIG", str(exc), EXIT_CODES)
    except InventoryError as exc:
        return fail("CONFIG", f"inventory: {exc}", EXIT_CODES)
    if not inv.modules:
        return fail("NO_MODULES", "the inventory is empty: no tracked file matched the module globs "
                    "after the denylist; check module_globs in the config", EXIT_CODES)
    sys.stdout.write(inventory_json(inv))
    print(f"wiring-audit: INVENTORY_OK {len(inv.modules)} modules", file=sys.stderr)
    return EXIT_CODES["OK"]


if __name__ == "__main__":
    sys.exit(main())
