---
name: webapp-testing
description: Test the web application (frontend + API) using Playwright. Use when asked to "test the webapp", "browser test", "test the UI", "check the frontend", or to verify that the SPA works correctly with the FastAPI backend.
allowed-tools: Bash, Read, Write, Grep, Glob
---

# Web Application Testing (Playwright)

Adapted from Anthropic's webapp-testing skill for this project's FastAPI + vanilla JS SPA architecture.

## Prerequisites

Check and install if needed:
```bash
pip install playwright pytest-playwright
python -m playwright install chromium
```

## Architecture

| Component | URL | Start Command |
|-----------|-----|---------------|
| Backend API | `http://localhost:8001` | `cd src/backend && uvicorn app.main:app --port 8001` |
| Frontend SPA | `http://localhost:8000` | `cd src/webapp && python3 -m http.server 8000` |

## Workflow

### 1. Start servers (if not running)
Use the helper script pattern — start both servers, run tests, tear down:
```python
import subprocess, time, signal

backend = subprocess.Popen(["uvicorn", "app.main:app", "--port", "8001"],
                           cwd="src/backend")
frontend = subprocess.Popen(["python3", "-m", "http.server", "8000"],
                            cwd="src/webapp")
time.sleep(3)  # Wait for servers
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
- Inspect DOM to identify selectors

### 3. Test categories

| Category | What to Test |
|----------|-------------|
| Navigation | All 6 pages load, nav buttons switch correctly |
| Theme | Toggle cycles auto → light → dark, persists in localStorage |
| Document Review | Text input, file upload, analyze button triggers API call |
| Comparison | Vendor selectors populate, comparison table renders |
| Watchlist | Add/remove vendors, filter by status |
| Reports | Rubric scores display, export buttons work |
| API Integration | Fetch calls reach backend, error states handled |
| Responsive | Key layouts work at mobile and desktop widths |

### 4. Always use sync Playwright
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("http://localhost:8000")
    page.wait_for_load_state("networkidle")
    # ... test actions ...
    page.screenshot(path="screenshot.png")
    browser.close()
```

### 5. Key selectors (from index.html + app.js)
```
nav buttons:     .nav-btn[data-page="dashboard|review|compare|watchlist|reports|settings"]
theme toggle:    #themeToggle
analyze button:  #analyzeBtn
document URL:    #documentUrl
document text:   #documentText
file input:      #fileInput
results section: #resultsSection
vendor selects:  #vendor1Select, #vendor2Select, #vendor3Select
compare button:  #compareBtn
watchlist grid:  #watchlistGrid
rubric grid:     #rubricGrid
modal:           #modal
toast container: #toastContainer
```

## Arguments
- `$ARGUMENTS`: specific test category (e.g., "navigation", "theme", "api") or "all"
- No arguments = run full test suite
