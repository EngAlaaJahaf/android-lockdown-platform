/**
 * ALP Real-Time WebSocket Client & Notification Engine.
 * Features:
 * - Live Status Badge in Header (Connected / Reconnecting / Offline)
 * - ManageEngine-style Toast Notifications for Device & Policy events
 * - Instant Auto-Refresh of Dashboard and Device Table on USB plug/unplug
 * - Live Audit Feed streaming
 */
(function () {
  if (typeof window === 'undefined') return;

  let ws = null;
  let retryTimer = null;
  let isConnected = false;

  // UI elements
  function getBadgeElements() {
    return {
      badge: document.getElementById('alpWsStatusBadge'),
      dot: document.getElementById('alpWsStatusDot'),
      text: document.getElementById('alpWsStatusText'),
    };
  }

  function setStatus(status, text) {
    const el = getBadgeElements();
    if (!el.badge) return;
    el.badge.className = 'tab-component-element alp-ws-live-badge ' + status;
    if (el.text) el.text.textContent = text;
  }

  // Toast Notification System
  function showToast(title, msg, type) {
    type = type || 'info';
    let container = document.getElementById('alpToastContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'alpToastContainer';
      container.className = 'alp-toast-container';
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = 'alp-toast alp-toast-' + type;

    const icons = {
      success: '✓',
      info: 'ℹ',
      warning: '⚠',
      danger: '✕',
    };

    toast.innerHTML =
      '<div class="alp-toast-icon">' + (icons[type] || 'ℹ') + '</div>' +
      '<div class="alp-toast-body">' +
      '<div class="alp-toast-title">' + title + '</div>' +
      '<div class="alp-toast-msg">' + msg + '</div>' +
      '</div>';

    container.appendChild(toast);

    setTimeout(function () {
      toast.classList.add('alp-toast-hide');
      setTimeout(function () {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 300);
    }, 4500);
  }

  function refreshFleetViews() {
    if (typeof window.populateDevices === 'function') {
      window.populateDevices();
    }
    if (typeof window.populateNewDevices === 'function') {
      window.populateNewDevices();
    }
    if (typeof window.dashboard === 'function') {
      window.dashboard();
    }
    const wsComp = document.getElementById('workspaceComprehensiveDeviceDetails');
    if (wsComp && wsComp.style.display !== 'none' && window.CURRENT_COMP_DID) {
      if (typeof window.openComprehensiveDeviceDetails === 'function') {
        window.openComprehensiveDeviceDetails(window.CURRENT_COMP_DID, window.CURRENT_COMP_TAB || 'summary', false, true);
      }
    }
    const wsDD = document.getElementById('workspaceDeviceDetails');
    if (wsDD && wsDD.style.display !== 'none' && window.CURRENT_DETAILS_DID) {
      if (typeof window.openDeviceDetails === 'function') {
        window.openDeviceDetails(window.CURRENT_DETAILS_DID, false, window.CURRENT_DETAILS_TAB || 'groups', true);
      }
    }
  }
  window.refreshFleetViews = refreshFleetViews;

  function initWebSocket() {
    if (!window.WebSocket) {
      setStatus('offline', 'WS Unavailable');
      return;
    }

    try {
      setStatus('connecting', 'Connecting...');
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const url = `${proto}//${window.location.host}/ws`;
      ws = new WebSocket(url);

      ws.onopen = function () {
        isConnected = true;
        setStatus('connected', 'Live Sync Active');
        console.log('[ALP WS] Connected to live control-plane socket.');
      };

      ws.onmessage = function (event) {
        try {
          const msg = JSON.parse(event.data);
          if (msg.topic === 'devices') {
            const data = msg.data || {};
            if (data.added && data.added.length > 0) {
              showToast(
                'USB Device Detected',
                'Device attached: ' + data.added.join(', '),
                'success'
              );
            }
            if (data.removed && data.removed.length > 0) {
              showToast(
                'Device Disconnected',
                'Device detached: ' + data.removed.join(', '),
                'warning'
              );
            }
            refreshFleetViews();
          } else if (msg.topic === 'audit') {
            const auditData = msg.data || {};
            showToast(
              'Audit Event',
              (auditData.action || 'Activity') + ': ' + (auditData.target || 'device'),
              'info'
            );
            refreshFleetViews();
          }
        } catch (e) {
          console.debug('[ALP WS] Parse error:', e);
        }
      };

      ws.onclose = function () {
        isConnected = false;
        setStatus('connecting', 'Reconnecting...');
        if (!retryTimer) {
          retryTimer = setTimeout(function () {
            retryTimer = null;
            initWebSocket();
          }, 3500);
        }
      };

      ws.onerror = function () {
        // Silent failure if port doesn't support WS (e.g. legacy server)
        setStatus('offline', 'Offline');
      };
    } catch (e) {
      setStatus('offline', 'Offline');
    }
  }

  window.ALP_WS = {
    showToast: showToast,
    isConnected: function () {
      return isConnected;
    },
    refresh: refreshFleetViews,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initWebSocket);
  } else {
    initWebSocket();
  }
})();
