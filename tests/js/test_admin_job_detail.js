/* Admin console — per-app detail (dashboard step 3).
 *
 * WHAT WAS WRONG. The backend already returned mem_mb, peak_mem_mb, restarts,
 * last_exit_reason, libs and worker on every row of /admin/jobs, and the table
 * rendered exactly six of them: App, Owner, Lang, Status, Uptime, Created.
 * Every number that would tell you WHY an app is misbehaving was fetched over
 * the wire and thrown away, and there was no per-job route to ask for more.
 * A monitoring console that cannot answer "why did this one die" is decoration.
 *
 * The rules this pins down:
 *   - a row must be openable (and by keyboard, not only mouse)
 *   - the detail view renders the resource picture, the restart history and
 *     the exit reason IN WORDS, not as a machine token
 *   - an unreachable worker reads as "unknown", never as "offline" — the
 *     second is a claim about the app, the first is the truth about us
 *   - logs are rendered with textContent: they are the user's own program
 *     output, i.e. the most obviously untrusted string on the page
 *   - env VALUES never appear, only key names
 *   - the source code never appears
 *
 * The render functions are extracted from static/pro.js and driven with real
 * /admin/jobs/{id} payloads, so a rename in the route breaks this test.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const JS = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');
const FRAG = fs.readFileSync(path.join(ROOT, 'templates/admin_panel.html'), 'utf8');
const PYADMIN = fs.readFileSync(path.join(ROOT, 'routes/admin.py'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, e) => { c ? pass++ : (fail++, console.log(`  FAIL ${n}${e ? ' -> ' + e : ''}`)); };

// ── harness ─────────────────────────────────────────────────────────────
const dom = new JSDOM(`<!doctype html><body><div class="dash-main"></div></body>`,
                      { pretendToBeVisual: true });
const d = dom.window.document;
d.querySelector('.dash-main').innerHTML = FRAG;
const st = d.createElement('style'); st.textContent = CSS; d.head.appendChild(st);

global.window = dom.window;
global.document = d;
global.Node = dom.window.Node;

// Pull the real implementations out of pro.js rather than reimplementing them.
function extract(name) {
  const start = JS.indexOf(`function ${name}(`);
  if (start < 0) throw new Error('not found: ' + name);
  let i = JS.indexOf('{', start), depth = 0;
  for (let k = i; k < JS.length; k++) {
    if (JS[k] === '{') depth++;
    else if (JS[k] === '}') { depth--; if (!depth) return JS.slice(start, k + 1); }
  }
  throw new Error('unbalanced: ' + name);
}
const REASONS = /const ADM_EXIT_REASON = \{[\s\S]*?\};/.exec(JS);
ok('the exit-reason table exists', !!REASONS);

const src = [
  'function escapeHtml(s){return String(s==null?"":s).replace(/[&<>"\']/g,' +
    'c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","\'":"&#39;"}[c]));}',
  'function _fmtUptime(s){s=Number(s)||0;if(s<=0)return "—";' +
    'const h=Math.floor(s/3600),m=Math.floor((s%3600)/60);' +
    'return h?`${h}h ${m}m`:`${m}m ${s%60}s`;}',
  'let opened=null; function openModal(id){opened=id;' +
    'const m=document.getElementById(id); if(m){m.classList.remove("hidden");m.classList.add("open");}}',
  'function closeModal(id){const m=document.getElementById(id); if(m)m.classList.add("hidden");}',
  REASONS[0],
  extract('_admRow'),
  extract('renderAdminJobs'),
  extract('renderAdminJobDetail'),
  'return {renderAdminJobs, renderAdminJobDetail, getOpened:()=>opened};',
].join('\n');
const api = new dom.window.Function(src)();

// ── real payloads (shapes copied from routes/admin.py) ───────────────────
const LIST = [
  { id: 1, name: 'realbot', language: 'python', owner: 'boss', owner_suspended: 0,
    created_at: '2026-07-20 10:00:00', runner_job_id: 'ja', live_status: 'running',
    uptime_s: 4210, mem_mb: 31.4, peak_mem_mb: 88.2, restarts: 0, worker: 'primary' },
  { id: 2, name: 'flappy', language: 'node', owner: 'someone', owner_suspended: 1,
    created_at: '2026-07-21 10:00:00', runner_job_id: 'jb', live_status: 'stopped',
    uptime_s: 0, mem_mb: null, peak_mem_mb: 240.0, restarts: 3, worker: 'https://worker-b.test' },
];
const DETAIL_OOM = {
  job: {
    id: 2, name: 'flappy', language: 'node', user_id: 7, owner: 'someone',
    owner_email: 'someone@gmail.com', owner_suspended: 1, owner_job_count: 3,
    source: 'telegram', source_inferred: true,
    created_at: '2026-07-21 10:00:00', worker: 'https://worker-b.test',
    status: 'stopped', uptime_s: 0, restarts: 3, mem_mb: 0.0, peak_mem_mb: 240.0,
    cpu_pct: 0.0, last_exit_reason: 'oom', web_slug: 'flappy',
    env_keys: ['BOT_TOKEN', 'ADMIN_ID'], libs: ['pyTelegramBotAPI', 'requests'],
  },
  logs: 'Traceback (most recent call last):\n  File "main.py", line 3\n' +
        '[system] Process stopped: exceeded memory limit (256MB).',
  log_truncated: false,
  runner_reachable: true,
};

// ── 1. the list becomes a way in ────────────────────────────────────────
console.log('\n[1] the list is openable');
api.renderAdminJobs(LIST);
const rows = [...d.querySelectorAll('#admJobs tr')].slice(1);
ok('both apps listed', rows.length === 2, String(rows.length));
ok('a row is a button', rows[0].getAttribute('role') === 'button');
ok('and reachable by keyboard, not mouse only',
   rows[0].getAttribute('tabindex') === '0' && !!rows[0].getAttribute('onkeydown'),
   rows[0].getAttribute('onkeydown'));
ok('the click carries the DB job id, not the row index',
   /openAdminJob\(2\)/.test(rows[1].getAttribute('onclick')),
   rows[1].getAttribute('onclick'));
ok('the table is marked clickable so CSS can show it',
   d.getElementById('admJobs').classList.contains('clickable'));
ok('a clickable row actually gets a cursor',
   /\.adm-table\.clickable tr\[role="button"\]\s*\{[^}]*cursor:\s*pointer/.test(CSS));

console.log('[2] the list shows what makes a row worth opening');
const txt0 = rows[0].textContent, txt1 = rows[1].textContent;
ok('memory is on the row', /31MB/.test(txt0), txt0);
ok('so is the peak', /peak 88MB/.test(txt0), txt0);
ok('a crash-looping app shows its restart count', /3×/.test(txt1), txt1);
ok('and it is flagged, not left as plain text',
   !!rows[1].querySelector('.adm-pill.warn'));
ok('a healthy app is NOT flagged',
   !rows[0].querySelector('.adm-num-zero') === false &&
   !!rows[0].querySelector('.adm-num-zero'));
ok('a suspended owner is still called out', /suspended/.test(txt1));
ok('memory with no live reading reads as —, not 0MB',
   /—/.test(rows[1].children[3].textContent), rows[1].children[3].textContent);

// ── 3. the detail view ──────────────────────────────────────────────────
console.log('[3] detail: the resource picture');
api.renderAdminJobDetail(DETAIL_OOM);
const body = d.getElementById('admJobBody');
const all = body.textContent;
ok('the title is the app name',
   d.getElementById('admJobTitle').textContent === 'flappy');
ok('current AND peak memory are both shown', /0MB now/.test(all) && /240MB peak/.test(all), all.slice(0, 200));
ok('restart count is shown', /\b3\b/.test(all));
ok('the physical worker is named', /worker-b\.test/.test(all));
ok('the owner is named', /someone/.test(all));
ok('with how many other apps they run', /3 apps on this account/.test(all));
ok('the signup route is labelled as an inference, not a fact',
   /telegram \(inferred\)/.test(all), all.match(/Created via[\s\S]{0,40}/));

console.log('[4] detail: why it died, in words');
ok('the OOM is explained in English, not as a token',
   /used more memory than it is allowed/.test(all), all.match(/adm-jd-why[\s\S]{0,80}/));
ok('the raw token is not left on screen', !/\boom\b/.test(all), all.match(/.{0,40}oom.{0,40}/));
ok('the explanation is visually separated', !!body.querySelector('.adm-jd-why'));

console.log('[5] detail: the log');
const pre = body.querySelector('.adm-jd-log');
ok('the log is rendered', !!pre && /Traceback/.test(pre.textContent));
ok('the memory-limit line reaches the admin',
   /exceeded memory limit/.test(pre.textContent));

// A log is whatever the user's program printed. If it is ever concatenated
// into innerHTML, a bot that prints a <script> tag owns the admin's session.
const XSS = JSON.parse(JSON.stringify(DETAIL_OOM));
XSS.logs = '<img src=x onerror="window.__pwned=1">';
XSS.job.name = '<script>window.__pwned=2</script>';
XSS.job.libs = ['<b>evil</b>'];
XSS.job.owner_email = '<i>ev@il</i>';
api.renderAdminJobDetail(XSS);
ok('a log full of HTML creates no elements',
   d.querySelectorAll('#admJobBody img, #admJobBody script').length === 0);
ok('the log text survives verbatim',
   d.querySelector('.adm-jd-log').textContent === XSS.logs);
ok('an app NAME full of HTML creates no elements',
   d.getElementById('admJobTitle').querySelector('*') === null &&
   d.getElementById('admJobTitle').textContent === XSS.job.name);
ok('a package name full of HTML creates no elements',
   d.querySelectorAll('#admJobBody b, #admJobBody i').length === 0);
ok('window was never touched', dom.window.__pwned === undefined);

console.log('[6] detail: what must never appear');
ok('env KEYS are listed', /BOT_TOKEN/.test(all));
ok('the render only ever reads env_keys, never env',
   !/j\.env\b(?!_keys)/.test(extract('renderAdminJobDetail')));
ok('the route never selects the code column',
   !/SELECT[\s\S]{0,400}j\.code/.test(
     /def admin_job_detail_route[\s\S]*?\n@router/.exec(PYADMIN)[0]));
ok('the source code is not in the payload', !('code' in DETAIL_OOM.job));

console.log('[7] an unreachable worker is not a dead app');
const STALE = {
  job: { id: 1, name: 'realbot', owner: 'boss', user_id: 1, owner_job_count: 1,
         status: 'unknown', status_stale: true, worker: 'https://worker-b.test',
         libs: [], env_keys: [] },
  logs: '', log_truncated: false, runner_reachable: false,
};
api.renderAdminJobDetail(STALE);
const staleTxt = d.getElementById('admJobBody').textContent;
ok('status reads unknown', /unknown/.test(staleTxt));
ok('it is NOT called offline', !/offline/.test(staleTxt), staleTxt.slice(0, 120));
ok('and the reason is stated plainly',
   /worker did not answer/.test(staleTxt), staleTxt.slice(0, 200));
ok('the empty log says why it is empty',
   /the worker did not answer/.test(d.querySelector('.adm-jd-log').textContent));

console.log('[8] every reason the runner can emit has a sentence');
// I wrote this map from memory the first time and invented two tokens the
// runner never emits ("killed", "error"), which meant a real crash would have
// printed the raw token. Read the tokens out of runner/app.py instead.
const RUNNER = fs.readFileSync(path.join(ROOT, 'runner/app.py'), 'utf8');
// Balance the parens by hand: j.get("stop_requested") closes one mid-way, so
// a lazy /\)\n/ stops two tokens early and the check silently under-reads.
const _a = RUNNER.indexOf('j["last_exit_reason"] = (');
let _i = RUNNER.indexOf('(', _a), _dep = 0, _end = _i;
for (let k = _i; k < RUNNER.length; k++) {
  if (RUNNER[k] === '(') _dep++;
  else if (RUNNER[k] === ')') { _dep--; if (!_dep) { _end = k; break; } }
}
const assign = _a < 0 ? null : [null, RUNNER.slice(_i, _end)];
ok('the assignment is found in the runner', !!assign);
const tokens = [...assign[1].matchAll(/"([a-z]+)"/g)].map(m => m[1]);
ok('the runner emits the tokens we think it does',
   tokens.length === 4, tokens.join(','));
const mapped = [...REASONS[0].matchAll(/^\s{2}([a-z]+):/gm)].map(m => m[1]);
tokens.forEach(t => ok(`"${t}" has a human sentence`, mapped.includes(t), mapped.join(',')));
ok('and no sentence is written for a token that cannot happen',
   mapped.every(m => tokens.includes(m)), mapped.filter(m => !tokens.includes(m)).join(','));

console.log('[9] the route itself');
ok('a per-job route exists', /@router\.get\("\/admin\/jobs\/\{job_id\}"\)/.test(PYADMIN));
const JOBDETAIL = /def admin_job_detail_route[\s\S]*?\n@router/.exec(PYADMIN)[0];
ok('it is behind the same 404 gate', /require_admin\(authorization\)/.test(JOBDETAIL));
ok('the gate runs before any DB work',
   JOBDETAIL.indexOf('require_admin') < JOBDETAIL.indexOf('get_db_connection'));
ok('it asks the worker that HOLDS the job, not pool[0]',
   /f"\/internal\/jobs\/\{rid\}", worker=worker/.test(PYADMIN));
ok('a missing job is 404, not 500',
   /if not row:\s*\n\s*raise HTTPException\(status_code=404/.test(PYADMIN));
ok('the log is tailed rather than returned whole',
   /logs\.splitlines\(\)\[-200:\]/.test(PYADMIN));
ok('and the truncation is admitted', /"log_truncated"/.test(PYADMIN));
ok('the detail modal ships INSIDE the admin fragment, not index.html',
   /id="admJobModal"/.test(FRAG) &&
   !/admJobModal/.test(fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8')));

console.log(`\ntest_admin_job_detail: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
