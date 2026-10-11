/**
 * alp-enrollment.js — Enrollment section logic (Enroll tree + Devices tabs).
 *
 * Mirrors the reference layout (Enrollment > Enroll > Devices with
 * Managed / Staged / Enrollment Pending tabs) plus a fourth tab,
 * "Connected Devices", for USB-attached phones.
 *
 * Loading contract (no more "empty tab for seconds"): opening the node
 * paints skeleton rows instantly, then each tab fills in as SOON as its own
 * data arrives — devices list and detected list need no group data, so
 * Managed/Pending/Connected render in the first round-trip while group
 * membership loads in parallel in the background. A generation guard keeps
 * a slow run from ever painting over a newer one.
 *
 * Self-contained on purpose: it only needs window.fetch and the shared
 * alp-dialog.js component (alpAlert/alpConfirm/alpChoose). It never calls
 * into alp-console.js internals, so either side can evolve independently.
 *
 * Tab definitions (honest, shown under each tab):
 *   managed   — every enrolled device.
 *   pending   — enrolled devices still in ENROLLMENT_PENDING.
 *   staged    — enrolled devices that are in no group yet (awaiting grouping).
 *   connected — ADB-attached right now; the single action shown per row is
 *               read verbatim from the backend's next_step field
 *               (authorize/install/register/group), never decided here.
 */
(function () {
  'use strict';

  var API = '/api/v1';
  var NODES = ['devices', 'users', 'self', 'settings', 'directory', 'catalog'];
  var TABS = ['managed', 'pending', 'staged', 'connected'];
  var state = { node: 'devices', tab: 'managed', det: [], reg: [],
                groups: [], memberOf: {}, gen: 0, filter: '',
                loaded: { devices: false, detected: false, groups: false } };

  function $(id) { return document.getElementById(id); }

  function enrEsc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function token() {
    try {
      return localStorage.getItem('alp_token') ||
             sessionStorage.getItem('alp_token') || '';
    } catch (e) { return ''; }
  }

  async function enrApi(path, method, body) {
    var opts = { method: method || 'GET',
                 headers: { Authorization: 'Bearer ' + token(),
                            'Content-Type': 'application/json' } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    var r = await fetch(API + path, opts);
    var j = null;
    try { j = await r.json(); } catch (e) { j = { ok: false, error: 'bad response' }; }
    j.status = r.status;
    if (r.status === 401) {
      try {
        localStorage.removeItem('alp_token');
        sessionStorage.removeItem('alp_token');
      } catch (e) {}
    }
    return j;
  }

  function pill(cls, txt) {
    return '<span class="pill ' + cls + '">' + enrEsc(txt) + '</span>';
  }

  function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  /* ------------------------------------------------------------ navigation */
  window.enrShowNode = function (node) {
    if (NODES.indexOf(node) < 0) node = 'devices';
    state.node = node;
    NODES.forEach(function (n) {
      var btn = $('enrNav' + cap(n));
      var panel = $('enrNode' + cap(n));
      if (btn) {
        btn.classList.toggle('active', n === node);
        btn.classList.toggle('common-bg', n === node);
        btn.classList.toggle('anchor-text__imp', n === node);
      }
      if (panel) panel.style.display = (n === node) ? 'block' : 'none';
    });
    if (typeof updateNavSlider === 'function') updateNavSlider();
    if (node === 'devices') {
      paintSkeletons();
      enrRefresh();
    }
    if (node === 'catalog' && typeof loadCatalog === 'function') {
      try { loadCatalog(); } catch (e) {}
    }
  };

  window.enrShowTab = function (tab) {
    if (TABS.indexOf(tab) < 0) tab = 'managed';
    state.tab = tab;
    TABS.forEach(function (t) {
      var btn = $('enrTab' + cap(t));
      var panel = $('enrTabPanel' + cap(t));
      if (btn) {
        btn.classList.toggle('active', t === tab);
        if (btn.parentElement && btn.parentElement.tagName === 'LI') {
          btn.parentElement.classList.toggle('active', t === tab);
        }
      }
      if (panel) panel.style.display = (t === tab) ? 'block' : 'none';
    });
    paintSkeleton(tab);
    renderToolbar();
    renderTab();
    enrRefresh();
  };

  window.addEventListener('hashchange', function () {
    var h = (location.hash || '').replace(/^#\/?/, '').split('?')[0];
    if (h === 'restrictions' || h === '') {
      var panel = $('sub-restrictions');
      if (panel && panel.classList.contains('active')) enrShowNode('devices');
    }
  });

  /* showView() navigates with history.pushState, which never fires
     hashchange — without this hook the Devices node would only load on the
     4s poll. Wrap once (guarded) instead of editing the host function. */
  (function () {
    try {
      if (typeof showView === 'function' && !showView.enrWrapped) {
        var original = showView;
        var wrapped = function (v, push) {
          var out = original(v, push);
          if (v === 'restrictions') {
            try { enrShowNode('devices'); } catch (e) {}
          }
          return out;
        };
        wrapped.enrWrapped = true;
        showView = wrapped;
      }
    } catch (e) {}
  })();

  setInterval(function () {
    var panel = $('sub-restrictions');
    var node = $('enrNodeDevices');
    if (!panel || !panel.classList.contains('active')) return;
    if (!node || node.style.display === 'none') return;
    enrRefresh();
  }, 4000);

  /* ----------------------------------------------------------------- data
     Three independent loaders race each other; each renders whatever tabs
     it unblocks the moment it lands. Managed/Pending need only /devices,
     Connected needs only /detected, Staged additionally needs membership. */
  window.enrRefresh = function () {
    var my = ++state.gen;
    enrLoadDevices(my);
    enrLoadDetected(my);
    enrLoadGroups(my);
  };

  async function enrLoadDevices(my) {
    var r = await enrApi('/devices', 'GET');
    if (my !== state.gen) return;
    state.reg = (r.ok && Array.isArray(r.data)) ? r.data : [];
    state.loaded.devices = true;
    renderCounts();
    renderTab();
  }

  async function enrLoadDetected(my) {
    var r = await enrApi('/devices/detected', 'GET');
    if (my !== state.gen) return;
    state.det = (r.ok && Array.isArray(r.data)) ? r.data : [];
    state.loaded.detected = true;
    renderBanner();
    renderCounts();
    renderTab();
  }

  async function enrLoadGroups(my) {
    var g = await enrApi('/groups', 'GET');
    if (my !== state.gen) return;
    state.groups = (g.ok && Array.isArray(g.data)) ? g.data : [];
    var memberOf = {};
    await Promise.all(state.groups.map(async function (gr) {
      try {
        var m = await enrApi('/groups/' + gr.id + '/members', 'GET');
        var list = (m.ok && Array.isArray(m.data)) ? m.data : [];
        list.forEach(function (d) {
          var id = d.device_id || d;
          if (!memberOf[id]) memberOf[id] = [];
          memberOf[id].push(gr.name);
        });
      } catch (e) {}
    }));
    if (my !== state.gen) return;
    state.memberOf = memberOf;
    state.loaded.groups = true;
    renderCounts();
    renderTab();
  }

  function isPending(d) {
    return String(d.enrollment_state || '') === 'ENROLLMENT_PENDING';
  }

  function matchFilterText(text) {
    var f = (state.filter || '').trim().toLowerCase();
    if (!f) return true;
    return String(text).toLowerCase().indexOf(f) >= 0;
  }

  /* --------------------------------------------------------------- render */
  function skeletonRow(cols) {
    return '<tr><td colspan="' + cols + '" style="text-align:center;padding:26px;' +
      'color:#94a3b8;font-size:12.5px;">جارٍ التحميل…</td></tr>';
  }

  function emptyRow(cols, text) {
    return '<tr><td colspan="' + cols + '" style="text-align:center;padding:26px;' +
      'color:#94a3b8;font-size:12.5px;">' + enrEsc(text) + '</td></tr>';
  }

  function paintSkeletons() {
    if (!state.loaded.devices) {
      $('enrBodyManaged').innerHTML = skeletonRow(7);
      $('enrBodyPending').innerHTML = skeletonRow(7);
    }
    if (!state.loaded.groups) {
      $('enrBodyStaged').innerHTML = skeletonRow(7);
    }
    if (!state.loaded.detected) {
      $('enrBodyConnected').innerHTML = skeletonRow(5);
    }
    renderToolbar();
  }

  function paintSkeleton(tab) {
    var map = { managed: ['enrBodyManaged', 7, 'devices'],
                pending: ['enrBodyPending', 7, 'devices'],
                staged: ['enrBodyStaged', 7, 'groups'],
                connected: ['enrBodyConnected', 5, 'detected'] };
    var m = map[tab];
    if (m && !state.loaded[m[2]]) $(m[0]).innerHTML = skeletonRow(m[1]);
  }

  function renderBanner() {
    var box = $('enrBanner');
    if (!box) return;
    var n = state.det.length;
    var ready = state.det.filter(function (d) { return d.ready; }).length;
    var noAgent = state.det.filter(function (d) {
      return d.ready && d.agent_installed !== true;
    }).length;
    function banner(kind, title, desc) {
      return '<div class="enr-banner ' + kind + '">' +
        '<div class="enr-banner-badge">!</div>' +
        '<div><div class="enr-banner-title">' + enrEsc(title) + '</div>' +
        '<div>' + desc + '</div></div></div>';
    }
    if (!state.loaded.detected) {
      box.innerHTML = '';
    } else if (!n) {
      box.innerHTML = banner('info', 'لا يوجد جهاز موصول',
        'وصّل الجهاز عبر USB وفعّل تصحيح أخطاء USB — سيظهر في تبويب Connected Devices.');
    } else if (noAgent) {
      box.innerHTML = banner('warn', 'التطبيق غير مثبت على جهاز متصل',
        'جهاز متصل (' + noAgent + ') بدون تطبيق الإدارة — ثبّته من تبويب Connected Devices قبل أي نشر.');
    } else {
      box.innerHTML = banner('info', 'أجهزة متصلة وجاهزة',
        'متصل عبر USB الآن: ' + n + ' (جاهز: ' + ready + ').');
    }
  }

  function counts() {
    var managed = state.reg.length;
    var pending = state.reg.filter(isPending).length;
    var staged = state.reg.filter(function (d) {
      return !(state.memberOf[d.device_id] && state.memberOf[d.device_id].length);
    }).length;
    return { managed: managed, pending: pending,
             staged: staged, connected: state.det.length };
  }

  function renderCounts() {
    var c = counts();
    TABS.forEach(function (t) {
      var el = $('enrCount' + cap(t));
      if (el) el.textContent = ' (' + c[t] + ')';
    });
    renderToolbar();
  }

  function groupCell(id) {
    var g = state.memberOf[id];
    return (g && g.length) ? enrEsc(g.join('، ')) : '<span style="color:#94a3b8;">—</span>';
  }

  function addBtn(id) {
    return '<button class="cp-btn-primary" style="padding:4px 12px;font-size:12px;" ' +
      'onclick="enrAddToGroup(\'' + enrEsc(id) + '\')">إضافة إلى مجموعة</button>';
  }

  /* The single action per attached row, read verbatim from the backend's
     next_step field (authorize/install/register/provision_owner/group) —
     never decided here. Shared by the Connected tab and the registered
     tables below, so a phone that lost its app or its owner grant shows
     Install / Make Owner wherever the operator looks, not only in one tab. */
  function detAction(x, serial, id) {
    var agent = x.agent_installed === true;
    var step = x.next_step || '';
    if (!x.ready) {
      return '<span style="color:#94a3b8;font-size:12px;">اسمح بتصحيح USB لهذا الكمبيوتر ثم حدّث</span>';
    } else if (step === 'install' || !agent) {
      // Android 5-6 handsets refuse the standard APK outright, so they get
      // the guarded legacy build (same agent, minSdk 21) instead of a button
      // that can only fail with INSTALL_FAILED_OLDER_SDK.
      if (x.legacy_build || (x.api_level > 0 && x.api_level < 24)) {
        return '<button class="cp-btn-primary" style="padding:4px 12px;font-size:12px;" ' +
          'onclick="enrInstallLegacy(\'' + enrEsc(serial) + '\')">تثبيت نسخة الأجهزة القديمة (أندرويد 5-6)</button>' +
          '<div style="font-size:11px;color:#b45309;margin-top:3px;">' +
          'هذا الهاتف أندرويد قديم (API ' + enrEsc(String(x.api_level || '?')) + ') — النسخة القياسية مرفوضة عليه.</div>';
      }
      return '<button class="cp-btn-primary" style="padding:4px 12px;font-size:12px;" ' +
        'onclick="enrInstall(\'' + enrEsc(serial) + '\')">تثبيت التطبيق</button>' +
        '<div style="font-size:11px;color:#b45309;margin-top:3px;">' +
        enrEsc(x.next_step_reason || 'التطبيق غير مثبت — ثبّته أولاً') + '</div>';
    } else if (step === 'register' || !id) {
      return '<button class="cp-btn-primary" style="padding:4px 12px;font-size:12px;" ' +
        'onclick="enrRegister(\'' + enrEsc(serial) + '\')">تسجيل الجهاز</button>';
    } else if (step === 'provision_owner') {
      return '<button class="cp-btn-primary" style="padding:4px 12px;font-size:12px;" ' +
        'onclick="enrMakeOwner(\'' + enrEsc(serial) + '\')">منح صلاحية مالك الجهاز</button>' +
        '<div style="font-size:11px;color:#b45309;margin-top:3px;">' +
        enrEsc(x.next_step_reason || 'لا يمكن تطبيق القيود قبل أن يصبح التطبيق مالك الجهاز') + '</div>';
    }
    return '<button class="cp-btn-primary" style="padding:4px 12px;font-size:12px;" ' +
      'onclick="enrAddToGroup(\'' + enrEsc(id) + '\')">إضافة إلى مجموعة</button>';
  }

  function deviceRows(list) {
    var vis = list.filter(function (d) {
      return matchFilterText((d.device_id || '') + ' ' + (d.model || '') +
                             ' ' + (d.serial || ''));
    });
    if (!state.loaded.devices) return skeletonRow(7);
    if (!vis.length) {
      return emptyRow(7, state.filter ? 'لا نتائج مطابقة للبحث.'
        : 'لا أجهزة هنا — وصّل جهازاً عبر USB ثم سجّله من تبويب Connected Devices.');
    }
    var detBySerial = {};
    state.det.forEach(function (x) { if (x.serial) detBySerial[x.serial] = x; });
    return vis.map(function (d) {
      var os = [d.model || d.manufacturer || '', d.android_version || '',
                 d.api_level ? 'API ' + d.api_level : '']
        .filter(Boolean).join(' · ') || '—';
      // Live override: when this registered phone is attached right now, the
      // action column follows the phone's truth (Install / Make Owner), not
      // the stale database row — uninstalling the app must surface here.
      var live = (d.serial && detBySerial[d.serial]) || null;
      var inGroups = !!(state.memberOf[d.device_id] &&
                        state.memberOf[d.device_id].length);
      var actionHtml;
      if (live && live.next_step === 'group' && state.loaded.groups && inGroups) {
        // Fully ready AND already grouped: "Add to Group" would imply
        // something is still missing. Further groups remain available from
        // the checkboxes batch action and the details page.
        actionHtml = '<span style="display:inline-flex;align-items:center;gap:4px;' +
          'color:#16a34a;font-weight:500;font-size:12px;">' +
          '<svg style="width:14px;height:14px;fill:#16a34a;" role="img">' +
          '<use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#tick-circle"></use></svg>' +
          'جاهز ومُدار</span>';
      } else {
        actionHtml = live
          ? '<div style="font-size:11px;color:#16a34a;margin-bottom:3px;">متصل الآن — الحالة حية</div>' +
            detAction(live, String(d.serial), d.device_id)
          : addBtn(d.device_id);
      }
      var statePill = pill(isPending(d) ? 'p-part' : 'p-ok',
                      isPending(d) ? 'Enrollment Pending' : 'Managed');
      if (live && live.agent_installed !== true && live.ready) {
        statePill += ' ' + pill('p-part', 'ينقصه التطبيق');
      }
      return '<tr><td style="text-align:center;">' +
        '<input type="checkbox" class="enr-row-chk" value="' + enrEsc(d.device_id) + '">' +
        '</td><td class="mono">' + enrEsc(d.device_id) + '</td>' +
        '<td>' + enrEsc(d.model || d.manufacturer || '—') + '</td>' +
        '<td>' + enrEsc(os) + '</td>' +
        '<td>' + statePill + '</td>' +
        '<td>' + groupCell(d.device_id) + '</td>' +
        '<td>' + actionHtml + '</td></tr>';
    }).join('');
  }

  function connectedRows() {
    var bySerial = {};
    state.reg.forEach(function (d) { if (d.serial) bySerial[d.serial] = d.device_id; });
    if (!state.loaded.detected) return skeletonRow(5);
    var vis = state.det.filter(function (x) {
      return matchFilterText((x.serial || '') + ' ' + (x.model || ''));
    });
    if (!vis.length) {
      return emptyRow(5, state.filter ? 'لا نتائج مطابقة للبحث.'
        : 'لا يوجد جهاز موصول عبر USB الآن.');
    }
    return vis.map(function (x) {
      var serial = String(x.serial || '');
      var id = bySerial[serial] || '';
      var agent = x.agent_installed === true;
      var statusPill = x.ready
        ? (agent ? pill('p-ok', 'متصل وجاهز') : pill('p-part', 'ينقصه التطبيق'))
        : pill('p-bad', String(x.state || 'غير جاهز'));
      var action = detAction(x, serial, id);
      return '<tr><td class="mono">' + enrEsc(serial) + '</td>' +
        '<td>' + enrEsc(x.model || '—') + '</td>' +
        '<td>' + statusPill + '</td>' +
        '<td>' + (id ? '<span class="mono">' + enrEsc(id) + '</span>'
                     : '<span style="color:#94a3b8;">جهاز جديد</span>') + '</td>' +
        '<td>' + action + '</td></tr>';
    }).join('');
  }

  function renderTab() {
    var t = state.tab;
    if (t === 'managed') {
      $('enrBodyManaged').innerHTML = deviceRows(state.reg);
    } else if (t === 'pending') {
      $('enrBodyPending').innerHTML = deviceRows(state.reg.filter(isPending));
    } else if (t === 'staged') {
      if (!state.loaded.groups && !state.loaded.devices) {
        $('enrBodyStaged').innerHTML = skeletonRow(7);
      } else {
        var s = state.reg.filter(function (d) {
          return !(state.memberOf[d.device_id] && state.memberOf[d.device_id].length);
        });
        $('enrBodyStaged').innerHTML = s.length ? deviceRows(s)
          : emptyRow(7, 'لا أجهزة مركونة — كل الأجهزة المسجلة داخل مجموعات.');
      }
    } else {
      $('enrBodyConnected').innerHTML = connectedRows();
    }
    renderCounts();
  }

  /* Toolbar: batch action for the active tab, live search, refresh, total —
     the reference table chrome, all wired to real behaviour. */
  function renderToolbar() {
    var bar = $('enrToolbar');
    if (!bar) return;
    var c = counts();
    var batchable = (state.tab !== 'connected');
    var n = c[state.tab];
    bar.innerHTML =
      '<div class="sub-menu-container" style="margin-bottom:10px;">' +
      '<div class="devices-menu">' +
      (batchable
        ? '<span class="table-menu-action"><div class="actionsButton ember-view">' +
          '<div class="dropdown-action-button table-display-button" ' +
          'onclick="enrBatchAdd()" style="cursor:pointer;"><span>إضافة المحدد إلى مجموعة</span></div>' +
          '</div></span>'
        : '<span style="font-size:12px;color:#64748b;">الإجراء لكل جهاز حسب خطوته التالية.</span>') +
      '</div>' +
      '<div class="sub-menu-container-right" style="display:flex;align-items:center;gap:8px;">' +
      '<input id="enrSearch" class="me-search-input" style="width:200px;height:30px;" ' +
      'placeholder="بحث" value="' + enrEsc(state.filter) + '" oninput="enrFilterChanged(this.value)">' +
      '<div class="mdm-mc-menu-btn"><div class="tableBtn-primary" onclick="enrManualRefresh()" title="Refresh">' +
      '<svg role="img" aria-label="refresh" class="svg-bucket-icon" data-icon="global::refresh" ' +
      'style="width:16px;height:16px;"><use href="/images/svg-bucket/global-ad8991927609f9db376ce73a09f940e5.svg#refresh"></use></svg>' +
      '</div></div>' +
      '<span class="total-count ember-view">Total : ' + n + '</span>' +
      '</div></div>';
  }

  window.enrFilterChanged = function (v) {
    state.filter = v || '';
    renderTab();
    var box = $('enrSearch');
    if (box && document.activeElement !== box) box.focus();
    if (box) {
      try {
        var L = box.value.length;
        box.setSelectionRange(L, L);
      } catch (e) {}
    }
  };

  window.enrManualRefresh = function () {
    state.loaded = { devices: false, detected: false, groups: false };
    paintSkeletons();
    enrRefresh();
  };

  window.enrToggleAll = function (box) {
    var tb = box.closest('table').querySelector('tbody');
    tb.querySelectorAll('.enr-row-chk').forEach(function (c) {
      c.checked = box.checked;
    });
  };

  window.enrBatchAdd = function () {    var panel = $('enrTabPanel' + cap(state.tab));
    var ids = Array.from(
      (panel || document).querySelectorAll('.enr-row-chk:checked')).map(function (c) {
        return c.value;
      });
    if (!ids.length) {
      alpAlert('اختر جهازاً واحداً على الأقل من الجدول.', 'Alert');
      return;
    }
    enrAddToGroup(ids);
  };

  /* ---------------------------------------------------------------- action */
  function apiError(what, r) {
    var code = r && (r.status || (r.ok === false ? 400 : 0));
    var raw = String((r && (r.error || r.message)) || 'خطأ غير معروف');
    if (code === 401) return what + ': انتهت الجلسة — سجّل الدخول من جديد.';
    if (code === 403) return what + ': صلاحيتك لا تسمح — ' + raw;
    if (code === 404) return what + ': غير موجود — ' + raw;
    if (code === 409) return what + ': تعارض — ' + raw;
    return what + ': ' + raw;
  }

  window.enrInstall = async function (serial) {
    var r = await enrApi('/devices/install-agent', 'POST', { serial: serial });
    if (!r.ok) { alpAlert(apiError('تثبيت التطبيق', r), 'Alert'); return; }
    var d = r.data || {};
    alpAlert(d.launched === false
      ? 'تم التثبيت على ' + serial + ' لكن تعذّر فتح التطبيق تلقائياً — افتحه مرة واحدة على الهاتف ثم حدّث.'
      : 'تم تثبيت التطبيق على ' + serial + ' — الخطوة التالية: تسجيل الجهاز.',
      'Alert');
    enrRefresh();
  };

  window.enrInstallLegacy = async function (serial) {
    var r = await enrApi('/devices/install-agent', 'POST',
      { serial: serial, variant: 'legacy' });
    if (!r.ok) { alpAlert(apiError('تثبيت نسخة الأجهزة القديمة', r), 'Alert'); return; }
    var d = r.data || {};
    alpAlert('تم تثبيت نسخة الأجهزة القديمة على ' + serial +
      ' — الخطوة التالية: تسجيل الجهاز.' +
      (d.launched === false ? ' (تعذّر فتحه تلقائياً — افتحه مرة واحدة على الهاتف)' : ''),
      'Alert');
    enrRefresh();
  };

  window.enrRegister = async function (serial) {
    var r = await enrApi('/devices/enroll', 'POST', { serial: serial });
    if (!r.ok) { alpAlert(apiError('تسجيل الجهاز', r), 'Alert'); return; }
    var d = r.data || {};
    alpAlert('تم تسجيل الجهاز ' + (d.device_id || serial) +
             ' — ' + (d.next_step_reason || 'الخطوة التالية: إضافته إلى مجموعة.'),
             'Alert');
    enrRefresh();
  };

  /* Real device-owner provisioning. The reply reports what dumpsys proved,
     never what we asked for, so a refusal must read as a refusal here. */
  window.enrMakeOwner = async function (serial) {
    var r = await enrApi('/devices/provision-device-owner', 'POST', { serial: serial });
    if (!r.ok) {
      alpAlert(apiError('منح صلاحية مالك الجهاز', r), 'Alert');
      return;
    }
    var d = r.data || {};
    alpAlert(d.device_owner
      ? 'Android منح التطبيق صلاحية مالك الجهاز على ' + serial +
        ' — 이제 ستصل القيود فعلياً.'
      : 'لم يؤكد Android صلاحية مالك الجهاز على ' + serial + '.', 'Alert');
    enrRefresh();
  };

  window.enrAddToGroup = async function (deviceIds) {
    var ids = Array.isArray(deviceIds) ? deviceIds.slice() : [deviceIds];
    ids = ids.filter(Boolean);
    if (!ids.length) {
      alpAlert('اختر جهازاً واحداً على الأقل.', 'Alert');
      return;
    }
    if (!state.groups.length) {
      var g = await enrApi('/groups', 'GET');
      state.groups = (g.ok && Array.isArray(g.data)) ? g.data : [];
    }
    if (!state.groups.length) {
      alpAlert('أنشئ مجموعة أولاً قبل إضافة الجهاز.', 'Alert');
      return;
    }
    var choice = await alpChoose('Add devices to group',
      state.groups.map(function (gr) {
        return { value: String(gr.id),
                 label: gr.name,
                 sub: 'أعضاء: ' + (gr.members || 0) +
                      ' · ملفات: ' + (gr.profiles || 0) };
      }), ids.length + ' جهاز محدد — سيُطبَّق ملف المجموعة عليهم فوراً إن كانوا متصلين.',
      'Add & Deploy', 'إلغاء');
    if (choice === null) return;
    var r = await enrApi('/groups/' + choice + '/members', 'POST',
      { device_ids: ids, deploy: true, bulk: true,
        skip_approval: true, real: true, reason: 'enrollment add to group' });
    if (!r.ok) { alpAlert(apiError('إضافة الأجهزة للمجموعة', r), 'Alert'); return; }
    var s = ((r.data || {}).deploy || {}).summary || {};
    alpAlert('أُضيف ' + ids.length + ' جهاز إلى المجموعة.\nنشر: ' + (s.total || 0) +
             ' · ناجح: ' + (s.success || 0) +
             ' · بانتظار الاتصال: ' + (s.yet_to_apply || 0) +
             ' · فاشل: ' + (s.failed || 0), 'Alert');
    enrRefresh();
  };
})();
