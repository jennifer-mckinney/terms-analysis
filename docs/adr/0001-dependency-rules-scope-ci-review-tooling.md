# ADR 0001: Hard requirements HR1-HR4 and HR6 cover the product, not CI review tooling

- **Status:** Accepted
- **Date:** 2026-10-09
- **Decided by:** owner, 2026-10-09
- **Approved-by:** @jennifer-mckinney, 2026-10-09
- **Governs:** `.claude/CLAUDE.md` hard requirements HR1 (open source only), HR2 (no investor-lawsuit vendors), HR3 (IRP Grade A or higher), HR4 (local-only data, no external API calls) and HR6 (no OpenAI, local-only LLM inference), plus their restatements in `.claude/library/LIB-PRINCIPLES.md` P5 and `.claude/library/LIB-STACK.md` S1
- **Companion:** legal-corpus-ingester ADR-015 records the same decision for that repo's constraints C3 and C7

## Context

Card #191 replaces the local P9 pre-push gate with two CI review jobs, `security-review` and `grumpy-review`, in `.github/workflows/p9-review.yml`. Each job runs `anthropics/claude-code-action` against the Claude API to review the pull request diff.

Read literally, HR1-HR4 and HR6 would bar that: the action and the API are a dependency from a VC-funded LLM vendor, with no IRP grade-A audit and no LIB-STACK listing; HR4 says no external API calls, and the review sends the PR diff to the Claude API; and HR6 says LLM inference is local-only. The same objection was raised by GitHub Copilot on the ingester's matching workflow.

These rules were written to protect the product: what the backend and Streamlit UI install and run, what reads or analyses user documents, and what builds or serves the legal knowledge base. They did not say whether they also cover tools that only review source code during development.

## Decision

HR1, HR2, HR3, HR4 and HR6 apply to the product's runtime and data path. For HR4 that means user documents, analysis results and legal-KB data never leave the machine that runs the product; it does not cover repository source code sent for review. That means every model, library and service that is installed by `requirements.txt`, `src/backend/requirements.txt` or `src/webapp/requirements.txt`, that processes or analyses user documents, or that builds, embeds, indexes or serves the legal knowledge base.

Development-time CI review tooling is exempt. This covers `anthropics/claude-code-action` and the Claude API calls it makes from `.github/workflows/p9-review.yml`. It never touches the product's data path and never ships with the application.

## Conditions

The exemption holds only while all of these are true. If any one stops being true, the exemption lapses and HR1-HR4 and HR6 apply in full.

1. **SHA-pinned action.** Every `uses:` of the action is pinned to a full 40-character commit SHA, not a tag or branch.
2. **Read-only tool allowlist.** The review agent gets only read tools (`Read`, `Grep`, `Glob`), an edit permission limited to its own verdict file, and the inline-comment tool. `Bash`, `WebFetch` and `WebSearch` are disallowed. Reads are limited to the checkout plus the job's own pre-written input directory (`$RUNNER_TEMP/p9`: the PR diff, changed-file list and commit list); reads of `/proc`, `/sys`, credentials and `.git` are denied.
3. **No product data beyond the PR diff.** The jobs run on GitHub-hosted runners. What reaches the API is the PR diff, the changed-file list, the commit list and tracked repository files the read tools open. User documents, the SQLite database and the legal-KB index and metadata are untracked (`.gitignore`) and are never in that checkout.
4. **Not in the application.** The action and its API client are not in any `requirements*.txt` file and are not installed or imported by the backend or the UI.

## Consequences

- The CI review jobs stay without an IRP grade-A audit entry. LIB-STACK lists the action under CI tooling, outside the product dependency tables, with a pointer to this ADR.
- The product's bar is unchanged. Any model or library on the runtime or data path still needs HR1-HR4 and HR6 in full, including the bans on Meta-origin and VC-funded LLM vendors, the no-external-API rule for user and legal-KB data, and the LocalAI-only inference rule.
- HR4 is scoped by owner decision on 2026-10-09: sending this repository's own source diff to the Claude API for CI review is allowed; condition 3 keeps user documents and product data out of the review jobs.
- Changing any condition above (unpinning the action, widening the tool allowlist, moving the jobs to a self-hosted runner, or sending product data) needs a new ADR that supersedes this one.
- Unrelated to the exemption: `ci.yml` and `gitignore-enforcement.yml` pin actions by tag, not SHA; that is tracked separately.
- Other development-time tools are not exempted by this ADR. Each one needs its own decision.

## Amendment 2026-10-15: ruff and uv exempt from HR6

- **Status:** Accepted
- **Date:** 2026-10-15
- **Decided by:** owner, 2026-10-15 (decision #14, the OpenAI acquisition of Astral)
- **Amends:** the last bullet of Consequences above ("Other development-time tools are not exempted by this ADR"), for ruff and uv only

### Context

The lead's decisions record for 2026-10-13 notes that an OpenAI acquisition of Astral, the maker of ruff and uv, was announced on 2026-03-19, and that whether it has closed is unverified. ruff is already a required CI check (`Lint (ruff)` in `.github/workflows/ci.yml`). HR6 is worded for the LLM provider, and this ADR exempts only CI *review* tooling, so ruff and uv needed their own decision. The lead recommended an exemption with a watch item, because ruff is MIT-licensed and runs fully locally.

### Decision

The owner's ruling, verbatim: "accept this as an exception".

ruff and uv are exempt from HR6 as development lint tooling, on the same footing as the CI review tooling above. As the decisions record states, they run locally, are MIT-licensed and send nothing to OpenAI.

This exemption does not adopt uv. The monorepo decision of the same date (#125: "Don't adopt uv now") still stands; the exemption only means that adopting uv later as dev tooling would not breach HR6.

### Scope and conditions

The exemption holds only while all of these are true. If any one stops being true, the exemption lapses and HR6 applies in full.

1. **Dev tooling only.** ruff and uv lint, format or install during development and in CI. They are never a runtime dependency of the product.
2. **Not in the application.** Neither tool appears in `requirements.txt`, `src/backend/requirements.txt` or `src/webapp/requirements.txt`, and neither is installed or imported by the backend or the UI.
3. **Nothing sent to OpenAI.** Neither tool sends source code, product data or telemetry to OpenAI or to any service it owns.

### Watch item

- **Trigger:** any change to the licence or the telemetry of ruff or uv. Any such change re-opens this decision; until the owner rules again, condition 3 is treated as unmet.
- **Who checks:** the lead, who reads the upstream licence file and release notes of each tool.
- **When:** before each gate sign-off from G2 onward, and in any PR that changes how either tool is installed. The result goes in that day's status log.

### Consequences

- ruff stays a required CI check without a replacement card. The alternative the owner did not take was carding a ruff replacement after G2.
- The product's bar is unchanged: HR6 still bars OpenAI from the runtime and data path.
