/* JOB DETAILS PAGE — rebuilt. Guards against the two failures that shipped:
 *   (a) the panel went BLANK, because it was a child of #wbWorkspace and the
 *       workspace was hidden with visibility/content-visibility;
 *   (b) opening it froze the tab (log innerHTML mirrored every SSE tick).
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "static", "pro.js"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "static", 'app.css'), "utf8");

const results = [];
const check = (n, c, x) => {
  results.push([n, !!c]);
  console.log((c ? "\u2713 " : "\u2717 FAIL ") + n.padEnd(56) + (c ? "" : " \u2014 " + (x || "")));
};

const dom = new JSDOM(html, { pretendToBeVisual: true });
const d = dom.window.document;
// jsdom reports document.hidden === true by default; the renderer deliberately
// skips work on hidden tabs, so present the page as visible for these tests.
Object.defineProperty(d, "hidden", { value: false, configurable: true });
Object.defineProperty(d, "visibilityState", { value: "visible", configurable: true });

// ---- (a) the blank-page bug ------------------------------------------
const panel = d.getElementById("jobDetailPanel");
const ws = d.getElementById("wbWorkspace");
check("details panel exists", !!panel);
check("panel is NOT inside #wbWorkspace (blank-page cause)", !ws.contains(panel));
check("panel sits in .rs-main", panel.parentElement.classList.contains("rs-main"));
check("hiding rule targets .rs-ws only, not the panel",
  /body\.rs-detail-open #tab-jobs \.rs-ws \{/.test(css) &&
  !/\.rs-ws > \*:not\(\.rs-detail\)/.test(css));
check("panel becomes visible when body has rs-detail-open",
  /body\.rs-detail-open #tab-jobs \.jd \{[^}]*visibility:\s*visible/.test(css));

// ---- structure: one concern per TAB ----------------------------------
// The page was rebuilt: the eight always-visible .jd-card sections became
// six mutually exclusive tab panels. The concerns they covered must all
// still be reachable, so assert the panels rather than the old cards.
// (Deep structural checks live in test_jd_rebuild.js.)
check("old card stack is gone", panel.querySelectorAll(".jd-card").length === 0,
  String(panel.querySelectorAll(".jd-card").length));
const tabLabels = [...panel.querySelectorAll(".jd-tab")].map(t => t.textContent.trim());
for (const want of ["Code", "Logs", "Env", "Files", "Metrics", "Settings"]) {
  check("tab present: " + want, tabLabels.includes(want), tabLabels.join(" | "));
}
// Every concern the old cards owned still has a home.
const homes = {
  "status/metrics":  "jdState",
  "controls":        "jdStart",
  "public URL":      "jdUrl",
  "live logs":       "jdLogBody",
  "env vars":        "jdEnvList",
  "downloads":       "jdDlSource",
  "run history":     "jdTimeline",
};
for (const [concern, id] of Object.entries(homes)) {
  const el = d.getElementById(id);
  check("concern still present: " + concern, !!el && !!el.closest(".jd-panel, .jd-top"),
    id);
}

// ---- every control must exist AND be wired ---------------------------
const controls = ["jobDetailBack","jdStart","jdRestart","jdStop","jdEditCode","jdDelete",
                  "jdUrlCopy","jdUrlOpen","jdHealthNow","jdCopy","jdClear","jdFollow",
                  "jdEnvAdd","jdDlSource","jdDlLogs","jdDlDb"];
for (const id of controls) check("control exists: " + id, !!d.getElementById(id));
for (const id of controls) {
  if (id === "jdUrlOpen") continue;                 // plain anchor
  check("control wired: " + id, new RegExp('"' + id + '"').test(js));
}
check("no dead 'coming soon' text", !/coming soon/i.test(panel.innerHTML));

// ---- fields the renderer writes to -----------------------------------
for (const id of ["jdName","jdLang","jdBadge","jdState","jdUptime","jdRestarts",
                  "jdLangName","jdPid","jdPort","jdUrl","jdHealth","jdHealthSub",
                  "jdLogBody","jdEnvList","jdTimeline","jdScroll"]) {
  check("render target exists: " + id, !!d.getElementById(id));
}

// ---- (b) performance guards ------------------------------------------
check("no innerHTML mirroring of the editor log pane",
  !/dst\.innerHTML\s*=\s*src\.innerHTML/.test(js));
check("renderJobDetails bails when hidden",
  /if \(!_jdOpen \|\| document\.hidden\) return;/.test(js));
check("fields update only on change (_jdText)", /function _jdText\(/.test(js));
check("health probe guarded (busy + abort)",
  /_jdHealthBusy/.test(js) && /AbortController/.test(js));
check("logs bounded + contained in CSS",
  /#tab-jobs \.jd-logs \{[^}]*contain:\s*content/.test(css));
check("scroll container does not chain to the page",
  /#tab-jobs \.jd-scroll \{[^}]*overscroll-behavior:\s*contain/.test(css));

// ---- behaviour: render with a real job -------------------------------
const w = dom.window;
global.window = w; global.document = d;
w.localStorage = {getItem: () => null, setItem: () => {}, removeItem: () => {}};

w._lastJobs = [{id: 7, name: "my-bot", language: "python", status: "running",
                uptime_s: 42, restarts: 2, runner_job_id: "abc123", port: 8100,
                web_url: "https://x.dev/live/my-bot/"}];

// Load the REAL renderer (not a copy) with its dependencies injected, so the
// assertions below exercise the shipped implementation.
const realSrc = js.slice(js.indexOf("/** Set textContent only if it differs"),
                         js.indexOf("/* ---- health check"));
const factory = new Function("document", "window", "state", `
  const _fmtStatus = s => ({label: (s || "stopped")});
  const _fmtUptime = s => s + "s";
  const _langIcon = l => (l || "py").slice(0, 2);
  const _escapeHtml = s => String(s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
  let _jdOpen = state.open;
  let _selectedJobId = state.sel;
  const closeJobDetails = () => { state.closed = true; };
  ${realSrc}
  return { renderJobDetails, setOpen: v => { _jdOpen = v; } };
`);
const api = factory(d, w, {open: true, sel: "7", closed: false});
api.renderJobDetails();

check("name rendered", d.getElementById("jdName").textContent === "my-bot");
check("status rendered", d.getElementById("jdState").textContent === "running");
check("uptime rendered", d.getElementById("jdUptime").textContent === "42s");
check("restarts rendered", d.getElementById("jdRestarts").textContent === "2");
check("runner id rendered", d.getElementById("jdPid").textContent === "abc123");
check("URL card shown for a running job with a url", d.getElementById("jdUrlCard").hidden === false);
check("URL text filled", d.getElementById("jdUrl").textContent.includes("live/my-bot"));
check("run history got an entry", d.getElementById("jdTimeline").children.length === 1);
check("page is NOT blank", d.getElementById("jdScroll").textContent.trim().length > 40);

// stopped job: URL card hides, buttons flip
w._lastJobs[0].status = "stopped";
api.renderJobDetails();
check("URL card hidden when stopped", d.getElementById("jdUrlCard").hidden === true);
check("Start enabled when stopped", d.getElementById("jdStart").disabled === false);
check("Stop disabled when stopped", d.getElementById("jdStop").disabled === true);
check("history appended on state change", d.getElementById("jdTimeline").children.length === 2);

// ---- full-screen: the surrounding chrome must be hidden ---------------
check("Details page is position:fixed (owns the viewport)",
  /#tab-jobs \.jd \{[^}]*position:\s*fixed/.test(css));
check("Details page covers the full viewport (inset:0)",
  /#tab-jobs \.jd \{[^}]*inset:\s*0/.test(css));
/* The layer order is a named ladder now (--z-sticky ... --z-fatal), declared
   once at :root, because it used to be 29 ad-hoc numbers with two selectors
   declared twice at different values. Assert the ORDER, which is the thing
   that matters, instead of a literal that has to be edited whenever the
   ladder is renumbered. */
const { zValue } = require('./zlayers');
const zm = css.match(/#tab-jobs \.jd \{[^}]*z-index:\s*([^;]+);/);
const jdZ = zm && zValue(zm[1]);
check("z-index is above the bottom nav and the drawers",
  jdZ > zValue('var(--z-nav)') && jdZ >= zValue('var(--z-drawer)'), String(jdZ));
check("z-index stays below toasts and modals, which must interrupt it",
  jdZ < zValue('var(--z-toast)') && jdZ < zValue('var(--z-modal)'), String(jdZ));
check("CodeNest dashboard bar hidden while open",
  /body\.rs-detail-open \.dash-bar[\s\S]{0,260}?display:\s*none/.test(css));
// The shell rebuild replaced .rs-bar + .rs-ed-bar with one .rs-head and a
// .rs-meta strip. The BEHAVIOUR under test is unchanged: no RunSpace chrome
// may remain visible behind the full-screen Details page.
check("RunSpace header hidden while open",
  /body\.rs-detail-open #tab-jobs \.rs-head[\s\S]{0,240}?display:\s*none/.test(css));
check("RunSpace meta strip hidden while open",
  /body\.rs-detail-open #tab-jobs \.rs-meta[\s\S]{0,240}?display:\s*none/.test(css));
check("mobile bottom nav hidden while open",
  /body\.rs-detail-open \.bottom-nav[\s\S]{0,240}?display:\s*none/.test(css));
check("job sidebar hidden while open",
  /body\.rs-detail-open #tab-jobs \.rs-side[\s\S]{0,160}?display:\s*none/.test(css));
check("page behind is scroll-locked at every width",
  /^body\.rs-detail-open \{ overflow: hidden; \}/m.test(css));
check("no mobile override pushing it under the nav",
  !/#tab-jobs \.jd \{ position: fixed; z-index: 300; \}/.test(css));
check("header keeps clear of the notch (safe-area)",
  /#tab-jobs \.jd-top \{[^}]*env\(safe-area-inset-top/.test(css));

const p = results.filter(r => r[1]).length, f = results.length - p;
console.log(`\n================ ${p} pass, ${f} fail ================`);
process.exit(f ? 1 : 0);
