# Project Structure Documentation

## Directory Organization

### `/src/demos/`
Active demonstration implementations of the AI Terms Reviewer:

- `ai_terms_reviewer_demo.html` - Original demo implementation
- `ai_terms_reviewer_beta_demo_v3_layout.html` - Beta version with improved layout
- `ai_terms_reviewer_v6_with_selftest.html` - Version with built-in validation testing
- `ai_terms_reviewer_v7_simple_mode.html` - Simplified mode for basic analysis
- `ai_terms_reviewer_simple_demo.html` - Minimal demo implementation
- `ai_terms_reviewer_diagrams.html` - Version with system diagrams

**Purpose**: Working prototypes and demonstrations of the tool's functionality.

### `/src/webapp/`
Complete production-ready web application:

- `index.html` - Main application HTML
- `style.css` - Application stylesheets
- `app.js` - Application JavaScript logic

**Purpose**: Full-featured web application implementation.

### `/docs/wireframes/`
UI/UX design wireframes:

- `reviewer_wireframe.png` - Main reviewer interface wireframe
- `reviewer_wireframe_v2.png` - Updated reviewer design
- `dashboard_wireframe.png` - Analytics dashboard wireframe
- `dashboard_wireframe_v2.png` - Updated dashboard design
- `all_up_template_wireframe.png` - Complete template layout
- `all_up_template_wireframe_v2.png` - Updated complete layout

**Purpose**: Visual design references for UI implementation.

### `/docs/specs/`
Technical specifications and requirements:

- `Enhanced Terms & Policies Reviewer Specification v2.pdf` - Enhanced specification (PDF)
- `TermsReviewerv2.rtf` - Comprehensive technical specification document (RTF)
- `TermsReviewer (1).rtf` - Earlier specification draft
- `terms_reviewer_rubric.md` - Evaluation rubric for product quality assessment

**Purpose**: Detailed requirements, architecture, implementation guidelines, and quality standards.

### `/archive/`
Historical versions and duplicates (22 files):

- Older demo versions (v1-v5)
- Duplicate wireframes
- Previous specification drafts
- User demo iterations

**Purpose**: Version history and backup copies. Not actively maintained.

## File Naming Conventions

### Demo Files
- Pattern: `ai_terms_reviewer_[version]_[feature].html`
- Example: `ai_terms_reviewer_v7_simple_mode.html`

### Wireframes
- Pattern: `[component]_wireframe[_version].png`
- Example: `dashboard_wireframe_v2.png`

### Documentation
- Pattern: `[DocumentType][Version].[extension]`
- Example: `TermsReviewerv2.rtf`

## Version History

### Current Active Versions
- **Demo**: v7 (simple mode), v6 (with self-test), v3 (layout)
- **Wireframes**: v2 (latest iteration)
- **Specs**: v2 (comprehensive spec)

### Archived Versions
- Beta demos v1-v2
- Original wireframes
- Early specification drafts

## Maintenance Guidelines

1. **Active Development**: Work in `/src/` and `/docs/`
2. **Archive Policy**: Move superseded versions to `/archive/` with datestamp
3. **Documentation**: Update specs in `/docs/specs/` before implementation changes
4. **Wireframes**: Keep `/docs/wireframes/` in sync with implemented designs

## Git Strategy

### Branches (Recommended)
- `main` - Stable, documented releases
- `develop` - Active development
- `feature/*` - Specific feature work

### Commit Guidelines
- Prefix commits: `feat:`, `fix:`, `docs:`, `style:`, `refactor:`
- Reference issue numbers when applicable

### What to Commit
- Source code (`/src/`)
- Documentation (`/docs/`, `README.md`)
- Configuration files (`.gitignore`)

### What NOT to Commit
- Archive files (`/archive/`) - optional, can be excluded
- Temporary/test files
- Personal notes
- System files (`.DS_Store`, etc.)

## Next Steps

1. Initialize Git repository: `git init`
2. Add remote: `git remote add origin [repository-url]`
3. Initial commit: `git add . && git commit -m "feat: initial project structure"`
4. Push to GitHub: `git push -u origin main`

## Additional Documentation Needed

- [ ] API documentation (if backend is added)
- [ ] User guide
- [ ] Developer setup instructions
- [ ] Testing strategy
- [ ] Deployment guide
- [ ] Contributing guidelines
- [ ] Code of conduct
- [ ] License selection
