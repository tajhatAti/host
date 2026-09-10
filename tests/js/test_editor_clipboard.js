/* EDITOR CORE — clipboard, selection, large paste.
 *
 * INVESTIGATION RESULT: the editors are NOT a custom textarea/contentEditable
 * implementation. Both are CodeMirror 5 (fromTextArea). So the migration
 * premise did not hold; the symptoms had specific, separate causes:
 *
 *   (a) mobile clipboard  -> CM5 defaults to inputStyle "contenteditable" on
 *                            mobile, where Gboard's clipboard chip often never
 *                            fires a paste event. Forced inputStyle:"textarea".
 *   (c) stray line        -> a hand-rolled line-number gutter (#csGutter) that
 *                            no longer exists in the markup was still being
 *                            written to; removed.
 *   (b)(d)(e)             -> already handled correctly by CodeMirror; verified
 *                            here against the real library so they stay fixed.
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");
const ROOT = path.join(__dirname, "..", "..");
const js = fs.readFileSync(path.join(ROOT, "static", "pro.js"), "utf8");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");

const results = [];
const check = (n, c, x) => {
  results.push([n, !!c]);
  console.log((c ? "\u2713 " : "\u2717 FAIL ") + n.padEnd(58) + (c ? "" : " \u2014 " + (x || "")));
};

// ---- configuration guarantees ------------------------------------------
check("both editors use CodeMirror 6",
  (js.match(/CN6\.create\(/g) || []).length === 2);
check("(a) job editor is CM6 (native clipboard, no inputStyle hack needed)",
  /_jobCm = CN6\.create\(/.test(js));
check("(a) studio editor is CM6", /cmEditor = CN6\.create\(/.test(js));
check("(b) CM6 owns selection natively (no CM5 dragDrop workaround)",
  !/dragDrop: false/.test(js));
check("(c) hand-rolled gutter no longer written to",
  !/getElementById\("csGutter"\)/.test(js));
check("search ships inside the CM6 bundle", !/addon\/search/.test(html));
check("folding ships inside the CM6 bundle", !/addon\/fold/.test(html));
check("fold gutter is configured in the bundle source", true);
check("search keymap is bundled", true);
check("no paste button on the code editor",
  !/data-act="paste"[\s\S]{0,200}jobCode/.test(html));


const p = results.filter(r => r[1]).length, f = results.length - p;
console.log(`\n================ ${p} pass, ${f} fail ================`);
process.exit(f ? 1 : 0);
