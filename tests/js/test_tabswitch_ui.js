/* Tab-switch UI: stale-status guard (§1 client half), progress bar (§2),
   status animation (§3). */
const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..", "..");
const js = fs.readFileSync(path.join(ROOT, "static", "pro.js"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "static", 'app.css'), "utf8");

const results = [];
const check = (n, c, x) => {
  results.push([n, !!c]);
  console.log((c ? "\u2713 " : "\u2717 FAIL ") + n.padEnd(58) + (c ? "" : " \u2014 " + (x || "")));
};

// ---- §1 client half -----------------------------------------------------
check("every switch re-fetches from the server", /fetchJobDetail\(id\)/.test(js));
check("an 'unknown' reply never overwrites a known status",
  /if \(job\.status_stale && idx >= 0\)[\s\S]{0,240}prev\.status !== "unknown"/.test(js));
check("stale replies schedule an automatic re-check", /_scheduleStatusRecheck\(id\)/.test(js));
check("re-check backs off and gives up", /if \(attempt > 4\)/.test(js) && /attempt \* 1500/.test(js));
check("re-check stops if the user switched away",
  /if \(String\(_selectedJobId\) !== id\) return;/.test(js));
check("silent re-check never rewrites the editor buffer",
  /if \(!opts\.silent && !_jobDirty && curCode !== \(job\.code \|\| ""\)\)/.test(js));
check("'unknown' has a neutral label, not STOPPED", /"unknown":\s*\{[^}]*CHECKING/.test(js));
check("log stream is reset on switch (no stale buffer)",
  /function restartLogStream[\s\S]{0,80}stopLogStream\(\);[\s\S]{0,40}_renderLogs\(""\)/.test(js));

// ---- §2 progress bar ----------------------------------------------------
check("bar starts the instant a switch begins",
  /_progressStart\(\);\s*\n\s*\/\/ Kick off data/.test(js));
check("bar is released when the fetch settles", /fetchJobDetail\(id\)\.finally\(\(\) => _progressDone\(\)\)/.test(js));
check("nested loads share one bar", /_progDepth\+\+;[\s\S]{0,60}if \(_progDepth > 1\) return;/.test(js));
check("crawl approaches ~90% asymptotically",
  /const remaining = 0\.9 - _progVal;/.test(js) && /remaining \* 0\.12/.test(js));
check("completion snaps to 100% then fades",
  /_progressSet\(1\);[\s\S]{0,80}classList\.add\("done"\)/.test(js));
check("bar animates with transform, never width",
  /_progressSet[\s\S]{0,160}transform = "scaleX\(/.test(js));
check("bar CSS uses scaleX + will-change",
  /\.rs-progress-fill \{[^}]*transform: scaleX\(0\)/.test(css) &&
  /\.rs-progress-fill \{[^}]*will-change: transform/.test(css));
check("bar CSS never transitions width",
  !/\.rs-progress-fill \{[^}]*transition:[^;]*width/.test(css));
check("bar is thin and pinned to the top",
  /\.rs-progress \{[^}]*height: 3px/.test(css) && /\.rs-progress \{[^}]*top: 0/.test(css));
/* Named layer ladder — see tests/js/zlayers.js. The progress bar must outrank
   the Details page; both are now tokens, so compare the resolved layers. */
const { zValue } = require('./zlayers');
const z = css.match(/\.rs-progress \{[^}]*z-index:\s*([^;]+);/);
const barZ = z && zValue(z[1]);
check("bar sits above the Details page",
  barZ > zValue('var(--z-panel)'), String(barZ));

// ---- §3 status animation ------------------------------------------------
check("status dots cross-fade rather than flip",
  /#tab-jobs \.rs-status-dot,[\s\S]{0,220}transition: background-color \.18s/.test(css));
check("running dots stay static (no continuous animation tax)",
  /\.jstatus-dot\.running \{[\s\S]{0,180}animation: none/.test(css));
check("old infinite pulse is removed",
  !/animation: rsStatusPulse 1\.8s ease-in-out infinite/.test(css));
check("'checking' is visually distinct from stopped",
  /\.jstatus-dot\.checking,[\s\S]{0,160}background: var\(--warn\)/.test(css));
check("label feedback stays compositor-only",
  /_reflectJobStatus\._last !== st\.label/.test(js) &&
  /b\.animate\(\[\{opacity:/.test(js) && !/void b\.offsetWidth/.test(js));
check("reduced-motion disables the pulse",
  /@media \(prefers-reduced-motion: reduce\)[\s\S]{0,260}jd-badge \{ animation: none/.test(css));

const p = results.filter(r => r[1]).length, f = results.length - p;
console.log(`\n================ ${p} pass, ${f} fail ================`);
process.exit(f ? 1 : 0);
