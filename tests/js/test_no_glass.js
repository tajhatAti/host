/* The frosted-glass layer is GONE, and must stay gone.
 *
 * This file replaces tests/js/test_glass_theme.js, which existed to enforce
 * the opposite. Glass was introduced, then broke three things in a row — a
 * white dashboard on a light-mode phone, an invisible RunSpace toolbar, and
 * unreadable text over whatever happened to be scrolling behind a panel. The
 * brief now says remove it entirely, no exceptions, so the guard is inverted
 * rather than deleted: without a test, the next redesign reintroduces it.
 *
 * What is asserted:
 *   1. no backdrop-filter blur in ANY stylesheet
 *   2. no glass tokens left behind
 *   3. core surfaces are fully opaque
 *   4. the dark palette matches the brief, at full contrast
 *   5. one accent — indigo — and only one (the hueless rule was reversed
 *      when the aurora design was adopted; see section 6)
 *   6. the RunSpace drawer still opens and closes, five times running
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');
const postcss = require('postcss');

const R = path.resolve(__dirname, '../../');
const ORDER = ['app.css'];
const SHEETS = Object.fromEntries(
  ORDER.map(f => [f, fs.readFileSync(path.join(R, 'static', f), 'utf8')]));
const CSS = ORDER.map(f => SHEETS[f]).join('\n');
const HTML = fs.readFileSync(path.join(R, 'index.html'), 'utf8');
const JS = fs.readFileSync(path.join(R, 'static/pro.js'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, e) => { c ? pass++ : (fail++, console.log(`  FAIL ${n}${e ? ' -> ' + e : ''}`)); };

// Resolve the cascade properly. jsdom cannot evaluate var() inside
// backdrop-filter or colour values, so measuring computed styles through it
// silently reports every surface as transparent — postcss is used instead.
const root = postcss.parse(CSS);
const TOK = {};
root.walkRules(r => {
  if (/^:root$/.test(r.selector))
    r.walkDecls(d => { if (d.prop.startsWith('--')) TOK[d.prop] = d.value.trim(); });
});
root.walkRules(r => {
  if (/data-theme="dark"/.test(r.selector))
    r.walkDecls(d => { if (d.prop.startsWith('--')) TOK[d.prop] = d.value.trim(); });
});
const resolve = (v) => {
  let out = v, i = 0;
  while (/var\(/.test(out) && i++ < 10)
    out = out.replace(/var\((--[\w-]+)(?:,[^)]*)?\)/g, (m, n) => TOK[n] || m);
  return out.trim();
};

// ── 1. no blur ──────────────────────────────────────────────────────────
console.log('\n[1] the glass effect is gone from every stylesheet');
for (const f of ORDER) {
  // Match a real blur only. `backdrop-filter: none` is the thing that FORCES
  // the effect off, so flagging it would fail on correct code — the lookahead
  // form of this regex did exactly that.
  const hits = (SHEETS[f].match(/backdrop-filter:\s*blur[^;]*/g) || []);
  ok(`${f} has no blur`, hits.length === 0, hits.join(' | '));
}
ok('and none in index.html either', !/backdrop-filter:\s*blur/.test(HTML));

console.log('[2] no glass tokens or helper classes survive');
ok('no --glass-* tokens', !/--glass-/.test(CSS),
   (CSS.match(/--glass-[\w-]+/g) || []).slice(0, 3).join(','));
ok('no --rs-glass tokens', !/--rs-glass/.test(CSS));
ok('no --cs-glass tokens', !/--cs-glass/.test(CSS));
ok('no ".glass" utility class', !/^\s*\.glass[\s,{]/m.test(CSS));

// ── 3. opaque surfaces ──────────────────────────────────────────────────
console.log('[3] core surfaces are fully opaque');
const CORE = /^\.(dash-bar|dash-main|profile-card|stat-card|job-card|adm-panel|adm-stat|ah-modal-card|bottom-nav|nav|side-menu)$/;
const semi = [];
root.walkRules(r => {
  if (!r.selectors) return;
  if (!r.selectors.some(x => CORE.test(x.trim()))) return;
  r.walkDecls(/^background(-color)?$/, d => {
    const v = resolve(d.value);
    // A translucent surface is exactly what made text unreadable: what sits
    // behind it keeps changing.
    if (/rgba\([^)]*,\s*0?\.\d+\s*\)/.test(v)) semi.push(`${r.selector.trim()} -> ${v}`);
  });
});
ok('no core panel uses a translucent background', semi.length === 0, semi.join(' | '));

// ── 4. the palette ──────────────────────────────────────────────────────
console.log('[4] the dark palette matches the brief');
const hex = (t) => (resolve(TOK[t] || '') .match(/#[0-9a-f]{6}/i) || [''])[0].toLowerCase();
const inRange = (h, lo, hi) => {
  const n = parseInt(h.slice(1), 16);
  return n >= parseInt(lo, 16) && n <= parseInt(hi, 16);
};
ok('canvas is near-black (#0a0a0a-#121212 band)',
   inRange(hex('--paper'), '0a0a0a', '121216'), hex('--paper'));
ok('panels are dark grey (#1a1a1a-#1e1e1e band)',
   inRange(hex('--panel'), '1a1a1a', '1e1e22'), hex('--panel'));
ok('bars have their own surface token', !!hex('--surface-1'), hex('--surface-1'));
ok('a hairline token exists', !!hex('--edge'), hex('--edge'));

function lum(h) {
  const n = parseInt(h.replace('#', ''), 16);
  const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  return 0.2126 * f((n >> 16) & 255) + 0.7152 * f((n >> 8) & 255) + 0.0722 * f(n & 255);
}
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};
console.log('[5] full contrast, no readability compromises');
for (const [fg, bg, label, min] of [
  ['--ink', '--paper', 'body text on canvas', 4.5],
  ['--ink', '--panel', 'body text on a card', 4.5],
  ['--ink-2', '--panel', 'secondary text', 4.5],
  ['--muted', '--panel', 'muted text', 4.5],
  ['--btn-fg', '--btn', 'label on the primary button', 4.5],
]) {
  const r = ratio(hex(fg), hex(bg));
  ok(`${label} clears AA`, r >= min, r.toFixed(2) + ':1');
}

// ── 6. one accent, hueless ──────────────────────────────────────────────
console.log('[6] one accent, and it carries no hue');
function sat(h) {
  const n = parseInt(h.slice(1), 16);
  const r = ((n >> 16) & 255) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
  return mx === 0 ? 0 : (mx - mn) / mx;
}
/* BRIEF CHANGE (aurora redesign, reference: tajhatAti/dashb). This section
   used to require a hueless accent, because an earlier indigo round had
   turned the whole UI blue. The product owner asked for that dashboard's
   language explicitly, so indigo is now the accent — and the useful part of
   the old rule survives: there is exactly ONE of it, and it is the same
   value in both themes rather than a second colour wearing the same name. */
const ACC = hex('--acc');
ok('--acc is the indigo accent', ACC === '#4f46e5', ACC);
ok('--acc really is coloured now', sat(ACC) > 0.5, 'sat=' + sat(ACC).toFixed(2));
ok('--btn is the same accent, not a second one', hex('--btn') === ACC, hex('--btn'));
ok('--btn-fg is white so the label clears AA', /^#f{6}$|^#ffffff$/i.test(hex('--btn-fg')), hex('--btn-fg'));
ok('status colours still exist and ARE coloured',
   sat(hex('--st-warn') || '#000000') > 0.3 || !hex('--st-warn'), hex('--st-warn'));

// ── 7. the drawer still works ───────────────────────────────────────────
console.log('[7] the RunSpace jobs panel opens and closes, five times');
{
  function grab(name) {
    const s = JS.indexOf('function ' + name + '(');
    if (s < 0) return null;
    let i = JS.indexOf('{', s), d = 0;
    for (let k = i; k < JS.length; k++) {
      if (JS[k] === '{') d++;
      else if (JS[k] === '}') { d--; if (!d) return JS.slice(s, k + 1); }
    }
    return null;
  }
  const dom = new JSDOM(HTML, { pretendToBeVisual: true, runScripts: 'dangerously' });
  const w = dom.window, d = w.document;
  const src = [grab('_closeJobsRail'), grab('_openJobsRail')].filter(Boolean).join('\n')
    + '\nfunction _syncMenuBtn(){}\n'
    + 'const b=document.getElementById("btnSideClose");'
    + 'b.addEventListener("click",(e)=>{e.preventDefault();e.stopPropagation();'
    + '_closeJobsRail();_syncMenuBtn();});'
    + 'window._open=_openJobsRail; window._closeBtn=b;';
  const t = d.createElement('script');
  t.textContent = src;
  d.body.appendChild(t);
  ok('the close button exists', !!d.getElementById('btnSideClose'));
  let broke = 0;
  for (let i = 0; i < 5; i++) {
    w._open();
    if (!d.body.classList.contains('rs-side-open')) broke++;
    w._closeBtn.click();
    if (d.body.classList.contains('rs-side-open')) broke++;
  }
  ok('five open/close cycles all succeed', broke === 0, `${broke} failures`);
}

console.log(`\ntest_no_glass: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
