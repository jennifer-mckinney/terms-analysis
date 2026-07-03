# Repository Guidelines

## Project Structure & Module Organization
- `src/webapp/`: Streamlit UI (`app_streamlit_v2.py` is the sole UI; `app_streamlit_legacy.py` is the v1 rollback path via `STREAMLIT_UI=v1`).
- `src/demos/`: demo/prototype HTML files (multiple versions).
- `docs/specs/`: requirements, rubric, and technical specs.
- `docs/wireframes/`: UI references.
- `archive/`: historical versions; avoid editing unless archiving older files.

## Build, Test, and Development Commands
- `./run.sh`: launches the FastAPI backend on `http://localhost:9000` and the Streamlit UI on `http://localhost:8501`.
- `cd src/webapp && streamlit run app_streamlit_v2.py --server.port 8501 --server.headless true`: launch UI standalone.
- No build step or bundler is used; the UI is Streamlit Python.

## Coding Style & Naming Conventions
- Follow existing indentation: HTML/JS use 4 spaces; CSS uses 2 spaces.
- Keep formatting consistent with the file you’re editing; avoid reformatting unrelated areas.
- Demo naming pattern: `ai_terms_reviewer_[version]_[feature].html`.
- Wireframe naming pattern: `[component]_wireframe[_version].png`.
- Document naming pattern: `[DocumentType][Version].[extension]` (see `docs/PROJECT_STRUCTURE.md`).

## Testing Guidelines
- No automated test framework is configured.
- Do manual smoke checks in the browser after changes (load `http://localhost:8501` after `./run.sh`).
- Some demos include self-test/validation buttons (e.g., v6/v7 demos); use them for quick checks.

## Commit & Pull Request Guidelines
- Git history uses conventional prefixes (e.g., `feat: ...`); follow `feat:`, `fix:`, `docs:`, `style:`, `refactor:` as outlined in `docs/PROJECT_STRUCTURE.md`.
- Reference issues when applicable.
- PRs should include: a brief summary, linked issue (if any), and screenshots for UI changes.

## Security & Configuration Notes
- This is a client-only app; keep data local and avoid adding network calls unless explicitly approved.
- If you update specs or wireframes, keep `docs/specs/` and `docs/wireframes/` in sync with the implementation.
