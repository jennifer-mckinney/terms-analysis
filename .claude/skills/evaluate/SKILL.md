---
name: evaluate
description: Run F1/Kappa evaluation against the gold dataset and report quality metrics. Use when asked to "run evaluation", "check F1 scores", "evaluate rule quality", "run kappa", or to validate that rule changes haven't degraded detection quality.
allowed-tools: Bash, Read, Grep, Glob
---

# Evaluation Runner

## Workflow

1. **Check gold dataset exists**
   ```bash
   ls src/backend/evaluation/gold_dataset.json src/backend/tests/fixtures/gold_dataset.json
   ```

2. **Run evaluation**
   ```bash
   cd src/backend && python scripts/evaluate.py 2>&1
   ```

3. **Parse and report metrics**
   Extract from output and format as:
   ```
   ## Evaluation Results
   | Category | Precision | Recall | F1 |
   |----------|-----------|--------|-----|
   | (per category rows) |

   | Aggregate Metric | Value | Target | Status |
   |-----------------|-------|--------|--------|
   | Macro F1 | X.XX | >= 0.70 | PASS/FAIL |
   | Cohen's Kappa | X.XX | >= 0.65 | PASS/FAIL |
   ```

4. **Quality gate check**
   Reference targets from @.claude/library/LIB-EVAL.md:
   - Macro F1 >= 0.70
   - Per-category F1 >= 0.60
   - Cohen's Kappa >= 0.65
   - False positive rate <= 15%

5. **If metrics fail targets**
   - Identify weakest categories
   - Cross-reference with rule patterns in @.claude/library/LIB-RULES.md
   - Suggest specific pattern additions or threshold adjustments

## Arguments
- `$ARGUMENTS` can specify: "rules-only" (skip LLM), "with-llm" (include LLM), or a gold dataset path
- Default: rules-only evaluation
