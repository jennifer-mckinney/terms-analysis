// Terms & Policies Reviewer Application JavaScript

// Plain-English category labels and impact descriptions for parents/students/caretakers
const CATEGORY_INFO = {
    'Dark Patterns': {
        label: 'Misleading Design',
        impact: 'The app may use tricks or confusing layouts to get you to agree to things you didn\'t intend to.'
    },
    'Sale/Share': {
        label: 'Selling Your Data',
        impact: 'Your personal information may be sold or shared with other companies for advertising or profit.'
    },
    'Retention': {
        label: 'Keeps Your Data Indefinitely',
        impact: 'They may store your information forever with no clear date for deleting it.'
    },
    'Unilateral Changes': {
        label: 'Can Change Terms Without Notice',
        impact: 'They can quietly update the policy at any time and it still applies to you — even if you never see the new version.'
    },
    'Children\'s Privacy': {
        label: 'Children\'s Data at Risk',
        impact: 'Your child\'s information may not be adequately protected or could be collected without proper parental consent.'
    },
    'Biometric Data': {
        label: 'Face, Voice & Fingerprint Data',
        impact: 'The app may record and store your child\'s biometric data such as facial recognition, voice prints, or fingerprints.'
    },
    'Sensitive Data': {
        label: 'Collects Sensitive Personal Info',
        impact: 'Health, financial, location, or other sensitive details are being collected — often shared more broadly than you\'d expect.'
    },
    'Automated Decisions': {
        label: 'Computer Makes Decisions About You',
        impact: 'An algorithm automatically makes decisions that affect you or your child — without a human reviewing them.'
    },
    'Liability': {
        label: 'Limits Your Legal Rights',
        impact: 'You may have signed away your right to sue or join a class action lawsuit if the company causes harm.'
    },
    'User Rights': {
        label: 'Hard to Delete or Access Your Data',
        impact: 'The policy makes it difficult for you to see what data they have, correct mistakes, or have it deleted.'
    }
};

const CONCERN_MAP = {
    'Selling My Data':           ['sale', 'share', 'sell', 'third'],
    'Health & Medical Info':     ['health', 'medical', 'biometric'],
    'How Long They Keep My Data':['retention', 'retain', 'store', 'indefinit'],
    "Children's Safety":         ['child', 'minor', 'coppa', 'under 13'],
    'Tracking & Profiling':      ['track', 'profil', 'monitor'],
    'Automated Decisions (AI)':  ['automat', 'ai training', 'decision'],
    'Arbitration & Legal Rights':['arbitrat', 'class action', 'waive', 'dispute'],
    'Financial Information':     ['financ', 'payment', 'credit'],
    'Right to Delete':           ['delet', 'remov', 'erasure', 'right to'],
    'Security Practices':        ['secur', 'breach', 'encrypt'],
};

const GRADE_NARRATIVE = {
    'A':  { emoji: '✅', headline: 'Looks Safe',         detail: 'This policy scored well. We didn\'t find major red flags.' },
    'B':  { emoji: '🟡', headline: 'Minor Concerns',     detail: 'A few things to be aware of, but nothing alarming. Worth a quick look.' },
    'C+': { emoji: '🟠', headline: 'Watch Out',          detail: 'Several issues that could affect your privacy. Read the findings carefully.' },
    'C':  { emoji: '🟠', headline: 'Concerning',         detail: 'Notable privacy or safety problems. Think carefully before using this service.' },
    'D+': { emoji: '🔴', headline: 'Serious Issues',     detail: 'Significant problems found. We recommend avoiding this service or contacting the company.' },
    'D':  { emoji: '🔴', headline: 'Very Concerning',    detail: 'Major red flags. This policy has serious privacy or safety violations.' }
};

// Application Data
const API_BASE_URL = window.API_BASE_URL || 'http://localhost:9000';
const API_LOGGING = true;
const state = {
    analyses: [],
    watchlist: [],
    rubricScores: null,
    backendOnline: false,
    reviews: []
};

// Application State

let currentPage = 'dashboard';
let currentTheme = 'auto';
let currentAnalysis = null;

// DOM Elements
const navButtons = document.querySelectorAll('.nav-btn');
const pages = document.querySelectorAll('.page');
const themeToggle = document.getElementById('themeToggle');
const loadingOverlay = document.getElementById('loadingOverlay');
const modal = document.getElementById('modal');
const modalTitle = document.getElementById('modalTitle');
const modalBody = document.getElementById('modalBody');
const modalClose = document.getElementById('modalClose');
const modalBackdrop = document.getElementById('modalBackdrop');
const toastContainer = document.getElementById('toastContainer');

// Initialize Application
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

async function initializeApp() {
    setupNavigation();
    setupThemeToggle();
    setupModalHandlers();
    setupDocumentReview();
    setupComparison();
    setupWatchlist();
    setupReports();
    setupSettings();
    await loadInitialData();
    
    // Set initial theme
    applyTheme(getPreferredTheme());
}

async function loadInitialData() {
    await checkBackendHealth();
    if (state.backendOnline) {
        await Promise.all([
            refreshAnalyses(),
            refreshWatchlist(),
            refreshReviews(),
            refreshRubricScores()
        ]);
    }
    populateDashboard();
    populateWatchlist();
    populateVendorSelectors();
    populateRubricScores();
    populateReviewQueue();
    setResultsPlaceholder('No analysis yet. Run a document to see results.');
}

// Navigation
function setupNavigation() {
    navButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetPage = btn.getAttribute('data-page');
            navigateToPage(targetPage);
        });
    });

    // Quick action buttons
    document.addEventListener('click', (e) => {
        const action = e.target.closest('[data-action]')?.getAttribute('data-action');
        if (action) {
            handleQuickAction(action);
        }
    });
}

function navigateToPage(pageName) {
    // Update active nav button
    navButtons.forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-page') === pageName);
    });

    // Update active page
    pages.forEach(page => {
        page.classList.toggle('active', page.id === pageName);
    });

    currentPage = pageName;

    // Load page-specific data
    switch (pageName) {
        case 'dashboard':
            populateDashboard();
            break;
        case 'compare':
            populateVendorSelectors();
            break;
        case 'watchlist':
            populateWatchlist();
            break;
        case 'reports':
            populateRubricScores();
            populateReviewQueue();
            break;
        case 'reviews':
            populateReviewQueue();
            break;
    }
}

function handleQuickAction(action) {
    switch (action) {
        case 'new-review':
            navigateToPage('reviews');
            break;
        case 'compare':
            navigateToPage('compare');
            break;
        case 'export':
            navigateToPage('reports');
            break;
        case 'export-results':
            if (currentAnalysis) {
                exportResults(currentAnalysis.id);
            } else {
                showToast('No analysis to export', 'warning');
            }
            break;
        case 'add-watchlist':
            if (currentAnalysis) {
                addToWatchlist(currentAnalysis.name || currentAnalysis.source_url || 'Untitled Document', currentAnalysis.source_url);
            } else {
                showToast('No analysis to add', 'warning');
            }
            break;
    }
}

// Theme Management
function setupThemeToggle() {
    themeToggle.addEventListener('click', toggleTheme);
}

function toggleTheme() {
    const themes = ['auto', 'light', 'dark'];
    const currentIndex = themes.indexOf(currentTheme);
    currentTheme = themes[(currentIndex + 1) % themes.length];
    
    applyTheme(currentTheme);
    updateThemeIcon();
    
    // Save preference
    localStorage.setItem('theme', currentTheme);
    showToast('Theme updated', 'info');
}

function applyTheme(theme) {
    const html = document.documentElement;
    
    if (theme === 'auto') {
        html.removeAttribute('data-color-scheme');
    } else {
        html.setAttribute('data-color-scheme', theme);
    }
    
    currentTheme = theme;
}

function updateThemeIcon() {
    const icon = themeToggle.querySelector('i');
    const icons = {
        'auto': 'fa-adjust',
        'light': 'fa-sun',
        'dark': 'fa-moon'
    };
    
    icon.className = `fas ${icons[currentTheme]}`;
}

function getPreferredTheme() {
    return localStorage.getItem('theme') || 'auto';
}

// Modal Management
function setupModalHandlers() {
    modalClose.addEventListener('click', closeModal);
    modalBackdrop.addEventListener('click', closeModal);
    
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
            closeModal();
        }
    });
}

function showModal(title, content) {
    modalTitle.textContent = title;
    modalBody.innerHTML = content;
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    modal.classList.add('hidden');
    document.body.style.overflow = '';
}

// Toast Notifications
function showToast(message, type = 'info', duration = 3000) {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <i class="fas fa-${getToastIcon(type)}"></i>
        <span>${message}</span>
    `;
    
    toastContainer.appendChild(toast);
    
    setTimeout(() => {
        toast.remove();
    }, duration);
}

function getToastIcon(type) {
    const icons = {
        'success': 'check-circle',
        'error': 'exclamation-circle',
        'warning': 'exclamation-triangle',
        'info': 'info-circle'
    };
    return icons[type] || 'info-circle';
}

async function fetchJSON(path, options = {}) {
    const method = options.method || 'GET';
    const url = `${API_BASE_URL}${path}`;
    const startedAt = performance.now();
    if (API_LOGGING) {
        console.info(`[api] ${method} ${url} -> start`);
    }
    const response = await fetch(url, options);
    if (!response.ok) {
        const raw = await response.text();
        if (API_LOGGING) {
            const duration = Math.round(performance.now() - startedAt);
            console.info(`[api] ${method} ${url} -> ${response.status} (${duration}ms)`);
        }
        let message = raw;
        try {
            const parsed = JSON.parse(raw);
            if (parsed && parsed.detail) message = parsed.detail;
        } catch (_) { /* use raw text */ }
        throw new Error(message || `Request failed (${response.status})`);
    }
    state.backendOnline = true;
    setBackendStatus(true);
    const data = await response.json();
    if (API_LOGGING) {
        const duration = Math.round(performance.now() - startedAt);
        console.info(`[api] ${method} ${url} -> ${response.status} (${duration}ms)`);
    }
    return data;
}

async function refreshAnalyses() {
    try {
        const data = await fetchJSON('/analyses');
        state.analyses = Array.isArray(data) ? data : [];
    } catch (error) {
        state.analyses = [];
        state.backendOnline = false;
        setBackendStatus(false);
        showToast('Backend not reachable for analyses', 'warning');
    }
}

async function refreshWatchlist() {
    try {
        const data = await fetchJSON('/watchlist');
        state.watchlist = Array.isArray(data) ? data : [];
    } catch (error) {
        state.watchlist = [];
        state.backendOnline = false;
        setBackendStatus(false);
        showToast('Backend not reachable for watchlist', 'warning');
    }
}

async function refreshReviews() {
    try {
        const data = await fetchJSON('/reviews');
        state.reviews = Array.isArray(data) ? data : [];
    } catch (error) {
        state.reviews = [];
        state.backendOnline = false;
        setBackendStatus(false);
    }
}

async function refreshRubricScores() {
    try {
        const data = await fetchJSON('/rubric');
        state.rubricScores = data || null;
    } catch (error) {
        state.rubricScores = null;
    }
}

function populateReviewQueue() {
    const containers = [
        document.getElementById('reviewQueue'),
        document.getElementById('reviewList')
    ].filter(Boolean);

    if (!containers.length) return;

    if (!state.backendOnline) {
        containers.forEach(container => {
            container.innerHTML = '<p class="text-secondary">Backend offline. Start the server to view the review queue.</p>';
        });
        return;
    }

    if (!state.reviews.length) {
        containers.forEach(container => {
            container.innerHTML = '<p class="text-secondary">No pending reviews — everything checked out automatically.</p>';
        });
        return;
    }

    // Build a quick lookup map: analysis_id → analysis record
    const analysisMap = {};
    (state.analyses || []).forEach(a => { analysisMap[a.id] = a; });

    const html = state.reviews.map(item => {
        const analysis = analysisMap[item.analysis_id] || null;
        const docName  = analysis ? (analysis.name || analysis.source_url || 'Unnamed document') : 'Unknown document';
        const grade    = analysis ? (analysis.grade || '?') : '?';
        const gradeInfo = GRADE_NARRATIVE[grade] || { emoji: '', headline: grade };
        const confPct  = analysis ? Math.round((analysis.confidence || 0) * 100) : '?';
        const checkedDate = item.created_at ? new Date(item.created_at).toLocaleDateString() : '';

        return `
            <div class="review-item" style="border:1px solid var(--color-card-border);border-radius:8px;padding:14px;margin-bottom:12px">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap">
                    <div style="flex:1;min-width:0">
                        <div style="font-weight:600;font-size:0.95rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${docName}</div>
                        <div class="text-secondary" style="font-size:0.85rem;margin-top:2px">
                            Checked ${checkedDate} &middot; Grade ${gradeInfo.emoji} ${grade} &middot; Scan confidence: ${confPct}%
                        </div>
                        <div style="font-size:0.82rem;margin-top:6px;color:var(--color-warning)">
                            <i class="fas fa-exclamation-triangle"></i>
                            Confidence below 80% — a human should verify these findings before the result is trusted.
                        </div>
                    </div>
                    <div class="review-actions" style="display:flex;gap:8px;flex-shrink:0;align-items:center">
                        <button class="btn btn--sm btn--primary" onclick="updateReview('${item.id}', 'approved')"
                            title="The AI findings look correct — mark this analysis as verified">
                            <i class="fas fa-check"></i> Findings Look Right
                        </button>
                        <button class="btn btn--sm btn--outline" onclick="updateReview('${item.id}', 'rejected')"
                            title="The AI findings seem wrong or misleading — flag this for re-analysis">
                            <i class="fas fa-times"></i> Findings Seem Wrong
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    containers.forEach(container => {
        container.innerHTML = html;
    });
}

async function updateReview(reviewId, status) {
    const notes = prompt('Optional notes for this review:', '');
    try {
        await fetchJSON(`/reviews/${reviewId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status, notes: notes || null })
        });
        await refreshReviews();
        populateReviewQueue();
        showToast(`Review ${status}`, 'success');
    } catch (error) {
        showToast('Failed to update review', 'error');
    }
}

async function checkBackendHealth() {
    try {
        if (API_LOGGING) {
            console.info(`[api] GET ${API_BASE_URL}/health -> start`);
        }
        const response = await fetch(`${API_BASE_URL}/health`);
        state.backendOnline = response.ok;
        setBackendStatus(response.ok);
        if (API_LOGGING) {
            console.info(`[api] GET ${API_BASE_URL}/health -> ${response.status}`);
        }
    } catch (error) {
        state.backendOnline = false;
        setBackendStatus(false);
    }
}

function setBackendStatus(isOnline) {
    const statusEl = document.getElementById('backendStatus');
    if (!statusEl) return;
    const label = isOnline ? 'Backend: Online' : 'Backend: Offline';
    const className = isOnline ? 'status status--success' : 'status status--error';
    statusEl.innerHTML = `<span class="${className}">${label}</span>`;
}

// Dashboard Functions
function populateDashboard() {
    populateDashboardStats();
    populateRecentAnalysis();
    populateWatchlistAlerts();
    populateGradeDistribution();
    populateTopRiskCategories();
}

function populateDashboardStats() {
    const docCount = state.analyses.length;
    const reviewCount = state.analyses.filter(item => item.status === 'needs_review').length;
    const watchlistCount = state.watchlist.length;
    const alertCount = state.watchlist.filter(item => item.status === 'Updated').length;

    const statDocuments = document.getElementById('statDocuments');
    const statNeedsReview = document.getElementById('statNeedsReview');
    const statWatchlist = document.getElementById('statWatchlist');
    const statAlerts = document.getElementById('statAlerts');

    if (statDocuments) statDocuments.textContent = docCount;
    if (statNeedsReview) statNeedsReview.textContent = reviewCount;
    if (statWatchlist) statWatchlist.textContent = watchlistCount;
    if (statAlerts) statAlerts.textContent = alertCount;
}

function populateRecentAnalysis() {
    const container = document.getElementById('recentAnalysis');
    if (!container) return;

    if (!state.backendOnline) {
        container.innerHTML = '<p class="text-secondary">Backend offline. Start the server to see analyses.</p>';
        return;
    }

    if (!state.analyses.length) {
        container.innerHTML = '<p class="text-secondary">No analyses yet</p>';
        return;
    }

    const html = state.analyses.map(doc => {
        const date = new Date(doc.created_at).toLocaleDateString();
        const riskClass = getRiskClass(doc.risk_score);
        const name = doc.name || doc.source_url || 'Untitled Document';
        const gradeInfo = GRADE_NARRATIVE[doc.grade] || { emoji: '', headline: doc.grade };

        const reviewBadge = doc.status === 'needs_review'
            ? '<span class="status status--warning">Needs expert review</span>'
            : '';
        const safeDocId = String(doc.id || '').replace(/'/g, "\\'");
        return `
            <div class="analysis-item analysis-item--clickable" style="cursor:pointer"
                 onclick="navigateToDashboardAnalysis('${safeDocId}')"
                 title="View full analysis">
                <div class="analysis-meta">
                    <div class="analysis-name">${name}</div>
                    <div class="analysis-date">Checked ${date} ${reviewBadge}</div>
                </div>
                <div class="risk-badge ${riskClass}" title="${gradeInfo.headline}">${gradeInfo.emoji} ${doc.grade}</div>
            </div>
        `;
    }).join('');

    container.innerHTML = html;
}

function populateWatchlistAlerts() {
    const container = document.getElementById('watchlistAlerts');
    if (!container) return;

    if (!state.backendOnline) {
        container.innerHTML = '<p class="text-secondary">Backend offline. Start the server to see alerts.</p>';
        return;
    }

    const updatedItems = state.watchlist.filter(item => item.status === 'Updated');
    
    const html = updatedItems.map(item => {
        return `
            <div class="analysis-item">
                <div class="analysis-meta">
                    <div class="analysis-name">${item.vendor}</div>
                    <div class="analysis-date">${item.change_count} changes detected</div>
                </div>
                <div class="risk-badge medium">+${item.risk_delta}</div>
            </div>
        `;
    }).join('');

    container.innerHTML = html || '<p class="text-secondary">No recent alerts</p>';
}

function populateGradeDistribution() {
    const container = document.getElementById('gradeDistribution');
    if (!container) return;

    if (!state.analyses.length) {
        container.innerHTML = '<p class="text-secondary" style="font-size:0.85rem">No policies checked yet.</p>';
        return;
    }

    const GRADE_ORDER = ['A', 'B', 'C+', 'C', 'D+', 'D'];
    const counts = {};
    GRADE_ORDER.forEach(g => { counts[g] = 0; });
    state.analyses.forEach(a => {
        const g = a.grade;
        if (g in counts) counts[g]++;
        else counts['C'] = (counts['C'] || 0) + 1;
    });

    const GRADE_COLORS = { 'A': '#059669', 'B': '#65a30d', 'C+': '#d97706', 'C': '#f59e0b', 'D+': '#dc2626', 'D': '#991b1b' };

    const bars = GRADE_ORDER.map(g => {
        const count = counts[g];
        if (!count) return '';
        const color = GRADE_COLORS[g] || 'var(--color-primary)';
        return `
            <div class="grade-bar-item">
                <div class="grade-bar-label" style="color:${color}">${g}</div>
                <div class="grade-bar-track">
                    <div class="grade-bar-fill" style="background:${color};width:${Math.round((count / state.analyses.length) * 100)}%"></div>
                </div>
                <div class="grade-bar-count">${count}</div>
            </div>
        `;
    }).join('');

    container.innerHTML = bars || '<p class="text-secondary" style="font-size:0.85rem">No graded policies yet.</p>';
}

function populateTopRiskCategories() {
    const container = document.getElementById('topRiskCategories');
    if (!container) return;

    if (!state.analyses.length) {
        container.innerHTML = '';
        return;
    }

    const categoryCounts = {};
    state.analyses.forEach(a => {
        (a.findings || []).forEach(f => {
            if (f.category) {
                categoryCounts[f.category] = (categoryCounts[f.category] || 0) + 1;
            }
        });
    });

    const top3 = Object.entries(categoryCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3);

    if (!top3.length) {
        container.innerHTML = '';
        return;
    }

    const items = top3.map(([cat, count]) => {
        const info = CATEGORY_INFO[cat] || { label: cat };
        return `<div class="top-risk-item"><span class="top-risk-name">${info.label}</span><span class="top-risk-count">${count} finding${count !== 1 ? 's' : ''}</span></div>`;
    }).join('');

    container.innerHTML = `<div style="margin-top:12px"><div style="font-size:0.8rem;font-weight:600;color:var(--color-text-secondary);text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px">Top Issues Found</div>${items}</div>`;
}

function navigateToDashboardAnalysis(docId) {
    const doc = state.analyses.find(a => String(a.id) === String(docId));
    if (!doc) {
        showToast('Analysis not found', 'warning');
        return;
    }
    navigateToPage('review');
    currentAnalysis = doc;
    displayAnalysisResults(doc, 'full');
}

// Document Review Functions
function setupDocumentReview() {
    setupInputTabs();
    setupFileUpload();
    setupAnalyzeButton();
    setupJurisdictionToggle();
    setupConcernChips();
}

function setupJurisdictionToggle() {
    const toggleBtn = document.getElementById('jurisdictionToggleBtn');
    const panel = document.getElementById('jurisdictionPanel');
    const summary = document.getElementById('jurisdictionSummary');
    if (!toggleBtn || !panel) return;

    toggleBtn.addEventListener('click', () => {
        const isOpen = !panel.classList.contains('hidden');
        panel.classList.toggle('hidden', isOpen);
        toggleBtn.setAttribute('aria-expanded', String(!isOpen));
        toggleBtn.innerHTML = isOpen
            ? 'Show all <i class="fas fa-chevron-down"></i>'
            : 'Hide <i class="fas fa-chevron-up"></i>';
    });

    // Update summary line whenever a checkbox changes
    panel.addEventListener('change', () => {
        updateJurisdictionSummary();
    });
}

function updateJurisdictionSummary() {
    const summary = document.getElementById('jurisdictionSummary');
    const toggleBtn = document.getElementById('jurisdictionToggleBtn');
    if (!summary || !toggleBtn) return;
    const checked = Array.from(document.querySelectorAll('input[name="jurisdiction"]:checked'))
        .map(i => i.value);
    const label = checked.length ? `Selected: ${checked.join(', ')}` : 'None selected';
    // Preserve the button
    summary.childNodes[0].textContent = label + ' ';
}

function setupConcernChips() {
    const container = document.getElementById('concernChips');
    if (!container) return;
    container.addEventListener('click', (e) => {
        const chip = e.target.closest('.concern-chip');
        if (!chip) return;
        chip.classList.toggle('selected');
    });
}

function setupInputTabs() {
    const tabButtons = document.querySelectorAll('.tab-btn');
    const inputPanels = document.querySelectorAll('.input-panel');

    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const inputType = btn.getAttribute('data-input');
            
            // Update active tab
            tabButtons.forEach(t => t.classList.remove('active'));
            btn.classList.add('active');
            
            // Update active panel
            inputPanels.forEach(panel => {
                panel.classList.toggle('active', panel.id === `${inputType}-input`);
            });
        });
    });
}

function setupFileUpload() {
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');

    uploadArea.addEventListener('click', () => fileInput.click());
    
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = 'var(--color-primary)';
    });
    
    uploadArea.addEventListener('dragleave', () => {
        uploadArea.style.borderColor = '';
    });
    
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = '';
        const files = e.dataTransfer.files;
        handleFileSelection(files);
    });

    fileInput.addEventListener('change', (e) => {
        handleFileSelection(e.target.files);
    });
}

function handleFileSelection(files) {
    if (files.length > 0) {
        const fileNames = Array.from(files).map(f => f.name).join(', ');
        showToast(`Selected: ${fileNames}`, 'success');
    }
}

function setupAnalyzeButton() {
    const analyzeBtn = document.getElementById('analyzeBtn');
    analyzeBtn.addEventListener('click', startAnalysis);
}

async function startAnalysis() {
    const activeTab = document.querySelector('.tab-btn.active');
    const activeInput = activeTab ? activeTab.getAttribute('data-input') : null;
    const documentUrl = document.getElementById('documentUrl').value;
    const documentText = document.getElementById('documentText').value;
    const fileInput = document.getElementById('fileInput');
    const analysisMode = document.querySelector('input[name="analysisMode"]:checked').value;
    const jurisdictions = Array.from(document.querySelectorAll('input[name="jurisdiction"]:checked'))
        .map(input => input.value);

    // Validate input based on active tab
    const hasUrl = activeInput === 'url' && documentUrl;
    const hasText = activeInput === 'text' && documentText;
    const hasFile = activeInput === 'upload' && fileInput.files.length > 0;
    if (!hasUrl && !hasText && !hasFile) {
        showToast('Please provide a document URL, upload a file, or paste text', 'error');
        return;
    }
    if (!jurisdictions.length) {
        showToast('Select at least one jurisdiction', 'error');
        return;
    }
    await checkBackendHealth();
    if (!state.backendOnline) {
        showToast('Backend offline. Start the server to analyze.', 'error');
        return;
    }

    // Map UI mode names to backend values
    const backendMode = analysisMode === 'quick' ? 'quick' : 'full';

    // Show loading
    showLoading('Checking policy...');
    setResultsPlaceholder('Checking policy...');
    try {
        let result = null;
        if (hasUrl) {
            result = await analyzeUrl(documentUrl, jurisdictions, backendMode);
        } else if (hasFile) {
            result = await analyzeFile(fileInput.files[0], jurisdictions, backendMode);
        } else {
            result = await analyzeText(documentText, jurisdictions, backendMode);
        }

        currentAnalysis = result;
        await refreshAnalyses();
        populateDashboard();
        populateVendorSelectors();
        await refreshRubricScores();
        populateRubricScores();
        displayAnalysisResults(result, analysisMode);
        applyUserConcernFilter();
        showToast('Policy check complete', 'success');
    } catch (error) {
        const msg = error.message || 'Analysis failed';
        const isBlocked = msg.toLowerCase().includes('block') || msg.toLowerCase().includes('403');
        const placeholder = isBlocked
            ? 'This website blocks automated access — try the "Paste Text" tab and paste the policy directly.'
            : `Check failed: ${msg}`;
        setResultsPlaceholder(placeholder);
        showToast(msg, 'error');
    } finally {
        hideLoading();
    }
}

async function analyzeText(text, jurisdictions, mode = 'full') {
    const payload = { text, jurisdictions, mode };
    return fetchJSON('/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
}

async function analyzeUrl(url, jurisdictions, mode = 'full') {
    const payload = { url, jurisdictions, mode };
    return fetchJSON('/analyze/url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
}

async function analyzeFile(file, jurisdictions, mode = 'full') {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('jurisdictions', jurisdictions.join(','));
    formData.append('mode', mode);
    return fetchJSON('/analyze/file', {
        method: 'POST',
        body: formData
    });
}

function displayAnalysisResults(doc, mode) {
    const resultsSection = document.getElementById('resultsSection');

    const name = doc.name || doc.source_url || 'Untitled Document';
    const analyzedDate = new Date(doc.created_at).toLocaleDateString();
    const grade = doc.grade || 'C';
    const gradeInfo = GRADE_NARRATIVE[grade] || GRADE_NARRATIVE['C'];
    const riskScore = typeof doc.risk_score === 'number' ? doc.risk_score.toFixed(1) : doc.risk_score;
    const modeLabel = mode === 'quick' ? 'Quick Scan — serious issues only' : 'Deep Read — full analysis';

    const highCount = (doc.findings || []).filter(f => (f.severity || '').toUpperCase() === 'HIGH').length;
    const medCount  = (doc.findings || []).filter(f => (f.severity || '').toUpperCase() === 'MEDIUM').length;
    const lowCount  = (doc.findings || []).filter(f => (f.severity || '').toUpperCase() === 'LOW').length;

    // Confidence explanation
    const confidencePct = Math.round((doc.confidence || 0) * 100);
    let confidenceNote = '';
    if (confidencePct < 50) {
        confidenceNote = `<p class="text-secondary" style="margin-top:6px;font-size:0.88rem">
            <i class="fas fa-info-circle"></i>
            <strong>Scan confidence: ${confidencePct}%</strong> — The AI assistant wasn't available, so this is a pattern-only scan.
            Results may miss some issues or have false positives. A human review is recommended.
        </p>`;
    } else if (confidencePct < 80) {
        confidenceNote = `<p class="text-secondary" style="margin-top:6px;font-size:0.88rem">
            <i class="fas fa-info-circle"></i>
            <strong>Scan confidence: ${confidencePct}%</strong> — Partial AI analysis completed.
            Some findings may need human verification before acting on them.
        </p>`;
    }

    // Score explanation
    const scoreContext = riskScore >= 8 ? 'Very high risk (8–10)' :
                         riskScore >= 7 ? 'High risk (7–8)' :
                         riskScore >= 5 ? 'Moderate risk (5–7)' :
                         riskScore >= 3 ? 'Low risk (3–5)' : 'Minimal risk (0–3)';

    const humanReviewNote = doc.review_required
        ? `<p class="text-secondary" style="margin-top:4px"><i class="fas fa-user-check"></i> Low confidence — a human expert should verify these findings before you decide.</p>`
        : '';

    const summaryText = doc.summary
        ? `<p style="margin-top:8px">${doc.summary}</p>`
        : '';

    const findingsHtml = (doc.findings || []).length
        ? (doc.findings).map(finding => createFindingHTML(finding)).join('')
        : '<p class="text-secondary">No issues found in this section.</p>';

    const html = `
        <div class="results-header">
            <div style="flex:1">
                <h3>${name}</h3>
                <p class="text-secondary">Checked on ${analyzedDate} &middot; ${modeLabel}</p>
            </div>
            <div class="risk-score" title="${scoreContext}">
                <div class="risk-score-value">${riskScore}</div>
                <div class="risk-grade">Grade ${grade}</div>
                <div style="font-size:0.72rem;color:var(--color-text-secondary);text-align:center;margin-top:2px">${scoreContext}</div>
            </div>
        </div>

        <div class="finding-item" style="background:var(--color-surface-alt,rgba(94,82,64,0.06));border-left:4px solid var(--color-primary);margin-bottom:16px">
            <div style="font-size:1.25rem;font-weight:700;margin-bottom:4px">${gradeInfo.emoji} ${gradeInfo.headline}</div>
            <p>${gradeInfo.detail}</p>
            ${summaryText}
            ${confidenceNote}
            ${humanReviewNote}
            <div style="margin-top:10px;display:flex;gap:12px;flex-wrap:wrap">
                ${highCount ? `<span class="finding-severity high">${highCount} Serious</span>` : ''}
                ${medCount  ? `<span class="finding-severity medium">${medCount} Moderate</span>` : ''}
                ${lowCount  ? `<span class="finding-severity low">${lowCount} Minor</span>` : ''}
                ${!highCount && !medCount && !lowCount ? '<span class="text-secondary">No issues flagged</span>' : ''}
            </div>
        </div>

        ${(doc.findings || []).length ? '<h4 style="margin-bottom:8px">What We Found</h4>' : ''}
        <div class="findings-list">
            ${findingsHtml}
        </div>

        <div class="jurisdiction-summary mt-16">
            <h4>Privacy Laws Checked Against</h4>
            ${createJurisdictionSummary(doc.findings || [])}
        </div>

        <div class="action-buttons mt-16">
            <button class="btn btn--primary" data-action="export-results">
                <i class="fas fa-download"></i> Save Report
            </button>
            <button class="btn btn--secondary" data-action="add-watchlist">
                <i class="fas fa-eye"></i> Watch for Changes
            </button>
            <button class="btn btn--outline" onclick="showVerifyView()">
                <i class="fas fa-list"></i> Show Source Text
            </button>
        </div>

        <div class="rubric-mini-card mt-16">
            <div class="rubric-mini-header">
                <i class="fas fa-info-circle"></i> How We Scored This
            </div>
            <div class="rubric-mini-body">
                <div class="rubric-mini-grade">
                    <span style="font-weight:700;font-size:1.1rem">Grade ${grade}</span>
                    &mdash; ${gradeInfo.headline}
                </div>
                <div class="rubric-mini-thresholds">
                    <span class="rubric-threshold" title="Score 0–3">A: few/no issues</span>
                    <span class="rubric-threshold" title="Score 3–5">B: minor concerns</span>
                    <span class="rubric-threshold" title="Score 5–8">C: watch out</span>
                    <span class="rubric-threshold" title="Score 8–10">D: serious problems</span>
                </div>
                <div style="margin-top:8px;font-size:0.82rem;color:var(--color-text-secondary)">
                    Score = 0.5&times;(Impact/5) + 0.4&times;(Likelihood/5) &minus; 0.3&times;(Safeguards/5)
                </div>
            </div>
            <div class="rubric-mini-footer">
                <a href="#" onclick="navigateToPage('reports');return false">See full rubric &rarr;</a>
            </div>
        </div>
    `;

    resultsSection.innerHTML = html;
    currentAnalysis = doc;
}

function setResultsPlaceholder(message) {
    const resultsSection = document.getElementById('resultsSection');
    if (!resultsSection) return;
    resultsSection.innerHTML = `<p class="text-secondary">${message}</p>`;
}

function applyUserConcernFilter() {
    const selectedChips = Array.from(document.querySelectorAll('.concern-chip.selected'));
    if (!selectedChips.length) return;

    const selectedConcerns = selectedChips.map(c => c.getAttribute('data-concern'));
    const keywords = selectedConcerns.flatMap(concern => CONCERN_MAP[concern] || []);
    if (!keywords.length) return;

    const findingsList = document.querySelector('.findings-list');
    if (!findingsList) return;
    const items = Array.from(findingsList.querySelectorAll('.finding-item'));
    if (!items.length) return;

    const matched = [];
    const unmatched = [];
    items.forEach(item => {
        const text = item.textContent.toLowerCase();
        const hits = keywords.some(kw => text.includes(kw.toLowerCase()));
        if (hits) {
            matched.push(item);
            item.classList.add('concern-highlight');
        } else {
            unmatched.push(item);
            item.classList.remove('concern-highlight');
        }
    });

    // Re-order: matched first, then unmatched
    [...matched, ...unmatched].forEach(el => findingsList.appendChild(el));
}

function createFindingHTML(finding) {
    const info = CATEGORY_INFO[finding.category] || { label: finding.category, impact: finding.explanation || '' };
    const severityUpper = (finding.severity || '').toUpperCase();
    const severityLabels = { HIGH: 'Serious', MEDIUM: 'Moderate', LOW: 'Minor' };
    const severityLabel = severityLabels[severityUpper] || finding.severity;
    const safeCategory = (finding.category || '').replace(/'/g, "\\'");
    return `
        <div class="finding-item" onclick="showFindingDetails('${safeCategory}')">
            <div class="finding-header">
                <div class="finding-category">${info.label}</div>
                <div class="finding-severity ${severityUpper.toLowerCase()}">${severityLabel}</div>
            </div>
            <p style="margin:6px 0 4px;font-size:0.92rem">${info.impact}</p>
            <div class="finding-excerpt">"${finding.excerpt}"</div>
        </div>
    `;
}

function createJurisdictionSummary(findings) {
    const jurisdictions = [...new Set(findings.flatMap(f => f.jurisdictions || []))];
    if (!jurisdictions.length) {
        return '<span class="text-secondary">No jurisdiction tags</span>';
    }
    return jurisdictions.map(j => `<span class="status status--info">${j}</span>`).join(' ');
}

function showFindingDetails(category) {
    const finding = currentAnalysis.findings.find(f => f.category === category);
    if (!finding) return;
    const evidence = finding.evidence || { line_start: '-', line_end: '-', legal_basis: [] };
    const info = CATEGORY_INFO[category] || { label: category, impact: finding.explanation || '' };
    const severityUpper = (finding.severity || '').toUpperCase();
    const severityLabels = { HIGH: 'Serious', MEDIUM: 'Moderate', LOW: 'Minor' };
    const severityLabel = severityLabels[severityUpper] || finding.severity;
    const confidencePct = formatConfidence(finding.confidence);

    const content = `
        <div class="finding-details">
            <div class="mb-16">
                <div class="finding-severity ${severityUpper.toLowerCase()}">${severityLabel} Issue</div>
            </div>

            <h4>What This Means for You</h4>
            <p class="mb-16">${info.impact}</p>

            <h4>Where We Found It</h4>
            <div class="finding-excerpt mb-16">"${finding.excerpt}"</div>

            <h4>More Detail</h4>
            <p class="mb-16">${finding.explanation || 'No additional detail available.'}</p>

            ${confidencePct >= 80 ? `<p class="text-secondary mb-16">How sure we are: ${confidencePct}%</p>` : ''}

            <h4>Privacy Laws This May Violate</h4>
            <div class="mt-8">
                ${(evidence.legal_basis || []).map(basis => `<span class="status status--info">${basis}</span>`).join(' ') || '<span class="text-secondary">None specified</span>'}
            </div>
        </div>
    `;

    showModal(info.label, content);
}

function showVerifyView() {
    if (!currentAnalysis || !currentAnalysis.document_text) {
        showToast('No document text available for verification', 'warning');
        return;
    }
    const numbered = formatVerifyView(
        currentAnalysis.document_text,
        currentAnalysis.findings || []
    );
    const content = `
        <div class="verify-view">
            <p class="text-secondary">Line numbers match evidence references.</p>
            <pre>${numbered}</pre>
        </div>
    `;
    showModal('Verify View', content);
}

function formatVerifyView(text, findings) {
    const ranges = (findings || [])
        .map(f => f.evidence || {})
        .map(e => ({ start: Number(e.line_start), end: Number(e.line_end) }))
        .filter(r => Number.isFinite(r.start) && Number.isFinite(r.end) && r.start > 0 && r.end >= r.start);

    return text.split('\n').map((line, idx) => {
        const lineNumber = idx + 1;
        const numberLabel = String(lineNumber).padStart(4, '0');
        const safeLine = escapeHtml(line);
        const hit = ranges.some(r => lineNumber >= r.start && lineNumber <= r.end);
        const className = hit ? 'verify-line verify-line--hit' : 'verify-line';
        return `<span class="${className}">${numberLabel}| ${safeLine}</span>`;
    }).join('\n');
}

function escapeHtml(text) {
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Comparison Functions
function setupComparison() {
    const compareBtn = document.getElementById('compareBtn');
    compareBtn.addEventListener('click', performComparison);
}

function populateVendorSelectors() {
    const selectors = ['vendor1Select', 'vendor2Select', 'vendor3Select'];
    const vendors = state.analyses.map(analysis => ({
        id: analysis.id,
        name: analysis.name || analysis.source_url || 'Untitled Document'
    }));
    
    selectors.forEach(selectorId => {
        const select = document.getElementById(selectorId);
        if (select) {
            const currentValue = select.value;
            select.innerHTML = '<option value="">Choose vendor...</option>';
            
            vendors.forEach(vendor => {
                const option = document.createElement('option');
                option.value = vendor.id;
                option.textContent = vendor.name;
                if (vendor.id === currentValue) option.selected = true;
                select.appendChild(option);
            });
        }
    });
}

function performComparison() {
    const vendor1 = document.getElementById('vendor1Select').value;
    const vendor2 = document.getElementById('vendor2Select').value;
    const vendor3 = document.getElementById('vendor3Select').value;

    if (!vendor1 || !vendor2) {
        showToast('Please select at least two vendors to compare', 'error');
        return;
    }

    const selectedVendors = [vendor1, vendor2, vendor3].filter(Boolean);
    const comparisonData = selectedVendors
        .map(id => state.analyses.find(d => d.id === id))
        .filter(Boolean);

    displayComparison(comparisonData);
    showToast('Comparison generated', 'success');
}

function displayComparison(data) {
    const resultsContainer = document.getElementById('comparisonResults');

    if (!data.length) {
        resultsContainer.innerHTML = '<p class="text-secondary">No analyses selected.</p>';
        return;
    }
    
    const html = `
        <div class="comparison-table">
            <table>
                <thead>
                    <tr>
                        <th>Metric</th>
                        ${data.map(d => `<th>${d.name || d.source_url || 'Untitled Document'}</th>`).join('')}
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><strong>Risk Score</strong></td>
                        ${data.map(d => `<td><span class="risk-badge ${getRiskClass(d.risk_score)}">${d.risk_score}</span></td>`).join('')}
                    </tr>
                    <tr>
                        <td>Grade</td>
                        ${data.map(d => `<td>${d.grade}</td>`).join('')}
                    </tr>
                    <tr>
                        <td>Confidence</td>
                        ${data.map(d => `<td>${formatConfidence(d.confidence)}%</td>`).join('')}
                    </tr>
                    <tr>
                        <td>Review Required</td>
                        ${data.map(d => `<td>${d.status === 'needs_review' ? 'Yes' : 'No'}</td>`).join('')}
                    </tr>
                    <tr>
                        <td>Analyzed On</td>
                        ${data.map(d => `<td>${formatDate(d.created_at)}</td>`).join('')}
                    </tr>
                </tbody>
            </table>
        </div>
        
        <div class="action-buttons mt-16">
            <button class="btn btn--primary" onclick="exportComparison()">
                <i class="fas fa-download"></i> Export Comparison
            </button>
        </div>
    `;
    
    resultsContainer.innerHTML = html;
}

// Watchlist Functions
function setupWatchlist() {
    const addVendorBtn = document.getElementById('addVendorBtn');
    const statusFilter = document.getElementById('statusFilter');
    
    addVendorBtn.addEventListener('click', showAddVendorModal);
    statusFilter.addEventListener('change', filterWatchlist);
}

function populateWatchlist() {
    const container = document.getElementById('watchlistGrid');
    if (!container) return;

    if (!state.backendOnline) {
        container.innerHTML = '<p class="text-secondary">Backend offline. Start the server to see the watchlist.</p>';
        return;
    }

    if (!state.watchlist.length) {
        container.innerHTML = '<p class="text-secondary">No watchlist items yet</p>';
        return;
    }

    const html = state.watchlist.map(item => {
        const lastChecked = new Date(item.last_checked).toLocaleDateString();
        const statusClass = item.status.toLowerCase().replace(' ', '-');
        
        return `
            <div class="watchlist-card">
                <div class="watchlist-header">
                    <div class="vendor-name">${item.vendor}</div>
                    <div class="status-badge ${statusClass}">${item.status}</div>
                </div>
                <div class="watchlist-meta">
                    <div>Last checked: ${lastChecked}</div>
                    <div>Changes: ${item.change_count}</div>
                    <div>Risk delta: ${item.risk_delta}</div>
                    ${item.change_summary ? `<div>Summary: ${item.change_summary}</div>` : ''}
                </div>
                <div class="action-buttons mt-16">
                    <button class="btn btn--sm btn--secondary" onclick="viewChanges('${item.id}')">
                        <i class="fas fa-eye"></i> View Changes
                    </button>
                    <button class="btn btn--sm btn--secondary" onclick="refreshWatchlistItem('${item.id}')">
                        <i class="fas fa-sync"></i> Refresh
                    </button>
                    <button class="btn btn--sm btn--outline" onclick="removeFromWatchlist('${item.id}')">
                        <i class="fas fa-trash"></i> Remove
                    </button>
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = html;
}

function showAddVendorModal() {
    const content = `
        <form id="addVendorForm">
            <div class="form-group">
                <label class="form-label">Vendor Name</label>
                <input type="text" class="form-control" id="vendorName" placeholder="Enter vendor name" required>
            </div>
            <div class="form-group">
                <label class="form-label">Policy URL</label>
                <input type="url" class="form-control" id="vendorUrl" placeholder="https://example.com/privacy" required>
            </div>
            <div class="form-group">
                <label class="form-label">Check Frequency</label>
                <select class="form-control" id="checkFrequency">
                    <option value="daily">Daily</option>
                    <option value="weekly" selected>Weekly</option>
                    <option value="monthly">Monthly</option>
                </select>
            </div>
            <div class="action-buttons">
                <button type="submit" class="btn btn--primary">Add to Watchlist</button>
                <button type="button" class="btn btn--secondary" onclick="closeModal()">Cancel</button>
            </div>
        </form>
    `;

    showModal('Add Vendor to Watchlist', content);

    document.getElementById('addVendorForm').addEventListener('submit', (e) => {
        e.preventDefault();
        const vendorName = document.getElementById('vendorName').value;
        const vendorUrl = document.getElementById('vendorUrl').value;
        addToWatchlist(vendorName, vendorUrl);
        closeModal();
    });
}

async function addToWatchlist(vendorName, vendorUrl = null) {
    if (!vendorName) {
        showToast('Vendor name is required', 'error');
        return;
    }
    try {
        await fetchJSON('/watchlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vendor: vendorName, source_url: vendorUrl })
        });
        await refreshWatchlist();
        populateWatchlist();
        populateWatchlistAlerts();
        showToast(`${vendorName} added to watchlist`, 'success');
    } catch (error) {
        showToast('Failed to add to watchlist', 'error');
    }
}

function viewChanges(itemId) {
    const item = state.watchlist.find(i => i.id === itemId);
    if (!item) return;

    const content = `
        <div class="change-history">
            <h4>Recent Changes for ${item.vendor}</h4>
            ${item.change_summary ? `<pre>${item.change_summary}</pre>` : '<p class="text-secondary">No change summary available.</p>'}
        </div>
    `;

    showModal('Change History', content);
}

async function refreshWatchlistItem(itemId) {
    if (!itemId) return;
    showLoading('Refreshing watchlist...');
    try {
        await fetchJSON(`/watchlist/${itemId}/refresh`, { method: 'POST' });
        await refreshWatchlist();
        populateWatchlist();
        populateWatchlistAlerts();
        showToast('Watchlist refreshed', 'success');
    } catch (error) {
        showToast('Failed to refresh watchlist', 'error');
    } finally {
        hideLoading();
    }
}

async function removeFromWatchlist(itemId) {
    const item = state.watchlist.find(i => i.id === itemId);
    if (!item) return;
    if (!confirm(`Remove ${item.vendor} from watchlist?`)) return;
    try {
        await fetchJSON(`/watchlist/${itemId}`, { method: 'DELETE' });
        await refreshWatchlist();
        populateWatchlist();
        populateWatchlistAlerts();
        showToast(`${item.vendor} removed from watchlist`, 'success');
    } catch (error) {
        showToast('Failed to remove watchlist item', 'error');
    }
}

function filterWatchlist() {
    const filterValue = document.getElementById('statusFilter').value;
    if (!filterValue) {
        populateWatchlist();
        return;
    }
    const filtered = state.watchlist.filter(item => {
        const normalized = item.status.toLowerCase().replace(' ', '-');
        return normalized === filterValue;
    });
    const container = document.getElementById('watchlistGrid');
    if (!container) return;
    if (!filtered.length) {
        container.innerHTML = '<p class="text-secondary">No watchlist items match that status</p>';
        return;
    }
    const html = filtered.map(item => {
        const lastChecked = new Date(item.last_checked).toLocaleDateString();
        const statusClass = item.status.toLowerCase().replace(' ', '-');
        return `
            <div class="watchlist-card">
                <div class="watchlist-header">
                    <div class="vendor-name">${item.vendor}</div>
                    <div class="status-badge ${statusClass}">${item.status}</div>
                </div>
                <div class="watchlist-meta">
                    <div>Last checked: ${lastChecked}</div>
                    <div>Changes: ${item.change_count}</div>
                    <div>Risk delta: ${item.risk_delta}</div>
                </div>
                <div class="action-buttons mt-16">
                    <button class="btn btn--sm btn--secondary" onclick="viewChanges('${item.id}')">
                        <i class="fas fa-eye"></i> View Changes
                    </button>
                    <button class="btn btn--sm btn--outline" onclick="removeFromWatchlist('${item.id}')">
                        <i class="fas fa-trash"></i> Remove
                    </button>
                </div>
            </div>
        `;
    }).join('');
    container.innerHTML = html;
}

// Reports Functions
function setupReports() {
    // Report generation buttons
    document.addEventListener('click', (e) => {
        if (e.target.closest('[onclick*="generate"]')) {
            const reportType = e.target.textContent.trim();
            generateReport(reportType);
        }
    });
}

function populateRubricScores() {
    const container = document.getElementById('rubricGrid');
    if (!container) return;

    if (!state.backendOnline) {
        container.innerHTML = '<p class="text-secondary">Backend offline. Start the server to load scores.</p>';
        return;
    }

    const totalChecked = state.analyses.length;

    if (!state.rubricScores) {
        container.innerHTML = `
            <p class="text-secondary" style="margin-bottom:12px">
                No policies have been checked yet. Scores will appear after your first analysis.
            </p>`;
        return;
    }

    const RUBRIC_META = {
        overall:               { label: 'Overall Score',            desc: 'Weighted average across all dimensions below.' },
        productIntegrity:      { label: 'Policy Risk Level',        desc: 'How risky the checked policies are on average. Higher = lower average risk score.' },
        legalSignalQuality:    { label: 'AI Detection Confidence',  desc: 'How confident the AI is in its findings. Low when the AI model is offline (pattern-only mode).' },
        privacySecurity:       { label: 'Privacy & Security',       desc: 'Blend of risk level and AI confidence — reflects overall data-safety picture.' },
        accessibilityUsability:{ label: 'Review Workload',          desc: 'How often analyses need human review. Higher = fewer items flagged for manual check.' },
        visualIxd:             { label: 'Clarity of Results',       desc: 'Combines human-review rate with avg risk — proxy for how clear and actionable the outputs are.' },
        performanceReliability:{ label: 'Reliability',              desc: 'How often the tool can complete an analysis without needing manual intervention.' },
        governanceReadiness:   { label: 'Governance Readiness',     desc: 'How close to fully-automated the tool is. Drops when many analyses need human review.' },
    };

    function scoreColor(s) {
        if (s >= 7) return 'var(--color-success)';
        if (s >= 4) return 'var(--color-warning)';
        return 'var(--color-error)';
    }
    function scoreLabel(s) {
        if (s >= 7) return 'Good';
        if (s >= 4) return 'Fair';
        return 'Needs work';
    }

    // Show overall first, then the rest
    const ordered = ['overall', 'productIntegrity', 'legalSignalQuality', 'privacySecurity',
                     'accessibilityUsability', 'visualIxd', 'performanceReliability', 'governanceReadiness'];

    const rows = ordered.map(key => {
        const score = state.rubricScores[key];
        if (score === undefined) return '';
        const meta = RUBRIC_META[key] || { label: key, desc: '' };
        const pct = Math.round((score / 10) * 100);
        const color = scoreColor(score);
        const lbl = scoreLabel(score);
        const isOverall = key === 'overall';
        return `
            <div style="padding:${isOverall ? '14px 12px' : '10px 12px'};border:1px solid var(--color-card-border);border-radius:8px;
                        margin-bottom:8px;${isOverall ? 'background:var(--color-highlight,rgba(15,164,175,0.06))' : ''}">
                <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px">
                    <span style="font-weight:${isOverall ? '700' : '600'};font-size:${isOverall ? '1rem' : '0.9rem'}">${meta.label}</span>
                    <span style="font-weight:700;font-size:${isOverall ? '1.1rem' : '0.95rem'};color:${color}">
                        ${score.toFixed(1)}<span style="font-size:0.75rem;font-weight:400;color:var(--color-text-secondary)">/10</span>
                        <span style="font-size:0.75rem;margin-left:4px">${lbl}</span>
                    </span>
                </div>
                <div style="background:var(--color-border);border-radius:4px;height:6px;margin-bottom:6px;overflow:hidden">
                    <div style="width:${pct}%;height:100%;background:${color};border-radius:4px;transition:width 0.4s"></div>
                </div>
                <div class="text-secondary" style="font-size:0.8rem">${meta.desc}</div>
            </div>
        `;
    }).join('');

    const irpBox = `
        <div style="margin-top:16px;padding:12px 14px;border:1px dashed var(--color-border);border-radius:8px;background:var(--color-surface)">
            <div style="font-weight:600;margin-bottom:6px"><i class="fas fa-calculator"></i> How the Risk Score Is Calculated</div>
            <p style="font-size:0.85rem;margin-bottom:6px">
                Each policy gets an <strong>IRP (Integrated Risk Profile) score</strong> from 0–10:
            </p>
            <code style="font-size:0.82rem;display:block;padding:6px 10px;background:var(--color-secondary);border-radius:4px;margin-bottom:8px">
                Score = 0.5 × (Impact/5) + 0.4 × (Likelihood/5) − 0.3 × (Safeguards/5)
            </code>
            <ul style="font-size:0.82rem;margin:0;padding-left:18px;line-height:1.7">
                <li><strong>Impact (0–5)</strong> — how serious the harm could be if the clause is enforced</li>
                <li><strong>Likelihood (0–5)</strong> — how likely the company is to actually use this clause</li>
                <li><strong>Safeguards (0–5)</strong> — how many protections exist (opt-out, deletion rights, etc.)</li>
            </ul>
            <p style="font-size:0.8rem;margin-top:8px;color:var(--color-text-secondary)">
                Grades: A (0–3) · B (3–5) · C+ (5–7) · C (7–8) · D+ (8–9) · D (9–10)
            </p>
        </div>
    `;

    container.innerHTML = `
        <p class="text-secondary" style="font-size:0.85rem;margin-bottom:14px">
            These scores reflect how our tool is performing across
            <strong>${totalChecked} ${totalChecked === 1 ? 'policy' : 'policies'}</strong> checked so far.
            All scores are on a 0–10 scale — higher is better.
        </p>
        ${rows}
        ${irpBox}
    `;
}

function generateReport(reportType) {
    showLoading('Generating report...');
    
    setTimeout(() => {
        hideLoading();
        showToast(`${reportType} generated successfully`, 'success');
    }, 2000);
}

function exportResults(docId) {
    if (!currentAnalysis || currentAnalysis.id !== docId) {
        showToast('No analysis to export', 'error');
        return;
    }
    const payload = JSON.stringify(currentAnalysis, null, 2);
    const blob = new Blob([payload], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `analysis-${docId}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    showToast('Report exported successfully', 'success');
}

function exportComparison() {
    showToast('Comparison exported successfully', 'success');
}

async function exportReports(format) {
    if (!state.backendOnline) {
        showToast('Backend offline', 'error');
        return;
    }
    try {
        if (format === 'csv') {
            const response = await fetch(`${API_BASE_URL}/exports/analyses.csv`);
            if (!response.ok) throw new Error('CSV export failed');
            const blob = await response.blob();
            downloadBlob(blob, 'analyses.csv');
        } else if (format === 'json' && currentAnalysis) {
            const response = await fetch(`${API_BASE_URL}/exports/analysis/${currentAnalysis.id}`);
            if (!response.ok) throw new Error('JSON export failed');
            const blob = await response.blob();
            downloadBlob(blob, `analysis-${currentAnalysis.id}.json`);
        } else if (format === 'pdf' && currentAnalysis) {
            const response = await fetch(`${API_BASE_URL}/exports/analysis/${currentAnalysis.id}.pdf`);
            if (!response.ok) throw new Error('PDF export failed');
            const blob = await response.blob();
            downloadBlob(blob, `analysis-${currentAnalysis.id}.pdf`);
        } else {
            showToast('Select an analysis to export', 'warning');
            return;
        }
        showToast('Export ready', 'success');
    } catch (error) {
        showToast('Export failed', 'error');
    }
}

function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

// Settings Functions
function setupSettings() {
    const themeSelect = document.getElementById('themeSelect');
    
    if (themeSelect) {
        themeSelect.value = currentTheme;
        themeSelect.addEventListener('change', (e) => {
            applyTheme(e.target.value);
            updateThemeIcon();
            localStorage.setItem('theme', e.target.value);
            showToast('Theme preference saved', 'success');
        });
    }
}

// Utility Functions
function showLoading(message = 'Loading...') {
    const loadingText = document.querySelector('.loading-text');
    if (loadingText) loadingText.textContent = message;
    loadingOverlay.classList.remove('hidden');
}

function hideLoading() {
    loadingOverlay.classList.add('hidden');
}

function getRiskClass(score) {
    if (score >= 8) return 'high';
    if (score >= 6) return 'medium';
    return 'low';
}

function formatDate(dateString) {
    return new Date(dateString).toLocaleDateString();
}

function formatConfidence(value) {
    if (value === null || value === undefined) return 0;
    const numeric = Number(value);
    if (Number.isNaN(numeric)) return 0;
    return numeric <= 1 ? Math.round(numeric * 100) : Math.round(numeric);
}

// Global functions for inline event handlers
window.showFindingDetails = showFindingDetails;
window.exportResults = exportResults;
window.addToWatchlist = addToWatchlist;
window.exportComparison = exportComparison;
window.viewChanges = viewChanges;
window.removeFromWatchlist = removeFromWatchlist;
window.refreshWatchlistItem = refreshWatchlistItem;
window.updateReview = updateReview;
window.exportReports = exportReports;
window.closeModal = closeModal;
window.navigateToDashboardAnalysis = navigateToDashboardAnalysis;
window.navigateToPage = navigateToPage;
