/* CodeNest inside Telegram — the SAME app, not a second one.
 *
 * This file adds three things and touches nothing else:
 *   1. auto-login from Telegram's signed initData (no login screen, no tap)
 *   2. theme variables taken from the user's actual Telegram theme
 *   3. ready()/expand() so the webview opens at full height
 *
 * The RunSpace editor, job list, Details page and everything else are reused
 * exactly as they are. If this script decides it is NOT inside Telegram it
 * does nothing at all and the normal website flow runs untouched.
 */
(function () {
  "use strict";

  const TG = window.Telegram && window.Telegram.WebApp;

  /* TWO INDEPENDENT SIGNALS, because relying on the SDK alone is what broke.
   *
   * 1. TG.initData — authoritative when telegram-web-app.js has loaded.
   * 2. The URL Telegram itself appends: it adds #tgWebAppData=... (and
   *    tgWebAppPlatform / tgWebAppVersion) to the webview URL. That is
   *    present the instant the page starts parsing, with no third-party
   *    script involved.
   *
   * THE BUG: only signal 1 existed. telegram-web-app.js is fetched from
   * telegram.org, so when it is slow or blocked, __inTelegram was false, boot
   * fell through to routeFromUrl() on /dashboard — a protected route — and the
   * user got a Sign in / Create account screen INSIDE Telegram. Reproduced:
   *
   *     SDK loaded      -> {inTelegram:true}
   *     SDK not loaded  -> {inTelegram:false}   <- auth screen appears
   *
   * Signal 2 cannot fail that way, so a Telegram webview is now recognised
   * even when Telegram's own script never arrives.
   */
  function _hashInitData() {
    // Telegram puts the signed payload in the fragment. Read it directly so a
    // missing SDK cannot hide the fact that we are inside Telegram.
    try {
      const h = (window.location.hash || "").replace(/^#/, "");
      if (!h) return "";
      const p = new URLSearchParams(h);
      return p.get("tgWebAppData") || "";
    } catch (e) { return ""; }
  }

  const hashData = _hashInitData();
  const sdkData = (TG && typeof TG.initData === "string") ? TG.initData : "";

  /* TWO SOURCES, AND THEY CAN DISAGREE.
   *
   * The HMAC is over the exact bytes Telegram signed. TG.initData and the
   * URL's tgWebAppData are USUALLY the same string, but not always — some
   * clients hand the SDK a value that has been URL-decoded one extra time,
   * and a single differing byte makes the signature fail. Verified: the two
   * forms are not equal, and picking the wrong one is bad_hash even with a
   * perfectly correct bot token.
   *
   * Choosing one blindly is the bug. Both are sent, and the server accepts
   * whichever verifies — that cannot weaken anything, because a candidate is
   * only accepted if it carries a valid signature for our own bot token.
   */
  const initData = sdkData || hashData;
  const candidates = [];
  if (sdkData) candidates.push(sdkData);
  if (hashData && hashData !== sdkData) candidates.push(hashData);

  /* Presence of the SDK object alone is NOT enough: telegram-web-app.js
   * defines window.Telegram.WebApp on any page that loads it, including a
   * plain browser tab, where initData is an empty string. Treating that as
   * "inside Telegram" would hide the login screen from a normal visitor. */
  const inTelegram = initData.length > 0;
  window.__inTelegram = inTelegram;
  window.__tgInitData = initData;

  if (!inTelegram) {
    if (TG) {
      // The SDK loaded but there is no session — a browser preview of the
      // Mini App URL. Say nothing, let the website behave normally.
      try { TG.ready(); } catch (e) {}
    }
    return;
  }

  /* Mark the document immediately, BEFORE pro.js boots. Every auth screen is
   * then unreachable by CSS as well as by logic — belt and braces, because a
   * user inside Telegram must never see a login form no matter which code
   * path runs. */
  document.documentElement.classList.add("tg-no-auth");

  document.documentElement.classList.add("in-telegram");

  // From here on the SDK may legitimately be absent (blocked script) while we
  // are still genuinely inside Telegram. Guard every call.
  const has = (fn) => !!(TG && typeof TG[fn] === "function");

  /* ---- 2. product colour -------------------------------------------
   * Telegram themeParams are client chrome colours, not product colours.
   * Mapping a user's Telegram button/background colour onto --bg/--acc made
   * the entire app blue in some Android themes and triggered a full style
   * recalculation on every theme event. Keep the same neutral CodeNest
   * palette as the website and only tell Telegram's surrounding chrome which
   * solid colour to use. */
  const PRODUCT_BG = "#090909";
  const root = document.documentElement;
  root.setAttribute("data-theme", "dark");
  try {
    if (has("setHeaderColor")) TG.setHeaderColor(PRODUCT_BG);
    if (has("setBackgroundColor")) TG.setBackgroundColor(PRODUCT_BG);
    if (has("setBottomBarColor")) TG.setBottomBarColor(PRODUCT_BG);
  } catch (e) {}

  /* ---- 3. viewport --------------------------------------------------- */
  if (has("ready")) { try { TG.ready(); } catch (e) {} }
  if (has("expand")) { try { TG.expand(); } catch (e) {} }   // full height
  try {
    if (has("setHeaderColor") && TG.themeParams && TG.themeParams.bg_color) {
      TG.setHeaderColor(TG.themeParams.bg_color);
    }
  } catch (e) {}

  /* Telegram's viewport is not the window: the keyboard and the drag-to-close
   * gesture change it. Editors sized with 100vh overflow their container. */
  let viewportFrame = 0;
  let lastViewportHeight = 0;
  function commitViewport() {
    const h = TG && (TG.viewportStableHeight || TG.viewportHeight);
    if (h && Math.abs(h - lastViewportHeight) > 1) {
      lastViewportHeight = h;
      document.documentElement.style.setProperty("--tg-vh", h + "px");
    }
  }
  function syncViewport() {
    if (viewportFrame) return;
    viewportFrame = requestAnimationFrame(function () {
      viewportFrame = 0;
      commitViewport();
    });
  }
  commitViewport();
  if (has("onEvent")) { try { TG.onEvent("viewportChanged", syncViewport); } catch (e) {} }

  /* ---- 1. auto-login -------------------------------------------------
   * The functional core. Without it the Mini App is just the website in a
   * frame, and the user still has to sign in — which is the one thing a Mini
   * App is supposed to remove. */
  window.__tgAutoLogin = async function () {
    // An existing session wins: re-authenticating would spawn a second
    // session row on every open and log the device out elsewhere for nothing.
    if (localStorage.getItem("ahad_token")) return { ok: true, reused: true };
    let fp = "";
    try {
      fp = typeof ensureFingerprint === "function" ? await ensureFingerprint() : "";
    } catch (e) {}
    // Same-origin path, NOT the API constant.
    //
    // THE BUG: this read `API`, which pro.js declares with `const API = ""` on
    // its line 6. miniapp.js is loaded BEFORE pro.js (it has to be — pro.js's
    // boot reads the globals set here), so `API` did not exist yet and this
    // threw ReferenceError: API is not defined. The rejection landed in the
    // boot branch's .catch(), which showed "Couldn't connect" — an error that
    // looked like a network or server problem and was neither.
    //
    // `API` is the empty string anyway, so a leading "/" is the same request
    // with no cross-file dependency to get wrong.

    /* THE REQUEST HAD NO DEADLINE, AND ON A SLEEPING SERVER THAT IS THE BUG.
     *
     * Render's free plan stops an idle service and only starts it again on
     * the first request, which then takes 30-60s to answer. fetch() has no
     * default timeout, so this promise simply never settled: .then() never
     * ran, done() never ran, and the Mini App sat there. Reproduced against
     * the real boot with a 30s-delayed login — for the entire wait the phone
     * showed a dashboard skeleton reading "Hello, User" with no data and no
     * spinner, because index.html's 4-second splash safety net had already
     * fired. Nothing was broken; nothing said so either. That is exactly
     * "open the Mini App and nothing happens".
     *
     * A deadline plus ONE automatic retry fixes the common case outright: the
     * first request is what wakes the service, and by the time it is retried
     * the service is usually up. Only if that also fails does the user see
     * anything, and then it is a real message with a real button.
     *
     * AbortController rather than Promise.race: race leaves the original
     * request running and a second attempt would queue behind it on the same
     * connection, which is what made the retry pointless in testing.
     */
    const attempt = (timeoutMs) => {
      const ac = (typeof AbortController === "function") ? new AbortController() : null;
      const timer = ac ? setTimeout(() => { try { ac.abort(); } catch (e) {} }, timeoutMs) : null;
      return fetch("/auth/telegram/miniapp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ init_data: initData,
                               init_data_alt: candidates.slice(1),
                               fingerprint: fp }),
        signal: ac ? ac.signal : undefined,
      }).finally(() => { if (timer) clearTimeout(timer); });
    };

    let res;
    try {
      // 20s: long enough that a merely slow reply is not thrown away, short
      // enough that a phone is not left staring at nothing.
      res = await attempt(20000);
    } catch (e) {
      // Report progress BEFORE the retry — a wait the user can see is a wait
      // the user will sit through. pro.js paints this on the splash.
      try {
        if (typeof window.__tgBootNote === "function") {
          window.__tgBootNote("Waking the server… this takes up to a minute "
                              + "on the free tier.");
        }
      } catch (e2) {}
      try {
        // The second attempt gets longer: the first one paid the cold start.
        res = await attempt(45000);
      } catch (e3) {
        // A genuine transport failure — this is the ONLY case where "couldn't
        // connect" is the truth, so it is the only case that says it.
        const aborted = e3 && (e3.name === "AbortError");
        return {
          ok: false,
          status: 0,
          detail: aborted
            ? "The server did not answer in time. It may still be waking up — "
              + "tap Try again in a few seconds."
            : "",
        };
      }
    }
    if (!res.ok) {
      // Carry the server's own wording up to the caller. A single
      // "Couldn't connect" for every cause is unactionable: a missing
      // TELEGRAM_PING_BOT_TOKEN, a token belonging to a different bot, and a
      // stale session all looked identical on the phone, so there was nothing
      // to go on but guessing.
      let detail = "";
      try { detail = (await res.json()).detail || ""; } catch (e) {}
      return { ok: false, status: res.status, detail: detail };
    }
    const data = await res.json();
    localStorage.setItem("ahad_token", data.token);
    if (data.username) localStorage.setItem("ahad_user", data.username);
    if (typeof authToken !== "undefined") { try { authToken = data.token; } catch (e) {} }
    window.authToken = data.token;
    return { ok: true, created: !!data.created, username: data.username };
  };

  /* Inside Telegram the account IS the Telegram account. A sign-out button
   * would drop the session and then the very next open would silently sign
   * the same person back in — a control that visibly does nothing. Hidden by
   * CSS rather than removed, so nothing that queries for it breaks. */
  document.documentElement.classList.add("tg-hide-signout");
})();
