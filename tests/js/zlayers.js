/* Resolve a z-index that is expressed as a token.
 *
 * WHY THIS EXISTS. The layer order used to be 29 ad-hoc numbers between 5 and
 * 10000, with .toast-container and .ah-modal each declared TWICE at different
 * values — so which one won depended on where it sat in the file. It is now a
 * named ladder (--z-sticky ... --z-fatal) declared once at :root.
 *
 * jsdom's getComputedStyle does not substitute custom properties, so
 * Number(cs.zIndex) on "var(--z-sheet)" is NaN and every ordering assertion
 * silently degrades to a comparison against NaN — which is always false, and
 * therefore always "fails" even when the order is correct. These helpers read
 * the token table out of the stylesheet and resolve it, so the tests keep
 * checking the thing that matters: THE ORDER, not the numbers.
 */
const fs = require('fs');
const path = require('path');

const CSS_PATH = path.resolve(__dirname, '../../static/app.css');

function tokenTable(css) {
  const table = {};
  const root = /:root\s*\{([\s\S]*?)\}/g;
  let m;
  while ((m = root.exec(css))) {
    const body = m[1];
    let d;
    const decl = /(--[\w-]+)\s*:\s*([^;]+);/g;
    while ((d = decl.exec(body))) table[d[1]] = d[2].trim();
  }
  return table;
}

/** Resolve "var(--z-sheet)" / "880" / "auto" to a number (0 when absent). */
function zValue(raw, css) {
  if (raw == null) return 0;
  let v = String(raw).trim();
  if (!v || v === 'auto') return 0;
  const table = tokenTable(css || fs.readFileSync(CSS_PATH, 'utf8'));
  for (let i = 0; i < 8 && v.includes('var('); i++) {
    v = v.replace(/var\(\s*(--[\w-]+)\s*(?:,\s*([^)]*))?\)/, (_, name, fb) =>
      (table[name] !== undefined ? table[name] : (fb || '0')));
  }
  const n = Number(v.trim());
  return Number.isFinite(n) ? n : 0;
}

/** z-index of an element, with tokens resolved. */
function zOf(win, el, css) {
  if (!el) return 0;
  return zValue(win.getComputedStyle(el).zIndex, css);
}

module.exports = { zValue, zOf, tokenTable, CSS_PATH };
