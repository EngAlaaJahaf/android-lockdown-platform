/**
 * alp-dialog.js — the ONE dialog component for the ALP console.
 *
 * Replaces every native alert()/confirm()/prompt() with a ManageEngine-style
 * modal (blue "Alert" title, X close, orange warning badge, blue action
 * button), matching the reference MDM dialogs in mdm/.
 *
 * Single source of truth: every new section MUST call alpAlert/alpConfirm/
 * alpPrompt instead of inventing its own popup, so all dialogs share one
 * design and one behaviour. A safety net below reroutes any stray
 * window.alert() call into the styled modal, so a native popup can never
 * appear again — even from code written before this component existed.
 *
 *   alpAlert(message, title?)                    -> Promise<void>
 *   alpConfirm(message, title?, ok?, cancel?)    -> Promise<boolean>
 *   alpPrompt(message, def?, title?, ok?, cancel?) -> Promise<string|null>
 *   (null = dismissed, exactly like the native prompt contract)
 *
 * Load once, after alp-console.js:
 *   <script src="assets/alp-dialog.js"></script>
 */
(function () {
  'use strict';

  var STYLE_ID = 'alp-dialog-style';
  var QUEUE = [];
  var OPEN = false;

  function css() {
    if (document.getElementById(STYLE_ID)) return;
    var st = document.createElement('style');
    st.id = STYLE_ID;
    st.textContent =
      '.alp-dlg-overlay{position:fixed !important;top:0 !important;left:0 !important;right:0 !important;bottom:0 !important;width:100vw !important;height:100vh !important;background:rgba(0,0,0,.52) !important;display:flex !important;align-items:center !important;justify-content:center !important;z-index:999999 !important;opacity:1 !important;backdrop-filter:blur(1px);}' +
      '.alp-dlg{width:460px !important;max-width:92vw !important;background:#ffffff !important;border-radius:6px !important;box-shadow:0 12px 38px rgba(0,0,0,.35),0 0 0 1px rgba(0,0,0,.08) !important;font:13px \'Open Sans\',Arial,Helvetica,sans-serif !important;color:#333 !important;overflow:hidden !important;position:relative !important;opacity:1 !important;display:flex !important;flex-direction:column !important;animation:alpDlgPop .16s cubic-bezier(0.16,1,0.3,1) !important;}' +
      '@keyframes alpDlgPop{from{opacity:0;transform:scale(0.96)}to{opacity:1;transform:scale(1)}}' +
      '.alp-dlg-head{display:flex !important;align-items:center !important;justify-content:space-between !important;padding:12px 18px !important;border-bottom:1px solid #e5e7eb !important;background:#f8fafc !important;}' +
      '.alp-dlg-title{color:#0073b6 !important;font-size:15px !important;font-weight:600 !important;margin:0 !important;font-family:inherit !important;display:block !important;}' +
      '.alp-dlg-x{border:0 !important;background:transparent !important;color:#64748b !important;font-size:22px !important;line-height:1 !important;cursor:pointer !important;padding:0 4px !important;border-radius:4px !important;}' +
      '.alp-dlg-x:hover{color:#0f172a !important;background:#e2e8f0 !important;}' +
      '.alp-dlg-body{display:flex !important;align-items:flex-start !important;gap:16px !important;padding:22px 20px !important;background:#ffffff !important;}' +
      '.alp-dlg-badge{flex:0 0 auto !important;width:42px !important;height:42px !important;border-radius:50% !important;background:#f5821f !important;color:#ffffff !important;font-size:24px !important;font-weight:700 !important;display:flex !important;align-items:center !important;justify-content:center !important;box-shadow:0 2px 6px rgba(245,130,31,.3) !important;}' +
      '.alp-dlg-badge.ok,.alp-dlg-badge.info{background:#0073b6 !important;box-shadow:0 2px 6px rgba(0,115,182,.3) !important;}' +
      '.alp-dlg-msg{flex:1 1 auto !important;padding-top:4px !important;white-space:pre-wrap !important;word-break:break-word !important;font-size:13.5px !important;line-height:1.5 !important;color:#334155 !important;}' +
      '.alp-dlg-input{width:100% !important;box-sizing:border-box !important;margin-top:10px !important;padding:7px 9px !important;border:1px solid #c6c6c6 !important;border-radius:3px !important;font:13px Arial,Helvetica,sans-serif !important;}' +
      '.alp-dlg-input:focus{outline:none !important;border-color:#0073b6 !important;}' +
      '.alp-dlg-foot{display:flex !important;align-items:center !important;justify-content:flex-end !important;gap:10px !important;padding:12px 18px !important;background:#f8fafc !important;border-top:1px solid #e5e7eb !important;}' +
      '.alp-dlg-btn{min-width:84px !important;padding:7px 20px !important;border-radius:3px !important;cursor:pointer !important;font:13px \'Open Sans\',Arial,Helvetica,sans-serif !important;font-weight:500 !important;}' +
      '.alp-dlg-primary{background:#0073b6 !important;border:1px solid #0073b6 !important;color:#ffffff !important;font-weight:600 !important;}' +
      '.alp-dlg-primary:hover{background:#005a8e !important;border-color:#005a8e !important;}' +
      '.alp-dlg-ghost{background:#ffffff !important;border:1px solid #cbd5e1 !important;color:#334155 !important;}' +
      '.alp-dlg-ghost:hover{background:#f1f5f9 !important;border-color:#94a3b8 !important;}';
    (document.head || document.documentElement).appendChild(st);
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function show(opts) {
    return new Promise(function (resolve) {
      QUEUE.push({ opts: opts, resolve: resolve });
      pump();
    });
  }

  function pump() {
    if (OPEN || !QUEUE.length) return;
    OPEN = true;
    var item = QUEUE.shift();
    render(item.opts, function (value) {
      OPEN = false;
      item.resolve(value);
      pump();
    });
  }

  function render(opts, done) {
    css();
    var overlay = document.createElement('div');
    overlay.className = 'alp-dlg-overlay';

    var buttons = '';
    if (opts.kind === 'confirm' || opts.kind === 'prompt') {
      buttons =
        '<button class="alp-dlg-btn alp-dlg-ghost" data-act="cancel">' +
        esc(opts.cancelText || 'No') + '</button>' +
        '<button class="alp-dlg-btn alp-dlg-primary" data-act="ok">' +
        esc(opts.okText || 'Yes') + '</button>';
    } else {
      buttons =
        '<button class="alp-dlg-btn alp-dlg-primary" data-act="ok">' +
        esc(opts.okText || 'OK') + '</button>';
    }

    var input = opts.kind === 'prompt'
      ? '<input class="alp-dlg-input" dir="auto" value="' +
        esc(opts.defaultValue || '').replace(/"/g, '&quot;') + '">'
      : '';

    overlay.innerHTML =
      '<div class="alp-dlg" role="alertdialog" aria-modal="true">' +
      '<div class="alp-dlg-head"><p class="alp-dlg-title">' +
      esc(opts.title || 'Alert') + '</p>' +
      '<button class="alp-dlg-x" data-act="cancel" aria-label="Close">×</button></div>' +
      '<div class="alp-dlg-body"><div class="alp-dlg-badge' +
      (opts.kind === 'alert' && opts.ok ? ' ok' : '') + '">!</div>' +
      '<div class="alp-dlg-msg" dir="auto">' + esc(opts.message) + input + '</div></div>' +
      '<div class="alp-dlg-foot">' + buttons + '</div></div>';

    var field = overlay.querySelector('.alp-dlg-input');
    var finished = false;
    function finish(value) {
      if (finished) return;
      finished = true;
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      document.removeEventListener('keydown', onKey);
      done(value);
    }
    function onKey(e) {
      if (e.key === 'Escape') finish(opts.kind === 'alert' ? undefined : (opts.kind === 'confirm' ? false : null));
      else if (e.key === 'Enter') {
        if (opts.kind === 'prompt' && document.activeElement !== field) return;
        primary();
      }
    }
    function primary() {
      if (opts.kind === 'alert') finish(undefined);
      else if (opts.kind === 'confirm') finish(true);
      else finish(field ? field.value : '');
    }
    overlay.addEventListener('click', function (e) {
      var act = e.target && e.target.getAttribute
        ? e.target.getAttribute('data-act') : null;
      if (e.target === overlay) {
        finish(opts.kind === 'alert' ? undefined : (opts.kind === 'confirm' ? false : null));
      } else if (act === 'ok') primary();
      else if (act === 'cancel') {
        finish(opts.kind === 'alert' ? undefined : (opts.kind === 'confirm' ? false : null));
      }
    });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    var btn = overlay.querySelector('.alp-dlg-primary');
    if (opts.kind === 'prompt' && field) field.focus();
    else if (btn) btn.focus();
  }

  function alpAlert(a, b, c) {
    var title = 'Alert';
    var message = '';
    var ok = false;
    if (typeof a === 'object' && a !== null) {
      return show(Object.assign({ kind: 'alert' }, a));
    }
    if (arguments.length >= 3) {
      if (a === 'ok' || a === 'success' || a === 'info') ok = true;
      title = b || 'Alert';
      message = c || '';
    } else if (arguments.length === 2) {
      message = a || '';
      title = b || 'Alert';
    } else {
      message = a || '';
      title = 'Alert';
    }
    return show({ kind: 'alert', message: message, title: title, ok: ok });
  }

  function alpConfirm(message, title, okText, cancelText) {
    return show({ kind: 'confirm', message: message, title: title || 'Confirm',
                  okText: okText || 'Yes', cancelText: cancelText || 'No' });
  }

  function alpPrompt(message, defaultValue, title, okText, cancelText) {
    return show({ kind: 'prompt', message: message,
                  defaultValue: defaultValue == null ? '' : defaultValue,
                  title: title || 'Input',
                  okText: okText || 'OK', cancelText: cancelText || 'Cancel' });
  }

  /* Choice dialog (same design language): radio list + OK/Cancel.
   * options: [{value, label, sub?}] — resolves the chosen value, null if
   * dismissed. Used for pickers like "choose the target group". */
  function alpChoose(title, options, message, okText, cancelText) {
    return new Promise(function (resolve) {
      QUEUE.push({ choose: { title: title, options: options || [],
                             message: message || '',
                             okText: okText || 'OK',
                             cancelText: cancelText || 'Cancel' },
                   resolve: resolve });
      pumpChoose();
    });
  }

  function pumpChoose() {
    if (OPEN || !QUEUE.length) return;
    var item = QUEUE[0];
    if (!item.choose) { pump(); return; }
    QUEUE.shift();
    OPEN = true;
    renderChoose(item.choose, function (value) {
      OPEN = false;
      item.resolve(value);
      if (QUEUE.length && QUEUE[0].choose) pumpChoose(); else pump();
    });
  }

  function renderChoose(cfg, done) {
    css();
    var overlay = document.createElement('div');
    overlay.className = 'alp-dlg-overlay';
    var rows = (cfg.options || []).map(function (o, i) {
      return '<label style="display:flex;gap:8px;align-items:center;padding:6px 0;' +
        'cursor:pointer;font-size:13px;color:#333;">' +
        '<input type="radio" name="alp-choose" value="' +
        esc(String(o.value)).replace(/"/g, '&quot;') + '"' +
        (i === 0 ? ' checked' : '') + '>' +
        '<span>' + esc(o.label) +
        (o.sub ? ' <span style="color:#94a3b8;font-size:11px;" dir="ltr">' +
          esc(o.sub) + '</span>' : '') + '</span></label>';
    }).join('') || '<div style="color:#94a3b8;">لا عناصر متاحة</div>';
    overlay.innerHTML =
      '<div class="alp-dlg" role="dialog" aria-modal="true">' +
      '<div class="alp-dlg-head"><p class="alp-dlg-title">' +
      esc(cfg.title || 'Choose') + '</p>' +
      '<button class="alp-dlg-x" data-act="cancel" aria-label="Close">×</button></div>' +
      '<div class="alp-dlg-body" style="display:block;">' +
      (cfg.message ? '<div class="alp-dlg-msg" dir="auto" style="padding:0 0 8px;">' +
        esc(cfg.message) + '</div>' : '') +
      '<div style="max-height:260px;overflow:auto;">' + rows + '</div></div>' +
      '<div class="alp-dlg-foot">' +
      '<button class="alp-dlg-btn alp-dlg-ghost" data-act="cancel">' +
      esc(cfg.cancelText) + '</button>' +
      '<button class="alp-dlg-btn alp-dlg-primary" data-act="ok">' +
      esc(cfg.okText) + '</button></div></div>';
    var finished = false;
    function finish(value) {
      if (finished) return;
      finished = true;
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      document.removeEventListener('keydown', onKey);
      done(value);
    }
    function onKey(e) {
      if (e.key === 'Escape') finish(null);
      else if (e.key === 'Enter') ok();
    }
    function ok() {
      var sel = overlay.querySelector('input[name="alp-choose"]:checked');
      finish(sel ? sel.value : null);
    }
    overlay.addEventListener('click', function (e) {
      var act = e.target && e.target.getAttribute
        ? e.target.getAttribute('data-act') : null;
      if (e.target === overlay || act === 'cancel') finish(null);
      else if (act === 'ok') ok();
    });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(overlay);
    var btn = overlay.querySelector('.alp-dlg-primary');
    if (btn) btn.focus();
  }

  window.alpAlert = alpAlert;
  window.alpConfirm = alpConfirm;
  window.alpPrompt = alpPrompt;
  window.alpChoose = alpChoose;

  /* Safety net: a native alert can never pop up again — even from code that
     predates this component, every stray window.alert() renders styled. */
  window.alert = function (message) {
    alpAlert(message == null ? '' : String(message));
  };
})();
