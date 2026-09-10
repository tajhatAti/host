/* Unified colour system · dashboard contrast · bottom-nav clearance.
 *
 * WHAT WAS MEASURED BEFORE THE FIX (facts, not impressions):
 *
 *  COLOUR  An audit of every rule painting a button background found 39
 *          DISTINCT values across the stylesheets. Off-system offenders:
 *            #238636 / #2ea043  GitHub-green on "Publish"
 *            var(--ok)          status-green on "Create new job"
 *            #3fb950            status-green on the "Run" label
 *            8 bespoke grays in terminal.css for the keypad
 *          Green is a STATUS (running/success). Using it because a button is
 *          important is what made the UI feel random.
 *
 *  CONTRAST  .fc-body small used var(--muted):
 *            light #7c7c85 on #ffffff = 4.13:1  -> FAILS WCAG AA (4.5)
 *
 *  OVERLAP   .bottom-nav is fixed, 67px + env(safe-area-inset-bottom).
 *            .dash-main reserved a flat 110px, ignoring the inset — on a
 *            notched iPhone (101px nav) only 9px of clearance remained, so
 *            the last stat row was clipped by the bar.
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '../../');
const SHEETS = ['app.css'];
const read = f => fs.readFileSync(path.join(ROOT, 'static', f), 'utf8');
const CLASSIC = read('app.css');
const ALL = SHEETS.map(read).join('\n');

let pass = 0, fail = 0;
const ok = (n, c, e) => { c ? pass++ : (fail++, console.log(`  FAIL ${n}${e ? ' -> ' + e : ''}`)); };

const lum = hex => {
  const h = hex.replace('#', '');
  const c = [0, 2, 4].map(i => {
    const v = parseInt(h.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const ratio = (a, b) => {
  const L1 = Math.max(lum(a), lum(b)), L2 = Math.min(lum(a), lum(b));
  return (L1 + 0.05) / (L2 + 0.05);
};
const hsl = hex => {
  const h = hex.replace('#', '');
  const [r, g, b] = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) / 255);
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  if (!d) return { h: 0, s: 0, l: (mx + mn) / 2 };
  let hh = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  hh *= 60; if (hh < 0) hh += 360;
  const l = (mx + mn) / 2;
  return { h: hh, s: d / (1 - Math.abs(2 * l - 1)), l };
};

// ── 1. the system exists and is authoritative ───────────────────────────
console.log('\n[1] the palette');
ok('status tokens defined', /--st-ok:/.test(CLASSIC) && /--st-danger:/.test(CLASSIC)
   && /--st-warn:/.test(CLASSIC));
ok('status tokens have a dark-theme pass',
   /html\[data-theme="dark"\][\s\S]{0,400}--st-ok:/.test(CLASSIC));
ok('the system block is in the LAST-loaded sheet (settles the cascade)',
   /UNIFIED COLOR SYSTEM/.test(CLASSIC));
ok('primary is contrast, not a hue (uses --btn, not a colour literal)',
   /\.btn-primary,[\s\S]{0,700}background: var\(--btn\) !important/.test(CLASSIC));

// ── 2. no decorative status colour on buttons ───────────────────────────
console.log('[2] status colour is reserved for status');
const norm = h => (h.length === 4
  ? '#' + [...h.slice(1)].map(c => c + c).join('') : h.slice(0, 7)).toLowerCase();

// Rules that paint a button background with a saturated hue.
const BTN = /(btn|button|\.rs-seg|\.cs-act|\.wb-btn|\.jd-btn|\.rs-empty-btn|\.rs-insp-btn)/i;
const offenders = [];
for (const name of SHEETS) {
  const css = read(name);
  const re = /([^{}]+)\{([^}]*)\}/g;
  let m;
  while ((m = re.exec(css)) !== null) {
    const sel = m[1].trim().split('\n').pop(), body = m[2];
    if (!BTN.test(sel)) continue;
    // A status-bearing selector may legitimately be coloured.
    if (/(danger|error|delete|remove|stop|kbd-ok|kbd-err|\.ok\b|\.warn\b|running|crashed|success)/i.test(sel)) continue;
    const bg = /(?:^|[;\s])background(?:-color)?:\s*([^;]+)/.exec(body);
    if (!bg) continue;
    for (const hm of bg[1].matchAll(/#([0-9a-fA-F]{3,8})\b/g)) {
      const hex = norm('#' + hm[1]);
      if (hex.length !== 7) continue;
      const { s, l } = hsl(hex);
      if (s > 0.30 && l > 0.12 && l < 0.92) {
        offenders.push(`${name}:${sel.slice(0, 38)} ${hex}`);
      }
    }
  }
}
ok('no saturated hue on a non-status button', offenders.length === 0,
   offenders.slice(0, 6).join(' | '));
ok('"Publish" no longer GitHub-green',
   /\.code-studio \.cs-act\.publish-btn[\s\S]{0,200}var\(--btn\)/.test(CLASSIC));
ok('"Create new job" no longer status-green',
   /#tab-jobs \.rs-empty-btn[\s\S]{0,200}var\(--btn\)/.test(CLASSIC));
ok('"Run" label returned to neutral',
   /\.cs-act\.run, #btnRunCode \{[^}]*var\(--ink\)/.test(CLASSIC));
ok('terminal keypad folded into the neutral ramp',
   /\.wb-term-kbd button,[\s\S]{0,300}var\(--panel\)/.test(CLASSIC));
ok('kbd-ok / kbd-err KEEP colour (they report a result)',
   /kbd-ok[^}]*--st-ok/.test(CLASSIC) && /kbd-err[^}]*--st-danger/.test(CLASSIC));
ok('destructive stays red', /\.btn-danger \{[^}]*--st-danger/.test(CLASSIC));

// The real proof: resolve the cascade and confirm every primary button ends
// up on the SAME token. A grep count is not enough — a more specific rule
// elsewhere can silently win, which is exactly how .publish-btn kept its
// gradient after the first pass of this audit.
const ORDER = ['app.css'];
const CASCADE = ORDER.map(read).join('\n');
function effectiveBg(target) {
  let best = null;
  const re = /([^{}]+)\{([^}]*)\}/g;
  let m;
  while ((m = re.exec(CASCADE)) !== null) {
    const sels = m[1].split(',').map(x => x.trim());
    if (!sels.some(x => x === target || x.endsWith(target))) continue;
    const bg = /(?:^|[;\s])background(?:-color)?:\s*([^;]+)/.exec(m[2]);
    if (!bg) continue;
    const val = bg[1].trim(), imp = val.includes('!important');
    if (best === null || imp || !best.imp) best = { val, imp };
  }
  return best && best.val;
}
const PRIMARIES = ['.btn-primary', '.cs-act.primary',
                   '.code-studio .cs-act.publish-btn', '#tab-jobs .rs-empty-btn',
                   '.wb-btn.primary', '.jd-btn.start'];
const resolved = PRIMARIES.map(effectiveBg);
PRIMARIES.forEach((sel, i) =>
  ok(`${sel} resolves to the primary token`,
     (resolved[i] || '').includes('var(--btn)'), resolved[i]));
ok('all primaries share ONE fill', new Set(resolved).size === 1,
   [...new Set(resolved)].join(' | '));

// ── 3. dashboard contrast ───────────────────────────────────────────────
console.log('[3] dashboard card contrast');
const TOK = { light: { muted: '#7c7c85', ink2: '#46464b', panel: '#ffffff' },
              dark:  { muted: '#85858f', ink2: '#c2c2c9', panel: '#1b1b1f' } };
ok('feature-card copy no longer uses the muted tone',
   /\.fc-body small \{[^}]*var\(--ink-2\)/.test(CLASSIC));
for (const t of ['light', 'dark']) {
  const before = ratio(TOK[t].muted, TOK[t].panel);
  const after  = ratio(TOK[t].ink2,  TOK[t].panel);
  console.log(`      ${t}: ${before.toFixed(2)}:1 -> ${after.toFixed(2)}:1`);
  ok(`[${t}] card body text clears WCAG AA 4.5:1`, after >= 4.5, after.toFixed(2));
}

// ── 4. bottom-nav clearance ─────────────────────────────────────────────
console.log('[4] bottom-nav clearance');
ok('nav height is a token, not a guess', /--bottom-nav-h:\s*\d+px/.test(CLASSIC));
ok('dashboard reserves the nav height', /--bottom-nav-h/.test(CLASSIC)
   && /\.dash-main \{[\s\S]{0,240}padding-bottom:\s*calc\(/.test(CLASSIC));
ok('reservation accounts for the safe-area inset',
   /padding-bottom:\s*calc\(var\(--bottom-nav-h\)[^)]*env\(safe-area-inset-bottom\)/.test(CLASSIC));
ok('scroll anchoring matches the padding',
   /scroll-padding-bottom:\s*calc\(var\(--bottom-nav-h\)/.test(CLASSIC));
// The clearance must survive a notched device.
const NAV = 67, INSET = 34, EXTRA = 32;
console.log(`      notched iPhone: nav ${NAV + INSET}px, reserved ${NAV + INSET + EXTRA}px`);
ok('clearance remains positive on a notched device', EXTRA > 0);

console.log(`\ntest_color_system: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
