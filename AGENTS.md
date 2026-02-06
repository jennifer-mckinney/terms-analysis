# Repository Guidelines

## Project Structure & Module Organization
- `src/webapp/`: main static app (`index.html`, `style.css`, `app.js`).
- `src/demos/`: demo/prototype HTML files (multiple versions).
- `docs/specs/`: requirements, rubric, and technical specs.
- `docs/wireframes/`: UI references.
- `archive/`: historical versions; avoid editing unless archiving older files.

## Build, Test, and Development Commands
- `./run.sh`: serves `src/webapp` on `http://localhost:8000` (installs Python via Homebrew if missing).
- `cd src/webapp && python3 -m http.server 8000`: manual static server alternative.
- No build step or bundler is used; the app is plain HTML/CSS/JS.

## Coding Style & Naming Conventions
- Follow existing indentation: HTML/JS use 4 spaces; CSS uses 2 spaces.
- Keep formatting consistent with the file you’re editing; avoid reformatting unrelated areas.
- Demo naming pattern: `ai_terms_reviewer_[version]_[feature].html`.
- Wireframe naming pattern: `[component]_wireframe[_version].png`.
- Document naming pattern: `[DocumentType][Version].[extension]` (see `docs/PROJECT_STRUCTURE.md`).

## Testing Guidelines
- No automated test framework is configured.
- Do manual smoke checks in the browser after changes (load `src/webapp/index.html`).
- Some demos include self-test/validation buttons (e.g., v6/v7 demos); use them for quick checks.

## Commit & Pull Request Guidelines
- Git history uses conventional prefixes (e.g., `feat: ...`); follow `feat:`, `fix:`, `docs:`, `style:`, `refactor:` as outlined in `docs/PROJECT_STRUCTURE.md`.
- Reference issues when applicable.
- PRs should include: a brief summary, linked issue (if any), and screenshots for UI changes.

## Security & Configuration Notes
- This is a client-only app; keep data local and avoid adding network calls unless explicitly approved.
- If you update specs or wireframes, keep `docs/specs/` and `docs/wireframes/` in sync with the implementation.
