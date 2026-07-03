---
name: legal-kb
description: Manage the legal knowledge base for the RAG pipeline. Use when asked to "update legal corpus", "add jurisdiction", "index legal text", "add GDPR articles", "add CCPA sections", or when expanding jurisdiction coverage. Handles downloading, chunking, and indexing legal source texts.
allowed-tools: Bash, Read, Write, Edit, WebFetch, WebSearch, Grep, Glob
---

# Legal Knowledge Base Manager

## Supported Jurisdictions

| Jurisdiction | Law | Source | Status |
|-------------|-----|--------|--------|
| EU | GDPR | EUR-Lex (CC-BY-4.0) | Planned |
| US-CA | CCPA/CPRA | leginfo.legislature.ca.gov (public domain) | Planned |
| US-CO | Colorado Privacy Act | coag.gov (public domain) | Planned |
| US-CT | CTDPA | cga.ct.gov (public domain) | Planned |
| US-NY | SHIELD Act | nysenate.gov (public domain) | Planned |
| Canada | PIPEDA | laws-lois.justice.gc.ca (public domain) | Planned |

## Workflow

### Adding a New Jurisdiction

1. **Locate source text**
   - Government websites only (public domain / CC-BY-4.0)
   - Never use Pile of Law (CC-BY-NC-SA, non-commercial)
   - Fetch full text of the law/regulation

2. **Structure the text**
   - Save raw text to `data/legal_corpus/<jurisdiction>/<law_name>.txt`
   - Split into sections/articles (one per chunk where possible)
   - Add metadata header: jurisdiction, law name, effective date, source URL

3. **Chunk for embedding**
   - Target chunk size: 512-1024 tokens
   - Overlap: 128 tokens between chunks
   - Preserve article/section boundaries where possible
   - Include article number and title in each chunk for retrieval context

4. **Generate embeddings**
   ```bash
   cd src/backend && python -m app.services.legal_kb index --jurisdiction <jur>
   ```
   Note: `--jurisdiction` is accepted for CLI compatibility but always rebuilds the
   full corpus — a full rebuild is simplest/correct at this corpus size.

5. **Verify retrieval quality**
   - Run test queries against known articles
   - Check top-k retrieval accuracy
   - Verify cross-jurisdiction queries work
   - Use the jurisdiction code exactly as it appears in `schemas.py`'s `Jurisdiction`
     Literal (e.g. `GDPR`, `PIPEDA`) for the `# Jurisdiction:` header — NOT the
     directory name — otherwise the jurisdiction filter silently falls back to
     searching the whole corpus (see issue #14)

### Updating Existing Corpus

1. Fetch updated text from source
2. Diff against existing version
3. Re-chunk and re-embed only changed sections
4. Rebuild the legal-KB index

## Data Directory Structure

```
data/
├── legal_corpus/
│   ├── eu/
│   │   └── gdpr.txt
│   ├── us-ca/
│   │   └── ccpa_cpra.txt
│   ├── us-co/
│   │   └── cpa.txt
│   ├── us-ct/
│   │   └── ctdpa.txt
│   ├── us-ny/
│   │   └── shield_act.txt
│   └── canada/
│       └── pipeda.txt
├── legal_kb.npy            # Vector matrix (L2-normalized, exact exhaustive
│                           # cosine search — no FAISS/ANN; Meta-origin FAISS
│                           # is excluded by the project's dependency no-go list)
└── legal_kb_metadata.json  # Chunk metadata (article refs, jurisdictions, status)
```

Each corpus file's header must include a `# Status: PLACEHOLDER` line while its
text is not yet real statute text — this propagates into every parsed chunk and
`prompts.py::build_user_prompt` uses it to prepend an explicit "UNVERIFIED
PLACEHOLDER" warning before any such passage reaches the LLM. Remove that line
once the file contains real, sourced statute text.

## Arguments
- `$ARGUMENTS`: jurisdiction code (e.g., "eu-gdpr", "us-ca", "canada-pipeda") or "all"
- No arguments = show status of all jurisdictions

## Reference
- Approved corpora and licenses: @.claude/library/LIB-LEGAL.md
- Architecture details: @.claude/library/LIB-ARCH.md
