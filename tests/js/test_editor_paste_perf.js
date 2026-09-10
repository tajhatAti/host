/* LARGE-PASTE PERFORMANCE.
 *
 * Finding: the editors ARE CodeMirror 5 (not naive custom highlighting), so
 * tokenising was never the problem. The cost was in OUR change handlers,
 * which ran synchronously on every single change:
 *     ta.value = cm.getValue()      full-document serialise
 *     _updateStats() -> getValue()  a SECOND full serialise + split("\n")
 *     _reflectJobStatus()           ~21 DOM reads/writes -> forced layout
 * Code Studio additionally rebuilt the entire line-number gutter string.
 *
 * Fix: coalesce into one animation frame, count lines with CM's O(1)
 * lineCount(), drop the redundant textarea mirror, and skip identical writes.
 */
const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..", "..");
const js = fs.readFileSync(path.join(ROOT, "static", "pro.js"), "utf8");

const results = [];
const check = (n, c, x) => {
  results.push([n, !!c]);
  console.log((c ? "\u2713 " : "\u2717 FAIL ") + n.padEnd(58) + (c ? "" : " \u2014 " + (x || "")));
};

// ---- a real editor library is in use (not custom highlighting) ---------
check("RunSpace editor is CodeMirror 6", /_jobCm = CN6\.create\(/.test(js));
check("Code Studio editor is CodeMirror 6", /cmEditor = CN6\.create\(/.test(js));

// ---- RunSpace change handler -------------------------------------------
const jobH = js.slice(js.indexOf("_jobCm = CN6.create("), js.indexOf("let _chgRaf = 0;"));
check("job handler coalesces into one frame", /requestAnimationFrame/.test(jobH));
check("job handler guards against re-entry", /if \(_chgRaf\) return;/.test(jobH));
check("job handler no longer mirrors into the textarea",
  !/ta\.value = /.test(jobH));
check("toolbar repaint only on dirty transition", /if \(!wasDirty\) _reflectJobStatus/.test(jobH));
check("programmatic loads skip the handler", /if \(_jobCmLoading\) return;/.test(jobH));

// ---- Code Studio change handler ----------------------------------------
const csH = js.slice(js.indexOf("cmEditor = CN6.create("), js.indexOf("updateCodeMirrorMode();"));
check("studio handler coalesces into one frame", /requestAnimationFrame/.test(csH));
check("studio handler no longer mirrors into the textarea",
  !/ta\.value = cm/.test(csH));

// ---- O(1) line counting instead of full-document splits ----------------
const stats = js.slice(js.indexOf("function _updateStats"), js.indexOf("function _reflectJobStatus"));
check("_updateStats uses lineCount()", /_jobCm\.lineCount\(\)/.test(stats));
check("_updateStats skips identical writes", /if \(txt === _statsLast\) return;/.test(stats));

// The hand-rolled gutter was REMOVED (its #csGutter target no longer exists);
// CodeMirror renders the real gutter, so there is nothing to recompute.
check("hand-rolled gutter no longer rebuilds line numbers",
  !/getElementById\("csGutter"\)/.test(js));
check("gutter work is delegated to CodeMirror",
  /CodeMirror owns the gutter/.test(js));

const meta = js.slice(js.indexOf("function updateEditorMeta"), js.indexOf("function _buildPreviewSrcdoc"));
check("editor meta uses lineCount()", /cmEditor\.lineCount\(\)/.test(meta));

// ---- no state-destroying side effects on load --------------------------
const setv = js.slice(js.indexOf("function _jobCmSetValue"), js.indexOf("function _jobCmFocus"));
check("_jobCmSetValue clears its loading flag in finally", /finally \{\s*\n\s*_jobCmLoading = false;/.test(setv));

const p = results.filter(r => r[1]).length, f = results.length - p;
console.log(`\n================ ${p} pass, ${f} fail ================`);
process.exit(f ? 1 : 0);
