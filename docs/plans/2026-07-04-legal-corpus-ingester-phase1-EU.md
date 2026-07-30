---
format: ingester-implementation-plan
date: 2026-07-04
scope: legal-corpus-ingester Phase 1 — EU cluster
corpus-plan: docs/plans/2026-07-04-corpus-EU.md
tracks-issue: legal-corpus-ingester#10
status: PLANNING — no code changes yet; tasks emerge from this doc
---

# Phase 1 Implementation Plan — EU Cluster Ingestion

## Purpose

Phase 0.1 of legal-corpus-ingester is complete (Tasks 1–40, pushed `e8d9dea`).
This document defines the Phase 1 implementation tasks required to ingest the EU
legal cluster into terms-analysis. Corpus content decisions (statutes in scope,
authoritative URLs, chunking strategy, citation schema, license terms) are captured in:

> **`docs/plans/2026-07-04-corpus-EU.md`** — read it first.

This document covers the **ingester-side** work only: source YAML configs, fetcher
modules, VCR cassettes, integration tests, and the publish/consumer handoff.

---

## Statutes in scope (Phase 1)

| Statute | CELEX | Priority |
|---------|-------|----------|
| GDPR — Regulation (EU) 2016/679 | 02016R0679-20160504 | P0 — block all other EU work |
| EU AI Act — Regulation (EU) 2024/1689 | 02024R1689-20240712 | P0 — primary consumer use case |
| DSA — Regulation (EU) 2022/2065 | 32022R2065 | P1 — after GDPR+AI Act green |
| Data Act — Regulation (EU) 2023/2854 | 32023R2854 | P1 |
| DMA — Regulation (EU) 2022/1925 | 32022R1925 | P2 — lower consumer demand |

---

## Implementation tasks

### T1 — Source YAML configs (config/sources/)

Create one YAML per statute in `legal-corpus-ingester/config/sources/`:

```
config/sources/
  eurlex_gdpr.yaml
  eurlex_ai_act.yaml
  eurlex_dsa.yaml
  eurlex_data_act.yaml
  eurlex_dma.yaml
```

Each YAML must include:
- `source_id`, `name`, `jurisdiction: EU`
- `base_url`, `celex_id` (for the consolidated version)
- `license.spdx: CC-BY-4.0`
- `license.url: https://eur-lex.europa.eu/content/legal-notice/legal-notice.html`
- `pipeline.fetcher: EurLexFetcher`
- `pipeline.cleaner: XmlCleaner`
- `pipeline.chunker: SectionAwareChunker`

See `config/sources/` for template patterns and `docs/plans/2026-07-04-corpus-EU.md`
§ "Per-statute detail" for authoritative URLs and CELEX identifiers.

### T2 — APPROVAL.yaml for all EU statutes (HR9)

Each source requires `config/approvals/<source_id>.yaml` with:
- `source_id`
- `expiry` (set to 1 year from ingestion date)
- `signed_artifact_sha256` (populated after first fetch)
- `reviewed_by` + `review_date`

EU statutes are CC-BY-4.0 (low license risk), so the legal review gate is
informational rather than blocking — but the APPROVAL.yaml is still required by HR9.

### T3 — VCR cassettes (tests/fixtures/cassettes/)

Record one cassette per statute per fetch URL:

```
tests/fixtures/cassettes/
  eurlex/
    gdpr_consolidated.yaml          # exists (gdpr_fetch.yaml — verify URI)
    ai_act_consolidated.yaml        # new
    dsa_consolidated.yaml           # new
    data_act_consolidated.yaml      # new
    dma_consolidated.yaml           # new
```

Record with `record_mode='new_episodes'` locally. Commit cassettes. CI uses
`record_mode='none'`. Weekly VCR drift canary (Sunday 4 AM UTC) re-records all.

### T4 — EurLexFetcher extension

`src/legal_corpus_ingester/fetchers/eurlex.py` — extend to accept a `celex_id`
parameter so it can fetch any statute by CELEX, not just GDPR. Current implementation
hardcodes `32016R0679`. The extension must:

1. Accept `celex_id` from source YAML
2. Resolve to the consolidated XML endpoint:
   `https://eur-lex.europa.eu/legal-content/EN/TXT/XML/?uri=CELEX:<celex_id>`
3. Return `FetchResult` with `provenance.license = "CC-BY-4.0"` and
   `provenance.upstream_version = celex_id`

### T5 — XmlCleaner validation

`src/legal_corpus_ingester/cleaners/` — verify the existing XML cleaner handles
AkomaNtoso 3.0 documents (all EU statutes use this schema). Run against AI Act XML;
the AI Act has 13 annexes which the current GDPR-only test corpus does not cover.
Add integration test for annex-level sections.

### T6 — Integration tests for each statute

`tests/integration/` — add one test module per statute:

```
tests/integration/
  test_eurlex_fetcher.py           # extend existing
  test_ai_act_fetcher.py           # new
  test_dsa_fetcher.py              # new
  test_data_act_fetcher.py         # new
  test_dma_fetcher.py              # new
```

Each test: `@pytest.mark.vcr` → replays cassette → asserts `FetchResult` shape,
`mime_type`, `provenance.license == "CC-BY-4.0"`.

### T7 — End-to-end refresh dry-run

After T1–T6 pass:
1. `ingester refresh --all --dry-run` — must list all 5 EU statutes
2. `ingester audit-license eurlex_gdpr` — must exit 0 (NEW or NO_CHANGE)
3. Full pipeline run against cassette fixtures (integration, not live)

### T8 — Bundle publish + consumer handoff

After a successful refresh:
1. `ingester validate-round-trip out/current` — must pass
2. Flip `out/current` symlink
3. terms-analysis consumer reads new bundle → runs retrieval smoke test

---

## Dependencies / blockers

| Dependency | Status |
|------------|--------|
| Phase 0.1 complete | DONE — pushed `e8d9dea` |
| `ingester refresh` CLI command | DONE — added Group A fix |
| `audit-license --offline` flag | DONE — added Group C fix |
| VCR cassette for eurlex legal notice | DONE — added Group D fix |
| LocalAI Apertus-8B running locally | REQUIRED for embed step |
| terms-analysis consumer LegalKnowledgeBase | REQUIRED for validate-round-trip |

---

## Ordering

```
T1 (source YAMLs) → T2 (approvals) → T3 (cassettes) → T4 (fetcher ext) →
T5 (cleaner) → T6 (integration tests) → T7 (dry-run) → T8 (publish)
```

T1 and T2 can be done in parallel. T3 requires network (record from live EUR-Lex
once; cassette committed for all future runs). T4–T6 can run in parallel after T3.

---

## Streamlit front-end implementation

The terms-analysis UI is Streamlit. The corpus-EU.md "Rendering behavior in the revamp UI" (§7
per statute) describes citation patterns (`GDPR Art. 6(1)(a)`, `AI Act Annex III (item 6)`) and
the `[see law text ▸]` tap-to-retrieve pattern. This section maps those specs to concrete
Streamlit components.

### Citation inline rendering

Use `st.markdown()` with `unsafe_allow_html=True` to embed inline citation badges alongside
finding text. Each badge is a short HTML `<span>` with a tooltip carrying the attribution string:

```python
def render_citation_badge(citation_short: str, source_url: str, attribution: str) -> str:
    """Return an HTML citation badge for st.markdown(unsafe_allow_html=True)."""
    return (
        f'<a href="{source_url}" target="_blank" title="{attribution}" '
        f'style="font-size:0.8em; background:#e8f0fe; border-radius:4px; '
        f'padding:2px 6px; text-decoration:none; color:#1a73e8;">'
        f'{citation_short}</a>'
    )
```

This produces a clickable badge that links to the EUR-Lex article anchor. No JS required.

### "See law text ▸" expansion

Use `st.expander()` to implement the tap-to-reveal pattern. The expander label is the
`citation_short` string; the body is the retrieved chunk text plus the mandatory CC-BY-4.0
attribution notice:

```python
def render_law_text_expander(
    citation_short: str,
    chunk_text: str,
    attribution: str,
    source_url: str,
) -> None:
    with st.expander(f"See law text ▸ {citation_short}"):
        st.markdown(chunk_text)
        st.caption(
            f"{attribution} · [View on EUR-Lex]({source_url})"
        )
```

The `[View on EUR-Lex]` link satisfies the CC-BY-4.0 attribution requirement in-UI without
requiring a dedicated `/legal/attribution` page (covers legal-review gate question (a)).

### Authoritative weight badge

AI Act guidelines have `authoritative_weight: interpretive`. Surface this via a Streamlit
`st.info()` (blue callout) vs. `st.success()` (green) to visually distinguish binding from
interpretive chunks:

```python
def render_passage(passage: dict) -> None:
    if passage.get("authoritative_weight") == "interpretive":
        st.info(f"Interpretive guidance — {passage['citation_short']}")
    else:
        st.success(f"Binding law — {passage['citation_short']}")
    st.markdown(passage["text"])
```

### Authentic-language disclaimer

Per legal-review gate question (c): display once per session in a `st.sidebar` expander, not
per chunk. Store display state in `st.session_state`:

```python
if "eu_legal_notice_shown" not in st.session_state:
    st.session_state.eu_legal_notice_shown = False

with st.sidebar:
    with st.expander("EU legal text notice", expanded=not st.session_state.eu_legal_notice_shown):
        st.caption(
            "Consolidated EU texts on this page are sourced from EUR-Lex "
            "(https://eur-lex.europa.eu) under CC-BY-4.0. These texts are "
            "documentation tools only — they have no legal effect. "
            "The authentic versions are those published in the Official Journal."
        )
        st.session_state.eu_legal_notice_shown = True
```

### Retrieve integration

The Streamlit page calls `legal_kb.retrieve()` with the structured metadata args defined in
the corpus-EU.md schema. The retrieve result populates `AnalysisPayload.finding.legal_context_passages`.
Ensure `retrieve()` returns the extended fields (`celex_consolidated`, `version_date`,
`chapter_title`, `article_paragraph`, `article_point`, `annex`, `annex_item`) before wiring
the Streamlit render path — these fields drive the citation badge and expander label.

### Component file location

Add the citation rendering helpers to:
```
src/terms_analysis/ui/components/legal_citations.py
```

Keep them pure functions (no Streamlit state). The Streamlit pages import and call them.

---

## Reference

- Corpus content decisions: `docs/plans/2026-07-04-corpus-EU.md`
- Ingester CLAUDE.md: `legal-corpus-ingester/.claude/CLAUDE.md`
- Hard requirements: HR1–HR9 (open-source only, license gate, local data)
- Tracks: legal-corpus-ingester GitHub issue #10
