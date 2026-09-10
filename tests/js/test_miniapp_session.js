/* THE MINI APP MUST NEVER SAY "SESSION EXPIRED".
 *
 * Inside Telegram the account IS the Telegram account, so an expired token is
 * something the app can fix by itself in one request. Twice now it did not,
 * and both times the user saw the same thing: "Session Expired", then a page
 * with no way to sign in, because app.css hides every auth screen under
 * html.tg-no-auth (correctly — a login form there is meaningless).
 *
 * The three faults this suite pins down, each reproduced before being fixed:
 *
 *  1. THE CONCURRENT-401 RACE. The re-auth guard was a boolean:
 *
 *         if (inTelegram && autoLogin && !_tgReauthInFlight) { re-auth }
 *         toast("Session expired"); location.href = "/";
 *
 *     The dashboard fires /profile, /snippets, /stats and /api/jobs together.
 *     With one dead token they 401 together: the first takes the lock, and
 *     every other one FAILS THE CONDITION and falls straight through to the
 *     browser logout. The guard written to prevent a race is what produced
 *     the message. Measured on the committed code: 1 call recovered, 3 were
 *     signed out.
 *
 *  2. THE SPENT RETRY. `_retried` was one budget shared by the cold-start
 *     retry and the retry-after-re-login, so a successful re-auth had no
 *     attempt left and failed anyway.
 *
 *  3. THE INVISIBLE SCREEN. Seven call sites still called
 *     showScreen("screen-signin"), which hid the dashboard and then "showed"
 *     an element the stylesheet keeps at display:none — a blank phone.
 *
 * These are behaviour tests: they execute the real api() and the real
 * showScreen() out of static/pro.js.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const SRC = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, e) => {
  if (c) { pass++; }
  else { fail++; console.log('  FAIL ' + n + (e !== undefined ? ' -> ' + e : '')); }
};

/* Lift api() and its re-auth lock out of pro.js and run them for real. The
   rest of the file touches the DOM at load time and is irrelevant here. */
function slice(startRe, endRe) {
  const a = SRC.search(startRe);
  if (a < 0) throw new Error('not found: ' + startRe);
  const rest = SRC.slice(a);
  const b = rest.search(endRe);
  return b < 0 ? rest : rest.slice(0, b);
}
const API_SRC = slice(/\nasync function api\(/, /\n\/\* -+ SERVER-UP BANNER/);
const LOCK_SRC = slice(/\nlet _tgReauthPromise/, /\nasync function api\(/);

/* @param inTelegram  simulate the Telegram webview
 * @param loginWorks  whether __tgAutoLogin can mint a fresh token */
function makeApi({ inTelegram = true, loginWorks = true } = {}) {
  const log = [];
  let store = { ahad_token: 'DEAD' };
  const sandbox = {
    API: '', authToken: 'DEAD', _fpCache: '',
    setTimeout, clearTimeout, Promise, JSON, Error, console,
    localStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: (k) => { delete store[k]; },
    },
    toast: (m) => log.push('TOAST:' + m),
    _tgFatal: (m) => log.push('FATAL:' + m),
    _serverDown: () => {}, _serverUp: () => {},
    log, loginCalls: 0,
  };
  sandbox.window = {
    __inTelegram: inTelegram,
    location: { set href(v) { log.push('REDIRECT:' + v); } },
  };
  if (inTelegram) {
    sandbox.window.__tgAutoLogin = async () => {
      sandbox.loginCalls++;
      await new Promise(r => setTimeout(r, 20));      // a real round-trip
      if (!loginWorks) return { ok: false, detail: 'Bot token mismatch.' };
      sandbox.localStorage.setItem('ahad_token', 'FRESH');
      sandbox.authToken = 'FRESH';
      return { ok: true };
    };
  }
  // Server: rejects DEAD, accepts FRESH.
  sandbox.fetch = async (url, opt) => {
    const good = ((opt.headers || {})['Authorization'] || '') === 'Bearer FRESH';
    await new Promise(r => setTimeout(r, 5));
    return { status: good ? 200 : 401, ok: good,
             json: async () => (good ? { ok: true } : { detail: 'expired' }) };
  };
  const ctx = vm.createContext(sandbox);
  vm.runInContext(LOCK_SRC + '\n' + API_SRC + '\nthis.api = api;', ctx);
  return sandbox;
}

// ── 1. the race ─────────────────────────────────────────────────────────
console.log('\n[1] four dashboard calls 401 at once on one dead token');
(async () => {
  const s = makeApi();
  const paths = ['/profile', '/snippets', '/stats', '/api/jobs'];
  const out = await Promise.all(paths.map(p =>
    s.api(p, 'GET', null, true).then(() => 'OK').catch(e => 'ERR:' + e.message)));

  ok('EVERY call recovers, not just the one that won the lock',
     out.every(x => x === 'OK'), out.join(', '));
  ok('nobody is told the session expired',
     !s.log.some(l => l.startsWith('TOAST:Session expired')), s.log.join(' | '));
  ok('and nobody is redirected to a page with no sign-in',
     !s.log.some(l => l.startsWith('REDIRECT:')));
  ok('exactly ONE login is sent for the whole burst — the losers wait for '
     + 'the winner rather than each opening their own session',
     s.loginCalls === 1, s.loginCalls);

  // ── 2. a single call ──────────────────────────────────────────────────
  console.log('[2] one call, one dead token');
  const s2 = makeApi();
  const r2 = await s2.api('/profile', 'GET', null, true)
                     .then(() => 'OK').catch(e => 'ERR:' + e.message);
  ok('it re-authenticates and returns the real answer', r2 === 'OK', r2);
  ok('the fresh token is stored',
     s2.localStorage.getItem('ahad_token') === 'FRESH');

  // ── 3. re-auth genuinely fails ────────────────────────────────────────
  console.log('[3] when Telegram itself refuses (wrong bot token)');
  const s3 = makeApi({ loginWorks: false });
  await s3.api('/profile', 'GET', null, true).catch(() => {});
  ok('the SERVER\'S OWN reason is shown, not a generic apology',
     s3.log.some(l => l === 'FATAL:Bot token mismatch.'), s3.log.join(' | '));
  ok('still no redirect to the dead page',
     !s3.log.some(l => l.startsWith('REDIRECT:')));

  // ── 4. the browser is untouched ───────────────────────────────────────
  console.log('[4] a normal browser still signs out the ordinary way');
  const s4 = makeApi({ inTelegram: false });
  await s4.api('/profile', 'GET', null, true).catch(() => {});
  // The redirect is deliberately on a 1.5s timer so the toast is readable.
  await new Promise(r => setTimeout(r, 1700));
  ok('it toasts', s4.log.some(l => l.startsWith('TOAST:Session expired')));
  ok('and it redirects home', s4.log.some(l => l === 'REDIRECT:/'));
  ok('the token is cleared', s4.localStorage.getItem('ahad_token') === null);

  // ── 5. the two retry budgets ──────────────────────────────────────────
  console.log('[5] a cold-start retry must not spend the re-login retry');
  ok('api() takes _retried AND _reauthed as separate parameters',
     /_retried\s*=\s*false,\s*\n?\s*_reauthed\s*=\s*false/.test(API_SRC));
  ok('the Telegram branch runs BEFORE the 800ms cold-start stall, so a '
     + 'Mini App re-login is not delayed by a wait that cannot help it',
     API_SRC.indexOf('__tgAutoLogin') < API_SRC.indexOf('800'));

  // ── 6. the hidden-screen trap ─────────────────────────────────────────
  console.log('[6] no code path can paint a screen the stylesheet hides');
  const hidden = new Set();
  CSS.replace(/html\.tg-no-auth\s+#([\w-]+)/g, (_, id) => hidden.add(id));
  ok('app.css hides the auth screens (precondition)', hidden.size >= 6);

  const block = (SRC.match(/const _TG_FORBIDDEN_SCREENS = \{([\s\S]*?)\};/) || [])[1] || '';
  const guarded = new Set();
  block.replace(/"([\w-]+)"/g, (_, id) => guarded.add(id));
  const gap = [...hidden].filter(id => !guarded.has(id));
  ok('every hidden screen is also refused by showScreen()',
     gap.length === 0, 'unguarded: ' + gap.join(','));

  const fnSrc = SRC.slice(SRC.indexOf('const _TG_FORBIDDEN_SCREENS'),
                          SRC.indexOf('/* ---------------- SIDEBAR DRAWER'));
  const mk = () => new JSDOM('<!doctype html><html><body>'
    + '<div class="auth" id="screen-signin">signin</div>'
    + '<div class="dashboard" id="screen-dashboard">dash</div></body></html>',
    { runScripts: 'outside-only' }).window;

  const wTg = mk();
  wTg.eval('var authToken="tok"; var window=this; ' + fnSrc);
  wTg.__inTelegram = true;
  wTg.eval('showScreen("screen-signin")');
  ok('inside Telegram, asking for sign-in shows the DASHBOARD',
     wTg.document.getElementById('screen-dashboard').style.display !== 'none');
  ok('and the sign-in screen is left hidden',
     wTg.document.getElementById('screen-signin').style.display === 'none');

  const wBr = mk();
  wBr.eval('var authToken=null; var window=this; ' + fnSrc);
  wBr.__inTelegram = false;
  wBr.eval('showScreen("screen-signin")');
  ok('in a browser the sign-in screen still appears',
     wBr.document.getElementById('screen-signin').style.display !== 'none');

  // ── 7. the error sheet must be visible ────────────────────────────────
  console.log('[7] _tgFatal has styling, or its message cannot be read');
  ok('.tg-fatal is styled at all', /\.tg-fatal\s*\{/.test(CSS));
  ok('it is a full-screen centred layer, not text below the fold',
     /\.tg-fatal\s*\{[^}]*position:\s*fixed[^}]*\}/.test(CSS));
  ok('[hidden] still closes it', /\.tg-fatal\[hidden\]\s*\{\s*display:\s*none/.test(CSS));

  console.log('\ntest_miniapp_session: ' + pass + ' passed, ' + fail + ' failed');
  if (fail) process.exit(1);
})();
