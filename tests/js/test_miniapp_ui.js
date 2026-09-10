/* CodeNest inside Telegram — the SAME app, adapted, not a second build.
 *
 * The trap this guards against: telegram-web-app.js defines
 * window.Telegram.WebApp on ANY page that loads it, including a plain browser
 * tab, where initData is an empty string. Treating mere presence as "inside
 * Telegram" would hide the login screen from ordinary visitors and leave them
 * on a blank page. Detection has to be initData, not the SDK object.
 *
 * Also checked: Telegram theme colours never overwrite product CSS
 * custom properties (they arrive from the client and land in a stylesheet),
 * an existing session is reused rather than re-authenticated, and a failed
 * verification falls back to the normal login rather than trapping the user.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const SRC = fs.readFileSync(path.join(ROOT, 'static/miniapp.js'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');
const HTML = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const PRO = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, e) => { c ? pass++ : (fail++, console.log(`  FAIL ${n}${e ? ' -> ' + e : ''}`)); };

/* Boot a page with a fake Telegram SDK and run the real miniapp.js in it. */
function boot({ initData, themeParams, colorScheme, fetchImpl, token }) {
  // runScripts: w.eval() runs in Node's scope, where `window` is undefined —
  // the module would throw before doing anything. Injecting a <script> makes
  // it execute inside the page, which is where it actually lives.
  const dom = new JSDOM('<!doctype html><html><body><button id="btnLogout">Out</button></body></html>',
                        { pretendToBeVisual: true, runScripts: 'dangerously',
                          url: 'https://ahadorg.onrender.com/' });
  const w = dom.window;
  const events = {};
  const calls = [];
  w.Telegram = initData === undefined ? undefined : {
    WebApp: {
      initData,
      themeParams: themeParams || {},
      colorScheme: colorScheme || 'dark',
      viewportStableHeight: 640,
      ready: () => calls.push('ready'),
      expand: () => calls.push('expand'),
      setHeaderColor: (c) => calls.push('header:' + c),
      setBackgroundColor: (c) => calls.push('background:' + c),
      setBottomBarColor: (c) => calls.push('bottom:' + c),
      onEvent: (name, fn) => { events[name] = fn; },
    },
  };
  w.API = '';
  w.requestAnimationFrame = (fn) => { fn(); return 0; };
  w.localStorage.clear();
  if (token) w.localStorage.setItem('ahad_token', token);
  w.fetch = fetchImpl || (() => Promise.reject(new Error('no fetch')));
  const tag = w.document.createElement('script');
  tag.textContent = SRC;
  w.document.body.appendChild(tag);
  return { dom, w, events, calls, d: w.document };
}

const GOOD_INIT = 'user=%7B%22id%22%3A555%7D&auth_date=1700000000&hash=abc';

// ── 1. detection ────────────────────────────────────────────────────────
console.log('\n[1] being inside Telegram is decided by initData, not by the SDK');
const noSdk = boot({ initData: undefined });
ok('no SDK at all → not in Telegram', noSdk.w.__inTelegram === false);
ok('and the html class is not set',
   !noSdk.d.documentElement.classList.contains('in-telegram'));

// This is the case that breaks real users: the SDK loads in a normal tab.
const browserTab = boot({ initData: '' });
ok('SDK present but initData empty → NOT in Telegram',
   browserTab.w.__inTelegram === false);
ok('no auto-login is even defined there',
   typeof browserTab.w.__tgAutoLogin !== 'function');
ok('the page is not restyled for a browser visitor',
   !browserTab.d.documentElement.classList.contains('in-telegram'));
ok('but ready() is still called so the SDK is not left hanging',
   browserTab.calls.includes('ready'));

const inTg = boot({ initData: GOOD_INIT });
ok('real initData → in Telegram', inTg.w.__inTelegram === true);
ok('the html class is set so CSS can adapt',
   inTg.d.documentElement.classList.contains('in-telegram'));

// ── 2. viewport ─────────────────────────────────────────────────────────
console.log('[2] the webview is opened at full height');
ok('ready() is called', inTg.calls.includes('ready'));
ok('expand() is called, or it opens as a small sheet',
   inTg.calls.includes('expand'));
ok('the stable height is exposed to CSS',
   inTg.d.documentElement.style.getPropertyValue('--tg-vh') === '640px',
   inTg.d.documentElement.style.getPropertyValue('--tg-vh'));
ok('and it tracks viewportChanged, since the keyboard resizes it',
   typeof inTg.events.viewportChanged === 'function');
inTg.w.Telegram.WebApp.viewportStableHeight = 400;
inTg.events.viewportChanged();
ok('a resize updates the variable',
   inTg.d.documentElement.style.getPropertyValue('--tg-vh') === '400px');

// ── 3. product colour ───────────────────────────────────────────────────
console.log('[3] Telegram chrome cannot turn the product blue');
const themed = boot({
  initData: GOOD_INIT,
  colorScheme: 'light',
  themeParams: { bg_color: '#2481cc', text_color: '#ffffff',
                 button_color: '#2481cc', hint_color: '#99bbee' },
});
const st = themed.d.documentElement.style;
ok('Telegram bg is not injected into --bg', st.getPropertyValue('--bg') === '');
ok('Telegram button blue is not injected into --acc', st.getPropertyValue('--acc') === '');
ok('the product remains in its supported dark scheme',
   themed.d.documentElement.getAttribute('data-theme') === 'dark');
ok('Telegram header uses the neutral product background',
   themed.calls.includes('header:#090909'));
ok('Telegram webview background uses the neutral product background',
   themed.calls.includes('background:#090909'));
ok('themeChanged does not trigger full product restyling',
   typeof themed.events.themeChanged === 'undefined');
ok('the source contains no themeParams-to-CSS map',
   !/root\.style\.setProperty\(cssVar/.test(SRC));
ok('viewport changes are coalesced into one animation frame',
   /if \(viewportFrame\) return;[\s\S]*requestAnimationFrame/.test(SRC));
ok('Telegram canvas is forced to the neutral product background',
   /html\.in-telegram #tab-jobs \{ background:#090909 !important/.test(CSS));
ok('blurred fixed panels are disabled in the WebView',
   /html\.in-telegram \.bottom-nav,[\s\S]{0,220}backdrop-filter:none !important/.test(CSS));

// ── 4. auto-login ───────────────────────────────────────────────────────
console.log('[4] auto-login: zero taps');
let posted = null;
const okFetch = (url, opts) => {
  posted = { url, body: JSON.parse(opts.body) };
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ token: 'tok123', username: 'tg_555', created: true }),
  });
};
(async () => {
  const a = boot({ initData: GOOD_INIT, fetchImpl: okFetch });
  const res = await a.w.__tgAutoLogin();
  ok('it posts to the Mini App route, not the widget one',
     posted.url.endsWith('/auth/telegram/miniapp'), posted.url);
  ok('sending the raw initData for the server to verify',
     posted.body.init_data === GOOD_INIT);
  ok('login succeeds', res.ok === true);
  ok('and the session is stored where the rest of the app reads it',
     a.w.localStorage.getItem('ahad_token') === 'tok123');
  ok('the username is cached too', a.w.localStorage.getItem('ahad_user') === 'tg_555');

  // Re-authenticating on every open would spawn a session row each time.
  posted = null;
  const b = boot({ initData: GOOD_INIT, fetchImpl: okFetch, token: 'existing' });
  const r2 = await b.w.__tgAutoLogin();
  ok('an existing session is reused, not re-authenticated', r2.reused === true);
  ok('no request is made at all', posted === null);
  ok('and the existing token is left alone',
     b.w.localStorage.getItem('ahad_token') === 'existing');

  // A rejected verification must not leave the user on a blank page.
  const badFetch = () => Promise.resolve({
    ok: false, status: 400,
    json: () => Promise.resolve({ detail: 'Could not verify Telegram sign-in.' }),
  });
  const cB = boot({ initData: GOOD_INIT, fetchImpl: badFetch });
  const r3 = await cB.w.__tgAutoLogin();
  ok('a rejected sign-in reports failure', r3.ok === false);
  ok('with the status, so the caller can decide', r3.status === 400);
  ok('and nothing is written to storage',
     cB.w.localStorage.getItem('ahad_token') === null);

  // ── 5. the boot path in pro.js ────────────────────────────────────────
  console.log('[5] the app signs in before choosing a screen');
  // Slice the WHOLE branch. Anchoring on window.__tgAutoLogin() used to work
  // when that call was the first line; it is now near the end, so the slice
  // ran past the branch and into unrelated boot code.
  const bootSeg = PRO.slice(PRO.indexOf('if (window.__inTelegram) {'),
                            PRO.indexOf('// ---- Boot: decide the screen SYNCHRONOUSLY'));
  ok('success goes straight to the dashboard',
     /showScreen\("screen-dashboard"\)/.test(bootSeg));
  // The old shape sent failures to screen-landing. That was the bug: a Mini
  // App user must never be shown a way to log in, because they already are.
  // Comments in the branch explain the old bug by name, so strip them before
  // asserting that the CODE no longer does it.
  const bootCode = bootSeg.replace(/\/\/.*$/gm, '');
  ok('failure shows a retry instead of a login screen',
     /_tgFatal\(/.test(bootCode) && !/showScreen\("screen-landing"\)/.test(bootCode),
     (bootCode.match(/showScreen\([^)]*\)/g) || []).join(','));
  ok('and the dashboard is what renders underneath',
     /showScreen\("screen-dashboard"\)/.test(bootSeg));
  ok('the splash is cleared on every path',
     (bootSeg.match(/done\(\)/g) || []).length >= 3, bootSeg.slice(0, 120));
  ok('it runs BEFORE the synchronous screen decision',
     PRO.indexOf('window.__tgAutoLogin()') <
     PRO.indexOf('// ---- Boot: decide the screen SYNCHRONOUSLY'));
  // An existing session must short-circuit: re-authenticating on every open
  // would create a session row each time.
  /* The one-line form this used to match was reformatted when the stale-token
     comment was added; the behaviour is unchanged — a stored token still
     renders the dashboard immediately instead of waiting on the network. What
     matters is that the branch exists and returns without an await, so match
     the statements rather than their whitespace. */
  ok('an existing session skips the round-trip',
     /if \(authToken\)\s*\{[\s\S]{0,80}?go\(\);\s*done\(\);[\s\S]{0,40}?return;/.test(bootSeg),
     bootSeg.slice(-500));

  // ── 6. visual adaptation ──────────────────────────────────────────────
  console.log('[6] redundant browser chrome is hidden, nothing is rebuilt');
  ok('sign-out is hidden inside the Mini App',
     /html\.tg-hide-signout #btnLogout\s*\{[^}]*display:\s*none/.test(CSS));
  ok('the class really is applied',
     inTg.d.documentElement.classList.contains('tg-hide-signout'));
  ok('the marketing navbar is hidden, since Telegram draws its own header',
     /html\.in-telegram nav\.nav\s*\{[^}]*display:\s*none/.test(CSS));
  // The rule has to match the real markup. An earlier version targeted
  // `.landing-nav`, a class that does not exist here, so it matched nothing.
  ok('and that selector exists in the page', /<nav class="nav">/.test(HTML));
  ok('full height uses the Telegram viewport, not 100vh',
     /html\.in-telegram body\s*\{[^}]*var\(--tg-vh/.test(CSS));

  console.log('[7] it is the same app, not a parallel one');
  ok('miniapp.js builds no UI', !/innerHTML|createElement\(/.test(SRC));
  ok('it defines no routes or screens of its own', !/screen-/.test(SRC));
  ok('and creates no second job path',
     !/\/api\/jobs|\/internal\//.test(SRC));
  ok('the SDK is loaded from Telegram\'s own origin',
     /https:\/\/telegram\.org\/js\/telegram-web-app\.js/.test(HTML));

  // ── 8. NO AUTH SCREEN INSIDE TELEGRAM, EVER ───────────────────────────
  console.log('[8] a Mini App user never sees a login form');

  // THE REPORTED BUG: the Mini App showed "Create Account". Two causes.
  //   (a) telegram-web-app.js is fetched from telegram.org. When it is slow or
  //       blocked, window.Telegram never exists, __inTelegram was false, and
  //       boot fell through to routeFromUrl() on /dashboard — a PROTECTED
  //       route — which redirects an unauthenticated visit to screen-signin.
  //   (b) the failure branch itself called showScreen("screen-landing").
  const DATA = 'user=%7B%22id%22%3A5%7D&auth_date=1&hash=x';

  function bootPage({ sdk, hash }) {
    const dd = new JSDOM(HTML, {
      pretendToBeVisual: true, runScripts: 'dangerously',
      url: 'https://ahadorg.onrender.com/dashboard' + (hash || ''),
    });
    const ww = dd.window;
    if (sdk !== null) {
      ww.Telegram = { WebApp: { initData: sdk, themeParams: {}, colorScheme: 'dark',
        viewportStableHeight: 640, ready() {}, expand() {}, onEvent() {} } };
    }
    const style = ww.document.createElement('style');
    style.textContent = CSS; ww.document.head.appendChild(style);
    const sc = ww.document.createElement('script');
    sc.textContent = SRC; ww.document.body.appendChild(sc);
    return ww;
  }

  function signinReachable(ww) {
    const e = ww.document.getElementById('screen-signin');
    if (!e) return false;
    e.classList.add('active');
    return ww.getComputedStyle(e).display !== 'none';
  }

  // Telegram appends #tgWebAppData to the webview URL itself — no third-party
  // script involved — so this signal survives a blocked SDK.
  const blocked = bootPage({ sdk: null, hash: '#tgWebAppData=' + encodeURIComponent(DATA) });
  ok('a blocked SDK is still recognised as Telegram', blocked.__inTelegram === true);
  ok('and the payload is read from the URL fragment',
     blocked.__tgInitData === DATA, String(blocked.__tgInitData).slice(0, 40));
  ok('auto-login is still available', typeof blocked.__tgAutoLogin === 'function');
  ok('the sign-in screen is unreachable', !signinReachable(blocked));

  const normal = bootPage({ sdk: DATA });
  ok('with the SDK it is recognised too', normal.__inTelegram === true);
  ok('and the sign-in screen is unreachable there as well', !signinReachable(normal));
  ok('the document is marked so CSS can enforce it',
     normal.document.documentElement.classList.contains('tg-no-auth'));

  // Every auth surface, not just sign-in — a Create Account screen is the one
  // that was actually reported.
  ['screen-signup', 'screen-otp', 'screen-forgot1'].forEach((id) => {
    const e = normal.document.getElementById(id);
    if (!e) return;
    e.classList.add('active');
    ok(`${id} is unreachable inside Telegram`,
       normal.getComputedStyle(e).display === 'none');
  });

  // A normal browser must be completely unaffected.
  const web = bootPage({ sdk: null });
  ok('a plain browser is NOT treated as Telegram', web.__inTelegram === false);
  ok('it is not marked tg-no-auth',
     !web.document.documentElement.classList.contains('tg-no-auth'));
  ok('and its sign-in screen still works', signinReachable(web));
  const webSdk = bootPage({ sdk: '' });
  ok('the SDK loading in a browser tab changes nothing',
     webSdk.__inTelegram === false && signinReachable(webSdk));

  console.log('[8b] miniapp.js cannot depend on anything pro.js defines');
  // THE BUG THAT PRODUCED "Couldn't connect": this file used `API`, which
  // pro.js declares on its line 6. miniapp.js loads BEFORE pro.js — it has
  // to, because pro.js's boot reads the globals set here — so `API` did not
  // exist and the fetch threw ReferenceError. The rejection hit the boot
  // branch's .catch() and surfaced as a connection error that was neither a
  // network nor a server problem.
  ok('the auth request uses a same-origin path, not the API constant',
     /fetch\("\/auth\/telegram\/miniapp"/.test(SRC),
     (SRC.match(/fetch\([^,]*/) || [''])[0]);
  ok('API is not referenced at all', !/\bAPI\b\s*\+/.test(SRC));

  // Any OTHER pro.js symbol must be typeof-guarded, or it reintroduces this.
  {
    const code = SRC.replace(/\/\*[\s\S]*?\*\//g, '')
                    .replace(/\/\/.*/g, '')
                    .replace(/"[^"]*"|'[^']*'|`[^`]*`/g, '""');
    const declared = new Set([...code.matchAll(/(?:const|let|var|function)\s+([A-Za-z_$][\w$]*)/g)]
                             .map(m => m[1]));
    // Bare calls only. A METHOD call like Object.keys() is not a global, and
    // counting it produced a false hit on "keys".
    const called = [...new Set([...code.matchAll(/(^|[^.\w$])([A-Za-z_$][\w$]*)\s*\(/g)]
                               .map(m => m[2]))];
    const fromPro = called.filter(n => !declared.has(n)
      && new RegExp('(?:function|const|let|var)\\s+' + n + '\\b').test(PRO));
    const unguarded = fromPro.filter(n => !new RegExp('typeof\\s+' + n).test(SRC));
    ok('every pro.js symbol it touches is typeof-guarded',
       unguarded.length === 0, unguarded.join(','));
  }

  // Drive the real function to prove it no longer throws.
  {
    const dd = new JSDOM('<!doctype html><body></body>', {
      pretendToBeVisual: true, runScripts: 'dangerously',
      url: 'https://ahadorg.onrender.com/dashboard#tgWebAppData=' + encodeURIComponent(DATA),
    });
    const ww = dd.window;
    ww.Telegram = { WebApp: { initData: DATA, themeParams: {}, colorScheme: 'dark',
      viewportStableHeight: 640, ready() {}, expand() {}, onEvent() {} } };
    let hit = null;
    ww.fetch = (u) => { hit = u; return Promise.resolve({ ok: true,
      json: () => Promise.resolve({ token: 't', username: 'tg_555' }) }); };
    const sc = ww.document.createElement('script');
    sc.textContent = SRC; ww.document.body.appendChild(sc);
    // pro.js has NOT run — exactly the real load order.
    ok('API is genuinely undefined at this point',
       ww.eval('typeof API') === 'undefined');
    const res = await ww.__tgAutoLogin().catch((e) => ({ threw: e.message }));
    ok('auto-login does not throw without pro.js', !res.threw, res.threw);
    ok('it succeeds', res.ok === true, JSON.stringify(res));
    ok('and hits the right endpoint', hit === '/auth/telegram/miniapp', String(hit));
  }

  console.log('[9] the boot branch cannot route to an auth screen');
  const branch = PRO.slice(PRO.indexOf('if (window.__inTelegram) {'),
                           PRO.indexOf('// ---- Boot: decide the screen SYNCHRONOUSLY'));
  // Strip comments first: the branch DESCRIBES the bug it fixes, and matching
  // that prose would fail on a correct implementation.
  const branchCode = branch.replace(/\/\/.*$/gm, '');
  ok('no auth screen is named anywhere in the actual code',
     !/screen-(signin|signup|landing|otp|forgot)/.test(branchCode),
     (branchCode.match(/screen-\w+/g) || []).join(','));
  ok('routeFromUrl runs only once a token exists',
     /if \(authToken\) \{ try \{ routeFromUrl\(\)/.test(branch));
  ok('failure shows a retry, not a form', /_tgFatal\(/.test(branch));
  ok('and the retry text offers to try again',
     /Couldn't connect/.test(branch), branch.slice(-400));
  ok('a missing miniapp.js still lands on the dashboard',
     /typeof window\.__tgAutoLogin !== "function"/.test(branch));

  // The website half must be untouched.
  console.log('[10] the website keeps its own Sign in / Sign out');
  const plain = new JSDOM(HTML).window.document;
  const navBtns = [...plain.querySelectorAll('.nav-cta button')].map(b => b.textContent.trim());
  ok('the navbar still has Sign in', navBtns.includes('Sign in'), navBtns.join(','));
  ok('and Get started', navBtns.some(t => /Get started/i.test(t)), navBtns.join(','));
  ok('the sign-out button still exists', !!plain.getElementById('btnLogout'));
  ok('the e-mail sign-in form is still in the page',
     !!plain.getElementById('formSignin'));
  ok('so is the Telegram login slot', !!plain.getElementById('telegramLoginBtn'));
  ok('sign-out is only hidden by the Telegram class, not deleted',
     /html\.tg-hide-signout #btnLogout/.test(CSS));

  console.log(`\ntest_miniapp_ui: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
