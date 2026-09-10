/* RUNSPACE DESIGN SYSTEM.
 *
 * "It doesn't feel minimal like GitHub" was a measurable problem, not taste.
 * runspace-dark.css used 12 font sizes (9.5/10/10.5/11/11.5/12/12.5/13/13.5/
 * 14/15/16), 7 radii and 25 colours. Values that are ALMOST the same never
 * line up, so the eye finds no pattern and it reads as messy. GitHub looks
 * calm despite dense data because everything derives from one small scale.
 *
 * This test locks that scale in so the drift cannot creep back.
 */
const fs = require("fs");
const path = require("path");
const ROOT = path.join(__dirname, "..", "..");
/* SCOPE (2026-08): this suite was written when runspace-dark.css was a
 * separate, RunSpace-only sheet, so "the whole file" and "the RunSpace
 * views" were the same thing. The nine sheets are now one app.css, and
 * reading the whole file made every legitimate literal elsewhere on the
 * site -- landing type sizes, syntax-highlighting colours -- look like
 * RunSpace drift. The scale being locked here is RunSpace's, so only
 * rules that target the RunSpace subtree are examined. */
const full = fs.readFileSync(path.join(ROOT, "static", 'app.css'), "utf8");

const tokenEnd = full.indexOf("*/", full.indexOf("DESIGN TOKENS")) + 2;
const tokens = full.slice(0, full.indexOf("}", full.indexOf("--dur")) + 1);

// Collect only the rules whose selector mentions a RunSpace surface.
const postcss = require('postcss');
/* A rule belongs to RunSpace only if EVERY selector in it targets RunSpace.
 * Matching "any selector" swept in the app-wide pill rule -- which lists
 * .rs-chip alongside a dozen non-RunSpace classes -- and then reported its
 * perfectly legitimate literals as RunSpace drift. That is how two guards
 * ended up demanding opposite things about the same declaration. */
const SCOPE = /#tab-jobs|\.rs-|\.jd-|\.job-item/;
let scoped = '';
postcss.parse(full).walkRules(r => {
  if (!r.selectors.every(sel => SCOPE.test(sel))) return;
  // A rule that only DECLARES custom properties is the scale itself --
  // literals belong there and nowhere else, so it is not part of the body
  // being audited for hardcoded values.
  const decls = [];
  r.walkDecls(dcl => decls.push(dcl.prop));
  // `color-scheme` travels with a token pin (it makes native controls
  // follow the same theme) so it does not make the rule a styling rule.
  const meaningful = decls.filter(pr => pr !== 'color-scheme');
  if (meaningful.length && meaningful.every(pr => pr.startsWith('--'))) return;
  scoped += r.toString() + '\n';
});
const css = scoped;
const body = scoped;

const results = [];
const check = (n, c, x) => {
  results.push([n, !!c]);
  console.log((c ? "\u2713 " : "\u2717 FAIL ") + n.padEnd(56) + (c ? "" : " \u2014 " + (x || "")));
};

// ---- the scale exists ---------------------------------------------------
for (const t of ["--bg", "--bg-2", "--bg-3", "--line", "--fg", "--fg-2", "--fg-3",
                 "--accent", "--ok", "--warn", "--danger",
                 "--t-xs", "--t-sm", "--t-md", "--t-lg",
                 "--r-sm", "--r-md", "--r-pill"]) {
  check(`token defined: ${t}`, new RegExp("\\" + t + ":\\s*[^;]+;").test(tokens));
}
check("tokens are literal, not self-referential",
  !/--(bg|fg|ok|warn|danger|accent)(-\d)?:\s*var\(/.test(tokens));

// ---- nothing bypasses the scale ----------------------------------------
const rawFonts = [...new Set((body.match(/font-size:\s*[0-9.]+px/g) || []))];
check("no hardcoded font sizes remain", rawFonts.length === 0, rawFonts.join(", "));

const rawRadii = [...new Set((body.match(/border-radius:\s*[0-9.]+px/g) || []))];
check("no hardcoded radii remain", rawRadii.length === 0, rawRadii.join(", "));

const rawHex = [...new Set((body.match(/#[0-9a-fA-F]{6}\b/g) || []).map(h => h.toLowerCase()))];
check("no hardcoded hex colours remain", rawHex.length === 0, rawHex.join(", "));

// ---- one accent, the rest are status only -------------------------------
const accentDefs = (tokens.match(/--(accent|ok|warn|danger):/g) || []).length;
check("exactly one brand accent + 3 status colours", accentDefs === 4, String(accentDefs));

// ---- restraint ----------------------------------------------------------
const gradients = (body.match(/linear-gradient|radial-gradient/g) || []).length;
check("at most one decorative gradient (loading skeleton)", gradients <= 1, String(gradients));
// Strip comments first — the rule explains WHY there is no gradient, and the
// word inside that comment must not count as a match.
const noComments = css.replace(/\/\*[\s\S]*?\*\//g, "");
check("progress bar is a flat fill, not a gradient+glow",
  !/\.rs-progress-fill \{[^}]*gradient/.test(noComments) &&
  !/\.rs-progress-fill \{[^}]*box-shadow/.test(noComments));

// ---- spacing on a 4px grid ---------------------------------------------
const offGrid = [...new Set((body.match(/\b(?:padding|margin):[^;!]*/g) || [])
  .flatMap(d => d.split(":")[1].trim().split(/\s+/))
  .filter(v => /^[0-9]+px$/.test(v))
  // 1px is a hairline rule, not spacing.
  .filter(v => v !== "1px" && parseInt(v, 10) % 4 !== 0))];
check("spacing sits on the 4px grid", offGrid.length === 0, offGrid.join(", "));

const p = results.filter(r => r[1]).length, f = results.length - p;
console.log(`\n================ ${p} pass, ${f} fail ================`);
process.exit(f ? 1 : 0);
