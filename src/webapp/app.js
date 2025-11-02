// Terms & Policies Reviewer Application JavaScript

// Application Data
const appData = {
  "sampleDocuments": [
    {
      "id": "doc1",
      "name": "TechCorp Privacy Policy",
      "type": "Privacy Policy",
      "url": "https://techcorp.com/privacy",
      "riskScore": 7.2,
      "grade": "C+",
      "lastAnalyzed": "2025-09-07T15:30:00Z",
      "findings": [
        {
          "category": "Data Collection",
          "severity": "Medium",
          "confidence": 87,
          "excerpt": "We collect personal information including browsing behavior, device identifiers, and location data for advertising purposes.",
          "explanation": "Broad data collection for advertising may require explicit consent under GDPR and clear opt-out mechanisms under CCPA.",
          "jurisdiction": ["US", "EU"],
          "page": 3,
          "section": "Data We Collect"
        },
        {
          "category": "Third-Party Sharing",
          "severity": "High",
          "confidence": 92,
          "excerpt": "We may share your personal information with our business partners, affiliates, and service providers for their own business purposes.",
          "explanation": "Sharing for partners' own purposes may constitute a 'sale' under CCPA, requiring disclosure and opt-out rights.",
          "jurisdiction": ["US"],
          "page": 5,
          "section": "Information Sharing"
        }
      ]
    },
    {
      "id": "doc2",
      "name": "DataFlow Terms of Service",
      "type": "Terms of Service",
      "url": "https://dataflow.com/terms",
      "riskScore": 8.7,
      "grade": "D+",
      "lastAnalyzed": "2025-09-06T09:15:00Z",
      "findings": [
        {
          "category": "Arbitration",
          "severity": "Critical",
          "confidence": 95,
          "excerpt": "Any dispute arising from this agreement must be resolved through binding arbitration and you waive your right to participate in class action lawsuits.",
          "explanation": "Mandatory arbitration with class action waiver significantly limits user rights to seek legal remedies.",
          "jurisdiction": ["US"],
          "page": 12,
          "section": "Dispute Resolution"
        },
        {
          "category": "Unilateral Changes",
          "severity": "Medium",
          "confidence": 84,
          "excerpt": "We reserve the right to modify these terms at any time without prior notice. Continued use constitutes acceptance.",
          "explanation": "Unilateral change rights without notice period may be unenforceable in some jurisdictions and unfair to users.",
          "jurisdiction": ["US", "EU", "UK"],
          "page": 15,
          "section": "Term Modifications"
        }
      ]
    }
  ],
  "watchlistItems": [
    {
      "id": "w1",
      "vendor": "TechCorp",
      "lastChecked": "2025-09-08T02:00:00Z",
      "status": "Updated",
      "changesSince": "2025-09-01T00:00:00Z",
      "changeCount": 3,
      "riskDelta": "+0.4"
    },
    {
      "id": "w2",
      "vendor": "DataFlow",
      "lastChecked": "2025-09-08T01:30:00Z",
      "status": "No Changes",
      "changesSince": "2025-08-15T00:00:00Z",
      "changeCount": 0,
      "riskDelta": "0"
    }
  ],
  "rubricScores": {
    "productIntegrity": 4.2,
    "legalSignalQuality": 4.1,
    "privacySecurity": 4.5,
    "accessibilityUsability": 3.8,
    "visualIxd": 4.0,
    "performanceReliability": 4.3,
    "governanceReadiness": 3.9,
    "overall": 4.11
  },
  "jurisdictionCompliance": {
    "US": {
      "ccpa": { "score": 6.5, "issues": ["No clear sale definition", "Opt-out process unclear"] },
      "cpra": { "score": 5.8, "issues": ["Sensitive data handling", "Third-party contracts"] }
    },
    "EU": {
      "gdpr": { "score": 7.2, "issues": ["Lawful basis unclear", "Data transfer mechanisms"] }
    },
    "UK": {
      "ukGdpr": { "score": 7.0, "issues": ["International transfers", "Retention periods"] }
    },
    "Canada": {
      "pipeda": { "score": 8.1, "issues": ["Consent model"] },
      "quebec": { "score": 6.9, "issues": ["Law 25 triggers", "Privacy officer contact"] }
    }
  },
  "comparisonData": [
    {
      "vendor": "TechCorp",
      "riskScore": 7.2,
      "arbitration": "Yes",
      "classAction": "Waived",
      "dataRetention": "Indefinite",
      "thirdPartySharing": "Yes",
      "jurisdiction": "Delaware"
    },
    {
      "vendor": "DataFlow",
      "riskScore": 8.7,
      "arbitration": "Yes",
      "classAction": "Waived",
      "dataRetention": "2 years",
      "thirdPartySharing": "Limited",
      "jurisdiction": "California"
    },
    {
      "vendor": "SafeGuard",
      "riskScore": 4.3,
      "arbitration": "Optional",
      "classAction": "Allowed",
      "dataRetention": "1 year",
      "thirdPartySharing": "No",
      "jurisdiction": "New York"
    }
  ]
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

function initializeApp() {
    setupNavigation();
    setupThemeToggle();
    setupModalHandlers();
    setupDocumentReview();
    setupComparison();
    setupWatchlist();
    setupReports();
    setupSettings();
    populateDashboard();
    
    // Set initial theme
    applyTheme(getPreferredTheme());
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
            break;
    }
}

function handleQuickAction(action) {
    switch (action) {
        case 'new-review':
            navigateToPage('review');
            break;
        case 'compare':
            navigateToPage('compare');
            break;
        case 'export':
            navigateToPage('reports');
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

// Dashboard Functions
function populateDashboard() {
    populateRecentAnalysis();
    populateWatchlistAlerts();
}

function populateRecentAnalysis() {
    const container = document.getElementById('recentAnalysis');
    if (!container) return;

    const html = appData.sampleDocuments.map(doc => {
        const date = new Date(doc.lastAnalyzed).toLocaleDateString();
        const riskClass = getRiskClass(doc.riskScore);
        
        return `
            <div class="analysis-item">
                <div class="analysis-meta">
                    <div class="analysis-name">${doc.name}</div>
                    <div class="analysis-date">Analyzed ${date}</div>
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

    const updatedItems = appData.watchlistItems.filter(item => item.status === 'Updated');
    
    const html = updatedItems.map(item => {
        return `
            <div class="analysis-item">
                <div class="analysis-meta">
                    <div class="analysis-name">${item.vendor}</div>
                    <div class="analysis-date">${item.changeCount} changes detected</div>
                </div>
                <div class="risk-badge medium">+${item.riskDelta}</div>
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

function startAnalysis() {
    const documentUrl = document.getElementById('documentUrl').value;
    const documentText = document.getElementById('documentText').value;
    const fileInput = document.getElementById('fileInput');
    const analysisMode = document.querySelector('input[name="analysisMode"]:checked').value;

    // Validate input
    if (!documentUrl && !documentText && fileInput.files.length === 0) {
        showToast('Please provide a document URL, upload a file, or paste text', 'error');
        return;
    }

    // Show loading
    showLoading('Analyzing document...');

    // Simulate analysis delay
    setTimeout(() => {
        hideLoading();
        
        // Use sample document for demo
        const sampleDoc = appData.sampleDocuments[0];
        displayAnalysisResults(sampleDoc, analysisMode);
        showToast('Analysis complete', 'success');
    }, 3000);
}

function displayAnalysisResults(doc, mode) {
    const resultsSection = document.getElementById('resultsSection');
    
    const html = `
        <div class="results-header">
            <div>
                <h3>${doc.name}</h3>
                <p class="text-secondary">${doc.type} • Analyzed ${new Date(doc.lastAnalyzed).toLocaleDateString()}</p>
            </div>
            <div class="risk-score">
                <div class="risk-score-value">${doc.riskScore}</div>
                <div class="risk-grade">Grade ${doc.grade}</div>
            </div>
        </div>
        
        <div class="findings-list">
            ${doc.findings.map(finding => createFindingHTML(finding)).join('')}
        </div>
        
        <div class="jurisdiction-summary mt-16">
            <h4>Jurisdiction Analysis</h4>
            ${createJurisdictionSummary(doc.findings)}
        </div>
        
        <div class="action-buttons mt-16">
            <button class="btn btn--primary" onclick="exportResults('${doc.id}')">
                <i class="fas fa-download"></i> Export Report
            </button>
            <button class="btn btn--secondary" onclick="addToWatchlist('${doc.name}')">
                <i class="fas fa-eye"></i> Add to Watchlist
            </button>
        </div>
    `;
    
    resultsSection.innerHTML = html;
    currentAnalysis = doc;
}

function createFindingHTML(finding) {
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
                    <div class="confidence-fill" style="width: ${finding.confidence}%"></div>
                </div>
                <span>${finding.confidence}%</span>
            </div>
        </div>
    `;
}

function createJurisdictionSummary(findings) {
    const jurisdictions = [...new Set(findings.flatMap(f => f.jurisdiction))];
    return jurisdictions.map(j => `<span class="status status--info">${j}</span>`).join(' ');
}

function showFindingDetails(category) {
    const finding = currentAnalysis.findings.find(f => f.category === category);
    if (!finding) return;

    const content = `
        <div class="finding-details">
            <div class="mb-16">
                <div class="finding-severity ${finding.severity.toLowerCase()}">${finding.severity} Risk</div>
                <div class="text-secondary">Confidence: ${finding.confidence}%</div>
            </div>
            
            <h4>Evidence</h4>
            <div class="finding-excerpt mb-16">"${finding.excerpt}"</div>
            
            <h4>Explanation</h4>
            <p class="mb-16">${finding.explanation}</p>
            
            <h4>Location</h4>
            <p class="text-secondary">Page ${finding.page} • Section: ${finding.section}</p>
            
            <h4>Jurisdictions</h4>
            <div class="mt-8">
                ${finding.jurisdiction.map(j => `<span class="status status--info">${j}</span>`).join(' ')}
            </div>
        </div>
    `;

    showModal(`Finding: ${category}`, content);
}

// Comparison Functions
function setupComparison() {
    const compareBtn = document.getElementById('compareBtn');
    compareBtn.addEventListener('click', performComparison);
}

function populateVendorSelectors() {
    const selectors = ['vendor1Select', 'vendor2Select', 'vendor3Select'];
    const vendors = appData.comparisonData.map(v => v.vendor);
    
    selectors.forEach(selectorId => {
        const select = document.getElementById(selectorId);
        if (select) {
            const currentValue = select.value;
            select.innerHTML = '<option value="">Choose vendor...</option>';
            
            vendors.forEach(vendor => {
                const option = document.createElement('option');
                option.value = vendor;
                option.textContent = vendor;
                if (vendor === currentValue) option.selected = true;
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
    const comparisonData = selectedVendors.map(vendor => 
        appData.comparisonData.find(d => d.vendor === vendor)
    );

    displayComparison(comparisonData);
    showToast('Comparison generated', 'success');
}

function displayComparison(data) {
    const resultsContainer = document.getElementById('comparisonResults');
    
    const html = `
        <div class="comparison-table">
            <table>
                <thead>
                    <tr>
                        <th>Metric</th>
                        ${data.map(d => `<th>${d.vendor}</th>`).join('')}
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><strong>Risk Score</strong></td>
                        ${data.map(d => `<td><span class="risk-badge ${getRiskClass(d.riskScore)}">${d.riskScore}</span></td>`).join('')}
                    </tr>
                    <tr>
                        <td>Arbitration Clause</td>
                        ${data.map(d => `<td>${d.arbitration}</td>`).join('')}
                    </tr>
                    <tr>
                        <td>Class Action Rights</td>
                        ${data.map(d => `<td>${d.classAction}</td>`).join('')}
                    </tr>
                    <tr>
                        <td>Data Retention</td>
                        ${data.map(d => `<td>${d.dataRetention}</td>`).join('')}
                    </tr>
                    <tr>
                        <td>Third-Party Sharing</td>
                        ${data.map(d => `<td>${d.thirdPartySharing}</td>`).join('')}
                    </tr>
                    <tr>
                        <td>Jurisdiction</td>
                        ${data.map(d => `<td>${d.jurisdiction}</td>`).join('')}
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

    const html = appData.watchlistItems.map(item => {
        const lastChecked = new Date(item.lastChecked).toLocaleDateString();
        
        return `
            <div class="watchlist-card">
                <div class="watchlist-header">
                    <div class="vendor-name">${item.vendor}</div>
                    <div class="status-badge ${item.status.toLowerCase().replace(' ', '-')}">${item.status}</div>
                </div>
                <div class="watchlist-meta">
                    <div>Last checked: ${lastChecked}</div>
                    <div>Changes: ${item.changeCount}</div>
                    <div>Risk delta: ${item.riskDelta}</div>
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
        addToWatchlist(vendorName);
        closeModal();
    });
}

function addToWatchlist(vendorName) {
    // Simulate adding to watchlist
    showToast(`${vendorName} added to watchlist`, 'success');
}

function viewChanges(itemId) {
    const item = appData.watchlistItems.find(i => i.id === itemId);
    if (!item) return;

    const content = `
        <div class="change-history">
            <h4>Recent Changes for ${item.vendor}</h4>
            <div class="change-item">
                <div class="change-date">September 5, 2025</div>
                <div class="change-desc">Privacy policy updated - new data collection practices</div>
                <div class="change-impact">Risk impact: +0.2</div>
            </div>
            <div class="change-item">
                <div class="change-date">September 3, 2025</div>
                <div class="change-desc">Terms of service modified - arbitration clause added</div>
                <div class="change-impact">Risk impact: +0.2</div>
            </div>
        </div>
    `;

    showModal('Change History', content);
}

function removeFromWatchlist(itemId) {
    const item = appData.watchlistItems.find(i => i.id === itemId);
    if (item && confirm(`Remove ${item.vendor} from watchlist?`)) {
        showToast(`${item.vendor} removed from watchlist`, 'success');
        populateWatchlist();
    }
}

function filterWatchlist() {
    const filterValue = document.getElementById('statusFilter').value;
    // Implementation would filter the watchlist items
    showToast(`Filtered by: ${filterValue || 'All'}`, 'info');
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

    const html = Object.entries(appData.rubricScores).map(([key, score]) => {
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
    showToast('Report exported successfully', 'success');
}

function exportComparison() {
    showToast('Comparison exported successfully', 'success');
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

// Global functions for inline event handlers
window.showFindingDetails = showFindingDetails;
window.exportResults = exportResults;
window.addToWatchlist = addToWatchlist;
window.exportComparison = exportComparison;
window.viewChanges = viewChanges;
window.removeFromWatchlist = removeFromWatchlist;
window.closeModal = closeModal;