/* Admin console — live updates (dashboard step 5).
 *
 * WHAT WAS WRONG, both reproduced before the fix.
 *
 * 1. THE POLL DESTROYED THE PAGE UNDER THE READER
 *    Every renderer replaces innerHTML wholesale. Measured on a real DOM:
 *      before poll: focused = TR   scrollTop = 120
 *      after  poll: focused = BODY scrollTop = 120  (row identity: false)
 *    Keyboard focus fell out to <body> every 10 seconds, silently, making the
 *    panel unusable by keyboard. The scroll position survived only because
 *    jsdom does not lay out; in a real browser a shorter replacement table
 *    clamps it back to 0.
 *
 * 2. THE MONITOR WAS A LOAD SOURCE
 *    One dashboard refresh, 3-worker pool, counted at the HTTP layer:
 *      12 upstream calls (9 × /internal/jobs + 3 × /health)
 *    = 72 calls/minute at a 10s poll, because four admin routes each call
 *    fleet_jobs() and the overview forced worker_health(refresh=True).
 *
 * Also pinned: a failed poll must not blank a working panel, a slow poll must
 * not stack, and the panel must SAY how old its numbers are — a live view that
 * quietly stops updating is worse than one that never claimed to be live.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const JS = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');
const FRAG = fs.readFileSync(path.join(ROOT, 'templates/admin_panel.html'), 'utf8');
const RC = fs.readFileSync(path.join(ROOT, 'services/runner_client.py'), 'utf8');
const PYADMIN = fs.readFileSync(path.join(ROOT, 'routes/admin.py'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, e) => { c ? pass++ : (fail++, console.log(`  FAIL ${n}${e ? ' -> ' + e : ''}`)); };

const dom = new JSDOM(`<!doctype html><body><div class="dash-main"></div></body>`,
                      { pretendToBeVisual: true });
const d = dom.window.document;
d.querySelector('.dash-main').innerHTML = FRAG;
const st = d.createElement('style'); st.textContent = CSS; d.head.appendChild(st);
global.window = dom.window; global.document = d;

// extract() must keep the `async` keyword. Slicing from "function foo(" drops
// it, and loadAdminPanel then fails to parse its own `await` — a bug in the
// harness that looks exactly like a bug in the page.
function extract(name) {
  let start = JS.indexOf(`function ${name}(`);
  if (start < 0) throw new Error('not found: ' + name);
  if (JS.slice(start - 6, start) === 'async ') start -= 6;
  let i = JS.indexOf('{', JS.indexOf('(', start)), depth = 0;
  for (let k = i; k < JS.length; k++) {
    if (JS[k] === '{') depth++;
    else if (JS[k] === '}') { depth--; if (!depth) return JS.slice(start, k + 1); }
  }
  throw new Error('unbalanced: ' + name);
}

// The real loadAdminPanel, with api() and the renderers swapped for spies.
const LOAD = extract('loadAdminPanel');
const src = [
  'const Node = window.Node;',
  'function escapeHtml(s){return String(s==null?"":s).replace(/[&<>"\']/g,' +
    'c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","\'":"&#39;"}[c]));}',
  'function _fmtUptime(s){return (s||0)+"s";}',
  'let _lastProfile = {id:1};',
  'const calls = [];',
  'let failMode = false, pending = null;',
  'function api(p){ calls.push(p);' +
  '  if (failMode) return Promise.reject(new Error("boom"));' +
  '  if (pending) return new Promise(r => pending.push(() => r(DATA[p] || {})));' +
  '  return Promise.resolve(DATA[p] || {}); }',
  'const DATA = {};',
  extract('renderAdminJobs'),
  extract('renderAdminUsers'),
  'function renderAdminStats(){} function renderAdminSpark(){}',
  'function renderAdminReports(){} function renderAdminAudit(){}',
  'function renderAdminLibs(){} function renderAdminBotUsage(){} function _wireAdminBotUsage(){}',
  'function renderAdminRisk(){} function _wireAdminRisk(){} function renderAdminTelegramJobs(){} function renderAdminRunners(){} function _wireAdminRunners(){}',
  'function _loadAdminRiskData(){return Promise.resolve([{}, {}, {}, {}]);}',
  'let _admLastOk = 0;',
  extract('_admPreserve'),
  extract('_admMarkFresh'),
  extract('_admMarkStale'),
  extract('_admRenderFreshness'),
  'let _admInFlight = false;',
  LOAD,
  'return {loadAdminPanel, renderAdminJobs, renderAdminUsers, calls, DATA,' +
  ' setFail:v=>{failMode=v;}, hold:()=>{pending=[];}, release:()=>{const p=pending;pending=null;p.forEach(f=>f());},' +
  ' setLastOk:v=>{_admLastOk=v;}, freshness:_admRenderFreshness};',
].join('\n');
const app = new dom.window.Function(src)();

const JOBS = [
  { id: 11, name: 'alpha', language: 'python', owner: 'boss', created_at: '2026-07-01',
    live_status: 'running', uptime_s: 10, mem_mb: 30, peak_mem_mb: 30, restarts: 0 },
  { id: 12, name: 'beta', language: 'node', owner: 'boss', created_at: '2026-07-02',
    live_status: 'running', uptime_s: 20, mem_mb: 40, peak_mem_mb: 60, restarts: 2 },
];
const USERS = [{ id: 1, username: 'boss', email: 'b@g.com', is_verified: 1,
                 is_suspended: 0, created_at: '2026-07-01', job_count: 2 }];
app.DATA['/admin/jobs'] = { jobs: JOBS };
app.DATA['/admin/users'] = { users: USERS };
app.DATA['/admin/overview'] = { users: 1 };

// ── 1. a poll must not yank the page away from the reader ───────────────
console.log('\n[1] the repaint keeps the reader in place');
(async () => {
await app.loadAdminPanel(true);
const wrap = d.getElementById('admJobs').closest('.adm-table-wrap');
Object.defineProperty(wrap, 'scrollTop', { value: 0, writable: true, configurable: true });
wrap.scrollTop = 120;
const row = d.querySelectorAll('#admJobs tr')[2];
ok('rows carry a stable identity across repaints',
   row.getAttribute('data-adm-key') === 'job:12', row.getAttribute('data-adm-key'));
row.focus();
ok('control: focus really landed on the row', d.activeElement === row);

await app.loadAdminPanel(true);
const newRow = d.querySelectorAll('#admJobs tr')[2];
ok('the element really was replaced (so this is not a no-op test)', newRow !== row);
ok('focus follows the LOGICAL row, not the dead element',
   d.activeElement === newRow, d.activeElement && d.activeElement.tagName);
ok('the refocused row is the same one', d.activeElement.getAttribute('data-adm-key') === 'job:12');
ok('scroll position is restored', wrap.scrollTop === 120, String(wrap.scrollTop));

// Focus inside the confirm modal must NOT be hijacked by a poll landing
// mid-typing — that would eat a 2FA digit.
const outside = d.createElement('input');
d.body.appendChild(outside);
outside.focus();
await app.loadAdminPanel(true);
ok('focus outside the panel is left alone', d.activeElement === outside,
   d.activeElement && d.activeElement.tagName);

// ── 2. a failed poll must not blank a working panel ─────────────────────
console.log('[2] a failed poll degrades, it does not erase');
const before = d.getElementById('admJobs').innerHTML;
app.setFail(true);
await app.loadAdminPanel(true);
ok('the table survives a failed refresh',
   d.getElementById('admJobs').innerHTML === before);
ok('it does not say "Nothing here" over working data',
   !/Nothing here/.test(d.getElementById('admStats').innerHTML),
   d.getElementById('admStats').innerHTML.slice(0, 60));
ok('but the panel admits the numbers are not current',
   /retrying/.test(d.getElementById('admFresh').textContent),
   d.getElementById('admFresh').textContent);
ok('and it is marked stale, not just worded differently',
   d.getElementById('admFresh').classList.contains('stale'));
app.setFail(false);
await app.loadAdminPanel(true);
ok('recovery clears the stale mark',
   !d.getElementById('admFresh').classList.contains('stale'),
   d.getElementById('admFresh').textContent);

// A FIRST load that fails is different: there is nothing to protect, and the
// non-admin case must stay ambiguous.
d.getElementById('admStats').dataset.loaded = '';
app.setFail(true);
await app.loadAdminPanel(true);
ok('a first load that 404s still says nothing revealing',
   /Nothing here/.test(d.getElementById('admStats').innerHTML));
app.setFail(false);
await app.loadAdminPanel(true);

// ── 3. slow polls must not stack ────────────────────────────────────────
console.log('[3] a slow poll does not pile up');
app.calls.length = 0;
app.hold();
const p1 = app.loadAdminPanel(true);
const p2 = app.loadAdminPanel(true);
const p3 = app.loadAdminPanel(true);
const during = app.calls.length;
app.release();
await Promise.all([p1, p2, p3]);
ok('three overlapping refreshes issue ONE round of requests',
   during === 9, `${during} calls`);
ok('the in-flight guard exists in the shipped source', /_admInFlight/.test(JS));

// ── 4. the freshness label ──────────────────────────────────────────────
console.log('[4] the panel says how old its numbers are');
app.setLastOk(Date.now());
app.freshness();
ok('a fresh panel says so', /just now/.test(d.getElementById('admFresh').textContent),
   d.getElementById('admFresh').textContent);
app.setLastOk(Date.now() - 45000);
app.freshness();
ok('45s later it reports the real age',
   /45s ago/.test(d.getElementById('admFresh').textContent),
   d.getElementById('admFresh').textContent);
ok('and goes stale rather than looking healthy',
   d.getElementById('admFresh').classList.contains('stale'));
app.setLastOk(Date.now() - 300000);
app.freshness();
ok('minutes are shown as minutes', /5m ago/.test(d.getElementById('admFresh').textContent),
   d.getElementById('admFresh').textContent);
ok('the stale state has its own colour, using a status token not a new hex',
   /\.adm-fresh\.stale\s*\{\s*color:\s*var\(--st-warn\)/.test(CSS));
ok('the clock keeps ticking while the tab is hidden',
   /_admRenderFreshness\(\);\s*\n\s*if \(document\.hidden\) return;/.test(JS));

// ── 5. polling discipline that already existed stays ────────────────────
console.log('[5] polling stays bounded');
ok('interval is 10s, not sub-second', /ADM_POLL_MS = 10000/.test(JS));
ok('polling only runs on the admin tab', /_admSetPolling\(tabId === "admin"\)/.test(JS));
ok('a background tab does not poll', /if \(document\.hidden\) return;/.test(JS));
ok('it resumes on refocus', /visibilitychange/.test(JS));

// ── 6. the server side of the same problem ──────────────────────────────
console.log('[6] the console stops hammering the fleet');
ok('the fleet job list is memoised', /_fleet_cache/.test(RC));
ok('the window is shorter than the poll interval so data still moves',
   /FLEET_CACHE_MS", "3000"/.test(RC));
ok('a write invalidates it — a stopped job must not keep showing as running',
   /if method\.upper\(\) != "GET":\s*\n\s*_fleet_cache\["jobs"\] = None/.test(RC));
ok('worker health can be asked for with a staleness budget',
   /def worker_health\(refresh: bool = False, max_age_s: float = None\)/.test(RC));
ok('the overview no longer forces a re-probe of every worker on every tick',
   !/worker_health\(refresh=True\)/.test(PYADMIN));
ok('it states the staleness it accepts', /ADMIN_HEALTH_MAX_AGE_S/.test(PYADMIN));
ok('and that budget is under the 10s poll',
   parseFloat(/ADMIN_HEALTH_MAX_AGE_S", "([\d.]+)"/.exec(PYADMIN)[1]) < 10,
   /ADMIN_HEALTH_MAX_AGE_S", "([\d.]+)"/.exec(PYADMIN)[1]);
ok('caching is opt-out, so a caller needing truth can still force it',
   /def fleet_jobs\(refresh: bool = False\)/.test(RC));

console.log(`\ntest_admin_live: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
})();
