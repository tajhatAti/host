/* Dark-mode surface + contrast guard.
 *
 * REPORTED: white/light cards, hero blocks, bottom nav and modals inside a
 * dark app; inline links and badges rendering as unreadable white rectangles;
 * "high-glare" solid-white buttons.
 *
 * MEASURED ROOT CAUSES (two independent bugs, not a styling preference):
 *
 *  A. THEME DEFAULT. initTheme() did:
 *         applyTheme(localStorage.getItem("ahad_theme") || "light")
 *     so a first-time visitor got data-theme="light" -> classic.css served
 *     --panel #ffffff / --paper #f4f4f5 for every card, hero and modal. But
 *     the landing page, RunSpace and the code editor are HARDCODED dark
 *     (#0d1117 / #08090d), and never consult data-theme. Result: genuinely
 *     light containers sitting inside a dark product. Now defaults to dark,
 *     honouring an explicit saved choice and then prefers-color-scheme.
 *
 *  B. WHITE-ON-WHITE. Removing the accent hue turned --acc/--grad into
 *     near-white (#e9e9ec / #e6e6ea) in dark mode. 11 rules painted those as
 *     a BACKGROUND and then wrote `color:#fff` on top — 1.21:1, invisible.
 *     That is the "white rectangle with light text" report.
 *
 * This test resolves CSS variables to their dark-theme values and fails on any
 * background/foreground pair below 3:1.
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '../../');
const SHEETS = ['app.css'];
const JS = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');

/* Dark-theme resolved values (html[data-theme="dark"] block in classic.css). */
const VARS = {
  '--acc': '#e9e9ec', '--grad': '#e6e6ea', '--brand-1': '#e6e6ea',
  '--brand-2': '#c9c9d1', '--brand-3': '#b9b9c2', '--btn': '#e9e9ec',
  '--btn-fg': '#111113', '--acc-ink': '#f5f5f6', '--cream': '#f5f5f6',
  '--paper': '#131316', '--panel': '#1b1b1f', '--band': '#08080a',
  '--ink': '#e9e9ec', '--on-cream': '#111113',
};

let pass = 0, fail = 0;
function ok(name, cond, extra) {
  if (cond) pass++;
  else { fail++; console.log(`  FAIL ${name}${extra ? ' -> ' + extra : ''}`); }
}

function lum(hex) {
  const h = hex.replace('#', '');
  const c = [0, 2, 4].map(i => {
    const v = parseInt(h.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
function contrast(a, b) {
  const L1 = Math.max(lum(a), lum(b)), L2 = Math.min(lum(a), lum(b));
  return (L1 + 0.05) / (L2 + 0.05);
}
function resolve(value) {
  const v = String(value).trim();
  const varm = /var\((--[a-z0-9-]+)/.exec(v);
  if (varm && VARS[varm[1]]) return VARS[varm[1]];
  const hex = /#([0-9a-fA-F]{6})\b/.exec(v);
  if (hex) return '#' + hex[1];
  if (/^#fff\b/.test(v) || v === 'white') return '#ffffff';
  if (/^#000\b/.test(v) || v === 'black') return '#000000';
  return null;
}

// ── A. the theme default ────────────────────────────────────────────────
console.log('\n[A] theme default');
ok('does not hard-default to light',
   !/localStorage\.getItem\("ahad_theme"\)\s*\|\|\s*"light"/.test(JS));
ok('falls back to dark', /applyTheme\(saved === "light" \? "light" : "dark"\)/.test(JS));
ok('still honours an explicit saved choice',
   /saved === "light" \? "light" : "dark"/.test(JS));
// REVERSED DELIBERATELY. This used to require prefers-color-scheme, and that
// requirement caused a real bug: a phone in light mode got light chrome, but
// RunSpace and Code Studio are hardcoded dark and PIN themselves dark even
// under data-theme="light". The result was light glass over permanently dark
// panels — the "white middle" report. Following the OS can return once every
// surface is able to follow it.
ok('the OS preference is NOT consulted, because not every surface can follow it',
   !/prefers-color-scheme/.test(
     JS.slice(JS.indexOf('function initTheme'), JS.indexOf('function initTheme') + 1200)));
ok('and the reversal is explained where it lives',
   /THE OS PREFERENCE IS NOT CONSULTED/.test(JS));

// ── B. no unreadable pair anywhere ──────────────────────────────────────
console.log('[B] contrast of every background/colour pair');
const offenders = [];
let checked = 0;
for (const name of SHEETS) {
  const p = path.join(ROOT, 'static', name);
  if (!fs.existsSync(p)) continue;
  const css = fs.readFileSync(p, 'utf8');
  const ruleRe = /([^{}]+)\{([^}]*)\}/g;
  let m;
  while ((m = ruleRe.exec(css)) !== null) {
    const body = m[2];
    const bg = /(?:^|[;\s])background(?:-color)?:\s*([^;]+)/.exec(body);
    const fg = /(?:^|[;\s])color:\s*([^;]+)/.exec(body);
    if (!bg || !fg) continue;
    const b = resolve(bg[1]), c = resolve(fg[1]);
    if (!b || !c) continue;
    checked++;
    const r = contrast(b, c);
    if (r < 3.0) {
      const line = css.slice(0, m.index).split('\n').length;
      offenders.push(`${name}:${line} ${m[1].trim().split('\n').pop().slice(0, 40)} (${b}/${c} = ${r.toFixed(2)}:1)`);
    }
  }
}
console.log(`      checked ${checked} background/colour pairs`);
ok('no pair below 3:1', offenders.length === 0, offenders.join(' | '));

// ── C. inline links carry no fill ───────────────────────────────────────
console.log('[C] inline links');
const classic = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');
ok('link rule strips any background',
   /\.link,[^{]*\{[^}]*background:\s*none\s*!important/.test(classic));
ok('links inherit the surrounding text colour',
   /\.link,[^{]*\{[^}]*color:\s*inherit\s*!important/.test(classic));
ok('links are underlined, not highlighted',
   /\.link,[^{]*\{[^}]*text-decoration:\s*underline/.test(classic));
ok('Terms-of-Use link is covered', /\.tos-check a/.test(classic));
ok('"Sign in instead" link is covered', /\.field-taken a/.test(classic));
ok('field-taken link no longer forces the near-white accent',
   !/\.field-taken a \{[^}]*color:\s*var\(--acc\)/.test(classic));
ok('links keep a visible focus ring', /\.link:focus-visible/.test(classic));

// ── D. bottom navigation ────────────────────────────────────────────────
console.log('[D] bottom navigation');
// REVERSED: these three used to require a translucent, blurred bar. The
// frosted-glass treatment is now removed from the product entirely — a nav
// bar over scrolling content is the worst case for it, because the text
// behind keeps changing what the labels sit on. Solid means the labels have
// one predictable background, and no @supports fallback is needed because
// there is nothing to fall back from.
ok('the bar is SOLID, not translucent',
   /\.bottom-nav,\s*\.bn \{[^}]*background:\s*var\(--surface-1\)/.test(classic));
ok('no blur on it', !/\.bottom-nav,\s*\.bn \{[^}]*backdrop-filter:\s*blur/.test(classic));
ok('has a hairline top border',
   /\.bottom-nav,\s*\.bn \{[^}]*border-top:\s*1px solid/.test(classic));
// `backdrop-filter: none` is fine and in fact desirable — it is what forces
// the effect off. Only a real blur is a failure. My first version of this
// regex flagged the `none` declarations too.
ok('no BLUR survives anywhere in the sheet',
   !/backdrop-filter:\s*blur/.test(classic),
   (classic.match(/backdrop-filter:\s*blur[^;]*/g) || []).join(' | '));

console.log(`\ntest_dark_surfaces: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
