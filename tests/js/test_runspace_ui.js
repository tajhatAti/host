/* RunSpace UI regressions:
 *   1. Typing in a NEW job's editor got wiped ~7s later — the jobs poll
 *      auto-selected an existing job because the guard was a 1500ms timer.
 *   2. index.html shipped a hardcoded ?v= stamp, so deploys served stale
 *      CSS/JS and fixes looked like they never shipped.
 *   3. Toolbar controls had drifted to different heights/fonts.
 *   4. The bottom nav overlapped RunSpace.
 */
const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..", "..");
const js = fs.readFileSync(path.join(ROOT, "static", "pro.js"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "static", 'app.css'), "utf8");
const appPy = fs.readFileSync(path.join(ROOT, "app.py"), "utf8");

const results = [];
const check = (n, c, x) => {
  results.push([n, !!c]);
  console.log((c ? "\u2713 " : "\u2717 FAIL ") + n.padEnd(58) + (c ? "" : " \u2014 " + (x || "")));
};

// ---- 1. new-job editor must not be stolen by polling -------------------
check("a persistent _composingNew flag exists", /let _composingNew = false;/.test(js));
check("'New' sets the flag", /_composingNew = true;/.test(js));
check("selecting an existing job clears it",
  /_selectedJobId = id;[\s\S]{0,120}?_composingNew = false;/.test(js));
check("a successful deploy clears it", /_jobDirty = false;\s*\n\s*_composingNew = false;/.test(js));
check("renderJobs refuses to auto-select while composing",
  /else if \(_composingNew \|\| Date\.now\(\) < _suppressAutoSelect\)/.test(js));
check("unsaved edits are never overwritten by a poll",
  /if \(cur && !_jobDirty\) \{ _showWorkspace\(cur\)/.test(js));

// ---- 2. cache busting ---------------------------------------------------
check("asset version derives from real file state", /def _asset_version\(\)/.test(appPy));
// Signature now takes an optional request, so the shell can strip the admin
// console for non-admins. Match the name, not the exact parameter list.
check("index.html is rewritten with the live stamp", /def _index_html\(/.test(appPy));
check("no hardcoded ?v= is served", !/FileResponse\(INDEX_FILE\)/.test(appPy));
check("HTML itself is sent no-cache", /Cache-Control": "no-cache, must-revalidate/.test(appPy));

// ---- 3. one consistent control size ------------------------------------
// The shell was rebuilt: Run/Stop/Restart/Details/Close moved out of a second
// wrapping toolbar into the header's segmented group, and what remains beside
// the editor is a fixed-height metadata strip. The INTENT of this section is
// unchanged — every control derives from one height token — so the assertions
// now target the surviving elements instead of the deleted .rs-ed-bar.
check("a single height token drives the controls", /--rs-ctl-h:\s*\d+px/.test(css));
const shared = css.match(/#tab-jobs \.rs-inp,\s*\n#tab-jobs \.rs-sel \{[\s\S]{0,400}?\}/);
check("inputs and select share one rule", !!shared);
check("shared rule sets height from the token",
  shared && /height:\s*var\(--rs-ctl-h\)/.test(shared[0]));
check("shared rule sets one radius", shared && /border-radius:\s*var\(--rs-ctl-r\)/.test(shared[0]));
check("shared rule sets one font-size", shared && /font-size:\s*var\(--rs-ctl-fs\)/.test(shared[0]));
check("language select no longer uses a different font",
  /#tab-jobs \.rs-sel \{[^}]*font-family:\s*inherit/.test(css));
check("ghost buttons use the same height token",
  /#tab-jobs \.rs-ghost-btn \{[^}]*height:\s*var\(--rs-ctl-h\)/.test(css));
check("segmented group uses the same height token",
  /#tab-jobs \.rs-seg \{[^}]*height:\s*var\(--rs-ctl-h\)/.test(css));
/* "Bigger" was written as 3x px when the desktop size was 28px, so 30-39
   counted as an improvement. The floor that actually matters is 44px (Apple
   HIG and Material both put a touch target there), and the controls now
   reach it — a rule that only accepted 3x px would REJECT the correct value
   and lock in the too-small one. Assert the guideline, not the old range. */
const mobileCtl = /@media \(max-width: 760px\)[\s\S]*?--rs-ctl-h:\s*(\d+)px/.exec(css);
check("tap targets reach the 44px guideline on mobile",
  !!mobileCtl && +mobileCtl[1] >= 44, mobileCtl ? mobileCtl[1] + 'px' : 'no rule');
// The old bar WRAPPED, which is exactly why it looked disorganised: at 412px
// it broke into ~3 rows and changed height between renders. The replacement
// must scroll, never rearrange.
check("meta strip never wraps",
  /#tab-jobs \.rs-meta \{[^}]*flex-wrap:\s*nowrap/.test(css));
check("meta strip scrolls when tight",
  /#tab-jobs \.rs-meta \{[^}]*overflow-x:\s*auto/.test(css));

// ---- 4. global navigation remains available ----------------------------
check("bottom nav remains visible on mobile RunSpace",
  /body\.rs-active:not\(\.rs-detail-open\) \.bottom-nav \{ display:flex !important; \}/.test(css));
check("RunSpace reserves the bottom-nav height",
  /body\.rs-active:not\(\.rs-detail-open\) \.dash-main \{[^}]*padding-bottom:calc\(var\(--bottom-nav-h\)/.test(css));
check("bottom nav hidden on the Details page",
  /body\.rs-detail-open[\s\S]{0,240}?\.bottom-nav[\s\S]{0,240}?display:\s*none/.test(css));

const p = results.filter(r => r[1]).length, f = results.length - p;
console.log(`\n================ ${p} pass, ${f} fail ================`);
process.exit(f ? 1 : 0);
