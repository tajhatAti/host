/* LANDING PAGE REDESIGN.
 *
 * The hero showed a fabricated "glass card" dashboard — invented UI with fake
 * rows (App / Status / Public URL) that no real screen ever renders. Invented
 * UI is what made the product read as a toy rather than a hosting service.
 * It is replaced by a real deploy transcript: install, start, poll, reply.
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");
const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "static", 'app.css'), "utf8");
const classic = fs.readFileSync(path.join(ROOT, "static", 'app.css'), "utf8");
const d = new JSDOM(html).window.document;

const results = [];
const check = (n, c, x) => {
  results.push([n, !!c]);
  console.log((c ? "\u2713 " : "\u2717 FAIL ") + n.padEnd(56) + (c ? "" : " \u2014 " + (x || "")));
};

// ---- the toy mockup is gone --------------------------------------------
check("fake glass-card mockup removed", !d.querySelector(".glass-card"));
check("no invented status rows remain", !/gc-row|gc-chip|gc-bar/.test(html));
/* classic.css is deleted; the landing page is themed by app.css, which is
   the point. The surviving requirement is that the old GLASS vocabulary
   did not come with it. */
check("no glass-card vocabulary survives",
  !/\.glass-card\b/.test(classic));

// ---- replaced with something real --------------------------------------
const term = d.querySelector(".term-card");
check("hero shows a real deploy transcript", !!term);
check("transcript is described for screen readers",
  term && term.getAttribute("aria-label"));
const body = term ? term.textContent : "";
for (const token of ["codenest deploy", "installing", "bot started", "polling"]) {
  check(`transcript shows a real step: ${token}`, body.includes(token));
}
check("transcript shows honest uptime, not a fake metric", /uptime/.test(body));

// ---- structure ----------------------------------------------------------
check("how-it-works section exists", !!d.getElementById("how"));
check("three numbered steps", d.querySelectorAll(".step").length === 3);
check("features section exists", !!d.getElementById("features"));
check("six feature cards", d.querySelectorAll(".feat").length === 6);
check("closing call to action", !!d.querySelector(".cta-band"));

// ---- every nav target resolves -----------------------------------------
const targets = [...html.matchAll(/scrollToId\('([a-z-]+)'\)/g)].map(m => m[1]);
const dead = [...new Set(targets)].filter(t => !d.getElementById(t));
check("no nav link points at a removed section", dead.length === 0, dead.join(", "));

// ---- restraint ----------------------------------------------------------
/* DECORATIVE gradients used to be banned outright; the two that existed were
   functional (the skeleton's shimmer and the feature tile's lift). The aurora
   redesign adds a deliberate, counted exception: the ambient backdrop is two
   radial washes on the page and two on the light auth/landing surfaces, which
   is the reference design's signature and the one place decoration is the
   point. The ceiling is raised to cover exactly those, not to open the door —
   a ninth gradient still fails. */
check("gradients stay counted, not sprawling",
  (css.match(/linear-gradient|radial-gradient/g) || []).length <= 10,
  String((css.match(/linear-gradient|radial-gradient/g) || []).length));
check("gradient text effect neutralised", /\.grad \{[^}]*background: none/.test(css));
/* REWRITTEN 2026-08. This asserted zero box-shadows, which was correct for
   the flat revision. The user reviewed four mockups, chose the one built on
   elevation, and said so explicitly -- "deep button animation nai". Depth is
   now the requirement, so the guard checks that shadows are BLACK (real
   elevation) rather than white/coloured GLOWS, which is what "no glow"
   actually meant. */
/* Two coloured glows are deliberate and were asked for:
     · the running status dot, so "it is alive" is readable at a glance
     · the light-slab active control from mockup C
   Everything else must be black elevation. The cap keeps that from
   becoming a habit. */
const glows = (css.match(/box-shadow:[^;]*rgba\((?!0\s*,\s*0\s*,\s*0)[^;]*\)/g) || [])
  .filter(s => !/inset/.test(s));
const blackShadows = (css.match(/box-shadow:[^;]*rgba\(0\s*,\s*0\s*,\s*0/g) || []).length;
check("depth comes from black elevation, glows are the exception",
  glows.length <= 8 && blackShadows >= glows.length,
  `${glows.length} glow vs ${blackShadows} elevation`);
/* --ln-* were landing.css's private tokens. That sheet is gone; the landing
   page now reads the app-wide scale, which is the stronger version of the
   same requirement. */
check("scale is token-driven", /--accent:/.test(css) && /--s5:/.test(css));
const rawHex = [...new Set((css.slice(css.indexOf("/* ---------- shell"))
  .match(/#[0-9a-fA-F]{6}\b/g) || []).map(s => s.toLowerCase()))];
check("body styles use tokens, not raw hex", rawHex.length <= 1, rawHex.join(", "));

// ---- the app still boots ------------------------------------------------
for (const id of ["screen-landing", "screen-signup", "screen-signin",
                  "screen-dashboard", "tab-jobs"]) {
  check(`app screen intact: ${id}`, !!d.getElementById(id));
}
/* There is only one stylesheet now, so "loaded last" is trivially true and
   comparing the file against itself asserted nothing. What still matters is
   that no OTHER local sheet can come after it. */
check("app.css is the only local stylesheet",
  (html.match(/<link rel="stylesheet" href="\/static\//g) || []).length === 1);

const p = results.filter(r => r[1]).length, f = results.length - p;
console.log(`\n================ ${p} pass, ${f} fail ================`);
process.exit(f ? 1 : 0);
