/* Panels must be CLOSED until something opens them.
 *
 * THE BUG THIS LOCKS OUT
 * ----------------------
 * Reported as: "all time Activity Log Page asce kno?? admin ba dashboard
 * open korleu same ase, Just Activity Page ase" -- the Activity log covered
 * the entire app on every screen and could not be dismissed.
 *
 * Cause: pro.js opens these panels by ADDING `.open` and closes them by
 * REMOVING it. When the nine stylesheets were replaced by one, the rewrite
 * gave .activity-panel `position:fixed; display:flex; z-index:950` and no
 * `.open` rule whatsoever. With no closed state the panel painted itself
 * over the dashboard and the admin console permanently, and removing the
 * class changed nothing because nothing referenced it.
 *
 * That is a whole CLASS of defect, not one selector: any element the script
 * drives with a state class is broken the same way if the stylesheet only
 * describes the open state. So this suite walks pro.js, finds every element
 * driven by `.open`, and checks each one both ways.
 *
 * It measures COMPUTED style after applying the real sheet, so it fails on
 * the rendered result rather than on the presence of some text in the CSS.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const R = path.resolve(__dirname, '../../');
const html = fs.readFileSync(path.join(R, 'index.html'), 'utf8');
const js   = fs.readFileSync(path.join(R, 'static', 'pro.js'), 'utf8');
const css  = fs.readFileSync(path.join(R, 'static', 'app.css'), 'utf8');

let pass = 0, fail = 0;
function ok(name, cond, extra) {
  if (cond) pass++;
  else { fail++; console.log(`  FAIL ${name}${extra ? ' -> ' + extra : ''}`); }
}

function build(width) {
  const dom = new JSDOM(html, { pretendToBeVisual: true });
  const d = dom.window.document;
  d.querySelectorAll('link[rel=stylesheet]').forEach(l => l.remove());
  // jsdom ignores @media, so lift the block for the width under test and
  // append it, letting the later rules win exactly as a browser would.
  let sheet = css;
  if (width && width <= 760) {
    const q = '@media (max-width: 760px)';
    let from = 0, lifted = '';
    for (;;) {
      const i = sheet.indexOf(q, from);
      if (i < 0) break;
      let depth = 0, start = sheet.indexOf('{', i), j = start;
      for (; j < sheet.length; j++) {
        if (sheet[j] === '{') depth++;
        else if (sheet[j] === '}') { depth--; if (!depth) break; }
      }
      lifted += sheet.slice(start + 1, j) + '\n';
      from = j;
    }
    sheet = sheet + '\n' + lifted;
  }
  const st = d.createElement('style'); st.textContent = sheet; d.head.appendChild(st);
  d.documentElement.setAttribute('data-theme', 'dark');
  return dom;
}

// An element counts as hidden if it cannot be seen OR cannot be touched.
function isHidden(win, el) {
  const s = win.getComputedStyle(el);
  if (s.display === 'none') return true;
  if (s.visibility === 'hidden') return true;
  if (parseFloat(s.opacity || '1') === 0) return true;
  if (/translateX\(100%\)|translateX\(-100%\)|translateY\(100%\)/.test(s.transform || '')) return true;
  if ((s.maxHeight || '').trim() === '0px' || (s.maxHeight || '').trim() === '0') return true;
  return false;
}

console.log('[1] the reported bug: Activity log is not always on screen');
{
  const dom = build(1280), w = dom.window, d = w.document;
  const panel = d.getElementById('activityPanel');
  ok('#activityPanel exists', !!panel);
  ok('it is CLOSED on a fresh dashboard', isHidden(w, panel),
     `display=${w.getComputedStyle(panel).display} vis=${w.getComputedStyle(panel).visibility} tf=${w.getComputedStyle(panel).transform}`);

  panel.classList.add('open');
  ok('adding .open reveals it', !isHidden(w, panel),
     `vis=${w.getComputedStyle(panel).visibility}`);

  panel.classList.remove('open');
  ok('removing .open hides it again (close button works)', isHidden(w, panel));
}

console.log('\n[2] it does not cover the dashboard or the admin console');
{
  const dom = build(1280), w = dom.window, d = w.document;
  const panel = d.getElementById('activityPanel');
  const ps = w.getComputedStyle(panel);
  // A fixed, high z-index element that is visible by default is exactly how
  // "every page looks like the Activity page" happens.
  const coversApp = ps.position === 'fixed' && !isHidden(w, panel);
  ok('no fixed always-visible overlay above the app', !coversApp,
     `position=${ps.position} z=${ps.zIndex}`);
  for (const id of ['tab-overview', 'tab-admin']) {
    const el = d.getElementById(id);
    if (!el) continue;
    ok(`#${id} is not obscured by a permanent panel`, isHidden(w, panel));
  }
}

console.log('\n[3] every element pro.js drives with .open has a closed state');
/* Find the elements the script toggles "open" on.
 *
 * Matching on proximity does not work here: openSideMenu() looks up
 * #sideOverlay and then calls .classList.add("open") on a DIFFERENT
 * element two lines down, so any character-window regex credits the
 * overlay with a state class it never receives. (#sideOverlay and
 * #activityOverlay are driven by .hidden; section [5] covers them.)
 *
 * So resolve it properly: find `x.classList.add("open")`, take the
 * variable name x, and look up what x was assigned from. */
const ids = new Set();
for (const m of js.matchAll(/([A-Za-z_$][\w$]*)\.classList\.(?:add|toggle)\("open"/g)) {
  const varName = m[1];
  const decl = new RegExp(
    '\\b' + varName + '\\s*=\\s*document\\.getElementById\\("([A-Za-z0-9_]+)"\\)'
  ).exec(js);
  if (decl) ids.add(decl[1]);
}

// ...and the one it reaches by selector.
const selectors = [...js.matchAll(/querySelector\("(\.[a-zA-Z0-9_-]+)"\)[\s\S]{0,220}?classList\.(?:add|toggle)\("open"/g)]
  .map(m => m[1]);

ok('found the .open-driven elements in pro.js', ids.size + selectors.length >= 3,
   `${[...ids].join(',')} ${selectors.join(',')}`);

for (const width of [1280, 720]) {
  const dom = build(width), w = dom.window, d = w.document;
  const label = width > 760 ? 'desktop' : 'mobile';
  for (const id of ids) {
    const el = d.getElementById(id);
    if (!el) continue;
    ok(`[${label}] #${id} starts closed`, isHidden(w, el),
       `display=${w.getComputedStyle(el).display} vis=${w.getComputedStyle(el).visibility}`);
    el.classList.add('open');
    ok(`[${label}] #${id} opens with .open`, !isHidden(w, el));
    el.classList.remove('open');
    ok(`[${label}] #${id} closes again`, isHidden(w, el));
  }
}

console.log('\n[4] the mobile drawer opens and closes, and stays a plain row on desktop');
{
  // On desktop .dash-tabs is the inline tab strip and must NOT be a drawer.
  const deskDom = build(1280), dw = deskDom.window;
  const deskTabs = dw.document.querySelector('.dash-tabs');
  ok('desktop: the tab rail is visible inline', !isHidden(dw, deskTabs),
     dw.getComputedStyle(deskTabs).transform);
  ok('desktop: it is not a fixed drawer', dw.getComputedStyle(deskTabs).position !== 'fixed');

  const mobDom = build(720), mw = mobDom.window;
  const mobTabs = mw.document.querySelector('.dash-tabs');
  ok('mobile: the drawer starts closed', isHidden(mw, mobTabs),
     `${mw.getComputedStyle(mobTabs).transform} vis=${mw.getComputedStyle(mobTabs).visibility}`);
  mobTabs.classList.add('open');
  ok('mobile: it opens', !isHidden(mw, mobTabs));
  mobTabs.classList.remove('open');
  ok('mobile: it closes', isHidden(mw, mobTabs));
}

console.log('\n[5] scrims start hidden too');
{
  const dom = build(1280), w = dom.window, d = w.document;
  for (const id of ['sideOverlay', 'activityOverlay']) {
    const el = d.getElementById(id);
    if (!el) continue;
    ok(`#${id} carries .hidden in the markup`, el.classList.contains('hidden'));
    ok(`#${id} is actually hidden`, isHidden(w, el));
  }
}

console.log('\n[6] a hidden panel is also unreachable, not just invisible');
// Translating a panel off-screen without hiding it leaves it clickable and
// still announced by screen readers -- the quieter half of the same bug.
{
  const dom = build(1280), w = dom.window, d = w.document;
  const panel = d.getElementById('activityPanel');
  const s = w.getComputedStyle(panel);
  ok('closed panel is visibility:hidden or display:none',
     s.visibility === 'hidden' || s.display === 'none',
     `vis=${s.visibility} display=${s.display}`);
}

console.log(`\ntest_panels_closed_by_default: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
