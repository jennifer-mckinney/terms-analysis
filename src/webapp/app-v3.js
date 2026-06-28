// Privacy Helper V3 - Consumer-Friendly Interface
// Warm, hand-holding UX for non-experts

(function() {
  'use strict';
  
  // API Configuration
  const API_BASE = window.location.protocol === 'file:' 
    ? 'http://localhost:8000' 
    : '';

  // ============================================
  // THEME TOGGLE
  // ============================================
  const themeToggle = document.getElementById('themeToggle');
  const html = document.documentElement;
  const sunIcon = themeToggle.querySelector('.sun-icon');
  const moonIcon = themeToggle.querySelector('.moon-icon');
  
  const savedTheme = localStorage.getItem('theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const currentTheme = savedTheme || (prefersDark ? 'dark' : 'light');
  
  function setTheme(theme) {
    html.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    
    if (theme === 'dark') {
      sunIcon.style.display = 'none';
      moonIcon.style.display = 'block';
    } else {
      sunIcon.style.display = 'block';
      moonIcon.style.display = 'none';
    }
  }
  
  setTheme(currentTheme);
  
  themeToggle.addEventListener('click', () => {
    const newTheme = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    setTheme(newTheme);
  });

  // ============================================
  // TABS
  // ============================================
  const tabs = document.querySelectorAll('.tab');
  const tabPanels = document.querySelectorAll('.tab-panel');
  
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const targetId = tab.getAttribute('aria-controls');
      
      // Update tabs
      tabs.forEach(t => {
        t.classList.remove('active');
        t.setAttribute('aria-selected', 'false');
      });
      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');
      
      // Update panels
      tabPanels.forEach(panel => {
        panel.hidden = true;
      });
      document.getElementById(targetId).hidden = false;
    });
  });

  // ============================================
  // FILE UPLOAD
  // ============================================
  const fileInput = document.getElementById('fileInput');
  const fileDropZone = document.getElementById('fileDropZone');
  const fileSelected = document.getElementById('fileSelected');
  const fileName = document.getElementById('fileName');
  
  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      const file = e.target.files[0];
      fileName.textContent = file.name;
      fileSelected.style.display = 'flex';
      fileDropZone.querySelector('.file-drop-content').style.display = 'none';
    }
  });
  
  // Drag and drop
  fileDropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    fileDropZone.style.borderColor = 'var(--color-teal-mid)';
    fileDropZone.style.background = 'var(--color-teal-pale)';
  });
  
  fileDropZone.addEventListener('dragleave', () => {
    fileDropZone.style.borderColor = '';
    fileDropZone.style.background = '';
  });
  
  fileDropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    fileDropZone.style.borderColor = '';
    fileDropZone.style.background = '';
    
    if (e.dataTransfer.files.length > 0) {
      fileInput.files = e.dataTransfer.files;
      const file = e.dataTransfer.files[0];
      fileName.textContent = file.name;
      fileSelected.style.display = 'flex';
      fileDropZone.querySelector('.file-drop-content').style.display = 'none';
    }
  });

  // ============================================
  // ANALYZE BUTTON
  // ============================================
  const analyzeBtn = document.getElementById('analyzeBtn');
  const resultsSection = document.getElementById('resultsSection');
  const resultsIntro = document.getElementById('resultsIntro');
  const resultsSummary = document.getElementById('resultsSummary');
  const resultsList = document.getElementById('resultsList');
  
  analyzeBtn.addEventListener('click', async () => {
    // Get active tab
    const activeTab = document.querySelector('.tab.active');
    const activeTabId = activeTab.getAttribute('aria-controls');
    
    // Get form values
    const mode = document.querySelector('input[name="mode"]:checked').value;
    const jurisdiction = document.getElementById('jurisdiction').value;
    const industry = document.getElementById('industry').value;
    
    let requestData = {
      mode: mode,
      jurisdictions: jurisdiction ? [jurisdiction] : ['US-CA', 'GDPR'],
      industry: industry || 'General'
    };
    
    let endpoint = '';
    let text = '';
    
    // Determine which input method
    if (activeTabId === 'tab-paste') {
      text = document.getElementById('textInput').value.trim();
      if (!text) {
        alert('Please paste some text to analyze');
        return;
      }
      endpoint = `${API_BASE}/analyze`;
      requestData.text = text;
      requestData.doc_type = 'Privacy Policy'; // Default
    } else if (activeTabId === 'tab-url') {
      const url = document.getElementById('urlInput').value.trim();
      if (!url) {
        alert('Please enter a website URL');
        return;
      }
      endpoint = `${API_BASE}/analyze/url`;
      requestData.url = url;
    } else if (activeTabId === 'tab-file') {
      if (!fileInput.files || fileInput.files.length === 0) {
        alert('Please select a file to analyze');
        return;
      }
      endpoint = `${API_BASE}/analyze/file`;
      const formData = new FormData();
      formData.append('file', fileInput.files[0]);
      formData.append('mode', mode);
      if (jurisdiction) formData.append('jurisdictions', jurisdiction);
      if (industry) formData.append('industry', industry);
      
      // File upload uses FormData instead of JSON
      await analyzeFile(endpoint, formData);
      return;
    }
    
    // Show loading state
    analyzeBtn.textContent = 'Analyzing...';
    analyzeBtn.disabled = true;
    
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestData)
      });
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const result = await response.json();
      displayResults(result);
      
    } catch (error) {
      console.error('Analysis error:', error);
      alert('Something went wrong while analyzing. Please check that the backend server is running on localhost:8000');
    } finally {
      analyzeBtn.textContent = 'Check this document';
      analyzeBtn.disabled = false;
    }
  });
  
  async function analyzeFile(endpoint, formData) {
    analyzeBtn.textContent = 'Analyzing...';
    analyzeBtn.disabled = true;
    
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        body: formData
      });
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const result = await response.json();
      displayResults(result);
      
    } catch (error) {
      console.error('Analysis error:', error);
      alert('Something went wrong while analyzing. Please check that the backend server is running on localhost:8000');
    } finally {
      analyzeBtn.textContent = 'Check this document';
      analyzeBtn.disabled = false;
    }
  }
  
  function displayResults(result) {
    // Show results section
    resultsSection.style.display = 'block';
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    
    // Update intro based on findings count
    const findingsCount = result.findings ? result.findings.length : 0;
    const mode = result.analysis_mode || 'full';
    
    if (findingsCount === 0) {
      resultsIntro.textContent = "Great news! We didn't find any major concerns in this document.";
    } else {
      const modeText = mode === 'quick' ? 'most important issues' : 'everything we found';
      resultsIntro.textContent = `We found ${findingsCount} thing${findingsCount !== 1 ? 's' : ''} worth knowing about. Here's ${modeText}:`;
    }
    
    // Build summary
    buildSummary(result);
    
    // Build findings list
    buildFindingsList(result);
  }
  
  function buildSummary(result) {
    const findings = result.findings || [];
    const severityCounts = {
      Critical: 0,
      High: 0,
      Medium: 0,
      Low: 0
    };
    
    findings.forEach(f => {
      if (severityCounts.hasOwnProperty(f.severity)) {
        severityCounts[f.severity]++;
      }
    });
    
    const summaryHTML = `
      <div class="summary-card">
        <div class="summary-severity critical">
          <div class="summary-number">${severityCounts.Critical}</div>
          <div class="summary-label">Critical</div>
        </div>
      </div>
      <div class="summary-card">
        <div class="summary-severity high">
          <div class="summary-number">${severityCounts.High}</div>
          <div class="summary-label">High Priority</div>
        </div>
      </div>
      <div class="summary-card">
        <div class="summary-severity medium">
          <div class="summary-number">${severityCounts.Medium}</div>
          <div class="summary-label">Medium</div>
        </div>
      </div>
      <div class="summary-card">
        <div class="summary-severity low">
          <div class="summary-number">${severityCounts.Low}</div>
          <div class="summary-label">Low Priority</div>
        </div>
      </div>
    `;
    
    resultsSummary.innerHTML = summaryHTML;
    
    // Add summary card styles if not already present
    if (!document.getElementById('summary-styles')) {
      const style = document.createElement('style');
      style.id = 'summary-styles';
      style.textContent = `
        .summary-card {
          background: var(--color-bg-card);
          border: 1px solid var(--color-border-light);
          border-radius: var(--radius-lg);
          padding: var(--space-lg);
          text-align: center;
        }
        .summary-severity {
          display: flex;
          flex-direction: column;
          gap: var(--space-xs);
        }
        .summary-number {
          font-size: var(--text-3xl);
          font-weight: var(--font-semibold);
        }
        .summary-label {
          font-size: var(--text-sm);
          color: var(--color-text-secondary);
        }
        .summary-severity.critical .summary-number { color: oklch(0.52 0.18 25); }
        .summary-severity.high .summary-number { color: var(--color-terracotta); }
        .summary-severity.medium .summary-number { color: var(--color-warning); }
        .summary-severity.low .summary-number { color: var(--color-text-muted); }
        
        .finding-card {
          background: var(--color-bg-card);
          border: 1px solid var(--color-border-light);
          border-radius: var(--radius-md);
          padding: var(--space-xl);
        }
        .finding-card.critical { background: oklch(0.98 0.02 25); border-color: oklch(0.88 0.04 25); }
        .finding-card.high { background: oklch(0.98 0.015 35); border-color: oklch(0.88 0.03 35); }
        .finding-card.medium { background: var(--color-bg-card); }
        .finding-card.low { background: var(--color-bg-card); }
        
        .finding-header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: var(--space-md);
          margin-bottom: var(--space-md);
        }
        .finding-title {
          font-size: var(--text-lg);
          font-weight: var(--font-semibold);
          color: var(--color-text-primary);
          margin: 0;
        }
        .finding-badges {
          display: flex;
          gap: var(--space-xs);
          flex-shrink: 0;
        }
        .badge {
          padding: 0.25rem 0.625rem;
          font-size: var(--text-xs);
          font-weight: var(--font-medium);
          border-radius: var(--radius-sm);
        }
        .badge-severity {
          background: var(--color-teal-pale);
          color: var(--color-teal-dark);
        }
        .badge-confidence {
          background: var(--color-bg-elevated);
          border: 1px solid var(--color-border-mid);
          color: var(--color-text-primary);
        }
        .badge-confidence.high { background: oklch(0.93 0.08 145); color: oklch(0.35 0.15 145); }
        .badge-confidence.medium { background: oklch(0.95 0.08 75); color: oklch(0.45 0.15 75); }
        .badge-confidence.low { background: oklch(0.94 0.08 35); color: oklch(0.42 0.15 35); }
        
        .finding-excerpt {
          background: var(--color-bg-elevated);
          border: 1px solid var(--color-border-light);
          padding: var(--space-md);
          margin: var(--space-md) 0;
          font-size: var(--text-sm);
          color: var(--color-text-secondary);
          font-style: italic;
          border-radius: var(--radius-sm);
        }
        .finding-explanation {
          font-size: var(--text-base);
          line-height: 1.7;
          color: var(--color-text-primary);
          margin-bottom: var(--space-md);
        }
        .finding-meta {
          font-size: var(--text-sm);
          color: var(--color-text-muted);
        }
      `;
      document.head.appendChild(style);
    }
  }
  
  function buildFindingsList(result) {
    const findings = result.findings || [];
    
    if (findings.length === 0) {
      resultsList.innerHTML = '<p style="color: var(--color-text-secondary); text-align: center;">No findings to display</p>';
      return;
    }
    
    const findingsHTML = findings.map(f => {
      const confidencePercent = Math.round((f.confidence || 0) * 100);
      let confidenceClass = 'low';
      if (confidencePercent >= 95) confidenceClass = 'high';
      else if (confidencePercent >= 70) confidenceClass = 'medium';
      
      const severityLower = (f.severity || 'low').toLowerCase();
      
      return `
        <div class="finding-card ${severityLower}">
          <div class="finding-header">
            <h3 class="finding-title">${f.category || 'Finding'}</h3>
            <div class="finding-badges">
              <span class="badge badge-severity">${f.severity || 'Low'}</span>
              <span class="badge badge-confidence ${confidenceClass}" title="${confidencePercent}% confident">
                ${confidencePercent}%
              </span>
            </div>
          </div>
          
          ${f.excerpt ? `<div class="finding-excerpt">"${escapeHtml(f.excerpt)}"</div>` : ''}
          
          <p class="finding-explanation">${escapeHtml(f.explanation || 'No explanation available')}</p>
          
          <div class="finding-meta">
            Lines ${f.evidence?.line_start || '?'}–${f.evidence?.line_end || '?'}
            ${f.jurisdictions && f.jurisdictions.length > 0 ? ` • Jurisdictions: ${f.jurisdictions.join(', ')}` : ''}
          </div>
        </div>
      `;
    }).join('');
    
    resultsList.innerHTML = findingsHTML;
  }
  
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

})();
