#!/usr/bin/env bash
# regen-manifest.sh
# Regenerate the governance hash manifests with current SHA256 hashes:
#   .claude/_governance-manifest.json        tracked; repo-relative entries
#   .claude/_governance-manifest.local.json  untracked (gitignored); $HOME/ entries
# The $HOME entries live only in the local manifest so the public repo never
# publishes hashes of a developer's private files (#200). Use ONLY after an
# intentional principle or governance change that has been reviewed via PR.
#
# Usage:
#   scripts/governance/regen-manifest.sh          # interactive confirm
#   scripts/governance/regen-manifest.sh --yes    # non-interactive
#
# Exit codes:
#   0 - both manifests written and verify-hashes.sh accepts them
#   1 - user declined, a listed file is missing, HOME is unset, or the
#       written manifests fail verify-hashes.sh (round trip)
#   2 - required tool unavailable or a write failed

set -u

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 required to emit JSON manifest" >&2
    exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TRACKED_REL=".claude/_governance-manifest.json"
LOCAL_REL=".claude/_governance-manifest.local.json"

# Entries. Each row: <manifest_path>|<note>
# Repo-relative rows go to the tracked manifest; $HOME/ rows go to the local
# manifest and are resolved against HOME at regen and verify time.
REPO_ENTRIES=(
    ".claude/CLAUDE.md|Project governance charter."
    ".claude/library/LIB-PRINCIPLES.md|LIB-PRINCIPLES P8 v2 baseline; single source of truth for role principles."
    ".claude/governance/required-gitignore.txt|Reviewer P9 F9 SSoT for required .gitignore patterns read by both pre-commit hook and CI workflow."
)
LOCAL_ENTRIES=(
    "\$HOME/.claude/CLAUDE.md|Global user CLAUDE.md; changes here affect every project session."
    "\$HOME/.claude/library/PEAS.md|PEAS agent design framework reference."
)

AUTO_YES=0
for arg in "$@"; do
    case "${arg}" in
        --yes|-y) AUTO_YES=1 ;;
        *) ;;
    esac
done

if [ "${AUTO_YES}" -ne 1 ]; then
    echo "This overwrites _governance-manifest.json and _governance-manifest.local.json - only run after an intentional governance change was reviewed. Continue? [y/N]"
    read -r reply
    case "${reply}" in
        y|Y|yes|YES) ;;
        *) echo "Aborted."; exit 1 ;;
    esac
fi

TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# Hand (scope, path, note) rows to python3 as argv; python3 hashes every file
# before writing anything, then writes each manifest via temp file + rename.
PY_ARGS=("${REPO_ROOT}" "${TRACKED_REL}" "${LOCAL_REL}" "${TS}")
for row in "${REPO_ENTRIES[@]}"; do
    IFS='|' read -r mpath note <<< "${row}"
    PY_ARGS+=("repo" "${mpath}" "${note}")
done
for row in "${LOCAL_ENTRIES[@]}"; do
    IFS='|' read -r mpath note <<< "${row}"
    PY_ARGS+=("home" "${mpath}" "${note}")
done

python3 -I - "${PY_ARGS[@]}" <<'PY'
import hashlib
import json
import os
import sys

HOME_PREFIX = "$HOME/"
repo, tracked_rel, local_rel, ts = sys.argv[1:5]
rest = sys.argv[5:]
if len(rest) % 3 != 0:
    print("regen-manifest.sh: internal error, entry args not a multiple of 3", file=sys.stderr)
    sys.exit(2)

home = os.environ.get("HOME", "")
groups = {"repo": [], "home": []}
for i in range(0, len(rest), 3):
    scope, mpath, note = rest[i], rest[i + 1], rest[i + 2]
    if scope == "home":
        if not os.path.isabs(home):
            print("ERROR: HOME is not an absolute path; cannot resolve %s" % mpath, file=sys.stderr)
            sys.exit(1)
        fpath = os.path.join(home, mpath[len(HOME_PREFIX):])
    else:
        fpath = os.path.join(repo, mpath)
    if not os.path.isfile(fpath):
        print("ERROR: file missing on disk: %s" % mpath, file=sys.stderr)
        sys.exit(1)
    with open(fpath, "rb") as fh:
        blob = fh.read()
    groups[scope].append({
        "path": mpath,
        "sha256": hashlib.sha256(blob).hexdigest(),
        "size_bytes": len(blob),
        "recorded_at": ts,
        "note": note,
    })

docs = (
    (tracked_rel, 0o644, groups["repo"],
     "Baseline captured after governance change. Repo-relative paths only, "
     "resolved from the repo root. Per-developer files are hashed in the "
     "untracked local manifest (see scripts/governance/README.md)."),
    (local_rel, 0o600, groups["home"],
     "Untracked, per-developer manifest (gitignored). Entries resolve "
     "against HOME at verify time. Never commit this file."),
)
try:
    for rel, mode, entries, note in docs:
        dest = os.path.join(repo, rel)
        tmp = dest + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 1, "generated_at": ts, "note": note,
                       "entries": entries}, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, dest)
except OSError as exc:
    print("ERROR: could not write manifest (%s)" % type(exc).__name__, file=sys.stderr)
    sys.exit(2)
PY
rc=$?
if [ "${rc}" -ne 0 ]; then
    exit "${rc}"
fi

# Round trip: the reader's validator must accept what was just written.
if ! bash "${SCRIPT_DIR}/verify-hashes.sh" >/dev/null; then
    echo "ERROR: regenerated manifests fail verify-hashes.sh" >&2
    exit 1
fi

echo "MANIFEST REGENERATED: ${#REPO_ENTRIES[@]} tracked entries (${TRACKED_REL}), ${#LOCAL_ENTRIES[@]} local entries (${LOCAL_REL})"
exit 0
