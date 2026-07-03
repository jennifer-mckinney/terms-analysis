# LIB-LEGAL — legal AI stack, RAG architecture, approved/rejected tools, corpora
loads: on-trigger
scope: project
xref: [[LIB-STACK]] [[LIB-ARCH]] [[LIB-RULES]] [[.claude/CLAUDE.md#hard-requirements]]

status: LLM/Embedding/Inference tables below describe an evaluated *candidate* stack. Shipped LLM = LocalAI + Apertus-8B/EuroLLM-22B (`services/localai.py`). Shipped legal-KB embeddings reuse `LocalAIClient.embed()` — no separate sentence-transformers/onnxruntime pipeline. Vector Store, REJECTED, and RAG Architecture sections ARE accurate to current implementation.

## approval-policy

### L1: approval-criteria
rule: every LLM/embedding/inference tool MUST pass: open source + no investor lawsuits + positive community + IRP Grade A

## approved-llm

### L2: legal-reasoning-primary
rule: **SaulLM-7B-Instruct** is primary legal analysis LLM candidate
alternatives: SaulLM-54B-Instruct (stronger, needs multi-GPU/quantization), OLMo 3 7B/32B (fallback), Mistral 3 Apache variants

| Model | License | Org | IRP | Training | Use For |
|-------|---------|-----|-----|----------|---------|
| **SaulLM-7B-Instruct** | MIT | Equall.ai | A+ (0.00) | 30B legal tokens (EUR-Lex, US case law, UK legislation) | Primary legal analysis LLM |
| SaulLM-54B-Instruct | MIT | Equall.ai | A+ (0.00) | 540B+ legal tokens | Stronger reasoning, needs multi-GPU or quantization |
| AI2 OLMo 3 7B/32B | Apache 2.0 | Allen Institute (nonprofit) | A+ (0.00) | General (no legal fine-tune) | Fallback or fine-tune candidate |
| Mistral 3 (Apache 2.0 variants) | Apache 2.0 | Mistral AI | A (0.02) | General | Self-hosted open models only |

## approved-embeddings

### L3: multilingual-primary
rule: primary embedding model MUST be multilingual
because: tool covers US, EU, UK, Canada, Brazil, Australia — source legal texts in multiple languages

| Model | License | Dims | Languages | Use For |
|-------|---------|------|-----------|---------|
| **intfloat/multilingual-e5-large-instruct** | MIT | 1024 | 100+ | Primary: world-coverage semantic search (Microsoft Research) |
| freelawproject/modernbert-embed-base-8192 | Apache 2.0 | 768 | English | English-only legal text |
| AdamLucek/ModernBERT-embed-base-legal-MRL | Apache 2.0 | 768 | English | Variable-dim English-only alternative |

## inference-runner

| Tool | License | IRP | Notes |
|------|---------|-----|-------|
| **Ollama CLI** | MIT | A- (0.26) | Local inference, chat/completions API; CLI only — avoid GUI/Turbo/cloud |

### L4: ollama-cli-only
rule: only Ollama CLI approved; GUI/Turbo/cloud REJECTED

## inference-backend

| Tool | License | Origin | Notes |
|------|---------|--------|-------|
| **onnxruntime** | MIT | Microsoft | Runs ONNX-exported models; no PyTorch needed |
| sentence-transformers[onnx] | Apache 2.0 | UKP Lab (Germany) | Wraps onnxruntime with HuggingFace model support |

## vector-store

### L5: exact-search-only
rule: all retrieval MUST be exact (exhaustive) search
forbidden: any HNSW/ANN vector store
because: legal risk findings — approximate NN introduces false negatives = missed compliance issues

| Tool | License | Search | Notes |
|------|---------|--------|-------|
| **numpy exhaustive** | BSD | Exact | Zero new deps. `np.dot(query, corpus.T)`. Correct for <50K chunks. Primary. |
| sqlite-vec | MIT | Exact | SQLite extension by Alex Garcia (independent). Use if corpus > 100K chunks. |

## rejected-tools

| Tool | Why Rejected |
|------|--------------|
| LM Studio | Proprietary closed source |
| Stability AI models | Investor lawsuits (co-founder fraud, Coatue pressure) |
| Voyage Law 2 | Proprietary API-only; fails open-source + local-only |
| Ollama GUI/Turbo | Unclear license (GUI), proprietary (Turbo) |
| FAISS / faiss-cpu | Meta origin; fails no-Meta requirement |
| torch / PyTorch | Meta origin (donated to Linux Foundation but Meta-created); use onnxruntime instead |
| BAAI/bge-m3 | Beijing Academy of AI — Chinese government-affiliated |
| Qwen / Qwen3-* | Alibaba (Chinese company); fails no-Chinese-company requirement |
| Any HNSW-based vector store | Approximate search; unacceptable for legal risk analysis |

## rag-architecture

status: implemented (`services/legal_kb.py`, wired into `analyzer.py::analyze_text()`). Uses actual project LLM stack (LocalAI/Apertus/EuroLLM), NOT Ollama/SaulLM stack sketched below. Corpus currently placeholder, not yet real statute text (see `data/legal_corpus/` file headers and issue #6).

```
Legal Corpus (data/legal_corpus/<jurisdiction>/<law>.txt)
      |
      v
  Chunk + Embed (LocalAIClient.embed(), Apertus-8B model)
      |
      v
  numpy exhaustive vector matrix (local, .npy — no FAISS)
      |
      +--- User uploads ToS/Privacy Policy
      |        |
      |     Rule-engine detection (regex baseline) runs in parallel
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

## legal-corpora

| Corpus | License | Coverage | Source |
|--------|---------|----------|--------|
| **EUR-Lex** | CC-BY-4.0 | Full EU legislation incl. GDPR | data.europa.eu |
| **MultiEURLEX** | CC-BY-4.0 | 65K EU laws, 23 languages | HuggingFace |
| **US state law texts** | Public domain | CCPA/CPRA, CPA, CTDPA, SHIELD | State legislature sites |
| **PIPEDA** | Public domain | Canadian federal privacy law | laws-lois.justice.gc.ca |
| **CourtListener/RECAP** | Public domain | US court opinions, dockets | courtlistener.com |
| **CUAD** | CC-BY-4.0 | 510 contracts, 41 clause types | atticusprojectai.org |
| **LegalBench** | Open | 162 legal reasoning tasks | HuggingFace |

### L6: no-pile-of-law
rule: Pile of Law is CC-BY-NC-SA-4.0 (non-commercial); do NOT use for commercial product

## services-implemented

| Service | File | Purpose |
|---------|------|---------|
| `embedding.py` | `src/backend/app/services/` | Doc-chunk BM25 + dense + RRF ensemble (not yet wired into `analyzer.py`) |
| `legal_kb.py` | `src/backend/app/services/` | Legal KB: corpus parser, numpy exhaustive index builder, BM25/RRF retrieval — wired into `analyzer.py::analyze_text()` |
| `localai.py` | `src/backend/app/services/` | LLM client targeting LocalAI (Apertus-8B/EuroLLM-22B); never named `lm_studio.py` in actual codebase |

## deps-actually-added

| Package | License | Purpose |
|---------|---------|---------|
| rank_bm25 | Apache 2.0 | Sparse retrieval (BM25) — already a dep before legal-KB work |
| numpy | BSD | Exact/exhaustive vector similarity |

### L7: no-new-embedding-frameworks-added
rule: no `sentence-transformers`, `torch`, or `faiss-cpu` were added
because: dense embeddings reuse existing `LocalAIClient.embed()` HTTP call (Apertus-8B); vector index is plain numpy matrix
