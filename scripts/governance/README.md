# Governance Hash Manifest

## What this protects against

Silent drift of governance files. The role principles in
`.claude/library/LIB-PRINCIPLES.md`, the project charter in
`.claude/CLAUDE.md`, and the two global anchors under `$HOME/.claude/` are
load-bearing. If they change without review, downstream agent behavior
changes without a paper trail.

This directory holds two shell scripts that maintain two hash manifests.
Each manifest records SHA256 of its files. The verify script detects any
drift. The regen script rebuilds both manifests after a legitimate change.

## Two manifests (#200)

- `.claude/_governance-manifest.json` is tracked and holds repo-relative
  files only. It is always verified; a missing or malformed one exits 2.
- `.claude/_governance-manifest.local.json` is untracked (gitignored, and
  listed in `.claude/governance/required-gitignore.txt`). It holds the
  per-developer `$HOME/` files, so the public repo never publishes hashes
  of private files. Verify checks it when present and prints
  `LOCAL MANIFEST SKIPPED` when absent (CI runners, fresh clones).

## Files

- `../../.claude/_governance-manifest.json`: the tracked manifest.
- `../../.claude/_governance-manifest.local.json`: the local manifest
  (written by regen, never committed).
- `verify-hashes.sh`: recompute hashes and compare to both manifests.
- `regen-manifest.sh`: overwrite both manifests with current hashes.

## Tracked governance files

| Manifest path | Manifest | Meaning |
| --- | --- | --- |
| `.claude/CLAUDE.md` | tracked | Project governance charter |
| `.claude/library/LIB-PRINCIPLES.md` | tracked | Role principles (P1 through Pn) |
| `.claude/governance/required-gitignore.txt` | tracked | Required `.gitignore` patterns (SSoT) |
| `$HOME/.claude/CLAUDE.md` | local | Global user CLAUDE.md |
| `$HOME/.claude/library/PEAS.md` | local | PEAS agent design framework |

The list lives in `regen-manifest.sh` (`REPO_ENTRIES`, `LOCAL_ENTRIES`).

### Canonical path form for global files

Global files are recorded, in the local manifest only, with the literal
string `$HOME/` prefix inside the JSON. The verify script expands `$HOME` at runtime using the calling
shell's environment. Rationale:

1. Portable across machines and users. No hardcoded `/Users/<name>/`
   paths in the repo.
2. Explicit distinction between repo-relative paths (no prefix) and
   home-relative paths (`$HOME/` prefix).
3. Resolvable with plain shell expansion, no extra tooling.

Project-relative paths have no prefix and are resolved from the repo
root, which the scripts derive from their own location on disk.

## Usage

### Verify (routine check)

```
scripts/governance/verify-hashes.sh
```

Exit codes:

- `0`: `HASHES OK: N files verified` (N counts tracked repo files),
  then `LOCAL MANIFEST OK: M files verified (...)` or
  `LOCAL MANIFEST SKIPPED: ...` when the local manifest is absent.
- `1`: `HASH DRIFT:` followed by one line per drifted file. Each line
  shows the first 12 hex chars of expected and actual hash plus a byte
  delta note. Full file contents are never dumped.
- `2`: `MANIFEST MISSING:` the tracked manifest was not found, or
  `MANIFEST INVALID:` a manifest is unreadable, not UTF-8, not JSON, has
  zero entries, or has an entry whose path is outside the allowlist
  (ASCII letters, digits, `.`, `_`, `-` per segment; no `..`; `$HOME/`
  only in the local manifest, never in the tracked one).
- `3`: `TRACKED FILE MISSING:` a manifested file no longer exists on
  disk (or cannot be read).

Messages name manifest paths only, never the resolved absolute path.

### Regenerate (only after an intentional change)

```
scripts/governance/regen-manifest.sh          # interactive prompt
scripts/governance/regen-manifest.sh --yes    # non-interactive
```

Run this only after an intentional governance change that has been
reviewed via PR. The interactive prompt is a deliberate speed bump.

## When to regenerate

Regenerate the manifest only when all of the following are true:

1. A governance file changed intentionally.
2. The change went through review, ideally on a PR that also updates
   the manifest in the same commit.
3. The reviewer explicitly notes that the manifest bump is expected.

Regenerating on every drift defeats the purpose. If verify fails and
you did not plan a governance change, treat it as a signal and
investigate before regenerating.

## How CI could enforce this

Not wired up yet, but the pattern would be:

1. Add a CI job that runs `scripts/governance/verify-hashes.sh` on
   every pull request and every push to the default branch.
2. Fail the build on exit code 1, 2, or 3.
3. Require any PR that intentionally changes a governance file to
   update `_governance-manifest.json` in the same commit. Reviewers
   confirm the manifest bump matches the file change.
4. Optionally add a pre-commit hook that runs verify locally so drift
   is caught before push.

Global files under `$HOME/` are per-developer and live only in the
untracked local manifest, so CI verifies the tracked repo files strictly
and reports `LOCAL MANIFEST SKIPPED` for the rest.

## Notes

- Hashing, parsing and validation use `python3` (stdlib `hashlib` and
  `json`, run with `-I`). No `jq`, `sha256sum` or `shasum` dependency.
- Regen writes each manifest through a temp file and rename, writes the
  local one with mode 0600, then runs verify as a round trip.
- The manifest is valid JSON. Validate with
  `python3 -m json.tool .claude/_governance-manifest.json`.
