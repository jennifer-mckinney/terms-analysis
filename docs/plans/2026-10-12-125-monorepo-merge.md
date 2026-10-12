# #125 (GM-2) monorepo merge: plan

Status: PLAN ONLY (owner ruling 2026-10-12: "merge the ingester"). No implementation in this document.
Author lens: principal engineer (architecture / scale / ops).
Anchors: plan §Gate M steps 1-2 and target layout; D9 (3 packages under `packages/`); D10 consequence "Monorepo (Gate M)" (Railway root directory); LIB-PRINCIPLES `## project-process` G2, G3, G4, G9, G10, G11, M2; card #125 test spec; card #123.
Not re-litigated: D9 layout, the merge-not-squash rule, P9-in-CI.

Facts below were read on 2026-10-12 (UTC) with read-only `git` / `gh`. Anything not verified is marked **OPEN:**.

---

## 0. Recommendation in one paragraph

Import the ingester as **its own line of history**: on a detached copy of the ingester main tip, make one commit that does nothing but `git mv` every top-level entry into `packages/ingester/` (100% renames), then merge that commit into a TA feature branch with `git merge --no-ff --allow-unrelated-histories`. Prove the import with a **tree-hash identity check** (the relocated subtree's tree hash equals the ingester tip's root tree hash), not with an LLM review. Ship it as **3 PRs**: (1) history import, frozen and byte-identical; (2) ingester CI, schedules and per-package governance wired at the repo root; (3) the app move (`src/backend` → `packages/app/backend`, `src/webapp` → `packages/app/webapp`) as a pure-rename commit plus a separate reference-fix commit. Before PR 1 opens, the owner has to turn off squash and rebase merging in TA. Today both are enabled, and one squash click would destroy the import, which can't be undone without a force-push.

---

## 1. Prerequisites

### 1.1 #123 (GM-1): what's left, and whether it needs its own PR

The substantive work is already done:
- The stale worktree (`agent-a62df1bc365d70999`, branch `worktree-agent-a62df1bc365d70999` at `950b56b`) was **discarded with owner authorisation on 2026-10-10**. The salvage record is the untracked TA evidence file `docs/evidence/2026-10-10-ingester-worktree-salvage.md`: the work is superseded by ingester `b1bc7fe`, the real base was `950b56b`, and it carried 0 unpushed commits. `.claude/worktrees/` in the ingester checkout is now empty.
- Ingester **PR #74 merged 2026-10-11** ("guard agent worktree roots in CI (terms-analysis#123)"). It adds `scripts/governance/check-no-stale-worktrees.sh`, `.claude/governance/worktree-roots.txt` (`.claude/worktrees/`), the tracked `.gitignore` rule `/.claude/worktrees/`, a CI step "Worktree hygiene", and `tests/unit/test_check_no_stale_worktrees.py`.

What #123 still needs (**no new PR**):
1. A close-out comment carrying the CI run that shows "Worktree hygiene" green on the ingester tip, plus the salvage record's disposition (as text, because the evidence file is untracked). Then close the card.
2. A record that the card's test spec was deliberately superseded. `git worktree list | wc -l == 1` can't hold under the owner's "worktrees stay" ruling, since the shared ingester `.git` has 15 per-lane worktrees. The shipped check is root-based ("ignored by a tracked file, nothing tracked under it"). Put this in the close-out comment.
3. Follow-up, not blocking: "tracked-path count isn't pinned by any test (3 surviving mutants)" (SESSION_HANDOFF 2026-10-11-LATE item 6). Card it as P3 in the ingester; after the merge it moves with the package.

The local ingester main checkout sits at `e184b8a`, 108 commits behind its remote. That's where the card's stale SHA came from. **The import must use the remote tip fetched by URL and must never use the local checkout.**

### 1.2 Ingester main tip

- `git ls-remote https://github.com/jennifer-mckinney/legal-corpus-ingester main` → **`9ad4d0cccdb3e2a6583a1df82b3215697d89dc91`** ("Merge pull request #80 from jennifer-mckinney/fix/17-health-check-parity", 2026-10-11T04:23:53Z).
- This tip contains the G0 fixes (#17 checkpoint/health parity, #81 OAuth reviews, #74 worktree hygiene, #69 Python pin, ADR-016 hosted runners).
- `e184b8a` in the card is stale (pre-G0). Replace it in the card body with `9ad4d0c…`.
- 182 commits (counted at `ad96cf5`, the tip before #80), 197 tree entries, 180 text files, about 25.5k text lines.
- **Freeze:** from the moment PR 1 opens until PR 2 merges, nothing merges to ingester main. If something must land anyway, re-pin the tip and redo the relocation commit (see §2.4).

### 1.3 Open PRs that must land or close first

| Repo | PR | State | Disposition |
|---|---|---|---|
| TA | #348 `fix/36-export-json` | open, ready for review; CI green, awaiting owner merge | Land or close **before PR 3** (it touches the backend that PR 3 moves). If it is still open when PR 3 merges, merge main into it; git's rename detection carries its edits to `packages/app/...`. Expect one more CI + P9 round. It doesn't block PR 1 or PR 2. |
| Ingester | none | — | Freeze from PR 1 onward (§1.2). |

Also blocking per the card: **#90 and #92**. Both are CLOSED (verified 2026-10-12).

Also relevant: #161 chose 4-digit ADRs 0003-0006, pushed on branch `docs/161-327-adrs` as draft PR #349. See §4.6.

---

## 2. Method choice

### 2.1 Options

| | A. `git subtree add --prefix packages/ingester <url> <tip>` | B. Relocation commit + `git merge --allow-unrelated-histories` (recommended) |
|---|---|---|
| Mechanics | One merge commit whose 2nd parent is the ingester tip with **root-level** paths; the prefix is applied only inside the merge's tree | On a detached ingester tip: one commit, `git mv` everything into `packages/ingester/` (R100 renames only). Then `git merge --no-ff --allow-unrelated-histories <reloc>` on the TA branch |
| Merge commits only / no rebase / no force-push / no squash | Compliant | Compliant |
| "Require up to date" (strict) | Merge main into the branch as usual; no conflict, because main never touches `packages/` | Same |
| Conflicts | None (prefix) | None (everything already under `packages/`; `packages/` doesn't exist in TA) |
| `git log --follow packages/ingester/<f>` | **Stops at the subtree merge**: the 2nd parent has the file at root and no commit records a rename. You need `git log -- <old root path>` or `git subtree split` to see history | **Follows through**: the relocation commit is a real R100 rename on the ingester line, so `--follow` crosses it |
| Tooling | `git subtree` is a contrib script and may not be installed on every runner or agent machine | Core git only |
| Re-sync if the ingester moves after import | Easy (`git subtree pull`) | Redo the relocation on the new tip and merge again (each re-sync is another R100 commit). The freeze makes this moot |
| Deterministic proof of fidelity | `HEAD:packages/ingester` tree == tip tree, true only until the first edit | `<reloc>:packages/ingester` tree == `<tip>^{tree}`, permanently true, because the reloc commit is immutable |

### 2.2 Recommendation: B

B gives `--follow` fidelity on both sides (the card's intent: "so `git log --follow` still works"), needs only core git, and leaves an immutable commit that the layout check can verify forever. A's only advantage, cheap re-sync, is cancelled by the freeze.

### 2.3 The app move (`src/backend` → `packages/app/backend`)

- Do it in TA's first-parent line as **a commit that only runs `git mv`** (no content edits, so every file is R100). Follow it with **a separate commit** that fixes the references. Rename detection, and with it `--follow`, depends on similarity; mixing edits into the rename commit erodes it.
- Proposed target paths (**OPEN, owner/lead confirm**): `src/backend/` → `packages/app/backend/` (the `app` Python package keeps its name, so `--cov=app` and every `from app...` import are unchanged), `src/webapp/` → `packages/app/webapp/`, root `tests/` → `packages/app/tests/`. `src/demos/` is undecided (**OPEN:** move to `packages/app/demos/` or `archive/`).
- Card check: `git log --follow` on `packages/app/backend/app/main.py` must list every commit that `git log 8797180 -- src/backend/app/main.py` lists (`--follow` shows 23 commits on main today).

### 2.4 Exact sequence for PR 1 (for the committer brief)

1. Cut `chore/125-import-ingester` on GitHub from TA main and fetch it into a fresh worktree `../ta-125` (G2).
2. **test-author red commit:** `scripts/governance/check-monorepo-layout.sh` plus its config `.claude/governance/monorepo-layout.conf` (pinned values: ingester remote URL, `INGESTER_TIP=9ad4d0cc…`, `APP_ANCHOR=8797180`; no hard-coded values in the script, per F13), plus pytest coverage for the script under the existing governance-test location. Stages: `--stage import|ci|app`. Red log goes to `docs/evidence/` (leak-scanned).
3. `git fetch https://github.com/jennifer-mckinney/legal-corpus-ingester main`; assert `FETCH_HEAD` == `INGESTER_TIP`, abort otherwise.
4. `git worktree add --detach ../ta-125-reloc FETCH_HEAD`. There: create `packages/ingester/`, `git mv` every top-level entry including dotfiles (`.claude .githooks .github .gitignore .python-version .dockerignore .env.example`) into it, commit `chore: relocate ingester tree under packages/ingester (#125)`. Verify that `git diff --name-status <tip> HEAD | grep -cv '^R100'` is `0`. Don't push this commit as its own branch: TA CI's push trigger (`feat/**`, `claude/**`) would run TA's jobs on an ingester-only tree.
5. Back in `../ta-125`: `git merge --no-ff --allow-unrelated-histories <reloc-sha> -m "Merge legal-corpus-ingester history into packages/ingester (#125)"`.
6. Run `check-monorepo-layout.sh --stage import` (green), push, open the PR. Do **not** edit anything under `packages/ingester/` in PR 1, because any edit breaks the identity proof.

---

## 3. PR slicing and review-diff size

### 3.1 Three PRs, strictly sequential

| PR | Branch | Content | Diff seen by p9-review |
|---|---|---|---|
| **1. Import** | `chore/125-import-ingester` | layout check (red → green, `--stage import`), relocation commit, unrelated-histories merge | ~197 added files, ~25.5k lines, ~183 commits in `commits.txt` |
| **2. Ingester CI + governance at root** | `chore/125-ingester-ci` | root workflows for the ingester (path-filtered), scheduled jobs ported, dead `packages/ingester/.github` removed, ingester workflow-contract tests repointed, companion checkout removed, tracked ingester evidence removed, hook decision, `.gitignore` rules, `--stage ci` | small to medium (YAML + tests) |
| **3. App move** | `refactor/125-app-move` | R100 rename commit + reference-fix commit (73 files reference `src/backend`/`src/webapp`; 14 of them executable/config, see §4.8), wiring-audit config, `--stage app` | renames show as `rename from/to` with no body; the reviewer sees only the reference fixes |

Don't fold PR 2 into PR 1. It would mix reviewable edits into the 25k-line import and break the identity proof. Don't fold PR 3 into PR 2. The app move has its own owner step (Railway) and its own blast radius.

### 3.2 Keeping the reviewer from choking on PR 1

- TA `p9-review.yml` builds `pr.diff` from `git diff origin/main...HEAD` and runs each reviewer with `--max-turns 40` and `timeout-minutes: 20`. PR 1's net diff is the whole ingester tree. Expect one of two outcomes: no verdict (turn or time cap, which `check_verdict.py` fails as "missing verdict"), or findings against pre-existing ingester code.
- **Don't build a bespoke skip** in `p9-review.yml` (G11: standard CI over custom machinery).
- Instead:
  1. PR 1's body states that the diff is byte-identical to ingester `9ad4d0c` and cites the `check-monorepo-layout.sh --stage import` output (tree-hash equality and an R100-only relocation). That deterministic proof is stronger than an LLM read for "is this the same code".
  2. Any P9 finding on PR 1 is pre-existing ingester code. Triage it as a card against `packages/ingester` (MEDIUM+ → `priority:P1/P2` card; LOW/NIT → `P3`), **never fixed inside PR 1**.
  3. If a review job is red only because of turn caps or pre-existing findings, the owner **waives P9 at merge time** (LIB-PRINCIPLES P9: "only the owner can waive, and does so at merge time"). `security-review`/`grumpy-review` aren't required checks in TA today, so the button isn't blocked, but G9 "ready" needs the owner's explicit waiver on record.
  4. Optional, owner's choice: one full-package review card for `packages/ingester` after PR 2. Its 40 founding tasks went to main without PRs (plan §Gate M "Accepted consequence").
- PR 2 and PR 3 diffs are normal size; P9 applies as usual, round cap 3.

### 3.3 Strict "require up to date"

Each slice merge sends every other open PR BEHIND. That's one extra CI + P9 round per open PR per slice. Keep the TA PR count near zero during the three-slice window. Today only #348 is open.

---

## 4. CI and governance moves

### 4.1 Workflows

GitHub runs workflows **only from the root `.github/workflows/`**. At PR 1 merge, `packages/ingester/.github/workflows/*` becomes dead config: the ingester code in TA has no CI until PR 2 merges. That's acceptable only because the ingester is frozen and its own repo's CI still runs on the frozen tip. Rule for the window: **no PR touching `packages/ingester/` merges between PR 1 and PR 2.**

Ingester workflows at the tip (all `ubuntu-latest`, per ADR-016):

| Ingester workflow | Trigger | Port to TA root as | Notes |
|---|---|---|---|
| `ci.yml` job `test` | PR (any branch), push main | jobs in TA `ci.yml` (e.g. `Ingester lint+type`, `Ingester test`) with `working-directory: packages/ingester` | **Path filtering:** don't use workflow-level `paths:`. A skipped workflow leaves a required check "Pending" forever and blocks merges (GitHub docs, "Handling skipped but required checks"). Use a `changes` job (core `git diff --name-only` against the PR base, no third-party action) and job-level `if:`. A job skipped via `if:` reports Success, so it can be required. App-only PRs then skip the ingester jobs (the plan's Gate M gate condition) |
| same: "Check out terms-analysis (companion…)" step | — | **delete** | `TERMS_ANALYSIS_ROOT` becomes the workspace root. PR 3 changes the schemas path the jurisdiction sync test reads (`packages/app/backend/app/schemas.py`) |
| same: `--cov-fail-under=0` | — | per-package floor (§4.4) | |
| `p9-review.yml` | PR to main | **delete**; TA's `p9-review.yml` covers the monorepo | the two `.github/p9/` brief sets diverge; merging the briefs is governance-collapse work (OPEN: which card) |
| `refresh.yml` | Sun 03:00 UTC, `issues: write` | TA root `ingester-refresh.yml` | issues now open in TA. Needs TA labels (§4.7). Ingester #71 (`actions/cache` refresh state + first-record seed) is **not implemented yet**. Implement it in the monorepo after PR 2, not in the old repo: Actions caches are repo-scoped and don't carry over, so state seeded in the old repo would be lost anyway |
| `health.yml` | daily 03:00 UTC | TA root `ingester-health.yml` | |
| `approval-expiry.yml` | daily 06:00 UTC, `issues: write` | TA root `ingester-approval-expiry.yml` | |
| `vcr-drift.yml` | Sun 04:00 UTC, `issues: write` | TA root `ingester-vcr-drift.yml` | |
| `.github/actionlint.yaml` | — | merge into one root config | TA has no actionlint step today; the ingester CI installs and verifies it. Keep that step in the ingester job and point it at the root workflows |

**Double-run hazard:** once PR 2 merges, the same schedules exist in both repos. Disable the four scheduled workflows in the ingester repo **at PR 2 merge** (§5, owner step), or they open duplicate issues in two repos.

**Silent-success hazard (top risk):** ingester tests that read their own workflow files (`tests/unit/test_p9_review_workflow.py`, `test_vcr_canary_contract.py`, `test_python_version_pin.py`, `test_check_no_stale_worktrees.py`, and probably more) would keep passing against the dead copies under `packages/ingester/.github/` while asserting nothing about what actually runs. PR 2 must **delete `packages/ingester/.github/`** and repoint every such test at the root workflow. `--stage ci` asserts `test ! -e packages/ingester/.github/workflows`.

### 4.2 ADR-016 and Python

ADR-016 (GitHub-hosted runners) holds unchanged: TA already runs everything on `ubuntu-latest`. Both repos pin Python `3.14`. Keep the single root `.python-version` and make the ported jobs use `python-version-file: .python-version` from the root. Then either delete `packages/ingester/.python-version` or make `test_python_version_pin.py` assert equality with the root file. **OPEN:** which assertion that test makes today.

### 4.3 `.githooks`

`core.hooksPath=.githooks` allows one hooks directory per clone. TA's root `.githooks/pre-commit` (gitignore SSoT, graveyard, `.env` variants, evidence leak check 4) stays as is. The ingester's hook (ruff, mypy, unit pytest, license-hashes audit) becomes dead at `packages/ingester/.githooks/`.

Recommendation: **delete it in PR 2 and rely on CI** (G11). Lint, type and test already run in the ingester CI job. **OPEN:** confirm the license-hashes audit also runs in ingester CI; if it doesn't, port it as a CI step in PR 2 rather than into the root hook.

### 4.4 Coverage floor per package

- App: unchanged, `--cov=app --cov-fail-under=98 --cov-precision=2`, `working-directory` → `packages/app/backend` in PR 3.
- Ingester: today `--cov=src/legal_corpus_ingester --cov-fail-under=0`, which is effectively no floor. PR 2 measures once and sets the floor to the **measured value at precision 2** (a ratchet that never goes down), as a separate job and separate coverage artifact.
- **OPEN (owner):** the target. D3 says 99% for everything; raising it is a G3 card, not #125.

### 4.5 `.claude/governance`, manifests, verify-hashes (M2)

- TA manifest `.claude/_governance-manifest.json` tracks `.claude/CLAUDE.md`, `.claude/library/LIB-PRINCIPLES.md` and `.claude/governance/required-gitignore.txt`.
- The ingester manifest (now `packages/ingester/.claude/_governance-manifest.json`) tracks the ingester's `.claude/CLAUDE.md` and LIB-PRINCIPLES. Its `verify-hashes.sh` resolves paths from the git top level, which is now the TA root, so it would hash **TA's** files against the ingester's hashes. It's broken by construction after PR 1.
- **PR 2:** `git rm` the ingester manifest, `regen-manifest.sh`, `verify-hashes.sh` and `sync-lib-principles.sh` under `packages/ingester/scripts/governance/`. Nothing calls them from the root, so deleting them changes no enforcement. **OPEN:** confirm `sync-lib-principles.sh` deletion isn't owned by another GM card; if it is, leave it for that card.
- **PR 2 does not touch any file in TA's manifest.** Add `/.claude/worktrees/` and `/packages/*/.claude/worktrees/` to `.gitignore` only, not to `required-gitignore.txt`. Root `worktree-roots.txt` moves to `.claude/governance/` with the two roots, and the check script runs from the root in the ingester CI job.
- **Where owner intent is needed:** the one manifest regeneration happens in the **governance-collapse card** (plan §Gate M step 5: one `.claude/` tree, one manifest, one LIB-* set). That PR promotes the worktree rule into `required-gitignore.txt` and merges the LIB-PRINCIPLES sets. The owner states intent in that PR, and the `chore(governance): regen manifest` commit is the last commit before review. `regen-manifest.sh` prompts y/N interactively, so the owner either runs it or authorises it in writing on that PR. #125's three PRs **never** regenerate the manifest.

### 4.6 Collisions

| Collision | Fact | Handling in #125 | Later |
|---|---|---|---|
| ADR numbering | TA: `docs/adr/0001`, `0002` (4-digit). Ingester: `docs/adr/015-dependency-rules-scope-ci-review-tooling.md` (same subject as TA 0001), `016-github-hosted-runners.md`. TA card #161 "reserves 015-017", which collides with the ingester's 015/016. #161 chose 4-digit ADRs 0003-0006, pushed on branch `docs/161-327-adrs` as draft PR #349 | Leave the ingester ADRs in `packages/ingester/docs/adr/` untouched | Governance-collapse card: one `docs/adr/` index in 4-digit form; ingester 015 → "Superseded by 0001"; ingester 016 → next free 4-digit number with a `Formerly: ingester ADR-016` line so old citations resolve; #161's reservation re-issued as 4-digit numbers. |
| HR identifiers | ingester HR7 = MANIFEST pin / 503 `X-Corpus-Mismatch`; TA HR7 = HITL below 0.80 | Claude Code loads `packages/ingester/CLAUDE.md` (and probably `packages/ingester/.claude/CLAUDE.md`) when an agent reads files there, so both HR7s can be live in one session. Interim rule for briefs: cite `TA-HR7` / `ING-HR7`, never bare `HR7` | Plan §Gate M step 5 namespacing card (resolves R-7) |
| Labels | TA: `priority:P0-P3`, `P3`, `gate:*`, `layer:*`. Ingester: `P0-critical`, `P1-high`, `P2-medium`, `P3-low`, `technical-debt`, `ci-cd`, `cli`, `testing`, `corpus`, `approval-expiry`, `corpus-refresh`, `corpus-drift`, `needs-review` | PR 2 merge needs the workflow-applied labels in TA **before** the first scheduled run. **OPEN:** grep the four scheduled workflows for the exact label names | Issue migration (§6) maps `P*-<word>` → `priority:P*` |
| CLAUDE.md | ingester has root `CLAUDE.md` + `.claude/CLAUDE.md` + `PRINCIPLES.md` (constitutional: changing it needs an ADR) + 7 skills under `.claude/skills/` | `git mv` is a path change, not a content change, so no ADR. Content untouched in #125 | Collapse card |
| Tracked evidence | ingester tracks 8 files under `docs/evidence/`; TA's rule is "untracked, never commit" | PR 2 `git rm`s `packages/ingester/docs/evidence/` (history keeps them) and adds `/packages/*/docs/evidence/` to `.gitignore`. TA's scanner and pre-commit check 4 are anchored at root `docs/evidence/`, so either extend both to `packages/*/docs/evidence/` in PR 2 or rely on the `.gitignore` plus the `ls-files` assertion in `--stage ci`. Recommendation: assertion + ignore; extending the scanner is a new mechanism → card | |

### 4.7 Evidence-scan on the import range (top risk)

TA `ci.yml` job `Evidence leak scan (docs/evidence)` scans **every line added under `docs/evidence/` by each commit in `PR_BASE..PR_HEAD`**. PR 1's range includes all ~182 ingester commits, and in those commits the ingester evidence sits at root `docs/evidence/`. So TA's leak regex will scan the ingester's whole evidence history, and agent logs leaked home paths twice in the past. Ingester history can't be rewritten (no force-push; history must be preserved).

**Pre-flight, read-only, before PR 1 opens:** run TA's `scripts/governance/scan-evidence-leaks.sh --range <ingester-root-commit>..9ad4d0c` against a clone of the ingester. If it hits, the owner decides before PR 1. The history is already public in the ingester repo, so importing it isn't new exposure, and `Evidence leak scan` isn't a required check. The alternative is a waiver at merge. **OPEN:** result of the pre-flight scan.

Also pre-flight the `gitignore-enforcement.yml` assertions (graveyard patterns, case-insensitive `.env` variants) against the merged tree. The ingester has `.env.example`, `state/`, `models/`, `Dockerfile`. **OPEN:** result.

### 4.8 Path references broken by PR 3 (must all land in PR 3's reference-fix commit)

These are the executable and config ones; 73 files mention `src/backend`/`src/webapp` in total, and the docs ones can be swept by a docs card.
- `.github/workflows/ci.yml`: `ruff check src/backend/app`, `-r src/backend/requirements.txt`, `-r src/webapp/requirements.txt`, `working-directory: src/backend`, `pip-audit -r src/backend/requirements.txt`
- `ruff.toml` `src = ["src/backend"]`; `run.sh` `APP_DIR`/`BACKEND_DIR`
- **`scripts/audit/config.json`**: `module_globs` start with `src/**/*.py`, and `exclude_globs` name `src/backend/tests/test_leak_scan_vectors.py` and `test_precommit_evidence_guard.py`. If these aren't updated, the weekly wiring audit **silently stops auditing the app** (it can't tell "nothing to do" from "not wired") and would **send the leak-vector test fixtures** it currently excludes. Adding `packages/**` also pulls the ingester into an audit scoped by ADR 0002. **OPEN (owner):** is the ingester inside ADR 0002's allowlist? Last run: 100 requests, worst case $1.73 of a $3 ceiling; doubling the module count would breach the ceiling, and budget-before-submission then fails loudly. Owner: raise the ceiling, or keep the audit app-only.
- `scripts/governance/leak_scan.py`, `.claude/governance/*` comments, `scripts/testing/*`, `.claude/skills/*`, `.claude/library/*`, `.claude/CLAUDE.md` project-map and commands. Changing `.claude/CLAUDE.md` changes a manifest-tracked file, so either defer those edits to the collapse card or include the owner-intended regen there. **Recommended: defer.** PR 3 must not touch `.claude/CLAUDE.md`, and a lead note covers the stale paths until then.
- `--stage app` gate: `git grep -n -E 'src/(backend|webapp)' -- .github scripts ruff.toml run.sh packages` returns nothing.
- Ingester jurisdiction sync test → `packages/app/backend/app/schemas.py`.

---

## 5. Per-repo secrets and settings (owner-only)

Agents never list, read or set secrets (`gh secret list` is denied here). Secret names below come from the workflow files only.

| Item | TA today | Ingester today | Owner action |
|---|---|---|---|
| Merge methods | merge commit, **squash and rebase also allowed** | same | **Before PR 1: disable "Allow squash merging" and "Allow rebase merging" in TA** (Settings → General). Otherwise merge PR 1 strictly with "Create a merge commit" |
| `CLAUDE_CODE_OAUTH_TOKEN` | used by `p9-review.yml` | used by `p9-review.yml` | none (TA already has it) |
| `PROJECT_TOKEN` | `board-sync.yml` | — | none |
| `WIRING_AUDIT_API_KEY` (env `wiring-audit`) | yes | — | none (ceiling decision in §4.8) |
| Secrets used by ingester scheduled workflows | — | none referenced in `refresh`/`health`/`approval-expiry`/`vcr-drift` (they use `GITHUB_TOKEN` with `issues: write`) | **OPEN (owner):** confirm in the ingester's Settings → Secrets that nothing exists beyond `CLAUDE_CODE_OAUTH_TOKEN`; recreate anything else in TA by hand |
| Environments | `copilot`, `Preview`, `Production`, `wiring-audit` | `copilot` | none expected. **OPEN:** whether `Preview`/`Production` (Railway, #133 deploy env) reference `src/` paths or a root directory |
| Branch protection `main` | strict; required `Lint (ruff)`, `Test (pytest + coverage)`, `Dependency audit (pip-audit)`; conversation resolution; enforce admins; PR required (0 approvals) | strict; required `test`, `grumpy-review`, `security-review`; admins not enforced | **After PR 2:** add the new ingester job contexts (exact names fixed in PR 2) to TA's required checks. Required P9 contexts are the owner's open decision; the ingester already requires them |
| Railway | builds the frontend | — | **At PR 3 merge:** set the Railway service root directory / start command to the new app path (D10 says root `packages/app`). **OPEN:** current Railway root dir and start command (dashboard only) |
| Ingester scheduled workflows | — | 4 schedules | **At PR 2 merge:** disable `refresh`, `health`, `approval-expiry`, `vcr-drift` in the ingester repo (owner, or the lead with owner approval) |
| Copilot code review / rulesets | none | none | **OPEN:** whether per-repo Copilot review settings need mirroring |
| Project board | "Terms (Backlog)" | **OPEN:** whether ingester issues are on a board | after issue transfer, check board membership |

---

## 6. The old ingester repo after the merge

- **Don't archive early.** Keep it live but frozen through PR 3 plus a soak of one full weekly schedule cycle (Sun refresh + vcr-drift, daily health + approval-expiry) running green **in TA**. Until then the old repo is the rollback.
- **Issue migration (69 open issues, 0 open PRs):** use `gh issue transfer <n> jennifer-mckinney/terms-analysis` per issue. It keeps comments and leaves a redirect at the old URL. Before transferring, create the mapped labels in TA. GitHub may not carry labels and milestones that don't exist in the target (**OPEN:** confirm the exact transfer semantics from GitHub docs before the run). Write an old→new number mapping table to an evidence file, because issue numbers change (ingester #71 → a new TA number), and update cards that cite ingester numbers. This is a GitHub write: owner approval, then a PM run, then `gh issue list` verification (memory: the PM agent drops labels).
- **Archive = owner action**, only after the transfer. An archived repo is read-only and its issues can't be transferred out. Archiving also stops its scheduled workflows. **Deleting the repo is a hard stop and isn't part of this plan.**
- Update the ingester README (last commit before archive, by PR in the old repo) to point to `packages/ingester/` in TA.

---

## 7. Risks and rollback

| # | Risk | Likelihood / impact | Mitigation | Rollback |
|---|---|---|---|---|
| R1 | **Squash or rebase merge of PR 1** flattens 182 commits into one; history lost from main | squash is enabled today / irreversible without force-push | owner disables squash+rebase first; `--stage import` checks that the merge on main has 2 parents (`git rev-list --parents -n1`) | none clean: revert the squash commit and redo PR 1; the squash commit stays in history forever |
| R2 | **Silent path breakage** at PR 3: wiring audit scope dropped, Railway build broken, `run.sh`/ruff/CI paths stale, ingester tests passing against dead workflow copies (PR 2) | high / silent | `git grep` gate in `--stage app`; delete `packages/ingester/.github` in PR 2; wiring-audit config in the same PR as the move; Railway step at merge time | `git revert -m 1 <PR3 merge>`; open PRs that were merged forward need main merged in again |
| R3 | **Import CI blockers:** evidence-scan range hits in ingester history; P9 reviewer cap / no verdict on a 25k-line diff | medium / blocks PR 1 | pre-flight scan; tree-hash proof; owner P9 waiver at merge | not merged = nothing to roll back |
| R4 | Ingester goes CI-dark between PR 1 and PR 2, or schedules double-run after PR 2 | certain if unmanaged / medium | freeze + "no `packages/ingester` PRs before PR 2"; disable old schedules at PR 2 merge | re-enable old repo schedules |
| R5 | Required check hangs Pending (workflow-level `paths:`) and blocks all merges | medium / high | job-level `if:` with a `changes` job; never `paths:` on a workflow that holds required checks | edit the required-checks list (owner) |
| R6 | Refresh state lost (Actions cache is repo-scoped) | certain / low today (#71 not implemented) | implement #71 in the monorepo after PR 2, including the first-record seed | n/a |
| R7 | Reverting PR 1 then re-importing: git treats the reverted merge's commits as already merged | low / confusing | if PR 1 is reverted, a re-import must revert the revert, not re-merge | documented here |

Point of no return: issue transfer + archive (§6). Everything before that is reversible with `git revert -m 1` plus keeping the old repo live.

---

## 8. Deterministic acceptance check list (card test spec, updated)

Implemented by `scripts/governance/check-monorepo-layout.sh --stage <s>` with pinned values in `.claude/governance/monorepo-layout.conf`. Every check exits 0 on pass. Red is recorded before the implementation commit of each PR.

Stage `import` (PR 1):
1. `git merge-base --is-ancestor 9ad4d0cccdb3e2a6583a1df82b3215697d89dc91 HEAD` → 0 (ingester history is an ancestor, not squashed).
2. `git merge-base --is-ancestor 8797180 HEAD` → 0. Note: already true on main today, so this check is **non-discriminating**; check 3 is the discriminating one.
3. `git rev-list --max-parents=0 HEAD` includes the ingester root commit (**OPEN:** pin its SHA in the conf) as well as TA's root(s).
4. Let `R = git rev-list --ancestry-path --reverse 9ad4d0c..HEAD | head -1` (the relocation commit). Then `git rev-parse R:packages/ingester` == `git rev-parse 9ad4d0c^{tree}`, and `git diff --name-status 9ad4d0c R | grep -cv '^R100'` == 0.
5. `test -f packages/ingester/pyproject.toml`.
6. `git log --follow --format=%H -- packages/ingester/pyproject.toml` ⊇ `git log --format=%H 9ad4d0c -- pyproject.toml` (checked with `comm -13` = empty).
7. On main after merge: the merge commit has 2 parents (squash guard, R1).

Stage `ci` (PR 2):
8. `test ! -e packages/ingester/.github/workflows`, and no ingester test opens a path under `packages/ingester/.github` (`git grep` empty).
9. `git ls-files packages/ingester/docs/evidence | wc -l` == 0; `git check-ignore -q .claude/worktrees/x` and `git check-ignore -q packages/ingester/.claude/worktrees/x` → 0.
10. Root `ci.yml` has no workflow-level `paths:`; the ingester jobs carry `if: needs.changes.outputs.ingester == 'true'`.
11. Evidence (CI, not script): on PR 2 itself the ingester jobs run green; on one app-only PR afterwards they show `skipped` (`gh run view --json jobs`). That's the Gate M gate condition.
12. Ingester suite passes from its new path: `cd packages/ingester && pytest tests/unit tests/snapshot tests/cli tests/integration tests/e2e`, with the coverage floor set (§4.4).

Stage `app` (PR 3):
13. `test -f packages/app/backend/app/main.py && test ! -d src/backend && test ! -d src/webapp`.
14. `git log --follow --format=%H -- packages/app/backend/app/main.py` ⊇ `git log --format=%H 8797180 -- src/backend/app/main.py` (pre-move history visible).
15. The rename commit is R100-only: `git diff --name-status <rename>^ <rename> | grep -cv '^R100'` == 0.
16. `git grep -n -E 'src/(backend|webapp)' -- .github scripts ruff.toml run.sh packages` is empty, and `scripts/audit/config.json` has no `src/backend` string and covers `packages/app/**`.
17. App suite passes from its new path: `cd packages/app/backend && python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=98 --cov-precision=2 -v` (the CI line, with only the working directory changed).

Card acceptance (unchanged): red before, green after, grumpy PASS + security PASS (or the owner's recorded waiver on PR 1), proof comment on #125.

---

## 9. Card dependency updates

- **#125 card body:** replace `e184b8a` with `9ad4d0cccdb3e2a6583a1df82b3215697d89dc91`; add "method B, 3 PRs, see `docs/plans/2026-10-12-125-monorepo-merge.md`"; mark the `8797180` ancestor check as non-discriminating and add checks 3, 4 and 7.
- **#123:** close-out comment and close (§1.1). Its `blocks: #125` link is then satisfied.
- **#90, #92** (blocked-by on #125): both CLOSED (verified 2026-10-12).
- **#125 blocks #130 #134 #136 #138 #142 #160.** After PR 3 merges and #125 closes, for each one: remove `#125` from "blocked by"; change `repo:` to `terms-analysis (monorepo)`; rewrite any ingester-relative path to `packages/ingester/...` and any `src/backend/...` path to `packages/app/backend/...`; re-check `parallel-ok` (several will touch the same governance files and can't run in parallel). **OPEN:** the mapping of these six cards to plan §Gate M steps 3-6 (corpus-contract extraction, path-filtered CI, HR namespacing/`.claude` collapse, real e2e round-trip) wasn't read. If one of them owns "path-filtered CI", PR 2's `changes`-job work moves into that card, and #125 PR 2 keeps only the minimum needed to make the ingester suite run at all.
- **New cards to file (PM, then verify with `gh issue list`):** ingester #123 surviving-mutant pin (P3); license-hashes audit to CI if missing; extend the evidence scanner to `packages/*/docs/evidence/` (new mechanism); full-package P9 review of `packages/ingester` (owner choice); ingester #71 re-homed to the monorepo.

---

## OPEN items (consolidated)

1. Resolved: #90 and #92 are CLOSED (verified 2026-10-12).
2. Ingester root commit SHA (pin in conf for check 3).
3. Pre-flight result: TA evidence-scan `--range` over ingester history.
4. Pre-flight result: `gitignore-enforcement` assertions against the merged tree.
5. Final app target paths, and where `src/demos/` goes.
6. `test_python_version_pin.py` assertion target; full list of ingester tests that read `.github/`.
7. Whether the license-hashes audit runs in ingester CI or only in its pre-commit hook.
8. Exact labels applied by the four ingester scheduled workflows.
9. Ingester secrets beyond `CLAUDE_CODE_OAUTH_TOKEN` (owner checks in Settings).
10. Railway current root directory / start command; whether `Preview`/`Production` envs encode paths.
11. ADR 0002 scope: does the wiring audit cover `packages/ingester`, and at what budget ceiling (owner).
12. Ingester coverage-floor target (owner; D3 says 99).
13. Resolved: #161 chose 4-digit ADRs 0003-0006 (draft PR #349).
14. Mapping of #130 #134 #136 #138 #142 #160 to Gate M steps 3-6, and which card owns path-filtered CI and `sync-lib-principles.sh` deletion.
15. GitHub issue-transfer semantics for labels/milestones; ingester board membership.
16. Copilot review settings per repo.
