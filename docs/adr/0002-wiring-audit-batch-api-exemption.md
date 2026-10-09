# ADR 0002: The weekly wiring audit may send repository source to the Message Batches API

- **Status:** Proposed (accepted when this PR is merged by the owner; decision card #267)
- **Date:** 2026-10-09
- **Decided by:** owner, via #267
- **Governs:** `.claude/CLAUDE.md` hard requirements HR1 (open source only), HR2 (no investor-lawsuit vendors), HR3 (IRP Grade A or higher), HR4 (local-only data, no external API calls) and HR6 (no OpenAI, local-only LLM inference), as scoped by ADR 0001
- **Companion:** legal-corpus-ingester ADR-016 records the same decision for that repo's constraints C3, C4 and C7
- **Supersedes:** nothing. ADR 0001 stays in force; its last consequence ("Other development-time tools are not exempted by this ADR. Each one needs its own decision.") is what this ADR answers for one tool.

## Context

Card #224 adds a weekly, GitHub-hosted audit that asks a Claude model whether each module in this repository is actually wired: entry points with no caller, public functions nothing imports, tests that skip themselves, workflows that never run. Three such silent failures were found by hand on 2026-10-09 (invalid ingester workflow YAML, a `refresh` no-op, review-gate edge cases). Reviews catch diffs; this audit looks for absences.

The audit uses the Anthropic Message Batches API (`POST /v1/messages/batches`), not `claude-code-action`, so ADR 0001's exemption does not cover it. Read literally, HR1-HR4 and HR6 would bar it for the same reasons they would have barred the CI review jobs: a VC-funded LLM vendor, an external API call, LLM inference that is not local.

Design and threat model: `docs/evidence/2026-10-10-224-design.md`, `docs/evidence/2026-10-10-224-attack-sketch.md`, `docs/research/2026-10-10-224-batch-api.md` (written 2026-10-09 under the next-session file names; untracked evidence, summarised in #224 and #267).

## Decision

The weekly wiring audit is development-time tooling and is exempt from HR1, HR2, HR3, HR4 and HR6 on the same footing as the CI review jobs in ADR 0001. HR4 is scoped the same way: this repository's own tracked source may be sent to the Claude API for the audit; user documents, analysis results and legal-KB data never are.

## Conditions

The exemption holds only while all of these are true. If any one stops being true, the exemption lapses and HR1-HR4 and HR6 apply in full.

1. **Source only, allowlisted.** The inventory builder enumerates files with `git ls-files` (never a directory walk) filtered by the configured module globs, then removes every path matching the denylist (`data/**`, `.env*`, `docs/evidence/**`, `.git/**`, virtualenvs, databases, VCR cassettes, test files) and every path or line matching `.claude/governance/personal-path-patterns.txt`. Every candidate passes `scripts/governance/leak_scan.py` before submission. A golden test pins the exact file list for a known checkout.
2. **GitHub-hosted runners only.** Both workflows run on `ubuntu-latest`. The ingester copy never runs on the self-hosted runner, where the corpus and secrets share a machine. A test asserts the `runs-on` value.
3. **SHA-pinned actions, least privilege.** Every `uses:` is pinned to a full commit SHA. The submit job has `contents: read`; the collect job has `contents: read`, `actions: read` and `issues: write` and nothing else. No step runs model output through a shell.
4. **Dedicated credential with its own cap.** The workflows use a dedicated Console workspace and key (`WIRING_AUDIT_API_KEY`), with a workspace spend limit set in the Console, so a budget bug cannot drain the credit that the CI review jobs use. The jobs fail closed when the secret is missing.
5. **Budget enforced before any call.** Before submitting, the job counts tokens for every request and refuses when the worst-case cost (input plus `max_tokens` output at batch rates, from a config file with a `price_review_by` date) exceeds the configured ceiling. Actual usage is summed after collection and written to the job summary.
6. **No silent success.** Zero modules, a batch that is not `ended`, any errored, expired or cancelled request, a missing or duplicated `custom_id`, a `stop_reason` other than `end_turn`, or output that fails the JSON schema each exit non-zero with a distinct message. The collect job is never `continue-on-error`. A canary module with a known defect is in every batch; if the canary finding is absent, the run fails and files nothing.
7. **Model output is data.** Findings are validated against a strict JSON schema with enumerated `kind` and `severity`, truncated and escaped before filing, and posted through the REST API from validated fields. The first run, and any run until the owner flips `card_mode` to `cards`, files one summary issue rather than per-finding cards. Cards per run are capped.
8. **Retention.** The batch is deleted through the API after collection, so repository-derived prompts do not sit in the vendor's 29-day result retention. GitHub artifacts carrying the batch id and cost carry no headers or secrets and use the repository's default retention.
9. **Not in the application.** The client is the standard library (`urllib`); no SDK is added to any `requirements*.txt`, and nothing the audit installs is imported by the backend or the UI.

## Consequences

- The audit's model and API stay without an IRP grade-A entry; LIB-STACK lists the audit under CI tooling with a pointer to this ADR, next to the ADR 0001 entry.
- The product's bar is unchanged. Nothing on the runtime or data path is touched by this decision.
- Both repositories are public, so run logs, artifacts and the issues the audit files are world-readable. Conditions 1, 6 and 7 are what keep that acceptable; the attack sketch records why.
- Changing any condition (walking the filesystem, moving to the self-hosted runner, widening permissions, sharing the review key, dropping the budget check, letting a run succeed on nothing, filing unvalidated output) needs a new ADR that supersedes this one.
- After the monorepo merge (D9, #125) this ADR and ADR-016 collapse into one; until then both are required.
- Known drive-bys recorded by the design gate, tracked separately: `ci.yml` pins `checkout` and `setup-python` by tag; `scripts/testing/tests/` is run by no workflow.
