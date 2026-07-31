"""Surface-conformance spec for vendor-derivation callable (issue #79).

This test independently specifies the public surface of the module that owns
vendor derivation from URLs. Per the spec, the ONLY vendor-derivation callable
exposed by that module must be ``_derive_vendor_from_url``. No alias, no shim,
no legacy name (in particular, no ``_vendor_from_url``).

Written by the Test Helper subagent (P8 role B) independently from the Coder's
regression test — this file specifies the required module surface rather than
asserting the absence of a single known-bad name.

# NOTE: This surface-conformance test can be safely removed 3+ months after
# issue #79 lands if no alias regression appears. Its purpose is to lock down
# the vendor-derivation surface during the immediate post-fix window.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


# Independently discovered module location: src/backend/scripts/migrate_policywatch_to_watchlist.py
# `scripts/` is not an importable package, so we load via importlib.util.
_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "migrate_policywatch_to_watchlist.py"
)


def _load_module() -> ModuleType:
    """Load the migration script as a module for surface assertions.

    This imports the script (executing its import-time setup) but does not run the
    CLI entrypoint guarded by ``if __name__ == '__main__':``.
    """
    spec = importlib.util.spec_from_file_location(
        "migrate_policywatch_to_watchlist_under_test",
        _MODULE_PATH,
    )
    assert spec is not None and spec.loader is not None, (
        f"Could not build import spec for {_MODULE_PATH}"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_module_file_exists() -> None:
    """Precondition: the module that owns vendor derivation is where we expect."""
    assert _MODULE_PATH.is_file(), (
        f"Expected vendor-derivation module at {_MODULE_PATH}; "
        "if it moved, update this spec test to point at the new location."
    )


def test_canonical_derive_vendor_from_url_exists_and_is_callable() -> None:
    """Spec: the canonical vendor-derivation function must exist and be callable."""
    module = _load_module()
    assert hasattr(module, "_derive_vendor_from_url"), (
        "_derive_vendor_from_url is missing from the module — the canonical "
        "vendor-derivation function must exist."
    )
    assert callable(getattr(module, "_derive_vendor_from_url")), (
        "_derive_vendor_from_url exists but is not callable — spec violation."
    )


def test_no_vendor_from_url_alias_on_module() -> None:
    """Spec: no ``_vendor_from_url`` alias/shim/legacy name may be exposed."""
    module = _load_module()
    assert not hasattr(module, "_vendor_from_url"), (
        "_vendor_from_url alias is present on the module. Issue #79 requires "
        "removal of this dead alias — the canonical name is "
        "_derive_vendor_from_url."
    )


def test_only_derive_vendor_from_url_ends_with_from_url() -> None:
    """Spec: enumerate all callables ending in ``_from_url`` and require exactly one.

    This is stricter than checking for a single known alias name: it catches
    any future alias (e.g. ``_vendor_id_from_url``, ``_guess_vendor_from_url``)
    that shadows the same responsibility under a different label.
    """
    module = _load_module()
    from_url_callables = {
        name
        for name in dir(module)
        if not name.startswith("__")
        and name.endswith("_from_url")
        and callable(getattr(module, name, None))
    }
    assert from_url_callables == {"_derive_vendor_from_url"}, (
        "Vendor-derivation surface violation: expected exactly "
        "{'_derive_vendor_from_url'} as the sole *_from_url callable on the "
        f"module, found {sorted(from_url_callables)!r}. If a new *_from_url "
        "helper is legitimately needed, update this spec deliberately."
    )
