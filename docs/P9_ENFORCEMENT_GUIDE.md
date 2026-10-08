# P9 Review Enforcement Guide

Implementation of **LIB-PRINCIPLES P9: pre-push-independent-review** for terms-analysis project.

> See `automations/p9-pre-push.md` for the current signoff-based gate reference. The prior interactive-checklist reminder hook has been retired; the local gate is now `.githooks/pre-push`, which requires a valid signoff file at `$(git rev-parse --git-common-dir)/reviews/<sha>.signoff.json` for the commit at the tip of every pushed ref, and refuses a push that would publish any commit outside the signoff's reviewed range (`range.base..tip`). The signoff lives in the shared common git dir, so the main checkout and every `git worktree` use the same location. The local gate guards against honest mistakes; GitHub branch protection on `main` is the enforcing control (see "Limits" under Layer 1).

## What is P9?

P9 mandates that before ANY push to main, two independent agents must review the assembled commits:

1. **security-engineer**: STRIDE-style threat-model review
   - Auth, secrets, user input validation
   - RLS, CSP, dependencies, session/cookie state
   - Migration safety, endpoint deprecation
   - **Policy**: ALL findings (CRITICAL → NIT) must be fixed (zero-tolerance)

2. **grumpy-developer**: Blunt code-quality review
   - Swallowed errors, dead code, brittle assumptions
   - Missed edge cases, tautological tests
   - Dispatch-boundary artifacts from multi-agent sessions
   - **Policy**: ALL findings (CRITICAL → NIT) must be fixed (zero-tolerance, `.claude/CLAUDE.md` G3 and SO11, owner directive 2026-07-04)

## Enforcement Layers

### Layer 1: Local gate (`.githooks/pre-push`)

**Triggers**: `git push` (any remote, any ref); runs locally before the transport step and checks every ref git is about to push.

**Behavior**: the enforced contract (per-ref signoff, zero-tolerance findings for both reviewers, reviewed-range check, override, deletions, the nothing-to-push case) is stated once, in the "Enforced contract" section of `automations/p9-pre-push.md`, which a test keeps word-for-word equal to the hook header. It is not restated here.

**Usage**: Automatic on `git push`. To satisfy the gate, ask the orchestrator to run the P9 review pair; the review agents write the signoff file to `$(git rev-parse --git-common-dir)/reviews/<sha>.signoff.json`.

**Limits**: the hook is client-side. `git push --no-verify`, `git -c core.hooksPath=... push`, a commit that edits `.githooks/pre-push`, or a hand-written signoff all bypass it. `main` is branch-protected on GitHub (PR required, required checks, `enforce_admins`), which is what actually blocks a direct push. A required CI check that verifies a committed signoff for the PR head is not in place yet. Full list: `automations/p9-pre-push.md`, "Limits and server-side enforcement".

**Authoritative reference**: `automations/p9-pre-push.md` documents the signoff schema, verdict rules, override path, and failure modes. That doc is the source of truth; this section is a pointer.

### Layer 2: GitHub Actions Workflow (`.github/workflows/enforce-p9-review.yml`)

**Triggers**: On pull request to `main` (opened, synchronize, reopened)

**Checks**:
1. Requires `security-engineer` review mention in PR body (case-insensitive)
2. Requires `grumpy-developer` review mention in PR body (case-insensitive)
3. Scans for unresolved CRITICAL/HIGH findings

**Enforcement**: Workflow fails if any check fails; PR cannot merge until fixed

**Status**: Blocks merge on GitHub

## How to Use P9

### Workflow for Feature Branches

1. **Implement changes** on feature branch (e.g., `claude/my-feature`)

2. **Open PR to main** with initial description

3. **Run review agents** (in-session, before merge):
   ```bash
   # In Claude Code session
   /dispatch-agent security-engineer --scope "review my-feature PR diff for threats"
   /dispatch-agent grumpy-developer --scope "review my-feature PR diff for code quality"
   ```

4. **Document results** in PR body:
   ```markdown
   ## P9 Reviews

   ✅ security-engineer: approved (no findings)
   ✅ grumpy-developer: approved (found 3 items: 1 HIGH, 2 MEDIUM, all resolved)

   ### Security Review Summary
   - No auth/secret/input validation issues
   - All CVE-checked dependencies pass
   
   ### Code Quality Review Summary
   - [RESOLVED] HIGH: error swallowing in `utils.py::parse_date()` — fixed with try/except + logging
   - [RESOLVED] MEDIUM: brittle assumption in `models.py` line 42 (assumes non-null role) — null role now handled
   - [RESOLVED] MEDIUM: dead code in `services.py` — `legacy_analyzer()` removed
   ```

5. **Push to main** after reviews are documented and GitHub Actions passes

### PR Body Template

```markdown
## Summary
[Brief description of changes]

## Changes
- [List key changes]

## P9 Reviews (Required for merge to main)

✅ security-engineer: approved ([findings summary])
✅ grumpy-developer: approved ([findings summary])

### Security Engineer Review
[Detailed review notes from security-engineer]

### Grumpy Developer Review
[Detailed review notes from grumpy-developer]
```

## Local Hook Configuration

The `.githooks` directory is configured in git:

```bash
git config --get core.hooksPath
# Expected: .githooks
```

The installer (`bash scripts/install-hooks.sh`) is idempotent and sets this automatically. It works from the main checkout or any worktree, replaces any other value (for example an absolute `<repo>/.git/hooks`, which disables the gate) with a stderr notice naming the old value, fails if a higher-precedence scope still shadows it, and creates `<git-common-dir>/reviews/`. To verify the local gate is in place:

```bash
# Confirm hooks path is wired
git config --get core.hooksPath          # expected: .githooks

# Confirm the pre-push hook is executable
test -x .githooks/pre-push && echo "hook installed"

# Confirm the signoff directory exists
ls -d "$(git rev-parse --path-format=absolute --git-common-dir)/reviews"   # expected: directory exists
```

To smoke-test the refuse path without actually pushing:

```bash
git push --dry-run
```

With no signoff present the hook prints a "signoff not found" diagnostic and exits 1; nothing leaves the machine. If the remote is already up to date, the hook prints "nothing to push" and exits 0.

## CI/CD Enforcement Details

### Workflow: `enforce-p9-review.yml`

**Location**: `.github/workflows/enforce-p9-review.yml`

**Triggers**: Pull requests to main

**Steps**:
1. Extract PR body safely (uses temp file to avoid escaping issues)
2. Check for `security-engineer` review — accepts either:
   - Inline approval: `security-engineer.*approved` or `✅.*security-engineer`
   - Signoff reference: `security-engineer` mentioned anywhere AND (`both PASS` / `verdict.*pass` / `signoff.json`) also present
3. Check for `grumpy-developer` review — accepts either:
   - Inline approval: `grumpy-developer.*approved` or `✅.*grumpy-developer`
   - Signoff reference: `grumpy-developer` mentioned anywhere AND (`both PASS` / `verdict.*pass` / `signoff.json`) also present
4. Scan for unresolved CRITICAL/HIGH findings
5. Report final status (pass/fail)

**Failure modes**:
- Missing security-engineer review → Workflow fails, PR blocked
- Missing grumpy-developer review → Workflow fails, PR blocked
- CRITICAL/HIGH marked as unresolved → Workflow fails, PR blocked

**Resolution**:
1. Run missing review agent(s)
2. Update PR body with review documentation
3. Commit status update (or commit new fix-commits if findings were resolved)
4. GitHub Actions re-runs automatically on push to PR

## Troubleshooting

### "Hook not running on push"

**Check hook path configuration**:
```bash
git config core.hooksPath
# Should output: .githooks
```

**If not set, or set to an absolute `.git/hooks` path, re-run the installer** (it replaces the value and reports what it replaced):
```bash
bash scripts/install-hooks.sh
```

### "Push refused from a worktree even though I have a signoff"

The signoff must be in the common git dir, not in the worktree's own git dir (`.git/worktrees/<name>/`). The refusal's "Expected signoff:" line prints the exact absolute path; move the file there.

### "GitHub Actions workflow not triggering"

**Check workflow file**:
- File must be in `.github/workflows/` with `.yml` extension
- File must be committed to repository
- Trigger conditions must match (e.g., branch is `main`)

**Manual trigger**:
```bash
# Push to main will trigger
git push origin feature-branch:main

# View workflow runs
# https://github.com/[owner]/[repo]/actions
```

### "Workflow passes but I forgot to add P9 reviews"

**This is a gap**: Workflow only checks for the _mention_ of reviews in PR body, not actual review execution. If you accidentally merged without running agents:

1. Create follow-up PR or issue
2. Document that reviews were skipped
3. Consider running reviews post-merge if findings are critical

**Prevention**: Use local hook reminder as checkpoint before push

## Examples

### Example PR with Clean Review

```markdown
## Summary
Refactored policy analyzer to use async/await pattern for I/O

## P9 Reviews

✅ security-engineer: approved (no findings)
✅ grumpy-developer: approved (no findings)

### Security Engineer Review
- Reviewed async/await pattern for race conditions: none found
- Checked database access for injection points: all parameterized
- Verified session handling: no new token creation paths
- Dependency audit: all deps in requirements.txt are Grade A

### Grumpy Developer Review
- No swallowed exceptions in async handlers
- All futures properly awaited (no dangling tasks)
- Edge case: empty policy text handled correctly
- Tests pass for concurrent requests
```

### Example PR with Findings

```markdown
## Summary
Added new GDPR jurisdiction to analyzer

## P9 Reviews

✅ security-engineer: approved (found 1 CRITICAL, resolved)
✅ grumpy-developer: approved (found 2 items: 1 HIGH, 1 MEDIUM, both resolved)

### Security Engineer Review
- [CRITICAL] SQL injection in jurisdiction filter → RESOLVED: added parameterized query in commit c3f4e5d
- RLS check for EU data: OK (existing safeguards sufficient)

### Grumpy Developer Review
- [HIGH] Hard-coded language assumptions in GDPR rules → RESOLVED: now reads from config
- [MEDIUM] Test for GDPR jurisdiction doesn't cover mixed-language cases → RESOLVED: mixed-language cases added in commit d4e5f6a
```

## See Also

- [LIB-PRINCIPLES P9](../.claude/library/LIB-PRINCIPLES.md#p9-pre-push-independent-review)
- [LIB-PRINCIPLES P8 (agent separation)](../.claude/library/LIB-PRINCIPLES.md#p8-agent-separation-of-duties)
- [CLAUDE.md § governance-monitoring](../.claude/CLAUDE.md#governance-monitoring)
