"""Simple server-side ping endpoint — CodeNest built-in.

/public:  GET /ping?url=...   → minimal text/HTML response (humans)
/api:     GET /api/ping?url=... → JSON  (bots, UIs, Telegram)

Timing stops the instant response headers arrive — pure server↔target latency,
no browser / Telegram round-trip included.
"""
from __future__ import annotations

import logging
import os
import time
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

log = logging.getLogger("codenest.ping")

router = APIRouter()

DEFAULT_TARGET = os.getenv("PING_DEFAULT_TARGET", "https://ahadorg.onrender.com").strip()
TIMEOUT_S = float(os.getenv("PING_TIMEOUT_S", "8"))
UA = "CodeNest-Ping/1.0"
ALLOWED_SCHEMES = ("http://", "https://")


def _normalise(url: str) -> str:
    url = (url or "").strip()
    if not url:
        url = DEFAULT_TARGET
    if not url.startswith(ALLOWED_SCHEMES):
        url = "https://" + url
    return url


async def _ping(url: str) -> dict:
    url = _normalise(url)
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return {"ok": False, "error": "invalid URL", "target": url}
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(TIMEOUT_S, connect=5.0),
            follow_redirects=True,
            max_redirects=5,
            headers={"User-Agent": UA},
            trust_env=False,
            verify=True,
        ) as c:
            for method in ("HEAD", "GET"):
                try:
                    r = await c.request(method, url)
                    t1 = time.perf_counter()
                    await r.aclose()
                    ms = (t1 - t0) * 1000
                    return {
                        "ok": True,
                        "target": url,
                        "final_url": str(r.url),
                        "status": r.status_code,
                        "latency_ms": round(ms, 2),
                        "server": r.headers.get("server", ""),
                    }
                except httpx.RemoteProtocolError:
                    continue
            # If both HEAD & GET raised RPE
            return {"ok": False, "target": url, "error": "protocol error"}
    except httpx.ConnectTimeout:
        return {"ok": False, "target": url, "error": f"connection timed out ({int(TIMEOUT_S)}s)"}
    except httpx.ReadTimeout:
        return {"ok": False, "target": url, "error": "server did not respond in time"}
    except httpx.ConnectError as e:
        return {"ok": False, "target": url, "error": f"connection error: {e}"}
    except httpx.SSLError as e:
        return {"ok": False, "target": url, "error": f"TLS error: {e}"}
    except Exception as e:  # noqa: BLE001
        log.exception("ping failed: %s", url)
        return {"ok": False, "target": url, "error": f"{type(e).__name__}: {e}"}


@router.get("/api/ping")
async def api_ping(url: str | None = Query(default=None)):
    return JSONResponse(await _ping(url or DEFAULT_TARGET))


# Minimal human-facing page — one input, one button, big number.
_PING_HTML = """<!doctype html>
<html lang="en"><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Ping · CodeNest</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#0d1117;color:#e6edf3;
font:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:24px;
max-width:480px;width:100%}
h1{margin:0 0 4px;font-size:20px}p{margin:0 0 18px;color:#8b949e;font-size:13px}
.row{display:flex;gap:8px}
input{flex:1;min-width:0;background:#010409;border:1px solid #30363d;color:#e6edf3;
border-radius:6px;padding:10px 12px;font:13px ui-monospace,Menlo,Consolas,monospace;outline:none}
input:focus{border-color:#58a6ff}
button{background:#3fb950;color:#000;border:0;border-radius:6px;padding:0 18px;
font-weight:600;font-size:13px;cursor:pointer}
button:disabled{opacity:.6}
.out{margin-top:18px;display:none}.out.show{display:block}
.lat{font:700 40px ui-monospace,monospace;letter-spacing:-.02em}
.lat .u{font-size:16px;color:#8b949e;font-weight:400;margin-left:4px}
.ok{color:#3fb950}.warn{color:#d29922}.bad{color:#f85149}
.meta{margin-top:8px;color:#8b949e;font:12px ui-monospace,monospace}
.err{margin-top:14px;color:#f85149;background:rgba(248,81,73,.08);
border:1px solid rgba(248,81,73,.25);padding:10px 12px;border-radius:6px;
font:12px ui-monospace,monospace}
.foot{margin-top:20px;text-align:center;color:#484f58;font-size:11px}
code{background:#010409;padding:1px 6px;border-radius:4px}
</style></head>
<body><div class=card>
<h1>🌐 Server Ping</h1>
<p>Real HTTP response time from our server. Timing stops at response headers — no browser/Telegram lag counted.</p>
<div class=row>
  <input id=u placeholder="https://example.com" value="https://ahadorg.onrender.com" spellcheck=false>
  <button id=b onclick="go()">Ping</button>
</div>
<div class=out id=out>
  <div class=lat id=lat>--<span class=u>ms</span></div>
  <div class=meta id=meta></div>
  <div class=err id=err style=display:none></div>
</div>
<div class=foot>API: <code>GET /api/ping?url=...</code></div>
</div>
<script>
async function go(){
  const u=document.getElementById('u').value.trim();if(!u)return;
  const b=document.getElementById('b');b.disabled=true;b.textContent='…';
  document.getElementById('out').classList.add('show');
  document.getElementById('err').style.display='none';
  try{
    const r=await fetch('/api/ping?url='+encodeURIComponent(u));
    const d=await r.json();
    if(!d.ok)throw new Error(d.error||'failed');
    const ms=d.latency_ms;
    const el=document.getElementById('lat');
    const cls=ms<150?'ok':ms<500?'warn':ms<1500?'warn':'bad';
    el.className='lat '+cls;el.innerHTML=ms.toFixed(2)+'<span class=u>ms</span>';
    document.getElementById('meta').textContent='HTTP '+d.status+' · '+d.target;
  }catch(e){
    document.getElementById('lat').textContent='—';
    const er=document.getElementById('err');er.style.display='block';er.textContent='❌ '+e.message;
  }finally{b.disabled=false;b.textContent='Ping'}
}
document.getElementById('u').addEventListener('keydown',e=>{if(e.key==='Enter')go()});
const p=new URLSearchParams(location.search);if(p.get('url')){document.getElementById('u').value=p.get('url');go()}
</script></body></html>"""


@router.get("/ping", include_in_schema=False)
def ping_page():
    return HTMLResponse(_PING_HTML)
