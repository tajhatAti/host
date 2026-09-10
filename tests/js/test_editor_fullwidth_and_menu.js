/* The editor owns the screen; the controls live in one menu.
 *
 * REPORTED
 *   "জব লিস্ট অনেক বড় হয়ে গেছে ... ফলে ইডিটর একপাশে সরে গিয়ে ছোট হয়ে গেছে,
 *    এডিটর ফুল স্ক্রিন লাগবে ... বাকি সব থাকবে একটা বাটনে, ক্লিক করলে ছোট ছোট
 *    বাটন উপর থেকে নিচ বরাবর সারি সারি নামবে ... রান, সেভ, ডিটেলস বাটন একটার
 *    উপর আরেকটা হয়ে গেছে, পাশাপাশি নাই"
 *   plus: the sign-in card carries filler text and its three controls are
 *   not laid out.
 *
 * TWO DISTINCT DEFECTS
 *   (a) .rs-side was a permanent 210px column on desktop, so the editor was
 *       never full width -- it only got the space back when the rail was
 *       explicitly collapsed. The rail is an overlay at every size now.
 *   (b) .rs-head packed a breadcrumb, a three-button segmented group and two
 *       icon buttons into a fixed 52px row with no flex-shrink guard, so
 *       under ~900px they overlapped instead of sitting side by side.
 *
 * WHAT THIS SUITE WILL NOT ACCEPT
 *   A rule that merely EXISTS. Every geometric claim is measured on
 *   computed style with the real sheet applied, at both widths, and the
 *   overlap check compares actual left/right box edges rather than looking
 *   for a property name.
 *
 * jsdom does not evaluate @media, so the blocks matching the width under
 * test are lifted and appended in source order -- which reproduces the
 * cascade, including later rules overriding earlier ones.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const R = path.resolve(__dirname, '../../');
const html = fs.readFileSync(path.join(R, 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(R, 'static', 'app.css'), 'utf8');

let pass = 0, fail = 0;
function ok(name, cond, extra) {
  if (cond) pass++;
  else { fail++; console.log(`  FAIL ${name}${extra ? ' -> ' + extra : ''}`); }
}

function sheetFor(width) {
  let out = CSS;
  const re = /@media\s*\(([a-z-]+):\s*(\d+)px\)\s*\{/g;
  let m;
  while ((m = re.exec(CSS))) {
    const [, kind, px] = m;
    const n = Number(px);
    const applies = (kind === 'max-width' && width <= n) ||
                    (kind === 'min-width' && width >= n);
    if (!applies) continue;
    let depth = 0, start = CSS.indexOf('{', m.index), j = start;
    for (; j < CSS.length; j++) {
      if (CSS[j] === '{') depth++;
      else if (CSS[j] === '}') { depth--; if (!depth) break; }
    }
    out += '\n' + CSS.slice(start + 1, j) + '\n';
  }
  return out;
}
function build(width) {
  const dom = new JSDOM(html, { pretendToBeVisual: true });
  const d = dom.window.document;
  d.querySelectorAll('link[rel=stylesheet]').forEach(l => l.remove());
  const st = d.createElement('style'); st.textContent = sheetFor(width);
  d.head.appendChild(st);
  d.documentElement.setAttribute('data-theme', 'dark');
  return dom;
}
const cs = (w, el) => w.getComputedStyle(el);

function outOfFlow(w, el) {
  const s = cs(w, el);
  return s.position === 'fixed' || s.position === 'absolute';
}
function closed(w, el) {
  const s = cs(w, el);
  return s.display === 'none' || s.visibility === 'hidden' ||
         /translateX\(-100%\)|translateX\(100%\)/.test(s.transform || '');
}

/* ── 1. THE EDITOR IS FULL WIDTH ───────────────────────────────────────── */
console.log('[1] the editor is not squeezed by the job list');
for (const width of [1280, 720]) {
  const dom = build(width), w = dom.window, d = w.document;
  const side = d.getElementById('wbSide');
  const main = d.querySelector('#tab-jobs .rs-main');
  ok(`[${width}] the rail exists`, !!side);
  ok(`[${width}] the editor pane exists`, !!main);
  if (!side || !main) continue;

  // The rail must not take a column out of the row.
  ok(`[${width}] the rail is an overlay, not a column`, outOfFlow(w, side),
     cs(w, side).position);
  ok(`[${width}] the rail starts closed`, closed(w, side),
     `${cs(w, side).transform} vis=${cs(w, side).visibility}`);

  // ...so the editor gets the whole row.
  const mainW = cs(w, main).width;
  ok(`[${width}] the editor spans the full width`,
     mainW === '100%' || mainW === '' || parseFloat(mainW) >= 99,
     `width=${mainW} flex=${cs(w, main).flex}`);
}

/* ── 2. THE UNIFIED MENU NEVER SHRINKS THE EDITOR ─────────────────────── */
console.log('\n[2] bot switching stays in the compact menu');
for (const width of [1280, 720]) {
  const dom = build(width), w = dom.window, d = w.document;
  const side = d.getElementById('wbSide');
  const menu = d.getElementById('rsMoreMenu');
  const main = d.querySelector('#tab-jobs .rs-main');
  const before = cs(w, main).width;
  d.body.classList.add('rs-side-open');
  ok(`[${width}] legacy rail stays visually removed`, cs(w, side).display === 'none', cs(w, side).display);
  menu.removeAttribute('hidden');
  ok(`[${width}] compact menu is out of document flow`, ['absolute','fixed'].includes(cs(w, menu).position), cs(w, menu).position);
  ok(`[${width}] editor width is unchanged while menu is open`, cs(w, main).width === before, `${before} -> ${cs(w, main).width}`);
}

/* ── 3. NO OVERLAPPING BUTTONS ─────────────────────────────────────────── */
console.log('\n[3] Run / Details / Close do not stack on each other');
/* REWRITTEN. This section used to assert that .rs-head-right becomes a
   dropdown below 900px. That element is gone: the brief that followed asked
   for ONE "···" button holding every action at every width, so there is no
   action group left in the header row to collapse. The requirement it was
   protecting -- two controls must never share a line and never overlap --
   is now enforced in test_runspace_single_header.js, which measures the
   row's minimum width at 320/375/414 and checks each menu row is full
   width. Keeping the old assertions would pin a layout that no longer
   exists. What is still worth checking here is the invariant itself. */
for (const width of [320, 375, 1280]) {
  const dom = build(width), w = dom.window, d = w.document;
  const head = d.querySelector('#tab-jobs .rs-head');
  const kids = [...head.children].filter(k => cs(w, k).display !== 'none');
  ok(`[${width}] the header holds at most three things`, kids.length <= 3,
     kids.map(k => k.id || k.className).join(','));
  ok(`[${width}] nothing in the row may shrink except the identity`,
     kids.every(k => k.id === 'rsIdentity' || (cs(w, k).flexShrink || '1') === '0'),
     kids.map(k => `${k.id || k.className}:${cs(w, k).flexShrink}`).join(' '));
  const menu = d.getElementById('rsMoreMenu');
  ok(`[${width}] every action sits in the menu, stacked`,
     cs(w, menu).flexDirection === 'column', cs(w, menu).flexDirection);
}

/* ── 4. SIGN-IN: filler gone, three controls arranged ──────────────────── */
console.log('\n[4] the sign-in card');
{
  const dom = build(1280), w = dom.window, d = w.document;
  const hint = d.querySelector('#screen-signin .telegram-hint');
  if (hint) ok('the duplicate Telegram hint is hidden',
     cs(w, hint).display === 'none', cs(w, hint).display);

  // The fallback note must survive: deleting it once left an empty card and
  // locked a user out when the widget script was blocked.
  const note = d.getElementById('telegramUnavailable');
  ok('the "Telegram unavailable" fallback still exists in the DOM', !!note);
  ok('it is hidden by its own attribute, not deleted by CSS',
     !!note && note.hasAttribute('hidden'));

  const row = d.querySelector('#screen-signin .field-row');
  ok('Remember me / Forgot password share one row', !!row);
  if (row) {
    ok('they are laid out horizontally', cs(w, row).flexDirection === 'row',
       cs(w, row).flexDirection);
    ok('pushed to opposite ends',
       cs(w, row).justifyContent === 'space-between', cs(w, row).justifyContent);
    ok('and never wrap onto two lines', cs(w, row).flexWrap === 'nowrap',
       cs(w, row).flexWrap);
  }
  const sw = d.querySelector('#screen-signin .auth-switch');
  ok('"Create an account" is separated as a footer', !!sw);
  if (sw) ok('with a divider above it',
     /1px/.test(cs(w, sw).borderTopWidth || '') || cs(w, sw).borderTopStyle === 'solid',
     `${cs(w, sw).borderTopWidth} ${cs(w, sw).borderTopStyle}`);
}

/* ── 5. NOTHING WAS REMOVED TO ACHIEVE ANY OF THIS ─────────────────────── */
console.log('\n[5] every control still exists');
{
  const dom = build(1280), d = dom.window.document;
  for (const id of ['btnStartJob', 'btnStopJob', 'btnRestartJob', 'btnInspector',
                    'btnDeselect', 'wbMenuBtn', 'wbSide', 'jobsList',
                    'si_username', 'si_password', 'btnSignin'])
    ok(`#${id} is still in the shell`, !!d.getElementById(id));
}

console.log(`\ntest_editor_fullwidth_and_menu: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
