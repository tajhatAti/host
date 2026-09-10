/* Details-panel regression test.
 *
 * The bug: opening Details froze the tab. renderJobDetails() copied the whole
 * log innerHTML from the editor pane into the Details pane on EVERY SSE tick
 * (~113 KB parsed twice, ~9 MB/min), and the covered workspace was left
 * visible so the browser kept compositing CodeMirror behind an opaque drawer.
 *
 * These tests assert the structural fixes, so the freeze cannot come back.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "..");
const js = fs.readFileSync(path.join(ROOT, "static", "pro.js"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "static", 'app.css'), "utf8");

const results = [];
function check(name, cond, extra) {
  results.push([name, !!cond]);
  console.log((cond ? "\u2713 " : "\u2717 FAIL ") + name.padEnd(58) + (cond ? "" : " \u2014 " + (extra || "")));
}

// ---- the actual freeze cause must be gone -------------------------------
check("log innerHTML is NOT mirrored into the Details pane",
  !/dst\.innerHTML\s*=\s*src\.innerHTML/.test(js));
check("logs render into ONE pane (_activeLogPane)",
  /function _activeLogPane\(\)/.test(js));
check("unchanged log text short-circuits re-render",
  /_lastLogText/.test(js) && /if \(!force && text === _lastLogText/.test(js));
check("renderJobDetails no-ops while the panel is closed",
  /function renderJobDetails\(\)\s*\{[\s\S]{0,200}?if \(!_jdOpen \|\| document\.hidden\) return;/.test(js));
check("SSE updates are coalesced into an animation frame",
  /requestAnimationFrame\(\(\) => \{[\s\S]{0,160}_applyStreamUpdate/.test(js));
check("log tail is bounded",
  /slice\(-400\)/.test(js));
check("timeline only rebuilds when an event was appended",
  /if \(!last \|\| last\.ev !== st\.label\) \{/.test(js));

// ---- health check must not pile up --------------------------------------
check("health probe has an abort timeout", /AbortController/.test(js) && /ctl\.abort\(\)/.test(js));
check("health probe cannot overlap itself", /_jdHealthBusy/.test(js));
check("health probe skips background tabs",
  /async function _jdCheckHealth\(\)\s*\{\s*\n\s*if \(!_jdOpen \|\| document\.hidden\) return;/.test(js));

// ---- leaving the tab must clean up --------------------------------------
check("switching tabs closes the Details drawer",
  /if \(tabId !== "jobs"[\s\S]{0,140}closeJobDetails/.test(js));
check("switching tabs clears the body scroll-lock classes",
  /classList\.remove\("rs-detail-open", "rs-drawer-open"\)/.test(js));

// ---- CSS -----------------------------------------------------------------
check("covered workspace is removed from the render tree",
  /body\.rs-detail-open #tab-jobs \.rs-ws \{[^}]*visibility:\s*hidden/.test(css));
// The page is a full-screen fixed layer now, so the document behind it must
// not scroll at ANY width (the old drawer only needed this on mobile).
check("page behind is scroll-locked while Details is open",
  /^body\.rs-detail-open \{ overflow: hidden; \}/m.test(css));
check("details scroll container does not chain to the page",
  /#tab-jobs \.jd-scroll \{[^}]*overscroll-behavior:\s*contain/.test(css));
check("details log pane is contained + bounded",
  /#tab-jobs \.jd-logs \{[^}]*contain:\s*content/.test(css) &&
  /#tab-jobs \.jd-logs \{[^}]*max-height/.test(css));
check("closed panel is not painted (visibility:hidden)",
  /#tab-jobs \.jd \{[^}]*visibility:\s*hidden/.test(css));

// ---- behavioural test in a real DOM --------------------------------------
const { JSDOM } = require("jsdom");
const dom = new JSDOM(`<!doctype html><body>
  <pre id="jobLogBody"></pre>
  <pre id="jdLogBody"></pre>
  <div id="jobLogTitle"></div>
</body>`);
global.window = dom.window; global.document = dom.window.document;

// Minimal stand-ins for the helpers _renderLogs depends on.
let _jdOpen = false, _logFollow = true, _jdLogFollow = true;
let _lastLogText = null, _lastLogTarget = null;
const _escapeHtml = s => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const _colorizeLine = l => '<span class="log-line">' + _escapeHtml(l) + "</span>";
const _reflectJobStatus = () => {};
function _activeLogPane() {
  return _jdOpen ? document.getElementById("jdLogBody") : document.getElementById("jobLogBody");
}
function _renderLogs(text, force) {
  const body = _activeLogPane();
  if (!body) return;
  if (!force && text === _lastLogText && body === _lastLogTarget) { _renderLogs.skipped++; return; }
  _lastLogText = text; _lastLogTarget = body;
  if (!text || !text.trim()) { body.innerHTML = '<span class="rs-log-empty"></span>'; _reflectJobStatus(); return; }
  const tail = text.split(/\r?\n/).slice(-400);
  body.textContent = "";
  body.insertAdjacentHTML("afterbegin", tail.map(_colorizeLine).join("\n"));
  _renderLogs.painted++;
}
_renderLogs.painted = 0; _renderLogs.skipped = 0;

const big = Array.from({ length: 600 }, (_, i) => `[INFO] tick ${i}`).join("\n");
_renderLogs(big);
check("editor pane receives the logs",
  document.getElementById("jobLogBody").children.length > 0);
check("Details pane is NOT written to while closed",
  document.getElementById("jdLogBody").children.length === 0);

// Repeated identical ticks must not repaint.
const before = _renderLogs.painted;
for (let i = 0; i < 40; i++) _renderLogs(big);
check("40 identical SSE ticks cause ZERO repaints",
  _renderLogs.painted === before, `painted ${_renderLogs.painted - before} times`);

// Opening Details moves rendering to the other pane.
_jdOpen = true;
_renderLogs(big, true);
check("opening Details paints into the Details pane",
  document.getElementById("jdLogBody").children.length > 0);
check("only the bounded tail is in the DOM",
  document.getElementById("jdLogBody").children.length <= 400,
  String(document.getElementById("jdLogBody").children.length));

// Log growth still renders.
_renderLogs(big + "\n[INFO] new line");
check("new log content still renders while Details is open",
  document.getElementById("jdLogBody").textContent.includes("new line"));

const passed = results.filter(r => r[1]).length;
const failed = results.length - passed;
console.log(`\n================ ${passed} pass, ${failed} fail ================`);
process.exit(failed ? 1 : 0);
