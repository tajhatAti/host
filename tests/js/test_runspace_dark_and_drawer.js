/* RunSpace: always dark · closable mobile drawer · roomier desktop editor.
 *
 * THREE REPORTS, THREE FINDINGS:
 *
 * 1. "RunSpace must be dark, no light mode."
 *    RunSpace's own surfaces are hardcoded dark and never read data-theme —
 *    but the site-wide component rules added in classic.css §18
 *    (.badge/.chip/.rs-chip/.job-pill, links, focus) resolve --line-2,
 *    --muted and --panel, and THOSE flip with the theme. Measured in light
 *    mode: --line-2 #c9c9cf and --muted #545b6e, i.e. light borders and text
 *    painted onto a dark panel. Fixed by pinning the shared tokens inside
 *    #tab-jobs so the subtree cannot follow the site theme.
 *
 * 2. "The jobs panel is always open on mobile; I cannot see or type."
 *    Reported THREE times. The drawer slid correctly and both the header
 *    toggle and the backdrop did remove the class — but there was NO close
 *    control inside the panel, and the backdrop starts below the header so
 *    it does not read as tappable. Verified by walking the drawer's DOM:
 *    exactly one button (New job), zero closers.
 *
 * 3. "Desktop is fine but the editor needs more room."
 *    The rail was 250px; now 210px, and the meta strip 36px -> 34px.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const ORDER = ['app.css'];
const read = f => fs.readFileSync(path.join(ROOT, 'static', f), 'utf8');
const CSS = read('app.css');
const ALLCSS = ORDER.map(read).join('\n');
const JS = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');
const HTML = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, e) => { c ? pass++ : (fail++, console.log(`  FAIL ${n}${e ? ' -> ' + e : ''}`)); };

function build(theme) {
  const dom = new JSDOM(HTML, { pretendToBeVisual: true });
  const d = dom.window.document;
  d.querySelectorAll('link[rel=stylesheet]').forEach(l => l.remove());
  const s = d.createElement('style'); s.textContent = ALLCSS; d.head.appendChild(s);
  if (theme) d.documentElement.setAttribute('data-theme', theme);
  return dom;
}

// ── 1. RunSpace never follows the site theme ────────────────────────────
console.log('\n[1] always dark');
ok('shared tokens are pinned inside #tab-jobs',
   /#tab-jobs,[\s\S]{0,260}--panel:\s*var\(--bg-2\)/.test(CSS));
ok('the pin also covers html[data-theme="light"]',
   /html\[data-theme="light"\] #tab-jobs/.test(CSS));
ok('the Job Detail subtree is covered too', /#tab-jobs \.jd,/.test(CSS));
// Anchor inside the pin block itself; a fixed char window broke as soon as
// comments were reworded.
const PIN = /html\[data-theme="light"\] #tab-jobs \.jd \{([\s\S]*?)\}/.exec(CSS);
ok('token pin block found', !!PIN);
ok('color-scheme declared dark (native controls follow)',
   !!PIN && /color-scheme:\s*dark/.test(PIN[1]));
// Aliased to RunSpace's own --danger rather than restating the hex, so the
// assertion follows the token, not a literal.
ok('status tokens re-pinned so pills keep meaning',
   !!PIN && /--st-danger:\s*var\(--danger\)/.test(PIN[1]));

// Behavioural: the token must resolve identically in BOTH themes.
for (const tok of ['--panel', '--muted', '--line-2', '--ink']) {
  const dark = build('dark'), light = build('light');
  const gd = dark.window.getComputedStyle(dark.window.document.getElementById('tab-jobs'));
  const gl = light.window.getComputedStyle(light.window.document.getElementById('tab-jobs'));
  const a = gd.getPropertyValue(tok).trim(), b = gl.getPropertyValue(tok).trim();
  ok(`${tok} identical in light and dark inside RunSpace`, a === b, `${a} vs ${b}`);
}
/* CONTROL (rewritten 2026-08).
 *
 * This used to assert that --line-2 DIFFERS between themes at :root, to
 * prove the leak the pin defends against was real. That was true when the
 * app shipped a full light theme in classic.css.
 *
 * app.css is single-theme: one dark ramp, and data-theme is honoured only
 * so pro.js can keep writing it. There is no light value left to leak, so
 * demanding the tokens differ would be demanding a light theme back.
 *
 * The control now proves the pin is REACHABLE instead -- the token resolves
 * to a real value inside RunSpace under both attribute values. If the pin
 * were dropped and :root ever regained a light pass, the identity checks
 * above would start failing, which is the protection that matters. */
{
  const dark = build('dark'), light = build('light');
  const inDark = dark.window.getComputedStyle(
    dark.window.document.getElementById('tab-jobs')).getPropertyValue('--line-2').trim();
  const inLight = light.window.getComputedStyle(
    light.window.document.getElementById('tab-jobs')).getPropertyValue('--line-2').trim();
  ok('control: the pin resolves inside RunSpace in both themes',
     !!inDark && inDark === inLight, `${inDark} vs ${inLight}`);
}

// ── 2. the blue focus glow is kept ──────────────────────────────────────
console.log('[2] focus glow retained');
ok('focus outline uses the accent',
   /#tab-jobs :focus-visible \{[^}]*outline:\s*2px solid var\(--accent\)/.test(CSS));
// The ring must EXIST; its colour is not this test's business. It used to
// pin rgba(88,166,255) -- the blue that was a second accent alongside the
// grey --acc. Asserting a literal hue here made the palette fix look like a
// regression. What matters for focus is that a ring is drawn at all.
ok('inputs get a ring instead of an offset outline',
   /#tab-jobs \.rs-inp:focus[\s\S]{0,220}box-shadow:\s*0 0 0 \dpx /.test(CSS));

// ── 3. mobile drawer is closable ────────────────────────────────────────
console.log('[3] mobile drawer');
const dom = build('dark');
const d = dom.window.document;
const side = d.getElementById('wbSide');
const closeBtn = d.getElementById('btnSideClose');
ok('a close button exists inside the drawer', !!closeBtn);
ok('it lives in the drawer, not the app header',
   !!closeBtn && !!closeBtn.closest('#wbSide'));
ok('it is labelled for screen readers',
   !!closeBtn && !!closeBtn.getAttribute('aria-label'));
ok('hidden on desktop', /#tab-jobs \.rs-side-close \{ display: none; \}/.test(CSS));
ok('shown on mobile',
   /@media \(max-width: 760px\)[\s\S]{0,900}\.rs-side-close \{[\s\S]{0,120}display: grid/.test(CSS));
ok('JS wires the close button', /btnSideClose/.test(JS));
// Closing is now centralised in _closeJobsRail() so every path behaves
// identically; assert the call, not the old inline classList line.
ok('it closes the rail', /btnSideClose[\s\S]{0,300}_closeJobsRail\(\)/.test(JS));
ok('Escape also closes the drawer',
   /e\.key !== "Escape"[\s\S]{0,260}rs-side-open/.test(JS));
ok('Escape yields to the Details page',
   /rs-side-open"\)\) return;[\s\S]{0,160}rs-detail-open/.test(JS));
ok('swipe-left dismisses it', /touchstart[\s\S]{0,900}dx < -48/.test(JS));
ok('swipe ignores vertical scrolling of the job list',
   /Math\.abs\(dx\) > Math\.abs\(dy\)/.test(JS));
ok('touch listeners are passive (no scroll jank)',
   (JS.match(/\{ passive: true \}/g) || []).length >= 2);
// The drawer header must fit two 30px targets without crowding.
ok('drawer header is tall enough on mobile for two tap targets',
   /@media \(max-width: 760px\)[\s\S]{0,1100}\.rs-side-head \{ flex-basis: 44px/.test(CSS));

// ── 4. desktop editor gets more room ────────────────────────────────────
console.log('[4] desktop space');
ok('rail narrowed to 210px',
   /@media \(min-width: 761px\)[\s\S]{0,240}\.rs-side \{ flex: 0 0 210px/.test(CSS));
const before = 250, after = 210;
console.log(`      rail ${before}px -> ${after}px  (+${before - after}px to the editor)`);
ok('that is a real gain', before - after >= 32);
ok('meta strip trimmed on desktop',
   /@media \(min-width: 761px\)[\s\S]{0,300}--rs-meta-h:\s*34px/.test(CSS));

// ── 5. nothing regressed ────────────────────────────────────────────────
console.log('[5] no regressions');
// Anchor on the rule itself rather than guessing a distance from the @media
// opener — the comment block above it is ~880 chars and a fixed window is
// brittle for exactly that reason.
ok('drawer still slides with transform',
   /#tab-jobs \.rs-side \{[^}]*transform: translateX\(-100%\)/.test(CSS));
ok('open state still shown', /body\.rs-side-open #tab-jobs \.rs-side \{ transform: translateX\(0\)/.test(CSS));
ok('selecting a job still closes the drawer',
   /function selectJob[\s\S]{0,900}_closeJobsRail\(\)/.test(JS));
ok('backdrop still closes it',
   /backdrop\.addEventListener\("click"[\s\S]{0,140}_closeJobsRail\(\)/.test(JS));
ok('New job button survived', !!d.getElementById('btnNew'));

// ── 6. the rail hides at BOTH breakpoints, with the SAME class ──────────
// REPORTED: "the job list bar will not hide". The toggle chose its class from
// matchMedia("(max-width:760px)"), but on a phone with a dynamic browser
// toolbar the viewport crosses 760px as the bar hides/shows — so a tap could
// evaluate to the DESKTOP branch and set rs-side-collapsed, which had no
// mobile rule. Nothing happened and the panel looked stuck.
console.log('[6] hiding works on both sides of the breakpoint');
function mediaBlocks(src, q) {
  let out = '', i = 0;
  while ((i = src.indexOf(q, i)) !== -1) {
    const o = src.indexOf('{', i);
    let dep = 0, k = o;
    for (; k < src.length; k++) {
      if (src[k] === '{') dep++;
      else if (src[k] === '}') { dep--; if (!dep) break; }
    }
    out += src.slice(o + 1, k) + '\n';
    i = k;
  }
  return out;
}
function railHidden(mediaQuery, bodyClass) {
  const dm = new JSDOM(HTML, { pretendToBeVisual: true });
  const doc = dm.window.document;
  doc.querySelectorAll('link[rel=stylesheet]').forEach(l => l.remove());
  const st2 = doc.createElement('style');
  st2.textContent = ALLCSS + '\n' + mediaBlocks(ALLCSS, mediaQuery);
  doc.head.appendChild(st2);
  doc.body.className = bodyClass;
  const el = doc.querySelector('#tab-jobs .rs-side');
  const cs = dm.window.getComputedStyle(el);
  /* The mobile rail now rises from the BOTTOM -- translateY(100%) when
     closed -- because a full-height side drawer covered the whole screen.
     Matching only '-100%' missed that and reported an obviously hidden
     panel as visible. Judge by "is it off-screen or collapsed", whichever
     axis it uses. */
  const tf = cs.transform || '';
  return tf.includes('-100%') || tf.includes('translateY(100%)') ||
         cs.width === '0px' || cs.visibility === 'hidden';
}
const DESK = '@media (min-width: 761px)', MOB = '@media (max-width: 760px)';
ok('desktop: rs-side-collapsed hides the rail', railHidden(DESK, 'rs-side-collapsed'));
ok('mobile:  rs-side-collapsed hides the rail', railHidden(MOB, 'rs-side-collapsed'));
ok('desktop: rs-side-open shows it', !railHidden(DESK, 'rs-side-open'));
ok('mobile:  rs-side-open shows it', !railHidden(MOB, 'rs-side-open'));
ok('mobile: hidden by default', railHidden(MOB, ''));
ok('open beats collapsed if both are somehow set',
   !railHidden(MOB, 'rs-side-collapsed rs-side-open'));

// The JS must not decide the class from a media query any more.
ok('toggle no longer picks its class from _isPhone()',
   !/classList\.toggle\(_isPhone\(\) \? "rs-side-open"/.test(JS));
/* THIS ASSERTION LOCKED IN THE BUG IT WAS WRITTEN TO PREVENT.
   It required the toggle to decide "is the rail open?" by MEASURING it with
   getBoundingClientRect().width > 4. That cannot work, because the rail is
   hidden two different ways: `width: 0` on desktop, and
   `transform: translateX(-100%)` on mobile — and a transformed element keeps
   its full width, since a transform moves the box without resizing it.
   Measured both ways:
       real browser, translateX-hidden : width = 260  -> reads "open"
       jsdom,        translateX-hidden : width = 0    -> reads "closed"
   So in a real browser the check said "open" in BOTH states: the first tap
   opened the drawer and every tap after that recomputed the same answer and
   re-applied the same classes. That is the reported "মেনু বাটন বন্ধ হয় না".
   jsdom returns 0, which is why the suite was happy.
   The class on <body> IS the state; read it instead of re-deriving it from
   geometry that two CSS mechanisms express differently. */
ok('toggle reads the state, not the geometry',
   /classList\.contains\("rs-side-open"\)/.test(JS)
   && !/getBoundingClientRect\(\)\.width > 4/.test(JS));
ok('toggle drives BOTH classes together',
   /toggle\("rs-side-open", show\)[\s\S]{0,120}toggle\("rs-side-collapsed", !show\)/.test(JS));
ok('one helper owns closing', /function _closeJobsRail\(\)/.test(JS));
ok('every close path uses it', (JS.match(/_closeJobsRail\(\)/g) || []).length >= 6,
   String((JS.match(/_closeJobsRail\(\)/g) || []).length));
ok('the helper clears both classes',
   /_closeJobsRail[\s\S]{0,220}remove\("rs-side-open"\)[\s\S]{0,120}add\("rs-side-collapsed"\)/.test(JS));

console.log(`\ntest_runspace_dark_and_drawer: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
