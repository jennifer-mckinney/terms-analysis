# AGENT & SKILLS SURFACE AREA AUDIT
## AI Terms & Policies Reviewer — Tooling Architecture & Gap Analysis

**Project:** terms-analysis
**Date:** 2026-02-07
**Scope:** Complete inventory of Claude Code skills, agent capabilities, tool requirements, and recommendations
**Reference:** SRS AI Systems agent teams analysis (sunny-humming-hearth.md)

> **Historical audit note (2026-07-03):** the `src/webapp/` inventory below (index.html / app.js / style.css) reflects the pre-Phase-4 state. Those files were deleted when the vanilla-JS SPA was retired; current UI is Streamlit only (`app_streamlit_v2.py` + `app_streamlit_legacy.py`).

---

## 1. EXECUTIVE SUMMARY

### Current Tooling Posture

| Metric | Value |
|--------|-------|
| Skills defined | 9 |
| Skills with verified tool access | 9/9 |
| Agent types used | Task subagents (Explore, Bash, general-purpose) |
| Custom agents (.claude/agents/) | 0 |
| Automation hooks | 0 (planned) |
| Test automation | Manual (`pytest -v`) |
| CI/CD pipeline | None |

### Assessment

The project has a **well-organized skill layer** (9 skills covering testing, evaluation, review, dependency audit, legal KB, and iterative development) but **no CI/CD pipeline, no automation hooks, and no custom agent definitions**. The skill definitions are clear and actionable but have not been stress-tested in practice. The current architecture is subagent-based (Task tool), which is appropriate for this project's complexity level and token budget.

---

## 2. CURRENT SKILLS INVENTORY

### 2.1 Complete Skills Catalog

| # | Skill | File | Lines | Trigger | Tools Required | PEAS Profile |
|---|-------|------|-------|---------|----------------|--------------|
| 1 | `/test-suite` | `.claude/skills/test-suite/SKILL.md` | ~30 | "run tests", "check coverage" | Bash, Read, Grep | P: coverage %, pass rate; E: pytest + src/backend; A: run commands, read output; S: stdout, coverage report |
| 2 | `/write-tests` | `.claude/skills/write-tests/SKILL.md` | ~83 | "write tests for X" | Read, Write, Edit, Bash, Grep, Glob | P: test count, coverage delta; E: source files + test dir; A: read source, write tests, run tests; S: source code, existing tests, LIB-TEST |
| 3 | `/evaluate` | `.claude/skills/evaluate/SKILL.md` | ~30 | "run evaluation", "check F1" | Bash, Read | P: F1 >= 0.70, Kappa >= 0.65; E: evaluation scripts + gold dataset; A: run scripts, read output; S: evaluation metrics |
| 4 | `/review` | `.claude/skills/review/SKILL.md` | ~50 | "review this", "check changes" | Read, Grep, Glob | P: issues found, false positive rate; E: changed files; A: read code, report issues; S: source code, diff output |
| 5 | `/webapp-testing` | `.claude/skills/webapp-testing/SKILL.md` | ~50 | "test the webapp", "browser test" | Bash, Read, Write, Edit | P: test pass rate, UI functionality; E: browser + API; A: write Playwright tests, run them; S: browser output, API responses |
| 6 | `/dependency-audit` | `.claude/skills/dependency-audit/SKILL.md` | ~40 | "audit dependency", "check license" | WebSearch, WebFetch, Read | P: IRP grade accuracy; E: web + pyproject.toml; A: search, fetch, score; S: license text, community data, legal pages |
| 7 | `/legal-kb` | `.claude/skills/legal-kb/SKILL.md` | ~60 | "update legal corpus", "add jurisdiction" | Bash, Read, Write, WebFetch | P: corpus completeness, index integrity; E: legal text sources + FAISS; A: download, chunk, embed, index; S: legal text HTML, embedding vectors |
| 8 | `/ralph-loop` | `.claude/skills/ralph-loop/SKILL.md` | ~90 | "ralph loop", "iterate on X until done" | Read, Write, Edit, Bash, Grep, Glob | P: completion promise met; E: full codebase; A: all tools; S: codebase state, test results, git history |
| 9 | `/session-start-hook` | (system skill) | — | startup hook setup | Read, Edit | P: environment ready; E: repo config; A: write hooks; S: repo structure |

### 2.2 Skill Tool Matrix

| Skill | Read | Write | Edit | Bash | Grep | Glob | WebSearch | WebFetch | Task |
|-------|------|-------|------|------|------|------|-----------|----------|------|
| `/test-suite` | YES | — | — | YES | YES | — | — | — | — |
| `/write-tests` | YES | YES | YES | YES | YES | YES | — | — | — |
| `/evaluate` | YES | — | — | YES | — | — | — | — | — |
| `/review` | YES | — | — | — | YES | YES | — | — | — |
| `/webapp-testing` | YES | YES | YES | YES | — | — | — | — | — |
| `/dependency-audit` | YES | — | — | — | — | — | YES | YES | — |
| `/legal-kb` | YES | YES | — | YES | — | — | — | YES | — |
| `/ralph-loop` | YES | YES | YES | YES | YES | YES | — | — | — |

### 2.3 Skill Dependencies & Prerequisites

| Skill | Prerequisite | Verified? |
|-------|-------------|-----------|
| `/test-suite` | pytest, pytest-cov, pytest-asyncio installed | NO — not verified in current env |
| `/write-tests` | conftest.py exists with fixtures | NO — conftest.py may not exist yet |
| `/evaluate` | Gold dataset at `src/backend/evaluation/` | PARTIAL — directory exists, dataset unknown |
| `/review` | Code changes staged or recent commits | YES — reads from working tree |
| `/webapp-testing` | Playwright installed, backend running | NO — not verified |
| `/dependency-audit` | Internet access for WebSearch/WebFetch | YES — available in this environment |
| `/legal-kb` | FAISS, sentence-transformers installed | NO — RAG pipeline not built yet |
| `/ralph-loop` | Stop hook configured | NO — hook not configured |

---

## 3. SKILL EFFECTIVENESS ANALYSIS

### 3.1 PEAS Framework per Skill

#### `/test-suite`

| Component | Definition | Assessment |
|-----------|------------|------------|
| **Performance** | Coverage %, pass rate, failure analysis quality | ADEQUATE — runs pytest with coverage, parses output |
| **Environment** | src/backend/ test directory, pytest ecosystem | ADEQUATE |
| **Actuators** | Run pytest, read output, report findings | ADEQUATE |
| **Sensors** | stdout, coverage report, failure tracebacks | ADEQUATE |

**Gap:** No automatic identification of which untested code paths are highest-risk. Runs tests but doesn't prioritize what to test next.

#### `/write-tests`

| Component | Definition | Assessment |
|-----------|------------|------------|
| **Performance** | Tests created, coverage delta, test quality | GOOD — 4-phase workflow (understand → plan → write → verify) |
| **Environment** | Source files, existing tests, LIB-TEST reference | GOOD — references coverage gap analysis |
| **Actuators** | Read source, plan tests, write tests, run tests | GOOD — full workflow |
| **Sensors** | Source code, existing tests, conftest fixtures, coverage output | GOOD |

**Gap:** No automatic conftest.py creation if missing. No parametrize heuristic (when to use `@pytest.mark.parametrize` vs separate test functions). No mutation testing guidance.

#### `/evaluate`

| Component | Definition | Assessment |
|-----------|------------|------------|
| **Performance** | F1, Kappa vs targets | UNKNOWN — evaluation pipeline not yet run |
| **Environment** | Gold dataset, evaluation scripts | UNKNOWN — scripts exist but untested |
| **Actuators** | Run evaluation, parse metrics | ADEQUATE (if scripts work) |
| **Sensors** | Evaluation output, per-category scores | ADEQUATE (if scripts work) |

**Gap:** Gold dataset may not exist or may be empty. Evaluation scripts not verified. No regression comparison (current vs previous run). This is a **high-risk unknown** — the skill may fail entirely on first use.

#### `/dependency-audit`

| Component | Definition | Assessment |
|-----------|------------|------------|
| **Performance** | Correct IRP grade, correct license identification | GOOD — structured 4-check framework |
| **Environment** | Web (license pages, community data) + local config | GOOD |
| **Actuators** | Web search, web fetch, score calculation | GOOD |
| **Sensors** | License text, PyPI pages, GitHub data, legal pages | GOOD |

**Gap:** No caching of audit results. Same dependency audited multiple times wastes tokens. No integration with `pyproject.toml` to auto-detect what needs auditing.

#### `/legal-kb`

| Component | Definition | Assessment |
|-----------|------------|------------|
| **Performance** | Corpus completeness, chunk quality, index integrity | SPECULATIVE — RAG pipeline not built |
| **Environment** | Legal text sources, FAISS, embeddings | NOT AVAILABLE — infrastructure doesn't exist yet |
| **Actuators** | Download, chunk, embed, index | NOT IMPLEMENTED |
| **Sensors** | Legal text HTML, embedding vectors, index metadata | NOT AVAILABLE |

**Gap:** This skill describes a future capability. It cannot function today. Dependencies (FAISS, sentence-transformers, modernbert-legal) are not installed. Legal corpus sources identified but not downloaded. **This skill should be marked as PLANNED, not AVAILABLE.**

#### `/ralph-loop`

| Component | Definition | Assessment |
|-----------|------------|------------|
| **Performance** | Completion promise met, iteration efficiency | ADEQUATE — well-defined protocol |
| **Environment** | Full codebase, state file, git history | GOOD |
| **Actuators** | All tools, state management | GOOD |
| **Sensors** | Codebase state, test results, git log, state file | GOOD |

**Gap:** Stop hook not configured. Without the hook, the loop relies on manual re-invocation. The skill describes the protocol but doesn't auto-install the hook. Additionally, no max-iteration safety net is enforced at the skill level (it's described but not enforced programmatically).

### 3.2 Skill Maturity Matrix

| Skill | Definition Quality | Tool Coverage | Prerequisites Met | Battle-Tested | Overall Maturity |
|-------|-------------------|---------------|-------------------|---------------|------------------|
| `/test-suite` | HIGH | FULL | UNKNOWN | NO | **DRAFT** |
| `/write-tests` | HIGH | FULL | PARTIAL | NO | **DRAFT** |
| `/evaluate` | MEDIUM | ADEQUATE | UNKNOWN | NO | **SPECULATIVE** |
| `/review` | HIGH | FULL | YES | NO | **DRAFT** |
| `/webapp-testing` | MEDIUM | ADEQUATE | UNKNOWN | NO | **SPECULATIVE** |
| `/dependency-audit` | HIGH | FULL | YES | YES (used in session) | **TESTED** |
| `/legal-kb` | HIGH | ADEQUATE | NO | NO | **PLANNED** |
| `/ralph-loop` | HIGH | FULL | NO (no hook) | NO | **DRAFT** |

**Maturity Levels:**
- **TESTED**: Used successfully in a real session
- **DRAFT**: Well-defined but not yet exercised
- **SPECULATIVE**: Depends on unverified infrastructure
- **PLANNED**: Describes future capability that doesn't exist yet

---

## 4. SUBAGENT ARCHITECTURE ANALYSIS

### 4.1 Current Subagent Usage

The project uses Claude Code's **Task tool** to spawn subagents for:

| Use Case | Subagent Type | Typical Prompt | Token Cost | Effectiveness |
|----------|---------------|----------------|------------|---------------|
| Codebase exploration | `Explore` | "Find all files matching X" | LOW (~2k tokens) | HIGH — fast, focused |
| Multi-file research | `general-purpose` | "Read these 5 files and summarize" | MEDIUM (~10k tokens) | HIGH — parallel reads |
| Background tasks | `Bash` (background) | "Run tests and report" | LOW (~1k tokens) | HIGH — non-blocking |
| Deep research | `general-purpose` | "Research dependency X against requirements" | HIGH (~20k tokens) | HIGH — thorough |

### 4.2 Subagent Cost-Benefit Analysis

| Approach | Context Cost | Latency | Accuracy | Best For |
|----------|-------------|---------|----------|----------|
| Direct tool call (Read/Grep/Glob) | MINIMAL — result in main context | ~1s | HIGH | Known file paths, specific searches |
| Task subagent (Explore) | LOW — summary returned | ~10s | HIGH | Broad codebase exploration |
| Task subagent (general-purpose) | MEDIUM — full research | ~30s | HIGH | Multi-step research |
| Task subagent (background) | MINIMAL until read | ~30s+ | HIGH | Independent parallel work |

### 4.3 When to Use Subagents vs Direct Tools

**USE DIRECT TOOLS when:**
- You know the file path (Read)
- You're searching for a specific string (Grep)
- You need a file listing (Glob)
- The task is 1-3 tool calls

**USE SUBAGENTS when:**
- Exploring an unfamiliar part of the codebase (Explore agent)
- Research requires 4+ tool calls with decision-making
- Work can be parallelized (multiple background agents)
- Results are large and should be summarized before entering main context
- Task is independent and doesn't need real-time interaction

### 4.4 Subagent Patterns for This Project

| Pattern | Description | Example |
|---------|-------------|---------|
| **Parallel research** | Spawn 2-3 agents to research independent questions simultaneously | Audit 3 dependencies in parallel |
| **Read-and-summarize** | Agent reads large files, returns structured summary | "Read all 7 service files, report functions and line counts" |
| **Test-and-report** | Background agent runs tests, main agent continues work | Run full test suite while writing new code |
| **Explore-then-act** | Agent explores codebase, main agent acts on findings | "Find all places where X is used" → main agent makes changes |

---

## 5. MISSING CAPABILITIES — GAP ANALYSIS

### 5.1 Skills That Should Exist But Don't

| # | Proposed Skill | Trigger | Purpose | Priority | Tool Requirements |
|---|----------------|---------|---------|----------|-------------------|
| 1 | `/security-scan` | "security check", "scan for vulnerabilities" | Audit input validation, SSRF risks, CORS config, secret exposure | **P1** | Read, Grep, Glob, Bash |
| 2 | `/migration-plan` | "migrate to Ollama", "switch to SaulLM" | Guided LLM/embedding migration with rollback checkpoints | **P1** | Read, Write, Edit, Bash, WebSearch |
| 3 | `/golden-test-set` | "create golden test set", "add test case" | Manage labeled policy→finding pairs for F1/Kappa evaluation | **P1** | Read, Write, Edit, Bash |
| 4 | `/confidence-calibrate` | "calibrate confidence", "tune thresholds" | Empirically calibrate confidence formula against golden test set | **P2** | Read, Edit, Bash |
| 5 | `/pattern-audit` | "audit patterns", "check false positives" | Analyze rule patterns for precision/recall, suggest improvements | **P2** | Read, Grep, Bash |
| 6 | `/architecture-inventory` | "what do we have", "map the codebase" | Generate complete inventory of files, dependencies, design artifacts | **P3** | Read, Glob, Grep, Bash |

### 5.2 Missing Automation (Hooks)

| # | Hook Type | Trigger | Purpose | Priority |
|---|-----------|---------|---------|----------|
| 1 | Pre-push | `git push` | Run tests, check coverage doesn't regress | **P1** |
| 2 | Post-commit | `git commit` | Lint changed files, check for secrets | **P2** |
| 3 | Session start | Claude session begins | Verify environment (deps installed, DB exists) | **P2** |
| 4 | Stop hook | Session end | Ralph loop continuation (if active) | **P3** |

### 5.3 Missing Infrastructure

| # | Infrastructure | Purpose | Status | Priority |
|---|---------------|---------|--------|----------|
| 1 | conftest.py | Shared test fixtures (sample_finding, sample_policy_text, etc.) | NOT CREATED | **P0** |
| 2 | .pre-commit-config.yaml | Automated pre-commit checks | NOT CREATED | **P1** |
| 3 | GitHub Actions CI | Automated test + lint on PR | NOT CREATED | **P1** |
| 4 | Gold dataset | Labeled policy→finding pairs | NOT CREATED | **P1** |
| 5 | FAISS index infrastructure | Vector store for legal corpus | NOT CREATED | **P2** |
| 6 | Evaluation runner in CI | F1/Kappa gates on every PR | NOT CREATED | **P2** |

---

## 6. AGENT TEAMS ASSESSMENT

### 6.1 Would Agent Teams Help This Project?

**Reference:** SRS AI Systems assessed Agent Teams as **WAIT** due to experimental status, token cost, and incompatibility with their 99.9% precision requirement.

**Assessment for terms-analysis: ALSO WAIT, but for different reasons.**

| Factor | SRS Project | Terms-Analysis | Verdict |
|--------|-------------|----------------|---------|
| Precision requirement | 99.9% (pharma-grade) | Macro F1 >= 0.70 | LOWER bar — Teams' reliability issues less critical |
| Project complexity | 240+ files, 100k+ LOC, Neo4j + Qdrant + PostgreSQL | ~15 files, ~2k LOC, SQLite | **OVERKILL** — project is too small for multi-agent coordination |
| Current agent count | 11 custom agents | 0 custom agents, 9 skills | **INSUFFICIENT BASE** — nothing to coordinate yet |
| Token budget | Enterprise (high throughput) | Individual/small team | **COST-PROHIBITIVE** — 4-5x token cost unjustifiable |
| Bottleneck | Execution of well-planned work | Building the foundation (tests, RAG, evaluation) | **WRONG TOOL** — need implementation, not coordination |

### 6.2 What Would Change the Verdict

1. **Project grows to 50+ files** with distinct modules that can be worked on independently
2. **Multiple humans** contributing code that needs coordinated review
3. **RAG pipeline** is built and requires adversarial validation (retrieval agent vs validation agent)
4. **Agent Teams exits experimental** with reliable task tracking

### 6.3 What to Use Instead (Now)

| Need | Solution | Why |
|------|----------|-----|
| Parallel research | Task subagents (Explore, general-purpose) | Lightweight, token-efficient, proven |
| Iterative development | `/ralph-loop` skill | Self-referential loop without multi-agent overhead |
| Code review | `/review` skill | Single-agent checklist, adequate for current codebase size |
| Test writing | `/write-tests` skill | Structured 4-phase workflow |
| Dependency auditing | `/dependency-audit` skill | Web-enabled single-agent research |

---

## 7. SKILL DESIGN PATTERNS

### 7.1 What Makes a Good Skill (Lessons from SRS)

| Principle | Description | Our Implementation |
|-----------|-------------|-------------------|
| **Clear trigger** | Users shouldn't guess; skill name and description explain when to use | GOOD — all skills have trigger phrases |
| **Tool allowlist** | Skills declare exactly which tools they need | GOOD — `allowed-tools` in frontmatter |
| **Phased workflow** | Complex skills have numbered phases (understand → plan → execute → verify) | GOOD — `/write-tests` has 4 phases |
| **Library references** | Skills point to relevant LIB-* docs for context | GOOD — `/write-tests` references LIB-TEST |
| **Arguments** | Skills accept parameters via `$ARGUMENTS` | GOOD — most skills accept module name or target |
| **Verification step** | Skills end with a verification phase | PARTIAL — `/write-tests` verifies, others don't |
| **Failure handling** | Skills explain what to do when things go wrong | POOR — most skills don't address failure scenarios |

### 7.2 Skill Template for New Skills

```markdown
---
name: skill-name
description: One sentence. Use when [trigger phrases]. Accepts [argument type] as argument.
allowed-tools: [tool list]
---

# Skill Name Workflow

## Phase 1: Assess
1. Read relevant files
2. Check prerequisites
3. Report if prerequisites not met — STOP if missing

## Phase 2: Plan
1. Identify specific work items
2. Present plan as table
3. Estimate scope

## Phase 3: Execute
1. Do the work
2. Track progress per item
3. Handle errors explicitly

## Phase 4: Verify
1. Run verification (tests, linting, evaluation)
2. Report results as table
3. If verification fails, return to Phase 3

## Arguments
- `$ARGUMENTS`: description of expected input
- If no argument given: explain default behavior

## Failure Modes
| Failure | Detection | Recovery |
|---------|-----------|----------|
| (common failure 1) | (how to detect) | (what to do) |
| (common failure 2) | (how to detect) | (what to do) |
```

---

## 8. RECOMMENDATIONS

### 8.1 Immediate Actions (This Sprint)

| # | Action | Priority | Effort | Impact |
|---|--------|----------|--------|--------|
| 1 | Create `conftest.py` with shared fixtures | P0 | 1 hour | Unblocks all test writing |
| 2 | Run `/test-suite` to verify it works | P0 | 10 min | Validates core skill |
| 3 | Run `/evaluate` to verify gold dataset exists | P0 | 10 min | Identifies critical gap |
| 4 | Mark `/legal-kb` as PLANNED in CLAUDE.md | P1 | 5 min | Prevents confusion |
| 5 | Add failure mode tables to all skills | P1 | 2 hours | Improves resilience |
| 6 | Create `/security-scan` skill | P1 | 1 hour | Addresses security audit gap |
| 7 | Create `/golden-test-set` skill | P1 | 1 hour | Addresses evaluation gap |

### 8.2 Short-Term (Next Sprint)

| # | Action | Priority | Effort | Impact |
|---|--------|----------|--------|--------|
| 8 | Add pre-push hook (run tests) | P1 | 2 hours | Prevents broken pushes |
| 9 | Create GitHub Actions CI workflow | P1 | 4 hours | Automated quality gates |
| 10 | Create `/migration-plan` skill for Ollama transition | P1 | 2 hours | Guided LLM migration |
| 11 | Build gold dataset (50 labeled documents minimum) | P1 | 8 hours | Enables F1/Kappa measurement |
| 12 | Verify all skills by running each one once | P2 | 2 hours | Identifies broken skills |

### 8.3 Long-Term (Roadmap)

| # | Action | Priority | Effort | Impact |
|---|--------|----------|--------|--------|
| 13 | Build RAG infrastructure → activate `/legal-kb` skill | P2 | Multi-sprint | Enables legal corpus features |
| 14 | Create `/confidence-calibrate` skill | P2 | 2 hours | Empirical threshold tuning |
| 15 | Implement Ralph Loop stop hook | P3 | 4 hours | Full iterative loop capability |
| 16 | Re-evaluate Agent Teams when project exceeds 50 files | P3 | Research | Future decision point |

---

## 9. PEAS FRAMEWORK FOR OVERALL SKILL SYSTEM

### Agent Task: Terms & Policies Reviewer — Skill Orchestration

| Component | Definition | This System |
|-----------|------------|-------------|
| **Performance** | Skill invocation success rate, time-to-result, quality of output | UNKNOWN — no skills exercised yet. Target: 100% invocation success, < 5min for test/review skills |
| **Environment** | .claude/ workspace, src/ codebase, local tooling (pytest, Playwright, FAISS) | PARTIAL — codebase present, some tools unverified |
| **Actuators** | 9 skills × their respective tools, Task subagents for parallel work | GOOD coverage — all major workflows have a skill |
| **Sensors** | Codebase state, test output, evaluation metrics, web search results, LLM responses | ADEQUATE — all needed data sources accessible |

### Environment Characteristics

| Property | Value | Impact on Skills |
|----------|-------|-----------------|
| Fully Observable | PARTIAL | Cannot see runtime behavior (LLM response quality, actual latency). Must infer from output. |
| Deterministic | PARTIAL | Rule engine deterministic, LLM stochastic, test results deterministic |
| Episodic | YES | Each skill invocation is independent (except `/ralph-loop` which is multi-episode) |
| Static | MOSTLY | Codebase changes between invocations but not during a single skill run |
| Discrete | YES | Finite set of skills, bounded tool permissions |
| Single Agent | YES | All skills run in the same Claude session. No inter-skill communication except through files. |

---

## 10. COMPARISON: OUR APPROACH vs SRS APPROACH

| Dimension | SRS AI Systems | Terms-Analysis | Notes |
|-----------|---------------|----------------|-------|
| Custom agents (.claude/agents/) | 11 | 0 | SRS has security-scanner, architecture-guardian, principal-engineer-planner, etc. We use skills instead. |
| Skills (.claude/skills/) | 0 (uses agents) | 9 | Different paradigm: SRS uses persistent agent definitions, we use invocable skills. Both valid. |
| Validation protocol | Pharmaceutical-grade: tool usage > 0, file:line citations, log top-to-bottom | Confidence-gated: < 0.80 triggers human review | SRS is stricter. Appropriate for pharma. |
| Orchestration model | Team Leader pattern (lead agent coordinates 11 agents) | Single agent with skill toolbox | Appropriate for project size. |
| Token optimization | 97% savings (20k file → 500 token summary via subagents) | Moderate (Task subagents for research, direct tools for focused work) | SRS handles much larger files. |
| Architecture docs | 125+ diagrams, 23 ADRs, 100+ doc files | DESIGN.md + CLAUDE.md + LIB-* library | SRS is 10 months old. Our docs are growing. |
| CI/CD | 6 GitHub Actions workflows, pre-commit hooks | None | **CRITICAL GAP** for us. |
| Agent Teams | Evaluated → WAIT | Evaluated → WAIT | Same conclusion, different reasons. |

---

## APPENDIX A: SKILLS FILE INVENTORY

```
.claude/
├── CLAUDE.md                           (78 lines — hub file, always loaded)
├── rules/
│   ├── testing.md                      (auto-loaded for test files)
│   └── code-style.md                   (auto-loaded for code files)
├── library/
│   ├── LIB-ARCH.md                     (architecture, data flow, failure modes)
│   ├── LIB-STACK.md                    (dependencies, versions, config)
│   ├── LIB-LEGAL.md                    (legal LLM/embedding models, RAG)
│   ├── LIB-TEST.md                     (test coverage gaps, priority order)
│   ├── LIB-API.md                      (16 endpoints, request/response contracts)
│   ├── LIB-RULES.md                    (rule engine, 9 categories, IRP scoring)
│   └── LIB-EVAL.md                     (quality rubric, F1/Kappa targets)
└── skills/
    ├── test-suite/SKILL.md             (run tests + coverage)
    ├── write-tests/SKILL.md            (4-phase test writing workflow)
    ├── evaluate/SKILL.md               (F1/Kappa evaluation)
    ├── review/SKILL.md                 (code quality review)
    ├── webapp-testing/SKILL.md         (Playwright frontend tests)
    ├── dependency-audit/SKILL.md       (IRP scoring dependencies)
    ├── legal-kb/SKILL.md               (legal corpus management — PLANNED)
    └── ralph-loop/SKILL.md             (iterative dev loop)
```

## APPENDIX B: CODEBASE FILE INVENTORY

```
src/backend/
├── app/
│   ├── __init__.py
│   ├── config.py                       (51 lines — Settings dataclass, env vars)
│   ├── database.py                     (42 lines — SQLAlchemy engine, session)
│   ├── main.py                         (584 lines — 16 FastAPI endpoints)
│   ├── models.py                       (57 lines — 3 SQLAlchemy tables)
│   ├── schemas.py                      (113 lines — 10 Pydantic models)
│   └── services/
│       ├── analyzer.py                 (163 lines — analysis pipeline, merge, scoring)
│       ├── diffing.py                  (22 lines — content hash, diff summary)
│       ├── ingest.py                   (128 lines — file ingestion, 6 formats)
│       ├── lm_studio.py               (89 lines — LLM client, error handling)
│       ├── prompts.py                  (55 lines — system/user prompts)
│       ├── rules.py                    (202 lines — 9 categories, 37 patterns)
│       └── validation.py              (67 lines — hallucination detection)
├── tests/
│   └── (3 test files, 5 tests total)
└── evaluation/
    └── (gold dataset + evaluation scripts — unverified)

src/webapp/
├── index.html
├── app.js                              (887 lines — full SPA)
└── style.css

docs/
├── DESIGN.md
├── TODO.md
├── reports/
│   └── backend-technology-terms-analysis.md  (PEAS self-eval)
├── plans/
│   ├── data-integrity-architecture-analysis.md  (NEW — this sprint)
│   └── agent-skills-surface-area-audit.md       (NEW — this sprint)
├── specs/
├── wireframes/
└── diagrams/
    └── architecture.mmd
```

---

*Report generated by AI Terms & Policies Reviewer tooling analysis*
*Methodology: PEAS framework per skill + subagent cost-benefit analysis*
*Reference: SRS AI Systems agent teams analysis, security audit, and architecture inventory*
*Next review: After first full test coverage sprint*
