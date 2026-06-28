"""
Terms & Policy Analyzer — Streamlit frontend
"""
from __future__ import annotations

import re
import streamlit as st
import requests
from typing import List, Dict

st.set_page_config(
    page_title="Terms & Policy Analyzer",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    /* System font stack — no external requests */
    :root {
        --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                     "Helvetica Neue", Arial, sans-serif;
        --font-mono: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;

        /* Mauve palette */
        --mauve-900: #3d2e3e;
        --mauve-700: #5e4c5f;
        --mauve-500: #8a7a8b;
        --mauve-200: #d8cfd9;
        --mauve-50:  #f5f2f5;

        /* Gold — used sparingly */
        --gold-600: #c49a3c;
        --gold-100: #faf0d7;

        /* Neutral text */
        --ink-900: #1a1a1a;
        --ink-600: #4a4a4a;
        --ink-400: #767676;
        --ink-100: #f0f0f0;

        /* Status — muted tones, not traffic lights */
        --status-critical-bg: #fdf2f2;
        --status-critical-fg: #8b1a1a;
        --status-critical-bd: #e8c4c4;
        --status-high-bg:     #fdf6ee;
        --status-high-fg:     #7a4a10;
        --status-high-bd:     #e8d0b0;
        --status-medium-bg:   #fdfaee;
        --status-medium-fg:   #6b5a10;
        --status-medium-bd:   #e8e0b0;
        --status-low-bg:      #f5f5f5;
        --status-low-fg:      #555555;
        --status-low-bd:      #d0d0d0;
    }

    html, body, [class*="css"] {
        font-family: var(--font-sans);
        color: var(--ink-900);
    }

    .stApp {
        background: #ffffff;
    }

    /* ── Typography ── */
    h1 {
        font-size: 1.75rem;
        font-weight: 600;
        color: var(--mauve-900);
        letter-spacing: -0.02em;
        margin-bottom: 0.25rem;
    }

    h2 {
        font-size: 1.25rem;
        font-weight: 600;
        color: var(--mauve-700);
        margin-top: 2rem;
        margin-bottom: 0.75rem;
    }

    h3 {
        font-size: 1.05rem;
        font-weight: 600;
        color: var(--ink-900);
        margin-top: 1.5rem;
        margin-bottom: 0.5rem;
    }

    p, li {
        font-size: 0.9375rem;
        line-height: 1.65;
        color: var(--ink-600);
    }

    /* ── Tabs ── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        border-bottom: 1px solid var(--mauve-200);
    }

    .stTabs [data-baseweb="tab"] {
        font-size: 0.875rem;
        font-weight: 500;
        color: var(--ink-400);
        padding: 0.625rem 1.25rem;
        border-bottom: 2px solid transparent;
        background: transparent;
    }

    .stTabs [aria-selected="true"] {
        color: var(--mauve-700);
        border-bottom-color: var(--mauve-700);
    }

    .stTabs [data-baseweb="tab-panel"] {
        padding: 1.5rem 0 0;
    }

    /* ── Inputs ── */
    .stTextArea textarea,
    .stTextInput input {
        font-family: var(--font-sans);
        font-size: 0.9375rem;
        border: 1px solid var(--mauve-200);
        border-radius: 4px;
        color: var(--ink-900);
    }

    .stTextArea textarea:focus,
    .stTextInput input:focus {
        border-color: var(--mauve-700);
        box-shadow: 0 0 0 2px rgba(94, 76, 95, 0.15);
    }

    .stSelectbox > div > div {
        border: 1px solid var(--mauve-200);
        border-radius: 4px;
    }

    /* ── Primary button ── */
    .stButton > button[kind="primary"],
    .stButton > button {
        background: var(--mauve-700);
        color: #ffffff;
        border: none;
        border-radius: 4px;
        font-size: 0.9375rem;
        font-weight: 500;
        padding: 0.625rem 1.5rem;
        letter-spacing: 0.01em;
        transition: background 0.15s;
    }

    .stButton > button:hover {
        background: var(--mauve-900);
    }

    /* ── Info / notice box ── */
    .notice-box {
        background: var(--mauve-50);
        border: 1px solid var(--mauve-200);
        border-radius: 4px;
        padding: 1rem 1.25rem;
        margin-bottom: 1.5rem;
    }

    .notice-box p {
        margin: 0;
        font-size: 0.875rem;
        color: var(--ink-600);
    }

    .notice-box strong {
        color: var(--mauve-700);
    }

    /* ── Divider ── */
    hr {
        border: none;
        border-top: 1px solid var(--ink-100);
        margin: 1.75rem 0;
    }

    /* ── Severity labels ── */
    .severity-label {
        display: inline-block;
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        padding: 0.2rem 0.6rem;
        border-radius: 3px;
        margin-right: 0.5rem;
    }

    .severity-critical {
        background: var(--status-critical-bg);
        color:      var(--status-critical-fg);
        border: 1px solid var(--status-critical-bd);
    }
    .severity-high {
        background: var(--status-high-bg);
        color:      var(--status-high-fg);
        border: 1px solid var(--status-high-bd);
    }
    .severity-medium {
        background: var(--status-medium-bg);
        color:      var(--status-medium-fg);
        border: 1px solid var(--status-medium-bd);
    }
    .severity-low {
        background: var(--status-low-bg);
        color:      var(--status-low-fg);
        border: 1px solid var(--status-low-bd);
    }

    .confidence-label {
        display: inline-block;
        font-size: 0.75rem;
        color: var(--ink-400);
        letter-spacing: 0.02em;
    }

    /* ── Excerpt block ── */
    .excerpt-block {
        background: var(--mauve-50);
        border-left: 3px solid var(--mauve-200);
        border-radius: 0 4px 4px 0;
        padding: 1rem 1.25rem;
        font-size: 0.9rem;
        line-height: 1.7;
        color: var(--ink-600);
        margin: 0.75rem 0;
    }

    .excerpt-block mark {
        background: var(--gold-100);
        color: var(--mauve-900);
        padding: 0 0.125rem;
        border-radius: 2px;
    }

    /* ── Analysis text ── */
    .analysis-text {
        font-size: 0.9375rem;
        line-height: 1.7;
        color: var(--ink-600);
        margin: 0.75rem 0 1.25rem;
    }

    /* ── Action list ── */
    .action-list {
        border-top: 1px solid var(--ink-100);
        padding-top: 1rem;
        margin-top: 1rem;
    }

    .action-list-title {
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--mauve-700);
        margin-bottom: 0.75rem;
    }

    .action-item {
        display: flex;
        gap: 0.75rem;
        margin-bottom: 0.625rem;
        font-size: 0.9rem;
        color: var(--ink-600);
        line-height: 1.5;
    }

    .action-item::before {
        content: "\2014";   /* em-dash */
        color: var(--mauve-500);
        flex-shrink: 0;
    }

    /* ── Pagination ── */
    .pagination-label {
        text-align: center;
        font-size: 0.875rem;
        color: var(--ink-400);
        padding-top: 0.5rem;
    }

    /* ── Summary metrics ── */
    [data-testid="metric-container"] {
        background: var(--mauve-50);
        border: 1px solid var(--mauve-200);
        border-radius: 4px;
        padding: 0.75rem 1rem;
    }

    [data-testid="metric-container"] label {
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--mauve-700);
    }

    [data-testid="metric-container"] [data-testid="metric-value"] {
        font-size: 1.75rem;
        font-weight: 300;
        color: var(--ink-900);
    }

    /* ── Footer ── */
    .app-footer {
        margin-top: 3rem;
        padding-top: 1.5rem;
        border-top: 1px solid var(--ink-100);
        font-size: 0.8125rem;
        color: var(--ink-400);
        line-height: 1.6;
    }

    .app-footer strong {
        color: var(--ink-600);
    }
</style>
""", unsafe_allow_html=True)

API_BASE = "http://localhost:8000"

# Session state
for key, default in {
    "findings": [],
    "current_page": 0,
    "analysis_complete": False,
    "source_text": "",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ── Helpers ──────────────────────────────────────────────────────────────────

def highlight_excerpt(paragraph: str, excerpt: str) -> str:
    if not excerpt or excerpt not in paragraph:
        return paragraph
    return paragraph.replace(excerpt, f"<mark>{excerpt}</mark>")


def action_suggestions(finding: Dict) -> List[str]:
    category = finding.get("category", "").lower()
    severity = finding.get("severity", "").lower()
    actions: List[str] = []

    if severity in ("critical", "high"):
        actions.append(
            "Contact the organization in writing to request clarification on this clause "
            "before accepting the agreement."
        )
        actions.append(
            "Review the organization's compliance history and any regulatory enforcement "
            "actions using the FTC's public action database."
        )

    if "data sale" in category or "third party" in category:
        actions.append(
            "Submit an opt-out request under applicable law (CCPA § 1798.120, GDPR Art. 21) "
            "via the organization's designated privacy contact."
        )
        actions.append(
            "File a complaint with your state Attorney General or, for EU residents, "
            "the relevant supervisory authority under GDPR Art. 77."
        )

    if "consent" in category or "agreement" in category:
        actions.append(
            "Request a plain-language summary of all consent obligations in writing "
            "before providing agreement."
        )

    if "retention" in category or "deletion" in category:
        actions.append(
            "Submit a data deletion request citing GDPR Article 17 or CCPA § 1798.105, "
            "specifying account and associated identifiers."
        )
        actions.append(
            "Export your data using portability rights (GDPR Art. 20) before requesting deletion."
        )

    if "children" in category or "minor" in category:
        actions.append(
            "Report suspected COPPA violations to the FTC at ftc.gov/complaint, "
            "referencing the specific data collection practice."
        )

    if "health" in category or "hipaa" in category:
        actions.append(
            "File a HIPAA complaint with the HHS Office for Civil Rights at hhs.gov/ocr "
            "if protected health information is being handled improperly."
        )

    if "arbitration" in category or "class action" in category:
        actions.append(
            "Review the opt-out provision and timeline — typically 30 days from acceptance. "
            "Send opt-out notice via certified mail to preserve your right to civil litigation."
        )
        actions.append(
            "Consult a consumer rights attorney before agreeing to binding arbitration "
            "in high-value or employment contexts."
        )

    if not actions:
        actions.append(
            "Request written clarification of this clause directly from the organization's "
            "legal or compliance department."
        )
        actions.append(
            "Compare this provision against alternatives with more transparent terms "
            "before proceeding."
        )

    return actions


def display_finding(finding: Dict, index: int, total: int) -> None:
    severity = finding.get("severity", "Low")
    category = finding.get("category", "Finding")
    confidence = finding.get("confidence", 0) * 100

    # Severity + confidence row
    badge_cls = f"severity-{severity.lower()}"
    st.markdown(
        f'<span class="severity-label {badge_cls}">{severity}</span>'
        f'<span class="confidence-label">{confidence:.0f}% confidence</span>',
        unsafe_allow_html=True,
    )

    st.markdown(f"### {category}")

    # Excerpt / paragraph
    paragraph = finding.get("full_paragraph", "")
    excerpt = finding.get("excerpt", "")

    if paragraph:
        highlighted = highlight_excerpt(paragraph, excerpt)
        label = "Context" if excerpt else "Relevant passage"
        st.markdown(f"**{label}**")
        st.markdown(
            f'<div class="excerpt-block">{highlighted}</div>',
            unsafe_allow_html=True,
        )
    elif excerpt:
        st.markdown("**Relevant passage**")
        st.markdown(
            f'<div class="excerpt-block">"{excerpt}"</div>',
            unsafe_allow_html=True,
        )

    # Analysis
    explanation = finding.get("explanation", "No explanation available.")

    # Expand underspecified explanations
    if len(explanation) < 100 or ("may" in explanation and "could" in explanation):
        cat_l = category.lower()
        if "third party" in cat_l or "sharing" in cat_l:
            explanation = (
                "This clause authorises disclosure of personally identifiable information to "
                "third parties. Recipients are not necessarily bound by equivalent privacy "
                "obligations and may further distribute or monetise the data."
            )
        elif "retention" in cat_l:
            explanation = (
                "The policy does not specify a deletion timeline, leaving personal data "
                "in the organization's systems indefinitely — including after account "
                "termination. No automated data lifecycle management is indicated."
            )
        elif "arbitration" in cat_l:
            explanation = (
                "This clause requires disputes to be resolved through binding arbitration "
                "and waives the right to class-action litigation. It materially limits "
                "available legal remedies and consolidates risk to the individual claimant."
            )

    st.markdown("**Analysis**")
    st.markdown(
        f'<div class="analysis-text">{explanation}</div>',
        unsafe_allow_html=True,
    )

    # Action list
    actions = action_suggestions(finding)
    action_html = "\n".join(
        f'<div class="action-item">{a}</div>' for a in actions
    )
    st.markdown(
        f"""
        <div class="action-list">
            <div class="action-list-title">Recommended actions</div>
            {action_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Pagination
    st.markdown("<hr>", unsafe_allow_html=True)
    col_prev, col_label, col_next = st.columns([1, 2, 1])

    with col_prev:
        if index > 0 and st.button("Previous", key=f"prev_{index}"):
            st.session_state.current_page = index - 1
            st.rerun()

    with col_label:
        st.markdown(
            f'<div class="pagination-label">Finding {index + 1} of {total}</div>',
            unsafe_allow_html=True,
        )

    with col_next:
        if index < total - 1 and st.button("Next", key=f"next_{index}"):
            st.session_state.current_page = index + 1
            st.rerun()


def group_by_category(findings: List[Dict]) -> Dict[str, List[Dict]]:
    grouped: Dict[str, List[Dict]] = {}
    for f in findings:
        cat = f.get("category", "Other")
        grouped.setdefault(cat, []).append(f)
    return grouped


def analyze_document(
    text: str | None = None,
    url: str | None = None,
    file=None,
    mode: str = "quick",
    jurisdiction: str = "US-CA",
    industry: str = "General",
):
    try:
        if file is not None:
            response = requests.post(
                f"{API_BASE}/analyze/file",
                files={"file": file},
                data={"mode": mode, "jurisdictions": jurisdiction, "industry": industry},
            )
        elif url:
            response = requests.post(
                f"{API_BASE}/analyze/url",
                json={"url": url, "mode": mode, "jurisdictions": [jurisdiction], "industry": industry},
            )
        else:
            response = requests.post(
                f"{API_BASE}/analyze",
                json={
                    "text": text,
                    "doc_type": "privacy-policy",
                    "mode": mode,
                    "jurisdictions": [jurisdiction],
                    "industry": industry,
                },
            )

        if response.status_code == 200:
            result = response.json()
            # Enrich findings with surrounding paragraph when source text is available
            if text and "findings" in result:
                for f in result["findings"]:
                    excerpt = f.get("excerpt", "")
                    if excerpt and excerpt in text:
                        start = text.rfind("\n\n", 0, text.index(excerpt))
                        end = text.find("\n\n", text.index(excerpt))
                        f["full_paragraph"] = text[max(start, 0) : (end if end != -1 else len(text))].strip()
            return result

        st.error(f"The backend returned an error ({response.status_code}). Please verify your input and try again.")
        return None

    except requests.exceptions.ConnectionError:
        st.error("Unable to reach the analysis service. Ensure the backend is running on localhost:8000.")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
        return None


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    # Header
    st.markdown("<h1>Terms &amp; Policy Analyzer</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p style='color: var(--ink-400); margin-top: 0; margin-bottom: 1.5rem;'>"
        "Automated analysis of privacy policies and terms of service for compliance risk</p>",
        unsafe_allow_html=True,
    )

    # Process notice
    st.markdown(
        """
        <div class="notice-box">
        <p>Submit a document using one of the methods below. The analyzer will identify
        clauses that carry compliance risk, explain what each clause means in plain terms,
        and suggest specific actions you can take. Documents are processed locally and
        are not transmitted to any external service.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Input
    tab1, tab2, tab3 = st.tabs(["Paste text", "Website URL", "Upload file"])

    with tab1:
        text_input = st.text_area(
            "Document text",
            height=220,
            placeholder="Paste the full text of the policy or agreement here.",
            label_visibility="collapsed",
        )

    with tab2:
        url_input = st.text_input(
            "URL",
            placeholder="https://example.com/privacy-policy",
            label_visibility="collapsed",
        )

    with tab3:
        file_input = st.file_uploader(
            "Document file",
            type=["pdf", "txt", "doc", "docx"],
            label_visibility="collapsed",
        )

    st.markdown("<hr>", unsafe_allow_html=True)

    # Parameters
    st.markdown("**Analysis parameters**")
    col1, col2 = st.columns(2)

    with col1:
        jurisdiction = st.selectbox(
            "Jurisdiction",
            options=["US-CA", "GDPR", "US-NY", "US-VA", "US-FED", "UK-GDPR", "PIPEDA"],
            format_func=lambda x: {
                "US-CA":   "California — CCPA / CPRA",
                "GDPR":    "European Union — GDPR",
                "US-NY":   "New York — SHIELD Act",
                "US-VA":   "Virginia — VCDPA",
                "US-FED":  "United States — Federal",
                "UK-GDPR": "United Kingdom — UK GDPR",
                "PIPEDA":  "Canada — PIPEDA / Quebec Law 25",
            }[x],
        )

    with col2:
        industry = st.selectbox(
            "Industry",
            options=["General", "Healthcare", "Financial", "Education", "Children"],
            format_func=lambda x: {
                "General":     "General commercial",
                "Healthcare":  "Healthcare — HIPAA",
                "Financial":   "Financial services — GLBA",
                "Education":   "Education — FERPA",
                "Children":    "Children's services — COPPA",
            }[x],
        )

    mode = st.radio(
        "Depth",
        options=["quick", "full"],
        format_func=lambda x: (
            "Quick scan — high-severity findings only, approx. 2 min"
            if x == "quick"
            else "Comprehensive review — all findings, approx. 6 min"
        ),
        horizontal=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("Analyze document", type="primary", use_container_width=True):
        if not text_input and not url_input and not file_input:
            st.warning("Please provide a document via one of the three input methods above.")
        else:
            with st.spinner("Analyzing — this may take a few minutes."):
                result = analyze_document(
                    text=text_input or None,
                    url=url_input or None,
                    file=file_input or None,
                    mode=mode,
                    jurisdiction=jurisdiction,
                    industry=industry,
                )
                if result:
                    st.session_state.findings = result.get("findings", [])
                    st.session_state.analysis_complete = True
                    st.session_state.current_page = 0
                    st.session_state.source_text = text_input
                    st.rerun()

    # Results
    if st.session_state.analysis_complete:
        st.markdown("<hr>", unsafe_allow_html=True)

        findings = st.session_state.findings

        if not findings:
            st.markdown(
                "<p>Analysis complete. No significant concerns identified under the selected "
                "jurisdiction and industry parameters.</p>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown("## Findings")

            # Summary counts
            counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
            for f in findings:
                sev = f.get("severity", "Low")
                if sev in counts:
                    counts[sev] += 1

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Critical", counts["Critical"])
            c2.metric("High",     counts["High"])
            c3.metric("Medium",   counts["Medium"])
            c4.metric("Low",      counts["Low"])

            st.markdown("<hr>", unsafe_allow_html=True)

            # Category filter
            grouped = group_by_category(findings)
            if len(grouped) > 1:
                categories = ["All categories"] + list(grouped.keys())
                selected = st.selectbox("Filter by category", options=categories)
                current = findings if selected == "All categories" else grouped[selected]
            else:
                current = findings

            if current:
                page = min(st.session_state.current_page, len(current) - 1)
                display_finding(current[page], page, len(current))

    # Footer
    st.markdown(
        """
        <div class="app-footer">
        <strong>Legal disclaimer:</strong> This tool provides automated informational analysis only
        and does not constitute legal advice. Results should be reviewed by qualified legal counsel
        before making decisions affecting rights, obligations, or regulatory compliance. No
        attorney&#8202;&ndash;&#8202;client relationship is created through use of this service.
        <br><br>
        Terms &amp; Policy Analyzer &nbsp;&middot;&nbsp; Documents processed locally &nbsp;&middot;&nbsp; No data retained
        </div>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
