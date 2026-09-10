/* THE BUGS THE USER ACTUALLY REPORTED, each pinned by BEHAVIOUR.
 *
 * The earlier UI work measured tokens and never clicked anything, so it
 * "passed" while every one of these was still broken. The user's words, and
 * what each turned out to be:
 *
 *  1. "মেনু বাটনে ক্লিক করলে উপর একটা আবছা পর্দা আছে ওইটা এখনো আসতেছে"
 *     -> a desktop rule turned .rs-menu-backdrop on whenever the job rail
 *        opened, dimming the editor behind a 260px panel on a 1280px screen.
 *
 *  2. "সাইটে তিনটা মেনু বাটন ... একটাতে ক্লিক করলে মেনু আসে এবং আরেকটাতে
 *     ক্লিক করলে কিছুই আসে না"
 *     -> the job list had TWO entry points with the same icon: the header
 *        hamburger, and a "Job list" row inside the ⋯ menu that reached the
 *        same drawer through a different code path.
 *
 *  3. "মেইন ড্যাশবোর্ডে হালকা লাগি লাগি হইতেছে"
 *     -> every card animated box-shadow on hover. Shadows cannot be
 *        composited, so the browser repainted the full blur radius each frame
 *        for every card the pointer crossed — 10 cards on the overview.
 *
 *  4. "সাইন আউট বাটন গুলো কেমন জানি হয়েছে তারপরে ইউজারনেম"
 *     -> the username had no width limit and the row could wrap, so a long
 *        handle pushed Sign out toward the edge of a fixed-height bar.
 *
 *  5. "এই দিক থেকে ওই পাশে টানলে সরে যাচ্ছে ... অ্যাটাচ থাকতেছে না"
 *     -> overflow-x: hidden was on <body> only. The viewport scroller is the
 *        HTML element, so the document still slid sideways.
 *
 * AND THE ONE THAT HID #2 FOR SO LONG: the drawer toggle decided whether the
 * rail was open by measuring getBoundingClientRect().width. The rail is
 * hidden with translateX(-100%) on mobile, and a transformed element keeps
 * its full width — so the check read "open" in both states and the button
 * could open the drawer but never close it.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const css = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const js = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, x) => {
  if (c) { pass++; console.log('  ok   ' + n); }
  else { fail++; console.log('  FAIL ' + n + (x !== undefined ? ' -> ' + x : '')); }
};

/* Boot the app for real: inject pro.js ourselves, because jsdom does not
   fetch <script src> and without it none of the wiring exists. */
function boot(width) {
  const stripped = html
    .replace(/<script[^>]+src="[^"]*"[^>]*><\/script>/g, '')
    .replace(/<link[^>]+rel="stylesheet"[^>]*>/g, '');
  const dom = new JSDOM(stripped, {
    url: 'https://codenest.test/dashboard',
    runScripts: 'dangerously', pretendToBeVisual: true,
  });
  const w = dom.window, d = w.document;
  Object.defineProperty(w, 'innerWidth', { value: width, writable: true });
  w.matchMedia = q => {
    const m = /max-width:\s*(\d+)px/.exec(q);
    return { matches: m ? width <= +m[1] : false, media: q,
             addEventListener() {}, removeEventListener() {},
             addListener() {}, removeListener() {}, onchange: null };
  };
  w.fetch = () => Promise.resolve({ ok: true, status: 200,
    json: async () => ({ jobs: [], snippets: [], stats: {} }), text: async () => '' });
  w.scrollTo = () => {};
  w.localStorage.setItem('ahad_token', 'T');
  const st = d.createElement('style'); st.textContent = css; d.head.appendChild(st);
  const sc = d.createElement('script'); sc.textContent = js; d.body.appendChild(sc);
  d.dispatchEvent(new w.Event('DOMContentLoaded', { bubbles: true }));
  return { w, d };
}
const click = (w, el) =>
  el.dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
const wait = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  // ── 1. the dim veil ────────────────────────────────────────────────────
  console.log('[1] no dim veil over the desktop editor');
  {
    const { w, d } = boot(1280);
    await wait(600);
    if (typeof w.switchTab === 'function') { try { w.switchTab('jobs'); } catch (e) {} }
    await wait(200);
    const bd = d.querySelector('.rs-menu-backdrop');
    const mb = d.getElementById('wbMenuBtn');
    click(w, mb);
    await wait(200);
    const c = w.getComputedStyle(bd);
    ok('the scrim stays hidden on desktop with the rail open',
       c.display === 'none' || c.visibility === 'hidden',
       `display=${c.display} visibility=${c.visibility}`);
    ok('body did open the rail (so the check above is meaningful)',
       d.body.classList.contains('rs-side-open'), d.body.className);
  }
  // A phone still needs one: there the drawer really does cover the content.
  ok('a phone still gets a scrim',
     /@media \(max-width: 760px\)[\s\S]*?body\.rs-side-open \.rs-menu-backdrop[\s\S]{0,120}visibility:\s*visible/.test(css));

  // ── 2. the drawer toggle closes again ──────────────────────────────────
  console.log('\n[2] the menu button opens AND closes');
  for (const width of [1280, 390]) {
    const { w, d } = boot(width);
    await wait(600);
    if (typeof w.switchTab === 'function') { try { w.switchTab('jobs'); } catch (e) {} }
    await wait(200);
    const mb = d.getElementById('wbMenuBtn');
    click(w, mb); await wait(150);
    const opened = d.body.classList.contains('rs-side-open');
    click(w, mb); await wait(150);
    const closed = !d.body.classList.contains('rs-side-open');
    ok(`[${width}] first tap opens`, opened, d.body.className);
    ok(`[${width}] second tap closes`, closed, d.body.className);
    ok(`[${width}] aria-expanded follows`,
       mb.getAttribute('aria-expanded') === 'false', mb.getAttribute('aria-expanded'));
  }
  ok('the toggle no longer measures a transformed element',
     !/getBoundingClientRect\(\)\.width > 4/.test(js),
     'a translateX-hidden rail keeps its width, so measuring always says "open"');

  // ── 3. one entry point per job ─────────────────────────────────────────
  console.log('\n[3] no duplicate menu buttons');
  ok('the ⋯ menu has no second "Job list" row', !/id="btnJobsInMenu"/.test(html));
  ok('and no handler is left pointing at it',
     !/getElementById\("btnJobsInMenu"\)/.test(js));
  {
    const { w, d } = boot(1280);
    await wait(600);
    if (typeof w.switchTab === 'function') { try { w.switchTab('jobs'); } catch (e) {} }
    await wait(200);
    const head = d.querySelector('#tab-jobs .rs-head');
    const shown = el => {
      let n = el;
      while (n && n !== d.body) {
        const c = w.getComputedStyle(n);
        if (c.display === 'none' || c.visibility === 'hidden' || n.hasAttribute('hidden')) return false;
        n = n.parentElement;
      }
      return true;
    };
    // Icon-only square buttons are the ones that read as "menu buttons".
    const squares = [...head.querySelectorAll('button.rs-sq')].filter(shown);
    ok('the header shows at most two icon-square buttons',
       squares.length <= 2, squares.map(b => b.id).join(', '));
    // And each one must actually do something.
    for (const b of squares) {
      const before = d.body.className + '|' +
        (d.getElementById('rsMoreMenu') || {}).hidden;
      click(w, b); await wait(150);
      const after = d.body.className + '|' +
        (d.getElementById('rsMoreMenu') || {}).hidden;
      ok(`#${b.id} does something when clicked`, before !== after,
         'clicked and nothing changed');
      click(w, b); await wait(120);   // put it back
    }
  }

  // ── 4. dashboard jank ──────────────────────────────────────────────────
  console.log('\n[4] the dashboard does not repaint on every hover');
  for (const sel of ['.stat-card', '.quick-card', '.feat-card', '.feat']) {
    const rule = new RegExp('\\' + sel + '\\s*\\{([^}]*)\\}').exec(css);
    if (!rule) continue;
    const t = /transition:([^;]*);/.exec(rule[1]);
    ok(`${sel} does not tween box-shadow`,
       !t || !/box-shadow/.test(t[1]), t && t[1].trim().slice(0, 60));
  }
  ok('the cards still change shadow on hover (just not animated)',
     /\.stat-card:hover[^}]*box-shadow/.test(css));

  // ── 5. the sign-out row ────────────────────────────────────────────────
  console.log('\n[5] the sign-out row holds together');
  const duRule = /\.dash-user\s*\{([^}]*)\}/.exec(css);
  ok('.dash-user never wraps', duRule && /flex-wrap:\s*nowrap/.test(duRule[1]));
  const unRule = /\.user-name\s*\{([^}]*)\}/.exec(css);
  ok('a long username truncates instead of pushing',
     unRule && /text-overflow:\s*ellipsis/.test(unRule[1]) && /max-width/.test(unRule[1]));
  ok('the row does not claim to be clickable as a whole',
     duRule && !/cursor:\s*pointer/.test(duRule[1]),
     'the username looked pressable and was not');

  // ── 6. sideways drag ───────────────────────────────────────────────────
  console.log('\n[6] the page cannot be dragged sideways');
  const htmlRule = /(?:^|\n)html\s*\{([^}]*)\}/.exec(css);
  ok('overflow-x is clipped on <html>, not just <body>',
     htmlRule && /overflow-x:\s*hidden/.test(htmlRule[1]),
     'the viewport scroller is <html>; a body-only rule leaves it sliding');
  ok('and the horizontal gesture is not handed to the browser',
     htmlRule && /overscroll-behavior-x:\s*none/.test(htmlRule[1]));
  ok('<body> keeps its own guard too', /body\s*\{[^}]*overflow-x:\s*hidden/.test(css));

  console.log(`\ntest_reported_ui_bugs: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
