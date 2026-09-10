/* Landing page / sign-out regressions.
 *   1. Paired buttons rendered at different heights: .btn-primary had
 *      `border: none` while .btn-ghost added 1px, and size came from padding
 *      alone, so ghost buttons were 2px taller than the primary next to them.
 *   2. Sign-out was an instant jump-cut AND left dashboard state behind
 *      (RunSpace body classes, job polling, the log stream).
 *   3. Dead vault-era assets were still shipped in /static.
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "static", "pro.js"), "utf8");
const css = fs.readFileSync(path.join(ROOT, "static", 'app.css'), "utf8");
const d = new JSDOM(html).window.document;

const results = [];
const check = (n, c, x) => {
  results.push([n, !!c]);
  console.log((c ? "\u2713 " : "\u2717 FAIL ") + n.padEnd(58) + (c ? "" : " \u2014 " + (x || "")));
};

// ---- 1. button sizing --------------------------------------------------
const base = css.match(/\.btn-primary, \.btn-secondary, \.btn-ghost, \.btn-danger \{[\s\S]*?\}/);
check("all button variants share one base rule", !!base);
check("base uses a transparent border (not `border: none`)",
  base && /border:\s*1px solid transparent/.test(base[0]),
  "ghost buttons were 2px taller than primary");
check("base is border-box", base && /box-sizing:\s*border-box/.test(base[0]));
check("base sets an explicit height", base && /height:\s*var\(--btn-h/.test(base[0]));
check("no `border: none` left on the base", base && !/border:\s*none/.test(base[0]));
check("lg/sm resize via the token, not padding hacks",
  /\.btn-primary\.lg[^{]*\{[^}]*--btn-h/.test(css) && /\.btn-primary\.sm[^{]*\{[^}]*--btn-h/.test(css));
check("nav pair sized together",
  /\.nav-cta \.btn-primary,\s*\n\.nav-cta \.btn-ghost \{[^}]*--btn-h/.test(css));
check("hero pair sized together",
  /\.hero-actions \.btn-primary,\s*\n\.hero-actions \.btn-ghost \{[^}]*--btn-h/.test(css));
check("hero CTAs go full-width when stacked",
  /@media \(max-width: 560px\)[\s\S]{0,400}?\.hero-actions \.btn-ghost \{ width: 100%/.test(css));

// every landing button pairs primary+ghost in the same container
for (const sel of [".nav-cta", ".hero-actions"]) {
  const box = d.querySelector(sel);
  check(`${sel} exists`, !!box);
  if (box) {
    const btns = [...box.querySelectorAll("button")];
    check(`${sel} holds exactly 2 buttons`, btns.length === 2, String(btns.length));
    const sizes = btns.map(b => (b.className.match(/\b(lg|sm)\b/) || ["base"])[0]);
    check(`${sel} buttons use the same size class`, new Set(sizes).size === 1, sizes.join("/"));
  }
}

// ---- 2. sign-out -------------------------------------------------------
check("sign-out stops the log stream", /stopLogStream\(\);[\s\S]{0,120}stopJobPolling\(\)/.test(js));
check("sign-out closes the Details page", /if \(typeof _jdOpen !== "undefined" && _jdOpen\) closeJobDetails/.test(js));
check("sign-out clears leftover body state",
  /classList\.remove\(\s*\n?\s*"rs-active", "rs-detail-open", "rs-drawer-open"/.test(js));
check("sign-out clears the cached user", /removeItem\("ahad_user"\)/.test(js));
check("sign-out resets the URL", /history\.replaceState\(\{\}, "", "\/"\)/.test(js));
check("sign-out animates out then in",
  /classList\.add\("signing-out"\)/.test(js) && /classList\.add\("signed-out-in"\)/.test(js));
check("fade-out styled", /body\.signing-out \.dashboard \{[^}]*opacity:\s*0/.test(css));
check("fade-in styled", /body\.signed-out-in \.hero \{[^}]*animation/.test(css));
check("motion preference respected",
  /@media \(prefers-reduced-motion: reduce\)[\s\S]{0,220}?body\.signed-out-in/.test(css));

// ---- 3. dead assets ----------------------------------------------------
for (const f of ["script.js", "style.css", "enhanced.css", "theme.js"]) {
  check(`removed dead asset: ${f}`, !fs.existsSync(path.join(ROOT, "static", f)));
  check(`nothing references ${f}`, !html.includes("/static/" + f));
}
check("no vault code left in the frontend", !/loadVault|saveVault|vault-item/i.test(js));
check("no bcrypt jargon on the landing page", !/bcrypt/i.test(html));

// ---- 4. minimal type scale --------------------------------------------
check("hero title scales fluidly", /\.hero-title \{[^}]*clamp\(/.test(css));
check("section headings scale fluidly", /\.section-head h2 \{[^}]*clamp\(/.test(css));
check("sections share one vertical rhythm", /\.section \{ padding-block: clamp\(/.test(css));

const p = results.filter(r => r[1]).length, f = results.length - p;
console.log(`\n================ ${p} pass, ${f} fail ================`);
process.exit(f ? 1 : 0);
