/* RunSpace shell rebuild — structural regression guard.
 *
 * What was measured before the rebuild (not opinions):
 *
 *   CHROME       .rs-bar 42px stacked on .rs-ed-bar (min-height 44px) = 86px
 *                of toolbar before a single line of code. Worse: BOTH the bar
 *                and its inner group had flex-wrap with height:auto, and the
 *                fields need ~710px to fit on one line — so at 412px the row
 *                broke into ~3 rows and the chrome grew to ~156px, changing
 *                height between renders. That reflow is what read as messy.
 *
 *   DRAWER       @media(max-width:760px) .rs-side { width: 78vw }. On a 412px
 *                phone that is 321px — it buried the editor. On desktop the
 *                hamburger was still rendered but the rail was statically
 *                250px, so the button toggled a class with no visible effect:
 *                a dead control in the primary toolbar.
 *
 *   BUTTONS      Five icon-only 28px squares (import, details, stop, restart,
 *                close) with identical borders. Destructive, navigational and
 *                informational actions were indistinguishable; only a title=
 *                tooltip separated them, and tooltips do not exist on touch.
 *
 *   DUPLICATES   Three separate "create a job" controls (btnNew, btnNew2,
 *                btnNewEmpty).
 *
 *   IDENTITY     #rsTitle was never written to by ANY code path, so the header
 *                permanently read the literal string "RunSpace" — it never
 *                told you which job was open.
 *
 * Run:  NODE_PATH=<jsdom> node tests/js/test_runspace_shell.js
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const CSS = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');
const HTML = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const JS = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');

const dom = new JSDOM(HTML, { pretendToBeVisual: true });
const d = dom.window.document;
d.querySelectorAll('link[rel=stylesheet]').forEach(l => l.remove());
const style = d.createElement('style');
style.textContent = CSS;
d.head.appendChild(style);

let pass = 0, fail = 0;
function ok(name, cond, extra) {
  if (cond) pass++;
  else { fail++; console.log(`  FAIL ${name}${extra ? ' -> ' + extra : ''}`); }
}

/* jsdom does not resolve var() in computed styles, so read the token values
   out of the stylesheet and do the arithmetic ourselves. */
function token(name, { mobile = false } = {}) {
  const all = [...CSS.matchAll(new RegExp(`--${name}:\\s*([0-9.]+)px`, 'g'))]
    .map(m => parseFloat(m[1]));
  if (!all.length) return null;
  return mobile ? all[all.length - 1] : all[0];
}

// ── 1. one header, not two bars ─────────────────────────────────────────
console.log('\n[1] chrome budget');
ok('single .rs-head exists', !!d.querySelector('#tab-jobs .rs-head'));
ok('old .rs-bar removed from markup', !d.querySelector('#tab-jobs .rs-bar'));
ok('old .rs-ed-bar removed from markup', !d.querySelector('#tab-jobs .rs-ed-bar'));
ok('.rs-meta strip exists', !!d.querySelector('#tab-jobs .rs-meta'));

const head = token('rs-head-h'), meta = token('rs-meta-h');
const headM = token('rs-head-h', { mobile: true });
const metaM = token('rs-meta-h', { mobile: true });
ok('--rs-head-h defined', head !== null, String(head));
ok('--rs-meta-h defined', meta !== null, String(meta));
console.log(`      desktop chrome = ${head} + ${meta} = ${head + meta}px  (was 86)`);
console.log(`      mobile  chrome = ${headM} + ${metaM} = ${headM + metaM}px  (was ~156 at 412px)`);
ok('desktop chrome is not worse than before (<=86)', head + meta <= 86, `${head + meta}px`);
ok('mobile chrome well under the old ~156px', headM + metaM <= 96, `${headM + metaM}px`);

// ── 2. the strip can never rearrange itself ─────────────────────────────
console.log('[2] no reflow');
const metaCS = dom.window.getComputedStyle(d.querySelector('#tab-jobs .rs-meta'));
ok('.rs-meta is nowrap', metaCS.flexWrap === 'nowrap', metaCS.flexWrap);
ok('.rs-meta scrolls instead of wrapping', /overflow-x:\s*auto/.test(CSS));
ok('no flex-wrap:wrap left on a toolbar row',
   !/\.rs-(ed-bar|ed-group|meta)[^{]*\{[^}]*flex-wrap:\s*wrap/.test(CSS));

// ── 3. buttons have roles, not just tooltips ────────────────────────────
console.log('[3] button system');
const seg = d.querySelector('#rsJobActions');
ok('segmented action group exists', !!seg);
['btnStartJob', 'btnRestartJob', 'btnStopJob'].forEach(id =>
  ok(`${id} is inside the group`, !!(seg && seg.querySelector('#' + id))));
['btnStartJob', 'btnRestartJob', 'btnStopJob'].forEach(id =>
  ok(`${id} has a text label`, !!d.querySelector(`#${id} .rs-seg-label`)));
const squares = [...d.querySelectorAll('#tab-jobs .rs-head .rs-ghost-btn.rs-sq')];
ok('at most 3 loose icon squares in the header', squares.length <= 3,
   `${squares.length}: ${squares.map(s => s.id).join(',')}`);
const unlabelled = [...d.querySelectorAll('#tab-jobs .rs-head button')]
  .filter(b => !(b.textContent || '').trim()
            && !b.getAttribute('aria-label')
            && !b.getAttribute('title'));
ok('every header button is labelled', unlabelled.length === 0,
   unlabelled.map(b => b.id).join(','));
ok('Stop is visually distinct from neutral actions', /rs-seg-danger/.test(CSS));

// ── 4. the run button keeps its behaviour ───────────────────────────────
console.log('[4] behaviour preserved through the rebuild');
ok('Run still has a spinner element', !!d.querySelector('#btnStartJob .rs-spin'));
ok('loading state styled', /#btnStartJob\.loading/.test(CSS));
ok('dirty state styled', /#btnStartJob\.dirty/.test(CSS));
ok('JS still sets the Run label', /rs-seg-label|rs-btn-label/.test(JS));

// ── 5. one way to create a job ──────────────────────────────────────────
console.log('[5] duplicate controls');
const creators = ['btnNew', 'btnNew2', 'btnNewEmpty'].filter(i => d.getElementById(i));
ok('no third "+ New" in the header', !d.getElementById('btnNew2'), creators.join(','));
ok('sidebar + empty-state creators remain', creators.length === 2, creators.join(','));

// ── 6. the sidebar toggle actually does something ───────────────────────
console.log('[6] sidebar');
ok('mobile drawer is no longer 78vw', !/width:\s*78vw/.test(CSS));
ok('mobile drawer capped so code stays visible', /min\(280px,\s*82vw\)/.test(CSS));
ok('desktop collapse rule exists', /rs-side-collapsed/.test(CSS));
ok('JS toggles collapse on desktop', /rs-side-collapsed/.test(JS));
ok('JS keeps the drawer state sane across the breakpoint',
   /matchMedia\("\(max-width:\s*760px\)"\)/.test(JS));
const menuBtn = d.getElementById('wbMenuBtn');
ok('toggle exposes aria-expanded', !!menuBtn && menuBtn.hasAttribute('aria-expanded'));
ok('toggle names the panel it controls',
   !!menuBtn && menuBtn.getAttribute('aria-controls') === 'wbSide');

// ── 7. the header says what is open ─────────────────────────────────────
console.log('[7] identity');
ok('breadcrumb root present', !!d.getElementById('rsCrumbRoot'));
ok('breadcrumb current present', !!d.getElementById('rsTitle'));
ok('state chip present', !!d.getElementById('rsHeadState'));
ok('breadcrumb hidden until a job is open',
   d.getElementById('rsTitle').hidden === true);
ok('JS now WRITES the breadcrumb (it never did before)',
   /crumbCur\.textContent\s*=/.test(JS));
ok('JS writes the state chip', /headChip\.textContent\s*=/.test(JS));

// ── 8. nothing references deleted classes ───────────────────────────────
console.log('[8] no dangling references');
const cssNoComments = CSS.replace(/\/\*[\s\S]*?\*\//g, '');
['.rs-ed-bar', '.rs-run-btn', '.rs-text-btn', '.rs-ed-group', '.rs-ed-actions']
  .forEach(sel => ok(`no live CSS rule for ${sel}`,
                     !cssNoComments.includes(sel), sel));
ok('details page hides the NEW header',
   /body\.rs-detail-open #tab-jobs \.rs-head/.test(CSS));
ok('details page hides the meta strip',
   /body\.rs-detail-open #tab-jobs \.rs-meta/.test(CSS));

console.log(`\ntest_runspace_shell: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
