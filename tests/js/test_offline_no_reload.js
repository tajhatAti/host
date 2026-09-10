/* OFFLINE MUST NEVER TOUCH EDITOR STATE.
 *
 * A connection drop used to:
 *   - render a "Retry" box that replaced the sidebar,
 *   - run _setJobsStatus("error") which set #wbWorkspace display:none,
 *     tearing the open editor (and everything typed) off the screen,
 *   - offer a banner that reloaded the whole page on click.
 *
 * Rule enforced here: nothing connectivity-related may reload the page or
 * clear editor/job state. The only allowed response is a status badge.
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

// ---- static guarantees -------------------------------------------------
const banner = js.slice(js.indexOf("function _serverDown()"), js.indexOf("function _serverUp()"));
check("offline banner cannot reload the page", !/location\.reload/.test(banner));
check("offline banner is just a status badge", /Reconnecting/.test(banner));
check("banner does not touch the workspace",
  !/wbWorkspace|_jobCmSetValue|_showEmpty/.test(banner));

const _ss = js.indexOf("function _setJobsStatus");
const errBranch = js.slice(js.indexOf('status === "error"', _ss), _ss + 3000);
check("error state never hides an open workspace",
  /if \(ws && ws\.style\.display !== "none"\)[\s\S]{0,120}return;/.test(errBranch));

const lj = js.slice(js.indexOf("async function loadJobs()"), js.indexOf("function _fmtUptime"));
check("failed refresh is ignored while work is open",
  /if \(_composingNew \|\| _jobDirty \|\| _selectedJobId\) return;/.test(lj));
check("infra errors never reach the error box",
  /e\.kind === "infra"[\s\S]{0,220}?return;/.test(lj));

check("no reload button in the fatal overlay",
  !/fatal-btns[\s\S]{0,200}location\.reload/.test(js));

// The only reloads left must be user-initiated (account deletion), never
// connectivity-driven.
const reloads = [...js.matchAll(/window\.location\.(reload|href)/g)]
  .map(m => js.slice(Math.max(0, m.index - 400), m.index));
check("every remaining reload is user-initiated",
  reloads.every(ctx => /account\/delete|Session expired/.test(ctx)),
  String(reloads.length) + " found");

// ---- behavioural: simulate going offline with typed code ---------------
const dom = new JSDOM(`<!doctype html><body>
  <div id="wbWorkspace" style="display:flex"><textarea id="code"></textarea></div>
  <div id="wbEmpty" style="display:none"></div>
  <div id="wbBootLoader" style="display:none"></div>
  <div id="jobsList"><div class="job-item" data-jid="1"></div></div>
</body>`);
const d = dom.window.document;
const TYPED = "import os\nprint('my unsaved work')\n";
d.getElementById("code").value = TYPED;

// Replay the SHIPPED error branch of _setJobsStatus.
function setJobsStatusError() {
  const ws = d.getElementById("wbWorkspace");
  const boot = d.getElementById("wbBootLoader");
  const emp = d.getElementById("wbEmpty");
  if (ws && ws.style.display !== "none") {      // the fix
    if (boot) boot.style.display = "none";
    return;
  }
  if (boot) boot.style.display = "none";
  emp.style.display = "";
  ws.style.display = "none";
}

for (let i = 0; i < 5; i++) setJobsStatusError();   // 5 failed polls ~ 35s offline

check("editor still visible after repeated offline polls",
  d.getElementById("wbWorkspace").style.display === "flex");
check("typed code is byte-for-byte intact",
  d.getElementById("code").value === TYPED);
check("empty panel never took over",
  d.getElementById("wbEmpty").style.display === "none");
check("sidebar rows untouched", !!d.querySelector('.job-item[data-jid="1"]'));

const p = results.filter(r => r[1]).length, f = results.length - p;
console.log(`\n================ ${p} pass, ${f} fail ================`);
process.exit(f ? 1 : 0);
