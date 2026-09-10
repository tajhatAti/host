/* Resolve CSS custom properties the way a browser would.
 *
 * jsdom's getComputedStyle returns "var(--ctl-h-sm)" verbatim, so any test
 * that reads a height and calls parseFloat gets NaN — and an assertion
 * against NaN is always false, which looks like a failure and tells you
 * nothing. This walks the cascade (element, ancestors, :root), honours
 * max-width media queries, and handles nested fallbacks like
 * var(--btn-h, var(--ctl-h)) with balanced-paren scanning: a lazy regex stops
 * at the first ")" and silently produces "40px)".
 */
const fs = require('fs');
const postcss = require('postcss');
const { JSDOM } = require('jsdom');
const ROOT = require('path').resolve(__dirname, '../../');

const css = fs.readFileSync(require('path').join(ROOT, 'static/app.css'), 'utf8');

/* Collect custom-property declarations per selector, honouring @media. */
const varsBySel = [];           // {sel, media, name, value}
postcss.parse(css).walkDecls(d => {
  if (!d.prop.startsWith('--')) return;
  const rule = d.parent;
  if (rule.type !== 'rule') return;
  let media = null;
  let p = rule.parent;
  while (p) { if (p.type === 'atrule' && p.name === 'media') { media = p.params; break; } p = p.parent; }
  rule.selectors.forEach(sel => varsBySel.push({ sel: sel.trim(), media, name: d.prop, value: d.value.trim() }));
});

function makeResolver(win, maxWidth) {
  /* Walk from the element up to :root, taking the first declaration of a
     token that applies (matching selector, and matching media). */
  function lookup(el, name) {
    let node = el;
    while (node) {
      let best = null;
      for (const v of varsBySel) {
        if (v.name !== name) continue;
        if (v.media) {
          const m = /max-width:\s*(\d+)px/.exec(v.media);
          if (!m) continue;
          if (maxWidth === undefined || maxWidth > +m[1]) continue;
        }
        try { if (!node.matches(v.sel)) continue; } catch (e) { continue; }
        best = v.value;            // later rules win at equal specificity
      }
      if (best !== null) return best;
      node = node.parentElement;
    }
    // :root fallbacks
    let best = null;
    for (const v of varsBySel) {
      if (v.name !== name) continue;
      if (v.sel !== ':root' && v.sel !== 'html') continue;
      if (v.media) {
        const m = /max-width:\s*(\d+)px/.exec(v.media);
        if (!m || maxWidth === undefined || maxWidth > +m[1]) continue;
      }
      best = v.value;
    }
    return best;
  }

  /* Balanced-paren scan. A lazy regex stops at the first ")", so a nested
     fallback like var(--btn-h, var(--ctl-h)) was captured as "var(--ctl-h"
     and left a stray ")" in the output — the measurement read "40px)".
     Getting this wrong makes the audit lie, which is worse than no audit. */
  function resolve(el, expr, depth = 0) {
    if (expr == null || depth > 12) return expr;
    const start = expr.indexOf('var(');
    if (start < 0) return expr.trim();
    let i = start + 4, level = 1;
    while (i < expr.length && level > 0) {
      if (expr[i] === '(') level++;
      else if (expr[i] === ')') level--;
      i++;
    }
    const inner = expr.slice(start + 4, i - 1);      // "--name, fallback"
    const comma = (() => {
      let lvl = 0;
      for (let j = 0; j < inner.length; j++) {
        if (inner[j] === '(') lvl++;
        else if (inner[j] === ')') lvl--;
        else if (inner[j] === ',' && lvl === 0) return j;
      }
      return -1;
    })();
    const name = (comma < 0 ? inner : inner.slice(0, comma)).trim();
    const fallback = comma < 0 ? '' : inner.slice(comma + 1).trim();
    const got = lookup(el, name);
    const replacement = (got !== null && got !== undefined) ? got : fallback;
    return resolve(el, expr.slice(0, start) + replacement + expr.slice(i), depth + 1);
  }
  return resolve;
}

module.exports = { makeResolver, css };
