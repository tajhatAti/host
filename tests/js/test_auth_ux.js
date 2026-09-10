/* SIGN-IN / SIGN-UP UX.
 *
 * Two problems:
 *  1. Copy that reads as machine-written filler — "Telegram sign-in is not
 *     configured on this deployment yet" (an internal deployment detail),
 *     "you can switch apps to check your mail safely", a terms line that
 *     recited the whole acceptable-use policy.
 *  2. Wrong next step. Entering an already-registered e-mail offered
 *     "Reset password" — but the user has not forgotten anything; they simply
 *     already have an account. The correct action is SIGN IN.
 *  3. CAPTCHA removed: a "what is 7+5" box stops no real abuse and taxes
 *     every genuine signup.
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");
const ROOT = path.join(__dirname, "..", "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const js = fs.readFileSync(path.join(ROOT, "static", "pro.js"), "utf8");
const authPy = fs.readFileSync(path.join(ROOT, "routes", "auth.py"), "utf8");
const d = new JSDOM(html).window.document;

const results = [];
const check = (n, c, x) => {
  results.push([n, !!c]);
  console.log((c ? "\u2713 " : "\u2717 FAIL ") + n.padEnd(56) + (c ? "" : " \u2014 " + (x || "")));
};

// ---- CAPTCHA fully gone -------------------------------------------------
check("captcha input removed from markup", !d.getElementById("su_captcha"));
check("captcha box removed", !d.querySelector(".captcha-box"));
check("no captcha logic left in the frontend", !/captcha/i.test(js));
check("backend no longer rejects on captcha", !/captcha_service\.verify/.test(authPy));
check("signup form is just the essentials",
  [...d.querySelectorAll("#formSignup input")].map(i => i.id).join(",")
    === "su_username,su_email,su_password,su_terms");

// ---- filler copy gone ---------------------------------------------------
// This USED to assert telegramUnavailable was deleted. It was deleted as
// filler in c12f41b — but pro.js never stopped calling show("telegramUnavailable"),
// so on the failure path the sign-in card rendered a hint sentence with no
// button and no explanation, and a signed-out user could not get back in.
// The element is back, and it must NOT be filler: it has to name the way
// forward rather than describe the deployment.
const _tgu = d.getElementById("telegramUnavailable");
check("the fallback notice exists", !!_tgu);
check("it is not deployment trivia",
  _tgu && !/not configured|deployment/i.test(_tgu.textContent),
  _tgu && _tgu.textContent.trim());
check("it tells the user what to do instead",
  _tgu && /email/i.test(_tgu.textContent), _tgu && _tgu.textContent.trim());
check("and it starts hidden", _tgu && _tgu.hasAttribute("hidden"));
check("'not configured on this deployment' gone", !/not configured on this deployment/i.test(html));
check("'switch apps' reassurance gone", !/switch apps/i.test(js));
check("terms line no longer recites the policy",
  !/no illegal content, no crypto-mining/i.test(html));
check("terms agreement still present", !!d.getElementById("su_terms"));
const tgHints = [...d.querySelectorAll(".telegram-hint")].map(e => e.textContent.trim());
check("telegram hint is one short line",
  tgHints.every(t => t.length <= 40), tgHints.join(" | "));

// ---- the actual logic fix ----------------------------------------------
check("registered e-mail offers SIGN IN, not reset",
  /This email already has an account[\s\S]{0,120}Sign in instead/.test(js));
check("reset-password is no longer the duplicate-email action",
  !/already registered\. <a onclick="showScreen\(\\'screen-forgot1/.test(js));
check("sign-in is pre-filled so the address is not retyped",
  /function _goSignIn\(prefill\)[\s\S]{0,220}u\.value = prefill/.test(js));
check("taken username gets its own, different message",
  /That username is taken/.test(js));
check("failed sign-in offers creating an account",
  /_authNote\("si_username", err\.message, "Create an account/.test(js));
check("sign-up is pre-filled from sign-in", /function _goSignUp\(prefill\)/.test(js));
check("e-mail enumeration protection respected (server wording kept)",
  /server deliberately does NOT say whether the account exists/.test(js));

// ---- OTP screen ---------------------------------------------------------
check("OTP note is short", (d.getElementById("otpEmailNote") || {}).textContent === "Check your inbox");
check("OTP screen still has 6 boxes",
  d.querySelectorAll("#otpBoxesSignup input").length === 6);
check("resend still available", !!d.getElementById("resendLink"));

// ---- nothing structural lost -------------------------------------------
for (const id of ["screen-signup", "screen-signin", "screen-otp",
                  "screen-forgot1", "screen-forgot2", "screen-forgot3"]) {
  check(`screen intact: ${id}`, !!d.getElementById(id));
}

const p = results.filter(r => r[1]).length, f = results.length - p;
console.log(`\n================ ${p} pass, ${f} fail ================`);
process.exit(f ? 1 : 0);
