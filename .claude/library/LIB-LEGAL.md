# LIB-LEGAL: Legal AI Stack & RAG Architecture

**Note:** the LLM/Embedding/Inference tables below (SaulLM, Ollama, multilingual-e5, onnxruntime) describe an evaluated *candidate* stack, not what's actually running. The shipped LLM stack is LocalAI + Apertus-8B-Instruct/EuroLLM-22B-Instruct (`services/localai.py`), and the shipped legal-KB embeddings reuse that same `LocalAIClient.embed()` call rather than a separate sentence-transformers/onnxruntime pipeline. The **Vector Store**, **REJECTED Tools**, and **RAG Architecture** sections below are accurate to the current implementation (`services/legal_kb.py`) — numpy exhaustive search, FAISS explicitly rejected.

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

Primary model must be multilingual — the tool covers US, EU, UK, Canada, Brazil, Australia jurisdictions whose source legal texts are in multiple languages.

| Model | License | Dimensions | Languages | Use For |
|-------|---------|-----------|-----------|---------|
| **intfloat/multilingual-e5-large-instruct** | MIT | 1024 | 100+ | Primary: world-coverage semantic search (Microsoft Research) |
| freelawproject/modernbert-embed-base-8192 | Apache 2.0 | 768 | English | English-only legal text (use only for English-language corpus chunks) |
| AdamLucek/ModernBERT-embed-base-legal-MRL | Apache 2.0 | 768 | English | Variable-dim English-only alternative |

### Inference Runner

| Tool | License | IRP Grade | Notes |
|------|---------|-----------|-------|
| **Ollama CLI** | MIT | A- (0.26) | Local inference, same chat/completions API. CLI only — avoid GUI/Turbo/cloud. |

### Inference Backend (for embeddings)

| Tool | License | Origin | Notes |
|------|---------|--------|-------|
| **onnxruntime** | MIT | Microsoft | Runs ONNX-exported models; no PyTorch needed |
| sentence-transformers[onnx] | Apache 2.0 | UKP Lab (Germany) | Wraps onnxruntime with HuggingFace model support |

### Vector Store

**REQUIREMENT: Exact (exhaustive) search only.** This tool produces legal risk findings — approximate nearest neighbor introduces false negatives that could cause missed compliance issues. All retrieval must be exact.

| Tool | License | Search | Notes |
|------|---------|--------|-------|
| **numpy exhaustive** | BSD | Exact | Zero new deps. `np.dot(query, corpus.T)` — correct for legal corpus size (<50K chunks). Primary choice. |
| sqlite-vec | MIT | Exact | SQLite extension by Alex Garcia (independent). Integrates with existing SQLAlchemy stack. Use if corpus grows beyond 100K chunks. |

### REJECTED Tools

| Tool | Why Rejected |
|------|-------------|
| LM Studio | Proprietary closed source. Fails open-source requirement. |
| Stability AI models | Investor lawsuits (co-founder fraud, Coatue pressure). |
| Voyage Law 2 | Proprietary API-only. Fails open-source + local-only. |
| Ollama GUI/Turbo | Unclear license (GUI), proprietary (Turbo). CLI only is approved. |
| FAISS / faiss-cpu | Facebook/Meta origin. Fails no-Meta requirement. |
| torch / PyTorch | Meta origin (donated to Linux Foundation but Meta-created). Use onnxruntime instead. |
| BAAI/bge-m3 | Beijing Academy of Artificial Intelligence — Chinese government-affiliated. |
| Qwen / Qwen3-* | Alibaba (Chinese company). Fails no-Chinese-company requirement. |
| Any HNSW-based vector store | Approximate search. Unacceptable for legal risk analysis — false negatives miss compliance issues. |

## RAG Architecture

**Status: implemented** (`services/legal_kb.py`, wired into `analyzer.py::analyze_text()`), using the project's actual LLM stack (LocalAI/Apertus/EuroLLM) rather than the Ollama/SaulLM stack originally sketched below — corpus is currently placeholder text, not yet real statute text (see `data/legal_corpus/` file headers and issue #6).

```
Legal Corpus (data/legal_corpus/<jurisdiction>/<law>.txt)
      |
      v
  Chunk + Embed (LocalAIClient.embed(), Apertus-8B model)
      |
      v
  numpy exhaustive vector matrix (local, .npy — no FAISS, see Vector Store above)
      |
      +--- User uploads ToS/Privacy Policy
      |        |
      |     Rule-engine detection (existing regex baseline) runs in parallel
      |        |
      |     Retrieve top-k matching legal requirements (numpy cosine + BM25/RRF)
      |        |
      |     Augment prompt with retrieved legal context
      |        |
      v        v
  LocalAI (Apertus-8B-Instruct / EuroLLM-22B-Instruct, routed by language)
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

## Services (implemented)

| Service | File | Purpose |
|---------|------|---------|
| `embedding.py` | `src/backend/app/services/` | Document-chunk BM25 + dense + RRF ensemble (not yet wired into `analyzer.py` — see `docs/architecture-diagrams.md`) |
| `legal_kb.py` | `src/backend/app/services/` | Legal knowledge base: corpus parser, numpy exhaustive index builder, BM25/RRF retrieval — wired into `analyzer.py::analyze_text()` |
| `localai.py` | `src/backend/app/services/` | LLM client targeting LocalAI (Apertus-8B/EuroLLM-22B); this was never named `lm_studio.py` in the actual codebase |

## Dependencies (actually added for this)

| Package | License | Purpose |
|---------|---------|---------|
| rank_bm25 | Apache 2.0 | Sparse retrieval (BM25) — already a dependency before the legal-KB work |
| numpy | BSD | Exact/exhaustive vector similarity for legal-KB retrieval |

No `sentence-transformers`, `torch`, or `faiss-cpu` were added — dense embeddings reuse the existing `LocalAIClient.embed()` HTTP call (Apertus-8B), and the vector index is a plain numpy matrix (see Vector Store above).
