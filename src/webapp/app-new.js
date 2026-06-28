// Privacy Check - Modern Consumer-Friendly Interface
// Enhanced with legal disclaimers, confidence scoring, and progressive disclosure

(function() {
  'use strict';
  
  // === API CONFIGURATION ===
  const API_BASE = window.location.protocol === 'file:' 
    ? 'http://localhost:8000' 
    : '';

  // === LEGAL DISCLAIMER MODAL ===
  
  function showLegalModal() {
    const modal = document.getElementById('legalModal');
    const confirmed = localStorage.getItem('legalDisclaimerConfirmed');
    
    if (!confirmed) {
      modal.setAttribute('aria-hidden', 'false');
    }
  }

  const legalModalConfirm = document.getElementById('legalModalConfirm');
  if (legalModalConfirm) {
    legalModalConfirm.addEventListener('click', () => {
      localStorage.setItem('legalDisclaimerConfirmed', 'true');
      dismissModal('legalModal');
    });
  }

  // === MODAL MANAGEMENT ===

  function dismissModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
      modal.setAttribute('aria-hidden', 'true');
    }
  }

  const modalCloseButtons = document.querySelectorAll('[data-dismiss]');
  modalCloseButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const modalId = btn.getAttribute('data-dismiss');
      dismissModal(modalId);
    });
  });

  // Close modal on overlay click
  document.querySelectorAll('.modal').forEach(modal => {
    const overlay = modal.querySelector('.modal-overlay');
    if (overlay) {
      overlay.addEventListener('click', () => {
        dismissModal(modal.id);
      });
    }
  });

  // Close modal on Escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      document.querySelectorAll('.modal').forEach(modal => {
        if (modal.getAttribute('aria-hidden') === 'false') {
          dismissModal(modal.id);
        }
      });
    }
  });

  // Help and disclaimer links
  const helpLink = document.getElementById('helpLink');
  const footerHelpLink = document.getElementById('footerHelpLink');
  const disclaimerLink = document.getElementById('disclaimerLink');

  if (helpLink) helpLink.addEventListener('click', () => {
    const modal = document.getElementById('helpModal');
    modal.setAttribute('aria-hidden', 'false');
  });

  if (footerHelpLink) footerHelpLink.addEventListener('click', () => {
    const modal = document.getElementById('helpModal');
    modal.setAttribute('aria-hidden', 'false');
  });

  if (disclaimerLink) disclaimerLink.addEventListener('click', () => {
    const modal = document.getElementById('legalModal');
    modal.setAttribute('aria-hidden', 'false');
  });

  // Show legal modal on first visit
  showLegalModal();

  // === THEME TOGGLE ===
  
  const themeToggle = document.getElementById('themeToggle');
  const html = document.documentElement;
  const sunIcon = themeToggle.querySelector('.sun-icon');
  const moonIcon = themeToggle.querySelector('.moon-icon');
  
  const savedTheme = localStorage.getItem('theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  
  if (savedTheme === 'dark' || (!savedTheme && prefersDark)) {
    html.setAttribute('data-theme', 'dark');
    sunIcon.style.display = 'none';
    moonIcon.style.display = 'block';
  }
  
  themeToggle.addEventListener('click', () => {
    const currentTheme = html.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    html.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    
    if (newTheme === 'dark') {
      sunIcon.style.display = 'none';
      moonIcon.style.display = 'block';
    } else {
      sunIcon.style.display = 'block';
      moonIcon.style.display = 'none';
    }
  });

  // === TAB NAVIGATION ===
  
  const tabs = document.querySelectorAll('.tab');
  const tabPanels = document.querySelectorAll('.tab-panel');
  
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const targetId = tab.getAttribute('aria-controls');
      
      tabs.forEach(t => {
        t.classList.remove('active');
        t.setAttribute('aria-selected', 'false');
      });
      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');
      
      tabPanels.forEach(panel => {
        panel.hidden = true;
        panel.classList.remove('active');
      });
      const targetPanel = document.getElementById(targetId);
      targetPanel.hidden = false;
      targetPanel.classList.add('active');
    });
  });

  // === FILE INPUT & MULTI-FILE HANDLING ===
  
  const fileInput = document.getElementById('fileInput');
  const fileList = document.getElementById('fileList');
  const fileListItems = document.getElementById('fileListItems');
  const fileLabel = document.querySelector('.file-label-text');
  const analyzeFileBtn = document.getElementById('analyzeFileBtn');
  
  if (fileInput) {
    fileInput.addEventListener('change', (e) => {
      const files = Array.from(e.target.files);
      
      if (files.length > 0) {
        fileLabel.textContent = files.length === 1 
          ? files[0].name 
          : `${files.length} files selected`;
        
        // Show file list
        fileListItems.innerHTML = '';
        files.forEach((file, index) => {
          const li = document.createElement('li');
          li.className = 'file-list-item';
          li.innerHTML = `
            <div class="file-list-item-name">
              <span>${file.name}</span>
            </div>
            <button class="file-list-item-remove" aria-label="Remove ${file.name}" data-index="${index}">✕</button>
          `;
          fileListItems.appendChild(li);
        });
        
        fileList.style.display = 'block';
        analyzeFileBtn.disabled = false;
      } else {
        fileLabel.textContent = 'Choose file(s) or drag here';
        fileList.style.display = 'none';
        analyzeFileBtn.disabled = true;
      }
    });

    // Handle drag and drop
    const fileUploadArea = fileInput.parentElement;
    fileUploadArea.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.stopPropagation();
      fileUploadArea.style.opacity = '0.7';
    });

    fileUploadArea.addEventListener('dragleave', () => {
      fileUploadArea.style.opacity = '1';
    });

    fileUploadArea.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      fileUploadArea.style.opacity = '1';
      fileInput.files = e.dataTransfer.files;
      fileInput.dispatchEvent(new Event('change'));
    });
  }

  // === ADVANCED TOGGLE ===
  
  const showAdvanced = document.getElementById('showAdvanced');
  const advancedLaws = document.getElementById('advanced-laws');
  
  if (showAdvanced) {
    showAdvanced.addEventListener('click', () => {
      const isExpanded = showAdvanced.getAttribute('aria-expanded') === 'true';
      showAdvanced.setAttribute('aria-expanded', !isExpanded);
      advancedLaws.hidden = isExpanded;
    });
  }

  // === LOCATION SELECTOR & GDPR CHECKBOX ===
  
  const locationSelect = document.getElementById('location');
  const gdprCheckGroup = document.getElementById('gdprCheckGroup');
  const alsoGdprCheckbox = document.getElementById('alsoGdpr');
  
  if (locationSelect && gdprCheckGroup) {
    locationSelect.addEventListener('change', () => {
      const value = locationSelect.value;
      if (value && value !== 'GDPR' && value !== 'UK-GDPR') {
        gdprCheckGroup.style.display = 'block';
        alsoGdprCheckbox.checked = true;
      } else {
        gdprCheckGroup.style.display = 'none';
        alsoGdprCheckbox.checked = false;
      }
    });
  }

  // === ANALYSIS MODE ===

  const analysisModeRadios = document.querySelectorAll('input[name="analysisMode"]');
  let selectedAnalysisMode = 'quick';

  analysisModeRadios.forEach(radio => {
    radio.addEventListener('change', (e) => {
      selectedAnalysisMode = e.target.value;
    });
  });

  // === ANALYZE BUTTONS ===
  
  const analyzeTextBtn = document.getElementById('analyzeTextBtn');
  const analyzeUrlBtn = document.getElementById('analyzeUrlBtn');
  const textInput = document.getElementById('textInput');
  const urlInput = document.getElementById('urlInput');
  const loading = document.getElementById('loading');
  const results = document.getElementById('results');
  const errorState = document.getElementById('errorState');
  const confidenceFilter = document.getElementById('confidenceFilter');
  
  let currentResults = null;

  function showLoading() {
    document.querySelectorAll('.wizard-step').forEach(step => step.hidden = true);
    loading.hidden = false;
    results.hidden = true;
    errorState.hidden = true;
  }
  
  function showResults(data) {
    loading.hidden = true;
    results.hidden = false;
    currentResults = data;
    renderResults(data);
  }
  
  function showError(message) {
    loading.hidden = true;
    errorState.hidden = false;
    document.getElementById('errorMessage').textContent = message;
  }

  function renderResults(data) {
    // Summary cards
    const summary = document.getElementById('resultsSummary');
    const categories = {
      critical: data.findings?.filter(f => f.severity === 'critical').length || 0,
      high: data.findings?.filter(f => f.severity === 'high').length || 0,
      medium: data.findings?.filter(f => f.severity === 'medium').length || 0,
      low: data.findings?.filter(f => f.severity === 'low').length || 0
    };

    summary.innerHTML = `
      <div class="summary-card" data-category="critical">
        <span class="summary-card-number">${categories.critical}</span>
        <span class="summary-card-label">Critical</span>
      </div>
      <div class="summary-card" data-category="high">
        <span class="summary-card-number">${categories.high}</span>
        <span class="summary-card-label">High</span>
      </div>
      <div class="summary-card" data-category="medium">
        <span class="summary-card-number">${categories.medium}</span>
        <span class="summary-card-label">Medium</span>
      </div>
      <div class="summary-card" data-category="low">
        <span class="summary-card-number">${categories.low}</span>
        <span class="summary-card-label">Low</span>
      </div>
    `;

    // Render collapsible category sections
    const container = document.getElementById('findingsContainer');
    container.innerHTML = '';

    const severities = ['critical', 'high', 'medium', 'low'];
    const labels = { critical: 'Critical Issues', high: 'High Priority', medium: 'Medium Priority', low: 'Low Priority' };

    severities.forEach(severity => {
      const severityFindings = data.findings?.filter(f => f.severity === severity) || [];
      
      if (severityFindings.length === 0) return;

      const section = document.createElement('div');
      section.className = 'category-section';
      
      const header = document.createElement('button');
      header.className = 'category-header';
      header.setAttribute('aria-expanded', 'true');
      header.setAttribute('aria-controls', `findings-${severity}`);
      header.innerHTML = `
        <h3 class="category-title">
          <span class="category-badge ${severity}">${severityFindings.length}</span>
          ${labels[severity]}
        </h3>
        <div class="category-toggle">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <path d="M5 7.5L10 12.5L15 7.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
      `;

      const content = document.createElement('div');
      content.className = 'category-content';
      content.id = `findings-${severity}`;

      const findingsList = document.createElement('div');
      findingsList.className = 'findings-list';

      severityFindings.forEach(finding => {
        const item = document.createElement('div');
        item.className = `finding-item ${severity}`;
        
        const confidencePercent = Math.round(finding.confidence * 100);
        let confidenceClass = 'high';
        let confidenceLabel = 'Confident';
        
        if (confidencePercent >= 95) {
          confidenceClass = 'high';
          confidenceLabel = 'Very Confident';
        } else if (confidencePercent >= 70) {
          confidenceClass = 'medium';
          confidenceLabel = 'Needs Review';
        } else {
          confidenceClass = 'low';
          confidenceLabel = 'Uncertain';
        }

        // Check for high-stakes findings
        const isHighStakes = finding.title?.toLowerCase().includes('arbitration') || 
                            finding.title?.toLowerCase().includes('class action') ||
                            finding.title?.toLowerCase().includes('waiver');

        item.innerHTML = `
          <div class="finding-header">
            <h4 class="finding-title">${finding.title}</h4>
            <span class="finding-severity ${severity}">${severity}</span>
          </div>
          <p class="finding-description">${finding.description}</p>
          <div class="confidence-badge ${confidenceClass}" title="${confidencePercent}% confidence score">
            ${confidencePercent}% confident
            <span class="confidence-icon">i</span>
          </div>
          ${isHighStakes ? `
            <div class="finding-warning">
              <div class="finding-warning-icon">⚠️</div>
              <div class="finding-warning-text">This is a high-stakes clause. Consult with an attorney for legal advice.</div>
            </div>
          ` : ''}
        `;

        findingsList.appendChild(item);
      });

      content.appendChild(findingsList);
      header.addEventListener('click', () => {
        const isExpanded = header.getAttribute('aria-expanded') === 'true';
        header.setAttribute('aria-expanded', !isExpanded);
      });

      section.appendChild(header);
      section.appendChild(content);
      container.appendChild(section);
    });
  }

  // Confidence filter
  if (confidenceFilter) {
    confidenceFilter.addEventListener('change', () => {
      if (currentResults) {
        const filtered = {
          ...currentResults,
          findings: currentResults.findings?.filter(f => {
            const confidence = Math.round(f.confidence * 100);
            return !confidenceFilter.checked || confidence >= 70;
          }) || []
        };
        renderResults(filtered);
      }
    });
  }
  
  if (analyzeTextBtn) {
    analyzeTextBtn.addEventListener('click', async () => {
      const text = textInput.value.trim();
      if (!text) {
        alert('Please paste some text to analyze');
        return;
      }
      
      showLoading();
      
      try {
        const docType = document.getElementById('docType').value;
        const location = locationSelect?.value || '';
        const alsoGdpr = alsoGdprCheckbox?.checked || false;
        
        const response = await fetch(`${API_BASE}/analyze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text,
            doc_type: docType,
            mode: selectedAnalysisMode,
            jurisdictions: getSelectedJurisdictions(location, alsoGdpr)
          })
        });
        
        if (!response.ok) throw new Error('Analysis failed');
        
        const data = await response.json();
        showResults(data);
        
      } catch (error) {
        showError(error.message || 'Something went wrong. Please try again.');
      }
    });
  }
  
  if (analyzeUrlBtn) {
    analyzeUrlBtn.addEventListener('click', async () => {
      const url = urlInput.value.trim();
      if (!url) {
        alert('Please enter a URL');
        return;
      }
      
      showLoading();
      
      try {
        const docType = document.getElementById('docType').value;
        const location = locationSelect?.value || '';
        const alsoGdpr = alsoGdprCheckbox?.checked || false;
        
        const response = await fetch(`${API_BASE}/analyze/url`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url,
            doc_type: docType,
            mode: selectedAnalysisMode,
            jurisdictions: getSelectedJurisdictions(location, alsoGdpr)
          })
        });
        
        if (!response.ok) throw new Error('Analysis failed');
        
        const data = await response.json();
        showResults(data);
        
      } catch (error) {
        showError(error.message || 'Something went wrong. Please try again.');
      }
    });
  }
  
  if (analyzeFileBtn) {
    analyzeFileBtn.addEventListener('click', async () => {
      const files = fileInput.files;
      if (!files || files.length === 0) {
        alert('Please select at least one file');
        return;
      }
      
      showLoading();
      
      try {
        // For now, analyze files sequentially
        // In a real app, could do batch processing
        const allResults = [];
        
        for (let i = 0; i < files.length; i++) {
          const file = files[i];
          const formData = new FormData();
          formData.append('file', file);
          formData.append('doc_type', document.getElementById('docType').value);
          formData.append('mode', selectedAnalysisMode);
          
          const location = locationSelect?.value || '';
          const alsoGdpr = alsoGdprCheckbox?.checked || false;
          formData.append('jurisdictions', JSON.stringify(getSelectedJurisdictions(location, alsoGdpr)));
          
          const response = await fetch(`${API_BASE}/analyze/file`, {
            method: 'POST',
            body: formData
          });
          
          if (!response.ok) throw new Error(`Analysis failed for ${file.name}`);
          
          const data = await response.json();
          allResults.push({ file: file.name, ...data });
        }
        
        // If multiple files, show batch tabs
        if (allResults.length > 1) {
          showResultsWithBatchTabs(allResults);
        } else {
          showResults(allResults[0]);
        }
        
      } catch (error) {
        showError(error.message || 'Something went wrong. Please try again.');
      }
    });
  }

  function showResultsWithBatchTabs(resultsArray) {
    loading.hidden = true;
    results.hidden = false;
    currentResults = resultsArray[0];

    // Show batch tabs
    const batchTabs = document.getElementById('batchTabs');
    const batchTabsList = document.getElementById('batchTabsList');
    
    batchTabs.hidden = false;
    batchTabsList.innerHTML = '';

    resultsArray.forEach((result, index) => {
      const tab = document.createElement('button');
      tab.className = `batch-tab ${index === 0 ? 'active' : ''}`;
      tab.textContent = result.file;
      tab.addEventListener('click', () => {
        document.querySelectorAll('.batch-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        currentResults = result;
        renderResults(result);
      });
      batchTabsList.appendChild(tab);
    });

    renderResults(resultsArray[0]);
  }
  
  function getSelectedJurisdictions(location, includeGdpr) {
    const jurisdictions = [];
    
    if (location) {
      jurisdictions.push(location);
    }
    
    if (includeGdpr && !jurisdictions.includes('GDPR')) {
      jurisdictions.push('GDPR');
    }
    
    if (!advancedLaws.hidden) {
      const checked = advancedLaws.querySelectorAll('.checkbox:checked');
      checked.forEach(cb => {
        const value = cb.value;
        if (!jurisdictions.includes(value)) {
          jurisdictions.push(value);
        }
      });
    }
    
    return jurisdictions.length > 0 ? jurisdictions : ['GDPR'];
  }

  // === CHECK ANOTHER & RETRY ===
  
  const checkAnotherBtn = document.getElementById('checkAnotherBtn');
  const errorRetryBtn = document.getElementById('errorRetryBtn');
  
  if (checkAnotherBtn) {
    checkAnotherBtn.addEventListener('click', () => {
      results.hidden = true;
      confidenceFilter.checked = false;
      document.querySelectorAll('.wizard-step').forEach(step => step.hidden = false);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }
  
  if (errorRetryBtn) {
    errorRetryBtn.addEventListener('click', () => {
      errorState.hidden = true;
      document.querySelectorAll('.wizard-step').forEach(step => step.hidden = false);
    });
  }

  // === EXPORT RESULTS ===
  
  const exportBtn = document.getElementById('exportBtn');
  
  if (exportBtn) {
    exportBtn.addEventListener('click', () => {
      if (!currentResults) return;

      const csv = generateCSV(currentResults);
      const blob = new Blob([csv], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `analysis-${new Date().toISOString().split('T')[0]}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  function generateCSV(results) {
    const headers = ['Severity', 'Title', 'Description', 'Confidence'];
    const rows = results.findings?.map(f => [
      f.severity,
      `"${f.title?.replace(/"/g, '""') || ''}"`,
      `"${f.description?.replace(/"/g, '""') || ''}"`,
      `${Math.round(f.confidence * 100)}%`
    ]) || [];

    return [
      headers.join(','),
      ...rows.map(row => row.join(','))
    ].join('\n');
  }

})();
