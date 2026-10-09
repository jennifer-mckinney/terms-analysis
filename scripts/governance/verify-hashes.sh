#!/usr/bin/env bash
# verify-hashes.sh
# Verify that governance files match the SHA256 hashes recorded in two
# manifests:
#   .claude/_governance-manifest.json        tracked; repo-relative paths only
#   .claude/_governance-manifest.local.json  untracked (gitignored); $HOME/ paths
# The tracked manifest is required. The local manifest is verified when it is
# present and reported as LOCAL MANIFEST SKIPPED when it is absent (#200), so
# the public repo never publishes hashes of a developer's private files.
#
# Exit codes:
#   0 - all hashes match (HASHES OK carries the repo-file count)
#   1 - hash drift detected on one or more files
#   2 - a manifest is missing, unreadable, malformed, empty or has an entry
#       outside the path allowlist; or python3 is unavailable
#   3 - a file named in a manifest is missing or unreadable on disk
#
# Messages name manifest paths only (never the resolved absolute path) and
# never echo raw manifest bytes.

set -u

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 required to read the governance manifests" >&2
    exit 2
fi

# Locate repo root: this script lives at <repo>/scripts/governance/verify-hashes.sh.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TRACKED_REL=".claude/_governance-manifest.json"
LOCAL_REL=".claude/_governance-manifest.local.json"

# -I: isolated mode, so nothing in the cwd can shadow a stdlib import.
exec python3 -I - "${REPO_ROOT}" "${TRACKED_REL}" "${LOCAL_REL}" <<'PY'
import hashlib
import json
import os
import re
import sys

EXIT_OK, EXIT_DRIFT, EXIT_MANIFEST, EXIT_MISSING = 0, 1, 2, 3
HOME_PREFIX = "$HOME/"
# Allowlist (F1): each path segment is ASCII letters, digits, '.', '_' or '-'.
# Line breaks of any kind, '|', NUL and every other character are rejected.
SEGMENT_RE = re.compile(r"[A-Za-z0-9._-]+")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
CHUNK = 1 << 16


class ManifestError(Exception):
    """The manifest itself is unusable (exit 2)."""


def check_path(raw, home_scope):
    """Validate one manifest path; return it relative to its base dir."""
    if not isinstance(raw, str):
        raise ManifestError("path is not a string")
    if home_scope:
        if not raw.startswith(HOME_PREFIX):
            raise ManifestError("path must start with $HOME/")
        rel = raw[len(HOME_PREFIX):]
    else:
        if raw.startswith(HOME_PREFIX):
            raise ManifestError("$HOME/ paths belong in the local manifest")
        rel = raw
    for seg in rel.split("/"):
        if seg in ("", ".", "..") or not SEGMENT_RE.fullmatch(seg):
            raise ManifestError("path has an empty, dot or non-allowlisted segment")
    return rel


def load_manifest(abs_path, home_scope):
    """Parse and validate a manifest; return [(raw, rel, sha256, size)]."""
    try:
        with open(abs_path, "rb") as fh:
            blob = fh.read()
    except OSError:
        raise ManifestError("cannot be read")
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        raise ManifestError("is not valid UTF-8")
    try:
        data = json.loads(text)
    except ValueError:
        raise ManifestError("is not valid JSON")
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise ManifestError("has no entries list")
    if not data["entries"]:
        raise ManifestError("has zero entries")
    seen = set()
    out = []
    for idx, entry in enumerate(data["entries"], 1):
        try:
            if not isinstance(entry, dict):
                raise ManifestError("is not an object")
            raw = entry.get("path")
            rel = check_path(raw, home_scope)
            if raw in seen:
                raise ManifestError("duplicates an earlier path")
            sha = entry.get("sha256")
            if not isinstance(sha, str) or not SHA256_RE.fullmatch(sha):
                raise ManifestError("sha256 is not 64 lowercase hex characters")
            size = entry.get("size_bytes")
            if type(size) is not int or size < 0:
                raise ManifestError("size_bytes is not a non-negative integer")
        except ManifestError as exc:
            raise ManifestError("entry %d: %s" % (idx, exc))
        seen.add(raw)
        out.append((raw, rel, sha, size))
    return out


def file_digest(abs_path):
    """Return (sha256 hex, size) or None when the file is absent/unreadable."""
    if not os.path.isfile(abs_path):
        return None
    digest = hashlib.sha256()
    size = 0
    try:
        with open(abs_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(CHUNK), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError:
        return None
    return digest.hexdigest(), size


def delta_note(expected_size, size):
    if size == expected_size:
        return "same size, content differs"
    return "%+d bytes vs manifest" % (size - expected_size)


def check(entries, base, tag, missing, drift):
    ok = 0
    for raw, rel, sha, expected_size in entries:
        got = file_digest(os.path.join(base, rel))
        if got is None:
            missing.append(raw + tag)
        elif got[0] == sha:
            ok += 1
        else:
            drift.append("%s: expected %s got %s (%s)%s" % (
                raw, sha[:12], got[0][:12], delta_note(expected_size, got[1]), tag))
    return ok


def main():
    repo, tracked_rel, local_rel = sys.argv[1:4]
    tracked_abs = os.path.join(repo, tracked_rel)
    local_abs = os.path.join(repo, local_rel)

    if not os.path.isfile(tracked_abs):
        print("MANIFEST MISSING: %s" % tracked_rel)
        return EXIT_MANIFEST
    try:
        tracked = load_manifest(tracked_abs, home_scope=False)
    except ManifestError as exc:
        print("MANIFEST INVALID: %s %s" % (tracked_rel, exc))
        return EXIT_MANIFEST

    local = None
    home = ""
    if os.path.lexists(local_abs):
        try:
            if not os.path.isfile(local_abs):
                raise ManifestError("is not a regular file")
            local = load_manifest(local_abs, home_scope=True)
            home = os.environ.get("HOME", "")
            if not os.path.isabs(home):
                raise ManifestError("cannot be verified: HOME is not an absolute path")
        except ManifestError as exc:
            print("MANIFEST INVALID: %s %s" % (local_rel, exc))
            return EXIT_MANIFEST

    missing, drift = [], []
    verified = check(tracked, repo, "", missing, drift)
    local_verified = 0
    if local is not None:
        local_verified = check(local, home, " [%s]" % local_rel, missing, drift)

    if missing:
        print("TRACKED FILE MISSING: %s" % missing[0])
        return EXIT_MISSING
    if drift:
        print("HASH DRIFT:")
        for line in drift:
            print(line)
        return EXIT_DRIFT

    print("HASHES OK: %d files verified" % verified)
    if local is None:
        print("LOCAL MANIFEST SKIPPED: %s not present; per-developer files not verified" % local_rel)
    else:
        print("LOCAL MANIFEST OK: %d files verified (%s)" % (local_verified, local_rel))
    return EXIT_OK


try:
    sys.exit(main())
except Exception as exc:  # fail closed (F4) without a traceback or path (F8)
    print("VERIFY ERROR: unexpected %s" % type(exc).__name__)
    sys.exit(EXIT_MANIFEST)
PY
