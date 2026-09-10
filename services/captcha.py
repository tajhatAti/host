"""CAPTCHA verification for the signup form (master prompt §5).

Supports Cloudflare Turnstile and hCaptcha; both expose the same
"POST siteverify with {secret, response, remoteip}" contract.

Provider is chosen by which secret is configured:

    TURNSTILE_SECRET_KEY   -> Cloudflare Turnstile
    HCAPTCHA_SECRET_KEY    -> hCaptcha
    (neither)              -> provider disabled, arithmetic fallback is used

The arithmetic question ("7 + 5") is NOT a real bot defense — it exists so a
deployment without provider keys still has a trivial speed bump, and so local
development needs no external service. Configure a real provider in production.
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger("codenest.captcha")

TURNSTILE_VERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
HCAPTCHA_VERIFY = "https://api.hcaptcha.com/siteverify"

# Answer to the built-in fallback question rendered in index.html.
MATH_ANSWER = os.getenv("SIGNUP_MATH_ANSWER", "12").strip()


def provider() -> str:
    """Which CAPTCHA provider is active: 'turnstile', 'hcaptcha' or 'none'."""
    if os.getenv("TURNSTILE_SECRET_KEY", "").strip():
        return "turnstile"
    if os.getenv("HCAPTCHA_SECRET_KEY", "").strip():
        return "hcaptcha"
    return "none"


def site_key() -> str:
    """Public site key for the active provider (safe to expose to the browser)."""
    p = provider()
    if p == "turnstile":
        return os.getenv("TURNSTILE_SITE_KEY", "").strip()
    if p == "hcaptcha":
        return os.getenv("HCAPTCHA_SITE_KEY", "").strip()
    return ""


def _verify_remote(url: str, secret: str, token: str, ip: str) -> bool:
    try:
        r = requests.post(
            url,
            data={"secret": secret, "response": token, "remoteip": ip},
            timeout=8,
        )
        ok = bool(r.json().get("success"))
        if not ok:
            logger.info("CAPTCHA rejected: %s", r.json().get("error-codes"))
        return ok
    except Exception as exc:  # noqa: BLE001
        # Fail CLOSED: a provider outage must not become an open signup window.
        logger.warning("CAPTCHA provider unreachable (%s) — rejecting", exc)
        return False


def verify(token: str | None, math_answer: str | None, ip: str = "") -> bool:
    """Validate a signup CAPTCHA. Returns True when the challenge passed."""
    p = provider()
    if p == "turnstile":
        return _verify_remote(
            TURNSTILE_VERIFY, os.getenv("TURNSTILE_SECRET_KEY", "").strip(),
            (token or "").strip(), ip)
    if p == "hcaptcha":
        return _verify_remote(
            HCAPTCHA_VERIFY, os.getenv("HCAPTCHA_SECRET_KEY", "").strip(),
            (token or "").strip(), ip)
    # No provider configured -> arithmetic fallback.
    return (math_answer or "").strip() == MATH_ANSWER
