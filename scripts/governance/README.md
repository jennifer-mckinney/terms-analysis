# Governance Hash Manifest

## What this protects against

Silent drift of governance files. The role principles in
`.claude/library/LIB-PRINCIPLES.md`, the project charter in
`.claude/CLAUDE.md`, and the two global anchors under `$HOME/.claude/` are
load-bearing. If they change without review, downstream agent behavior
changes without a paper trail.

This directory holds a small hash manifest and two shell scripts. The
manifest records SHA256 of each tracked file. The verify script detects
any drift. The regen script rebuilds the manifest after a legitimate
change.

## Files

- `../../.claude/_governance-manifest.json`: the manifest itself.
- `verify-hashes.sh`: recompute hashes and compare to the manifest.
- `regen-manifest.sh`: overwrite the manifest with current hashes.
- `tests/`: optional shell tests for regen and verify.

## Tracked governance files

| Manifest path | Meaning |
| --- | --- |
| `.claude/CLAUDE.md` | Project governance charter |
| `.claude/library/LIB-PRINCIPLES.md` | Role principles (P1 through Pn) |
| `$HOME/.claude/CLAUDE.md` | Global user CLAUDE.md |
| `$HOME/.claude/library/PEAS.md` | PEAS agent design framework |

### Canonical path form for global files

Global files are recorded with the literal string `$HOME/` prefix inside
the JSON. The verify script expands `$HOME` at runtime using the calling
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

- `0`: `HASHES OK: N files verified`
- `1`: `HASH DRIFT:` followed by one line per drifted file. Each line
  shows the first 12 hex chars of expected and actual hash plus a byte
  delta note. Full file contents are never dumped.
- `2`: `MANIFEST MISSING:` the JSON manifest was not found.
- `3`: `TRACKED FILE MISSING:` a manifested file no longer exists on
  disk.

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

Global files under `$HOME/` are per-developer. CI cannot verify them
unless a copy is checked into the repo or the CI environment mirrors
the developer environment. In practice CI should verify the two
project files strictly, and treat the two global files as advisory,
skipping them when `$HOME/.claude/` does not exist on the runner.

## Notes

- Both scripts detect `sha256sum` first and fall back to
  `shasum -a 256`. This keeps them portable across Linux and macOS.
- No `jq` dependency. Manifest parsing uses `python3`.
- The manifest is valid JSON. Validate with
  `python3 -m json.tool .claude/_governance-manifest.json`.
