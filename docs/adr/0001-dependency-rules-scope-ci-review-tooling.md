# ADR 0001: Hard requirements HR1-HR4 and HR6 cover the product, not CI review tooling

- **Status:** Accepted
- **Date:** 2026-10-09
- **Decided by:** owner, 2026-10-09
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
2. **Read-only tool allowlist.** The review agent gets only read tools (`Read`, `Grep`, `Glob`), an edit permission limited to its own verdict file, and the inline-comment tool. `Bash`, `WebFetch` and `WebSearch` are disallowed. Reads outside the checkout and reads of credentials and `.git` are denied.
3. **No product data beyond the PR diff.** The jobs run on GitHub-hosted runners. What reaches the API is the PR diff, the changed-file list, the commit list and tracked repository files the read tools open. User documents, the SQLite database and the legal-KB index and metadata are untracked (`.gitignore`) and are never in that checkout.
4. **Not in the application.** The action and its API client are not in any `requirements*.txt` file and are not installed or imported by the backend or the UI.

## Consequences

- The CI review jobs stay without an IRP grade-A audit entry. LIB-STACK lists the action under CI tooling, outside the product dependency tables, with a pointer to this ADR.
- The product's bar is unchanged. Any model or library on the runtime or data path still needs HR1-HR4 and HR6 in full, including the bans on Meta-origin and VC-funded LLM vendors, the no-external-API rule for user and legal-KB data, and the LocalAI-only inference rule.
- HR4 is scoped by owner decision on 2026-10-09: sending this repository's own source diff to the Claude API for CI review is allowed; condition 3 keeps user documents and product data out of the review jobs.
- Changing any condition above (unpinning the action, widening the tool allowlist, moving the jobs to a self-hosted runner, or sending product data) needs a new ADR that supersedes this one.
- Unrelated to the exemption: `ci.yml` and `gitignore-enforcement.yml` pin actions by tag, not SHA; that is tracked separately.
- Other development-time tools are not exempted by this ADR. Each one needs its own decision.
