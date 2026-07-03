"""
Terms & Policy Reviewer — Streamlit v2

Issue #19 redesign: plain-language guided intake + verdict-first results.
Design source: docs/wireframes/issue-19-plain-language-design.html
Decisions: docs/wireframes/issue-19-design-decisions.md
Compliance: docs/wireframes/issue-19-brd-prd-compliance.md

Notes:
    * Two-view app: intake -> results, routed via st.session_state["view"].
    * Voice is warm/first-person on intake, observational/third-person on results
      (see decision #1). Tool voice avoids em-dashes (decision #3).
    * Backend contract expects a /infer endpoint plus context-aware /analyze* endpoints.
    * If /infer is unavailable the intake still renders; location is asked as a
      fallback so analysis can proceed without inference.
"""
from __future__ import annotations

import html
import os
from typing import Optional

import requests
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────

# Backend API base. run.sh exports API_BASE_URL; default to localhost:9000 to
# match the FastAPI backend port used elsewhere in the project.
API_BASE = os.environ.get("API_BASE_URL", "http://localhost:9000")

# Context chip choices — copy taken verbatim from the design mockup.
# Each entry: value (stable id), label (chip text), sub (italic help copy).
CONTEXT_CHIPS = [
    {
        "value": "want_understand",
        "label": "I want to understand what I am agreeing to",
        "sub": "Nice to know before you tap \"I agree.\" No judgment if you already did.",
    },
    {
        "value": "for_child",
        "label": "Something my child wants to use",
        "sub": "Games, apps, social platforms. We will help you see what matters.",
    },
    {
        "value": "for_care",
        "label": "Helping someone I care about with this",
        "sub": "A family member, extended family, and/or a friend.",
    },
    {
        "value": "for_work",
        "label": "For work or a vendor pick",
        "sub": "A tool the team might use, or an agreement to sign.",
    },
    {
        "value": "just_curious",
        "label": "Just curious",
        "sub": "Sometimes it is good to just know. No pressure either way.",
    },
]

# Location dropdowns for the fallback path (when /infer cannot pin jurisdiction).
COUNTRY_OPTIONS = [
    "United States",
    "European Union",
    "Canada",
    "United Kingdom",
    "Brazil",
    "India",
    "Australia",
    "Japan",
    "Other",
]
US_STATE_OPTIONS = [
    "California",
    "Texas",
    "New York",
    "Virginia",
    "Colorado",
    "Illinois",
    "Other state",
]

# ── Page config + CSS ─────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Policy Reviewer",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# CSS is a straight port of the mockup stylesheet with `pr-` prefixes so it can
# coexist with any legacy classes if the two apps ever share a container.
CSS = """
<style>
/* Palette + base */
:root {
    --ink: #1a1f2e; --ink-soft: #4a5568; --ink-muted: #718096;
    --border: #e2e8f0; --bg: #f8f9fb; --bg-card: #ffffff;
    --teal: #0d6e8a; --teal-soft: #e6f4f8;
    --amber: #b45309; --amber-bg: #fffbeb; --amber-bdr: #fcd34d;
    --green: #166534; --green-bg: #f0fdf4;
    --red: #991b1b; --red-bg: #fff5f5;
    --scope-bg: #f1f5f9;
}
html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif !important;
}
.block-container { padding-top: 1.5rem !important; max-width: 720px !important; }
#MainMenu, footer { visibility: hidden; }

/* Wordmark */
.pr-wordmark { font-size: 0.9rem; font-weight: 600; color: var(--teal); }
.pr-tagline { font-size: 0.82rem; color: var(--ink-muted); margin-left: 0.4rem; }

/* Intake headline */
.pr-intake-headline { font-size: 1.6rem; font-weight: 700; line-height: 1.25; color: var(--ink); margin-bottom: 0.4rem; letter-spacing: -0.02em; margin-top: 1.5rem; }
.pr-intake-sub { font-size: 0.95rem; color: var(--ink-soft); margin-bottom: 1.5rem; }

/* Option card (via st.container border=True + st.checkbox styled) */
.pr-card-label { font-size: 0.9rem; font-weight: 500; color: var(--ink); }
.pr-card-sub { font-size: 0.78rem; font-style: italic; color: var(--ink-muted); line-height: 1.45; margin-top: 0.15rem; }

/* Optional-section label */
.pr-opt-label { font-size: 0.8rem; font-weight: 600; letter-spacing: 0.03em; color: var(--ink-muted); text-transform: uppercase; margin: 1.5rem 0 0.75rem; }
.pr-opt-label .pr-opt-hint { font-weight: 400; font-size: 0.78rem; text-transform: none; letter-spacing: 0; color: var(--ink-muted); }

/* Verdict */
.pr-verdict { border-radius: 10px; padding: 1.375rem 1.5rem; margin-bottom: 1rem; border: 1.5px solid; }
.pr-verdict.caution { background: var(--amber-bg); border-color: var(--amber-bdr); }
.pr-verdict.go { background: var(--green-bg); border-color: #86efac; }
.pr-verdict.stop { background: #fff5f5; border-color: #feb2b2; }
.pr-verdict-top { display: flex; align-items: center; gap: 0.625rem; margin-bottom: 0.5rem; }
.pr-verdict-icon { font-size: 1.4rem; }
.pr-verdict-label { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: var(--amber); }
.pr-verdict.go .pr-verdict-label { color: var(--green); }
.pr-verdict.stop .pr-verdict-label { color: var(--red); }
.pr-verdict-headline { font-size: 1.1rem; font-weight: 700; line-height: 1.3; color: var(--ink); margin-bottom: 0.375rem; letter-spacing: -0.01em; }
.pr-verdict-sub { font-size: 0.88rem; color: var(--ink-soft); line-height: 1.55; }

/* Context chip */
.pr-context-chip { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0.75rem; background: var(--teal-soft); border: 1px solid #b8dae4; border-radius: 999px; margin-bottom: 1.25rem; font-size: 0.78rem; color: var(--ink-soft); }
.pr-context-chip strong { color: var(--teal); font-weight: 600; }

/* Scope box */
.pr-scope-box { background: var(--scope-bg); border-radius: 8px; padding: 1rem 1.25rem; margin: 0.75rem 0 1.25rem; font-size: 0.84rem; color: var(--ink-soft); line-height: 1.6; }
.pr-scope-box strong { color: var(--ink); font-weight: 600; }

/* Top-things (domain-grouped) */
.pr-top-thing { display: flex; gap: 0.875rem; background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 0.875rem 1rem; font-size: 0.9rem; color: var(--ink); line-height: 1.5; margin-bottom: 0.625rem; }
.pr-thing-num { flex-shrink: 0; width: 24px; height: 24px; background: var(--teal-soft); color: var(--teal); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 0.75rem; font-weight: 700; }
.pr-domain-head { margin: 1.25rem 0 0.5rem; font-size: 0.85rem; }
.pr-domain-name { font-weight: 700; color: var(--ink); letter-spacing: -0.01em; }
.pr-domain-desc { color: var(--ink-muted); font-weight: 400; font-style: italic; margin-left: 0.4rem; font-size: 0.8rem; }
.pr-domain-empty { font-size: 0.82rem; font-style: italic; color: var(--ink-muted); padding: 0.5rem 0 0.5rem 2.5rem; }

/* Legal detail item */
.pr-finding { padding: 0.875rem 1.125rem; border-bottom: 1px solid var(--border); font-size: 0.84rem; }
.pr-finding-meta { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.3rem; flex-wrap: wrap; }
.pr-sev-tag { font-size: 0.67rem; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; padding: 0.15rem 0.5rem; border-radius: 3px; }
.pr-sev-high { background: #fef3c7; color: #92400e; }
.pr-sev-medium { background: #fffbeb; color: #78350f; }
.pr-sev-critical { background: #fee2e2; color: #7f1d1d; }
.pr-sev-low { background: #f3f4f6; color: #4b5563; }
.pr-finding-cat { font-weight: 600; color: var(--ink); font-size: 0.84rem; }
.pr-irp-badge { margin-left: auto; font-size: 0.7rem; color: var(--ink-muted); background: var(--scope-bg); padding: 0.1rem 0.45rem; border-radius: 4px; }
.pr-finding-excerpt { background: var(--scope-bg); border-left: 3px solid #cbd5e0; padding: 0.5rem 0.75rem; font-size: 0.8rem; color: var(--ink-soft); margin: 0.4rem 0; line-height: 1.55; font-style: italic; }
.pr-finding-plain { font-size: 0.82rem; color: var(--ink-soft); line-height: 1.55; margin-top: 0.3rem; }
.pr-finding-basis { margin-top: 0.3rem; font-size: 0.75rem; color: var(--teal); }
.pr-irp-row { display: flex; gap: 1rem; margin-top: 0.35rem; font-size: 0.72rem; color: var(--ink-muted); }

/* Action list */
.pr-action-head { font-size: 0.78rem; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; color: var(--ink-muted); margin: 1.5rem 0 0.75rem; }
.pr-action-item { padding: 0.5rem 0; font-size: 0.86rem; color: var(--ink-soft); line-height: 1.55; }
.pr-action-item::before { content: "→ "; color: var(--teal); font-weight: 600; }

/* Primary CTA button styling */
div.stButton > button[kind="primary"] {
    background: var(--teal); color: white; border: none; border-radius: 10px;
    font-weight: 600; font-size: 1rem; padding: 0.875rem 1.5rem; width: 100%;
    letter-spacing: -0.01em;
}
div.stButton > button[kind="primary"]:hover { background: #0a5870; color: white; }

/* Privacy note */
.pr-privacy-note { text-align: center; font-size: 0.75rem; color: var(--ink-muted); margin-top: 0.75rem; }

/* Crumb */
.pr-crumb { font-size: 0.78rem; color: var(--ink-muted); margin-bottom: 1rem; }
.pr-crumb a { color: var(--teal); text-decoration: none; }

/* Disclaimer */
.pr-disclaimer { font-size: 0.73rem; color: var(--ink-muted); line-height: 1.6; border-top: 1px solid var(--border); padding-top: 1rem; margin-top: 2rem; }
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────


def init_state() -> None:
    """Populate default session state keys on first render.

    Streamlit re-runs the whole script on every interaction, so we guard each
    key with an existence check to preserve user input across reruns.
    """
    defaults = {
        "view": "intake",
        "input_mode": "link",
        "url_input": "",
        "text_input": "",
        "file_input": None,
        "context_selections": [],
        "inferred_juris": None,
        "inferred_doc_type": None,
        "inferred_industry": None,
        "location_needed": False,
        # Location defaults are intentionally blank. This is a global tool and we
        # must never infer/assume the reader's jurisdiction — session-state itself
        # is the "cache" for a returning user in the same session; a fresh session
        # leaves the selects empty until the reader chooses.
        "location_country": None,
        "location_state": None,
        "analysis_result": None,
        "analysis_error": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()

# ── API helpers ───────────────────────────────────────────────────────────────


def call_infer(url: Optional[str], text: Optional[str], context: list[str]) -> Optional[dict]:
    """Ask the backend to guess jurisdiction/doc_type/industry from the input.

    Returns the parsed JSON on success, or None if the backend is unavailable
    or returns a non-200. Callers must treat None as "keep asking the user."
    """
    try:
        resp = requests.post(
            f"{API_BASE}/infer",
            json={"url": url, "text": text, "context": context},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        # Backend not up / network error — the intake still functions without inference.
        return None


def call_analyze(
    url: Optional[str],
    text: Optional[str],
    file,
    context: list[str],
    jurisdictions: list[str],
    doc_type: Optional[str],
    industry: Optional[str],
) -> Optional[dict]:
    """Dispatch to /analyze, /analyze/url, or /analyze/file based on input.

    All three endpoints accept a `context` list. Errors are surfaced to the
    user via st.error so they know why nothing happened.
    """
    try:
        payload_common = {
            "context": context,
            # Empty list is intentional: this is a global tool. When the reader
            # hasn't chosen a location (or chose "Other"), we send [] and let the
            # backend skip jurisdiction filtering. Never fall back to US-CA + GDPR.
            "jurisdictions": jurisdictions,
            "doc_type": doc_type,
            "industry": industry,
            "mode": "full",
        }
        if url:
            resp = requests.post(
                f"{API_BASE}/analyze/url",
                json={**payload_common, "url": url},
                timeout=400,
            )
        elif file:
            resp = requests.post(
                f"{API_BASE}/analyze/file",
                files={"file": file},
                data={
                    "mode": "full",
                    "jurisdictions": ",".join(jurisdictions),
                    "industry": industry or "General",
                    "context": ",".join(context),
                },
                timeout=400,
            )
        else:
            resp = requests.post(
                f"{API_BASE}/analyze",
                json={**payload_common, "text": text},
                timeout=400,
            )
        if resp.status_code == 200:
            return resp.json()
        st.error(f"Analysis service returned {resp.status_code}. Try again in a moment.")
        return None
    except requests.exceptions.ConnectionError:
        st.error(
            f"The analysis service is not reachable at {API_BASE}. Start the backend and try again."
        )
        return None
    except Exception as exc:
        st.error(f"Unexpected error: {exc}")
        return None


def _location_to_jurisdictions(country: Optional[str], state: Optional[str]) -> list[str]:
    """Map the reader's location selection to jurisdiction codes.

    Returns [] (empty) when the reader hasn't chosen or chose "Other" — the
    backend interprets empty as "no filter" (this is a global tool with an
    unknown reader). NEVER falls back to US-CA + GDPR; that would silently
    mis-scope findings for the ~90% of world users who aren't in California.
    """
    if not country or country == "Other":
        return []
    if country == "United States":
        if not state or state == "Other state":
            return ["US-FED"]
        mapping = {
            "California": "US-CA",
            "Texas": "US-TX",
            "New York": "US-NY",
            "Virginia": "US-VA",
            "Colorado": "US-CO",
            "Illinois": "US-IL",
        }
        primary = mapping.get(state)
        return [primary, "US-FED"] if primary else ["US-FED"]
    country_map = {
        "European Union": ["GDPR"],
        "Canada": ["PIPEDA"],
        "United Kingdom": ["UK-GDPR"],
        "Brazil": ["LGPD"],
        "India": ["DPDP"],
        "Australia": ["APP"],
        "Japan": ["APPI"],
    }
    return country_map.get(country, [])  # unknown country -> no filter


# ── Intake view ───────────────────────────────────────────────────────────────


def render_intake() -> None:
    """Render the plain-language intake screen (mockup view #1)."""
    # Wordmark + tagline row.
    st.markdown(
        "<span class='pr-wordmark'>Policy Reviewer</span>"
        "<span class='pr-tagline'>Plain-language privacy &amp; terms analysis</span>",
        unsafe_allow_html=True,
    )
    # Warm, first-person headline. Double-quoted to allow the apostrophe.
    st.markdown(
        "<h1 class='pr-intake-headline'>What's on<br>your mind?</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p class='pr-intake-sub'>Privacy policies are confusing on purpose. "
        "We're here to help make sense of one.</p>",
        unsafe_allow_html=True,
    )

    # Input mode tabs — Streamlit tabs are the closest native equivalent to the
    # mockup's segmented input control.
    tab_link, tab_text, tab_file = st.tabs(["Paste link", "Paste text", "Upload file"])
    with tab_link:
        st.session_state.url_input = st.text_input(
            "URL",
            value=st.session_state.url_input,
            placeholder="Paste a privacy policy or terms of service link",
            label_visibility="collapsed",
        )
        st.caption("Any URL that leads to a privacy policy or terms of service page works here.")
        if st.session_state.url_input:
            st.session_state.input_mode = "link"
    with tab_text:
        st.session_state.text_input = st.text_area(
            "Text",
            value=st.session_state.text_input,
            height=140,
            placeholder="Paste the policy text here.",
            label_visibility="collapsed",
            max_chars=50000,
        )
        st.caption("Up to 50,000 characters. Text stays on this machine.")
        if st.session_state.text_input:
            st.session_state.input_mode = "text"
    with tab_file:
        uploaded = st.file_uploader(
            "File",
            type=["pdf", "docx", "rtf", "html", "txt"],
            label_visibility="collapsed",
        )
        if uploaded is not None:
            st.session_state.file_input = uploaded
            st.session_state.input_mode = "file"
        st.caption("PDF, DOCX, RTF, HTML, or TXT. Up to 10MB. Text is extracted locally.")

    # Optional context cards. Design uses selectable cards; Streamlit doesn't
    # have those natively so we use a bordered container + checkbox + styled sub.
    st.markdown(
        "<div class='pr-opt-label'>A little context "
        "<span class='pr-opt-hint'>(optional, choose any that fit)</span></div>",
        unsafe_allow_html=True,
    )

    selections: list[str] = []
    for chip in CONTEXT_CHIPS:
        with st.container(border=True):
            checked = st.checkbox(
                chip["label"],
                key=f"ctx_{chip['value']}",
                value=chip["value"] in st.session_state.context_selections,
            )
            st.markdown(
                f"<div class='pr-card-sub'>{html.escape(chip['sub'])}</div>",
                unsafe_allow_html=True,
            )
            if checked:
                selections.append(chip["value"])
    st.session_state.context_selections = selections

    # Inference is about the POLICY jurisdictions we detected in the text/URL —
    # NOT about where the reader is. We surface these signals in results (so the
    # reader can see what the policy talks about) but never use them to pre-fill
    # or override the reader's location choice. The reader's location is a
    # separate, explicit decision that must always come from the reader.
    if st.session_state.url_input or st.session_state.text_input:
        inferred = call_infer(
            st.session_state.url_input or None,
            st.session_state.text_input or None,
            selections,
        )
        if inferred:
            st.session_state.inferred_juris = inferred.get("jurisdictions")
            st.session_state.inferred_doc_type = inferred.get("doc_type")
            st.session_state.inferred_industry = inferred.get("industry")
            st.session_state.location_needed = bool(inferred.get("location_needed"))

    # Always show the location question when the user has provided any input.
    # Both country and region selects start blank — the session itself is the
    # "cache" for a returning user, and a fresh session leaves them empty until
    # the reader chooses. Never infer/prefill from the source document.
    if st.session_state.url_input or st.session_state.text_input or st.session_state.file_input:
        with st.container(border=True):
            st.markdown(
                "<div style='font-size:0.9rem;font-weight:500;'>Where are you located?</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div style='font-size:0.78rem;font-style:italic;color:var(--ink-muted);"
                "margin-bottom:0.75rem;'>Different regions offer different protections. "
                "Pick your location to focus the analysis on the right region.</div>",
                unsafe_allow_html=True,
            )
            col1, col2 = st.columns(2)
            with col1:
                # index=None + placeholder requires Streamlit >= 1.27. This lets
                # the select render truly blank on first paint instead of forcing
                # a "United States" default.
                current_country = st.session_state.location_country
                country_idx = (
                    COUNTRY_OPTIONS.index(current_country)
                    if current_country in COUNTRY_OPTIONS
                    else None
                )
                selected_country = st.selectbox(
                    "Country",
                    COUNTRY_OPTIONS,
                    index=country_idx,
                    placeholder="Select country",
                    label_visibility="collapsed",
                )
                # When the country changes, reset the region so we never carry a
                # stale California/Texas/etc. selection into a non-US country.
                if selected_country != st.session_state.location_country:
                    st.session_state.location_country = selected_country
                    st.session_state.location_state = None
            with col2:
                # Region select only renders for the United States. Same blank
                # default via index=None + placeholder.
                if st.session_state.location_country == "United States":
                    current_state = st.session_state.location_state
                    state_idx = (
                        US_STATE_OPTIONS.index(current_state)
                        if current_state in US_STATE_OPTIONS
                        else None
                    )
                    st.session_state.location_state = st.selectbox(
                        "Region",
                        US_STATE_OPTIONS,
                        index=state_idx,
                        placeholder="Select state",
                        label_visibility="collapsed",
                    )

    st.markdown("<div style='margin-top:1.5rem;'></div>", unsafe_allow_html=True)
    if st.button("Take a look →", type="primary", use_container_width=True):
        run_analysis()

    st.markdown(
        "<p class='pr-privacy-note'>Processed locally. Policy text is not stored. "
        "No account required.</p>",
        unsafe_allow_html=True,
    )


def run_analysis() -> None:
    """Dispatch analysis and, on success, switch to the results view."""
    url = st.session_state.url_input or None
    text = st.session_state.text_input or None
    file = st.session_state.file_input
    if not (url or text or file):
        st.warning("Paste a link, paste some text, or upload a file first.")
        return

    # The user's location choice is the source of truth for which jurisdictions
    # to filter findings by. Inference (from URL TLD / policy text signals) tells
    # us what the POLICY talks about, not where the READER lives — never let it
    # override the explicit selection or force a US-CA/GDPR default.
    jurisdictions = _location_to_jurisdictions(
        st.session_state.location_country,
        st.session_state.location_state,
    )
    # No location chosen (or "Other" chosen) -> proceed with no filter, but let
    # the reader know results won't be scoped to a specific region.
    if not jurisdictions:
        st.info(
            "Analyzing without a regional filter. Findings may include rules "
            "that don't apply to every jurisdiction. Pick a country in the "
            "location card above to focus the analysis on a specific region."
        )

    with st.spinner("Reading through the policy. This can take a minute."):
        result = call_analyze(
            url=url,
            text=text,
            file=file,
            context=st.session_state.context_selections,
            jurisdictions=jurisdictions,
            doc_type=st.session_state.inferred_doc_type,
            industry=st.session_state.inferred_industry,
        )
    if result:
        st.session_state.analysis_result = result
        st.session_state.view = "results"
        st.rerun()


# ── Results view ──────────────────────────────────────────────────────────────


def _friendly_jurisdiction_labels(codes: list[str]) -> list[str]:
    """Convert jurisdiction codes to plain-language labels for display.

    Deduplicates in order — the returned list is safe to render directly. Any
    code not in the map falls through as-is so the user sees the raw code rather
    than nothing.
    """
    friendly = {
        "US-FED": "US federal",
        "US-CA": "California",
        "US-TX": "Texas",
        "US-NY": "New York",
        "US-VA": "Virginia",
        "US-CO": "Colorado",
        "US-IL": "Illinois",
        "GDPR": "EU (GDPR)",
        "UK-GDPR": "UK (UK GDPR)",
        "PIPEDA": "Canada (PIPEDA)",
        "CA-QC": "Quebec (Law 25)",
        "LGPD": "Brazil (LGPD)",
        "APP": "Australia",
        "APPI": "Japan",
        "PIPA": "South Korea",
        "DPDP": "India",
        "POPIA": "South Africa",
        "EU-AI-ACT": "EU AI Act",
    }
    seen = set()
    result = []
    for c in codes:
        label = friendly.get(c, c)
        if label not in seen:
            seen.add(label)
            result.append(label)
    return result


def _selected_context_labels() -> list[str]:
    """Return chip labels for all selected contexts, ordered by priority.

    Priority order matches the design intent: parenting > caretaker > work >
    self > curiosity. The first label in the returned list is the primary
    (used for headline/verdict), the rest are secondaries.
    """
    if not st.session_state.context_selections:
        return []
    priority = ["for_child", "for_care", "for_work", "want_understand", "just_curious"]
    ordered = [p for p in priority if p in st.session_state.context_selections]
    result = []
    for p in ordered:
        for chip in CONTEXT_CHIPS:
            if chip["value"] == p:
                result.append(chip["label"])
                break
    return result


def render_results() -> None:
    """Render the verdict-first results screen (mockup view #2)."""
    result = st.session_state.analysis_result
    if not result:
        # Defensive: if a user somehow lands here with no result, bounce home.
        st.session_state.view = "intake"
        st.rerun()
        return

    # Wordmark row (same as intake for continuity).
    st.markdown(
        "<span class='pr-wordmark'>Policy Reviewer</span>"
        "<span class='pr-tagline'>Plain-language privacy &amp; terms analysis</span>",
        unsafe_allow_html=True,
    )

    # Crumb: what was reviewed + source link.
    source_name = result.get("name") or result.get("source_url") or "Pasted document"
    source_url = result.get("source_url")
    # Defense-in-depth against ``javascript:`` (and other non-web) schemes —
    # ``html.escape`` does NOT neutralise a scheme in an ``href`` attribute, so
    # the URL must be validated separately before it's rendered as a link. The
    # backend schema layer (AnalyzeRequest/AnalyzeUrlRequest) already rejects
    # non-http(s) source URLs; this is a belt-and-braces check in case a legacy
    # payload lacking that validation is rendered. See PR #34 security review
    # HIGH-1.
    safe_source_url: str | None = None
    if source_url:
        from urllib.parse import urlparse
        try:
            parsed = urlparse(str(source_url))
        except Exception:
            parsed = None
        if parsed and parsed.scheme in ("http", "https") and parsed.hostname:
            safe_source_url = str(source_url)
    crumb_bits = [f"Reviewed: <strong>{html.escape(str(source_name))}</strong>"]
    if safe_source_url:
        crumb_bits.append(
            f'<a href="{html.escape(safe_source_url)}" target="_blank" '
            f'rel="noopener">open source</a>'
        )
    st.markdown(
        f"<div class='pr-crumb'>{' &middot; '.join(crumb_bits)}</div>",
        unsafe_allow_html=True,
    )

    if st.button("<- Review another"):
        st.session_state.view = "intake"
        st.session_state.analysis_result = None
        st.rerun()

    # Context chip so the reader knows the results are tuned for their choice.
    # Multi-select: primary label bolded, secondaries listed; 3+ collapsed to "+ N more".
    ctx_labels = _selected_context_labels()
    if ctx_labels:
        if len(ctx_labels) == 1:
            chip_content = f'<strong>{html.escape(ctx_labels[0])}</strong>'
        elif len(ctx_labels) == 2:
            chip_content = f'<strong>{html.escape(ctx_labels[0])}</strong>, {html.escape(ctx_labels[1])}'
        else:
            others = len(ctx_labels) - 1
            chip_content = f'<strong>{html.escape(ctx_labels[0])}</strong> + {others} more'
        st.markdown(f'<div class="pr-context-chip">Tuned for: {chip_content}</div>', unsafe_allow_html=True)

    # Show which jurisdictions the analysis actually filtered by. This is derived from
    # the user's location choice (see run_analysis) and echoes back so the reader can
    # verify the correct region was targeted. Falls back to session inference for
    # backward compatibility with older result payloads that lacked the field.
    juris_used = result.get("jurisdictions") or st.session_state.get("inferred_juris") or []
    if juris_used:
        juris_labels = _friendly_jurisdiction_labels(juris_used)
        st.markdown(
            f'<div style="font-size:0.78rem;color:var(--ink-muted);margin-bottom:1rem;">'
            f'Rules applied for: <strong style="color:var(--ink-soft);">'
            f'{", ".join(juris_labels)}</strong></div>',
            unsafe_allow_html=True,
        )

    # Verdict block. Backend may supply verdict_headline / verdict_label; fall
    # back to a reasonable default derived from action_readiness.
    action = result.get("action_readiness", "Review")
    verdict_class = {"Go": "go", "Review": "caution", "Stop": "stop"}.get(action, "caution")
    verdict_icon = {"Go": "✓", "Review": "👀", "Stop": "⛔"}.get(action, "👀")
    verdict_label = result.get("verdict_label") or {
        "Go": "Reasonable",
        "Review": "Worth a closer read",
        "Stop": "Serious concerns",
    }.get(action, "Worth a closer read")
    verdict_headline = (
        result.get("verdict_headline")
        or "A few things here may be worth understanding before agreement."
    )
    verdict_sub = result.get("summary") or "Analysis complete."
    st.markdown(
        f"<div class='pr-verdict {verdict_class}'>"
        f"<div class='pr-verdict-top'>"
        f"<span class='pr-verdict-icon'>{html.escape(verdict_icon)}</span>"
        f"<span class='pr-verdict-label'>{html.escape(verdict_label)}</span></div>"
        f"<div class='pr-verdict-headline'>{html.escape(verdict_headline)}</div>"
        f"<div class='pr-verdict-sub'>{html.escape(verdict_sub)}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Score cards — grade and IRP shown as context, not headline (decision #6).
    findings = result.get("findings", []) or []
    total = len(findings)
    high = sum(1 for f in findings if f.get("severity") == "High")
    medium = sum(1 for f in findings if f.get("severity") == "Medium")
    low = sum(1 for f in findings if f.get("severity") == "Low")
    critical = sum(1 for f in findings if f.get("severity") == "Critical")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            "Risk level",
            f"{result.get('risk_score', 0):.1f} / 10",
            delta=f"Grade {result.get('grade', '')}",
            delta_color="off",
        )
    with col2:
        completeness = result.get("completeness", 0) or 0
        st.metric(
            "Policy coverage",
            f"{int(completeness * 8)} / 8",
            delta="sections found",
            delta_color="off",
        )
    with col3:
        st.metric(
            "Issues found",
            f"{total}",
            delta=f"{critical + high} high · {medium} medium · {low} low",
            delta_color="off",
        )

    # Scope box: what was and was not checked. Always visible per decision #7.
    st.markdown(
        '<div class="pr-scope-box">'
        '<strong>What was checked:</strong> The words in this policy. How it describes data collection, sharing, tracking, AI/automated decisions, and rights under applicable jurisdictions.'
        '<br><br>'
        '<strong>What wasn\'t checked:</strong>'
        '<ul style="margin: 0.5rem 0 0 1.25rem; padding: 0; list-style: disc;">'
        '<li>What permissions the app actually requests on a phone (camera, microphone, contacts, location). Those live in device Settings.</li>'
        '<li>Whether real-world practices match what this policy says. Only the document itself was analyzed.</li>'
        '</ul>'
        '</div>',
        unsafe_allow_html=True,
    )

    # Domain-grouped top findings (replaces flat top-things list)
    top_by_domain = result.get("top_by_domain") or {}
    DOMAIN_LABELS = [
        ("Data", "what's collected"),
        ("Data use", "how it's used"),
        ("Terms of use", "the agreement itself"),
        ("Privacy rights", "what can still be exercised"),
    ]
    for domain_key, domain_desc in DOMAIN_LABELS:
        st.markdown(
            f'<div class="pr-domain-head"><span class="pr-domain-name">{domain_key}</span>'
            f' <span class="pr-domain-desc">{domain_desc}</span></div>',
            unsafe_allow_html=True,
        )
        items = top_by_domain.get(domain_key) or []
        if not items:
            st.markdown(
                f'<div class="pr-domain-empty">Nothing notable surfaced under {domain_key}.</div>',
                unsafe_allow_html=True,
            )
            continue
        for i, f in enumerate(items, 1):
            plain = f.get("explanation") or "See legal details below."
            st.markdown(
                f'<div class="pr-top-thing"><div class="pr-thing-num">{i}</div><div>{html.escape(plain)}</div></div>',
                unsafe_allow_html=True,
            )

    # Legal details — collapsed by default (decision #7).
    with st.expander(f"Legal details / {total} issues"):
        for f in findings:
            sev = f.get("severity", "Low")
            sev_class = f"pr-sev-{sev.lower()}"
            cat = html.escape(str(f.get("category", "-")))
            irp = f.get("irp_score")
            irp_str = f"IRP {irp:.2f}" if isinstance(irp, (int, float)) else "-"
            conf_pct = int((f.get("confidence") or 0) * 100)
            excerpt = html.escape(str(f.get("excerpt", "")))
            explanation = html.escape(str(f.get("explanation", "")))
            evidence = f.get("evidence") or {}
            basis = " / ".join(
                html.escape(str(b)) for b in (evidence.get("legal_basis") or [])
            )
            impact = f.get("impact", 0) or 0
            likelihood = f.get("likelihood", 0) or 0
            safeguard = f.get("safeguard_score", 0) or 0
            lstart = evidence.get("line_start")
            lend = evidence.get("line_end")
            line_ref = f"Lines {lstart} to {lend}" if lstart and lend else ""
            line_html = (
                f"<div style='font-size:0.72rem;color:var(--ink-muted);"
                f"margin-top:0.3rem;'>{line_ref}</div>"
                if line_ref
                else ""
            )
            st.markdown(
                f"<div class='pr-finding'>"
                f"<div class='pr-finding-meta'>"
                f"<span class='pr-sev-tag {sev_class}'>{html.escape(sev)}</span>"
                f"<span class='pr-finding-cat'>{cat}</span>"
                f"<span class='pr-irp-badge'>{irp_str}</span></div>"
                f"<div class='pr-finding-excerpt'>&quot;{excerpt}&quot;</div>"
                f"<div class='pr-finding-plain'>{explanation}</div>"
                f"<div class='pr-finding-basis'>{basis}</div>"
                f"{line_html}"
                f"<div class='pr-irp-row'>"
                f"<span>Impact <strong>{impact}</strong>/5</span>"
                f"<span>Likelihood <strong>{likelihood}</strong>/5</span>"
                f"<span>Safeguards <strong>{safeguard}</strong>/5</span>"
                f"<span>Confidence <strong>{conf_pct}%</strong></span>"
                f"</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # Suggestions — tentative language per decision #2.
    # Sourced from the backend response (AnalysisPayload.action_items) so the SPA
    # fallback and API consumers get the same guidance and the derivation logic
    # lives in one place. Falls back to a generic pointer when the field is empty
    # or missing (older payloads / legacy backend).
    st.markdown(
        "<div class='pr-action-head'>Some things worth considering</div>",
        unsafe_allow_html=True,
    )
    action_lines = result.get("action_items") or []
    if action_lines:
        for line in action_lines:
            st.markdown(
                f'<div class="pr-action-item">{html.escape(str(line))}</div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            '<div class="pr-action-item">Review the specific opt-out and rights '
            'mechanisms named in the legal details above.</div>',
            unsafe_allow_html=True,
        )

    # Export bar. Buttons only appear if we can successfully pull the export.
    st.markdown("<div style='margin-top:1.5rem;'></div>", unsafe_allow_html=True)
    export_cols = st.columns(4)
    doc_id = result.get("id", "")
    with export_cols[0]:
        if doc_id:
            try:
                pdf_resp = requests.get(
                    f"{API_BASE}/exports/analysis/{doc_id}.pdf", timeout=30
                )
                if pdf_resp.status_code == 200:
                    st.download_button(
                        "Save PDF",
                        pdf_resp.content,
                        file_name="policy_review.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )
                else:
                    st.warning(
                        f"PDF export unavailable (server returned {pdf_resp.status_code})."
                    )
            except requests.RequestException as exc:
                # Surface the transport error to the reader rather than swallowing it
                # (which used to leave the export bar silently missing a button).
                st.warning(f"PDF export unavailable: {exc}")
    with export_cols[1]:
        if doc_id:
            try:
                json_resp = requests.get(
                    f"{API_BASE}/exports/analysis/{doc_id}.json", timeout=15
                )
                if json_resp.status_code == 200:
                    st.download_button(
                        "Download JSON",
                        json_resp.content,
                        file_name="policy_review.json",
                        mime="application/json",
                        use_container_width=True,
                    )
                else:
                    st.warning(
                        f"JSON export unavailable (server returned {json_resp.status_code})."
                    )
            except requests.RequestException as exc:
                st.warning(f"JSON export unavailable: {exc}")
    with export_cols[2]:
        if doc_id:
            try:
                csv_resp = requests.get(
                    f"{API_BASE}/exports/analyses.csv?ids={doc_id}&detailed=true",
                    timeout=15,
                )
                if csv_resp.status_code == 200:
                    st.download_button(
                        "Download CSV",
                        csv_resp.content,
                        file_name="policy_review.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )
                else:
                    st.warning(
                        f"CSV export unavailable (server returned {csv_resp.status_code})."
                    )
            except requests.RequestException as exc:
                st.warning(f"CSV export unavailable: {exc}")
    with export_cols[3]:
        # Share summary: a lightweight text export of just the verdict.
        summary_text = (verdict_headline + "\n\n" + verdict_sub).encode()
        st.download_button(
            "Share summary",
            summary_text,
            file_name="policy_summary.txt",
            mime="text/plain",
            use_container_width=True,
        )

    st.markdown(
        "<div class='pr-disclaimer'>This analysis is automated and informational only. "
        "Not legal advice. Review by qualified legal counsel is recommended before making "
        "decisions that affect legal rights or obligations. Processed locally. No data retained."
        "</div>",
        unsafe_allow_html=True,
    )


# ── Router ────────────────────────────────────────────────────────────────────


def main() -> None:
    """Route between the two views based on session state."""
    if st.session_state.view == "results" and st.session_state.analysis_result:
        render_results()
    else:
        render_intake()


if __name__ == "__main__":
    main()
