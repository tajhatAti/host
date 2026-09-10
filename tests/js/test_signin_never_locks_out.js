/* Signing out must never lock a user out of their own account.
 *
 * THE BUG THIS EXISTS FOR — reported from the live site, then reproduced here.
 * TELEGRAM_ONLY_AUTH defaulted to "1", which HID the e-mail form whenever a
 * bot username was configured. The Telegram widget was then the only way in.
 * telegram-widget.js is a third-party script: an extension, a network, or a
 * slow response can stop it rendering. Measured on the real markup with the
 * widget not rendering:
 *
 *   what the user sees : "Sign in  One tap. No password to remember."
 *   clickable ways in  : none
 *
 * A user who signed out could not get back in. Config could not save them,
 * because the config is what hid the form.
 *
 * The rule pinned here is deliberately blunt: in EVERY combination of server
 * config and widget health, the sign-in card must offer at least one way to
 * actually sign in.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const HTML = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const JS = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');
const APP = fs.readFileSync(path.join(ROOT, 'app.py'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, e) => { c ? pass++ : (fail++, console.log(`  FAIL ${n}${e ? ' -> ' + e : ''}`)); };

/* Pull the REAL mount() and mountWidget() out of pro.js — a reimplementation
 * here would test the test, not the page. */
function slice(startMarker) {
  const start = JS.indexOf(startMarker);
  if (start < 0) throw new Error('not found: ' + startMarker);
  let i = JS.indexOf('{', start), dep = 0;
  for (let k = i; k < JS.length; k++) {
    if (JS[k] === '{') dep++;
    else if (JS[k] === '}') { dep--; if (!dep) return JS.slice(start, k + 1); }
  }
  throw new Error('unbalanced: ' + startMarker);
}
const MOUNT_WIDGET = slice('function mountWidget(');
const MOUNT = slice('async function mount() {');

/* Run mount() against a given server config and widget outcome. */
function run(cfg, { widgetLoads, runSafetyNet = true }) {
  const dom = new JSDOM(HTML, { pretendToBeVisual: true });
  const w = dom.window, d = w.document;

  // Fake the widget script: it only produces an iframe when it "loads".
  const origAppend = w.HTMLElement.prototype.appendChild;
  w.HTMLElement.prototype.appendChild = function (node) {
    const r = origAppend.call(this, node);
    if (node.tagName === 'SCRIPT' && /telegram-widget/.test(node.src || '') && widgetLoads) {
      origAppend.call(this, d.createElement('iframe'));
    }
    return r;
  };

  // fetch must be PASSED IN. new w.Function's scope chain reaches Node's own
  // global fetch, not window.fetch — a mock assigned to window is ignored, and
  // every config silently arrived as {}. That was a bug in this harness that
  // made the page look broken when it was not.
  const timers = [];
  const body = MOUNT.replace('async function mount() {', '').replace(/\}$/, '');
  const fn = new w.Function('document', 'setTimeout', 'fetch',
    MOUNT_WIDGET + '\nreturn (async () => {' + body + '})();');

  return fn(d, (cb) => timers.push(cb),
            () => Promise.resolve({ ok: true, json: () => Promise.resolve(cfg) }))
    .then(() => {
      if (runSafetyNet) timers.forEach(f => f());
      const vis = (id) => { const e = d.getElementById(id); return !!e && !e.hidden; };
      const widgetRendered = !!d.querySelector('#telegramLoginBtn iframe');
      return {
        d,
        telegram: vis('telegramLogin'),
        email: vis('emailAuthSignin'),
        notice: vis('telegramUnavailable'),
        widgetRendered,
        // The only question that matters.
        canSignIn: vis('emailAuthSignin') || (vis('telegramLogin') && widgetRendered),
      };
    });
}

(async () => {

// ── 1. the markup the code depends on ───────────────────────────────────
console.log('\n[1] the fallback notice exists at all');
const bare = new JSDOM(HTML).window.document;
// mount() has always tried to show this element; it was never in the markup,
// so on the failure path the card rendered a hint sentence and nothing else.
ok('telegramUnavailable exists in index.html',
   !!bare.getElementById('telegramUnavailable'));
ok('the sign-up card has one too',
   !!bare.getElementById('telegramUnavailableSignup'));
ok('it is styled', /\.auth-note\s*\{/.test(CSS));
ok('and it reads as information, not an error',
   !/error|failed|problem/i.test(bare.getElementById('telegramUnavailable').textContent),
   bare.getElementById('telegramUnavailable').textContent.trim());
ok('it names the way forward',
   /email/i.test(bare.getElementById('telegramUnavailable').textContent));

// ── 2. every combination leaves a way in ────────────────────────────────
console.log('[2] no configuration can lock a user out');
const cases = [
  ['bot configured, widget loads', { telegram_bot_username: 'MyBot', telegram_only: false }, { widgetLoads: true }],
  ['bot configured, widget BLOCKED', { telegram_bot_username: 'MyBot', telegram_only: false }, { widgetLoads: false }],
  ['no bot configured', { telegram_bot_username: '', telegram_only: false }, { widgetLoads: false }],
  ['config fetch failed entirely', {}, { widgetLoads: false }],
  ['TELEGRAM_ONLY_AUTH=1 and widget loads', { telegram_bot_username: 'MyBot', telegram_only: true }, { widgetLoads: true }],
  // The case that actually bit: opinionated config PLUS a dead script.
  ['TELEGRAM_ONLY_AUTH=1 and widget BLOCKED', { telegram_bot_username: 'MyBot', telegram_only: true }, { widgetLoads: false }],
];
for (const [name, cfg, opt] of cases) {
  const r = await run(cfg, opt);
  ok(`can sign in — ${name}`, r.canSignIn,
     `telegram=${r.telegram} widget=${r.widgetRendered} email=${r.email}`);
}

// ── 3. the safety net is a DOM check, not a config check ────────────────
console.log('[3] the safety net reads reality, not settings');
// Telegram-only is exactly the case where config cannot help: the config is
// what hid the form. So the net has to look for a button that really exists.
const blocked = await run({ telegram_bot_username: 'MyBot', telegram_only: true },
                          { widgetLoads: false });
ok('a dead widget reveals the e-mail form anyway', blocked.email);
ok('and explains why', blocked.notice);
const alive = await run({ telegram_bot_username: 'MyBot', telegram_only: true },
                        { widgetLoads: true });
ok('a working widget is left alone', alive.telegram && alive.widgetRendered);
ok('and no notice is shown for a healthy widget', !alive.notice);
ok('the net checks for a rendered iframe',
   /slot\.querySelector\("iframe"\)/.test(JS));
ok('it runs on a delay rather than racing the script',
   /setTimeout\(\(\) => \{[\s\S]{0,400}querySelector\("iframe"\)/.test(JS));

// Before the safety net existed this same case was a dead end.
console.log('[4] the regression is real, not theoretical');
const noNet = await run({ telegram_bot_username: 'MyBot', telegram_only: true },
                        { widgetLoads: false, runSafetyNet: false });
ok('WITHOUT the net, a blocked widget leaves nothing to click',
   !noNet.canSignIn,
   'the old failure no longer reproduces, so this test proves nothing');
ok('WITH the net, the same case recovers', blocked.canSignIn);

// ── 5. the server default ───────────────────────────────────────────────
console.log('[5] e-mail sign-in is on by default');
ok('TELEGRAM_ONLY_AUTH now defaults to off',
   /os\.getenv\("TELEGRAM_ONLY_AUTH", "0"\)/.test(APP),
   'the default still hides the e-mail form');
ok('and it is opt-IN, not opt-out',
   /\.strip\(\)\.lower\(\) in \("1", "true", "yes"\)/.test(APP));
ok('the reason is recorded next to it',
   /locked out of their own account/.test(APP));

// ── 6. both cards, not just sign-in ─────────────────────────────────────
console.log('[6] sign-up is protected the same way');
const su = await run({ telegram_bot_username: 'MyBot', telegram_only: true },
                     { widgetLoads: false });
const suVis = (id) => { const e = su.d.getElementById(id); return !!e && !e.hidden; };
ok('the sign-up e-mail form is revealed too', suVis('emailAuthSignup'));
ok('with its own notice', suVis('telegramUnavailableSignup'));

console.log(`\ntest_signin_never_locks_out: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
})();
