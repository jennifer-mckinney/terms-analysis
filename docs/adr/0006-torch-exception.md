# ADR 0006: torch is allowed under HR2b, only as the runtime dependency of sentence-transformers

- **Status:** Accepted
- **Date:** 2026-10-12
- **Decided by:** owner, ruling "b" on #327
- **Approved-by:** @jennifer-mckinney, 2026-10-12
- **Governs:** `.claude/CLAUDE.md` hard requirement HR2 as split by ADR 0003, and its restatement in `.claude/library/LIB-STACK.md` S5 ("reject torch/PyTorch (Meta origin)")
- **Related:** #152 / PR #330 (sentence-transformers[onnx] approved for the product); ADR 0003 (HR2a/HR2b split)

## Context

On 2026-10-11 the owner approved onnxruntime, sentence-transformers[onnx] and sqlite-vec (exact mode) for the product (#152, PR #330). PR #330 verified on PyPI that sentence-transformers 6.1.0 declares `Requires-Dist: torch>=2.2` with no extra marker, so torch is a hard install requirement even when inference runs on onnxruntime.

LIB-STACK S5 rejected torch/PyTorch as Meta-origin with "no exceptions". Until that was revisited, sentence-transformers was approved but unusable. #327 asked the owner to decide; the owner chose option b: allow torch through an ADR exception.

## Decision

torch is allowed in the product under HR2b, with this scope: only as the runtime dependency that `sentence-transformers[onnx]` (approved under #152, PR #330) requires, `torch>=2.2`. It is not a general approval of torch, of PyTorch-based code, or of any other Meta-origin artifact.

Grounds:

- **HR2b (licence, not origin).** torch is distributed under BSD-3-Clause, a permissive licence that satisfies HR1. Under ADR 0003 an artifact is judged on its licence, not its originator.
- **Governance.** PyTorch is governed by the PyTorch Foundation, part of the Linux Foundation, not by Meta.
- **HR2a not engaged.** Installing a library from PyPI is not a transaction with, an API call to, or a service dependency on Meta.

## Conditions

The exception holds only while all of these are true. If any stops being true, the exception lapses and torch is rejected again under LIB-STACK S5.

1. **Pinned.** torch is pinned to an exact version in the requirements file that adds sentence-transformers[onnx], within its `torch>=2.2` range.
2. **CPU build.** The CPU-only torch build is installed; no CUDA build is pulled into the product.
3. **Audited.** torch passes `pip-audit` with no known vulnerability, and it has an HR3 grade (A or higher) from `/dependency-audit` before it ships.
4. **Not used directly.** No product module does `import torch`; torch is present only because sentence-transformers needs it, and inference runs on onnxruntime.
5. **Model bars still apply.** This exception covers the library, never model weights: every model loaded through sentence-transformers is screened against the model bars (no Meta, no Chinese-origin, no VC-funded LLM house, no ANN) on its own.

## Consequences

- LIB-STACK S5 no longer says "no exceptions"; S3 and S5 cite this ADR, and so do the LIB-LEGAL rows for sentence-transformers and torch.
- sentence-transformers[onnx] becomes usable for the G2 embedder work (plan R3) once conditions 1-3 are met.
- FAISS stays rejected (LIB-LEGAL L5, no ANN). This ADR does not reopen it.
- Any other use of torch, or any other Meta-origin library, needs its own ADR.
