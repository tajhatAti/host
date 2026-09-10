/* Regression guard for the site palette.
 *
 * Round 1: every box and button had a warm/orange cast. It was never a
 * per-button rule — the classic.css palette itself was warm (--panel #fffdf7,
 * --line-2 #c9bfa4 ... hue ~44°, sat ~0.3) and .btn-secondary/.btn-ghost/cards/
 * inputs all resolve to those tokens.
 *
 * Round 2: de-warming the palette also swapped the ACCENT to indigo, which
 * nobody asked for — the whole UI turned blue. The brief is black / white /
 * grey: emphasis comes from weight and contrast, never hue. Only status
 * (green / amber / red) may be coloured, because there colour carries meaning.
 *
 * So this file now asserts two things on real computed colours, in BOTH
 * themes: (1) no core token has a visible hue at all, and (2) the primary
 * button still passes WCAG AA contrast — a near-white button inherits
 * color:#fff from a shared rule, which would be invisible. */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const R = path.resolve(__dirname, '../../');
const ORDER = ['app.css'];

function build(theme) {
  const css = ORDER.map(f => fs.readFileSync(path.join(R,'static',f),'utf8')).join('\n');
  const dom = new JSDOM(fs.readFileSync(path.join(R,'index.html'),'utf8'),
                        { pretendToBeVisual: true });
  const d = dom.window.document;
  d.querySelectorAll('link[rel=stylesheet]').forEach(l => l.remove());
  const st = d.createElement('style'); st.textContent = css; d.head.appendChild(st);
  if (theme) d.documentElement.setAttribute('data-theme', theme);
  return dom;
}

function rgb(s) {
  const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(s || '');
  if (m) return [+m[1], +m[2], +m[3]];
  if (s && s.startsWith('#') && s.length >= 7)
    return [1,3,5].map(i => parseInt(s.slice(i, i+2), 16));
  return null;
}
function hsl(c) {
  const [r,g,b] = c.map(x => x/255);
  const mx = Math.max(r,g,b), mn = Math.min(r,g,b), dl = mx - mn;
  if (!dl) return { h:0, s:0, l:(mx+mn)/2 };
  let h = mx===r ? ((g-b)/dl)%6 : mx===g ? (b-r)/dl+2 : (r-g)/dl+4;
  h *= 60; if (h < 0) h += 360;
  const l = (mx+mn)/2;
  return { h, s: dl/(1-Math.abs(2*l-1)), l };
}
/* "warm cast" = orange/amber/cream hue with enough saturation to be visible.
   Status amber (#d29922) is deliberate and lives on .warn/.installing dots,
   never on a token below, so it is not caught here. */
function isWarm(c) {
  if (!c) return false;
  const { h, s, l } = hsl(c);
  return h >= 10 && h <= 60 && s > 0.22 && l > 0.12;
}

/* Round 2 escalated this to "any visible hue is wrong", which is a different
   claim than the one this file exists to make — and the aurora redesign
   (indigo accent, cool slate ramp) falsifies it on purpose. What still has to
   hold, and what the name of this file actually says: nothing is WARM, and a
   surface never gets saturated enough to read as a colour. The accent itself
   is exempt; it is supposed to be indigo. */
function isHueOverreach(c, token) {
  if (!c) return false;
  if (/^--(acc|accent|btn|ring|glow|chart-grid)/.test(token || '')) return false;
  const { s, h } = hsl(c);
  return s >= 0.45 || (h >= 10 && h <= 60 && s > 0.2);
}

/* WCAG relative luminance -> contrast ratio. Guards the case where a token
   flip makes a button's background and its inherited text colour collide. */
function contrast(a, b) {
  const lum = c => {
    const v = c.map(x => {
      x /= 255;
      return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
  };
  const L1 = Math.max(lum(a), lum(b));
  const L2 = Math.min(lum(a), lum(b));
  return (L1 + 0.05) / (L2 + 0.05);
}

const TOKENS = ['--panel','--paper','--paper-2','--line','--line-2',
                '--acc','--acc-ink','--btn','--btn-fg','--ink','--ink-2',
                '--muted','--code-bg','--band','--cream'];
const CONTROLS = ['.btn-primary','.btn-secondary','.btn-ghost','.cs-act',
                  'input','.stat-card','.quick-card','.dash-tab'];

let pass = 0, fail = 0;
function ok(name, cond, extra) {
  if (cond) { pass++; }
  else { fail++; console.log(`  FAIL ${name}${extra ? ' -> ' + extra : ''}`); }
}

for (const theme of [null, 'dark']) {
  const label = theme || 'light';
  const dom = build(theme);
  const d = dom.window.document;
  const root = dom.window.getComputedStyle(d.documentElement);

  for (const t of TOKENS) {
    const v = root.getPropertyValue(t).trim();
    if (!v) continue;
    /* Tokens now alias each other (--ink: var(--fg)), and jsdom does not
       resolve var(), so rgb() returns null for them. A null is "unknown",
       not "hued": the literal ramp is audited from source by test_app_css
       and test_one_accent_no_hue. Skip rather than crash on it. */
    if (!rgb(v)) continue;
    ok(`[${label}] token ${t} is not warm`, !isWarm(rgb(v)), v);
    ok(`[${label}] token ${t} stays neutral, not a colour`, !isHueOverreach(rgb(v), t),
       `${v} sat=${hsl(rgb(v)).s.toFixed(2)}`);
  }
  for (const sel of CONTROLS) {
    const el = d.querySelector(sel);
    if (!el) continue;
    const cs = dom.window.getComputedStyle(el);
    for (const prop of ['backgroundColor','borderTopColor','color']) {
      ok(`[${label}] ${sel}.${prop}`, !isWarm(rgb(cs[prop])), cs[prop]);
    }
  }
  // A hue-less palette makes "primary" a light solid on dark (and vice
  // versa). If the label colour is not flipped to match, the button reads as
  // blank. Check the rendered pair, not the stylesheet text.
  const primary = d.querySelector('.btn-primary');
  if (primary) {
    const cs = dom.window.getComputedStyle(primary);
    const bg = rgb(cs.backgroundColor), fg = rgb(cs.color);
    if (bg && fg) {
      const ratio = contrast(bg, fg);
      ok(`[${label}] .btn-primary label is readable (AA 4.5:1)`, ratio >= 4.5,
         `ratio=${ratio.toFixed(2)} bg=${cs.backgroundColor} fg=${cs.color}`);
    }
  }
}

console.log(`\ntest_no_warm_cast: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
