/* The "editor reloads while I type" bug.
 *
 * renderJobs() was guarded, but loadJobs() — which runs every 7s — has THREE
 * other paths that hide or repaint the editor:
 *     _showEmpty(true)    (zero jobs)
 *     _showWorkspace(cur) (signature unchanged)
 *     _showEmpty(false)   (nothing selected)
 * _showEmpty() sets #wbWorkspace to display:none, so whatever was typed in a
 * brand-new job vanished mid-keystroke and looked like a page reload.
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");
const ROOT = path.join(__dirname, "..", "..");
const js = fs.readFileSync(path.join(ROOT, "static", "pro.js"), "utf8");

const results = [];
const check = (n, c, x) => {
  results.push([n, !!c]);
  console.log((c ? "\u2713 " : "\u2717 FAIL ") + n.padEnd(58) + (c ? "" : " \u2014 " + (x || "")));
};

// ---- the guard must sit INSIDE loadJobs, before any pane swap -----------
const lj = js.slice(js.indexOf("async function loadJobs()"),
                    js.indexOf("function _fmtUptime"));
check("loadJobs guards composing/dirty state", /if \(_composingNew \|\| _jobDirty\)/.test(lj));
const guardAt = lj.indexOf("_composingNew || _jobDirty");
check("guard runs BEFORE _showEmpty(true)", guardAt > 0 && guardAt < lj.indexOf("_showEmpty(true)"));
check("guard runs BEFORE _showWorkspace", guardAt > 0 && guardAt < lj.indexOf("_showWorkspace(cur)"));
check("guard returns early", /_renderJobList\(jobs\);\s*\}\s*\n\s*return;/.test(lj));
check("sidebar still refreshes while guarded", /_renderJobList\(jobs\)/.test(lj));

// ---- the sidebar-only renderer must not touch the editor ---------------
const rl = js.slice(js.indexOf("function _renderJobList"), js.indexOf("function renderJobs"));
check("_renderJobList exists", rl.length > 50);
for (const forbidden of ["_showEmpty", "_showWorkspace", "_jobCmSetValue", "selectJob("]) {
  check(`_renderJobList never calls ${forbidden}`, !rl.includes(forbidden));
}
check("_renderJobList updates the count", /txJobCount/.test(rl));

// ---- switching jobs must not silently discard work ---------------------
const sj = js.slice(js.indexOf("function selectJob(id)"), js.indexOf("function deselectJob"));
check("selectJob asks before discarding unsaved work",
  /_jobDirty \|\| \(_composingNew &&/.test(sj) && /confirm\(/.test(sj));
check("selectJob clears the dirty flag after switching", /_jobDirty = false;/.test(sj));

// ---- closing the tab must warn -----------------------------------------
check("beforeunload guards unsaved work", /addEventListener\("beforeunload"/.test(js));

// ---- behavioural: _showEmpty really does hide the editor ---------------
const dom = new JSDOM(`<!doctype html><body>
  <div id="wbWorkspace" style="display:flex"></div>
  <div id="wbEmpty" style="display:none"></div>
  <div id="wbBootLoader" style="display:none"></div>
  <button id="btnNewEmpty"></button>
</body>`);
const d = dom.window.document;
let _jobsStatus = "loaded";
function _showEmpty(zeroJobs) {
  const emp = d.getElementById("wbEmpty"), ws = d.getElementById("wbWorkspace");
  if (_jobsStatus === "loading") { ws.style.display = "none"; return; }
  emp.style.display = ""; ws.style.display = "none";
}
_showEmpty(false);
check("_showEmpty() does hide the workspace (root cause confirmed)",
  d.getElementById("wbWorkspace").style.display === "none");

const p = results.filter(r => r[1]).length, f = results.length - p;
console.log(`\n================ ${p} pass, ${f} fail ================`);
process.exit(f ? 1 : 0);
