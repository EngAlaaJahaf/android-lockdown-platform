/**
 * Runtime + handler-reference check for the inline UI script in webui/index.html.
 *
 * `node --check` only validates syntax. This harness goes further:
 *
 *   1. Executes the script against minimal DOM stubs. A stray statement left
 *      behind by a bad text edit (a function body that lost its header) throws
 *      ReferenceError here, which in the browser would kill the whole UI.
 *   2. Then compares every function the script defined against every name used
 *      in an onclick="" handler, so a stale reference fails the check instead of
 *      silently doing nothing when the admin clicks.
 *
 * Usage:  node scripts/webui_inline_runtime.js [path/to/index.html]
 * Exit code 1 means the UI script will not run or has a dangling handler.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

const ROOT = path.dirname(__dirname);
const HTML = process.argv[2] || path.join(ROOT, 'webui', 'index.html');
const html = fs.readFileSync(HTML, 'utf8');

/* ------------------------------------------------------------------ extract
   Inline blocks PLUS local <script src="..."> files, in document order, so
   onclick handler resolution sees the real implementation (the console logic
   lives in webui/assets/*.js, not inline). Remote URLs are skipped: they are
   third-party code, not ours to verify. A src that points at a missing local
   file fails the check — a dangling script tag is a bug of its own. */
const scripts = [...html.matchAll(
  /<script([^>]*)>([\s\S]*?)<\/script>/g)];
const blocks = [];
for (const m of scripts) {
  const attrs = m[1];
  const srcMatch = attrs.match(/\bsrc\s*=\s*"([^"]*)"/);
  if (!srcMatch) {
    blocks.push(m[2]);
    continue;
  }
  const src = srcMatch[1];
  if (/^(https?:)?\/\//.test(src) || src.startsWith('data:')) continue;
  const file = path.resolve(path.dirname(HTML), src.split('?')[0]);
  if (!fs.existsSync(file)) {
    console.error(`missing local script file: ${src} (referenced from ${HTML})`);
    process.exit(1);
  }
  // Vendor bundles (jQuery, ManageEngine engine/vendor chunks) are
  // third-party code: their presence is verified above, but executing them
  // against DOM stubs proves nothing about our code and jQuery's own
  // feature-detection throws outside a real browser. Only first-party
  // scripts (assets/alp-*.js) plus the inline blocks are executed.
  if (/\/me\/|jquery/i.test(src)) continue;
  blocks.push(`\n/* ---- ${src} ---- */\n` + fs.readFileSync(file, 'utf8'));
}
if (!blocks.length) {
  console.error('no script found in ' + HTML);
  process.exit(1);
}
const code = blocks.join('\n;\n');
console.log(`inline script blocks: ${blocks.length} (${code.length} bytes)`);

/* ------------------------------------------------------------- DOM stubs */
function stubElement(tag) {
  const el = {
    tagName: (tag || 'div').toUpperCase(),
    style: {},
    dataset: {},
    children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    value: '', innerHTML: '', textContent: '', disabled: false,
    appendChild(c) { this.children.push(c); return c; },
    setAttribute() {}, getAttribute: () => null, removeAttribute() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
    insertAdjacentHTML(pos, html) { this._inserted = (this._inserted || '') + html; },
    querySelector: () => null, querySelectorAll: () => [],
    closest: () => null, focus() {}, blur() {}, click() {},
    getBoundingClientRect: () => ({ top: 0, left: 0, width: 0, height: 0 }),
  };
  return el;
}

const doc = {
  body: stubElement('body'),
  documentElement: stubElement('html'),
  readyState: 'complete',
  // Every lookup resolves to a stub: the goal is to reach the end of the
  // script and prove no statement throws, not to simulate rendering.
  getElementById: () => stubElement('div'),
  querySelector: () => stubElement('div'),
  querySelectorAll: () => [],
  createElement: (t) => stubElement(t),
  createTextNode: (t) => ({ textContent: t }),
  addEventListener() {}, removeEventListener() {},
  cookie: '',
  title: '',
};

const listeners = [];
const win = {
  document: doc,
  location: { hash: '', href: 'http://127.0.0.1/', pathname: '/', search: '', assign() {}, replace() {} },
  history: { pushState() {}, replaceState() {}, back() {}, forward() {} },
  localStorage: {
    _m: new Map(),
    getItem(k) { return this._m.has(k) ? this._m.get(k) : null; },
    setItem(k, v) { this._m.set(k, String(v)); },
    removeItem(k) { this._m.delete(k); },
    clear() { this._m.clear(); },
  },
  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {}, clear() {} },
  navigator: { userAgent: 'node', clipboard: { writeText: () => Promise.resolve() } },
  matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
  getComputedStyle: () => ({ getPropertyValue: () => '' }),
  requestAnimationFrame: (cb) => setTimeout(cb, 0),
  cancelAnimationFrame: () => {},
  addEventListener(type, fn) { listeners.push([type, fn]); },
  removeEventListener() {},
  open: () => null, close() {}, focus() {}, alert() {}, scrollTo() {},
  setTimeout, clearTimeout, setInterval, clearInterval,
  console, fetch: () => Promise.reject(new Error('fetch is stubbed')),
  URL, URLSearchParams, TextEncoder, TextDecoder, AbortController,
  Headers: function Headers() {}, FormData: function FormData() {},
  Blob: function Blob() {}, FileReader: function FileReader() {},
  CryptoKey: undefined,
};

/* ---------------------------------------------------------------- run it */
let loadError = null;
try { globalThis.window = win; } catch (_) {}
try { globalThis.self = win; } catch (_) {}
try { globalThis.global = globalThis; } catch (_) {}
for (const n of Object.keys(win)) {
  try { globalThis[n] = win[n]; } catch (_) { /* read-only global */ }
}
// `document` is read-only on globalThis in some node builds
try { globalThis.document = doc; } catch (_) {}

try {
  // Indirect eval keeps the script in sloppy mode, like an inline <script>.
  (0, eval)(code);
} catch (e) {
  loadError = e;
}

if (loadError) {
  console.error('\nLOAD-TIME ERROR (the whole UI script would fail in a browser):');
  console.error('  ' + loadError.name + ': ' + loadError.message);
  const m = String(loadError.stack || '').match(/<anonymous>:(\d+):(\d+)/);
  if (m) {
    const src = code.split('\n');
    const n = Number(m[1]);
    for (let i = Math.max(0, n - 4); i < Math.min(src.length, n + 3); i++) {
      console.error(`  ${String(i + 1).padStart(5)}${i + 1 === n ? ' >' : '  '} ${src[i]}`);
    }
  } else {
    console.error('  ' + String(loadError.stack || '').split('\n').slice(0, 4).join('\n  '));
  }
  process.exit(1);
}
console.log('load: OK (no top-level error)');

/* --------------------------------------------------- handler references */
const defined = new Set(Object.getOwnPropertyNames(globalThis));
// Top-level `const`/`let` in an eval do not become globalThis properties, so
// also collect declared names textually.
const srcRe = /\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(|\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(?:function\b|\(|[A-Za-z_$][\w$]*\s*=>)|\bwindow\.([A-Za-z_$][\w$]*)\s*=/g;
let mm;
while ((mm = srcRe.exec(code))) {
  if (mm[1]) defined.add(mm[1]);
  else if (mm[2]) defined.add(mm[2]);
  else if (mm[3]) defined.add(mm[3]);
}

const BUILTINS = new Set([
  'if', 'for', 'while', 'switch', 'catch', 'return', 'typeof', 'await', 'function',
  'String', 'Number', 'Boolean', 'Array', 'Object', 'JSON', 'Math', 'Date', 'Promise',
  'Set', 'Map', 'RegExp', 'Error', 'parseInt', 'parseFloat', 'isNaN', 'setTimeout',
  'setInterval', 'clearTimeout', 'clearInterval', 'fetch', 'confirm', 'prompt', 'alert',
  'encodeURIComponent', 'decodeURIComponent', 'encodeURI', 'decodeURI', 'require',
]);

const attrs = [...html.matchAll(/on(?:click|change|input|submit|load|keydown)\s*=\s*"([^"]*)"/g)]
  .map((m) => m[1]);
const used = new Map();
for (const a of attrs) {
  // `${...}` inside a template literal is evaluated when the script renders the
  // row, not when the admin clicks, so those names are not attribute targets.
  const attr = a.replace(/\$\{[^}]*\}/g, '');
  for (const call of attr.matchAll(/(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(/g)) {
    const name = call[1];
    if (BUILTINS.has(name)) continue;
    if (!used.has(name)) used.set(name, a.slice(0, 70));
  }
}
const missing = [...used.keys()].filter((n) => !defined.has(n));
console.log(`onclick handler targets: ${used.size} distinct, undefined: ${missing.length}`);
for (const n of missing) {
  console.log(`   UNDEFINED HANDLER: ${n}  <-  ${used.get(n)}`);
}

console.log(`\nRESULT: ${missing.length ? 'PROBLEMS FOUND' : 'clean'}`);
process.exit(missing.length ? 1 : 0);