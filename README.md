# AI Terms & Policies Reviewer

A privacy-focused tool for analyzing Terms of Service and Privacy Policies. Identifies high-risk clauses, maps compliance requirements, and explains implications in plain language.

## Features

- **Multi-format input**: URLs, PDFs, DOCX, RTF, HTML, or pasted text
- **Risk scoring**: Impact/Likelihood/Safeguards (IRP) methodology with letter grades
- **Jurisdiction mapping**: US (CA, CO, CT, NY, Federal), EU/GDPR, UK, Canada, Australia, Brazil
- **Industry profiles**: Retail, Finance, Health, Gaming, Social, Education
- **Watchlist monitoring**: Track policy changes over time
- **Vendor comparison**: Side-by-side risk analysis
- **Export options**: PDF reports, CSV, JSON

### Risk Categories

| Category | What it detects |
|----------|-----------------|
| Data Sharing | Third-party sales, data broker relationships |
| Automated Decisions | ADM/profiling without human review |
| Dark Patterns | Deceptive consent, hidden opt-outs |
| Retention | Indefinite storage, vague deletion timelines |
| User Rights | Missing access/correction/deletion mechanisms |
| Minors | Inadequate child protections |
| Sensitive Data | Biometrics, health, financial data handling |
| Unilateral Changes | Terms modifications without notice |
| Liability | Excessive limitations, forced arbitration |

## Quick Start

### Prerequisites

- Python 3.11+
- [LM Studio](https://lmstudio.ai/) running locally (for LLM-powered analysis)

### Installation

```bash
# Clone the repository
git clone https://github.com/jennifer-mckinney/terms-analysis.git
cd terms-analysis

# Run the setup script
./run.sh
```

The script will:
1. Create a Python virtual environment
2. Install dependencies
3. Initialize the SQLite database
4. Start the FastAPI backend on `http://localhost:8000`
5. Open the web UI

### Configuration

Copy `.env.example` to `.env` and adjust as needed:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `LOCALAI_BASE_URL` | `http://localhost:8080/v1` | LocalAI API endpoint |
| `MODEL_WORLD` | `apertus-8b-instruct` | World/multilingual model |
| `MODEL_EU` | `eurollm-22b-instruct` | EU legal-specialist model |
| `DATABASE_URL` | `sqlite:///./data/terms_analysis.db` | Database location |

## Architecture

```
terms-analysis/
├── src/
│   ├── webapp/              # Frontend (HTML/CSS/JS)
│   │   ├── index.html
│   │   ├── app.js
│   │   └── style.css
│   ├── backend/             # FastAPI backend
│   │   ├── app/
│   │   │   ├── main.py      # API endpoints
│   │   │   ├── services/    # Analysis, ingestion, LLM integration
│   │   │   └── models.py    # Database models
│   │   └── tests/
│   └── demos/               # Standalone demo versions
├── docs/
│   ├── specs/               # Technical specifications
│   ├── wireframes/          # UI/UX designs
│   ├── DESIGN.md            # Architecture documentation
│   └── LOCAL_DATA.md        # Data handling guide
└── archive/                 # Legacy versions
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/analyze` | Analyze raw text |
| `POST` | `/analyze/url` | Analyze document from URL |
| `POST` | `/analyze/file` | Analyze uploaded file |
| `GET` | `/analyses` | List all analyses |
| `GET` | `/analyses/{id}` | Get specific analysis |
| `GET` | `/watchlist` | List watched documents |
| `POST` | `/watchlist` | Add document to watchlist |
| `GET` | `/exports/analysis/{id}.pdf` | Export as PDF |

Full API documentation available at `http://localhost:8000/docs` when running.

## Risk Scoring

**IRP Score** = 0.5 × (Impact/5) + 0.4 × (Likelihood/5) - 0.3 × (Safeguards/5)

| Level | IRP Score | Grade |
|-------|-----------|-------|
| High | >= 0.75 | D or F |
| Medium | 0.45 - 0.74 | C |
| Low | < 0.45 | A or B |

## Development

### Running Tests

```bash
cd src/backend
pytest
```

### Evaluation

Test against the gold dataset:

```bash
python src/backend/scripts/evaluate.py
```

### Frontend Only

Open `src/webapp/index.html` directly in a browser for the UI without the backend (uses sample data).

## Limitations

This tool does **not**:
- Provide legal advice
- Replace qualified legal counsel
- Guarantee analysis completeness
- Make binding legal determinations

Use it for triage and due diligence, not as a substitute for professional review.

## License

TBD

## Contributing

TBD
