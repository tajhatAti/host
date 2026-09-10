/* CODEMIRROR 6 MIGRATION.
 *
 * WHY: CodeMirror 5 positions the line-number gutter with JavaScript on every
 * horizontal scroll:
 *     gutters.style.left = compensateForHScroll(cm.display) + "px"
 * so while you drag a long line sideways the numbers are repositioned one
 * frame late and visibly wobble ("নড়বড়া"). CM6 pins the gutter with CSS
 * position:sticky, which the compositor handles, so it cannot drift.
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const js = fs.readFileSync(path.join(ROOT, "static", "pro.js"), "utf8");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const bundlePath = path.join(ROOT, "static", "cm6.bundle.js");
const bundle = fs.readFileSync(bundlePath, "utf8");

const results = [];
const check = (n, c, x) => {
  results.push([n, !!c]);
  console.log((c ? "\u2713 " : "\u2717 FAIL ") + n.padEnd(58) + (c ? "" : " \u2014 " + (x || "")));
};

// ---- the gutter bug is structurally gone -------------------------------
check("CM6 never repositions the gutter from JS (the wobble cause)",
  !bundle.includes("gutters.style.left"));
check("CM6 pins the gutter with position:sticky",
  bundle.includes('position:"sticky"'));

// ---- CM5 is fully removed ----------------------------------------------
check("no CodeMirror 5 CDN tags remain", !/codemirror\/5\./.test(html));
check("no CM5 API calls remain in pro.js",
  !/CodeMirror\.fromTextArea|typeof CodeMirror/.test(js));
check("bundle is self-hosted, not a CDN", /\/static\/cm6\.bundle\.js/.test(html));
check("bundle loads before pro.js",
  html.indexOf("cm6.bundle.js") < html.indexOf("/static/pro.js"));
check("build source is committed for reproducibility",
  fs.existsSync(path.join(ROOT, "editor-src", "cm6.js")) &&
  fs.existsSync(path.join(ROOT, "editor-src", "package.json")));

// ---- both editors migrated ---------------------------------------------
check("RunSpace editor uses CN6", /_jobCm = CN6\.create\(/.test(js));
check("Code Studio editor uses CN6", /cmEditor = CN6\.create\(/.test(js));
check("language switching uses the CM6 compartment",
  /_jobCm\.setLanguage\(/.test(js) && /cmEditor\.setLanguage\(/.test(js));

// ---- run the REAL bundle ------------------------------------------------
const dom = new JSDOM(`<!doctype html><body><div id="host"></div></body>`,
  { pretendToBeVisual: true, runScripts: "outside-only" });
dom.window.document.createRange = () => ({
  setEnd() {}, setStart() {},
  getBoundingClientRect: () => ({ top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }),
  getClientRects: () => [],
});
dom.window.eval(bundle);
const CN6 = dom.window.CN6;
check("bundle exposes the editor facade",
  CN6 && typeof CN6.create === "function");

let changes = 0;
const ed = CN6.create(dom.window.document.getElementById("host"),
  { value: "", language: "python", onChange: () => changes++ });

// (e) large paste
const big = Array.from({ length: 250 }, (_, i) => `def f${i}(a, b): return a + b  # ${i}`).join("\n");
const t0 = Date.now();
ed.setValue(big);
const ms = Date.now() - t0;
check("(e) 250-line paste lands in one change event", changes === 1, String(changes));
check("(e) 250-line paste is fast", ms < 600, ms + "ms");
check("(e) all 250 lines present", ed.lineCount() === 250, String(ed.lineCount()));
check("content round-trips byte-for-byte", ed.getValue() === big);

// (d) select-all + paste replaces everything
ed.setValue("print('only me')");
check("(d) replacing all content leaves no remnants",
  ed.getValue() === "print('only me')" && ed.lineCount() === 1);

// language switching must not corrupt the document
ed.setValue(big);
ed.setLanguage("javascript");
check("language switch preserves the document", ed.getValue() === big);
ed.setLanguage("bash");
check("legacy-mode language also works", ed.getValue() === big);

// gutter actually rendered
const out = dom.window.document.getElementById("host").innerHTML;
check("gutter is rendered", out.includes("cm-gutters"));
check("line numbers are rendered", out.includes("cm-lineNumbers"));

// (c) no leftover hand-rolled gutter
check("(c) hand-rolled gutter is gone", !/getElementById\("csGutter"\)/.test(js));

const p = results.filter(r => r[1]).length, f = results.length - p;
console.log(`\n================ ${p} pass, ${f} fail ================`);
process.exit(f ? 1 : 0);
