/* Every icon in the shell must actually be able to paint.
 *
 * REPORTED: "File Upload Icon নেই কেনো?" — the Upload row in Code Studio's
 * "···" menu showed a label with no icon.
 *
 * TWO CAUSES, both mine, and both silent:
 *
 *   1. viewBox="0 0 24"
 *      A viewBox needs FOUR numbers: min-x min-y width height. With three
 *      the attribute is in error and the viewport resolves to 0x0, so the
 *      <svg> occupies its layout box and paints nothing. Confirmed by
 *      parsing: "0 0 24" gives baseVal 0x0, "0 0 24 24" gives 24x24.
 *      14 icons across Code Studio and RunSpace were written this way, so
 *      the whole toolbar was blank, not just Upload.
 *
 *   2. <use href="#i-wand"> / <use href="#i-term">
 *      referenced symbols that were never defined. A <use> pointing at a
 *      missing id renders nothing and throws no error.
 *
 * Neither shows up in a console, in a network log, or in any layout check —
 * the element is present and correctly sized. Only inspecting the attribute
 * and resolving the reference catches them, which is what this does.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const R = path.resolve(__dirname, '../../');
const html = fs.readFileSync(path.join(R, 'index.html'), 'utf8');
const dom = new JSDOM(html);
const d = dom.window.document;

let pass = 0, fail = 0;
function ok(name, cond, extra) {
  if (cond) pass++;
  else { fail++; console.log(`  FAIL ${name}${extra ? ' -> ' + extra : ''}`); }
}

// ── 1. every viewBox is well formed ────────────────────────────────────
console.log('[1] viewBox attributes');
const svgs = [...d.querySelectorAll('svg[viewBox], symbol[viewBox]')];
ok('the shell contains icons at all', svgs.length > 20, String(svgs.length));

const malformed = svgs
  .map(el => [el, (el.getAttribute('viewBox') || '').trim().split(/[\s,]+/)])
  .filter(([, parts]) => parts.length !== 4 || parts.some(n => Number.isNaN(Number(n))))
  .map(([el]) => `${el.tagName}#${el.id || el.getAttribute('class') || '?'}="${el.getAttribute('viewBox')}"`);
ok('every viewBox has four numeric values', malformed.length === 0,
   `${malformed.length}: ${malformed.slice(0, 6).join(' | ')}`);

const zeroSized = svgs
  .map(el => [el, (el.getAttribute('viewBox') || '').trim().split(/[\s,]+/)])
  .filter(([, p]) => p.length === 4 && (Number(p[2]) <= 0 || Number(p[3]) <= 0))
  .map(([el]) => el.id || el.getAttribute('class'));
ok('no viewBox has zero width or height', zeroSized.length === 0, zeroSized.join(','));

// ── 2. every <use> resolves ────────────────────────────────────────────
console.log('\n[2] symbol references');
const defined = new Set([...d.querySelectorAll('symbol[id]')].map(e => e.id));
const used = [...new Set([...html.matchAll(/href="#(i-[a-z0-9-]+)"/g)].map(m => m[1]))];
ok('the sprite defines symbols', defined.size > 0, String(defined.size));
ok('the shell references symbols', used.length > 0, String(used.length));
const missing = used.filter(u => !defined.has(u));
ok('every referenced symbol exists', missing.length === 0, missing.join(', '));

// A symbol with no drawable content is the same blank box.
const emptySymbols = [...d.querySelectorAll('symbol[id]')]
  .filter(sym => !sym.querySelector('path, rect, circle, line, polyline, polygon, ellipse'))
  .map(s => s.id);
ok('no symbol is empty', emptySymbols.length === 0, emptySymbols.join(','));

// ── 3. the reported control specifically ───────────────────────────────
console.log('\n[3] the Upload controls that were reported');
for (const id of ['btnUploadFile', 'btnUploadFileEmpty']) {
  const btn = d.getElementById(id);
  ok(`#${id} exists`, !!btn);
  if (!btn) continue;
  const svg = btn.querySelector('svg');
  ok(`#${id} contains an svg`, !!svg);
  if (!svg) continue;
  const parts = (svg.getAttribute('viewBox') || '').trim().split(/[\s,]+/);
  ok(`#${id} icon has a valid viewBox`, parts.length === 4,
     svg.getAttribute('viewBox'));
  const drawn = svg.querySelector('path, rect, circle, line, polyline, use');
  ok(`#${id} icon has something to draw`, !!drawn);
  // An inline stroke icon with no stroke colour is invisible on any surface.
  const usesSprite = !!svg.querySelector('use');
  if (!usesSprite) {
    const stroke = svg.getAttribute('stroke') || '';
    const fill = svg.getAttribute('fill') || '';
    ok(`#${id} icon declares a visible stroke or fill`,
       stroke === 'currentColor' || (fill && fill !== 'none'),
       `stroke=${stroke} fill=${fill}`);
  }
}

// ── 4. no icon-bearing button ends up label-less AND icon-less ─────────
console.log('\n[4] every menu row shows something');
for (const sel of ['.cs-menu-item', '.rs-menu-item']) {
  for (const el of d.querySelectorAll(sel)) {
    const label = (el.textContent || '').trim();
    const svg = el.querySelector('svg');
    /* A row may be text-only on purpose -- the Files row had its icon
       removed by request. What must never happen is a BROKEN icon: an svg
       that is present but cannot paint. So only rows that carry an svg are
       checked, and every row must still show something. */
    if (svg) {
      const iconOk = (svg.getAttribute('viewBox') || '').trim().split(/[\s,]+/).length === 4;
      ok(`${sel} "${label.slice(0, 18) || el.id}" icon is usable`, iconOk,
         svg.getAttribute('viewBox'));
    } else {
      ok(`${sel} "${label.slice(0, 18) || el.id}" has a label instead`, !!label, el.id);
    }
  }
}

console.log(`\ntest_icons_render: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
