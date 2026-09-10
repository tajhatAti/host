"""Bot Store API.

Public browsing is anonymous; installs, ratings, favourites and submissions
need a session; moderation is owner-only and 404-stealth like the rest of the
admin surface.

Every listing is one complete Python file. `/api/store/{slug}` hands back the
whole source to a signed-in reader — the store sells raw Python, not a
platform dialect, so hiding the file would hide the product.
"""
from typing import Optional, List

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from routes.deps import *  # shared kernel (config, helpers, models)
from routes.admin import require_admin, _admin_audit
from services import store

router = APIRouter()


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class StoreInstall(BaseModel):
    job_id: Optional[int] = None


class StoreRating(BaseModel):
    rating: int
    comment: Optional[str] = ""


class StoreFavorite(BaseModel):
    favorite: bool = True


class StoreEnvField(BaseModel):
    key: str
    label: Optional[str] = ""
    secret: Optional[bool] = True
    required: Optional[bool] = False
    placeholder: Optional[str] = ""


class StoreSubmission(BaseModel):
    title: str
    summary: str
    description: Optional[str] = ""
    category: str
    difficulty: Optional[str] = "Intermediate"
    tags: Optional[List[str]] = []
    features: Optional[List[str]] = []
    setup_notes: Optional[str] = ""
    env_fields: Optional[List[StoreEnvField]] = []
    code: str
    version: Optional[str] = "1.0.0"


class StoreModeration(BaseModel):
    note: Optional[str] = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _optional_user(authorization: Optional[str]):
    """Signed-in user, or None. Browsing the store never demands a session."""
    if not authorization:
        return None
    try:
        user, _session = get_current_user_and_session(authorization)
    except HTTPException:
        return None
    return user


def _require_user(authorization: Optional[str]):
    user, session = get_current_user_and_session(authorization)
    return user, session


def _conn():
    conn = get_db_connection()
    # Built-in products are mirrored on every read path so a fresh database,
    # a restored snapshot and a schema change all show the same catalog.
    try:
        store.sync_builtins(conn, now_utc_str())
    except Exception:
        conn.rollback()
    return conn


# ---------------------------------------------------------------------------
# Public catalog
# ---------------------------------------------------------------------------


@router.get("/api/store")
def store_catalog(q: str = "", category: str = "", sort: str = "popular",
                  source: str = "", limit: int = 24, offset: int = 0,
                  authorization: Optional[str] = Header(None)):
    conn = _conn()
    try:
        page = store.catalog(conn, query=q, category=category, sort=sort,
                             source=source, limit=limit, offset=offset)
        page["facets"] = store.facets(conn)
        user = _optional_user(authorization)
        if user:
            rows = conn.execute(
                "SELECT item_slug FROM store_favorites WHERE user_id = ?", (user["id"],)
            ).fetchall()
            installed = conn.execute(
                "SELECT DISTINCT item_slug FROM store_installs WHERE user_id = ?", (user["id"],)
            ).fetchall()
            page["favorite_slugs"] = sorted(r["item_slug"] for r in rows)
            page["installed_slugs"] = sorted(r["item_slug"] for r in installed)
        else:
            page["favorite_slugs"] = []
            page["installed_slugs"] = []
        return page
    finally:
        conn.close()


@router.get("/api/store/categories")
def store_categories():
    conn = _conn()
    try:
        facets = store.facets(conn)
        facets["allowed"] = list(store.CATEGORIES)
        facets["difficulties"] = list(store.DIFFICULTIES)
        return facets
    finally:
        conn.close()


@router.get("/api/store/mine/library")
def store_library(authorization: Optional[str] = Header(None)):
    user, _ = _require_user(authorization)
    conn = _conn()
    try:
        return store.library(conn, user["id"])
    finally:
        conn.close()


@router.get("/api/store/{slug}")
def store_item(slug: str, authorization: Optional[str] = Header(None)):
    conn = _conn()
    try:
        user = _optional_user(authorization)
        item = store.get_item(conn, slug, include_code=bool(user))
        if item is None:
            raise HTTPException(status_code=404, detail="That listing is not in the store.")
        item["code_full"] = bool(user)
        item["reviews"] = store.reviews(conn, slug, limit=10)
        if user:
            favourite = conn.execute(
                "SELECT id FROM store_favorites WHERE item_slug = ? AND user_id = ?",
                (slug, user["id"]),
            ).fetchone()
            installs = conn.execute(
                "SELECT COUNT(*) AS c FROM store_installs WHERE item_slug = ? AND user_id = ?",
                (slug, user["id"]),
            ).fetchone()["c"]
            item["favorite"] = bool(favourite)
            item["my_installs"] = installs
        else:
            item["favorite"] = False
            item["my_installs"] = 0
        return item
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Install / rate / favourite
# ---------------------------------------------------------------------------


@router.post("/api/store/{slug}/install")
def store_install(slug: str, body: StoreInstall, request: Request,
                  authorization: Optional[str] = Header(None)):
    user, _ = _require_user(authorization)
    rate_limit_user(user["id"], "store-install", 60, 300)
    conn = _conn()
    try:
        item = store.install(conn, slug, user["id"], now_utc_str(), job_id=body.job_id)
        if item is None:
            raise HTTPException(status_code=404, detail="That listing is not in the store.")
        return {"ok": True, "item": item}
    finally:
        conn.close()


@router.post("/api/store/{slug}/rate")
def store_rate(slug: str, body: StoreRating, authorization: Optional[str] = Header(None)):
    user, _ = _require_user(authorization)
    if not 1 <= int(body.rating or 0) <= 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5.")
    rate_limit_user(user["id"], "store-rate", 20, 300)
    conn = _conn()
    try:
        result = store.rate(conn, slug, user["id"], body.rating, body.comment or "", now_utc_str())
        if result is None:
            raise HTTPException(status_code=404, detail="That listing is not in the store.")
        result["reviews"] = store.reviews(conn, slug, limit=10)
        return result
    finally:
        conn.close()


@router.post("/api/store/{slug}/favorite")
def store_favorite(slug: str, body: StoreFavorite, authorization: Optional[str] = Header(None)):
    user, _ = _require_user(authorization)
    conn = _conn()
    try:
        if not store.set_favorite(conn, slug, user["id"], now_utc_str(), bool(body.favorite)):
            raise HTTPException(status_code=404, detail="That listing is not in the store.")
        return {"ok": True, "favorite": bool(body.favorite), "slug": slug}
    finally:
        conn.close()


@router.delete("/api/store/{slug}/favorite")
def store_unfavorite(slug: str, authorization: Optional[str] = Header(None)):
    user, _ = _require_user(authorization)
    conn = _conn()
    try:
        if not store.set_favorite(conn, slug, user["id"], now_utc_str(), False):
            raise HTTPException(status_code=404, detail="That listing is not in the store.")
        return {"ok": True, "favorite": False, "slug": slug}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Community submissions
# ---------------------------------------------------------------------------


@router.post("/api/store/items")
def store_submit(body: StoreSubmission, authorization: Optional[str] = Header(None)):
    user, _ = _require_user(authorization)
    # Validate BEFORE spending the budget: a form that would be rejected
    # anyway never reaches the human review queue, so it must not cost the
    # author one of their submissions.
    try:
        store.validate_submission(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # A submission stores a whole program and lands in a human review queue:
    # the budget is a handful per hour, not a handful per minute.
    rate_limit_user(user["id"], "store-submit", 5, 3600)
    conn = _conn()
    try:
        try:
            created = store.submit(conn, dict(user), body.model_dump(), now_utc_str())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, **created,
                "message": "Submitted. An owner reviews new listings before they go live."}
    finally:
        conn.close()


@router.patch("/api/store/items/{slug}")
def store_update(slug: str, body: StoreSubmission, authorization: Optional[str] = Header(None)):
    user, _ = _require_user(authorization)
    try:
        store.validate_submission(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    conn = _conn()
    try:
        # Ownership is checked before the budget: someone probing another
        # person's listing should not be able to burn that person's allowance.
        if store.own_submission(conn, slug, user["id"]) is None:
            raise HTTPException(status_code=404, detail="That is not one of your listings.")
        rate_limit_user(user["id"], "store-submit", 5, 3600)
        try:
            updated = store.update_submission(conn, dict(user), slug, body.model_dump(), now_utc_str())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if updated is None:
            raise HTTPException(status_code=404, detail="That is not one of your listings.")
        return {"ok": True, **updated}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Owner moderation (404-stealth for everyone else)
# ---------------------------------------------------------------------------


@router.get("/api/store/admin/queue")
def store_queue(status: str = "pending", authorization: Optional[str] = Header(None)):
    admin, _ = require_admin(authorization)
    conn = _conn()
    try:
        return {"status": status, "items": store.queue(conn, status), "stats": store.stats(conn)}
    finally:
        conn.close()


@router.post("/api/store/admin/{slug}/{action}")
def store_moderate(slug: str, action: str, body: StoreModeration,
                   authorization: Optional[str] = Header(None)):
    admin, _ = require_admin(authorization)
    if action not in ("approve", "reject", "remove", "restore", "feature"):
        raise HTTPException(status_code=404, detail="Not found.")
    conn = _conn()
    try:
        result = store.moderate(conn, slug, action, now_utc_str(), body.note or "")
        if result is None:
            raise HTTPException(status_code=404, detail="Not found.")
        _admin_audit(conn, admin["id"], f"store.{action}", slug, (body.note or "")[:200])
        conn.commit()
        return {"ok": True, **result}
    finally:
        conn.close()


@router.get("/api/store/admin/stats")
def store_stats(authorization: Optional[str] = Header(None)):
    admin, _ = require_admin(authorization)
    conn = _conn()
    try:
        return store.stats(conn)
    finally:
        conn.close()
