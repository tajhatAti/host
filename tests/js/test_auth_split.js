/* AUTH SCREENS — the split-screen rebuild.
 *
 * What this pins down:
 *   1. STRUCTURE — seven screens, each with exactly one card column, and one
 *      shared brand panel rather than seven hand-copied ones.
 *   2. NOTHING LOST — the form ids, the OTP boxes, the Telegram fallback and
 *      the no-captcha rule all survive a visual rewrite. This is the check
 *      that matters most: a redesign that silently drops `su_terms` or the
 *      sixth OTP box still looks fine.
 *   3. BEHAVIOUR — the panel is injected by real shipping code and the
 *      password reveal really toggles, executed here rather than assumed.
 *   4. DESIGN RULES — no blur, no new colour, collapses on a phone, hidden
 *      inside Telegram.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const HTML = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');
const JS = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, e) => { c ? pass++ : (fail++, console.log(`  FAIL ${n}${e ? ' -> ' + e : ''}`)); };

const SCREENS = ['screen-signup', 'screen-signin', 'screen-otp',
                 'screen-forgot1', 'screen-forgot2', 'screen-forgot3',
                 'screen-forgot-success'];

console.log('[1] structure');
const staticDom = new JSDOM(HTML).window.document;
SCREENS.forEach(id => ok(`screen intact: ${id}`, !!staticDom.getElementById(id)));
ok('every screen has exactly one card column',
   SCREENS.every(id => {
     const s = staticDom.getElementById(id);
     return s && s.querySelectorAll(':scope > .auth-main').length === 1;
   }));
ok('one shared brand panel, not seven copies',
   !!staticDom.getElementById('authAside') &&
   staticDom.querySelectorAll('.auth-aside').length === 0);
/* A <template>'s children live in .content, not in the element itself — so
   these read the fragment, which is also what the browser clones. */
const PANEL = staticDom.getElementById('authAside').content;
ok('the panel makes the product case',
   /Three bots free/.test(PANEL.textContent) && !!PANEL.querySelector('h1'));
ok('the panel names three concrete facts',
   PANEL.querySelectorAll('li').length === 3);
ok('every panel claim sits in the checklist, not in a badge',
   PANEL.querySelectorAll('.auth-points li').length === 3 &&
   !PANEL.querySelector('.store-badge, .adm-pill, .rs-badge'));

console.log('[2] nothing the forms need was lost');
ok('signup inputs are still exactly the four essentials',
   [...staticDom.querySelectorAll('#formSignup input')].map(i => i.id).join(',')
     === 'su_username,su_email,su_password,su_terms');
ok('terms checkbox still present', !!staticDom.getElementById('su_terms'));
ok('strength meter still wired', !!staticDom.getElementById('strengthFill') &&
   !!staticDom.getElementById('strengthLabel'));
ok('sign-in keeps both credential fields',
   !!staticDom.getElementById('si_username') && !!staticDom.getElementById('si_password'));
ok('both OTP screens still have six boxes',
   staticDom.querySelectorAll('#otpBoxesSignup input').length === 6 &&
   staticDom.querySelectorAll('#otpBoxesForgot input').length === 6);
ok('resend + expiry still present', !!staticDom.getElementById('resendLink') &&
   !!staticDom.getElementById('otpExpire'));
ok('Telegram fallback notice still present and hidden',
   staticDom.getElementById('telegramUnavailable').hasAttribute('hidden') &&
   staticDom.getElementById('telegramUnavailableSignup').hasAttribute('hidden'));
ok('forgot-password path intact',
   ['formForgot1', 'btnForgot2', 'formForgot3', 'fp_newpass', 'fp_confirmpass']
     .every(id => !!staticDom.getElementById(id)));
ok('no captcha came back', !staticDom.getElementById('su_captcha') &&
   !staticDom.querySelector('.captcha-box'));
ok('field errors still have a home (.field wrapper)',
   ['su_username', 'su_email', 'si_username', 'fp_email'].every(id =>
     !!staticDom.getElementById(id).closest('.field')));
ok('price question answered on the signup card',
   /free forever for three bots/i.test(staticDom.querySelector('.auth-trust').textContent) &&
   /no card/i.test(staticDom.querySelector('.auth-trust').textContent));

console.log('[3] design rules');
const authCss = CSS.slice(CSS.indexOf('/* ──────────────────────────────── AUTH ──'),
                          CSS.indexOf('/* ───────────────────────────── DASHBOARD ──'));
ok('split layout is a two-column grid', /\.auth \{[\s\S]*grid-template-columns: minmax\(0, 1\.02fr\) minmax\(0, 1fr\)/.test(authCss));
ok('it collapses to one column on a phone', /@media \(max-width: 900px\) \{[\s\S]*\.auth \{ grid-template-columns: minmax\(0, 1fr\); \}/.test(authCss));
ok('the panel is hidden on a phone', /\.auth-aside \{ display: none; \}/.test(authCss));
ok('the panel is hidden inside Telegram', /html\.tg-no-auth \.auth-aside \{ display: none; \}/.test(authCss));
ok('the card does not carry a second brand on desktop',
   /@media \(min-width: 901px\) \{[\s\S]*\.auth-aside \+ \.auth-main \.auth-head \.brand-mark \{ display: none; \}/.test(authCss));
ok('the back button is finally styled', /\.back \{[\s\S]*cursor: pointer/.test(authCss));
ok('no blur in the auth block', !/backdrop-filter/.test(authCss));
ok('no raw hex colour in the auth block', !/#[0-9a-fA-F]{3,8}\b/.test(authCss));
ok('surfaces come from the neutral ramp', /background: var\(--bar\)/.test(authCss));
/* Status tokens are allowed (they carry meaning); a SECOND accent is not.
   The auth block leans on .btn-primary for emphasis and adds no colour of
   its own beyond the green ✓ that marks an included fact. */
ok('the only hue is the status green checkmark', /color: var\(--ok\)/.test(authCss) &&
   (authCss.match(/var\(--(ok|warn|danger)\)/g) || []).join(' ') === 'var(--ok) var(--danger)');
ok('no second accent is introduced', !/var\(--acc\)/.test(authCss) && !/--acc-2|--brand-/.test(authCss));
ok('viewport height uses dvh with a vh fallback',
   /min-height: 100vh;\s*min-height: 100dvh;/.test(authCss));

console.log('[4] the panel is injected, and the reveal works — executed');
const start = JS.indexOf('(function _initAuthScreens()');
const end = JS.indexOf('})();', start) + 5;
ok('the auth boot block exists in pro.js', start > 0 && end > start);

const dom = new JSDOM(HTML, { pretendToBeVisual: true });
const w = dom.window;
/* Run the shipping IIFE against the real document. jsdom only executes
   window.eval inside the window realm with runScripts:'dangerously', so the
   block is compiled with the two globals it actually reads instead. */
const boot = new Function('document', 'window', JS.slice(start, end));
boot(w.document, w);

setTimeout(() => {
  const d = w.document;
  const withPanel = SCREENS.filter(id => {
    const s = d.getElementById(id);
    return s && s.querySelectorAll('.auth-aside').length === 1;
  });
  ok('every auth screen received exactly one panel', withPanel.length === SCREENS.length,
     withPanel.join(','));
  ok('the panel is the first child, so it takes the left column',
     SCREENS.every(id => d.getElementById(id).firstElementChild.classList.contains('auth-aside')));
  ok('the panel is not duplicated on a second run', (() => {
    boot(w.document, w);
    return SCREENS.every(id => d.getElementById(id).querySelectorAll('.auth-aside').length === 1);
  })());
  ok('the panel brings the brand mark with it',
     !!d.querySelector('#screen-signin .auth-aside .brand-mark'));

  const input = d.getElementById('su_password');
  const btn = d.querySelector('.pw-toggle[data-pw="su_password"]');
  ok('a password field has its own reveal button', !!btn);
  ok('it starts hidden as a password', input.type === 'password' && btn.textContent === 'Show');
  btn.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
  ok('one tap reveals it', input.type === 'text' && btn.textContent === 'Hide');
  ok('and says so to a screen reader', btn.getAttribute('aria-pressed') === 'true');
  btn.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
  ok('a second tap hides it again', input.type === 'password' && btn.textContent === 'Show' &&
     btn.getAttribute('aria-pressed') === 'false');
  ok('the reveal is a button, so it never submits the form',
     btn.tagName === 'BUTTON' && btn.getAttribute('type') === 'button');
  ok('every reveal button points at a real input',
     [...d.querySelectorAll('.pw-toggle')].every(b => !!d.getElementById(b.dataset.pw)));

  console.log(`test_auth_split: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
}, 60);
