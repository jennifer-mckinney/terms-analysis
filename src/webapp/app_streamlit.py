"""
Terms & Policy Analyzer — corporate Streamlit frontend

Design patterns applied:
  1. config.toml base theming (primaryColor / font / backgrounds)
  2. st.container(border=True) for all card sections
  3. st.tabs styled as top navigation bar
  4. System font stack via CSS (no external CDN)
  5. st.dataframe with on_select row selection for findings
  6. st.popover for recommended actions
  7. Progress breadcrumb on Analyze page
  8. Consistent gap / spacing via st.container + st.divider
"""
from __future__ import annotations

import os
import re
import streamlit as st
import requests
import pandas as pd
from typing import List, Dict

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Terms & Policy Analyzer",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
# config.toml handles: primaryColor, backgroundColor, secondaryBackgroundColor,
# textColor, font.  Only add CSS that Streamlit theming cannot reach.

st.markdown("""
<style>
    /* System font stack — no external requests */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                     "Helvetica Neue", Arial, sans-serif !important;
    }

    /* Reduce default top padding */
    .block-container { padding-top: 1.25rem !important; }

    /* Hide Streamlit chrome */
    #MainMenu, footer { visibility: hidden; }

    /* ── App header ── */
    .app-header {
        display: flex;
        align-items: baseline;
        gap: 0.875rem;
        padding-bottom: 1rem;
        border-bottom: 1px solid #d8cfd9;
        margin-bottom: 0;
    }
    .app-title    { font-size: 1.125rem; font-weight: 600; color: #3d2e3e; }
    .app-subtitle { font-size: 0.875rem; color: #8a7a8b; }

    /* ── Top nav (styled st.tabs) ── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        background: transparent;
        border-bottom: 1px solid #d8cfd9;
        padding: 0;
        margin-bottom: 0;
    }
    .stTabs [data-baseweb="tab"] {
        background: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        border-radius: 0;
        padding: 0.875rem 1.375rem;
        font-size: 0.875rem;
        font-weight: 500;
        color: #8a7a8b;
    }
    .stTabs [aria-selected="true"] {
        background: transparent !important;
        border-bottom: 2px solid #5e4c5f !important;
        color: #3d2e3e !important;
    }

    /* ── Progress steps ── */
    .step-row {
        display: flex;
        margin-bottom: 1.75rem;
        border-bottom: 1px solid #eeebee;
    }
    .step {
        flex: 1;
        text-align: center;
        padding: 0.5rem;
        font-size: 0.8rem;
        font-weight: 500;
        color: #b0a4b1;
        border-bottom: 2px solid transparent;
    }
    .step.active { color: #5e4c5f; border-bottom-color: #5e4c5f; }
    .step.done   { color: #8a7a8b; border-bottom-color: #c4bac5; }

    /* ── Severity labels ── */
    .sev {
        display: inline-block;
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.07em;
        text-transform: uppercase;
        padding: 0.175rem 0.55rem;
        border-radius: 3px;
    }
    .sev-critical { background: #fdf2f2; color: #8b1a1a; border: 1px solid #e8c4c4; }
    .sev-high     { background: #fdf6ee; color: #7a4a10; border: 1px solid #e8d0b0; }
    .sev-medium   { background: #fdfaee; color: #6b5a10; border: 1px solid #e2daa8; }
    .sev-low      { background: #f5f5f5; color: #555;    border: 1px solid #d0d0d0; }

    /* ── Excerpt / passage block ── */
    .excerpt {
        background: #f5f2f5;
        border-left: 3px solid #c4bac5;
        border-radius: 0 4px 4px 0;
        padding: 0.875rem 1.125rem;
        font-size: 0.9rem;
        line-height: 1.75;
        color: #4a4a4a;
        margin: 0.5rem 0 1.25rem;
    }
    .excerpt mark {
        background: #faf0d7;
        color: #3d2e3e;
        padding: 0.05rem 0.15rem;
        border-radius: 2px;
    }

    /* ── Action items (inside popover) ── */
    .action-item {
        padding: 0.5rem 0 0.5rem 1.25rem;
        position: relative;
        font-size: 0.875rem;
        color: #4a4a4a;
        line-height: 1.55;
        border-bottom: 1px solid #f0eef0;
    }
    .action-item::before {
        content: "\2014";
        position: absolute;
        left: 0;
        color: #8a7a8b;
    }
    .action-item:last-child { border-bottom: none; }

    /* ── Metric cards tweak ── */
    [data-testid="metric-container"] {
        border-radius: 6px;
    }
    [data-testid="metric-container"] label {
        font-size: 0.7rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.07em !important;
        text-transform: uppercase !important;
        color: #8a7a8b !important;
    }
    [data-testid="metric-container"] [data-testid="metric-value"] {
        font-size: 2rem !important;
        font-weight: 300 !important;
        color: #3d2e3e !important;
    }

    /* ── Footer ── */
    .app-footer {
        margin-top: 3.5rem;
        padding-top: 1.25rem;
        border-top: 1px solid #eeebee;
        font-size: 0.8rem;
        color: #8a7a8b;
        line-height: 1.65;
    }
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────

API_BASE = os.environ.get("API_BASE_URL", "http://localhost:9000")

JURISDICTIONS = {
    "US-CA":   "California — CCPA / CPRA",
    "GDPR":    "European Union — GDPR",
    "US-NY":   "New York — SHIELD Act",
    "US-VA":   "Virginia — VCDPA",
    "US-CO":   "Colorado — CPA",
    "US-CT":   "Connecticut — CTDPA",
    "US-TX":   "Texas — TDPSA",
    "US-FED":  "United States — Federal",
    "UK-GDPR": "United Kingdom — UK GDPR",
    "PIPEDA":  "Canada — PIPEDA / Quebec Law 25",
    "EU-AI-ACT": "EU AI Act",
}

INDUSTRIES = {
    "General":            "General commercial",
    "Healthcare":         "Healthcare — HIPAA",
    "Finance":            "Finance — GLBA",
    "Education":          "Education — FERPA",
    "Social Media":       "Social Media",
    "AI / Tech Platform": "AI / Tech Platform",
    "Gaming":             "Gaming",
    "Retail":             "Retail",
}

# ── Session state ─────────────────────────────────────────────────────────────

for _k, _v in {
    "findings": [],
    "analysis_complete": False,
    "source_text": "",
    "selected_finding_idx": None,
    "last_result": {},
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Helpers ───────────────────────────────────────────────────────────────────

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
            "Review any regulatory enforcement history using the FTC's public action "
            "database at ftc.gov/legal-library/browse/cases-proceedings."
        )

    if "data sale" in category or "third party" in category or "sharing" in category:
        actions.append(
            "Submit an opt-out request under applicable law — CCPA § 1798.120 or "
            "GDPR Art. 21 — via the organization's designated privacy contact."
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
            "Submit a deletion request citing GDPR Art. 17 or CCPA § 1798.105, "
            "specifying account identifiers and associated data categories."
        )
        actions.append(
            "Export your data using portability rights (GDPR Art. 20) before "
            "initiating deletion."
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
            "Review the opt-out provision and timeline (typically 30 days). "
            "Send opt-out via certified mail to preserve your right to civil litigation."
        )
        actions.append(
            "Consult a consumer rights attorney before agreeing to binding arbitration."
        )

    if not actions:
        actions.append(
            "Request written clarification of this clause from the organization's "
            "legal or compliance department."
        )
        actions.append(
            "Compare this provision against alternatives with more transparent terms."
        )

    return actions


def build_findings_df(findings: List[Dict]) -> pd.DataFrame:
    rows = []
    for f in findings:
        rows.append({
            "Severity": f.get("severity", "Low"),
            "Category": f.get("category", "—"),
            "Confidence": f"{f.get('confidence', 0) * 100:.0f}%",
            "Excerpt": (f.get("excerpt", "") or "")[:90] + ("…" if len(f.get("excerpt", "") or "") > 90 else ""),
        })
    return pd.DataFrame(rows)


def severity_row_style(row: pd.Series) -> List[str]:
    palette = {
        "Critical": "background-color: #fdf2f2; color: #8b1a1a",
        "High":     "background-color: #fdf6ee; color: #7a4a10",
        "Medium":   "background-color: #fdfaee; color: #6b5a10",
        "Low":      "background-color: #f9f9f9; color: #555555",
    }
    base = palette.get(row.get("Severity", "Low"), "")
    return [base] * len(row)


def analyze_document(
    text: str | None = None,
    url: str | None = None,
    file=None,
    mode: str = "quick",
    jurisdiction: str = "US-CA",
    industry: str = "General",
) -> Dict | None:
    try:
        if file is not None:
            resp = requests.post(
                f"{API_BASE}/analyze/file",
                files={"file": file},
                data={"mode": mode, "jurisdictions": jurisdiction, "industry": industry},
                timeout=400,
            )
        elif url:
            resp = requests.post(
                f"{API_BASE}/analyze/url",
                json={"url": url, "mode": mode, "jurisdictions": [jurisdiction], "industry": industry},
                timeout=400,
            )
        else:
            resp = requests.post(
                f"{API_BASE}/analyze",
                json={
                    "text": text,
                    "mode": mode,
                    "jurisdictions": [jurisdiction],
                    "industry": industry,
                },
                timeout=400,
            )

        if resp.status_code == 200:
            result = resp.json()
            # Enrich findings with surrounding paragraph
            if text and "findings" in result:
                for f in result["findings"]:
                    excerpt = f.get("excerpt", "") or ""
                    if excerpt and excerpt in text:
                        start = max(text.rfind("\n\n", 0, text.index(excerpt)), 0)
                        end = text.find("\n\n", text.index(excerpt))
                        f["full_paragraph"] = text[start:(end if end != -1 else len(text))].strip()
            return result

        st.error(f"Backend error {resp.status_code}. Check your input and try again.")
        return None

    except requests.exceptions.ConnectionError:
        st.error(f"Unable to reach the analysis service at {API_BASE}. Start the backend first.")
        return None
    except Exception as exc:
        st.error(f"Unexpected error: {exc}")
        return None


# ── Rendering helpers ─────────────────────────────────────────────────────────

def render_finding_detail(finding: Dict) -> None:
    severity  = finding.get("severity", "Low")
    category  = finding.get("category", "Finding")
    confidence = finding.get("confidence", 0) * 100

    sev_cls = f"sev sev-{severity.lower()}"
    st.markdown(
        f'<span class="{sev_cls}">{severity}</span>'
        f'<span style="font-size:0.8rem;color:#8a7a8b;margin-left:0.625rem;">'
        f'{confidence:.0f}% confidence</span>',
        unsafe_allow_html=True,
    )
    st.markdown(f"**{category}**")

    paragraph = finding.get("full_paragraph", "")
    excerpt   = finding.get("excerpt", "") or ""

    if paragraph:
        st.markdown(
            f'<div class="excerpt">{highlight_excerpt(paragraph, excerpt)}</div>',
            unsafe_allow_html=True,
        )
    elif excerpt:
        st.markdown(
            f'<div class="excerpt">"{excerpt}"</div>',
            unsafe_allow_html=True,
        )

    explanation = finding.get("explanation", "") or ""
    if len(explanation) < 100:
        cat_l = category.lower()
        if "third party" in cat_l or "sharing" in cat_l:
            explanation = (
                "This clause authorises disclosure of personally identifiable information "
                "to third parties. Recipients are not necessarily bound by equivalent privacy "
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
                "available legal remedies."
            )

    st.markdown(f"<p style='font-size:0.9375rem;line-height:1.7;color:#4a4a4a;margin:0.5rem 0 1rem;'>{explanation}</p>",
                unsafe_allow_html=True)

    # Actions in a popover — keeps the card clean
    actions = action_suggestions(finding)
    action_html = "\n".join(f'<div class="action-item">{a}</div>' for a in actions)
    with st.popover("Recommended actions", use_container_width=True):
        st.markdown(action_html, unsafe_allow_html=True)


def render_severity_counts(findings: List[Dict]) -> None:
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


# ── Main app ──────────────────────────────────────────────────────────────────

def main() -> None:
    # App header
    st.markdown(
        '<div class="app-header">'
        '<span class="app-title">Terms &amp; Policy Analyzer</span>'
        '<span class="app-subtitle">Privacy &amp; compliance review</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    # Top navigation via styled tabs
    tab_analyze, tab_findings, tab_compare, tab_export = st.tabs(
        ["Analyze", "Findings", "Compare", "Export"]
    )

    # ── Analyze ──────────────────────────────────────────────────────────────
    with tab_analyze:
        findings_exist = bool(st.session_state.findings)
        step1 = "done" if findings_exist else "active"
        step2 = "done" if findings_exist else ""
        step3 = "done" if findings_exist else ""
        st.markdown(
            f'<div class="step-row">'
            f'<div class="step {step1}">1. Document</div>'
            f'<div class="step {step2}">2. Parameters</div>'
            f'<div class="step {step3}">3. Review findings</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Input card
        with st.container(border=True):
            st.markdown("**Document input**")
            sub1, sub2, sub3 = st.tabs(["Paste text", "Website URL", "Upload file"])

            with sub1:
                text_input = st.text_area(
                    "Text",
                    height=200,
                    placeholder="Paste the full text of the policy or agreement.",
                    label_visibility="collapsed",
                )
            with sub2:
                url_input = st.text_input(
                    "URL",
                    placeholder="https://example.com/privacy-policy",
                    label_visibility="collapsed",
                )
                st.caption("Enter a direct link to the policy page.")
            with sub3:
                file_input = st.file_uploader(
                    "File",
                    type=["pdf", "txt", "doc", "docx"],
                    label_visibility="collapsed",
                )
                st.caption("Supported: PDF, TXT, DOC, DOCX")

        st.write("")

        # Parameters card
        with st.container(border=True):
            st.markdown("**Parameters**")
            col_j, col_i = st.columns(2)

            with col_j:
                jurisdiction = st.selectbox(
                    "Jurisdiction",
                    options=list(JURISDICTIONS.keys()),
                    format_func=lambda x: JURISDICTIONS[x],
                )
            with col_i:
                industry = st.selectbox(
                    "Industry",
                    options=list(INDUSTRIES.keys()),
                    format_func=lambda x: INDUSTRIES[x],
                )

            mode = st.radio(
                "Analysis depth",
                options=["quick", "full"],
                format_func=lambda x: (
                    "Quick scan — critical issues only, approx. 2 min"
                    if x == "quick"
                    else "Comprehensive review — all findings, approx. 6 min"
                ),
                horizontal=True,
            )

        st.write("")

        if st.button("Analyze document", type="primary", use_container_width=True):
            if not any([
                text_input if "text_input" in dir() else None,
                url_input if "url_input" in dir() else None,
                file_input if "file_input" in dir() else None,
            ]):
                st.warning("Provide a document via one of the three input methods above.")
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
                        st.session_state.last_result = result
                        st.session_state.source_text = text_input or ""
                        st.session_state.selected_finding_idx = None
                        st.success(
                            f"Analysis complete — {len(st.session_state.findings)} "
                            f"finding(s) identified. Open the **Findings** tab to review."
                        )

    # ── Findings ─────────────────────────────────────────────────────────────
    with tab_findings:
        findings = st.session_state.findings

        if not findings:
            st.info("No findings yet. Run an analysis on the Analyze tab first.")
        else:
            # Summary metrics
            render_severity_counts(findings)
            st.divider()

            # Findings table
            df = build_findings_df(findings)
            styled = df.style.apply(severity_row_style, axis=1)

            st.markdown("**Select a row to review the full finding.**")
            event = st.dataframe(
                styled,
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                column_config={
                    "Severity":   st.column_config.TextColumn(width="small"),
                    "Category":   st.column_config.TextColumn(width="medium"),
                    "Confidence": st.column_config.TextColumn(width="small"),
                    "Excerpt":    st.column_config.TextColumn(width="large"),
                },
            )

            selected = event.selection.rows
            if selected:
                st.write("")
                with st.container(border=True):
                    render_finding_detail(findings[selected[0]])

    # ── Compare ───────────────────────────────────────────────────────────────
    with tab_compare:
        with st.container(border=True):
            st.markdown("**Vendor comparison**")
            st.markdown(
                "<p style='color:#8a7a8b;font-size:0.9rem;'>Side-by-side comparison of "
                "two or three vendor policies — risk scores, category deltas, and clause "
                "highlights — is available in the next release.</p>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "To compare manually, run separate analyses and note the risk scores "
                "returned in each result.",
            )

    # ── Export ────────────────────────────────────────────────────────────────
    with tab_export:
        with st.container(border=True):
            st.markdown("**Export findings**")

            if not st.session_state.findings:
                st.info("Run an analysis first to enable export.")
            else:
                result = st.session_state.get("last_result", {})
                doc_id = result.get("id", "")

                col_pdf, col_csv = st.columns(2)

                with col_pdf:
                    st.markdown("**PDF report**")
                    st.caption("Executive summary, severity table, and annotated findings.")
                    if doc_id:
                        try:
                            pdf_resp = requests.get(f"{API_BASE}/analyses/{doc_id}/export/pdf", timeout=30)
                            if pdf_resp.status_code == 200:
                                st.download_button(
                                    label="Download PDF",
                                    data=pdf_resp.content,
                                    file_name="policy_analysis.pdf",
                                    mime="application/pdf",
                                    use_container_width=True,
                                )
                            else:
                                st.warning("PDF export unavailable for this result.")
                        except Exception:
                            st.warning("PDF export service not reachable.")
                    else:
                        st.warning("Analysis ID not available for this session result.")

                with col_csv:
                    st.markdown("**CSV / JSON**")
                    st.caption("Machine-readable findings for import into other tools.")
                    df_export = build_findings_df(st.session_state.findings)
                    st.download_button(
                        label="Download CSV",
                        data=df_export.to_csv(index=False).encode(),
                        file_name="policy_findings.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

    # ── Footer ────────────────────────────────────────────────────────────────
    st.markdown(
        "<div class='app-footer'>"
        "<strong style='color:#5e4c5f;'>Legal disclaimer:</strong> "
        "This tool provides automated informational analysis only and does not constitute "
        "legal advice. Results should be reviewed by qualified legal counsel before making "
        "decisions affecting rights, obligations, or regulatory compliance. No "
        "attorney&#8202;&ndash;&#8202;client relationship is created through use of this service."
        "<br><br>"
        "Terms &amp; Policy Analyzer &nbsp;&middot;&nbsp; "
        "Documents processed locally &nbsp;&middot;&nbsp; No data retained"
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
