# Legal Corpus Ingester Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a standalone Python tool at `_AUTOMATION/Claude_Projects/legal-corpus-ingester/` that fetches, cleans, chunks, embeds, and publishes legal statute + court-judgment corpus as versioned bundles consumed by `terms-analysis`.

**Architecture:** Repository-pattern pipeline (Fetcher → Cleaner → Chunker → Embedder → Publisher → Provenance). Each stage behind a Python `Protocol`. Config-driven per-source YAML. Full versioned bundle (`corpus/` + `index/` + `MANIFEST.yaml` + `provenance/` + `ALERTS.md`) atomically written. Consumer (terms-analysis) verifies MANIFEST on startup, never rebuilds. Bundle publish via atomic symlink flip + SIGHUP.

**Tech Stack:** Python 3.10+, Typer, Pydantic v2, httpx (async), BeautifulSoup4 + trafilatura, pdfminer.six, lxml, LocalAI client (Apertus-8B for embeddings), numpy, PyYAML, pytest, vcrpy, Docker, self-hosted GitHub Actions runner.

**Reference specification:** `~/.claude/plans/delightful-humming-tome.md` — the source design doc with all 14 ADRs, gap answers, and locked decisions (L1–L6).

---

## Tactical Agent Team Execution

Per `.claude/library/LIB-PRINCIPLES.md` P8 (agent separation of duties), every task in this plan is dispatched to a role-scoped agent. Orchestrator (Claude) coordinates but does not execute code.

| Role | Subagent type | Scope | Signoff authority |
|------|---------------|-------|-------------------|
| **Coder** | `general-purpose` | Writes implementation + own unit tests | None |
| **Test Helper** | `general-purpose` | Writes spec-conformance tests from spec only; no visibility into Coder's diff | None |
| **Critic** | `general-purpose` | Runs Coder + Test Helper tests against Coder's code; reports pass/fail with diffs | None |
| **Grumpy Reviewer** | `grumpy-developer` | Code-quality review before push (adversarial) | Push gate — HIGH/CRITICAL blocks |
| **Security Reviewer** | `security-engineer` | STRIDE review before push | Push gate — ANY finding blocks (P9 zero-tolerance) |
| **Frontend QA** | `frontend-qa` | E2E when the tool exposes a UI (later phases) | Signoff on UI acceptance |
| **Decision** | Orchestrator (Claude) or user | Only signoff authority | Merge / push |

**Dispatch pattern per task:**

1. Orchestrator reads task spec.
2. Dispatch Coder with role-scoped prompt (per-task exact file paths + acceptance criteria).
3. Coder returns diff + own unit test results.
4. Dispatch Critic with Coder's output + Test Helper's spec-tests (if applicable).
5. On task boundary: orchestrator spot-checks disk state (mtimes, greps, git diff).
6. On phase boundary: dispatch Grumpy + Security in parallel.
7. Push only after both pass.

**PEAS discipline** (Performance / Environment / Actuators / Sensors) per dispatch:
- Every dispatch prompt names a single-line **Performance** measure (e.g., "test passes with exit 0").
- **Environment** bounds explicit (which files may / may not be touched, which subprocess is allowed).
- **Actuators** implicit from `subagent_type` tool-gating.
- **Sensors** implicit from prompt + tool-result stream.

**Orchestrator agent audit** after each return:
- Read the report.
- Spot-check on disk: `git diff --stat`, `mtime` on claimed files, `grep` for asserted changes.
- Scope drift, unexecuted-but-claimed tasks, or vague success measures surface here.

---

## Test Strategy

**Total tests written across Phase 0**: 20+ (see task list below). Coverage floor **80%** enforced via `pyproject.toml`.

**Test layers:**

| Layer | Framework | Location | When run |
|-------|-----------|----------|----------|
| **Unit** | pytest | `tests/unit/` | Every task |
| **Integration** (mocked upstream) | pytest + VCR cassettes | `tests/integration/` | Per stage complete |
| **Contract** (round-trip with terms-analysis) | pytest + dynamic import | `tests/e2e/` | Per phase complete |
| **Snapshot** (chunker parity) | syrupy | `tests/snapshot/` | On chunker change |
| **CLI smoke** | Typer `CliRunner` | `tests/cli/` | Per phase complete |
| **Weekly drift canary** | pytest + VCR record=all | CI schedule | Weekly on self-hosted runner |

**Fixture strategy:**

- **VCR cassettes** in `tests/fixtures/cassettes/<source>/` — recorded once, replayed in CI (`record_mode='none'`).
- **Sample corpus** in `tests/fixtures/corpus/` — one fixture .txt per parseable variant (plain body, sectioned body, PLACEHOLDER header, multi-metadata-field).
- **Chunker snapshots** in `tests/fixtures/snapshots/` — byte-exact expected output for each fixture.
- **Reference terms-analysis** — installed as a dev dependency for E2E imports.

**Coverage gates:**

- Phase 0: 80% line + 75% branch
- Each new module: 90% before merge
- Round-trip test MUST cover: parse → chunk → embed → serialize → deserialize → terms-analysis retrieve → assert non-empty result

---

## Automation Stack Documentation

The `automations/` directory (created in Task 3) documents every automated behavior. Every automation gets a one-page markdown file with: trigger, artifact produced, failure mode, escalation.

**Automations shipped in Phase 0:**

| Automation | Trigger | Location | Docs file |
|------------|---------|----------|-----------|
| Pre-commit hook | `git commit` | `.githooks/pre-commit` | `automations/pre-commit.md` |
| CI on PR | GitHub PR | `.github/workflows/ci.yml` | `automations/ci-pr.md` |
| Nightly quick health check | Cron `0 3 * * *` | `.github/workflows/health.yml` | `automations/health-check.md` |
| Weekly refresh | Cron `0 3 * * 0` | `.github/workflows/refresh.yml` | `automations/refresh.md` |
| Weekly VCR drift canary | Cron `0 4 * * 0` | `.github/workflows/vcr-drift.yml` | `automations/vcr-drift.md` |
| Approval expiry watcher | Cron daily | `.github/workflows/approval-expiry.yml` | `automations/approval-expiry.md` |
| License drift audit | Every fetch | inline in `pipeline/orchestrator.py` | `automations/license-drift.md` |
| Publish handoff (symlink flip + SIGHUP) | End of `ingester publish` | inline in `publishers/terms_analysis.py` | `automations/publish-handoff.md` |

**GitHub Actions runner**: **self-hosted** on user's local machine per L3 (HR4-compliant — all corpus fetches + artifacts stay local; GitHub only stores workflow logs).

**Self-hosted runner setup** documented in Task 40 (`automations/self-hosted-runner.md`).

**Automation health surfaced via** `ingester status` — a single command that reads every automation's last-run manifest and shows freshness / staleness per pipeline.

---

## Working Principles + Strategy

**Normative references** (read first, applied throughout):
- `~/.claude/CLAUDE.md` — global user rules (attribution, testing requirements, ask-confirm-execute, technology preferences, MCP tool availability)
- `_AUTOMATION/CLAUDE.md` — hub-level architecture + governance (data model is master, zero hallucination, constitutional PRINCIPLES.md docs, autonomy thresholds, session handoff at 85% context, repository / adapter / strategy / multi-agent patterns)
- `terms-analysis/.claude/CLAUDE.md` — project identity + hard requirements HR1–HR9 + global-tool contract (jurisdictions=[] = no filter)
- `terms-analysis/.claude/library/LIB-PRINCIPLES.md` — governance P1–P9

### Applied principles for this ingester

**P1 — No inference, ask** (LIB-PRINCIPLES §1). Any ambiguity encountered during execution (missing spec, unclear config, undocumented behavior of upstream source) → executor STOPS and dispatches `AskUserQuestion` before proceeding. Silent inference is a Coder-role violation.

**P2 — Anchor to BRD/PRD** (LIB-PRINCIPLES §2). This ingester's corpus scope traces back to `terms-analysis/docs/BRD_Terms_Policies_Reviewer.md` (customer segments + jurisdictions + hard scope limits) and `terms-analysis/docs/PRD_Terms_Policies_Reviewer.md` (persona journeys). Every added jurisdiction or instrument must cite the BRD/PRD section that justifies it (or open a drift ticket per P3).

**P3 — Surface drift, do not silently execute** (LIB-PRINCIPLES §3). If a task in this plan turns out to require a design change (schema evolution, dependency addition, scope shift), executor pauses + surfaces the drift via `AskUserQuestion` before implementing. Drift is not automatically wrong; anchor docs may be stale — but silent divergence is disqualifying.

**P4 — Hard scope limits non-negotiable** (LIB-PRINCIPLES §4, revised 2026-07-04). The corpus tool analyzes document text only; the runtime-permission scope limit is surfaced verbatim in the results "what else worth checking" note. This ingester never fetches or stores install-time permission manifests; only policy text.

**P5 — Local-only, open-source-only** (LIB-PRINCIPLES §5 + `terms-analysis/.claude/CLAUDE.md` §hard-requirements HR1–HR6). Every dependency added to this ingester passes `.claude/skills/dependency-audit` first (IRP Grade A or higher, permissive license, no Meta-origin, no investor-lawsuit vendors, no VC-funded LLM houses per hub funding-bar). HR4: all data local — self-hosted GitHub Actions runner per L3. HR6: no OpenAI; LocalAI Apertus-8B for embeddings per L5.

**P6 — Two-voice, no em-dash, tentative** (LIB-PRINCIPLES §6 + LIB-VOICE). Applies to CLI output + human-facing docs + error messages:
- No em-dashes (U+2014) in tool voice; use " — " only inside code excerpts / verbatim source quotes.
- Tentative framings ("may / possibly / might") in status output; never "you should".
- CLI error text is observational ("license SPDX changed from CC-BY-4.0 to CC-BY-NC — publish blocked"), not warm ("Uh oh, we can't publish because...").
- User-facing docs (README, automations/*.md) follow the same rules.

**P7 — Attribution + personal-path hygiene** (LIB-PRINCIPLES §7 + global CLAUDE.md). Every commit MUST include co-authorship trailers:

```
Co-Authored-By: Jennifer McKinney <jennifer.mckinney@croiai.com>
Co-Authored-By: Claude <noreply@anthropic.com>
```

Commit messages use HEREDOC (see the "Commit template" below). No personal paths (`/Users/<name>/…`) in committed files, docs, or examples. Credit Shawn Peng in any commit that uses Mermaid MCP for diagram generation.

**P8 — Agent separation of duties** (LIB-PRINCIPLES §8, refined 2026-07-04). Codified in the "Tactical Agent Team Execution" section above:
- Coder implements per spec. MAY write unit tests for own code. MUST NOT write spec-conformance tests. MUST NOT sign off.
- Test Helper writes spec-conformance tests from spec ONLY (no visibility to Coder's diff, unit tests, or output). Existing spec-conformance tests from prior Test Helper dispatches can be reused — do not re-dispatch when the test already codifies the spec.
- Critic runs Coder's unit tests + Test Helper's spec-conformance tests against Coder's code; reports pass/fail with diffs. No authority to modify code or tests. No signoff.
- Decision (orchestrator = Claude, or user) is the ONLY role with signoff authority.
- **One ask per agent.** No multi-ask dispatch prompts.
- **Agents run in isolation** — Coder does not know about Test Helper's existence or output.
- Orchestrator holds sole visibility to all agents.
- **Orchestrator agent audit after each return**: read the report AND spot-check disk state (mtime, grep for asserted change, `git diff --stat`).

**P9 — Pre-push independent review** (LIB-PRINCIPLES §9). Every phase push dispatches grumpy-developer + security-engineer in parallel BEFORE the push. Security findings are **zero-tolerance** (user directive 2026-07-03): any severity blocks push until resolved or user overrides. Grumpy CRITICAL/HIGH blocks; MEDIUM/LOW/NIT can be filed as follow-up issues. Push is via `git push` no `--force`, no `--no-verify`.

### Autonomy thresholds (from `_AUTOMATION/CLAUDE.md`)

- Confidence **≥ 0.98** → orchestrator dispatches Coder without asking user
- **0.95–0.97** → self-correct + verify + dispatch
- **< 0.95** → escalate via AskUserQuestion before dispatching

Applies to every task in this plan.

### Testing requirements (global CLAUDE.md + LIB-TEST)

- Every new functionality gets integration tests (not just unit tests) — reflected in the layered test strategy above.
- Tests run before every commit (pre-commit hook enforces this).
- Coverage ≥80% line + ≥75% branch at Phase 0 exit; ≥90% per new module before merge.
- No `@pytest.mark.asyncio` (project rule per `terms-analysis/.claude/rules/testing.md` T1 — same rule applies here). Use `asyncio.run(...)` inside sync test functions.

### Commit template (P7-compliant HEREDOC)

Every commit example in the tasks below uses this pattern. Replace the subject + body per task:

```bash
git commit -m "$(cat <<'EOF'
feat(scope): one-line subject under 72 chars

Optional body paragraph explaining the WHY (not the WHAT — the diff
shows the what). Reference the task number (Task N) and any linked
issue or ADR.

Co-Authored-By: Jennifer McKinney <jennifer.mckinney@croiai.com>
Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

Prefixes per project convention (from `terms-analysis/.claude/rules/code-style.md`): `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `style:`. Subject under 72 characters. Body explains why.

### Session handoff at 85% context

Global rule. When conversation reaches ~85% token budget during execution:
1. Create `SESSION_HANDOFF_YYYY-MM-DD_LEGAL_CORPUS_INGESTER.md` at repo root
2. Include: task-in-progress, files touched, tests written, next task, blockers
3. Commit the handoff before ending session

Next session reads the handoff first before continuing.

### Constitutional docs (from `_AUTOMATION/CLAUDE.md`)

The ingester's `PRINCIPLES.md` (Task 3) is constitutional — architectural decisions locked there require an ADR to change. Every ADR is a separate file under `docs/adr/NNN-<slug>.md`; PR-reviewed; supersedes prior text only after merge.

---

## Phase 0.0: Prework — CI/CD + Logging + Runner

**Rationale (user directive 2026-07-04):** Automation floor is stood up BEFORE any code tasks. Every Coder task from Task 1 onward runs against green CI + structured logs + a self-hosted runner already ticking. Tasks P1–P7 are done sequentially; each is a task-boundary with an orchestrator agent audit.

---

### Task P1: Create the GitHub repo (empty)

**Files:**
- Create: remote GitHub repo `jennifer-mckinney/legal-corpus-ingester`

**Step 1: Verify gh CLI auth**

```bash
gh auth status
```

Expected: authenticated as `jennifer-mckinney`.

**Step 2: Create private repo**

```bash
gh repo create jennifer-mckinney/legal-corpus-ingester \
  --private \
  --description "Standalone tool that ingests, cleans, chunks, embeds, and publishes legal corpus bundles consumed by terms-analysis." \
  --clone \
  --add-readme=false
```

Expected: repo created, local clone at `~/Documents/…/01_Claude_Projects/legal-corpus-ingester`.

**Step 3: Verify remote**

```bash
cd legal-corpus-ingester
git remote -v
```

Expected: `origin  https://github.com/jennifer-mckinney/legal-corpus-ingester.git (fetch/push)`.

**Step 4: Set default branch to `main`**

```bash
git branch -m main 2>/dev/null || true
git push -u origin main --allow-empty
```

**Step 5: Commit sentinel + verify**

Not required — repo is empty. Move to Task P2.

---

### Task P2: Self-hosted GitHub Actions runner

**Files:**
- Create: `scripts/setup_runner.sh` (in-repo)
- Create: `automations/self-hosted-runner.md`

**Step 1: Get runner registration token**

```bash
gh api -X POST /repos/jennifer-mckinney/legal-corpus-ingester/actions/runners/registration-token -q .token
```

Copy the token. Expires in 60 minutes.

**Step 2: Download and configure runner**

```bash
mkdir -p ~/actions-runner-legal-corpus && cd ~/actions-runner-legal-corpus
curl -o actions-runner.tar.gz -L https://github.com/actions/runner/releases/latest/download/actions-runner-osx-arm64-2.319.1.tar.gz
tar xzf actions-runner.tar.gz
./config.sh --url https://github.com/jennifer-mckinney/legal-corpus-ingester \
  --token <TOKEN_FROM_STEP_1> \
  --labels legal-corpus-ingester,self-hosted,macos \
  --unattended
```

Expected: `√ Runner successfully configured.`

**Step 3: Install as launchd service**

```bash
./svc.sh install
./svc.sh start
```

Expected: `Service is running.`

**Step 4: Verify in GitHub**

```bash
gh api /repos/jennifer-mckinney/legal-corpus-ingester/actions/runners -q '.runners[] | {name, status, labels: [.labels[].name]}'
```

Expected: `{name: "…", status: "online", labels: ["legal-corpus-ingester", "self-hosted", "macos"]}`.

**Step 5: Document + commit**

Write `automations/self-hosted-runner.md` covering: why self-hosted (HR4), install steps, service management, tear-down, security (only run trusted workflows).

Return to repo dir, create `scripts/setup_runner.sh` codifying the above for future rebuilds.

```bash
git add scripts/setup_runner.sh automations/self-hosted-runner.md
git commit -m "$(cat <<'EOF'
chore: configure self-hosted GitHub Actions runner (Task P2)

HR4 requires all corpus fetches + artifacts to stay local.
GitHub-hosted runners would move data through Azure/Microsoft.
Self-hosted runner on macOS ARM64 keeps everything on-machine;
GitHub sees only workflow logs.

Co-Authored-By: Jennifer McKinney <jennifer.mckinney@croiai.com>
Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
git push
```

---

### Task P3: Baseline CI workflow (runs on self-hosted, initially trivial)

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `automations/ci-pr.md`

**Step 1: Write minimal ci.yml**

```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main]
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
jobs:
  test:
    runs-on: [self-hosted, legal-corpus-ingester]
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        run: |
          python3 --version
      - name: Install (if pyproject exists)
        run: |
          if [ -f pyproject.toml ]; then
            python3 -m venv .venv
            source .venv/bin/activate
            pip install -e '.[dev]' 2>&1 | tail -5
          else
            echo "pyproject.toml not present yet — skipping install"
          fi
      - name: Lint (if ruff configured)
        run: |
          if [ -f pyproject.toml ] && grep -q "^\[tool.ruff\]" pyproject.toml; then
            source .venv/bin/activate
            ruff check .
          else
            echo "ruff not configured yet — skipping"
          fi
      - name: Test (if tests exist)
        run: |
          if [ -d tests ] && [ -n "$(ls -A tests 2>/dev/null)" ]; then
            source .venv/bin/activate
            pytest --cov-fail-under=0 2>&1 | tail -20
          else
            echo "no tests yet — skipping"
          fi
```

**Step 2: Push and verify workflow triggers**

```bash
git add .github/workflows/ci.yml
git commit -m "$(cat <<'EOF'
ci: baseline workflow on self-hosted runner (Task P3)

Runs on self-hosted (HR4). Conditionals let it pass even before
any code lands; as pyproject / ruff / tests get added in later
tasks, the steps become active automatically.

Co-Authored-By: Jennifer McKinney <jennifer.mckinney@croiai.com>
Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
git push
```

**Step 3: Verify workflow ran**

```bash
sleep 10
gh run list --workflow=ci.yml --limit=1
```

Expected: latest run status `completed` conclusion `success`.

**Step 4: Write automations/ci-pr.md**

Describes: what triggers CI (PR + push to main), what steps run, where to see results (`gh run view`), how to add steps as the codebase grows.

**Step 5: Commit docs**

```bash
git add automations/ci-pr.md
git commit -m "$(cat <<'EOF'
docs: describe CI workflow (Task P3)

Co-Authored-By: Jennifer McKinney <jennifer.mckinney@croiai.com>
Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
git push
```

---

### Task P4: Structured logging module + config

**Files:**
- Create: `src/legal_corpus_ingester/utils/logging.py`
- Create: `src/legal_corpus_ingester/utils/__init__.py`
- Create: `tests/unit/test_logging.py`
- Create: `automations/logging.md`

**Step 1: Write the failing test**

```python
# tests/unit/test_logging.py
from __future__ import annotations
import json
import logging
import io
from legal_corpus_ingester.utils.logging import configure_logging, get_logger

def test_configure_logging_emits_json():
    stream = io.StringIO()
    configure_logging(level="INFO", stream=stream, format="json")
    log = get_logger("test.mod")
    log.info("hello", extra={"source": "eurlex", "chunk_count": 42})
    line = stream.getvalue().strip().splitlines()[-1]
    record = json.loads(line)
    assert record["level"] == "INFO"
    assert record["message"] == "hello"
    assert record["logger"] == "test.mod"
    assert record["source"] == "eurlex"
    assert record["chunk_count"] == 42
    assert "timestamp" in record

def test_configure_logging_default_text():
    stream = io.StringIO()
    configure_logging(level="INFO", stream=stream, format="text")
    log = get_logger("test.mod")
    log.info("hello")
    line = stream.getvalue().strip().splitlines()[-1]
    assert "INFO" in line and "hello" in line

def test_get_logger_returns_module_scoped():
    log_a = get_logger("mod.a")
    log_b = get_logger("mod.b")
    assert log_a.name == "mod.a"
    assert log_b.name == "mod.b"
    assert log_a is get_logger("mod.a")  # same instance on re-call
```

**Step 2: Run to fail**

```bash
pytest tests/unit/test_logging.py -v
```

Expected: `ModuleNotFoundError: No module named 'legal_corpus_ingester.utils'`.

**Step 3: Implement logging module**

```python
# src/legal_corpus_ingester/utils/logging.py
from __future__ import annotations
import json
import logging
import sys
from datetime import datetime, timezone
from typing import IO, Optional

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in ("args", "msg", "levelname", "levelno", "pathname",
                       "filename", "module", "exc_info", "exc_text", "stack_info",
                       "lineno", "funcName", "created", "msecs", "relativeCreated",
                       "thread", "threadName", "processName", "process", "name",
                       "message"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)

_configured = False

def configure_logging(
    level: str = "INFO",
    stream: Optional[IO[str]] = None,
    format: str = "json",
) -> None:
    global _configured
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(stream or sys.stderr)
    if format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
    root.addHandler(handler)
    root.setLevel(level)
    _configured = True

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
```

**Step 4: Run to pass**

```bash
pytest tests/unit/test_logging.py -v
```

Expected: 3 passed.

**Step 5: Write automations/logging.md + commit**

Content of `automations/logging.md`:
- Structured JSON to stderr by default; `LOG_FORMAT=text` for humans.
- Every module gets a named logger via `get_logger(__name__)`.
- `LOG_LEVEL` env var controls verbosity (`DEBUG` / `INFO` / `WARNING` / `ERROR`).
- Fields consistently attached to LogRecord: `source` (source name), `chunk_count`, `bytes_fetched`, `stage` (fetch/clean/chunk/embed/publish), `run_id`, `elapsed_ms`.
- Log rotation NOT handled in-app; delegate to launchd log rotation on macOS or `logrotate` on Linux.

```bash
git add src/legal_corpus_ingester/utils/ tests/unit/test_logging.py automations/logging.md
git commit -m "$(cat <<'EOF'
feat(utils): structured JSON logging module (Task P4)

Every module gets a named logger via get_logger(__name__). Default
format is JSON to stderr; LOG_FORMAT=text switches to human readable.
Fields consistently attached across the pipeline: source, stage,
chunk_count, run_id, elapsed_ms — enables observability queries
without a schema-per-module.

Co-Authored-By: Jennifer McKinney <jennifer.mckinney@croiai.com>
Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
git push
```

---

### Task P5: Pre-commit hook + install script

**Files:**
- Create: `.githooks/pre-commit`
- Create: `scripts/install-hooks.sh`
- Create: `automations/pre-commit.md`

**Step 1: Write .githooks/pre-commit**

```bash
#!/usr/bin/env bash
# Pre-commit hook — enforce ruff + mypy + pytest unit before commit.
# Bypass with `git commit --no-verify` — DON'T (P7 violation if used to bypass fixes).
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "${REPO_ROOT}"

if [ ! -f pyproject.toml ]; then
  echo "pre-commit: no pyproject.toml yet — skipping"
  exit 0
fi

VENV="${REPO_ROOT}/.venv"
if [ ! -d "${VENV}" ]; then
  echo "pre-commit: .venv missing; run 'python3 -m venv .venv && source .venv/bin/activate && pip install -e .[dev]'"
  exit 1
fi

# shellcheck source=/dev/null
source "${VENV}/bin/activate"

echo "pre-commit: ruff check"
ruff check .

echo "pre-commit: mypy src/"
mypy src/ 2>&1 || {
  echo "pre-commit: mypy failed (non-blocking during Phase 0.0 — will block after Task 1)"
}

echo "pre-commit: pytest unit"
pytest tests/unit -q 2>&1 | tail -20 || {
  # Phase 0.0 has no tests yet — allow pass
  if [ ! -d tests/unit ] || [ -z "$(ls -A tests/unit 2>/dev/null)" ]; then
    echo "pre-commit: no unit tests yet — skipping"
    exit 0
  fi
  exit 1
}

echo "pre-commit: all checks passed"
```

**Step 2: Write scripts/install-hooks.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
git -C "${REPO_ROOT}" config core.hooksPath .githooks
chmod +x "${REPO_ROOT}/.githooks/pre-commit"
echo "pre-commit hook installed via git config core.hooksPath=.githooks"
```

**Step 3: Install + verify**

```bash
chmod +x .githooks/pre-commit scripts/install-hooks.sh
bash scripts/install-hooks.sh
```

**Step 4: Write automations/pre-commit.md**

Content: what it enforces (ruff, mypy, pytest unit), how to install, how to bypass (and why NOT to), grace during Phase 0.0.

**Step 5: Commit**

```bash
git add .githooks/ scripts/install-hooks.sh automations/pre-commit.md
git commit -m "$(cat <<'EOF'
chore: pre-commit hook (ruff + mypy + pytest unit) (Task P5)

Grace during Phase 0.0 — pyproject.toml + tests haven't landed yet
so the hook skips those steps. From Task 1 onward the hook is
enforcing. install-hooks.sh sets core.hooksPath to .githooks so
new clones pick it up on first bootstrap.

Co-Authored-By: Jennifer McKinney <jennifer.mckinney@croiai.com>
Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
git push
```

---

### Task P6: Dockerfile + docker-compose skeleton

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`
- Create: `automations/docker.md`

**Step 1: Write Dockerfile (multi-stage)**

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml* ./
RUN if [ -f pyproject.toml ]; then \
      python -m venv /venv && \
      /venv/bin/pip install --upgrade pip && \
      /venv/bin/pip install -e '.[dev]' ; \
    else \
      python -m venv /venv ; \
    fi

FROM python:3.12-slim AS runtime
RUN useradd --create-home --shell /bin/bash ingester
WORKDIR /app
COPY --from=builder /venv /venv
COPY --chown=ingester:ingester . .
USER ingester
ENV PATH="/venv/bin:${PATH}" \
    INGESTER_OUT_DIR=/app/out \
    INGESTER_STATE_DIR=/app/state \
    INGESTER_CONFIG_DIR=/app/config \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
VOLUME ["/app/out", "/app/state", "/app/config"]
ENTRYPOINT ["ingester"]
CMD ["--help"]
```

**Step 2: Write docker-compose.yml**

```yaml
services:
  ingester:
    build: .
    volumes:
      - ./out:/app/out
      - ./state:/app/state
      - ./config:/app/config
    environment:
      INGESTER_LOCALAI_URL: http://localai:8080/v1
      LOG_LEVEL: INFO
      LOG_FORMAT: json
    depends_on:
      - localai
  localai:
    image: localai/localai:latest-aio-cpu
    ports:
      - "8080:8080"
    volumes:
      - ./models:/models
    environment:
      MODELS_PATH: /models
```

**Step 3: Write .dockerignore**

```
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.git/
out/
state/*.json
tests/fixtures/cassettes/
.env
```

**Step 4: Test build**

```bash
docker build -t legal-corpus-ingester:dev . 2>&1 | tail -20
```

Expected: build succeeds (currently just installs the venv, since no code yet).

**Step 5: Write automations/docker.md + commit**

Docs cover: image layout, volume mounts, why non-root user, LocalAI dep, when to use compose vs `docker run`.

```bash
git add Dockerfile docker-compose.yml .dockerignore automations/docker.md
git commit -m "$(cat <<'EOF'
chore: Docker + compose skeleton (Task P6)

Multi-stage build (builder venv → slim runtime). Non-root user
per _AUTOMATION security convention. Volume mounts for out/,
state/, config/. Compose adds LocalAI as a sibling service so
the ingester's embedder has a target from day 1.

Co-Authored-By: Jennifer McKinney <jennifer.mckinney@croiai.com>
Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
git push
```

---

### Task P7: .env.example + secrets management doc

**Files:**
- Create: `.env.example`
- Create: `automations/secrets.md`

**Step 1: Write .env.example**

```
# legal-corpus-ingester — copy to .env and edit.
# All env vars are prefixed INGESTER_.

# Paths
INGESTER_OUT_DIR=./out
INGESTER_STATE_DIR=./state
INGESTER_CONFIG_DIR=./config

# LocalAI (must be running locally per HR4)
INGESTER_LOCALAI_URL=http://localhost:8080/v1
INGESTER_LOCALAI_MODEL=apertus-8b-instruct

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Legal-review gate overrides (emergency use only — prefer APPROVAL.yaml per ADR-007)
# INGESTER_LEGAL_REVIEW_APPROVED_sg_sso_terms=1
```

**Step 2: Write automations/secrets.md**

Content: how to manage `.env` (never committed — `.gitignore` covers it), rotation policy, how CI reads env vars (self-hosted runner reads from the host environment, NOT GitHub secrets, to keep HR4).

**Step 3: Verify .env is gitignored**

```bash
grep -q "^\.env$" .gitignore || echo ".env" >> .gitignore
git status --porcelain .env 2>&1 | head -3
```

Expected: `.env` does NOT appear (untracked because gitignored) or shows as ignored.

**Step 4: Commit**

```bash
git add .env.example automations/secrets.md .gitignore
git commit -m "$(cat <<'EOF'
chore: env.example + secrets management doc (Task P7)

Prefer APPROVAL.yaml (ADR-007) for legal-review gates; env-var
override is emergency-only. .env is gitignored; CI reads from
self-hosted-runner host env, NOT GitHub secrets, per HR4.

Co-Authored-By: Jennifer McKinney <jennifer.mckinney@croiai.com>
Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
git push
```

---

### Task P8: `.claude/` project governance scaffolding

**Rationale:** Per `_AUTOMATION/CLAUDE.md` §governance-rules and the `session-start-governance-chain` in the global CLAUDE.md, every project in the hub has the same governance chain: `.claude/CLAUDE.md` (project identity), `.claude/library/LIB-PRINCIPLES.md` (P1–P9 governance), `.claude/rules/` (code-style + testing), and (when it dispatches sub-agents) `.claude/_governance-manifest.json` for hash tracking. This ingester dispatches sub-agents per P8, so it inherits the full chain.

**Files:**
- Create: `PRINCIPLES.md` (root — constitutional per `_AUTOMATION/CLAUDE.md`)
- Create: `.claude/CLAUDE.md`
- Create: `.claude/library/LIB-PRINCIPLES.md`
- Create: `.claude/library/LIB-ARCH.md`
- Create: `.claude/library/LIB-STACK.md`
- Create: `.claude/library/LIB-TEST.md`
- Create: `.claude/rules/code-style.md`
- Create: `.claude/rules/testing.md`

**Step 1: Write PRINCIPLES.md**

Root-level PRINCIPLES.md (per hub convention). Content:
- Constraint-native design — what the ingester CANNOT do (fetch runtime permission manifests, use CC-BY-NC deps, use VC-funded LLM houses, dispatch to remote runners with corpus payload)
- Locked ADRs 001–014 (short cross-reference table to `docs/adr/NNN-*.md`)
- Change process: any principle change requires an ADR + PR review + LIB-PRINCIPLES manifest bump

**Step 2: Write `.claude/CLAUDE.md`**

Agent-optimized format matching `terms-analysis/.claude/CLAUDE.md`:

```markdown
format: agent-optimized (2026-07-04)
# legal-corpus-ingester — project identity, hard requirements, library index
loads: auto
scope: project
xref: [[LIB-PRINCIPLES]] [[LIB-ARCH]] [[LIB-STACK]] [[LIB-TEST]]
      [[docs/plans/2026-07-04-legal-corpus-ingester.md]]
      [[~/.claude/plans/delightful-humming-tome.md]]
      [[_AUTOMATION/CLAUDE.md]]
      [[../terms-analysis/.claude/CLAUDE.md]]

## identity

| Key | Value |
|-----|-------|
| Purpose | Fetch + clean + chunk + embed + publish legal corpus bundles for terms-analysis |
| Stack | Python 3.10+, Typer, Pydantic v2, httpx, BeautifulSoup4, pdfminer.six, lxml, LocalAI (Apertus-8B), numpy, PyYAML, pytest, vcrpy |
| Consumer | terms-analysis (sibling project) — reads bundles produced here |
| Status | Phase 0.0 prework (2026-07-04) |

## hard-requirements

### HR1: open-source-only
rule: all dependencies MUST be open source (Apache 2.0, MIT, BSD, MPL 2.0, public domain preferred)

### HR2: no-investor-lawsuit-vendors
rule: no tools/services from companies facing investor lawsuits; no Meta-origin packages (FAISS excluded); no VC-funded LLM houses per _AUTOMATION funding bar

### HR3: IRP-grade-A-or-higher
rule: every dependency added passes .claude/skills/dependency-audit before merge

### HR4: local-only-data
rule: all corpus data stays local; self-hosted GitHub Actions runner (never GitHub-hosted)

### HR5: fail-loud-on-source-drift
rule: 404 / schema change / license SPDX drift halts the affected source and emits ALERTS.md; never silent shorter corpus

### HR6: no-openai-local-LLM-only
rule: embedding via LocalAI + Apertus-8B; no OpenAI, no cloud embedding APIs

### HR7: manifest-pinning-hard-fail
rule: consumer verifies MANIFEST embedder_model + embedder_revision on startup; mismatch → HTTP 503 with X-Corpus-Mismatch header

### HR8: license-drift-zero-tolerance
rule: SPDX change on any tracked source blocks publish until human review

### HR9: legal-review-gate-required
rule: sources with license risk (e.g. Singapore SSO) require APPROVAL.yaml with signed_artifact_sha256 verification before ingest

## project-map

| Path | Purpose |
|------|---------|
| `src/legal_corpus_ingester/` | Python package |
| `src/legal_corpus_ingester/fetchers/` | Per-source fetch modules |
| `src/legal_corpus_ingester/cleaners/` | HTML/PDF/XML/plaintext normalization |
| `src/legal_corpus_ingester/chunkers/` | Section-aware + plain chunkers (vendored from terms-analysis) |
| `src/legal_corpus_ingester/embedders/` | LocalAI Apertus-8B client |
| `src/legal_corpus_ingester/publishers/` | filesystem / terms-analysis / tarball |
| `src/legal_corpus_ingester/pipeline/` | orchestrator + state + manifest + retention |
| `src/legal_corpus_ingester/provenance/` | tracker + license_audit + manifest writer |
| `config/sources/` | per-source YAML |
| `state/` | manifest.json, checkpoints, license-hashes.json (git-tracked) |
| `out/YYYY.MM.PATCH/` | versioned bundles |
| `docs/adr/` | 14 ADRs |
| `automations/` | one .md per automation |
| `tests/` | unit + integration + e2e + snapshot + cli |

## commands

| Task | Command |
|------|---------|
| Install | `python -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'` |
| Install hooks | `bash scripts/install-hooks.sh` |
| Run tests | `pytest` |
| Fetch one source | `ingester fetch eurlex` |
| Full refresh | `ingester refresh` |
| Status | `ingester status` |
| Validate round-trip | `ingester validate-round-trip out/current` |

## reference-library

| Key | File | Use When |
|-----|------|----------|
| **LIB-PRINCIPLES** | `.claude/library/LIB-PRINCIPLES.md` | P1–P9 governance (mirrors terms-analysis) |
| **LIB-ARCH** | `.claude/library/LIB-ARCH.md` | Module structure, interface contracts, data flow |
| **LIB-STACK** | `.claude/library/LIB-STACK.md` | Dependency list, versions, IRP grades |
| **LIB-TEST** | `.claude/library/LIB-TEST.md` | Test layers, coverage gates, VCR cassette workflow |

## governance-monitoring

### G1: content-consistency
manifest: `.claude/_governance-manifest.json`
tracks: SHA256 of `.claude/CLAUDE.md`, `.claude/library/LIB-PRINCIPLES.md`, `$HOME/.claude/CLAUDE.md`, `$HOME/.claude/library/PEAS.md`
verify: `scripts/governance/verify-hashes.sh`
regen: `scripts/governance/regen-manifest.sh --yes`

### G2: pre-push-independent-review
rule: LIB-PRINCIPLES P9 — grumpy-developer + security-engineer dispatched before every push; zero-tolerance security gate
```

**Step 3: Write `.claude/library/LIB-PRINCIPLES.md`**

Copy P1–P9 verbatim from `terms-analysis/.claude/library/LIB-PRINCIPLES.md`. Add a top-of-file note: "principles inherit from terms-analysis; kept in-sync via `scripts/governance/sync-lib-principles.sh` which mirrors from sibling repo." No divergence unless justified by ADR.

**Step 4: Write `.claude/library/LIB-ARCH.md`**

Module tree (from the reference plan in `~/.claude/plans/delightful-humming-tome.md`), interface contracts (Fetcher / Cleaner / Chunker / Embedder / Publisher / Provenance Protocols), data types (`ProvenanceRecord`, `FetchResult`, `CleanedDocument`, `Chunk`, `Corpus`), MANIFEST schema, publish mechanism (symlink hybrid at bundle level).

**Step 5: Write `.claude/library/LIB-STACK.md`**

Dependency list from `pyproject.toml` with per-dep IRP grade + license + funding origin (verified via `.claude/skills/dependency-audit`). Table: `package | version | license | funding | IRP grade | rationale`.

**Step 6: Write `.claude/library/LIB-TEST.md`**

Test strategy from this plan (unit / integration / contract / snapshot / cli / weekly drift canary), coverage gates (80% at Phase 0 exit, 90% per new module), fixture strategy (VCR cassettes, sample corpus, chunker snapshots), test naming convention.

**Step 7: Write `.claude/rules/testing.md`**

Mirror `terms-analysis/.claude/rules/testing.md`:
- T1: no `@pytest.mark.asyncio`; use `asyncio.run(...)` inside sync tests
- T2–T9: standard pytest conventions
- Coverage floor + branch coverage

**Step 8: Write `.claude/rules/code-style.md`**

Mirror `terms-analysis/.claude/rules/code-style.md`:
- PY1–PY6: Python style (4-space, type hints, Pydantic for API shapes, dataclasses for internal, import order, `from __future__ import annotations`, async I/O)
- Commit conventions (feat/fix/docs/test/refactor/chore/style, 72-char subject, HEREDOC + Co-Authored-By trailers)
- Ruff config aligned with `pyproject.toml`

**Step 9: Commit all governance scaffolding**

```bash
git add PRINCIPLES.md .claude/
git commit -m "$(cat <<'EOF'
docs: .claude/ project governance scaffolding (Task P8)

Establishes the standard hub governance chain (session-start
loads .claude/CLAUDE.md + LIB-PRINCIPLES automatically):

- PRINCIPLES.md at root (constitutional per _AUTOMATION convention)
- .claude/CLAUDE.md (project identity + HR1-HR9 hard requirements)
- .claude/library/LIB-PRINCIPLES.md (mirrors terms-analysis P1-P9)
- .claude/library/LIB-ARCH.md (module tree + interface contracts)
- .claude/library/LIB-STACK.md (dep list + IRP grades)
- .claude/library/LIB-TEST.md (test strategy + coverage gates)
- .claude/rules/testing.md + code-style.md (pytest + Python style)

Governance manifest + hash-tracking scripts land in Task P9.

Co-Authored-By: Jennifer McKinney <jennifer.mckinney@croiai.com>
Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
git push
```

---

### Task P9: Governance manifest + hash-tracking scripts

**Rationale:** Per `_AUTOMATION/CLAUDE.md` §governance-rules §G1 + §G2 and the session-start-governance-chain in the global CLAUDE.md, projects that host LIB-PRINCIPLES SHOULD host `.claude/_governance-manifest.json` + `scripts/governance/*` to catch silent drift of governance files between sessions.

**Files:**
- Create: `.claude/_governance-manifest.json`
- Create: `scripts/governance/verify-hashes.sh`
- Create: `scripts/governance/regen-manifest.sh`
- Create: `scripts/governance/sync-lib-principles.sh`
- Create: `scripts/governance/README.md`

**Step 1: Write scripts/governance/regen-manifest.sh**

Content: computes SHA256 of `.claude/CLAUDE.md`, `.claude/library/LIB-PRINCIPLES.md`, `$HOME/.claude/CLAUDE.md`, `$HOME/.claude/library/PEAS.md`. Writes to `.claude/_governance-manifest.json`. Requires `--yes` flag or interactive `y/N` prompt (matches terms-analysis pattern — governance regen must be intentional).

**Step 2: Write scripts/governance/verify-hashes.sh**

Content: reads `_governance-manifest.json`, recomputes SHA256 for each tracked path, exits 0 on match, 1 on drift (specifies which file), 2 on manifest missing, 3 on tracked-file missing.

**Step 3: Write scripts/governance/sync-lib-principles.sh**

Content: `diff` `.claude/library/LIB-PRINCIPLES.md` against `../terms-analysis/.claude/library/LIB-PRINCIPLES.md`. On mismatch: prompt user to review + accept mirror (or open an ADR to justify divergence). Prevents silent P1–P9 drift between sibling projects.

**Step 4: Generate initial manifest**

```bash
chmod +x scripts/governance/*.sh
bash scripts/governance/regen-manifest.sh --yes
```

**Step 5: Verify + document + commit**

```bash
bash scripts/governance/verify-hashes.sh
```

Expected: `HASHES OK: 4 files verified`.

Write `scripts/governance/README.md` covering: what the scripts do, when to run, PR-review policy (regen only after intentional governance edit).

```bash
git add .claude/_governance-manifest.json scripts/governance/
git commit -m "$(cat <<'EOF'
chore: governance manifest + hash-tracking scripts (Task P9)

Adds G1 (content-consistency) + G2 (regen-with-intent) monitoring
per _AUTOMATION/CLAUDE.md session-start-governance-chain.
Tracks project + global CLAUDE.md + PEAS.md + LIB-PRINCIPLES.md.
sync-lib-principles.sh mirrors P1-P9 from terms-analysis with
divergence-must-have-ADR gate.

Co-Authored-By: Jennifer McKinney <jennifer.mckinney@croiai.com>
Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
git push
```

---

### Task P10: Tools / Skills / Agents inventory + `.claude/skills/` scaffolding

**Rationale:** Executor sessions need to know which external tools are prerequisites, which `.claude/skills/` are invocable during work, and which subagent types are dispatched at which task boundaries. This task inventories all three + scaffolds the local skills directory (mirroring the useful subset from terms-analysis).

**Files:**
- Create: `docs/TOOLS.md` (external tool prerequisites)
- Create: `docs/AGENTS.md` (subagent dispatch guide)
- Create: `.claude/skills/dependency-audit/SKILL.md` (adapted from terms-analysis)
- Create: `.claude/skills/test-suite/SKILL.md` (adapted)
- Create: `.claude/skills/write-tests/SKILL.md` (adapted)
- Create: `.claude/skills/review/SKILL.md` (adapted)
- Create: `.claude/skills/ralph-loop/SKILL.md` (adapted)
- Create: `.claude/skills/corpus-fetch/SKILL.md` (new — ingester-specific)
- Create: `.claude/skills/corpus-publish/SKILL.md` (new — ingester-specific)

**Step 1: Write docs/TOOLS.md — external prerequisites**

Content:

| Tool | Purpose | Install | Version pin |
|------|---------|---------|-------------|
| Python 3.10+ | Runtime | `brew install python@3.12` | ≥3.10 |
| Docker Desktop / colima | Container builds | brew | latest |
| Docker Compose v2 | Multi-service orchestration | bundled with Docker | latest |
| `gh` CLI | GitHub interactions (repo create, PR, runner registration) | `brew install gh` | ≥2.40 |
| Git | VCS | system | ≥2.30 |
| LocalAI + Apertus-8B model | Embedding (HR6) | see `automations/localai-setup.md` (Task later) | model SHA pinned in MANIFEST |
| GitHub Actions self-hosted runner binary | CI on-host | Task P2 script | 2.319.1 |
| `jq` | JSON parsing in shell scripts | `brew install jq` | any |
| `shellcheck` | Shell-script lint | `brew install shellcheck` | any |

Also note MCP tools available during Claude sessions (from user's global config):
- `mcp__mermaid__generate` (Shawn Peng's Mermaid MCP) — for diagram generation
- `mcp__llm__*` (Perplexity + Gemini access) — for cross-checking upstream statute claims
- `mcp__plugin_playwright_playwright__*` — E2E when a UI lands (later phases)

**Step 2: Write docs/AGENTS.md — subagent dispatch guide**

Content:

Ingester execution dispatches subagents per LIB-PRINCIPLES P8. Use this table when writing dispatch prompts:

| Subagent type | Role | Used at | Prompt template location |
|---------------|------|---------|--------------------------|
| `general-purpose` | Coder — implements per task spec + writes own unit tests | Every Task 1–N | `docs/prompts/coder.md` |
| `general-purpose` (isolated) | Test Helper — writes spec-conformance tests from spec ONLY, no visibility to Coder | Once per stage complete | `docs/prompts/test-helper.md` |
| `general-purpose` (isolated) | Critic — runs Coder unit tests + Test Helper spec tests, reports pass/fail | After Coder + Test Helper return | `docs/prompts/critic.md` |
| `grumpy-developer` | Adversarial code-quality review | Before every phase push | `docs/prompts/grumpy.md` |
| `security-engineer` | STRIDE review, zero-tolerance gate | Before every phase push | `docs/prompts/security.md` |
| `researcher` | Upstream source verification, license research | When adding a new source | `docs/prompts/researcher.md` |
| `Explore` (read-only) | Codebase exploration when scope is uncertain | Ad hoc | `docs/prompts/explore.md` |
| `code-simplifier` | End-of-phase cleanup pass | Optional at phase boundary | `docs/prompts/simplifier.md` |

**Dispatch rules (P8 restated):**
- One ask per agent. Multi-ask prompts violate role isolation.
- Coder does NOT know Test Helper exists.
- Critic reports pass/fail but has no signoff authority.
- Decision = orchestrator (Claude) or user only.
- Orchestrator agent audit after each return: spot-check disk state (mtime, grep, `git diff --stat`).

**Step 3: Adapt skills from terms-analysis**

For each of `dependency-audit`, `test-suite`, `write-tests`, `review`, `ralph-loop`:
1. Copy `terms-analysis/.claude/skills/<name>/SKILL.md` into `.claude/skills/<name>/SKILL.md`.
2. Rewrite paths from `src/backend/…` to `src/legal_corpus_ingester/…`.
3. Rewrite framework references (FastAPI/Streamlit → Typer CLI + pipeline).
4. Update trigger examples to the ingester's vocabulary (e.g. "run tests" still valid; "check f1 score" removed since ingester has no F1).

**Step 4: Write new ingester-specific skills**

`.claude/skills/corpus-fetch/SKILL.md`:
- Trigger: "fetch corpus", "refresh <source>", "ingest GDPR"
- Purpose: guided workflow for adding a new source — read source YAML, verify license, check VCR cassette exists, dispatch fetcher, verify FetchResult, commit cassette + provenance
- Cross-refs: LIB-ARCH fetcher Protocol, `docs/prompts/researcher.md` for upstream verification

`.claude/skills/corpus-publish/SKILL.md`:
- Trigger: "publish corpus", "cut a bundle", "publish to terms-analysis"
- Purpose: guided workflow for cutting a corpus bundle — verify all sources fresh, run round-trip validation, dispatch publisher, verify symlink flip, SIGHUP terms-analysis (or POST /reload), verify `X-Corpus-Mismatch` header is absent on the consumer's `/health`
- Cross-refs: LIB-ARCH publisher Protocol, `automations/publish-handoff.md`

**Step 5: Commit**

```bash
git add docs/TOOLS.md docs/AGENTS.md .claude/skills/
git commit -m "$(cat <<'EOF'
docs: tools + agents inventory + .claude/skills/ (Task P10)

- docs/TOOLS.md — external tool prerequisites (Python, Docker,
  gh CLI, LocalAI, self-hosted runner, jq, shellcheck) + MCP
  tools available during Claude sessions
- docs/AGENTS.md — subagent dispatch table matching LIB-PRINCIPLES
  P8 role separation + prompt template locations
- .claude/skills/{dependency-audit,test-suite,write-tests,review,
  ralph-loop}/SKILL.md — adapted from terms-analysis with ingester
  paths + Typer/pipeline framework references
- .claude/skills/corpus-{fetch,publish}/SKILL.md — new
  ingester-specific workflows

Co-Authored-By: Jennifer McKinney <jennifer.mckinney@croiai.com>
Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
git push
```

---

### Phase 0.0 exit gate (final)

Before starting Task 1:

- [ ] `gh repo view jennifer-mckinney/legal-corpus-ingester` returns the repo (P1)
- [ ] Self-hosted runner shows `online` (P2)
- [ ] Latest CI run on `main` is green (P3)
- [ ] Structured-logging tests pass (P4)
- [ ] `bash scripts/install-hooks.sh` reports `pre-commit hook installed` (P5)
- [ ] `docker build -t legal-corpus-ingester:dev .` succeeds (P6)
- [ ] `.env.example` present + `.env` gitignored (P7)
- [ ] `.claude/CLAUDE.md` + LIB-PRINCIPLES.md + LIB-ARCH.md + LIB-STACK.md + LIB-TEST.md present (P8)
- [ ] `bash scripts/governance/verify-hashes.sh` exits 0 (P9)
- [ ] `bash scripts/governance/sync-lib-principles.sh` reports no drift from terms-analysis (P9)
- [ ] `docs/TOOLS.md` + `docs/AGENTS.md` + 7 skill SKILL.md files present (P10)
- [ ] `automations/` contains: `self-hosted-runner.md`, `ci-pr.md`, `logging.md`, `pre-commit.md`, `docker.md`, `secrets.md` (6 files — 4 more come in Tasks 30–35 of Phase 0.1)
- [ ] Grumpy-developer + security-engineer peer review dispatched on the P1–P10 diff → both PASS

Only after all boxes ticked, proceed to Task 1.

---

## Phase 0.1: Core Scaffolding (Tasks 1–40)

Renumbered from prior Task 1–40. Same content; each task now assumes Phase 0.0's automation floor is live. Every commit is caught by the pre-commit hook; every push triggers CI on the self-hosted runner; every module gets a structured logger via `get_logger(__name__)`.

Estimated effort: ~1 week Coder + Critic pair, ~200 total steps.

Phase 1 (EU cluster), Phase 2 (US federal), Phase 3 (US state), Phase 4 (APAC + international), Phase 5 (rolling refresh) get their own writing-plans docs.

---

### Task 1: Scaffold project directory + git init

**Files:**
- Create: `_AUTOMATION/Claude_Projects/legal-corpus-ingester/.gitignore`
- Create: `_AUTOMATION/Claude_Projects/legal-corpus-ingester/README.md`
- Create: `_AUTOMATION/Claude_Projects/legal-corpus-ingester/CLAUDE.md`

**Step 1: Create directory and initialize git**

```bash
cd ~/Documents/05_Technical_Development/01_AUTOMATION/01_Claude_Projects
mkdir legal-corpus-ingester
cd legal-corpus-ingester
git init
```

**Step 2: Write .gitignore**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
coverage.xml
htmlcov/
out/
state/*.json
!state/.gitkeep
tests/fixtures/cassettes/*/pii-scrub.log
.env
.DS_Store
```

**Step 3: Write minimal README.md**

```markdown
# legal-corpus-ingester

Standalone tool that ingests, cleans, chunks, embeds, and publishes legal statute + court-judgment corpus consumed by [terms-analysis](https://github.com/jennifer-mckinney/terms-analysis).

See `docs/plans/2026-07-04-legal-corpus-ingester.md` in the terms-analysis repo for the full implementation plan.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
ingester init
ingester status
```
```

**Step 4: Write minimal CLAUDE.md (project agent context)**

Reference the plan file at `~/.claude/plans/delightful-humming-tome.md` and the executable plan in terms-analysis.

**Step 5: Commit**

```bash
git add .gitignore README.md CLAUDE.md
git commit -m "chore: scaffold repo (Task 1)"
```

---

### Task 2: pyproject.toml + Python packaging

**Files:**
- Create: `legal-corpus-ingester/pyproject.toml`
- Create: `legal-corpus-ingester/src/legal_corpus_ingester/__init__.py`

**Step 1: Write pyproject.toml with pinned dependencies**

```toml
[project]
name = "legal-corpus-ingester"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
  "typer>=0.12",
  "pydantic>=2.6",
  "pyyaml>=6.0",
  "httpx>=0.27",
  "beautifulsoup4>=4.12",
  "trafilatura>=1.9",
  "pdfminer.six>=20240706",
  "lxml>=5.2",
  "numpy>=1.26,<2.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-cov>=5.0",
  "pytest-asyncio>=0.23",
  "vcrpy>=6.0",
  "syrupy>=4.6",
  "ruff>=0.4",
  "mypy>=1.10",
]

[project.scripts]
ingester = "legal_corpus_ingester.cli:app"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --cov=src/legal_corpus_ingester --cov-report=term-missing --cov-fail-under=80"

[tool.coverage.report]
fail_under = 80
show_missing = true

[tool.ruff]
line-length = 100
target-version = "py310"
```

**Step 2: Write minimal package init**

```python
# src/legal_corpus_ingester/__init__.py
"""Legal corpus ingester — fetches, cleans, chunks, embeds, publishes legal corpus."""
__version__ = "0.1.0"
```

**Step 3: Verify install works**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
```

Expected: install succeeds, `ingester --help` works (even though CLI is a stub — Typer will exit gracefully).

**Step 4: Verify pytest runs on empty test dir**

```bash
mkdir -p tests
pytest
```

Expected: `no tests ran in 0.XXs` exit 5.

**Step 5: Commit**

```bash
git add pyproject.toml src/legal_corpus_ingester/__init__.py
git commit -m "chore: add pyproject.toml + package init (Task 2)"
```

---

### Task 3: Documentation skeleton — PRINCIPLES.md + automations/

**Files:**
- Create: `legal-corpus-ingester/PRINCIPLES.md`
- Create: `legal-corpus-ingester/automations/README.md`
- Create: `legal-corpus-ingester/automations/.gitkeep`
- Create: `legal-corpus-ingester/docs/adr/README.md`

**Step 1: Write PRINCIPLES.md**

Content: 14 ADRs from the reference plan, plus constraint-native design principles, funding bar (excludes VC-funded orgs), license bar (Apache 2.0 / MIT / BSD / MPL 2.0 / public domain).

**Step 2: Write automations/README.md**

Content: index of the 8 automations table from this plan's Automation Stack section.

**Step 3: Write docs/adr/README.md**

ADR-001 through ADR-014 as separate files come in later tasks; the README lists them.

**Step 4: Verify structure**

```bash
tree -a -L 3 . | head -40
```

Expected: directories and files match the expected skeleton.

**Step 5: Commit**

```bash
git add PRINCIPLES.md automations/ docs/
git commit -m "docs: add PRINCIPLES + automations + ADR skeleton (Task 3)"
```

---

### Task 4: types.py — ProvenanceRecord dataclass + test

**Files:**
- Create: `src/legal_corpus_ingester/types.py`
- Create: `tests/unit/test_types.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_types.py
from datetime import datetime, timezone
from legal_corpus_ingester.types import ProvenanceRecord

def test_provenance_record_requires_all_fields():
    p = ProvenanceRecord(
        source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
        fetch_timestamp="2026-07-04T12:00:00Z",
        license="CC-BY-4.0",
        upstream_version="20160504",
        content_sha256="a" * 64,
        source_name="eurlex",
        fetcher_class="fetchers.eurlex.EurLexFetcher",
    )
    assert p.license == "CC-BY-4.0"
    assert len(p.content_sha256) == 64

def test_provenance_record_is_frozen():
    import dataclasses
    from legal_corpus_ingester.types import ProvenanceRecord
    p = ProvenanceRecord(
        source_url="x", fetch_timestamp="x", license="x",
        upstream_version=None, content_sha256="x", source_name="x",
        fetcher_class="x",
    )
    try:
        p.license = "MIT"
        raise AssertionError("Expected FrozenInstanceError")
    except dataclasses.FrozenInstanceError:
        pass
```

**Step 2: Run to fail**

```bash
pytest tests/unit/test_types.py -v
```

Expected: `ModuleNotFoundError: No module named 'legal_corpus_ingester.types'` or equivalent.

**Step 3: Implement types.py**

```python
# src/legal_corpus_ingester/types.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class ProvenanceRecord:
    source_url: str
    fetch_timestamp: str
    license: str
    upstream_version: Optional[str]
    content_sha256: str
    source_name: str
    fetcher_class: str
```

**Step 4: Run to pass**

```bash
pytest tests/unit/test_types.py -v
```

Expected: 2 passed.

**Step 5: Commit**

```bash
git add src/legal_corpus_ingester/types.py tests/unit/test_types.py
git commit -m "feat(types): add ProvenanceRecord dataclass (Task 4)"
```

---

### Task 5: types.py — FetchResult + CleanedDocument + Chunk + Corpus

**Files:**
- Modify: `src/legal_corpus_ingester/types.py`
- Modify: `tests/unit/test_types.py`

**Step 1: Write failing tests for each dataclass**

Test that:
- `FetchResult(source_name, raw_bytes, mime_type, upstream_metadata, provenance)` — mime_type in `{"text/html", "application/pdf", "application/xml", "text/plain"}`
- `CleanedDocument(text, has_sections, headers, provenance)` — headers dict has jurisdiction key
- `Chunk(text, section, metadata, provenance, offset_start, offset_end)` — offsets non-negative
- `Corpus(chunks, embeddings, corpus_files)` — embeddings dtype float32, shape (n, 1024), L2 norm ~= 1.0

**Step 2: Run to fail**

Expected: `ImportError` on each new type.

**Step 3: Implement**

Add to types.py: `FetchResult`, `CleanedDocument`, `Chunk`, `Corpus` (with numpy for embeddings). Follow the design in `~/.claude/plans/delightful-humming-tome.md` Interface Contracts section.

**Step 4: Run to pass**

Expected: all tests pass.

**Step 5: Commit**

```bash
git add src/legal_corpus_ingester/types.py tests/unit/test_types.py
git commit -m "feat(types): add FetchResult/CleanedDocument/Chunk/Corpus (Task 5)"
```

---

### Task 6: errors.py — typed exception hierarchy

**Files:**
- Create: `src/legal_corpus_ingester/errors.py`
- Create: `tests/unit/test_errors.py`

**Step 1: Failing test**

Test that these exceptions exist and inherit from a base `IngesterError`:
- `UpstreamNotFoundError`, `SchemaDriftError`, `RateLimitedWarning`, `LicenseDriftError`, `EmbedEndpointError`, `IndexMismatchError`, `PublishError`, `RoundTripValidationError`, `LegalReviewGateError`, `CorpusMismatchError`.

**Step 2–5**: implement, run, commit.

---

### Task 7: config.py — Pydantic Settings

**Files:**
- Create: `src/legal_corpus_ingester/config.py`
- Create: `tests/unit/test_config.py`
- Create: `.env.example`

**Step 1: Failing test**

Test that:
- `Settings()` loads with defaults when no env vars set
- Setting `INGESTER_OUT_DIR=/tmp/foo` env var flows into `settings.out_dir`
- Setting `INGESTER_LOCALAI_URL` flows into `settings.localai_url`
- `settings.state_dir`, `settings.config_dir`, `settings.corpus_dir` all resolve as `Path` objects

**Step 2: Run to fail**.

**Step 3: Implement**

```python
# src/legal_corpus_ingester/config.py
from __future__ import annotations
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="INGESTER_")
    out_dir: Path = Path("./out")
    state_dir: Path = Path("./state")
    config_dir: Path = Path("./config")
    corpus_dir: Path = Path("./out/current/corpus")
    localai_url: str = "http://localhost:8080/v1"
    localai_model: str = "apertus-8b-instruct"
    log_level: str = "INFO"
```

Add `pydantic-settings` to `pyproject.toml` deps.

**Step 4: Run to pass**.

**Step 5: Commit**.

---

### Task 8: Chunker parity — vendor + snapshot

**Files:**
- Create: `src/legal_corpus_ingester/chunkers/text_utils.py`
- Create: `tests/snapshot/test_chunker_parity.py`
- Create: `tests/fixtures/corpus/gdpr_placeholder.txt`

**Step 1: Copy `terms-analysis::embedding.py::chunk_text` verbatim into `text_utils.py`**

Read `../terms-analysis/src/backend/app/services/embedding.py`; find `chunk_text(text, chunk_size=800, overlap=100)`; copy the function body verbatim. Add a `__version__ = "v1.0.0-vendored-from-terms-analysis@<sha>"` module constant.

**Step 2: Copy the placeholder GDPR fixture from terms-analysis**

Read `terms-analysis/data/legal_corpus/eu/gdpr.txt`; copy into `tests/fixtures/corpus/gdpr_placeholder.txt`.

**Step 3: Write snapshot test**

```python
# tests/snapshot/test_chunker_parity.py
from pathlib import Path
from legal_corpus_ingester.chunkers.text_utils import chunk_text

def test_chunker_snapshot_matches_terms_analysis(snapshot):
    text = Path("tests/fixtures/corpus/gdpr_placeholder.txt").read_text()
    chunks = list(chunk_text(text))
    assert chunks == snapshot
```

**Step 4: Run once to generate snapshot**

```bash
pytest tests/snapshot/test_chunker_parity.py --snapshot-update
```

Then re-run without `--snapshot-update`; expected: pass.

**Step 5: Commit**

```bash
git add src/legal_corpus_ingester/chunkers/ tests/snapshot/ tests/fixtures/corpus/
git commit -m "feat(chunkers): vendor chunk_text + snapshot parity test (Task 8)"
```

---

### Task 9: Source YAML schema (Pydantic model + validator)

**Files:**
- Create: `src/legal_corpus_ingester/sources/schema.py`
- Create: `tests/unit/test_sources_schema.py`

**Step 1: Failing test**

Test that:
- Valid EUR-Lex config parses.
- Unknown jurisdiction code raises validation error.
- Missing `license.spdx` raises.
- `refresh.cadence` outside `{weekly, monthly, quarterly, event-driven}` raises.

**Step 2–5:** implement Pydantic schema (see reference plan Interface Contracts) + tests + commit.

---

### Task 10: Sources registry loader

**Files:**
- Create: `src/legal_corpus_ingester/sources/registry.py`
- Create: `tests/unit/test_sources_registry.py`
- Create: `tests/fixtures/sources/eurlex.yaml` (sample from reference plan)

**Step 1: Failing test**

- `registry.load_all("tests/fixtures/sources/")` returns a dict keyed by source name.
- Invalid YAML raises with helpful error message including filename.
- Registry resolves `pipeline.fetcher: "fetchers.eurlex.EurLexFetcher"` as a class path (no import until called — lazy).

**Step 2–5**: implement, test, commit.

---

### Task 11: scripts/sync_jurisdictions.py

**Files:**
- Create: `scripts/sync_jurisdictions.py`
- Create: `src/legal_corpus_ingester/jurisdictions.py` (generated)
- Create: `tests/unit/test_jurisdictions.py`

**Step 1: Failing test**

- Generated `jurisdictions.py` contains a `JURISDICTION_CODES: frozenset[str]` matching `terms-analysis::schemas.py::Jurisdiction` Literal.
- Running the sync script twice is idempotent.

**Step 2:** Implement the sync script that reads terms-analysis's `schemas.py`, extracts the `Jurisdiction = Literal["US-CA", ...]` values, generates `jurisdictions.py`.

**Step 3–5**: run, verify, commit.

---

### Task 12: License audit hasher (per Gap E)

**Files:**
- Create: `src/legal_corpus_ingester/provenance/license_audit.py`
- Create: `tests/unit/test_license_audit.py`

**Step 1: Failing test**

- `hash_license_page(url_or_path)` returns SHA256 of normalized (whitespace-collapsed) content.
- `check_license_drift(source_name, current_hash)` returns `DRIFT` / `NO_CHANGE` / `NEW` based on stored baseline in `state/license-hashes.json`.
- SPDX mismatch → returns `SPDX_DRIFT` regardless of hash.

**Step 2–5**: implement, test, commit.

---

### Task 13: Provenance tracker (per Gap D)

**Files:**
- Create: `src/legal_corpus_ingester/provenance/tracker.py`
- Create: `tests/unit/test_provenance_tracker.py`

**Step 1: Failing test**

- `ProvenanceTracker().record(source, url, license, upstream_version)` produces a `ProvenanceRecord` with valid ISO-8601 UTC timestamp + SHA256 content hash.
- Serializes deterministically (same content → identical JSON).
- Roundtrip: `record → json.dumps → json.loads → ProvenanceRecord` byte-identical.

**Step 2–5**: implement, test, commit.

---

### Task 14: MANIFEST schema + writer (per Gap I / ADR-008)

**Files:**
- Create: `src/legal_corpus_ingester/pipeline/manifest.py`
- Create: `tests/unit/test_manifest.py`

**Step 1: Failing test**

- `Manifest.write(bundle_dir, corpus_version, chunker_version, embedder_model, embedder_revision, sources)` writes a valid YAML file.
- Round-trip: `Manifest.load(bundle_dir)` reproduces the same object.
- Missing required field raises validation error.
- corpus_version follows `YYYY.MM.PATCH` calver.

**Step 2–5**: implement, test, commit.

---

### Task 15: Grace-period status resolver (per Gap H / ADR-010)

**Files:**
- Create: `src/legal_corpus_ingester/pipeline/status_rules.py`
- Create: `tests/unit/test_status_rules.py`

**Step 1: Failing test**

- `resolve_status({"default": "not_yet_in_force", "transitions": [{"on": "2027-01-01", "to": "in_force"}]}, today=date(2026, 7, 4))` returns `"not_yet_in_force"`.
- Same call with `today=date(2027, 1, 1)` returns `"in_force"`.
- Same call with `today=date(2027, 6, 15)` still returns `"in_force"`.
- Multiple transitions apply in order.

**Step 2–5**: implement, test, commit.

---

### Task 16: Fetcher Protocol + BaseFetcher (retry + rate-limit)

**Files:**
- Create: `src/legal_corpus_ingester/fetchers/base.py`
- Create: `tests/unit/test_fetchers_base.py`

**Step 1: Failing test**

- BaseFetcher retries on 429 with exponential backoff (mocked httpx).
- 3 consecutive failures raise `UpstreamNotFoundError`.
- Rate limiter respects `rate_limit_rps` config.
- Provenance recorded on every fetch.

**Step 2–5**: implement, test, commit.

---

### Task 17: EurLexFetcher (first concrete fetcher, VCR cassette)

**Files:**
- Create: `src/legal_corpus_ingester/fetchers/eurlex.py`
- Create: `tests/integration/test_eurlex_fetcher.py`
- Create: `tests/fixtures/cassettes/eurlex/gdpr_fetch.yaml` (recorded once with `--vcr-record=once`)

**Step 1: Failing test with VCR cassette (mode='none')**

- `EurLexFetcher.fetch({celex_id: "32016R0679"})` returns a FetchResult with mime_type XML.
- Provenance carries CELEX ID as upstream_version.
- License field is `"CC-BY-4.0"`.

**Step 2: Run first time with `--vcr-record=once` to record cassette**

Live fetch against EUR-Lex, cassette written.

**Step 3: Sanitize cassette** (strip auth headers, cookies).

**Step 4: Re-run with `record_mode='none'` — should pass from cassette**.

**Step 5: Commit** cassette + fetcher + test.

---

### Task 18: Akoma Ntoso XML cleaner

**Files:**
- Create: `src/legal_corpus_ingester/cleaners/xml_akn.py`
- Create: `tests/unit/test_cleaner_akn.py`

**Step 1: Failing test**

- Given EUR-Lex Akoma Ntoso XML fixture, cleaner produces `CleanedDocument` with:
  - `text` containing `## Article N — Title` section markers
  - `has_sections=True`
  - `headers` populated with jurisdiction (`GDPR`), law, source, effective_date.

**Step 2–5**: implement using lxml, test with a small AKN fixture, commit.

---

### Task 19: Sectioned + plain chunkers (using vendored text_utils)

**Files:**
- Create: `src/legal_corpus_ingester/chunkers/sectioned.py`
- Create: `src/legal_corpus_ingester/chunkers/plain.py`
- Create: `src/legal_corpus_ingester/chunkers/factory.py`
- Create: `tests/unit/test_chunkers.py`

**Step 1: Failing test**

- SectionedChunker produces chunks with `f"{title}\n{body}"` format matching `_parse_corpus_file` output byte-for-byte on the GDPR placeholder fixture.
- PlainChunker uses 800/100 window; SectionedChunker uses 1000/150.
- Factory dispatches based on `CleanedDocument.has_sections`.

**Step 2–5**: implement, test, commit.

---

### Task 20: LocalAI embedder (Apertus-8B) with mock test

**Files:**
- Create: `src/legal_corpus_ingester/embedders/base.py`
- Create: `src/legal_corpus_ingester/embedders/localai.py`
- Create: `src/legal_corpus_ingester/embedders/mean_pool.py`
- Create: `tests/unit/test_embedder_localai.py`

**Step 1: Failing test**

- `LocalAIEmbedder(url=..., model="apertus-8b-instruct").embed([Chunk(...)])` returns `(1, 1024) float32` matrix with unit L2 norm (mocked httpx response).
- `revision()` returns SHA256 of the model identifier (pinned per L6).
- Health check returns True on 200, False on connection error.
- Batches of size > `batch_size` split correctly.

**Step 2–5**: implement with httpx AsyncClient, mock endpoint, test, commit.

---

### Task 21: Publisher Protocol + FilesystemPublisher

**Files:**
- Create: `src/legal_corpus_ingester/publishers/base.py`
- Create: `src/legal_corpus_ingester/publishers/filesystem.py`
- Create: `tests/unit/test_publisher_fs.py`

**Step 1: Failing test**

- `FilesystemPublisher.publish(corpus, PublishTarget(kind="filesystem", path=tmp_path))` writes:
  - `corpus/<jur>/<law>.txt` files with proper headers
  - `index/legal_kb.npy` with correct shape + dtype + L2 norm
  - `index/legal_kb_metadata.json` matching chunks
  - `MANIFEST.yaml` with all pinned versions
  - `checksums.txt` with SHA256 of every file
- `PublishReceipt` returned has chunk_count, matrix_sha256, metadata_sha256.
- Atomic writes: uses tmp file + rename.

**Step 2–5**: implement, test, commit.

---

### Task 22: TermsAnalysisPublisher (symlink + copy hybrid per L2 / ADR-012)

**Files:**
- Create: `src/legal_corpus_ingester/publishers/terms_analysis.py`
- Create: `src/legal_corpus_ingester/publishers/latest_symlink.py`
- Create: `tests/integration/test_publisher_terms_analysis.py`

**Step 1: Failing test**

- Publish writes `out/2026.07.0/` then atomically symlinks `out/current -> 2026.07.0`.
- Consumer path `terms-analysis/data/corpus_bundle` symlink → `out/current`.
- Small `.npy` + `.json` files ALSO copied into `terms-analysis/data/` (for hot-reload safety).
- `--copy` flag forces direct copy (no symlinks).
- SIGHUP is sent to a mock FastAPI process (test uses a subprocess mock).
- Rollback: repointing symlink to prior version works.

**Step 2–5**: implement, test, commit.

---

### Task 23: Tarball publisher (per L2 alt)

**Files:**
- Create: `src/legal_corpus_ingester/publishers/tarball.py`
- Create: `tests/unit/test_publisher_tarball.py`

**Step 1: Failing test**

- Produces `out/<version>/legal-corpus-<version>.tar.gz` (NOT zstd per HR2).
- Tarball contains every file in the bundle.
- SHA256 of tarball recorded in receipt.
- Round-trip: extract + verify.

**Step 2–5**: implement (using stdlib tarfile + gzip), test, commit.

---

### Task 24: Pipeline orchestrator

**Files:**
- Create: `src/legal_corpus_ingester/pipeline/orchestrator.py`
- Create: `src/legal_corpus_ingester/pipeline/state.py`
- Create: `tests/integration/test_orchestrator.py`

**Step 1: Failing test**

- `Orchestrator.run(source_name)` runs fetch → clean → chunk → embed → publish.
- On fetch failure: checkpoint records `stage=fetch_failed`; next run resumes.
- On embed failure: publish blocked; chunks preserved for retry.
- Idempotent: unchanged upstream produces byte-identical output.

**Step 2–5**: implement, test, commit.

---

### Task 25: License-drift check integration

**Files:**
- Modify: `src/legal_corpus_ingester/pipeline/orchestrator.py`
- Create: `tests/integration/test_license_drift_gate.py`

**Step 1: Failing test**

- Orchestrator BLOCKS publish when SPDX changes (CC-BY-4.0 → CC-BY-NC).
- Orchestrator WARNS on text hash change with same SPDX.
- ALERTS.md written under `out/<version>/`.
- Exit code non-zero on BLOCK.

**Step 2–5**: implement, test, commit.

---

### Task 26: Legal-review gate (APPROVAL.yaml verification)

**Files:**
- Create: `src/legal_corpus_ingester/pipeline/approval_gate.py`
- Create: `tests/unit/test_approval_gate.py`
- Create: `tests/fixtures/approvals/sg_sso_terms.yaml`
- Create: `tests/fixtures/approvals/expired.yaml`

**Step 1: Failing test**

- Gate PASSES when APPROVAL.yaml exists + signed_artifact SHA256 matches + today < expiry + source_id matches.
- Gate BLOCKS on missing file → `LegalReviewGateError`.
- Gate BLOCKS on expired approval.
- Gate BLOCKS on SHA256 mismatch.
- Gate WARNS at T-60d before expiry.

**Step 2–5**: implement, test, commit.

---

### Task 27: CLI — Typer entry points

**Files:**
- Create: `src/legal_corpus_ingester/cli.py`
- Create: `tests/cli/test_cli_smoke.py`

**Step 1: Failing test**

- `ingester --help` returns exit 0 with usage.
- `ingester init` scaffolds `config/ out/ state/` dirs.
- `ingester sources list` returns configured sources.
- `ingester status` returns exit 0 with freshness table.
- `ingester fetch <source> --dry-run` returns exit 0 without writing.
- Every subcommand has `--help`.

**Step 2–5**: implement, test, commit.

---

### Task 28: Consumer-side change in terms-analysis — load_from_bundle()

**Files:**
- Modify: `terms-analysis/src/backend/app/services/legal_kb.py` (add `load_from_bundle` method + `CorpusMismatchError`)
- Create: `terms-analysis/src/backend/tests/test_legal_kb_bundle.py`

**Step 1: Failing test**

- `LegalKnowledgeBase.load_from_bundle(bundle_dir)` reads MANIFEST.yaml, `index/legal_kb.npy`, `index/legal_kb_metadata.json`.
- Raises `CorpusMismatchError` when `chunker_version` in MANIFEST doesn't match expected.
- Raises when `embedder_model` mismatches.
- Raises when `embedder_revision` mismatches.
- On mismatch, API layer returns HTTP 503 with `X-Corpus-Mismatch` header naming drift dimension.

**Step 2: Implement in terms-analysis (dispatch a Coder scoped to that repo)**.

**Step 3: Run terms-analysis pytest**: `cd ../terms-analysis && python -m pytest src/backend/tests/test_legal_kb_bundle.py -v`. Expected: pass.

**Step 4: Verify no regression**: full terms-analysis suite still green.

**Step 5: Commit** in terms-analysis; ingester repo unchanged this task.

---

### Task 29: End-to-end round-trip test

**Files:**
- Create: `tests/e2e/test_round_trip_gdpr.py`

**Step 1: Failing test**

Given the ingester run against the EUR-Lex VCR cassette for GDPR:
- Publish produces a bundle at `tmp/2026.07.0/`.
- Dynamically import `terms_analysis.src.backend.app.services.legal_kb.LegalKnowledgeBase`.
- `kb.load_from_bundle(tmp/2026.07.0)` succeeds.
- `kb.retrieve("consent lawful basis")` returns non-empty list.
- Top chunk's jurisdiction is `GDPR`.
- Top chunk contains a GDPR Art. 6 reference.

**Step 2–5**: implement, run, commit.

---

### [COMPLETE] Task 30: Weekly VCR drift canary (automations/vcr-drift.md + workflow)

**Files:**
- Create: `.github/workflows/vcr-drift.yml`
- Create: `automations/vcr-drift.md`
- Create: `scripts/vcr_drift_report.py`

**Step 1: Write automations/vcr-drift.md**

Describes: cron `0 4 * * 0` (Sunday 4am), what it does (re-records cassettes with `--vcr-record=all`, diffs), what artifact it produces (a GitHub issue with diff summary), what escalation looks like on drift.

**Step 2: Write workflow YAML**

Uses `runs-on: self-hosted` per L3. Runs `pytest --vcr-record=all tests/integration/`, then `python scripts/vcr_drift_report.py`.

**Step 3: Test locally**

```bash
act -W .github/workflows/vcr-drift.yml   # if act installed
# or just: pytest --vcr-record=all tests/integration/
```

**Step 4: Verify report script produces summary**.

**Step 5: Commit**.

---

### [COMPLETE] Task 31: Pre-commit hook

**Files:**
- Create: `.githooks/pre-commit`
- Create: `scripts/install-hooks.sh`
- Create: `automations/pre-commit.md`

**Step 1: Write .githooks/pre-commit**

Runs: `ruff check .`, `mypy src/`, `pytest tests/unit/ -q`, sha256 audit of `state/license-hashes.json` (fail if any tracked source has drift).

**Step 2: Write install-hooks.sh** that `git config core.hooksPath .githooks`.

**Step 3: Document in automations/pre-commit.md**.

**Step 4: Run hook manually to verify**.

**Step 5: Commit**.

---

### [COMPLETE] Task 32: CI workflow (PR + push)

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `automations/ci-pr.md`

**Step 1: Write ci.yml**

- `runs-on: self-hosted`
- Runs on PR + push to main
- Steps: install → ruff → mypy → pytest unit + integration → coverage report → upload artifact

**Step 2: Document in automations/ci-pr.md**.

**Step 3–5**: verify, commit.

---

### [COMPLETE] Task 33: Nightly health check workflow

**Files:**
- Create: `.github/workflows/health.yml`
- Create: `scripts/health_check.py`
- Create: `automations/health-check.md`

**Step 1: Write health.yml**

Cron `0 3 * * *`. Runs `ingester status`, checks every source for freshness, writes report to `out/health/YYYY-MM-DD.md`.

**Step 2: Write health_check.py** that reads latest manifest per source, computes freshness lag, writes markdown table.

**Step 3–5**: document, verify, commit.

---

### Task 34: Weekly refresh workflow

**Files:**
- Create: `.github/workflows/refresh.yml`
- Create: `automations/refresh.md`

**Step 1: Write refresh.yml**

Cron `0 3 * * 0`. Runs `ingester refresh --all`. On success, opens PR against terms-analysis with corpus bundle diff.

**Step 2–5**: document, verify, commit.

---

### Task 35: Approval expiry watcher workflow

**Files:**
- Create: `.github/workflows/approval-expiry.yml`
- Create: `scripts/check_approvals.py`
- Create: `automations/approval-expiry.md`

**Step 1: Write approval-expiry.yml**

Cron daily. Walks all APPROVAL.yaml files, checks `today < expiry`, emits `expiring_soon` warnings at T-60d and `expired` blockers at T-0.

**Step 2–5**: implement, document, verify, commit.

---

### Task 36: `ingester audit-license <source>` subcommand

**Files:**
- Modify: `src/legal_corpus_ingester/cli.py`
- Create: `tests/cli/test_audit_license.py`

**Step 1: Failing test**

- `ingester audit-license eurlex` fetches the license URL, hashes it, compares to stored baseline, exits 0 on no-change / non-zero on SPDX drift.

**Step 2–5**: implement, test, commit.

---

### Task 37: `ingester validate-round-trip` subcommand

**Files:**
- Modify: `src/legal_corpus_ingester/cli.py`
- Modify: `tests/cli/test_cli_smoke.py`

**Step 1: Failing test**

- `ingester validate-round-trip <bundle-dir>` invokes terms-analysis's `load_from_bundle` + `retrieve` + asserts non-empty. Exit 0 on success, non-zero + `X-Corpus-Mismatch` reason on fail.

**Step 2–5**: implement, test, commit.

---

### Task 38: Retention policy CLI (per Gap A / ADR-011)

**Files:**
- Create: `src/legal_corpus_ingester/pipeline/retention.py`
- Modify: `src/legal_corpus_ingester/cli.py`
- Create: `tests/unit/test_retention.py`

**Step 1: Failing test**

- `retention.plan(out_dir)` returns list of directories to keep + list to prune (last 4 weekly + first-of-month × 12 + first-of-quarter forever).
- `ingester prune --dry-run` prints plan without deleting.
- `ingester prune --force` deletes.
- Refuses to prune `out/current` symlink target.

**Step 2–5**: implement, test, commit.

---

### Task 39: Docker + docker-compose

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `automations/docker.md`

**Step 1: Write Dockerfile**

Multi-stage: builder (installs deps), runtime (copies src + venv). Non-root user. Volume mounts for `out/`, `state/`, `config/`.

**Step 2: Write docker-compose.yml**

Two services: `ingester` (this project) + `localai` (Apertus-8B model, matches terms-analysis).

**Step 3: Test build**

```bash
docker compose build
docker compose run --rm ingester ingester status
```

**Step 4: Document usage in automations/docker.md**.

**Step 5: Commit**.

---

### Task 40: Self-hosted GitHub Actions runner setup

**Files:**
- Create: `automations/self-hosted-runner.md`
- Create: `scripts/setup_runner.sh`

**Step 1: Write automations/self-hosted-runner.md**

Documents: why self-hosted (HR4 — all data local), setup steps, runner labels, tear-down, security considerations.

**Step 2: Write scripts/setup_runner.sh**

Downloads GitHub Actions runner binary, configures it with a labeled `legal-corpus-ingester-runner`, registers as a service.

**Step 3: Test setup on user's local machine**

User runs `bash scripts/setup_runner.sh`. Verify runner appears in GitHub repo settings.

**Step 4: Trigger a workflow, verify it runs on self-hosted**.

**Step 5: Commit**.

---

## Phase 0 exit checklist

> **Progress as of 2026-07-04:** Tasks 1-33 complete and pushed. Tasks 34-40 remaining.

Before considering Phase 0 done and moving to Phase 1 (EU cluster full ingestion):

- [ ] All 40 tasks complete
- [ ] `pytest` shows 20+ tests passing, ≥80% coverage
- [ ] `ingester status` runs clean
- [ ] `ingester validate-round-trip out/2026.07.0` passes against GDPR fixture
- [ ] All 8 automations documented under `automations/`
- [ ] Self-hosted GitHub Actions runner registered + at least one workflow ran successfully
- [ ] Docker build succeeds
- [ ] Pre-commit hook enforcing ruff + mypy + pytest unit
- [ ] Consumer-side `load_from_bundle()` in terms-analysis passes full test suite
- [ ] Grumpy-developer + security-engineer peer review both PASS
- [ ] Push to GitHub as `v0.1.0` (or `2026.07.0` calver) tag

## Follow-on plans (not this doc)

- `docs/plans/2026-07-04-legal-corpus-ingester-phase1-EU.md` — EUR-Lex full ingest (GDPR + AI Act + DSA + Data Act + DMA)
- `docs/plans/2026-07-04-legal-corpus-ingester-phase2-US-fed.md` — govinfo.gov (COPPA, HIPAA, GLBA, FERPA, FCRA, FTC §5)
- `docs/plans/2026-07-04-legal-corpus-ingester-phase3-US-state.md` — CA leginfo + Open States + top-tier states
- `docs/plans/2026-07-04-legal-corpus-ingester-phase4-APAC-INTL.md` — Isaacus + AU + SG (gated) + HUDOC + CURIA + soft-law + international courts
- `docs/plans/2026-07-04-legal-corpus-ingester-phase5-refresh.md` — remaining state laws + cron loop + amendment tripwires

## References

- Source design doc: `~/.claude/plans/delightful-humming-tome.md` — all 14 ADRs, gap answers, locked decisions
- Consumer contract: `terms-analysis/src/backend/app/services/legal_kb.py`
- Aggregator strategy: `terms-analysis/docs/plans/2026-07-04-corpus-AGG.md` (once written from plan-mode-staged content)
- Jurisdiction-specific plans: `terms-analysis/docs/plans/2026-07-04-corpus-{EU,US,APAC,APAC-child-agency,INTL}.md`
- Governance: `terms-analysis/.claude/library/LIB-PRINCIPLES.md` (P8 role separation, P9 pre-push review)
- Skills to invoke during execution: @superpowers:executing-plans @superpowers:subagent-driven-development @superpowers:test-driven-development @superpowers:verification-before-completion
