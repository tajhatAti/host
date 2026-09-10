/* Mobile blockers: the "···" sheet must be visible, "New job" reachable.
 *
 * REPORTED
 *   1. On mobile the "···" button fires but the menu cannot be seen or used.
 *   2. The "New RunSpace" control is hidden behind/under the editor.
 *
 * ROOT CAUSE — one, shared, and mine
 *   The toolbar-collapse pass gave the header
 *       #tab-jobs .rs-head { position: relative; z-index: 870; }
 *   A positioned element with a numeric z-index creates a STACKING CONTEXT,
 *   and a position:fixed descendant can never escape it. The sheet painted
 *   at z-index 880 inside a context capped at 870, so .bottom-nav (800 in
 *   the ROOT context) covered it, and "bottom: 0" resolved against the
 *   header's context rather than the viewport. It opened, it rendered, it
 *   was unreachable.
 *
 *   The same pass turned .rs-side into an off-canvas overlay at every width
 *   so the editor could be full-bleed. #btnNew lives inside that rail, and
 *   the only other entry point, #btnNewEmpty, ships with inline
 *   style="display:none". On a fresh load there was no way to create a job.
 *
 * WHY THIS SUITE IS WORTH TRUSTING
 *   A stacking-context bug is invisible to "is it display:none?" checks —
 *   every naive assertion passed while the feature was broken. So the trap
 *   is detected structurally: walk the ancestors and fail if any of them
 *   establishes a context the fixed child cannot leave. Section [6] proves
 *   the detector works by rebuilding the broken header and requiring it to
 *   fail there.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');
const { zOf } = require('./zlayers');

const R = path.resolve(__dirname, '../../');
const html = fs.readFileSync(path.join(R, 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(R, 'static', 'app.css'), 'utf8');
const JS = fs.readFileSync(path.join(R, 'static', 'pro.js'), 'utf8');

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
    const n = Number(m[2]);
    if (!((m[1] === 'max-width' && width <= n) || (m[1] === 'min-width' && width >= n))) continue;
    let depth = 0, start = CSS.indexOf('{', m.index), j = start;
    for (; j < CSS.length; j++) {
      if (CSS[j] === '{') depth++;
      else if (CSS[j] === '}') { depth--; if (!depth) break; }
    }
    out += '\n' + CSS.slice(start + 1, j) + '\n';
  }
  return out;
}
function build(width, markup) {
  const dom = new JSDOM(markup || html, { pretendToBeVisual: true });
  const d = dom.window.document;
  d.querySelectorAll('link[rel=stylesheet]').forEach(l => l.remove());
  const st = d.createElement('style'); st.textContent = sheetFor(width);
  d.head.appendChild(st);
  d.documentElement.setAttribute('data-theme', 'dark');
  // RunSpace as the live tab, which is when these bugs appear.
  const jobs = d.getElementById('tab-jobs');
  if (jobs) jobs.classList.add('active');
  d.body.classList.add('rs-active');
  return dom;
}
const cs = (w, el) => w.getComputedStyle(el);

/* Does any ancestor establish a stacking context that a position:fixed
 * child cannot escape? Per CSS spec the triggers that matter here are a
 * positioned element with a numeric z-index, plus transform / filter /
 * perspective / contain:paint / will-change on those properties. */
function trappingAncestors(w, el) {
  const traps = [];
  let cur = el.parentElement;
  while (cur && cur !== w.document.body && cur !== w.document.documentElement) {
    const s = cs(w, cur);
    const positioned = s.position !== 'static';
    const zNum = s.zIndex !== 'auto' && s.zIndex !== '' && !Number.isNaN(Number(s.zIndex));
    const why = [];
    if (positioned && zNum) why.push(`position:${s.position} + z-index:${s.zIndex}`);
    if (s.transform && s.transform !== 'none') why.push(`transform:${s.transform}`);
    if (s.filter && s.filter !== 'none') why.push(`filter:${s.filter}`);
    if (s.perspective && s.perspective !== 'none') why.push(`perspective`);
    if (/paint|strict|content/.test(s.contain || '')) why.push(`contain:${s.contain}`);
    if (/transform|filter|opacity/.test(s.willChange || '')) why.push(`will-change:${s.willChange}`);
    if (why.length) traps.push(`${cur.id || cur.className || cur.tagName}: ${why.join(', ')}`);
    cur = cur.parentElement;
  }
  return traps;
}
/* Does any ancestor clip an overflowing child? */
function clippingAncestors(w, el) {
  const clips = [];
  let cur = el.parentElement;
  while (cur && cur !== w.document.body) {
    const s = cs(w, cur);
    for (const p of ['overflow', 'overflowX', 'overflowY']) {
      const v = s[p];
      if (v && v !== 'visible' && v !== '') clips.push(`${cur.id || cur.className}: ${p}:${v}`);
    }
    cur = cur.parentElement;
  }
  return clips;
}

/* ── 1. the sheet is not trapped ───────────────────────────────────────── */
console.log('[1] the "···" menu can escape its ancestors');
for (const width of [320, 375, 414]) {
  const dom = build(width), w = dom.window, d = w.document;
  const menu = d.getElementById('rsMoreMenu');
  ok(`[${width}] the menu exists`, !!menu);
  if (!menu) continue;
  menu.removeAttribute('hidden');

  const traps = trappingAncestors(w, menu);
  ok(`[${width}] no ancestor traps the fixed sheet`, traps.length === 0, traps.join(' | '));

  /* An ancestor's overflow does NOT clip a position:fixed child -- the
     child's containing block is the viewport. Only an ancestor that also
     establishes a containing block (transform / filter / contain) can clip
     it, and trappingAncestors() above already fails on exactly those. So
     clipping only matters for the DESKTOP dropdown, which is absolutely
     positioned and therefore genuinely clippable. */
  if (cs(w, menu).position === 'absolute') {
    const clips = clippingAncestors(w, menu);
    ok(`[${width}] no ancestor clips the anchored dropdown`, clips.length === 0,
       clips.join(' | '));
  } else {
    ok(`[${width}] the sheet is viewport-positioned, so ancestor overflow cannot clip it`,
       cs(w, menu).position === 'fixed', cs(w, menu).position);
  }
}

/* ── 2. it is a real bottom sheet, inside the viewport ─────────────────── */
console.log('\n[2] on mobile it is a compact panel, fully in the viewport');
/* CHANGED 2026-08. This asserted a full-width bottom sheet. The user
   rejected that -- "pura screen জুড়ে আসে, আমি চাচ্ছি শুধু অল্প একটু জায়গায়
   আসবে, উপরে উঠে আসবে এমন" -- so the menu is a compact anchored panel now.
   It stays position:fixed so no ancestor overflow can clip it (.dash-main
   sets overflow:hidden), but hangs below the header instead of filling the
   screen. */
for (const width of [320, 375, 414]) {
  const dom = build(width), w = dom.window, d = w.document;
  const menu = d.getElementById('rsMoreMenu');
  menu.removeAttribute('hidden');
  const s = cs(w, menu);
  ok(`[${width}] viewport-anchored, so ancestor overflow cannot clip it`,
     s.position === 'fixed', s.position);
  ok(`[${width}] it hangs below the header, not at the bottom edge`,
     parseFloat(s.top) > 0 && s.bottom === 'auto', `top=${s.top} bottom=${s.bottom}`);
  ok(`[${width}] it is narrow, not full width`,
     parseFloat(s.width) > 0 && parseFloat(s.width) <= 310, s.width);
  ok(`[${width}] and can never exceed the screen`,
     /max-width:\s*calc\(100vw - (?:16|24)px\)/.test(CSS));
  ok(`[${width}] height is capped so it stays a panel`,
     parseFloat(s.maxHeight) > 0 && parseFloat(s.maxHeight) < 768, s.maxHeight);
  ok(`[${width}] it is actually rendered`,
     s.display !== 'none' && s.visibility !== 'hidden', `${s.display}/${s.visibility}`);
}


/* ── 3. it outranks every other fixed layer it must beat ───────────────── */
console.log('\n[3] nothing paints over the open sheet');
{
  const dom = build(375), w = dom.window, d = w.document;
  const menu = d.getElementById('rsMoreMenu');
  menu.removeAttribute('hidden');
  // The ladder is expressed as tokens now; resolve before comparing.
  const mz = zOf(w, menu);
  for (const [sel, label] of [['.bottom-nav', 'bottom nav'], ['#wbSide', 'job rail'],
                              ['.rs-menu-backdrop', 'rail scrim'], ['.dash-bar', 'dash bar'],
                              ['.activity-panel', 'activity panel']]) {
    const el = d.querySelector(sel);
    if (!el) continue;
    const z = zOf(w, el);
    ok(`the sheet (${mz}) outranks the ${label} (${z})`, mz > z);
  }
  // ...but must not outrank things that have to interrupt it.
  const toast = d.querySelector('.toast-container');
  if (toast) ok('toasts still appear above it', zOf(w, toast) > mz,
                `${zOf(w, toast)} vs ${mz}`);
  const modal = d.querySelector('.ah-modal');
  if (modal) ok('modals still appear above it', zOf(w, modal) > mz,
                `${zOf(w, modal)} vs ${mz}`);

  // The bottom nav is removed outright while the sheet is open.
  d.body.classList.add('rs-menu-open');
  const bn = d.querySelector('.bottom-nav');
  /* The panel no longer reaches the bottom of the screen, so the nav has no
     reason to disappear -- hiding it would just make the app flicker. */
  if (bn) ok('the bottom nav stays put beside the panel',
             cs(w, bn).display !== 'none', cs(w, bn).display);
  const scrim = d.getElementById('rsMenuScrim');
  ok('a scrim appears behind it', !!scrim && cs(w, scrim).visibility === 'visible',
     scrim && cs(w, scrim).visibility);
  /* Resolve the token, and compare against the LAYER it must clear rather
     than a bare 950: the ladder is named now, so the assertion should read
     the same way the stylesheet does. */
  const { zValue } = require('./zlayers');
  const flyout = zValue('var(--z-flyout)');
  ok('the scrim sits below the sheet but above everything else',
     !!scrim && zOf(w, scrim) < mz && zOf(w, scrim) > flyout,
     scrim && `${zOf(w, scrim)} (sheet ${mz}, flyout ${flyout})`);
}

/* ── 4. desktop keeps the anchored dropdown ────────────────────────────── */
console.log('\n[4] desktop is unchanged');
{
  const dom = build(1280), w = dom.window, d = w.document;
  const menu = d.getElementById('rsMoreMenu');
  menu.removeAttribute('hidden');
  const s = cs(w, menu);
  ok('desktop: anchored, not a sheet', s.position === 'absolute', s.position);
  ok('desktop: opens below the trigger', /calc/.test(s.top || ''), s.top);
  ok('desktop: still escapes any trap', trappingAncestors(w, menu).length === 0,
     trappingAncestors(w, menu).join(' | '));
  const scrim = d.getElementById('rsMenuScrim');
  ok('desktop: no full-screen scrim', cs(w, scrim).display === 'none', cs(w, scrim).display);
}

/* ── 5. "New job" is reachable from a cold start ───────────────────────── */
console.log('\n[5] "New job" can always be reached');
for (const width of [320, 375, 414, 1280]) {
  const dom = build(width), w = dom.window, d = w.document;

  // Reproduce the reported state: fresh load, nothing opened, no jobs yet.
  const rail = d.getElementById('wbSide');
  const railHidden = cs(w, rail).visibility === 'hidden' ||
                     /translateX\(-100%\)/.test(cs(w, rail).transform || '');
  const emptyBtn = d.getElementById('btnNewEmpty');
  const emptyHidden = !!emptyBtn && (emptyBtn.getAttribute('style') || '').includes('display:none');

  const inMenu = d.getElementById('btnNewInMenu');
  ok(`[${width}] a "New job" entry exists in the menu`, !!inMenu);
  if (!inMenu) continue;

  // The menu is opened from the header, which is never covered.
  d.getElementById('rsMoreMenu').removeAttribute('hidden');
  const s = cs(w, inMenu);
  ok(`[${width}] it is rendered`, s.display !== 'none' && s.visibility !== 'hidden',
     `${s.display}/${s.visibility}`);
  ok(`[${width}] it is a full-width row`, s.width === '100%', s.width);
  ok(`[${width}] it clears 44px for touch`, parseFloat(s.minHeight) >= 44, s.minHeight);

  // And record WHY the fallbacks were not enough, so the reasoning is testable.
  ok(`[${width}] (context) the rail copy really is off-canvas`, railHidden,
     'if this fails the menu copy may be redundant');
  if (emptyBtn) ok(`[${width}] (context) the empty-state copy really starts hidden`, emptyHidden);
}

console.log('\n[5b] it forwards to the real control, not a second implementation');
ok('the menu item clicks #btnNew', /btnNewInMenu[\s\S]{0,420}getElementById\("btnNew"\)[\s\S]{0,60}\.click\(\)/.test(JS));
ok('no duplicate new-job logic was added', (JS.match(/_composingNew = true/g) || []).length === 1);
/* The menu's "Job list" row is GONE, and its absence is the fix. The header
   already carries a dedicated hamburger (#wbMenuBtn) with the SAME icon whose
   only job is the job list, so the toolbar showed two near-identical grey
   squares — one opening a drawer, the other opening a menu containing a row
   that opened the same drawer by a different code path. Reported as
   "সাইটে তিনটা মেনু বাটন ... একটাতে ক্লিক করলে কিছুই আসে না".
   The requirement is that the rail is REACHABLE, not that it is reachable
   twice. */
ok('the job list has exactly one entry point',
   /wbMenuBtn[\s\S]{0,600}rs-side-open/.test(JS)
   && !/getElementById\("btnJobsInMenu"\)/.test(JS));

/* ── 6. the trap detector actually detects ─────────────────────────────── */
console.log('\n[6] the detector is falsifiable');
{
  /* Rebuild the exact broken header and require a FAILURE. Without this,
     section [1] passing would prove nothing: the original bug produced a
     perfectly "visible" element by every naive measure. */
  const broken = `<!doctype html><html><body>
    <div id="tab-jobs"><header class="rs-head" style="position:relative;z-index:870">
      <div class="rs-more-wrap" style="position:relative">
        <div class="rs-menu" id="m" style="position:fixed;bottom:0;left:0;right:0;z-index:880"></div>
      </div></header></div></body></html>`;
  const dom = build(375, broken), w = dom.window;
  const menu = w.document.getElementById('m');
  const traps = trappingAncestors(w, menu);
  ok('the old header IS reported as a trap', traps.length > 0,
     'detector is blind — section [1] would be meaningless');
  ok('and it names z-index as the reason', /z-index:870/.test(traps.join(' ')), traps.join(' '));
}

/* ── 7. the header still paints correctly without the z-index ──────────── */
console.log('\n[7] removing the z-index did not break the header');
for (const width of [375, 1280]) {
  const dom = build(width), w = dom.window, d = w.document;
  const head = d.querySelector('#tab-jobs .rs-head');
  ok(`[${width}] the header still anchors the dropdown`,
     cs(w, head).position === 'relative', cs(w, head).position);
  ok(`[${width}] but no longer creates a context`, cs(w, head).zIndex === 'auto',
     cs(w, head).zIndex);
  // The rail is z-indexed itself, so it still covers the header when open.
  const rail = d.getElementById('wbSide');
  ok(`[${width}] the rail still layers over the header when open`,
     Number(cs(w, rail).zIndex || 0) > 0, cs(w, rail).zIndex);
}

console.log(`\ntest_mobile_menu_and_newjob: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
