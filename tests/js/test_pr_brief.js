/* THE THREE ITEMS FROM THE BRIEF (pr.html), each pinned by behaviour.
 *
 * 1. MENU OPENS BUT ITEMS DO NOT RESPOND.
 *    Found by parsing the stylesheet rather than guessing: .side-overlay was
 *    declared TWICE. The first declaration grouped it with .ah-modal and
 *    .cmd-overlay — a MODAL rule — so the nav scrim inherited
 *    z-index: var(--z-modal) = 1000 and display: grid. The drawer it is
 *    meant to sit behind (.dash-tabs.open) is 940. 1000 > 940, so the scrim
 *    covered the menu edge to edge and every tap on Overview / Code /
 *    RunSpace / Activity / Profile landed on the scrim, which has no handler
 *    for them. Exactly the "invisible overlay absorbing clicks" class the
 *    brief describes.
 *    A second, smaller fault in the same area: .side-menu-btn had no
 *    breakpoint rule, so the hamburger rendered on desktop too, where
 *    .dash-tabs is already a visible inline row — pressing it raised the
 *    scrim and slid nothing into view.
 *
 * 2. SAVE & RUN GAVE NO FEEDBACK.
 *    startJob() did maintain a busy state, but on #btnStartJob (the Run row
 *    inside the ⋯ menu). The button the user presses is #btnRunQuick in the
 *    header, and the only thing mirrored onto it was a `loading` class
 *    (opacity .6) — no label change, no spinner.
 *    The lag was measured, not masked. Against the running server:
 *        t+  22 ms  POST /api/jobs returns, status "installing"
 *        t+  28 ms  the job is actually "running"
 *        t+2500 ms  the UI finally looks — a hardcoded setTimeout
 *    So the deploy took 28ms and the user waited another 2.4 SECONDS for a
 *    fixed timer. That timer is now a short backoff that stops as soon as
 *    the status settles.
 *
 * 3. DASHBOARD HAD NO VISUAL HIERARCHY.
 *    Measured: .feat-card, .stat-card and .quick-card all resolved to the
 *    same background (#161616), border (1px #282828), shadow and 18px
 *    radius. Three groups with three different jobs, rendered identically.
 */
const fs = require('fs');
const path = require('path');
const postcss = require('postcss');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const css = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const js = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, x) => {
  if (c) { pass++; console.log('  ok   ' + n); }
  else { fail++; console.log('  FAIL ' + n + (x !== undefined ? ' -> ' + x : '')); }
};

/* Resolve :root tokens so z-index comparisons use real numbers. */
const TOK = {};
postcss.parse(css).walkDecls(d => {
  if (d.prop.startsWith('--') && d.parent.type === 'rule'
      && d.parent.selectors.some(s => s.trim() === ':root')) TOK[d.prop] = d.value.trim();
});
function zval(raw) {
  let v = String(raw || '').trim();
  for (let i = 0; i < 8 && v.includes('var('); i++)
    v = v.replace(/var\(\s*(--[\w-]+)\s*(?:,\s*([^)]*))?\)/,
      (_, n, fb) => (TOK[n] !== undefined ? TOK[n] : (fb || '0')));
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}
/* Every z-index a selector receives, with its media context. */
function zIndexes(needle) {
  const out = [];
  postcss.parse(css).walkDecls('z-index', d => {
    const rule = d.parent;
    if (rule.type !== 'rule') return;
    if (!rule.selectors.some(s => s.includes(needle))) return;
    let media = null, p = rule.parent;
    while (p) { if (p.type === 'atrule' && p.name === 'media') { media = p.params; break; } p = p.parent; }
    out.push({ z: zval(d.value), media, sel: rule.selector });
  });
  return out;
}

// ───────────────────────────────────────────────────────────────────────────
console.log('[1] the menu is clickable: nothing sits on top of it');
// ───────────────────────────────────────────────────────────────────────────
const scrim = zIndexes('.side-overlay');
const drawer = zIndexes('.dash-tabs');
ok('the nav scrim has exactly one z-index', scrim.length === 1,
   scrim.map(r => `${r.z}${r.media ? ' @' + r.media : ''}`).join(', '));
ok('the drawer declares one too', drawer.length === 1,
   drawer.map(r => `${r.z}${r.media ? ' @' + r.media : ''}`).join(', '));
const zs = Math.max(0, ...scrim.map(r => r.z));
const zd = Math.max(0, ...drawer.map(r => r.z));
ok('the scrim sits BELOW the drawer it dims', zs < zd, `scrim ${zs} vs drawer ${zd}`);

/* The specific regression: the scrim must not be grouped with the modals,
   which is where both the 1000 and the display:grid came from. */
const modalRule = /\.ah-modal[^{]*\{/.exec(css);
ok('the nav scrim is not grouped with .ah-modal',
   modalRule && !modalRule[0].includes('.side-overlay'), modalRule && modalRule[0].trim());
ok('a closed scrim cannot take clicks',
   /\.side-overlay\.hidden[^{]*\{[^}]*pointer-events:\s*none/s.test(css));

/* The hamburger is a phone control. */
ok('the hamburger is hidden by default',
   /\.side-menu-btn\s*\{[^}]*display:\s*none/s.test(css));
const phoneBlock = (() => {
  const i = css.indexOf('@media (max-width: 760px)');
  return i < 0 ? '' : css.slice(i, i + 4000);
})();
ok('...and shown only on phones', /\.side-menu-btn\s*\{[^}]*display:\s*inline-flex/s.test(phoneBlock));

/* Behaviour: every item in the menu really does switch tab. */
{
  const dom = new JSDOM(
    html.replace(/<script[^>]+src="[^"]*"[^>]*><\/script>/g, '')
        .replace(/<link[^>]+rel="stylesheet"[^>]*>/g, ''),
    { url: 'https://codenest.test/dashboard', runScripts: 'dangerously', pretendToBeVisual: true });
  const w = dom.window, d = w.document;
  w.matchMedia = () => ({ matches: true, addEventListener(){}, removeEventListener(){},
                          addListener(){}, removeListener(){} });
  w.fetch = () => Promise.resolve({ ok: true, status: 200,
    json: async () => ({ jobs: [], stats: {} }), text: async () => '' });
  w.scrollTo = () => {};
  w.localStorage.setItem('ahad_token', 'T');
  const st = d.createElement('style'); st.textContent = css; d.head.appendChild(st);
  const sc = d.createElement('script'); sc.textContent = js; d.body.appendChild(sc);
  d.dispatchEvent(new w.Event('DOMContentLoaded', { bubbles: true }));

  setTimeout(() => {
    /* Only the items a normal user can actually SEE. #tabBtnAdmin ships with
       the `hidden` class and is revealed by pro.js after /profile confirms an
       admin session, so counting it would fail the run for the correct
       reason — it is not on screen to be tapped. */
    const tabs = [...d.querySelectorAll('.dash-tabs .dash-tab[data-tab]')]
      .filter(t => !t.classList.contains('hidden'));
    ok('the menu holds the expected items', tabs.length >= 4, String(tabs.length));
    ok('the admin tab stays hidden for a normal user',
       !!d.getElementById('tabBtnAdmin')
       && d.getElementById('tabBtnAdmin').classList.contains('hidden'));
    let moved = 0;
    for (const t of tabs) {
      const want = t.getAttribute('data-tab');
      t.dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
      const active = d.querySelector('.dash-tab-content.active');
      if (active && active.id === 'tab-' + want) moved++;
    }
    ok('every menu item navigates', moved === tabs.length, `${moved}/${tabs.length}`);

    // Opening and closing repeatedly must keep working (brief asks for 5+).
    const btn = d.getElementById('sideMenuBtn');
    let cycles = 0;
    for (let i = 0; i < 6; i++) {
      w.openSideMenu && w.openSideMenu();
      const opened = d.querySelector('.dash-tabs').classList.contains('open');
      w.closeSideMenu && w.closeSideMenu();
      const closed = !d.querySelector('.dash-tabs').classList.contains('open');
      if (opened && closed) cycles++;
    }
    ok('open/close survives 6 cycles', cycles === 6, `${cycles}/6`);

    step2();
  }, 700);
}

// ───────────────────────────────────────────────────────────────────────────
function step2() {
  console.log('\n[2] Save & Run reports what it is doing');
  ok('a state machine exists', /window\.rsRunState\s*=/.test(js));
  ['idle', 'saving', 'starting'].forEach(s =>
    ok(`the "${s}" state has a label`, new RegExp(`${s}:\\s*"`).test(js)));
  ok('the button is disabled while busy', /btn\.disabled = busy/.test(js));
  ok('screen readers are told too', /aria-busy/.test(js));
  ok('a spinner element is created', /rs-run-spin/.test(js) && /\.rs-run-spin\s*\{/.test(css));

  const startJob = js.slice(js.indexOf('async function startJob'));
  ok('startJob enters a busy state on click',
     /rsRunState\(editingId \? "saving" : "starting"\)/.test(startJob));
  ok('it reports "starting" once the write returns',
     /rsRunState\("starting"\)/.test(startJob));
  ok('it always returns to idle, including on error',
     /finally\s*\{[\s\S]{0,700}rsRunState\("idle"\)/.test(startJob));
  ok('failures still surface through the toast',
     /catch\s*\([\s\S]{0,200}toast\(/.test(startJob));

  /* THE MEASURED LAG. A fixed 2.5s wait meant a job that was running in 28ms
     still showed "Starting…" for two and a half seconds. */
  ok('the hardcoded 2.5s status wait is gone',
     !/setTimeout\(\(\) => \{ loadJobs\(\)\.catch\(\(\)=>\{\}\); \}, 2500\)/.test(js));
  ok('replaced by a backoff that stops when the status settles',
     /DELAYS\s*=\s*\[\s*250/.test(js)
     && /st === "running" \|\| st === "crashed" \|\| st === "stopped"/.test(js));

  ok('transitions are composited and short',
     /#tab-jobs \.rs-run-quick \{[^}]*transition:[^;]*opacity \.16s/s.test(css));
  ok('reduced motion is respected',
     /prefers-reduced-motion[\s\S]{0,300}rs-run-spin/.test(css));

  step3();
}

// ───────────────────────────────────────────────────────────────────────────
function step3() {
  console.log('\n[3] the dashboard has a visible hierarchy');
  const dom = new JSDOM(html, { pretendToBeVisual: true });
  const w = dom.window, d = w.document;
  d.documentElement.setAttribute('data-theme', 'dark');
  const st = d.createElement('style'); st.textContent = css; d.head.appendChild(st);
  const res = v => {
    let s = String(v || '');
    for (let i = 0; i < 8 && s.includes('var('); i++)
      s = s.replace(/var\(\s*(--[\w-]+)\s*(?:,\s*([^)]*))?\)/,
        (_, n, fb) => (TOK[n] !== undefined ? TOK[n] : (fb || '')));
    return s.trim();
  };
  const look = sel => {
    const el = d.querySelector(sel);
    if (!el) return null;
    const c = w.getComputedStyle(el);
    return [res(c.background || c.backgroundColor), res(c.border), res(c.boxShadow) || 'none',
            res(c.borderRadius)].join('|');
  };
  const primary = look('.feat-card'), support = look('.stat-card'), tertiary = look('.quick-card');
  ok('the three groups exist', !!primary && !!support && !!tertiary);
  ok('primary and supporting do not look identical', primary !== support);
  ok('primary and tertiary do not look identical', primary !== tertiary);
  ok('only the primary cards are raised',
     /\.feat-card\s*\{[^}]*box-shadow:\s*var\(--e2\)/s.test(css)
     && /\.stat-card\s*\{[^}]*box-shadow:\s*none/s.test(css)
     && /\.quick-card\s*\{[^}]*box-shadow:\s*none/s.test(css));

  const labels = [...d.querySelectorAll('.section-label')].map(e => e.textContent.trim());
  ok('the stats are announced as a group', labels.includes('Your usage'), labels.join(', '));
  ok('quick actions use the same label treatment', labels.includes('Quick actions'));
  ok('quick actions is no longer a page-level heading',
     !/<div class="quick">\s*<h2>/.test(html));

  /* The greeting must be quieter than the cards it introduces. */
  const h1 = d.querySelector('.welcome h1');
  const cardTitle = d.querySelector('.fc-body b');
  const px = el => parseFloat(res(w.getComputedStyle(el).fontSize)) || 0;
  ok('the greeting does not shout over the action cards',
     h1 && cardTitle && px(h1) <= 20, h1 ? res(w.getComputedStyle(h1).fontSize) : '?');

  /* Rhythm: every section on this page steps by the same amount. */
  const gaps = ['.welcome', '.feat-cards', '.stats-grid']
    .map(s => {
      const m = new RegExp('\\' + s + '\\s*\\{[^}]*margin-bottom:\\s*([^;]+)').exec(css);
      return m ? res(m[1]) : null;
    })
    .filter(Boolean);
  ok('sections share one vertical step', new Set(gaps).size === 1, gaps.join(' / '));

  console.log(`\ntest_pr_brief: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
}
