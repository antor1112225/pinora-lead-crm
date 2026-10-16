/**
 * PINORA LEAD WORKSPACE & SIMPLE CRM
 * Full Client Controller
 * 
 * Features:
 * 1. 5 Interactive Views: Leads Table, Follow-ups Today, Ads Verification, Lead Finder, Settings & Backup
 * 2. Real-time CRM top metrics strip & live mission telemetry polling
 * 3. Compact Lead Table matching reference UI (Circular WA, email check badge, social icons, ad status badges, CRM status dropdown)
 * 4. Google Ads & Meta Ads verification modal + direct official library browser launcher
 * 5. WhatsApp click-to-chat + manual verification recorder
 * 6. Manual outreach logger with automatic Day 0 -> Day 3 -> Day 5 follow-up sequence calculator
 * 7. Today's follow-up reminders dashboard with 1-click WhatsApp/Email, Complete, and Snooze
 * 8. Full lead detail modal with contact history timeline and copyable message drafts
 * 9. CSV/Excel import wizard, duplicate detector & merger, SQLite backup & integrity
 */

// Global Application State
let activeMissionState = "IDLE";
let telemetryTimer = null;
let debounceTimeout = null;
let currentStagedToken = null;
let selectedLeadIds = new Set();
let currentDetailLead = null;
let cachedSettings = { followup_interval_1: 3, followup_interval_2: 5 };

// Initialize on DOM load
document.addEventListener("DOMContentLoaded", () => {
  updateQueryPreview();
  loadLeads();
  fetchCrmStats();
  loadSettings();
  startTelemetryPolling();
});

// ==========================================
// 1. TAB NAVIGATION
// ==========================================

function switchTab(tabKey) {
  const tabs = [
    { key: "leads", btnId: "tabBtnLeads", secId: "sectionLeads", display: "flex" },
    { key: "notes", btnId: "tabBtnNotes", secId: "sectionNotes", display: "block" },
    { key: "followups", btnId: "tabBtnFollowups", secId: "sectionFollowups", display: "block" },
    { key: "ads", btnId: "tabBtnAds", secId: "sectionAds", display: "block" },
    { key: "finder", btnId: "tabBtnFinder", secId: "sectionFinder", display: "grid" },
    { key: "settings", btnId: "tabBtnSettings", secId: "sectionSettings", display: "block" }
  ];

  tabs.forEach(t => {
    const btn = document.getElementById(t.btnId);
    const sec = document.getElementById(t.secId);
    if (!btn || !sec) return;

    if (t.key === tabKey) {
      btn.classList.add("active");
      sec.style.display = t.display;
    } else {
      btn.classList.remove("active");
      sec.style.display = "none";
    }
  });

  // Action on tab activation
  if (tabKey === "leads") {
    loadLeads();
  } else if (tabKey === "notes") {
    loadDailyNotes();
  } else if (tabKey === "followups") {
    loadFollowupsDue();
  } else if (tabKey === "ads") {
    loadAdsVerificationList();
  } else if (tabKey === "settings") {
    loadSettings();
  }
}

// ==========================================
// 2. TELEMETRY & CRM METRICS POLLING
// ==========================================

function startTelemetryPolling() {
  if (telemetryTimer) clearInterval(telemetryTimer);
  fetchTelemetry();
  fetchCrmStats();
  telemetryTimer = setInterval(() => {
    fetchTelemetry();
    fetchCrmStats();
  }, 1500);
}

async function fetchTelemetry() {
  try {
    const res = await fetch("/api/telemetry");
    if (!res.ok) return;
    const data = await res.json();
    renderTelemetry(data);
  } catch (err) {
    // Server busy or restarting
  }
}

async function fetchCrmStats() {
  try {
    const res = await fetch("/api/crm/stats");
    if (!res.ok) return;
    const stats = await res.json();
    renderCrmStats(stats);
  } catch (err) {
    // Ignore network blip
  }
}

function renderCrmStats(stats) {
  const setEl = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val !== undefined ? val : 0;
  };

  // Section 18 Metric Cards
  setEl("crmTotalLeads", stats.total_leads);
  setEl("crmGoogleAdsYes", stats.google_ads_yes);
  setEl("crmMetaAdsYes", stats.meta_ads_yes);
  setEl("crmGooglePlusMeta", stats.google_plus_meta);
  setEl("crmContacted", stats.contacted);
  setEl("crmFollowupsDue", stats.followups_due);
  setEl("crmRepliesReceived", stats.replies_received);

  // Tab badges
  const badgeLeads = document.getElementById("tabBadgeAllLeads");
  if (badgeLeads) badgeLeads.textContent = stats.total_leads || 0;

  const badgeNotes = document.getElementById("tabBadgeNotes");
  if (badgeNotes && stats.notes_count !== undefined) badgeNotes.textContent = stats.notes_count;

  const badgeFollowups = document.getElementById("tabBadgeFollowups");
  if (badgeFollowups) badgeFollowups.textContent = stats.followups_due || 0;
}

function renderTelemetry(data) {
  activeMissionState = data.state || "IDLE";

  // Header status pill
  const pill = document.getElementById("headerStatusPill");
  const txt = document.getElementById("headerStatusText");
  const tBadge = document.getElementById("telemetryStatusBadge");
  const tText = document.getElementById("telemetryStatusText");

  if (pill && txt) {
    pill.className = `status-pill ${activeMissionState.toLowerCase()}`;
    txt.textContent = activeMissionState;
  }
  if (tBadge && tText) {
    tBadge.className = `status-pill ${activeMissionState.toLowerCase()}`;
    tText.textContent = activeMissionState;
  }

  // Buttons state
  const btnDeploy = document.getElementById("btnDeploy");
  const btnPause = document.getElementById("btnPause");
  if (btnDeploy && btnPause) {
    if (activeMissionState === "RUNNING") {
      btnDeploy.disabled = true;
      btnDeploy.style.opacity = "0.6";
      btnPause.textContent = "⏸ Pause";
    } else if (activeMissionState === "PAUSED") {
      btnDeploy.disabled = true;
      btnDeploy.style.opacity = "0.6";
      btnPause.textContent = "▶ Resume";
    } else {
      btnDeploy.disabled = false;
      btnDeploy.style.opacity = "1";
      btnPause.textContent = "⏸ Pause";
    }
  }

  // Counters
  const g = data.global_stats || {};
  const elFound = document.getElementById("statLeadsFound");
  const elFoundSub = document.getElementById("statLeadsFoundSub");
  const elProcessed = document.getElementById("statProcessed");
  const elQueued = document.getElementById("statQueued");
  const dupeBadge = document.getElementById("dupeCountBadge");

  if (elFound) elFound.textContent = g.records_discovered || 0;
  if (elFoundSub) elFoundSub.textContent = activeMissionState === "RUNNING" ? "searching live..." : "master database";
  if (elProcessed) elProcessed.textContent = data.records_reviewed || g.records_reviewed || 0;
  if (elQueued) elQueued.textContent = data.queued_queries || 0;
  if (dupeBadge) dupeBadge.textContent = g.duplicates_detected || 0;

  // Progress
  const pct = data.progress_percent || 0;
  const pLbl = document.getElementById("progressPercentLabel");
  const pFill = document.getElementById("progressFill");
  if (pLbl) pLbl.textContent = `${pct}%`;
  if (pFill) pFill.style.width = `${pct}%`;

  // Terminal window
  const terminal = document.getElementById("terminalWindow");
  if (terminal && data.logs && data.logs.length > 0) {
    const linesHtml = data.logs.map(l => `
      <div class="terminal-line ${l.level || 'INFO'}">
        <span class="t-time">[${l.time}]</span>
        <span class="t-prompt">&gt;</span>
        <span class="t-msg">${escapeHtml(l.message)}</span>
      </div>
    `).join("");
    terminal.innerHTML = linesHtml;
    terminal.scrollTop = terminal.scrollHeight;
  }
}

// ==========================================
// 3. LEADS DATABASE & COMPACT TABLE (MATCHING REFERENCE SCREENSHOT)
// ==========================================

function debounceLoadLeads() {
  clearTimeout(debounceTimeout);
  debounceTimeout = setTimeout(loadLeads, 300);
}

function getFilterParams() {
  const params = new URLSearchParams();
  const search = document.getElementById("filterSearch") ? document.getElementById("filterSearch").value.trim() : "";
  const city = document.getElementById("filterCity") ? document.getElementById("filterCity").value.trim() : "";
  const category = document.getElementById("filterCategory") ? document.getElementById("filterCategory").value.trim() : "";
  const crmStatus = document.getElementById("filterCrmStatus") ? document.getElementById("filterCrmStatus").value : "";
  const adsStatus = document.getElementById("filterAdsStatus") ? document.getElementById("filterAdsStatus").value : "";
  const waStatus = document.getElementById("filterWhatsAppStatus") ? document.getElementById("filterWhatsAppStatus").value : "";

  if (search) params.append("search", search);
  if (city) params.append("city", city);
  if (category) params.append("category", category);
  if (crmStatus) params.append("crm_status", crmStatus);
  if (adsStatus) params.append("ads_filter", adsStatus);
  if (waStatus) params.append("whatsapp_status", waStatus);

  if (document.getElementById("chkVerifiedAdvertisersOnly") && document.getElementById("chkVerifiedAdvertisersOnly").checked) {
    params.append("verified_advertisers_only", "1");
  }

  if (document.getElementById("chkHasPhone") && document.getElementById("chkHasPhone").checked) params.append("has_phone", "true");
  if (document.getElementById("chkHasWebsite") && document.getElementById("chkHasWebsite").checked) params.append("has_website", "true");
  if (document.getElementById("chkHasEmail") && document.getElementById("chkHasEmail").checked) params.append("has_email", "true");
  if (document.getElementById("chkHasSocial") && document.getElementById("chkHasSocial").checked) params.append("has_social", "true");
  if (document.getElementById("chkNoWebsite") && document.getElementById("chkNoWebsite").checked) params.append("no_website", "true");

  return params;
}

async function loadLeads() {
  const params = getFilterParams();
  params.append("limit", "150");

  try {
    const res = await fetch(`/api/leads?${params.toString()}`);
    if (!res.ok) return;
    const data = await res.json();
    window.cachedLeads = data.leads || [];
    renderLeadsTable(window.cachedLeads, data.total || 0);
  } catch (err) {
    console.error("Failed to load leads:", err);
  }
}

function renderLeadsTable(leads, totalCount) {
  const tbody = document.getElementById("leadsTableBody");
  const emptyState = document.getElementById("emptyLeadsState");
  const countTitle = document.getElementById("leadsLoadedTitle");
  const statShown = document.getElementById("statShown");

  if (countTitle) countTitle.textContent = `${totalCount} leads loaded`;
  if (statShown) statShown.textContent = leads.length;

  // Active filter summary text
  const params = getFilterParams();
  const activeKeys = Array.from(params.keys());
  const summaryEl = document.getElementById("filterSummaryText");
  if (summaryEl) {
    if (activeKeys.length > 0) {
      summaryEl.textContent = `Active filters: ${activeKeys.join(", ")}`;
      summaryEl.style.color = "var(--accent-cyan)";
    } else {
      summaryEl.textContent = "No filters active";
      summaryEl.style.color = "var(--text-muted)";
    }
  }

  if (leads.length === 0) {
    tbody.innerHTML = "";
    if (emptyState) emptyState.style.display = "flex";
    return;
  }

  if (emptyState) emptyState.style.display = "none";
  tbody.innerHTML = leads.map(lead => {
    const isSelected = selectedLeadIds.has(lead.id);
    const hasPhone = lead.phone && lead.phone !== "NOT AVAILABLE";
    const hasEmail = lead.email && lead.email !== "NOT AVAILABLE";
    const hasWeb = lead.website && lead.website !== "NOT AVAILABLE";

    // Social icons
    let socials = {};
    if (lead.social_profiles) {
      try {
        socials = typeof lead.social_profiles === "string" ? JSON.parse(lead.social_profiles) : lead.social_profiles;
      } catch (e) {
        socials = {};
      }
    }

    const socialBadgesHtml = renderSocialBadges(socials, lead.phone, lead);
    const googleBadgeClass = getAdBadgeClass(lead.google_ads_status);
    const metaBadgeClass = getAdBadgeClass(lead.meta_ads_status);

    const leadNum = lead.lead_number || ('#' + String(lead.id).padStart(4, '0'));
    const waDigits = hasPhone ? normalizePhoneDigits(lead.phone, lead.country, lead.city) : "";
    const waHref = waDigits ? `https://wa.me/${waDigits}` : "#";
    const waSt = lead.whatsapp_status || "Not Checked";
    const waSelectClass = waSt === "Available / Chat Opens"
      ? "wa-select-open"
      : (waSt === "Not Available" ? "wa-select-none" : "wa-select-unchecked");
    const crmSt = lead.crm_status || lead.outreach_status || "NEW";
    const crmSelectClass = getCrmStatusClass(crmSt);

    return `
      <tr class="${isSelected ? 'selected' : ''}" id="leadRow_${lead.id}">
        <td>
          <input type="checkbox" onchange="toggleSelectLead(${lead.id}, this)" ${isSelected ? 'checked' : ''}>
        </td>

        <!-- Circular WhatsApp Button -->
        <td>
          ${hasPhone && waDigits ? `
            <a href="${escapeHtml(waHref)}" target="_blank" rel="noopener noreferrer" class="btn-wa-round ${waSt === 'Available / Chat Opens' ? 'wa-verified-active' : ''}" onclick="openWhatsAppVerification(${lead.id})" title="Click to open WhatsApp chat (${escapeHtml(lead.phone)}) &amp; check status">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>
              </svg>
            </a>
          ` : `<span style="color:var(--text-muted); font-size:12px;">&mdash;</span>`}
        </td>

        <!-- Business Name & Permanent Lead Number -->
        <td>
          <div class="biz-title-cell">
            <div style="display:flex; align-items:center; gap:6px;">
              <span class="lead-id-badge" title="Permanent Lead ID">${escapeHtml(leadNum)}</span>
              <span class="biz-name" title="${escapeHtml(lead.business_name)}">${escapeHtml(lead.business_name)}</span>
            </div>
            <span class="biz-category">${escapeHtml(lead.category || 'Local Business')}${lead.city ? ' &bull; ' + escapeHtml(lead.city) : ''}</span>
          </div>
        </td>

        <!-- Website with 1-Click Copy & Copy Domain (Section 3) -->
        <td>
          <div class="web-cell-wrapper">
            ${hasWeb ? `
              <a href="${escapeHtml(lead.website)}" target="_blank" rel="noopener noreferrer" class="web-domain-link" title="Open ${escapeHtml(lead.website)}">
                🌐 ${escapeHtml(lead.normalized_domain || lead.website)} ↗
              </a>
            ` : `<span style="color:var(--text-muted); font-size:12px;">Not available</span>`}
            <div class="web-actions-row">
              <button type="button" class="btn-copy-web" onclick="copyLeadWebsite('${escapeHtml(lead.website || '')}', this)" ${hasWeb ? '' : 'disabled title="No website available"'}>
                COPY URL
              </button>
              <button type="button" class="btn-copy-web" onclick="copyLeadDomain('${escapeHtml(lead.normalized_domain || '')}', this)" ${hasWeb && lead.normalized_domain ? '' : 'disabled title="No website available"'}>
                COPY DOMAIN
              </button>
            </div>
          </div>
        </td>

        <!-- Google Ads Status Badge -->
        <td>
          <span class="ad-badge ${googleBadgeClass}" onclick="openAdsVerification(${lead.id}, 'Google')" title="Click to inspect Google Transparency Center">
            ${escapeHtml(lead.google_ads_status || 'NOT CHECKED')}
          </span>
        </td>

        <!-- Meta Ads Status Badge -->
        <td>
          <span class="ad-badge ${metaBadgeClass}" onclick="openAdsVerification(${lead.id}, 'Meta')" title="Click to inspect Meta Ad Library">
            ${escapeHtml(lead.meta_ads_status || 'NOT CHECKED')}
          </span>
        </td>

        <!-- WhatsApp-Linkable Phone Number + Inline WhatsApp Open Checker -->
        <td>
          ${hasPhone && waDigits ? `
            <div class="phone-wa-wrapper">
              <a href="${escapeHtml(waHref)}" target="_blank" rel="noopener noreferrer" class="phone-wa-link" onclick="openWhatsAppVerification(${lead.id})" title="Click to open ${escapeHtml(lead.phone)} in WhatsApp &amp; check if active">
                <span class="wa-mini-dot">💬</span>
                <span>${escapeHtml(lead.phone)}</span>
                <span style="font-size:10px; opacity:0.85;">↗</span>
              </a>
              <select class="wa-inline-select ${waSelectClass}" onchange="quickUpdateWhatsAppStatus(${lead.id}, this.value)" title="Mark whether WhatsApp is open/available on this number">
                <option value="Not Checked" ${waSt === 'Not Checked' ? 'selected' : ''}>? Check WA</option>
                <option value="Available / Chat Opens" ${waSt === 'Available / Chat Opens' ? 'selected' : ''}>✓ WA Open</option>
                <option value="Not Available" ${waSt === 'Not Available' ? 'selected' : ''}>✕ No WA</option>
                <option value="Uncertain" ${waSt === 'Uncertain' ? 'selected' : ''}>~ Uncertain</option>
              </select>
            </div>
          ` : `<span style="color:var(--text-muted); font-size:12px;">Not available</span>`}
        </td>

        <!-- Email with Verified Badge -->
        <td>
          ${hasEmail ? `
            <div style="display:inline-flex; align-items:center; gap:5px;">
              <a href="mailto:${escapeHtml(lead.email)}" class="email-link-bright" title="Discovered on website">
                ${escapeHtml(lead.email)}
              </a>
              <span class="email-check-icon" title="Email verified from public website">✓</span>
            </div>
          ` : `<span style="color:var(--text-muted); font-size:12px;">Not available</span>`}
        </td>

        <!-- Social Icons (FB, IG, IN, YT, TT, X) -->
        <td>
          <div class="social-badges-group">
            ${socialBadgesHtml}
          </div>
        </td>

        <!-- CRM Status Dropdown -->
        <td>
          <select class="crm-status-select ${crmSelectClass}" onchange="updateCrmStatus(${lead.id}, this.value)">
            ${[
              "NEW", "READY TO CONTACT", "CONTACTED", "REPLIED", "INTERESTED",
              "FOLLOW-UP DUE", "QUALIFIED", "CLIENT", "NOT INTERESTED", "DO NOT CONTACT"
            ].map(st => `
              <option value="${st}" ${crmSt === st ? 'selected' : ''}>${st}</option>
            `).join("")}
          </select>
        </td>

        <!-- Next Action / Follow-up Date -->
        <td>
          <div class="next-followup-cell" style="color:${lead.next_followup_date ? '#FBBF24' : '#F1F5F9'};">
            ${escapeHtml(lead.next_action || 'Ready to Contact')}
            ${lead.next_followup_date ? `<div class="next-followup-due">📅 Due: ${escapeHtml(lead.next_followup_date)}</div>` : ''}
          </div>
        </td>

        <!-- Action Buttons -->
        <td>
          <div style="display:flex; gap:6px; flex-wrap:nowrap;">
            <button class="btn-tool" style="padding:5px 9px; font-size:11.5px;" onclick="openLogOutreachForLead(${lead.id})" title="Log Outreach (WhatsApp/Email sent)">
              ✉️ Log
            </button>
            <button class="btn-tool" style="padding:5px 9px; font-size:11.5px;" onclick="openLeadDetail(${lead.id})" title="View Details, History &amp; Message Drafts">
              📝 Details
            </button>
            <button class="btn-tool btn-danger" style="padding:5px 9px; font-size:11.5px;" onclick="deleteSingleLead(${lead.id})" title="Delete Lead">
              🗑
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

function renderSocialBadges(socials, phone, lead = {}) {
  const merged = Object.assign({}, socials || {});
  if (lead) {
    if (lead.facebook_url && lead.facebook_url !== "NOT AVAILABLE") merged.facebook = merged.facebook || lead.facebook_url;
    if (lead.instagram_url && lead.instagram_url !== "NOT AVAILABLE") merged.instagram = merged.instagram || lead.instagram_url;
    if (lead.linkedin_url && lead.linkedin_url !== "NOT AVAILABLE") merged.linkedin = merged.linkedin || lead.linkedin_url;
    if (lead.tiktok_url && lead.tiktok_url !== "NOT AVAILABLE") merged.tiktok = merged.tiktok || lead.tiktok_url;
    if (lead.youtube_url && lead.youtube_url !== "NOT AVAILABLE") merged.youtube = merged.youtube || lead.youtube_url;
    if (lead.twitter_url && lead.twitter_url !== "NOT AVAILABLE") merged.twitter = merged.twitter || lead.twitter_url;
  }

  const platforms = [
    { key: "facebook", code: "fb", label: "FB", title: "Facebook" },
    { key: "instagram", code: "ig", label: "IG", title: "Instagram" },
    { key: "linkedin", code: "in", label: "IN", title: "LinkedIn" },
    { key: "youtube", code: "yt", label: "YT", title: "YouTube" },
    { key: "tiktok", code: "tt", label: "TT", title: "TikTok" },
    { key: "twitter", code: "x", label: "X", title: "X / Twitter" }
  ];

  const badges = [];
  for (const p of platforms) {
    const url = merged[p.key] || merged[p.code];
    if (url && url !== "NOT AVAILABLE") {
      badges.push(
        `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" class="social-badge ${p.code}" title="${p.title}: ${escapeHtml(url)}">${p.label}</a>`
      );
    }
  }

  if (badges.length === 0) {
    return `<span style="color:var(--text-muted); font-size:11px;">&mdash;</span>`;
  }
  return badges.join("");
}

// 1-Click Clipboard Copy Functions (Section 3)
async function copyLeadWebsite(url, btn) {
  if (!url) return;
  try {
    await navigator.clipboard.writeText(url);
    showButtonCopiedFeedback(btn);
  } catch (err) {
    fallbackCopyText(url, btn);
  }
}

async function copyLeadDomain(domain, btn) {
  if (!domain) return;
  try {
    await navigator.clipboard.writeText(domain);
    showButtonCopiedFeedback(btn);
  } catch (err) {
    fallbackCopyText(domain, btn);
  }
}

function showButtonCopiedFeedback(btn) {
  if (!btn) return;
  const originalText = btn.textContent;
  btn.textContent = "Copied!";
  btn.classList.add("copied");
  setTimeout(() => {
    btn.textContent = originalText;
    btn.classList.remove("copied");
  }, 1500);
}

function fallbackCopyText(text, btn) {
  const textArea = document.createElement("textarea");
  textArea.value = text;
  document.body.appendChild(textArea);
  textArea.select();
  try {
    document.execCommand("copy");
    showButtonCopiedFeedback(btn);
  } catch (err) {
    console.error("Fallback copy failed", err);
  }
  document.body.removeChild(textArea);
}

// Quick Ads Checker & Backup buttons (Section 18)
function quickOpenAdsChecker(platform) {
  const leads = window.cachedLeads || [];
  let targetLead = null;
  if (selectedLeadIds.size > 0) {
    const firstId = Array.from(selectedLeadIds)[0];
    targetLead = leads.find(l => l.id === firstId);
  } else if (leads.length > 0) {
    targetLead = leads[0];
  }

  if (targetLead) {
    openAdsVerification(targetLead.id, platform);
  } else {
    if (platform === "Google") {
      window.open("https://adstransparency.google.com/", "_blank");
    } else {
      window.open("https://www.facebook.com/ads/library/", "_blank");
    }
  }
}

async function triggerQuickBackup() {
  try {
    const res = await fetch("/api/backup/now", { method: "POST" });
    const data = await res.json();
    if (data.status === "success" || data.success) {
      alert(`Point-in-time SQLite backup created & verified (PRAGMA integrity_check = ok)!\n\nSaved to:\n• ${data.backup_path || data.local_backup || data.filename}`);
      fetchCrmStats();
    } else {
      alert("Backup error: " + (data.error || data.message || "Unknown error"));
    }
  } catch (err) {
    alert("Network error triggering backup: " + err.message);
  }
}

function getAdBadgeClass(status) {
  if (!status) return "ad-badge-unchecked";
  const s = status.toUpperCase();
  if (s.includes("YES") || s.includes("ACTIVE")) return "ad-badge-active";
  if (s.includes("NO") || s.includes("NO PUBLIC")) return "ad-badge-none";
  if (s.includes("PAUSED") || s.includes("REVIEW")) return "ad-badge-review";
  return "ad-badge-unchecked";
}

function getCrmStatusClass(status) {
  if (!status) return "status-new";
  const s = status.toUpperCase();
  if (s.includes("CLIENT")) return "status-client";
  if (s.includes("INTERESTED")) return "status-interested";
  if (s.includes("REPLIED")) return "status-replied";
  if (s.includes("CONTACTED")) return "status-contacted";
  if (s.includes("FOLLOW-UP") || s.includes("FOLLOW UP")) return "status-followup";
  if (s.includes("READY")) return "status-ready";
  if (s.includes("NOT INTERESTED") || s.includes("DECLINED")) return "status-declined";
  return "status-new";
}

async function updateCrmStatus(id, newStatus) {
  try {
    const res = await fetch(`/api/leads/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ crm_status: newStatus, outreach_status: newStatus })
    });
    if (res.ok) {
      loadLeads();
      fetchCrmStats();
      loadFollowupsDue();
    }
  } catch (err) {
    console.error("CRM status update failed:", err);
  }
}

function resetAllFilters() {
  const fields = [
    "filterSearch", "filterCity", "filterCategory", "filterCrmStatus",
    "filterAdsStatus", "filterWhatsAppStatus"
  ];
  fields.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });

  const checkboxes = [
    "chkHasPhone", "chkHasWebsite", "chkHasEmail", "chkHasSocial", "chkNoWebsite",
    "chkVerifiedAdvertisersOnly"
  ];
  checkboxes.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.checked = false;
  });

  loadLeads();
}

// Bulk Selection
function toggleSelectAll(masterCheckbox) {
  const checked = masterCheckbox.checked;
  const checkboxes = document.querySelectorAll("#leadsTableBody input[type='checkbox']");
  checkboxes.forEach(cb => {
    cb.checked = checked;
    const tr = cb.closest("tr");
    const id = parseInt(tr.id.replace("leadRow_", ""));
    if (checked) selectedLeadIds.add(id);
    else selectedLeadIds.delete(id);
    tr.classList.toggle("selected", checked);
  });
  updateBulkActionButtons();
}

function toggleSelectLead(id, cb) {
  if (cb.checked) selectedLeadIds.add(id);
  else selectedLeadIds.delete(id);
  cb.closest("tr").classList.toggle("selected", cb.checked);
  updateBulkActionButtons();
}

function updateBulkActionButtons() {
  const btn = document.getElementById("btnDeleteSelected");
  const badge = document.getElementById("selectedCountBadge");
  if (btn && badge) {
    if (selectedLeadIds.size > 0) {
      btn.style.display = "inline-flex";
      badge.textContent = selectedLeadIds.size;
    } else {
      btn.style.display = "none";
    }
  }
}

async function deleteSelectedLeads() {
  if (selectedLeadIds.size === 0) return;
  if (!confirm(`Are you sure you want to delete ${selectedLeadIds.size} selected leads?`)) return;

  try {
    const res = await fetch("/api/leads", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lead_ids: Array.from(selectedLeadIds) })
    });
    const data = await res.json();
    if (data.success) {
      selectedLeadIds.clear();
      updateBulkActionButtons();
      loadLeads();
      fetchCrmStats();
    }
  } catch (err) {
    alert("Error deleting leads: " + err);
  }
}

async function deleteSingleLead(id) {
  if (!confirm("Delete this lead record?")) return;
  try {
    await fetch("/api/leads", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lead_ids: [id] })
    });
    selectedLeadIds.delete(id);
    loadLeads();
    fetchCrmStats();
  } catch (err) {
    alert("Error: " + err);
  }
}

async function confirmClearAll() {
  if (!confirm("WARNING: This will permanently delete ALL leads in your local database. Do you wish to continue?")) return;
  try {
    await fetch("/api/leads/clear", { method: "POST" });
    selectedLeadIds.clear();
    updateBulkActionButtons();
    loadLeads();
    fetchCrmStats();
  } catch (err) {
    alert("Error: " + err);
  }
}

// Export Download
function downloadExport(fmt) {
  const params = getFilterParams();
  params.append("format", fmt);
  window.location.href = `/api/export?${params.toString()}`;
}

// ==========================================
// 4. + ADD LEAD (MANUAL QUICK LEAD CREATION)
// ==========================================

function openAddLeadModal() {
  document.getElementById("addLeadName").value = "";
  document.getElementById("addLeadCategory").value = "";
  document.getElementById("addLeadPhone").value = "";
  document.getElementById("addLeadEmail").value = "";
  document.getElementById("addLeadWebsite").value = "";
  document.getElementById("addLeadCity").value = "";
  document.getElementById("addLeadAddress").value = "";
  document.getElementById("addLeadCrmStatus").value = "READY TO CONTACT";
  document.getElementById("addLeadFollowupDate").value = "";
  document.getElementById("addLeadNotes").value = "";

  openModal("modalAddLead");
}

async function submitNewLead() {
  const name = document.getElementById("addLeadName").value.trim();
  if (!name) {
    alert("Please enter a business name.");
    return;
  }

  let webVal = document.getElementById("addLeadWebsite").value.trim();
  if (webVal && !webVal.startsWith("http://") && !webVal.startsWith("https://")) {
    webVal = "https://" + webVal;
  }

  const payload = {
    business_name: name,
    category: document.getElementById("addLeadCategory").value.trim() || "General",
    phone: document.getElementById("addLeadPhone").value.trim() || "NOT AVAILABLE",
    email: document.getElementById("addLeadEmail").value.trim() || "NOT AVAILABLE",
    website: webVal || "NOT AVAILABLE",
    city: document.getElementById("addLeadCity").value.trim(),
    address: document.getElementById("addLeadAddress").value.trim(),
    crm_status: document.getElementById("addLeadCrmStatus").value,
    next_followup_date: document.getElementById("addLeadFollowupDate").value || null,
    notes: document.getElementById("addLeadNotes").value.trim() || "Added via + Add Lead",
    source_name: "Manual Quick Entry"
  };

  try {
    const res = await fetch("/api/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      closeModal("modalAddLead");
      loadLeads();
      fetchCrmStats();
    } else {
      alert("Error adding lead: " + (data.error || "Unknown error"));
    }
  } catch (err) {
    alert("Network error: " + err);
  }
}

// ==========================================
// 5. WHATSAPP NUMBER CHECK & OUTREACH
// ==========================================

function normalizePhoneDigits(raw, country = "", city = "") {
  if (!raw || raw === "NOT AVAILABLE") return "";
  const trimmed = String(raw).trim();
  let digits = trimmed.replace(/\D/g, "");
  if (!digits) return "";

  // Strip leading 00 international prefix
  if (digits.startsWith("00")) {
    digits = digits.slice(2);
  }

  // If original had explicit '+' prefix, trust its country code (removing trunk (0) if present)
  if (trimmed.startsWith("+")) {
    digits = trimmed.replace(/\+/g, "").replace(/\(0\)/g, "").replace(/\D/g, "");
    return digits;
  }

  const loc = `${country || ""} ${city || ""}`.toLowerCase();

  // Local numbers starting with single '0'
  if (digits.startsWith("0")) {
    if (loc.includes("ireland") || loc.includes("dublin") || loc.includes("cork") || loc.includes("galway") || loc.includes("limerick")) {
      return "353" + digits.slice(1);
    }
    if (loc.includes("uk") || loc.includes("united kingdom") || loc.includes("london") || loc.includes("manchester") || loc.includes("birmingham") || loc.includes("glasgow")) {
      return "44" + digits.slice(1);
    }
    if (loc.includes("bangladesh") || loc.includes("dhaka") || loc.includes("chittagong") || loc.includes("sylhet")) {
      return "88" + digits; // 017... -> 88017...
    }
    if (loc.includes("australia") || loc.includes("sydney") || loc.includes("melbourne")) {
      return "61" + digits.slice(1);
    }
    // Heuristics by length/pattern when location isn't specified
    if (digits.length === 11 && /^01[3-9]\d{8}$/.test(digits)) {
      return "88" + digits; // Bangladesh mobile
    }
    if (digits.length === 11 && (digits.startsWith("07") || digits.startsWith("02") || digits.startsWith("01"))) {
      return "44" + digits.slice(1); // UK standard
    }
    if ((digits.length === 9 || digits.length === 10) && (digits.startsWith("01") || digits.startsWith("08"))) {
      return "353" + digits.slice(1); // Ireland Dublin/mobile
    }
  }

  // US / Canada 10-digit number
  if (digits.length === 10 && !digits.startsWith("0")) {
    return "1" + digits;
  }

  return digits;
}

async function quickUpdateWhatsAppStatus(leadId, newStatus) {
  try {
    const res = await fetch(`/api/leads/${leadId}/whatsapp-verification`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: newStatus, notes: "Updated via quick inline check" })
    });
    if (res.ok) {
      loadLeads();
      fetchCrmStats();
    }
  } catch (err) {
    console.error("Quick WhatsApp status update failed:", err);
  }
}

async function openWhatsAppOutreachById(leadId) {
  try {
    const res = await fetch(`/api/leads/${leadId}`);
    if (!res.ok) return;
    const lead = await res.json();
    const cleanPhone = normalizePhoneDigits(lead.phone, lead.country, lead.city);

    if (!cleanPhone) {
      alert("No valid phone number available for this business.");
      return;
    }

    const waUrl = `https://wa.me/${cleanPhone}`;
    window.open(waUrl, "_blank", "noopener,noreferrer");

    // Also open WhatsApp status verification modal so user can record if chat opened
    openWhatsAppVerification(lead.id);
  } catch (err) {
    console.error("WhatsApp launch error:", err);
  }
}

async function openWhatsAppVerification(leadId) {
  try {
    const res = await fetch(`/api/leads/${leadId}`);
    if (!res.ok) return;
    const lead = await res.json();

    document.getElementById("waLeadId").value = lead.id;
    document.getElementById("waBizName").textContent = lead.business_name;
    document.getElementById("waPhoneDisplay").textContent = lead.phone || "No phone";
    document.getElementById("waStatusSelect").value = lead.whatsapp_status || "Available / Chat Opens";
    document.getElementById("waNotesInput").value = lead.whatsapp_notes || "";

    openModal("modalVerifyWhatsApp");
  } catch (err) {
    alert("Error: " + err);
  }
}

async function openWaLinkForCurrentLead() {
  const leadId = document.getElementById("waLeadId").value;
  if (!leadId) return;
  const res = await fetch(`/api/leads/${leadId}`);
  if (!res.ok) return;
  const lead = await res.json();
  const digits = normalizePhoneDigits(lead.phone, lead.country, lead.city);
  if (digits) {
    const waUrl = `https://wa.me/${digits}`;
    window.open(waUrl, "_blank", "noopener,noreferrer");
  }
}

async function submitWhatsAppVerification() {
  const leadId = document.getElementById("waLeadId").value;
  const status = document.getElementById("waStatusSelect").value;
  const notes = document.getElementById("waNotesInput").value.trim();

  try {
    const res = await fetch(`/api/leads/${leadId}/whatsapp-verification`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, notes })
    });
    const data = await res.json();
    if (data.success) {
      closeModal("modalVerifyWhatsApp");
      loadLeads();
      fetchCrmStats();
    }
  } catch (err) {
    alert("Error: " + err);
  }
}

// ==========================================
// 6. ADVERTISING VERIFICATION WORKSPACE & MODAL
// ==========================================

async function loadAdsVerificationList() {
  const tbody = document.getElementById("adsVerificationTableBody");
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; color:var(--text-muted);">Loading advertising verification records...</td></tr>`;

  try {
    const res = await fetch("/api/leads?limit=150");
    if (!res.ok) return;
    const data = await res.json();
    const leads = data.leads || [];

    if (leads.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; color:var(--text-muted);">No leads found. Add leads to verify advertising.</td></tr>`;
      return;
    }

    tbody.innerHTML = leads.map(l => {
      const gClass = getAdBadgeClass(l.google_ads_status);
      const mClass = getAdBadgeClass(l.meta_ads_status);
      const hasWeb = l.website && l.website !== "NOT AVAILABLE";

      return `
        <tr>
          <td>
            <strong style="color:#fff;">${escapeHtml(l.business_name)}</strong>
            <div style="font-size:11px; color:var(--text-muted);">${escapeHtml(l.category || 'Local Business')}</div>
          </td>
          <td>
            ${hasWeb ? `
              <a href="${escapeHtml(l.website)}" target="_blank" rel="noopener noreferrer" style="color:var(--accent-emerald); font-weight:600; text-decoration:none;">
                ${escapeHtml(l.normalized_domain || 'visit')}
              </a>
            ` : `<span style="color:var(--text-muted); font-size:11px;">Not available</span>`}
          </td>
          <td>
            <span class="ad-badge ${gClass}" onclick="openAdsVerification(${l.id}, 'Google')">
              ${escapeHtml(l.google_ads_status || 'Not Checked')}
            </span>
          </td>
          <td>
            <span class="ad-badge ${mClass}" onclick="openAdsVerification(${l.id}, 'Meta')">
              ${escapeHtml(l.meta_ads_status || 'Not Checked')}
            </span>
          </td>
          <td>
            <span style="font-size:11px; font-weight:700; color:var(--accent-cyan); font-family:var(--font-mono);">
              ${escapeHtml(l.ads_summary || 'NEEDS REVIEW')}
            </span>
          </td>
          <td>
            <div style="display:flex; gap:6px;">
              <button class="btn-tool" style="padding:3px 8px; font-size:11px;" onclick="openAdsVerification(${l.id}, 'Google')">
                Check Google
              </button>
              <button class="btn-tool btn-accent" style="padding:3px 8px; font-size:11px;" onclick="openAdsVerification(${l.id}, 'Meta')">
                Check Meta
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="color:var(--error); padding:20px;">Error loading ads list: ${err}</td></tr>`;
  }
}

async function openAdsVerification(leadId, platform) {
  try {
    const res = await fetch(`/api/leads/${leadId}`);
    if (!res.ok) return;
    const lead = await res.json();

    document.getElementById("adLeadId").value = lead.id;
    document.getElementById("adPlatform").value = platform.toLowerCase();
    document.getElementById("verifyAdsModalTitle").innerHTML = `${platform} Ads Verification &mdash; <span style="color:#fff;">${escapeHtml(lead.business_name)}</span>`;
    document.getElementById("adBizName").textContent = lead.business_name;
    document.getElementById("adTargetDomain").textContent = lead.normalized_domain || lead.website || "No website domain";

    const isGoogle = platform.toLowerCase() === "google";
    const currentStatus = isGoogle ? (lead.google_ads_status || "Not Checked") : (lead.meta_ads_status || "Not Checked");
    const currentAdvName = isGoogle ? (lead.google_advertiser_name || lead.business_name) : (lead.meta_advertiser_name || lead.business_name);
    const currentEvidence = isGoogle ? (lead.google_evidence_url || "") : (lead.meta_evidence_url || "");
    const currentNotes = isGoogle ? (lead.google_ads_notes || "") : (lead.meta_ads_notes || "");

    document.getElementById("adStatusSelect").value = currentStatus;
    document.getElementById("adAdvertiserName").value = currentAdvName;
    document.getElementById("adEvidenceUrl").value = currentEvidence;
    document.getElementById("adNotes").value = currentNotes;

    openModal("modalVerifyAds");
  } catch (err) {
    alert("Error: " + err);
  }
}

async function openOfficialAdLibrarySearch() {
  const leadId = document.getElementById("adLeadId").value;
  const platform = document.getElementById("adPlatform").value;
  if (!leadId) return;

  const res = await fetch(`/api/leads/${leadId}`);
  if (!res.ok) return;
  const lead = await res.json();

  const domain = lead.normalized_domain || "";
  const bizName = lead.business_name || "";

  let targetUrl = "";
  if (platform === "google") {
    // Google Ads Transparency Center search
    const query = domain || bizName;
    targetUrl = `https://adstransparency.google.com/?region=anywhere&domain=${encodeURIComponent(query)}`;
  } else {
    // Meta Ad Library search
    const query = domain || bizName;
    targetUrl = `https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=ALL&q=${encodeURIComponent(query)}`;
  }

  try {
    await fetch("/api/browser-open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: targetUrl })
    });
  } catch (err) {
    window.open(targetUrl, "_blank");
  }
}

async function submitAdsVerification() {
  const leadId = document.getElementById("adLeadId").value;
  const platform = document.getElementById("adPlatform").value;
  const status = document.getElementById("adStatusSelect").value;
  const advertiser_name = document.getElementById("adAdvertiserName").value.trim();
  const evidence_url = document.getElementById("adEvidenceUrl").value.trim();
  const notes = document.getElementById("adNotes").value.trim();

  try {
    const res = await fetch(`/api/leads/${leadId}/ads-verification`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        platform,
        status,
        advertiser_name,
        evidence_url,
        notes
      })
    });
    const data = await res.json();
    if (data.success) {
      closeModal("modalVerifyAds");
      loadLeads();
      loadAdsVerificationList();
      fetchCrmStats();
    }
  } catch (err) {
    alert("Save error: " + err);
  }
}

// ==========================================
// 7. FOLLOW-UPS TODAY DASHBOARD & REMINDERS
// ==========================================

async function loadFollowupsDue() {
  const todaySub = document.getElementById("todayDateSubtitle");
  const now = new Date();
  if (todaySub) {
    todaySub.textContent = now.toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "short", day: "numeric" });
  }

  const overdueGrid = document.getElementById("overdueCardsGrid");
  const dueTodayGrid = document.getElementById("dueTodayCardsGrid");
  const dueTomorrowGrid = document.getElementById("dueTomorrowCardsGrid");
  const emptyState = document.getElementById("emptyFollowupsState");

  try {
    const res = await fetch("/api/reminders/due");
    if (!res.ok) return;
    const data = await res.json();

    const overdue = data.overdue || [];
    const today = data.due_today || [];
    const tomorrow = data.due_tomorrow || [];

    document.getElementById("overdueCountBadge").textContent = overdue.length;
    document.getElementById("dueTodayCountBadge").textContent = today.length;
    document.getElementById("dueTomorrowCountBadge").textContent = tomorrow.length;

    // Overdue cards
    if (overdue.length > 0) {
      document.getElementById("overdueSection").style.display = "block";
      overdueGrid.innerHTML = overdue.map(r => renderReminderCard(r, "overdue")).join("");
    } else {
      document.getElementById("overdueSection").style.display = "none";
      overdueGrid.innerHTML = "";
    }

    // Due Today cards
    if (today.length > 0) {
      document.getElementById("dueTodaySection").style.display = "block";
      dueTodayGrid.innerHTML = today.map(r => renderReminderCard(r, "today")).join("");
    } else {
      document.getElementById("dueTodaySection").style.display = "none";
      dueTodayGrid.innerHTML = "";
    }

    // Due Tomorrow cards
    if (tomorrow.length > 0) {
      document.getElementById("dueTomorrowSection").style.display = "block";
      dueTomorrowGrid.innerHTML = tomorrow.map(r => renderReminderCard(r, "tomorrow")).join("");
    } else {
      document.getElementById("dueTomorrowSection").style.display = "none";
      dueTomorrowGrid.innerHTML = "";
    }

    if (overdue.length === 0 && today.length === 0 && tomorrow.length === 0) {
      emptyState.style.display = "block";
    } else {
      emptyState.style.display = "none";
    }
  } catch (err) {
    console.error("Error loading reminders:", err);
  }
}

function renderReminderCard(rem, typeClass) {
  const bizName = rem.business_name || "Prospect";
  const category = rem.category || "Local Business";
  const phone = rem.phone || "";
  const email = rem.email || "";

  return `
    <div class="action-card ${typeClass}">
      <div class="action-card-header">
        <div>
          <div class="action-card-title">${escapeHtml(bizName)}</div>
          <div class="action-card-cat">${escapeHtml(category)} &bull; Status: <strong style="color:var(--accent-cyan);">${escapeHtml(rem.crm_status || 'NEW')}</strong></div>
        </div>
        <span class="action-card-date">${escapeHtml(rem.reminder_date)}</span>
      </div>

      <p style="font-size:12px; color:#CBD5E1; margin:4px 0;">
        ${escapeHtml(rem.description || 'Follow-up is due.')}
      </p>

      <div class="action-card-btns">
        ${phone && phone !== 'NOT AVAILABLE' ? `
          <button class="btn-tool" style="background:#25D366; color:#042416; font-weight:700; border:none;" onclick="openWhatsAppOutreachById(${rem.lead_id})">
            Chat WA
          </button>
        ` : ''}

        ${email && email !== 'NOT AVAILABLE' ? `
          <a href="mailto:${escapeHtml(email)}" class="btn-tool" style="text-decoration:none;">
            Email
          </a>
        ` : ''}

        <button class="btn-tool btn-accent" onclick="openLogOutreachForLead(${rem.lead_id})">
          Log Sent
        </button>

        <button class="btn-tool" onclick="completeReminder(${rem.id})">
          Done ✓
        </button>

        <button class="btn-tool" onclick="snoozeReminder(${rem.id}, 1)">
          +1 Day
        </button>

        <button class="btn-tool" onclick="snoozeReminder(${rem.id}, 3)">
          +3 Days
        </button>
      </div>
    </div>
  `;
}

async function completeReminder(remId) {
  try {
    const res = await fetch(`/api/reminders/${remId}/complete`, { method: "POST" });
    const data = await res.json();
    if (data.success) {
      loadFollowupsDue();
      fetchCrmStats();
    }
  } catch (err) {
    alert("Error: " + err);
  }
}

async function snoozeReminder(remId, days) {
  try {
    const res = await fetch(`/api/reminders/${remId}/snooze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ days })
    });
    const data = await res.json();
    if (data.success) {
      loadFollowupsDue();
      fetchCrmStats();
    }
  } catch (err) {
    alert("Error: " + err);
  }
}

// ==========================================
// 8. LOG OUTREACH SENT (DAY 0 -> DAY 3 -> DAY 5)
// ==========================================

async function openLogOutreachForLead(leadId) {
  try {
    const res = await fetch(`/api/leads/${leadId}`);
    if (!res.ok) return;
    const lead = await res.json();

    document.getElementById("logLeadId").value = lead.id;
    document.getElementById("logOutreachTitle").innerHTML = `Log Outreach Sent &mdash; <span style="color:#fff;">${escapeHtml(lead.business_name)}</span>`;
    
    // Set default date to today
    const today = new Date().toISOString().split("T")[0];
    document.getElementById("logDateSent").value = today;

    // Suggest default channel
    const hasPhone = lead.phone && lead.phone !== "NOT AVAILABLE";
    document.getElementById("logChannel").value = hasPhone ? "WhatsApp" : "Email";

    // Suggest message type based on followup count
    const fCount = lead.followup_count || 0;
    const msgTypeEl = document.getElementById("logMessageType");
    if (fCount === 0) {
      msgTypeEl.value = "First Outreach";
    } else if (fCount === 1) {
      msgTypeEl.value = "Follow-up #1";
    } else {
      msgTypeEl.value = "Follow-up #2";
    }

    autoSuggestNextFollowupDate();
    document.getElementById("logNote").value = "";

    openModal("modalLogOutreach");
  } catch (err) {
    alert("Error loading lead: " + err);
  }
}

function autoSuggestNextFollowupDate() {
  const msgType = document.getElementById("logMessageType").value;
  const sentDateStr = document.getElementById("logDateSent").value || new Date().toISOString().split("T")[0];
  const sentDate = new Date(sentDateStr);

  let daysToAdd = 3;
  if (msgType === "First Outreach") {
    daysToAdd = cachedSettings.followup_interval_1 || 3;
  } else if (msgType === "Follow-up #1") {
    daysToAdd = cachedSettings.followup_interval_2 || 5;
  } else {
    daysToAdd = 7;
  }

  const nextDate = new Date(sentDate);
  nextDate.setDate(nextDate.getDate() + daysToAdd);
  document.getElementById("logNextFollowupDate").value = nextDate.toISOString().split("T")[0];
}

async function submitLogOutreach() {
  const leadId = document.getElementById("logLeadId").value;
  const date_sent = document.getElementById("logDateSent").value;
  const channel = document.getElementById("logChannel").value;
  const message_type = document.getElementById("logMessageType").value;
  const next_followup_date = document.getElementById("logNextFollowupDate").value;
  const note = document.getElementById("logNote").value.trim();

  if (!date_sent) {
    alert("Please select the date sent.");
    return;
  }

  try {
    const res = await fetch("/api/outreach/log", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        lead_id: leadId,
        date_sent,
        channel,
        message_type,
        next_followup_date,
        note
      })
    });
    const data = await res.json();
    if (data.success) {
      closeModal("modalLogOutreach");
      loadLeads();
      loadFollowupsDue();
      fetchCrmStats();
    } else {
      alert("Error saving outreach: " + (data.error || "Unknown error"));
    }
  } catch (err) {
    alert("Save error: " + err);
  }
}

// ==========================================
// 9. LEAD DETAILS & CONTACT HISTORY TIMELINE
// ==========================================

async function openLeadDetail(id) {
  try {
    const res = await fetch(`/api/leads/${id}`);
    if (!res.ok) return;
    const lead = await res.json();
    currentDetailLead = lead;

    document.getElementById("editLeadId").value = lead.id;
    document.getElementById("leadDetailTitle").innerHTML = `Lead #${lead.id} &mdash; <span style="color:#fff;">${escapeHtml(lead.business_name)}</span>`;
    document.getElementById("detailBizHeading").textContent = lead.business_name;
    document.getElementById("detailServiceHeading").textContent = `${lead.category || 'Local Business'} &bull; Discovered: ${lead.research_date || 'Recent'}`;

    document.getElementById("editName").value = lead.business_name || "";
    document.getElementById("editCategory").value = lead.category || "";
    document.getElementById("editPhone").value = lead.phone !== "NOT AVAILABLE" ? (lead.phone || "") : "";
    document.getElementById("editEmail").value = lead.email !== "NOT AVAILABLE" ? (lead.email || "") : "";
    document.getElementById("editWebsite").value = lead.website !== "NOT AVAILABLE" ? (lead.website || "") : "";
    document.getElementById("editCrmStatus").value = lead.crm_status || "NEW";
    document.getElementById("editNotes").value = lead.notes || "";

    // Message drafts
    document.getElementById("editWaDraft").value = lead.whatsapp_draft || "";
    document.getElementById("editEmailBodyDraft").value = lead.email_body_draft || "";

    // Contact history timeline
    loadLeadTimeline(lead.id);

    openModal("modalLeadDetail");
  } catch (err) {
    alert("Error loading lead details: " + err);
  }
}

async function loadLeadTimeline(leadId) {
  const container = document.getElementById("detailTimelineContainer");
  if (!container) return;
  container.innerHTML = "<p style='color:var(--text-muted); font-size:11px;'>Loading outreach history...</p>";

  try {
    const res = await fetch(`/api/leads/${leadId}/history`);
    if (!res.ok) return;
    const data = await res.json();
    const history = data.history || [];

    if (history.length === 0) {
      container.innerHTML = "<p style='color:var(--text-muted); font-size:11.5px;'>No outreach logged yet for this lead.</p>";
      return;
    }

    container.innerHTML = history.map(h => `
      <div class="timeline-entry">
        <span class="timeline-entry-date">${escapeHtml(h.contact_date)}</span>
        <div class="timeline-entry-content">
          <div>
            <span class="timeline-entry-channel">${escapeHtml(h.channel)}</span>
            <span style="color:var(--text-secondary); font-size:11.5px; margin-left:6px;">(${escapeHtml(h.message_type)})</span>
          </div>
          ${h.notes ? `<div class="timeline-entry-note">${escapeHtml(h.notes)}</div>` : ''}
        </div>
      </div>
    `).join("");
  } catch (err) {
    container.innerHTML = "<p style='color:var(--error); font-size:11px;'>Failed to load timeline.</p>";
  }
}

async function saveLeadDetails() {
  const id = document.getElementById("editLeadId").value;
  const payload = {
    business_name: document.getElementById("editName").value.trim(),
    category: document.getElementById("editCategory").value.trim(),
    phone: document.getElementById("editPhone").value.trim() || "NOT AVAILABLE",
    email: document.getElementById("editEmail").value.trim() || "NOT AVAILABLE",
    website: document.getElementById("editWebsite").value.trim() || "NOT AVAILABLE",
    crm_status: document.getElementById("editCrmStatus").value,
    outreach_status: document.getElementById("editCrmStatus").value,
    whatsapp_draft: document.getElementById("editWaDraft").value,
    email_body_draft: document.getElementById("editEmailBodyDraft").value,
    notes: document.getElementById("editNotes").value.trim()
  };

  try {
    const res = await fetch(`/api/leads/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      closeModal("modalLeadDetail");
      loadLeads();
      fetchCrmStats();
    }
  } catch (err) {
    alert("Update error: " + err);
  }
}

function openWhatsAppOutreach(lead) {
  if (!lead) return;
  openWhatsAppOutreachById(lead.id);
}

function openEmailOutreach(lead) {
  if (!lead || !lead.email || lead.email === "NOT AVAILABLE") {
    alert("No valid email address for this business.");
    return;
  }
  const subject = encodeURIComponent(lead.email_subject_draft || `Question regarding ${lead.business_name}`);
  const body = encodeURIComponent(lead.email_body_draft || "");
  window.location.href = `mailto:${lead.email}?subject=${subject}&body=${body}`;
}

function copyDraft(textareaId) {
  const el = document.getElementById(textareaId);
  if (!el || !el.value) return;
  navigator.clipboard.writeText(el.value).then(() => {
    alert("Draft copied to clipboard! You can paste and send it directly.");
  }).catch(err => {
    el.select();
    document.execCommand("copy");
    alert("Draft copied to clipboard!");
  });
}

// ==========================================
// 10. SETTINGS & DESKTOP REMINDERS
// ==========================================

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    if (!res.ok) return;
    const settings = await res.json();
    cachedSettings.followup_interval_1 = parseInt(settings.followup_interval_1 || "3", 10);
    cachedSettings.followup_interval_2 = parseInt(settings.followup_interval_2 || "5", 10);
    cachedSettings.reminders_enabled = settings.reminders_enabled !== "0";

    const int1El = document.getElementById("settingInterval1");
    const int2El = document.getElementById("settingInterval2");
    const remEl = document.getElementById("settingRemindersEnabled");
    if (int1El) int1El.value = cachedSettings.followup_interval_1;
    if (int2El) int2El.value = cachedSettings.followup_interval_2;
    if (remEl) remEl.checked = cachedSettings.reminders_enabled;
  } catch (err) {
    console.error("Error loading settings:", err);
  }
}

async function saveSettings() {
  const int1 = parseInt(document.getElementById("settingInterval1").value, 10) || 3;
  const int2 = parseInt(document.getElementById("settingInterval2").value, 10) || 5;
  const remEl = document.getElementById("settingRemindersEnabled");
  const remEnabled = remEl ? (remEl.checked ? "1" : "0") : "1";

  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        followup_interval_1: int1,
        followup_interval_2: int2,
        reminders_enabled: remEnabled
      })
    });
    const data = await res.json();
    if (data.success) {
      cachedSettings.followup_interval_1 = int1;
      cachedSettings.followup_interval_2 = int2;
      cachedSettings.reminders_enabled = remEnabled === "1";
      alert("Follow-up sequence and reminder settings successfully updated.");
    }
  } catch (err) {
    alert("Save error: " + err);
  }
}

async function testNotification() {
  try {
    const res = await fetch("/api/reminders/test", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      alert("Dispatched native Windows notification! Check your Windows taskbar notification area.");
    }
  } catch (err) {
    alert("Notification trigger error: " + err);
  }
}

// ==========================================
// 11. LEAD FINDER MISSION ORCHESTRATION
// ==========================================

function updateQueryPreview() {
  const kwEl = document.getElementById("inputKeywords");
  const cityEl = document.getElementById("inputCity");
  const zipEl = document.getElementById("inputZip");
  const maxEl = document.getElementById("inputMaxResults");
  if (!kwEl || !cityEl) return;

  const kw = kwEl.value.split("\n").filter(k => k.trim());
  const city = cityEl.value.trim();
  const zip = zipEl ? zipEl.value.trim() : "";
  const rawMax = maxEl ? maxEl.value.trim() : "";
  const maxVal = rawMax === "" ? 0 : parseInt(rawMax, 10);

  const countBadge = document.getElementById("searchesReadyBadge");
  if (countBadge) {
    countBadge.textContent = `${kw.length} search${kw.length === 1 ? '' : 'es'} ready`;
  }

  const previewBox = document.getElementById("searchPreviewBox");
  const limitLabel = maxVal <= 0 ? "⚡ ALL available leads" : `max ${maxVal} results`;
  if (previewBox) {
    if (kw.length > 0) {
      const loc = [city, zip].filter(Boolean).join(" ");
      previewBox.innerHTML = `Maps & Open Data will search: <span>"${escapeHtml(kw[0])} in ${escapeHtml(loc || 'target location')}"</span> (${limitLabel}, ${kw.length} queued)`;
    } else {
      previewBox.innerHTML = `Maps & Open Data will search: <span>"Enter keywords above"</span>`;
    }
  }
}

async function deployAgent() {
  const keywords = document.getElementById("inputKeywords").value;
  const city = document.getElementById("inputCity").value;
  const postal_code = document.getElementById("inputZip").value.trim();
  const rawMax = document.getElementById("inputMaxResults").value.trim();
  const max_results = rawMax === "" ? 0 : parseInt(rawMax, 10);
  const hunt_emails = document.getElementById("chkHuntEmails").checked;
  const auto_dedup = document.getElementById("chkAutoDedup").checked;

  if (!keywords.trim()) {
    alert("Please enter at least one business type / keyword.");
    return;
  }

  let cleanCity = city.trim();
  let detectedCountry = "";
  if (cleanCity.includes(",")) {
    const parts = cleanCity.split(",").map(p => p.trim()).filter(Boolean);
    if (parts.length >= 2) {
      detectedCountry = parts[parts.length - 1];
      cleanCity = parts.slice(0, -1).join(", ");
    }
  }

  try {
    const res = await fetch("/api/mission/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        keywords,
        city: cleanCity,
        postal_code,
        country: detectedCountry,
        max_results,
        hunt_emails,
        auto_dedup
      })
    });
    const data = await res.json();
    if (!data.success) {
      alert(data.error || "Unable to launch mission.");
    } else {
      setTimeout(() => {
        loadLeads();
        fetchCrmStats();
      }, 1500);
    }
  } catch (err) {
    alert("Network error starting mission: " + err);
  }
}

async function togglePauseMission() {
  if (activeMissionState === "RUNNING") {
    await fetch("/api/mission/pause", { method: "POST" });
  } else if (activeMissionState === "PAUSED") {
    await fetch("/api/mission/resume", { method: "POST" });
  }
  fetchTelemetry();
}

async function stopMission() {
  await fetch("/api/mission/stop", { method: "POST" });
  fetchTelemetry();
  loadLeads();
  fetchCrmStats();
}

// ==========================================
// 12. CSV / EXCEL IMPORT WIZARD
// ==========================================

function openImportModal() {
  document.getElementById("importMappingSection").style.display = "none";
  document.getElementById("importSummarySection").style.display = "none";
  document.getElementById("btnExecuteImport").style.display = "none";
  document.getElementById("csvFileInput").value = "";
  openModal("modalImport");
}

async function handleFileSelected(input) {
  if (!input.files || input.files.length === 0) return;
  const file = input.files[0];

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/import/preview", {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    if (!data.success) {
      alert("Error parsing file: " + (data.error || "Unknown error"));
      return;
    }
    renderImportPreview(data.preview);
  } catch (err) {
    alert("Error uploading file: " + err);
  }
}

function renderImportPreview(preview) {
  currentStagedToken = preview.token;
  const mappingSection = document.getElementById("importMappingSection");
  mappingSection.style.display = "block";
  document.getElementById("btnExecuteImport").style.display = "inline-flex";

  const headers = preview.headers;
  const suggested = preview.suggested_mapping || {};

  const appFields = [
    { key: "business_name", label: "Business Name *" },
    { key: "category", label: "Category" },
    { key: "phone", label: "Phone Number" },
    { key: "email", label: "Email Address" },
    { key: "website", label: "Official Website" },
    { key: "address", label: "Street Address" },
    { key: "city", label: "City" },
    { key: "postal_code", label: "Postal / Zip Code" },
    { key: "crm_status", label: "CRM Status" },
    { key: "notes", label: "Notes" }
  ];

  const grid = document.getElementById("mappingControlsGrid");
  grid.innerHTML = appFields.map(f => {
    const currentMatch = suggested[f.key] || "";
    return `
      <div class="field-group">
        <label class="field-label">${f.label}</label>
        <select class="input-control" data-app-field="${f.key}">
          <option value="">-- Do Not Import --</option>
          ${headers.map(h => `
            <option value="${escapeHtml(h)}" ${h === currentMatch ? 'selected' : ''}>${escapeHtml(h)}</option>
          `).join("")}
        </select>
      </div>
    `;
  }).join("");

  const previewTable = document.getElementById("previewTable");
  const pRows = preview.preview_rows || [];
  let tableHtml = "<thead><tr>" + headers.map(h => `<th style="padding:6px; border:1px solid #1E293B; color:var(--accent-cyan);">${escapeHtml(h)}</th>`).join("") + "</tr></thead><tbody>";
  pRows.forEach(r => {
    tableHtml += "<tr>" + headers.map(h => `<td style="padding:4px 6px; border:1px solid #1E293B; color:#CBD5E1;">${escapeHtml(r[h] || '')}</td>`).join("") + "</tr>";
  });
  tableHtml += "</tbody>";
  previewTable.innerHTML = tableHtml;
}

async function executeImport() {
  if (!currentStagedToken) return;

  const mapping = {};
  const selects = document.querySelectorAll("#mappingControlsGrid select");
  selects.forEach(s => {
    const appField = s.getAttribute("data-app-field");
    const chosenHeader = s.value;
    if (chosenHeader) mapping[appField] = chosenHeader;
  });

  if (!mapping["business_name"]) {
    alert("Please map the 'Business Name' field to a valid column in your file.");
    return;
  }

  try {
    const res = await fetch("/api/import/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token: currentStagedToken,
        mapping: mapping
      })
    });
    const data = await res.json();
    if (!data.success) {
      alert("Import failed: " + (data.error || "Unknown error"));
      return;
    }

    document.getElementById("importMappingSection").style.display = "none";
    document.getElementById("btnExecuteImport").style.display = "none";
    
    const summarySec = document.getElementById("importSummarySection");
    summarySec.style.display = "block";
    document.getElementById("importSummaryText").innerHTML = `
      Successfully imported <strong>${data.imported_unique}</strong> unique leads.<br>
      Flagged <strong>${data.flagged_duplicates}</strong> potential duplicates for review.<br>
      Skipped ${data.invalid_rows_count} invalid empty rows.
    `;

    loadLeads();
    fetchCrmStats();
  } catch (err) {
    alert("Import execution error: " + err);
  }
}

// ==========================================
// 13. DUPLICATE REVIEW & MERGING
// ==========================================

async function openDuplicateModal() {
  openModal("modalDuplicates");
  const container = document.getElementById("duplicatePairsContainer");
  container.innerHTML = "<p style='color:var(--text-muted);'>Scanning for duplicates...</p>";

  try {
    const res = await fetch("/api/duplicates");
    const data = await res.json();
    renderDuplicates(data.duplicates || []);
  } catch (err) {
    container.innerHTML = "<p style='color:var(--error);'>Error scanning duplicates.</p>";
  }
}

function renderDuplicates(dupes) {
  const container = document.getElementById("duplicatePairsContainer");
  const btnFooter = document.getElementById("btnMergeAllDuplicates");
  const btnHeader = document.getElementById("btnMergeAllHeader");

  if (dupes.length === 0) {
    if (btnFooter) btnFooter.style.display = "none";
    if (btnHeader) btnHeader.style.display = "none";
    container.innerHTML = `
      <div style="text-align:center; padding:30px; color:var(--accent-emerald);">
        <h4>✓ Zero Duplicates Detected</h4>
        <p style="font-size:12px; color:var(--text-muted); margin-top:4px;">All leads in your master database have distinct domains, phones, and locations.</p>
      </div>
    `;
    return;
  }

  if (btnFooter) {
    btnFooter.style.display = "inline-flex";
    btnFooter.textContent = `⚡ Merge All (${dupes.length}) in 1 Click`;
  }
  if (btnHeader) {
    btnHeader.style.display = "inline-flex";
    btnHeader.textContent = `⚡ Merge All (${dupes.length}) in 1 Click`;
  }

  const topBanner = `
    <div style="display:flex; justify-content:space-between; align-items:center; background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.4); padding:12px 16px; border-radius:8px;">
      <div>
        <strong style="color:#34D399; font-size:13px;">Found ${dupes.length} Duplicate Pair${dupes.length === 1 ? '' : 's'}</strong>
        <div style="font-size:11.5px; color:var(--text-secondary); margin-top:2px;">Click once to automatically merge all duplicate pairs while preserving phones, emails, websites, and notes.</div>
      </div>
      <button class="btn-tool btn-accent" style="padding:8px 16px; font-weight:700; font-size:12.5px;" onclick="mergeAllDuplicates()">
        ⚡ Merge All (${dupes.length}) in 1 Click
      </button>
    </div>
  `;

  container.innerHTML = topBanner + dupes.map((pair, idx) => {
    const raw1 = pair.lead1;
    const raw2 = pair.lead2;
    const n1 = (raw1.business_name || "").trim().toLowerCase();
    const n2 = (raw2.business_name || "").trim().toLowerCase();
    const swap = n1.startsWith("http") && !n2.startsWith("http");
    const l1 = swap ? raw2 : raw1;
    const l2 = swap ? raw1 : raw2;
    return `
      <div class="card-panel" style="background:#091422; border:1px solid rgba(245,158,11,0.3); padding:14px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
          <span style="font-size:11px; font-weight:700; color:var(--warning); text-transform:uppercase;">
            Candidate #${idx + 1}: ${escapeHtml(pair.reason)}
          </span>
          <button class="btn-tool btn-accent" onclick="mergeDuplicatePair(${l1.id}, ${l2.id})">
            Merge into #${l1.id}
          </button>
        </div>

        <div class="dupe-compare-grid">
          <div class="dupe-card">
            <span class="dupe-card-title">Record #${l1.id} (Primary)</span>
            <div class="dupe-field"><span>Name:</span> <strong>${escapeHtml(l1.business_name)}</strong></div>
            <div class="dupe-field"><span>Phone:</span> <strong>${escapeHtml(l1.phone || 'N/A')}</strong></div>
            <div class="dupe-field"><span>Email:</span> <strong>${escapeHtml(l1.email || 'N/A')}</strong></div>
            <div class="dupe-field"><span>Website:</span> <strong>${escapeHtml(l1.website || 'N/A')}</strong></div>
            <div class="dupe-field"><span>City:</span> <strong>${escapeHtml(l1.city || 'N/A')}</strong></div>
          </div>

          <div class="dupe-card">
            <span class="dupe-card-title">Record #${l2.id} (Secondary)</span>
            <div class="dupe-field"><span>Name:</span> <strong>${escapeHtml(l2.business_name)}</strong></div>
            <div class="dupe-field"><span>Phone:</span> <strong>${escapeHtml(l2.phone || 'N/A')}</strong></div>
            <div class="dupe-field"><span>Email:</span> <strong>${escapeHtml(l2.email || 'N/A')}</strong></div>
            <div class="dupe-field"><span>Website:</span> <strong>${escapeHtml(l2.website || 'N/A')}</strong></div>
            <div class="dupe-field"><span>City:</span> <strong>${escapeHtml(l2.city || 'N/A')}</strong></div>
          </div>
        </div>
      </div>
    `;
  }).join("");
}

async function mergeAllDuplicates() {
  try {
    const res = await fetch("/api/duplicates/merge-all", {
      method: "POST",
      headers: { "Content-Type": "application/json" }
    });
    const data = await res.json();
    if (data.success) {
      if (data.dedup_history_id) {
        window.lastDedupHistoryId = data.dedup_history_id;
        const undoBtn = document.getElementById("btnUndoLastMerge");
        if (undoBtn) undoBtn.style.display = "inline-flex";
      }
      openDuplicateModal();
      loadLeads();
      fetchCrmStats();
    } else {
      alert("Bulk merge failed: " + (data.error || "Unknown error"));
    }
  } catch (err) {
    alert("Error merging all duplicates: " + err);
  }
}

async function mergeDuplicatePair(primaryId, secondaryId) {
  try {
    const res = await fetch("/api/duplicates/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        primary_id: primaryId,
        secondary_id: secondaryId,
        reason: "User Confirmed in Duplicate Review"
      })
    });
    const data = await res.json();
    if (data.success) {
      window.lastDedupHistoryId = data.dedup_history_id;
      const undoBtn = document.getElementById("btnUndoLastMerge");
      if (undoBtn && data.dedup_history_id) {
        undoBtn.style.display = "inline-flex";
      }
      openDuplicateModal();
      loadLeads();
      fetchCrmStats();
    } else {
      alert("Merge failed: " + data.error);
    }
  } catch (err) {
    alert("Error merging: " + err);
  }
}

async function undoLastMerge() {
  if (!window.lastDedupHistoryId) return;
  try {
    const res = await fetch("/api/duplicates/undo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dedup_history_id: window.lastDedupHistoryId })
    });
    const data = await res.json();
    if (data.success) {
      window.lastDedupHistoryId = null;
      const undoBtn = document.getElementById("btnUndoLastMerge");
      if (undoBtn) undoBtn.style.display = "none";
      openDuplicateModal();
      loadLeads();
      fetchCrmStats();
    } else {
      alert("Undo merge failed.");
    }
  } catch (err) {
    alert("Error undoing merge: " + err);
  }
}

// ==========================================
// 14. LOCAL DATABASE BACKUPS & INTEGRITY
// ==========================================

async function openBackupModal() {
  openModal("modalBackups");
  loadBackupList();
  checkDbIntegrity();
}

async function loadBackupList() {
  const container = document.getElementById("backupListContainer");
  container.innerHTML = "<p style='color:var(--text-muted); font-size:11px;'>Loading backups...</p>";

  try {
    const res = await fetch("/api/database/backups");
    const data = await res.json();
    const backups = data.backups || [];
    if (backups.length === 0) {
      container.innerHTML = "<p style='color:var(--text-muted); font-size:11px;'>No backups created yet.</p>";
      return;
    }
    container.innerHTML = backups.map(b => `
      <div style="display:flex; justify-content:space-between; align-items:center; background:#07111F; padding:8px 10px; border-radius:6px; border:1px solid #1E293B;">
        <div>
          <strong style="color:var(--accent-cyan); font-size:11.5px;">${escapeHtml(b.filename)}</strong>
          <span style="color:var(--text-muted); font-size:10.5px; margin-left:8px;">(${(b.size_bytes / 1024).toFixed(1)} KB &bull; ${escapeHtml(b.created_at || '')})</span>
        </div>
        <button class="btn-tool" style="padding:3px 8px; font-size:10.5px;" onclick="restoreBackup(${JSON.stringify(b.path).replace(/"/g, '&quot;')})">Preview &amp; Restore</button>
      </div>
    `).join("");
  } catch (err) {
    container.innerHTML = "<p style='color:var(--error); font-size:11px;'>Failed to load backups.</p>";
  }
}

async function createBackup() {
  try {
    const res = await fetch("/api/database/backup");
    const data = await res.json();
    if (data.success) {
      loadBackupList();
    }
  } catch (err) {
    alert("Backup creation error: " + err);
  }
}

async function restoreBackup(path) {
  try {
    const prevRes = await fetch(`/api/database/backup-preview?path=${encodeURIComponent(path)}`);
    const prevData = await prevRes.json();
    let confirmMsg = "Are you sure you want to restore this database snapshot? A pre-restore safety backup of your current state will be saved automatically.";
    if (prevData.success && prevData.preview) {
      const p = prevData.preview;
      if (!p.healthy) {
        alert("Backup integrity check failed: " + p.status);
        return;
      }
      confirmMsg = `Restore Verified Backup: ${p.filename}?\n\n` +
        `• Integrity Check: OK\n` +
        `• Created: ${p.created_at}\n` +
        `• Leads: ${p.leads_count}\n` +
        `• Sticky Notes: ${p.notes_count}\n` +
        `• Contact History: ${p.contact_history_count}\n` +
        `• Reminders: ${p.reminders_count}\n\n` +
        `A safety backup of your current database will be created automatically before restoring.`;
    }
    if (!confirm(confirmMsg)) return;

    const res = await fetch("/api/database/restore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup_path: path })
    });
    const data = await res.json();
    if (data.success) {
      alert("Database successfully restored.");
      closeModal("modalBackups");
      loadLeads();
      fetchCrmStats();
      loadDailyNotes();
      loadFollowupsDue();
    } else {
      alert("Restore failed: " + data.error);
    }
  } catch (err) {
    alert("Restore error: " + err);
  }
}

async function checkDbIntegrity() {
  const el = document.getElementById("dbIntegrityStatus");
  if (!el) return;
  el.textContent = "Checking...";
  try {
    const res = await fetch("/api/database/integrity");
    const data = await res.json();
    if (data.healthy) {
      el.textContent = "OK (PRAGMA integrity_check passed)";
      el.style.color = "var(--accent-emerald)";
    } else {
      el.textContent = "Warning: " + data.status;
      el.style.color = "var(--error)";
    }
  } catch (err) {
    el.textContent = "Failed to run check";
  }
}

// Clean Server Shutdown
async function shutdownServer() {
  if (!confirm("Shut down the local Pinora workspace server?")) return;
  try {
    await fetch("/api/shutdown", { method: "POST" });
    document.body.innerHTML = `
      <div style="display:flex; height:100vh; align-items:center; justify-content:center; flex-direction:column; background:#07111F; color:#F8FAFC; font-family:sans-serif;">
        <h2 style="color:#10B981; margin-bottom:8px;">Workspace Safely Stopped</h2>
        <p style="color:#94A3B8;">All local database transactions committed. You can close this browser tab.</p>
      </div>
    `;
  } catch (err) {
    window.close();
  }
}

// Modal Helpers & Utilities
function openModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.classList.add("open");
}

function closeModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.classList.remove("open");
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ==========================================
// 15. MY DAILY NOTES & SMART TEXT-TO-CRM INTERPRETER (SECTIONS 8, 9, 10, 11, 12, 13)
// ==========================================

let currentNotesRange = 'TODAY';
let cachedDailyNotes = [];
let noteFilterDebounceTimer = null;
let currentInterpPayload = null;

async function loadDailyNotes() {
  const container = document.getElementById("notesGridContainer");
  const emptyState = document.getElementById("emptyNotesState");
  const searchInput = document.getElementById("notesSearchInput");
  const searchVal = searchInput ? searchInput.value.trim() : "";

  if (!container) return;

  try {
    const params = new URLSearchParams();
    if (currentNotesRange) params.append("range", currentNotesRange);
    if (searchVal) params.append("search", searchVal);

    const res = await fetch(`/api/notes?${params.toString()}`);
    if (!res.ok) return;
    const data = await res.json();
    cachedDailyNotes = data.notes || [];

    // Update ALL badge
    const badgeAll = document.getElementById("allNotesCountBadge");
    if (badgeAll && data.total_all !== undefined) badgeAll.textContent = data.total_all;

    // Update Tab badge
    const badgeTab = document.getElementById("tabBadgeNotes");
    if (badgeTab) badgeTab.textContent = cachedDailyNotes.length;

    renderNotesGrid(cachedDailyNotes);
  } catch (err) {
    console.error("Failed to load daily notes:", err);
  }
}

function debounceFilterNotes() {
  clearTimeout(noteFilterDebounceTimer);
  noteFilterDebounceTimer = setTimeout(loadDailyNotes, 300);
}

function filterNotesByRange(rangeKey) {
  currentNotesRange = rangeKey;
  const tabIds = {
    'TODAY': 'noteTabToday',
    'YESTERDAY': 'noteTabYesterday',
    'THIS WEEK': 'noteTabWeek',
    'OLDER NOTES': 'noteTabOlder',
    'ALL': 'noteTabAll'
  };

  Object.entries(tabIds).forEach(([key, id]) => {
    const btn = document.getElementById(id);
    if (!btn) return;
    if (key === rangeKey) btn.classList.add("active");
    else btn.classList.remove("active");
  });

  loadDailyNotes();
}

function renderNotesGrid(notes) {
  const container = document.getElementById("notesGridContainer");
  const emptyState = document.getElementById("emptyNotesState");
  if (!container) return;

  if (notes.length === 0) {
    container.innerHTML = "";
    if (emptyState) emptyState.style.display = "block";
    return;
  }

  if (emptyState) emptyState.style.display = "none";

  container.innerHTML = notes.map(note => {
    const isPinned = !!note.is_pinned;
    const statusClass = note.status === "PROCESSED" ? "status-processed" : "status-draft";
    const statusLabel = note.status || "DRAFT";
    
    // Parse lead numbers detected or linked
    let leadBadges = [];
    if (note.linked_lead_ids) {
      try {
        const ids = typeof note.linked_lead_ids === "string" ? JSON.parse(note.linked_lead_ids) : note.linked_lead_ids;
        if (Array.isArray(ids) && ids.length > 0) {
          leadBadges = ids.map(id => `#${String(id).padStart(4, '0')}`);
        }
      } catch (e) {}
    }

    // Format display date
    const dateStr = note.created_at ? note.created_at.slice(0, 16).replace("T", " ") : "";

    return `
      <div class="note-card ${isPinned ? 'is-pinned' : ''}" id="noteCard_${note.id}">
        <div class="note-card-header">
          <div class="note-card-title-group">
            <h4 class="note-card-title">${escapeHtml(note.title || 'Outreach Note')}</h4>
            <div class="note-card-meta">
              <span>${escapeHtml(dateStr)}</span>
              <span>&bull;</span>
              <span style="color:var(--accent-cyan); font-weight:600;">${escapeHtml(note.category || 'Outreach')}</span>
            </div>
          </div>
          <button class="note-pin-btn ${isPinned ? 'pinned' : ''}" onclick="togglePinNote(${note.id})" title="${isPinned ? 'Unpin note' : 'Pin note to top'}">
            ${isPinned ? '★' : '☆'}
          </button>
        </div>

        <div class="note-card-body">${escapeHtml(note.content || '')}</div>

        ${leadBadges.length > 0 ? `
          <div class="note-card-leads">
            <span style="font-size:10.5px; color:var(--text-muted); font-weight:600;">LEADS:</span>
            ${leadBadges.map(b => `<span class="note-lead-tag">${escapeHtml(b)}</span>`).join("")}
          </div>
        ` : ''}

        <div class="note-card-footer">
          <span class="note-status-badge ${statusClass}">${escapeHtml(statusLabel)}</span>
          <div class="note-actions-group">
            <button class="btn-note-action btn-parse-action" onclick="parseDailyNote(${note.id})" title="Parse note and preview CRM updates">
              ⚡ PARSE FOR CRM
            </button>
            <button class="btn-note-action" onclick="copyNoteText(${note.id})" title="Copy note text to clipboard">
              📋
            </button>
            <button class="btn-note-action" onclick="openEditNoteModal(${note.id})" title="Edit note">
              ✎
            </button>
            <button class="btn-note-action" onclick="deleteDailyNote(${note.id})" title="Delete note" style="color:#F87171;">
              🗑
            </button>
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function openNewNoteModal() {
  document.getElementById("dailyNoteModalTitle").textContent = "📝 New Daily Outreach Sticky Note";
  document.getElementById("noteEditId").value = "";
  document.getElementById("noteInputTitle").value = "";
  document.getElementById("noteInputContent").value = "";
  document.getElementById("noteInputCategory").value = "Outreach";
  document.getElementById("noteInputIsPinned").checked = false;
  document.getElementById("noteCreatedAtHint").textContent = "";
  document.getElementById("btnDeleteNoteFromModal").style.display = "none";
  openModal("modalDailyNote");
}

async function openEditNoteModal(noteId) {
  try {
    const res = await fetch(`/api/notes/${noteId}`);
    if (!res.ok) return;
    const note = await res.json();

    document.getElementById("dailyNoteModalTitle").textContent = "📝 Edit Outreach Sticky Note";
    document.getElementById("noteEditId").value = note.id;
    document.getElementById("noteInputTitle").value = note.title || "";
    document.getElementById("noteInputContent").value = note.content || "";
    document.getElementById("noteInputCategory").value = note.category || "Outreach";
    document.getElementById("noteInputIsPinned").checked = !!note.is_pinned;
    document.getElementById("noteCreatedAtHint").textContent = note.created_at ? `Created: ${note.created_at.slice(0, 16)}` : "";
    document.getElementById("btnDeleteNoteFromModal").style.display = "inline-flex";

    openModal("modalDailyNote");
  } catch (err) {
    alert("Error loading note: " + err);
  }
}

async function saveDailyNote(shouldParse = false) {
  const noteId = document.getElementById("noteEditId").value;
  const title = document.getElementById("noteInputTitle").value.trim();
  const content = document.getElementById("noteInputContent").value.trim();
  const category = document.getElementById("noteInputCategory").value;
  const is_pinned = document.getElementById("noteInputIsPinned").checked ? 1 : 0;

  if (!content) {
    alert("Please enter note content.");
    return;
  }

  const payload = {
    title: title || (content.slice(0, 30) + (content.length > 30 ? "..." : "")),
    content,
    category,
    is_pinned
  };

  try {
    let savedId = noteId;
    if (noteId) {
      const res = await fetch(`/api/notes/${noteId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!data.success) throw new Error(data.error || "Update failed");
    } else {
      const res = await fetch("/api/notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      const createdId = data.id || data.note_id;
      if (!createdId) throw new Error(data.error || "Creation failed");
      savedId = createdId;
    }

    closeModal("modalDailyNote");
    loadDailyNotes();
    fetchCrmStats();

    if (shouldParse && savedId) {
      parseDailyNote(savedId);
    }
  } catch (err) {
    alert("Error saving note: " + err.message);
  }
}

function saveAndInterpretDailyNote() {
  saveDailyNote(true);
}

async function togglePinNote(noteId) {
  try {
    const res = await fetch(`/api/notes/${noteId}/pin`, { method: "POST" });
    const data = await res.json();
    if (data.success) {
      loadDailyNotes();
    }
  } catch (err) {
    console.error("Pin toggle failed:", err);
  }
}

async function deleteDailyNote(noteId) {
  if (!confirm("Are you sure you want to delete this note?")) return;
  try {
    const res = await fetch(`/api/notes/${noteId}`, { method: "DELETE" });
    const data = await res.json();
    if (data.success) {
      loadDailyNotes();
      fetchCrmStats();
    }
  } catch (err) {
    alert("Error deleting note: " + err);
  }
}

function deleteNoteFromModal() {
  const noteId = document.getElementById("noteEditId").value;
  if (noteId) {
    closeModal("modalDailyNote");
    deleteDailyNote(noteId);
  }
}

async function copyNoteText(noteId) {
  const note = cachedDailyNotes.find(n => n.id === noteId);
  if (!note || !note.content) return;
  try {
    await navigator.clipboard.writeText(note.content);
    alert("Note text copied to clipboard!");
  } catch (err) {
    const ta = document.createElement("textarea");
    ta.value = note.content;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    alert("Note text copied to clipboard!");
  }
}

// -------------------------------------------------------------
// TEXT-TO-CRM INTERPRETATION & PREVIEW (SECTIONS 10, 11, 12, 13)
// -------------------------------------------------------------

async function parseDailyNote(noteId) {
  try {
    const res = await fetch(`/api/notes/${noteId}/parse`, { method: "POST" });
    if (!res.ok) {
      const errData = await res.json();
      alert("Note parse failed: " + (errData.error || res.statusText));
      return;
    }
    const rawData = await res.json();
    const interp = rawData.interpretation || rawData;
    interp.note_id = rawData.note_id || noteId;
    currentInterpPayload = interp;
    renderNoteInterpretationPreview(interp);
    openModal("modalNoteInterpretation");
  } catch (err) {
    alert("Error parsing note: " + err);
  }
}

function resolveEffectiveLeadAction(leadId, currentStatus, interp) {
  const actions = interp.actions || [];
  let channel = interp.channel || "WhatsApp";
  let targetStatus = interp.is_plan_only ? currentStatus : "CONTACTED";
  let followupDate = interp.followup_date || "—";
  let isPlan = !!interp.is_plan_only;

  for (const act of actions) {
    const lids = act.lead_ids || [];
    if (lids.includes(leadId)) {
      if (act.channel) channel = act.channel;
      if (act.is_plan_only || act.action_type === "PLAN_ONLY") {
        isPlan = true;
        targetStatus = `${currentStatus} (Plan Only)`;
        followupDate = act.followup_date || followupDate;
      } else {
        isPlan = false;
        if (act.outcome_status) {
          targetStatus = act.outcome_status;
          if (act.outcome_status === "NOT INTERESTED" || act.outcome_status === "REPLIED") {
            followupDate = "—";
          } else if (act.followup_date) {
            followupDate = act.followup_date;
          }
        } else {
          targetStatus = "CONTACTED";
          followupDate = act.followup_date || "—";
        }
      }
    }
  }
  return { channel, targetStatus, followupDate, isPlan };
}

function renderNoteInterpretationPreview(data) {
  document.getElementById("interpNoteId").value = data.note_id;
  document.getElementById("interpRawNoteText").textContent = `"${data.raw_text || ''}"`;
  document.getElementById("interpDetectedChannel").textContent = data.channel || "WhatsApp";
  document.getElementById("interpDetectedType").textContent = data.is_plan_only ? "PLAN ONLY (Future Task)" : "COMPLETED OUTREACH";
  document.getElementById("interpFollowupDate").textContent = data.followup_date || "Not Scheduled";
  document.getElementById("interpLeadCount").textContent = (data.resolved_leads || []).length;
  document.getElementById("interpTableCountBadge").textContent = `${(data.resolved_leads || []).length} leads`;

  // Notice banner based on is_plan_only (Section 13 Outreach Safety)
  const noticeBanner = document.getElementById("interpActionNotice");
  if (data.is_plan_only) {
    noticeBanner.className = "interp-notice-banner plan-only";
    noticeBanner.innerHTML = `
      <strong>⚠️ OUTREACH SAFETY DETECTED (FUTURE PLAN):</strong> This note describes a future plan (e.g. <em>"tomorrow I will email..."</em>). 
      Leads will <strong>NOT</strong> be marked as contacted. Only a scheduled reminder date will be saved so you don't record false outreach.
    `;
  } else {
    noticeBanner.className = "interp-notice-banner";
    noticeBanner.innerHTML = `
      <strong>✓ COMPLETED OUTREACH DETECTED:</strong> The system identified outreach actions via <strong>${escapeHtml(data.channel || 'WhatsApp')}</strong>. 
      Completed leads will be updated to <strong>CONTACTED</strong> (or <strong>INTERESTED</strong> / <strong>NOT INTERESTED</strong> per line) and next follow-up scheduled.
    `;
  }

  // Missing leads warning
  const missingWarning = document.getElementById("interpMissingWarning");
  const missingList = document.getElementById("interpMissingList");
  const missingArr = data.missing_ids || data.missing_lead_ids || [];
  if (missingArr.length > 0) {
    missingWarning.style.display = "block";
    missingList.textContent = missingArr.map(id => `#${String(id).padStart(4, '0')}`).join(", ") + " (these IDs do not exist in your database)";
  } else {
    missingWarning.style.display = "none";
  }

  // Populate resolved leads table with per-lead checkboxes and resolved action preview
  const tbody = document.getElementById("interpLeadsTableBody");
  const leads = data.resolved_leads || [];
  if (leads.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:18px; color:var(--text-muted);">No existing database leads matched the IDs mentioned in this note.</td></tr>`;
  } else {
    tbody.innerHTML = leads.map(l => {
      const currentSt = l.crm_status || l.current_status || "READY TO CONTACT";
      const eff = resolveEffectiveLeadAction(l.id, currentSt, data);
      return `
        <tr>
          <td>
            <label style="display:inline-flex; align-items:center; gap:6px; cursor:pointer;">
              <input type="checkbox" class="interp-lead-chk" value="${l.id}" checked>
              <span class="lead-id-badge">${escapeHtml(l.lead_number)}</span>
            </label>
          </td>
          <td>
            <strong style="color:#fff;">${escapeHtml(l.business_name)}</strong>
            <div style="font-size:11px; color:var(--text-muted);">${escapeHtml(l.category || '')} &bull; ${escapeHtml(eff.channel)}</div>
          </td>
          <td><span style="color:var(--text-secondary); font-size:11px;">${escapeHtml(currentSt)}</span></td>
          <td><strong style="color:${eff.isPlan ? 'var(--warning)' : 'var(--accent-emerald)'}; font-size:11.5px;">${escapeHtml(eff.targetStatus)}</strong></td>
          <td><span style="color:var(--warning); font-family:var(--font-mono); font-size:11.5px;">${escapeHtml(eff.followupDate)}</span></td>
        </tr>
      `;
    }).join("");
  }

  // Reset override section
  document.getElementById("interpOverrideSection").style.display = "none";
  document.getElementById("overrideChannel").value = data.channel || "WhatsApp";
  document.getElementById("overrideFollowupDate").value = data.followup_date || "";
}

function toggleInterpEditMode() {
  const section = document.getElementById("interpOverrideSection");
  if (!section) return;
  const isHidden = section.style.display === "none";
  section.style.display = isHidden ? "block" : "none";
}

async function applyInterpretedCrmUpdates() {
  if (!currentInterpPayload) return;
  const noteId = currentInterpPayload.note_id;

  const overrideSection = document.getElementById("interpOverrideSection");
  const isOverrideOpen = overrideSection && overrideSection.style.display !== "none";
  const overrideChannel = document.getElementById("overrideChannel").value;
  const overrideDate = document.getElementById("overrideFollowupDate").value;

  const chkNodes = document.querySelectorAll(".interp-lead-chk:checked");
  const selectedIds = chkNodes.length > 0
    ? Array.from(chkNodes).map(cb => parseInt(cb.value, 10))
    : (currentInterpPayload.targeted_lead_ids || currentInterpPayload.lead_ids || []);
  const selectedSet = new Set(selectedIds);

  const rawActions = currentInterpPayload.actions || [];
  let actionsToSend = [];
  if (rawActions.length > 0) {
    actionsToSend = rawActions.map(act => {
      const copy = Object.assign({}, act);
      copy.lead_ids = (act.lead_ids || []).filter(id => selectedSet.has(id));
      if (isOverrideOpen || rawActions.length === 1) {
        if (overrideChannel && rawActions.length === 1) copy.channel = overrideChannel;
        if (overrideDate && !copy.is_plan_only && copy.outcome_status !== "NOT INTERESTED") {
          copy.followup_date = overrideDate;
        }
      }
      return copy;
    }).filter(a => a.lead_ids.length > 0);
  }

  const finalPayload = {
    actions: actionsToSend,
    channel: overrideChannel || currentInterpPayload.channel,
    followup_date: overrideDate || currentInterpPayload.followup_date,
    next_followup_date: overrideDate || currentInterpPayload.followup_date,
    lead_ids: selectedIds,
    is_plan_only: currentInterpPayload.is_plan_only
  };

  const btn = document.getElementById("btnApplyCrmUpdates");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Applying Updates...";
  }

  try {
    const res = await fetch(`/api/notes/${noteId}/apply-crm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(finalPayload)
    });
    const result = await res.json();
    if (!result.success) {
      alert("Failed to apply CRM updates: " + (result.error || "Unknown error"));
      return;
    }

    closeModal("modalNoteInterpretation");
    alert(`Success! Updated ${result.updated_count} leads in SQLite CRM and recorded activity logs.`);

    // Refresh CRM stats, leads table, notes, and reminders
    fetchCrmStats();
    loadLeads();
    loadDailyNotes();
    loadFollowupsDue();
  } catch (err) {
    alert("Error applying CRM updates: " + err);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Apply Updates ⚡";
    }
  }
}

// ==========================================
// 15. GOOGLE MAPS INSTANT EXTRACTOR HELPERS
// ==========================================

function openCurrentSearchInGoogleMaps() {
  const kwEl = document.getElementById("inputKeywords");
  const cityEl = document.getElementById("inputCity");
  const zipEl = document.getElementById("inputZip");

  let kw = "double glazing company";
  if (kwEl && kwEl.value.trim()) {
    const lines = kwEl.value.split("\n").map(l => l.trim()).filter(Boolean);
    if (lines.length > 0) kw = lines[0];
  }

  let location = "";
  if (cityEl && cityEl.value.trim()) location += cityEl.value.trim();
  if (zipEl && zipEl.value.trim()) location += (location ? " " : "") + zipEl.value.trim();

  const fullQuery = (kw + (location ? " " + location : "")).trim();
  const mapsUrl = `https://www.google.com/maps/search/${encodeURIComponent(fullQuery)}?hl=en`;
  window.open(mapsUrl, "_blank");
}

function openGmapsExtractorGuide() {
  const modal = document.getElementById("modalGmapsGuide");
  if (modal) {
    openModal("modalGmapsGuide");
  } else {
    alert("গুগল ম্যাপস থেকে ১-ক্লিকে লিড নেওয়ার ৩টি সহজ ধাপ:\n\n1. '⭐ 2. Drag to Bookmarks: ⚡ Extract to Pinora' বাটনটি টেনে আপনার ব্রাউজারের বুকমার্ক বারে রাখুন (Ctrl+Shift+B চাপলে বুকমার্ক বার দেখা যাবে)।\n2. '🗺️ 1. Open Search in Google Maps' বাটনে ক্লিক করে গুগল ম্যাপস পেজ ওপেন করুন।\n3. গুগল ম্যাপসে ফলাফল স্ক্রল করে নিচে নামান, এরপর বুকমার্ক বারের সেই '⚡ Extract to Pinora' বাটনে ক্লিক করুন! সব লিড সরাসরি Pinora CRM-এ সেভ হয়ে যাবে।");
  }
}
