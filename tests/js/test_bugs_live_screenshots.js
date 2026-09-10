/* Pins the four live defects from tajhatAti/bugs (2026-09-08 screenshots)
 * plus the "what's i really want" mockups:
 *   1. no script leak after </html>
 *   2. mobile hamburger actually hides desktop links and lists How it works
 *   3. auth card has its own ink so headings are not stuck faded
 *   4. landing terminal is readable on the dark well
 *   5. password reveal is an eye (Show text stays for a11y/tests)
 *   6. job overview has Restart / Stop + collapsible logs
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');
const js = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');
const d = new JSDOM(html).window.document;

let pass = 0, fail = 0;
const ok = (n, c, e) => {
  if (c) pass++;
  else { fail++; console.log('  FAIL ' + n + (e ? ' -> ' + e : '')); }
};

console.log('[1] leaked script');
const afterHtml = html.slice(html.toLowerCase().lastIndexOf('</html>') + 7);
ok('exactly one </html>', (html.match(/<\/html>/gi) || []).length === 1);
ok('nothing after </html> except whitespace', afterHtml.trim() === '', JSON.stringify(afterHtml.slice(0, 80)));
ok('the splash safety net is INSIDE a script, not as visible text',
   /<script>[\s\S]*s\.style\.display = 'none'[\s\S]*<\/script>\s*<\/body>/i.test(html));

console.log('[2] mobile nav');
ok('hamburger exists', !!d.getElementById('navBurger'));
ok('sheet exists', !!d.getElementById('navSheet'));
const sheetText = (d.getElementById('navSheet') || { textContent: '' }).textContent;
ok('sheet includes How it works', /How it works/i.test(sheetText));
ok('sheet includes Features', /Features/i.test(sheetText));
ok('closeNavSheet is defined', /function closeNavSheet\s*\(/.test(js));
ok('a later unscoped .nav-links flex cannot beat the phone hide',
   /@media \(max-width: 760px\)[\s\S]*?\.nav-links \{ display: none !important; \}/.test(css));
ok('hamburger bars are painted',
   /\.nav-burger span \{[\s\S]*?background: currentColor/.test(css));

console.log('[3] fade / auth ink');
ok('.auth sets color: var(--fg)', /\.auth \{[\s\S]*?color: var\(--fg\)/.test(css));
ok('post-boot reveal does not stay at opacity 0',
   /html:not\(\.booting\) \.reveal[\s\S]*?opacity: 1/.test(css));
ok('.back is static so it cannot cover the logo',
   /\.auth[\s\S]{0,80}\.back \{[\s\S]*?position: static/.test(css));

console.log('[4] terminal contrast');
ok('.term-card pins its own ink',
   /\.term-card \{[\s\S]*?--fg-3:\s*#8993a5/.test(css));
ok('.tc-mut on the card uses the pinned quiet ink',
   /\.term-card \.tc-mut \{ color: var\(--fg-3\)/.test(css));

console.log('[5] auth reveal + telegram fallback');
const toggles = [...d.querySelectorAll('.pw-toggle')];
ok('four password reveal buttons', toggles.length === 4, String(toggles.length));
ok('each points at a real input',
   toggles.every(b => !!d.getElementById(b.getAttribute('data-pw'))));
ok('initPasswordEyes will not nest a second wrap',
   /existingWrap && existingWrap\.querySelector\("\.pw-toggle/.test(js));
ok('dead Telegram widget hides the black slot',
   /show\(isSignin \? "telegramLogin" : "telegramSignup", false\)/.test(js));
ok('fallback banner exists and starts hidden',
   d.getElementById('telegramUnavailable') &&
   d.getElementById('telegramUnavailable').hasAttribute('hidden'));

console.log('[6] dashboard overview');
ok('overview Restart', !!d.getElementById('jdOvRestart'));
ok('overview Stop', !!d.getElementById('jdOvStop'));
ok('collapsible View logs',
   !!d.getElementById('jdOvLogs') &&
   d.getElementById('jdOvLogs').tagName === 'DETAILS');
ok('menu still owns the original Restart/Stop (not moved)',
   d.getElementById('jdRestart') &&
   d.getElementById('jdRestart').closest('#jdMoreMenu') &&
   d.getElementById('jdStop').closest('#jdMoreMenu'));

console.log(`\ntest_bugs_live_screenshots: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
