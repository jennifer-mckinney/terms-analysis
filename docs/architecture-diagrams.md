# System Architecture & Flow Diagrams

---

## L1 — System Context

High-level boundary view. What the system is, who uses it, and what it talks to.

```mermaid
graph TB
    classDef user     fill:#f5f2f5,stroke:#5e4c5f,color:#3d2e3e,font-weight:600
    classDef frontend fill:#eef4fb,stroke:#4a7fb5,color:#1e3a5f,font-weight:600
    classDef backend  fill:#fff8ee,stroke:#c49a3c,color:#5a3e00,font-weight:600
    classDef ai       fill:#eefaf4,stroke:#3a8c5c,color:#1a4a30,font-weight:600
    classDef data     fill:#fdf2f2,stroke:#8b3a3a,color:#5a1a1a,font-weight:600
    classDef ext      fill:#f0f0f0,stroke:#888,color:#444

    USER["👤 User\n(browser)"]:::user

    subgraph LOCAL ["Local Machine — all data stays here"]
        FE1["Streamlit UI\n:8501"]:::frontend
        BE["FastAPI Backend\n:9000\n24 endpoints + /health"]:::backend

        subgraph AI ["AI / ML Layer"]
            LLM["LocalAI\nApertus-8B-Instruct · EuroLLM-22B-Instruct"]:::ai
            LKB["Legal KB\nnumpy-exhaustive + BM25/RRF\n(wired into analyze_text)"]:::ai
            EMB["Doc-chunk Embedding Ensemble\nBM25 + dense + RRF\n(NOT wired into analyze_text)"]:::ai
            RULES["Rule Engine\n64 patterns · ~50 categories · 30 jurisdictions"]:::ai
        end

        DB[("SQLite\nDatabase")]:::data
    end

    EXT["External URLs\n(policy pages, legal-corpus sources)"]:::ext

    USER -->|"HTTP :8501"| FE1
    FE1  -->|"REST :9000"| BE
    BE   -->|orchestrates| AI
    BE   <-->|read / write| DB
    BE   -->|"HTTP (SSRF-validated)"| EXT

    style LOCAL fill:#fafafa,stroke:#ddd
    style AI    fill:#f5faf7,stroke:#bde
```

---

## L2 — Component Architecture

Service-level view. Every module, its responsibilities, and how data moves between them.

```mermaid
graph TB
    classDef tab      fill:#eef4fb,stroke:#4a7fb5,color:#1e3a5f
    classDef endpoint fill:#fff8ee,stroke:#c49a3c,color:#5a3e00
    classDef svc      fill:#f5f2f5,stroke:#5e4c5f,color:#3d2e3e
    classDef ai       fill:#eefaf4,stroke:#3a8c5c,color:#1a4a30
    classDef model    fill:#e8f4e8,stroke:#5a9c5a,color:#1a3a1a
    classDef db       fill:#fdf2f2,stroke:#8b3a3a,color:#5a1a1a
    classDef dead     fill:#f5f5f5,stroke:#aaa,color:#666,stroke-dasharray: 5 5

    subgraph FE1 ["Streamlit UI  :8501"]
        TA["Analyze tab"]:::tab
        TF["Findings tab"]:::tab
        TC["Compare tab"]:::tab
        TE["Export tab"]:::tab
    end

    subgraph API ["FastAPI  :9000"]
        direction TB
        subgraph INGEST_EP ["Analyze endpoints"]
            EP1["POST /analyze"]:::endpoint
            EP2["POST /analyze/url"]:::endpoint
            EP3["POST /analyze/file"]:::endpoint
            EP4["POST /analyze/batch"]:::endpoint
        end
        subgraph RESULTS_EP ["Result endpoints"]
            EP5["GET /analyses"]:::endpoint
            EP6["GET /analyses/{id}"]:::endpoint
            EP7["GET /rubric"]:::endpoint
        end
        subgraph EXPORT_EP ["Export endpoints"]
            EP8["GET /exports/analysis/{id}.pdf"]:::endpoint
            EP9["GET /exports/analyses.csv"]:::endpoint
            EP10["GET /exports/analysis/{id}"]:::endpoint
        end
        subgraph WATCH_EP ["Watchlist / Snapshot / Policy-watch (12 endpoints)"]
            EP11["POST/GET /watchlist\nDELETE /watchlist/{id}\nPOST /watchlist/{id}/refresh"]:::endpoint
            EP13["GET/POST /snapshots\nGET /snapshots/detail/{id}"]:::endpoint
            EP14["GET /diff/{id1}/{id2}"]:::endpoint
            EP16["POST/GET /policy-watch\nDELETE /policy-watch/{id}\nPOST /policy-watch/{id}/snapshot"]:::endpoint
        end
        subgraph REVIEW_EP ["Human review"]
            EP15["GET /reviews"]:::endpoint
            EP17["POST /reviews/{id}"]:::endpoint
        end
        PERSIST["_persist_analysis()"]:::endpoint
    end

    subgraph SERVICES ["Services"]
        ING["ingest.py\nextract_text_from_bytes()\nfetch_url_text()\nSSRF blocklist"]:::svc
        ANA["analyzer.py  ← orchestrator\nanalyze_text()\n_merge_findings()\ncalculate_risk_score() — severity-weighted"]:::svc
        RUL["rules.py\ndetect_findings()\n64 patterns · ~50 categories · 30 jurisdictions\nconfidence clamp 0.90–0.95"]:::svc
        VAL["validation.py\nvalidate_findings()"]:::svc
        DIF["diffing.py\ncontent_hash()\ndiff_tokens()\ndiff_summary()"]:::svc
        LKB["legal_kb.py\nLegalKnowledgeBase\nbuild() / retrieve()\nnumpy-exhaustive + BM25/RRF"]:::svc
        EMB["embedding.py\nchunk_text() / bm25_scores() / rrf_fuse()\nselect_relevant_chunks() — NOT called by analyzer.py"]:::dead
        LOC["localai.py\nLocalAIClient\n_select_model() · embed()"]:::svc
    end

    subgraph AIMODELS ["AI Models — LocalAI"]
        EUR["EuroLLM-22B-Instruct\nEU / legal specialist\n35 languages"]:::model
        APE["Apertus-8B-Instruct\nWorld model\n1,000+ languages"]:::model
    end

    subgraph DBL ["SQLite — Data Layer"]
        T1[("Analysis\nid · document_text · result_json\nrisk_score · grade · status")]:::db
        T2[("ReviewItem\nanalysis_id · status · notes")]:::db
        T3[("WatchlistItem\nvendor · source_url\nlast_document_hash · last_analysis_id")]:::db
        T4[("PolicySnapshot\nurl · content_hash · raw_text")]:::db
        T5[("PolicyWatch\nurl · check_frequency")]:::db
    end

    subgraph CORPUS ["Legal Corpus (source)"]
        C1[("data/legal_corpus/&lt;jurisdiction&gt;/&lt;law&gt;.txt\ncurrently placeholder text —\nreal statutes pending (issue #6)")]:::db
    end

    %% Frontend → API
    TA -->|POST| EP1
    TA -->|POST| EP2
    TA -->|POST| EP3
    TF -->|GET| EP5
    TF -->|GET| EP6
    TE -->|GET| EP8
    TE -->|GET| EP9

    %% API → Services
    EP1 & EP2 & EP3 & EP4 --> ING
    ING --> ANA
    ANA --> RUL
    ANA --> LKB
    ANA --> LOC
    ANA --> VAL
    EP11 & EP13 --> DIF
    EP14 --> DIF

    %% Services → AI models
    LOC -->|"EU / legal text"| EUR
    LOC -->|"non-EU / multilingual"| APE
    LKB -->|"embed() calls"| LOC
    LKB -.->|"chunk_text / bm25_scores / rrf_fuse (shared helpers)"| EMB
    LKB -->|"reads at build time"| C1

    %% Persist
    ANA --> PERSIST
    PERSIST --> T1
    T1 -.->|FK| T2
    T3 -.->|last_analysis_id| T1
    T4 -.-> T5

    style FE1 fill:#f0f5fc,stroke:#c0d4f0
    style FE2 fill:#f0f5fc,stroke:#c0d4f0
    style API     fill:#fffcf0,stroke:#f0e0b0
    style SERVICES fill:#f8f5f8,stroke:#d0c0d0
    style AIMODELS fill:#f0faf4,stroke:#b0d8c0
    style DBL     fill:#fdf5f5,stroke:#f0c0c0
```

---

## Data Flow — Document to Findings

How a single document travels through the analysis pipeline.

```mermaid
flowchart TD
    classDef input   fill:#eef4fb,stroke:#4a7fb5,color:#1e3a5f,font-weight:600
    classDef proc    fill:#f5f2f5,stroke:#5e4c5f,color:#3d2e3e
    classDef ai      fill:#eefaf4,stroke:#3a8c5c,color:#1a4a30
    classDef gate    fill:#fff8ee,stroke:#c49a3c,color:#5a3e00,font-weight:600
    classDef output  fill:#fdf2f2,stroke:#8b3a3a,color:#5a1a1a,font-weight:600

    INPUT(["Document Input\ntext · URL · file\nPDF · DOCX · RTF · HTML"]):::input

    subgraph INGEST ["1 · Ingest  ingest.py"]
        FETCH["URL fetch\nSSRF-validated\nhttpx + blocklist"]:::proc
        EXTRACT["Text extraction\nPDF → pypdf\nDOCX → python-docx\nHTML → BeautifulSoup\nOCR fallback"]:::proc
        NORM["Normalise\nwhitespace · line numbers\ntruncate to MAX_CHARS\n(head-truncation — embedding.py's\nchunk-selection is NOT wired in here)"]:::proc
    end

    subgraph PARALLEL ["2 · Detection"]
        direction LR
        subgraph RULES_PASS ["Rule Pass  rules.py"]
            RP1["Pattern match\n64 patterns\n30 jurisdictions"]:::ai
            RP2["Confidence score\n_confidence_rules_based()\nclamp [0.90–0.95]"]:::ai
        end
        subgraph LEGALKB_PASS ["Legal-KB Retrieval  legal_kb.py"]
            LK1["Query = jurisdictions + doc excerpt"]:::ai
            LK2["Embed query via LocalAIClient"]:::ai
            LK3["Numpy exhaustive dot-product\n(exact cosine similarity, no FAISS)"]:::ai
            LK4["BM25 + RRF fusion\nover dense hits"]:::ai
            LK5["Top-K legal passages\n(jurisdiction-filtered)"]:::ai
        end
        subgraph LLM_PASS ["LLM Pass  localai.py"]
            LP1["Language detect\nlangdetect"]:::ai
            LP2{"Route model"}:::gate
            LP3["EuroLLM-22B-Instruct\nEU / legal text"]:::ai
            LP4["Apertus-8B-Instruct\nmultilingual"]:::ai
            LP5["Structured\nfinding extraction\n(prompt augmented with\nlegal-KB context)"]:::ai
        end
    end

    subgraph MERGE ["3 · Merge  analyzer.py"]
        MRG["_merge_findings()\ndeduplicate on\ncategory + excerpt offset"]:::proc
        DWT["_apply_doctype_weighting()"]:::proc
        IND["_apply_industry_emphasis()"]:::proc
    end

    subgraph VALIDATE ["4 · Validate  validation.py"]
        VAL["validate_findings()\nexcerpt anchor check\nconfidence penalty\nduplicate suppression"]:::proc
    end

    subgraph SCORE ["5 · Score  analyzer.py"]
        RISK["calculate_risk_score()\nseverity-weighted average\nweight: Low .2 · Med .5 · High .8 · Critical 1.0\nscore = 10 × mean(weight)"]:::proc
        GRADE["Grade mapping (higher = worse)\n&lt;3.5 A · &lt;4.5 A- · &lt;5.5 B\n&lt;6.5 B- · &lt;7.5 C+ · &lt;8.5 C · ≥8.5 D+"]:::proc
        CONF["Confidence < 0.80\n→ human review flag"]:::gate
    end

    subgraph PERSIST ["6 · Persist  main.py"]
        DB[("SQLite\nAnalysis row\nresult_json blob")]:::output
        REV["ReviewItem created\nif low confidence"]:::output
    end

    RESPONSE(["JSON Response\nfindings · risk_score · grade\nconfidence · jurisdiction_map"]):::output

    INPUT --> FETCH --> EXTRACT --> NORM
    NORM --> RP1 --> RP2
    NORM --> LK1 --> LK2 --> LK3 --> LK4 --> LK5
    NORM --> LP1 --> LP2
    LK5 --> LP5
    LP2 -->|"EU / legal"| LP3 --> LP5
    LP2 -->|"other"| LP4 --> LP5
    RP2 & LP5 --> MRG --> DWT --> IND
    IND --> VAL --> RISK --> GRADE --> CONF
    CONF -->|"≥ 0.80"| DB
    CONF -->|"< 0.80"| REV
    DB --> RESPONSE
```

---

## User Journey — Swim Lane

End-to-end journey across all actors from first visit to export, using the Streamlit UI.

```mermaid
sequenceDiagram
    actor User
    participant UI   as Streamlit UI<br/>:8501
    participant API  as FastAPI<br/>:9000
    participant SVC  as Analysis Engine<br/>services/
    participant LKB  as Legal KB<br/>legal_kb.py
    participant AI   as LocalAI<br/>Apertus · EuroLLM
    participant DB   as SQLite

    rect rgb(240, 245, 255)
        note over User,UI: Onboarding
        User  ->> UI   : Open app (first visit)
        UI    -->> User: Analyze tab · progress steps · legal disclaimer
    end

    rect rgb(245, 252, 248)
        note over User,API: Document submission
        User  ->> UI   : Paste text / enter URL / upload file
        User  ->> UI   : Select jurisdiction (e.g. GDPR) + industry + depth
        User  ->> UI   : Click "Analyze document"
        UI    ->> API  : POST /analyze  {text, jurisdictions, industry, mode}
        note right of API: Validate inputs<br/>SSRF-check if URL
        API   ->> SVC  : extract_text_from_bytes() or fetch_url_text()
        SVC   -->> API : normalised plain text
    end

    rect rgb(255, 252, 240)
        note over API,AI: Parallel detection
        par Rule pass
            API ->> SVC : detect_findings(text, jurisdictions)
            SVC -->> API: rule findings + confidence (0.90–0.95 clamp)
        and Legal-KB retrieval
            API ->> LKB : retrieve(query, client, jurisdictions)
            LKB -->> API: top-K legal passages (numpy-exhaustive + BM25/RRF), or [] if index/endpoint unavailable
        and LLM pass
            API ->> SVC  : _select_model(text) → language route
            SVC ->> AI   : prompt + rule findings + legal-KB context
            AI  -->> SVC : structured findings JSON
            SVC -->> API : LLM findings + confidence
        end
    end

    rect rgb(248, 245, 252)
        note over API,DB: Merge, score, persist
        API  ->> SVC  : _merge_findings() + doctype/industry weighting
        SVC  -->> API : merged + weighted findings
        API  ->> SVC  : validate_findings()
        SVC  -->> API : validated findings + confidence flags
        API  ->> SVC  : calculate_risk_score() → grade (severity-weighted, 0–10 scale)
        API  ->> DB   : INSERT Analysis (result_json, risk_score, grade)
        alt confidence < 0.80
            API ->> DB : INSERT ReviewItem (needs human review)
        end
        DB   -->> API : analysis_id
        API  -->> UI  : AnalysisPayload {id, findings, risk_score, grade}
    end

    rect rgb(245, 252, 248)
        note over User,UI: Review findings
        UI    -->> User: "Analysis complete — N findings. Open Findings tab."
        User  ->> UI   : Click Findings tab
        UI    -->> User: Severity metrics · findings dataframe
        User  ->> UI   : Click row in findings table
        UI    -->> User: Detail panel (excerpt highlighted · analysis text)
        User  ->> UI   : Click "Recommended actions"
        UI    -->> User: st.popover — specific regulatory actions
    end

    rect rgb(255, 245, 240)
        note over User,DB: Export
        User  ->> UI   : Click Export tab
        User  ->> UI   : Click "Download PDF"
        UI    ->> API  : GET /exports/analysis/{id}.pdf
        API   ->> DB   : SELECT Analysis WHERE id={id}
        DB    -->> API : result_json + metadata
        API   -->> UI  : PDF binary (ReportLab)
        UI    -->> User: Browser download — policy_analysis.pdf
    end

    rect rgb(240, 248, 255)
        note over User,DB: Watchlist (async background)
        User  ->> UI   : Add vendor to watchlist
        UI    ->> API  : POST /watchlist {source_url, vendor}
        API   ->> DB   : INSERT WatchlistItem
        note over API,DB: Background loop (lifespan task, WATCHLIST_REFRESH_SECONDS)
        API   ->> SVC  : fetch_url_text(url)
        SVC   -->> API : new text
        API   ->> SVC  : content_hash() — compare to last_document_hash
        alt hash changed
            API ->> SVC : diff_tokens(old, new)
            SVC -->> API: token-level diff + risk delta
            API ->> DB  : UPDATE WatchlistItem · INSERT Analysis
        end
    end
```

---

*All components run locally. No data leaves the machine, except one-time legal-corpus ingestion from public government sources (offline, not part of the request-serving path). Architecture as of 2026-07-03 — reconciled against actual implementation (see issues #6/#7).*
