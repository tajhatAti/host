"""services/store.py — the Bot Store.

Bots.Business sells a Store of ready-made bots whose logic is written in BJS,
their own JavaScript dialect: you learn `Bot.sendMessage`, `User.setProperty`,
`Libs.…` and you cannot use the language you already know.

This is the same product idea with the opposite language decision. Every
listing here is ONE complete, ordinary Python file — the kind of file you
would have written yourself, using real libraries (`python-telegram-bot`,
`aiogram`, `httpx`, `sqlite3`), no custom syntax and no platform runtime to
learn. You read the listing, you deploy it, you get the whole source in the
editor and you keep editing it as plain Python.

Two kinds of listing live in one catalog:

  * `built-in`  — the curated complete products. They are mirrored from
    `services/bot_templates` on boot so installs, ratings and favourites
    attach to them exactly like any other listing, while the code itself
    stays under version control.
  * `community` — a Python file a user submitted. It is validated on the way
    in (compiles, reads `BOT_TOKEN` from the environment, embeds no bot
    token) and stays `pending` until an owner approves it.

Everything here is portable SQL: the same code runs on SQLite locally and on
PostgreSQL in production, so no `INSERT OR REPLACE`, no `IFNULL`, no
`COLLATE NOCASE` and no `datetime('now')`.
"""
from __future__ import annotations

import hashlib
import json
import re

from services import bot_templates
from services import telegram_detector

# ---------------------------------------------------------------------------
# Catalog shape
# ---------------------------------------------------------------------------

# The seven complete products keep the categories from the product guide. The
# extra ones exist so community submissions have a home without inventing a
# category per listing.
CATEGORIES = [
    "Community", "Channels", "Rewards", "Commerce", "Files",
    "Media & AI", "AI & Support", "Utilities", "Tools",
]

DIFFICULTIES = ("Beginner", "Intermediate", "Advanced")

MAX_CODE_BYTES = 400_000          # a "complete bot" file is far smaller than this
MAX_TITLE = 80
MAX_SUMMARY = 200
MAX_DESCRIPTION = 4_000
MAX_TAGS = 12
PREVIEW_LINES = 40                # what an anonymous visitor may read

_SORTS = {
    "popular": "featured DESC, install_count DESC, rating_count DESC, id DESC",
    "rating": "featured DESC, (rating_sum * 1.0 / NULLIF(rating_count, 0)) DESC, install_count DESC, id DESC",
    "newest": "created_at DESC, id DESC",
    "name": "LOWER(title) ASC, id ASC",
}

# Per-product store metadata: what the card advertises and what the detail
# page lists as features. Scope text mirrors BOT_TEMPLATE_GUIDE.md so the
# listing cannot drift from the product it sells.
BUILTIN_META = {
    "complete-group-manager": {
        "difficulty": "Intermediate",
        "tags": ["moderation", "captcha", "anti-spam", "warnings", "group", "rose"],
        "features": [
            "Join captcha with timed kick",
            "Anti-flood limits per user",
            "Link guard and blocked words",
            "Rules, warnings and timed mute",
            "Ban / unban / lock / unlock",
            "User reports to the owner",
            "Group statistics and audit history",
        ],
    },
    "complete-channel-manager": {
        "difficulty": "Intermediate",
        "tags": ["channel", "force-join", "scheduler", "forwarding", "captions"],
        "features": [
            "Force-join membership gate",
            "Member approval with private invite links",
            "Scheduled posts with auto-delete",
            "Broadcasts to every member",
            "Forward / copy content into the channel",
            "Hashtag remover and caption editor",
            "Inline buttons on channel posts",
        ],
    },
    "complete-referral-rewards": {
        "difficulty": "Intermediate",
        "tags": ["referral", "invite", "points", "leaderboard", "withdrawal"],
        "features": [
            "Personal invite links",
            "Referral tracking with join verification",
            "Points balance per user",
            "Top-10 leaderboard",
            "Withdrawal requests",
            "Owner payout approvals",
            "Rate and minimum settings",
        ],
    },
    "complete-commerce": {
        "difficulty": "Advanced",
        "tags": ["store", "cart", "checkout", "orders", "payment", "bkash"],
        "features": [
            "Product catalog with stock",
            "Cart and checkout flow",
            "bKash / Nagad / SSLCommerz reference review",
            "Order history per buyer",
            "Buyer status notifications",
            "Support hand-off",
            "Sales analytics for the owner",
        ],
    },
    "complete-file-share": {
        "difficulty": "Beginner",
        "tags": ["files", "deep-link", "storage", "expiry", "download-limit"],
        "features": [
            "Telegram deep-link file sharing",
            "Expiry dates per link",
            "Download limits per link",
            "Per-user link settings",
            "Revoke and delete",
            "Owner statistics",
        ],
    },
    "complete-media-ai-converter": {
        "difficulty": "Advanced",
        "tags": ["media", "pdf", "ocr", "voice", "tts", "qrcode", "convert"],
        "features": [
            "Image compression",
            "JPG / PNG / WebP / PDF conversion",
            "Image to PDF",
            "PDF text extraction",
            "OCR via OCR.Space",
            "Voice transcription and text-to-speech",
            "QR code generation",
        ],
    },
    "complete-ai-support": {
        "difficulty": "Intermediate",
        "tags": ["ai", "support", "openai", "bangla", "memory", "quota"],
        "features": [
            "OpenAI-compatible provider",
            "Bangla / Banglish support policy",
            "Per-user conversation memory",
            "Owner-editable system prompt",
            "Daily quota and bans",
            "Usage analytics",
            "Broadcast to users",
        ],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(text: str, fallback: str = "bot") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return slug[:60].strip("-") or fallback


def _code_hash(code: str) -> str:
    return hashlib.sha256(str(code or "").encode("utf-8")).hexdigest()[:16]


def _tags_list(raw) -> list:
    if isinstance(raw, (list, tuple)):
        out = [str(t).strip().lower() for t in raw if str(t).strip()]
    else:
        out = [t.strip().lower() for t in str(raw or "").split(",") if t.strip()]
    seen, ordered = set(), []
    for tag in out:
        if tag not in seen:
            seen.add(tag)
            ordered.append(tag)
    return ordered[:MAX_TAGS]


def _json_loads(raw, default):
    try:
        value = json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def _requirements(code: str) -> list:
    """The `# requirements:` line the runner already understands."""
    match = re.search(r"(?m)^#\s*requirements:\s*(.+)$", str(code or ""))
    if not match:
        return []
    return [part.strip() for part in re.split(r"[,\s]+", match.group(1).strip()) if part.strip()]


# ---------------------------------------------------------------------------
# Validation — the gate every community submission passes through
# ---------------------------------------------------------------------------


def check_code(code: str) -> dict:
    """Validate one complete Python bot file.

    Returns `{"ok", "errors", "warnings", "lines", "bytes"}`. Errors block the
    submission; warnings are shown to the reviewer.
    """
    source = str(code or "")
    errors, warnings = [], []
    size = len(source.encode("utf-8"))

    if not source.strip():
        errors.append("The code is empty.")
    if size > MAX_CODE_BYTES:
        errors.append(f"The file is too large ({size} bytes, max {MAX_CODE_BYTES}).")

    if source.strip():
        try:
            compile(source, "<store-submission>", "exec")
        except SyntaxError as exc:
            errors.append(f"Python syntax error on line {exc.lineno}: {exc.msg}")

    analysis = telegram_detector.analyze_code(source, "python")
    if analysis["token_source"] == "hardcoded":
        errors.append(
            "A live-looking bot token is embedded in the code. "
            "Read it from the environment instead: os.getenv(\"BOT_TOKEN\")."
        )
    elif analysis["token_source"] == "not_found":
        errors.append(
            "The bot token must come from the environment: "
            "token = os.getenv(\"BOT_TOKEN\")."
        )
    elif analysis["token_source"] == "example_or_literal":
        warnings.append("The token is assigned from a literal. Prefer os.getenv(\"BOT_TOKEN\").")

    if not analysis["telegram_detected"]:
        warnings.append("No Telegram code detected — the listing may not be a bot.")
    if analysis["update_mode"] == "unknown":
        warnings.append("No polling or webhook loop detected; the job may exit immediately.")

    for pattern, label in (
        (r"(?im)^\s*(?:api[_-]?key|secret|password|token)\s*=\s*[\"'][A-Za-z0-9_\-]{16,}[\"']",
         "a long credential-looking literal"),
        (r"(?i)rm\s+-rf\s+/", "a destructive shell command"),
    ):
        if re.search(pattern, source):
            warnings.append(f"The code contains {label}; a reviewer will look at it closely.")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "lines": source.count("\n") + (1 if source.strip() else 0),
        "bytes": size,
        "requirements": _requirements(source),
        "framework": analysis["framework"],
        "update_mode": analysis["update_mode"],
    }


# ---------------------------------------------------------------------------
# Built-in catalog mirror
# ---------------------------------------------------------------------------


def _builtin_rows(now: str) -> list:
    rows = []
    for template_id, value in bot_templates.TEMPLATES.items():
        meta = BUILTIN_META.get(template_id, {})
        code = value["code"]
        rows.append({
            "slug": template_id,
            "source": "built-in",
            "builtin_id": template_id,
            "title": value["name"],
            "summary": value["description"],
            "description": value["description"],
            "category": value["category"],
            "tags": ",".join(_tags_list(meta.get("tags", []))),
            "language": value["language"],
            "framework": value.get("framework", ""),
            "difficulty": meta.get("difficulty", "Intermediate"),
            "features": "\n".join(meta.get("features", [])),
            "setup_notes": value.get("after_deploy", ""),
            "env_fields": json.dumps(value.get("env_fields") or []),
            "code": code,
            "code_hash": _code_hash(code),
            "version": "1.0.0",
            "status": "published",
            "author_name": "CodeNest",
            "created_at": now,
            "updated_at": now,
            "published_at": now,
        })
    return rows


def sync_builtins(conn, now: str) -> int:
    """Mirror the curated products into `store_items` (idempotent).

    Install counts, ratings and favourites are preserved: an existing row only
    ever has its content refreshed, never its statistics reset.
    """
    written = 0
    for row in _builtin_rows(now):
        existing = conn.execute(
            "SELECT id, code_hash, version FROM store_items WHERE slug = ?",
            (row["slug"],),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO store_items (slug, source, builtin_id, title, summary, description,"
                " category, tags, language, framework, difficulty, features, setup_notes,"
                " env_fields, code, code_hash, version, status, author_name,"
                " created_at, updated_at, published_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["slug"], row["source"], row["builtin_id"], row["title"], row["summary"],
                 row["description"], row["category"], row["tags"], row["language"],
                 row["framework"], row["difficulty"], row["features"], row["setup_notes"],
                 row["env_fields"], row["code"], row["code_hash"], row["version"],
                 row["status"], row["author_name"], row["created_at"], row["updated_at"],
                 row["published_at"]),
            )
            written += 1
        elif existing["code_hash"] != row["code_hash"]:
            # Content changed upstream: refresh it, keep the statistics.
            conn.execute(
                "UPDATE store_items SET source = ?, builtin_id = ?, title = ?, summary = ?,"
                " description = ?, category = ?, tags = ?, language = ?, framework = ?,"
                " difficulty = ?, features = ?, setup_notes = ?, env_fields = ?, code = ?,"
                " code_hash = ?, status = 'published', updated_at = ?,"
                " published_at = COALESCE(published_at, ?) WHERE id = ?",
                (row["source"], row["builtin_id"], row["title"], row["summary"],
                 row["description"], row["category"], row["tags"], row["language"],
                 row["framework"], row["difficulty"], row["features"], row["setup_notes"],
                 row["env_fields"], row["code"], row["code_hash"], now, now, existing["id"]),
            )
            written += 1
    conn.commit()
    return written


# ---------------------------------------------------------------------------
# Read paths
# ---------------------------------------------------------------------------


def _public_item(row, include_code: bool = False, viewer: dict | None = None) -> dict:
    code = row["code"] or ""
    rating_count = row["rating_count"] or 0
    rating_sum = row["rating_sum"] or 0
    item = {
        "slug": row["slug"],
        "source": row["source"],
        "title": row["title"],
        "summary": row["summary"],
        "category": row["category"],
        "tags": _tags_list(row["tags"]),
        "language": row["language"],
        "framework": row["framework"],
        "difficulty": row["difficulty"],
        "features": [line for line in str(row["features"] or "").split("\n") if line.strip()],
        "setup_notes": row["setup_notes"],
        "env_fields": _json_loads(row["env_fields"], []),
        "requirements": _requirements(code),
        "version": row["version"],
        "author": row["author_name"],
        "author_id": row["author_user_id"],
        "featured": bool(row["featured"]),
        "install_count": row["install_count"] or 0,
        "rating_count": rating_count,
        "rating": round(rating_sum / rating_count, 2) if rating_count else 0,
        "code_lines": code.count("\n") + (1 if code.strip() else 0),
        "code_bytes": len(code.encode("utf-8")),
        "status": row["status"],
        "created_at": row["created_at"],
        "published_at": row["published_at"],
    }
    if include_code:
        item["code"] = code
        item["after_deploy"] = row["setup_notes"]
    else:
        # Anonymous browsing shows the shape of the file, not all of it: the
        # listing is a shop window, the deploy hands over the whole source.
        lines = code.split("\n")
        item["code_preview"] = "\n".join(lines[:PREVIEW_LINES])
        item["code_full"] = False
    return item


def catalog(conn, query: str = "", category: str = "", sort: str = "popular",
            source: str = "", limit: int = 24, offset: int = 0,
            statuses: tuple = ("published",)) -> dict:
    """Search + filter the published catalog. Returns page + facets."""
    where = ["status IN (" + ",".join("?" for _ in statuses) + ")"]
    params: list = list(statuses)

    if category and category.lower() not in ("all", ""):
        where.append("category = ?")
        params.append(category)
    if source in ("built-in", "community"):
        where.append("source = ?")
        params.append(source)

    term = (query or "").strip().lower()
    if term:
        like = "%" + term + "%"
        where.append("(LOWER(title) LIKE ? OR LOWER(summary) LIKE ?"
                     " OR LOWER(description) LIKE ? OR LOWER(tags) LIKE ?"
                     " OR LOWER(category) LIKE ? OR LOWER(author_name) LIKE ?)")
        params.extend([like] * 6)

    clause = " AND ".join(where)
    order = _SORTS.get(sort, _SORTS["popular"])
    limit = max(1, min(int(limit or 24), 60))
    offset = max(0, int(offset or 0))

    total = conn.execute(f"SELECT COUNT(*) AS c FROM store_items WHERE {clause}", params).fetchone()["c"]
    rows = conn.execute(
        f"SELECT * FROM store_items WHERE {clause} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()

    return {
        "items": [_public_item(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": sort if sort in _SORTS else "popular",
    }


def facets(conn) -> dict:
    """Category counts for the filter rail (published listings only)."""
    rows = conn.execute(
        "SELECT category, COUNT(*) AS c FROM store_items"
        " WHERE status = 'published' GROUP BY category ORDER BY LOWER(category)"
    ).fetchall()
    published = conn.execute(
        "SELECT COUNT(*) AS c, COALESCE(SUM(install_count), 0) AS installs FROM store_items"
        " WHERE status = 'published'"
    ).fetchone()
    return {
        "categories": [{"name": r["category"], "count": r["c"]} for r in rows],
        "listings": published["c"],
        "installs": published["installs"] or 0,
        "community": conn.execute(
            "SELECT COUNT(*) AS c FROM store_items WHERE status = 'published' AND source = 'community'"
        ).fetchone()["c"],
    }


def get_item(conn, slug: str, include_code: bool = False) -> dict | None:
    row = conn.execute("SELECT * FROM store_items WHERE slug = ?", (slug,)).fetchone()
    if row is None or row["status"] != "published":
        return None
    return _public_item(row, include_code=include_code)


def library(conn, user_id: int) -> dict:
    """The signed-in person's own Store view."""
    favourites = conn.execute(
        "SELECT i.* FROM store_favorites f JOIN store_items i ON i.slug = f.item_slug"
        " WHERE f.user_id = ? ORDER BY f.created_at DESC", (user_id,)
    ).fetchall()
    installs = conn.execute(
        "SELECT s.item_slug, s.version, s.created_at, i.title, i.category, i.source"
        " FROM store_installs s LEFT JOIN store_items i ON i.slug = s.item_slug"
        " WHERE s.user_id = ? ORDER BY s.created_at DESC LIMIT 50", (user_id,)
    ).fetchall()
    submissions = conn.execute(
        "SELECT slug, title, category, status, review_note, version, install_count,"
        " rating_count, created_at, updated_at FROM store_items"
        " WHERE author_user_id = ? ORDER BY updated_at DESC", (user_id,)
    ).fetchall()
    installed_slugs = {r["item_slug"] for r in installs}
    return {
        "favorites": [_public_item(r) for r in favourites],
        "installs": [dict(r) for r in installs],
        "submissions": [dict(r) for r in submissions],
        "installed": sorted(installed_slugs),
        "favorite_slugs": sorted(r["slug"] for r in favourites),
    }


# ---------------------------------------------------------------------------
# Write paths
# ---------------------------------------------------------------------------


def install(conn, slug: str, user_id: int, now: str, job_id: int | None = None) -> dict | None:
    """Record an install and hand back the full deploy payload."""
    row = conn.execute("SELECT * FROM store_items WHERE slug = ? AND status = 'published'",
                       (slug,)).fetchone()
    if row is None:
        return None
    conn.execute(
        "INSERT INTO store_installs (item_slug, user_id, job_id, version, created_at)"
        " VALUES (?,?,?,?,?)",
        (slug, user_id, job_id, row["version"], now),
    )
    conn.execute("UPDATE store_items SET install_count = install_count + 1 WHERE slug = ?", (slug,))
    conn.commit()
    item = _public_item(row, include_code=True)
    item["installed_at"] = now
    return item


def rate(conn, slug: str, user_id: int, rating: int, comment: str, now: str) -> dict | None:
    """One rating per person per listing; re-rating replaces the old one."""
    row = conn.execute("SELECT slug FROM store_items WHERE slug = ? AND status = 'published'",
                       (slug,)).fetchone()
    if row is None:
        return None
    rating = max(1, min(5, int(rating or 0)))
    comment = str(comment or "")[:500].strip()
    existing = conn.execute(
        "SELECT id FROM store_reviews WHERE item_slug = ? AND user_id = ?", (slug, user_id)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE store_reviews SET rating = ?, comment = ?, updated_at = ? WHERE id = ?",
            (rating, comment, now, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO store_reviews (item_slug, user_id, rating, comment, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?)",
            (slug, user_id, rating, comment, now, now),
        )
    totals = conn.execute(
        "SELECT COUNT(*) AS c, COALESCE(SUM(rating), 0) AS s FROM store_reviews WHERE item_slug = ?",
        (slug,),
    ).fetchone()
    conn.execute(
        "UPDATE store_items SET rating_count = ?, rating_sum = ? WHERE slug = ?",
        (totals["c"], totals["s"], slug),
    )
    conn.commit()
    return {"slug": slug, "rating": rating, "comment": comment,
            "rating_count": totals["c"],
            "rating_average": round(totals["s"] / totals["c"], 2) if totals["c"] else 0}


def reviews(conn, slug: str, limit: int = 20) -> list:
    rows = conn.execute(
        "SELECT r.rating, r.comment, r.created_at, u.username AS author"
        " FROM store_reviews r LEFT JOIN users u ON u.id = r.user_id"
        " WHERE r.item_slug = ? ORDER BY r.updated_at DESC LIMIT ?",
        (slug, max(1, min(int(limit or 20), 50))),
    ).fetchall()
    return [dict(r) for r in rows]


def set_favorite(conn, slug: str, user_id: int, now: str, favourite: bool = True) -> bool:
    row = conn.execute("SELECT slug FROM store_items WHERE slug = ? AND status = 'published'",
                       (slug,)).fetchone()
    if row is None:
        return False
    existing = conn.execute(
        "SELECT id FROM store_favorites WHERE item_slug = ? AND user_id = ?", (slug, user_id)
    ).fetchone()
    if favourite and not existing:
        conn.execute(
            "INSERT INTO store_favorites (item_slug, user_id, created_at) VALUES (?,?,?)",
            (slug, user_id, now),
        )
    elif not favourite and existing:
        conn.execute("DELETE FROM store_favorites WHERE id = ?", (existing["id"],))
    conn.commit()
    return True


def _unique_slug(conn, wanted: str) -> str:
    slug = _slugify(wanted)
    candidate, suffix = slug, 2
    while conn.execute("SELECT id FROM store_items WHERE slug = ?", (candidate,)).fetchone():
        candidate = f"{slug}-{suffix}"
        suffix += 1
    return candidate


def validate_submission(payload: dict) -> dict:
    """Every rule a submission must satisfy, without touching the database.

    The routes call this BEFORE spending the author's submission budget, so a
    form that would be rejected anyway never costs them one of their attempts
    and never lands in the human review queue.
    """
    title = str(payload.get("title") or "").strip()[:MAX_TITLE]
    summary = str(payload.get("summary") or "").strip()[:MAX_SUMMARY]
    category = str(payload.get("category") or "Utilities").strip()[:40]
    difficulty = str(payload.get("difficulty") or "Intermediate").strip()[:20]

    if len(title) < 3:
        raise ValueError("Give the bot a title of at least 3 characters.")
    if len(summary) < 10:
        raise ValueError("Write a one-line summary of at least 10 characters.")
    if category not in CATEGORIES:
        raise ValueError("Pick one of the listed categories.")
    if difficulty not in DIFFICULTIES:
        raise ValueError("Pick a difficulty: Beginner, Intermediate or Advanced.")

    checks = check_code(str(payload.get("code") or ""))
    if not checks["ok"]:
        raise ValueError(" ".join(checks["errors"]))
    return checks


def own_submission(conn, slug: str, user_id: int):
    """The caller's own community listing, or None."""
    row = conn.execute(
        "SELECT * FROM store_items WHERE slug = ? AND source = 'community'", (slug,)
    ).fetchone()
    if row is None or row["author_user_id"] != user_id:
        return None
    return row


def submit(conn, user: dict, payload: dict, now: str) -> dict:
    """Create a community listing. Returns the row (status `pending`)."""
    checks = validate_submission(payload)
    title = str(payload.get("title") or "").strip()[:MAX_TITLE]
    summary = str(payload.get("summary") or "").strip()[:MAX_SUMMARY]
    description = str(payload.get("description") or "").strip()[:MAX_DESCRIPTION]
    category = str(payload.get("category") or "Utilities").strip()[:40]
    difficulty = str(payload.get("difficulty") or "Intermediate").strip()[:20]
    code = str(payload.get("code") or "")
    version = str(payload.get("version") or "1.0.0").strip()[:20] or "1.0.0"
    features = payload.get("features") or []
    if isinstance(features, str):
        features = [line for line in features.split("\n")]
    features = [str(f).strip()[:120] for f in features if str(f).strip()][:15]

    analysis = telegram_detector.analyze_code(code, "python")
    slug = _unique_slug(conn, payload.get("slug") or title)
    env_fields = payload.get("env_fields") or []
    if not isinstance(env_fields, list):
        env_fields = []
    env_fields = [
        {"key": str(f.get("key", "")).strip()[:40],
         "label": str(f.get("label") or f.get("key", "")).strip()[:60],
         "type": "password" if f.get("secret", True) else "text",
         "required": bool(f.get("required")),
         "placeholder": str(f.get("placeholder") or "")[:80]}
        for f in env_fields if str(f.get("key", "")).strip()
    ][:10]

    conn.execute(
        "INSERT INTO store_items (slug, source, builtin_id, title, summary, description,"
        " category, tags, language, framework, difficulty, features, setup_notes,"
        " env_fields, code, code_hash, version, status, review_note, author_user_id,"
        " author_name, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (slug, "community", None, title, summary, description, category,
         ",".join(_tags_list(payload.get("tags"))), "python",
         analysis["framework"] if analysis["framework"] != "unknown" else "python",
         difficulty, "\n".join(features),
         str(payload.get("setup_notes") or "").strip()[:400],
         json.dumps(env_fields), code, _code_hash(code), version, "pending", "",
         user["id"], str(user["username"] or "member"), now, now),
    )
    conn.commit()
    return {"slug": slug, "title": title, "status": "pending", "checks": checks}


def update_submission(conn, user: dict, slug: str, payload: dict, now: str) -> dict | None:
    """The author refreshes their own listing (bumps the version)."""
    row = own_submission(conn, slug, user["id"])
    if row is None:
        return None
    code = str(payload.get("code") or row["code"])
    checks = check_code(code)
    if not checks["ok"]:
        raise ValueError(" ".join(checks["errors"]))
    version = str(payload.get("version") or row["version"]).strip()[:20] or row["version"]
    conn.execute(
        "UPDATE store_items SET code = ?, code_hash = ?, version = ?, status = 'pending',"
        " review_note = '', updated_at = ?, title = ?, summary = ?, description = ?,"
        " setup_notes = ? WHERE id = ?",
        (code, _code_hash(code), version, now,
         str(payload.get("title") or row["title"]).strip()[:MAX_TITLE],
         str(payload.get("summary") or row["summary"]).strip()[:MAX_SUMMARY],
         str(payload.get("description") or row["description"]).strip()[:MAX_DESCRIPTION],
         str(payload.get("setup_notes") or row["setup_notes"]).strip()[:400],
         row["id"]),
    )
    conn.commit()
    return {"slug": slug, "status": "pending", "version": version, "checks": checks}


def moderate(conn, slug: str, action: str, now: str, note: str = "") -> dict | None:
    """Owner moderation: publish, reject, remove, restore, feature."""
    row = conn.execute("SELECT * FROM store_items WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        return None
    note = str(note or "").strip()[:400]
    if action == "approve":
        conn.execute(
            "UPDATE store_items SET status = 'published', review_note = ?, updated_at = ?,"
            " published_at = COALESCE(published_at, ?) WHERE id = ?",
            (note, now, now, row["id"]),
        )
        status = "published"
    elif action == "reject":
        conn.execute(
            "UPDATE store_items SET status = 'rejected', review_note = ?, updated_at = ? WHERE id = ?",
            (note, now, row["id"]),
        )
        status = "rejected"
    elif action == "remove":
        conn.execute(
            "UPDATE store_items SET status = 'removed', review_note = ?, updated_at = ? WHERE id = ?",
            (note, now, row["id"]),
        )
        status = "removed"
    elif action == "restore":
        conn.execute(
            "UPDATE store_items SET status = 'published', review_note = ?, updated_at = ?,"
            " published_at = COALESCE(published_at, ?) WHERE id = ?",
            (note, now, now, row["id"]),
        )
        status = "published"
    elif action == "feature":
        featured = 0 if row["featured"] else 1
        conn.execute("UPDATE store_items SET featured = ?, updated_at = ? WHERE id = ?",
                     (featured, now, row["id"]))
        return {"slug": slug, "featured": bool(featured)}
    else:
        raise ValueError("Unknown moderation action.")
    conn.commit()
    return {"slug": slug, "status": status, "review_note": note}


def queue(conn, status: str = "pending") -> list:
    """Owner review queue."""
    if status not in ("pending", "published", "rejected", "removed"):
        status = "pending"
    rows = conn.execute(
        "SELECT slug, title, summary, category, language, framework, difficulty, version,"
        " status, review_note, author_name, author_user_id, install_count, rating_count,"
        " code_hash, created_at, updated_at FROM store_items WHERE status = ?"
        " ORDER BY created_at ASC", (status,)
    ).fetchall()
    return [dict(r) for r in rows]


def stats(conn) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS listings, COALESCE(SUM(install_count), 0) AS installs,"
        " COALESCE(SUM(rating_count), 0) AS ratings FROM store_items WHERE status = 'published'"
    ).fetchone()
    pending = conn.execute(
        "SELECT COUNT(*) AS c FROM store_items WHERE status = 'pending'"
    ).fetchone()["c"]
    top = conn.execute(
        "SELECT slug, title, install_count, rating_count FROM store_items"
        " WHERE status = 'published' ORDER BY install_count DESC, id DESC LIMIT 5"
    ).fetchall()
    return {"listings": row["listings"], "installs": row["installs"] or 0,
            "ratings": row["ratings"] or 0, "pending": pending,
            "top": [dict(r) for r in top]}
