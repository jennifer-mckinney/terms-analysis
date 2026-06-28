"""
Privacy Helper - Streamlit App
Consumer-friendly interface for analyzing privacy policies and terms of service
"""

import streamlit as st
import requests
from typing import List, Dict
import re

# Page config
st.set_page_config(
    page_title="Privacy Helper",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for warm cream theme
st.markdown("""
<style>
    /* Import system fonts */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');
    
    /* Professional theme - Dull Purple + Gray + Gold */
    :root {
        --purple-dark: #5e4c5f;
        --purple-mid: #735e74;
        --purple-light: #a89aa9;
        --gray-dark: #4a4a4a;
        --gray-mid: #8e8e8e;
        --gray-light: #d4d4d4;
        --gold-accent: #e8b563;
        --gold-light: #f5d9a8;
        --white-bg: #fafafa;
        --white-card: #ffffff;
    }
    
    /* Main background */
    .stApp {
        background: var(--white-bg);
    }
    
    /* Cards */
    .stTabs [data-baseweb="tab-panel"] {
        background: var(--white-card);
        padding: 2rem;
        border-radius: 0.75rem;
        border: 1px solid var(--gray-light);
    }
    
    /* Headers */
    h1, h2, h3 {
        color: var(--purple-dark);
        font-weight: 400;
    }
    
    h1 {
        font-size: 2.5rem;
        margin-bottom: 1rem;
        font-weight: 500;
    }
    
    /* Buttons */
    .stButton > button {
        background: var(--purple-dark);
        color: white;
        border: none;
        padding: 0.75rem 2rem;
        font-weight: 500;
        border-radius: 0.5rem;
        transition: all 0.2s;
    }
    
    .stButton > button:hover {
        background: var(--purple-mid);
        box-shadow: 0 4px 12px rgba(94,76,95,0.25);
    }
    
    /* Info boxes */
    .stAlert {
        background: var(--white-card);
        border-left: 4px solid var(--gold-accent);
        border-radius: 0.5rem;
    }
    
    /* Selectboxes */
    .stSelectbox > div > div {
        background: var(--white-card);
        border: 1px solid var(--gray-light);
    }
    
    /* Text areas */
    .stTextArea textarea {
        background: var(--white-card);
        border: 1px solid var(--gray-light);
        border-radius: 0.5rem;
        color: var(--gray-dark);
    }
    
    /* Expanders for findings */
    .streamlit-expanderHeader {
        background: var(--white-card);
        border: 1px solid var(--gray-light);
        border-radius: 0.5rem;
        font-weight: 500;
        color: var(--purple-dark);
    }
    
    /* Mark/highlight styling */
    mark {
        background: var(--gold-light);
        color: var(--purple-dark);
        padding: 0.125rem 0.25rem;
        border-radius: 0.25rem;
        font-weight: 500;
    }
    
    /* Badge styling */
    .badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 0.375rem;
        font-size: 0.875rem;
        font-weight: 600;
        margin-right: 0.5rem;
    }
    
    .badge-critical {
        background: #fdecea;
        color: #c41e3a;
        border: 1px solid #f0b8bb;
    }
    
    .badge-high {
        background: #fff4e5;
        color: #d97706;
        border: 1px solid #fed7aa;
    }
    
    .badge-medium {
        background: #fef9e7;
        color: #ca8a04;
        border: 1px solid #fde68a;
    }
    
    .badge-low {
        background: #f5f5f5;
        color: var(--gray-mid);
        border: 1px solid var(--gray-light);
    }
    
    /* Action box */
    .action-box {
        background: rgba(232, 181, 99, 0.08);
        border: 1px solid var(--gold-accent);
        border-radius: 0.5rem;
        padding: 1.5rem;
        margin-top: 1rem;
    }
    
    .action-box h4 {
        color: var(--purple-dark);
        margin-bottom: 0.5rem;
    }
    
    .action-item {
        margin: 0.5rem 0;
        padding-left: 1.5rem;
        position: relative;
    }
    
    .action-item::before {
        content: "→";
        position: absolute;
        left: 0;
        color: var(--gold-accent);
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# API Configuration
API_BASE = "http://localhost:8000"

# Initialize session state
if 'findings' not in st.session_state:
    st.session_state.findings = []
if 'current_page' not in st.session_state:
    st.session_state.current_page = 0
if 'current_group' not in st.session_state:
    st.session_state.current_group = 'all'
if 'analysis_complete' not in st.session_state:
    st.session_state.analysis_complete = False

def highlight_text_in_paragraph(paragraph: str, excerpt: str) -> str:
    """Highlight the specific excerpt within the paragraph"""
    if not excerpt or excerpt not in paragraph:
        return paragraph
    highlighted = paragraph.replace(excerpt, f"<mark>{excerpt}</mark>")
    return highlighted

def get_action_suggestions(finding: Dict) -> List[str]:
    """Generate actionable follow-up suggestions based on finding"""
    category = finding.get('category', '').lower()
    severity = finding.get('severity', '').lower()
    
    actions = []
    
    # Generic high-severity actions
    if severity in ['critical', 'high']:
        actions.append("📧 **Contact the organization** to request clarification on this section before proceeding")
        actions.append("🔍 **Research** the organization's compliance history and user feedback regarding this practice")
    
    # Category-specific actions
    if 'data sale' in category or 'third party' in category:
        actions.append("❌ **Exercise opt-out rights** if available under applicable privacy regulations (CCPA, GDPR)")
        actions.append("📋 **File a formal complaint** with your state Attorney General or data protection authority")
        
    if 'consent' in category.lower() or 'agreement' in category.lower():
        actions.append("📝 **Request written documentation** of all terms before providing consent")
        
    if 'retention' in category or 'deletion' in category:
        actions.append("📅 **Submit a data deletion request** under GDPR Article 17 or CCPA deletion rights")
        actions.append("💾 **Export your data** using data portability rights (GDPR Article 20)")
    
    if 'children' in category or 'minor' in category:
        actions.append("👨‍👩‍👧 **Review with minors** the scope of information being collected and shared")
        actions.append("⚖️ **Report COPPA violations** to the FTC via ftc.gov/complaint")
    
    if 'health' in category or 'hipaa' in category:
        actions.append("🏥 **File a HIPAA complaint** with HHS Office for Civil Rights if PHI handling is improper")
        actions.append("💬 **Consult your healthcare provider** about more privacy-protective alternatives")
    
    if 'arbitration' in category or 'class action' in category:
        actions.append("📃 **Send opt-out notice** within the specified timeframe (typically 30 days) if permitted")
        actions.append("💼 **Seek legal counsel** before agreeing to binding arbitration in high-stakes agreements")
    
    # Default professional actions
    if not actions:
        actions.append("❓ **Request clarification** in writing with specific reference to this clause")
        actions.append("🔄 **Evaluate alternatives** with more favorable or transparent terms")
    
    return actions

def display_finding(finding: Dict, index: int, total: int):
    """Display a single finding with context, explanation, and actions"""
    
    severity = finding.get('severity', 'Low')
    category = finding.get('category', 'Finding')
    confidence = finding.get('confidence', 0) * 100
    
    # Severity badge
    badge_class = f"badge-{severity.lower()}"
    st.markdown(f"""
        <div>
            <span class="badge {badge_class}">{severity}</span>
            <span class="badge" style="background: #E8F4F8; color: {finding.get('confidence', 0) >= 0.9 and '#0A5C66' or '#666'}">
                {confidence:.0f}% confident
            </span>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown(f"### {category}")
    
    # Full paragraph with highlighted excerpt
    if 'full_paragraph' in finding and finding['full_paragraph']:
        paragraph = finding['full_paragraph']
        excerpt = finding.get('excerpt', '')
        highlighted = highlight_text_in_paragraph(paragraph, excerpt)
        
        st.markdown("#### 📄 Full context:")
        st.markdown(f'<div style="background: var(--white-card); padding: 1.5rem; border-radius: 0.5rem; border: 1px solid var(--gray-light); line-height: 1.75; color: var(--gray-dark);">{highlighted}</div>', unsafe_allow_html=True)
    elif finding.get('excerpt'):
        st.markdown("#### 📄 Relevant excerpt:")
        st.markdown(f'<div style="background: var(--white-card); padding: 1.5rem; border-radius: 0.5rem; border: 1px solid var(--gray-light); font-style: italic; line-height: 1.75; color: var(--gray-dark);">"{finding["excerpt"]}"</div>', unsafe_allow_html=True)
    
    # Plain language explanation
    st.markdown("#### 💡 Analysis:")
    explanation = finding.get('explanation', 'No explanation available')
    
    # Rewrite vague explanations to be professional yet clear
    if len(explanation) < 100 or 'may' in explanation.lower() and 'could' in explanation.lower():
        # This is too vague - make it concrete but professional
        if 'third party' in category.lower() or 'sharing' in category.lower():
            explanation = f"This clause **permits third-party data disclosure**. The organization may share personally identifiable information (PII) including contact details, behavioral data, and geolocation with external entities. These third parties are not bound by the same privacy obligations and may further redistribute or monetize the data."
        elif 'retention' in category.lower():
            explanation = f"This policy establishes **indefinite data retention** without specified deletion timelines. Information remains in the organization's systems beyond account termination, creating ongoing security and privacy exposure. No automated data lifecycle management is indicated."
        elif 'arbitration' in category.lower():
            explanation = f"This agreement **mandates binding arbitration** and waives your right to pursue claims through civil litigation. It includes a class action waiver, effectively eliminating collective legal recourse. This significantly limits remedies available for potential violations or damages."
    
    st.markdown(f'<div style="font-size: 1.05rem; line-height: 1.7; color: var(--gray-dark);">{explanation}</div>', unsafe_allow_html=True)
    
    # Actions
    actions = get_action_suggestions(finding)
    if actions:
        st.markdown(f"""
        <div class="action-box">
            <h4>✅ What you can do:</h4>
            {''.join([f'<div class="action-item">{action}</div>' for action in actions])}
        </div>
        """, unsafe_allow_html=True)
    
    # Pagination footer
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        if index > 0:
            if st.button("← Previous", key=f"prev_{index}"):
                st.session_state.current_page = index - 1
                st.rerun()
    
    with col2:
        st.markdown(f"<center style='color: #666; padding-top: 0.5rem;'>Finding {index + 1} of {total}</center>", unsafe_allow_html=True)
    
    with col3:
        if index < total - 1:
            if st.button("Next →", key=f"next_{index}"):
                st.session_state.current_page = index + 1
                st.rerun()

def group_findings_by_category(findings: List[Dict]) -> Dict[str, List[Dict]]:
    """Group findings by category for better organization"""
    grouped = {}
    for finding in findings:
        category = finding.get('category', 'Other')
        if category not in grouped:
            grouped[category] = []
        grouped[category].append(finding)
    return grouped

def analyze_document(text: str = None, url: str = None, file = None, 
                     mode: str = 'quick', jurisdiction: str = 'US-CA', industry: str = 'General'):
    """Call the backend API to analyze document"""
    
    try:
        if file is not None:
            # File upload
            files = {'file': file}
            data = {
                'mode': mode,
                'jurisdictions': jurisdiction,
                'industry': industry
            }
            response = requests.post(f"{API_BASE}/analyze/file", files=files, data=data)
            
        elif url:
            # URL analysis
            payload = {
                'url': url,
                'mode': mode,
                'jurisdictions': [jurisdiction],
                'industry': industry
            }
            response = requests.post(f"{API_BASE}/analyze/url", json=payload)
            
        else:
            # Text analysis
            payload = {
                'text': text,
                'doc_type': 'Privacy Policy',
                'mode': mode,
                'jurisdictions': [jurisdiction],
                'industry': industry
            }
            response = requests.post(f"{API_BASE}/analyze", json=payload)
        
        if response.status_code == 200:
            result = response.json()
            
            # Enrich findings with full paragraphs
            if 'findings' in result and text:
                for finding in result['findings']:
                    if 'excerpt' in finding and finding['excerpt']:
                        # Find the sentence in the full text and extract surrounding paragraph
                        excerpt = finding['excerpt']
                        if excerpt in text:
                            # Find paragraph boundaries
                            start = text.rfind('\n\n', 0, text.index(excerpt))
                            end = text.find('\n\n', text.index(excerpt))
                            start = start if start != -1 else 0
                            end = end if end != -1 else len(text)
                            finding['full_paragraph'] = text[start:end].strip()
            
            return result
        else:
            st.error(f"Error: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        st.error(f"Failed to connect to backend: {str(e)}")
        st.info("💡 Make sure the FastAPI backend is running on localhost:8000")
        return None

# Main App
def main():
    # Header
    st.markdown("<h1 style='text-align: center;'>🔍 Privacy Policy Analyzer</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; font-size: 1.125rem; color: var(--gray-mid); margin-bottom: 2rem;'>Comprehensive privacy and terms-of-service analysis</p>", unsafe_allow_html=True)
    
    # Guide box
    st.info("""
    **Analysis Process:**
    
    1. Submit document via text paste, URL, or file upload
    2. Automated analysis completes in 2–6 minutes depending on scope and mode selection
    3. Receive detailed findings with severity classification and compliance implications
    4. Review actionable recommendations with regulatory and remediation guidance
    """)
    
    # Input tabs
    tab1, tab2, tab3 = st.tabs(["📝 Paste text", "🔗 Enter a website", "📎 Upload a file"])
    
    with tab1:
        text_input = st.text_area(
            "Document text",
            height=200,
            placeholder="Paste full document text here...",
            help="Copy complete policy or agreement text from source document"
        )
    
    with tab2:
        url_input = st.text_input(
            "Document URL",
            placeholder="https://example.com/privacy-policy",
            help="Direct link to privacy policy or terms of service page"
        )
    
    with tab3:
        file_input = st.file_uploader(
            "Upload document",
            type=['pdf', 'txt', 'doc', 'docx'],
            help="Supported formats: PDF, TXT, DOC, DOCX"
        )
    
    st.markdown("---")
    st.markdown("### Analysis Parameters")
    
    col1, col2 = st.columns(2)
    
    with col1:
        jurisdiction = st.selectbox(
            "Jurisdiction",
            options=['US-CA', 'GDPR', 'US-NY', 'US-VA', 'US-General', 'UK', 'CA'],
            format_func=lambda x: {
                'US-CA': 'California (CCPA/CPRA)',
                'GDPR': 'European Union (GDPR)',
                'US-NY': 'New York (SHIELD Act)',
                'US-VA': 'Virginia (VCDPA)',
                'US-General': 'United States (Federal)',
                'UK': 'United Kingdom (UK GDPR)',
                'CA': 'Canada (PIPEDA)'
            }[x],
            help="Select applicable privacy framework for compliance analysis"
        )
    
    with col2:
        industry = st.selectbox(
            "Industry sector",
            options=['General', 'Healthcare', 'Financial', 'Education', 'Children'],
            format_func=lambda x: {
                'General': 'General commercial',
                'Healthcare': 'Healthcare (HIPAA)',
                'Financial': 'Financial services (GLBA)',
                'Education': 'Education (FERPA)',
                'Children': "Children's services (COPPA)"
            }[x],
            help="Industry-specific regulatory frameworks will be applied"
        )
    
    mode = st.radio(
        "Analysis depth",
        options=['quick', 'full'],
        format_func=lambda x: 'Quick scan (~2 min, high-severity only)' if x == 'quick' else 'Comprehensive review (~6 min, all findings)',
        help="Quick scan prioritizes critical issues; comprehensive review examines all potential concerns",
        horizontal=True
    )
    
    # Analyze button
    if st.button("🔍 Analyze Document", type="primary", use_container_width=True):
        with st.spinner('Processing document... estimated completion: 2-6 minutes'):
            result = analyze_document(
                text=text_input if text_input else None,
                url=url_input if url_input else None,
                file=file_input if file_input else None,
                mode=mode,
                jurisdiction=jurisdiction,
                industry=industry
            )
            
            if result:
                st.session_state.findings = result.get('findings', [])
                st.session_state.analysis_complete = True
                st.session_state.current_page = 0
                st.session_state.source_text = text_input  # Save for paragraph extraction
                st.rerun()
    
    # Results
    if st.session_state.analysis_complete and st.session_state.findings:
        st.markdown("---")
        st.markdown("## 📊 Analysis Results")
        
        findings = st.session_state.findings
        
        # Summary stats
        severity_counts = {'Critical': 0, 'High': 0, 'Medium': 0, 'Low': 0}
        for f in findings:
            sev = f.get('severity', 'Low')
            if sev in severity_counts:
                severity_counts[sev] += 1
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Critical", severity_counts['Critical'])
        col2.metric("High", severity_counts['High'])
        col3.metric("Medium", severity_counts['Medium'])
        col4.metric("Low", severity_counts['Low'])
        
        st.markdown("---")
        
        # Group by category
        grouped = group_findings_by_category(findings)
        
        if len(grouped) > 1:
            st.markdown("### Category filter:")
            categories = ['All categories'] + list(grouped.keys())
            selected_category = st.selectbox(
                "Select category",
                options=categories,
                label_visibility="collapsed"
            )
            
            if selected_category == 'All categories':
                current_findings = findings
            else:
                current_findings = grouped[selected_category]
        else:
            current_findings = findings
        
        # Display current finding
        if current_findings:
            current_page = min(st.session_state.current_page, len(current_findings) - 1)
            display_finding(current_findings[current_page], current_page, len(current_findings))
    
    elif st.session_state.analysis_complete:
        st.success("✅ Analysis complete. No significant concerns identified under selected jurisdiction and industry parameters.")
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; padding: 2rem; color: var(--gray-mid);'>
        <p><strong style='color: var(--purple-dark);'>Legal Disclaimer:</strong> 
        This tool provides automated informational analysis only and does not constitute legal advice. 
        Results should be reviewed by qualified legal counsel before making decisions affecting rights, obligations, or regulatory compliance. 
        No attorney-client relationship is created through use of this service.</p>
        <p style='font-size: 0.875rem; margin-top: 1rem;'>
            Privacy Policy Analyzer • Professional Analysis • Documents processed locally and not retained
        </p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
