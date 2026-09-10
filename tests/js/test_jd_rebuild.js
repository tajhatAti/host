/* Job Detail Page — structural rebuild, not a rearrangement.
 *
 * BEFORE: one scroller containing EIGHT always-visible .jd-card sections
 * (Status, Controls, Public URL, Env, Logs, Download, Data backup, Run
 * history). Everything competed for attention at once and the page was
 * mostly scrolling. Secondary and destructive actions sat in the same row
 * as the primary one.
 *
 * AFTER: three separated structural pieces —
 *   1. header row   avatar + inline-editable name + status PILL + ONE
 *                   accent-filled primary + theme toggle + overflow menu
 *   2. tab row      pill tabs (Code/Logs/Env/Files/Metrics/Settings),
 *                   exactly one accent-filled active tab
 *   3. content      ONE panel mounted at a time, filling the height
 *
 * The strongest assertions here are the NEGATIVE ones: the old card stack
 * must be gone, and the panels must be mutually exclusive. A recolour of the
 * old markup would pass a "does it look new" check but fails these.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const HTML = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');
const JS = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');

const dom = new JSDOM(HTML, { pretendToBeVisual: true });
const d = dom.window.document;
const st = d.createElement('style'); st.textContent = CSS; d.head.appendChild(st);
const panel = d.getElementById('jobDetailPanel');

let pass = 0, fail = 0;
const ok = (n, c, e) => { c ? pass++ : (fail++, console.log(`  FAIL ${n}${e ? ' -> ' + e : ''}`)); };

// ── 1. the old component is GONE ────────────────────────────────────────
console.log('\n[1] old structure removed');
ok('detail panel exists', !!panel);
const oldCards = panel ? panel.querySelectorAll('.jd-card').length : -1;
ok('the eight stacked .jd-card sections are gone', oldCards === 0, String(oldCards));
ok('no .jd-h card headings remain',
   !!panel && panel.querySelectorAll('.jd-h').length === 0);
ok('no .jd-meta header cluster remains',
   !!panel && panel.querySelectorAll('.jd-meta').length === 0);

// ── 2. three distinct structural pieces ─────────────────────────────────
console.log('[2] three separated pieces');
const head = panel && panel.querySelector(':scope > .jd-top');
const tabs = panel && panel.querySelector(':scope > .jd-tabs');
const body = panel && panel.querySelector(':scope > .jd-body');
ok('header row is a direct child', !!head);
ok('tab row is a direct child', !!tabs);
ok('content area is a direct child', !!body);
ok('they are siblings, not nested',
   !!head && !!tabs && !!body &&
   !head.contains(tabs) && !tabs.contains(body) && !head.contains(body));
ok('and they appear in order: header, tabs, body',
   !!head && !!tabs && !!body &&
   (head.compareDocumentPosition(tabs) & 4) !== 0 &&
   (tabs.compareDocumentPosition(body) & 4) !== 0);

// ── 3. header row ───────────────────────────────────────────────────────
console.log('[3] header row');
ok('avatar chip present', !!d.getElementById('jdLang'));
ok('job name present', !!d.getElementById('jdName'));
const pill = d.getElementById('jdBadge');
ok('status is a PILL, not a bare dot', !!pill && /jd-pill/.test(pill.className),
   pill && pill.className);
ok('pill renders a dot AND a word', /\.jd-pill::before/.test(CSS)
   && /text-transform:\s*capitalize/.test(CSS));
ok('JS writes the pill class', /"jd-pill "/.test(JS));
ok('exactly ONE primary button in the header',
   !!head && head.querySelectorAll('.jd-primary').length === 1,
   head && String(head.querySelectorAll('.jd-primary').length));
/* The theme toggle is GONE, and its absence is the fix. It set data-theme and
   swapped its own icon; app.css maps both values to the same dark palette
   ("One product, one theme") because RunSpace and Code Studio are hardcoded
   dark surfaces. Resolving --bg/--fg/--card under each value gives identical
   results, so pressing it changed nothing a user could see — which reads as a
   broken app, not a design choice. Assert it stays gone until a real light
   theme exists to switch to. */
ok('no dead theme toggle in the header', !d.getElementById('jdThemeToggle'));
ok('overflow menu present', !!d.getElementById('jdMoreBtn') && !!d.getElementById('jdMoreMenu'));
['jdRestart', 'jdStop', 'jdDelete'].forEach(id => {
  const el = d.getElementById(id);
  ok(`${id} moved into the overflow menu`,
     !!el && !!el.closest('#jdMoreMenu'), el ? 'in header' : 'missing');
});
ok('destructive action is styled as destructive',
   !!d.getElementById('jdDelete') &&
   /jd-menu-danger/.test(d.getElementById('jdDelete').className));

// ── 4. tab row is a NEW component ───────────────────────────────────────
console.log('[4] pill tab row');
const tabEls = panel ? [...panel.querySelectorAll('.jd-tab')] : [];
ok('eight tabs', tabEls.length === 8, String(tabEls.length));
['Overview', 'Code', 'Logs', 'Env', 'Files', 'Metrics', 'Settings'].forEach(label =>
  ok(`tab "${label}" exists`, tabEls.some(t => t.textContent.trim() === label)));
ok('tabs are pill-shaped', /\.jd-tab \{[^}]*border-radius:\s*var\(--r-pill\)/.test(CSS));
ok('exactly one tab starts active',
   tabEls.filter(t => t.classList.contains('is-active')).length === 1);
ok('active tab is filled with the single accent',
   /\.jd-tab\.is-active \{[^}]*background:\s*var\(--jd-accent\)/.test(CSS));
ok('inactive tabs have no fill',
   /\.jd-tab \{[^}]*background:\s*transparent/.test(CSS));
ok('tablist semantics', tabs && tabs.getAttribute('role') === 'tablist');
ok('every tab has aria-selected', tabEls.every(t => t.hasAttribute('aria-selected')));
ok('every tab points at its panel', tabEls.every(t => {
  const id = t.getAttribute('aria-controls');
  return id && !!d.getElementById(id);
}));

// ── 5. panels are mutually exclusive ────────────────────────────────────
console.log('[5] one view at a time');
const panels = panel ? [...panel.querySelectorAll('.jd-panel')] : [];
ok('eight panels', panels.length === 8, String(panels.length));
ok('exactly one panel is active', panels.filter(p => p.classList.contains('is-active')).length === 1);
ok('the other seven are hidden', panels.filter(p => p.hidden).length === 7,
   String(panels.filter(p => p.hidden).length));
ok('hidden panels are display:none in CSS', /\.jd-panel \{[^}]*display:\s*none/.test(CSS));
ok('tab router exists', /function jdSwitchTab\(/.test(JS));
ok('router toggles BOTH the class and the hidden attribute',
   /p\.classList\.toggle\("is-active", on\)/.test(JS) && /p\.hidden = !on/.test(JS));
ok('opening the page resets to Overview', /jdSwitchTab\("overview"\)/.test(JS));
ok('arrow keys move between tabs', /ArrowRight/.test(JS) && /ArrowLeft/.test(JS));

// ── 6. Code tab has a real terminal ─────────────────────────────────────
console.log('[6] Output terminal');
const term = d.getElementById('jdLogBody');
ok('output element is inside the Code panel',
   !!term && !!term.closest('#jdPanelCode'));
ok('it is a <pre>', !!term && term.tagName === 'PRE');
ok('monospace terminal surface', /\.jd-term \{[^}]*font-family:\s*var\(--mono/.test(CSS));
ok('sunken/dark console background', /\.jd-term \{[^}]*background:\s*var\(--bg-sunken\)/.test(CSS));
ok('auto-scroll follow control', !!d.getElementById('jdFollow'));
ok('Logs tab mirrors the same buffer safely (textContent, not innerHTML)',
   /function _jdMirrorLogs/.test(JS) && /dst\.textContent = src\.textContent/.test(JS));
ok('mirror only runs when the Logs tab is mounted',
   /_jdTab === "logs"/.test(JS));
ok('code preview uses textContent (user code is untrusted)',
   /_cp\.textContent = src/.test(JS));

// ── 7. colour discipline ────────────────────────────────────────────────
console.log('[7] single accent');
const accentUses = (CSS.match(/var\(--jd-accent\)/g) || []).length;
// The accent is aliased to the app-wide --accent rather than re-declaring a
// hex, so there is exactly ONE source of truth for it in the whole product.
ok('accent token aliases the app accent, not a new literal',
   /--jd-accent:\s*var\(--accent\)/.test(CSS));
const accentRules = [...CSS.matchAll(/([^{}]+)\{[^}]*var\(--jd-accent\)[^}]*\}/g)]
  .map(m => m[1].trim().split('\n').pop());
ok('accent used only by the active tab and the primary button',
   accentRules.every(r => /jd-tab\.is-active|jd-primary/.test(r)),
   accentRules.join(' | '));
ok('status colours stay on status elements only',
   /\.jd-pill\.running[^}]*--ok/.test(CSS) &&
   /\.jd-pill\.crashed[^}]*--danger/.test(CSS));

// ── 8. nothing lost ─────────────────────────────────────────────────────
console.log('[8] no functionality dropped');
const needed = [...new Set([...JS.matchAll(/getElementById\("(jd[A-Za-z0-9_]*)"\)/g)]
  .map(m => m[1]))];
const missing = needed.filter(id => !d.getElementById(id));
ok('every jd* element the JS binds to still exists', missing.length === 0,
   missing.join(','));
const dupes = [...HTML.matchAll(/id="([^"]+)"/g)].map(m => m[1]);
const dupSet = dupes.filter((v, i) => dupes.indexOf(v) !== i);
ok('no duplicate ids introduced', dupSet.length === 0, [...new Set(dupSet)].join(','));

console.log(`\ntest_jd_rebuild: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
