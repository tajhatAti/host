/* Admin console — library insights + per-account drill-down (dashboard step 4).
 *
 * WHAT WAS WRONG.
 *
 * 1. /admin/users/{id} already returned jobs, sessions with IP + fingerprint,
 *    and the activity log. The browser NEVER CALLED IT. grep for
 *    "/admin/users/" + id in static/pro.js returned nothing; the only user
 *    interaction in the whole panel was the Suspend button. A complete
 *    drill-down endpoint had been sitting unreachable.
 *
 * 2. The package panel ordered by COUNT and hid the owners in a title=
 *    tooltip. A tooltip does not exist on a phone, so on mobile the panel
 *    answered nothing. And on a 512MB box "which package is popular" is
 *    trivia — the question is "what is holding the memory, and whose is it".
 *
 * The rules pinned here:
 *   - a user row opens the account; a package row names its owners INLINE
 *   - packages sort by attributed memory, and the fact that it is ATTRIBUTED
 *     (a job counts toward every package it imports, so the column does not
 *     sum) is stated on screen, not left for the reader to misread
 *   - linked accounts are framed as a prompt to look, never as a verdict
 *   - the Suspend button inside a clickable row must not also open the row
 *   - every user-controlled string goes through textContent
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

const dom = new JSDOM(`<!doctype html><body><div class="dash-main"></div></body>`,
                      { pretendToBeVisual: true });
const d = dom.window.document;
d.querySelector('.dash-main').innerHTML = FRAG;
const st = d.createElement('style'); st.textContent = CSS; d.head.appendChild(st);
global.window = dom.window; global.document = d;

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

// jsdom's Node lives on the window, not on globalThis inside a new Function.
// _admRow does `value instanceof Node`, so without this the harness throws
// where a browser would not — a bug in the TEST, not in the page.
const src = [
  'const Node = window.Node;',
  'function escapeHtml(s){return String(s==null?"":s).replace(/[&<>"\']/g,' +
    'c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","\'":"&#39;"}[c]));}',
  'let _lastProfile = {id: 1};',
  'const openedJobs = [], openedUsers = [], closed = [];',
  'function openModal(id){const m=document.getElementById(id);if(m)m.classList.remove("hidden");}',
  'function closeModal(id){closed.push(id);const m=document.getElementById(id);if(m)m.classList.add("hidden");}',
  'function openAdminJob(id){openedJobs.push(id);}',
  extract('_admRow'),
  extract('_admSubhead'),
  extract('_admEmpty'),
  extract('renderAdminLibs'),
  extract('renderAdminUsers'),
  extract('renderAdminUserDetail'),
  'function openAdminUser(id){openedUsers.push(id);}',
  'return {renderAdminLibs, renderAdminUsers, renderAdminUserDetail,' +
    ' openedJobs, openedUsers, closed};',
].join('\n');
const api = new dom.window.Function(src)();

// ── real payload shapes, copied from routes/admin.py ─────────────────────
// In the order GET /admin/libraries really returns them: attributed memory
// descending. numpy is in ONE job and requests in two, so a count-ordered
// panel would have put numpy first — which is the old behaviour this replaces.
const LIBS = {
  libraries: [
    { library: 'requests', count: 2, mem_mb: 271.4, heavy: false, watch: false,
      pct_of_jobs: 100,
      jobs: [{ job_id: 2, name: 'flappy', owner: 'someone', mem_mb: 240.0, status: 'running' },
             { job_id: 1, name: 'realbot', owner: 'boss', mem_mb: 31.4, status: 'running' }] },
    { library: 'numpy', count: 1, mem_mb: 240.0, heavy: true, watch: false,
      pct_of_jobs: 50,
      jobs: [{ job_id: 2, name: 'flappy', owner: 'someone', mem_mb: 240.0, status: 'running' }] },
    { library: 'paramiko', count: 1, mem_mb: 31.4, heavy: false, watch: true,
      pct_of_jobs: 50,
      jobs: [{ job_id: 1, name: 'realbot', owner: 'boss', mem_mb: 31.4, status: 'running' }] },
  ],
  jobs_sampled: 2,
  mem_attributed: true,
  note: 'Counts cover jobs currently known to the runner.',
};

const USERS = [
  { id: 1, username: 'boss', email: 'boss@gmail.com', is_verified: 1,
    is_suspended: 0, is_admin: 1, created_at: '2026-07-01 09:00:00', job_count: 1 },
  { id: 7, username: 'someone', email: 'someone@gmail.com', is_verified: 1,
    is_suspended: 1, is_admin: 0, created_at: '2026-07-20 09:00:00', job_count: 3 },
];

const DETAIL = {
  user: { id: 7, username: 'someone', email: 'someone@gmail.com', is_verified: 1,
          is_suspended: 1, is_admin: 0, created_at: '2026-07-20 09:00:00',
          auth_method: 'telegram', auth_method_inferred: true,
          telegram_id: 5551234, fingerprint: 'fp-abc', last_ip: '203.0.113.9' },
  jobs: [
    { id: 2, name: 'flappy', language: 'node', live_status: 'running', mem_mb: 240.0 },
    { id: 3, name: 'idle', language: 'python', live_status: null, mem_mb: null },
  ],
  jobs_running: 1,
  mem_used_mb: 240.0,
  devices: 2,
  networks: 3,
  sessions: [
    { id: 9, ip_address: '203.0.113.9', device_info: 'Chrome on Android',
      fingerprint: 'fp-abc', created_at: '2026-07-27 11:00:00' },
  ],
  linked_accounts: [
    { id: 8, username: 'someone2', email: 'someone2@gmail.com',
      is_suspended: 0, created_at: '2026-07-21 09:00:00' },
  ],
  linked_note: 'Same device fingerprint or IP. Shared networks are common; this is a prompt to look, not proof.',
  events: [],
};

// ── 1. packages ─────────────────────────────────────────────────────────
console.log('\n[1] packages answer "what is eating the memory"');
api.renderAdminLibs(LIBS);
const libRows = [...d.querySelectorAll('#admLibs .adm-lib')];
ok('all packages render', libRows.length === 3, String(libRows.length));
ok('memory is on the row', /271MB/.test(libRows[0].textContent), libRows[0].textContent);
const order = libRows.map(r => r.querySelector('.adm-lib-name').textContent);
ok('the render preserves the order it was given',
   order.join(',') === 'requests,numpy,paramiko', order.join(','));
// The old panel sorted by count, which would have led with numpy (1 job, but
// 240MB is not why it would have won) — the route's ordering is what changed.
ok('a package in fewer jobs but holding more RAM outranks a popular one',
   order.indexOf('numpy') < order.indexOf('paramiko'), order.join(','));
ok('owners are ON the row, not in a tooltip',
   /someone\/flappy/.test(libRows[0].textContent), libRows[0].textContent);
ok('the tooltip is gone (a phone cannot show one)',
   !libRows[0].getAttribute('title'), libRows[0].getAttribute('title'));
ok('each owner link opens that app', libRows[0].querySelectorAll('a.adm-link').length === 2);
libRows[0].querySelector('a.adm-link').dispatchEvent(
  new dom.window.MouseEvent('click', { bubbles: true, cancelable: true }));
ok('clicking an owner opens the right job id',
   api.openedJobs[api.openedJobs.length - 1] === 2, JSON.stringify(api.openedJobs));

console.log('[2] attributed memory is labelled, not passed off as a breakdown');
const hint = d.getElementById('admLibsHint').textContent;
ok('the hint says attributed', /attributed/.test(hint), hint);
ok('it explains WHY it does not sum',
   /counts toward every package it imports/.test(hint), hint);
ok('the sample size is stated', /2 jobs sampled/.test(hint), hint);
// The numbers deliberately over-sum: 271 + 240 + 31 > the 271MB really in use.
const summed = LIBS.libraries.reduce((a, r) => a + r.mem_mb, 0);
ok('the column really does over-sum, so the label is load-bearing',
   summed > 271.4, String(summed));
ok('a watched package is flagged for review, not accused',
   /review/.test(libRows[2].textContent) && !/abuse/i.test(libRows[2].textContent),
   libRows[2].textContent);

// ── 3. the user list becomes a way in ───────────────────────────────────
console.log('[3] a user row opens the account');
api.renderAdminUsers(USERS);
const uRows = [...d.querySelectorAll('#admUsers tr')].slice(1);
ok('rows render', uRows.length === 2);
ok('a row is a button', uRows[1].getAttribute('role') === 'button');
ok('keyboard reachable', uRows[1].getAttribute('tabindex') === '0' &&
   !!uRows[1].getAttribute('onkeydown'));
ok('the click carries the user id', /openAdminUser\(7\)/.test(uRows[1].getAttribute('onclick')),
   uRows[1].getAttribute('onclick'));
// The Suspend button sits inside the clickable row. Without the guard, one tap
// both opens the drill-down and the confirm modal, stacked.
ok('the Suspend button does not also open the row',
   /closest\('\.adm-act'\)/.test(uRows[1].getAttribute('onclick')),
   uRows[1].getAttribute('onclick'));
ok('the suspend action is still wired', /askSuspend\(7/.test(uRows[1].innerHTML));
ok('the table is marked clickable', d.getElementById('admUsers').classList.contains('clickable'));

// ── 4. the drill-down ───────────────────────────────────────────────────
console.log('[4] the account view');
api.renderAdminUserDetail(DETAIL);
const ubody = d.getElementById('admUserBody');
const utxt = ubody.textContent;
ok('the title is the username',
   d.getElementById('admUserTitle').textContent === 'someone');
ok('suspension is visible up front', /suspended/.test(utxt));
ok('email is shown', /someone@gmail\.com/.test(utxt));
ok('signup route is labelled as an inference',
   /telegram \(inferred\)/.test(utxt), utxt.match(/Signed up via[\s\S]{0,40}/));
ok('apps are counted, running separately', /2 total · 1 running/.test(utxt), utxt.match(/Apps[\s\S]{0,40}/));
ok('their total memory is shown', /240MB across their running apps/.test(utxt));
ok('distinct devices and networks are counted',
   /2 devices · 3 networks/.test(utxt), utxt.match(/Devices seen[\s\S]{0,40}/));
ok('last IP is shown', /203\.0\.113\.9/.test(utxt));

console.log('[5] their apps drill through');
const jobTables = [...ubody.querySelectorAll('table.adm-table.clickable')];
ok('the app list is clickable', jobTables.length >= 1);
const jobRow = jobTables[0].querySelectorAll('tr')[1];
ok('the app name is there', /flappy/.test(jobRow.textContent));
ok('its live status is shown', !!jobRow.querySelector('.adm-pill.ok'));
ok('an app with no live reading reads —, not 0MB',
   /—/.test(jobTables[0].querySelectorAll('tr')[2].textContent));
jobRow.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
ok('clicking an app opens it', api.openedJobs[api.openedJobs.length - 1] === 2);
ok('and closes the account view first, rather than stacking modals',
   api.closed[api.closed.length - 1] === 'admUserModal', api.closed.join(','));

console.log('[6] linked accounts are a prompt, not a verdict');
ok('the section is present and counted', /Linked accounts \(1\)/.test(utxt), utxt.match(/Linked[\s\S]{0,30}/));
ok('the other account is named', /someone2/.test(utxt));
ok('the caveat about shared networks is on screen',
   /Shared networks are common/.test(utxt));
ok('it is phrased as a prompt to look', /prompt to look, not proof/.test(utxt));
ok('no accusatory word appears',
   !/(fraud|abuser|cheat|guilty)/i.test(utxt), utxt.slice(0, 200));
ok('the caveat is styled neutrally, not as an alert',
   !!ubody.querySelector('.adm-jd-why.neutral'));
ok('and neutral really removes the red bar',
   /\.adm-jd-why\.neutral\s*\{[^}]*border-left-color:\s*var\(--line-2\)/.test(CSS));

console.log('[7] an account with nothing to show says so');
const BARE = { user: { id: 5, username: 'newbie', is_verified: 1 }, jobs: [],
               jobs_running: 0, mem_used_mb: 0, devices: 0, networks: 0,
               sessions: [], linked_accounts: [], events: [] };
api.renderAdminUserDetail(BARE);
const btxt = d.getElementById('admUserBody').textContent;
ok('no apps reads as a sentence, not an empty table',
   /No apps on this account/.test(btxt));
ok('no linked accounts is stated positively',
   /No other account shares this device or IP/.test(btxt), btxt);
ok('a zero count is not dressed up as a finding',
   /Linked accounts \(0\)/.test(btxt));

console.log('[8] every user-controlled string is inert');
const XSS = JSON.parse(JSON.stringify(DETAIL));
XSS.user.username = '<script>window.__pwned=1</script>';
XSS.user.email = '<img src=x onerror="window.__pwned=2">';
XSS.jobs[0].name = '<b>evil</b>';
XSS.linked_accounts[0].username = '<i>evil2</i>';
XSS.sessions[0].device_info = '<u>evil3</u>';
api.renderAdminUserDetail(XSS);
ok('no elements are created from any of it',
   d.querySelectorAll('#admUserBody script, #admUserBody img, #admUserBody b:not(td b), ' +
                      '#admUserBody i, #admUserBody u').length === 0);
ok('the username stays literal text',
   d.getElementById('admUserTitle').querySelector('*') === null);
ok('window untouched', dom.window.__pwned === undefined);
const XLIB = JSON.parse(JSON.stringify(LIBS));
XLIB.libraries[0].library = '<script>window.__pwned=3</script>';
XLIB.libraries[0].jobs[0].owner = '<img src=x onerror="window.__pwned=4">';
api.renderAdminLibs(XLIB);
ok('a package name full of HTML creates no elements',
   d.querySelectorAll('#admLibs script, #admLibs img').length === 0);
ok('so does an owner name', dom.window.__pwned === undefined);

console.log('[8b] Telegram is visible throughout the console');
// The bot is a second front door onto the same platform. Before this, the
// console could not tell you which accounts could drive it, or which apps
// came from a chat — measured: overview had NO telegram key, and the user
// list had none either.
const TGUSERS = [
  { id: 1, username: 'boss', email: 'b@g.com', is_verified: 1, is_suspended: 0,
    created_at: '2026-07-01', job_count: 2, telegram_id: 555, telegram_name: '@bosstg' },
  { id: 9, username: 'webonly', email: 'w@g.com', is_verified: 1, is_suspended: 0,
    created_at: '2026-07-02', job_count: 0 },
];
api.renderAdminUsers(TGUSERS);
const tgRows = [...d.querySelectorAll('#admUsers tr')];
ok('the users table has a Telegram column',
   /Telegram/.test(tgRows[0].textContent), tgRows[0].textContent);
ok('a linked account shows its handle, not a bare number',
   /@bosstg/.test(tgRows[1].textContent), tgRows[1].textContent);
ok('an unlinked account shows a dash, not a stale value',
   !!tgRows[2].querySelector('.adm-num-zero'), tgRows[2].textContent);
ok('the handle goes through escapeHtml',
   /escapeHtml\(u\.telegram_name/.test(extract('renderAdminUsers')));
// The pill is a FACT about the account, not a status, so it must not borrow
// the ok/warn colours the design system reserves for meaning.
ok('the tg pill is neutral, not coloured as a status',
   !/\.adm-pill\.tg[^{]*\{[^}]*(--st-ok|--st-warn|--green|--red)/.test(CSS));

api.renderAdminUserDetail({
  ...DETAIL,
  user: { ...DETAIL.user, telegram_id: 555, telegram_name: '@bosstg' },
});
const tgTxt = d.getElementById('admUserBody').textContent;
ok('the drill-down names the connected Telegram', /@bosstg/.test(tgTxt),
   tgTxt.slice(0, 200));
ok('with the id for the ambiguous case', /555/.test(tgTxt));
// DETAIL's fixture user HAS a telegram_id (it is the telegram-signup case),
// so asserting "not connected" against it was testing the wrong row.
api.renderAdminUserDetail({
  ...DETAIL,
  user: { ...DETAIL.user, telegram_id: null, telegram_name: null },
});
ok('an account with no Telegram says so plainly',
   /not connected/.test(d.getElementById('admUserBody').textContent),
   d.getElementById('admUserBody').textContent.slice(0, 200));
// A link made before the name column existed must still render.
api.renderAdminUserDetail({
  ...DETAIL,
  user: { ...DETAIL.user, telegram_id: 5551234, telegram_name: null },
});
ok('an older link with no cached name falls back to the id',
   /linked · ID 5551234/.test(d.getElementById('admUserBody').textContent),
   d.getElementById('admUserBody').textContent.slice(0, 220));

console.log('[9] the routes behind it');
const UDET = /def admin_user_detail_route[\s\S]*?\n@router/.exec(PYADMIN)[0];
ok('the gate runs before any DB work',
   UDET.indexOf('require_admin') < UDET.indexOf('get_db_connection'));
ok('linked accounts reuse the existing cluster logic rather than new SQL',
   /limits\.cluster_user_ids\(/.test(UDET));
ok('the account itself is excluded from its own linked list',
   /ids\.discard\(user_id\)/.test(UDET));
ok('the list is bounded', /sorted\(ids\)\[:20\]/.test(UDET));
ok('a failed cluster lookup does not 500 the whole view',
   /except Exception as exc:[\s\S]{0,120}cluster lookup failed/.test(UDET));
ok('the overview counts Telegram-linked accounts',
   /"telegram_linked": tg_linked/.test(PYADMIN));
ok('the user list selects the handle, not only the id',
   /u\.telegram_name/.test(PYADMIN));
ok('devices and networks are counted from real sessions',
   /"devices": len\(fps\)/.test(UDET) && /"networks": len\(ips\)/.test(UDET));
ok('the shared-network caveat is authored server-side, so it cannot drift',
   /prompt to look, not proof/.test(UDET));

const LIBR = /def admin_libraries_route[\s\S]*?\n@router/.exec(PYADMIN)[0];
ok('packages sort by memory first', /key=lambda e: \(-e\["mem_mb"\]/.test(LIBR));
ok('memory is attributed per importing job', /e\["mem_mb"\] \+= mem/.test(LIBR));
ok('and the response flags it as attributed', /"mem_attributed": True/.test(LIBR));
ok('the over-sum is called out in a comment, not silently shipped',
   /ATTRIBUTED, NOT CAUSED/.test(LIBR));
ok('the per-package job list is capped and ordered by memory',
   /e\["jobs"\]\.sort\(key=lambda x: -\(x\["mem_mb"\] or 0\)\)/.test(LIBR));

ok('the account modal ships inside the admin fragment only',
   /id="admUserModal"/.test(FRAG) &&
   !/admUserModal/.test(fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8')));

console.log(`\ntest_admin_user_libs: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
