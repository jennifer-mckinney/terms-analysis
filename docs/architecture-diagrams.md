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
        FE["Streamlit Frontend\n:8503"]:::frontend
        BE["FastAPI Backend\n:8000\n16 endpoints"]:::backend

        subgraph AI ["AI / ML Layer"]
            LLM["LocalAI\nEuroLLM-9B · Apertus"]:::ai
            EMB["Embedding Engine\nBM25 + Dense + RRF"]:::ai
            RULES["Rule Engine\n39 rules · 30 jurisdictions"]:::ai
        end

        DB[("SQLite\nDatabase")]:::data
    end

    EXT["External URLs\n(policy pages)"]:::ext

    USER -->|"HTTP :8503"| FE
    FE   -->|"REST :8000"| BE
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

    subgraph FE ["Streamlit Frontend  :8503"]
        TA["Analyze tab"]:::tab
        TF["Findings tab"]:::tab
        TC["Compare tab"]:::tab
        TE["Export tab"]:::tab
    end

    subgraph API ["FastAPI  :8000"]
        direction TB
        subgraph INGEST_EP ["Ingest endpoints"]
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
        subgraph WATCH_EP ["Watchlist / Snapshot"]
            EP11["POST /watchlist"]:::endpoint
            EP12["POST /watchlist/{id}/refresh"]:::endpoint
            EP13["POST /snapshots"]:::endpoint
            EP14["GET /diff/{id1}/{id2}"]:::endpoint
        end
        subgraph REVIEW_EP ["Human review"]
            EP15["GET /reviews"]:::endpoint
            EP16["POST /reviews/{id}"]:::endpoint
        end
        PERSIST["_persist_analysis()"]:::endpoint
    end

    subgraph SERVICES ["Services"]
        ING["ingest.py\nextract_text_from_bytes()\nfetch_url_text()\n_validate_url() — SSRF block"]:::svc
        ANA["analyzer.py  ← orchestrator\nanalyze_text()\n_merge_findings()\n_apply_doctype_weighting()\n_apply_industry_emphasis()\ncalculate_risk_score()"]:::svc
        RUL["rules.py\ndetect_findings()\n39 patterns · 30 jurisdictions\nIRP confidence scoring"]:::svc
        VAL["validation.py\nvalidate_findings()\nconfidence clamp [0.35–0.95]"]:::svc
        DIF["diffing.py\ncontent_hash()\ndiff_tokens()\ndiff_summary()"]:::svc
        EMB["embedding.py\nbm25_scores()\nrrf_fuse()\nselect_relevant_chunks()"]:::svc
        LOC["localai.py\nLocalAIClient\n_select_model()"]:::svc
    end

    subgraph AIMODELS ["AI Models — LocalAI"]
        EUR["EuroLLM-9B\nEU / legal specialist\n35 languages"]:::model
        APE["Apertus\nWorld model\n1 000+ languages"]:::model
    end

    subgraph DBL ["SQLite — Data Layer"]
        T1[("Analysis\nid · text · findings_json\nrisk_score · grade · status")]:::db
        T2[("ReviewItem\nanalysis_id · status\nreviewer_notes")]:::db
        T3[("WatchlistItem\nurl · last_hash\nlast_analysis_id")]:::db
        T4[("PolicySnapshot\nurl · content_hash\nraw_text")]:::db
        T5[("PolicyWatch\nurl · schedule")]:::db
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
    ANA --> EMB
    ANA --> LOC
    ANA --> VAL
    EP12 & EP13 --> DIF
    EP14 --> DIF

    %% Services → AI models
    LOC -->|"EU / legal text"| EUR
    LOC -->|"non-EU / multilingual"| APE

    %% Persist
    ANA --> PERSIST
    PERSIST --> T1
    T1 -.->|FK| T2
    T3 -.->|last_analysis_id| T1
    T4 -.-> T5

    style FE      fill:#f0f5fc,stroke:#c0d4f0
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
        NORM["Normalise\nwhitespace · line numbers\ntruncate to MAX_CHARS"]:::proc
    end

    subgraph PARALLEL ["2 · Detection  — parallel passes"]
        direction LR
        subgraph RULES_PASS ["Rule Pass  rules.py"]
            RP1["Pattern match\n39 regex rules\n30 jurisdictions"]:::ai
            RP2["Confidence score\nIRP formula\nclamp [0.35–0.95]"]:::ai
        end
        subgraph EMBED_PASS ["Embedding Pass  embedding.py"]
            EP1["Chunk text\n1 200 token windows\n15% overlap"]:::ai
            EP2["BM25 lexical score"]:::ai
            EP3["Dense semantic score\nApertus encoder"]:::ai
            EP4["RRF fusion\nk=60 reciprocal rank"]:::ai
            EP5["Top-K relevant chunks"]:::ai
        end
        subgraph LLM_PASS ["LLM Pass  localai.py"]
            LP1["Language detect\nlangdetect"]:::ai
            LP2{"Route model"}:::gate
            LP3["EuroLLM-9B\nEU / legal text"]:::ai
            LP4["Apertus\nmultilingual"]:::ai
            LP5["Structured\nfinding extraction"]:::ai
        end
    end

    subgraph MERGE ["3 · Merge  analyzer.py"]
        MRG["_merge_findings()\ndeduplicate on\ncategory + excerpt offset"]:::proc
        DWT["_apply_doctype_weighting()\nPrivacy Policy → sale/share ↑\nToS → liability ↑\nCookie → tracking ↑"]:::proc
        IND["_apply_industry_emphasis()\nHealthcare → HIPAA ↑\nFinance → GLBA ↑\nChildren → COPPA ↑"]:::proc
    end

    subgraph VALIDATE ["4 · Validate  validation.py"]
        VAL["validate_findings()\nexcerpt anchor check\nconfidence penalty\nduplicate suppression"]:::proc
    end

    subgraph SCORE ["5 · Score  analyzer.py"]
        RISK["calculate_risk_score()\nIRP = 0.5×(I/5) + 0.4×(L/5) − 0.3×(S/5)\nweighted average"]:::proc
        GRADE["Grade mapping\n0–3 A · 3–5 B · 5–7 C+\n7–8 C · 8–9 D+ · 9–10 D"]:::proc
        CONF["Confidence < 0.80\n→ human review flag"]:::gate
    end

    subgraph PERSIST ["6 · Persist  main.py"]
        DB[("SQLite\nAnalysis row\nfindings JSON")]:::output
        REV["ReviewItem created\nif low confidence"]:::output
    end

    RESPONSE(["JSON Response\nfindings · risk_score · grade\nconfidence · jurisdiction_map"]):::output

    INPUT --> FETCH --> EXTRACT --> NORM
    NORM --> RP1 --> RP2
    NORM --> EP1 --> EP2 & EP3 --> EP4 --> EP5 --> LP1
    LP1 --> LP2
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

End-to-end journey across all actors from first visit to export.

```mermaid
sequenceDiagram
    actor User
    participant UI   as Streamlit UI<br/>:8503
    participant API  as FastAPI<br/>:8000
    participant SVC  as Analysis Engine<br/>services/
    participant AI   as LocalAI<br/>EuroLLM · Apertus
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
            SVC -->> API: rule findings + IRP confidence
        and Embedding pass
            API ->> SVC  : select_relevant_chunks(text)
            SVC -->> API : top-K chunks via BM25 + RRF
        and LLM pass
            API ->> SVC  : _select_model(text) → language route
            SVC ->> AI   : prompt + relevant chunks
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
        API  ->> SVC  : calculate_risk_score() → grade
        API  ->> DB   : INSERT Analysis (findings_json, risk_score, grade)
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
        DB    -->> API : findings + metadata
        API   -->> UI  : PDF binary (ReportLab Platypus)
        UI    -->> User: Browser download — policy_analysis.pdf

        User  ->> UI   : Click "Download CSV"
        UI    -->> User: findings CSV (in-browser, no API call)
    end

    rect rgb(240, 248, 255)
        note over User,DB: Watchlist (async background)
        User  ->> UI   : Add vendor to watchlist
        UI    ->> API  : POST /watchlist {url, name}
        API   ->> DB   : INSERT WatchlistItem
        note over API,DB: Background loop (lifespan task)<br/>runs every N hours
        API   ->> SVC  : fetch_url_text(url)
        SVC   -->> API : new text
        API   ->> SVC  : content_hash() — compare to stored hash
        alt hash changed
            API ->> SVC : diff_tokens(old, new)
            SVC -->> API: token-level diff + risk delta
            API ->> DB  : UPDATE WatchlistItem · INSERT Analysis
        end
    end
```

---

*All components run locally. No data leaves the machine. Architecture as of 2026-06-28.*
