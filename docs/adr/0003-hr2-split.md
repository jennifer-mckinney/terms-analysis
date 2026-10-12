# ADR 0003: Split HR2 into HR2a (vendor, zero hops) and HR2b (licence, not origin)

- **Status:** Accepted
- **Date:** 2026-10-12
- **Decided by:** owner; plan recommendation R1 approved, and this record approved on #161 ("my approval is fine, renumber")
- **Approved-by:** @jennifer-mckinney, 2026-10-12
- **Governs:** `.claude/CLAUDE.md` hard requirement HR2 (no vendors facing investor lawsuits, no Meta-origin dependencies), plus its restatements in `.claude/library/LIB-STACK.md` (S5, S7) and `.claude/library/LIB-LEGAL.md`
- **Related:** ADR 0001 (HR1-HR4 and HR6 cover the product, not CI review tooling); ADR 0006 (torch exception under HR2b)

## Context

HR2 bars vendors facing investor lawsuits and, in practice, Meta-origin dependencies. FAISS was excluded under it, yet FAISS is MIT-licensed, the same licence as models the stack already accepts. So the exclusion was a judgement about the originating organisation, not about the licence. Applied transitively and consistently, the same test also disqualifies PyTorch, and with it sentence-transformers, ONNX export and most of the Python ML ecosystem. The rule as written was self-inconsistent and had to be re-argued on every model or library addition.

The relevant standards ask for provenance to be recorded, not for originating organisations to be banned transitively: CycloneDX 1.5+ (`pedigree.ancestors`) and SPDX 3.0.1 (`trainedOn`, `ancestorOf`), OWASP LLM03:2025 (vulnerable pre-trained models) and NIST SP 800-218A. OWASP's remedy is hashes and signing, not vendor exclusion.

The settled project plan recommended splitting HR2 into two tests (recommendation R1). The owner approved R1, and on #161 approved this written record.

## Decision

HR2 is split into two tests:

- **HR2a, vendor and operational risk (zero hops, origin-based).** The product does not transact with, call APIs from, or take service dependencies on an excluded company. HR4 (local-only data) already satisfies most of this.
- **HR2b, artifact and licence risk (licence-based, not origin-based).** A permissively licensed artifact (library or model weights) is judged on its licence terms, not on its originator's corporate conduct.

Lineage is recorded for every model in CycloneDX `pedigree.ancestors` or SPDX `trainedOn`. Recording lineage is a provenance duty, not a ban trigger.

## Consequences

- "X is Meta-origin, therefore banned" no longer follows for a permissively licensed artifact; such an artifact is judged under HR2b. Each specific exception is still recorded in its own ADR (ADR 0006 is the first, for torch).
- FAISS stays rejected, now on its merits: LIB-LEGAL L5 forbids ANN indexes (plan R2). The model bars (no Meta, no Chinese-origin, no VC-funded LLM house, no ANN) still apply to model choice.
- HR1 (open-source licence) and HR3 (IRP grade A or higher via `/dependency-audit`) apply unchanged to anything admitted under HR2b.
- A future SBOM step records lineage per model; until it exists, lineage is written in the model's dependency-audit report.
