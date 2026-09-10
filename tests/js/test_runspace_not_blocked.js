/* RunSpace must be usable: no scrim over it, one rail, terminal in its tab.
 *
 * REPORTED (all at once, and all one family of defect):
 *   "Runspace a dhukle উপর দিয়ে পর্দার মতো কি জানি একটা থাকে কোন কাজ করা যায় না"
 *   "মেইন ডাই বোটে অনেকগুলা অগোছালো লেখা ... ট্যাব ESC এগুলা আছে"
 *   "ডেস্কটপ এর জন্য বানাতে পারো নাই মোবাইলের জন্য বানাতে পারো নাই"
 *   "মেনু বাটনে ক্লিক করলে ওখানে কোন কাজ হয় না"
 *
 * Root cause, mine: when nine stylesheets became one I wrote the OPEN state
 * of several components and never the closed state.
 *
 *   · .rs-menu-backdrop was `position:fixed; inset:0; z-index:855;
 *     background:rgba(0,0,0,.6)` with nothing to hide it. #wbBackdrop is the
 *     first child of #tab-jobs, so entering RunSpace dropped an opaque sheet
 *     over everything. It also explains the dead menu button: the click
 *     never reached it, and the rail it opens was under the scrim anyway.
 *
 *   · `.term, .term-page, .term-standalone { display:flex }` came after
 *     `.dash-tab-content { display:none }`, so the standalone terminal page
 *     -- ESC/TAB/CTRL keypad included -- won the cascade and rendered inside
 *     whatever tab happened to be open.
 *
 *   · rs-side-collapsed only had a desktop rule (`width:0`), but pro.js sets
 *     it on <body> at every width, so on a phone the class landed with
 *     nothing to answer it and the drawer looked stuck.
 *
 * jsdom ignores @media, so each width is built by lifting the matching
 * media blocks and appending them, exactly as the cascade would apply them.
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

/* Lift every @media block whose max/min-width matches `width`. */
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

/* Blocking = paints over the app AND swallows pointer events. */
function blocks(win, el) {
  const s = win.getComputedStyle(el);
  if (s.display === 'none' || s.visibility === 'hidden') return false;
  if (parseFloat(s.opacity || '1') === 0 && s.pointerEvents !== 'auto') return false;
  if (s.pointerEvents === 'none') return false;
  return s.position === 'fixed' || s.position === 'absolute';
}
function offCanvasOrHidden(win, el) {
  const s = win.getComputedStyle(el);
  return s.display === 'none' || s.visibility === 'hidden' ||
         /translateX\(-100%\)|translateX\(100%\)/.test(s.transform || '') ||
         (s.width || '').trim() === '0px';
}

console.log('[1] the sheet over RunSpace is gone');
for (const w of [1280, 720]) {
  const dom = build(w), win = dom.window, d = win.document;
  const bd = d.getElementById('wbBackdrop');
  ok(`#wbBackdrop exists (${w}px)`, !!bd);
  if (!bd) continue;
  ok(`[${w}] it does NOT block the view by default`, !blocks(win, bd),
     `pos=${win.getComputedStyle(bd).position} vis=${win.getComputedStyle(bd).visibility} pe=${win.getComputedStyle(bd).pointerEvents}`);
  ok(`[${w}] it does not swallow clicks`,
     win.getComputedStyle(bd).pointerEvents === 'none' ||
     win.getComputedStyle(bd).visibility === 'hidden' ||
     win.getComputedStyle(bd).display === 'none');
}

console.log('\n[2] the menu button is reachable and the rail responds');
{
  // Desktop: the rail is a column; collapsing folds it away.
  const dom = build(1280), win = dom.window, d = win.document;
  const side = d.getElementById('wbSide');
  const btn = d.getElementById('wbMenuBtn');
  ok('menu button exists', !!btn);
  /* CHANGED 2026-08. These two asserted that the rail is a permanent
     visible COLUMN on desktop. That was the behaviour until the user
     reported it as the actual problem -- "জব লিস্ট অনেক বড় হয়ে গেছে অনেকটা
     জায়গা খেয়ে ফেলছে ফলে ইডিটর ছোট হয়ে গেছে, এডিটর ফুল স্ক্রিন লাগবে".
     The rail is an overlay at every width now, so the editor always has
     the full row. Keeping the old assertions would have pinned the bug.
     What still matters is that it OPENS on desktop, which is checked
     immediately below. */
  ok('desktop: rail starts closed so the editor is full width',
     offCanvasOrHidden(win, side), win.getComputedStyle(side).transform);
  ok('desktop: rail overlays rather than taking a column',
     win.getComputedStyle(side).position === 'absolute' ||
     win.getComputedStyle(side).position === 'fixed',
     win.getComputedStyle(side).position);
  d.body.classList.add('rs-side-open');
  ok('desktop: it still opens on demand', !offCanvasOrHidden(win, side));
  d.body.classList.remove('rs-side-open');

  d.body.classList.add('rs-side-collapsed');
  d.body.classList.remove('rs-side-open');
  ok('desktop: rs-side-collapsed actually collapses it', offCanvasOrHidden(win, side),
     `width=${win.getComputedStyle(side).width}`);

  d.body.classList.remove('rs-side-collapsed');
  d.body.classList.add('rs-side-open');
  ok('desktop: rs-side-open brings it back', !offCanvasOrHidden(win, side));
}
{
  // Mobile: the rail is a drawer; BOTH classes must resolve to a closed
  // drawer, because pro.js sets them together from the measured width.
  const dom = build(720), win = dom.window, d = win.document;
  const side = d.getElementById('wbSide');
  ok('mobile: drawer starts off-canvas', offCanvasOrHidden(win, side),
     win.getComputedStyle(side).transform);

  d.body.classList.add('rs-side-open');
  d.body.classList.remove('rs-side-collapsed');
  ok('mobile: rs-side-open slides it in', !offCanvasOrHidden(win, side),
     win.getComputedStyle(side).transform);
  const bd = d.getElementById('wbBackdrop');
  ok('mobile: the scrim appears only WITH the open drawer', blocks(win, bd),
     win.getComputedStyle(bd).visibility);

  d.body.classList.remove('rs-side-open');
  d.body.classList.add('rs-side-collapsed');
  ok('mobile: rs-side-collapsed closes it too (not just desktop)',
     offCanvasOrHidden(win, side), win.getComputedStyle(side).transform);
  ok('mobile: scrim goes away with it', !blocks(win, bd));
}

console.log('\n[3] the terminal page stays in its own tab');
for (const w of [1280, 720]) {
  const dom = build(w), win = dom.window, d = win.document;
  const term = d.getElementById('tab-term');
  ok(`[${w}] #tab-term exists`, !!term);
  if (!term) continue;
  ok(`[${w}] terminal page is hidden while another tab is active`,
     win.getComputedStyle(term).display === 'none',
     win.getComputedStyle(term).display);
  const kbd = d.getElementById('standKbd');
  if (kbd) ok(`[${w}] the ESC/TAB keypad is hidden with it`,
     win.getComputedStyle(kbd).display === 'none' ||
     win.getComputedStyle(term).display === 'none');

  term.classList.add('active');
  ok(`[${w}] it shows when its tab is active`,
     win.getComputedStyle(term).display === 'flex',
     win.getComputedStyle(term).display);
  term.classList.remove('active');
  ok(`[${w}] and hides again`, win.getComputedStyle(term).display === 'none');
}

console.log('\n[4] RunSpace itself renders when selected');
{
  const dom = build(1280), win = dom.window, d = win.document;
  const jobs = d.getElementById('tab-jobs');
  ok('#tab-jobs hidden while inactive', win.getComputedStyle(jobs).display === 'none');
  jobs.classList.add('active');
  ok('#tab-jobs shows when active', win.getComputedStyle(jobs).display !== 'none',
     win.getComputedStyle(jobs).display);
  /* CHANGED 2026-08. This required z-index >= 860 on the header, and that
     requirement is what caused the next bug: a positioned element with a
     numeric z-index creates a STACKING CONTEXT, which trapped the "···"
     bottom sheet inside it -- the sheet rendered at 880 but could never
     paint above the header's own 870, so on mobile it was invisible.

     The requirement was also wrong on its own terms. The rail is an
     overlay; covering the header while it is OPEN is the drawer pattern
     working, not a defect. With the rail closed -- the default -- nothing
     covers the header at all. So assert what actually matters: the header
     is reachable when the rail is closed, and it does not trap its own
     descendants. */
  const head = d.querySelector('#tab-jobs .rs-head');
  ok('the header creates no stacking context (or the menu gets trapped)',
     win.getComputedStyle(head).zIndex === 'auto',
     win.getComputedStyle(head).zIndex);
  ok('with the rail closed nothing covers the header',
     offCanvasOrHidden(win, d.getElementById('wbSide')));
}

console.log('\n[5] desktop and mobile do not both apply');
{
  const deskCSS = sheetFor(1280);
  ok('desktop sheet pins the rail static',
     /@media \(min-width: 761px\)[\s\S]{0,700}position:\s*static/.test(CSS));
  ok('mobile sheet pins it fixed',
     /@media \(max-width: 760px\)[\s\S]{0,900}#tab-jobs \.rs-side\s*\{[\s\S]{0,200}position:\s*fixed/.test(CSS));
  ok('collapsed has a rule at BOTH widths',
     /@media \(min-width: 761px\)[\s\S]{0,900}rs-side-collapsed/.test(CSS) &&
     /@media \(max-width: 760px\)[\s\S]{0,1400}rs-side-collapsed/.test(CSS));
}

console.log(`\ntest_runspace_not_blocked: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
