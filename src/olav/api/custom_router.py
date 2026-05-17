"""OLAV-specific FastAPI routes for the native langgraph_api user_router extension.

This module is the ``http.app`` entry configured in app.py via the ``LANGGRAPH_HTTP``
env var.  langgraph_api's server merges these routes with the native LG protocol
routes (assistants, threads, runs, stream, store) at startup.

Routes provided (all OLAV-specific, none collide with LG native routes):
  GET  /                → SPA shell (auth-gated when mode != none)
  GET  /login           → Login page HTML
  POST /login           → Validate token, set olav_session cookie, redirect to /
  GET  /memory/graph    → Knowledge graph vis.js HTML (built on-demand)
  POST /reload          → Flush graph cache + config/router singletons
  GET  /_next/*         → Next.js static asset bundles

The ``/_next`` StaticFiles mount is registered at import time; its path is
controlled by ``_NEXT_DIR`` which tests can patch before importing.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

from olav.core.auth import get_auth_provider

_logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"
_NEXT_DIR = _STATIC_DIR / "_next"
_KG_PATH = Path(".olav") / "knowledge" / "_graph.html"

app = FastAPI(title="OLAV custom routes", docs_url=None, redoc_url=None)

# Mount Next.js static bundles (/_next/static/…)
if _NEXT_DIR.exists():
    from fastapi.staticfiles import StaticFiles  # noqa: PLC0415

    app.mount("/_next", StaticFiles(directory=str(_NEXT_DIR)), name="next_static")


# ---------------------------------------------------------------------------
# CIDR allowlist middleware (migrated from server.py)
# ---------------------------------------------------------------------------

def _load_allowed_cidrs() -> list | None:
    """Load allowed_cidrs from api.json security section. Returns None if unconfigured."""
    try:
        from olav.core.config import ConfigLoader  # noqa: PLC0415

        cidrs = ConfigLoader().security.allowed_cidrs
        if not cidrs:
            return None
        import ipaddress  # noqa: PLC0415

        return [ipaddress.ip_network(c, strict=False) for c in cidrs]
    except Exception:
        return None


@app.middleware("http")
async def cidr_allowlist_middleware(request: Request, call_next):
    """Block requests from IPs outside the configured CIDR allowlist.

    - If no allowlist is configured, all IPs are allowed (backward compatible).
    - 127.0.0.1 and ::1 are always allowed.
    - /health is always allowed (monitoring probes).
    """
    if request.url.path == "/health":
        return await call_next(request)

    allowed = _load_allowed_cidrs()
    if allowed is None:
        return await call_next(request)

    import ipaddress  # noqa: PLC0415

    client_ip = request.client.host if request.client else "127.0.0.1"
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return await call_next(request)

    if addr.is_loopback:
        return await call_next(request)

    for network in allowed:
        if addr in network:
            return await call_next(request)

    from starlette.responses import JSONResponse  # noqa: PLC0415

    return JSONResponse({"detail": "Forbidden"}, status_code=403)


# ---------------------------------------------------------------------------
# Auth helpers (migrated from server.py)
# ---------------------------------------------------------------------------

def _get_auth_mode() -> str:
    try:
        from olav.core.config import ConfigLoader  # noqa: PLC0415

        return ConfigLoader().auth.mode or "none"
    except Exception:
        return "none"


def _set_session_cookie(response: Response, token: str, request: Request | None = None) -> None:
    """Set olav_session cookie with GAP-4 security flags."""
    try:
        from olav.core.config import ConfigLoader  # noqa: PLC0415

        ttl_hours = ConfigLoader().auth.session_ttl_hours
    except Exception:
        ttl_hours = 24
    is_https = request is not None and request.url.scheme == "https"
    response.set_cookie(
        key="olav_session",
        value=token,
        httponly=True,
        secure=is_https,
        samesite="lax",
        max_age=ttl_hours * 3600,
        path="/",
    )


def _minimal_login_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>OLAV Login</title>
  <style>
    body { font-family: monospace; background: #1a1a2e; color: #e0e0e0;
           display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
    .box { background: #16213e; border: 1px solid #0f3460; border-radius: 8px;
           padding: 2rem; width: 320px; }
    h2 { color: #e94560; margin-bottom: 1.5rem; text-align: center; }
    label { display: block; margin-bottom: 0.25rem; color: #a0a0b0; font-size: 0.85rem; }
    input { width: 100%; box-sizing: border-box; padding: 0.5rem; border: 1px solid #0f3460;
            background: #0f3460; color: #e0e0e0; border-radius: 4px; margin-bottom: 1rem; }
    button { width: 100%; padding: 0.6rem; background: #e94560; color: white;
             border: none; border-radius: 4px; cursor: pointer; font-family: monospace; }
    button:hover { background: #c73652; }
  </style>
</head>
<body>
  <div class="box">
    <h2>&#9632; OLAV</h2>
    <form id="loginForm">
      <label for="token">Token</label>
      <input type="password" id="token" name="token" autocomplete="current-password" required>
      <button type="submit">Login</button>
    </form>
  </div>
  <script>
    document.getElementById('loginForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const token = document.getElementById('token').value;
      const resp = await fetch('/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({token})
      });
      if (resp.ok || resp.redirected) {
        window.location.href = '/';
      } else {
        alert('Invalid token. Please try again.');
      }
    });
  </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# KG helpers — isolated functions so tests can patch them cleanly
# ---------------------------------------------------------------------------

def _build_kg():
    from olav.core.memory.knowledge_graph import build_graph  # noqa: PLC0415

    return build_graph()


def _export_kg_visjs(graph_data, out_path: Path) -> None:
    from olav.core.memory.knowledge_graph import export_visjs  # noqa: PLC0415

    export_visjs(graph_data, out_path)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def root(request: Request):
    """Serve the SPA shell (auth-gated when mode != none)."""
    mode = _get_auth_mode()
    if mode != "none":
        url_token = request.query_params.get("token")
        if url_token:
            resp = RedirectResponse(url="/", status_code=302)
            _set_session_cookie(resp, url_token, request)
            return resp

        session_token = request.cookies.get("olav_session")
        if not session_token:
            return RedirectResponse(url="/login")

        try:
            identity = get_auth_provider(mode).authenticate(
                token=session_token, source_channel="api_bearer"
            )
            if identity.source != "token":
                resp = RedirectResponse(url="/login")
                resp.delete_cookie("olav_session")
                return resp
        except Exception:
            resp = RedirectResponse(url="/login")
            resp.delete_cookie("olav_session")
            return resp

    index = _STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index), media_type="text/html")
    return RedirectResponse(url="/docs")


@app.get("/login", include_in_schema=False)
async def login_page():
    """Serve the login page HTML."""
    login_html = _STATIC_DIR / "login.html"
    if login_html.exists():
        return FileResponse(str(login_html), media_type="text/html")
    return HTMLResponse(content=_minimal_login_html(), status_code=200)


class LoginRequest(BaseModel):
    token: str


@app.post("/login", include_in_schema=False)
async def login_submit(body: LoginRequest, request: Request):
    """Validate token and set session cookie."""
    mode = _get_auth_mode()
    if mode == "none":
        # Set a dummy cookie so the Next.js SPA's client-side auth check
        # finds a session and doesn't redirect back to /login in a loop.
        resp = RedirectResponse(url="/", status_code=302)
        _set_session_cookie(resp, "anonymous", request)
        return resp

    try:
        identity = get_auth_provider(mode).authenticate(token=body.token)
        if identity.source != "token":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.") from exc

    resp = RedirectResponse(url="/", status_code=302)
    _set_session_cookie(resp, body.token, request)
    return resp


@app.get("/memory/graph", include_in_schema=False)
async def memory_graph():
    """Serve the knowledge graph vis.js HTML (built on demand)."""
    import asyncio  # noqa: PLC0415

    kg_path = _KG_PATH
    if not kg_path.exists():
        try:
            # Run blocking filesystem/KG-build ops in a thread so we don't
            # block the event loop (avoids blockbuster warnings).
            def _build_sync():
                kg_path.parent.mkdir(parents=True, exist_ok=True)
                graph_data = _build_kg()
                _export_kg_visjs(graph_data, kg_path)

            await asyncio.to_thread(_build_sync)
        except Exception as exc:
            return HTMLResponse(
                "<html><body style='font-family:sans-serif;background:#0d1117;color:#e6edf3;padding:40px'>"
                "<h2>Knowledge Graph</h2>"
                "<p style='color:#8b949e'>No knowledge data yet. The graph will appear after:</p>"
                "<ul style='color:#8b949e'>"
                "<li><code>olav kb import &lt;file&gt;</code> — import documents</li>"
                "<li>Agent conversations — auto-captured as operational knowledge</li>"
                "</ul>"
                f"<p style='font-size:12px;color:#484f58'>Debug: {exc}</p>"
                "</body></html>",
                status_code=200,
            )
    return FileResponse(str(kg_path), media_type="text/html")


@app.get("/agents", include_in_schema=False)
async def list_agents():
    """Compatibility shim: Next.js login page calls GET /agents to validate auth and list agents."""
    from olav.core.workspace_discovery import discover_top_level_agent_names  # noqa: PLC0415

    agents = discover_top_level_agent_names() or ["core"]
    return [{"id": name, "name": name} for name in agents]


@app.post("/reload")
async def reload_agent():
    """Flush graph cache and config/router singletons so the next request rebuilds."""
    try:
        import olav.server.graph_factory as _gf  # noqa: PLC0415

        _gf._graph_cache.clear()
    except Exception:
        pass

    try:
        from olav.core.config import ConfigLoader  # noqa: PLC0415

        ConfigLoader._loaded = False
        ConfigLoader._instance = None
    except Exception:
        pass

    try:
        import olav.core.router as _router_mod  # noqa: PLC0415

        _router_mod._router_instance = None
    except Exception:
        pass

    _logger.info("Graph cache, config, and router reset")
    return {"status": "reloaded"}
