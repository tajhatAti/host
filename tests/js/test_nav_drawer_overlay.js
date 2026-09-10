/* The mobile drawer (three-line button) must be tappable above its scrim.
 *
 * ROOT CAUSE: .dash-bar is sticky with z-index: var(--z-sticky) (700), which
 * creates a stacking context. The drawer lives INSIDE .dash-bar, so its own
 * z-index (--z-nav-drawer, 940) cannot escape the header's 700 context. The
 * scrim (#sideOverlay) sits at --z-scrim-nav (930) outside that context, so
 * it painted over the drawer and swallowed every tap on Overview / Bots /
 * Store / Profile / Admin.
 *
 * FIX: opening the drawer also sets body.nav-drawer-open, and in that state
 * the header itself moves up to the drawer layer, so the drawer is truly
 * above its scrim. */
const fs = require('fs');
const js = fs.readFileSync('static/pro.js', 'utf8');
const css = fs.readFileSync('static/app.css', 'utf8');

let pass = 0;
function ok(name, cond) {
  if (!cond) throw new Error('FAIL: ' + name);
  pass += 1;
}

// JS: open/close the drawer synchronously toggles the body class.
ok('openSideMenu adds nav-drawer-open', /function openSideMenu\(\)[\s\S]*body\.classList\.add\("nav-drawer-open"\)/.test(js));
ok('closeSideMenu removes nav-drawer-open', /function closeSideMenu\(\)[\s\S]*body\.classList\.remove\("nav-drawer-open"\)/.test(js));

// CSS: while the drawer is open, the header is lifted above the scrim.
ok('header lifts while drawer is open',
   /body\.nav-drawer-open \.dash-bar\s*\{\s*z-index:\s*var\(--z-nav-drawer\)\s*;?\s*\}/.test(css));

// The fix lives under the mobile media query where the drawer actually exists.
const mobileStart = css.search(/@media \(max-width:\s*760px\)\s*\{/);
const fixAt = css.search(/body\.nav-drawer-open \.dash-bar/);
ok('the fix is inside the mobile media query', fixAt > -1 && (mobileStart < fixAt));

console.log(`test_nav_drawer_overlay: ${pass} passed`);
