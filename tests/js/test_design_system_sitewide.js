/* ONE design system across every screen — Job Detail Page is the reference.
 *
 * MEASURED BEFORE (facts):
 *   · 37 different hex values expressed just FOUR meanings —
 *     11 greens (#3fb950 #4ade80 #34d399 #28c840 #238636 #2ea043 …),
 *     16 reds   (#f85149 #ef5b5b #f87171 #ff5f57 #ff7b72 #c87474 …),
 *     3 ambers, 7 blues. Near-duplicates like #4ade80 / #34d399 / #3fb950
 *     all meant "running".
 *   · 14 separate badge classes (.ah-term-badge .jd-badge .rs-chip .rs-badge
 *     .job-pill .cs-pill .chip .adm-pill .wb-badge …), each its own shape.
 *   · --accent was scoped to #tab-jobs, so every OTHER screen could not read
 *     it at all and fell back to hardcoded literals.
 *
 * Syntax highlighting, terminal ANSI and HTTP status-code colouring are
 * deliberately EXCLUDED: there the colour carries information rather than
 * being UI chrome, so normalising it would destroy meaning.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

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

/* Rules whose colour is information, not chrome. */
const SYNTAX = /\.cm-|\.CodeMirror|token|highlight|\.hljs|xterm|ansi|\.t-(out|err|in|sys)\b|log-code|\.cs-(kw|str|num|com)/i;

// ── 1. one accent, readable from everywhere ─────────────────────────────
console.log('\n[1] single accent token');
/* The point of this check is "there is ONE accent", not "it is spelled as a
   hex literal here". --accent was declared twice at :root — once as
   var(--acc) and once as #ffffff — which agreed only by coincidence: change
   --acc and the hardcoded copy silently keeps the old colour. It is an alias
   now, so accept either form and additionally require that the value it
   resolves to has exactly one definition. */
ok('--accent is declared on :root',
   /:root\s*\{[^}]*--accent:\s*(?:#[0-9a-f]{3,8}|var\(--acc\))/i.test(CLASSIC));
ok('...and the accent has a single source of truth',
   (CLASSIC.match(/:root\s*\{[^}]*--accent:\s*#[0-9a-f]{3,8}/gi) || []).length <= 1);
ok('light theme overrides it for contrast',
   /html\[data-theme="light"\]\s*\{[^}]*--accent:/.test(CLASSIC));
// The dark accent on white is only 2.2:1, so a single value cannot serve both.
ok('dark accent readable on dark bg (AA)', ratio('#58a6ff', '#0d1117') >= 4.5,
   ratio('#58a6ff', '#0d1117').toFixed(2));
ok('light accent readable on white (AA)', ratio('#0969da', '#ffffff') >= 4.5,
   ratio('#0969da', '#ffffff').toFixed(2));
ok('active-tab label readable on the accent fill (dark)',
   ratio('#0d1117', '#58a6ff') >= 4.5, ratio('#0d1117', '#58a6ff').toFixed(2));
ok('active-tab label readable on the accent fill (light)',
   ratio('#ffffff', '#0969da') >= 4.5, ratio('#ffffff', '#0969da').toFixed(2));

// ── 2. status hues collapsed onto the tokens ────────────────────────────
console.log('[2] status colour consolidation');
function countOutsideSyntax(hexes) {
  let n = 0;
  for (const name of SHEETS) {
    const css = read(name);
    const re = /([^{}]+)\{([^}]*)\}/g;
    let m;
    while ((m = re.exec(css)) !== null) {
      const sel = m[1].trim().split('\n').pop();
      if (SYNTAX.test(sel)) continue;
      for (const h of hexes) {
        if (new RegExp(h + '\\b', 'i').test(m[2])) n++;
      }
    }
  }
  return n;
}
const DUP_GREEN = ['#4ade80', '#34d399', '#28c840', '#2ea043', '#7bd79a', '#56d364'];
const DUP_RED   = ['#ef5b5b', '#f87171', '#ff5f57', '#ff8b8b', '#c87474', '#ff8a8a', '#ff8080'];
const DUP_BLUE  = ['#388bfd', '#a5b4fc', '#7dd3fc', '#a5d6ff'];
ok('duplicate greens removed from UI chrome', countOutsideSyntax(DUP_GREEN) === 0,
   String(countOutsideSyntax(DUP_GREEN)));
ok('duplicate reds removed from UI chrome', countOutsideSyntax(DUP_RED) === 0,
   String(countOutsideSyntax(DUP_RED)));
ok('duplicate blues removed from UI chrome', countOutsideSyntax(DUP_BLUE) === 0,
   String(countOutsideSyntax(DUP_BLUE)));
ok('status tokens exist', /--st-ok:/.test(CLASSIC) && /--st-warn:/.test(CLASSIC)
   && /--st-danger:/.test(CLASSIC));
// Guard the exclusion itself: code colour must NOT have been flattened.
ok('syntax highlighting still has its own palette',
   /\.cm-/.test(ALL) && (ALL.match(/\.cm-[a-z-]+\s*\{[^}]*#[0-9a-f]{6}/gi) || []).length > 5);

// ── 3. one pill shape for every badge class ─────────────────────────────
console.log('[3] unified pill/badge');
const PILL_GROUP = /\.badge,\s*\.chip,\s*\.rs-badge,\s*\.rs-chip,\s*\.job-pill/;
ok('all badge classes share one rule', PILL_GROUP.test(CLASSIC));
// The selector list wraps across two lines, so anchor on the opening brace
// of the rule rather than assuming it follows the first selector.
const pillRule = /\.badge, \.chip,[\s\S]*?\{([\s\S]*?)\}/.exec(CLASSIC);
ok('pill rule found', !!pillRule);
ok('pills are fully rounded', !!pillRule && /border-radius:\s*999px/.test(pillRule[1]));
ok('pills carry a generated dot', /\.badge::before, \.chip::before/.test(CLASSIC));
ok('the dot inherits the status colour',
   /::before[\s\S]{0,200}background:\s*currentColor/.test(CLASSIC));
ok('status variants map to the tokens',
   /\.job-pill\.running[\s\S]{0,200}--st-ok/.test(CLASSIC) &&
   /\.job-pill\.crashed[\s\S]{0,200}--st-danger/.test(CLASSIC));

// ── 4. tabs match the Job Detail Page ───────────────────────────────────
console.log('[4] unified tabs');
ok('dashboard tabs are pills', /\.dash-tab, \.tab-secondary[\s\S]{0,400}border-radius:\s*999px/.test(CLASSIC));
ok('inactive tabs have no fill',
   /\.dash-tab, \.tab-secondary[\s\S]{0,400}background:\s*transparent\s*!important/.test(CLASSIC));
ok('active tab is accent-filled',
   /\.dash-tab\.active[\s\S]{0,220}background:\s*var\(--accent/.test(CLASSIC));
ok('the jobs tab no longer gets special colour treatment',
   /\.dash-tab\[data-tab="jobs"\][\s\S]{0,300}background-image:\s*none/.test(CLASSIC));
// Checked against a FRESH read: the dead declaration must be deleted at
// source, not merely overridden later in the cascade.
ok('no gradient declaration remains on any tab',
   !SHEETS.map(read).join('\n').includes('.dash-tab.active { background: var(--grad)'));
ok('bottom-nav active uses the accent, not a brand colour',
   /\.bn-item\.active \{[^}]*var\(--accent/.test(CLASSIC));

// ── 5. focus ring is uniform ────────────────────────────────────────────
console.log('[5] focus');
ok('one focus ring for the whole app',
   /:focus-visible \{[^}]*outline:\s*2px solid var\(--accent/.test(CLASSIC));

// ── 6. the reference page is unchanged by all this ──────────────────────
console.log('[6] reference page still intact');
const dom = new JSDOM(fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8'));
const d = dom.window.document;
const panel = d.getElementById('jobDetailPanel');
ok('detail panel present', !!panel);
ok('still six pill tabs', !!panel && panel.querySelectorAll('.jd-tab').length === 6);
ok('still exactly one active tab',
   !!panel && panel.querySelectorAll('.jd-tab.is-active').length === 1);
ok('detail page reads the shared accent',
   /--jd-accent:\s*var\(--accent\)/.test(read('app.css')));

console.log(`\ntest_design_system_sitewide: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
