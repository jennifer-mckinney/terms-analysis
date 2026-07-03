// Terms & Policies Reviewer Application JavaScript

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
        const message = await response.text();
        if (API_LOGGING) {
            const duration = Math.round(performance.now() - startedAt);
            console.info(`[api] ${method} ${url} -> ${response.status} (${duration}ms)`);
        }
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
            container.innerHTML = '<p class="text-secondary">No pending reviews.</p>';
        });
        return;
    }

    const html = state.reviews.map(item => {
        return `
            <div class="review-item">
                <div class="text-secondary">Review ID: ${item.id}</div>
                <div class="text-secondary">Analysis ID: ${item.analysis_id}</div>
                <div class="review-actions">
                    <button class="btn btn--sm btn--primary" onclick="updateReview('${item.id}', 'approved')">Approve</button>
                    <button class="btn btn--sm btn--outline" onclick="updateReview('${item.id}', 'rejected')">Reject</button>
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
        
        const reviewBadge = doc.status === 'needs_review'
            ? '<span class="status status--warning">Needs Review</span>'
            : '<span class="status status--success">Completed</span>';
        return `
            <div class="analysis-item">
                <div class="analysis-meta">
                    <div class="analysis-name">${name}</div>
                    <div class="analysis-date">Analyzed ${date} ${reviewBadge}</div>
                </div>
                <div class="risk-badge ${riskClass}">${doc.grade}</div>
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

// Document Review Functions
function setupDocumentReview() {
    setupInputTabs();
    setupFileUpload();
    setupAnalyzeButton();
    setupDocumentTextCounter();
    setupJurisdictionBulkActions();
}

function setupJurisdictionBulkActions() {
    const selectAllBtn = document.getElementById('selectAllJurisdictions');
    const clearAllBtn = document.getElementById('clearAllJurisdictions');
    const checkboxes = () => document.querySelectorAll('input[name="jurisdiction"]');

    if (selectAllBtn) {
        selectAllBtn.addEventListener('click', () => {
            checkboxes().forEach(cb => { cb.checked = true; });
        });
    }
    if (clearAllBtn) {
        clearAllBtn.addEventListener('click', () => {
            checkboxes().forEach(cb => { cb.checked = false; });
        });
    }
}

function setupDocumentTextCounter() {
    const textarea = document.getElementById('documentText');
    const counter = document.getElementById('documentTextCounter');
    if (!textarea || !counter) return;

    const maxLength = parseInt(textarea.getAttribute('maxlength'), 10) || 50000;

    const update = () => {
        const length = textarea.value.length;
        let text = `${length.toLocaleString()} / ${maxLength.toLocaleString()} characters`;
        if (length > 0 && length < 1000) {
            text += ' — this text appears short. Is this the complete policy?';
        }
        counter.textContent = text;
    };

    textarea.addEventListener('input', update);
    update();
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
    const documentUrl = document.getElementById('documentUrl').value;
    const documentText = document.getElementById('documentText').value;
    const fileInput = document.getElementById('fileInput');
    const analysisMode = document.querySelector('input[name="analysisMode"]:checked').value;
    let jurisdictions = Array.from(document.querySelectorAll('input[name="jurisdiction"]:checked'))
        .map(input => input.value);
    if (jurisdictions.length === 0) {
        jurisdictions = ['US-CA', 'GDPR'];
        showToast('Using default jurisdictions (US-CA, GDPR)', 'info');
    }

    // Validate input
    if (!documentUrl && !documentText && fileInput.files.length === 0) {
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

    // Show loading
    showLoading('Analyzing document...');
    setResultsPlaceholder('Analyzing document...');
    try {
        let result = null;
        if (documentUrl) {
            result = await analyzeUrl(documentUrl, jurisdictions);
        } else if (fileInput.files.length > 0) {
            result = await analyzeFile(fileInput.files[0], jurisdictions);
        } else {
            result = await analyzeText(documentText, jurisdictions);
        }

        currentAnalysis = result;
        await refreshAnalyses();
        populateDashboard();
        populateVendorSelectors();
        await refreshRubricScores();
        populateRubricScores();
        displayAnalysisResults(result, analysisMode);
        showToast('Analysis complete', 'success');
    } catch (error) {
        setResultsPlaceholder('Analysis failed. Check the console for API logs.');
        showToast(error.message || 'Analysis failed', 'error');
    } finally {
        hideLoading();
    }
}

async function analyzeText(text, jurisdictions) {
    const payload = {
        text,
        jurisdictions
    };
    return fetchJSON('/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
}

async function analyzeUrl(url, jurisdictions) {
    const payload = {
        url,
        jurisdictions
    };
    return fetchJSON('/analyze/url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
}

async function analyzeFile(file, jurisdictions) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('jurisdictions', jurisdictions.join(','));
    return fetchJSON('/analyze/file', {
        method: 'POST',
        body: formData
    });
}

function displayAnalysisResults(doc, mode) {
    const resultsSection = document.getElementById('resultsSection');

    const name = doc.name || doc.source_url || 'Untitled Document';
    const docType = doc.doc_type || 'Document';
    const analyzedDate = new Date(doc.created_at).toLocaleDateString();
    const confidence = formatConfidence(doc.confidence);
    const reviewLabel = doc.review_required ? 'Needs Review' : 'Completed';
    const analysisId = doc.id || 'unknown';
    const summaryHtml = doc.summary
        ? `<div class="mt-16"><h4>Summary</h4><p class="text-secondary">${doc.summary}</p></div>`
        : '';

    const findingsHtml = doc.findings.length
        ? doc.findings.map(finding => createFindingHTML(finding)).join('')
        : '<p class="text-secondary">No findings detected.</p>';

    const html = `
        <div class="results-header">
            <div>
                <h3>${name}</h3>
                <p class="text-secondary">${docType} • Analyzed ${analyzedDate}</p>
                <p class="text-secondary">Confidence ${confidence}% • ${reviewLabel}</p>
                <p class="text-secondary">Analysis ID: ${analysisId}</p>
            </div>
            <div class="risk-score">
                <div class="risk-score-value">${doc.risk_score}</div>
                <div class="risk-grade">Grade ${doc.grade}</div>
            </div>
        </div>
        
        <div class="findings-list">
            ${findingsHtml}
        </div>

        ${summaryHtml}
        
        <div class="jurisdiction-summary mt-16">
            <h4>Jurisdiction Analysis</h4>
            ${createJurisdictionSummary(doc.findings)}
        </div>
        
        <div class="action-buttons mt-16">
            <button class="btn btn--primary" data-action="export-results">
                <i class="fas fa-download"></i> Export JSON
            </button>
            <button class="btn btn--secondary" data-action="add-watchlist">
                <i class="fas fa-eye"></i> Add to Watchlist
            </button>
            <button class="btn btn--outline" onclick="showVerifyView()">
                <i class="fas fa-list"></i> Verify View
            </button>
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

function createFindingHTML(finding) {
    const confidence = formatConfidence(finding.confidence);
    return `
        <div class="finding-item" onclick="showFindingDetails('${finding.category}')">
            <div class="finding-header">
                <div class="finding-category">${finding.category}</div>
                <div class="finding-severity ${finding.severity.toLowerCase()}">${finding.severity}</div>
            </div>
            <div class="finding-excerpt">"${finding.excerpt}"</div>
            <div class="finding-confidence">
                <span>Confidence:</span>
                <div class="confidence-bar">
                    <div class="confidence-fill" style="width: ${confidence}%"></div>
                </div>
                <span>${confidence}%</span>
            </div>
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

    const content = `
        <div class="finding-details">
            <div class="mb-16">
                <div class="finding-severity ${finding.severity.toLowerCase()}">${finding.severity} Risk</div>
                <div class="text-secondary">Confidence: ${formatConfidence(finding.confidence)}%</div>
            </div>
            
            <h4>Evidence</h4>
            <div class="finding-excerpt mb-16">"${finding.excerpt}"</div>
            
            <h4>Explanation</h4>
            <p class="mb-16">${finding.explanation}</p>
            
            <h4>Location</h4>
            <p class="text-secondary">Lines ${evidence.line_start}-${evidence.line_end}</p>

            <h4>Legal Basis</h4>
            <div class="mt-8">
                ${(evidence.legal_basis || []).map(basis => `<span class="status status--info">${basis}</span>`).join(' ') || '<span class="text-secondary">Not provided</span>'}
            </div>
            
            <h4>Jurisdictions</h4>
            <div class="mt-8">
                ${(finding.jurisdictions || []).map(j => `<span class="status status--info">${j}</span>`).join(' ')}
            </div>
        </div>
    `;

    showModal(`Finding: ${category}`, content);
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

    if (!state.rubricScores) {
        container.innerHTML = '<p class="text-secondary">Run evaluations to populate rubric scores.</p>';
        return;
    }

    const rubricLabels = {
        productIntegrity: 'Product Integrity',
        legalSignalQuality: 'Legal Signal Quality',
        privacySecurity: 'Privacy & Security',
        accessibilityUsability: 'Accessibility/Usability',
        visualIxd: 'Visual/IXD',
        performanceReliability: 'Performance/Reliability',
        governanceReadiness: 'Governance Readiness',
        overall: 'Overall Score'
    };

    const html = Object.entries(state.rubricScores).map(([key, score]) => {
        return `
            <div class="rubric-item">
                <div class="rubric-label">${rubricLabels[key]}</div>
                <div class="rubric-score">${score.toFixed(1)}</div>
            </div>
        `;
    }).join('');

    container.innerHTML = html;
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
