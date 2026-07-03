# P9 Review Enforcement Guide

Implementation of **LIB-PRINCIPLES P9: pre-push-independent-review** for terms-analysis project.

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
   - **Policy**: CRITICAL/HIGH must be fixed; MEDIUM/LOW/NIT can be follow-up issues

## Enforcement Layers

### Layer 1: Local Git Hook (`.githooks/pre-push-p9-check`)

**Triggers**: Before any push to `main`

**Behavior**:
- Displays P9 reminder with review scope
- Asks user to confirm they have P9 reviews documented
- Can be bypassed by user (not automated enforcement)

**Usage**: Automatic on `git push origin main`

**Example output**:
```
════════════════════════════════════════════════════════════════
⚠️  P9 REVIEW REMINDER: Before Pushing to Main
════════════════════════════════════════════════════════════════

P9 (LIB-PRINCIPLES) Requirement:
  Before ANY push to main, you MUST have reviewed commits with:
    1. security-engineer agent (STRIDE threat-model review)
    2. grumpy-developer agent (code-quality review)
...
Continue? (y/n):
```

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
   ✅ grumpy-developer: approved (found 3 items: 1 HIGH resolved, 2 MEDIUM filed as follow-ups)

   ### Security Review Summary
   - No auth/secret/input validation issues
   - All CVE-checked dependencies pass
   
   ### Code Quality Review Summary
   - [RESOLVED] HIGH: error swallowing in `utils.py::parse_date()` — fixed with try/except + logging
   - [FOLLOW-UP] MEDIUM: brittle assumption in `models.py` line 42 (assumes non-null role)
   - [FOLLOW-UP] MEDIUM: dead code in `services.py` — `legacy_analyzer()` not called anywhere
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
git config core.hooksPath
# Output: .githooks
```

This was set automatically. To verify:

```bash
# Check hook is executable
ls -l .githooks/pre-push-p9-check
# Should show: -rwxr-xr-x ... pre-push-p9-check

# Test hook manually (optional)
bash .githooks/pre-push-p9-check
```

## CI/CD Enforcement Details

### Workflow: `enforce-p9-review.yml`

**Location**: `.github/workflows/enforce-p9-review.yml`

**Triggers**: Pull requests to main

**Steps**:
1. Extract PR body safely (uses temp file to avoid escaping issues)
2. Check for `security-engineer` mention (regex: `security-engineer.*approved` or `✅.*security-engineer`)
3. Check for `grumpy-developer` mention (regex: `grumpy-developer.*approved` or `✅.*grumpy-developer`)
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

**If not set, configure manually**:
```bash
git config core.hooksPath .githooks
```

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
✅ grumpy-developer: approved (no blocking findings)

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
✅ grumpy-developer: approved (found 2 items: 1 HIGH resolved, 1 MEDIUM follow-up)

### Security Engineer Review
- [CRITICAL] SQL injection in jurisdiction filter → RESOLVED: added parameterized query in commit c3f4e5d
- RLS check for EU data: OK (existing safeguards sufficient)

### Grumpy Developer Review
- [HIGH] Hard-coded language assumptions in GDPR rules → RESOLVED: now reads from config
- [MEDIUM] Test for GDPR jurisdiction doesn't cover mixed-language cases → Filed as #412 (follow-up)
```

## See Also

- [LIB-PRINCIPLES P9](../.claude/library/LIB-PRINCIPLES.md#p9-pre-push-independent-review)
- [LIB-PRINCIPLES P8 (agent separation)](../.claude/library/LIB-PRINCIPLES.md#p8-agent-separation-of-duties)
- [CLAUDE.md § governance-monitoring](../.claude/CLAUDE.md#governance-monitoring)
