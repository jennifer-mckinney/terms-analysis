---
name: dependency-audit
description: IRP-score a dependency against the project's hard requirements. Use when asked to "audit dependency", "check license", "can we use X", "is X approved", or when adding any new package to the project. Verifies open source license, investor lawsuits, community standing, and IRP grade.
allowed-tools: WebSearch, WebFetch, Read, Bash, Grep
---

# Dependency Audit

## Hard Requirements (ALL must pass)

| # | Requirement | Fail Criteria |
|---|------------|---------------|
| 1 | Open source | Proprietary, closed source, source-available with restrictions |
| 2 | No investor lawsuits | Active securities litigation, investor fraud claims, investor revolt |
| 3 | Community standing | Negative sentiment, major ethics controversies, "enshittification" |
| 4 | IRP Grade A or higher | IRP score > 0.30 |

## Workflow

1. **Identify the dependency** from `$ARGUMENTS`

2. **Research** (use WebSearch + WebFetch):
   - License type and full text
   - GitHub/PyPI page for stars, activity, governance
   - Search: `"<package> lawsuit"`, `"<package> controversy"`, `"<package> license"`
   - Check if VC-funded (increases monetization pressure risk)
   - Community sentiment (Reddit, HN, GitHub issues)

3. **Score IRP**
   ```
   Impact (I):    How much damage if terms change or project dies? (1-5)
   Likelihood (L): How likely are adverse changes? (1-5)
   Safeguards (S): How protected are we? (open source = high, irrevocable license = high) (1-5)

   IRP = 0.5*(I/5) + 0.4*(L/5) - 0.3*(S/5)
   Grade: A+ (<=0.05), A (<=0.15), A- (<=0.30), B (<=0.45), C+ (<=0.60)
   ```

4. **Report**
   ```
   ## Dependency Audit: <package>

   | Requirement | Status | Evidence |
   |------------|--------|----------|
   | Open source | PASS/FAIL | License type |
   | No investor lawsuits | PASS/FAIL | Details |
   | Community standing | PASS/FAIL | Sentiment |
   | IRP Grade A+ | PASS/FAIL | Score |

   **Verdict: APPROVED / REJECTED**
   **Reason:** ...
   ```

5. **If APPROVED**, check @.claude/library/LIB-STACK.md and suggest adding it
6. **If REJECTED**, suggest an approved alternative

## Reference
- Approved tools: @.claude/library/LIB-STACK.md
- Rejected tools: @.claude/library/LIB-LEGAL.md (Rejected Tools section)
