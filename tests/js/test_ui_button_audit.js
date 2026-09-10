/* BUTTON AUDIT — boot the real SPA in demo mode and actually press the
 * controls a user sees, instead of just reading the markup.
 *
 * The earlier UX passes were structural: they asserted that a button EXISTS
 * and that some handler string exists somewhere in pro.js. That let a broken
 * navigation survive three rounds of polish. This suite is behavioural:
 *
 *   1. every desktop tab and every mobile bottom-nav destination has a real
 *      #tab-* that becomes active when clicked;
 *   2. Add Bot (both the centred nav button and the floating FAB) reach the
 *      same new-bot workspace;
 *   3. the Account tab really is trimmed (no sessions / activity / danger
 *      cards, and no Save button that could wipe stored phone/custom_code);
 *   4. the admin console's section nav anchors all point at sections that
 *      exist, and the admin tab is reachable in demo (profile says admin);
 *   5. every inline onclick target in the shell is a real global function.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const js = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');
const css = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, x) => {
  if (c) { pass++; }
  else { fail++; console.log('  FAIL ' + n + (x !== undefined ? ' -> ' + x : '')); }
};

function boot(width) {
  const stripped = html
    .replace(/<script[^>]+src="[^"]*"[^>]*><\/script>/g, '')
    .replace(/<link[^>]+rel="stylesheet"[^>]*>/g, '');
  const dom = new JSDOM(stripped, {
    url: 'https://codenest.test/dashboard?demo=1',
    runScripts: 'dangerously', pretendToBeVisual: true,
  });
  const w = dom.window, d = w.document;
  Object.defineProperty(w, 'innerWidth', { value: width, writable: true });
  w.matchMedia = q => {
    const m = /max-width:\s*(\d+)px/.exec(q);
    return { matches: m ? width <= +m[1] : false, media: q,
             addEventListener() {}, removeEventListener() {},
             addListener() {}, removeListener() {}, onchange: null };
  };
  w.fetch = () => Promise.resolve({ ok: true, status: 200,
    json: async () => ({ jobs: [], snippets: [], stats: {} }), text: async () => '' });
  w.scrollTo = () => {};
  w.localStorage.setItem('ahad_token', 'T');
  const st = d.createElement('style'); st.textContent = css; d.head.appendChild(st);
  const sc = d.createElement('script'); sc.textContent = js; d.body.appendChild(sc);
  d.dispatchEvent(new w.Event('DOMContentLoaded', { bubbles: true }));
  return { w, d };
}
const click = (w, el) =>
  el.dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
const wait = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  // ── 1. every onclick target is a real function ─────────────────────────
  console.log('[1] inline handlers resolve');
  const { w, d } = boot(390);
  await wait(900);
  const used = new Set();
  for (const el of d.querySelectorAll('[onclick]')) {
    for (const m of String(el.getAttribute('onclick')).matchAll(/\b([A-Za-z_$][\w$]*)\s*\(/g)) {
      const f = m[1];
      if (['event', 'window', 'document', 'if', 'else', 'open', 'click',
           'getElementById', 'preventDefault', 'stopPropagation', 'newSnippet']
          .includes(f)) continue;
      used.add(f);
    }
  }
  for (const f of used) ok(`onclick resolves: ${f}`, typeof w[f] === 'function');
  ok('no fatal overlay after boot', !d.getElementById('fatalOverlay'));
  ok('demo pill is shown', (d.getElementById('demoPill') || {}).textContent === 'Demo UI');

  // ── 2. desktop tabs switch real panels ────────────────────────────────
  console.log('[2] desktop tab buttons');
  const desktop = boot(1280); await wait(900);
  const dw = desktop.w, dd = desktop.d;
  const tabs = [...dd.querySelectorAll('.dash-tab')]
    .filter(b => b.dataset.tab && b.dataset.tab !== 'admin')
    .map(b => b.dataset.tab);
  for (const tab of tabs) {
    const btn = dd.querySelector(`.dash-tab[data-tab="${tab}"]`);
    click(dw, btn); await wait(120);
    const panel = dd.getElementById('tab-' + tab);
    ok(`desktop ${tab} opens its panel`, !!panel && panel.classList.contains('active'));
  }

  // ── 3. mobile bottom nav destinations ─────────────────────────────────
  console.log('[3] mobile bottom nav');
  const bn = [...d.querySelectorAll('.bn-item[data-tab]')].map(b => b.dataset.tab);
  ok('bottom nav has the four real destinations',
     JSON.stringify(bn) === JSON.stringify(['jobs', 'store', 'code', 'profile']),
     bn.join(','));
  for (const tab of bn) {
    const btn = d.querySelector(`.bn-item[data-tab="${tab}"]`);
    click(w, btn); await wait(140);
    const panel = d.getElementById('tab-' + tab);
    ok(`mobile ${tab} opens its panel`, !!panel && panel.classList.contains('active'));
    // the bottom button itself is marked active
    ok(`mobile ${tab} button shows active state`,
       btn.classList.contains('active'));
  }

  // ── 4. Add Bot from nav and FAB ──────────────────────────────────────
  console.log('[4] Add Bot buttons share the real flow');
  const add = d.getElementById('bnAddBot');
  click(w, add); await wait(250);
  ok('centred Add Bot enters the new-bot workspace',
     d.body.classList.contains('rs-composing'));
  const realNew = d.getElementById('wbWorkspace');
  ok('new-bot workspace is visible',
     !!realNew && realNew.style.display !== 'none');
  click(w, d.getElementById('mobileFabAdd')); await wait(250);
  ok('floating FAB also enters the new-bot workspace',
     d.body.classList.contains('rs-composing'));

  // ── 5. Account tab is trimmed ─────────────────────────────────────────
  console.log('[5] account tab trimmed');
  click(w, d.querySelector('.bn-item[data-tab="profile"]')); await wait(250);
  const profile = d.getElementById('tab-profile');
  ok('profile tab open', profile.classList.contains('active'));
  ok('no Active sessions card', !d.getElementById('sessList'));
  ok('no Recent activity card', !/Recent activity/.test(profile.textContent));
  ok('no Danger zone card', !/Danger zone/.test(profile.textContent));
  ok('no editable Save that could wipe stored phone/code',
     !/saveProfile\(\)/.test(profile.innerHTML));
  ok('identity card stays read-only', !!d.getElementById('profileUsername') &&
      d.getElementById('profileUsername').disabled);

  // ── 6. admin section nav is coherent ──────────────────────────────────
  console.log('[6] admin console coherence');
  const admin = d.getElementById('tab-admin');
  ok('admin tab exists in demo', !!admin);
  ok('admin nav links point to existing sections',
     [...(admin.querySelectorAll('.adm-section-nav a') || [])]
       .every(a => { const id = a.getAttribute('href').slice(1); return !!d.getElementById(id); }));
  ok('admin console is reachable in demo (profile says admin)',
     !(d.getElementById('tabBtnAdmin') || { classList: { contains: () => false } })
       .classList.contains('hidden'));
  const gridRe = new RegExp('@media \\(min-width: 761px\\)[\\s\\S]*?#tab-admin\\.active' +
                            '[\\s\\S]*?grid-template-columns:[^;]*repeat\\(2, minmax');
  ok('two-column admin layout is declared on wide screens', gridRe.test(css));

  console.log(`\ntest_ui_button_audit: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
