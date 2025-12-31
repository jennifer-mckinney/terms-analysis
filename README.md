# AI Terms & Policies Reviewer

An automated privacy-focused legal technology tool that analyzes Terms of Service (ToS) and Privacy Policies for potential risks and compliance issues.

## Overview

This tool helps individuals and organizations quickly identify rights-infringing language and high-risk clauses in legal documents. It provides jurisdiction-specific compliance mapping and explains implications in plain language with direct citations.

## Key Features

- **Privacy-First**: Runs entirely locally in the browser - no data leaves your device
- **Multi-Format Input**: Supports URLs, PDFs, and pasted text
- **Risk Scoring**: Uses Impact/Likelihood/Safeguards (IRP) methodology
- **9 Risk Categories**:
  - Data Selling/Third-Party Sharing
  - Automated Decision Making
  - Dark Patterns (deceptive consent)
  - Data Retention Policies
  - User Rights (access, deletion, correction)
  - Minors/Children Protections
  - Sensitive Data Handling
  - Unilateral Terms Changes
  - Liability Limitations
- **Jurisdiction Support**: US (CA, CO, CT, NY, Federal), EU (GDPR), UK
- **Industry-Specific Analysis**: Retail, Finance, Health, Gaming, Social, Education
- **Dashboard Analytics**: Aggregated KPIs and heatmaps
- **Validation System**: Built-in testing with F1 scores and Cohen's Kappa

## Project Structure

```
terms-analysis/
├── src/
│   ├── demos/           # Demo HTML implementations (6 files)
│   └── webapp/          # Full web application (index.html, style.css, app.js)
├── docs/
│   ├── wireframes/      # UI/UX wireframes (6 files)
│   └── specs/           # Technical specifications & rubric (4 files)
├── archive/             # Older versions and duplicates (22 files)
├── README.md
├── .gitignore
└── GITHUB_SETUP.md
```

## Risk Scoring Methodology

**IRP Score** = 0.5 × (Impact/5) + 0.4 × (Likelihood/5) - 0.3 × (Safeguards/5)

- **Impact (I)**: Severity of the issue (1-5)
- **Likelihood (L)**: Probability of risk materialization (1-5)
- **Safeguards (S)**: Protections/mitigations in place (1-5)

**Risk Levels**:
- 🔴 **Red** (High): IRP ≥ 0.75
- 🟡 **Yellow** (Medium): 0.45 ≤ IRP < 0.75
- 🟢 **Green** (Low): IRP < 0.45

## Target Stakeholders

- Individual consumers reviewing service agreements
- SMB founders and product leads vetting third-party services
- Privacy champions in startups
- Digital rights advocates
- Procurement teams conducting vendor due diligence

## Document Types Supported

- Terms of Service (ToS)
- Privacy Policies
- Cookie Policies
- End User License Agreements (EULA)
- Data Processing Agreements (DPA)
- In-app privacy notices
- Data retention and residency policies

## Technical Details

- **Client-Side Only**: No backend required
- **localStorage**: For optional anonymized analytics aggregation
- **Pattern Matching**: Regex-based heuristics for clause detection
- **Compliance Mapping**: Pre-configured regulatory knowledge base
- **Version Control**: Supports diff analysis of policy changes

## Status

**Version**: Beta (v1 Draft Complete)
**Last Updated**: September 2025

## Non-Goals

This tool does NOT:
- Provide legal advice or replace qualified counsel
- Guarantee completeness of analysis
- Make legally binding determinations

It accelerates triage and due diligence by highlighting potential issues with traceable evidence.

## Development Notes

See `docs/specs/` for detailed technical specifications and requirements.
See `docs/LOCAL_DATA.md` for local-only data handling and backup guidance.
OCR fallback for scanned PDFs requires local Tesseract (`brew install tesseract`).
If you want a different LM Studio target, add a `./.env` with e.g. `LM_STUDIO_BASE_URL=http://localhost:1234/v1` and rerun.

## License

[To be determined]

## Contributing

[To be determined]
