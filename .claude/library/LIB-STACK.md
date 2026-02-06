# LIB-STACK: Tech Stack & Configuration

## Python Dependencies

| Package | Version | Purpose | License |
|---------|---------|---------|---------|
| fastapi | latest | Web framework | MIT |
| uvicorn | latest | ASGI server | BSD-3 |
| pydantic | v2 | Data validation, schemas | MIT |
| sqlalchemy | latest | ORM, database | MIT |
| httpx | latest | Async HTTP client (LM Studio, URL fetch) | BSD-3 |
| beautifulsoup4 | latest | HTML text extraction | MIT |
| pypdf | latest | PDF text extraction | BSD-3 |
| python-docx | latest | DOCX text extraction | MIT |
| striprtf | latest | RTF text extraction | BSD-3 |
| reportlab | latest | PDF export generation | BSD |
| pytesseract | latest | OCR fallback for scanned PDFs | Apache-2.0 |
| pillow | latest | Image processing for OCR | HPND |

## Test Dependencies (needed)

| Package | Purpose |
|---------|---------|
| pytest | Test runner |
| pytest-asyncio | Async test support |
| pytest-cov | Coverage reporting |
| respx | httpx mock (for LM Studio + URL fetch tests) |

## Configuration (env vars)

| Variable | Default | Purpose |
|----------|---------|---------|
| `LM_STUDIO_BASE_URL` | `http://localhost:1234/v1` | LM Studio endpoint |
| `LM_STUDIO_MODEL` | `qwen3-vl-4b-instruct-mlx` | Model name |
| `DATABASE_URL` | `sqlite:///data/terms_analysis.db` | SQLite path |
| `REVIEW_THRESHOLD` | `0.80` | Confidence threshold for HITL review |
| `LM_REQUEST_TIMEOUT_S` | `60` | LLM request timeout |
| `MAX_INPUT_CHARS` | `20000` | Max document text length |
| `ALLOWED_ORIGINS` | `http://localhost:8000,...` | CORS origins |
| `WATCHLIST_REFRESH_SECONDS` | `0` | Background refresh interval (0 = off) |

## Frontend Stack

| Tech | Purpose |
|------|---------|
| Vanilla HTML/CSS/JS | No build step, no bundler |
| Font Awesome | Icons (CSS-only) |
| CSS custom properties | Design tokens, light/dark theming |
| Fetch API | Backend communication |
| localStorage | Theme persistence, optional analytics rollup |
