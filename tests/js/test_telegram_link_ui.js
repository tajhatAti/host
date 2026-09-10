/* Settings → Connect Telegram, the site half of the bot's identity gate.
 *
 * The bot now refuses any chat that is not bound to an account. That gate is
 * only usable if the site can actually hand out a code, so this pins the flow
 * a person walks: open Settings, get a code, see what to send, and have the
 * card flip once the BOT redeems it.
 *
 * The rule that matters most: the code is requested by an authenticated web
 * session. Nothing here may let the chat ask for its own code.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const JS = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');
const HTML = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const PROFILE = fs.readFileSync(path.join(ROOT, 'routes/profile.py'), 'utf8');
const PINGBOT = fs.readFileSync(path.join(ROOT, 'services/pingbot.py'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, e) => { c ? pass++ : (fail++, console.log(`  FAIL ${n}${e ? ' -> ' + e : ''}`)); };

const dom = new JSDOM(HTML, { pretendToBeVisual: true });
const d = dom.window.document;
d.querySelectorAll('link[rel=stylesheet]').forEach(l => l.remove());
const st = d.createElement('style'); st.textContent = CSS; d.head.appendChild(st);
global.window = dom.window; global.document = d;

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

const src = [
  'const calls = []; const toasts = []; let STATE = {linked:false};',
  'const CODE = {code:"482913", expires_in_min:10, bot_username:"CodeNestBot",' +
  ' deep_link:"https://t.me/CodeNestBot?start=482913",' +
  ' instructions:"Send /link 482913"};',
  'const openedUrls = []; window.open = (u) => { openedUrls.push(u); };',
  'function api(p, m){ calls.push([m||"GET", p]);' +
  '  if (p === "/profile/telegram") return Promise.resolve(STATE);' +
  '  if (p === "/profile/telegram/code") return Promise.resolve(CODE);' +
  '  if (p === "/profile/telegram/unlink") { STATE = {linked:false}; return Promise.resolve({}); }' +
  '  return Promise.reject(new Error("404")); }',
  'function toast(t){ toasts.push(t); }',
  'function setLoading(){}',
  'const opened = [], closed = [];',
  'function openModal(id){opened.push(id);const m=document.getElementById(id);if(m)m.classList.remove("hidden");}',
  'function closeModal(id){closed.push(id);const m=document.getElementById(id);if(m)m.classList.add("hidden");}',
  'let _tgPollTimer = null;',
  extract('refreshTelegramCard'),
  extract('manageTelegram'),
  extract('_tgPoll'),
  'return {refreshTelegramCard, manageTelegram, calls, toasts, opened, closed,' +
  ' openedUrls, setState:v=>{STATE=v;}, getState:()=>STATE,' +
  ' setCode:v=>{Object.assign(CODE,v);}};',
].join('\n');
const app = new dom.window.Function(src)();

(async () => {

// ── 1. the card ─────────────────────────────────────────────────────────
console.log('\n[1] Settings shows the connection state');
ok('the card exists in Settings', !!d.getElementById('tgChip'));
ok('with a button', !!d.getElementById('btnTelegram'));
ok('and the modal ships with the page', !!d.getElementById('tgModal'));

await app.refreshTelegramCard();
ok('an unlinked account says so',
   d.getElementById('tgChip').textContent === 'Not connected',
   d.getElementById('tgChip').textContent);
ok('the button invites you to connect',
   d.getElementById('btnTelegram').textContent === 'Connect Telegram');
// Someone messaging a bot that ignores them has no way to know why. Saying it
// here is the only place that costs nothing.
ok('and the card explains the bot will ignore you until you link',
   /ignore you until you link/.test(d.getElementById('tgMeta').textContent),
   d.getElementById('tgMeta').textContent);

app.setState({ linked: true, telegram_id: 111222333 });
await app.refreshTelegramCard();
ok('a linked account flips the chip',
   d.getElementById('tgChip').textContent === 'Connected');
ok('the chip is marked on, not just reworded',
   d.getElementById('tgChip').className.includes('on'));
ok('the chat id is shown, so you can tell WHICH Telegram is bound',
   /111222333/.test(d.getElementById('tgMeta').textContent),
   d.getElementById('tgMeta').textContent);
ok('and the button becomes Manage',
   d.getElementById('btnTelegram').textContent === 'Manage Telegram');

// ── 2. getting a code ───────────────────────────────────────────────────
console.log('[2] the code comes from the site, on request');
app.setState({ linked: false });
await app.manageTelegram();
const body = d.getElementById('tgModalBody');
ok('the modal opened', app.opened.includes('tgModal'));
ok('no code is shown before you ask',
   d.querySelector('.tg-code').textContent === '······',
   d.querySelector('.tg-code').textContent);
// Opening Settings must not mint a code — codes replace each other, so an
// idle visit would silently kill a code the user is mid-way through typing.
ok('merely opening the modal does not issue one',
   !app.calls.some(([m, p]) => p === '/profile/telegram/code'),
   JSON.stringify(app.calls));

// ONE TAP is the whole change: the old flow made the user read a 6-digit
// code, find the bot by name, and retype the code from memory. Those were the
// three steps a person could actually fail.
const openBtn = body.querySelector('a.tg-open');
ok('the primary action is a single Connect button', !!openBtn,
   body.innerHTML.slice(0, 120));
ok('it says what it does', /Connect bot to account/.test(openBtn.textContent),
   openBtn.textContent);
ok('the manual code is demoted to a fallback, not the main path',
   !!body.querySelector('details.tg-fallback'));
ok('and that fallback starts closed',
   body.querySelector('details.tg-fallback').open !== true);

await openBtn.onclick({ preventDefault() {} });
ok('the code is requested with POST, not GET',
   app.calls.some(([m, p]) => p === '/profile/telegram/code' && m === 'POST'),
   JSON.stringify(app.calls));
ok('the button now points at the t.me deep link',
   openBtn.href === 'https://t.me/CodeNestBot?start=482913', openBtn.href);
ok('the link carries the SAME code, not a second weaker secret',
   openBtn.href.endsWith('=482913'));
ok('Telegram is actually opened for the user',
   app.openedUrls.includes('https://t.me/CodeNestBot?start=482913'),
   JSON.stringify(app.openedUrls));
ok('it opens in a new tab so the dashboard stays put',
   openBtn.target === '_blank' && /noopener/.test(openBtn.rel));
ok('the user is told what happens next',
   /Waiting for you to press START/.test(body.textContent),
   body.textContent.slice(0, 200));

// The fallback still has to work for a desktop with no Telegram installed.
ok('the code is available in the fallback',
   d.querySelector('.tg-code').textContent === '482913');
ok('the exact command is spelled out there',
   /\/link 482913/.test(body.textContent), body.textContent.slice(0, 260));
ok('the bot handle is named', /@CodeNestBot/.test(body.textContent));
ok('and so is the expiry, so a stale code is not a mystery',
   /10 min/.test(body.textContent));

// A second tap must NOT mint a new code — that would invalidate the one the
// user is already looking at in Telegram.
const before = app.calls.filter(([m, p]) => p === '/profile/telegram/code').length;
await openBtn.onclick({ preventDefault() {} });
ok('tapping again reuses the issued code',
   app.calls.filter(([m, p]) => p === '/profile/telegram/code').length === before,
   String(before));

// The bot username comes from an env var; it must not be parsed as markup.
ok('the instruction line is built with textContent',
   /step\.textContent =/.test(extract('manageTelegram')));
ok('the deep link is assigned to href, never interpolated into HTML',
   /openBtn\.href = r\.deep_link/.test(extract('manageTelegram')));
ok('the code element is too',
   /codeBox\.textContent = r\.code/.test(extract('manageTelegram')));

// ── 3. the card flips when the BOT redeems it ───────────────────────────
console.log('[3] the wait is handled, and bounded');
app.setState({ linked: true, telegram_id: 111222333 });
await new Promise(r => setTimeout(r, 5200));
ok('the modal closes once the bot links',
   app.closed.includes('tgModal'), app.closed.join(','));
ok('and the user is told', app.toasts.some(t => /connected/i.test(t)),
   app.toasts.join('|'));
const pollSrc = extract('_tgPoll');
ok('the poll is 5s, not sub-second', /5000/.test(pollSrc));
ok('it stops itself rather than running forever',
   /ticks > 60/.test(pollSrc), pollSrc.slice(0, 200));
ok('and clears any previous timer, so two opens do not double-poll',
   /if \(_tgPollTimer\) clearInterval\(_tgPollTimer\)/.test(pollSrc));

// ── 4. disconnecting ────────────────────────────────────────────────────
console.log('[4] disconnecting');
await app.manageTelegram();
const body2 = d.getElementById('tgModalBody');
ok('the linked view is different from the connect view',
   /Disconnect/.test(body2.textContent), body2.textContent.slice(0, 120));
ok('it says what disconnecting actually does',
   /stops the bot from deploying/.test(body2.textContent));
const offBtn = [...body2.querySelectorAll('button')].find(b => /Disconnect/.test(b.textContent));
ok('the disconnect button is styled as destructive',
   offBtn.className.includes('btn-danger'));
await offBtn.onclick();
ok('unlink is called', app.calls.some(([m, p]) => p === '/profile/telegram/unlink'));
ok('and the card goes back to not connected',
   d.getElementById('tgChip').textContent === 'Not connected');

// ── 5. the server contract this UI depends on ───────────────────────────
console.log('[4b] the card names WHO is connected');
// A bare chat id is not something a person recognises. "Connected" without a
// who cannot be checked by the account owner at all.
app.setState({ linked: true, telegram_id: 111222333, telegram_name: '@ahadxyz' });
await app.refreshTelegramCard();
ok('the Telegram handle is shown',
   /@ahadxyz/.test(d.getElementById('tgMeta').textContent),
   d.getElementById('tgMeta').textContent);
ok('the id is still there for the ambiguous case',
   /111222333/.test(d.getElementById('tgMeta').textContent));
await app.manageTelegram();
ok('and the manage view names it too',
   /@ahadxyz/.test(d.getElementById('tgModalBody').textContent),
   d.getElementById('tgModalBody').textContent.slice(0, 120));
// An older link made before the name column existed must still render.
app.setState({ linked: true, telegram_id: 111222333 });
await app.refreshTelegramCard();
ok('a link with no cached name falls back to the id',
   /Chat ID 111222333/.test(d.getElementById('tgMeta').textContent),
   d.getElementById('tgMeta').textContent);

console.log('[4c] no bot username configured');
// TELEGRAM_BOT_USERNAME unset means no t.me link can be built. Handing the
// user a broken URL would be worse than saying so.
app.setState({ linked: false });
app.setCode({ deep_link: '' });
await app.manageTelegram();
const b3 = d.getElementById('tgModalBody');
await b3.querySelector('a.tg-open').onclick({ preventDefault() {} });
ok('the dead button is removed rather than left to fail',
   !b3.querySelector('a.tg-open'));
ok('the code fallback is opened automatically',
   b3.querySelector('details.tg-fallback').open === true);
ok('and the user is told to use it',
   /Use the code below/.test(b3.textContent), b3.textContent.slice(0, 160));
app.setCode({ deep_link: 'https://t.me/CodeNestBot?start=482913' });

console.log('[5] the routes behind it');
ok('status route exists', /@router\.get\("\/profile\/telegram"\)/.test(PROFILE));
ok('code route exists', /@router\.post\("\/profile\/telegram\/code"\)/.test(PROFILE));
ok('unlink route exists', /@router\.post\("\/profile\/telegram\/unlink"\)/.test(PROFILE));
const CODEROUTE = /def telegram_link_code[\s\S]*?\n@router/.exec(PROFILE)[0];
ok('issuing a code needs a session',
   /get_current_user_and_session\(authorization\)/.test(CODEROUTE));
ok('and is rate limited, since codes replace each other',
   /rate_limit_custom\(/.test(CODEROUTE));
ok('the code is issued for the SESSION user, not an id from the request',
   /issue_code\(user\["id"\]\)/.test(CODEROUTE));

// The whole point: the bot cannot mint its own code.
ok('the bot never calls issue_code', !/issue_code/.test(PINGBOT));
ok('the bot only ever REDEEMS', /redeem_code/.test(PINGBOT));

// The deep link must go through the same redeem path as the typed command,
// or it is a second front door with its own rules to get wrong.
ok('a /start payload is handed to the same handler as /link',
   /handle_link\(chat_id, f"\/link \{payload\}", first_name\)/.test(PINGBOT),
   'handle_start payload branch');
ok('the payload is split off with split(None, 1)',
   /text\.split\(None, 1\)/.test(PINGBOT));
const TLPY = fs.readFileSync(path.join(ROOT, 'services/telegram_link.py'), 'utf8');
ok('the deep link is built from the issued code, not a new secret',
   /f"https:\/\/t\.me\/\{BOT_USERNAME\}\?start=\{code\}"/.test(TLPY));
ok('an unset bot username yields no link at all',
   /if not BOT_USERNAME or not code:\s*\n\s*return ""/.test(TLPY));
ok('a leading @ in the env var is stripped',
   /\.lstrip\("@"\)/.test(TLPY));

console.log(`\ntest_telegram_link_ui: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
})();
