# P9 review in CI

P9 (`.claude/library/LIB-PRINCIPLES.md`) requires a security-engineer review
and a grumpy-developer review of every change, both at zero findings, before
it reaches `main`. Since 2026-10-09 (terms-analysis#191) that review runs as
two standard GitHub Actions jobs on the pull request. The earlier local
pre-push signoff hook is retired. The file keeps its old name so existing
links still resolve.

## How it runs

Workflow: `.github/workflows/p9-review.yml`.

- **Trigger:** `pull_request` to `main` (opened, synchronize, reopened,
  ready_for_review). Not `pull_request_target`, so the PR's code never runs
  with the base repository's secrets.
- **Jobs:** `security-review` and `grumpy-review`, on `ubuntu-latest`.
  Each job:
  1. checks out the PR (`actions/checkout`, pinned by commit SHA);
  2. deletes any `p9-verdict.json` committed in the PR and copies
     `.github/p9/check_verdict.py` to the runner's temp directory, before the
     reviewer can touch the tree;
  3. runs `anthropics/claude-code-action` (pinned by commit SHA) with a prompt
     that points at its brief, `.github/p9/security-engineer.md` or
     `.github/p9/grumpy-developer.md`;
  4. runs the copied gate on `p9-verdict.json`.
- **Bounds:** `timeout-minutes` per job, `--max-turns` for the reviewer, and a
  `concurrency` group per PR that cancels the run for a superseded commit.
- **Tools:** the reviewer may only read files (`Read`, `Glob`, `Grep`), write
  the verdict file (`Write`), and run `gh pr diff`, `gh pr view` and
  `gh pr comment`.
- **Permissions:** the workflow grants nothing by default; each job gets
  `contents: read` and `pull-requests: write` (for the comment) and uses the
  job's own `github.token`.
- **Secret:** `ANTHROPIC_API_KEY`, used only as the action's
  `anthropic_api_key` input. Fork PRs receive no secrets, so the review step
  fails and the job fails closed.

## Verdict contract

Each reviewer posts one summary comment on the PR and writes
`p9-verdict.json` in the working directory:

```json
{"verdict": "PASS", "findings": []}
```

```json
{"verdict": "FAIL", "findings": [
  {"severity": "HIGH", "title": "Short title", "file": "path/to/file.py", "line": 42}
]}
```

`.github/p9/check_verdict.py` decides the job result:

| Exit | Meaning |
|---|---|
| 0 | verdict `PASS` and `findings` is `[]`; prints `P9 verdict: PASS, 0 findings` |
| 1 | verdict `FAIL`, or any finding listed (each printed on one sanitised line) |
| 2 | file missing, unreadable, not JSON, duplicate keys, or not the contract shape |

Only exit 0 passes the job. A reviewer that crashes, runs out of turns or
writes nothing fails the job.

## Merging

Branch protection is not enabled yet (pending). After the first green run,
the owner adds `security-review` and `grumpy-review` (source: GitHub Actions)
as required status checks on `main` (see Owner setup). From then on a PR
merges only when both pass on its head commit. A new push re-runs both. Only
the owner can waive a finding, at merge time.

## Owner setup

1. Add the `ANTHROPIC_API_KEY` repository secret.
2. After the first green run, add `security-review` and `grumpy-review` as
   required status checks on `main`.

## Limits

- The workflow and briefs are read from the PR's own merge commit, as with
  any `pull_request` workflow. A PR that edits them changes its own review;
  that edit is visible in the diff both reviewers read and the owner merges.
- The reviewer reads untrusted PR content. The gate copy, the deleted
  committed verdict and the narrow tool list limit what a prompt injection can
  change; the owner's merge decision remains the final control.

## Local hooks

`scripts/install-hooks.sh` sets `core.hooksPath=.githooks` so the tracked
`.githooks/pre-commit` (gitignore and leak guards) runs on `git commit`.
There is no local pre-push gate any more and no `.git/reviews/` directory.
