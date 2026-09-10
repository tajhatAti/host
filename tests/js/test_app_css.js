/* app.css — the single stylesheet. Guards the rewrite, not a repaint.
 *
 * WHAT WENT WRONG BEFORE
 * ----------------------
 * Four rounds shipped a NEW sheet layered on top of the existing eight and
 * fought them with !important. The user's verdict: "তুমি তো আগের design er
 * oper প্রলেপ দিয়ে দিছো" -- a coat of paint. It was, because 1,973 lines of
 * classic.css and 1,959 of runspace-dark.css kept asserting the old shape
 * underneath, and a tenth sheet can only ever override what it thought to
 * name.
 *
 * So the nine sheets are deleted and app.css is the whole surface. The
 * risk of that is the opposite failure: a class that used to be styled by
 * a deleted sheet and is now styled by nothing, which shows up as a
 * collapsed or unreadable region rather than as an error. The first and
 * most important assertion here is therefore COVERAGE -- every class that
 * index.html or pro.js can put on an element must have a rule.
 *
 * jsdom notes, learned the hard way:
 *   · it does not resolve var() -- given `:root{--x:none}` getComputedStyle
 *     returns the literal string "var(--x)". Numeric values are resolved
 *     one level against the declared tokens.
 *   · it ignores @media entirely, so responsive rules are checked by
 *     lifting the block out of the source with brace counting.
 */
const fs = require('fs');
const path = require('path');
const postcss = require('postcss');
const { JSDOM } = require('jsdom');

const R = path.resolve(__dirname, '../../');
const html = fs.readFileSync(path.join(R, 'index.html'), 'utf8');
const js = fs.readFileSync(path.join(R, 'static', 'pro.js'), 'utf8');
const SRC = fs.readFileSync(path.join(R, 'static', 'app.css'), 'utf8');

let pass = 0, fail = 0;
function ok(name, cond, extra) {
  if (cond) pass++;
  else { fail++; console.log(`  FAIL ${name}${extra ? ' -> ' + extra : ''}`); }
}

// ── 1. ONE SHEET ───────────────────────────────────────────────────────
console.log('[1] one stylesheet, nine gone');
const links = [...html.matchAll(/<link rel="stylesheet" href="\/static\/([a-z0-9-]+\.css)/g)]
  .map(m => m[1]);
ok('exactly one local stylesheet is linked', links.length === 1, links.join(','));
ok('and it is app.css', links[0] === 'app.css', links[0]);
for (const dead of ['pro.css', 'classic.css', 'runspace-dark.css', 'workbench.css',
                    'codestudio.css', 'terminal.css', 'landing.css', 'emoji.css', 'nova.css']) {
  ok(`${dead} is deleted from disk`, !fs.existsSync(path.join(R, 'static', dead)));
  ok(`${dead} is not referenced by the shell`, !html.includes('/static/' + dead));
}

// ── 2. COVERAGE — the real risk of deleting nine sheets ────────────────
console.log('\n[2] coverage: no class left unstyled');
const styled = new Set();
postcss.parse(SRC).walkRules(r => r.selectors.forEach(s => {
  (s.match(/\.[a-zA-Z0-9_-]+/g) || []).forEach(c => styled.add(c.slice(1)));
}));
const used = new Set();
for (const src of [html, js])
  for (const m of src.matchAll(/class="([^"]+)"/g))
    m[1].split(/\s+/).forEach(c => { if (/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(c)) used.add(c); });
// Classes the script adds or removes at runtime never appear in markup.
for (const m of js.matchAll(/classList\.(?:add|remove|toggle)\(([^)]*)\)/g))
  (m[1].match(/["']([a-zA-Z0-9_-]+)["']/g) || []).forEach(s => used.add(s.slice(1, -1)));

const missing = [...used].filter(c => !styled.has(c)).sort();
ok(`every used class has a rule (${used.size} used)`, missing.length === 0,
   `${missing.length} unstyled: ${missing.slice(0, 25).join(' ')}`);

// ── 3. IT PARSES AND OWNS THE PAGE ─────────────────────────────────────
console.log('\n[3] renders');
let parsed = true;
try { postcss.parse(SRC, { from: 'app.css' }); } catch (e) { parsed = false; }
ok('app.css parses', parsed);

const dom = new JSDOM(html, { pretendToBeVisual: true });
const d = dom.window.document;
d.querySelectorAll('link[rel=stylesheet]').forEach(l => l.remove());
const st = d.createElement('style'); st.textContent = SRC; d.head.appendChild(st);
d.documentElement.setAttribute('data-theme', 'dark');
const cs = el => dom.window.getComputedStyle(el);

const PX = {};
for (const m of SRC.matchAll(/(--[a-z0-9-]+):\s*(-?[\d.]+)px\s*[;}]/gi)) PX[m[1]] = parseFloat(m[2]);
for (let i = 0; i < 3; i++)
  for (const m of SRC.matchAll(/(--[a-z0-9-]+):\s*var\((--[a-z0-9-]+)\)\s*[;}]/gi))
    if (PX[m[2]] !== undefined) PX[m[1]] = PX[m[2]];
function px(v) {
  v = (v || '').trim(); if (!v) return 0;
  const m = /^var\((--[a-z0-9-]+)\)$/i.exec(v);
  if (m) return PX[m[1]] !== undefined ? PX[m[1]] : NaN;
  const n = parseFloat(v); return Number.isNaN(n) ? NaN : n;
}

// ── 4. ROUND — the user's first complaint ──────────────────────────────
console.log('\n[4] round');
for (const sel of ['.stat-card', '.quick-card', '.feat-card', '.auth-card', '.term-card']) {
  const el = d.querySelector(sel);
  if (!el) continue;
  const r = px(cs(el).borderRadius);
  ok(`${sel} radius >= 12px`, r >= 12, `${cs(el).borderRadius} -> ${r}`);
}
ok('card radius token >= 16px', (PX['--r-card'] || 0) >= 16, `${PX['--r-card']}`);
ok('a pill radius exists', (PX['--pill'] || 0) >= 100, `${PX['--pill']}`);
ok('primary CTA is a pill', /\.btn-primary\s*\{[^}]*border-radius:\s*var\(--pill\)/s.test(SRC));

// ── 5. DEEP — the second complaint ─────────────────────────────────────
console.log('\n[5] deep');
ok('three elevation steps are defined', /--e1:/.test(SRC) && /--e2:/.test(SRC) && /--e3:/.test(SRC));
ok('elevation is layered, not one blur', /--e2:\s*[^;]*rgba[^;]*,[^;]*rgba/.test(SRC));
ok('a lit top edge exists', /--rim:\s*inset 0 1px 0 rgba\(255,255,255/.test(SRC));
ok('cards use elevation', /\.card,[\s\S]{0,600}box-shadow:\s*var\(--e2\), var\(--rim\)/.test(SRC));
ok('log wells are recessed, not raised', /inset 0 2px 10px rgba\(0,0,0/.test(SRC));

// ── 6. BUTTON ANIMATION — the third complaint ──────────────────────────
console.log('\n[6] button animation');
ok('buttons transition transform', /button,[\s\S]{0,700}transition:\s*transform/.test(SRC));
ok('buttons travel down when pressed', /button:active[^{]*\{[^}]*transform:\s*translateY\(1px\)/s.test(SRC));
ok('primary CTA lifts on hover', /\.btn-primary:hover[^{]*\{[^}]*translateY\(-2px\)/s.test(SRC));
ok('primary CTA glows on hover', /\.btn-primary:hover[^{]*\{[^}]*var\(--glow\)/s.test(SRC));
ok('tabs depress into an inset shadow', /\.dash-tab:active[\s\S]{0,160}inset 0 2px 6px/.test(SRC));
ok('cards lift on hover', /\.stat-card:hover[^{]*\{[^}]*translateY\(-3px\)/s.test(SRC));

// ── 7. BENTO ───────────────────────────────────────────────────────────
console.log('\n[7] bento layout');
ok('feature tiles are a 2-up grid', /\.feat-cards\s*\{[^}]*grid-template-columns:\s*1fr 1fr/s.test(SRC));
ok('metrics are a 4-up strip', /\.stats-grid\s*\{[^}]*repeat\(4, 1fr\)/s.test(SRC));
/* The intent is "the metric is the biggest text on the card", not the literal
   string 30px. Every font-size in the sheet now comes from the type scale
   (--fs-1..--fs-8) because eighteen ad-hoc sizes — four of them half-pixel —
   were making labels that should match look subtly misaligned. Assert the
   display step, which is what "big" means here. */
ok('big bento numerals',
   /\.stat-card b\s*\{[^}]*font-size:\s*var\(--fs-8\)/s.test(SRC)
   && /--fs-8:\s*30px/.test(SRC));

// ── 8. MOBILE ──────────────────────────────────────────────────────────
console.log('\n[8] mobile');
function media(q) {
  const i = SRC.indexOf(q); if (i < 0) return '';
  let depth = 0, start = SRC.indexOf('{', i), j = start;
  for (; j < SRC.length; j++) {
    if (SRC[j] === '{') depth++;
    else if (SRC[j] === '}') { depth--; if (!depth) break; }
  }
  return SRC.slice(start, j);
}
const M = media('@media (max-width: 760px)');
const M8 = media('@media (max-width: 860px)');
ok('phone breakpoint exists', M.length > 300, `${M.length}`);
ok('tablet breakpoint exists', M8.length > 80, `${M8.length}`);
ok('bento collapses to one column', /\.feat-cards\s*\{\s*grid-template-columns:\s*1fr/s.test(M8));
ok('bottom bar appears on phones', /\.bottom-nav\s*\{[^}]*display:\s*flex/s.test(M));
ok('desktop tab rail hides on phones', /\.dash-tabs\s*\{\s*display:\s*none/s.test(M));
ok('targets clear 44px', /min-height:\s*44px/.test(M));
ok('safe-area inset is honoured', /env\(safe-area-inset-bottom/.test(M));
ok('content clears the floating bar', /\.dash-main\s*\{[^}]*calc\(88px \+ env/s.test(M));
ok('hover transforms cancelled on touch', /:hover[^{]*\{\s*transform:\s*none/s.test(M));
ok('press feedback replaces hover', /:active[^{]*\{[^}]*scale\(\.985\)/s.test(M));
ok('runspace list becomes a drawer', /\.rs-side\s*\{[^}]*translateX\(-100%\)/s.test(M));
ok('drawer close button shows on phones', /\.rs-side-close\s*\{\s*display:\s*inline-flex/s.test(M));
ok('small-phone breakpoint exists', /@media \(max-width: 380px\)/.test(SRC));

// ── 9. PALETTE: grey/black, hue only for status ────────────────────────
console.log('\n[9] palette');
function hsl(hex) {
  const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255);
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), dl = mx - mn;
  const l = (mx + mn) / 2;
  return { s: dl ? dl / (1 - Math.abs(2 * l - 1)) : 0, l, h: dl ? (
    mx === r ? (((g - b) / dl) % 6) * 60 : mx === g ? ((b - r) / dl + 2) * 60 : ((r - g) / dl + 4) * 60
  ) : 0 };
}
// --st-* are aliases of the same three; they are status, not surfaces.
const STATUS = new Set(['--ok', '--warn', '--danger',
                        '--st-ok', '--st-warn', '--st-danger']);
/* The aurora palette is an indigo accent on a cool slate ramp, so the accent
   family is exempt from the surface scan — it is not a surface. What is still
   policed below: a surface token may be COOL, but it may not be warm, and it
   may not be saturated enough to read as a colour rather than a grey. */
const ACCENT_FAMILY = /^--(acc|accent|btn|ring|glow|chart-grid)/;
let hued = [];
for (const m of SRC.matchAll(/(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
  if (STATUS.has(m[1])) continue;
  // hsl() indexes from 1 because it expects the leading '#'. Passing an
  // already-stripped string shifted every channel by one and reported
  // #090909 at saturation .88, which is nonsense -- caught because a pure
  // grey cannot be saturated.
  if (ACCENT_FAMILY.test(m[1])) continue;
  const { s, h } = hsl(m[2]);
  const warm = h >= 10 && h <= 60 && s > 0.2;
  if (warm || s > 0.45) hued.push(`${m[1]}=${m[2]} sat=${s.toFixed(2)} h=${h.toFixed(0)}`);
}
ok('no surface or ink token is warm or reads as a colour', hued.length === 0, hued.join(' '));
for (const t of ['--ok', '--warn', '--danger'])
  ok(`${t} kept (colour means something)`, new RegExp(t + ':\\s*#').test(SRC));

// White fills would be frosted glass; white in a shadow is an edge light.
const glass = [];
postcss.parse(SRC).walkDecls(dcl => {
  const p = dcl.prop.toLowerCase();
  if (p.startsWith('--') && /(rim|e\d|glow|shadow)/.test(p)) return;
  if (!/^(background|background-color|background-image)$/.test(p)) return;
  if (/rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*0?\.[0-9]+/.test(dcl.value))
    glass.push(`${dcl.prop}: ${dcl.value}`);
});
ok('no translucent white fills (frosted glass)', glass.length === 0, glass.join(' | '));
ok('no backdrop-filter', !/backdrop-filter\s*:\s*(?!none)/i.test(SRC));

// ── 10. CONTRAST ───────────────────────────────────────────────────────
console.log('\n[10] contrast');
function lum(hex) {
  const c = [1, 3, 5].map(i => {
    const x = parseInt(hex.slice(i, i + 2), 16) / 255;
    return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + .05) / (y + .05); };
const tok = t => (new RegExp('\\' + t + ':\\s*(#[0-9a-f]{6})', 'i').exec(SRC) || [])[1];
for (const [label, a, b] of [
  ['ink on page',      '--fg',   '--bg'],
  ['secondary on page','--fg-2', '--bg'],
  ['tertiary on page', '--fg-3', '--bg'],
  ['ink on card',      '--fg',   '--card'],
  ['CTA label on CTA', '--acc-fg', '--acc'],
]) {
  const [x, y] = [tok(a), tok(b)];
  if (!x || !y) { ok(`${label} tokens resolve`, false, `${a}=${x} ${b}=${y}`); continue; }
  ok(`${label} passes AA`, ratio(x, y) >= 4.5, `${ratio(x, y).toFixed(2)}:1`);
}

// ── 11. NOTHING HIDDEN THAT SHOULD NOT BE ──────────────────────────────
console.log('\n[11] features intact');
for (const id of ['tab-overview', 'tab-code', 'tab-jobs', 'bottomNav',
                  'wbSide', 'btnSideClose', 'screen-signin', 'screen-signup'])
  ok(`#${id} still in the shell`, !!d.getElementById(id));
// .hidden is pro.js's own toggle and must keep working.
ok('.hidden still hides', /\.hidden[^{]*\{[^}]*display:\s*none/s.test(SRC));
ok('inactive tab panes are hidden', /\.dash-tab-content\s*\{\s*display:\s*none/s.test(SRC));
ok('active tab pane shows', /\.dash-tab-content\.active\s*\{[^}]*display:\s*block/s.test(SRC));

console.log(`\ntest_app_css: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
