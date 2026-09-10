/* Palette guard that reads the STYLESHEET SOURCE, not just :root tokens.
 *
 * WHY THIS EXISTS (the hole it plugs)
 * -----------------------------------
 * test_no_warm_cast.js checks computed values of the tokens declared in
 * classic.css. It reported 108/108 green while the live site still looked
 * exactly as before, because it could not see two things:
 *
 *   1. runspace-dark.css, codestudio.css, workbench.css and landing.css
 *      hardcode GitHub's palette with !important -- #0d1117 (hue 216,
 *      sat .28), #161b22, #21262d (x21), #e6edf3 (x19). Those sheets never
 *      read the neutral tokens, so retuning the tokens changed nothing on
 *      the four biggest surfaces in the app.
 *   2. Its own hasHue() carried the comment "the dark IDE greys are very
 *      slightly blue-tinted by design and must not trip this" and a 0.12
 *      threshold, which is a deliberate exemption for exactly the colours
 *      that were wrong. A test that excuses the bug cannot catch it.
 *
 * It also only looked for a WARM cast, so a second accent (#58a6ff, used in
 * 31 places alongside --acc:#f2f2f4) passed silently -- two accents at once,
 * where the brief asks for one.
 *
 * Run against the pre-fix stylesheets this file reports 9 failures, so it
 * is known to actually catch the regression rather than merely pass.
 *
 * WHAT IS ALLOWED TO HAVE A HUE
 * -----------------------------
 * Status only, because there colour carries meaning: running/ok green,
 * crashed/error red, starting/warning amber. Plus syntax highlighting inside
 * the code editors, which is a reading aid, not UI chrome.
 */
const fs = require('fs');
const path = require('path');

const R = path.resolve(__dirname, '../../');
const SHEETS = fs.readdirSync(path.join(R, 'static')).filter(f => f.endsWith('.css'));

let pass = 0, fail = 0;
function ok(name, cond, extra) {
  if (cond) pass++;
  else { fail++; console.log(`  FAIL ${name}${extra ? ' -> ' + extra : ''}`); }
}

function hsl([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), dl = mx - mn;
  const l = (mx + mn) / 2;
  if (!dl) return { h: 0, s: 0, l };
  let h = mx === r ? ((g - b) / dl) % 6 : mx === g ? (b - r) / dl + 2 : (r - g) / dl + 4;
  h *= 60; if (h < 0) h += 360;
  return { h, s: dl / (1 - Math.abs(2 * l - 1)), l };
}

// Hue bands that carry meaning and stay coloured.
function isStatusHue(h) {
  return (h <= 30 || h >= 340)   // red    — crashed / danger
      || (h >= 95 && h <= 165)   // green  — running / ok
      || (h >= 30 && h <= 60);   // amber  — starting / warning
}

/* The aurora redesign (reference: tajhatAti/dashb) introduces one accent —
   indigo — plus the two tints its KPI cards use. Those bands are allowed
   here; the point this file was written to make survives unchanged: there is
   ONE accent, so a stray second hue (the old #229ED9 Telegram blue, a purple
   panel) still shows up as an offender. */
function isAccentHue(h) {
  return h >= 195 && h <= 265;   // sky → indigo → violet
}

// Selectors whose colours are syntax highlighting, not chrome.
const SYNTAX = /\.cm-|\.token|\.hljs|CodeMirror-(?!gutter|lines|scroll)|xterm-fg|xterm-bg|ansi/i;

const HEX  = /#([0-9a-fA-F]{6})\b/g;
const FUNC = /rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})/g;

// ---------------------------------------------------------------- scan
const offenders = [];   // hued UI colours
const glass     = [];   // semi-transparent white veils
const blurs     = [];   // frosted glass

for (const f of SHEETS) {
  const src = fs.readFileSync(path.join(R, 'static', f), 'utf8');
  const lines = src.split('\n');
  let sel = "", openProp = "";
  lines.forEach((line, idx) => {
    const n = idx + 1;
    if (line.includes('{')) sel = line.split('{')[0].trim();
    // Skip comment bodies: they may legitimately name an old colour while
    // explaining why it was removed.
    const code = line.replace(/\/\*[^]*?\*\//g, '');
    const isComment = /^\s*(\/\*|\*|\/\/)/.test(line);
    if (isComment) return;

    // Only a blur that is actually APPLIED counts. Lines that set it to
    // `none` are the removal itself, and a line may carry both the standard
    // and the -webkit- property, so test each declaration separately.
    for (const decl of code.split(';')) {
      if (/backdrop-filter\s*:/i.test(decl) && !/:\s*none/i.test(decl))
        blurs.push(`${f}:${n} ${decl.trim()}`);
    }

    // A translucent white FILL is frosted glass. A translucent white in a
    // shadow or a border is not: it is an edge highlight or a glow, which
    // is how a raised control is drawn, and the user explicitly asked for
    // that ("deep button animation nai"). So judge by the property, not by
    // the colour alone -- checking only for rgba(255,255,255,a) flagged
    // nova's --rim and the CTA glow as glass and would have forced the
    // flat look back.
    /* Glass detection moved out of this line loop -- see the postcss pass
       below. Declarations such as `--e-2:` span three physical lines, so
       nothing that reads one line at a time can tell whether a white rgba
       belongs to a shadow or to a background. */

    if (SYNTAX.test(sel)) return;

    const found = [];
    while ((m = HEX.exec(code)))
      found.push([m[0], [1, 3, 5].map(i => parseInt(m[1].slice(i - 1, i + 1), 16))]);
    while ((m = FUNC.exec(code)))
      found.push([m[0], [+m[1], +m[2], +m[3]]]);

    for (const [txt, c] of found) {
      const { h, s, l } = hsl(c);
      if (s <= 0.10) continue;              // neutral enough to read as grey
      if (l < 0.03 || l > 0.985) continue;  // effectively black / white
      if (isStatusHue(h)) continue;         // meaningful colour
      if (isAccentHue(h)) continue;         // the one accent + its KPI tints
      offenders.push(`${f}:${n} ${txt} hue=${Math.round(h)} sat=${s.toFixed(2)}  [${sel}]`);
    }
  });
}

// ---------------------------------------------------------------- assert
console.log('scanned ' + SHEETS.length + ' stylesheets');

ok('no backdrop-filter anywhere', blurs.length === 0,
   blurs.slice(0, 6).join(' | '));
/* Frosted glass = a translucent white FILL. A translucent white inside a
   box-shadow, outline or border-colour is an edge highlight or a glow --
   that is how a raised, pressable control is drawn, and it is exactly what
   the user asked for after rejecting the flat revision. Parsed with
   postcss because a declaration can span multiple lines (`--e-2:` spans
   three), which defeats any line-by-line scan. */
{
  const postcss = require('postcss');
  const FILL = /^(background|background-color|background-image|border|fill|color)$/;
  const WHITE_RGBA = /rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*(0?\.[0-9]+)\s*\)/g;
  for (const f of SHEETS) {
    let root;
    try { root = postcss.parse(fs.readFileSync(path.join(R, 'static', f), 'utf8'), { from: f }); }
    catch (e) { continue; }
    root.walkDecls(decl => {
      const p = decl.prop.toLowerCase();
      const isToken = p.startsWith('--');
      // A custom property is judged by what it is plainly for.
      if (isToken && /(shadow|rim|ring|glow|e-\d|elev)/.test(p)) return;
      if (!isToken && !FILL.test(p)) return;
      let m;
      WHITE_RGBA.lastIndex = 0;
      while ((m = WHITE_RGBA.exec(decl.value)))
        if (parseFloat(m[1]) > 0.01)
          glass.push(`${f} ${decl.prop}: ${m[0]}`);
    });
  }
}

ok('no semi-transparent white overlays', glass.length === 0,
   `${glass.length} left: ` + glass.slice(0, 6).join(' | '));
ok('no hued UI colour outside the status and accent families', offenders.length === 0,
   `${offenders.length} left: ` + offenders.slice(0, 8).join(' | '));

// The specific second accent that slipped past the old test.
for (const bad of ['#58a6ff', '#0969da', '#388bfd', '56,139,253', '168,85,247', '99,102,241']) {
  const hits = SHEETS.filter(f => {
    const src = fs.readFileSync(path.join(R, 'static', f), 'utf8')
      .replace(/\/\*[^]*?\*\//g, '');           // ignore explanatory comments
    return src.replace(/\s+/g, '').includes(bad.replace(/\s+/g, ''));
  });
  ok(`second accent ${bad} is gone`, hits.length === 0, hits.join(','));
}

// The dark canvas must sit in the range the brief names.
const cls = fs.readFileSync(path.join(R, 'static', 'app.css'), 'utf8');
const dark = cls.slice(cls.indexOf('html[data-theme="dark"]'));
for (const [tok, lo, hi] of [['--paper', 0.02, 0.09], ['--panel', 0.07, 0.16]]) {
  const m = new RegExp(tok + ':\\s*(#[0-9a-f]{6})', 'i').exec(dark);
  if (!m) { ok(`dark ${tok} declared`, false); continue; }
  const c = [1, 3, 5].map(i => parseInt(m[1].slice(i, i + 2), 16));
  const { s, l } = hsl(c);
  ok(`dark ${tok} is near-black/dark-grey`, l >= lo && l <= hi, `${m[1]} L=${l.toFixed(3)}`);
  ok(`dark ${tok} has no hue`, s <= 0.06, `${m[1]} sat=${s.toFixed(2)}`);
}

console.log(`\ntest_one_accent_no_hue: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
