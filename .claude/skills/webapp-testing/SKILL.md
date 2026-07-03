---
name: webapp-testing
description: Test the web application (Streamlit UI + FastAPI backend) using Playwright. Use when asked to "test the webapp", "browser test", "test the UI", or "check the frontend".
allowed-tools: Bash, Read, Write, Grep, Glob
---

# Web Application Testing (Playwright)

Adapted from Anthropic's webapp-testing skill for this project's FastAPI + Streamlit architecture. Streamlit v2 (`app_streamlit_v2.py`) is the sole UI; `app_streamlit_legacy.py` is retained only as the `STREAMLIT_UI=v1` rollback path.

## Prerequisites

Check and install if needed:
```bash
pip install playwright pytest-playwright
python -m playwright install chromium
```

## Architecture

| Component | URL | Start Command |
|-----------|-----|---------------|
| Backend API | `http://localhost:9000` | `cd src/backend && uvicorn app.main:app --port 9000` |
| Streamlit UI | `http://localhost:8501` | `cd src/webapp && streamlit run app_streamlit_v2.py --server.port 8501 --server.headless true` |

## Workflow

### 1. Start servers (if not running)
Use the helper script pattern — start both servers, run tests, tear down:
```python
import subprocess, time, signal

backend = subprocess.Popen(
    ["uvicorn", "app.main:app", "--port", "9000"],
    cwd="src/backend",
)
frontend = subprocess.Popen(
    ["streamlit", "run", "app_streamlit_v2.py",
     "--server.port", "8501", "--server.headless", "true"],
    cwd="src/webapp",
)
time.sleep(5)  # Streamlit boot is slower than a bare http.server
try:
    # ... run tests ...
finally:
    backend.send_signal(signal.SIGTERM)
    frontend.send_signal(signal.SIGTERM)
```

### 2. Reconnaissance first
Before any test actions:
- Navigate to page
- Wait for `networkidle`
- Take screenshot to understand current state
- Inspect DOM to identify selectors (Streamlit exposes stable `data-testid` attributes on most primitives — prefer those over class-name selectors, which are hashed and change build-to-build)

### 3. Test categories

| Category | What to Test |
|----------|-------------|
| Intake tabs | Link / Text / File tab switching, character counter, short-text warning |
| Context chips | 5 multi-select chips (want_understand, for_child, for_care, for_work, just_curious), weight-tier hover help |
| Location filter | Empty = "no filter"; multi-select of jurisdictions; Select-All / Clear-All controls |
| Analyze flow | Submit → progress indicator → results render |
| Domain sections | 4 fixed domains (Data, Data use, Terms of use, Privacy rights) rendered from `top_by_domain` |
| Verdict framing | Two-voice copy conventions (LIB-VOICE); no em-dashes; tentative framings |
| Scope box | Always visible, never collapsible; hardware & real-world-practice caveats present |
| Verify view | "View in full document" expander opens; excerpt-in-context visible |
| API integration | `requests` calls reach backend on :9000; error banners on backend down |
| Responsive | Key layouts work at mobile and desktop widths |

### 4. Always use sync Playwright
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("http://localhost:8501")
    page.wait_for_load_state("networkidle")
    # ... test actions ...
    page.screenshot(path="screenshot.png")
    browser.close()
```

### 5. Selector patterns (Streamlit)

Streamlit component selectors are stable on `data-testid`:

```
tabs:               [data-testid="stTabs"] button[role="tab"]
text area:          [data-testid="stTextArea"] textarea
file uploader:      [data-testid="stFileUploaderDropzone"]
multiselect:        [data-testid="stMultiSelect"]
buttons:            [data-testid="stButton"] button
expander header:    [data-testid="stExpander"] summary
markdown blocks:    [data-testid="stMarkdownContainer"]
```

For app-specific elements (chip cards, domain headers, verdict banner), locate by visible text via `page.get_by_text(...)` or `page.get_by_role("heading", name=...)`.

## Arguments
- `$ARGUMENTS`: specific test category (e.g., "intake", "chips", "verdict", "scope-box", "api") or "all"
- No arguments = run full test suite
