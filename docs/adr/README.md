# Architecture decision records

Each ADR records one decision, its context, and the conditions under which it holds. ADRs are numbered in order (`NNNN-short-slug.md`) and are never renumbered. A changed decision gets a new ADR that supersedes the old one; the old one stays, with its status set to "Superseded by NNNN".

| ADR | Title | Status | Date |
|---|---|---|---|
| [0001](0001-dependency-rules-scope-ci-review-tooling.md) | Hard requirements HR1-HR4 and HR6 cover the product, not CI review tooling | Accepted | 2026-10-09 |
| [0002](0002-wiring-audit-batch-api-exemption.md) | The weekly wiring audit may send repository source to the Message Batches API | Accepted | 2026-10-09 |
| [0003](0003-hr2-split.md) | Split HR2 into HR2a (vendor, zero hops) and HR2b (licence, not origin) | Accepted | 2026-10-12 |
| [0004](0004-streamlit-to-vue.md) | Vue 3 + Vite, with Capacitor for native, replaces the Streamlit UI | Accepted | 2026-10-12 |
| [0005](0005-hr4-amendment.md) | HR4 amended for the Railway-hosted UI (document text may transit, never persists) | Accepted | 2026-10-12 |
| [0006](0006-torch-exception.md) | torch is allowed under HR2b, only as the runtime dependency of sentence-transformers | Accepted | 2026-10-12 |

## Checking the ADRs

`scripts/governance/check-adrs.py` checks every ADR against `.claude/governance/adr-policy.conf`: file names with this repo's 4-digit number (the ingester's ADRs use 3 digits, so the two never collide), unique and contiguous numbers, a title matching the number, the required sections, a known status, an `Approved-by` field naming a configured approver on every Accepted ADR whose header mentions a hard requirement, and a link from this index. CI runs it through `src/backend/tests/test_adrs.py`; run it locally with `python3 scripts/governance/check-adrs.py`.
