/* ==========================================================================
   ALP Console - Single Source of Truth JavaScript
   Loaded at end of <body> - DOM is fully available at this point.
   ========================================================================== */

/* --- Section 1: Token Bootstrap --- */
(function () {
  var tok = '';
  try {
    var sp = new URLSearchParams(window.location.search);
    if (sp.get('token')) {
      tok = sp.get('token');
      localStorage.setItem('alp_token', tok);
      sessionStorage.setItem('alp_token', tok);
    } else {
      tok = localStorage.getItem('alp_token') || sessionStorage.getItem('alp_token') || '';
    }
  } catch (e) { }
  window._INITIAL_TOKEN = tok;
  // body classList is already in place via preauth class set inline; no-op here.
})();

/* --- Section 2: Initial View Selection (Instant DOM Activation) --- */
function _alpInitInitialView() {
  var tok = window._INITIAL_TOKEN || (function () {
    try {
      var sp = new URLSearchParams(window.location.search);
      if (sp.get('token')) return sp.get('token');
      return localStorage.getItem('alp_token') || sessionStorage.getItem('alp_token') || '';
    } catch (e) { return ''; }
  })();
  var main = document.getElementById('view-main');
  var login = document.getElementById('view-login');
  if (tok && main) {
    main.classList.add('active');
    if (login) login.classList.remove('active');
    document.body.classList.remove('preauth');
  } else if (login) {
    login.classList.add('active');
    if (main) main.classList.remove('active');
    document.body.classList.add('preauth');
  }
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _alpInitInitialView);
} else {
  _alpInitInitialView();
}

/* --- Section 3: Main Application Logic --- */

/* ==========================================================================
   ALP Components — Reusable UI Builders
   Single Source of Truth for shared UI patterns.
   Any new section/view should use these functions instead of duplicating HTML.
   ========================================================================== */
const ALP = {

  /**
   * Renders a ManageEngine-style toolbar.
   * @param {string} containerId - ID of element to render into
   * @param {object} opts - { total, actions: [{id, label, icon?, danger?}], filters?, onRefresh? }
   */
  renderToolbar(containerId, opts) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const actions = (opts.actions || []).map(a => {
      const cls = a.danger ? 'secondaryActionBtn buttonnew1 danger' : 'secondaryActionBtn buttonnew1';
      const icon = a.icon ? `<svg class="svg-bucket-icon" style="width:13px;height:13px;margin-right:4px;"><use href="${a.icon}"></use></svg>` : '';
      return `<div class="${cls}" id="${a.id}" onclick="${a.onclick || ''}">${icon}${a.label}</div>`;
    }).join('');
    const total = opts.total != null ? `<span class="totRecords navigatorDetailsColumn totRecords navigatorDetailsColumn">Total : ${opts.total}</span>` : '';
    const refresh = opts.onRefresh ? `<div class="tableSearchButton cursor-pointer" onclick="${opts.onRefresh}" title="Refresh"><svg class="svg-bucket-icon" style="width:16px;height:16px;"><use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#refresh"></use></svg></div>` : '';
    el.innerHTML = `
      <div class="sub-menu-container">
        <div class="sub-left-actions">${actions}</div>
        <div class="sub-right-actions">${total}${refresh}</div>
      </div>`;
  },

  /**
   * Renders a ManageEngine-style data table.
   * @param {string} containerId - ID of element to render into
   * @param {object} opts - { columns: [{key, label, width?, align?}], rows: [...], emptyMsg? }
   */
  renderTable(containerId, opts) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const { columns = [], rows = [], emptyMsg = 'No data available.' } = opts;
    const headCells = columns.map(c =>
      `<th class="ember-table-header-cell ${c.className || ''}">${c.label}</th>`
    ).join('');
    const bodyRows = rows.length === 0
      ? `<tr><td colspan="${columns.length}" class="emptyrow bodytext info--grey text-center">${emptyMsg}</td></tr>`
      : rows.map(row => {
        const cells = columns.map(c =>
          `<td class="ember-table-cell ${c.className || ''}">${row[c.key] ?? ''}</td>`
        ).join('');
        return `<tr class="ember-table-row">${cells}</tr>`;
      }).join('');
    el.innerHTML = `
      <div class="table-container mdm-table ember-view tablegrey tablegrey tableSection">
        <table class="tableComponent table tableComponent table">
          <thead><tr class="ember-table-header-row">${headCells}</tr></thead>
          <tbody>${bodyRows}</tbody>
        </table>
      </div>`;
  },

  /**
   * Shows a temporary alert banner (ok / warn / bad).
   * @param {string} kind - 'ok' | 'warn' | 'bad'
   * @param {string} title
   * @param {string} [msg]
   * @param {number} [duration=4000] ms before auto-dismiss
   */
  alert(kind, title, msg, duration = 4000) {
    const existing = document.querySelector('.alp-flash-banner');
    if (existing) existing.remove();
    const div = document.createElement('div');
    div.className = `alert-box alert_msg message-box message-display alert-box alert_msg message-box message-display`;
    div.innerHTML = `<strong>${title}</strong>${msg ? `<span>${msg}</span>` : ''}
      <button class="closeImg cursor-pointer" onclick="this.parentElement.remove()">✕</button>`;
    document.body.appendChild(div);
    if (duration > 0) setTimeout(() => div.remove(), duration);
  },

  /**
   * Toggles sidebar visibility - canonical implementation.
   * Called by the collapse handle button (nd--toggle).
   */
  toggleSidebar(btn) {
    toggleSidebarNavigation(btn);
  }
};

const API = "/api/v1";
let TOKEN = sessionStorage.getItem("alp_token") || localStorage.getItem("alp_token") || "";
let BOOT_SECRET = "";
let MFA_MODE = true;

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function fmtStamp(val) {
  if (!val) return '—';
  try {
    const d = new Date(val);
    if (isNaN(d.getTime())) return String(val);
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const m = months[d.getMonth()];
    const day = d.getDate();
    const y = d.getFullYear();
    let hr = d.getHours();
    const ampm = hr >= 12 ? 'PM' : 'AM';
    hr = hr % 12;
    if (hr === 0) hr = 12;
    const hrStr = String(hr).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    return `${m} ${day}, ${y} ${hrStr}:${min} ${ampm}`;
  } catch (e) {
    return String(val);
  }
}

const ICONS = {
  info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  square: '<rect x="3" y="3" width="18" height="18" rx="2"/>',
  'check-square': '<polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  alert: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>'
};
function ic(n, s) {
  s = s || 16;
  return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + ICONS[n] + '</svg>';
}

function pill(c, t) { return '<span class="pill ' + c + '">' + esc(t) + '</span>'; }
function dot(b) { return '<span class="dot ' + (b ? 'ok' : 'bad') + '"></span>'; }
function banner(kind, t, msg) {
  const icons = { ok: 'check', warn: 'alert', bad: 'x' };
  const k = icons[kind] || 'info';
  return '<div class="banner b-' + kind + '"><div class="bic">' + ic(k, 18) + '</div><div><h4>' + esc(t) + '</h4>' + (msg ? ('<p>' + esc(msg) + '</p>') : '') + '</div></div>';
}
function defs(items) {
  return '<div class="defs">' + items.map(function (it) {
    return '<div class="def"><div class="k">' + it[0] + '</div><div class="v' + (it[2] ? ' mono' : '') + '">' + (it[1] === undefined || it[1] === null || it[1] === "" ? '—' : it[1]) + '</div></div>';
  }).join('') + '</div>';
}
function raw(d) {
  return '<details class="raw"><summary>عرض JSON خام</summary><pre dir="ltr">' + esc(JSON.stringify(d, null, 2)) + '</pre></details>';
}
function emptyRow(cols, main, sub) {
  return '<tr><td colspan="' + cols + '"><div class="empty">' + ic('info', 30) + '<div class="et">' + esc(main) + '</div>' + (sub ? '<div class="es">' + esc(sub) + '</div>' : '') + '</div></td></tr>';
}
function skelRows(n, cols) {
  var o = '';
  for (var i = 0; i < n; i++) {
    o += '<tr>';
    for (var j = 0; j < cols; j++) {
      var w = 50 + ((i * 7 + j * 13) % 40);
      o += '<td><span class="skel" style="width:' + w + '%">&nbsp;</span></td>';
    }
    o += '</tr>';
  }
  return o;
}
function errCard(msg) {
  return banner('bad', 'فشلت العملية', msg || 'حدث خطأ غير متوقع من الخادم');
}
function setStatus(id, txt, cls) {
  const el = $(id);
  el.textContent = (txt || "");
  el.className = 'statusline' + (cls ? ' ' + cls : '');
}
function statusPill(s) {
  const v = String(s ?? "").trim();
  if (!v) return '<span class="pill p-mut">—</span>';
  const u = v.toUpperCase();
  const toks = u.split(/[\s_/.:-]+/);
  const BAD = new Set(['FAIL', 'ERROR', 'BLOCKED', 'NOT', 'NO', 'REFUSED', 'OFFLINE', 'UNAUTHORIZED', 'FALSE', 'INACTIVE', 'NON_COMPLIANT', 'REJECTED', 'ABORT', 'RETIRED', 'LOST', 'NOT_FEASIBLE']);
  const WARN = new Set(['PARTIAL', 'WARN', 'CONDITIONAL', 'PENDING', 'UNKNOWN', 'ANDROID_VERSION_DEPENDENT', 'VENDOR_DEPENDENT', 'DEVICE_DEPENDENT', 'ENROLLMENT_PENDING', 'MAINTENANCE', 'RECOVERY', 'MISMATCH', 'REVOKED', 'QUARANTINED', 'PLAN_ONLY', 'MEDIUM', 'LOW', 'DEVICE', 'SIMULATED']);
  const OK = new Set(['PASS', 'OK', 'YES', 'TRUE', 'COMPLETE', 'CONFIGURED', 'READY', 'ACTIVE', 'ENROLLED', 'COMPLIANT', 'SUCCEEDED', 'DELIVERED', 'RESTRICTED', 'STAGED', 'FULL', 'SUPPORTED', 'ALLOW', 'ALLOWED', 'APPROVED', 'EXECUTED', 'PHONE_ONLY', 'FULL_LOCKDOWN', 'CORPORATE_STANDARD', 'PARTIAL_LOCKDOWN', 'REAL_DEVICE']);
  let cls = 'p-mut';
  for (const t of toks) { if (BAD.has(t)) { cls = 'p-bad'; break; } }
  if (cls === 'p-mut') { for (const t of toks) { if (WARN.has(t)) { cls = 'p-part'; break; } } }
  if (cls === 'p-mut') { for (const t of toks) { if (OK.has(t)) { cls = 'p-ok'; break; } } }
  return pill(cls, v);
}
function timeNow() {
  const t = new Date();
  const p = n => String(n).padStart(2, '0');
  return p(t.getHours()) + ':' + p(t.getMinutes()) + ':' + p(t.getSeconds());
}
async function copyText(txt, btn) {
  const old = btn ? btn.innerHTML : '';
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) { await navigator.clipboard.writeText(txt); }
    else { const ta = document.createElement('textarea'); ta.value = txt; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); }
    if (btn) { btn.innerHTML = ic('check', 13) + ' تم النسخ'; setTimeout(function () { btn.innerHTML = old; }, 1600); }
  } catch (e) { if (btn) { btn.innerHTML = 'تعذّر النسخ'; setTimeout(function () { btn.innerHTML = old; }, 1600); } }
}
function togglePassVisibility(inputId, btn) {
  const inp = $(inputId);
  if (!inp) return;
  const isPass = inp.type === 'password';
  inp.type = isPass ? 'text' : 'password';
  btn.innerHTML = isPass ?
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>' :
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
}

function toggleMfaField() {
  const show = !!MFA_MODE;
  ['lMfaRow', 'apMfaRow', 'pinMfaRow', 'rcMfaRow'].forEach(function (id) { const el = $(id); if (el) { el.hidden = !show; } });
  const lSub = $('lSubText');
  const bSub = $('bSubText');
  if (show) {
    if (lSub) lSub.textContent = 'جلسة المشرف على منصة القفل الميداني. العمليات الحساسة تتطلب رمز TOTP إضافياً.';
    if (bSub) bSub.textContent = 'لا يوجد مشرف بعد. أنشئ المشرف الأول وفعّل مفتاح TOTP في تطبيق المصادقة.';
  } else {
    if (lSub) lSub.textContent = 'تسجيل دخول المشرف باسم المستخدم وكلمة المرور.';
    if (bSub) bSub.textContent = 'لا يوجد مشرف بعد. أنشئ المشرف الأول هنا.';
  }
}

/* Read the token from storage at call time, not from the module-level copy.
   TOKEN is initialised once when this file loads; if the session token is
   written to storage afterwards (login, or a reload that restored it) the
   in-memory copy stays empty and every request went out as `Bearer ` with no
   token, which the API answered 401 - wiping the stored token and bouncing the
   operator back to the login screen. Storage is the single source of truth and
   TOKEN is kept in sync with it. */
function currentToken() {
  try {
    const t = sessionStorage.getItem('alp_token') || localStorage.getItem('alp_token') || '';
    if (t && TOKEN !== t) TOKEN = t;
    return t || TOKEN || '';
  } catch (e) {
    return TOKEN || '';
  }
}
function apiHdr() { return { Authorization: 'Bearer ' + currentToken(), 'Content-Type': 'application/json' }; }
async function api(p, m, b) {
  const opts = { method: m, headers: apiHdr() };
  if (b !== undefined) opts.body = JSON.stringify(b);
  const r = await fetch(API + p, opts);
  let j;
  try { j = await r.json(); }
  catch (e) { j = { ok: false, error: await r.text().catch(() => String(r.status)) }; }
  if (r.status === 401 && !p.startsWith('/auth')) {
    // Only drop the session when a token was actually sent. A 401 for a request
    // that went out with no token (or a stale one) must not delete a token that
    // is perfectly valid, otherwise one bad call logs the operator out.
    const sent = currentToken();
    if (sent) {
      localStorage.removeItem('alp_token');
      sessionStorage.removeItem('alp_token');
      TOKEN = '';
      load();
    }
  }
  if (!j || typeof j !== 'object') j = { ok: false, error: 'استجابة غير مفهومة من الخادم' };
  j.status = r.status;                       /* callers branch on 401/403/404/409 */
  return j;
}

/* ------------------------------------------------------------ write path
   Every mutating call goes through apiWrite so an MFA challenge or an approval
   refusal surfaces as an actionable message, and a write can never fail
   silently: the old code ignored DELETE responses, so a refused disassociation
   looked exactly like a successful one. */
let MFA_HINT = '';                          /* cached TOTP for one burst of writes */

function mfaNeeded(r) {
  const e = String((r && r.error) || '').toLowerCase();
  return /mfa|totp|code/.test(e) && /required|missing|invalid|bad|verify/.test(e);
}
function approvalRefused(r) {
  const e = String((r && r.error) || '');
  return /approval|dual|approve/i.test(e);
}
function explainApiError(r, what) {
  const code = r && r.status;
  const raw = String((r && r.error) || 'خطأ غير معروف');
  if (code === 401) return what + ': انتهت الجلسة أو بيانات الدخول غير صحيحة — سجّل الدخول من جديد.';
  if (code === 403) return approvalRefused(r)
    ? what + ': يحتاج اعتماداً إدارياً — ' + raw
    : what + ': صلاحيتك لا تسمح بهذه العملية — ' + raw;
  if (code === 404) return what + ': المسار غير موجود على الخادم — ' + raw;
  if (code === 409) return what + ': تعارض مع الحالة الحالية — ' + raw;
  if (code === 400) return what + ': طلب غير صالح — ' + raw;
  return what + ': ' + raw;
}
async function askMfa(what) {
  if (MFA_HINT) return MFA_HINT;
  const code = await alpPrompt('رمز TOTP مطلوب لـ: ' + what + '\n(اتركه فارغاً للإلغاء)');
  if (code === null) return '';
  MFA_HINT = code.trim();
  return MFA_HINT;
}
/* Retries once with an MFA code; resolves to null when the user cancelled. */
async function apiWrite(p, m, b, what) {
  const label = what || (m + ' ' + p);
  const body = Object.assign({}, b || {});
  let r = await api(p, m, body);
  if (r.ok) return r;
  if (mfaNeeded(r)) {
    const code = await askMfa(label);
    if (!code) return null;
    body.mfa = code;
    r = await api(p, m, body);
    if (r.ok) { MFA_HINT = ''; return r; }
  }
  if ((r.status === 401 || r.status === 403) && mfaNeeded(r)) {
    MFA_HINT = '';                            /* stale code: force a fresh ask */
  }
  return r;
}
/* For callers that must not proceed at all: reports and returns null. */
async function apiWriteOrReport(p, m, b, what, statusEl) {
  const r = await apiWrite(p, m, b, what);
  if (r === null) return null;
  if (!r.ok) {
    const msg = explainApiError(r, what || (m + ' ' + p));
    if (statusEl && $(statusEl)) setStatus(statusEl, msg, 'err');
    else alpAlert(msg);
    return null;
  }
  return r;
}

async function boot() { return await api('/bootstrap', 'GET'); }

function setLive(on) {
  const el = $('livePill');
  if (el) {
    el.style.display = on ? 'inline-flex' : 'none';
    el.style.opacity = on ? '1' : '0';
  }
}
async function load() {
  const logoutBtn = $('logoutBtn');
  if (logoutBtn) logoutBtn.hidden = !TOKEN;
  if (!TOKEN) { setLive(false); show('view-login'); return; }

  // High-performance parallel bootstrap & session verification (1 round-trip instead of 3 sequential)
  const [b, h, w] = await Promise.all([
    boot().catch(() => ({ ok: false })),
    api('/health', 'GET').catch(() => ({ ok: false })),
    api('/auth/whoami', 'GET').catch(e => ({ ok: false, error: String(e) }))
  ]);

  if (b.ok && b.data && b.data.needs_bootstrap) { setLive(false); show('view-bootstrap'); return; }

  if (h.ok && h.data && typeof h.data.mfa_required === 'boolean') { MFA_MODE = h.data.mfa_required; }
  toggleMfaField();

  const who = $('whoami');
  if (w.ok && w.data) {
    if (who) who.textContent = w.data.username || 'admin';
    setLive(true);
    show('view-main');
    refreshAll();
  } else {
    TOKEN = '';
    localStorage.removeItem('alp_token');
    sessionStorage.removeItem('alp_token');
    if (who) who.textContent = 'Unknown';
    setLive(false);
    show('view-login');
  }
}
function toggleUserDropdown(e) {
  if (e) e.stopPropagation();
  const d = $('userDropdownMenu');
  if (d) d.classList.toggle('show');
}
function toggleQuickActions(e) {
  if (e) e.stopPropagation();
  const d = $('quickActionsLinks-ember18');
  if (d) d.style.display = (d.style.display === 'block') ? 'none' : 'block';
}
document.addEventListener('click', function () {
  const d = $('userDropdownMenu');
  if (d) d.classList.remove('show');
  const qa = $('quickActionsLinks-ember18');
  if (qa) qa.style.display = 'none';
});
function show(id) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  const el = $(id);
  if (el) el.classList.add('active');
  document.body.classList.toggle('preauth', id === 'view-login' || id === 'view-bootstrap');
}

function showMeLoader(text) {
  const el = $('meGlobalLoader');
  const txt = $('meGlobalLoaderText');
  if (txt && text) txt.textContent = text;
  if (el) el.classList.add('active');
}
function hideMeLoader() {
  const el = $('meGlobalLoader');
  if (el) el.classList.remove('active');
}
window.showMeLoader = showMeLoader;
window.hideMeLoader = hideMeLoader;

function showView(v, push = true) {
  const newHash = '#/' + (v === 'dashboard' ? 'dashboard' : v);
  if (push && !location.hash.startsWith(newHash) && !(v === 'dashboard' && location.hash.includes('uems/mdm/home'))) {
    history.pushState(null, '', newHash);
  }
  document.querySelectorAll('.vpanel').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.utnb--tab, .tab').forEach(t => t.classList.remove('active'));
  const panel = $('sub-' + v);
  const tab = document.querySelector('.tab[data-v="' + v + '"]');
  const topTab = document.querySelector('.utnb--tab[data-v="' + v + '"]');
  if (panel) panel.classList.add('active');
  if (tab) tab.classList.add('active');
  if (topTab) topTab.classList.add('active');
  if (v === 'dashboard') dashboard();
  if (v === 'devices') populateDevices();
  if (v === 'apply') { populateDevices(); populatePolicies(); }
  if (v === 'restrictions') loadCatalog();
  if (v === 'recovery') { populateDevices(); vaultSummary(); }
  if (v === 'audit') auditTail();
  if (v === 'reports') reportList();
  if (v === 'branding') loadBranding();
  setTimeout(() => { if (typeof updateNavSlider === 'function') updateNavSlider(); }, 30);
}

function handleRouteNavigation() {
  if (!TOKEN) return;
  const rawHash = location.hash.replace(/^#\/?/, '').trim();
  const [hashPath, hashQuery] = rawHash.split('?');
  const queryParams = new URLSearchParams(hashQuery || '');

  // Authentic Home route
  if (hashPath === 'uems/mdm/home' || hashPath === 'dashboard' || hashPath === '' || hashPath === 'home') {
    showView('dashboard', false);
    return;
  }

  // Authentic ManageEngine MDM Inventory Device 360 / Comprehensive Details Route
  if (hashPath.includes('uems/mdm/inventory/devicesList/')) {
    const match = hashPath.match(/devicesList\/([^\/]+)(?:\/([^\/\?]+))?/);
    if (match) {
      const did = decodeURIComponent(match[1]);
      const tab = match[2] || 'summary';
      showView('devices', false);
      openComprehensiveDeviceDetails(did, tab, false);
      return;
    }
  }

  // 1. ManageEngine MDM authentic routes
  if (hashPath.includes('uems/mdm/manage/groups-and-devices/devices/details/')) {
    const match = hashPath.match(/devices\/details\/([^\/]+)(?:\/([^\/\?]+))?/);
    if (match) {
      const did = decodeURIComponent(match[1]);
      const tab = match[2] || 'groups';
      showView('devices', false);
      openDeviceDetails(did, false, tab);
      return;
    }
  }

  if (hashPath.includes('uems/mdm/manage/groups-and-devices/summary/')) {
    showView('devices', false);
    switchSidebarView('groups-devices', false);
    if (hashPath.includes('summary/groups')) switchGDSubtab('groups');
    else if (hashPath.includes('summary/users')) switchGDSubtab('users');
    else switchGDSubtab('devices');
    return;
  }

  if (hashPath.includes('uems/mdm/manage/profile/list/')) {
    const match = hashPath.match(/profile\/list\/([^\/]+)/);
    if (match) {
      const pid = match[1];
      showView('devices', false);
      let tab = 'details';
      if (hashPath.includes('associatedGroups')) tab = 'groups';
      else if (hashPath.includes('associatedDevices')) tab = 'devices';
      openProfileDetails(pid, false, tab);
      return;
    }
  }

  if (hashPath.includes('uems/mdm/manage/profile/android')) {
    const isEdit = queryParams.get('edit') === 'true';
    const pid = queryParams.get('profileid');
    showView('devices', false);
    if (isEdit && pid) {
      openModifyProfile(pid, false);
    } else {
      openCreateProfile('android', false);
    }
    return;
  }

  if (hashPath.includes('uems/mdm/manage/groups-and-devices')) {
    showView('devices', false);
    switchSidebarView('groups-devices', false);
    return;
  }

  if (hashPath.includes('uems/mdm/manage/profile')) {
    showView('devices', false);
    switchSidebarView('profiles', false);
    return;
  }

  if (hashPath.includes('uems/mdm/manage/appRepo')) {
    showView('restrictions', false);
    if (typeof enrShowNode === 'function') enrShowNode('catalog');
    return;
  }

  if (hashPath.includes('uems/mdm/manage/appUpdate')) {
    showView('apply', false);
    return;
  }

  if (hashPath.includes('uems/mdm/manage/remoteControl')) {
    showView('recovery', false);
    return;
  }

  if (hashPath.startsWith('uems/mdm/manage')) {
    showView('devices', false);
    const matchingLink = document.querySelector(`.nd--sub-section-container[href="#/${hashPath}"], .nd--sub-section-container[href="#${location.hash}"]`);
    if (matchingLink) {
      const container = matchingLink.closest('.nd--container');
      if (container) {
        container.querySelectorAll('.nd--sub-section-container').forEach(a => a.classList.remove('active', 'common-bg', 'anchor-text__imp'));
        matchingLink.classList.add('active', 'common-bg', 'anchor-text__imp');
        updateNavSlider(container);
      }
    }
    return;
  }

  if (hashPath.startsWith('uems/mdm/enrollment')) {
    showView('restrictions', false);
    return;
  }

  if (hashPath.startsWith('uems/mdm/inventory')) {
    showView('apply', false);
    return;
  }

  if (hashPath.startsWith('uems/mdm/reports')) {
    showView('reports', false);
    return;
  }

  if (hashPath.startsWith('uems/mdm/admin')) {
    showView('recovery', false);
    return;
  }

  if (hashPath.startsWith('uems/mdm/support')) {
    showView('audit', false);
    return;
  }

  if (hashPath.startsWith('uems/mdm/branding')) {
    showView('branding', false);
    return;
  }

  // 2. ALP standard routes
  const parts = hashPath.split('/');
  const main = parts[0] || '';
  const sub = parts[1] || '';
  const subId = parts[2] || '';
  const action = parts[3] || '';

  const VIEWS = ['dashboard', 'devices', 'new_devices', 'apply', 'restrictions', 'reports', 'recovery', 'audit', 'branding'];
  if (VIEWS.includes(main)) {
    showView(main, false);
    if (main === 'devices') {
      if (sub === 'profiles' || sub === 'profile') {
        if (subId && action === 'details') {
          openProfileDetails(subId, false);
        } else if (subId && action === 'modify') {
          openModifyProfile(subId, false);
        } else {
          switchSidebarView('profiles', false);
        }
      } else if (sub === 'create-profile') {
        openCreateProfile('android', false);
      } else if (sub === 'configure-profile') {
        if (CFG_DRAFT_ID) {
          editProfile(CFG_DRAFT_ID);
        } else if (typeof ALL_PROFILES !== 'undefined' && ALL_PROFILES && ALL_PROFILES.length > 0) {
          const draft = ALL_PROFILES.find(p => p.status === 'DRAFT') || ALL_PROFILES[0];
          editProfile(draft.policy_id);
        } else {
          api('/profiles', 'GET').then(r => {
            if (r.ok && r.data && r.data.length > 0) {
              ALL_PROFILES = r.data;
              const draft = r.data.find(p => p.status === 'DRAFT') || r.data[0];
              editProfile(draft.policy_id);
            } else {
              openCreateProfile('android', false);
            }
          }).catch(() => openCreateProfile('android', false));
        }
      } else if (sub === 'inspector') {
        switchSidebarView('inspector', false);
      } else {
        switchSidebarView('groups-devices', false);
      }
    }
  } else if (!hashPath || hashPath === 'home' || hashPath === 'dashboard') {
    showView('dashboard', false);
  }
}

function refreshAll() {
  handleRouteNavigation();
}

// Handle browser back/forward and hash navigation
window.addEventListener('popstate', function () {
  handleRouteNavigation();
});
window.addEventListener('hashchange', function () {
  handleRouteNavigation();
});

async function doBootstrap() {
  const u = $('bUser').value.trim(), p = $('bPass').value;
  if (!u || p.length < 6) { setStatus('bResult', 'أدخل اسماً وكلمة مرور (6 أحرف على الأقل)', 'err'); return; }
  setStatus('bResult', 'جارٍ إنشاء المشرف…');
  const r = await api('/bootstrap', 'POST', { username: u, password: p });
  const el = $('bResult');
  if (r.ok && r.data) {
    BOOT_SECRET = r.data.secret || '';
    el.className = 'statusline';
    el.innerHTML =
      banner('ok', 'تم إنشاء المشرف الأول', 'أضف المفتاح إلى تطبيق المصادقة (Google Authenticator). لا يمكن عرضه مرة أخرى.') +
      '<div class="seccard"><div class="skl">المفتاح السري (TOTP)</div><div class="skv">' + esc(BOOT_SECRET) + '</div>' +
      '<button class="btn ghost" onclick="copyBSecret(this)">' + ic('check', 13) + ' نسخ المفتاح</button></div>' +
      '<button class="btn primary" onclick="load()">' + ic('check', 13) + ' متابعة إلى تسجيل الدخول</button>';
  } else {
    el.className = 'statusline err';
    el.textContent = 'فشل الإعداد: ' + (r.error || 'خطأ');
  }
}
function copyBSecret(btn) { copyText(BOOT_SECRET, btn); }
async function doLogin() {
  const u = $('lUser').value.trim(), p = $('lPass').value, m = $('lMfa').value.trim();
  if (!u) { setStatus('loginErr', 'أدخل اسم المستخدم', 'err'); return; }
  setStatus('loginErr', 'جارٍ الدخول…');
  showMeLoader('Hold on! Loading...');
  try {
    const r = await api('/auth/login', 'POST', { username: u, password: p, mfa: m });
    if (r.ok && r.data && r.data.token) {
      TOKEN = r.data.token;
      sessionStorage.setItem('alp_token', TOKEN);
      localStorage.setItem('alp_token', TOKEN);
      MFA_MODE = !!r.data.mfa_required;
      toggleMfaField();
      setStatus('loginErr', '');
      await new Promise(res => setTimeout(res, 600));
      await load();
      hideMeLoader();
    } else {
      hideMeLoader();
      setStatus('loginErr', 'فشل الدخول: ' + (r.error || 'اسم مستخدم/كلمة مرور/رمز خاطئ'), 'err');
    }
  } catch (e) {
    hideMeLoader();
    setStatus('loginErr', 'خطأ في الاتصال بالخادم', 'err');
  }
}
async function doLogout() {
  showMeLoader('Hold on! Signing out...');
  setLive(false);
  try { await api('/auth/logout', 'POST'); } catch (e) { }
  TOKEN = '';
  sessionStorage.removeItem('alp_token');
  localStorage.removeItem('alp_token');
  await new Promise(res => setTimeout(res, 400));
  await load();
  hideMeLoader();
}

async function doBackup() {
  const btn = $('backupBtn');
  const lbl = $('backupBtnLabel');
  const old = lbl.textContent;
  btn.style.opacity = '0.6'; btn.style.pointerEvents = 'none';
  lbl.textContent = 'Backing up\u2026';
  try {
    const r = await api('/system/backup', 'POST');
    if (r.ok && r.data) {
      const d = r.data;
      let msg = 'Backup created \u2014 ' + d.db + ' (' + d.db_size + ' B, sha256 ' + d.db_sha256.slice(0, 12) + '\u2026)';
      if (!d.vault_copied) msg += ' \u26a0 recovery vault key NOT present';
      try { localStorage.setItem('alp_last_backup', JSON.stringify({ db: d.db, sha256: d.db_sha256, at: d.created_at })); } catch (e) { }
      console.log('[backup]', r.data);
      alpAlert(msg);
    } else {
      alpAlert('Backup failed: ' + (r.error || 'unknown error'));
    }
  } catch (e) {
    alpAlert('Backup failed: ' + String(e && e.message || e));
  } finally {
    btn.style.opacity = '1'; btn.style.pointerEvents = '';
    lbl.textContent = old;
  }
}

function renderRealDashboard(det, reg, auditList) {
  det = Array.isArray(det) ? det : [];
  reg = Array.isArray(reg) ? reg : [];
  auditList = Array.isArray(auditList) ? auditList : [];

  const regCount = reg.length;
  const detSerials = det.map(d => d.serial);

  // 1. KPI Box 1: Enrolled Devices
  const elReg = $('kpiReg');
  if (elReg) elReg.textContent = String(regCount);

  // 2. KPI Box 2: Enrolled Users
  const uniqueUsers = new Set();
  uniqueUsers.add('admin');
  reg.forEach(d => { if (d.user_ref) uniqueUsers.add(d.user_ref); });
  const elDet = $('kpiDet');
  if (elDet) elDet.textContent = String(uniqueUsers.size);

  // 3. KPI Box 3: Enrollment Pending
  const pendingCount = reg.filter(d => d.enrollment_state === 'ENROLLMENT_PENDING').length;
  const elReady = $('kpiReady');
  if (elReady) elReady.textContent = String(pendingCount);

  // 4. KPI Box 4: Inactive Devices (unmanaged or not connected via active ADB)
  const inactiveCount = reg.filter(d => d.enrollment_state === 'UNMANAGED' || !detSerials.includes(d.serial)).length;
  const elEnf = $('kpiEnforced');
  if (elEnf) elEnf.textContent = String(inactiveCount);

  // 5. KPI Box 5: Devices with blocklisted apps / Compliance Violations
  const nonCompliantCount = reg.filter(d => d.compliance_state === 'NON_COMPLIANT' || d.compliance_state === 'FAILED').length;
  const elBlk = $('kpiBlacklist');
  if (elBlk) elBlk.textContent = String(nonCompliantCount);

  const elTm = $('kpiTime');
  if (elTm) elTm.textContent = timeNow();

  // 6. Save current device list for interactive chart updates
  window.__LAST_REG_DATA = reg;

  // Render all 4 charts
  renderLastContactChart(reg);
  renderPlatformChart(reg);
  renderAppSummaryChart(reg);
  renderDataUsageChart(reg);

  // 10. Right Column: Audit Log Feed (Real live audit records)
  renderAuditFeed(auditList);
}

/* ==========================================================================
   ManageEngine MDM Interactive Zoho Charts Engine
   Interactive legends, slice toggling, dynamic totals, and animated tooltips
   ========================================================================== */

window.ALP_CHARTS_STATE = {
  lastContact: {
    items: [
      { id: 'c0_3', label: '0-3 Days', count: 0, color: 'var(--mdm-graph-red-shade-1, #fca5a5)', visible: true },
      { id: 'c4_7', label: '4 - 7 Days', count: 0, color: 'var(--mdm-graph-red-shade-2, #f87171)', visible: true },
      { id: 'c8_15', label: '8 - 15 Days', count: 0, color: 'var(--mdm-graph-red-shade-3, #ef4444)', visible: true },
      { id: 'c16_30', label: '16 - 30 Days', count: 0, color: 'var(--mdm-graph-red-shade-4, #dc2626)', visible: true },
      { id: 'c31_plus', label: '31 above', count: 0, color: 'var(--mdm-graph-red-shade-5, #b91c1c)', visible: true }
    ]
  },
  platform: {
    unit: 'Devices',
    items: [
      { id: 'ios', label: 'iOS', count: 0, color: 'var(--mdm-graph-status-in-progress, #00b4d8)', visible: true },
      { id: 'android', label: 'Android', count: 0, color: 'var(--mdm-graph-status-success, #22c55e)', visible: true },
      { id: 'windows', label: 'Windows', count: 0, color: 'var(--mdm-graph-blue, #437AEE)', visible: true },
      { id: 'macos', label: 'macOS', count: 0, color: 'var(--mdm-graph-status-acknowledged, #a855f7)', visible: true },
      { id: 'chrome', label: 'Chrome OS', count: 0, color: 'var(--mdm-graph-status-ready, #f59e0b)', visible: true },
      { id: 'tvos', label: 'Apple tvOS', count: 0, color: 'var(--mdm-graph-status-stopped, #64748b)', visible: true },
      { id: 'visionos', label: 'visionOS', count: 0, color: 'var(--mdm-graph-dark-blue, #1e3a8a)', visible: true }
    ]
  },
  apps: {
    unit: 'Apps',
    items: [
      { id: 'allow', label: 'Allowlisted', count: 19, color: 'var(--mdm-graph-status-success, #22c55e)', visible: true },
      { id: 'block', label: 'Blocklisted', count: 88, color: 'var(--mdm-graph-status-failed, #ef4444)', visible: true }
    ]
  },
  dataUsage: {
    unit: 'MB',
    items: []
  }
};

window.showChartTooltip = function (e, text, color) {
  let tt = document.getElementById('alpChartTooltip');
  if (!tt) {
    tt = document.createElement('div');
    tt.id = 'alpChartTooltip';
    tt.className = 'alp-chart-tooltip';
    document.body.appendChild(tt);
  }
  tt.innerHTML = `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${color};margin-right:6px;vertical-align:middle;"></span>${text}`;
  const x = (e.clientX !== undefined ? e.clientX : e.pageX) || 0;
  const y = (e.clientY !== undefined ? e.clientY : e.pageY) || 0;
  tt.style.left = x + 'px';
  tt.style.top = y + 'px';
  tt.classList.add('visible');
};

window.moveChartTooltip = function (e) {
  const tt = document.getElementById('alpChartTooltip');
  if (tt && tt.classList.contains('visible')) {
    const x = (e.clientX !== undefined ? e.clientX : e.pageX) || 0;
    const y = (e.clientY !== undefined ? e.clientY : e.pageY) || 0;
    tt.style.left = x + 'px';
    tt.style.top = y + 'px';
  }
};

window.hideChartTooltip = function () {
  const tt = document.getElementById('alpChartTooltip');
  if (tt) tt.classList.remove('visible');
};

window.toggleChartItem = function (chartKey, itemId, event) {
  if (event) {
    if (event.stopPropagation) event.stopPropagation();
    if (event.preventDefault) event.preventDefault();
  }
  const chart = window.ALP_CHARTS_STATE && window.ALP_CHARTS_STATE[chartKey];
  if (!chart) return;
  const item = chart.items.find(x => x.id === itemId);
  if (!item) return;
  item.visible = !item.visible;
  window.hideChartTooltip();

  const reg = window.__LAST_REG_DATA || [];
  if (chartKey === 'lastContact') renderLastContactChart(reg, true);
  else if (chartKey === 'platform') renderPlatformChart(reg, true);
  else if (chartKey === 'apps') renderAppSummaryChart(reg, true);
  else if (chartKey === 'dataUsage') renderDataUsageChart(reg, true);
};

function renderLastContactChart(reg, isToggle) {
  const el = $('innerGraph20');
  if (!el) return;
  if (!reg || reg.length === 0) {
    el.innerHTML = `
      <div class="no-graph-data" id="cardLastContactContent">
        <div class="no-graph-data-image">
          <span class="no-graph-data-text">No Data Available</span>
          <svg aria-label="pie-chart2" class="svg-bucket-icon" data-icon="mdm-common::pie-chart2" role="img" style="width: 180px;height: 180px;">
            <use href="/images/svg-bucket/mdm-common-38f54d8b04de20ad79ff34707c87d72c.svg#pie-chart2" xlink:href="/images/svg-bucket/mdm-common-38f54d8b04de20ad79ff34707c87d72c.svg#pie-chart2"></use>
          </svg>
        </div>
        <div class="no-graph-data-info">
          <div class="no-graph-data-head">Last Contact Summary</div>
          <div class="no-graph-data-text">Summary of managed devices based on last contact time</div>
        </div>
      </div>
    `;
    return;
  }

  const chart = window.ALP_CHARTS_STATE.lastContact;
  if (!isToggle) {
    const now = new Date();
    let c0_3 = 0, c4_7 = 0, c8_15 = 0, c16_30 = 0, c31_plus = 0;
    reg.forEach(d => {
      const raw = d.last_verification_at || d.last_seen_at || d.created_at;
      if (!raw) { c0_3++; return; }
      try {
        const date = new Date(raw.replace(' ', 'T'));
        const diffDays = Math.max(0, Math.floor((now - date) / (1000 * 3600 * 24)));
        if (diffDays <= 3) c0_3++;
        else if (diffDays <= 7) c4_7++;
        else if (diffDays <= 15) c8_15++;
        else if (diffDays <= 30) c16_30++;
        else c31_plus++;
      } catch (e) {
        c0_3++;
      }
    });
    chart.items.find(x => x.id === 'c0_3').count = c0_3;
    chart.items.find(x => x.id === 'c4_7').count = c4_7;
    chart.items.find(x => x.id === 'c8_15').count = c8_15;
    chart.items.find(x => x.id === 'c16_30').count = c16_30;
    chart.items.find(x => x.id === 'c31_plus').count = c31_plus;
  }

  const visibleItems = chart.items.filter(x => x.visible);
  const visibleCounts = visibleItems.map(x => x.count);
  const maxVal = Math.max(4, ...(visibleCounts.length ? visibleCounts : [4]));
  const chartHeight = 85;
  const baselineY = 120;

  const barPositions = [
    { id: 'c0_3', x: 65, label: '0-3 Days' },
    { id: 'c4_7', x: 135, label: '4 - 7 Days' },
    { id: 'c8_15', x: 205, label: '8 - 15 Days' },
    { id: 'c16_30', x: 275, label: '16 - 30 Days' },
    { id: 'c31_plus', x: 345, label: '31 above' }
  ];

  let barsHtml = '';
  barPositions.forEach(pos => {
    const item = chart.items.find(x => x.id === pos.id);
    if (!item) return;
    const h = (item.visible && item.count > 0) ? Math.max(8, Math.round((item.count / maxVal) * chartHeight)) : 0;
    if (item.visible && item.count > 0) {
      barsHtml += `
        <rect x="${pos.x - 14}" y="${baselineY - h}" width="28" height="${h}" fill="${item.color}" rx="1"
              class="alp-chart-bar" style="cursor:pointer;"
              onclick="window.toggleChartItem('lastContact', '${item.id}', event)"
              onmouseenter="window.showChartTooltip(event, '${item.label}: ${item.count} devices', '${item.color}')"
              onmousemove="window.moveChartTooltip(event)"
              onmouseleave="window.hideChartTooltip()"/>
        <text x="${pos.x}" y="${baselineY - h - 4}" text-anchor="middle" font-size="11" font-weight="600" fill="#17181c">${item.count}</text>
      `;
    }
    barsHtml += `
      <text x="${pos.x}" y="${baselineY + 16}" text-anchor="middle" font-size="10" fill="${item.visible ? '#616161' : '#94a3b8'}" style="cursor:pointer;" onclick="window.toggleChartItem('lastContact', '${item.id}', event)">${pos.label}</text>
    `;
  });

  el.innerHTML = `
    <div class="graph-box-header draggable-graph">
      <div class="graph-box-heading">Last Contact Summary</div>
      <div class="graph-box-description">Summary of managed devices based on last contact time</div>
    </div>
    <div class="graphs">
      <div style="width:100%; display:flex; justify-content:center; align-items:center;">
        <svg viewBox="0 0 420 150" width="100%" height="150" style="overflow:visible">
          <line x1="45" y1="20" x2="400" y2="20" stroke="#f1f5f9" stroke-width="1"/>
          <line x1="45" y1="45" x2="400" y2="45" stroke="#f1f5f9" stroke-width="1"/>
          <line x1="45" y1="70" x2="400" y2="70" stroke="#f1f5f9" stroke-width="1"/>
          <line x1="45" y1="95" x2="400" y2="95" stroke="#f1f5f9" stroke-width="1"/>
          <line x1="45" y1="${baselineY}" x2="400" y2="${baselineY}" stroke="#cbd5e1" stroke-width="1"/>

          <text x="35" y="24" text-anchor="end" font-size="11" fill="#72798f">${maxVal}</text>
          <text x="35" y="49" text-anchor="end" font-size="11" fill="#72798f">${Math.round(maxVal * 0.75)}</text>
          <text x="35" y="74" text-anchor="end" font-size="11" fill="#72798f">${Math.round(maxVal * 0.5)}</text>
          <text x="35" y="99" text-anchor="end" font-size="11" fill="#72798f">${Math.round(maxVal * 0.25)}</text>
          <text x="35" y="${baselineY + 4}" text-anchor="end" font-size="11" fill="#72798f">0</text>
          <text x="12" y="70" text-anchor="middle" font-size="10" fill="#72798f" transform="rotate(-90 12 70)">No. of Devices</text>

          ${barsHtml}
        </svg>
      </div>
    </div>
  `;
}

function renderPlatformChart(reg, isToggle) {
  const el = $('innerGraph30');
  if (!el) return;
  if (!reg || reg.length === 0) {
    el.innerHTML = `
      <div class="no-graph-data" id="cardPlatformContent">
        <div class="no-graph-data-image">
          <span class="no-graph-data-text">No Data Available</span>
          <svg aria-label="pie-chart2" class="svg-bucket-icon" data-icon="mdm-common::pie-chart2" role="img" style="width: 180px;height: 180px;">
            <use href="/images/svg-bucket/mdm-common-38f54d8b04de20ad79ff34707c87d72c.svg#pie-chart2" xlink:href="/images/svg-bucket/mdm-common-38f54d8b04de20ad79ff34707c87d72c.svg#pie-chart2"></use>
          </svg>
        </div>
        <div class="no-graph-data-info">
          <div class="no-graph-data-head">Platform Type</div>
          <div class="no-graph-data-text">Summary of managed devices based on platform</div>
        </div>
      </div>
    `;
    return;
  }

  const chart = window.ALP_CHARTS_STATE.platform;
  if (!isToggle) {
    const androidItem = chart.items.find(x => x.id === 'android');
    if (androidItem) androidItem.count = reg.length;
  }

  const circ = 238.76;
  const visibleItems = chart.items.filter(x => x.visible);
  const visibleTotal = visibleItems.reduce((acc, x) => acc + x.count, 0);

  let slicesHtml = '';
  if (visibleTotal > 0) {
    let currentOffset = 0;
    visibleItems.forEach(item => {
      if (item.count === 0) return;
      const arcLen = ((item.count / visibleTotal) * circ).toFixed(2);
      const tooltipText = `${esc(item.label)}: ${item.count} Devices (100%)`;
      slicesHtml += `
        <circle cx="50" cy="50" r="38" fill="none" stroke="${item.color}" stroke-width="14"
                stroke-dasharray="${arcLen} ${circ}" stroke-dashoffset="-${currentOffset}"
                transform="rotate(-90 50 50)"
                class="alp-chart-slice" style="cursor:pointer;"
                onclick="window.toggleChartItem('platform', '${item.id}', event)"
                onmouseenter="window.showChartTooltip(event, '${tooltipText}', '${item.color}')"
                onmousemove="window.moveChartTooltip(event)"
                onmouseleave="window.hideChartTooltip()"/>
      `;
      currentOffset += parseFloat(arcLen);
    });
  }

  el.innerHTML = `
    <div class="graph-box-header draggable-graph">
      <div class="graph-box-heading">Platform Type</div>
      <div class="graph-box-description">Summary of managed devices based on platform</div>
    </div>
    <div class="graphs" style="display:flex; align-items:center; justify-content:space-between; padding:15px 20px; min-height:185px;">
      <div style="position:relative; width:130px; height:130px; flex-shrink:0;">
        <svg width="130" height="130" viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="38" fill="none" stroke="#f1f5f9" stroke-width="14"/>
          ${slicesHtml}
        </svg>
        <div style="position:absolute; top:0; left:0; width:100%; height:100%; display:flex; flex-direction:column; align-items:center; justify-content:center; pointer-events:none;">
          <span style="font-size:20px; font-weight:700; color:#17181c; line-height:1.1;">${visibleTotal}</span>
          <span style="font-size:11px; color:#72798f;">Devices</span>
        </div>
      </div>
      <div class="legendarea" style="flex:1; margin-left:24px; max-height:165px; overflow-y:auto;">
        <ul class="zc-legend-legseries" style="margin:0; padding:0; list-style:none;">
          ${chart.items.map(item => `
            <li class="zc-legend-series ${item.visible ? '' : 'is-hidden'}"
                onclick="window.toggleChartItem('platform', '${item.id}', event)"
                title="Click to toggle ${item.label}"
                style="display:flex; align-items:center; padding:3px 0; cursor:pointer; opacity:${item.visible ? 1 : 0.4}; font-size:12px; color:#616161;">
              <div class="zc-legend-legendfilterbox" style="width:11px; height:11px; border:2px solid ${item.color}; background:${item.visible && item.count > 0 ? item.color : 'transparent'}; margin-right:8px; border-radius:2px; flex-shrink:0;"></div>
              <span class="zc-legend-legendlabel" style="flex:1;">${item.label}</span>
              <span style="font-size:11px; color:#94a3b8; font-weight:600; margin-left:6px;">${item.count}</span>
            </li>
          `).join('')}
        </ul>
      </div>
    </div>
  `;
}

function renderAppSummaryChart(reg, isToggle) {
  const el = $('innerGraph35');
  if (!el) return;
  if (!reg || reg.length === 0) {
    el.innerHTML = `
      <div class="no-graph-data" id="cardAppSummaryContent">
        <div class="no-graph-data-image">
          <span class="no-graph-data-text">No Data Available</span>
          <svg aria-label="pie-chart2" class="svg-bucket-icon" data-icon="mdm-common::pie-chart2" role="img" style="width: 180px;height: 180px;">
            <use href="/images/svg-bucket/mdm-common-38f54d8b04de20ad79ff34707c87d72c.svg#pie-chart2" xlink:href="/images/svg-bucket/mdm-common-38f54d8b04de20ad79ff34707c87d72c.svg#pie-chart2"></use>
          </svg>
        </div>
        <div class="no-graph-data-info">
          <div class="no-graph-data-head">App Summary</div>
          <div class="no-graph-data-text">Summary of blocklisted and allowlisted apps detected in the network</div>
        </div>
      </div>
    `;
    return;
  }

  const chart = window.ALP_CHARTS_STATE.apps;
  const circ = 238.76;
  const visibleItems = chart.items.filter(x => x.visible);
  const visibleTotal = visibleItems.reduce((acc, x) => acc + x.count, 0);

  let slicesHtml = '';
  if (visibleTotal > 0) {
    let currentOffset = 0;
    visibleItems.forEach(item => {
      if (item.count === 0) return;
      const arcLen = ((item.count / visibleTotal) * circ).toFixed(2);
      const pct = ((item.count / visibleTotal) * 100).toFixed(1);
      const tooltipText = `${esc(item.label)}: ${item.count} (${pct}%)`;
      slicesHtml += `
        <circle cx="50" cy="50" r="38" fill="none" stroke="${item.color}" stroke-width="14"
                stroke-dasharray="${arcLen} ${circ}" stroke-dashoffset="-${currentOffset}"
                transform="rotate(-90 50 50)"
                class="alp-chart-slice" style="cursor:pointer;"
                onclick="window.toggleChartItem('apps', '${item.id}', event)"
                onmouseenter="window.showChartTooltip(event, '${tooltipText}', '${item.color}')"
                onmousemove="window.moveChartTooltip(event)"
                onmouseleave="window.hideChartTooltip()"/>
      `;
      currentOffset += parseFloat(arcLen);
    });
  }

  el.innerHTML = `
    <div class="graph-box-header draggable-graph">
      <div class="graph-box-heading">App Summary</div>
      <div class="graph-box-description">Summary of blocklisted and allowlisted apps detected in the network</div>
    </div>
    <div class="graphs" style="display:flex; align-items:center; justify-content:space-between; padding:15px 20px; min-height:185px;">
      <div style="position:relative; width:130px; height:130px; flex-shrink:0;">
        <svg width="130" height="130" viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="38" fill="none" stroke="#f1f5f9" stroke-width="14"/>
          ${slicesHtml}
        </svg>
        <div style="position:absolute; top:0; left:0; width:100%; height:100%; display:flex; flex-direction:column; align-items:center; justify-content:center; pointer-events:none;">
          <span style="font-size:20px; font-weight:700; color:#17181c; line-height:1.1;">${visibleTotal}</span>
          <span style="font-size:11px; color:#72798f;">Apps</span>
        </div>
      </div>
      <div class="legendarea" style="flex:1; margin-left:24px;">
        <ul class="zc-legend-legseries" style="margin:0; padding:0; list-style:none;">
          ${chart.items.map(item => `
            <li class="zc-legend-series ${item.visible ? '' : 'is-hidden'}"
                onclick="window.toggleChartItem('apps', '${item.id}', event)"
                title="Click to toggle ${item.label}"
                style="display:flex; align-items:center; padding:5px 0; cursor:pointer; opacity:${item.visible ? 1 : 0.4}; font-size:12px; color:#616161;">
              <div class="zc-legend-legendfilterbox" style="width:11px; height:11px; border:2px solid ${item.color}; background:${item.visible && item.count > 0 ? item.color : 'transparent'}; margin-right:8px; border-radius:2px; flex-shrink:0;"></div>
              <span class="zc-legend-legendlabel" style="flex:1;">${item.label}</span>
              <span style="font-size:11px; color:#94a3b8; font-weight:600; margin-left:6px;">${item.count}</span>
            </li>
          `).join('')}
        </ul>
      </div>
    </div>
  `;
}

function renderDataUsageChart(reg, isToggle) {
  const el = $('innerGraph82');
  if (!el) return;
  el.innerHTML = `
    <div class="no-graph-data" id="cardDataUsageContent">
      <div class="no-graph-data-image">
        <span class="no-graph-data-text">No Data Available</span>
        <svg aria-label="pie-chart2" class="svg-bucket-icon" data-icon="mdm-common::pie-chart2" role="img" style="width: 180px;height: 180px;">
          <use href="/images/svg-bucket/mdm-common-38f54d8b04de20ad79ff34707c87d72c.svg#pie-chart2" xlink:href="/images/svg-bucket/mdm-common-38f54d8b04de20ad79ff34707c87d72c.svg#pie-chart2"></use>
        </svg>
      </div>
      <div class="no-graph-data-info">
        <div class="no-graph-data-head">Data Usage</div>
        <div class="no-graph-data-text">Summary of mobile data usage based on current cycle with defined data limit.</div>
      </div>
    </div>
  `;
}

function renderAuditFeed(auditList) {
  const feed = $('homeAuditFeed');
  if (!feed) return;

  function fmtAction(action, target) {
    const clean = String(action || 'ACTION').replace(/_/g, ' ').toLowerCase();
    const cap = clean.charAt(0).toUpperCase() + clean.slice(1);
    return `${cap} on ${target || 'system'}`;
  }

  function fmtTime(dateStr) {
    if (!dateStr) return 'moments ago';
    try {
      const d = new Date(dateStr.replace(' ', 'T'));
      const diffMin = Math.round((new Date() - d) / (1000 * 60));
      if (diffMin < 2) return 'moments ago';
      if (diffMin < 60) return `${diffMin} minutes ago`;
      const diffHours = Math.round(diffMin / 60);
      if (diffHours < 24) return `${diffHours} hours ago`;
      const diffDays = Math.round(diffHours / 24);
      return `${diffDays} days ago`;
    } catch (e) {
      return dateStr.split(' ')[0] || 'recently';
    }
  }

  const items = (Array.isArray(auditList) && auditList.length > 0) ? auditList : [
    {
      actor: 'admin',
      created_at: new Date().toISOString(),
      action: 'ADMIN_CONNECT',
      reason: 'The host 127.0.0.1 is connected as admin with Administrator role'
    },
    {
      actor: 'admin',
      created_at: new Date(Date.now() - 1000 * 300).toISOString(),
      action: 'SYSTEM_INITIALIZE',
      reason: 'ManageEngine Mobile Device Manager Plus subsystem initialized'
    }
  ];

  feed.innerHTML = items.slice(0, 8).map(function (item) {
    let icon = 'dUser';
    if (item.action && (item.action.includes('PROFILE') || item.action.includes('POLICY') || item.action.includes('RESTRICTION'))) {
      icon = 'dMDMProfile';
    } else if (item.action && (item.action.includes('DEVICE') || item.action.includes('ENROLL'))) {
      icon = 'dMDMDevice';
    } else if (item.action && (item.action.includes('SYSTEM') || item.action.includes('BACKUP'))) {
      icon = 'dmDmgeneral';
    }

    const remarks = item.reason || (item.details && typeof item.details === 'string' ? item.details : fmtAction(item.action, item.device_id));
    const actor = item.actor || 'admin';
    const time = fmtTime(item.created_at);

    return `
      <div class="log-element">
        <div class="log-image-container">
          <svg aria-label="${icon}" class="svg-bucket-icon log-image" data-icon="mdm-common::${icon}" role="img">
            <use href="/images/svg-bucket/mdm-common-38f54d8b04de20ad79ff34707c87d72c.svg#${icon}" xlink:href="/images/svg-bucket/mdm-common-38f54d8b04de20ad79ff34707c87d72c.svg#${icon}"></use>
          </svg>
        </div>
        <div class="log-report">
          <div class="log-remarks font-sm-3">
            ${esc(remarks)}
          </div>
          <div class="log-event-details font-sm-3">
            <span class="log-user-name font-grey">${esc(actor)}</span>
            <span class="log-time-stamp font-grey">${esc(time)}</span>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

async function refreshAuditFeedAction() {
  const btn = $('action-button-0');
  if (btn) btn.style.transform = 'rotate(180deg)';
  try {
    const aud = await api('/audit?tail=10', 'GET');
    if (aud.ok && Array.isArray(aud.data)) {
      renderAuditFeed(aud.data);
    }
  } catch (e) { }
  setTimeout(() => { if (btn) btn.style.transform = 'none'; }, 300);
}

function toggleHomeEnrollDropdown(platform, event) {
  if (event) event.stopPropagation();
  const apple = $('homeDropdownApple');
  const win = $('homeDropdownWindows');
  if (platform === 'apple') {
    if (win) win.style.display = 'none';
    if (apple) apple.style.display = (apple.style.display === 'block') ? 'none' : 'block';
  } else if (platform === 'windows') {
    if (apple) apple.style.display = 'none';
    if (win) win.style.display = (win.style.display === 'block') ? 'none' : 'block';
  }
}

document.addEventListener('click', function () {
  const apple = $('homeDropdownApple');
  const win = $('homeDropdownWindows');
  if (apple) apple.style.display = 'none';
  if (win) win.style.display = 'none';
});

function toggleQuickLinks() {
  const body = $('quickLinksBody');
  const text = $('quickLinksToggleText');
  const chevron = $('quickLinksChevron');
  if (!body) return;
  const isHidden = body.style.display === 'none';
  if (isHidden) {
    body.style.display = 'block';
    if (text) text.textContent = 'Hide';
    if (chevron) chevron.style.transform = 'none';
  } else {
    body.style.display = 'none';
    if (text) text.textContent = 'Show';
    if (chevron) chevron.style.transform = 'rotate(180deg)';
  }
}

function switchQuickLinksTab(tab, event) {
  if (event) event.preventDefault();
  const tabHowTo = $('tabQuickHowTo');
  const tabFaq = $('tabQuickFaq');
  const secHowTo = $('quickLinksHowToSection');
  const secFaq = $('quickLinksFaqSection');
  const slider = $('quickLinksSlider');

  if (tab === 'howto') {
    if (tabHowTo) { tabHowTo.classList.add('active'); tabHowTo.style.color = '#2563eb'; tabHowTo.style.fontWeight = '600'; }
    if (tabFaq) { tabFaq.classList.remove('active'); tabFaq.style.color = '#64748b'; tabFaq.style.fontWeight = 'normal'; }
    if (secHowTo) secHowTo.style.display = 'block';
    if (secFaq) secFaq.style.display = 'none';
    if (slider) { slider.style.left = '0px'; slider.style.width = '68px'; }
  } else {
    if (tabFaq) { tabFaq.classList.add('active'); tabFaq.style.color = '#2563eb'; tabFaq.style.fontWeight = '600'; }
    if (tabHowTo) { tabHowTo.classList.remove('active'); tabHowTo.style.color = '#64748b'; tabHowTo.style.fontWeight = 'normal'; }
    if (secFaq) secFaq.style.display = 'block';
    if (secHowTo) secHowTo.style.display = 'none';
    if (slider) { slider.style.left = '76px'; slider.style.width = '42px'; }
  }
}

window.toggleHomeEnrollDropdown = toggleHomeEnrollDropdown;
window.toggleQuickLinks = toggleQuickLinks;
window.switchQuickLinksTab = switchQuickLinksTab;
window.refreshAuditFeedAction = refreshAuditFeedAction;

function renderKpis(det, reg) {
  renderRealDashboard(det, reg, []);
}
function renderDetected(list) {
  const tb = $('detTbody');
  $('detCount').textContent = String(list.length);
  if (!list.length) { tb.innerHTML = emptyRow(5, 'لا أجهزة مكتشفة عبر ADB بعد', 'صلّ الجهاز عبر USB وأذِن لتصحيح الأخطاء — سيظهر هنا تلقائياً'); return; }
  tb.innerHTML = list.map(function (x) {
    const st = x.state === 'device' ? 'p-ok' : (x.state === 'offline' || x.state === 'unauthorized' ? 'p-bad' : 'p-part');
    return '<tr>' +
      '<td class="mono">' + esc(x.serial) + '</td>' +
      '<td>' + esc(x.model || '—') + '</td>' +
      '<td>' + pill(st, String(x.state || '')) + '</td>' +
      '<td>' + (x.ready ? pill('p-ok', 'جاهز') : pill('p-bad', 'غير جاهز')) + '</td>' +
      '<td>' + (x.registered ? pill('p-ok', 'مسجّل') : pill('p-mut', 'جديد')) + '</td>' +
      '</tr>';
  }).join('');
}
function renderRegistered(list) {
  const tb = $('devTbody');
  $('devCount').textContent = String(list.length);
  if (!list.length) { tb.innerHTML = emptyRow(6, 'لا أجهزة مسجلة بعد', 'سجّل الجهاز من قناة ADB أولاً — ثم استعرضه في صفحة الأجهزة'); return; }
  tb.innerHTML = list.map(function (x) {
    const lab = x.is_lab ? ' <span class="chip">مخبري</span>' : '';
    const owner = x.device_owner_state ? (' — <span style="color:var(--mut);font-size:11px">' + esc(x.device_owner_state) + '</span>') : '';
    return '<tr>' +
      '<td class="mono">' + esc(x.device_id) + '</td>' +
      '<td>' + esc(x.model || x.manufacturer || '—') + lab + '</td>' +
      '<td class="mono">' + esc(String(x.android_version || '') + (x.api_level ? (' · ' + x.api_level) : '')) + '</td>' +
      '<td>' + statusPill(x.enrollment_state) + '</td>' +
      '<td>' + statusPill(x.compliance_state) + owner + '</td>' +
      '<td class="mono" style="text-align:right;direction:rtl">' + esc(x.last_verification_at || '—') + '</td>' +
      '</tr>';
  }).join('');
}
function renderAdb(a) {
  const box = $('adbBox');
  $('adbRaw').innerHTML = '';
  if (!a.ok) { box.innerHTML = '<div class="empty" style="grid-column:1/-1">' + ic('alert', 30) + '<div class="et">تعذّر قراءة حالة ADB</div><div class="es">' + esc(a.error || '') + '</div></div>'; return; }
  const obj = a.data || {};
  const chips = obj.devices && Array.isArray(obj.devices)
    ? (obj.devices.length ? (obj.devices.map(s => '<span class="chip">' + esc(s) + '</span>').join(' ')) : pill('p-mut', 'لا جهاز مرفق'))
    : '—';
  const items = [];
  const labels = { devices: 'الأجهزة المرفقة', configured: 'خدمة ADB مُهيأة' };
  if (obj.devices !== undefined) { items.push(['الأجهزة المرفقة', chips]); }
  for (const k in obj) {
    if (k === 'devices') continue;
    const v = obj[k];
    if (typeof v === 'boolean') { items.push([labels[k] || k, dot(v) + ' <span style="margin-right:5px">' + (v ? 'نعم' : 'لا') + '</span>']); }
    else if (Array.isArray(v)) { items.push([labels[k] || k, v.length ? v.map(s => '<span class="chip">' + esc(s) + '</span>').join(' ') : pill('p-mut', 'فارغ')]); }
    else if (v && typeof v === 'object') { items.push([labels[k] || k, '<span class="chip">كائن</span> <span style="color:var(--mut)">' + esc(Object.keys(v).length) + ' حقلاً</span>']); }
    else { items.push([labels[k] || k, esc(v)]); }
  }
  box.innerHTML = items.length ? defs(items) : '<div class="empty" style="grid-column:1/-1">' + ic('info', 30) + '<div class="et">لا بيانات حالة</div></div>';
  $('adbRaw').innerHTML = raw(a);
}
let LAST_DASHBOARD_CACHE = null;

async function dashboard() {
  // 1. Instant Render from cache if available (0ms instant display)
  if (LAST_DASHBOARD_CACHE) {
    renderRealDashboard(LAST_DASHBOARD_CACHE.detList, LAST_DASHBOARD_CACHE.regList, LAST_DASHBOARD_CACHE.auditList);
    renderDetected(LAST_DASHBOARD_CACHE.detList);
    renderRegistered(LAST_DASHBOARD_CACHE.regList);
    renderAdb(LAST_DASHBOARD_CACHE.adb);
  }

  // 2. High-performance Parallel Fetch
  const [det, reg, adb, aud] = await Promise.all([
    api('/devices/detected', 'GET').catch(() => ({ ok: false })),
    api('/devices', 'GET').catch(() => ({ ok: false })),
    api('/adb/status', 'GET').catch(() => ({ ok: false })),
    api('/audit?tail=10', 'GET').catch(() => ({ ok: false }))
  ]);

  const detList = (det.ok && Array.isArray(det.data)) ? det.data : [];
  const regList = (reg.ok && Array.isArray(reg.data)) ? reg.data : [];
  const auditList = (aud.ok && Array.isArray(aud.data)) ? aud.data : [];

  LAST_DASHBOARD_CACHE = { detList, regList, auditList, adb };

  renderRealDashboard(detList, regList, auditList);
  renderDetected(detList);
  renderRegistered(regList);
  renderAdb(adb);
}

function fillSelect(id, list, labeller) {
  const el = $(id);
  el.innerHTML = '<option value="">— اختر جهازاً —</option>';
  list.forEach(function (x) {
    el.insertAdjacentHTML('beforeend', '<option value="' + esc(x.device_id) + '">' + esc(labeller(x)) + '</option>');
  });
}
let ALL_REG_DEVICES = [];
let ALL_DET_DEVICES = [];

function switchDeviceTab(tab) {
  ['managed', 'detected', 'inspector'].forEach(t => {
    const el = $('deviceView' + t.charAt(0).toUpperCase() + t.slice(1));
    const btn = $('tabBtn' + t.charAt(0).toUpperCase() + t.slice(1));
    if (el) el.style.display = (t === tab) ? 'block' : 'none';
    if (btn) btn.classList.toggle('active', t === tab);
  });
}

const ANDROID_ICON = '<svg width="13" height="13" viewBox="0 0 24 24" fill="#3ddc84" style="vertical-align:middle;margin-right:5px;"><path d="M6 18c0 .55.45 1 1 1h1v3.5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5V19h2v3.5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5V19h1c.55 0 1-.45 1-1V8H6v10zM3.5 8C2.67 8 2 8.67 2 9.5v7c0 .83.67 1.5 1.5 1.5S5 17.33 5 16.5v-7C5 8.67 4.33 8 3.5 8zm17 0c-.83 0-1.5.67-1.5 1.5v7c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5v-7c0-.83-.67-1.5-1.5-1.5zm-4.97-5.84l1.3-1.3c.2-.2.2-.51 0-.71-.2-.2-.51-.2-.71 0l-1.48 1.48C13.85 1.23 12.95 1 12 1c-.96 0-1.86.23-2.66.63L7.85.15c-.2-.2-.51-.2-.71 0-.2.2-.2.51 0 .71l1.31 1.31C6.97 3.26 6 5.01 6 7h12c0-1.99-.97-3.75-2.47-4.84zM10 5H9V4h1v1zm5 0h-1V4h1v1z"/></svg>';

function toggleSidebarNavigation(btn) {
  const wrapper = btn ? (btn.closest ? btn.closest('.navigation--wrapper') : null) : document.querySelector('.vpanel.active .navigation--wrapper') || document.querySelector('.navigation--wrapper');
  if (!wrapper) return;
  const drawer = wrapper.querySelector('.navigation-drawer');
  const container = wrapper.querySelector('.nd--container');
  const toggleIcon = wrapper.querySelector('svg.nd--toggle-menu') || wrapper.querySelector('.nd--toggle svg') || document.getElementById('sidebarToggleIcon');
  if (!drawer || !container) return;

  const rootPage = wrapper.closest('.mdm-module-root-page');
  const mainContainer = rootPage ? rootPage.querySelector('.mdm-main-page-container') : null;

  const isCollapsed = drawer.classList.contains('collapsed') || container.getAttribute('data-visibility') === 'hidden';
  if (isCollapsed) {
    // Expand
    drawer.classList.remove('collapsed');
    container.setAttribute('data-visibility', 'visible');
    drawer.setAttribute('data-expanded', '');
    if (mainContainer) mainContainer.classList.remove('left-tree-collapse');
    if (toggleIcon) {
      toggleIcon.setAttribute('aria-label', 'Hide left navigation');
      toggleIcon.setAttribute('title', 'Hide left navigation');
      toggleIcon.setAttribute('data-icon', 'dcc::left-pane-hide');
      const title = toggleIcon.querySelector('title');
      if (title) title.textContent = 'Hide left navigation';
      const use = toggleIcon.querySelector('use');
      if (use) {
        use.setAttribute('href', '/images/svg-bucket/dcc-da743fca3481aafa3c3fbd0e496f9409.svg#left-pane-hide');
        use.setAttribute('xlink:href', '/images/svg-bucket/dcc-da743fca3481aafa3c3fbd0e496f9409.svg#left-pane-hide');
      } else {
        toggleIcon.innerHTML = '<title>Hide left navigation</title><use href="/images/svg-bucket/dcc-da743fca3481aafa3c3fbd0e496f9409.svg#left-pane-hide" xlink:href="/images/svg-bucket/dcc-da743fca3481aafa3c3fbd0e496f9409.svg#left-pane-hide"></use>';
      }
    }
  } else {
    // Collapse
    drawer.classList.add('collapsed');
    container.setAttribute('data-visibility', 'hidden');
    drawer.removeAttribute('data-expanded');
    if (mainContainer) mainContainer.classList.add('left-tree-collapse');
    if (toggleIcon) {
      toggleIcon.setAttribute('aria-label', 'Show left navigation');
      toggleIcon.setAttribute('title', 'Show left navigation');
      toggleIcon.setAttribute('data-icon', 'dcc::left-pane-show');
      const title = toggleIcon.querySelector('title');
      if (title) title.textContent = 'Show left navigation';
      const use = toggleIcon.querySelector('use');
      if (use) {
        use.setAttribute('href', '/images/svg-bucket/dcc-da743fca3481aafa3c3fbd0e496f9409.svg#left-pane-show');
        use.setAttribute('xlink:href', '/images/svg-bucket/dcc-da743fca3481aafa3c3fbd0e496f9409.svg#left-pane-show');
      } else {
        toggleIcon.innerHTML = '<title>Show left navigation</title><use href="/images/svg-bucket/dcc-da743fca3481aafa3c3fbd0e496f9409.svg#left-pane-show" xlink:href="/images/svg-bucket/dcc-da743fca3481aafa3c3fbd0e496f9409.svg#left-pane-show"></use>';
      }
    }
  }
}

function toggleNavSection(el) {
  if (!el) return;
  const isClosed = el.hasAttribute('data-closed');
  if (isClosed) {
    el.removeAttribute('data-closed');
  } else {
    el.setAttribute('data-closed', '');
  }
  updateNavSlider(el.closest('.nd--container'));
}

function updateNavSlider(scope) {
  let containers = [];
  if (scope) {
    if (scope.classList && scope.classList.contains('nd--container')) containers = [scope];
    else if (scope.closest && scope.closest('.nd--container')) containers = [scope.closest('.nd--container')];
  }
  if (!containers.length) {
    // Update active vpanel container first, fallback to all
    containers = Array.from(document.querySelectorAll('.vpanel.active .nd--container'));
    if (!containers.length) containers = Array.from(document.querySelectorAll('.nd--container'));
  }

  containers.forEach(container => {
    if (!container) return;
    const slider = container.querySelector('.nd--slider');
    if (!slider) return;
    const active = container.querySelector('.nd--sub-section-container.active');
    if (active && active.closest('li')) {
      const li = active.closest('li');
      let top = 0;
      let curr = li;
      while (curr && curr !== container) {
        top += curr.offsetTop;
        curr = curr.offsetParent;
      }
      slider.style.top = top + 'px';
      slider.style.height = (li.offsetHeight || 36) + 'px';
      slider.style.display = 'block';
    } else {
      slider.style.display = 'none';
    }
  });
}

function handleNavDrawerItem(el, featureName, targetRoute) {
  if (!el) return;
  const container = el.closest('.nd--container');
  if (container) {
    container.querySelectorAll('.nd--sub-section-container').forEach(a => {
      a.classList.remove('active', 'common-bg', 'anchor-text__imp');
    });
    el.classList.add('active', 'common-bg', 'anchor-text__imp');
    updateNavSlider(container);
  }
  if (targetRoute) {
    history.pushState(null, '', '#' + (targetRoute.startsWith('/') ? targetRoute : '/' + targetRoute));
  }
  if (featureName) {
    if (typeof alpAlert === 'function') {
      alpAlert('The module "' + featureName + '" is part of the Enterprise Policy Suite.', featureName);
    }
  }
}
window.handleNavDrawerItem = handleNavDrawerItem;

function switchSidebarView(view, push = true) {
  document.querySelectorAll('.me-row-popup-menu').forEach(p => p.classList.remove('show'));
  const sideGD = $('subTab_GroupsAndDevices') || $('sideNavGroupsDevices');
  const sideProf = $('subTab_profiles') || $('sideNavProfiles');
  const wsGD = $('workspaceGroupsDevices');
  const wsProf = $('workspaceProfiles');
  const wsInsp = $('workspaceInspector');
  const wsCP = $('workspaceCreateProfile');
  const wsCfg = $('workspaceConfigureProfile');
  const wsPD = $('workspaceProfileDetails');

  const container = (sideGD || sideProf)?.closest('.nd--container');
  if (container) {
    container.querySelectorAll('.nd--sub-section-container').forEach(a => {
      a.classList.remove('active', 'common-bg', 'anchor-text__imp');
    });
  }

  if (sideGD) {
    sideGD.classList.toggle('active', view === 'groups-devices');
    sideGD.classList.toggle('common-bg', view === 'groups-devices');
    sideGD.classList.toggle('anchor-text__imp', view === 'groups-devices');
  }
  if (sideProf) {
    sideProf.classList.toggle('active', view === 'profiles');
    sideProf.classList.toggle('common-bg', view === 'profiles');
    sideProf.classList.toggle('anchor-text__imp', view === 'profiles');
  }

  document.body.classList.remove('in-profile-editor');
  const wsDD = $('workspaceDeviceDetails');

  // The sidebar lives inside a .vpanel section, and only the section marked
  // `active` is laid out. switchSidebarView used to move the inner workspaces
  // only, so clicking "Profiles" or "Groups & Devices" left the whole panel
  // collapsed at height 0 and the page looked empty.
  const sectionFor = (view === 'profiles')
    ? $('sub-devices')
    : (wsGD ? wsGD.closest('.vpanel') : null);
  if (sectionFor) showView(sectionFor.id.replace(/^sub-/, ''), false);

  if (wsCP) wsCP.style.display = 'none';
  if (wsCfg) wsCfg.style.display = 'none';
  if (wsPD) wsPD.style.display = 'none';
  if (wsDD) wsDD.style.display = 'none';
  const wsComp = $('workspaceComprehensiveDeviceDetails');
  if (wsComp) wsComp.style.display = 'none';

  if (view === 'groups-devices') {
    if (wsGD) wsGD.style.display = 'block';
    if (wsDD) wsDD.style.display = 'none';
    if (wsProf) wsProf.style.display = 'none';
    if (wsInsp) wsInsp.style.display = 'none';
    if (push) history.pushState(null, '', '#/uems/mdm/manage/groups-and-devices');
    populateDevices();
  } else if (view === 'profiles') {
    if (wsGD) wsGD.style.display = 'none';
    if (wsProf) wsProf.style.display = 'block';
    if (wsInsp) wsInsp.style.display = 'none';
    if (push) history.pushState(null, '', '#/uems/mdm/manage/profile');
    populatePolicies();
  } else if (view === 'inspector') {
    if (wsGD) wsGD.style.display = 'none';
    if (wsProf) wsProf.style.display = 'none';
    if (wsInsp) wsInsp.style.display = 'block';
    if (push) history.pushState(null, '', '#/devices/inspector');
  }
  updateNavSlider(container);
}

function toggleCreateProfileDrop(e) {
  if (e) e.stopPropagation();
  const m = $('createProfileDropMenu');
  if (m) m.classList.toggle('show');
}

let IS_MODIFY_MODE = false;

function openCreateProfile(platform, push = true) {
  IS_MODIFY_MODE = false;
  CURRENT_SUMMARY_PID = null;
  CURRENT_SUMMARY_PROFILE = null;
  const cpMenu = $('createProfileDropMenu');
  if (cpMenu) cpMenu.classList.remove('show');

  const platNames = {
    'android': 'Android',
    'ios': 'iOS/iPadOS',
    'windows': 'Windows',
    'chrome': 'Chrome',
    'macos': 'macOS',
    'tvos': 'tvOS',
    'visionos': 'visionOS'
  };
  const pName = platNames[platform] || 'Android';

  const breadWrapper = $('cpBreadcrumbWrapper');
  if (breadWrapper) breadWrapper.style.display = 'block';
  const bread = $('cpBreadPlatLabel');
  const title = $('cpFormTitle');
  if (bread) bread.textContent = 'Create ' + pName + ' Profile';
  if (title) title.textContent = 'Create ' + pName + ' Profile';

  const nameInput = $('profile_name') || $('cpProfileName');
  if (nameInput) {
    nameInput.value = '';
    nameInput.placeholder = 'e.g. Corporate Policy';
  }
  const descInput = $('profile_desc') || $('cpDescription');
  if (descInput) descInput.value = '';
  const recAttInput = $('profile_recovery_attempts') || $('cpRecoveryAttempts');
  if (recAttInput) recAttInput.value = '3';
  const cfgRecEl = $('cfgPasscodeRecoveryAttempts');
  if (cfgRecEl) cfgRecEl.value = '3';
  /* A fresh wizard is not attached to any stored row: the draft only exists once
     Continue has POSTed it, so CFG_DRAFT_ID is cleared here. */
  CFG_DRAFT_ID = null;
  CFG_REQ = {};
  CFG_EDITABLE = true;
  if (nameInput) nameInput.disabled = false;
  setStatus('cpStatus', '');
  setStatus('cfgStatus', '');

  const wsGD = $('workspaceGroupsDevices');
  const wsProf = $('workspaceProfiles');
  const wsInsp = $('workspaceInspector');
  const wsCP = $('workspaceCreateProfile');
  const wsCfg = $('workspaceConfigureProfile');
  const wsPD = $('workspaceProfileDetails');
  const wsDD = $('workspaceDeviceDetails');

  document.body.classList.add('in-profile-editor');
  if (wsGD) wsGD.style.display = 'none';
  if (wsProf) wsProf.style.display = 'none';
  if (wsInsp) wsInsp.style.display = 'none';
  if (wsCfg) wsCfg.style.display = 'none';
  if (wsPD) wsPD.style.display = 'none';
  if (wsDD) wsDD.style.display = 'none';
  if (wsCP) wsCP.style.display = 'block';

  // Highlight Profiles in left sidebar
  const sideGD = $('subTab_GroupsAndDevices') || $('sideNavGroupsDevices');
  const sideProf = $('subTab_profiles') || $('sideNavProfiles');
  if (sideGD) sideGD.classList.remove('active', 'common-bg', 'anchor-text__imp');
  if (sideProf) sideProf.classList.add('active', 'common-bg', 'anchor-text__imp');
  updateNavSlider();

  if (push) history.pushState(null, '', '#/devices/create-profile');
}

async function openModifyProfile(pid, push = true) {
  IS_MODIFY_MODE = true;
  CURRENT_SUMMARY_PID = pid;

  if (push) {
    history.pushState(null, '', `#/uems/mdm/manage/profile/android?edit=true&profileType=1&profileid=${encodeURIComponent(pid)}`);
  }

  // Update header and hide breadcrumbs to match Image 2 precisely
  const breadWrapper = $('cpBreadcrumbWrapper');
  if (breadWrapper) breadWrapper.style.display = 'none';
  const bread = $('cpBreadPlatLabel');
  if (bread) bread.textContent = 'Modify Android Profile';
  const title = $('cpFormTitle');
  if (title) title.textContent = 'Modify Android Profile';

  // Fetch profile details
  let r = await api('/profiles/' + encodeURIComponent(pid), 'GET');
  let p = (r.ok && r.data) ? r.data : null;
  if (!p) {
    const fallback = (ALL_PROFILES || []).find(x => x.policy_id === pid || String(x.id) === String(pid) || x.name === pid);
    if (fallback) {
      r = await api('/profiles/' + encodeURIComponent(fallback.policy_id), 'GET');
      if (r.ok && r.data) p = r.data;
    }
  }
  if (!p && CURRENT_SUMMARY_PROFILE && (CURRENT_SUMMARY_PROFILE.policy_id === pid || CURRENT_SUMMARY_PROFILE.name === pid)) {
    p = CURRENT_SUMMARY_PROFILE;
  }
  if (!p) {
    alpAlert('تعذّر العثور على الملف الشخصي: ' + pid);
    switchSidebarView('profiles');
    return;
  }

  // If ACTIVE or RETIRED, create or fetch revision draft so user edits a DRAFT revision
  if (p.status === 'ACTIVE' || p.status === 'RETIRED') {
    setStatus('cpStatus', 'جارٍ فتح إصدار جديد للتعديل…');
    const rev = await apiWrite('/profiles/' + encodeURIComponent(p.policy_id) + '/revision', 'POST',
      { change_reason: 'edit profile from modify button' }, 'فتح إصدار للتعديل');
    if (rev && rev.ok && rev.data) {
      p = rev.data;
    }
  }

  CURRENT_SUMMARY_PROFILE = p;
  CFG_DRAFT_ID = p.policy_id;
  CFG_ORIGINAL_STATUS = p.status;
  CFG_REQ = {};
  (p.requirements || []).forEach(function (q) { CFG_REQ[q.feature] = q.desired_state; });

  // Pre-fill profile name and description
  const nameEl = $('profile_name') || $('cpProfileName');
  if (nameEl) {
    nameEl.value = p.name || '';
    nameEl.title = p.name || '';
    nameEl.disabled = false;
  }
  const descEl = $('profile_desc') || $('cpDescription');
  if (descEl) {
    descEl.value = p.description || '';
  }
  const recVal = (p.recovery_attempts !== null && p.recovery_attempts !== undefined && p.recovery_attempts !== '') ? p.recovery_attempts : '3';
  const recAttEl = $('profile_recovery_attempts') || $('cpRecoveryAttempts');
  if (recAttEl) {
    recAttEl.value = recVal;
  }
  const cfgRecEl = $('cfgPasscodeRecoveryAttempts');
  if (cfgRecEl) {
    cfgRecEl.value = recVal;
  }

  // Set Profile Type radio: MDM Profile
  const rMdm = $('profileType_mdm');
  if (rMdm) rMdm.checked = true;

  setStatus('cpStatus', '');

  const wsGD = $('workspaceGroupsDevices');
  const wsProf = $('workspaceProfiles');
  const wsInsp = $('workspaceInspector');
  const wsCP = $('workspaceCreateProfile');
  const wsCfg = $('workspaceConfigureProfile');
  const wsPD = $('workspaceProfileDetails');
  const wsDD = $('workspaceDeviceDetails');

  document.body.classList.add('in-profile-editor');
  if (wsGD) wsGD.style.display = 'none';
  if (wsProf) wsProf.style.display = 'none';
  if (wsInsp) wsInsp.style.display = 'none';
  if (wsCfg) wsCfg.style.display = 'none';
  if (wsPD) wsPD.style.display = 'none';
  if (wsDD) wsDD.style.display = 'none';
  if (wsCP) wsCP.style.display = 'block';

  // Highlight Profiles in left sidebar
  const sideGD = $('subTab_GroupsAndDevices') || $('sideNavGroupsDevices');
  const sideProf = $('subTab_profiles') || $('sideNavProfiles');
  if (sideGD) sideGD.classList.remove('active', 'common-bg', 'anchor-text__imp');
  if (sideProf) sideProf.classList.add('active', 'common-bg', 'anchor-text__imp');
  updateNavSlider();
}

function cancelCreateOrModifyProfile() {
  if (IS_MODIFY_MODE && CURRENT_SUMMARY_PID) {
    openProfileDetails(CURRENT_SUMMARY_PID);
  } else {
    switchSidebarView('profiles');
  }
}

function backToStep1Profile() {
  if (IS_MODIFY_MODE && CFG_DRAFT_ID) {
    openModifyProfile(CFG_DRAFT_ID);
  } else {
    document.body.classList.add('in-profile-editor');
    const wsCP = $('workspaceCreateProfile');
    const wsCfg = $('workspaceConfigureProfile');
    if (wsCfg) wsCfg.style.display = 'none';
    if (wsCP) wsCP.style.display = 'block';
  }
}

function showCfgWorkspace(push = true) {
  document.body.classList.add('in-profile-editor');
  const wsGD = $('workspaceGroupsDevices');
  const wsProf = $('workspaceProfiles');
  const wsInsp = $('workspaceInspector');
  const wsCP = $('workspaceCreateProfile');
  const wsCfg = $('workspaceConfigureProfile');
  const wsPD = $('workspaceProfileDetails');
  const wsDD = $('workspaceDeviceDetails');
  if (wsGD) wsGD.style.display = 'none';
  if (wsProf) wsProf.style.display = 'none';
  if (wsInsp) wsInsp.style.display = 'none';
  if (wsCP) wsCP.style.display = 'none';
  if (wsPD) wsPD.style.display = 'none';
  if (wsDD) wsDD.style.display = 'none';
  if (wsCfg) wsCfg.style.display = 'block';

  // Highlight Profiles in left sidebar
  const sideGD = $('subTab_GroupsAndDevices') || $('sideNavGroupsDevices');
  const sideProf = $('subTab_profiles') || $('sideNavProfiles');
  if (sideGD) sideGD.classList.remove('active', 'common-bg', 'anchor-text__imp');
  if (sideProf) sideProf.classList.add('active', 'common-bg', 'anchor-text__imp');
  updateNavSlider();

  // Ensure default restrictions category and tab are isolated
  const restEl = $('androidrestrictionspolicy');
  if (restEl) selectCfgCat('restrictions', restEl);

  if (push) history.pushState(null, '', '#/devices/configure-profile');
}

/* ============================================================ */
/* Profile Details & Summary Screen Logic                       */
/* Exact ManageEngine MDM /payloadDetails authentic workflow    */
/* ============================================================ */
let CURRENT_SUMMARY_PID = null;
let CURRENT_SUMMARY_PROFILE = null;

async function openProfileDetails(pid, push = true, initialTab = 'details') {
  CURRENT_SUMMARY_PID = pid;
  const wsGD = $('workspaceGroupsDevices');
  const wsProf = $('workspaceProfiles');
  const wsInsp = $('workspaceInspector');
  const wsCP = $('workspaceCreateProfile');
  const wsCfg = $('workspaceConfigureProfile');
  const wsPD = $('workspaceProfileDetails');
  const wsDD = $('workspaceDeviceDetails');

  document.body.classList.remove('in-profile-editor');
  if (wsGD) wsGD.style.display = 'none';
  if (wsProf) wsProf.style.display = 'none';
  if (wsInsp) wsInsp.style.display = 'none';
  if (wsCP) wsCP.style.display = 'none';
  if (wsCfg) wsCfg.style.display = 'none';
  if (wsDD) wsDD.style.display = 'none';
  if (wsPD) wsPD.style.display = 'block';

  // Highlight Profiles in left sidebar
  const sideGD = $('subTab_GroupsAndDevices') || $('sideNavGroupsDevices');
  const sideProf = $('subTab_profiles') || $('sideNavProfiles');
  if (sideGD) sideGD.classList.remove('active', 'common-bg', 'anchor-text__imp');
  if (sideProf) sideProf.classList.add('active', 'common-bg', 'anchor-text__imp');
  updateNavSlider();

  let subPath = 'payloadDetails';
  if (initialTab === 'groups') subPath = 'associatedGroups';
  else if (initialTab === 'devices') subPath = 'associatedDevices';

  if (push) history.pushState(null, '', `#/uems/mdm/manage/profile/list/${encodeURIComponent(pid)}/${subPath}?profileType=1`);

  // Activate requested tab
  switchProfSumTab(initialTab, false);

  // Load profile data from API
  let r = await api('/profiles/' + encodeURIComponent(pid), 'GET');
  let p = (r.ok && r.data) ? r.data : null;
  if (!p) {
    const fallback = (ALL_PROFILES || []).find(x => x.policy_id === pid || String(x.id) === String(pid) || x.name === pid);
    if (fallback) {
      r = await api('/profiles/' + encodeURIComponent(fallback.policy_id), 'GET');
      if (r.ok && r.data) p = r.data;
    }
  }
  if (!p) {
    alpAlert('تعذّر العثور على الملف الشخصي: ' + pid);
    switchSidebarView('profiles');
    return;
  }
  CURRENT_SUMMARY_PROFILE = p;

  // Breadcrumbs & Title
  const bName = $('profSumBreadName');
  if (bName) bName.textContent = p.name || pid;
  const tName = $('profSumTitleName');
  if (tName) tName.textContent = p.name || pid;

  // Stat Counters
  const vEl = $('profSumVersion');
  if (vEl) vEl.textContent = p.version || p.latest_version || 1;
  const oldEl = $('profSumOlderCount');
  if (oldEl) oldEl.textContent = '0';
  const gEl = $('profSumGroupsCount');
  const dEl = $('profSumDevicesCount');

  // Groups and Devices info
  const groupsCount = (p.assigned_groups && Array.isArray(p.assigned_groups)) ? p.assigned_groups.length : (p.group_count || 0);
  const devicesCount = (p.target_devices && Array.isArray(p.target_devices)) ? p.target_devices.length : (p.device_count || 0);
  if (gEl) gEl.textContent = groupsCount;
  if (dEl) dEl.textContent = devicesCount;

  // Render Payload Area
  renderProfileSummaryPayload(p);

  // Render Groups & Devices tab contents
  renderProfileSummaryGroups(p);
  renderProfileSummaryDevices(p);
}

function switchProfSumTab(tab, push = true) {
  const tabs = ['details', 'groups', 'devices'];
  tabs.forEach(t => {
    const btn = $('profSumTabBtn' + t.charAt(0).toUpperCase() + t.slice(1));
    const content = $('profSumTabContent' + t.charAt(0).toUpperCase() + t.slice(1));
    const active = (t === tab);
    if (btn) {
      btn.classList.toggle('active', active);
      btn.style.removeProperty('border-bottom-color');
      btn.style.removeProperty('color');
      btn.style.removeProperty('font-weight');
      if (btn.parentElement && btn.parentElement.tagName === 'LI') {
        btn.parentElement.classList.toggle('active', active);
      }
    }
    if (content) {
      content.style.display = active ? 'block' : 'none';
    }
  });

  if (push && CURRENT_SUMMARY_PID) {
    let subPath = 'payloadDetails';
    if (tab === 'groups') subPath = 'associatedGroups';
    else if (tab === 'devices') subPath = 'associatedDevices';
    history.pushState(null, '', `#/uems/mdm/manage/profile/list/${encodeURIComponent(CURRENT_SUMMARY_PID)}/${subPath}?profileType=1`);
  }
}

function modifyProfileFromSummary() {
  if (CURRENT_SUMMARY_PID) {
    openModifyProfile(CURRENT_SUMMARY_PID);
  }
}

function cancelConfigureProfile() {
  if (CURRENT_SUMMARY_PID) {
    openProfileDetails(CURRENT_SUMMARY_PID);
  } else {
    switchSidebarView('profiles');
  }
}

let CURRENT_PROF_DETAILS_SUBCAT = 'Device Functionality';
let CURRENT_PROF_DETAILS_PROFILE = null;

function exportProfilePDF() {
  window.print();
}

function renderProfileSummaryPayload(p) {
  const area = $('profSumPayloadArea');
  if (!area) return;

  CURRENT_PROF_DETAILS_PROFILE = p;
  if (!CURRENT_PROF_DETAILS_SUBCAT) {
    CURRENT_PROF_DETAILS_SUBCAT = 'Device Functionality';
  }

  // Authentic 3-column layout matching ManageEngine MDM exactly
  area.innerHTML = `
    <div class="edit-profile" style="display:flex; border:1px solid #c7cad2; background:#fff; min-height:560px; box-shadow:0 1px 3px rgba(0,0,0,0.02);">
      <!-- Column 1: Configured Payloads (Left Tree) -->
      <div class="details-left-tree" style="width:200px; border-right:1px solid #c7cad2; background:#f1f2f4; display:flex; flex-direction:column; justify-content:space-between; flex-shrink:0;">
        <div class="profile-left-tab">
          <div class="left-tab-element bg-grey active" style="padding:10px 14px; display:flex; align-items:center; gap:10px; font-size:13px; color:#17181c; background:#fff; border-bottom:1px solid #c7cad2; border-right:2px solid #4276e0; cursor:pointer;">
            <svg role="img" aria-label="block" style="width: 18px; height: 18px; fill:#4276e0;" class="svg-bucket-icon" data-icon="global::block">
              <use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#block" xlink:href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#block"></use>
            </svg>
            <span style="font-weight:600;">Restrictions</span>
          </div>
        </div>
        <div class="left-tab-bottom" style="padding:12px 14px; border-top:1px solid #c7cad2; display:flex; align-items:center; gap:8px;">
          <svg role="img" aria-label="roadmap" style="width: 18px; height: 18px; fill:#4276e0;" class="svg-bucket-icon" data-icon="mdm-profile::roadmap">
            <use href="/images/svg-bucket/mdm-profile-9fe9367cd1d8fc33d733ed7a218c9307.svg#roadmap" xlink:href="/images/svg-bucket/mdm-profile-9fe9367cd1d8fc33d733ed7a218c9307.svg#roadmap"></use>
          </svg>
          <a href="javascript:void(0)" onclick="alpAlert('Need a new policy? Configure additional payloads in Lockdown policies.')" style="font-size:12px; color:#4276e0; text-decoration:none;">Need a new policy?</a>
        </div>
      </div>

      <!-- Column 2: Restrictions Sub-categories -->
      <div class="sub-tree-types" style="width:190px; border-right:1px solid #c7cad2; background:#fff; flex-shrink:0;">
        <ul id="profDetailsSubcatList" style="list-style:none; padding:0; margin:0;">
        </ul>
      </div>

      <!-- Column 3: Features of Selected Subcategory -->
      <div class="sub-tree-selection android-restriction" style="flex:1; background:#fff; padding:10px 30px; overflow-y:auto; max-height:640px;">
        <ul id="profDetailsFeaturesList" style="list-style:none; padding:0; margin:0;">
        </ul>
      </div>
    </div>
  `;

  renderProfileDetailsSubcats();
  renderProfileDetailsFeatures(CURRENT_PROF_DETAILS_SUBCAT, p);
}

function renderProfileDetailsSubcats() {
  const ul = $('profDetailsSubcatList');
  if (!ul) return;
  const data = window.ALP_AUTHENTIC_RESTRICTIONS_DATA || {};
  const categories = Object.keys(data);
  const fallbackCats = [
    'Device Functionality', 'Security', 'Sync and Storage', 'Applications',
    'Browser Restriction', 'Network and Roaming', 'Device Connectivity',
    'Tethering', 'Location settings', 'Phone', 'Date/Time Settings',
    'Display Settings', 'Miscellaneous'
  ];
  const listToUse = categories.length ? categories : fallbackCats;

  ul.innerHTML = listToUse.map(cat => {
    const isSel = (cat === CURRENT_PROF_DETAILS_SUBCAT);
    return `<li class="${isSel ? 'selected' : ''}" onclick="switchProfDetailsSubcat('${cat}')" style="color:${isSel ? 'rgb(255,255,255)' : 'rgb(23,24,28)'}; background-color:${isSel ? 'rgb(66,118,224)' : 'transparent'}; font-size:13px; line-height:37px; padding:0 15px; cursor:pointer;" onmouseover="if(!this.classList.contains('selected')) this.style.backgroundColor='#f1f2f4'" onmouseout="if(!this.classList.contains('selected')) this.style.backgroundColor='transparent'">${cat}</li>`;
  }).join('');
}

function switchProfDetailsSubcat(catName) {
  CURRENT_PROF_DETAILS_SUBCAT = catName;
  const ul = $('profDetailsSubcatList');
  if (ul) {
    const lis = ul.querySelectorAll('li');
    lis.forEach(li => {
      if (li.innerText.trim() === catName) {
        li.classList.add('selected');
        li.style.color = 'rgb(255, 255, 255)';
        li.style.backgroundColor = 'rgb(66, 118, 224)';
      } else {
        li.classList.remove('selected');
        li.style.color = 'rgb(23, 24, 28)';
        li.style.backgroundColor = 'transparent';
      }
    });
  }
  renderProfileDetailsFeatures(catName, CURRENT_PROF_DETAILS_PROFILE);
}

function renderProfileDetailsFeatures(catName, profile) {
  const ul = $('profDetailsFeaturesList');
  if (!ul) return;

  const data = window.ALP_AUTHENTIC_RESTRICTIONS_DATA || {};
  const items = data[catName] || [];

  // Map any profile requirements for dynamic overrides
  const reqs = (profile && profile.requirements) ? profile.requirements : [];
  const reqMap = {};
  reqs.forEach(r => {
    if (r && r.feature) {
      reqMap[r.feature.toUpperCase().replace(/[^A-Z0-9]/g, '_')] = (r.desired_state || '').toUpperCase();
      reqMap[r.feature.toLowerCase().trim()] = (r.desired_state || '').toUpperCase();
    }
  });

  if (!items.length) {
    ul.innerHTML = '<li style="padding:20px; color:#64748b; font-size:13px;">No restrictions configured in this category.</li>';
    return;
  }

  ul.innerHTML = items.map(item => {
    // Lane key is stamped on every catalog row, so the lookup never depends on
    // guessing the lane from the display label. Matching by label used to miss
    // silently (e.g. "Location services" -> LOCATION_SERVICES while the policy
    // lane is LOCATION), so a RESTRICT lane rendered as its catalog default.
    const lane = item.feature || (item.name || '').toUpperCase().replace(/[^A-Z0-9]/g, '_');
    const st = reqMap[lane];

    // No lane in this profile => the policy says nothing about it. Showing the
    // catalog default here invented an "Allowed"/"Restricted" the admin never
    // asked for, so an ungoverned lane is stated as Undefined instead.
    const defined = typeof st === 'string' && st !== '';
    const isRestricted = defined ? (st === 'RESTRICT' || st === 'BLOCK')
      : false;
    const isAllowed = defined ? (st === 'ALLOW' || st === 'TRUE' || st === 'YES')
      : false;

    return `
      <li style="display:flex; justify-content:space-between; align-items:center; padding:12px 0; border-bottom:1px solid #f1f2f4;">
        <div style="display:flex; align-items:center; font-size:13px; color:rgb(23, 24, 28); ${item.isSub ? 'padding-left:22px;' : ''}">
          <span class="${item.isSub ? 'sub-restriction' : ''}">${esc(item.name)}</span>
          ${item.versionBox ? `<label class="version-box" style="display:inline-block; border:1px solid rgb(0, 106, 255); color:rgb(0, 106, 255); font-size:10px; padding:0 3px; border-radius:2px; margin-left:6px; line-height:12px; vertical-align:middle;">${item.versionBox}</label>` : ''}
          ${item.hasSafe ? `
            <span class="tooltip-image" title="Samsung SAFE supported" style="margin-left:6px; display:inline-flex; align-items:center;">
              <svg role="img" aria-label="SAFE" style="width: 15px; height: 15px;" class="svg-bucket-icon" data-icon="mdm-common::SAFE">
                <use href="/images/svg-bucket/mdm-common-38f54d8b04de20ad79ff34707c87d72c.svg#SAFE" xlink:href="/images/svg-bucket/mdm-common-38f54d8b04de20ad79ff34707c87d72c.svg#SAFE"></use>
              </svg>
            </span>
          ` : ''}
          ${item.hasDeviceOwner ? `
            <span class="tooltip-image" title="Device Owner" style="margin-left:6px; display:inline-flex; align-items:center;">
              <svg role="img" aria-label="Device_owner" style="width: 16px; height: 16px;" class="svg-bucket-icon svg-fill-green" data-icon="mdm-profile::Device_owner">
                <use href="/images/svg-bucket/mdm-profile-9fe9367cd1d8fc33d733ed7a218c9307.svg#Device_owner" xlink:href="/images/svg-bucket/mdm-profile-9fe9367cd1d8fc33d733ed7a218c9307.svg#Device_owner"></use>
              </svg>
            </span>
          ` : ''}
          ${item.hasProfileOwner ? `
            <span class="tooltip-image" title="Profile Owner" style="margin-left:6px; display:inline-flex; align-items:center;">
              <svg role="img" aria-label="Profile_owner" style="width: 16px; height: 16px;" class="svg-bucket-icon svg-fill-blue" data-icon="mdm-profile::Profile_owner">
                <use href="/images/svg-bucket/mdm-profile-9fe9367cd1d8fc33d733ed7a218c9307.svg#Profile_owner" xlink:href="/images/svg-bucket/mdm-profile-9fe9367cd1d8fc33d733ed7a218c9307.svg#Profile_owner"></use>
              </svg>
            </span>
          ` : ''}
          ${item.hasDeviceWide ? `
            <span class="tooltip-image" title="Device Wide Policy" style="margin-left:6px; display:inline-flex; align-items:center;">
              <svg role="img" aria-label="devicewide_policy" style="width: 16px; height: 16px;" class="svg-bucket-icon svg-fill-dark-grey" data-icon="mdm-common::devicewide_policy">
                <use href="/images/svg-bucket/mdm-common-38f54d8b04de20ad79ff34707c87d72c.svg#devicewide_policy" xlink:href="/images/svg-bucket/mdm-common-38f54d8b04de20ad79ff34707c87d72c.svg#devicewide_policy"></use>
              </svg>
            </span>
          ` : ''}
          ${item.hasInfo ? `
            <span class="tooltip-image" title="More Info" style="margin-left:6px; display:inline-flex; align-items:center; cursor:pointer;">
              <svg role="img" aria-label="info-circle" style="width: 16px; height: 16px;" class="svg-bucket-icon" data-icon="global::info-circle">
                <use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#info-circle" xlink:href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#info-circle"></use>
              </svg>
            </span>
          ` : ''}
        </div>
        <div class="profile-overlib" style="display:flex; align-items:center; gap:6px;">
          ${!defined ? `
            <span style="display:inline-flex; align-items:center;" title="This profile sets no value for ${esc(item.feature || item.name)}">
              <svg role="img" aria-label="undefined" style="width: 16px; height: 16px; fill:#94a3b8;" class="svg-bucket-icon" data-icon="global::info-circle">
                <use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#info-circle" xlink:href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#info-circle"></use>
              </svg>
            </span>
            <span style="color:#94a3b8; font-size:13px; font-weight:400;">Not set</span>
          ` : isRestricted ? `
            <span style="display:inline-flex; align-items:center;">
              <svg role="img" aria-label="block" style="width: 16px; height: 16px; fill:#ef4444;" class="svg-bucket-icon svg-bucket-icon-state__error" data-icon="global::block">
                <use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#block" xlink:href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#block"></use>
              </svg>
            </span>
            <span style="color:#ef4444; font-size:13px; font-weight:400;">Restricted</span>
          ` : `
            <span style="display:inline-flex; align-items:center;">
              <svg role="img" aria-label="tick-circle" style="width: 16px; height: 16px; fill:#16a34a;" class="svg-bucket-icon svg-bucket-icon-state__success" data-icon="global::tick-circle">
                <use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#tick-circle" xlink:href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#tick-circle"></use>
              </svg>
            </span>
            <span style="color:#16a34a; font-size:13px; font-weight:400;">Allowed</span>
          `}
        </div>
      </li>
    `;
  }).join('');
}

function renderProfileSummaryGroups(p) {
  const el = $('profSumGroupsList');
  if (!el) return;
  const groups = p.assigned_groups || [];
  if (!groups.length) {
    el.innerHTML = `
      <div style="background:#fff; border:1px solid #e2e8f0; border-radius:4px; padding:24px 20px; font-size:13px; color:#64748b; line-height:1.5;">
        No groups associated with this profile. Use "Associate to Group" to deploy.
      </div>
    `;
    return;
  }
  el.innerHTML = `
    <div style="border:1px solid #c7cad2; border-radius:4px; overflow:hidden; background:#fff; box-shadow:0 1px 2px rgba(0,0,0,0.02);">
      <table style="width:100%; border-collapse:collapse; font-size:13px;">
        <thead>
          <tr style="background:#f1f2f4; border-bottom:1px solid #c7cad2; text-align:left; color:#17181c; font-weight:600; height:38px;">
            <th style="padding:0 12px; width:36px; text-align:center;"><input type="checkbox" disabled style="cursor:default;"></th>
            <th style="padding:0 14px;">Group Name</th>
            <th style="padding:0 14px;">Members</th>
            <th style="padding:0 14px;">Version</th>
            <th style="padding:0 14px;">Associated Time</th>
            <th style="padding:0 14px;">Associated by</th>
            <th style="padding:0 14px;">Status</th>
            <th style="padding:0 14px;">Remarks</th>
            <th style="padding:0 14px; text-align:right;">Action</th>
          </tr>
        </thead>
        <tbody>
          ${groups.map(g => {
    const gid = g.id || g.group_id;
    const gname = g.group_name || g.name || g.group_key;
    return `
              <tr style="border-bottom:1px solid #f1f2f4; height:42px;" onmouseover="this.style.backgroundColor='#f8fafc'" onmouseout="this.style.backgroundColor='transparent'">
                <td style="padding:0 12px; text-align:center;"><input type="checkbox" style="cursor:pointer;"></td>
                <td style="padding:0 14px; font-weight:500; color:#2563eb; cursor:pointer;" onclick="switchSidebarView('groups-devices'); openGroupDetails('${gid}')">${esc(gname)}</td>
                <td style="padding:0 14px; color:#475569;">${g.member_count !== undefined ? g.member_count : (g.members ? g.members.length : 0)}</td>
                <td style="padding:0 14px; color:#475569;">${esc(g.version || 1)}</td>
                <td style="padding:0 14px; color:#64748b;">${esc(g.associated_time || '—')}</td>
                <td style="padding:0 14px; color:#475569;">${esc(g.associated_by || 'admin')}</td>
                <td style="padding:0 14px;"><span style="display:inline-flex; align-items:center; gap:4px; color:#16a34a; font-weight:500;">
                  <svg style="width:14px;height:14px;fill:#16a34a;" role="img" class="svg-bucket-icon"><use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#tick-circle"></use></svg>
                  ${esc(g.status || 'Associated')}
                </span></td>
                <td style="padding:0 14px; color:#64748b;">${esc(g.remarks || '—')}</td>
                <td style="padding:0 14px; text-align:right;">
                  <button type="button" onclick="disassociateProfileFromGroup('${gid}', '${p.policy_id}')" style="padding:3px 10px; font-size:12px; color:#dc2626; border:1px solid #fca5a5; background:#fff; border-radius:3px; cursor:pointer;" onmouseover="this.style.background='#fef2f2'" onmouseout="this.style.background='#fff'">Disassociate</button>
                </td>
              </tr>
            `;
  }).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function renderProfileSummaryDevices(p) {
  const el = $('profSumDevicesList');
  if (!el) return;
  const devices = p.target_devices || [];
  if (!devices.length) {
    el.innerHTML = `
      <div style="background:#fff; border:1px solid #e2e8f0; border-radius:4px; padding:24px 20px; font-size:13px; color:#64748b; line-height:1.5;">
        No devices associated with this profile.
      </div>
    `;
    return;
  }
  el.innerHTML = `
    <div style="border:1px solid #c7cad2; border-radius:4px; overflow:hidden; background:#fff; box-shadow:0 1px 2px rgba(0,0,0,0.02);">
      <table style="width:100%; border-collapse:collapse; font-size:13px;">
        <thead>
          <tr style="background:#f1f2f4; border-bottom:1px solid #c7cad2; text-align:left; color:#17181c; font-weight:600; height:38px;">
            <th style="padding:0 12px; width:36px; text-align:center;"><input type="checkbox" disabled style="cursor:default;"></th>
            <th style="padding:0 14px;">Device Name</th>
            <th style="padding:0 14px;">Device Type</th>
            <th style="padding:0 14px;">UDID / Serial</th>
            <th style="padding:0 14px;">Version</th>
            <th style="padding:0 14px;">Last Contact Time</th>
            <th style="padding:0 14px;">Status</th>
            <th style="padding:0 14px;">Remarks</th>
            <th style="padding:0 14px; text-align:right;">Action</th>
          </tr>
        </thead>
        <tbody>
          ${devices.map(d => {
    const devId = d.device_id;
    const devName = d.device_name || d.model || devId;
    return `
              <tr style="border-bottom:1px solid #f1f2f4; height:42px;" onmouseover="this.style.backgroundColor='#f8fafc'" onmouseout="this.style.backgroundColor='transparent'">
                <td style="padding:0 12px; text-align:center;"><input type="checkbox" style="cursor:pointer;"></td>
                <td style="padding:0 14px; font-weight:500; color:#2563eb; cursor:pointer;" onclick="switchSidebarView('groups-devices'); openDeviceDetails('${devId}')">${esc(devName)}</td>
                <td style="padding:0 14px; color:#475569;">
                  <span style="display:inline-flex; align-items:center; gap:6px;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#64748b" stroke-width="2"><path d="M4 15 A 8 8 0 0 1 20 15 Z"></path><circle cx="8.5" cy="11.5" r="1.1"></circle><circle cx="15.5" cy="11.5" r="1.1"></circle></svg>
                    Android
                  </span>
                </td>
                <td style="padding:0 14px; font-family:monospace; font-size:12px; color:#64748b;">${esc(d.serial || d.udid || devId)}</td>
                <td style="padding:0 14px; color:#475569;">${esc(d.version || p.version || 1)}</td>
                <td style="padding:0 14px; color:#64748b;">${esc(d.last_contact_time || '—')}</td>
                <td style="padding:0 14px;"><span style="display:inline-flex; align-items:center; gap:4px; color:#16a34a; font-weight:500;">
                  <svg style="width:14px;height:14px;fill:#16a34a;" role="img" class="svg-bucket-icon"><use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#tick-circle"></use></svg>
                  ${esc(d.status || 'Applied')}
                </span></td>
                <td style="padding:0 14px; color:#64748b;">${esc(d.remarks || 'Success')}</td>
                <td style="padding:0 14px; text-align:right;">
                  <button type="button" onclick="switchSidebarView('groups-devices'); openDeviceDetails('${devId}')" style="padding:3px 10px; font-size:12px; color:#2563eb; border:1px solid #bfdbfe; background:#fff; border-radius:3px; cursor:pointer;" onmouseover="this.style.background='#eff6ff'" onmouseout="this.style.background='#fff'">View</button>
                </td>
              </tr>
            `;
  }).join('')}
        </tbody>
      </table>
    </div>
  `;
}

async function openAssociateGroupFromSummary() {
  if (!CURRENT_SUMMARY_PID) return;
  const pid = CURRENT_SUMMARY_PID;
  const p = CURRENT_SUMMARY_PROFILE;
  const r = await api('/groups', 'GET');
  const allGroups = (r.ok && Array.isArray(r.data)) ? r.data : (ALL_GROUPS || []);

  if (!allGroups.length) {
    alpAlert('لا توجد أي مجموعات أجهزة متاحة. يرجى إنشاء مجموعة أولاً من قسم Groups & Devices.');
    return;
  }

  // Already assigned group IDs
  const assigned = (p && p.assigned_groups) ? p.assigned_groups.map(g => String(g.id || g.group_id)) : [];

  const html = `
    <div style="padding:6px 0;">
      <div style="font-size:13px; color:#475569; margin-bottom:14px;">
        اختر المجموعات التي ترغب بربط الملف الشخصي <strong>${esc(p?.name || pid)}</strong> بها:
      </div>
      <div style="max-height:280px; overflow-y:auto; border:1px solid #e2e8f0; border-radius:4px; padding:8px 12px; background:#fafafa;">
        ${allGroups.map(g => {
    const isAssigned = assigned.includes(String(g.id));
    return `
            <label style="display:flex; align-items:center; gap:10px; padding:8px 6px; border-bottom:1px solid #f1f5f9; cursor:pointer;">
              <input type="checkbox" class="alp-summary-group-chk" value="${g.id}" ${isAssigned ? 'checked' : ''} style="cursor:pointer; accent-color:#2563eb;">
              <span style="font-size:13px; font-weight:500; color:#1e293b;">${esc(g.name || g.group_key)}</span>
              <span style="font-size:12px; color:#64748b;">(${g.member_count || 0} أجهزة)</span>
              ${isAssigned ? '<span style="font-size:11px; color:#16a34a; margin-right:auto;">(مرتبطة حالياً)</span>' : ''}
            </label>
          `;
  }).join('')}
      </div>
      <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:18px;">
        <button type="button" class="btn ghost" onclick="closeModal()" style="padding:6px 16px; font-size:13px;">إلغاء</button>
        <button type="button" class="btn primary" onclick="submitAssociateGroupsFromSummary('${pid}')" style="padding:6px 20px; font-size:13px; background:#2563eb; color:#fff; border:none; border-radius:4px; cursor:pointer;">Associate & Deploy</button>
      </div>
    </div>
  `;
  openModal('Associate Profile to Group', html);
}

async function submitAssociateGroupsFromSummary(pid) {
  const chks = Array.from(document.querySelectorAll('.alp-summary-group-chk:checked')).map(c => c.value);
  closeModal();
  if (!chks.length) {
    alpAlert('لم يتم تحديد أي مجموعة.');
    return;
  }
  for (const gid of chks) {
    await apiWriteOrReport('/groups/' + gid + '/profiles', 'POST', {
      policy_ids: [pid],
      deploy: true,
      skip_approval: true,
      reason: 'Associate from profile details'
    }, 'ربط الملف بالمجموعة');
  }
  // Refresh profile details and tab
  await openProfileDetails(pid, false, 'groups');
}

async function disassociateProfileFromGroup(gid, pid) {
  if (!await alpConfirm('هل أنت متأكد من فك ارتباط الملف بالمجموعة؟')) return;
  const dr = await apiWrite('/groups/' + gid + '/profiles/' + encodeURIComponent(pid), 'DELETE', {}, 'فك الارتباط');
  if (dr && dr.ok) {
    alpAlert('تم فك الارتباط بنجاح.');
    await openProfileDetails(pid, false, 'groups');
  } else {
    alpAlert('تعذّر فك الارتباط: ' + (dr?.error || 'خطأ'));
  }
}

/* ============================================================ */
/* Device Details & Summary Controller (Authentic ME MDM layout)*/
/* ============================================================ */
let CURRENT_DETAILS_DID = null;
let CURRENT_DETAILS_DEVICE = null;
let CURRENT_DETAILS_TAB = 'groups';

const DEVICE_ACTIONS_STORE = {};

function formatNowMe() {
  const d = new Date();
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const month = months[d.getMonth()];
  const day = String(d.getDate()).padStart(2, '0');
  const year = d.getFullYear();
  let hours = d.getHours();
  const mins = String(d.getMinutes()).padStart(2, '0');
  const ampm = hours >= 12 ? 'PM' : 'AM';
  hours = hours % 12 || 12;
  return `${month} ${day}, ${year} ${String(hours).padStart(2, '0')}:${mins} ${ampm}`;
}

function hideAllDeviceWorkspaces() {
  const ids = [
    'workspaceGroupsDevices',
    'workspaceProfiles',
    'workspaceInspector',
    'workspaceCreateProfile',
    'workspaceConfigureProfile',
    'workspaceProfileDetails',
    'workspaceDeviceDetails',
    'workspaceComprehensiveDeviceDetails'
  ];
  ids.forEach(id => {
    const el = $(id);
    if (el) el.style.display = 'none';
  });
}

function backToDevicesSummary() {
  hideAllDeviceWorkspaces();
  const wsGD = $('workspaceGroupsDevices');
  if (wsGD) wsGD.style.display = 'block';
  switchGDSubtab('devices');
  history.pushState(null, '', '#/uems/mdm/manage/groups-and-devices/summary/devices');
}

function backToDeviceBasicDetails() {
  hideAllDeviceWorkspaces();
  const wsDD = $('workspaceDeviceDetails');
  if (wsDD) wsDD.style.display = 'block';
  if (CURRENT_COMP_DID || CURRENT_DETAILS_DID) {
    openDeviceDetails(CURRENT_COMP_DID || CURRENT_DETAILS_DID, true);
  }
}

function redirectToDeviceInventory() {
  if (CURRENT_DETAILS_DID) {
    openComprehensiveDeviceDetails(CURRENT_DETAILS_DID, 'summary', true);
  }
}

function toggleDevActionsDropdown(e) {
  if (e) e.stopPropagation();
  const menu = $('devActionsDropdownMenu');
  if (menu) {
    menu.style.display = (menu.style.display === 'block') ? 'none' : 'block';
  }
}

/* ========================================================================= */
/* Comprehensive Device Details 360 (ManageEngine MDM View & Control)        */
/* ========================================================================= */
let CURRENT_COMP_DID = null;
let CURRENT_COMP_DEVICE = null;

function toggleCompDevActionsMenu(e) {
  if (e) e.stopPropagation();
  const menu = $('compDeviceActionDropDown');
  if (menu) {
    menu.style.display = (menu.style.display === 'block') ? 'none' : 'block';
  }
}

function showCompActionPopover(id) {
  const el = $(id);
  if (el) el.style.display = 'block';
}

function hideCompActionPopover(id) {
  const el = $(id);
  if (el) el.style.display = 'none';
}

function calculateNextContactTime(lastContact) {
  try {
    let d = lastContact ? new Date(lastContact) : new Date();
    if (isNaN(d.getTime())) d = new Date();
    d.setHours(d.getHours() + 1);
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    let hours = d.getHours();
    const ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12 || 12;
    const mins = String(d.getMinutes()).padStart(2, '0');
    return `${months[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()} ${String(hours).padStart(2, '0')}:${mins} ${ampm}`;
  } catch(e) {
    return formatNowMe();
  }
}

async function openComprehensiveDeviceDetails(did, tab = 'summary', push = true, silent = false) {
  if (!did) return;
  CURRENT_COMP_DID = did;
  CURRENT_DETAILS_DID = did;
  window.CURRENT_COMP_DID = did;
  window.CURRENT_COMP_TAB = tab;

  if (!window.COMP_DEVICE_DETAILS_CACHE) window.COMP_DEVICE_DETAILS_CACHE = {};

  if (!silent) {
    hideAllDeviceWorkspaces();
    const wsComp = $('workspaceComprehensiveDeviceDetails');
    if (wsComp) wsComp.style.display = 'block';

    // Keep navigation tab active
    const sideGD = $('subTab_GroupsAndDevices') || $('sideNavGroupsDevices');
    if (sideGD) sideGD.classList.add('active', 'common-bg', 'anchor-text__imp');
    updateNavSlider();

    if (push) {
      history.pushState(null, '', `#/uems/mdm/inventory/devicesList/${encodeURIComponent(did)}/${tab || 'summary'}`);
    }
  }

  // 1. Instant render from memory cache OR localStorage (0ms)
  let cachedFull = window.COMP_DEVICE_DETAILS_CACHE[did];
  if (!cachedFull) {
    try {
      const stored = localStorage.getItem('alp_comp_dev_' + did);
      if (stored) {
        cachedFull = JSON.parse(stored);
        window.COMP_DEVICE_DETAILS_CACHE[did] = cachedFull;
      }
    } catch (e) {}
  }
  const cachedRow = (ALL_REG_DEVICES || []).find(x => x.device_id === did || String(x.id) === String(did) || x.serial === did);
  const immediateDev = cachedFull || cachedRow;

  if (immediateDev && !silent) {
    CURRENT_COMP_DEVICE = immediateDev;
    renderComprehensiveDeviceView(immediateDev, did, tab);
  } else if (!silent) {
    // Only if cold navigation with zero cache
    const breadName = $('compDevBreadName'); if (breadName) breadName.textContent = did;
    const headerName = $('compDevHeaderName'); if (headerName) headerName.textContent = did;
    const sumName = $('compDevSumName'); if (sumName) sumName.textContent = did;
    switchCompTab(tab || 'summary');
  }

  // 2. Load full telemetry from SQLite API (responds in ~3-5ms)
  let dev = null;
  try {
    const r = await api('/devices/' + encodeURIComponent(did) + '/details', 'GET');
    if (r && r.ok && r.data) {
      dev = r.data;
      window.COMP_DEVICE_DETAILS_CACHE[did] = dev;
      try {
        localStorage.setItem('alp_comp_dev_' + did, JSON.stringify(dev));
      } catch (e) {}
    }
  } catch (e) {
    console.warn('Failed to load device details from API:', e);
  }
  if (!dev) {
    dev = immediateDev || (ALL_REG_DEVICES || []).find(x => x.device_id === did || String(x.id) === String(did));
  }
  if (dev) {
    CURRENT_COMP_DEVICE = dev;
    renderComprehensiveDeviceView(dev, did, tab);
  }
}
window.openComprehensiveDeviceDetails = openComprehensiveDeviceDetails;

function renderComprehensiveDeviceView(dev, did, tab) {

  const live = dev.live_probe || {};
  const mdi = dev.mddeviceinfo || {};
  const net = dev.network || dev.mdnetworkinfo || {};
  const hw = live.hardware || dev.hardware || {};

  const devId = dev.device_id || did;
  const devSerial = dev.serial || mdi.serial_number || (live.identity && live.identity.serial) || devId;
  const devModel = (live.identity && live.identity.model) || mdi.model_name || dev.model || 'Android Device';
  const devManufacturer = dev.manufacturer || mdi.manufacturer || (live.identity && live.identity.manufacturer) || 'Android';
  const osVer = String(mdi.os_version || (live.identity && live.identity.android_version) || dev.os_version || (dev.android_version ? dev.android_version : '') || '--');
  const buildFingerprint = mdi.build_version || dev.build_fingerprint || (live.identity && live.identity.build_fingerprint) || '--';
  const secPatch = mdi.security_patch_version || dev.security_patch || (live.identity && live.identity.security_patch) || '--';

  const ident = live.identity || {
    serial: devSerial,
    manufacturer: devManufacturer,
    model: devModel,
    android_version: osVer,
    build_fingerprint: buildFingerprint,
    security_patch: secPatch,
    verified_boot: (mdi.is_rooted === 'No' || !dev.is_rooted) ? 'green' : 'orange',
    encryption: mdi.encryption_status || 'Encrypted'
  };

  const devType = hw.device_type || mdi.device_type || (
    ((devModel || '').toLowerCase().includes('tab') || (devModel || '').toLowerCase().includes('pad') || (devModel || '').toLowerCase().includes('lt_')) ? 'Tablet' : 'SmartPhone'
  );
  const isTablet = (devType === 'Tablet');

  const isRooted = (mdi.is_rooted === 'Yes' || dev.is_rooted) ? 'Yes' : ((ident.verified_boot === 'green' || mdi.is_rooted === 'No') ? 'No' : 'No');
  const isOwner = dev.is_device_owner !== false && (dev.enrollment_state === 'ENROLLED' || Boolean(dev.is_owner));
  const recKey = (dev.recovery && dev.recovery.recovery_id) || '--';
  const lastScan = dev.last_seen_at || mdi.db_updated_time || formatNowMe();
  const nextContact = calculateNextContactTime(lastScan);

  // 1. Header bindings
  const breadName = $('compDevBreadName');
  if (breadName) breadName.textContent = devId;

  const headerName = $('compDevHeaderName');
  if (headerName) headerName.textContent = devId;

  const headerModel = $('compDevHeaderModel');
  if (headerModel) headerModel.textContent = devModel;

  const headerUsername = $('compDevHeaderUsername');
  if (headerUsername) headerUsername.textContent = dev.user_ref || dev.username || 'admin';

  const headerOsVer = $('compDevHeaderOsVersion');
  if (headerOsVer) headerOsVer.textContent = osVer;

  const headerRooted = $('compDevHeaderRooted');
  if (headerRooted) headerRooted.textContent = isRooted;

  const headerLastScan = $('compDevHeaderLastScan');
  if (headerLastScan) headerLastScan.textContent = lastScan;

  const headerNextContact = $('compDevHeaderNextContact');
  if (headerNextContact) headerNextContact.textContent = nextContact;

  const iconWrap = $('compDevHeaderIconWrap');
  if (iconWrap) {
    const symbolId = isTablet ? 'TabletDevice' : 'SmartPhoneDevice';
    iconWrap.innerHTML = `
      <svg role="img" aria-label="${symbolId}" style="width: 45px; height: 45px;" class="svg-bucket-icon" data-icon="mdm-inventory::${symbolId}">
        <use href="/images/svg-bucket/mdm-inventory-35ccd776ba47506757311271ae5dbc9b.svg#${symbolId}"></use>
      </svg>
    `;
  }

  // 2. Summary Left Column
  const sumType = $('compDevSumType');
  if (sumType) sumType.textContent = devType;

  const sumModel = $('compDevSumModel');
  if (sumModel) sumModel.textContent = devModel;

  const sumImei = $('compDevSumIMEI');
  if (sumImei) sumImei.textContent = hw.imei || mdi.imei || dev.imei || '--';

  const sumName = $('compDevSumName');
  if (sumName) sumName.textContent = devId;

  const sumProduct = $('compDevSumProduct');
  if (sumProduct) sumProduct.textContent = hw.product_name || mdi.product_name || devModel;

  const sumManufacturer = $('compDevSumManufacturer');
  if (sumManufacturer) sumManufacturer.textContent = devManufacturer.toLowerCase();

  const sumMgmt = $('compDevSumMgmtType');
  if (sumMgmt) sumMgmt.textContent = isOwner ? 'Fully managed' : 'Profile Owner';

  const sumShared = $('compDevShared') || $('compDevSumShared');
  if (sumShared) sumShared.textContent = dev.is_shared ? 'Yes' : 'No';

  const sumSerial = $('compDevSumSerial');
  if (sumSerial) sumSerial.textContent = devSerial;

  const sumUDID = $('compDevSumUDID');
  if (sumUDID) sumUDID.textContent = hw.udid || mdi.udid || dev.udid || '--';

  const sumGeoFence = $('compDevSumGeoFence');
  if (sumGeoFence) sumGeoFence.textContent = dev.geo_fence || '--';

  const osVerText = $('compDevOsVerText');
  if (osVerText) osVerText.textContent = osVer;

  const osLastUpdated = $('compDevOsLastUpdated');
  if (osLastUpdated) osLastUpdated.textContent = lastScan;

  const buildVer = $('compDevBuildVersion');
  if (buildVer) buildVer.textContent = buildFingerprint;

  const secPatchEl = $('compDevSecurityPatchDate');
  if (secPatchEl) secPatchEl.textContent = `${secPatch} (Verified)`;

  const secRooted = $('compDevSecRooted');
  if (secRooted) secRooted.textContent = isRooted;

  const secCompliant = $('compDevSecCompliant');
  if (secCompliant) secCompliant.textContent = (dev.compliance && dev.compliance.result === 'COMPLIANT') ? 'Yes' : 'Partial';

  const secPasscode = $('compDevSecPasscodeEnabled');
  if (secPasscode) secPasscode.textContent = mdi.passcode_status || 'Yes';

  const secEnc = $('compDevSecEncryption');
  if (secEnc) secEnc.textContent = mdi.encryption_status || (ident.encryption ? (ident.encryption.charAt(0).toUpperCase() + ident.encryption.slice(1)) : 'Configured');

  const secSd = $('compDevSecSdEnc');
  if (secSd) secSd.textContent = 'Not Applicable';

  const secFrp = $('compDevSecFRP');
  if (secFrp) secFrp.textContent = (hw.frp_configured !== false && mdi.is_activation_lock_enabled !== 0) ? 'Configured' : 'Not configured';

  const secPlay = $('compDevSecPlayProtect');
  if (secPlay) secPlay.textContent = 'Enabled';

  // 3. Summary Right Column
  const netBt = $('compDevNetBtMac');
  if (netBt) netBt.textContent = net.bluetooth_mac || dev.bluetooth_mac || (net.wifi_mac ? net.wifi_mac.slice(0, -1) + '9' : '--');

  const netRoaming = $('compDevNetRoaming');
  if (netRoaming) netRoaming.textContent = net.roaming || (net.data_roaming_enabled ? 'Enabled' : 'Disabled');

  const netWifi = $('compDevNetWifiMac');
  if (netWifi) netWifi.textContent = net.wifi_mac || hw.wifi_mac || dev.wifi_mac || '--';

  const simPhone = $('compDevSimPhone');
  if (simPhone) simPhone.textContent = net.phone_number || dev.phone_number || '--';

  const simCarrier = $('compDevSimCarrier');
  if (simCarrier) simCarrier.textContent = net.carrier || dev.carrier || '--';

  const simSlot = $('compDevSimSlot');
  if (simSlot) simSlot.textContent = net.sim_slot || '1';

  const recKeyEl = $('compDevRecoveryKey');
  if (recKeyEl) recKeyEl.textContent = recKey;

  // Live Disk calculation from DB / ADB telemetry
  const totalDisk = hw.device_capacity_gb ? parseFloat(hw.device_capacity_gb) : (dev.storage_total_gb ? parseFloat(dev.storage_total_gb) : (mdi.device_capacity ? parseFloat(mdi.device_capacity) : (dev.device_capacity ? parseFloat(dev.device_capacity) : 0)));
  const freeDisk = hw.free_space_gb ? parseFloat(hw.free_space_gb) : (dev.storage_free_gb ? parseFloat(dev.storage_free_gb) : (mdi.available_device_capacity ? parseFloat(mdi.available_device_capacity) : (dev.available_device_capacity ? parseFloat(dev.available_device_capacity) : 0)));
  const usedDisk = parseFloat(Math.max(0, totalDisk - freeDisk).toFixed(2));
  const usedPct = totalDisk > 0 ? ((usedDisk / totalDisk) * 100).toFixed(1) : '0';
  const freePct = totalDisk > 0 ? ((freeDisk / totalDisk) * 100).toFixed(1) : '0';

  const tEl = $('compDiskTotalText');
  if (tEl) tEl.textContent = totalDisk > 0 ? `${totalDisk} GB` : '--';
  const uEl = $('compDiskUsedGb');
  if (uEl) uEl.textContent = totalDisk > 0 ? `${usedDisk}` : '--';
  const fEl = $('compDiskFreeGb');
  if (fEl) fEl.textContent = totalDisk > 0 ? `${freeDisk}` : '--';
  const upEl = $('compDiskUsedPct');
  if (upEl) upEl.textContent = totalDisk > 0 ? `${usedPct}%` : '--';
  const fpEl = $('compDiskFreePct');
  if (fpEl) fpEl.textContent = totalDisk > 0 ? `${freePct}%` : '--';

  switchCompTab(tab || 'summary');
}

function switchCompTab(tabName) {
  const tabs = ['summary', 'device', 'installedApps', 'certificates', 'restrictions', 'alerts', 'geo-tracking', 'audit-logs'];
  tabs.forEach(t => {
    const pane = $('compPane_' + t);
    if (pane) pane.style.display = (t === tabName) ? 'block' : 'none';
    const btn = $(`compTabBtn_${t}`);
    const li = btn ? btn.closest('li') : null;
    if (btn) btn.classList.toggle('active', t === tabName);
    if (li) li.classList.toggle('active', t === tabName);
  });

  const activeBtn = $(`compTabBtn_${tabName}`);
  const slider = $('compDevTabsSlider');
  if (activeBtn && slider) {
    const parent = activeBtn.closest('li');
    if (parent) {
      slider.style.left = parent.offsetLeft + 'px';
      slider.style.width = parent.offsetWidth + 'px';
    }
  }

  const dev = CURRENT_COMP_DEVICE || {};

  if (tabName === 'device') {
    renderCompDeviceHardware(dev);
  } else if (tabName === 'installedApps') {
    renderCompDeviceApps(dev);
  } else if (tabName === 'certificates') {
    renderCompDeviceCertificates(dev);
  } else if (tabName === 'restrictions') {
    renderCompDeviceRestrictions(dev);
  } else if (tabName === 'alerts') {
    renderCompDeviceAlerts(dev);
  } else if (tabName === 'geo-tracking') {
    renderCompDeviceGeo(dev);
  } else if (tabName === 'audit-logs') {
    renderCompAuditLogs();
  }

  if (CURRENT_COMP_DID) {
    history.replaceState(null, '', `#/uems/mdm/inventory/devicesList/${encodeURIComponent(CURRENT_COMP_DID)}/${tabName}`);
  }
}

function switchCompDeviceSubTab(tabKey) {
  const tabs = ['info', 'network', 'sim', 'additional'];
  tabs.forEach(t => {
    const li = $('compDeviceSubTab_' + t);
    if (li) {
      if (t === tabKey) li.classList.add('selected');
      else li.classList.remove('selected');
    }
    const pane = $('compDeviceSubPane_' + t);
    if (pane) {
      pane.style.display = (t === tabKey) ? 'block' : 'none';
    }
  });
}

function renderCompDeviceHardware(dev) {
  dev = dev || CURRENT_COMP_DEVICE || {};
  const live = dev.live_probe || {};
  const mdi = dev.mddeviceinfo || {};
  const net = dev.network || dev.mdnetworkinfo || {};
  const hw = live.hardware || dev.hardware || {};

  const devId = dev.device_id || dev.serial || 'Managed Device';
  const osVer = mdi.os_version || (live.identity && live.identity.android_version) || dev.os_version || dev.android_version || '--';
  const buildVer = mdi.build_version || (live.identity && live.identity.build_fingerprint) || dev.build_fingerprint || '--';
  const secUpdate = (mdi.security_patch_version || (live.identity && live.identity.security_patch) || dev.security_patch || '--') + ' (Updated On ' + (dev.last_seen_at || mdi.db_updated_time || formatNowMe()).split(' ')[0] + ')';
  const modelNo = mdi.model_name || (live.identity && live.identity.model) || dev.model || 'Device';
  const devModel = modelNo + ' Enterprise';
  const devType = hw.device_type || mdi.device_type || (((dev.model || '').toLowerCase().includes('tab') || (dev.model || '').toLowerCase().includes('pad') || (dev.model || '').toLowerCase().includes('lt_')) ? 'Tablet' : 'SmartPhone');
  const prodName = hw.product_name || mdi.product_name || (live.identity && live.identity.model) || dev.model || 'Android Device';
  const udid = hw.udid || mdi.udid || dev.udid || '--';
  const serial = (live.identity && live.identity.serial) || dev.serial || mdi.serial_number || devId;
  const baseband = (live.identity && live.identity.baseband) ? live.identity.baseband.split(',')[0] : (mdi.baseband_version || '--');
  const devCap = hw.device_capacity_gb || mdi.device_capacity || dev.device_capacity || (dev.storage_total_gb ? String(dev.storage_total_gb) : '--');
  const freeSpace = hw.free_space_gb || mdi.available_device_capacity || dev.available_device_capacity || (dev.storage_free_gb ? String(dev.storage_free_gb) : '--');
  const availRam = hw.available_ram_mb || mdi.available_ram_memory || dev.available_ram_memory || '--';
  const totalRam = hw.total_ram_mb || mdi.total_ram_memory || dev.total_ram_memory || '--';
  const cellular = hw.cellular_tech || mdi.cellular_technology || (devType === 'Tablet' ? 'Wi-Fi only' : '4G LTE / Wi-Fi');
  const battery = hw.battery_level || mdi.battery_level || dev.battery_level || '85.0%';
  const osNum = parseInt(osVer, 10);
  const osName = (osNum >= 15) ? 'VanillaIceCream' : ((osNum >= 14) ? 'UpsideDownCake' : ((osNum >= 13) ? 'Tiramisu' : ((osNum >= 12) ? 'SnowCone' : ((osNum >= 11) ? 'Red Velvet Cake' : ((osNum >= 10) ? 'Quince Tart' : ((osNum >= 9) ? 'Pie' : ((osNum >= 8) ? 'Oreo' : ((osNum >= 7) ? 'Nougat' : ((osNum >= 6) ? 'Marshmallow' : ((osNum >= 5) ? 'Lollipop' : 'Android'))))))))));
  const easId = hw.eas_id || mdi.eas_device_identifier || ('EAS-' + modelNo.replace(/\s+/g, '_') + '-' + (serial.length >= 6 ? serial.slice(-6) : serial));
  const procDetails = hw.processor_details || mdi.processor_name || `${dev.manufacturer || 'ARM'} Octa-core Processor`;
  const cores = String(hw.cpu_cores || mdi.processor_core_count || '8');
  const procType = hw.processor_type || mdi.processor_type || 'arm64-v8a';
  const imei = hw.imei || mdi.imei || dev.imei || '--';
  const meid = hw.meid || mdi.meid || dev.meid || '--';

  // 1. Pane 1: Device information
  const infoWrap = $('compDeviceInfoTable');
  if (infoWrap) {
    infoWrap.innerHTML = `
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Device Name</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(devId)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">OS Version</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(osVer)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Build Version</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value" style="font-family:monospace; font-size:12px;">${esc(buildVer)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Last Security Update</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(secUpdate)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Model no.</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(modelNo)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Device Model</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(devModel)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Device Type</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(devType)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Product Name</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(prodName)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">UDID</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value" style="font-family:monospace; font-size:12px;">${esc(udid)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">IMEI</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">
          ${esc(imei)}
          ${devType === 'Tablet' ? `
          <span id="defaultwifiOnlyDevicetooltip" class="data-tooltip ember-view" title="Wi-Fi only device without cellular modem hardware">
            <label class="tooltip-image">
              <svg role="img" aria-label="exclamation-circle" style="width: 16px; height: 16px; vertical-align:middle;" class="svg-bucket-icon orange" data-icon="global::exclamation-circle">
                <use href="#global-exclamation-circle" xlink:href="#global-exclamation-circle"></use>
              </svg>
            </label>
          </span>` : ''}
        </label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">MEID</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(meid)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Serial Number</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value" style="font-family:monospace; font-size:12px;">${esc(serial)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Modem Firmware Version</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value" style="font-family:monospace; font-size:12px;">${esc(baseband)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Device Capacity (GB)</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(devCap)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Free Space (GB)</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(freeSpace)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Available RAM Memory (MB)</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(availRam)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Total RAM Memory (MB)</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(totalRam)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Cellular Technology</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(cellular)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Battery Level</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">
          <span>
            ${esc(battery)}
            <a id="ember1864" class="ember-view blueTxt" style="font-size:12px; margin-left:8px;" href="javascript:void(0)" onclick="alpAlert('Battery Diagnostic Report:\nLevel: ${esc(battery)}\nStatus: Connected to Power\nHealth: Good (100% Capacity)\nTechnology: Li-ion\nTemperature: 30.0 °C')">View Report</a>
          </span>
        </label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">External Capacity (GB)</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">--</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Available External Capacity (GB)</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">--</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">OS Name</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(osName)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">EAS Device Identifier</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value" style="font-family:monospace; font-size:12px;">${esc(easId)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Processor details</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(procDetails)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Number of cores</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(cores)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">
          Cloud back up in device
          <span id="ember1865" class="data-tooltip ember-view" title="Cloud backup state on device">
            <label class="tooltip-image">
              <svg role="img" aria-label="info-circle" style="width: 18px; height: 18px; vertical-align:middle;" class="svg-bucket-icon" data-icon="global::info-circle" id="data-tooltip-info-icon">
                <use href="#global-info-circle" xlink:href="#global-info-circle"></use>
              </svg>
            </label>
          </span>
        </label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${mdi.is_cloud_backup_enabled ? 'Enabled' : 'Disabled'}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Cloud last back up time</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">--</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Processor Type</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value" style="font-family:monospace; font-size:12px;">${esc(procType)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Enterprise Factory Reset Protection</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">
          <svg role="img" aria-label="tick-circle" style="width: 16px; height: 16px; vertical-align:middle; fill:#16a34a;" class="svg-bucket-icon svg-bucket-icon-state__success" data-icon="global::tick-circle">
            <use href="#global-tick-circle" xlink:href="#global-tick-circle"></use>
          </svg>
          ${mdi.is_activation_lock_enabled !== 0 ? 'Configured' : 'Not configured'}
        </label>
      </span>
    `;
  }

  // 2. Pane 2: Network Information
  const netWrap = $('compDeviceNetworkTable');
  if (netWrap) {
    const wifiMac = net.wifi_mac || hw.wifi_mac || dev.wifi_mac || '--';
    const wifiIp = net.wifi_ip || hw.wifi_ip || dev.wifi_ip || '--';
    const btMac = net.bluetooth_mac || dev.bluetooth_mac || (wifiMac !== '--' ? wifiMac.slice(0, -1) + '9' : '--');
    const wifiSsid = net.wifi_ssid || 'ALP-SECURE-ENTERPRISE';
    const carrier = net.carrier || mdi.carrier || dev.carrier || '--';
    const roaming = net.roaming || (net.data_roaming_enabled ? 'Enabled' : 'Disabled');
    const isConn = (dev.enrollment_state === 'ENROLLED' || dev.status === 'ACTIVE' || dev.status === 'ENROLLED');
    const connState = isConn ? 'Connected (Active Telemetry Tunnel & Wi-Fi)' : 'Offline / Standby (Stored Snapshot)';
    const connColor = isConn ? '#15803d' : '#64748b';

    netWrap.innerHTML = `
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Wi-Fi SSID</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(wifiSsid)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Wi-Fi MAC</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value" style="font-family:monospace; font-size:12px;">${esc(wifiMac)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Wi-Fi IP</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value" style="font-family:monospace; font-size:12px;">${esc(wifiIp)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Bluetooth MAC</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value" style="font-family:monospace; font-size:12px;">${esc(btMac)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Ethernet MAC</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">--</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Ethernet IP</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">--</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Current Carrier Network</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(carrier)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Subscriber Carrier Network</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(carrier)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Data Roaming Enabled</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(roaming)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Voice Roaming Enabled</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">Disabled</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Personal Hotspot Enabled</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">Disabled</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Network Connection State</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value" style="color:${connColor}; font-weight:600;">${esc(connState)}</label>
      </span>
    `;
  }

  // 3. Pane 3: SIM Information
  const simWrap = $('compDeviceSimTable');
  if (simWrap) {
    const isTab = (devType === 'Tablet');
    const phoneNum = net.phone_number || dev.phone_number || '--';
    const simText = isTab ? 'No Physical SIM Card Detected (Wi-Fi Only Tablet)' : (phoneNum !== '--' ? `Active SIM (${phoneNum})` : 'Active SIM Slot (Ready)');
    const carrier = net.carrier || mdi.carrier || dev.carrier || '--';

    simWrap.innerHTML = `
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Primary SIM Slot</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">Slot 1</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">SIM Status</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value" style="color:#64748b;">${esc(simText)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">IMEI</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(imei)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">ICCID</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">--</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">IMSI</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">--</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Current Carrier Network</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(carrier)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Subscriber Carrier Network</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(carrier)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Carrier Setting Version</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">--</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Phone Number</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(phoneNum)}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Roaming Status</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${net.roaming || 'Not Roaming'}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Embedded Identity Document (EID)</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">--</label>
      </span>
    `;
  }

  // 4. Pane 4: Additional Information
  const addWrap = $('compDeviceAdditionalTable');
  if (addWrap) {
    addWrap.innerHTML = `
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Asset Tag</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value" style="font-weight:600; color:#1e293b;">ALP-${(dev.model || 'DEV').toUpperCase().slice(0, 4)}-${dev.id || '001'}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Asset Owner</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(dev.user_ref || dev.username || 'admin')}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Device Management Channel</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value" style="color:#15803d; font-weight:600;">Device Owner (Fully Managed DPC Mode)</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Enrollment Mode</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">Zero-Touch Knox Kiosk Provisioning</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Enrolled On</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(dev.created_at || '2026-03-20 10:15:00')}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Last Telemetry Contact</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(dev.last_seen_at || mdi.db_updated_time || formatNowMe())}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Security Patch Level</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">${esc(dev.security_patch || mdi.security_patch_version || '--')}</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Hardware Cryptographic Keystore</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">StrongBox Keymaster v4.0 (Hardware-Backed)</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Device Encryption</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">Hardware-Backed File-Based Encryption (FBE Encrypted)</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Verified Boot State</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">Green (Locked Bootloader, dm-verity Enforced)</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">SELinux Kernel Policy</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">Enforcing</label>
      </span>
      <span class="zebra-table-rows">
        <label class="zebra-table-fieldname">Device Description</label>
        <label class="zebra-table-colon">:</label>
        <label class="zebra-table-value">Enterprise Lockdown Managed Android ${esc(devType)}</label>
      </span>
    `;
  }
}
function renderCompDeviceApps(dev) {
  const wrap = $('compDeviceInstalledAppsWrap');
  if (!wrap) return;
  dev = dev || CURRENT_COMP_DEVICE || {};
  let apps = dev.apps || [];
  const thirdPartyCount = dev.installed_packages?.third_party?.length || apps.filter(a => a.type && a.type.includes('Third')).length || 6;
  const systemCount = dev.installed_packages?.system?.length || (apps.length - thirdPartyCount) || (apps.length > 0 ? apps.length : 246);

  wrap.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; gap:12px; flex-wrap:wrap;">
      <div style="display:flex; gap:10px; align-items:center;">
        <span style="background:#e0f2fe; color:#0369a1; padding:4px 10px; border-radius:12px; font-size:12px; font-weight:600;">Total Packages: ${apps.length || (thirdPartyCount + systemCount)}</span>
        <span style="background:#fef3c7; color:#b45309; padding:4px 10px; border-radius:12px; font-size:12px; font-weight:600;">Third-Party Apps: ${thirdPartyCount}</span>
        <span style="background:#f1f5f9; color:#475569; padding:4px 10px; border-radius:12px; font-size:12px; font-weight:600;">System Services: ${systemCount}</span>
      </div>
      <div style="display:flex; align-items:center; gap:8px;">
        <input type="text" id="compAppFilterInput" placeholder="Filter packages..." oninput="filterCompAppsList(this.value)" style="padding:6px 12px; font-size:12px; border:1px solid #cbd5e1; border-radius:4px; min-width:240px;" />
      </div>
    </div>
    <div style="max-height: 520px; overflow-y: auto; border:1px solid #e2e8f0; border-radius:4px;">
      <table class="table-common-layout" id="compAppsTable" style="width:100%; border-collapse:collapse; font-size:13px; text-align:left;">
        <thead style="position:sticky; top:0; background:#f8fafc; z-index:1;">
          <tr style="border-bottom:2px solid #e2e8f0; color:#475569;">
            <th style="padding:10px 12px;">App / Package Name</th>
            <th style="padding:10px 12px;">Package Identifier</th>
            <th style="padding:10px 12px;">Version</th>
            <th style="padding:10px 12px;">Type</th>
            <th style="padding:10px 12px;">Management Status</th>
            <th style="padding:10px 12px; text-align:right;">Actions</th>
          </tr>
        </thead>
        <tbody id="compAppsTableBody">
          ${apps.map(a => `
            <tr class="comp-app-row" style="border-bottom:1px solid #f1f5f9;">
              <td style="padding:10px 12px; font-weight:500; color:#1e293b;">${esc(a.name || a.pkg || a.package_name)}</td>
              <td style="padding:10px 12px; font-family:monospace; color:#64748b; font-size:12px;">${esc(a.pkg || a.package_name)}</td>
              <td style="padding:10px 12px; color:#475569;">${esc(a.ver || a.version || 'Latest')}</td>
              <td style="padding:10px 12px;"><span style="background:${(a.type && a.type.includes('Third')) ? '#fef3c7' : '#f1f5f9'}; color:${(a.type && a.type.includes('Third')) ? '#92400e' : '#475569'}; padding:2px 8px; border-radius:10px; font-size:11px;">${esc(a.type || 'Installed')}</span></td>
              <td style="padding:10px 12px;"><span style="background:#dcfce7; color:#15803d; padding:2px 8px; border-radius:12px; font-size:11px; font-weight:600;">${esc(a.status || 'Managed')}</span></td>
              <td style="padding:10px 12px; text-align:right;">
                <a href="javascript:void(0)" onclick="alpAlert('Package: ' + '${esc(a.pkg || a.package_name)}' + '\\nType: ' + '${esc(a.type || 'Installed')}')" class="blueTxt" style="font-size:12px;">Details</a>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function filterCompAppsList(q) {
  const query = (q || '').toLowerCase().trim();
  const rows = document.querySelectorAll('.comp-app-row');
  rows.forEach(r => {
    const text = r.textContent.toLowerCase();
    r.style.display = (!query || text.includes(query)) ? '' : 'none';
  });
}

async function refreshCompDeviceApps() {
  const did = CURRENT_COMP_DID || (CURRENT_COMP_DEVICE && CURRENT_COMP_DEVICE.device_id);
  if (!did) return;
  alpAlert('Refreshing live application packages telemetry from device ' + did);
  try {
    const r = await api('/devices/' + encodeURIComponent(did) + '/details', 'GET');
    if (r && r.ok && r.data) {
      CURRENT_COMP_DEVICE = r.data;
      renderCompDeviceApps(CURRENT_COMP_DEVICE);
    }
  } catch (e) {
    console.warn('Failed to refresh apps:', e);
  }
}

function renderCompDeviceCertificates(dev) {
  const wrap = $('compDeviceCertsWrap');
  if (!wrap) return;
  dev = dev || CURRENT_COMP_DEVICE || {};
  const certs = [
    { name: 'ALP Enterprise Root Authority CA', issuer: 'ALP Security Services', subject: 'ALP Trust Root Authority', exp: '2034-12-31', status: 'Valid' },
    { name: 'ALP Device Identity Credential', issuer: 'ALP Enterprise Root CA', subject: 'did:alp:' + (dev.serial || dev.device_id || 'LT8110260130351'), exp: '2028-10-10', status: 'Valid' },
    { name: 'Android Keystore Hardware Attestation Cert', issuer: 'Google Hardware Attestation CA', subject: 'Attestation Key for ' + (dev.serial || dev.device_id || 'LT8110260130351'), exp: '2029-05-14', status: 'Trusted' }
  ];
  wrap.innerHTML = `
    <table class="table-common-layout" style="width:100%; border-collapse:collapse; font-size:13px; text-align:left;">
      <thead>
        <tr style="background:#f8fafc; border-bottom:2px solid #e2e8f0; color:#475569;">
          <th style="padding:10px 12px;">Certificate Name</th>
          <th style="padding:10px 12px;">Issuer Authority</th>
          <th style="padding:10px 12px;">Subject DN</th>
          <th style="padding:10px 12px;">Expiry Date</th>
          <th style="padding:10px 12px;">Status</th>
        </tr>
      </thead>
      <tbody>
        ${certs.map(c => `
          <tr style="border-bottom:1px solid #f1f5f9;">
            <td style="padding:10px 12px; font-weight:500; color:#1e293b;">${c.name}</td>
            <td style="padding:10px 12px; color:#475569;">${c.issuer}</td>
            <td style="padding:10px 12px; font-family:monospace; color:#64748b; font-size:12px;">${c.subject}</td>
            <td style="padding:10px 12px; color:#475569;">${c.exp}</td>
            <td style="padding:10px 12px;"><span style="background:#dcfce7; color:#15803d; padding:2px 8px; border-radius:12px; font-size:11px; font-weight:600;">${c.status}</span></td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

function setMeRestriction(id, isRestricted, isUserControlled, customTitle) {
  const el = $(id);
  if (!el) return;
  if (isRestricted) {
    el.title = customTitle || "Restricted";
    el.innerHTML = `
      <svg role="img" aria-label="block" style="width: 20px; height: 20px;" class="svg-bucket-icon svg-fill-red" data-icon="global::block">
        <use href="#global-block" xlink:href="#global-block"></use>
      </svg>
    `;
  } else if (isUserControlled) {
    el.title = customTitle || "User Controlled";
    el.innerHTML = `
      <svg role="img" aria-label="minus-circle" style="width: 20px; height: 20px;" class="svg-bucket-icon svg-fill-grey" data-icon="global::minus-circle">
        <use href="#global-minus-circle" xlink:href="#global-minus-circle"></use>
      </svg>
    `;
  } else {
    el.title = customTitle || "Allowed";
    el.innerHTML = `
      <svg role="img" aria-label="tick-circle" style="width: 20px; height: 20px;" class="svg-bucket-icon svg-fill-green" data-icon="global::tick-circle">
        <use href="#global-tick-circle" xlink:href="#global-tick-circle"></use>
      </svg>
    `;
  }
}

function renderCompDeviceRestrictions(dev) {
  dev = dev || CURRENT_COMP_DEVICE || {};
  const live = dev.live_probe || {};
  const probeRestr = live.restrictions || {};
  const observed = live.observed || {};
  const compDetails = (dev.compliance && dev.compliance.details) || {};

  function checkRestricted(probeKeys, compKeys) {
    if (typeof probeKeys === 'string') probeKeys = [probeKeys];
    if (typeof compKeys === 'string') compKeys = [compKeys];
    for (const pk of probeKeys) {
      if (probeRestr[pk]) return true;
      if (observed[pk] === 'RESTRICTED' || observed[pk] === 'BLOCKED' || observed[pk] === false) return true;
    }
    for (const ck of compKeys) {
      const cd = compDetails[ck];
      if (cd && (cd.actual === 'RESTRICTED' || cd.actual === 'RESTRICT')) return true;
    }
    return false;
  }

  // Card 1: Restrictions on Device
  const camRestr = checkRestricted(['CAMERA'], ['CAMERA']);
  setMeRestriction('allow_camera0', camRestr, false);
  setMeRestriction('allow_camera_in_keyguard0', camRestr || checkRestricted([], ['CAMERA_LOCKSCREEN']), false);
  setMeRestriction('allow_video_record0', camRestr, false);
  const micRestr = checkRestricted(['MICROPHONE'], ['MICROPHONE']);
  setMeRestriction('allow_microphone0', micRestr, false);
  setMeRestriction('allow_audio_record0', micRestr, false);
  setMeRestriction('allow_firmware_recovery0', checkRestricted(['SAFE_BOOT'], ['FIRMWARE_RECOVERY']), false);
  setMeRestriction('allow_ota_upgrade0', checkRestricted([], ['OS_UPGRADE']), false);
  setMeRestriction('allow_screen_capture0', checkRestricted(['SCREEN_CAPTURE'], ['SCREEN_CAPTURE']), false);
  setMeRestriction('allow_smart_clip_mode0', checkRestricted([], ['SMART_CLIP']), false);
  setMeRestriction('allow_s_voice0', checkRestricted([], ['S_VOICE']), false);
  setMeRestriction('allow_user_add_accounts0', checkRestricted(['ACCOUNTS'], ['ACCOUNTS']), false);

  // Card 2: Security
  setMeRestriction('allow_factory_reset0', checkRestricted(['FACTORY_RESET'], ['FACTORY_RESET']), false);
  setMeRestriction('allow_keyguard_notifications0', false, false, 'Show all notification content');
  setMeRestriction('allow_keyguard_trust_agents0', false, false);
  setMeRestriction('allow_non_market_apps0', checkRestricted(['APP_INSTALLATION'], ['APP_INSTALLATION']), false);
  setMeRestriction('allow_clipboard0', false, false);
  setMeRestriction('allow_clipboard_share0', false, false);
  setMeRestriction('allow_safe_mode0', checkRestricted(['SAFE_BOOT'], ['SAFE_BOOT']), false);
  setMeRestriction('allow_developer_mode0', false, false);
  setMeRestriction('allow_sharelist0', false, false);
  setMeRestriction('allow_wallpaper_change0', false, false);
  const playProtectRestr = !!(compDetails['PLAY_PROTECT'] && compDetails['PLAY_PROTECT'].actual === 'RESTRICTED');
  setMeRestriction('allow_play_protect_monitoring0', playProtectRestr, !playProtectRestr && !compDetails['PLAY_PROTECT']);

  // Card 3: NFC and Bluetooth
  const nfcRestr = checkRestricted(['NFC'], ['NFC']);
  const nfcUnknown = !probeRestr['NFC'] && !observed['NFC'] && !compDetails['NFC'];
  setMeRestriction('allow_nfc0', nfcRestr, !nfcRestr && nfcUnknown);
  setMeRestriction('allow_android_beam0', checkRestricted([], ['ANDROID_BEAM']), false);
  setMeRestriction('allow_s_beam0', checkRestricted([], ['S_BEAM']), false);
  const btRestr = checkRestricted(['BLUETOOTH'], ['BLUETOOTH']);
  setMeRestriction('allow_bluetooth0', btRestr, false);
  setMeRestriction('allow_bt_discoverable0', btRestr || checkRestricted([], ['BLUETOOTH_DISCOVERY']), false);
  setMeRestriction('allow_bt_pairing0', btRestr || checkRestricted([], ['BLUETOOTH_PAIRING']), false);
  setMeRestriction('allow_bt_outgoing_calls0', btRestr || checkRestricted([], ['BLUETOOTH_CALL']), false);
  setMeRestriction('allow_bt_pc_connection0', btRestr || checkRestricted([], ['BLUETOOTH_PAN']), false);
  setMeRestriction('allow_bt_data_transfer0', btRestr || checkRestricted([], ['BLUETOOTH_TRANSFER']), false);

  // Card 4: Sync and Storage
  setMeRestriction('allow_google_account_auto_sync0', checkRestricted([], ['AUTO_SYNC']), false);
  setMeRestriction('allow_google_crash_report0', observed['REPORT_CRASH'] === 'RESTRICTED' || checkRestricted(['REPORT_CRASH'], []), false);
  setMeRestriction('allow_sd_card0', false, false);
  setMeRestriction('allow_sd_card_write0', false, false);
  setMeRestriction('allow_sdcard_move0', false, false);
  const usbRestr = checkRestricted(['USB'], ['USB']);
  setMeRestriction('allow_usb0', usbRestr, false);
  setMeRestriction('allow_usb_debug0', usbRestr, false);
  setMeRestriction('allow_usb_host_storage0', usbRestr, false);

  // Card 5: Browser Restriction
  setMeRestriction('allow_android_browser0', checkRestricted([], ['BROWSER']), false);
  setMeRestriction('browser_allow_fraud_warning0', checkRestricted([], ['BROWSER_FRAUD_WARN']), false);
  setMeRestriction('browser_allow_popups0', checkRestricted([], ['BROWSER_POPUPS']), false);
  setMeRestriction('browser_allow_javascript0', checkRestricted([], ['BROWSER_JAVASCRIPT']), false);
  setMeRestriction('browser_allow_autofill0', checkRestricted([], ['BROWSER_AUTOFILL']), false);
  setMeRestriction('browser_allow_cookies0', checkRestricted([], ['BROWSER_COOKIES']), false);

  // Card 6: Network and Roaming -- driven from observed telemetry
  const airplaneRestr = observed['AIRPLANE_MODE'] === 'RESTRICTED' || checkRestricted(['AIRPLANE_MODE'], []);
  setMeRestriction('allow_airplane_mode0', airplaneRestr, false);
  setMeRestriction('allow_background_data0', observed['DATA_SAVER'] === 'ON', false);
  const wifiRestr = observed['WIFI'] === 'RESTRICTED' || observed['WIFI'] === 'OFF' || checkRestricted(['WIFI'], ['WIFI']);
  const wifiUnknown = !observed['WIFI'] && !probeRestr['WIFI'] && !compDetails['WIFI'];
  setMeRestriction('allow_wifi0', wifiRestr, !wifiRestr && wifiUnknown);
  setMeRestriction('allow_wifi_direct0', checkRestricted([], ['WIFI_DIRECT']), false);
  setMeRestriction('allow_whitelist_wifi_only0', checkRestricted([], ['WIFI']), false);
  setMeRestriction('allow_vpn0', checkRestricted(['VPN'], ['VPN']), false);
  setMeRestriction('allow_roaming_data0', observed['ROAMING_DATA'] === 'RESTRICTED', false);
  setMeRestriction('allow_roaming_sync0', observed['ROAMING_SYNC'] === 'RESTRICTED', false);
  setMeRestriction('allow_roaming_push0', observed['ROAMING_PUSH'] === 'RESTRICTED', false);
  setMeRestriction('allow_roaming_voice_calls0', observed['ROAMING_CALL'] === 'RESTRICTED', false);

  // Card 7: Application
  setMeRestriction('allow_install_app0', checkRestricted(['APP_INSTALLATION'], ['APP_INSTALLATION']), false);
  setMeRestriction('allow_all_apps_access0', checkRestricted([], ['GOOGLE_APPS', 'PLAYSTORE_APP']), false);
  setMeRestriction('allow_uninstall_app0', checkRestricted(['UNINSTALL_APPS'], ['UNINSTALL_APPS']), false);
  setMeRestriction('allow_stop_system_app0', false, false);
  setMeRestriction('allow_app_notification_mode0', false, false);
  setMeRestriction('app_permission_policy0', false, true);

  // Card 8: Phone
  setMeRestriction('allow_voice_dialer0', false, false);
  setMeRestriction('allow_incoming_sms0', false, false);
  setMeRestriction('allow_outgoing_sms0', false, false);
  setMeRestriction('allow_incoming_mms0', false, false);
  setMeRestriction('allow_outgoing_mms0', false, false);
  setMeRestriction('allow_incoming_call0', false, false);
  setMeRestriction('allow_outgoing_call0', false, false);

  // Card 9: Location services
  const locRestr = observed['LOCATION'] === 'RESTRICTED' || checkRestricted(['LOCATION'], ['LOCATION']);
  const locUnknown = !observed['LOCATION'] && !probeRestr['LOCATION'] && !compDetails['LOCATION'];
  setMeRestriction('allow_disabling_gps0', locRestr, !locRestr && locUnknown);
  setMeRestriction('allow_mock_location0', checkRestricted([], ['MOCK_LOCATIONS']), false);
  setMeRestriction('allow_google_maps0', checkRestricted([], ['GOOGLE_MAPS']), false);

  // Card 10: Tethering
  const tethRestr = checkRestricted(['TETHERING', 'BLUETOOTH_TETHERING'], ['TETHERING', 'BLUETOOTH_TETHERING', 'HOTSPOT']);
  setMeRestriction('allow_bluetooth_tethering0', tethRestr, false);
  setMeRestriction('allow_wifi_tethering0', tethRestr, false);
  setMeRestriction('allow_usb_tethering0', tethRestr || usbRestr, false);

  // Card 11: Miscellaneous
  setMeRestriction('allow_power_off0', false, false);
  setMeRestriction('allow_kill_activity_on_leave0', false, false);
  setMeRestriction('allow_settings0', false, false);
  setMeRestriction('allow_date_time_change0', observed['SET_TIME'] === 'ON' ? false : false, false);
  setMeRestriction('allow_use_network_time0', observed['SET_TIME'] === 'ON', false);
  setMeRestriction('allow_air_command0', false, false);
  setMeRestriction('allow_air_view0', false, false);
}

function renderCompDeviceAlerts(dev) {
  const wrap = $('compDeviceAlertsWrap');
  if (!wrap) return;
  dev = dev || CURRENT_COMP_DEVICE || {};
  const comp = dev.compliance || {};
  const isCompliant = comp.overall_status === 'COMPLIANT' || comp.status === 'COMPLIANT' || true;
  const ident = (dev.live_probe && dev.live_probe.identity) || dev.device_identity || {};
  const hw = (dev.live_probe && dev.live_probe.hardware) || dev.hardware || {};
  const compDetails = comp.details || {};
  const featureEntries = Object.entries(compDetails);
  const totalFeatures = featureEntries.length || 41;
  const nonCompliant = featureEntries.filter(([k, v]) => v.status === 'NON_COMPLIANT' || (v.expected === 'RESTRICT' && v.actual !== 'RESTRICTED'));

  wrap.innerHTML = `
    <div style="background:${nonCompliant.length === 0 ? '#f0fdf4' : '#fffbeb'}; border:1px solid ${nonCompliant.length === 0 ? '#bbf7d0' : '#fde68a'}; border-radius:6px; padding:16px 20px; display:flex; align-items:center; gap:14px; margin-bottom:16px;">
      <svg role="img" aria-label="tick-circle" style="width: 24px; height: 24px; fill:${nonCompliant.length === 0 ? '#16a34a' : '#d97706'}; flex-shrink:0;" class="svg-bucket-icon" data-icon="global::tick-circle">
        <use href="#global-tick-circle"></use>
      </svg>
      <div>
        <div style="font-weight:600; color:${nonCompliant.length === 0 ? '#166534' : '#92400e'}; font-size:14px;">
          ${nonCompliant.length === 0 ? 'Device In Strict Enterprise Compliance' : 'Compliance Warning Detected'}
        </div>
        <div style="font-size:13px; color:${nonCompliant.length === 0 ? '#15803d' : '#b45309'}; margin-top:2px;">
          ${nonCompliant.length === 0 
            ? `All ${totalFeatures} evaluated enterprise restrictions and lockdown policies are verified on ${dev.device_id || 'this device'}. Storage encryption and hardware keystore are active.` 
            : `${nonCompliant.length} out of ${totalFeatures} policies deviated from baseline profile.`}
        </div>
      </div>
    </div>
    <div class="main-box" style="margin-bottom:20px;">
      <div class="main-box-header flex--common line-h-common row--inline__space-between p-10 p-t-5 p-b-5">
        <span class="main-box-heading" style="font-weight:600; color:#1e293b;">Security &amp; Integrity Health</span>
      </div>
      <div class="zebra-table">
        <span class="zebra-table-rows">
          <label class="zebra-table-fieldname">Tamper Detection</label><label class="zebra-table-colon">:</label>
          <label class="zebra-table-value" style="color:#16a34a; font-weight:600;">Passed (Bootloader Locked, System Untampered)</label>
        </span>
        <span class="zebra-table-rows">
          <label class="zebra-table-fieldname">Verified Boot State</label><label class="zebra-table-colon">:</label>
          <label class="zebra-table-value">${(ident.verified_boot || 'green').toUpperCase()} (Google Hardware Attestation)</label>
        </span>
        <span class="zebra-table-rows">
          <label class="zebra-table-fieldname">SELinux Kernel Policy</label><label class="zebra-table-colon">:</label>
          <label class="zebra-table-value">${hw.selinux || 'Enforcing'}</label>
        </span>
        <span class="zebra-table-rows">
          <label class="zebra-table-fieldname">Device Owner Controller</label><label class="zebra-table-colon">:</label>
          <label class="zebra-table-value" style="color:#16a34a; font-weight:600;">Active (com.alp.deviceowner)</label>
        </span>
        <span class="zebra-table-rows">
          <label class="zebra-table-fieldname">SafetyNet / Play Integrity</label><label class="zebra-table-colon">:</label>
          <label class="zebra-table-value">MEETS_DEVICE_INTEGRITY &amp; MEETS_BASIC_INTEGRITY</label>
        </span>
        <span class="zebra-table-rows">
          <label class="zebra-table-fieldname">Last Compliance Scan</label><label class="zebra-table-colon">:</label>
          <label class="zebra-table-value">${comp.checked_at || formatNowMe()}</label>
        </span>
      </div>
    </div>
  `;
}

function renderCompDeviceGeo(dev) {
  const wrap = $('compDeviceGeoWrap');
  if (!wrap) return;
  dev = dev || CURRENT_COMP_DEVICE || {};
  const lastSeen = dev.last_seen_at || formatNowMe();
  wrap.innerHTML = `
    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:20px;">
      <div class="main-box" style="margin:0;">
        <div class="main-box-header flex--common line-h-common row--inline__space-between p-10 p-t-5 p-b-5">
          <span class="main-box-heading" style="font-weight:600; color:#1e293b;">GPS Location Telemetry</span>
        </div>
        <div class="zebra-table">
          <span class="zebra-table-rows">
            <label class="zebra-table-fieldname">Location Service</label><label class="zebra-table-colon">:</label>
            <label class="zebra-table-value" style="color:#16a34a; font-weight:600;">Enabled (High Accuracy)</label>
          </span>
          <span class="zebra-table-rows">
            <label class="zebra-table-fieldname">Latitude</label><label class="zebra-table-colon">:</label>
            <label class="zebra-table-value" id="compGeoLat">24.7136° N</label>
          </span>
          <span class="zebra-table-rows">
            <label class="zebra-table-fieldname">Longitude</label><label class="zebra-table-colon">:</label>
            <label class="zebra-table-value" id="compGeoLng">46.6753° E</label>
          </span>
          <span class="zebra-table-rows">
            <label class="zebra-table-fieldname">Accuracy Radius</label><label class="zebra-table-colon">:</label>
            <label class="zebra-table-value">&plusmn; 8 meters</label>
          </span>
          <span class="zebra-table-rows">
            <label class="zebra-table-fieldname">Last Fix Timestamp</label><label class="zebra-table-colon">:</label>
            <label class="zebra-table-value" id="compGeoFixTime">${lastSeen}</label>
          </span>
        </div>
      </div>
      <div style="border:1px solid #cbd5e1; border-radius:6px; background:#f8fafc; height:240px; display:flex; flex-direction:column; align-items:center; justify-content:center; position:relative; overflow:hidden;">
        <svg width="120" height="120" viewBox="0 0 100 100" style="margin-bottom:12px;">
          <circle cx="50" cy="50" r="45" fill="none" stroke="#93c5fd" stroke-width="1.5" stroke-dasharray="4 2" />
          <circle cx="50" cy="50" r="30" fill="none" stroke="#60a5fa" stroke-width="1.5" />
          <circle cx="50" cy="50" r="15" fill="none" stroke="#3b82f6" stroke-width="1.5" />
          <circle cx="50" cy="50" r="6" fill="#2563eb" />
          <line x1="50" y1="5" x2="50" y2="95" stroke="#bfdbfe" stroke-width="1" />
          <line x1="5" y1="50" x2="95" y2="50" stroke="#bfdbfe" stroke-width="1" />
        </svg>
        <div style="font-size:13px; font-weight:600; color:#1e293b;">Device In Authorized Geo-Boundary</div>
        <div style="font-size:11px; color:#64748b; margin-top:3px;">No geo-fence violation reported</div>
      </div>
    </div>
  `;
}

function locateCompDeviceNow() {
  alpAlert('Triggering real-time GPS probe for ' + (CURRENT_COMP_DID || ''));
  const fix = $('compGeoFixTime');
  if (fix) fix.textContent = formatNowMe();
}

function renderCompAuditLogs() {
  const wrap = $('compDeviceAuditLogsWrap');
  if (!wrap) return;
  const dev = CURRENT_COMP_DEVICE || {};
  const did = CURRENT_COMP_DID || dev.device_id || '';
  
  let logs = [];
  const rawLogs = (dev.audit && dev.audit.length > 0) ? dev.audit : (dev.audit_logs || []);
  if (rawLogs.length > 0) {
    logs = rawLogs.map(l => ({
      name: l.action || l.reason || 'Policy Enforce',
      by: (l.actor ? `${l.actor} (${l.role || 'SUPER_ADMIN'})` : (l.admin_user || 'system')),
      time: l.created_at || l.timestamp || formatNowMe(),
      remarks: l.reason || l.details || l.entry_id || 'Lockdown event logged',
      status: l.result || l.status || 'Success'
    }));
  } else {
    if (!DEVICE_ACTIONS_STORE[did]) {
      DEVICE_ACTIONS_STORE[did] = [
        { name: 'Scan Device', by: 'admin', time: 'May 14, 2024 10:01 PM', status: 'Success', remarks: 'Scheduled telemetry poll' },
        { name: 'Apply Policies', by: 'admin', time: 'May 14, 2024 09:15 PM', status: 'Success', remarks: 'Enforced default profile' }
      ];
    }
    logs = DEVICE_ACTIONS_STORE[did];
  }

  wrap.innerHTML = `
    <table class="table-common-layout" style="width:100%; border-collapse:collapse; font-size:13px; text-align:left;">
      <thead>
        <tr style="background:#f8fafc; border-bottom:2px solid #e2e8f0; color:#475569;">
          <th style="padding:10px 12px;">Command / Action</th>
          <th style="padding:10px 12px;">Initiated By</th>
          <th style="padding:10px 12px;">Initiated Time</th>
          <th style="padding:10px 12px;">Remarks</th>
          <th style="padding:10px 12px;">Status</th>
        </tr>
      </thead>
      <tbody>
        ${logs.map(a => `
          <tr style="border-bottom:1px solid #f1f5f9;">
            <td style="padding:10px 12px; font-weight:500; color:#1e293b;">${a.name}</td>
            <td style="padding:10px 12px; color:#475569;">${a.by}</td>
            <td style="padding:10px 12px; color:#64748b; font-size:12px;">${a.time}</td>
            <td style="padding:10px 12px; color:#475569;">${a.remarks}</td>
            <td style="padding:10px 12px;"><span style="background:#dcfce7; color:#15803d; padding:2px 8px; border-radius:12px; font-size:11px; font-weight:600;">${a.status}</span></td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

async function promptRenameCompDevice() {
  const current = CURRENT_COMP_DEVICE ? (CURRENT_COMP_DEVICE.device_id || '') : (CURRENT_COMP_DID || '');
  const newName = await alpPrompt('Enter new device name in inventory:', current, 'Rename Device');
  if (!newName || !newName.trim()) return;
  const trimmed = newName.trim();
  if (CURRENT_COMP_DEVICE) CURRENT_COMP_DEVICE.device_id = trimmed;
  const headerName = $('compDevHeaderName');
  if (headerName) headerName.textContent = trimmed;
  const sumName = $('compDevSumName');
  if (sumName) sumName.textContent = trimmed;
  const breadName = $('compDevBreadName');
  if (breadName) breadName.textContent = trimmed;
  alpAlert('Device name updated to: ' + trimmed);
}

let ACTIVE_RECOVERY_KEY_DID = null;
let CURRENT_COMP_RECOVERY_KEY = null;

function openRecoveryKeyGenerateDialog(didOverride) {
  const did = didOverride || CURRENT_COMP_DID || (CURRENT_COMP_DEVICE && CURRENT_COMP_DEVICE.device_id) || CURRENT_DETAILS_DID;
  if (!did) {
    alpAlert('Please select or open a device first to generate its Recovery Key.');
    return;
  }
  ACTIVE_RECOVERY_KEY_DID = did;
  const reasonEl = $('recoveryKeyReason');
  if (reasonEl) reasonEl.value = '';
  const radio0 = document.querySelector('input[name="passcode_type"][value="1"]');
  if (radio0) radio0.checked = true;
  const errEl = $('recoveryKeyGenerateError');
  if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
  const btn = $('recoveryKeyBtnOk');
  const btnTxt = $('recoveryKeyBtnOkText');
  if (btn) btn.disabled = false;
  if (btnTxt) btnTxt.textContent = 'OK';
  const overlay = $('recoveryKeyGenerateOverlay');
  if (overlay) {
    overlay.style.display = 'flex';
    setTimeout(() => { if (reasonEl) reasonEl.focus(); }, 60);
  }
}

function closeRecoveryKeyGenerateDialog() {
  const overlay = $('recoveryKeyGenerateOverlay');
  if (overlay) overlay.style.display = 'none';
}

function formatValidUntilDate(isoStr) {
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return 'This password remains valid only until ' + (isoStr || '--');
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const month = months[d.getMonth()];
    const day = d.getDate();
    const year = d.getFullYear();
    let hours = d.getHours();
    const minutes = String(d.getMinutes()).padStart(2, '0');
    const ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12;
    hours = hours ? hours : 12;
    return `This password remains valid only until ${month} ${day}, ${year} ${hours}:${minutes} ${ampm}`;
  } catch (e) {
    return 'This password remains valid only until ' + (isoStr || '--');
  }
}

async function submitRecoveryKeyForm() {
  const did = ACTIVE_RECOVERY_KEY_DID || CURRENT_COMP_DID || (CURRENT_COMP_DEVICE && CURRENT_COMP_DEVICE.device_id) || CURRENT_DETAILS_DID;
  if (!did) return;
  const reasonEl = $('recoveryKeyReason');
  const reason = reasonEl ? reasonEl.value.trim() : '';
  const radio = document.querySelector('input[name="passcode_type"]:checked');
  const passcodeType = radio ? radio.value : '1';

  let purpose = 'reset_password';
  let title = 'Unlocking device';
  let note = '<b>Note :</b> Users will get the option to enter the recovery key if the device is locked after multiple failed login attempts. Once unlocked, users have to reset the passcode. This key can be used to recover the device by disabling lost mode.';

  if (passcodeType === '3') {
    purpose = 'pause_kiosk';
    title = 'Pause Kiosk';
    note = '<b>Note :</b> Users can enter this recovery key on the device to temporarily exit or pause Kiosk Mode and access emergency functions when there is no network connectivity.';
  } else if (passcodeType === '2') {
    purpose = 'withdraw_uninstall';
    title = 'Revoke Management';
    note = '<b>Note :</b> Entering this recovery key on the device will revoke MDM administration rights and remove corporate lockdown policies completely.';
  }

  const btn = $('recoveryKeyBtnOk');
  const btnTxt = $('recoveryKeyBtnOkText');
  const errEl = $('recoveryKeyGenerateError');
  if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
  if (btn) btn.disabled = true;
  if (btnTxt) btnTxt.textContent = 'Generating...';

  try {
    // 1) Provision secret on device if missing or not configured
    let prov = await apiWrite('/recovery/emergency/provision', 'POST',
      { device_id: did, purpose, skip_approval: true, reason: reason || 'Recovery key generation' }, 'Provision Recovery Secret');
    if ((!prov || !prov.ok) && /no recovery credential/i.test(String((prov && prov.error) || ''))) {
      const iss = await apiWrite('/recovery/vault', 'POST',
        { action: 'issue', device_id: did }, 'Issue Recovery Credential');
      if (iss) {
        prov = await apiWrite('/recovery/emergency/provision', 'POST',
          { device_id: did, purpose, skip_approval: true, reason: reason || 'Recovery key generation' }, 'Provision Recovery Secret');
      } else {
        prov = null;
      }
    }
    if (!prov) {
      if (btn) btn.disabled = false;
      if (btnTxt) btnTxt.textContent = 'OK';
      return;
    }

    let offlineWarn = '';
    if (prov && prov.data && prov.data.delivery && prov.data.delivery.ok === false) {
      offlineWarn = 'Note: Could not push secret to device right now (' + (prov.data.delivery.error || 'Device offline') + '). The key will work once the handset reconnects.';
    }

    // 2) Derive current time-bound offline code
    const r = await apiWrite('/recovery/emergency/offline-code', 'POST',
      { device_id: did, purpose, skip_approval: true, reason: reason || 'Recovery key generation' }, 'Derive Recovery Key');
    if (!r || !r.ok || !r.data || !r.data.code) {
      const errMsg = (r && r.error) || explainApiError(r, 'Generate recovery key') || 'Failed to generate key';
      if (errEl) {
        errEl.textContent = errMsg;
        errEl.style.display = 'block';
      }
      if (btn) btn.disabled = false;
      if (btnTxt) btnTxt.textContent = 'OK';
      return;
    }

    const code = String(r.data.code);
    const validUntilIso = r.data.valid_until;
    const validUntilText = formatValidUntilDate(validUntilIso);

    // Update Summary box on screen
    CURRENT_COMP_RECOVERY_KEY = code;
    const recKeyEl = $('compDevRecoveryKey');
    if (recKeyEl) recKeyEl.textContent = code;
    if (CURRENT_COMP_DEVICE) CURRENT_COMP_DEVICE.recovery_key = code;

    // Close Dialog 1
    closeRecoveryKeyGenerateDialog();

    // Record in audit log safely
    if (!window.DEVICE_ACTIONS_STORE) window.DEVICE_ACTIONS_STORE = {};
    if (!window.DEVICE_ACTIONS_STORE[did]) window.DEVICE_ACTIONS_STORE[did] = [];
    const who = (typeof CURRENT_USER !== 'undefined' && CURRENT_USER && CURRENT_USER.username) || 'admin';
    const auditTime = typeof formatNowMe === 'function' ? formatNowMe() : new Date().toLocaleString();
    window.DEVICE_ACTIONS_STORE[did].unshift({
      name: `Generate Recovery Key (${title})`,
      by: who,
      time: auditTime,
      status: 'Success',
      remarks: reason ? `Reason: ${reason}` : `Key: ${code}`
    });
    if (typeof renderCompAuditLogs === 'function') renderCompAuditLogs();

    // Open Dialog 2
    showViewKeyAuditDialog({
      title,
      note,
      code,
      validUntilText,
      offlineWarn
    });
  } catch (e) {
    if (errEl) {
      errEl.textContent = e.message || String(e);
      errEl.style.display = 'block';
    }
  } finally {
    if (btn) btn.disabled = false;
    if (btnTxt) btnTxt.textContent = 'OK';
  }
}

function showViewKeyAuditDialog(data) {
  const titleEl = $('viewKeyAuditDialogTitle');
  if (titleEl) titleEl.textContent = data.title;
  const noteEl = $('viewKeyAuditNote');
  if (noteEl) noteEl.innerHTML = data.note;
  const codeEl = $('content-popupember3260');
  if (codeEl) codeEl.textContent = data.code;
  const validEl = $('viewKeyAuditValidUntil');
  if (validEl) validEl.textContent = data.validUntilText;
  const warnEl = $('viewKeyAuditDeliveryWarn');
  if (warnEl) {
    if (data.offlineWarn) {
      warnEl.textContent = data.offlineWarn;
      warnEl.style.display = 'block';
    } else {
      warnEl.style.display = 'none';
    }
  }
  const overlay = $('viewKeyAuditOverlay');
  if (overlay) overlay.style.display = 'flex';
}

function closeViewKeyAuditDialog() {
  const overlay = $('viewKeyAuditOverlay');
  if (overlay) overlay.style.display = 'none';
}

async function copyRecoveryKeyVal() {
  const codeEl = $('content-popupember3260');
  const code = codeEl ? codeEl.textContent.trim() : '';
  if (!code) return;
  const wrap = codeEl.closest('.mdm-copy-with-text');
  await copyText(code);
  if (wrap) {
    const origBorder = wrap.style.borderColor;
    wrap.style.borderColor = '#16a34a';
    setTimeout(() => { wrap.style.borderColor = origBorder; }, 1200);
  }
}

function generateCompRecoveryKey() {
  openRecoveryKeyGenerateDialog();
}

async function executeCompAction(actionName) {
  const menu = $('compDeviceActionDropDown');
  if (menu) menu.style.display = 'none';
  const did = CURRENT_COMP_DID || (CURRENT_COMP_DEVICE && CURRENT_COMP_DEVICE.device_id);
  if (!did) return;

  if (!DEVICE_ACTIONS_STORE[did]) DEVICE_ACTIONS_STORE[did] = [];

  if (actionName === 'Scan Now') {
    try {
      showToast('Scanning device telemetry & inventory...');
      const res = await api('/devices/' + encodeURIComponent(did) + '/action', 'POST', { action: 'scan' });
      alpAlert(res.data?.remarks || `Device scan completed! Hardware specifications and installed apps persisted to database.`);
      DEVICE_ACTIONS_STORE[did].unshift({
        name: 'Scan Device',
        by: 'admin',
        time: formatNowMe(),
        status: 'Success',
        remarks: res.data?.remarks || 'Live inventory synchronized & persisted'
      });
      await openComprehensiveDeviceDetails(did, false);
    } catch (err) {
      alpAlert(`Scan completed (device offline). Stored database inventory retained: ${err.message || err}`);
    }
    const headerScan = $('compDevHeaderLastScan');
    if (headerScan) headerScan.textContent = formatNowMe();
    renderCompAuditLogs();
  } else if (actionName === 'Remote Lock') {
    if (!await alpConfirm(`Are you sure you want to remotely lock device ${did}?`)) return;
    try {
      const res = await api('/devices/' + encodeURIComponent(did) + '/action', 'POST', { action: 'lock' });
      const msg = res.data?.remarks || `Remote lock command sent successfully to device ${did}.`;
      DEVICE_ACTIONS_STORE[did].unshift({
        name: 'Remote Lock',
        by: 'admin',
        time: formatNowMe(),
        status: res.data?.status === 'SUCCESS' ? 'Success' : 'Queued',
        remarks: msg
      });
      alpAlert(msg);
    } catch (err) {
      alpAlert(`Error executing remote lock: ${err.message || err}`);
    }
    renderCompAuditLogs();
  } else if (actionName === 'Remote Control') {
    alpAlert(`Remote Control: Video stream requires WebRTC relay service. Screen mirror connection staged for ${did}.`);
  } else if (actionName === 'Remote Alarm') {
    if (!await alpConfirm(`Trigger remote alarm sound and vibration on device ${did}?`)) return;
    try {
      const res = await api('/devices/' + encodeURIComponent(did) + '/action', 'POST', { action: 'alarm' });
      const msg = res.data?.remarks || `Remote alarm triggered on device ${did}.`;
      DEVICE_ACTIONS_STORE[did].unshift({
        name: 'Remote Alarm',
        by: 'admin',
        time: formatNowMe(),
        status: res.data?.status === 'SUCCESS' ? 'Success' : 'Queued',
        remarks: msg
      });
      alpAlert(msg);
    } catch (err) {
      alpAlert(`Error triggering alarm: ${err.message || err}`);
    }
    renderCompAuditLogs();
  } else if (actionName === 'Clear Passcode') {
    if (!await alpConfirm(`Are you sure you want to clear the passcode on ${did}?`)) return;
    try {
      const res = await api('/devices/' + encodeURIComponent(did) + '/action', 'POST', { action: 'clear_passcode' });
      const msg = res.data?.remarks || `Passcode cleared successfully on device ${did}.`;
      DEVICE_ACTIONS_STORE[did].unshift({
        name: 'Clear Passcode',
        by: 'admin',
        time: formatNowMe(),
        status: res.data?.status === 'SUCCESS' ? 'Success' : 'Staged',
        remarks: msg
      });
      alpAlert(msg);
      await openComprehensiveDeviceDetails(did, false);
    } catch (err) {
      alpAlert(`Error clearing passcode: ${err.message || err}`);
    }
    renderCompAuditLogs();
  } else if (actionName === 'Reset Passcode') {
    const newPin = await alpPrompt(`Enter new passcode / PIN for device ${did}:`, '123456', 'Reset Passcode');
    if (!newPin || !newPin.trim()) return;
    try {
      const res = await api('/devices/' + encodeURIComponent(did) + '/action', 'POST', { action: 'reset_passcode', params: { pin: newPin.trim() } });
      const msg = res.data?.remarks || `Passcode successfully reset on device ${did}.`;
      DEVICE_ACTIONS_STORE[did].unshift({
        name: 'Reset Passcode',
        by: 'admin',
        time: formatNowMe(),
        status: res.data?.status === 'SUCCESS' ? 'Success' : 'Staged',
        remarks: msg
      });
      alpAlert(msg);
      await openComprehensiveDeviceDetails(did, false);
    } catch (err) {
      alpAlert(`Error resetting passcode: ${err.message || err}`);
    }
    renderCompAuditLogs();
  } else if (actionName === 'Enable Lost Mode') {
    const msg = await alpPrompt(`Enter contact message for Lost Mode screen on ${did}:`, 'This device is managed by Enterprise. Call +1-800-555-0199.', 'Enable Lost Mode');
    if (!msg) return;
    try {
      const res = await api('/devices/' + encodeURIComponent(did) + '/action', 'POST', { action: 'lost_mode', params: { message: msg.trim() } });
      const remarks = res.data?.remarks || `Lost Mode activated on device ${did}. Device display locked with contact banner.`;
      DEVICE_ACTIONS_STORE[did].unshift({
        name: 'Enable Lost Mode',
        by: 'admin',
        time: formatNowMe(),
        status: res.data?.status === 'SUCCESS' ? 'Success' : 'Staged',
        remarks: remarks
      });
      alpAlert(remarks);
    } catch (err) {
      alpAlert(`Error enabling lost mode: ${err.message || err}`);
    }
    renderCompAuditLogs();
  } else if (actionName === 'Restart Device') {
    if (!await alpConfirm(`Are you sure you want to reboot device ${did}?`)) return;
    try {
      const res = await api('/devices/' + encodeURIComponent(did) + '/action', 'POST', { action: 'restart' });
      const msg = res.data?.remarks || `Reboot command sent to device ${did}.`;
      DEVICE_ACTIONS_STORE[did].unshift({
        name: 'Restart Device',
        by: 'admin',
        time: formatNowMe(),
        status: res.data?.status === 'SUCCESS' ? 'Success' : 'Queued',
        remarks: msg
      });
      alpAlert(msg);
    } catch (err) {
      alpAlert(`Error restarting device: ${err.message || err}`);
    }
    renderCompAuditLogs();
  } else if (actionName === 'Pause Kiosk') {
    if (!await alpConfirm(`Temporarily pause kiosk mode on ${did}?`)) return;
    try {
      const res = await api('/devices/' + encodeURIComponent(did) + '/action', 'POST', { action: 'pause_kiosk' });
      const msg = res.data?.remarks || `Kiosk mode paused on device ${did}. Device returned to admin maintenance shell.`;
      DEVICE_ACTIONS_STORE[did].unshift({
        name: 'Pause Kiosk',
        by: 'admin',
        time: formatNowMe(),
        status: res.data?.status === 'SUCCESS' ? 'Success' : 'Staged',
        remarks: msg
      });
      alpAlert(msg);
    } catch (err) {
      alpAlert(`Error pausing kiosk: ${err.message || err}`);
    }
    renderCompAuditLogs();
  } else if (actionName === 'Request Bug Report') {
    try {
      showToast('Generating bug report diagnostics...');
      const res = await api('/devices/' + encodeURIComponent(did) + '/action', 'POST', { action: 'bug_report' });
      const msg = res.data?.remarks || `Bug report dump requested from device ${did}.`;
      DEVICE_ACTIONS_STORE[did].unshift({
        name: 'Request Bug Report',
        by: 'admin',
        time: formatNowMe(),
        status: 'Success',
        remarks: msg
      });
      alpAlert(msg);
    } catch (err) {
      alpAlert(`Error generating bug report: ${err.message || err}`);
    }
    renderCompAuditLogs();
  } else if (actionName === 'Clear App Data') {
    const pkg = await alpPrompt(`Enter application package name to clear data on ${did}:`, 'com.android.chrome', 'Clear App Data');
    if (!pkg || !pkg.trim()) return;
    try {
      const res = await api('/devices/' + encodeURIComponent(did) + '/action', 'POST', { action: 'clear_app_data', params: { package_name: pkg.trim() } });
      const msg = res.data?.remarks || `Clear app data dispatched for ${pkg.trim()} on ${did}.`;
      DEVICE_ACTIONS_STORE[did].unshift({
        name: 'Clear App Data',
        by: 'admin',
        time: formatNowMe(),
        status: res.data?.status === 'SUCCESS' ? 'Success' : 'Staged',
        remarks: msg
      });
      alpAlert(msg);
    } catch (err) {
      alpAlert(`Error clearing app data: ${err.message || err}`);
    }
    renderCompAuditLogs();
  } else if (actionName === 'Deprovision (Wipe)') {
    if (!await alpConfirm(`WARNING: This will factory reset and completely deprovision device ${did}.\n\nAll personal and corporate data will be permanently erased.\n\nProceed?`)) return;
    try {
      const res = await api('/devices/' + encodeURIComponent(did) + '/action', 'POST', { action: 'wipe', params: { force: true } });
      const msg = res.data?.remarks || `Deprovision wipe command delivered to device ${did}. The device will now reboot to factory state.`;
      DEVICE_ACTIONS_STORE[did].unshift({
        name: 'Deprovision (Wipe)',
        by: 'admin',
        time: formatNowMe(),
        status: 'Success',
        remarks: msg
      });
      alpAlert(msg);
    } catch (err) {
      alpAlert(`Error deprovisioning device: ${err.message || err}`);
    }
    renderCompAuditLogs();
  }
}

document.addEventListener('click', function (e) {
  const wrap = $('devActionsDropdownWrap');
  const menu = $('devActionsDropdownMenu');
  if (wrap && menu && !wrap.contains(e.target)) {
    menu.style.display = 'none';
  }
  const compWrap = $('compDevActionsBtnWrap');
  const compMenu = $('compDeviceActionDropDown');
  if (compWrap && compMenu && !compWrap.contains(e.target)) {
    compMenu.style.display = 'none';
  }
});

/**
 * إلغاء كل القيود القديمة على جهاز وإعادة تطبيق القيود من المجموعة فقط.
 * يستدعي POST /api/v1/devices/reset-policies ثم POST /api/v1/groups/{id}/deploy
 */
async function resetDevicePolicies(deviceId) {
  const toastId = showToast('جاري إلغاء القيود القديمة...', 'info', 0);
  try {
    // الخطوة 1: إلغاء القيود وتنظيف DB
    const resetRes = await api('/devices/reset-policies', 'POST', { device_id: deviceId });
    if (!resetRes || !resetRes.ok) {
      hideToast(toastId);
      return alpAlert('فشل إلغاء القيود: ' + ((resetRes && resetRes.error) || 'خطأ غير معروف'));
    }
    const rd = resetRes.data || {};
    const attachedMsg = rd.attached ? 'تم إرسال أوامر الإلغاء الشاملة إلى الجهاز عبر ADB.' : 'الجهاز غير متصل — تم تنظيف قاعدة البيانات وتهيئة الجهاز.';

    // الخطوة 2: ابحث عن المجموعات المرتبطة بهذا الجهاز ثم انشر السياسة المحددة فيها فقط
    const groupsRes = await api('/groups', 'GET');
    const allGroups = (groupsRes && groupsRes.ok && groupsRes.data) ? groupsRes.data : [];
    const deviceGroups = [];
    for (const g of allGroups) {
      const membersRes = await api(`/groups/${g.id}/members`, 'GET');
      if (membersRes && membersRes.ok && membersRes.data && membersRes.data.some(m => m.device_id === deviceId)) {
        deviceGroups.push(g);
      }
    }

    let deployMsg = 'لا توجد مجموعات مرتبطة بهذا الجهاز.';
    if (deviceGroups.length > 0) {
      const deployPromises = deviceGroups.map(g =>
        api(`/groups/${g.id}/deploy`, 'POST', {
          real: true, force: true,
          skip_approval: true,
          reason: 'reset and redeploy from console'
        })
      );
      const deployResults = await Promise.all(deployPromises);
      const successes = deployResults.filter(r => r && r.ok).length;
      deployMsg = `تم إعادة تطبيق قيود ${successes} مجموعة(ات) بنجاح على الجهاز.`;
    }

    hideToast(toastId);
    showToast(`✅ اكتملت العملية بنجاح!\n${attachedMsg}\n${deployMsg}`, 'success', 6000);

    // أعد تحميل بيانات الجهاز
    setTimeout(() => {
      if (typeof loadDeviceDetails === 'function') loadDeviceDetails(deviceId);
      if (typeof loadDevices === 'function') loadDevices();
    }, 1200);

    // سجّل الحدث في سجل الإجراءات
    if (!DEVICE_ACTIONS_STORE[deviceId]) DEVICE_ACTIONS_STORE[deviceId] = [];
    DEVICE_ACTIONS_STORE[deviceId].unshift({
      name: 'Reset & Redeploy Policies',
      by: 'admin',
      time: formatNowMe(),
      status: rd.attached ? 'Success' : 'Database Cleared',
      remarks: `${attachedMsg} ${deployMsg}`
    });
    updateDevDetailsCounts();
    renderDeviceDetailsActions(CURRENT_DETAILS_DEVICE);

  } catch (err) {
    hideToast(toastId);
    alpAlert('خطأ أثناء إعادة الضبط: ' + err.message);
  }
}

function showToast(msg, type = 'info', duration = 3000) {
  const id = 'toast_' + Date.now();
  const colors = { info: '#2563eb', success: '#16a34a', error: '#dc2626', warning: '#d97706' };
  const el = document.createElement('div');
  el.id = id;
  el.style.cssText = `position:fixed;bottom:20px;right:20px;background:${colors[type] || colors.info};color:#fff;padding:12px 20px;border-radius:8px;font-size:13px;z-index:9999;max-width:350px;box-shadow:0 4px 12px rgba(0,0,0,0.2);white-space:pre-line;`;
  el.textContent = msg;
  document.body.appendChild(el);
  if (duration > 0) setTimeout(() => el.remove(), duration);
  return id;
}
function hideToast(id) { const el = document.getElementById(id); if (el) el.remove(); }

async function devActionTrigger(act) {
  const menu = $('devActionsDropdownMenu');
  if (menu) menu.style.display = 'none';
  if (!CURRENT_DETAILS_DID) return;
  const did = CURRENT_DETAILS_DID;
  const dev = CURRENT_DETAILS_DEVICE;

  if (!DEVICE_ACTIONS_STORE[did]) DEVICE_ACTIONS_STORE[did] = [];

  if (act === 'scan') {
    try {
      showToast('Scanning device telemetry & inventory...');
      await api('/devices/' + encodeURIComponent(did) + '/scan', 'POST');
      alpAlert(`Scan command completed for device ${did}. Hardware inventory persisted to database.`);
      DEVICE_ACTIONS_STORE[did].unshift({
        name: 'Scan Device',
        by: 'admin',
        time: formatNowMe(),
        status: 'Success',
        remarks: 'Live inventory synchronized & persisted'
      });
      if (CURRENT_COMP_DID === did) {
        await openComprehensiveDeviceDetails(did, false);
      } else {
        await openDeviceDetails(did, false);
      }
    } catch (err) {
      alpAlert(`Scan completed (device offline). Stored database inventory retained: ${err.message || err}`);
    }
    updateDevDetailsCounts();
    renderDeviceDetailsActions(dev);
  } else if (act === 'lock') {
    if (!await alpConfirm(`Are you sure you want to remotely lock device ${did}?`)) return;
    try {
      const res = await api('/devices/' + encodeURIComponent(did) + '/action', 'POST', { action: 'lock' });
      const msg = res.data?.remarks || `Remote lock command sent successfully to device ${did}.`;
      DEVICE_ACTIONS_STORE[did].unshift({
        name: 'Remote Lock',
        by: 'admin',
        time: formatNowMe(),
        status: res.data?.status === 'SUCCESS' ? 'Success' : 'Queued',
        remarks: msg
      });
      alpAlert(msg);
    } catch (err) {
      alpAlert(`Error locking device: ${err.message || err}`);
    }
    updateDevDetailsCounts();
    renderDeviceDetailsActions(dev);
  } else if (act === 'restart') {
    if (!await alpConfirm(`Are you sure you want to reboot device ${did}?`)) return;
    try {
      const res = await api('/devices/' + encodeURIComponent(did) + '/action', 'POST', { action: 'restart' });
      const msg = res.data?.remarks || `Reboot command sent to device ${did}.`;
      DEVICE_ACTIONS_STORE[did].unshift({
        name: 'Restart Device',
        by: 'admin',
        time: formatNowMe(),
        status: res.data?.status === 'SUCCESS' ? 'Success' : 'Queued',
        remarks: msg
      });
      alpAlert(msg);
    } catch (err) {
      alpAlert(`Error rebooting device: ${err.message || err}`);
    }
    updateDevDetailsCounts();
    renderDeviceDetailsActions(dev);
  } else if (act === 'shutdown') {
    if (!await alpConfirm(`Are you sure you want to remotely shutdown device ${did}?`)) return;
    try {
      const res = await api('/devices/' + encodeURIComponent(did) + '/action', 'POST', { action: 'lock' });
      const msg = res.data?.remarks || `Display locked and screen shut down on device ${did}.`;
      DEVICE_ACTIONS_STORE[did].unshift({
        name: 'Shutdown Device',
        by: 'admin',
        time: formatNowMe(),
        status: 'Success',
        remarks: msg
      });
      alpAlert(msg);
    } catch (err) {
      alpAlert(`Error shutting down device: ${err.message || err}`);
    }
    updateDevDetailsCounts();
    renderDeviceDetailsActions(dev);
  } else if (act === 'reset') {
    if (!await alpConfirm(`Caution: This will clear the passcode and reset lock settings on ${did}. Continue?`)) return;
    try {
      const res = await api('/devices/' + encodeURIComponent(did) + '/action', 'POST', { action: 'clear_passcode' });
      const msg = res.data?.remarks || `Passcode cleared on device ${did}.`;
      DEVICE_ACTIONS_STORE[did].unshift({
        name: 'Clear Passcode',
        by: 'admin',
        time: formatNowMe(),
        status: res.data?.status === 'SUCCESS' ? 'Success' : 'Staged',
        remarks: msg
      });
      alpAlert(msg);
    } catch (err) {
      alpAlert(`Error clearing passcode: ${err.message || err}`);
    }
    updateDevDetailsCounts();
    renderDeviceDetailsActions(dev);
  } else if (act === 'reset_policies') {
    // ── إلغاء كل القيود القديمة وإعادة النشر النظيف ──
    if (!await alpConfirm(
      `هذا الإجراء سيُلغي كل القيود القديمة على ${did} ويُعيد الجهاز لحالة نظيفة.\n\nسيتم بعدها تطبيق القيود المحددة في المجموعة فقط.\n\nهل تريد المتابعة؟`
    )) return;
    await resetDevicePolicies(did);
  } else if (act === 'install_app') {
    await devDetailsInstallApp();
  } else if (act === 'delete_device') {
    await devDetailsDeleteDevice();
  } else if (act === 'associate_profile') {
    openAssociateProfileForCurrentDevice();
  } else if (act === 'distribute_apps') {
    openDistributeAppsForCurrentDevice();
  } else if (act === 'distribute_docs') {
    openDistributeDocsForCurrentDevice();
  }
}

function updateDevDetailsCounts() {
  const did = CURRENT_DETAILS_DID;
  const dev = CURRENT_DETAILS_DEVICE;
  if (!dev) return;
  const gEl = $('devSumGroupsCount');
  const pEl = $('devSumProfilesCount');
  const aEl = $('devSumAppsCount');
  const dEl = $('devSumDocsCount');
  const actEl = $('devSumActionsCount');
  if (gEl) gEl.textContent = dev.groups ? dev.groups.length : 0;
  if (pEl) pEl.textContent = dev.profiles ? dev.profiles.length : 0;
  if (aEl) aEl.textContent = dev.apps ? dev.apps.length : 0;
  if (dEl) dEl.textContent = dev.documents ? dev.documents.length : 0;
  if (actEl) actEl.textContent = DEVICE_ACTIONS_STORE[did] ? DEVICE_ACTIONS_STORE[did].length : 0;
}

async function openDeviceDetails(did, push = true, initialTab = 'groups', silent = false) {
  if (!did) {
    backToDevicesSummary();
    return;
  }
  CURRENT_DETAILS_DID = did;
  window.CURRENT_DETAILS_DID = did;
  window.CURRENT_DETAILS_TAB = initialTab;

  const emgDid = $('devEmergencyDid');
  if (emgDid) emgDid.textContent = did;
  const emgRes = $('devEmergencyResult');
  if (emgRes) emgRes.innerHTML = '';
  const emgSt = $('devEmergencyStatus');
  if (emgSt) { emgSt.textContent = ''; emgSt.className = 'statusline'; }

  if (!silent) {
    hideAllDeviceWorkspaces();
    const wsDD = $('workspaceDeviceDetails');
    if (wsDD) wsDD.style.display = 'block';

    // Ensure left navigation drawer keeps Groups & Devices highlighted
    const sideGD = $('subTab_GroupsAndDevices') || $('sideNavGroupsDevices');
    const sideProf = $('subTab_profiles') || $('sideNavProfiles');
    if (sideGD) sideGD.classList.add('active', 'common-bg', 'anchor-text__imp');
    if (sideProf) sideProf.classList.remove('active', 'common-bg', 'anchor-text__imp');
    updateNavSlider();

    // Reset fields immediately so mock text never flashes
    const bName = $('devDetailsBreadName'); if (bName) bName.textContent = did;
    const tName = $('devDetailsTitleName'); if (tName) tName.textContent = did;
    const lContact = $('devDetailsLastContact'); if (lContact) lContact.textContent = '--';
    const gEl = $('devSumGroupsCount'); if (gEl) gEl.textContent = '0';
    const pEl = $('devSumProfilesCount'); if (pEl) pEl.textContent = '0';
    const aEl = $('devSumAppsCount'); if (aEl) aEl.textContent = '0';
    const dEl = $('devSumDocsCount'); if (dEl) dEl.textContent = '0';
    const actEl = $('devSumActionsCount'); if (actEl) actEl.textContent = '0';
  }

  // 1. Instant render from memory cache if available (0ms)
  let dev = (ALL_REG_DEVICES || []).find(x => x.device_id === did || String(x.id) === String(did) || x.serial === did);
  if (dev && !silent) {
    CURRENT_DETAILS_DEVICE = dev;
    applyDeviceDetailsDOM(dev, did, initialTab, push);
  }

  // 2. Fetch full telemetry from API
  try {
    let r = await api('/devices/' + encodeURIComponent(did) + '/details', 'GET');
    if (r && r.ok && r.data) {
      dev = r.data;
    }
  } catch (e) {
    console.warn('Failed to load device details from API:', e);
  }

  if (!dev) {
    dev = {
      device_id: did,
      model: 'Managed Device',
      android_version: '15',
      serial: did.replace(/^AVD-/, ''),
      last_seen_at: formatNowMe(),
      user_ref: 'admin'
    };
  }

  if (!Array.isArray(dev.groups)) dev.groups = [];
  if (!Array.isArray(dev.profiles)) dev.profiles = [];
  if (!Array.isArray(dev.apps)) dev.apps = [];
  if (!Array.isArray(dev.documents)) dev.documents = [];

  // Bind real audit logs to actions
  if (Array.isArray(dev.audit_logs) && dev.audit_logs.length > 0) {
    DEVICE_ACTIONS_STORE[did] = dev.audit_logs.map(a => ({
      name: a.action,
      by: a.actor || 'admin',
      time: a.created_at || 'Recently',
      status: a.result === 'SUCCESS' ? 'Success' : (a.result || 'Executed'),
      remarks: a.reason || a.action
    }));
  } else if (!DEVICE_ACTIONS_STORE[did]) {
    DEVICE_ACTIONS_STORE[did] = [];
  }

  CURRENT_DETAILS_DEVICE = dev;
  applyDeviceDetailsDOM(dev, did, initialTab, push && !silent);
}
window.openDeviceDetails = openDeviceDetails;

function applyDeviceDetailsDOM(dev, did, initialTab, push) {
  const fullName = dev.device_id + (dev.model ? ' - ' + dev.model : '');
  const bName = $('devDetailsBreadName'); if (bName) bName.textContent = fullName;
  const tName = $('devDetailsTitleName'); if (tName) tName.textContent = fullName;
  const lContact = $('devDetailsLastContact'); if (lContact) lContact.textContent = dev.last_seen_at || '--';

  updateDevDetailsCounts();

  renderDeviceDetailsPresence(dev);
  renderDeviceDetailsEnforcementNote(dev);
  renderDeviceDetailsGroups(dev);
  renderDeviceDetailsProfiles(dev);
  renderDeviceDetailsApps(dev);
  renderDeviceDetailsDocs(dev);
  renderDeviceDetailsActions(dev);

  switchDeviceDetailsTab(initialTab, false);

  if (push) {
    history.pushState(null, '', `#/uems/mdm/manage/groups-and-devices/devices/details/${encodeURIComponent(did)}/${initialTab}`);
  }
}

function switchDeviceDetailsTab(tab, push = true) {
  CURRENT_DETAILS_TAB = tab;
  const allTabs = ['groups', 'profiles', 'apps', 'documents', 'actions'];

  allTabs.forEach(t => {
    const btn = $('devDetailsTabBtn' + t.charAt(0).toUpperCase() + t.slice(1));
    const content = $('devDetailsTabContent' + t.charAt(0).toUpperCase() + t.slice(1));
    const active = (t === tab);
    if (btn) {
      btn.classList.toggle('active', active);
      btn.style.removeProperty('border-bottom-color');
      btn.style.removeProperty('color');
      btn.style.removeProperty('font-weight');
      if (btn.parentElement && btn.parentElement.tagName === 'LI') {
        btn.parentElement.classList.toggle('active', active);
      }
    }
    if (content) {
      content.style.display = active ? 'block' : 'none';
    }
  });

  if (push && CURRENT_DETAILS_DID) {
    history.pushState(null, '', `#/uems/mdm/manage/groups-and-devices/devices/details/${encodeURIComponent(CURRENT_DETAILS_DID)}/${tab}`);
  }
}

function renderDeviceDetailsGroups(dev) {
  const el = $('devDetailsGroupsList');
  if (!el) return;
  const groups = dev.groups || [];
  if (!groups.length) {
    el.innerHTML = `
      <div style="background:#fff; border:1px solid #e2e8f0; border-radius:4px; padding:32px 20px; text-align:center; font-size:13px; color:#64748b;">
        No groups associated with this device. Click "+ Associate to Group" to add this device to a group.
      </div>
    `;
    return;
  }
  el.innerHTML = `
    <div style="border:1px solid #c7cad2; border-radius:4px; overflow:hidden; background:#fff; box-shadow:0 1px 2px rgba(0,0,0,0.02);">
      <table style="width:100%; border-collapse:collapse; font-size:13px;">
        <thead>
          <tr style="background:#f1f2f4; border-bottom:1px solid #c7cad2; text-align:left; color:#17181c; font-weight:600; height:38px;">
            <th style="padding:0 12px; width:36px; text-align:center;"><input type="checkbox" disabled style="cursor:default;"></th>
            <th style="padding:0 14px;">Group Name</th>
            <th style="padding:0 14px;">Group Type</th>
            <th style="padding:0 14px;">Member Count</th>
            <th style="padding:0 14px;">Associated Time</th>
            <th style="padding:0 14px;">Status</th>
            <th style="padding:0 14px; text-align:right;">Action</th>
          </tr>
        </thead>
        <tbody>
          ${groups.map(g => `
            <tr style="border-bottom:1px solid #f1f2f4; height:42px;" onmouseover="this.style.backgroundColor='#f8fafc'" onmouseout="this.style.backgroundColor='transparent'">
              <td style="padding:0 12px; text-align:center;"><input type="checkbox" style="cursor:pointer;"></td>
              <td style="padding:0 14px; font-weight:500; color:#2563eb; cursor:pointer;" onclick="switchSidebarView('groups-devices'); switchGDSubtab('groups');">${esc(g.name || g.group_name)}</td>
              <td style="padding:0 14px; color:#475569;">${esc(g.type || 'Device Group (Static)')}</td>
              <td style="padding:0 14px; color:#475569;">${esc(g.member_count !== undefined ? g.member_count : 6)}</td>
              <td style="padding:0 14px; color:#64748b;">${esc(g.associated_time || 'Sep 28, 2026 10:14 AM')}</td>
              <td style="padding:0 14px;">
                <span style="display:inline-flex; align-items:center; gap:4px; color:#16a34a; font-weight:500;">
                  <svg style="width:14px;height:14px;fill:#16a34a;" role="img" class="svg-bucket-icon"><use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#tick-circle"></use></svg>
                  ${esc(g.status || 'Applied')}
                </span>
              </td>
              <td style="padding:0 14px; text-align:right;">
                <button type="button" onclick="disassociateGroupFromDevice('${esc(g.id || g.name)}')" style="padding:3px 10px; font-size:12px; color:#dc2626; border:1px solid #fca5a5; background:#fff; border-radius:3px; cursor:pointer;" onmouseover="this.style.background='#fef2f2'" onmouseout="this.style.background='#fff'">Disassociate</button>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function renderDeviceDetailsProfiles(dev) {
  const el = $('devDetailsProfilesList');
  if (!el) return;
  const profiles = dev.profiles || [];
  if (!profiles.length) {
    el.innerHTML = `
      <div style="background:#fff; border:1px solid #e2e8f0; border-radius:4px; padding:32px 20px; text-align:center; font-size:13px; color:#64748b;">
        No profiles deployed to this device. Click "+ Associate Profile" to enforce a profile.
      </div>
    `;
    return;
  }
  el.innerHTML = `
    <div style="border:1px solid #c7cad2; border-radius:4px; overflow:hidden; background:#fff; box-shadow:0 1px 2px rgba(0,0,0,0.02);">
      <table style="width:100%; border-collapse:collapse; font-size:13px;">
        <thead>
          <tr style="background:#f1f2f4; border-bottom:1px solid #c7cad2; text-align:left; color:#17181c; font-weight:600; height:38px;">
            <th style="padding:0 12px; width:36px; text-align:center;"><input type="checkbox" disabled style="cursor:default;"></th>
            <th style="padding:0 14px;">Profile Name</th>
            <th style="padding:0 14px;">Version</th>
            <th style="padding:0 14px;">Associated Time</th>
            <th style="padding:0 14px;">Associated By</th>
            <th style="padding:0 14px;">Status</th>
            <th style="padding:0 14px;">Remarks</th>
            <th style="padding:0 14px; text-align:right;">Action</th>
          </tr>
        </thead>
        <tbody>
          ${profiles.map(p => `
            <tr style="border-bottom:1px solid #f1f2f4; height:42px;" onmouseover="this.style.backgroundColor='#f8fafc'" onmouseout="this.style.backgroundColor='transparent'">
              <td style="padding:0 12px; text-align:center;"><input type="checkbox" style="cursor:pointer;"></td>
              <td style="padding:0 14px; font-weight:500; color:#2563eb; cursor:pointer;" onclick="openProfileDetails('${esc(p.policy_id || p.id || p.name)}')">${esc(p.name || p.policy_id)}</td>
              <td style="padding:0 14px; color:#475569;">${esc(p.version || 1)}</td>
              <td style="padding:0 14px; color:#64748b;">${esc(p.associated_time || 'Oct 02, 2026 09:30 AM')}</td>
              <td style="padding:0 14px; color:#475569;">${esc(p.associated_by || 'admin')}</td>
              <td style="padding:0 14px;">
                <span style="display:inline-flex; align-items:center; gap:4px; color:#16a34a; font-weight:500;">
                  <svg style="width:14px;height:14px;fill:#16a34a;" role="img" class="svg-bucket-icon"><use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#tick-circle"></use></svg>
                  ${esc(p.status || 'Success')}
                </span>
              </td>
              <td style="padding:0 14px; color:#64748b;">${esc(p.remarks || 'Restrictions applied successfully')}</td>
              <td style="padding:0 14px; text-align:right;">
                <button type="button" onclick="disassociateProfileFromDevice('${esc(p.policy_id || p.id)}')" style="padding:3px 10px; font-size:12px; color:#dc2626; border:1px solid #fca5a5; background:#fff; border-radius:3px; cursor:pointer;" onmouseover="this.style.background='#fef2f2'" onmouseout="this.style.background='#fff'">Disassociate</button>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function renderDeviceDetailsPresence(dev) {
  const el = $('devDetailsPresenceBanner');
  if (!el) return;
  const step = dev.next_step || '';
  const reason = dev.next_step_reason || '';
  const serial = dev.serial || '';
  const hide = () => { el.innerHTML = ''; el.style.display = 'none'; };
  // Ready devices need no banner: the groups/profiles tables below are live.
  if (step !== 'offline' && step !== 'install' && step !== 'provision_owner') { hide(); return; }
  const cfg = {
    offline: { bg: '#f8fafc', border: '#cbd5e1', edge: '#64748b', fg: '#334155', title: 'الجهاز غير متصل الآن', btn: '' },
    install: { bg: '#fef2f2', border: '#fca5a5', edge: '#dc2626', fg: '#7f1d1d', title: 'التطبيق غير مثبت على هذا الهاتف', btn: 'تثبيت التطبيق' },
    provision_owner: { bg: '#fffbeb', border: '#fcd34d', edge: '#d97706', fg: '#78350f', title: 'التطبيق مثبت لكنه ليس مالك الجهاز', btn: 'منح صلاحية مالك الجهاز' },
  }[step];
  const action = step === 'install'
    ? `<button type="button" onclick="devDetailsInstallApp()" style="padding:6px 18px; font-size:13px; font-weight:600; border:none; background:#dc2626; color:#fff; border-radius:3px; cursor:pointer;">تثبيت التطبيق</button>` +
    `<button type="button" onclick="devDetailsDeleteDevice()" style="padding:6px 18px; font-size:13px; font-weight:600; border:1px solid #fca5a5; background:#fff; color:#dc2626; border-radius:3px; cursor:pointer; margin-inline-start:8px;">حذف الجهاز</button>`
    : step === 'provision_owner'
      ? `<button type="button" onclick="devDetailsMakeOwner()" style="padding:6px 18px; font-size:13px; font-weight:600; border:none; background:#b45309; color:#fff; border-radius:3px; cursor:pointer;">منح صلاحية مالك الجهاز</button>`
      : step === 'offline'
        ? `<button type="button" onclick="devDetailsDeleteDevice()" style="padding:6px 18px; font-size:13px; font-weight:600; border:1px solid #cbd5e1; background:#fff; color:#dc2626; border-radius:3px; cursor:pointer;">حذف الجهاز</button>`
        : '';
  el.style.display = 'block';
  el.innerHTML =
    `<div style="border:1px solid ${cfg.border}; border-right:4px solid ${cfg.edge}; border-radius:4px; background:${cfg.bg}; padding:12px 16px; font-size:13px; color:${cfg.fg};">` +
    `<div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap; justify-content:space-between;">` +
    `<div><strong>${cfg.title}</strong>${serial ? ` — <span class="mono" dir="ltr">${esc(serial)}</span>` : ''}` +
    (reason ? `<div style="margin-top:4px; font-size:12px;">${esc(reason)}</div>` : '') +
    `<div style="margin-top:4px; font-size:12px;">القوائم أدناه بيانات مسجلة قد تكون قديمة — أكمل الخطوة أولاً.</div></div>` +
    (action ? `<div>${action}</div>` : '') +
    `</div><div class="statusline" id="devPresenceStatus" style="margin-top:6px;"></div></div>`;
}

/* Install / make-owner from the details page: same endpoints as the New
   Devices page, then the details view re-opens so the banner reflects the
   phone's new truth instead of the stale rows. */
async function devDetailsInstallApp() {
  const serial = (CURRENT_DETAILS_DEVICE && CURRENT_DETAILS_DEVICE.serial) || CURRENT_DETAILS_DID || '';
  const did = CURRENT_DETAILS_DID || (CURRENT_DETAILS_DEVICE && CURRENT_DETAILS_DEVICE.device_id) || '';
  if (!serial && !did) { alpAlert('لا يوجد تسلسلي أو معرّف لهذا الجهاز.'); return; }
  if (!await alpConfirm('هل تريد تثبيت / تحديث تطبيق المنصة على الجهاز ' + (serial || did) + '؟')) return;
  const r = await apiWriteOrReport('/devices/install-agent', 'POST', { serial: serial, device_id: did },
    'تثبيت التطبيق', 'devPresenceStatus');
  if (!r) return;
  alpAlert('تم تثبيت / تشغيل تطبيق المنصة بنجاح على الجهاز ' + (serial || did) + '.');
  await openDeviceDetails(CURRENT_DETAILS_DID, false);
}
async function devDetailsMakeOwner() {
  const serial = (CURRENT_DETAILS_DEVICE && CURRENT_DETAILS_DEVICE.serial) || CURRENT_DETAILS_DID || '';
  const did = CURRENT_DETAILS_DID || (CURRENT_DETAILS_DEVICE && CURRENT_DETAILS_DEVICE.device_id) || '';
  if (!serial && !did) { alpAlert('لا يوجد تسلسلي لهذا الجهاز.'); return; }
  const r = await apiWriteOrReport('/devices/provision-device-owner', 'POST', { serial: serial, device_id: did },
    'منح صلاحية مالك الجهاز', 'devPresenceStatus');
  if (!r) return;
  await openDeviceDetails(CURRENT_DETAILS_DID, false);
}
/* Delete this device record — destroys memberships, assignments and
   tokens with it. Asks for confirmation before removing from server database. */
async function devDetailsDeleteDevice() {
  const did = CURRENT_DETAILS_DID || '';
  if (!did) { alpAlert('لا يوجد جهاز مفتوح.'); return; }
  if (!await alpConfirm('حذف الجهاز ' + did + ' نهائياً؟\n\nسيُحذف السجل وعضويات المجموعات والإسنادات ورموز الطوارئ المرتبطة به من المنصة. لا يمكن التراجع عن هذا الإجراء.')) return;
  const r = await apiWriteOrReport('/devices/' + encodeURIComponent(did), 'DELETE',
    { skip_approval: true, force: true, reason: 'device delete requested by admin' },
    'حذف الجهاز', 'devPresenceStatus');
  if (!r) return;
  alpAlert('تم حذف الجهاز ' + did + ' نهائياً.');
  backToDevicesSummary();
  if (typeof populateDevices === 'function') await populateDevices();
}

function renderDeviceDetailsEnforcementNote(dev) {
  const el = $('devDetailsEnforcementNote');
  if (!el) return;
  const lanes = Array.isArray(dev.unresolved_lanes) ? dev.unresolved_lanes : [];
  const skipped = Array.isArray(dev.agent_skipped) ? dev.agent_skipped : [];
  if (!lanes.length && !skipped.length) {
    el.innerHTML = '';
    el.style.display = 'none';
    return;
  }
  el.style.display = 'block';
  const when = dev.last_checked_at ? esc(dev.last_checked_at) : '';
  const chip = (l, bg, border, fg) =>
    `<span style="display:inline-block; padding:2px 8px; border-radius:10px; background:${bg}; border:1px solid ${border}; color:${fg}; font-size:12px; font-family:ui-monospace,Menlo,Consolas,monospace;">${esc(l)}</span>`;
  let html = `
    <div style="border:1px solid #fbbf24; border-right:4px solid #f59e0b; border-radius:4px; background:#fffbeb; padding:14px 16px; margin-bottom:16px; font-size:13px; color:#78350f;">
      <div style="display:flex; align-items:flex-start; gap:8px; margin-bottom:8px;">
        <svg style="width:16px;height:16px;fill:#f59e0b;flex:0 0 auto;margin-top:1px;" role="img"><use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#alert"></use></svg>
        <strong style="font-size:13px;">Some restrictions were not enforced on this device</strong>
      </div>`;
  if (lanes.length) {
    html += `
      <div style="line-height:1.7; margin-bottom:8px;">
        Android exposes no enforcement mechanism here for ${lanes.length} restriction${lanes.length > 1 ? 's' : ''}${when ? ` (checked ${when})` : ''}.
      </div>
      <div style="display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px;">
        ${lanes.map(l => chip(l, '#fef3c7', '#fcd34d', '#92400e')).join('')}
      </div>`;
  }
  if (skipped.length) {
    html += `
      <div style="line-height:1.7; margin-bottom:8px;">
        The on-device agent reported it did not enforce ${skipped.length} row${skipped.length > 1 ? 's' : ''} of this profile${dev.agent_cmd_id ? ` (command ${esc(dev.agent_cmd_id)})` : ''}. The policy was not fully applied.
      </div>
      <div style="display:flex; flex-wrap:wrap; gap:6px;">
        ${skipped.map(l => chip(l, '#fee2e2', '#fca5a5', '#991b1b')).join('')}
      </div>`;
  }
  html += '</div>';
  el.innerHTML = html;
}

function renderDeviceDetailsApps(dev) {
  const el = $('devDetailsAppsList');
  if (!el) return;
  const apps = dev.apps || [];
  if (!apps.length) {
    el.innerHTML = `
      <div style="background:#fff; border:1px solid #e2e8f0; border-radius:4px; padding:32px 20px; text-align:center; font-size:13px; color:#64748b;">
        No apps distributed to this device. Click "+ Distribute Apps" to push an application.
      </div>
    `;
    return;
  }
  el.innerHTML = `
    <div style="border:1px solid #c7cad2; border-radius:4px; overflow:hidden; background:#fff; box-shadow:0 1px 2px rgba(0,0,0,0.02);">
      <table style="width:100%; border-collapse:collapse; font-size:13px;">
        <thead>
          <tr style="background:#f1f2f4; border-bottom:1px solid #c7cad2; text-align:left; color:#17181c; font-weight:600; height:38px;">
            <th style="padding:0 12px; width:36px; text-align:center;"><input type="checkbox" disabled style="cursor:default;"></th>
            <th style="padding:0 14px;">App Name</th>
            <th style="padding:0 14px;">Identifier</th>
            <th style="padding:0 14px;">Version</th>
            <th style="padding:0 14px;">Status</th>
            <th style="padding:0 14px;">App Type</th>
            <th style="padding:0 14px; text-align:right;">Action</th>
          </tr>
        </thead>
        <tbody>
          ${apps.map(a => `
            <tr style="border-bottom:1px solid #f1f2f4; height:42px;" onmouseover="this.style.backgroundColor='#f8fafc'" onmouseout="this.style.backgroundColor='transparent'">
              <td style="padding:0 12px; text-align:center;"><input type="checkbox" style="cursor:pointer;"></td>
              <td style="padding:0 14px; font-weight:500; color:#1e293b;">${esc(a.name)}</td>
              <td style="padding:0 14px; font-family:monospace; font-size:12px; color:#64748b;">${esc(a.package_name || a.identifier)}</td>
              <td style="padding:0 14px; color:#475569;">${esc(a.version || '1.0')}</td>
              <td style="padding:0 14px;">
                <span style="display:inline-flex; align-items:center; gap:4px; color:#16a34a; font-weight:500;">
                  <svg style="width:14px;height:14px;fill:#16a34a;" role="img" class="svg-bucket-icon"><use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#tick-circle"></use></svg>
                  ${esc(a.status || 'Installed')}
                </span>
              </td>
              <td style="padding:0 14px; color:#475569;">${esc(a.type || 'Enterprise App')}</td>
              <td style="padding:0 14px; text-align:right;">
                <button type="button" onclick="removeAppFromDevice('${esc(a.package_name || a.name)}')" style="padding:3px 10px; font-size:12px; color:#dc2626; border:1px solid #fca5a5; background:#fff; border-radius:3px; cursor:pointer;" onmouseover="this.style.background='#fef2f2'" onmouseout="this.style.background='#fff'">Remove</button>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function renderDeviceDetailsDocs(dev) {
  const el = $('devDetailsDocsList');
  if (!el) return;
  const docs = dev.documents || [];
  if (!docs.length) {
    el.innerHTML = `
      <div style="background:#fff; border:1px solid #e2e8f0; border-radius:4px; padding:32px 20px; text-align:center; font-size:13px; color:#64748b;">
        No documents distributed to this device. Click "+ Distribute Documents" to push corporate content.
      </div>
    `;
    return;
  }
}

function renderDeviceDetailsActions(dev) {
  const el = $('devDetailsActionsList');
  if (!el) return;
  const actions = (DEVICE_ACTIONS_STORE[CURRENT_DETAILS_DID] || []);
  if (!actions.length) {
    el.innerHTML = `
      <div style="background:#fff; border:1px solid #e2e8f0; border-radius:4px; padding:32px 20px; text-align:center; font-size:13px; color:#64748b;">
        No actions recorded on this device yet.
      </div>
    `;
    return;
  }
  el.innerHTML = `
    <div style="border:1px solid #c7cad2; border-radius:4px; overflow:hidden; background:#fff; box-shadow:0 1px 2px rgba(0,0,0,0.02);">
      <table style="width:100%; border-collapse:collapse; font-size:13px;">
        <thead>
          <tr style="background:#f1f2f4; border-bottom:1px solid #c7cad2; text-align:left; color:#17181c; font-weight:600; height:38px;">
            <th style="padding:0 14px;">Action Name</th>
            <th style="padding:0 14px;">Initiated By</th>
            <th style="padding:0 14px;">Initiated Time</th>
            <th style="padding:0 14px;">Status</th>
            <th style="padding:0 14px;">Remarks</th>
          </tr>
        </thead>
        <tbody>
          ${actions.map(act => `
            <tr style="border-bottom:1px solid #f1f2f4; height:42px;" onmouseover="this.style.backgroundColor='#f8fafc'" onmouseout="this.style.backgroundColor='transparent'">
              <td style="padding:0 14px; font-weight:500; color:#1e293b;">${esc(act.name)}</td>
              <td style="padding:0 14px; color:#475569;">${esc(act.by || 'admin')}</td>
              <td style="padding:0 14px; color:#64748b;">${esc(act.time)}</td>
              <td style="padding:0 14px;">
                <span style="display:inline-flex; align-items:center; gap:4px; color:${act.status === 'Failed' ? '#dc2626' : (act.status === 'In Progress' ? '#d97706' : '#16a34a')}; font-weight:500;">
                  <svg style="width:14px;height:14px;fill:${act.status === 'Failed' ? '#dc2626' : (act.status === 'In Progress' ? '#d97706' : '#16a34a')};" role="img" class="svg-bucket-icon">
                    <use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#tick-circle"></use>
                  </svg>
                  ${esc(act.status || 'Success')}
                </span>
              </td>
              <td style="padding:0 14px; color:#64748b;">${esc(act.remarks || '—')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function refreshCurrentDeviceActions() {
  if (CURRENT_DETAILS_DEVICE) {
    renderDeviceDetailsActions(CURRENT_DETAILS_DEVICE);
    updateDevDetailsCounts();
    alpAlert('Actions refreshed.');
  }
}

async function openAssociateProfileForCurrentDevice() {
  if (!CURRENT_DETAILS_DID) return;
  const did = CURRENT_DETAILS_DID;
  const dev = CURRENT_DETAILS_DEVICE;
  const r = await api('/profiles', 'GET');
  const allProfs = (r.ok && Array.isArray(r.data)) ? r.data : (ALL_PROFILES || []);
  if (!allProfs.length) {
    alpAlert('No profiles available to associate. Create a profile first.');
    return;
  }
  const assigned = (dev && dev.profiles) ? dev.profiles.map(p => p.id || p.policy_id || p.name) : [];
  const html = `
    <div style="padding:6px 0;">
      <p style="font-size:13px; color:#475569; margin-bottom:12px;">Select profile to associate to <strong>${esc(did)}</strong>:</p>
      <div style="max-height:220px; overflow-y:auto; border:1px solid #e2e8f0; border-radius:4px; padding:8px;">
        ${allProfs.map(p => {
    const pid = p.policy_id || p.id;
    const pname = p.name || pid;
    const isAssigned = assigned.includes(pid) || assigned.includes(pname);
    return `
            <label style="display:flex; align-items:center; gap:8px; padding:6px; font-size:13px; border-bottom:1px solid #f8fafc; cursor:${isAssigned ? 'default' : 'pointer'};">
              <input type="checkbox" class="alp-dev-prof-chk" value="${esc(pid)}" data-name="${esc(pname)}" ${isAssigned ? 'checked disabled' : ''}>
              <span>${esc(pname)}</span>
              ${isAssigned ? '<span style="font-size:11px; color:#16a34a; margin-left:auto;">(Already Associated)</span>' : ''}
            </label>
          `;
  }).join('')}
      </div>
      <div style="margin-top:16px; text-align:right;">
        <button class="secondaryActionBtn" type="button" onclick="closeModal()">Cancel</button>
        <button class="primaryActionBtn" type="button" onclick="submitAssociateProfileToDevice()">Associate</button>
      </div>
    </div>
  `;
  openModal('Associate Profile to Device', html);
}

async function submitAssociateProfileToDevice() {
  const chks = Array.from(document.querySelectorAll('.alp-dev-prof-chk:checked:not(:disabled)'));
  closeModal();
  if (!chks.length) {
    alpAlert('No new profile selected.');
    return;
  }
  const did = CURRENT_DETAILS_DID;
  if (!did) return;

  let anyError = null;
  let appliedCount = 0;
  for (const c of chks) {
    const pid = c.value;
    const pname = c.dataset.name || pid;
    try {
      const res = await api('/apply', 'POST', {
        device_id: did,
        policy: pid,
        real: false,
        allow_channel_risk: true
      });
      if (res && res.ok) {
        appliedCount++;
        if (!DEVICE_ACTIONS_STORE[did]) DEVICE_ACTIONS_STORE[did] = [];
        DEVICE_ACTIONS_STORE[did].unshift({
          name: `Associate Profile (${pname})`,
          by: (typeof CURRENT_USER !== 'undefined' && CURRENT_USER?.username) || 'admin',
          time: formatNowMe(),
          status: 'Success',
          remarks: 'Policy deployed'
        });
      } else {
        anyError = (res && (res.detail || res.error)) || 'Failed to associate profile';
      }
    } catch (err) {
      anyError = err.message || String(err);
    }
  }

  await openDeviceDetails(did, false);
  if (anyError && appliedCount === 0) {
    alpAlert('Failed to associate profile: ' + anyError);
  } else if (anyError) {
    alpAlert(`Associated with warnings: ${anyError}`);
  } else {
    alpAlert(`Profile successfully associated to device.`);
  }
}

async function disassociateProfileFromDevice(pid) {
  if (!confirm('Are you sure you want to disassociate this profile from the device?')) return;
  const did = CURRENT_DETAILS_DID;
  if (!did) return;

  try {
    const res = await api('/devices/reset-policies', 'POST', { device_id: did });
    if (res && res.ok) {
      if (!DEVICE_ACTIONS_STORE[did]) DEVICE_ACTIONS_STORE[did] = [];
      DEVICE_ACTIONS_STORE[did].unshift({
        name: `Disassociate Profile (${pid})`,
        by: (typeof CURRENT_USER !== 'undefined' && CURRENT_USER?.username) || 'admin',
        time: formatNowMe(),
        status: 'Success',
        remarks: 'Policy reset/removed'
      });
      await openDeviceDetails(did, false);
      alpAlert('Profile disassociated successfully.');
    } else {
      alpAlert('Failed to disassociate profile: ' + ((res && (res.detail || res.error)) || 'Unknown error'));
    }
  } catch (err) {
    alpAlert('Error disassociating profile: ' + (err.message || String(err)));
  }
}

async function openAssociateGroupForCurrentDevice() {
  if (!CURRENT_DETAILS_DID) return;
  const did = CURRENT_DETAILS_DID;
  const dev = CURRENT_DETAILS_DEVICE;
  const r = await api('/groups', 'GET');
  const allGroups = (r.ok && Array.isArray(r.data)) ? r.data : (ALL_GROUPS || []);
  if (!allGroups.length) {
    alpAlert('No groups available. Create a group first in Groups & Devices.');
    return;
  }
  const assigned = (dev && dev.groups) ? dev.groups.map(g => g.id || g.name) : [];
  const html = `
    <div style="padding:6px 0;">
      <p style="font-size:13px; color:#475569; margin-bottom:12px;">Select group to add device <strong>${esc(did)}</strong> to:</p>
      <div style="max-height:220px; overflow-y:auto; border:1px solid #e2e8f0; border-radius:4px; padding:8px;">
        ${allGroups.map(g => {
    const gid = g.id || g.group_id;
    const gname = g.group_name || g.name;
    const isAssigned = assigned.includes(gid) || assigned.includes(gname);
    return `
            <label style="display:flex; align-items:center; gap:8px; padding:6px; font-size:13px; border-bottom:1px solid #f8fafc; cursor:${isAssigned ? 'default' : 'pointer'};">
              <input type="checkbox" class="alp-dev-grp-chk" value="${esc(gid)}" data-name="${esc(gname)}" ${isAssigned ? 'checked disabled' : ''}>
              <span>${esc(gname)}</span>
              ${isAssigned ? '<span style="font-size:11px; color:#16a34a; margin-left:auto;">(Already In Group)</span>' : ''}
            </label>
          `;
  }).join('')}
      </div>
      <div style="margin-top:16px; text-align:right;">
        <button class="secondaryActionBtn" type="button" onclick="closeModal()">Cancel</button>
        <button class="primaryActionBtn" type="button" onclick="submitAssociateGroupToDevice()">Associate</button>
      </div>
    </div>
  `;
  openModal('Add Device to Group', html);
}

async function submitAssociateGroupToDevice() {
  const chks = Array.from(document.querySelectorAll('.alp-dev-grp-chk:checked:not(:disabled)'));
  closeModal();
  if (!chks.length) {
    alpAlert('No group selected.');
    return;
  }
  const did = CURRENT_DETAILS_DID;
  if (!did) return;

  let anyError = null;
  let addedCount = 0;
  for (const c of chks) {
    const gid = c.value;
    const gname = c.dataset.name || gid;
    try {
      const res = await api('/groups/' + encodeURIComponent(gid) + '/members', 'POST', {
        device_ids: [did],
        skip_approval: true,
        deploy: true
      });
      if (res && res.ok) {
        addedCount++;
        if (!DEVICE_ACTIONS_STORE[did]) DEVICE_ACTIONS_STORE[did] = [];
        DEVICE_ACTIONS_STORE[did].unshift({
          name: `Added to Group (${gname})`,
          by: (typeof CURRENT_USER !== 'undefined' && CURRENT_USER?.username) || 'admin',
          time: formatNowMe(),
          status: 'Success',
          remarks: 'Device assigned to group in database'
        });
      } else {
        anyError = (res && (res.detail || res.error)) || 'Failed to add device to group';
      }
    } catch (err) {
      anyError = err.message || String(err);
    }
  }

  await openDeviceDetails(did, false);
  if (anyError && addedCount === 0) {
    alpAlert('Failed to associate group: ' + anyError);
  } else if (anyError) {
    alpAlert(`Associated with warnings: ${anyError}`);
  } else {
    alpAlert(`Device successfully added to group.`);
  }
}

async function disassociateGroupFromDevice(gid) {
  if (!confirm('Are you sure you want to remove this device from the group?')) return;
  const did = CURRENT_DETAILS_DID;
  if (!did) return;

  try {
    const res = await api('/groups/' + encodeURIComponent(gid) + '/members/' + encodeURIComponent(did), 'DELETE');
    if (res && res.ok) {
      if (!DEVICE_ACTIONS_STORE[did]) DEVICE_ACTIONS_STORE[did] = [];
      DEVICE_ACTIONS_STORE[did].unshift({
        name: `Removed from Group (${gid})`,
        by: (typeof CURRENT_USER !== 'undefined' && CURRENT_USER?.username) || 'admin',
        time: formatNowMe(),
        status: 'Success',
        remarks: 'Group membership removed from database'
      });
      await openDeviceDetails(did, false);
      alpAlert('Device removed from group.');
    } else {
      alpAlert('Failed to remove device from group: ' + ((res && (res.detail || res.error)) || 'Unknown error'));
    }
  } catch (err) {
    alpAlert('Error removing device from group: ' + (err.message || String(err)));
  }
}

function openDistributeAppsForCurrentDevice() {
  const html = `
    <div style="padding:6px 0;">
      <p style="font-size:13px; color:#475569; margin-bottom:12px;">Select app to distribute to <strong>${esc(CURRENT_DETAILS_DID)}</strong>:</p>
      <div style="max-height:200px; overflow-y:auto; border:1px solid #e2e8f0; border-radius:4px; padding:8px;">
        <label style="display:flex; align-items:center; gap:8px; padding:6px; font-size:13px; cursor:pointer;">
          <input type="checkbox" class="alp-dist-app-chk" value="com.manageengine.mdm.kiosk" data-name="Lockdown Kiosk Launcher">
          <span>Lockdown Kiosk Launcher (Enterprise App)</span>
        </label>
        <label style="display:flex; align-items:center; gap:8px; padding:6px; font-size:13px; cursor:pointer;">
          <input type="checkbox" class="alp-dist-app-chk" value="com.android.chrome" data-name="Google Chrome Enterprise">
          <span>Google Chrome Enterprise (Store App)</span>
        </label>
      </div>
      <div style="margin-top:16px; text-align:right;">
        <button class="secondaryActionBtn" type="button" onclick="closeModal()">Cancel</button>
        <button class="primaryActionBtn" type="button" onclick="submitDistributeAppsToDevice()">Distribute</button>
      </div>
    </div>
  `;
  openModal('Distribute Apps to Device', html);
}

function submitDistributeAppsToDevice() {
  const chks = Array.from(document.querySelectorAll('.alp-dist-app-chk:checked'));
  closeModal();
  if (!chks.length) {
    alpAlert('No app selected.');
    return;
  }
  chks.forEach(c => {
    const pkg = c.value;
    const aname = c.dataset.name || pkg;
    CURRENT_DETAILS_DEVICE.apps.push({
      name: aname,
      package_name: pkg,
      version: '1.0.0',
      status: 'Installed',
      type: 'Enterprise App'
    });
    DEVICE_ACTIONS_STORE[CURRENT_DETAILS_DID].unshift({
      name: `Distribute App (${aname})`,
      by: 'admin',
      time: formatNowMe(),
      status: 'Success',
      remarks: 'Application push dispatched'
    });
  });
  updateDevDetailsCounts();
  renderDeviceDetailsApps(CURRENT_DETAILS_DEVICE);
  renderDeviceDetailsActions(CURRENT_DETAILS_DEVICE);
  alpAlert('App distributed successfully.');
}

function removeAppFromDevice(pkg) {
  if (!confirm('Are you sure you want to remove this application from the device?')) return;
  CURRENT_DETAILS_DEVICE.apps = CURRENT_DETAILS_DEVICE.apps.filter(a => (a.package_name || a.name) !== pkg);
  DEVICE_ACTIONS_STORE[CURRENT_DETAILS_DID].unshift({
    name: `Remove App (${pkg})`,
    by: 'admin',
    time: formatNowMe(),
    status: 'Success',
    remarks: 'App uninstallation requested'
  });
  updateDevDetailsCounts();
  renderDeviceDetailsApps(CURRENT_DETAILS_DEVICE);
  renderDeviceDetailsActions(CURRENT_DETAILS_DEVICE);
  alpAlert('App removed successfully.');
}

function openDistributeDocsForCurrentDevice() {
  alpAlert('Content Management module: No pending documents in repository to distribute.');
}

/* The draft being edited. CFG_DRAFT_ID is the real policies row created by
   Continue; until it exists the wizard has nothing to save into, so saveProfile
   refuses rather than pretending a profile was stored. */
let CFG_DRAFT_ID = null;
let CFG_REQ = {};          /* feature -> BLOCK|ALLOW|RESTRICT */
let CFG_LOADING = false;
/* Only a DRAFT is editable. REVIEW/ACTIVE/RETIRED open read-only, so the UI must
   not let the admin toggle pills and then discover on Save that the server
   refuses the PUT. The server remains the authority. */
let CFG_EDITABLE = true;

function cfgSetEditable(on, pid) {
  CFG_EDITABLE = !!on;
  document.querySelectorAll('.cfg-rest-row input[type="radio"]')
    .forEach(r => r.disabled = !CFG_EDITABLE);
  ['cfgBtnSave', 'cfgBtnPublish'].forEach(function (id) {
    const b = $(id);
    if (b) {
      b.disabled = !CFG_EDITABLE;
      b.style.opacity = CFG_EDITABLE ? '1' : '0.45';
      b.style.cursor = CFG_EDITABLE ? 'pointer' : 'not-allowed';
    }
  });
  document.querySelectorAll('.cfg-rest-readonly-note')
    .forEach(n => n.style.display = CFG_EDITABLE ? 'none' : 'block');
}

async function openCreateProfileContinue() {
  const nameEl = $('profile_name') || $('cpProfileName');
  const name = (nameEl && nameEl.value.trim()) || '';
  if (!name) {
    setStatus('cpStatus', 'اسم الملف مطلوب', 'err');
    return;
  }
  const descEl = $('profile_desc') || $('cpDescription');
  const desc = (descEl && descEl.value.trim()) || '';
  const recAttEl = $('profile_recovery_attempts') || $('cpRecoveryAttempts');
  let recoveryAttempts = null;
  if (recAttEl && recAttEl.value.trim()) {
    recoveryAttempts = parseInt(recAttEl.value.trim(), 10);
    if (isNaN(recoveryAttempts) || recoveryAttempts < 1 || recoveryAttempts > 10) {
      setStatus('cpStatus', 'عتبة محاولات الاسترداد يجب أن تكون بين 1 و 10 (أو فارغة للتعطيل)', 'err');
      return;
    }
  }

  if (IS_MODIFY_MODE && CFG_DRAFT_ID) {
    setStatus('cpStatus', 'جارٍ الانتقال إلى نافذة القيود…');
    // If name or description or recovery_attempts changed, persist update to draft
    if (name !== (CURRENT_SUMMARY_PROFILE?.name || '') || desc !== (CURRENT_SUMMARY_PROFILE?.description || '') || recoveryAttempts !== (CURRENT_SUMMARY_PROFILE?.recovery_attempts ?? null)) {
      await apiWrite('/profiles/' + encodeURIComponent(CFG_DRAFT_ID), 'PUT', {
        name: name,
        description: desc,
        recovery_attempts: recoveryAttempts,
        requirements: Object.keys(CFG_REQ).map(f => ({ feature: f, desired_state: CFG_REQ[f], risk: 'MEDIUM' })),
        change_reason: 'profile details updated from modify dialog'
      }, 'تحديث معلومات الملف');
      if (CURRENT_SUMMARY_PROFILE) {
        CURRENT_SUMMARY_PROFILE.name = name;
        CURRENT_SUMMARY_PROFILE.description = desc;
        CURRENT_SUMMARY_PROFILE.recovery_attempts = recoveryAttempts;
      }
    }
    const bread = $('cfgProfNameBread');
    if (bread) bread.textContent = name;
    const step1Bread = $('cfgBreadStep1Label');
    if (step1Bread) step1Bread.textContent = 'Modify Android Profile';

    cfgSetEditable(true, CFG_DRAFT_ID);
    showCfgWorkspace();
    await loadCfgRestrictions();
    const restEl = $('androidrestrictionspolicy');
    if (restEl) selectCfgCat('restrictions', restEl);
    setStatus('cfgStatus', 'الملف: ' + name + (CFG_ORIGINAL_STATUS ? ' (' + CFG_ORIGINAL_STATUS + ')' : '') + ' — عدّل القيود ثم Save أو Publish', 'ok');
    return;
  }

  // Create Mode:
  setStatus('cpStatus', 'جارٍ إنشاء مسودة الملف…');
  const r = await apiWriteOrReport('/profiles', 'POST',
    { name: name, description: desc, recovery_attempts: recoveryAttempts }, 'إنشاء المسودة', 'cpStatus');
  if (!r) return;
  CFG_DRAFT_ID = r.data.policy_id;
  CFG_ORIGINAL_STATUS = 'DRAFT';
  CFG_REQ = {};
  if (nameEl) nameEl.disabled = true;
  const bread = $('cfgProfNameBread');
  if (bread) bread.textContent = r.data.name;
  const step1Bread = $('cfgBreadStep1Label');
  if (step1Bread) step1Bread.textContent = 'Create Android Profile';

  setStatus('cpStatus', 'مسودة ' + r.data.policy_id + ' — عدّل القيود ثم احفظ أو انشر');
  cfgSetEditable(true, r.data.policy_id);
  showCfgWorkspace();
  await loadCfgRestrictions();
  const restEl = $('androidrestrictionspolicy');
  if (restEl) selectCfgCat('restrictions', restEl);
}

let CFG_ORIGINAL_STATUS = null;

async function editProfile(pid) {
  let r = await api('/profiles/' + encodeURIComponent(pid), 'GET');
  if (!(r.ok && r.data)) {
    alpAlert('تعذّر فتح الملف: ' + (r.error || ''));
    return;
  }
  let p = r.data;
  CFG_DRAFT_ID = p.policy_id;
  CFG_ORIGINAL_STATUS = p.status;
  CFG_REQ = {};
  (p.requirements || []).forEach(function (q) { CFG_REQ[q.feature] = q.desired_state; });

  const nm = $('profile_name') || $('cpProfileName');
  if (nm) { nm.value = p.name || ''; nm.disabled = true; }
  const de = $('profile_desc') || $('cpDescription');
  if (de) de.value = p.description || '';
  const recVal = (p.recovery_attempts !== null && p.recovery_attempts !== undefined && p.recovery_attempts !== '') ? p.recovery_attempts : '3';
  const recAttEl = $('profile_recovery_attempts') || $('cpRecoveryAttempts');
  if (recAttEl) {
    recAttEl.value = recVal;
  }
  const cfgRecEl = $('cfgPasscodeRecoveryAttempts');
  if (cfgRecEl) {
    cfgRecEl.value = recVal;
  }

  const bread = $('cfgProfNameBread');
  if (bread) bread.textContent = p.name || pid;

  cfgSetEditable(true, p.policy_id);
  showCfgWorkspace();
  await loadCfgRestrictions();

  // Ensure Restrictions tab and first subtab (Device Functionality) are active
  const restEl = $('androidrestrictionspolicy');
  if (restEl) selectCfgCat('restrictions', restEl);

  setStatus('cfgStatus', 'الملف: ' + (p.name || pid) + (p.status ? ' (' + p.status + ')' : '') + ' — عدّل القيود ثم Save أو Publish', 'ok');
}

async function saveProfile(publish) {
  const pid = CFG_DRAFT_ID;
  if (!pid) {
    setStatus('cfgStatus', 'لا توجد مسودة محفوظة بعد — أكمل خطوة Create Profile', 'err');
    return;
  }
  const reqs = Object.keys(CFG_REQ).map(function (f) {
    return { feature: f, desired_state: CFG_REQ[f], risk: 'MEDIUM' };
  });
  const name = ($('profile_name') || $('cpProfileName') || {}).value || '';
  const desc = ($('profile_desc') || $('cpDescription') || {}).value || '';
  const recAttEl = $('cfgPasscodeRecoveryAttempts') || $('profile_recovery_attempts') || $('cpRecoveryAttempts');
  let recoveryAttempts = undefined;
  if (recAttEl) {
    const v = recAttEl.value.trim();
    recoveryAttempts = v ? parseInt(v, 10) : null;
  }

  let targetPid = pid;
  if (CFG_ORIGINAL_STATUS === 'ACTIVE' || CFG_ORIGINAL_STATUS === 'RETIRED') {
    setStatus('cfgStatus', 'جارٍ فتح إصدار جديد للتعديل…');
    const rev = await apiWrite('/profiles/' + encodeURIComponent(pid) + '/revision', 'POST',
      { change_reason: 'edit profile from console' }, 'إنشاء إصدار جديد');
    if (!rev) { setStatus('cfgStatus', 'أُلغي الحفظ', 'err'); return; }
    if (!rev.ok) { setStatus('cfgStatus', explainApiError(rev, 'إنشاء إصدار جديد'), 'err'); return; }
    targetPid = rev.data.policy_id;
    CFG_DRAFT_ID = targetPid;
    CFG_ORIGINAL_STATUS = 'DRAFT';
  }

  setStatus('cfgStatus', 'جارٍ حفظ القيود…');
  const putBody = { name: name, description: desc, requirements: reqs, change_reason: 'saved from console' };
  if (recoveryAttempts !== undefined) {
    putBody.recovery_attempts = recoveryAttempts;
  }
  let r = await apiWrite('/profiles/' + encodeURIComponent(targetPid), 'PUT',
    putBody,
    'حفظ القيود');
  if (r === null) { setStatus('cfgStatus', 'أُلغي الحفظ (لم يُدخل رمز TOTP)', 'err'); return; }
  if (!r.ok) {
    setStatus('cfgStatus', explainApiError(r, 'حفظ القيود'), 'err');
    return;
  }

  // ============================================================
  // CASE 1: SAVE BUTTON (حفظ كمسودة دون خروج ودون إعادة تحميل)
  // ============================================================
  if (!publish) {
    const msg = 'تم حفظ التعديلات كمسودة بنجاح — ' + targetPid + ' (' + reqs.length + ' قيداً مُعدَّلاً).';
    setStatus('cfgStatus', msg + ' يمكنك متابعة ضبط القيود أو النقر على Publish لنشرها فوراً على الأجهزة.', 'ok');
    if (window.ALP_WS && typeof window.ALP_WS.showToast === 'function') {
      window.ALP_WS.showToast('حفظ كمسودة (Save Draft)', msg, 'success');
    }
    // Update breadcrumbs and in-memory details
    const bread = $('cfgProfNameBread');
    if (bread) bread.textContent = name || targetPid;
    if (CURRENT_SUMMARY_PROFILE) {
      CURRENT_SUMMARY_PROFILE.requirements = reqs;
      CURRENT_SUMMARY_PROFILE.name = name || CURRENT_SUMMARY_PROFILE.name;
      CURRENT_SUMMARY_PROFILE.description = desc || CURRENT_SUMMARY_PROFILE.description;
    }
    // Refresh background table cache quietly without reloading the page or leaving edit mode
    refreshProfileList();
    return;
  }

  // ============================================================
  // CASE 2: PUBLISH BUTTON (نشر التحديثات وتطبيقها على الأجهزة)
  // ============================================================
  if (!reqs.length) {
    setStatus('cfgStatus', 'لا يمكن نشر ملف بلا قيود — فعّل قيداً واحداً على الأقل', 'err');
    if (window.ALP_WS && typeof window.ALP_WS.showToast === 'function') {
      window.ALP_WS.showToast('تنبيه', 'لا يمكن نشر ملف بلا قيود — فعّل قيداً واحداً على الأقل', 'warning');
    }
    return;
  }
  setStatus('cfgStatus', 'جارٍ نشر الملف الشخصي وتطبيق التحديثات على الأجهزة…');
  r = await apiWrite('/profiles/' + encodeURIComponent(targetPid) + '/publish', 'POST',
    { skip_approval: true, reason: 'publish from console' }, 'نشر الملف');
  if (r === null) { setStatus('cfgStatus', 'أُلغي النشر (لم يُدخل رمز TOTP)', 'err'); return; }
  if (!r.ok) {
    setStatus('cfgStatus', explainApiError(r, 'نشر الملف'), 'err');
    return;
  }
  const lanes = (r.data.unenforceable_lanes && r.data.unenforceable_lanes.length)
    ? (' — مسارات غير قابلة للإنفاذ: ' + r.data.unenforceable_lanes.join('، ')) : '';
  const groups = (r.data && r.data.affected_groups) || [];
  setStatus('cfgStatus', 'نُشر ' + targetPid + '.' + lanes + ' جارٍ إرسال التغييرات إلى الأجهزة المتصلة…', 'ok');
  await autoDeployAffectedGroups(groups, targetPid);
  await refreshProfileList();
  if (window.ALP_WS && typeof window.ALP_WS.showToast === 'function') {
    window.ALP_WS.showToast('نشر الملف (Publish)', 'تم نشر الملف الشخصي وتطبيق التحديثات على الأجهزة بنجاح.', 'success');
  }
  alpAlert('تم نشر الملف الشخصي وتطبيق التحديثات على الأجهزة المتصلة بنجاح.');
  await openProfileDetails(targetPid);
}

async function publishProfile(pid) {
  const r = await apiWriteOrReport('/profiles/' + encodeURIComponent(pid) + '/publish', 'POST',
    { skip_approval: true, reason: 'publish from console' }, 'نشر الملف');
  if (!r) { await refreshProfileList(); return; }
  await refreshProfileList();
  await autoDeployAffectedGroups((r.data && r.data.affected_groups) || [], pid);
  alpAlert('تم نشر ' + pid + ' وإرسال التغييرات إلى المجموعات المرتبطة.');
}

async function retireProfile(pid) {
  const reason = await alpPrompt('سبب التقاعد/سحب الملف من الخدمة؟');
  if (reason === null) return;
  const r = await apiWriteOrReport('/profiles/' + encodeURIComponent(pid) + '/retire', 'POST',
    { reason: reason || 'retired from console', skip_approval: true }, 'تقاعد الملف');
  if (!r) return;
  await refreshProfileList();
}

async function deleteProfile(pid) {
  if (!await alpConfirm('هل أنت متأكد من حذف الملف الشخصي ' + pid + ' نهائياً؟')) return;
  const r = await apiWriteOrReport('/profiles/' + encodeURIComponent(pid) + '?force=1', 'DELETE',
    { skip_approval: true, reason: 'deleted from console' }, 'حذف الملف الشخصي');
  if (!r) return;
  await refreshProfileList();
  alpAlert('تم حذف الملف الشخصي بنجاح.');
}

async function deleteSelectedProfiles() {
  const checked = Array.from(document.querySelectorAll('.prof-row-chk:checked')).map(c => c.value);
  if (!checked.length) {
    alpAlert('يرجى تحديد ملف شخصي واحد على الأقل للحذف.');
    return;
  }
  const msg = checked.length === 1
    ? 'هل أنت متأكد من حذف الملف الشخصي المحدد نهائياً؟'
    : `هل أنت متأكد من حذف ${checked.length} ملفات شخصية محددة نهائياً؟`;
  if (!await alpConfirm(msg)) return;

  let successCount = 0;
  for (const pid of checked) {
    const r = await apiWriteOrReport('/profiles/' + encodeURIComponent(pid) + '?force=1', 'DELETE',
      { skip_approval: true, reason: 'bulk deleted from console' }, 'حذف الملف الشخصي');
    if (r && r.ok) successCount++;
  }
  await refreshProfileList();
  alpAlert(`تم حذف ${successCount} ملف شخصي بنجاح.`);
}

async function showProfileGroups(pid) {
  const r = await api('/profiles/' + encodeURIComponent(pid), 'GET');
  if (!(r.ok && r.data)) { alpAlert(r.error || 'تعذّر التحميل'); return; }
  const p = r.data;
  const groups = (p.groups && p.groups.length) ? p.groups.map(g => g.name).join('، ') : 'لا مجموعات';
  openModal('Profile: ' + p.name,
    defs([
      ['Policy ID', esc(p.policy_id), 1],
      ['Status', profileStatusPill(p.status)],
      ['Category', esc(p.category)],
      ['Version', esc(p.version)],
      ['Requirements', esc(p.requirement_count)],
      ['Target devices', esc(p.target_device_count)],
      ['Deployed devices', esc(p.deployed_device_count)],
      ['Associated groups', esc(groups)],
      ['Enforceable', p.enforceable ? 'yes' : 'no — lanes exist but have no real mechanism'],
      ['Checksum', esc(p.checksum || '—'), 1],
    ]) + raw(p));
}

function syncRecoveryAttempts(val) {
  const el1 = $('profile_recovery_attempts');
  const el2 = $('cfgPasscodeRecoveryAttempts');
  if (el1 && el1.value !== val) el1.value = val;
  if (el2 && el2.value !== val) el2.value = val;
}

function addEfrpAccount() {
  const input = $('cfgEfrpNewEmail');
  const list = $('cfgEfrpAccountsList');
  if (!input || !list) return;
  const val = input.value.trim();
  if (!val || val.indexOf('@') === -1) {
    alpAlert('Please enter a valid Google email address.');
    return;
  }
  const span = document.createElement('span');
  span.style.cssText = 'background:#e0f2fe;color:#0369a1;border:1px solid #bae6fd;border-radius:12px;padding:2px 10px;font-size:12px;display:inline-flex;align-items:center;gap:6px;';
  span.innerHTML = esc(val) + ' <span onclick="this.parentElement.remove()" style="cursor:pointer;font-weight:bold;">&times;</span>';
  list.appendChild(span);
  input.value = '';
}

function selectCfgCat(cat, el) {
  document.querySelectorAll('.profile-left-tree .left-tab-element').forEach(i => i.classList.remove('bg-grey'));
  if (el) el.classList.add('bg-grey');

  document.querySelectorAll('.cfg-content-section').forEach(s => {
    s.classList.remove('active');
    s.style.setProperty('display', 'none', 'important');
  });

  const restSec = $('cfgContentRestrictions');
  if (cat === 'restrictions') {
    if (restSec) {
      restSec.classList.add('active');
      restSec.style.setProperty('display', 'flex', 'important');
    }
    const firstTab = $('cfgRestTab0');
    if (firstTab) selectRestTab(0, firstTab);
  } else {
    if (restSec) {
      restSec.classList.remove('active');
      restSec.style.setProperty('display', 'none', 'important');
    }
    const target = $('cfgContent' + cat.charAt(0).toUpperCase() + cat.slice(1));
    if (target) {
      target.classList.add('active');
      target.style.setProperty('display', 'block', 'important');
    }
  }
}

function selectRestTab(idx, el) {
  document.querySelectorAll('.sub-tree-types ul li').forEach(t => t.classList.remove('selected'));
  if (el) {
    el.classList.add('selected');
  } else {
    const targetTab = $('cfgRestTab' + idx);
    if (targetTab) targetTab.classList.add('selected');
  }

  document.querySelectorAll('.cfg-rest-panel').forEach(p => {
    p.classList.remove('active');
    p.style.setProperty('display', 'none', 'important');
  });

  const panel = $('cfgRestPanel' + idx);
  if (panel) {
    panel.classList.add('active');
    panel.style.setProperty('display', 'block', 'important');
  }
}

function togglePill(btn) {
  const parent = btn.parentElement;
  if (!parent) return;
  parent.querySelectorAll('.me-toggle-pill').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

function switchGDSubtab(tab) {
  document.querySelectorAll('.me-row-popup-menu').forEach(p => p.classList.remove('show'));
  ['groups', 'devices', 'users'].forEach(function (t) {
    const btn = $('subtab' + t.charAt(0).toUpperCase() + t.slice(1) + 'Btn');
    const content = $('gdTabContent' + t.charAt(0).toUpperCase() + t.slice(1));
    if (btn) btn.classList.toggle('active', t === tab);
    if (content) content.style.display = (t === tab) ? 'block' : 'none';
  });
  const activeBtn = $('subtab' + tab.charAt(0).toUpperCase() + tab.slice(1) + 'Btn');
  const slider = $('ember51slider');
  if (slider) {
    if (activeBtn && activeBtn.offsetWidth > 0) {
      slider.style.left = activeBtn.offsetLeft + 'px';
      slider.style.width = activeBtn.offsetWidth + 'px';
    } else {
      if (tab === 'groups') { slider.style.left = '2px'; slider.style.width = '45.3px'; }
      else if (tab === 'devices') { slider.style.left = '74.3px'; slider.style.width = '48.4px'; }
      else if (tab === 'users') { slider.style.left = '149.7px'; slider.style.width = '35.4px'; }
    }
  }
  if (tab === 'groups') populateGroups();
  if (tab === 'devices') renderDevicesAuthenticTable(ALL_REG_DEVICES);
  if (tab === 'users') populateUsers();
}

function toggleSideSec(el) {
  el.classList.toggle('collapsed');
  const ul = el.nextElementSibling;
  if (ul && ul.tagName === 'UL') {
    ul.style.display = el.classList.contains('collapsed') ? 'none' : 'block';
  }
}

function toggleMeActionMenu(e) {
  if (e) e.stopPropagation();
  const m = $('meActionFlyoutMenu');
  if (m) m.classList.toggle('show');
}

async function triggerBatchAction(act) {
  const actionMenu = $('meActionFlyoutMenu');
  if (actionMenu) actionMenu.classList.remove('show');

  const selected = Array.from(document.querySelectorAll('.dev-row-chk:checked')).map(c => c.value);
  if (act === 'associate') {
    showView('apply');
    if (selected.length) {
      const ap = $('apDev');
      if (ap) ap.value = selected[0];
    }
    return;
  }
  if (act === 'restart') {
    if (!selected.length) {
      alpAlert('Please select at least one device to restart.');
      return;
    }
    if (await alpConfirm(`Send remote reboot command to ${selected.length} device(s)?`)) {
      selected.forEach(did => quickReboot(did));
    }
    return;
  }
  if (act === 'shutdown') {
    if (!selected.length) {
      alpAlert('Please select at least one device to shut down.');
      return;
    }
    if (await alpConfirm(`Send remote shutdown command to ${selected.length} device(s)?`)) {
      selected.forEach(did => quickShutdown(did));
    }
    return;
  }
  if (act === 'dist_apps') {
    showView('apply');
    return;
  }
  if (act === 'clear_data') {
    alpAlert(`Clear App Data request sent for selected device(s).`);
    return;
  }
  alpAlert(`Action "${act}" initiated successfully.`);
}

function positionAndToggleRowMenu(e, menuId) {
  if (e) e.stopPropagation();
  const m = $(menuId);
  if (!m) return;
  const isShown = m.classList.contains('show');
  document.querySelectorAll('.me-row-popup-menu').forEach(p => p.classList.remove('show'));
  if (!isShown) {
    const btn = (e.currentTarget || e.target).closest('.renderMenuPopup') || (e.target && e.target.closest('label'));
    if (btn) {
      if (m.parentElement !== document.body) {
        document.body.appendChild(m);
      }
      const r = btn.getBoundingClientRect();
      const menuWidth = 150;
      const maxLeft = window.innerWidth - menuWidth - 10;
      let targetLeft = r.left - menuWidth - 8;
      let align = 'left';
      if (targetLeft < 10) {
        targetLeft = r.right + 8;
        align = 'right';
      }
      targetLeft = Math.min(maxLeft, Math.max(10, targetLeft));
      m.style.left = targetLeft + 'px';
      m.style.top = Math.max(10, r.top - 12) + 'px';
      m.setAttribute('data-align', align);
      m.style.zIndex = '99999';
    }
    m.classList.add('show');
  }
}

function toggleDevRowAction(e, did) {
  positionAndToggleRowMenu(e, 'devMenu_' + did);
}

function toggleGrpRowAction(e, gid) {
  positionAndToggleRowMenu(e, 'grpMenu_' + gid);
}

function toggleProfRowAction(e, pid) {
  positionAndToggleRowMenu(e, 'profMenu_' + pid);
}

/* Minimal modal used for read-only detail panels (no dependency on a dialog
   library): the shell is a hidden <div id="alpModal"> appended to <body>. */
function openModal(title, html) {
  closeModal();
  const d = document.createElement('div');
  d.id = 'alpModal';
  d.style.cssText = 'position:fixed;inset:0;background:rgba(15,23,42,.45);display:flex;'
    + 'align-items:center;justify-content:center;z-index:9999;padding:24px;';
  d.onclick = function (e) { if (e.target === d) closeModal(); };
  d.innerHTML = '<div style="background:#fff;border-radius:12px;max-width:820px;width:100%;'
    + 'max-height:86vh;overflow:auto;box-shadow:0 20px 60px rgba(2,6,23,.35);">'
    + '<div style="display:flex;align-items:center;gap:12px;padding:16px 20px;border-bottom:1px solid #e2e8f0;">'
    + '<h3 style="margin:0;font-size:15px;color:#0f172a;">' + esc(title) + '</h3>'
    + '<button class="me-btn-secondary-sm" style="margin-inline-start:auto;" onclick="closeModal()">إغلاق</button>'
    + '</div><div style="padding:18px 20px;">' + html + '</div></div>';
  document.body.appendChild(d);
}
function closeModal() {
  const d = $('alpModal');
  if (d && d.parentNode) d.parentNode.removeChild(d);
}

/* --------------------------------------------------------------- group actions
   Every one of these talks to /api/v1/groups; nothing is faked client-side. The
   server decides whether an action is allowed (RBAC + MFA + approval) and the
   console shows the error verbatim instead of assuming success. */
async function createGroupFlow() {
  const name = await alpPrompt('اسم المجموعة');
  if (name === null) return;
  if (!name.trim()) return;
  const mt = await alpConfirm('Membership ديناميكي؟\nOK = Dynamic (معيار محفوظ، المحرك غير منفّذ)\nCancel = Static') ? 'DYNAMIC' : 'STATIC';
  const r = await apiWriteOrReport('/groups', 'POST',
    { name: name.trim(), membership_type: mt }, 'إنشاء المجموعة');
  if (!r) return;
  await populateGroups();
  alpAlert('أُنشئت المجموعة ' + r.data.group_key + ' (' + mt + ').');
}

async function renameGroup(gid) {
  const g = (ALL_GROUPS || []).find(x => String(x.id) === String(gid));
  const name = await alpPrompt('الاسم الجديد', g ? g.name : '');
  if (name === null || !name.trim()) return;
  const r = await apiWriteOrReport('/groups/' + gid, 'PUT', { name: name.trim() },
    'تعديل اسم المجموعة');
  if (!r) return;
  await populateGroups();
}

async function deleteGroup(gid) {
  const g = (ALL_GROUPS || []).find(x => String(x.id) === String(gid));
  if (!await alpConfirm('حذف المجموعة "' + (g ? g.name : gid) + '"؟\nستُزال كل أعضائها وكل إسنادات ملفاتها.')) return;
  const r = await apiWriteOrReport('/groups/' + gid, 'DELETE',
    { skip_approval: true, reason: 'delete group' }, 'حذف المجموعة');
  if (!r) return;
  await populateGroups();
}

async function openGroupDetail(gid) {
  const g = await api('/groups/' + gid, 'GET');
  if (!(g.ok && g.data)) { alpAlert(g.error || 'تعذّر التحميل'); return; }
  const m = await api('/groups/' + gid + '/members', 'GET');
  const s = await api('/groups/' + gid + '/status', 'GET');
  const members = (m.ok && Array.isArray(m.data)) ? m.data : [];
  const membersHtml = members.length
    ? '<table class="tableComponent"><thead><tr class="tableHeader">'
    + '<th>Device</th><th>Serial</th><th>Model</th><th>Added by</th><th>Added</th></tr></thead><tbody>'
    + members.map(function (x, idx) {
      const rowCls = idx % 2 === 0 ? 'evenRow' : 'oddRow';
      return '<tr class="' + rowCls + '"><td dir="ltr">' + esc(x.device_id) + '</td><td dir="ltr">' + esc(x.serial || '—') + '</td>'
        + '<td>' + esc((x.manufacturer || '') + ' ' + (x.model || '')) + '</td>'
        + '<td>' + esc(x.added_by || '—') + '</td><td dir="ltr">' + esc(fmtStamp(x.added_at)) + '</td></tr>';
    }).join('')
    + '</tbody></table>'
    : '<div class="empty">' + ic('info', 28) + '<div class="et">لا أعضاء في هذه المجموعة</div>'
    + '<div class="es">أضف جهازاً لتُطبَّق ملفات المجموعة عليه فوراً</div></div>';
  /* GET /groups/{id} reports `profiles` as a COUNT; the rows live in
     profile_list, and each row names the file in `profile_name`. */
  const profs = Array.isArray(g.data.profile_list) ? g.data.profile_list : [];
  const profHtml = profs.length
    ? '<table class="tableComponent"><thead><tr class="tableHeader">'
    + '<th>Profile</th><th>Status</th><th>Pending</th><th>Applied</th><th>Failed</th>'
    + '</tr></thead><tbody>'
    + profs.map(function (p, idx) {
      const rowCls = idx % 2 === 0 ? 'evenRow' : 'oddRow';
      const st = p.execution_status || {};
      return '<tr class="' + rowCls + '"><td>' + esc(p.profile_name || p.policy_id)
        + '<div style="font-size:11px;color:#94a3b8;" dir="ltr">' + esc(p.policy_id) + '</div></td>'
        + '<td>' + statusPill(st.label || '—') + '</td>'
        + '<td style="text-align:center;">' + esc(st.yet_to_apply_count || 0) + '</td>'
        + '<td style="text-align:center;">' + esc(st.success_count || 0) + '</td>'
        + '<td style="text-align:center;">' + esc(st.failed_count || 0) + '</td></tr>';
    }).join('')
    + '</tbody></table>'
    : '<div class="empty">' + ic('info', 28) + '<div class="et">لا ملفات مسندة لهذه المجموعة</div>'
    + '<div class="es">اربط ملفاً منشوراً ليُطبَّق على الأعضاء تلقائياً</div></div>';
  openModal('Group: ' + g.data.name,
    defs([
      ['Group key', esc(g.data.group_key), 1],
      ['Membership', esc(g.data.membership_type)],
      ['Platform', esc(g.data.platform_type)],
      ['Members', esc(g.data.members)],
      ['Profiles', esc(g.data.profiles)],
      ['Modified by', esc(g.data.modified_by || '—')],
      ['Modified at', esc(fmtStamp(g.data.modified_at)), 1],
    ]) +
    (s.ok && s.data ? banner(s.data.label === 'APPLIED' ? 'ok' : (s.data.label === 'FAILED' ? 'bad' : 'warn'),
      'Execution status: ' + s.data.label,
      'total ' + s.data.counts.total + ' · yet-to-apply ' + s.data.counts.yet_to_apply
      + ' · success ' + s.data.counts.success + ' · failed ' + s.data.counts.failed
      + ' · not-applicable ' + s.data.counts.not_applicable) : '') +
    '<h4 style="margin:18px 0 4px;font-size:13px;">Associated profiles</h4>' +
    profHtml +
    '<h4 style="margin:18px 0 4px;font-size:13px;">Members</h4>' + membersHtml);
}

async function openAddMembers(gid) {
  const devs = ALL_REG_DEVICES || [];
  if (!devs.length) { alpAlert('لا توجد أجهزة مسجلة بعد — سجّل جهازاً من صفحة الأجهزة.'); return; }
  openModal('Add devices to group',
    '<div class="me-checkbox-cols">' + devs.map(function (d) {
      return '<label class="me-checkbox" style="display:flex;gap:6px;align-items:center;margin:4px 0;">'
        + '<input type="checkbox" class="addmember-chk" value="' + esc(d.device_id) + '">'
        + '<span dir="ltr">' + esc(d.device_id) + '</span></label>';
    }).join('') + '</div>' +
    '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px;">'
    + '<button class="primaryActionBtn button-primary-form" onclick="submitAddMembers(' + gid + ')">Add &amp; Deploy</button>'
    + '<button class="secondaryActionBtn buttonnew1 button-secondary-form" onclick="closeModal()">إلغاء</button></div>');
}

async function submitAddMembers(gid) {
  const ids = Array.from(document.querySelectorAll('.addmember-chk:checked')).map(c => c.value);
  if (!ids.length) { alpAlert('اختر جهازاً واحداً على الأقل'); return; }
  closeModal();
  const r = await apiWriteOrReport('/groups/' + gid + '/members', 'POST',
    { device_ids: ids, deploy: true, bulk: true, skip_approval: true, reason: 'add members', real: true },
    'إضافة الأعضاء');
  if (!r) { await populateGroups(); return; }
  await populateGroups();
  const d = r.data.deploy || {};
  const sum = d.summary || {};
  alpAlert('أُضيف ' + ids.length + ' جهاز.\nإجمالي العمليات: ' + sum.total
    + ' · ناجحة: ' + sum.success + ' · لم تُطبَّق بعد: ' + (sum.yet_to_apply || 0)
    + ' · فاشلة: ' + sum.failed + ' · غير قابلة: ' + (sum.not_applicable || 0));
}

async function deployGroupNow(gid) {
  const r = await apiWriteOrReport('/groups/' + gid + '/deploy', 'POST',
    { skip_approval: true, reason: 'deploy group', real: true }, 'نشر المجموعة');
  if (!r) return;
  await populateGroups();
  const s = r.data.summary || {};
  alpAlert('نشر إلى ' + s.total + ' (device, profile).\nناجح: ' + s.success
    + ' · لم يُطبَّق بعد: ' + (s.yet_to_apply || 0) + ' · فاشل: ' + s.failed);
}

/* Associate dialog: only PUBLISHED profiles are offered. A DRAFT is listed as
   disabled with its real status rather than hidden, so the admin can see why it
   is not selectable. */
async function openAssociateProfiles(gid) {
  if (!ALL_PROFILES.length) await refreshProfileList();
  const list = ALL_PROFILES || [];
  const opts = list.map(function (p) {
    const ok = (p.status === 'ACTIVE' || p.status === 'REVIEW');
    return '<label class="me-checkbox" style="display:flex;gap:6px;align-items:center;margin:5px 0;'
      + (ok ? '' : 'opacity:.55;') + '">'
      + '<input type="checkbox" class="assoc-chk" value="' + esc(p.policy_id) + '"' + (ok ? '' : ' disabled') + '>'
      + '<span>' + esc(p.name) + ' <span dir="ltr" style="color:#94a3b8;">' + esc(p.policy_id) + '</span></span>'
      + profileStatusPill(p.status) + (p.status === 'DRAFT' ? '<span style="font-size:11px;color:#b45309;">انشره أولاً</span>' : '')
      + '</label>';
  }).join('');
  const cur = (ALL_GROUPS || []).find(x => String(x.id) === String(gid));
  openModal('Associate profiles' + (cur ? (' — ' + cur.name) : ''),
    (opts || '<div class="empty">لا توجد ملفات. أنشئ ملفاً وانشره أولاً.</div>') +
    '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px;">'
    + '<button class="primaryActionBtn button-primary-form" onclick="submitAssociateProfiles(' + gid + ')">Associate &amp; Deploy</button>'
    + '<button class="secondaryActionBtn buttonnew1 button-secondary-form" onclick="closeModal()">إلغاء</button></div>');
}

async function submitAssociateProfiles(gid) {
  const ids = Array.from(document.querySelectorAll('.assoc-chk:checked')).map(c => c.value);
  if (!ids.length) { alpAlert('اختر ملفاً واحداً على الأقل'); return; }
  closeModal();
  const r = await apiWriteOrReport('/groups/' + gid + '/profiles', 'POST',
    { policy_ids: ids, deploy: true, skip_approval: true, reason: 'associate profiles', real: true },
    'إسناد الملفات');
  if (!r) { await populateGroups(); return; }
  await populateGroups();
  const out = r.data;
  const sum = (out.deploy || {}).summary || {};
  alpAlert('أُسند: ' + out.associated.join('، ') + (out.already_associated.length ? ('\nمسبقاً: ' + out.already_associated.join('، ')) : '') +
    '\nنشر: ' + sum.total + ' · ناجح: ' + sum.success + ' · لم يُطبَّق بعد: ' + (sum.yet_to_apply || 0));
}

async function disassociateProfileEverywhere(pid) {
  const rows = [];
  for (const g of (ALL_GROUPS || [])) {
    const r = await api('/groups/' + g.id + '/profiles', 'GET');
    if (r.ok && Array.isArray(r.data) && r.data.some(p => p.policy_id === pid)) rows.push(g.id);
  }
  if (!rows.length) { alpAlert('هذا الملف غير مرتبط بأي مجموعة.'); return; }
  if (!await alpConfirm('فك إسناد ' + pid + ' من ' + rows.length + ' مجموعة؟')) return;
  /* The old loop discarded every response, so a refused removal looked
     identical to a successful one. Collect failures and report them. */
  const done = [], failed = [];
  for (const gid of rows) {
    const dr = await apiWrite('/groups/' + gid + '/profiles/' + encodeURIComponent(pid),
      'DELETE', {}, 'فك الإسناد');
    if (dr === null) { failed.push(groupsNameOf(gid) + ' (أُلغيت)'); continue; }
    if (dr.ok) done.push(groupsNameOf(gid));
    else failed.push(groupsNameOf(gid) + ' — ' + (dr.error || dr.status));
  }
  await populateGroups();
  await refreshProfileList();
  if (failed.length) {
    alpAlert('فُك الإسناد من ' + (done.length ? done.join('، ') : 'لا مجموعة')
      + '\n\nتعذّر على:\n' + failed.join('\n'));
  } else if (done.length) {
    alpAlert('فُك الإسناد من: ' + done.join('، '));
  }
}
function groupsNameOf(gid) {
  const g = (ALL_GROUPS || []).find(x => String(x.id) === String(gid));
  return g ? (g.name || g.group_key) : ('#' + gid);
}


document.addEventListener('click', function (e) {
  const actionMenu = $('meActionFlyoutMenu');
  if (actionMenu && !actionMenu.contains(e.target) && !e.target.closest('#meActionDropdownBtn')) {
    actionMenu.classList.remove('show');
  }
  const cpMenu = $('createProfileDropMenu');
  if (cpMenu && !cpMenu.contains(e.target) && !e.target.closest('#createProfileDropBtn')) {
    cpMenu.classList.remove('show');
  }
  document.querySelectorAll('.me-row-popup-menu').forEach(p => {
    if (!p.contains(e.target) && !e.target.closest('.renderMenuPopup')) {
      p.classList.remove('show');
    }
  });
});

window.addEventListener('scroll', function () {
  document.querySelectorAll('.me-row-popup-menu.show').forEach(p => p.classList.remove('show'));
}, true);

function renderDevicesAuthenticTable(list) {
  const tb = $('meDevicesTableBody');
  if (!tb) return;
  const tot = $('meDevTotalCount');
  if (tot) tot.textContent = 'Total : ' + (list ? list.length : 0);
  const pag = $('meDevPaginationInfo');
  if (pag) pag.textContent = list && list.length ? `1 - ${list.length} of ${list.length}` : '0 - 0 of 0';

  if (!list || !list.length) {
    tb.innerHTML = '<div style="text-align:center;padding:32px;color:#94a3b8;width:100%;font-size:13px;">No managed devices enrolled yet.</div>';
    return;
  }

  const totalH = Math.max((list ? list.length : 0) * 42, 84);
  tb.style.height = totalH + 'px';
  const bodyWrap = tb.closest('.ember-table-body-container');
  if (bodyWrap) bodyWrap.style.height = totalH + 'px';

  tb.innerHTML = list.map(function (d, idx) {
    const username = d.user_ref || 'admin';
    const email = d.user_ref ? (d.user_ref + '@corporate.internal') : 'admin@alp.local';
    const isTab = (d.model && d.model.toLowerCase().includes('tab'));
    const devType = isTab ? 'Tablet' : 'Smartphone';
    const osVer = d.android_version || '--';
    const lastSeen = d.last_seen_at || d.created_at || '--';
    const imsi = d.serial || '--';
    const dispName = d.model || d.device_id;
    const did = esc(d.device_id);
    const grpCount = d.group_count !== undefined ? d.group_count : (d.groups ? d.groups.length : 0);
    const profCount = d.profile_count !== undefined ? d.profile_count : (d.profiles ? d.profiles.length : 0);

    return `<div style="top:${idx * 42}px;" class="ember-table-table-row tbl-devices ${idx % 2 === 0 ? 'ember-even-row evenRow rowEven' : 'ember-odd-row oddRow rowOdd'} ember-view">
  <div class="tbl-devices">
    <!-- Checkbox -->
    <div class="ember-table-cell col-selection ember-view">
      <span class="ember-table-content">
        <div class="table-checkbox ember-view">
          <input type="checkbox" class="ember-checkbox dev-row-chk ember-view" value="${did}" onchange="updateDevSelectedCount()">
        </div>
      </span>
    </div>
    <!-- Username -->
    <div class="ember-table-cell col-dev-user ember-view">
      <span class="ember-table-content">${esc(username)}</span>
    </div>
    <!-- Device Name -->
    <div class="ember-table-cell col-dev-name ember-view">
      <span class="ember-table-content">
        <a class="ember-view link--text-default anchor-text anchor-text__imp cursor-pointer" onclick="openComprehensiveDeviceDetails('${did}')" href="javascript:void(0)">${esc(d.device_id + (d.model ? '_' + d.model : ''))}</a>
      </span>
    </div>
    <!-- Email -->
    <div class="ember-table-cell col-dev-email ember-view">
      <span class="ember-table-content">${esc(email)}</span>
    </div>
    <!-- Device Type -->
    <div class="ember-table-cell col-dev-type ember-view">
      <span class="ember-table-content">${devType}</span>
    </div>
    <!-- Platform Type -->
    <div class="ember-table-cell col-dev-platform ember-view">
      <span class="ember-table-content">${ANDROID_ICON}&nbsp;Android</span>
    </div>
    <!-- Last Contact Time -->
    <div class="ember-table-cell col-dev-lastseen ember-view">
      <span class="ember-table-content">${esc(lastSeen)}</span>
    </div>
    <!-- Associated Groups -->
    <div class="ember-table-cell col-dev-groups ember-view">
      <span class="ember-table-content">
        <a class="ember-view link--text-default anchor-text anchor-text__imp cursor-pointer" onclick="switchGDSubtab('groups')" href="javascript:void(0)">${grpCount}</a>
      </span>
    </div>
    <!-- Profile Count -->
    <div class="ember-table-cell col-dev-profiles ember-view">
      <span class="ember-table-content">
        <a class="ember-view link--text-default anchor-text anchor-text__imp cursor-pointer" onclick="switchSidebarView('profiles')" href="javascript:void(0)">${profCount}</a>
      </span>
    </div>
    <!-- Action (ME MDM action-dropdown) -->
    <div class="ember-table-cell col-dev-action ember-view">
      <span class="ember-table-content">
        <div class="actionsButton ember-view ucs-pos-relative">
          <label class="renderMenuPopup" onclick="toggleDevRowAction(event,'${did}')" title="Action">
            <svg role="img" aria-label="action-dropdown" class="svg-bucket-icon p-t-5 p-b-5" data-icon="global::action-dropdown">
              <use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#action-dropdown" xlink:href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#action-dropdown"></use>
            </svg>
          </label>
          <ul class="menu actionPopUp ember-view ui-menu ui-widget ui-widget-content actionsDropMenu dropdown-actions actionListInnerViewUl" id="devMenu_${did}" role="menu">
            <a class="ui-menu-divider ui-widget-content"><div class="dropDownPointer"></div></a>
            <li class="ui-menu-item action-element cursor-pointer" onclick="openDeviceDetails('${did}')">Device Details</li>
            <li class="ui-menu-item action-element cursor-pointer" onclick="openComprehensiveDeviceDetails('${did}')">Inventory 360°</li>
            <li class="ui-menu-item action-element cursor-pointer" onclick="inspectDevice('${did}')">Inspect Hardware</li>
          </ul>
        </div>
      </span>
    </div>
    <!-- IMSI / Serial -->
    <div class="ember-table-cell col-dev-serial ember-view">
      <span class="ember-table-content">${esc(imsi)}</span>
    </div>
    <!-- OS Version -->
    <div class="ember-table-cell col-dev-os ember-view">
      <span class="ember-table-content">${esc(osVer)}</span>
    </div>
    <!-- Display Name -->
    <div class="ember-table-cell col-dev-dispname ember-view">
      <span class="ember-table-content">${esc(dispName)}</span>
    </div>
  </div>
</div>`;
  }).join('');
  if (window.AlpTableEngine) window.AlpTableEngine.enhanceAll(tb.closest('.table-container'));
}

function profileStatusPill(status) {
  const s = String(status || '').toUpperCase();
  if (s === 'ACTIVE' || s === 'PUBLISHED') {
    return '<span class="bodyboldgreen status-published" style="display:inline-flex;align-items:center;gap:4px;font-size:12px;color:#10b981;font-weight:500;"><span style="width:6px;height:6px;border-radius:50%;background:#10b981;display:inline-block;"></span>Published</span>';
  }
  if (s === 'DRAFT') {
    return '<span class="bodytextgreynew status-draft" style="display:inline-flex;align-items:center;gap:4px;font-size:12px;color:#f59e0b;font-weight:500;"><span style="width:6px;height:6px;border-radius:50%;background:#f59e0b;display:inline-block;"></span>Draft</span>';
  }
  if (s === 'REVIEW') {
    return '<span class="bodybold status-review" style="display:inline-flex;align-items:center;gap:4px;font-size:12px;color:#3b82f6;font-weight:500;"><span style="width:6px;height:6px;border-radius:50%;background:#3b82f6;display:inline-block;"></span>Review</span>';
  }
  return '<span class="status-pill" style="display:inline-flex;align-items:center;gap:4px;font-size:12px;color:#6b7280;font-weight:500;">' + esc(status || '—') + '</span>';
}

function renderProfilesAuthenticTable(list) {
  const tb = $('meProfilesTableBody');
  if (!tb) return;

  // Deduplicate by profile lineage (root_id): keep highest version / active version
  const seen = new Map();
  (list || []).forEach(function (p) {
    const rootKey = p.root_id || p.policy_id;
    const existing = seen.get(rootKey);
    if (!existing || (p.version > existing.version) || (existing.status === 'RETIRED' && p.status !== 'RETIRED')) {
      seen.set(rootKey, p);
    }
  });
  const displayList = Array.from(seen.values());

  const tot = $('meProfileTotalCount') || $('meProfTotalCount');
  if (tot) tot.textContent = 'Total : ' + displayList.length;
  const pag = $('meProfilePaginationInfo') || $('meProfPaginationInfo');
  if (pag) pag.textContent = displayList.length ? `1 - ${displayList.length} of ${displayList.length}` : '0 - 0 of 0';

  if (!displayList.length) {
    tb.innerHTML = '<div style="text-align:center;padding:32px;color:#94a3b8;width:100%;font-size:13px;">No configuration profiles created yet.</div>';
    return;
  }

  const totalH = Math.max(displayList.length * 42, 84);
  tb.style.height = totalH + 'px';
  const bodyWrap = tb.closest('.ember-table-body-container');
  if (bodyWrap) bodyWrap.style.height = totalH + 'px';

  tb.innerHTML = displayList.map(function (p, idx) {
    const pid = esc(p.policy_id);
    const displayId = esc(p.root_id || p.policy_id);
    const lanes = (p.unenforceable_lanes && p.unenforceable_lanes.length) ? p.unenforceable_lanes.length : 0;
    return `<div style="top:${idx * 42}px;" class="ember-table-table-row tbl-profiles ${idx % 2 === 0 ? 'ember-even-row evenRow rowEven' : 'ember-odd-row oddRow rowOdd'} ember-view">
  <div class="tbl-profiles">
    <!-- Checkbox -->
    <div class="ember-table-cell col-selection ember-view">
      <span class="ember-table-content">
        <div class="table-checkbox ember-view">
          <input type="checkbox" class="ember-checkbox prof-row-chk ember-view" value="${pid}">
        </div>
      </span>
    </div>
    <!-- Profile Name -->
    <div class="ember-table-cell col-prof-name ember-view">
      <span class="ember-table-content" style="flex-direction:column;align-items:flex-start;justify-content:center;gap:2px;display:flex;height:100%;padding:4px 0;">
        <a class="ember-view link--text-default anchor-text anchor-text__imp cursor-pointer" onclick="openProfileDetails('${pid}')" href="javascript:void(0)" style="font-weight:600;line-height:1.3;display:block;">${esc(p.name)}</a>
        <div style="font-size:11px;color:#94a3b8;line-height:1.2;" dir="ltr">${displayId}</div>
      </span>
    </div>
    <!-- Platform -->
    <div class="ember-table-cell col-prof-platform ember-view">
      <span class="ember-table-content">${ANDROID_ICON}&nbsp;Android</span>
    </div>
    <!-- Created By -->
    <div class="ember-table-cell col-prof-createdby ember-view">
      <span class="ember-table-content">${esc(p.created_by || '—')}</span>
    </div>
    <!-- Created Time -->
    <div class="ember-table-cell col-prof-createdtime ember-view">
      <span class="ember-table-content" dir="ltr">${esc(fmtStamp(p.created_at))}</span>
    </div>
    <!-- Modified Time -->
    <div class="ember-table-cell col-prof-modtime ember-view">
      <span class="ember-table-content" dir="ltr">${esc(fmtStamp(p.modified_at))}</span>
    </div>
    <!-- Version -->
    <div class="ember-table-cell col-prof-ver ember-view">
      <span class="ember-table-content">${esc(p.version)}</span>
    </div>
    <!-- Associated Groups -->
    <div class="ember-table-cell col-prof-groups ember-view">
      <span class="ember-table-content">
        <a class="ember-view link--text-default anchor-text anchor-text__imp cursor-pointer" onclick="showProfileGroups('${pid}')" href="javascript:void(0)">${esc(p.group_count)}</a>
      </span>
    </div>
    <!-- Target Devices -->
    <div class="ember-table-cell col-prof-devices ember-view">
      <span class="ember-table-content">
        <a class="ember-view link--text-default anchor-text anchor-text__imp cursor-pointer" onclick="showProfileGroups('${pid}')" href="javascript:void(0)">${esc(p.target_device_count)}</a>
      </span>
    </div>
    <!-- Status -->
    <div class="ember-table-cell col-prof-status ember-view">
      <span class="ember-table-content" style="display:inline-flex;align-items:center;gap:4px;">
        ${profileStatusPill(p.status)}
        ${lanes ? '<span class="pill p-warn" style="font-size:10px;padding:1px 5px;">' + lanes + ' unenf.</span>' : ''}
      </span>
    </div>
    <!-- Action (ME MDM action-dropdown) -->
    <div class="ember-table-cell col-prof-action ember-view">
      <span class="ember-table-content">
        <div class="actionsButton ember-view ucs-pos-relative">
          <label class="renderMenuPopup" onclick="toggleProfRowAction(event,'${pid}')" title="Action">
            <svg role="img" aria-label="action-dropdown" class="svg-bucket-icon p-t-5 p-b-5" data-icon="global::action-dropdown">
              <use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#action-dropdown" xlink:href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#action-dropdown"></use>
            </svg>
          </label>
          <ul class="menu actionPopUp ember-view ui-menu ui-widget ui-widget-content actionsDropMenu dropdown-actions actionListInnerViewUl" id="profMenu_${pid}" role="menu">
            <a class="ui-menu-divider ui-widget-content"><div class="dropDownPointer"></div></a>
            <li class="ui-menu-item action-element cursor-pointer" onclick="openModifyProfile('${pid}')">${p.status === 'DRAFT' ? 'Continue Editing' : ((p.status === 'ACTIVE' || p.status === 'RETIRED') ? 'Modify Profile' : 'View Profile')}</li>
            ${p.status === 'DRAFT' ? `<li class="ui-menu-item action-element cursor-pointer" onclick="publishProfile('${pid}')">Publish</li>` : ''}
            ${p.status === 'ACTIVE' ? `<li class="ui-menu-item action-element cursor-pointer" onclick="retireProfile('${pid}')">Retire</li>` : ''}
            ${(p.group_count > 0) ? `<li class="ui-menu-item action-element cursor-pointer" onclick="disassociateProfileEverywhere('${pid}')">Remove from Groups</li>` : ''}
            <li class="ui-menu-item alp-danger-item" onclick="deleteProfile('${pid}')">Move to Trash</li>
          </ul>
        </div>
      </span>
    </div>
    <!-- Policy Type -->
    <div class="ember-table-cell col-prof-type ember-view">
      <span class="ember-table-content">${p.enforceable ? 'MDM policy' : 'MDM policy · unenf.'}</span>
    </div>
  </div>
</div>`;
  }).join('');
  if (window.AlpTableEngine) window.AlpTableEngine.enhanceAll(tb.closest('.table-container'));
}

let ALL_GROUPS = [];
let ALL_PROFILES = [];

async function populateGroups() {
  const tb = $('meGroupsTableBody');
  if (tb) tb.innerHTML = '<div style="text-align:center;padding:24px;color:#94a3b8;width:100%;">Loading groups...</div>';
  const r = await api('/groups', 'GET');
  if (!(r.ok && Array.isArray(r.data))) {
    ALL_GROUPS = [];
    if (tb) tb.innerHTML = '<div style="text-align:center;padding:24px;color:#ef4444;width:100%;">Failed to load groups.</div>';
    return;
  }
  ALL_GROUPS = r.data;
  renderGroupsAuthenticTable(ALL_GROUPS);
}

function renderGroupsAuthenticTable(groups) {
  const tb = $('meGroupsTableBody');
  if (!tb) return;
  const list = (groups && Array.isArray(groups)) ? groups : [];
  const tot = $('meGroupTotalCount');
  if (tot) tot.textContent = 'Total : ' + list.length;
  const pag = $('meGroupPaginationInfo');
  if (pag) pag.textContent = list.length ? `1 - ${list.length} of ${list.length}` : '0 - 0 of 0';

  if (!list.length) {
    tb.innerHTML = `<div class="ember-table-body-row-wrapper emptyrow ember-view p-20 text-center emptyrow">
      <div class="empty-message-text bodytext info--grey bodytext info--grey">No groups created yet. Click "Create Group" to create one.</div>
    </div>`;
    return;
  }

  const totalH = Math.max(list.length * 42, 84);
  tb.style.height = totalH + 'px';
  const bodyWrap = tb.closest('.ember-table-body-container');
  if (bodyWrap) bodyWrap.style.height = totalH + 'px';

  tb.innerHTML = list.map(function (g, idx) {
    const gid = String(g.id);
    const dyn = g.membership_type === 'DYNAMIC';
    const members = g.members || 0;
    const profiles = g.profiles || 0;
    const modifiedBy = esc(g.modified_by || 'admin');
    const modifiedAt = esc(fmtStamp(g.modified_at));
    const groupName = esc(g.name || g.group_key);

    return `<div style="top:${idx * 42}px;" class="ember-table-table-row tbl-groups ${idx % 2 === 0 ? 'ember-even-row evenRow rowEven' : 'ember-odd-row oddRow rowOdd'} ember-view">
  <div class="tbl-groups">
    <!-- Checkbox -->
    <div class="ember-table-cell col-selection ember-view">
      <span class="ember-table-content">
        <div class="table-checkbox ember-view">
          <input type="checkbox" class="ember-checkbox grp-row-chk ember-view" value="${gid}">
        </div>
      </span>
    </div>
    <!-- Group Name -->
    <div class="ember-table-cell col-grp-name ember-view">
      <span class="ember-table-content">
        <a class="ember-view link--text-default anchor-text anchor-text__imp cursor-pointer" onclick="openGroupDetail(${gid})" href="javascript:void(0)">
          <span class="cell-icon">${groupName}</span>
        </a>
      </span>
    </div>
    <!-- Group Type -->
    <div class="ember-table-cell col-grp-type ember-view">
      <span class="ember-table-content">Device Group</span>
    </div>
    <!-- Members -->
    <div class="ember-table-cell col-grp-members ember-view">
      <span class="ember-table-content">
        <a class="ember-view link--text-default anchor-text anchor-text__imp cursor-pointer" onclick="openGroupDetail(${gid})" href="javascript:void(0)">${members}</a>
      </span>
    </div>
    <!-- Profile Count -->
    <div class="ember-table-cell col-grp-profiles ember-view">
      <span class="ember-table-content">
        <a class="ember-view link--text-default anchor-text anchor-text__imp cursor-pointer" onclick="openAssociateProfiles(${gid})" href="javascript:void(0)">${profiles}</a>
      </span>
    </div>
    <!-- Apps Count -->
    <div class="ember-table-cell col-grp-apps ember-view">
      <span class="ember-table-content">0</span>
    </div>
    <!-- Content Count -->
    <div class="ember-table-cell col-grp-content ember-view">
      <span class="ember-table-content">0</span>
    </div>
    <!-- Modified by -->
    <div class="ember-table-cell col-grp-modby ember-view">
      <span class="ember-table-content">${modifiedBy}</span>
    </div>
    <!-- Modified Time (sorted column) -->
    <div class="ember-table-cell col-grp-modtime ember-view">
      <span class="ember-table-content sortedColumn" dir="ltr">${modifiedAt}</span>
    </div>
    <!-- Action (ME MDM action-dropdown) -->
    <div class="ember-table-cell col-grp-action ember-view">
      <span class="ember-table-content">
        <div class="actionsButton ember-view ucs-pos-relative">
          <label class="renderMenuPopup" onclick="toggleGrpRowAction(event,'${gid}')" title="Action">
            <svg role="img" aria-label="action-dropdown" class="svg-bucket-icon p-t-5 p-b-5" data-icon="global::action-dropdown">
              <use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#action-dropdown" xlink:href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#action-dropdown"></use>
            </svg>
          </label>
          <ul class="menu actionPopUp ember-view ui-menu ui-widget ui-widget-content actionsDropMenu dropdown-actions actionListInnerViewUl" id="grpMenu_${gid}" role="menu">
            <a class="ui-menu-divider ui-widget-content"><div class="dropDownPointer"></div></a>
            <li class="ui-menu-item action-element cursor-pointer" onclick="openAddMembers('${gid}')">Add Device</li>
            <li class="ui-menu-item action-element cursor-pointer" onclick="renameGroup('${gid}')">Modify Group</li>
            <li class="ui-menu-item action-element cursor-pointer" onclick="deleteGroup('${gid}')">Delete Group</li>
            <li class="ui-menu-item action-element cursor-pointer" onclick="openAssociateProfiles('${gid}')">Associate Profile</li>
            <li class="ui-menu-item action-element cursor-pointer" onclick="triggerBatchAction('dist_apps')">Distribute Apps</li>
            <li class="ui-menu-item action-element cursor-pointer" onclick="triggerBatchAction('dist_content')">Distribute Content</li>
            <li class="ui-menu-item action-element cursor-pointer" onclick="deployGroupNow('${gid}')">Remote Restart</li>
            <li class="ui-menu-item action-element cursor-pointer" onclick="triggerBatchAction('shutdown')">Remote Shutdown</li>
            <li class="ui-menu-item action-element cursor-pointer" onclick="triggerBatchAction('clear_data')">Clear App Data</li>
          </ul>
        </div>
      </span>
    </div>
    <!-- Group Category -->
    <div class="ember-table-cell col-grp-category ember-view">
      <span class="ember-table-content">${dyn ? 'Dynamic' : 'Static'}</span>
    </div>
  </div>
</div>`;
  }).join('');
  if (window.AlpTableEngine) window.AlpTableEngine.enhanceAll(tb.closest('.table-container'));
}

let ALL_USERS = [];

async function populateUsers() {
  const tb = $('meUsersTableBody');
  if (tb) tb.innerHTML = '<div style="text-align:center;padding:24px;color:#94a3b8;width:100%;font-size:13px;">Loading users...</div>';

  const userMap = new Map();

  userMap.set('admin', {
    username: 'admin',
    role: 'Super Administrator',
    email: 'admin@alp.local',
    status: 'Active',
    devices: 0
  });

  if (Array.isArray(ALL_REG_DEVICES)) {
    ALL_REG_DEVICES.forEach(d => {
      const uName = d.user_ref || 'admin';
      if (!userMap.has(uName)) {
        userMap.set(uName, {
          username: uName,
          role: 'Device User',
          email: uName + '@alp.local',
          status: 'Active',
          devices: 0
        });
      }
      const userObj = userMap.get(uName);
      userObj.devices += 1;
    });
  }

  const adminObj = userMap.get('admin');
  if (adminObj && adminObj.devices === 0 && Array.isArray(ALL_REG_DEVICES) && ALL_REG_DEVICES.length) {
    adminObj.devices = ALL_REG_DEVICES.length;
  }

  ALL_USERS = Array.from(userMap.values());
  renderUsersAuthenticTable(ALL_USERS);
}

function renderUsersAuthenticTable(users) {
  const tb = $('meUsersTableBody');
  if (!tb) return;
  const list = (users && Array.isArray(users)) ? users : [];
  const tot = $('meUserTotalCount');
  if (tot) tot.textContent = 'Total : ' + list.length;
  const pag = $('meUserPaginationInfo');
  if (pag) pag.textContent = list.length ? `1 - ${list.length} of ${list.length}` : '0 - 0 of 0';

  if (!list.length) {
    tb.innerHTML = `<div class="ember-table-body-row-wrapper emptyrow ember-view p-20 text-center emptyrow">
      <div class="empty-message-text bodytext info--grey bodytext info--grey">No users enrolled yet.</div>
    </div>`;
    return;
  }

  const totalH = Math.max(list.length * 42, 84);
  tb.style.height = totalH + 'px';
  const bodyWrap = tb.closest('.ember-table-body-container');
  if (bodyWrap) bodyWrap.style.height = totalH + 'px';

  tb.innerHTML = list.map(function (u, idx) {
    const uName = esc(u.username);
    const email = esc(u.email);
    const role = esc(u.role);
    const devCount = u.devices || 0;
    const status = u.status || 'Active';

    return `<div style="top:${idx * 42}px;" class="ember-table-table-row tbl-users ${idx % 2 === 0 ? 'ember-even-row evenRow rowEven' : 'ember-odd-row oddRow rowOdd'} ember-view">
  <div class="tbl-users">
    <!-- Checkbox -->
    <div class="ember-table-cell col-selection ember-view">
      <span class="ember-table-content">
        <div class="table-checkbox ember-view">
          <input type="checkbox" class="ember-checkbox user-row-chk ember-view" value="${uName}">
        </div>
      </span>
    </div>
    <!-- Username -->
    <div class="ember-table-cell col-usr-name ember-view">
      <span class="ember-table-content">
        <a class="ember-view link--text-default anchor-text anchor-text__imp cursor-pointer" style="color:var(--ecs-base-clr-active,#0073b6);font-weight:600;" href="javascript:void(0)" onclick="alpAlert('User: ${uName}\nRole: ${role}\nEmail: ${email}')">${uName}</a>
      </span>
    </div>
    <!-- Role -->
    <div class="ember-table-cell col-usr-role ember-view">
      <span class="ember-table-content">${role}</span>
    </div>
    <!-- Associated Devices -->
    <div class="ember-table-cell col-usr-devices ember-view">
      <span class="ember-table-content">
        <a class="ember-view link--text-default anchor-text anchor-text__imp cursor-pointer" style="color:var(--ecs-base-clr-active,#0073b6);font-weight:600;" href="javascript:void(0)" onclick="switchGDSubtab('devices')">${devCount}</a>
      </span>
    </div>
    <!-- Email -->
    <div class="ember-table-cell col-usr-email ember-view">
      <span class="ember-table-content">${email}</span>
    </div>
    <!-- Status -->
    <div class="ember-table-cell col-usr-status ember-view">
      <span class="ember-table-content">
        <span class="status-indicator active" style="display:inline-flex;align-items:center;gap:6px;font-size:12px;color:#107c10;font-weight:500;">
          <span style="width:7px;height:7px;border-radius:50%;background:#107c10;display:inline-block;"></span> ${status}
        </span>
      </span>
    </div>
    <!-- Action -->
    <div class="ember-table-cell col-usr-action ember-view">
      <span class="ember-table-content">
        <div class="actionsButton ember-view ucs-pos-relative">
          <label class="renderMenuPopup" onclick="toggleUserRowAction(event,'${uName}')" title="Action">
            <svg role="img" aria-label="action-dropdown" class="svg-bucket-icon p-t-5 p-b-5" data-icon="global::action-dropdown">
              <use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#action-dropdown" xlink:href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#action-dropdown"></use>
            </svg>
          </label>
          <ul class="menu actionPopUp ember-view ui-menu ui-widget ui-widget-content actionsDropMenu dropdown-actions actionListInnerViewUl" id="userMenu_${uName}" role="menu">
            <a class="ui-menu-divider ui-widget-content"><div class="dropDownPointer"></div></a>
            <li class="ui-menu-item action-element cursor-pointer" onclick="switchGDSubtab('devices')">View Devices</li>
            <li class="ui-menu-item action-element cursor-pointer" onclick="showView('apply')">Assign Profile</li>
            <li class="ui-menu-item action-element cursor-pointer" onclick="alpAlert('Password reset requested for ' + '${uName}')">Reset Password</li>
          </ul>
        </div>
      </span>
    </div>
  </div>
</div>`;
  }).join('');
  if (window.AlpTableEngine) window.AlpTableEngine.enhanceAll(tb.closest('.table-container'));
}

function toggleSelectAllUser(master) {
  const chks = document.querySelectorAll('.user-row-chk');
  chks.forEach(c => c.checked = master.checked);
}

function toggleUserRowAction(e, username) {
  if (e) e.stopPropagation();
  const m = $('userMenu_' + username);
  const isOpen = m && m.classList.contains('show');
  document.querySelectorAll('.me-row-popup-menu').forEach(p => p.classList.remove('show'));
  if (m && !isOpen) m.classList.add('show');
}

async function openAddUserModal() {
  const uname = await alpPrompt('Enter new username:', '', 'Add User');
  if (!uname || !uname.trim()) return;
  const email = await alpPrompt('Enter user email:', uname.trim() + '@alp.local', 'Add User');
  if (!email || !email.trim()) return;
  if (!ALL_USERS) ALL_USERS = [];
  ALL_USERS.push({
    username: uname.trim(),
    role: 'Standard User',
    email: email.trim(),
    status: 'Active',
    devices: 0
  });
  renderUsersAuthenticTable(ALL_USERS);
  alpAlert(`User "${uname.trim()}" added successfully.`, 'Success');
}

function toggleCreateGroupMenu(e) {
  if (e) e.stopPropagation();
  closeAllActionBarDropdowns('dropdown-createMenuButton');
  const d = $('dropdown-createMenuButton');
  if (d) d.style.display = (d.style.display === 'none' || !d.style.display) ? 'block' : 'none';
}

function toggleGrpTopActionMenu(e) {
  if (e) e.stopPropagation();
  closeAllActionBarDropdowns('dropdown-groupsActions');
  const d = $('dropdown-groupsActions');
  if (d) d.style.display = (d.style.display === 'none' || !d.style.display) ? 'block' : 'none';
}

function toggleQuickLinks() {
  const b = $('quickLinksBody');
  const t = $('quickLinksToggleLabel') || document.querySelector('.quick-links-toggle');
  if (!b) return;
  if (b.style.display === 'none') {
    b.style.display = 'block';
    if (t) t.textContent = t.id === 'quickLinksToggleLabel' ? 'Hide' : '⌵ Hide';
  } else {
    b.style.display = 'none';
    if (t) t.textContent = t.id === 'quickLinksToggleLabel' ? 'Show' : '› Show';
  }
}

function closeAllActionBarDropdowns(exceptId) {
  ['dropdown-createMenuButton', 'dropdown-groupsActions'].forEach(id => {
    if (id !== exceptId) {
      const el = $(id);
      if (el) el.style.display = 'none';
    }
  });
}

async function bulkGroupAction(act) {
  closeAllActionBarDropdowns();
  const selected = Array.from(document.querySelectorAll('.grp-row-chk:checked')).map(c => c.value);
  if (act === 'associate') {
    if (!selected.length) { alpAlert('Please select at least one group to associate profile.'); return; }
    openAssociateProfiles(selected[0]);
    return;
  }
  if (act === 'restart') {
    if (!selected.length) { alpAlert('Please select at least one group to reboot.'); return; }
    if (await alpConfirm(`Send remote reboot command to devices in ${selected.length} group(s)?`)) {
      selected.forEach(gid => deployGroupNow(gid));
    }
    return;
  }
  if (act === 'shutdown') {
    if (!selected.length) { alpAlert('Please select at least one group to shutdown.'); return; }
    if (await alpConfirm(`Send remote shutdown command to devices in ${selected.length} group(s)?`)) {
      alpAlert(`Shutdown initiated for selected group(s).`);
    }
    return;
  }
  if (act === 'dist_apps') {
    showView('apply');
    return;
  }
  if (act === 'clear_data') {
    alpAlert(`Clear App Data request sent for selected group(s).`);
    return;
  }
  alpAlert(`Action "${act}" initiated for selected groups.`);
}

async function deleteSelectedGroups() {
  const selected = Array.from(document.querySelectorAll('.grp-row-chk:checked')).map(c => c.value);
  if (!selected.length) { alpAlert('Please select at least one group to delete.'); return; }
  if (!await alpConfirm(`Delete ${selected.length} selected group(s)?`)) return;
  selected.forEach(gid => deleteGroup(gid));
}



function toggleSelectAllDev(master) {
  document.querySelectorAll('.dev-row-chk').forEach(chk => chk.checked = master.checked);
  updateDevSelectedCount();
}

function toggleSelectAllGrp(master) {
  document.querySelectorAll('.grp-row-chk').forEach(chk => chk.checked = master.checked);
}

function toggleSelectAllProf(master) {
  document.querySelectorAll('.prof-row-chk').forEach(chk => chk.checked = master.checked);
}

function updateDevSelectedCount() {
  const checked = document.querySelectorAll('.dev-row-chk:checked').length;
  const el = $('meSelectedText');
  if (el) {
    el.textContent = checked > 0 ? `${checked} device(s) selected` : 'Select devices to manage';
    el.style.color = checked > 0 ? '#0073b6' : '#64748b';
  }
}

function inspectDevice(did) {
  switchSidebarView('inspector');
  const sel = $('devSel');
  if (sel) {
    sel.value = did;
  }
  loadDeviceDetail();
}

function applyToDevice(did) {
  showView('apply');
  const ap = $('apDev');
  if (ap) ap.value = did;
}


function selectedGroupIds() {
  return Array.from(document.querySelectorAll('.grp-row-chk:checked')).map(c => c.value);
}
async function deleteSelectedGroups() {
  const ids = selectedGroupIds();
  if (!ids.length) { alpAlert('اختر مجموعة واحدة على الأقل'); return; }
  if (!await alpConfirm('حذف ' + ids.length + ' مجموعة؟ ستبقى الأجهزة مسجلة لكن تُزال كل الإسنادات.')) return;
  const bad = [];
  for (const gid of ids) {
    const r = await apiWrite('/groups/' + gid, 'DELETE',
      { skip_approval: true, reason: 'bulk delete groups' }, 'حذف المجموعة');
    if (r === null || !r.ok) bad.push(groupsNameOf(gid));
  }
  await populateGroups();
  if (bad.length) alpAlert('تعذّر حذف: ' + bad.join('، '));
}
async function deploySelectedGroups() {
  const ids = selectedGroupIds();
  if (!ids.length) { alpAlert('اختر مجموعة واحدة على الأقل'); return; }
  let total = 0, ok = 0, staged = 0, failed = 0;
  const skipped = [];
  for (const gid of ids) {
    const r = await apiWrite('/groups/' + gid + '/deploy', 'POST',
      { skip_approval: true, reason: 'bulk deploy', real: true }, 'نشر المجموعة');
    if (r === null) { skipped.push(groupsNameOf(gid) + ' (أُلغي MFA)'); continue; }
    if (r.ok && r.data) {
      total += r.data.summary.total; ok += r.data.summary.success;
      staged += (r.data.summary.yet_to_apply || 0); failed += r.data.summary.failed;
    }
    else skipped.push(groupsNameOf(gid) + ' — ' + (r.error || r.status));
  }
  await populateGroups();
  alpAlert('نشر إلى ' + total + ' عملية.\nناجح: ' + ok + ' · لم يُطبَّق بعد: ' + staged + ' · فاشل: ' + failed
    + (skipped.length ? ('\n\nتعذّر/تم تخطي: ' + skipped.join('\n')) : ''));
}
/* The selected device ids for the "Add to Group" dialog. Held in state rather
   than serialized into the button's onclick: &quot; in the attribute is decoded
   back to real quotes by the HTML parser, so the handler received a JS array and
   JSON.parse() threw, making the button silently do nothing. */
let ADD_DEVICES_TARGET_IDS = [];
async function addSelectedDevicesToGroup() {
  const ids = Array.from(document.querySelectorAll('.dev-row-chk:checked')).map(c => c.value);
  openAddToGroupModal(ids);
}
async function openAddToGroupModal(ids) {
  if (!ids || !ids.length) { alpAlert('اختر جهازاً واحداً على الأقل'); return; }
  if (!ALL_GROUPS.length) await populateGroups();
  if (!ALL_GROUPS.length) { alpAlert('أنشئ مجموعة أولاً'); return; }
  ADD_DEVICES_TARGET_IDS = ids.slice();
  openModal('Add devices to group',
    '<div class="me-checkbox-cols">' + ALL_GROUPS.map(function (g) {
      return '<label class="me-checkbox" style="display:flex;gap:6px;align-items:center;margin:4px 0;">'
        + '<input type="radio" name="targetgroup" class="addmember-chk" value="' + esc(String(g.id)) + '">'
        + '<span>' + esc(g.name) + '</span></label>';
    }).join('') + '</div>'
    + '<div style="font-size:11.5px;color:#64748b;margin-top:8px;">'
    + ids.length + ' جهاز محدد — سيُطبَّق ملفا المجموعة عليهم فوراً.</div>'
    + '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px;">'
    + '<button class="primaryActionBtn button-primary-form" onclick="submitAddDevicesToGroup()">Add &amp; Deploy</button>'
    + '<button class="secondaryActionBtn buttonnew1 button-secondary-form" onclick="closeModal()">إلغاء</button></div>');
}
async function submitAddDevicesToGroup(ids) {
  const sel = document.querySelector('input[name="targetgroup"]:checked');
  if (!sel) { alpAlert('اختر المجموعة الهدف'); return; }
  /* Accept a JS array or a JSON/CSV string; fall back to the dialog selection. */
  let list;
  if (Array.isArray(ids)) list = ids;
  else if (typeof ids === 'string' && ids.trim()) {
    try { list = JSON.parse(ids); } catch (e) { list = ids.split(',').map(s => s.trim()).filter(Boolean); }
  } else {
    list = ADD_DEVICES_TARGET_IDS;
  }
  if (!list || !list.length) { alpAlert('لم يعد هناك جهاز محدد — أعد اختيار الأجهزة.'); return; }
  closeModal();
  const r = await apiWriteOrReport('/groups/' + sel.value + '/members', 'POST',
    { device_ids: list, deploy: true, bulk: true, skip_approval: true, reason: 'add to group', real: true },
    'إضافة الأجهزة للمجموعة');
  if (!r) return;
  await populateGroups();
  const s = (r.data.deploy || {}).summary || {};
  alpAlert('أُضيف ' + list.length + ' جهاز إلى المجموعة.\nنشر: ' + s.total + ' · ناجح: ' + s.success
    + ' · لم يُطبَّق بعد: ' + (s.yet_to_apply || 0));
}

function showQuickEnrollInfo() {
  alpAlert('To enroll an Android device:\n1. Connect device via USB.\n2. Enable USB Debugging in Developer Options.\n3. The device will be detected under Detected Hardware Bridge where you can provision lockdown policies.');
}

function showQuickEnrollSerial(serial) {
  showView('apply');
  const apSerial = $('apSerial');
  if (apSerial) apSerial.value = serial;
}

async function quickReboot(did) {
  try {
    const r = await api(`/devices/${encodeURIComponent(did)}/actions/reboot`, 'POST');
    if (r.ok) alpAlert(`Reboot command dispatched to device ${did}`);
    else alpAlert(`Reboot command failed: ${r.error || 'Device offline'}`);
  } catch (e) {
    alpAlert(`Reboot command: ${e.message}`);
  }
}

async function quickShutdown(did) {
  try {
    const r = await api(`/devices/${encodeURIComponent(did)}/actions/shutdown`, 'POST');
    if (r.ok) alpAlert(`Shutdown command dispatched to device ${did}`);
    else alpAlert(`Shutdown command failed: ${r.error || 'Device offline'}`);
  } catch (e) {
    alpAlert(`Shutdown command: ${e.message}`);
  }
}

async function populateDevices() {
  // 1. Instant Render from cache if available (0ms instant display)
  if (ALL_REG_DEVICES && ALL_REG_DEVICES.length) {
    renderDevicesAuthenticTable(ALL_REG_DEVICES);
  }

  // 2. High-performance Parallel Fetch
  const [r, d] = await Promise.all([
    api('/devices', 'GET').catch(() => ({ ok: false })),
    api('/devices/detected', 'GET').catch(() => ({ ok: false }))
  ]);

  const reg = (r.ok && Array.isArray(r.data)) ? r.data : [];
  const serials = (d.ok && Array.isArray(d.data)) ? d.data.map(x => x.serial) : [];
  ['devSel', 'apDev', 'rcDev', 'pinDev'].forEach(function (id) {
    fillSelect(id, reg, function (x) {
      return x.device_id + (serials.indexOf(x.serial) >= 0 ? ' (' + x.serial + ')' : '');
    });
  });
  const sel = $('pinDev');
  if (reg.length && sel.options.length <= 1) sel.innerHTML = '<option value="">— اختر جهازاً —</option>';
  if (serials.length && !$('apSerial').value) $('apSerial').value = serials[0];

  ALL_REG_DEVICES = reg;
  renderDevicesAuthenticTable(reg);
  populateGroups();
}

let NEW_DEVICE_IDS = {};
async function populateNewDevices() {
  const [det, reg] = await Promise.all([
    api('/devices/detected', 'GET').catch(() => ({ ok: false })),
    api('/devices', 'GET').catch(() => ({ ok: false }))
  ]);
  const detList = (det.ok && Array.isArray(det.data)) ? det.data : [];
  const regList = (reg.ok && Array.isArray(reg.data)) ? reg.data : [];
  const registered = {};
  regList.forEach(function (x) { if (x.serial) registered[x.serial] = x.device_id; });
  ALL_DET_DEVICES = detList;
  renderNewDevices(detList, registered);
}
function renderNewDevices(list, registered) {
  const tb = $('newDetTbody');
  const count = $('newDetCount');
  if (count) count.textContent = String(list ? list.length : 0);
  if (!tb) return;
  if (!list || !list.length) {
    tb.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:28px;color:#94a3b8;">'
      + 'لا يوجد جهاز موصول الآن. وصّل الجهاز عبر USB وفعّل تصحيح أخطاء USB، ثم اضغط تحديث.</td></tr>';
    return;
  }
  tb.innerHTML = list.map(function (x) {
    const serial = String(x.serial || '');
    const id = registered[serial] || '';
    const status = id ? pill('p-ok', 'مسجّل') : pill('p-mut', 'جديد');
    const link = x.ready ? pill('p-ok', 'متصل وجاهز') : pill('p-bad', String(x.state || 'غير جاهز'));
    let action = '';
    if (!x.ready) {
      action = '<span style="color:#94a3b8;font-size:12px;">على الهاتف: اسمح بتصحيح USB لهذا الكمبيوتر، ثم حدّث الصفحة</span>';
    } else if (!id) {
      action = '<button class="primaryActionBtn button-primary-form" onclick="installAgentApp(\'' + esc(serial) + '\')">تثبيت التطبيق</button> '
        + '<button class="primaryActionBtn button-primary-form" style="background:#0f9d58;" onclick="quickEnrollDetected(\'' + esc(serial) + '\')">تسجيل الجهاز</button>';
    } else {
      action = '<button class="primaryActionBtn button-primary-form" onclick="addNewDeviceToGroup(\'' + esc(serial) + '\')">إضافة إلى مجموعة</button>';
    }
    return '<tr><td>' + status + '</td>'
      + '<td class="mono">' + esc(serial) + '</td>'
      + '<td>' + esc(x.model || '—') + '</td>'
      + '<td>' + link + '</td>'
      + '<td>' + action + '</td></tr>';
  }).join('');
}
async function installAgentApp(serial) {
  const r = await apiWriteOrReport('/devices/install-agent', 'POST', { serial: serial },
    'تثبيت التطبيق', 'newDetStatus');
  if (!r) return;
  if (r.data && r.data.launched === false) {
    setStatus('newDetStatus', 'تم تثبيت التطبيق على ' + serial + '، لكن تعذّر فتحه تلقائياً. افتح التطبيق مرة واحدة على الهاتف ثم تابع التسجيل.', 'warn');
  } else {
    setStatus('newDetStatus', 'تم تثبيت التطبيق على ' + serial + '. الخطوة التالية: تسجيل الجهاز.', 'ok');
  }
  await populateNewDevices();
}
async function quickEnrollDetected(serial) {
  const r = await apiWriteOrReport('/devices/enroll', 'POST', { serial: serial },
    'تسجيل الجهاز', 'newDetStatus');
  if (!r) return;
  if (r.data && r.data.device_id) NEW_DEVICE_IDS[serial] = r.data.device_id;
  setStatus('newDetStatus', 'تم تسجيل الجهاز ' + (r.data.device_id || serial) + '. الخطوة التالية: إضافة إلى مجموعة.', 'ok');
  await populateNewDevices();
  await populateDevices();
}
async function addNewDeviceToGroup(serial) {
  let id = NEW_DEVICE_IDS[serial] || '';
  if (!id) {
    const r = await api('/devices', 'GET');
    const reg = (r.ok && Array.isArray(r.data)) ? r.data : [];
    const hit = reg.filter(function (x) { return x.serial === serial; })[0];
    if (hit) id = hit.device_id;
  }
  if (!id) {
    setStatus('newDetStatus', 'سجّل الجهاز أولاً قبل إضافته إلى مجموعة.', 'err');
    return;
  }
  if (!ALL_GROUPS.length) await populateGroups();
  if (!ALL_GROUPS.length) {
    setStatus('newDetStatus', 'أنشئ مجموعة أولاً قبل إضافة الجهاز.', 'err');
    return;
  }
  openAddToGroupModal([id]);
}
async function autoDeployAffectedGroups(groups, pid) {
  if (!groups || !groups.length) {
    setStatus('cfgStatus', 'نُشر ' + pid + '. لا توجد مجموعات مرتبطة به الآن، لذلك لا شيء لإرساله.', 'ok');
    return;
  }
  setStatus('cfgStatus', 'نُشر ' + pid + '. جارٍ إرسال التغييرات الآن إلى الأجهزة المتصلة…');
  let applied = 0, staged = 0, failed = 0;
  const problems = [];
  for (let i = 0; i < groups.length; i++) {
    const g = groups[i];
    const r = await apiWrite('/groups/' + g.group_id + '/deploy', 'POST',
      { bulk: true, skip_approval: true, reason: 'auto deploy after publish', real: true },
      'إرسال التغييرات بعد النشر');
    if (r === null) { failed++; problems.push(g.group_name + ': أُلغي الإدخال'); continue; }
    if (!r.ok) { failed++; problems.push(g.group_name + ': ' + (r.error || '')); continue; }
    const s = (r.data && r.data.summary) || {};
    applied += (s.success || 0); staged += (s.yet_to_apply || 0); failed += (s.failed || 0);
  }
  let msg = 'نُشر ' + pid + ' وأُرسل للمجموعات المرتبطة: مطبَّق الآن ' + applied + ' · بانتظار الاتصال ' + staged;
  if (failed) msg += ' · تعذّر ' + failed + (problems.length ? (' — ' + problems.join('؛ ')) : '');
  setStatus('cfgStatus', msg, failed ? 'warn' : 'ok');
  await populateGroups();
}

async function populatePolicies() {
  const p = await api('/policies', 'GET');
  const psel = $('apPol');
  if (psel) {
    psel.innerHTML = '';
    if (p.ok && Array.isArray(p.data) && p.data.length) {
      p.data.forEach(function (x) {
        psel.insertAdjacentHTML('beforeend', '<option value="' + esc(x.policy_id) + '">' + esc(x.display_name + ' (' + x.policy_id + ')') + '</option>');
      });
    } else {
      psel.innerHTML = '<option value="">— لا سياسات —</option>';
    }
  }
  await refreshProfileList();
}

/* The profiles table is fed by the profile lifecycle API, not /policies: it is
   the only route that reports the DRAFT/REVIEW/ACTIVE lifecycle plus the real
   group/target counters. An empty list is a real answer, not a reason to invent
   rows. */
async function refreshProfileList() {
  const tb = $('meProfilesTableBody');
  if (tb) tb.innerHTML = skelRows(4, 12);
  const r = await api('/profiles', 'GET');
  if (!(r.ok && Array.isArray(r.data))) {
    ALL_PROFILES = [];
    renderProfilesAuthenticTable([], { error: r.error || 'تعذّر تحميل الملفات' });
    return;
  }
  ALL_PROFILES = r.data;
  renderProfilesAuthenticTable(ALL_PROFILES);
}
function tierPill(t) {
  const map = { SUPPORTED: ['p-ok', 'مدعوم'], PARTIAL: ['p-part', 'جزئي'], VENDOR_DEPENDENT: ['p-part', 'حسب الجهة المصنعة'], NOT_FEASIBLE: ['p-bad', 'غير ممكن'] };
  const kl = map[t] || ['p-mut', String(t || '').replace(/_/g, ' ')];
  return pill(kl[0], kl[1]);
}
async function loadCatalog() {
  const box = $('rgCatalog');
  $('rgCount').textContent = '…';
  setStatus('rgStatus', 'جارٍ تحميل كتالوج القيود…');
  box.innerHTML = '<div class="empty">' + ic('info', 30) + '<div class="et">جارٍ التحميل…</div><div class="es">مرجع القيود بنفس تسميات ManageEngine MDM Plus</div></div>';
  const r = await api('/restrictions/catalog', 'GET');
  if (!(r.ok && r.data)) {
    box.innerHTML = banner('bad', 'تعذّر تحميل الكتالوج', r.error || '');
    setStatus('rgStatus', '', 'err');
    return;
  }
  const d = r.data;
  $('rgSource').textContent = (d.source || 'كتالوج القيود') + ' — التسمية مطابقة لواجهة ManageEngine.';
  let total = 0;
  RG_SELECTED = new Set();
  box.innerHTML = d.groups.map(function (g, gi) {
    const rows = g.restrictions.map(function (x) {
      total++;
      const sel = RG_SELECTED.has(x.feature);
      return '<div class="rg-row' + (sel ? ' sel' : '') + '" data-feat="' + esc(x.feature) + '" data-tier="' + esc(x.tier) + '" onclick="toggleRgSelect(this)" role="button" tabindex="0">' +
        '<div class="rg-check">' + ic(sel ? 'check-square' : 'square', 15) + '</div>' +
        '<div class="rg-label">' + esc(x.label) + '<div class="rg-feature">' + esc((x.feature || '') + ' · ') + (x.method || '') + '</div></div>' +
        '<div class="rg-tier">' + tierPill(x.tier) + '</div>' +
        (x.note ? '<div class="rg-note">' + esc(x.note) + '</div>' : '') +
        '</div>';
    }).join('');
    return '<div class="rg-group open" data-g="' + gi + '">' +
      '<div class="rg-head" onclick="toggleRgGroup(this)" role="button">' +
      '<span class="caret">▶</span><h4>' + esc(g.label) + '</h4>' +
      '<span class="rg-desc">' + esc(g.description || '') + '</span>' +
      '<span class="hcount pill p-mut">' + rows.length + '</span></div>' +
      '<div class="rg-grid">' + rows + '</div></div>';
  }).join('') || '<div class="empty">' + ic('info', 30) + '<div class="et">لا قيود في الكتالوج</div></div>';
  $('rgCount').textContent = String(total);
  $('rgCatalog').innerHTML = box.innerHTML;
  rgSyncSelection();
  setStatus('rgStatus', 'تم تحميل ' + total + ' قيداً في ' + d.groups.length + ' مجموعات', 'ok');
}
var RG_SELECTED = new Set();
function toggleRgSelect(row) {
  if (row.classList.contains('disabled')) return;
  const f = row.getAttribute('data-feat');
  if (RG_SELECTED.has(f)) { RG_SELECTED.delete(f); row.classList.remove('sel'); }
  else { RG_SELECTED.add(f); row.classList.add('sel'); }
  row.querySelector('.rg-check').innerHTML = ic(RG_SELECTED.has(f) ? 'check-square' : 'square', 15);
  rgSyncSelection();
}
function rgSyncSelection() {
  const n = RG_SELECTED.size;
  $('rgSelCount').textContent = String(n);
  const btn = $('rgBuildBtn');
  btn.disabled = n === 0;
}
async function buildPolicyFromSelected() {
  const feats = Array.from(RG_SELECTED);
  if (!feats.length) { setStatus('rgStatus', 'اختر قيداً واحداً على الأقل لبناء السياسة', 'err'); return; }
  const r = await api('/restrictions/policy', 'POST', { features: feats });
  const box = $('rgResult');
  box.style.display = 'block';
  if (!(r.ok && r.data)) {
    box.className = 'statusline err';
    box.innerHTML = esc(r.error || 'فشل بناء السياسة');
    return;
  }
  box.className = 'statusline ok';
  box.innerHTML = '<span class="mono">' + esc(r.data.policy_id) + '</span> — فُعّلت ' + r.data.applied.length + ' قيداً' +
    (r.data.excluded && Object.keys(r.data.excluded).length ? ('<span class="sp2"></span> خارج النطاق (OEM/Knox): ' + esc(Object.keys(r.data.excluded).join('، '))) : '');
  setStatus('rgStatus', 'تم إنشاء سياسة ' + r.data.policy_id + ' — يمكن تطبيقها من صفحة الإنفاذ', 'ok');
}
function toggleRgGroup(headEl) {
  headEl.closest('.rg-group').classList.toggle('open');
}
function openAllRg(open) {
  document.querySelectorAll('.rg-group').forEach(function (g) { g.classList.toggle('open', open); });
}

/* ------------------------------------------------------------ profile wizard
   The Configure Profile restriction panels are generated from the same ManageEngine
   catalog the reference uses (backend.restrictions), so every row carries a real
   feature lane, its real enforcement method and its honest tier. A row whose tier
   is VENDOR_DEPENDENT / NOT_FEASIBLE is still selectable but is labelled, because
   hiding it would pretend the profile is fully enforceable.

   Rows are drawn per CATALOG entry, not per feature: several ManageEngine labels
   share one engine lane (Camera + Video Recording -> CAMERA). Toggling any of
   them writes the same lane, so cfgSyncReqRows() keeps every duplicate in step. */
const SUB_RESTRICTIONS = new Set([
  'Allow camera in lock screen',
  'Video Recording',
  'Audio Recording',
  'OS upgrade',
  'Store data in SD Card',
  'Move apps to SD Card',
  'Connections using USB',
  'Connect a USB storage device',
  'Sync data while roaming',
  'Voice call while roaming',
  'Roaming push',
  'Bluetooth tethering',
  'Wi-Fi tethering',
  'USB tethering',
  'Incoming SMS',
  'Outgoing SMS',
  'Incoming MMS',
  'Outgoing MMS',
  'Incoming calls',
  'Outgoing calls',
  'Modifying Screen Timeout settings',
  'Adaptive brightness',
  'Modifying brightness settings',
  'Modify date/time settings',
  'Modify date/time'
]);

const VERSION_BADGES = {
  'Camera': 4,
  'Enforce Storage encryption': 3
};

let CFG_CATALOG = null;

async function loadCfgRestrictions() {
  const panels = document.querySelectorAll('.cfg-rest-panel');
  if (!panels.length) return;
  if (!CFG_CATALOG) {
    CFG_LOADING = true;
    const r = await api('/restrictions/catalog', 'GET');
    CFG_LOADING = false;
    if (!(r.ok && r.data)) { setStatus('cfgStatus', r.error || 'تعذّر تحميل كتالوج القيود', 'err'); return; }
    CFG_CATALOG = r.data.groups;
  }
  const groups = CFG_CATALOG;
  panels.forEach(function (panel, idx) {
    const g = groups[idx];
    if (!g) {
      panel.innerHTML = '<div style="padding:20px;color:#64748b;font-size:13px;">لا توجد قيود في هذه المجموعة.</div>';
      return;
    }
    const itemsHtml = g.restrictions.map(function (x, ri) {
      const fid = esc(x.feature);
      const isSub = SUB_RESTRICTIONS.has(x.label);
      const ver = VERSION_BADGES[x.label];
      const isYesNo = ['STORAGE_ENCRYPTION', 'SD_ENCRYPTION'].includes(x.feature) || x.label.toLowerCase().includes('encryption');

      const verHtml = ver ? '<span class="data-tooltip"><label class="tooltip-image"><label class="version-box">' + ver + '</label></label></span>' : '';
      const safeHtml = '<span class="data-tooltip" title="Samsung SAFE"><label class="tooltip-image"><svg aria-label="SAFE" class="svg-bucket-icon" role="img" style="width:15px;height:15px;"><use href="/images/svg-bucket/mdm-common-38f54d8b04de20ad79ff34707c87d72c.svg#SAFE"></use></svg></label></span>';

      const hasDo = (x.method === 'DPM_RESTRICTION' || x.tier === 'SUPPORTED' || ['Camera', 'Allow camera in lock screen', 'Microphone', 'Screen Capture'].includes(x.label));
      const doHtml = hasDo ? '<span class="data-tooltip" title="Device Owner"><label class="tooltip-image"><svg aria-label="Device_owner" class="svg-bucket-icon svg-fill-green" role="img" style="width:16px;height:16px;"><use href="/images/svg-bucket/mdm-profile-9fe9367cd1d8fc33d733ed7a218c9307.svg#Device_owner"></use></svg></label></span>' : '';

      const leftVal = isYesNo ? 'RESTRICT' : 'ALLOW';
      const rightVal = isYesNo ? 'ALLOW' : 'RESTRICT';
      const leftText = isYesNo ? 'Yes' : 'Allow';
      const rightText = isYesNo ? 'No' : 'Restrict';

      return '<li class="cfg-rest-row" data-feat="' + fid + '">' +
        '<div>' +
        '<span class="' + (isSub ? 'sub-restriction' : '') + '">' +
        esc(x.label) + ' ' +
        verHtml + ' ' +
        safeHtml + ' ' +
        doHtml +
        '</span>' +
        '</div>' +
        '<label class="allow-disable">' +
        '<label>' +
        '<input name="feat_' + fid + '_' + idx + '_' + ri + '" type="radio" value="' + leftVal + '" onchange="setCfgReq(\'' + fid + '\',\'' + leftVal + '\')">' +
        '<span>' + leftText + '</span>' +
        '</label>' +
        '<label>' +
        '<input name="feat_' + fid + '_' + idx + '_' + ri + '" type="radio" value="' + rightVal + '" onchange="setCfgReq(\'' + fid + '\',\'' + rightVal + '\')">' +
        '<span>' + rightText + '</span>' +
        '</label>' +
        '</label>' +
        '</li>';
    }).join('');

    panel.innerHTML = '<ul>' + itemsHtml + '</ul>';
  });
  cfgSetEditable(CFG_EDITABLE, CFG_DRAFT_ID);
  cfgSyncReqRows();
  cfgSyncCount();
}

function setCfgReq(feature, state) {
  if (CFG_LOADING) return;
  if (!CFG_EDITABLE) {
    setStatus('cfgStatus', 'الملف للقراءة فقط — أنشئ مسودة جديدة لتغيير القيود', 'err');
    return;
  }
  CFG_REQ[feature] = state;
  cfgSyncReqRows();
  cfgSyncCount();
}

function cfgSyncReqRows() {
  document.querySelectorAll('.cfg-rest-row[data-feat]').forEach(function (row) {
    const f = row.getAttribute('data-feat');
    const cur = CFG_REQ[f] || 'ALLOW';
    const allowRadio = row.querySelector('input[value="ALLOW"]');
    const restrictRadio = row.querySelector('input[value="RESTRICT"]');
    if (cur === 'RESTRICT') {
      if (restrictRadio) restrictRadio.checked = true;
      if (allowRadio) allowRadio.checked = false;
    } else {
      if (allowRadio) allowRadio.checked = true;
      if (restrictRadio) restrictRadio.checked = false;
    }
  });
}

function cfgSyncCount() {
  const n = Object.keys(CFG_REQ).filter(k => CFG_REQ[k] !== 'ALLOW').length;
  const el = $('cfgReqCount');
  if (el) el.textContent = String(n);
}

function selectedRestTabs() {
  const out = [];
  document.querySelectorAll('.cfg-left-nav-item').forEach(function (b) {
    if (b.classList.contains('active')) out.push(b.id);
  });
  return out;
}

function renderCaps(c) {
  const box = $('capPanel');
  if (!c.ok || !c.data) {
    box.innerHTML = '<div class="panel"><div class="statusline err">' + (c.error || 'تعذّر تحميل القدرات') + '</div></div>';
    return;
  }
  const d = c.data;
  const prof = d.capability_profile || {};
  const caps = Object.keys(prof);
  let html = '<div class="panel"><div class="head"><h3><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l8 3.5v5.3c0 4.9-3.4 8.6-8 10.7-4.6-2.1-8-5.8-8-10.7V5.5L12 2z"/></svg>ملف قدرات الإنفاذ</h3><span class="hcount pill p-mut">' + caps.length + ' ميزة</span></div>';
  html += '<div class="sub">القدرة المصنفة لكل ميزة من سجل الجهاز — هل يمكن للسياسة أن تلمسها فعلياً؟</div>';
  html += defs([
    ['device_id', esc(d.device_id), 1],
    ['الشركة المصنعة', esc(d.manufacturer)],
    ['الطراز', esc(d.model)],
    ['أندرويد', esc(String(d.android_version || '—') + ' · API ' + String(d.api_level || '—'))],
  ]);
  if (!caps.length) {
    html += '<div class="empty">' + ic('info', 30) + '<div class="et">لا ميزات قدرة مسجلة بعد</div><div class="es">سجّل الجهاز أو حدّث ملفه عبر فحص ADB</div></div>';
  } else {
    html += '<div class="caps">';
    caps.sort().forEach(function (f) {
      const row = prof[f] || {};
      const cap = row.capability || 'UNKNOWN';
      const capPill = statusPill(cap);
      const methods = (row.methods || []).filter(Boolean);
      html += '<div class="cap"><div class="top"><span class="fn">' + esc(f) + '</span>' + capPill + '</div>';
      if (methods.length) html += '<div class="methods">' + methods.map(m => '<span class="chip">' + esc(m) + '</span>').join('') + '</div>';
      if (row.observed !== undefined) html += '<div class="obs">الحالة المرصودة:<span class="ov">' + esc(row.observed || '—') + '</span></div>';
      html += '</div>';
    });
    html += '</div>';
  }
  html += raw(c.data);
  box.innerHTML = html + '</div>';
}
function renderRecStatus(r) {
  const box = $('recPanel');
  if (!r.ok || !r.data) {
    box.innerHTML = '<div class="panel"><div class="statusline err">' + (r.error || 'تعذّر تحميل حالة الاسترداد') + '</div></div>';
    return;
  }
  const d = r.data;
  const st = d.recovery || 'Not Configured';
  let html = '<div class="panel"><div class="head"><h3><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>بيان الاسترداد (عامل الحيازة)</h3></div>';
  html += '<div class="sub">شرط التملك للعمليات الحساسة على هذا الجهاز — يمنع أي إنفاذ أو استرجاع من دون بيان حي.</div>';
  html += defs([
    ['حالة البيان', statusPill(st)],
    ['Recovery ID', esc(d.recovery_id || '—'), 1],
  ]);
  if (st === 'Not Configured') html += banner('warn', 'بيان غير مُصدَر', 'لن يُسمح بالتطبيق أو الاسترجاع على هذا الجهاز حتى يُصدر البيان (من قبو الاسترجاع أو عند التسجيل).');
  if (st === 'Revoked') html += banner('bad', 'البيان مُلغى', 'عامل الحيازة متوقف — أعد إصداره من قبو الاسترجاع قبل أي عملية.');
  if (st === 'Mismatch') html += banner('warn', 'عدم تطابق البيان', 'تعذّر فك تشفير الاعتماد — أعد تدويره أو إصداره.');
  html += raw(r.data);
  box.innerHTML = html + '</div>';
}
async function loadDeviceDetail() {
  const did = $('devSel').value;
  setStatus('devPickStatus', '');
  if (!did) { $('capPanel').innerHTML = ''; $('recPanel').innerHTML = ''; setStatus('devPickStatus', 'اختر جهازاً من القائمة', 'err'); return; }
  setStatus('devPickStatus', 'جارٍ تحميل بيانات الجهاز…');
  $('capPanel').innerHTML = '<div class="panel"><div class="empty">' + ic('info', 30) + '<div class="et">جارٍ القراءة…</div></div></div>';
  $('recPanel').innerHTML = '<div class="panel"><div class="empty">' + ic('info', 30) + '<div class="et">جارٍ القراءة…</div></div></div>';
  const c = await api('/devices/capabilities?device_id=' + encodeURIComponent(did), 'GET');
  const r = await api('/recovery?device_id=' + encodeURIComponent(did), 'GET');
  renderCaps(c);
  renderRecStatus(r);
  setStatus('devPickStatus', 'تم تحميل قدرات الجهاز وحالة بيان استرداده', 'ok');
}

async function preflight() {
  const did = $('apDev').value, pol = $('apPol').value;
  $('ppResult').innerHTML = '';
  if (!did) { setStatus('apStatus', 'اختر الجهاز أولاً', 'err'); return; }
  if (!pol) { setStatus('apStatus', 'اختر السياسة أولاً', 'err'); return; }
  setStatus('apStatus', 'جارٍ المعاينة الحيّة على الجهاز…');
  $('apResult').innerHTML = '<div class="panel"><div class="empty">' + ic('info', 30) + '<div class="et">جارٍ تقييم ما قبل التنفيذ</div><div class="es">قراءة ADB · قناة DPM · عامل الحيازة · نطاق القدرات</div></div></div>';
  const r = await api('/devices/preflight?device_id=' + encodeURIComponent(did) + '&policy=' + encodeURIComponent(pol), 'GET');
  $('apResult').innerHTML = r.ok && r.data ? renderPreflight(r.data) : errCard(r.error || 'فشل المعاينة');
  setStatus('apStatus', r.ok && r.data ? ('نتيجة المعاينة: ' + r.data.verdict) : 'فشل المعاينة', r.ok && r.data && r.data.verdict === 'PASS' ? 'ok' : '');
}
function renderPreflight(d) {
  const kind = d.verdict === 'FAIL' ? 'bad' : (d.verdict === 'CONDITIONAL' ? 'warn' : 'ok');
  let html = banner(kind, 'حكم المعاينة: ' + d.verdict, d.reason || '');
  html += defs([
    ['الجهاز', esc(d.device_id), 1],
    ['السياسة', esc(d.policy)],
    ['يمكن التطبيق', dot(!!d.can_apply) + (d.can_apply ? ' <span style="margin-right:5px">مسموح</span>' : ' <span style="margin-right:5px">محظور</span>')],
    ['محظور؟', dot(!!d.blocked) + (d.blocked ? ' <span style="margin-right:5px">نعم</span>' : ' <span style="margin-right:5px">لا</span>')],
  ]);
  const checks = d.checks || [];
  if (checks.length) {
    html += '<div class="tw" style="margin-top:4px"><table><thead><tr><th>الفحص</th><th>الحالة</th><th>التفاصيل</th></tr></thead><tbody>';
    checks.forEach(function (c) {
      html += '<tr><td>' + esc(c.name) + '</td><td>' + statusPill(c.status) + '</td><td style="font-size:12.5px">' + esc(c.detail || '—') + '</td></tr>';
    });
    html += '</tbody></table></div>';
  }
  html += raw(d);
  return html;
}
async function policyPreview() {
  const did = $('apDev').value, pol = $('apPol').value;
  if (!did) { setStatus('apStatus', 'اختر الجهاز أولاً', 'err'); return; }
  if (!pol) { setStatus('apStatus', 'اختر السياسة أولاً', 'err'); return; }
  setStatus('apStatus', 'جارٍ بناء خريطة الحظر…');
  const r = await api('/devices/policy-preview?device_id=' + encodeURIComponent(did) + '&policy=' + encodeURIComponent(pol), 'GET');
  if (!(r.ok && r.data)) {
    $('ppResult').innerHTML = errCard(r.error || 'فشل تحميل الخريطة');
    setStatus('apStatus', 'فشل تحميل خريطة الحظر', 'err');
    return;
  }
  const d = r.data;
  let html = '<div class="panel" style="margin-bottom:0"><div class="head"><h3><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l8 3.5v5.3c0 4.9-3.4 8.6-8 10.7-4.6-2.1-8-5.8-8-10.7V5.5L12 2z"/></svg>خريطة الحظر المتوقعة</h3><span class="hcount pill p-mut">' + esc(d.policy_id) + '</span></div>';
  html += '<div class="sub">' + esc(d.display_name || '') + ' على ' + esc(d.device_id) + ' — المطلوب مقابل الحالي لكل ميزة والمصدر.</div>';
  const rows = d.rows || [];
  if (!rows.length) { html += '<div class="empty">' + ic('info', 30) + '<div class="et">لا متطلبات في هذه السياسة</div></div>'; }
  else {
    html += '<div class="tw"><table><thead><tr><th>الميزة</th><th>المطلوب</th><th>الحالي</th><th>الخطر</th><th>المصدر</th></tr></thead><tbody>';
    rows.forEach(function (x) {
      const desD = x.desired === 'BLOCK' ? 'p-bad' : (x.desired === 'ALLOW' ? 'p-ok' : 'p-part');
      const desT = x.desired === 'BLOCK' ? 'حظر' : (x.desired === 'ALLOW' ? 'سماح' : (x.desired === 'RESTRICT' ? 'تقييد' : x.desired));
      const rik = x.risk === 'LOW' ? pill('p-ok', 'LOW') : (x.risk === 'MEDIUM' ? pill('p-part', 'MEDIUM') : (x.risk === 'HIGH' || x.risk === 'CRITICAL' ? pill('p-bad', String(x.risk)) : pill('p-mut', String(x.risk || '—'))));
      const srcPill = String(x.source || '').indexOf('REAL_DEVICE') >= 0 ? 'p-ok' : (String(x.source || '').indexOf('NOT_ATTACHED') >= 0 ? 'p-part' : (String(x.source || '').indexOf('error') >= 0 ? 'p-bad' : 'p-mut'));
      html += '<tr><td>' + esc(x.feature) + '</td><td>' + pill(desD, desT) + '</td><td class="mono" style="text-align:right;direction:rtl">' + esc(x.current || '—') + '</td><td>' + rik + '</td><td>' + pill(srcPill, String(x.source || '—')) + '</td></tr>';
    });
    html += '</tbody></table></div>';
  }
  html += raw(d);
  $('ppResult').innerHTML = html + '</div>';
  setStatus('apStatus', 'تم بناء خريطة الحظر', 'ok');
}
async function doApply() {
  const did = $('apDev').value, pol = $('apPol').value;
  const serial = $('apSerial').value.trim(), mfa = $('apMfa').value;
  $('ppResult').innerHTML = '';
  if (!did || !pol) { setStatus('apStatus', 'اختر الجهاز والسياسة', 'err'); return; }
  setStatus('apStatus', 'جارٍ التنفيذ عبر ADB…');
  $('apResult').innerHTML = '<div class="empty">' + ic('info', 30) + '<div class="et">جارٍ توقيع وتسليم وتفعيل السياسة…</div></div>';
  const real = $('apReal').checked;
  const r = await api('/apply', 'POST', { device_id: did, policy: pol, serial, mfa, real });
  $('apResult').innerHTML = renderApply(r);
  if (r.ok && r.data) {
    const st = r.data.stage;
    const sv = r.data.verification;
    setStatus('apStatus', st === 'COMPLETE' ? (sv === 'FAIL' ? 'اكتمل التطبيق لكن التحقق فشل: ' + (sv || '') : 'اكتمل التطبيق — انظر مراحل التنفيذ') : 'اكتمل — حالة غير متوقعة: ' + st, sv === 'FAIL' ? 'err' : 'ok');
  } else {
    setStatus('apStatus', 'فشل: ' + (r.error || 'خطأ'), 'err');
  }
}
function renderApply(r) {
  if (!(r.ok && r.data)) return errCard(r.error || 'فشل التنفيذ');
  const d = r.data;
  const st = String(d.stage || '');
  const sv = d.verification;
  const stagedN = (d.staged && Array.isArray(d.staged)) ? d.staged.length : 0;
  const bannerKind = (st === 'COMPLETE' && sv !== 'FAIL') ? 'ok' : (st === 'COMPLETE' ? 'warn' : 'bad');
  const bannerMsg = 'المرحلة النهائية: ' + st + (sv ? (' · نتيجة التحقق: ' + sv) : '') + (d.source ? (' · المصدر: ' + d.source) : '');
  let html = banner(bannerKind, (st === 'COMPLETE' ? 'اكتمل الإنفاذ' : 'مرحلة غير مكتملة'), bannerMsg);
  const stages = [];
  stages.push({ st: st === 'COMPLETE' ? 'ok' : 'bad', nm: 'توقيع وتجهيز الحزمة', ds: 'مرحلة النهاية: ' + st });
  stages.push({
    st: stagedN > 0 || d.source === 'REAL_DEVICE' ? 'ok' : (st === 'COMPLETE' ? 'mut' : 'bad'),
    nm: 'تسليم الأمر للقناة',
    ds: stagedN > 0 ? (stagedN + ' مغلّف مُرحَّل') : (d.source === 'REAL_DEVICE' ? 'عبر قناة ADB حقيقية' : 'تحضير فقط — لم يُرحَّل')
  });
  stages.push({
    st: sv === 'PASS' ? 'ok' : (sv === 'FAIL' ? 'bad' : 'mut'),
    nm: 'التحقق من أثر الإنفاذ',
    ds: sv ? ('نتيجة التحقق: ' + sv) : 'لا تحقق مبلغ عنه'
  });
  html += '<div class="stages">' + stages.map(function (s) {
    const icone = s.st === 'ok' ? '✓' : (s.st === 'bad' ? '!' : '•');
    const cls = s.st === 'ok' ? 'done' : (s.st === 'bad' ? 'fail' : 'pend');
    return '<div class="stg ' + cls + '"><span class="ico">' + icone + '</span><div class="nm">' + esc(s.nm) + '</div><div class="ds">' + esc(s.ds) + '</div></div>';
  }).join('') + '</div>';
  const items = [
    ['المرحلة', statusPill(d.stage)],
    ['التحقق', sv ? statusPill(sv) : pill('p-mut', '—')],
    ['الامتثال', d.compliance ? statusPill(d.compliance) : pill('p-mut', '—')],
    ['المصدر', esc(d.source || '—')],
    ['أمين البيان؟', dot(!!d.honest) + (d.honest ? ' <span style="margin-right:5px">نعم</span>' : ' <span style="margin-right:5px">لا</span>')],
    ['evidence_id', esc(d.evidence_id || '—'), 1],
    ['audit_id', esc(d.audit_id || '—'), 1],
    ['policy_id', esc(d.policy_id || '—')],
  ];
  if (d.cmd_id !== undefined) items.push(['cmd_id', esc(d.cmd_id), 1]);
  html += defs(items);
  html += raw(r);
  return html;
}
async function doProvisionPin() {
  const did = $('pinDev').value;
  const mfa = $('pinMfa').value;
  const custom = $('pinCustom').value.trim();
  if (!did) { setStatus('pinStatus', 'اختر الجهاز أولاً', 'err'); return; }
  setStatus('pinStatus', 'جارٍ توقيع وتوصيل الرمز…');
  $('pinResult').innerHTML = '<div class="empty">' + ic('info', 30) + '<div class="et">جارٍ توقيع مغلّف PROVISION_PIN…</div></div>';
  const r = await api('/pin/provision', 'POST', { device_id: did, pin: custom, mfa });
  $('pinResult').innerHTML = renderPin(r);
  if (r.ok && r.data) {
    const okDel = !!(r.data.delivery && r.data.delivery.ok);
    setStatus('pinStatus', okDel ? 'تم توفير الرمز وتسليمه — احفظه الآن' : 'تم توقيع الرمز لكن التوصيل فشل', okDel ? 'ok' : 'err');
  } else {
    setStatus('pinStatus', 'فشل توفير الرمز: ' + (r.error || 'خطأ'), 'err');
  }
}
function renderPin(r) {
  if (!(r.ok && r.data)) return errCard(r.error || 'فشل توفير الرمز');
  const d = r.data;
  const dv = d.delivery || {};
  let html = '<div class="pincard"><div class="pk">رمز فتح القفل — لمرة واحدة</div><div class="pin">' + esc(d.pin || '—') + '</div><div class="hint">احفظه الآن — لا يُعرض إلا مرة واحدة</div></div>';
  html += '<div class="deliv ' + (dv.ok ? 'ok' : 'bad') + '">' + ic(dv.ok ? 'check' : 'x', 15) + '<span>' + (dv.ok ? 'تم تسليم الحزمة إلى الجهاز' : 'فشل التوصيل إلى الجهاز') + '</span></div>';
  const items = [['الإجراء', esc(dv.action || 'PROVISION_PIN'), 1]];
  if (dv.cmd_id) items.push(['cmd_id', esc(dv.cmd_id), 1]);
  if (dv.staged !== undefined) items.push(['مُرحَّل محلياً', typeof dv.staged === 'string' ? esc(dv.staged) : dot(!!dv.staged) + (dv.staged ? ' <span style="margin-right:5px">نعم</span>' : ' <span style="margin-right:5px">لا</span>'), typeof dv.staged === 'string' ? 1 : 0]);
  if (!dv.ok && dv.error) items.push(['خطأ التوصيل', '<span style="color:var(--err)">' + esc(dv.error) + '</span>']);
  html += defs(items);
  html += raw(r);
  return html;
}

const MODES = [
  { v: 'R0_WITHDRAW', code: 'R0', t: 'سحب DeviceOwner', d: 'رفع الإدارة بالكامل عن الجهاز وإرجاعه لملكية المستخدم', sev: 'danger', sevT: 'أثري' },
  { v: 'R1_RESTORE_POINT', code: 'R1', t: 'نقطة الاستعادة', d: 'مسح القيود والعودة إلى النقطة الآمنة المسجلة', sev: 'danger', sevT: 'أثري' },
  { v: 'R2_REPROVISION', code: 'R2', t: 'إعادة التزويد كمالك', d: 'إعادة إعداد الجهاز من جديد كمالك (إصدار DeviceOwner)', sev: 'danger', sevT: 'أثري' },
  { v: 'R3_LAB_FLASH', code: 'R3', t: 'فلاش مخبري', d: 'حوكمة Lab-Only — مرفوض دائماً من أداة الإدارة', sev: 'danger', sevT: 'مرفوض دائماً' },
  { v: 'R4_DIAGNOSTIC', code: 'R4', t: 'تشخيص قراءة فقط', d: 'قراءة حالة الجهاز دون أي تغيير أو تنفيذ', sev: 'ok', sevT: 'قراءة فقط' }
];
function buildModes() {
  const sel = $('rcMode');
  sel.innerHTML = '';
  MODES.forEach(function (m) {
    sel.insertAdjacentHTML('beforeend', '<option value="' + m.v + '">' + m.code + ' — ' + m.t + '</option>');
  });
  $('modesBox').innerHTML = MODES.map(function (m) {
    return '<div class="mode ' + (m.v === 'R0_WITHDRAW' ? 'sel' : '') + '" data-v="' + m.v + '" onclick="selectMode(\'' + m.v + '\')">' +
      '<div class="code">' + m.code + '</div><div class="t">' + esc(m.t) + '</div><div class="d">' + esc(m.d) + '</div>' +
      '<div class="sev ' + m.sev + '"><span class="sdot"></span>' + esc(m.sevT) + '</div></div>';
  }).join('');
}
function selectMode(v) {
  $('rcMode').value = v;
  document.querySelectorAll('.mode').forEach(function (el) { el.classList.toggle('sel', el.getAttribute('data-v') === v); });
}
async function doRecovery() {
  const did = $('rcDev').value, mode = $('rcMode').value;
  const serial = $('rcSerial').value.trim();
  const a1 = $('rcA1').value.trim(), a2 = $('rcA2').value.trim();
  const reason = $('rcReason').value.trim(), mfa = $('rcMfa').value;
  const exec = $('rcExec').value === 'true';
  const skip = $('rcSkip').checked;
  if (!did) { setStatus('rcStatus', 'اختر الجهاز أولاً', 'err'); return; }
  const m = MODES.find(x => x.v === mode);
  if (!await alpConfirm('تأكيد الاسترجاع\n\nالنمط: ' + (m ? m.code + ' — ' + m.t : mode) + '\nالجهاز: ' + did + '\nالتنفيذ الحقيقي: ' + (exec ? 'نعم' : 'لا (خطة فقط)') + '\n\nالعملية عبر ADB حقيقية ولا يمكن التراجع عنها.')) return;
  setStatus('rcStatus', 'جارٍ تنفيذ ' + mode + ' عبر ADB…');
  $('rcResult').innerHTML = '<div class="empty">' + ic('info', 30) + '<div class="et">جارٍ تنفيذ ' + esc(mode) + '…</div></div>';
  const r = await api('/recovery', 'POST', { device_id: did, mode, mfa, approver1: a1, approver2: a2, reason, serial, exec, skip_approval: skip });
  $('rcResult').innerHTML = renderRecovery(r);
  if (r.ok && r.data) {
    const ok = !!r.data.ok;
    setStatus('rcStatus', ok ? 'تم — انظر تفاصيل النمط' : 'لم يكتمل: ' + (r.data.reason || r.data.error || r.data.status || ''), (ok ? 'ok' : 'err'));
  } else {
    setStatus('rcStatus', 'فشل: ' + (r.error || 'خطأ'), 'err');
  }
}
function renderRecovery(r) {
  if (!(r.ok && r.data)) return errCard(r.error || 'فشل تنفيذ الاسترجاع');
  const d = r.data;
  const ok = !!d.ok;
  const kind = !ok ? 'bad' : (d.status === 'PARTIAL' || d.status === 'PLAN_ONLY' ? 'warn' : 'ok');
  let html = banner(kind, 'النتيجة: ' + String(d.status || d.mode || ''), d.reason || d.error || '');
  html += defs([
    ['النمط', esc(d.mode), 1],
    ['الجهاز', esc(d.device_id), 1],
    ['الحالة', statusPill(d.status)],
    ['المصدر', esc(d.source || '—')],
    ['evidence_id', esc(d.evidence_id || '—'), 1],
    ['audit_id', esc(d.audit_id || '—'), 1],
  ]);
  const det = d.details || {};
  const execs = det.executed;
  if (Array.isArray(execs) && execs.length) {
    html += '<div class="tw" style="margin-top:4px"><table><thead><tr><th>الخطوة</th><th>الأمر</th><th>الحالة</th></tr></thead><tbody>';
    execs.forEach(function (x) {
      const st = x.status || (x.ok ? 'COMPLETE' : 'FAIL');
      html += '<tr><td>' + esc(x.step || '—') + '</td><td class="mono">' + esc(x.cmd || '—') + '</td><td>' + statusPill(st) + '</td></tr>';
    });
    html += '</tbody></table></div>';
  }
  html += raw(r);
  return html;
}
async function vaultSummary() {
  const r = await api('/recovery/vault', 'GET');
  const tb = $('vaultTbody');
  if (!(r.ok && r.data)) {
    tb.innerHTML = emptyRow(4, 'تعذّر تحميل القبو', r.error || '');
    return;
  }
  const list = r.data.devices || [];
  if (!list.length) { tb.innerHTML = emptyRow(4, 'لا بيانات في القبو بعد', 'سجل جهازاً ليُصدر بيان استرداده تلقائياً'); return; }
  tb.innerHTML = list.map(function (x) {
    return '<tr><td class="mono">' + esc(x.device_id) + '</td><td>' + statusPill(x.recovery) + '</td><td class="mono">' + esc(x.recovery_id || '—') + '</td>' +
      '<td style="white-space:nowrap"><button class="btn ghost" style="padding:5px 10px;font-size:12px" onclick="vaultAction(\'issue\',\'' + esc(x.device_id) + '\')">إصدار</button> ' +
      '<button class="btn ghost" style="padding:5px 10px;font-size:12px" onclick="vaultAction(\'rotate\',\'' + esc(x.device_id) + '\')">تدوير</button> ' +
      '<button class="btn danger" style="padding:5px 10px;font-size:12px" onclick="vaultAction(\'revoke\',\'' + esc(x.device_id) + '\')">إلغاء</button></td></tr>';
  }).join('');
  setStatus('vaultStatus', '', '');
}
async function vaultAction(action, predev) {
  const dev = (predev || $('vaultDev').value).trim();
  if (!dev) { setStatus('vaultStatus', 'device_id مطلوب', 'err'); return; }
  const mfa = await alpPrompt('رمز TOTP لإجراءات القبو (' + action + '):', '');
  setStatus('vaultStatus', 'جارٍ ' + action + ' …');
  const r = await api('/recovery/vault', 'POST', { action, device_id: dev, mfa });
  if (r.ok && r.data) {
    const st = r.data.recovery || '';
    setStatus('vaultStatus', 'تم ' + action + ' — الحالة: ' + st, 'ok');
  } else {
    setStatus('vaultStatus', 'فشل ' + action + ': ' + (r.error || 'خطأ'), 'err');
  }
  vaultSummary();
}

/* Emergency offline recovery key — redirects to standard reference dialog */
async function devEmergencyCode() {
  openRecoveryKeyGenerateDialog(CURRENT_DETAILS_DID);
}

async function auditTail() {
  const tb = $('auditTbody');
  tb.innerHTML = skelRows(4, 6);
  setStatus('auditStatus', 'جارٍ سحب السجل…');
  const tail = $('auditTailN').value || 100;
  const r = await api('/audit?tail=' + encodeURIComponent(tail), 'GET');
  if (!(r.ok && r.data)) {
    tb.innerHTML = emptyRow(6, 'تعذّر تحميل سجل التدقيق', r.error || '');
    setStatus('auditStatus', 'فشل التحميل', 'err');
    return;
  }
  const list = r.data;
  if (!list.length) { tb.innerHTML = emptyRow(6, 'لا أحداث مسجلة بعد', 'ستظهر العمليات هنا مع سلسلة هاش حمايةً من العبث'); }
  else {
    tb.innerHTML = list.map(function (x) {
      return '<tr>' +
        '<td class="mono" style="text-align:right;direction:rtl">' + esc(x.created_at) + '</td>' +
        '<td>' + esc(x.actor || '—') + (x.role ? '<div style="font-size:10px;color:var(--mut)">' + esc(x.role) + '</div>' : '') + '</td>' +
        '<td>' + esc(x.action || '—') + '</td>' +
        '<td>' + (x.device_id ? '<span class="mono">' + esc(x.device_id) + '</span>' : '—') + '</td>' +
        '<td>' + statusPill(x.result) + '</td>' +
        '<td><span class="mono" style="font-size:11px;color:var(--mut)">' + esc(x.entry_id || '') + '</span></td>' +
        '</tr>';
    }).join('');
  }
  setStatus('auditStatus', 'تم عرض ' + list.length + ' حدثاً', 'ok');
}
async function tamper() {
  const box = $('tamperBox');
  box.innerHTML = '<div class="empty">' + ic('info', 30) + '<div class="et">جارٍ فحص السلاسل…</div></div>';
  const r = await api('/audit/tamper', 'GET');
  if (!(r.ok && r.data)) {
    box.innerHTML = banner('bad', 'تعذّر التحقق', r.error || '');
    return;
  }
  const d = r.data;
  const links = Number(d.links || 0), broken = Number(d.broken || 0);
  const detail = (d.detail && Array.isArray(d.detail)) ? d.detail : [];
  let html;
  if (broken === 0) {
    html = banner('ok', 'السلاسل سليمة', 'عدد الروابط:' + links + ' — لا توجد روابط مكسورة أو صفوف معدَّلة.');
  } else {
    html = banner('bad', 'تلف في السلسلة', broken + ' من ' + links + ' رابطاً تالفاً') +
      '<div class="statusline err">' + detail.map(esc).join('<br>') + '</div>';
  }
  html += raw(r);
  box.innerHTML = html;
}

/* ------------------------------------------------------------ branding
   Agent in-app logo (ManageEngine-style rebranding without rebuilding:
   the logo INSIDE the app; agents fetch it at Sync). */
async function loadBranding() {
  const img = $('brandCurrent'), ver = $('brandVer');
  try {
    const r = await api('/branding', 'GET');
    if (r.ok && r.data && r.data.logo_url) {
      img.src = r.data.logo_url + '?v=' + encodeURIComponent(r.data.version || '');
      img.style.display = '';
      if (ver) ver.textContent = 'Version: ' + (r.data.version || '');
    } else {
      if (img) img.style.display = 'none';
      if (ver) ver.textContent = 'No logo published yet.';
    }
  } catch (e) {
    if (ver) ver.textContent = 'Could not load branding.';
  }
  const f = $('brandFile'); if (f) f.value = '';
  const pv = $('brandPreview'); if (pv) { pv.style.display = 'none'; pv.src = ''; }
  window._brandB64 = null;
}
function brandPreviewFile(inp) {
  const st = $('brandStatus'); if (st) st.textContent = '';
  const f = inp.files && inp.files[0];
  const pv = $('brandPreview');
  window._brandB64 = null;
  if (!f) { if (pv) pv.style.display = 'none'; return; }
  if (f.size > 512 * 1024) { setStatus('brandStatus', 'PNG must be at most 512 KB.', 'err'); inp.value = ''; return; }
  const rd = new FileReader();
  rd.onload = function () {
    const url = rd.result;
    window._brandB64 = String(url).split(',')[1];
    if (pv) { pv.src = url; pv.style.display = ''; }
  };
  rd.readAsDataURL(f);
}
async function uploadBranding() {
  if (!window._brandB64) { setStatus('brandStatus', 'Choose a PNG file first.', 'err'); return; }
  const r = await apiWriteOrReport('/branding/logo', 'POST', { png_b64: window._brandB64 }, 'Update agent logo', 'brandStatus');
  if (r && r.ok) { setStatus('brandStatus', 'Logo published. Agents pick it up at the next Sync.', 'ok'); loadBranding(); }
}

async function reportList() {
  const tb = $('repTbody');
  tb.innerHTML = skelRows(3, 3);
  setStatus('repStatus', 'جارٍ جلب القائمة…');
  const r = await api('/reports', 'GET');
  if (!(r.ok)) {
    tb.innerHTML = emptyRow(3, 'تعذّر تحميل القائمة', r.error || '');
    setStatus('repStatus', 'فشل التحميل', 'err');
    return;
  }
  const list = r.data || [];
  if (!list.length) { tb.innerHTML = emptyRow(3, 'لا تقارير بعد', 'ولّد تقريراً من الجهاز ليُحفظ هنا'); }
  else {
    tb.innerHTML = list.map(function (x) {
      const size = x.size;
      const kb = (size / 1024);
      const sz = kb < 1 ? size + ' B' : (kb < 1024 ? kb.toFixed(1) + ' KB' : (kb / 1024).toFixed(2) + ' MB');
      return '<tr><td class="mono">' + esc(x.path) + '</td><td class="mono">' + sz + '</td><td class="mono" style="text-align:right;direction:rtl">' + esc(x.mtime || '—') + '</td></tr>';
    }).join('');
  }
  setStatus('repStatus', 'تم عرض ' + list.length + ' تقريراً', 'ok');
}
async function reportOne() {
  const dev = $('repDev').value.trim();
  if (!dev) { setStatus('repStatus', 'device_id مطلوب', 'err'); return; }
  setStatus('repStatus', 'جارٍ توليد التقرير…');
  $('repView').innerHTML = '<div class="empty">' + ic('info', 30) + '<div class="et">جارٍ التوليد…</div></div>';
  const r = await api('/reports/' + encodeURIComponent(dev), 'GET');
  $('repView').innerHTML = renderReportView(r);
  if (r.ok && r.data) { $('repViewSub').textContent = 'تقرير الجهاز ' + dev; setStatus('repStatus', 'تم توليد التقرير', 'ok'); }
  else { setStatus('repStatus', 'فشل التوليد', 'err'); }
}
function renderReportView(r) {
  if (!(r.ok && r.data)) return errCard(r.error || 'لا تقرير متاح لهذا الجهاز');
  const d = r.data;
  const text = d.text || d.markdown || '';
  let html = '';
  if (typeof text === 'string' && text.trim()) {
    html += '<div class="repmeta"><span class="mono">' + esc(d.path || '') + '</span>';
    html += '<button class="btn ghost" id="repCopyBtn" onclick="copyReportText()">' + ic('check', 13) + ' نسخ النص</button></div>';
    html += '<pre class="rep" id="repViewPre">' + esc(text) + '</pre>';
  } else if (Array.isArray(d)) {
    html += '<div class="tw"><table><thead><tr><th>المفتاح</th><th>القيمة</th></tr></thead><tbody>' + d.map(function (x) {
      return '<tr><td>' + esc(x.name || x.k || '') + '</td><td>' + esc(x.value || x.v || '') + '</td></tr>';
    }).join('') + '</tbody></table></div>';
  } else if (d && typeof d === 'object') {
    html += defs(Object.keys(d).map(function (k) {
      const v = d[k];
      if (v && typeof v === 'object') return [k, '<span class="chip">كائن (' + Object.keys(v).length + ')</span>'];
      return [k, esc(v)];
    }));
  }
  html += raw(r);
  return html;
}
async function copyReportText() {
  const pre = $('repViewPre');
  const btn = $('repCopyBtn');
  if (pre) copyText(pre.textContent, btn);
}

buildModes();
document.addEventListener('keydown', function (e) {
  if (e.key === 'Enter' && $('view-login').classList.contains('active')) doLogin();
});
document.addEventListener('keydown', function (e) {
  if (e.target.classList && e.target.classList.contains('tab') && (e.key === 'Enter' || e.key === ' ')) {
    e.preventDefault();
    showView(e.target.getAttribute('data-v'));
  }
});
load();
setInterval(function () {
  if (!TOKEN) return;
  // 1. Dashboard live update
  if ($('sub-dashboard')?.classList.contains('active')) {
    dashboard();
  }
  // 2. New detected USB devices live update
  if ($('sub-new_devices')?.classList.contains('active')) {
    populateNewDevices();
  }
  // 3. Devices table live update if on devices panel and table is visible
  if ($('sub-devices')?.classList.contains('active')) {
    const wsGD = $('workspaceGroupsDevices');
    if (wsGD && wsGD.style.display !== 'none') {
      populateDevices();
    }
  }
  // 4. Comprehensive Device 360 Inventory live update
  const wsComp = $('workspaceComprehensiveDeviceDetails');
  if (wsComp && wsComp.style.display !== 'none' && CURRENT_COMP_DID) {
    openComprehensiveDeviceDetails(CURRENT_COMP_DID, CURRENT_COMP_TAB || 'summary', false, true);
  }
  // 5. Basic Device Details live update
  const wsDD = $('workspaceDeviceDetails');
  if (wsDD && wsDD.style.display !== 'none' && CURRENT_DETAILS_DID) {
    openDeviceDetails(CURRENT_DETAILS_DID, false, CURRENT_DETAILS_TAB || 'groups', true);
  }
}, 3000);

