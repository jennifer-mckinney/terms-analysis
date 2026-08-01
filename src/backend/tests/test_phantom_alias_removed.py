"""Regression: _vendor_from_url alias should not exist (issue #79)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_migration_module() -> ModuleType:
    # The migration script lives under scripts/ and is not a package member,
    # so load it via importlib to reach its module namespace for hasattr().
    script_path = (
        Path(__file__).resolve().parent.parent
        / "scripts"
        / "migrate_policywatch_to_watchlist.py"
    )
    spec = importlib.util.spec_from_file_location(
        "migrate_policywatch_to_watchlist", script_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vendor_from_url_alias_does_not_exist() -> None:
    # Only _derive_vendor_from_url should exist — the alias was dead weight
    # per triage 2026-07-31 (issue #79). Delete this test after 3 months
    # if it stays green and no one has re-added the alias.
    module = _load_migration_module()
    assert hasattr(module, "_derive_vendor_from_url"), (
        "_derive_vendor_from_url (the real function) is missing; test is stale"
    )
    assert not hasattr(module, "_vendor_from_url"), (
        "_vendor_from_url alias re-appeared; delete it and update this test"
    )
