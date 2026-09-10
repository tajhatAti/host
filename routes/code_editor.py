"""Code Studio: snippet CRUD, publish/unpublish, the standalone
/s/{token} page, and the legacy /code/s/{token} redirect."""
from typing import Optional, List

from fastapi import APIRouter, Header, HTTPException, Request

from routes.deps import *  # shared kernel (config, helpers, models)


from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/snippets")
def list_snippets(authorization: Optional[str] = Header(None)):
    user, _ = get_current_user_and_session(authorization)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, title, language, content, share_token, is_public, views, created_at, updated_at "
            "FROM snippets WHERE user_id = ? ORDER BY updated_at DESC", (user["id"],),
        ).fetchall()
        return {"snippets": [dict(r) for r in rows]}
    finally:
        conn.close()


class GenericDelete(BaseModel):
    id: int


class SnippetShare(BaseModel):
    id: int
    share: bool = True


class SnippetCreate(BaseModel):
    title: str
    language: Optional[str] = "text"
    content: str


class SnippetUpdate(BaseModel):
    id: int
    title: Optional[str] = None
    language: Optional[str] = None
    content: Optional[str] = None


@router.post("/snippets")
def create_snippet(payload: SnippetCreate, authorization: Optional[str] = Header(None)):
    user, _ = get_current_user_and_session(authorization)
    title = payload.title.strip() or "Untitled snippet"
    content = payload.content
    if not content.strip():
        raise HTTPException(status_code=400, detail="Snippet content cannot be empty.")
    ct = now_utc_str()
    conn = get_db_connection()
    try:
        cur = conn.execute(
            "INSERT INTO snippets (user_id, title, language, content, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user["id"], title, (payload.language or "text")[:32], content, ct, ct),
        )
        conn.commit()
        return {"message": "Snippet saved.", "id": cur.lastrowid}
    finally:
        conn.close()


@router.put("/snippets")
def update_snippet(payload: SnippetUpdate, authorization: Optional[str] = Header(None)):
    user, _ = get_current_user_and_session(authorization)
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM snippets WHERE id = ? AND user_id = ?", (payload.id, user["id"])).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Snippet not found.")
        title = payload.title if payload.title is not None else row["title"]
        language = payload.language if payload.language is not None else row["language"]
        content = payload.content if payload.content is not None else row["content"]
        conn.execute("UPDATE snippets SET title=?, language=?, content=?, updated_at=? WHERE id=?",
                     (title, language, content, now_utc_str(), payload.id))
        conn.commit()
        return {"message": "Snippet updated."}
    finally:
        conn.close()


@router.delete("/snippets")
def delete_snippet(payload: GenericDelete, authorization: Optional[str] = Header(None)):
    user, _ = get_current_user_and_session(authorization)
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT id FROM snippets WHERE id = ? AND user_id = ?", (payload.id, user["id"])).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Snippet not found.")
        conn.execute("DELETE FROM snippets WHERE id = ?", (payload.id,))
        conn.commit()
        return {"message": "Snippet deleted."}
    finally:
        conn.close()


@router.post("/snippets/share")
def toggle_snippet_share(payload: SnippetShare, authorization: Optional[str] = Header(None)):
    user, _ = get_current_user_and_session(authorization)
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT id, share_token FROM snippets WHERE id = ? AND user_id = ?",
                           (payload.id, user["id"])).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Snippet not found.")
        token = row["share_token"]
        if payload.share:
            if not token:
                token = secrets.token_urlsafe(12)
                conn.execute("UPDATE snippets SET share_token=?, is_public=1 WHERE id=?", (token, payload.id))
                conn.commit()
        else:
            conn.execute("UPDATE snippets SET share_token=NULL, is_public=0 WHERE id=?", (payload.id,))
            conn.commit()
            token = None
        return {"share": payload.share, "token": token,
                "url": f"/s/{token}" if token else None}
    finally:
        conn.close()


@router.get("/s/{token}")
def view_shared_snippet(token: str):
    """Public PUBLISHED page via share token."""
    return _serve_shared(token)


@router.get("/@{username}/{filename}")
def view_shared_by_user_file(username: str, filename: str):
    """Pretty public URL: /@username/filename → resolves to published snippet."""
    conn = get_db_connection()
    try:
        # Find user by username
        u = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if not u:
            raise HTTPException(status_code=404, detail="User not found.")
        # Find snippet owned by that user whose title (strips extension) matches filename
        # Normalize: strip any extension from both
        import os
        base = os.path.splitext(filename)[0]
        rows = conn.execute(
            "SELECT share_token FROM snippets WHERE user_id = ? AND is_public = 1 "
            "AND (title = ? OR title LIKE ?)",
            (u["id"], filename, base + "%")
        ).fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="Published page not found.")
        token = rows[0]["share_token"]
    finally:
        conn.close()
    return _serve_shared(token)


def _serve_shared(token: str):
    from snippet_page import build_published_page
    from fastapi.responses import HTMLResponse
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT title, language, content, created_at, views FROM snippets "
            "WHERE share_token = ? AND is_public = 1", (token,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="This page is private or no longer published.")
        conn.execute("UPDATE snippets SET views = views + 1 WHERE share_token = ?", (token,))
        conn.commit()
    finally:
        conn.close()
    html, is_raw = build_published_page(row)
    return HTMLResponse(content=html)





# ================================
# CODE EXECUTION PROXY (main website → runner service)
# ================================
