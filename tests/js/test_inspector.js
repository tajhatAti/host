/* RunSpace inspector — option 4 (desktop third column) + option 9 (mobile sheet).
 *
 * ONE panel, two presentations. The regression this guards against is the one
 * that already bit twice in this file's history: a panel positioned against
 * the WRONG containing block. .rs-side was absolute inside .rs-body while
 * `top: var(--rs-head-h)` assumed it was inside #tab-jobs, so it started 44px
 * too low and ran 44px past the bottom. The inspector must not repeat that.
 *
 * It also checks that the panel only ever renders fields the runner really
 * returns from _job_public(): status, uptime_s, restarts, port, cpu_pct,
 * mem_mb, env_keys, web_slug, language.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const CSS = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');
const HTML = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const JS = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');
const RUNNER = fs.readFileSync(path.join(ROOT, 'runner/app.py'), 'utf8');

const dom = new JSDOM(HTML, { pretendToBeVisual: true });
const d = dom.window.document;
d.querySelectorAll('link[rel=stylesheet]').forEach(l => l.remove());
const st = d.createElement('style'); st.textContent = CSS; d.head.appendChild(st);

let pass = 0, fail = 0;
const ok = (n, c, e) => { c ? pass++ : (fail++, console.log(`  FAIL ${n}${e ? ' -> ' + e : ''}`)); };

// ── 1. structure ────────────────────────────────────────────────────────
console.log('\n[1] structure');
const insp = d.getElementById('wbInspector');
ok('inspector exists', !!insp);
ok('it is a sibling of the editor, inside .rs-body',
   !!insp && insp.parentElement && insp.parentElement.classList.contains('rs-body'),
   insp && insp.parentElement && insp.parentElement.className);
ok('it is NOT nested inside .rs-ws (that is what blanked the Details page)',
   !!insp && !insp.closest('.rs-ws'));
ok('toggle button exists', !!d.getElementById('btnInspector'));
ok('close button exists', !!d.getElementById('wbInspClose'));

// ── 2. the containing-block trap ────────────────────────────────────────
console.log('[2] positioning');
// Take the LAST @media(max-width:760px) block — the inspector's own — and
// read its .rs-insp rule. A lazy match from the first media query would run
// past it and grab the desktop rule instead.
// Find the media block that actually contains the inspector's mobile rule.
// lastIndexOf() broke once more CSS was appended after it, so search forward
// from the sheet start for the first @media whose body defines .rs-insp.
let inspMobile = null;
for (const m of CSS.matchAll(/@media \(max-width: 760px\)/g)) {
  const chunk = CSS.slice(m.index, m.index + 2600);
  const hit = /#tab-jobs \.rs-insp \{([\s\S]*?)\}/.exec(chunk);
  if (hit && /inset:\s*auto/.test(hit[1])) { inspMobile = hit; break; }
}
ok('mobile sheet rule found', !!inspMobile);
if (inspMobile) {
  const body = inspMobile[1];
  ok('sheet is anchored to the bottom of its own container',
     /inset:\s*auto 0 0 0/.test(body), body.trim().split('\n')[0]);
  ok('sheet does NOT offset by the header height (wrong containing block)',
     !/top:\s*var\(--rs-head-h\)/.test(body));
  ok('sheet slides with transform, not width', /transform:\s*translateY\(100%\)/.test(body));
}
ok('open state is a single body class', /body\.rs-insp-open #tab-jobs \.rs-insp/.test(CSS));
ok('desktop column is opt-in, not always-on',
   /#tab-jobs \.rs-insp \{[^}]*display:\s*none/.test(CSS));
ok('hidden behind the full-screen Details page',
   /body\.rs-detail-open #tab-jobs \.rs-insp \{[^}]*display:\s*none/.test(CSS));
ok('mobile sheet is height-capped so the editor stays visible',
   /max-height:\s*72%/.test(CSS));
ok('sheet has a grab handle', /#tab-jobs \.rs-insp-head::before/.test(CSS));

// ── 3. only real fields ─────────────────────────────────────────────────
console.log('[3] data honesty');
const FIELDS = ['status', 'uptime_s', 'restarts', 'port', 'cpu_pct', 'mem_mb',
                'env_keys', 'web_slug', 'language'];
const pub = RUNNER.slice(RUNNER.indexOf('def _job_public'), RUNNER.indexOf('def _clear_manifest_pid'));
// cpu_pct / mem_mb are not literals in _job_public — they are spread in from
// _proc_stats(), so check that function's body for those two.
const stats = RUNNER.slice(RUNNER.indexOf('def _proc_stats'), RUNNER.indexOf('def _manifest_path'));
FIELDS.forEach(f => ok(`runner really returns "${f}"`,
  pub.includes(`"${f}"`) || stats.includes(`"${f}"`), f));
ok('_proc_stats is spread into the job payload', /_proc_stats\(j\.get\("proc"\)\)/.test(pub));
ok('renderInspector exists', /function renderInspector\(\)/.test(JS));
const fn = JS.slice(JS.indexOf('function renderInspector()'), JS.indexOf('function _setRunnerStat'));
ok('reads uptime_s', /job\.uptime_s/.test(fn));
ok('reads restarts', /job\.restarts/.test(fn));
ok('reads port', /job\.port/.test(fn));
ok('reads cpu_pct', /job\.cpu_pct/.test(fn));
ok('reads mem_mb', /job\.mem_mb/.test(fn));
ok('reads env_keys', /job\.env_keys/.test(fn));
ok('missing values render an em dash, not a fake number',
   /"—"/.test(fn) && /_inspSet/.test(JS));
ok('memory scale is documented as a reference, not a real cap',
   /_INSP_MEM_REF_MB/.test(JS));

// ── 4. secrets ──────────────────────────────────────────────────────────
console.log('[4] secrets');
ok('env VALUES are never referenced (API only returns keys)',
   !/job\.env\b(?!_keys)/.test(fn), 'renderInspector touches job.env');
ok('env keys are set via textContent, never innerHTML',
   /s\.textContent = k/.test(fn));
ok('runner comment confirms keys-only', /Only the KEYS/.test(RUNNER));

// ── 5. wiring ───────────────────────────────────────────────────────────
console.log('[5] wiring');
ok('toggle flips the body class', /classList\.toggle\("rs-insp-open"\)/.test(JS));
ok('close button clears it', /classList\.remove\("rs-insp-open"\)/.test(JS));
ok('Escape closes the sheet', /e\.key !== "Escape"[\s\S]{0,320}rs-insp-open/.test(JS));
ok('Escape yields to the Details page',
   /rs-insp-open[\s\S]{0,200}rs-detail-open/.test(JS));
ok('repaints on the SSE tick', /rs-insp-open"\)\) renderInspector\(\)/.test(JS));
ok('toggle hidden when no job is open', /_show\(btnInsp, !!isSelected\)/.test(JS));
ok('closing a job also closes the panel',
   /if \(!isSelected\) \{[\s\S]{0,200}remove\("rs-insp-open"\)/.test(JS));

// ── 6. accessibility ────────────────────────────────────────────────────
console.log('[6] accessibility');
const btn = d.getElementById('btnInspector');
ok('toggle reports expanded state', !!btn && btn.hasAttribute('aria-expanded'));
ok('toggle names the panel', !!btn && btn.getAttribute('aria-controls') === 'wbInspector');
ok('panel is labelled', !!insp && !!insp.getAttribute('aria-label'));
const unlabelled = [...d.querySelectorAll('#wbInspector button')]
  .filter(b => !(b.textContent || '').trim() && !b.getAttribute('aria-label'));
ok('every inspector button is labelled', unlabelled.length === 0,
   unlabelled.map(b => b.id).join(','));
ok('aria-expanded is kept in sync', /setAttribute\("aria-expanded"/.test(JS));

console.log(`\ntest_inspector: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
