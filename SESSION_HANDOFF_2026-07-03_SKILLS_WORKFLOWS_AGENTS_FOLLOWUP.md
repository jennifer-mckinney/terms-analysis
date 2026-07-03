# Session Handoff — Skills / Workflows / Agents Follow-Up

**Date:** 2026-07-03
**Prior sessions:** Issue #19 redesign + tech-spec audit remediation
**Branch/PR:** PR #35 merged into main (12 commits landed)
**Purpose:** Package the 2026-07-03 session's patterns as portable skills, agents, and workflows so every future project inherits them
**Author:** Claude (Opus 4.7 [1M])

---

## 1. Why this handoff exists

The 2026-07-03 tech-spec audit remediation session shipped a large infrastructure layer:

- **LIB-PRINCIPLES P1-P9** (codified governance including agent-orchestration rules)
- **Test-automation scripts** (`scripts/testing/verify.sh` — 100x token reduction on Critic-agent pytest verification)
- **Governance content-hash monitoring** (`.claude/_governance-manifest.json` + verify/regen shell scripts)
- **`.gitignore` invariant governance layer** (pre-commit hook + CI workflow + `.claude/governance/required-gitignore.txt` SSoT)
- **Agent-optimized `.claude/` rewrite** (13 files, 155 grep-anchored rule IDs, backups preserved)
- **Session-start hook enhancements** (`~/.claude/hooks/session-start.py` now injects LIB-PRINCIPLES + PEAS + writes `session-start.log` JSONL)
- **P8 v2 DCD dispatch pattern** (Coder / Test Helper / Critic / Decision role separation with orchestrator visibility)
- **P9 pre-push review with security zero-tolerance** (mandatory security-engineer + grumpy-developer review before any push; security-engineer findings of ANY severity block)

Most of this lives inside terms-analysis. Turning it into portable skills and agent types multiplies the value: every future project (srs-ai-assist, claude-dashboard, my-skills, and new ones) gets P9 review + governance monitoring + cheap test verification for free.

This handoff catalogs what to build, prioritized, with prerequisites and a concrete next-session opener.

---

## 2. Skills to create

Invocable via `/skill-name`. Structure follows my-skills conventions (`SKILL.md` + `scripts/` + `references/` + `templates/`).

| # | Skill | Priority | What it does |
|---|---|---|---|
| 1 | `/dcd-dispatch` | **HIGH** | Takes a spec + task title, generates 4 role-scoped prompts (Coder / Test Helper / Critic / Decision) enforcing P8 v2. Includes PEAS accountability (single-line P, explicit E bounds). No per-prompt paperwork |
| 2 | `/pre-push-review` | **HIGH** | Runs P9 gate: `git diff base..HEAD`, dispatches security-engineer + grumpy-developer with prompts customized to the actual diff, applies zero-tolerance filter, returns APPROVE / BLOCK verdict |
| 3 | `/security-fix-loop` | **HIGH** | Orchestrates security-engineer → Fix-Coder → security-engineer round-N until zero findings. Codifies the round-1 → round-2 pattern the tech-spec-audit session ran manually |
| 4 | `/setup-verify-sh` | **HIGH** | Scaffolds `scripts/testing/verify.sh` + `tests-for.py` + `pytest-summary.py` for any pytest project. Auto-audits test suite, generates 10-15 scope groupings. The 100x-token-reduction pattern portable per project |
| 5 | `/setup-governance-manifest` | **HIGH** | Bootstraps `.claude/_governance-manifest.json` + `scripts/governance/verify-hashes.sh` + `regen-manifest.sh` + README. Discovers protected files by scanning for `.claude/CLAUDE.md`, `LIB-PRINCIPLES.md`, `PEAS.md` |
| 6 | `/setup-gitignore-invariant` | **HIGH** | Bootstraps `.githooks/pre-commit` + `.github/workflows/gitignore-enforcement.yml` + `.claude/governance/required-gitignore.txt` SSoT + `scripts/install-hooks.sh` |
| 7 | `/agent-optimize-claude` | **HIGH** | Rewrites `.claude/CLAUDE.md` + `LIB-*.md` + `rules/*.md` from prose narrative to grep-anchored rule IDs + `because:` one-liners + xref wikilinks. Preserves normative content. Backups to `_pre-agent-sweep-backup/` |
| 8 | `/decision-brief` | MED | For a set of open questions, generates a structured markdown brief with options + trade-offs + recommendation per the A1-A4 pattern used this session. Save to `docs/reports/user-decision-brief-YYYY-MM-DD.md` |
| 9 | `/session-close` | MED | End-of-session pattern: refresh handoff, generate retro from git log + task list, draft PR body if missing, save all under `docs/reports/` + `retros/` + `SESSION_HANDOFF_*.md` |
| 10 | `/adopt-p8-p9` | MED | For a new project without LIB-PRINCIPLES yet: copy the P1-P9 template, adjust anchors, install session-start hook injection, run manifest bootstrap. One-shot governance adoption |

---

## 3. Agents to create

Custom `subagent_type`s registered with the Agent tool.

| # | Agent | Priority | What it specializes in |
|---|---|---|---|
| 1 | `committer` | **HIGH** | Per-file `git add`, halt on `jennifermckinney` grep hit, HEREDOC message with Co-Authored-By trailer enforcement, no `-A` / `.` / `-u`, no push, no amend. Ran three times in prompt this session — encapsulate |
| 2 | `fix-coder` | **HIGH** | Coder specialization for resolving review findings. Structured intake: list of findings with file:line + fix spec. Outputs: per-finding resolution status + `verify.sh full` result. No test-writing beyond unit-level. No signoff |
| 3 | `push-pr-agent` | MED | Push + create/update draft PR with body from `docs/reports/pr-body-draft-*.md`. Auto-detects existing PRs, updates in place. Enforces `--draft` default. Returns URL + issue number |
| 4 | `manifest-regenerator` | MED | Runs `regen-manifest.sh --yes` + `verify-hashes.sh`. Commits governance file + manifest as one atomic change with a clear message. Used after any intentional governance-file edit |
| 5 | `retro-writer` | LOW | Populates `retros/YYYY-MM-DD-topic.md` from session artifacts (git log + task list + agent transcripts if available). What went well / didn't / start / stop / lessons |

---

## 4. Workflows to codify

Documentation + orchestration patterns (not skills, not agents — but reusable multi-step sequences).

| # | Workflow | Priority | Where it lives |
|---|---|---|---|
| 1 | **P9 pre-push gate as git hook** | **HIGH** | `.githooks/pre-push` script that refuses push until a signed reviewer-log exists at `docs/reviews/<HEAD-sha>.md`. Combined with `/pre-push-review` skill, makes P9 structurally enforced not prompt-enforced |
| 2 | **Parallel-Doer domain boundary rule** | **HIGH** | Codify in P8 v2 or new LIB-DISPATCH.md: when dispatching parallel Doers, enumerate file-level ownership in every prompt. This session's OE-003 + Code-Drift collision at `schemas.py` was the trigger |
| 3 | **DCD retrofit for legacy work** | MED | Docs pattern: for prior single-agent-signoff work, dispatch independent Test Helper + Critic post-hoc as verification. Not blocking, but changes historical work from "trust me" to "verified" |
| 4 | **Zero-tolerance security fix loop** | **HIGH** | Documented in `docs/workflows/security-fix-loop.md`: security-engineer → orchestrator triage → Fix-Coder single-ask → re-verify → commit chunk. Iterate until clean. This session did it once; codify |
| 5 | **Commit-chunking discipline** | MED | Docs pattern: for multi-concern work, split into semantic commits per grumpy F6 lesson (mega-commit `59759fb` was the anti-pattern). Rule of thumb: one commit per PRD/BRD section that changed |

---

## 5. What NOT to build

- **`/dispatch-agent` prompt helper** — orchestrator handles this per P8. Skill would duplicate.
- **`/scrub-personal-paths`** — one-off grep, adds noise. Existing pre-commit gate is enough.
- **Skill-per-audit-finding-type** — audit findings are too varied; general `/security-fix-loop` covers.
- **New security-review agent variant** — existing `security-engineer` + `grumpy-developer` are sufficient with custom prompts. Do not fork.
- **Global agent-optimized sweep of `~/.claude/CLAUDE.md`** — that file is user's cross-project instructions; user preference is currently mixed prose. Wait for explicit request.

---

## 6. Recommended dispatch order

1. **First:** #1 `/dcd-dispatch` + #2 `/pre-push-review` — foundation for every future multi-agent session
2. **Then:** #4 `/setup-verify-sh` + #5 `/setup-governance-manifest` + #6 `/setup-gitignore-invariant` — portable per-project bootstraps
3. **Then:** `committer` + `fix-coder` agent types — high-frequency reusable roles
4. **Finally:** #7 `/agent-optimize-claude` + #10 `/adopt-p8-p9` — for propagating this session's governance shape to other projects (srs-ai-assist, claude-dashboard, my-skills)

---

## 7. Prerequisites and dependencies

### For skills:
- **my-skills conventions** — reference the existing skills at `~/Documents/05_Technical_Development/01_AUTOMATION/01_Claude_Projects/my-skills/` for the `SKILL.md + scripts/ + references/ + templates/` structure
- **Skill loading** — skills are auto-discovered via `~/.claude/skills/` and per-project `.claude/skills/`. Global skills should probably live in a dedicated `~/.claude/skills/governance/` folder to group P8/P9-related tooling
- **Skill invocation** — user types `/skill-name` OR the model uses the Skill tool. Documented in each SKILL.md

### For custom agents:
- **Agent SDK** — custom `subagent_type` definitions require the Agent SDK. There is a plugin `agent-sdk-dev` visible in the session's available agent list, with `agent-sdk-verifier-py` and `agent-sdk-verifier-ts`. Use those for validation
- **Registration** — new agent types register via project or global config. See existing custom agents (`claude-code-guide`, `bug-reproducer`, `frontend-qa`) for the pattern
- **Testing** — each new agent needs its own smoke test (dispatch it against a synthetic input, confirm output shape)

### For workflows:
- **Git hooks** — the P9 pre-push hook can reuse the `.githooks/` + `scripts/install-hooks.sh` pattern already shipped this session
- **CI** — the P9 CI enforcement can reuse the `.github/workflows/gitignore-enforcement.yml` shape

### Reference material shipped this session (read first):
- `.claude/library/LIB-PRINCIPLES.md` — P1-P9 authoritative
- `~/.claude/CLAUDE.md` § "Session Start Governance Chain" — hook load order + telemetry
- `docs/testing-automation.md` — verify.sh scope model
- `scripts/governance/README.md` — hash-manifest rationale
- `scripts/testing/README.md` — invocation examples
- `~/.claude/library/PEAS.md` — the framework P8 references

---

## 8. Where to start the next session

Concrete first steps for a fresh Claude session picking this up:

1. Read `.claude/library/LIB-PRINCIPLES.md` for the P8/P9 authoritative form
2. Read `~/.claude/CLAUDE.md` § "Session Start Governance Chain" for the injection contract
3. Read this handoff (section 2, table row 1)
4. Pick **skill #1 `/dcd-dispatch`** as the first build — highest leverage; every future skill and agent depends on it as the underlying pattern
5. Follow the my-skills structure: `SKILL.md` + `scripts/dcd-generate.py` + `templates/coder-prompt.txt` + `templates/test-helper-prompt.txt` + `templates/critic-prompt.txt` + `~/.claude/library/PEAS.md` (global, not project-local)
6. Smoke test: run `/dcd-dispatch` against a synthetic small task (e.g., "fix a typo in a config file"). Confirm all 4 prompts generate cleanly
7. Commit as its own PR against my-skills; do NOT batch with other new skills

---

## 9. Key file map (fast reference)

```
LIB-PRINCIPLES:       .claude/library/LIB-PRINCIPLES.md
Governance manifest:  .claude/_governance-manifest.json
Governance SSoT:      .claude/governance/required-gitignore.txt
Session-start hook:   ~/.claude/hooks/session-start.py
Injection verifier:   ~/.claude/scripts/verify-injection.sh
Hash verifier:        scripts/governance/verify-hashes.sh
Hash regenerator:     scripts/governance/regen-manifest.sh
Test scoped runner:   scripts/testing/verify.sh
File→tests mapper:    scripts/testing/tests-for.py
Test summarizer:      scripts/testing/pytest-summary.py
Testing docs:         docs/testing-automation.md
Governance docs:      scripts/governance/README.md, docs/DEV_SETUP.md
PR body draft:        docs/reports/pr-body-draft-2026-07-03.md
Decision brief:       docs/reports/user-decision-brief-2026-07-03.md
Retro:                retros/2026-07-03-tech-spec-audit-remediation.md
Prior handoffs:       SESSION_HANDOFF_2026-07-03_ISSUE_19_REDESIGN.md
                      SESSION_HANDOFF_2026-07-03_TECH_SPEC_AUDIT_REMEDIATION.md
```

> Note: handoffs are gitignored per PR #80 (commit 721150f). Two prior handoffs remain in git history from before the ignore — retrieve via 'git show <sha>:<file>'.

---

## 10. GitHub state at handoff time

- **PR #35** merged into main (12 commits): tech-spec audit remediation + governance layer + agent-optimized `.claude/`
- **Follow-up issues on repo** (labeled `audit-2026-07-03`):
  - #36-#76 — 41 audit backlog items (GAPs, OEs, BLs, LEs, GOVs)
  - #77 — Alembic migration setup for public-repo readiness
  - #78 — `.env` case-insensitive guard is ASCII-only (grumpy N1)
  - #79 — `_vendor_from_url` alias caller verification (grumpy N2)

None of the follow-up issues block the skills/agents work catalogued here. They are terms-analysis feature backlog, orthogonal.

---

## 11. Do-not-do list carried forward

- Do NOT fork existing `security-engineer` or `grumpy-developer` agent types. Custom prompts are the extension mechanism.
- Do NOT bundle multiple skills into one PR against my-skills. One skill per PR per grumpy F6 lesson.
- Do NOT skip the smoke test on any new skill or agent type.
- Do NOT introduce em-dashes in tool-voice copy (LIB-VOICE). Skill descriptions, agent prompts, and any user-visible strings must comply.
- Do NOT commit a governance-manifest.json without a corresponding intentional edit to a tracked file. Silent regen is exactly the drift the manifest protects against.

---

## 12. One-line summary

Session shipped LIB-PRINCIPLES P1-P9 + verify.sh + governance layer + agent-optimized `.claude/`; next session should package these as 10 skills + 5 agents + 5 workflows so every future project inherits them. Start with `/dcd-dispatch` skill against my-skills.
