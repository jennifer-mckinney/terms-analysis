# LIB-LEGAL: Legal AI Stack & RAG Architecture

## Approved LLM/Embedding/Inference Tools

All tools must pass: open source + no investor lawsuits + positive community + IRP Grade A.

### LLM (Legal Reasoning)

| Model | License | Org | IRP Grade | Training | Use For |
|-------|---------|-----|-----------|----------|---------|
| **SaulLM-7B-Instruct** | MIT | Equall.ai | A+ (0.00) | 30B legal tokens (EUR-Lex, US case law, UK legislation) | Primary legal analysis LLM |
| **SaulLM-54B-Instruct** | MIT | Equall.ai | A+ (0.00) | 540B+ legal tokens | Stronger reasoning, needs multi-GPU or quantization |
| AI2 OLMo 3 7B/32B | Apache 2.0 | Allen Institute (nonprofit) | A+ (0.00) | General (no legal fine-tune) | Fallback or fine-tune candidate |
| Mistral 3 (Apache 2.0 variants) | Apache 2.0 | Mistral AI | A (0.02) | General | Self-hosted open models only |

### Embedding (Legal Semantic Search)

| Model | License | Dimensions | Context | Use For |
|-------|---------|-----------|---------|---------|
| **freelawproject/modernbert-embed-base-8192** | Apache 2.0 | 768 | 8192 tokens | Primary legal embeddings (Free Law Project, nonprofit) |
| AdamLucek/ModernBERT-embed-base-legal-MRL | Apache 2.0 | 768 (MRL: 64-768) | 8192 tokens | Variable-dim alternative |
| BAAI/bge-m3 | MIT | 1024 | 8192 tokens | Multilingual fallback (EU languages) |
| Qwen3-Embedding-0.6B | Apache 2.0 | 32-1024 | 32K tokens | Long-context multilingual |

### Inference Runner

| Tool | License | IRP Grade | Notes |
|------|---------|-----------|-------|
| **Ollama CLI** | MIT | A- (0.26) | Local inference, same chat/completions API. CLI only — avoid GUI/Turbo/cloud. |

### Vector Store

| Tool | License | IRP Grade | Notes |
|------|---------|-----------|-------|
| **FAISS** | MIT | A+ | Facebook AI Similarity Search. Local, in-memory. |
| sqlite-vss | MIT | A+ | SQLite extension, stays in existing DB stack. |

### REJECTED Tools

| Tool | Why Rejected |
|------|-------------|
| LM Studio | Proprietary closed source. Fails open-source requirement. |
| Stability AI models | Investor lawsuits (co-founder fraud, Coatue pressure). |
| Voyage Law 2 | Proprietary API-only. Fails open-source + local-only. |
| Ollama GUI/Turbo | Unclear license (GUI), proprietary (Turbo). CLI only is approved. |

## RAG Architecture

```
Legal Requirements DB
  (GDPR articles, CCPA/CPRA sections, PIPEDA, US state laws)
      |
      v
  Chunk + Embed (modernbert-legal-8192)
      |
      v
  FAISS Vector Index (local)
      |
      +--- User uploads ToS/Privacy Policy
      |        |
      |     Chunk + Embed (same model)
      |        |
      |     Retrieve top-k matching legal requirements
      |        |
      |     Augment prompt with retrieved legal context
      |        |
      v        v
  SaulLM-7B-Instruct (via Ollama)
      |
      v
  Rule Engine (existing regex baseline)
      |
      v
  Merge + Validate + Score (existing pipeline)
```

## Legal Corpora (Open Source)

| Corpus | License | Coverage | Source |
|--------|---------|----------|--------|
| **EUR-Lex** | CC-BY-4.0 | Full EU legislation incl. GDPR | data.europa.eu |
| **MultiEURLEX** | CC-BY-4.0 | 65K EU laws, 23 languages | HuggingFace |
| **US state law texts** | Public domain | CCPA/CPRA, CPA, CTDPA, SHIELD | State legislature sites |
| **PIPEDA** | Public domain | Canadian federal privacy law | laws-lois.justice.gc.ca |
| **CourtListener/RECAP** | Public domain | US court opinions, dockets | courtlistener.com |
| **CUAD** | CC-BY-4.0 | 510 contracts, 41 clause types | atticusprojectai.org |
| **LegalBench** | Open | 162 legal reasoning tasks | HuggingFace |

**CAUTION:** Pile of Law is CC-BY-NC-SA-4.0 (non-commercial only). Do NOT use for commercial product.

## New Services Needed

| Service | File | Purpose |
|---------|------|---------|
| `embeddings.py` | `src/backend/app/services/` | Embedding service using sentence-transformers + modernbert-legal |
| `legal_kb.py` | `src/backend/app/services/` | Legal knowledge base loader, chunker, FAISS indexer |
| Refactor `lm_studio.py` | `src/backend/app/services/` | Rename to generic LLM client, point at Ollama + SaulLM |

## New Dependencies Needed

| Package | License | Purpose |
|---------|---------|---------|
| sentence-transformers | Apache 2.0 | Embedding model loading |
| faiss-cpu | MIT | Vector similarity search |
| torch | BSD-3 | Model inference runtime |
| rank-bm25 | Apache 2.0 | Hybrid retrieval (BM25 + dense) |
