# P9 Review Enforcement Guide

How LIB-PRINCIPLES P9 (pr-independent-review) is enforced in terms-analysis.
The authoritative reference is `automations/p9-pre-push.md`; this guide is a
short orientation and does not restate the contract.

## What is P9?

Every change to `main` gets two independent reviews, and both must pass with
zero findings at any severity (owner directives 2026-07-03 and 2026-07-04):

1. **security-engineer**: STRIDE-style threat-model review (auth, secrets,
   user input, dependencies, CI permissions, migration safety).
2. **grumpy-developer**: blunt code-quality review (swallowed errors, dead
   code, brittle assumptions, missed edges, tautological tests).

## How it is enforced (since 2026-10-09, #191)

| Layer | What | Where |
|---|---|---|
| Review jobs | `security-review` and `grumpy-review` run Claude with the vendored briefs on every PR to `main` | `.github/workflows/p9-review.yml`, `.github/p9/*.md` |
| Verdict gate | Each job fails unless `p9-verdict.json` says PASS with no findings | `.github/p9/check_verdict.py` |
| Merge block | Pending: the owner adds both jobs as required checks on `main` after the first green run | GitHub repository settings |

The local `.githooks/pre-push` signoff gate, `.git/reviews/*.signoff.json`
files and the `enforce-p9-review.yml` text check are retired.
The ingester's copies retire in jennifer-mckinney/legal-corpus-ingester#20,
which merges right after #214; until then the ingester's main-branch parity
step fails. See "Companion change" in `automations/p9-pre-push.md`.

## Developer workflow

1. Push the feature branch and open a PR to `main`.
2. Read the reviewers' inline comments on the PR and the job logs.
3. If either job fails, fix every finding and push again; both jobs re-run.
4. When both jobs pass on the head commit, the PR is ready for the owner to
   merge.

## Troubleshooting

- **Job fails with `p9-verdict.json was not written`:** the reviewer did not
  finish (turn limit, timeout, missing `ANTHROPIC_API_KEY`, or a fork PR
  without secrets). Re-run the job, or check the secret.
- **Job fails with `does not match the verdict contract`:** the reviewer wrote
  the wrong shape. Re-run the job; if it repeats, tighten the brief.
- **Job fails with `P9 verdict: FAIL`:** read the findings in the job log or
  the inline PR comments, fix them, and push.

## References

- `automations/p9-pre-push.md`: workflow, verdict contract, owner setup, limits
- [LIB-PRINCIPLES P9](../.claude/library/LIB-PRINCIPLES.md#p9-pr-independent-review)
- `.claude/CLAUDE.md`: SO11, SO13, G3
