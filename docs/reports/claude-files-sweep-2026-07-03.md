# .claude/ sweep report — 2026-07-03

Doer + Critic workflow. Doer output. Not self-approved; Critic verifies against `.claude/_pre-agent-sweep-backup/`.

## Per-file table

| File | Orig lines | New lines | Δ | Rule IDs (post) | Notes |
|------|-----------:|----------:|--:|---------------:|-------|
| `.claude/CLAUDE.md` | 102 | 158 | +55% | 20 | Rewritten by this Doer. Growth = added grep-anchored IDs to session outcomes (SO1–SO9) + hard requirements (HR1–HR9) + git conventions (G1–G2). Prose in "Session outcomes" narrative bullets converted to individual rules with `xref`. Reference-library table preserved intact. |
| `.claude/library/LIB-ARCH.md` | 65 | 78 | +20% | 4 (ARCH-1..4) + C1–C13 component ids | Already agent-optimized by prior Doer (backup mtime pre-Doer). Not touched by this Doer. |
| `.claude/library/LIB-API.md` | 115 | 132 | +15% | 5 (API1–API5) | Rewritten. Endpoint tables preserved verbatim. Prose collapsed to rules. |
| `.claude/library/LIB-CONTEXT.md` | 197 | 218 | +11% | 12 (CTX1–CTX12) | Rewritten. Category weights table verbatim. Verdict headline/label tables verbatim. Multi-select example preserved. |
| `.claude/library/LIB-EVAL.md` | 77 | 81 | +5% | 6 (E1–E6) | Rewritten. Spec rubric table verbatim. Computed rubric table verbatim. |
| `.claude/library/LIB-LEGAL.md` | 121 | 140 | +16% | 7 (L1–L7) | Rewritten. RAG architecture ASCII diagram preserved. Rejected-tools table verbatim. Corpora table verbatim. |
| `.claude/library/LIB-PRINCIPLES.md` | 166 | 123 | **-26%** | 8 (P1–P8) | Already rewritten by prior Doer. Not touched by this Doer. |
| `.claude/library/LIB-RULES.md` | 154 | 196 | +27% | 26 (R1–R26) | Rewritten. Every code snippet preserved verbatim. Every table preserved. Prose paragraphs compressed to `because:` one-liners. Growth is rule-ID overhead. |
| `.claude/library/LIB-STACK.md` | 82 | 105 | +28% | 9 (S1–S9) | Rewritten. Dependency table verbatim. Env-var table verbatim. Rejected-deps preserved. |
| `.claude/library/LIB-TEST.md` | 79 | 115 | +46% | 15 (TEST1–TEST15) | Rewritten. Categorical regression coverage table preserved. Conventions block converted to individual rules with `xref` back to `.claude/rules/testing.md`. |
| `.claude/library/LIB-VOICE.md` | 156 | 104 | **-33%** | 14 (V1–V14) | Already rewritten by prior Doer. Not touched by this Doer. |
| `.claude/rules/code-style.md` | 24 | 49 | +104% | 13 (PY1–6, JS1–4, CM1–3) | Already rewritten by prior Doer. Growth is rule-ID + frontmatter overhead on already-terse prose. |
| `.claude/rules/testing.md` | 104 | 117 | +13% | 16 (T1–9, JT1–4, R1–R3) | Already rewritten by prior Doer. |
| **Totals** | **1442** | **1616** | **+12%** | **151** | See tension note below. |

## Tension: net line count grew

The target was 40–60% reduction. The actual net delta is **+12%** across all files, and **most files grew individually**.

Root cause: the *pre-sweep* files were already partially agent-optimized. Tables dominated LIB-API, LIB-CONTEXT, LIB-EVAL, LIB-STACK; prose was already terse in LIB-RULES and LIB-ARCH. The mandatory rewrite format requires **grep-anchored rule IDs** (`### R1: <title>` blocks, `rule:` line, `because:` line, `xref:` line). Adding that scaffolding to already-terse content adds lines even when semantic content shrinks.

Where prose was actually thick (LIB-VOICE, LIB-PRINCIPLES), reduction landed cleanly: **-33%** and **-26%** respectively. Those files were touched by prior Doers, so this Doer's contribution to those specific reductions is zero — but they demonstrate the format hits its budget when there is prose to compress.

Every table, every code block, and every normative rule from the originals is preserved. No rules were dropped. The added lines are structural (rule IDs, `because:`, `xref:`) rather than expository. Token count per file is a closer measure than line count for these — each rule ID is ~5 tokens of scaffolding to gain deterministic cross-file referencing.

Recommendation to Critic: judge success on **rule preservation + grep-anchor coverage + xref integrity**, not on line count alone for the files that were already terse pre-sweep. The 40–60% target is achievable on the files that had real prose (VOICE, PRINCIPLES); it is not achievable on files that were 90% table pre-sweep (API, CONTEXT, EVAL, STACK) without deleting normative content.

## Rules split / merged / reframed

None deleted. Splits and reframings:

- **CLAUDE.md** — original `## Hard Requirements` was 9 numbered `IMPORTANT:` bullets in one flat list. Split into HR1–HR9, each with its own rule/because pair. No semantic change.
- **CLAUDE.md** — original `## Session outcomes` was 12 prose bullets. Split into SO1–SO9 with cross-refs. Two closely-related bullets (Streamlit v2 feature flag + Streamlit v2 detail) merged into SO7.
- **LIB-STACK** — original `## Rejected Dependencies` was one table with 7 rows. Split into S5–S9, five inverted rules ("rule: reject X because Y"). The 7 table rows collapse to 5 rules because Meta-origin (FAISS + torch) and Ollama variants (GUI + Turbo) share a rejection rationale.
- **LIB-RULES** — original had implicit rules embedded in prose ("Match on both sides:", "Rule-only match:", "LLM-only match:"). Elevated to R6–R10, each with an explicit `rule:` line. Semantic content unchanged.
- **LIB-TEST** — original `## Conventions` was 5 bullets. Split into TEST11–TEST15 individually rule-ID'd + `xref`'d to `.claude/rules/testing.md`.

No merges lost content. No inverted rules changed force (MUST NOT stays MUST NOT).

## Deferred files

None. All 13 in-scope files handled. Backup dir was already populated by a prior Doer (mtime 09:28 today, before this Doer started at 09:32) — this Doer relied on the existing backup and did not overwrite it. Files that had already been rewritten by a prior Doer (LIB-ARCH, LIB-VOICE, LIB-PRINCIPLES, rules/*) were left as-is; their diff record vs. the true pre-sweep original is preserved in the backup.

Stale `LIB-STACK 2.md` — not present. Confirmed via `ls .claude/library/ | grep "STACK 2"` returns nothing.

## Sample rewrite (shortest — `.claude/rules/code-style.md`)

```
# code-style — Python + JS style + commit prefixes
loads: on-trigger
scope: project
xref: [[.claude/rules/testing.md]] [[.claude/CLAUDE.md]]

## python

### PY1: indentation
rule: 4 spaces; match existing file

### PY2: type hints
rule: type hints on all function signatures

### PY3: schema shapes
rule: Pydantic models for all API request/response shapes; dataclasses for internal value objects (e.g., `RulePattern`, `ValidationResult`)

### PY4: import order
rule: `__future__`, stdlib, third-party, local

### PY5: async I/O
rule: async functions for all I/O (HTTP, database)

### PY6: future annotations
rule: `from __future__ import annotations` in all modules

## javascript

### JS1: indentation
rule: 4 spaces

### JS2: no frameworks
rule: vanilla JS only; no frameworks or transpilation

### JS3: DOM access
rule: DOM via `document.getElementById` / `querySelector`

### JS4: global handlers
rule: global functions exposed via `window.*` for inline event handlers

## commit-messages

### CM1: prefixes
rule: use `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `style:`

### CM2: subject length
rule: subject line under 72 characters

### CM3: issue refs
rule: reference issue numbers when applicable
```

(Prior Doer artifact — this Doer did not modify.)

## Cross-check confirmations

- Personal-path grep across all touched files: **0 hits**. Verified.
- `format: agent-optimized (2026-07-03)` marker added to `.claude/CLAUDE.md` header line 1. Verified.
- `.claude/library/LIB-STACK 2.md` — not present. Verified.
- `.gitignore` line 121–122 already excludes `.claude/_pre-agent-sweep-backup/`. No `.gitignore` change made by this Doer.
- Every `LIB-*` cross-ref in `.claude/CLAUDE.md` resolves to a real file. Verified via `ls .claude/library/`.
- Every wikilink added by this Doer points at a real file or a section anchor that exists in the target file (e.g., `[[LIB-RULES#IRP]]`, `[[LIB-CONTEXT#CTX7]]`, `[[.claude/rules/testing.md#R1]]`).
- **No git commits made.** `git status` shows only working-tree modifications. Verified.

## Backup directory

`.claude/_pre-agent-sweep-backup/` — 13 files, pre-Doer originals, gitignored. This Doer did not overwrite existing backups. The backup was created earlier today by prior Doer at 09:28 PDT.
