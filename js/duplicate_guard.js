/**
 * ENTERPRISE-GRADE REAL-TIME DUPLICATE DETECTION, PREVENTION & DIRECTORY SCANNER
 * 
 * Capabilities:
 * 1. Single Entity Real-Time Multi-Field Validation (Phone/E.164, Email, Brand/Domain)
 * 2. Visual Indicators: Field warning borders, inline badges, informative Alert Cards
 * 3. Fail-Safe Submission Lock & Explicit Override Checkbox
 * 4. Rapid Bulk / CSV / Paste Two-Tier Deduplication Scanner (In-Batch + CRM Cross-Reference)
 * 5. Auxiliary Entity Guards (Categories/Niches, Sticky Notes)
 * 6. Retroactive Directory Scanner, Pipeline Alert Banner, Dedicated Status Filter & Row Badging
 */

window.DuplicateGuard = (function () {
  'use strict';

  // --- Normalization Utilities ---
  function sanitizeDigits(val) {
    if (!val) return '';
    return String(val).replace(/\D+/g, '');
  }

  function normalizePhoneE164(phone) {
    if (!phone || phone === 'NOT AVAILABLE' || phone === 'N/A') return '';
    let digits = sanitizeDigits(phone);
    if (!digits) return '';
    // If standard country code prefixes (e.g. 353 for Ireland, 1 for US/CA, 44 for UK, 880 for BD)
    // Strip leading 00 if international format
    if (digits.startsWith('00')) digits = digits.slice(2);
    // Take significant tail digits (last 9 digits) for resilient matching across international & local formats
    return digits.length > 9 ? digits.slice(-9) : digits;
  }

  function normalizeEmail(email) {
    if (!email || email === 'NOT AVAILABLE' || email === 'N/A') return '';
    return String(email).trim().toLowerCase();
  }

  function normalizeDomain(url) {
    if (!url || url === 'NOT AVAILABLE' || url === 'N/A') return '';
    let clean = String(url).trim().toLowerCase();
    clean = clean.replace(/^https?:\/\//i, '');
    clean = clean.split('/')[0];
    clean = clean.replace(/^www\./i, '');
    clean = clean.split(':')[0];
    return clean;
  }

  function normalizeBrand(name) {
    if (!name || name === 'NOT AVAILABLE' || name === 'N/A') return '';
    let clean = String(name).trim().toLowerCase();
    // Strip common legal/corporate suffixes
    clean = clean.replace(/\b(ltd|limited|llc|inc|co|corp|plc)\b/gi, '').trim();
    // Normalize punctuation & whitespace
    clean = clean.replace(/[^\w\s]/gi, '').replace(/\s+/g, ' ');
    return clean.length >= 3 ? clean : '';
  }

  // --- Core Scanner: Check Single Candidate Against Database ---
  function scanSingleLead(candidate, excludeId, leadPool) {
    if (!leadPool || !Array.isArray(leadPool)) return { isDuplicate: false, matches: [] };

    const candPhoneNorm = normalizePhoneE164(candidate.phone);
    const candEmailNorm = normalizeEmail(candidate.email);
    const candDomainNorm = normalizeDomain(candidate.website);
    const candBrandNorm = normalizeBrand(candidate.business_name);

    const matches = [];

    for (const lead of leadPool) {
      if (lead.duplicate_status === 'MERGED') continue;
      if (excludeId && String(lead.id) === String(excludeId)) continue;

      const matchedFields = [];

      // 1. Phone match
      if (candPhoneNorm && candPhoneNorm.length >= 7) {
        const leadPhoneNorm = normalizePhoneE164(lead.phone || lead.normalized_phone);
        if (leadPhoneNorm && (leadPhoneNorm === candPhoneNorm || leadPhoneNorm.endsWith(candPhoneNorm) || candPhoneNorm.endsWith(leadPhoneNorm))) {
          matchedFields.push({
            field: 'phone',
            label: 'Phone Number',
            value: lead.phone || leadPhoneNorm,
            tag: `Match: Phone (${lead.phone || candidate.phone})`
          });
        }
      }

      // 2. Email match
      if (candEmailNorm && candEmailNorm.includes('@')) {
        const leadEmailNorm = normalizeEmail(lead.email);
        if (leadEmailNorm && leadEmailNorm === candEmailNorm) {
          matchedFields.push({
            field: 'email',
            label: 'Email Address',
            value: lead.email,
            tag: `Match: Email (${lead.email})`
          });
        }
      }

      // 3. Domain match
      if (candDomainNorm && candDomainNorm.includes('.')) {
        const leadDomainNorm = normalizeDomain(lead.website || lead.normalized_domain);
        if (leadDomainNorm && leadDomainNorm === candDomainNorm) {
          matchedFields.push({
            field: 'website',
            label: 'Official Domain',
            value: lead.website || leadDomainNorm,
            tag: `Match: Domain (${leadDomainNorm})`
          });
        }
      }

      // 4. Exact Company/Brand match (length >= 3)
      if (candBrandNorm && candBrandNorm.length >= 4) {
        const leadBrandNorm = normalizeBrand(lead.business_name);
        if (leadBrandNorm && leadBrandNorm === candBrandNorm) {
          matchedFields.push({
            field: 'business_name',
            label: 'Business Name',
            value: lead.business_name,
            tag: `Match: Name (${lead.business_name})`
          });
        }
      }

      if (matchedFields.length > 0) {
        matches.push({
          existingRecord: lead,
          matchedFields: matchedFields
        });
      }
    }

    return {
      isDuplicate: matches.length > 0,
      matches: matches,
      primaryMatch: matches.length > 0 ? matches[0].existingRecord : null
    };
  }

  // --- Retroactive Directory Scanner: Compute Set of All Duplicate IDs ---
  function computeDirectoryDuplicates(leadPool) {
    if (!leadPool || !Array.isArray(leadPool)) return { duplicateIdSet: new Set(), duplicatePairs: [] };

    const seenPhones = new Map();
    const seenEmails = new Map();
    const seenDomains = new Map();
    const dupeIdSet = new Set();
    const duplicatePairs = [];

    for (const lead of leadPool) {
      if (lead.duplicate_status === 'MERGED') continue;

      const p = normalizePhoneE164(lead.phone || lead.normalized_phone);
      const e = normalizeEmail(lead.email);
      const d = normalizeDomain(lead.website || lead.normalized_domain);

      let matchedWith = null;
      let reason = '';

      if (p && p.length >= 7) {
        if (seenPhones.has(p)) {
          matchedWith = seenPhones.get(p);
          reason = `Phone (${lead.phone})`;
        } else {
          seenPhones.set(p, lead);
        }
      }

      if (!matchedWith && e && e.includes('@')) {
        if (seenEmails.has(e)) {
          matchedWith = seenEmails.get(e);
          reason = `Email (${lead.email})`;
        } else {
          seenEmails.set(e, lead);
        }
      }

      if (!matchedWith && d && d.includes('.')) {
        if (seenDomains.has(d)) {
          matchedWith = seenDomains.get(d);
          reason = `Domain (${d})`;
        } else {
          seenDomains.set(d, lead);
        }
      }

      if (matchedWith) {
        dupeIdSet.add(lead.id);
        dupeIdSet.add(matchedWith.id);
        duplicatePairs.push({
          lead1: matchedWith,
          lead2: lead,
          reason: reason
        });
      }
    }

    return {
      duplicateIdSet: dupeIdSet,
      duplicatePairs: duplicatePairs,
      count: dupeIdSet.size
    };
  }

  // --- Two-Tier Bulk / Import Batch Deduplication Scanner ---
  function scanBatchRecords(incomingRows, fieldMapping, existingPool) {
    const results = [];
    const inBatchSeenPhones = new Map();
    const inBatchSeenEmails = new Map();
    const inBatchSeenDomains = new Map();

    let duplicateCount = 0;

    for (let idx = 0; idx < incomingRows.length; idx++) {
      const row = incomingRows[idx];
      const name = String(row[fieldMapping.business_name] || '').trim();
      const phone = String(row[fieldMapping.phone] || '').trim();
      const email = String(row[fieldMapping.email] || '').trim();
      const website = String(row[fieldMapping.website] || '').trim();

      const candidate = {
        business_name: name,
        phone: phone,
        email: email,
        website: website
      };

      const pNorm = normalizePhoneE164(phone);
      const eNorm = normalizeEmail(email);
      const dNorm = normalizeDomain(website);

      let isBatchDupe = false;
      let batchDupeDetail = '';

      // Tier 1: In-Batch Deduplication
      if (pNorm && pNorm.length >= 7 && inBatchSeenPhones.has(pNorm)) {
        isBatchDupe = true;
        batchDupeDetail = `Repeated in batch (Phone matches row #${inBatchSeenPhones.get(pNorm) + 1})`;
      } else if (eNorm && eNorm.includes('@') && inBatchSeenEmails.has(eNorm)) {
        isBatchDupe = true;
        batchDupeDetail = `Repeated in batch (Email matches row #${inBatchSeenEmails.get(eNorm) + 1})`;
      } else if (dNorm && dNorm.includes('.') && inBatchSeenDomains.has(dNorm)) {
        isBatchDupe = true;
        batchDupeDetail = `Repeated in batch (Domain matches row #${inBatchSeenDomains.get(dNorm) + 1})`;
      }

      if (pNorm && pNorm.length >= 7) inBatchSeenPhones.set(pNorm, idx);
      if (eNorm && eNorm.includes('@')) inBatchSeenEmails.set(eNorm, idx);
      if (dNorm && dNorm.includes('.')) inBatchSeenDomains.set(dNorm, idx);

      // Tier 2: Database Cross-Referencing
      const dbScan = scanSingleLead(candidate, null, existingPool);

      const itemResult = {
        rowIndex: idx,
        candidate: candidate,
        isDuplicate: isBatchDupe || dbScan.isDuplicate,
        isBatchDuplicate: isBatchDupe,
        isCrmDuplicate: dbScan.isDuplicate,
        batchDetail: batchDupeDetail,
        crmMatch: dbScan.isDuplicate ? dbScan.matches[0] : null,
        crmMatches: dbScan.matches
      };

      if (itemResult.isDuplicate) {
        duplicateCount++;
      }

      results.push(itemResult);
    }

    return {
      rows: results,
      totalRows: incomingRows.length,
      duplicateCount: duplicateCount,
      freshCount: incomingRows.length - duplicateCount
    };
  }

  // --- Real-Time Modal Form Controller ---
  function attachModalValidator(config) {
    const {
      formId,
      nameInputId,
      phoneInputId,
      emailInputId,
      websiteInputId,
      alertContainerId,
      submitBtnId,
      overrideCheckboxId,
      getExcludeId,
      getLeadPool
    } = config;

    let debounceTimer = null;

    function runValidation() {
      const nameInput = document.getElementById(nameInputId);
      const phoneInput = document.getElementById(phoneInputId);
      const emailInput = document.getElementById(emailInputId);
      const websiteInput = document.getElementById(websiteInputId);
      const alertContainer = document.getElementById(alertContainerId);
      const submitBtn = document.getElementById(submitBtnId);
      const overrideCb = document.getElementById(overrideCheckboxId);

      if (!nameInput || !alertContainer) return;

      const candidate = {
        business_name: nameInput ? nameInput.value.trim() : '',
        phone: phoneInput ? phoneInput.value.trim() : '',
        email: emailInput ? emailInput.value.trim() : '',
        website: websiteInput ? websiteInput.value.trim() : ''
      };

      const excludeId = typeof getExcludeId === 'function' ? getExcludeId() : null;
      const pool = typeof getLeadPool === 'function' ? getLeadPool() : (window.allCachedLeads || []);

      const scan = scanSingleLead(candidate, excludeId, pool);

      // Clear field highlights & badges
      [nameInput, phoneInput, emailInput, websiteInput].forEach(inp => {
        if (!inp) return;
        inp.classList.remove('input-field-duplicate-warning');
        const existingBadge = inp.parentNode.querySelector('.inline-dupe-tag');
        if (existingBadge) existingBadge.remove();
      });

      if (!scan.isDuplicate) {
        alertContainer.innerHTML = '';
        alertContainer.style.display = 'none';
        if (submitBtn) {
          submitBtn.disabled = false;
          if (submitBtn.getAttribute('data-original-text')) {
            submitBtn.textContent = submitBtn.getAttribute('data-original-text');
          }
        }
        return;
      }

      // Mark offending input fields
      scan.matches.forEach(m => {
        m.matchedFields.forEach(mf => {
          let targetInput = null;
          if (mf.field === 'phone') targetInput = phoneInput;
          else if (mf.field === 'email') targetInput = emailInput;
          else if (mf.field === 'website') targetInput = websiteInput;
          else if (mf.field === 'business_name') targetInput = nameInput;

          if (targetInput) {
            targetInput.classList.add('input-field-duplicate-warning');
            if (!targetInput.parentNode.querySelector('.inline-dupe-tag')) {
              const badge = document.createElement('span');
              badge.className = 'inline-dupe-tag';
              badge.textContent = '⚠️ Duplicate';
              const lbl = targetInput.parentNode.querySelector('.field-label');
              if (lbl) {
                lbl.appendChild(badge);
              }
            }
          }
        });
      });

      // Render Rich Informative Alert Card
      const primaryMatch = scan.primaryMatch;
      const allTags = [];
      scan.matches.forEach(m => m.matchedFields.forEach(mf => allTags.push(mf.tag)));
      const uniqueTags = [...new Set(allTags)];

      const allowOverride = overrideCb && overrideCb.checked;

      alertContainer.style.display = 'block';
      alertContainer.innerHTML = `
        <div class="duplicate-alert-card animate-fade-in">
          <div class="dupe-card-header">
            <div class="dupe-card-title">
              <span class="dupe-warning-icon">⚠️</span>
              <strong>Duplicate Contact / Data Detected!</strong>
            </div>
            <span class="dupe-badge-count">${scan.matches.length} Match${scan.matches.length === 1 ? '' : 'es'}</span>
          </div>

          <div class="dupe-card-tags">
            ${uniqueTags.map(t => `<span class="dupe-tag-pill">${escapeHtml(t)}</span>`).join('')}
          </div>

          <div class="dupe-preview-box">
            <div class="dupe-preview-title">Existing Record in CRM:</div>
            <div class="dupe-preview-grid">
              <div><span class="lbl">Name:</span> <strong>${escapeHtml(primaryMatch.business_name)}</strong></div>
              <div><span class="lbl">Stage:</span> <span class="badge-stage">${escapeHtml(primaryMatch.crm_status || 'NEW')}</span></div>
              <div><span class="lbl">Phone:</span> <span>${escapeHtml(primaryMatch.phone || 'N/A')}</span></div>
              <div><span class="lbl">Email:</span> <span>${escapeHtml(primaryMatch.email || 'N/A')}</span></div>
              <div><span class="lbl">Website:</span> <span>${escapeHtml(primaryMatch.website || 'N/A')}</span></div>
              <div><span class="lbl">Created:</span> <span>${escapeHtml(primaryMatch.research_date || primaryMatch.created_at || 'Recent')}</span></div>
            </div>
          </div>

          <div class="dupe-card-actions">
            <button type="button" class="btn-tool btn-view-dupe-pipeline" onclick="DuplicateGuard.jumpToLeadInPipeline(${primaryMatch.id}, '${escapeHtml(primaryMatch.business_name)}')">
              🔍 View Existing Lead in Pipeline
            </button>
            <label class="dupe-override-toggle">
              <input type="checkbox" id="${overrideCheckboxId}" onchange="DuplicateGuard.onOverrideToggle('${config.formId}', '${config.submitBtnId}')" ${allowOverride ? 'checked' : ''}>
              <span>Allow adding duplicate record anyway</span>
            </label>
          </div>
        </div>
      `;

      // Submission Lock Logic
      if (submitBtn) {
        if (!submitBtn.getAttribute('data-original-text')) {
          submitBtn.setAttribute('data-original-text', submitBtn.textContent);
        }
        if (allowOverride) {
          submitBtn.disabled = false;
          submitBtn.textContent = submitBtn.getAttribute('data-original-text');
        } else {
          submitBtn.disabled = true;
          submitBtn.textContent = '⚠️ Duplicate Warning Active';
        }
      }
    }

    const handler = () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(runValidation, 140);
    };

    [nameInputId, phoneInputId, emailInputId, websiteInputId].forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener('input', handler);
        el.addEventListener('change', handler);
      }
    });

    return { validate: runValidation };
  }

  function onOverrideToggle(formId, submitBtnId) {
    const form = document.getElementById(formId);
    const btn = document.getElementById(submitBtnId);
    if (!form || !btn) return;
    const cb = form.querySelector('.dupe-override-toggle input[type="checkbox"]');
    if (cb && cb.checked) {
      btn.disabled = false;
      const orig = btn.getAttribute('data-original-text') || 'Save Lead';
      btn.textContent = orig;
    } else {
      btn.disabled = true;
      btn.textContent = '⚠️ Duplicate Warning Active';
    }
  }

  function jumpToLeadInPipeline(leadId, businessName) {
    // 1. Close open modals
    if (typeof closeModal === 'function') {
      closeModal('modalAddLead');
      closeModal('modalLeadDetail');
    }
    // 2. Switch to Leads Directory tab
    if (typeof switchTab === 'function') {
      switchTab('leads');
    }
    // 3. Set search filter & highlight
    const searchInput = document.getElementById('searchLeadsInput');
    if (searchInput) {
      searchInput.value = businessName;
      if (typeof handleSearchInput === 'function') {
        handleSearchInput();
      } else if (typeof loadLeads === 'function') {
        loadLeads();
      }
    }
  }

  // --- Auxiliary Entity Duplication: Category / Niche Guard ---
  function validateCategoryUniqueness(categoryName, existingCategories) {
    if (!categoryName) return { isDuplicate: false };
    const clean = String(categoryName).trim().toLowerCase();
    if (!clean) return { isDuplicate: false };

    const exists = existingCategories.some(cat => String(cat).trim().toLowerCase() === clean);
    return {
      isDuplicate: exists,
      message: exists ? '⚠️ Duplicate Category - Choose Unique Name' : ''
    };
  }

  function escapeHtml(text) {
    if (!text) return '';
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  return {
    normalizePhoneE164,
    normalizeEmail,
    normalizeDomain,
    normalizeBrand,
    scanSingleLead,
    computeDirectoryDuplicates,
    scanBatchRecords,
    attachModalValidator,
    onOverrideToggle,
    jumpToLeadInPipeline,
    validateCategoryUniqueness
  };
})();
