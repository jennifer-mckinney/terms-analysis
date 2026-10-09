# Board sync

The project board is kept up to date by a GitHub Action, not by a
project-manager agent dispatched after every event (agent-setup audit item 5,
2026-10-09).

- Workflow: `.github/workflows/board-sync.yml`
- Routing and GitHub calls: `.github/board-sync/board_sync.py` (standard
  library plus the `gh` CLI)
- Config, the only place the board URL, the status field name and the
  status per event live: `.github/board-sync/config.json`

## What it does

| Event key | When | Status |
|---|---|---|
| `issue_opened` | An issue is opened. `actions/add-to-project` adds it to the board. | Backlog |
| `issue_closed_not_planned` | An issue is closed as not planned. | Done |
| `pr_ready` | A PR is opened, reopened or marked ready for review, and is not a draft. Every issue it links with a closing keyword (`Fixes #12`) moves. | In review |
| `pr_merged` | A PR is merged. Every issue it links with a closing keyword moves. | Done |

Everything else is a deliberate skip, logged as `board-sync: plan: skip
(<reason>)`: a draft PR, a PR closed without merging, and an issue closed as
completed or duplicate. Issues closed as completed are normally closed by a
merged PR, which already moved them to Done. Linked issues not yet on the
board are added first.

The project ID, the field ID and the option IDs are looked up by name on
every run. Renaming a status on the board without updating `config.json`
fails the run with a message listing the board's options.

Fork PRs are skipped by the job condition. They never receive the token, so
outside contributors cannot move cards.

## Owner setup (once)

A user-owned Projects v2 board needs a token with the `project` scope. The
job's built-in token cannot write to it.

1. Create a token for the board owner:
   - classic personal access token with the `project` and `repo` scopes; or
   - fine-grained token with account permission Projects: read and write,
     and repository permissions Issues and Pull requests: read for this
     repository.
2. Add it as a repository secret named `PROJECT_TOKEN`:

   ```bash
   gh secret set PROJECT_TOKEN --repo jennifer-mckinney/terms-analysis
   ```

Until the secret exists, every run fails with an error annotation that names
`PROJECT_TOKEN`. It never skips silently.

## Exit codes of board_sync.py

- `0`: done. The last line says what moved (`moved N issue(s) to "<status>"`)
  or why the event was skipped.
- `1`: a GitHub call failed, timed out or returned too much, or the board
  does not match the config (no such project, field or option).
- `2`: bad config, environment, event payload or usage, or a missing token.

## Changing the mapping

Edit `statuses` in `.github/board-sync/config.json`, then update the table
above; `src/backend/tests/test_board_sync.py` checks that the two agree.
