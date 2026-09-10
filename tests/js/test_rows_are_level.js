/* EVERY TOOLBAR ROW MUST BE LEVEL, AT EVERY WIDTH.
 *
 * This is the check that would have caught the original complaint directly.
 * The token tests next door prove the SCALE is coherent; this proves the
 * result — that in each real row of the real markup, every control resolves
 * to the same height.
 *
 * What it found before the fix (desktop):
 *
 *     RunSpace toolbar     32 / 34 / 30px
 *     Code Studio header   32 / 40px      (name field vs action buttons)
 *     sign-in form         40 / 42px      (button vs text input)
 *
 * A two-pixel difference between a button and the field beside it is not
 * something a user can name, but it is exactly what "the UI looks unfinished"
 * means in practice.
 *
 * TWO THINGS THIS HAS TO GET RIGHT, both learned by getting them wrong:
 *
 *  1. Resolve custom properties. jsdom hands back "var(--ctl-h-sm)", so a
 *     naive parseFloat yields NaN and every row "passes" — see cssvars.js.
 *  2. Ignore controls that are not really in the row. Dropdown menus are
 *     markup children of their toolbar but sit in a [hidden], absolutely
 *     positioned panel. Counting them reported four ragged toolbars that no
 *     user can ever see, because menu items are deliberately 44px.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');
const { makeResolver, css } = require('./cssvars');

const ROOT = path.resolve(__dirname, '../../');
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, x) => {
  if (c) { pass++; console.log('  ok   ' + n); }
  else { fail++; console.log('  FAIL ' + n + (x !== undefined ? ' -> ' + x : '')); }
};

const ROWS = [
  ['.rs-head', 'RunSpace toolbar'],
  ['.cs-header', 'Code Studio header'],
  ['.cs-actions', 'Code Studio actions'],
  ['.nav-cta', 'landing nav CTAs'],
  ['.hero-actions', 'hero CTAs'],
  ['.auth-form', 'sign-in form'],
];

function measure(width) {
  const dom = new JSDOM(html, { pretendToBeVisual: true });
  const w = dom.window, d = w.document;
  d.documentElement.setAttribute('data-theme', 'dark');
  const st = d.createElement('style'); st.textContent = css; d.head.appendChild(st);
  d.querySelectorAll('.hidden').forEach(e => e.classList.remove('hidden'));
  d.documentElement.classList.remove('booting');
  const resolve = makeResolver(w, width);
  const cs = el => w.getComputedStyle(el);

  return ROWS.map(([sel, label]) => {
    const row = d.querySelector(sel);
    if (!row) return { label, skip: 'absent' };

    // Only controls actually laid out IN this row (see note 2 above).
    const inRow = (k) => {
      let n = k;
      while (n && n !== row) {
        if (n.hasAttribute && n.hasAttribute('hidden')) return false;
        const ns = cs(n);
        if (ns.display === 'none') return false;
        if (ns.position === 'absolute' || ns.position === 'fixed') return false;
        n = n.parentElement;
      }
      return true;
    };
    const kids = [...row.querySelectorAll('button, input, select, a.btn-primary')]
      .filter(k => cs(k).display !== 'none' && !k.hasAttribute('hidden') && inRow(k));
    if (kids.length < 2) return { label, skip: `${kids.length} control` };

    const heights = kids.map(k => {
      const h = parseFloat(resolve(k, cs(k).height || ''));
      const mh = parseFloat(resolve(k, cs(k).minHeight || ''));
      // A real browser lets min-height win over a smaller height.
      return Number.isFinite(mh) && (!Number.isFinite(h) || mh > h) ? mh : h;
    });
    return { label, kids, heights, uniq: [...new Set(heights.filter(Number.isFinite))] };
  });
}

for (const width of [undefined, 760, 390]) {
  console.log(`\n[${width ? '<=' + width + 'px' : 'desktop'}]`);
  for (const r of measure(width)) {
    if (r.skip) { console.log(`  --   ${r.label} (${r.skip})`); continue; }
    ok(`${r.label} is level`, r.uniq.length === 1,
       r.uniq.sort((a, b) => a - b).join(' / ') + 'px');
    // A row that resolved to nothing measurable would pass the check above
    // by accident; NaN is not agreement.
    ok(`${r.label} is measurable`, r.heights.every(Number.isFinite),
       r.heights.join(', '));
  }
}

console.log(`\ntest_rows_are_level: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
