/* UI CONSISTENCY — the things that made the app look unfinished.
 *
 * Each check below started as a MEASUREMENT, not an opinion: the real page was
 * booted in jsdom, custom properties were resolved by hand (jsdom does not
 * substitute var()), and getComputedStyle was read on every control. What that
 * turned up:
 *
 *   1. SEVEN control heights for one job — buttons 40, text inputs 42,
 *      selects 32, .rs-inp 34, .rs-seg-btn 28, .jd-btn 34, .rs-sq 30. Put a
 *      button next to a field, which the Code Studio header, the RunSpace
 *      toolbar and the job-detail bar all do, and the row is visibly ragged.
 *
 *   2. EIGHTEEN font sizes, four of them half-pixel (10.5, 11.5, 12.5, 13.5).
 *      Differences too small to read as deliberate, big enough to make two
 *      labels that should match look misaligned — and half-pixel text lands
 *      off the pixel grid, which is what makes a UI look faintly blurry.
 *
 *   3. THE DENSE CONTROLS WERE EXEMPT FROM THE 44px TOUCH FLOOR. The mobile
 *      rule named generic elements only, so every RunSpace control kept its
 *      32px desktop size on a phone — in the most crowded toolbar in the app.
 *
 *   4. --fg-4 (#5c5c5c) was doing two jobs: "disabled" and ordinary quiet
 *      text. At 2.98:1 on --bg it is below even the 3:1 large-text floor, so
 *      placeholders and log timestamps were genuinely hard to read.
 *
 *   5. 29 AD-HOC z-index VALUES from 5 to 10000, with .toast-container and
 *      .ah-modal each declared TWICE at different values — so which one won
 *      depended on source order. The RunSpace sheet also opened underneath
 *      the activity panel.
 *
 *   6. The bottom nav floated over the full-screen RunSpace editor, covering
 *      the last ~64px of the code area.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');
const { zValue } = require('./zlayers');

const ROOT = path.resolve(__dirname, '../../');
const css = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, x) => {
  if (c) { pass++; console.log('  ok   ' + n); }
  else { fail++; console.log('  FAIL ' + n + (x !== undefined ? ' -> ' + x : '')); }
};

/* Resolve a custom property from :root (and from a scoped block when named). */
function tokenIn(block, name) {
  const m = new RegExp('\\' + name + ':\\s*([^;]+);').exec(block);
  return m ? m[1].trim() : null;
}
const rootBlock = (css.match(/:root\s*\{[\s\S]*?\}/g) || []).join('\n');

// ---------------------------------------------------------------------------
console.log('[1] one control size system');
// ---------------------------------------------------------------------------
['--ctl-h-sm', '--ctl-h', '--ctl-h-lg'].forEach(t =>
  ok(`${t} is declared`, !!tokenIn(rootBlock, t), tokenIn(rootBlock, t)));

ok('the three sizes are distinct and ordered',
   (() => {
     const v = ['--ctl-h-sm', '--ctl-h', '--ctl-h-lg'].map(t => parseInt(tokenIn(rootBlock, t), 10));
     return v[0] < v[1] && v[1] < v[2];
   })());

// Buttons AND fields must read the same token, or a row cannot line up.
ok('buttons size from the token',
   /button, \.btn, \.btn-primary[^{]*\{[^}]*height:\s*var\(--btn-h,\s*var\(--ctl-h\)\)/s.test(css)
   || /\.btn-primary, \.btn-secondary[^{]*\{[^}]*height:\s*var\(--btn-h,\s*var\(--ctl-h\)\)/s.test(css));
const baseField = /\binput, select, textarea \{([^}]*)\}/.exec(css);
ok('inputs and selects size from the same token',
   !!baseField && !/height:\s*\d+px/.test(baseField[1]),
   'a literal height here is what made fields 2px taller than buttons');

// No control may reintroduce its own literal height.
const literalHeights = [];
[['.rs-inp', 34], ['.rs-sel', 32], ['.rs-seg-btn', 28], ['.jd-btn', 34],
 ['.cs-name', 32], ['.cs-lang', 32], ['.rs-run-quick', 32]].forEach(([sel]) => {
  const re = new RegExp('\\' + sel + '[^{]*\\{[^}]*height:\\s*(\\d+)px');
  const m = re.exec(css);
  if (m) literalHeights.push(`${sel}=${m[1]}px`);
});
ok('no control hardcodes its own height again', literalHeights.length === 0,
   literalHeights.join(', '));

// ---------------------------------------------------------------------------
console.log('[2] one type scale');
// ---------------------------------------------------------------------------
const steps = ['--fs-1', '--fs-2', '--fs-3', '--fs-4', '--fs-5', '--fs-6', '--fs-7', '--fs-8'];
ok('the scale is declared', steps.every(t => !!tokenIn(rootBlock, t)));
ok('every step is a whole pixel',
   steps.map(t => tokenIn(rootBlock, t)).every(v => /^\d+px$/.test(v)),
   steps.map(t => tokenIn(rootBlock, t)).join(' '));
ok('the steps ascend',
   (() => { const v = steps.map(t => parseInt(tokenIn(rootBlock, t), 10));
            return v.every((n, i) => i === 0 || n > v[i - 1]); })());

const strayFonts = [...css.matchAll(/font-size:\s*([\d.]+)px/g)].map(m => m[1]);
ok('no literal font-size survives outside the scale', strayFonts.length === 0,
   [...new Set(strayFonts)].join(', '));
ok('no half-pixel type anywhere', !/font-size:\s*[\d]+\.\d+px/.test(css));

// ---------------------------------------------------------------------------
console.log('[3] touch targets on a phone');
// ---------------------------------------------------------------------------
const mobile = css.slice(css.indexOf('@media (max-width: 760px)'));
ok('the dense control token is raised on mobile',
   /--ctl-h-sm:\s*44px/.test(mobile));
ok('the RunSpace alias is raised too (it is scoped to #tab-jobs)',
   /#tab-jobs \{ --rs-ctl-h: 44px; \}/.test(mobile),
   'raising --ctl-h-sm on a row does not reach a token declared on #tab-jobs');
ok('square icon buttons stay square as they grow',
   /\.rs-sq, \.rs-side-new \{ width: var\(--ctl-h-sm\); \}/.test(mobile));
ok('the generic 44px floor is still there',
   /min-height:\s*44px/.test(mobile));

// ---------------------------------------------------------------------------
console.log('[4] contrast');
// ---------------------------------------------------------------------------
function lum(hex) {
  const h = hex.replace('#', '');
  const f = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
  const [r, g, b] = [0, 2, 4].map(i => parseInt(f.substr(i, 2), 16) / 255)
    .map(v => v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
                          return (x + 0.05) / (y + 0.05); };
const bg = tokenIn(rootBlock, '--bg');
['--fg', '--fg-2', '--fg-3', '--fg-4'].forEach(t => {
  const v = tokenIn(rootBlock, t);
  const r = ratio(v, bg);
  ok(`${t} (${v}) clears AA on --bg`, r >= 4.5, r.toFixed(2) + ':1');
});
ok('a separate token exists for genuinely inert text',
   !!tokenIn(rootBlock, '--fg-off'),
   'without it, "disabled" and "quiet" share one value and one of them is wrong');

// ---------------------------------------------------------------------------
console.log('[5] the layer ladder');
// ---------------------------------------------------------------------------
const layers = ['--z-sticky', '--z-nav', '--z-scrim', '--z-drawer', '--z-panel',
                '--z-flyout', '--z-sheet', '--z-modal', '--z-toast', '--z-fatal'];
ok('every layer is named', layers.every(t => !!tokenIn(rootBlock, t)));
ok('the ladder ascends',
   (() => { const v = layers.map(t => parseInt(tokenIn(rootBlock, t), 10));
            return v.every((n, i) => i === 0 || n >= v[i - 1]); })(),
   layers.map(t => tokenIn(rootBlock, t)).join(' '));

// The specific inversion that was found: a sheet opened behind the flyout.
ok('a sheet opens ABOVE the activity panel',
   zValue('var(--z-sheet)') > zValue('var(--z-flyout)'));
ok('its scrim covers the flyout but not the sheet',
   zValue('var(--z-sheet-scrim)') > zValue('var(--z-flyout)')
   && zValue('var(--z-sheet-scrim)') < zValue('var(--z-sheet)'));
ok('toasts and modals outrank every panel',
   zValue('var(--z-toast)') > zValue('var(--z-sheet)')
   && zValue('var(--z-modal)') > zValue('var(--z-panel)'));

// The duplicates that made source order decide the winner.
ok('.toast-container is declared once',
   (css.match(/\.toast-container[^{]*\{[^}]*z-index/g) || []).length === 1);
ok('.ah-modal is declared once',
   (css.match(/\.ah-modal[^{]*\{[^}]*z-index/g) || []).length === 1,
   String((css.match(/\.ah-modal[^{]*\{[^}]*z-index/g) || []).length));
ok('no runaway z-index survives',
   !/z-index:\s*(?:[2-9]\d{3,}|1[3-9]\d{2})/.test(css),
   (css.match(/z-index:\s*\d{4,}/g) || []).join(', '));

// ---------------------------------------------------------------------------
console.log('[6] RunSpace keeps global navigation');
// ---------------------------------------------------------------------------
ok('the mobile bottom nav remains visible in RunSpace',
   /body\.rs-active:not\(\.rs-detail-open\) \.bottom-nav \{ display:flex !important; \}/.test(css));
ok('RunSpace reserves the real nav height instead of covering the editor',
   /body\.rs-active:not\(\.rs-detail-open\) \.dash-main \{[^}]*padding-bottom:calc\(var\(--bottom-nav-h\)/.test(css));

// ---------------------------------------------------------------------------
console.log('[7] touch hygiene');
// ---------------------------------------------------------------------------
ok('tap highlight suppressed on controls', /-webkit-tap-highlight-color:\s*transparent/.test(css));
ok('controls are not selectable on double-tap', /user-select:\s*none/.test(css));
ok('but text inputs still are', /input, textarea[^{]*\{[^}]*user-select:\s*text/s.test(css));
ok('scroll panes do not chain to the page', /overscroll-behavior:\s*contain/.test(css));
ok('bottom-pinned panels respect the home indicator',
   (css.match(/padding-bottom:\s*calc\([\s\S]{0,80}?safe-area-inset-bottom/g) || []).length >= 2);

// ---------------------------------------------------------------------------
console.log('[8] accessibility of the OTP boxes');
// ---------------------------------------------------------------------------
const dom = new JSDOM(html);
const otp = [...dom.window.document.querySelectorAll('.otp-boxes input')];
ok('every OTP digit has a label', otp.length > 0 && otp.every(i => i.getAttribute('aria-label')),
   `${otp.filter(i => !i.getAttribute('aria-label')).length} of ${otp.length} unlabelled`);
ok('the labels are distinct, so a reader can say which digit',
   new Set(otp.map(i => i.getAttribute('aria-label'))).size === otp.length);
ok('the OS can autofill the code', otp.every(i => i.getAttribute('autocomplete') === 'one-time-code'));

// ---------------------------------------------------------------------------
console.log('[9] weights that the font actually ships');
// ---------------------------------------------------------------------------
/* index.html loads Inter at 400;500;600;700;800. The sheet asked for 550,
   570, 650, 680, 750, 760 and 780 as well — 11 distinct weights in all. A
   browser cannot render a face it never downloaded, so each of those was
   silently rounded to the nearest one that exists: 550 rendered as 500, 570
   as 600, and so on. They read as fine-grained typographic control and were
   nothing of the kind, while making two elements that were meant to match
   (600 and 570, say) resolve to the same weight by accident rather than by
   intent. */
const loaded = (/Inter:wght@([\d;]+)/.exec(html) || [, ''])[1].split(';').filter(Boolean);
const used = [...new Set([...css.matchAll(/font-weight:\s*(\d+)/g)].map(m => m[1]))];
ok('the font declares the weights it uses', loaded.length > 0, loaded.join(';'));
ok('every weight in the sheet is actually downloaded',
   used.every(w => loaded.includes(w)),
   'not loaded: ' + used.filter(w => !loaded.includes(w)).join(', '));
ok('the ladder is small enough to be deliberate', used.length <= 5,
   used.sort().join(', '));

// ---------------------------------------------------------------------------
console.log('[10] spacing sits on the 4px grid');
// ---------------------------------------------------------------------------
/* The file header calls the rhythm a 4px grid and every --s token obeys it,
   but padding/gap carried 2, 5, 6, 7, 9, 10, 11, 13 and 14px literals — 6px
   and 10px fourteen times each. That is what makes two rows that should share
   a rhythm sit a pixel or two apart: not obviously wrong, just never quite
   aligned. A few off-grid values remain on purpose (a select's arrow
   clearance, the bottom nav's deliberately tight 3px), so the check allows a
   small budget rather than demanding zero. */
const spacing = [...css.matchAll(/\b(?:gap|padding|column-gap|row-gap)(?:-\w+)?:\s*([^;{}]+);/g)]
  .flatMap(m => m[1].split(/\s+/))
  .filter(v => /^\d+px$/.test(v))
  .map(v => parseInt(v, 10))
  .filter(n => n > 0 && n % 4 !== 0);
ok('few off-grid spacing literals remain', spacing.length <= 6,
   [...new Set(spacing)].sort((a, b) => a - b).join(', ') + ` (${spacing.length} uses)`);

// ---------------------------------------------------------------------------
console.log('[11] no control that visibly does nothing');
// ---------------------------------------------------------------------------
/* The dashboard and the job-detail header each carried a theme toggle. Both
   set data-theme and swapped their own icon — and nothing else happened,
   because app.css states "One product, one theme" and maps BOTH values to the
   same palette (RunSpace and Code Studio are hardcoded dark surfaces with no
   data-theme rules at all). Proven by resolving the surface tokens under each
   value: identical.
   A button that responds to a press but changes nothing is read as a bug in
   the app, so it is worse than not offering it. */
const themeMapsToOnePalette = (() => {
  const dark = /html\[data-theme="dark"\][^{]*\{([^}]*)\}/.exec(css);
  const light = /html\[data-theme="light"\][^{]*\{([^}]*)\}/.exec(css);
  // Either there is no per-theme surface palette at all, or both exist.
  const surfaces = /--bg:|--card:|--fg:/;
  return !(light && surfaces.test(light[1])) || !!(dark && surfaces.test(dark[1]));
})();
ok('the two data-theme values are not pretending to differ', themeMapsToOnePalette);
ok('no dashboard theme toggle while there is one palette',
   !/id="themeBtn"/.test(html));
ok('no job-detail theme toggle either', !/id="jdThemeToggle"/.test(html));

const proJs = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');
ok('and no orphaned handler left behind', !/toggleTheme/.test(proJs),
   'a listener for a button that no longer exists');
ok('but the boot path can still write the attribute', /function applyTheme/.test(proJs),
   'index.html sets data-theme before first paint and pro.js must agree');

// ---------------------------------------------------------------------------
console.log('[12] one source of truth per token');
// ---------------------------------------------------------------------------
/* :root is declared in eight places in this sheet, which is fine on its own —
   but three tokens were declared in two of them with DIFFERENT right-hand
   sides: --accent (var(--acc) and #ffffff), --nav-height (var(--nav-h) and
   62px), --jd-accent. They resolved to the same value today, so nothing
   looked wrong; that is luck, not design. Change --acc and the hardcoded
   copy silently keeps the old colour, and the bug appears in one half of the
   UI only. A duplicate must be an ALIAS, never a second copy of the value. */
const rootBlocks = [...css.matchAll(/:root\s*\{([^}]*)\}/g)].map(m => m[1]);
const decls = {};
rootBlocks.forEach((b, i) => {
  [...b.matchAll(/(--[\w-]+):\s*([^;]+);/g)].forEach(m => {
    (decls[m[1]] = decls[m[1]] || []).push(m[2].trim());
  });
});
const conflicting = Object.entries(decls)
  .filter(([, vals]) => new Set(vals).size > 1)
  .map(([k, vals]) => `${k} = ${[...new Set(vals)].join(' | ')}`);
ok('no token is declared twice with different values', conflicting.length === 0,
   conflicting.join('; '));

console.log(`\ntest_ui_consistency: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
