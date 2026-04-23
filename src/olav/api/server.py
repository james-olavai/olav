"""OLAV API - LangGraph Server API compatible layer.

This module provides a FastAPI-based API layer compatible with deep-agents-ui.

Endpoints:
- POST /threads - Create new conversation thread
- GET /threads/search - List existing threads
- POST /threads/{id}/runs/stream - Stream execution (primary)
- POST /runs/stream - Threadless streaming execution
- GET /login - Login page (WebUI, P3)
- POST /login - Validate token, set session cookie (P3)
- GET /health - Health check
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from olav.core.audit_recorder import AuditEventRecorder
from olav.core.auth import UserIdentity, get_auth_provider

_STATIC_DIR = Path(__file__).parent / "static"

import logging
import os

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# P1: Bearer token authentication dependency
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


def _get_auth_mode() -> str:
    try:
        from olav.core.config import ConfigLoader

        return ConfigLoader().auth.mode
    except Exception:
        return "none"


def _emit_auth_mode_warning() -> None:
    """Emit a security warning if auth.mode is 'none' (no authentication)."""
    if _get_auth_mode() == "none":
        _logger.warning(
            "⚠️  auth.mode=none — Web has no authentication. "
            "Run 'olav admin-users add-user %s --role admin' then set auth.mode='token' in api.json.",
            os.environ.get("USER", "admin"),
        )


def _verify_bearer(credentials: HTTPAuthorizationCredentials | None) -> UserIdentity:
    """Verify Bearer token and return UserIdentity.

    If auth.mode == 'none', returns OS identity without verification.
    Raises HTTP 401 if token is invalid.
    """

    mode = _get_auth_mode()
    if mode == "none":
        return get_auth_provider("none").authenticate()

    token = credentials.credentials if credentials else None
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Provide Authorization: Bearer <token>.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    identity = get_auth_provider(mode).authenticate(token=token, source_channel="api_bearer")
    if identity.source != "token":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return identity


async def _require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> UserIdentity:
    """Resolve identity from Authorization: Bearer header OR olav_session cookie."""
    mode = _get_auth_mode()
    if mode == "none":
        return get_auth_provider("none").authenticate()

    token = credentials.credentials if credentials else None
    if not token:
        token = request.cookies.get("olav_session")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Provide Authorization: Bearer <token> or olav_session cookie.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    identity = get_auth_provider(mode).authenticate(token=token, source_channel="api_bearer")
    if identity.source != "token":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return identity


def _get_thread_owner(thread_id: str) -> str | None:
    """Return the user_id who owns the given thread, or None if not found."""
    try:
        import duckdb
        from olav.core.config import AUDIT_DB_PATH
        db_path = Path(AUDIT_DB_PATH)
        if not db_path.exists():
            return None
        with duckdb.connect(str(db_path), read_only=True) as conn:
            row = conn.execute(
                "SELECT user_id FROM sessions WHERE thread_id = ?", [thread_id]
            ).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _check_thread_access(thread_id: str, identity: UserIdentity) -> None:
    """Raise HTTP 403 if identity does not own thread_id and is not admin.

    New threads (not yet in sessions) are always allowed.
    """
    owner = _get_thread_owner(thread_id)
    if owner is None:
        return  # new thread — allow
    if owner == identity.username:
        return  # owner
    role = getattr(identity, "role", "user")
    if role == "admin":
        return  # admin can access everything
    raise HTTPException(
        status_code=403,
        detail=f"Thread {thread_id!r} belongs to '{owner}'. Access denied.",
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ThreadCreate(BaseModel):
    metadata: dict[str, Any] | None = None


class RunStreamRequest(BaseModel):
    assistant_id: str = "olav-orchestrator"
    input: dict[str, Any]
    thread_id: str | None = None
    stream_mode: str = "messages-tuple"
    user_id: str | None = None


class MessageInput(BaseModel):
    messages: list[dict[str, str]]


# ---------------------------------------------------------------------------
# Agent singleton
# ---------------------------------------------------------------------------

_agent_instance = None


async def get_agent():
    global _agent_instance
    if _agent_instance is None:
        from olav.agents.agent import create_olav_agent

        _agent_instance = create_olav_agent()
    return _agent_instance


@asynccontextmanager
async def lifespan(app):
    _emit_auth_mode_warning()
    yield
    if _agent_instance is not None:
        await _agent_instance.close()


app = FastAPI(
    title="OLAV API",
    version="1.0.0",
    description="LangGraph Server API compatible layer for OLAV",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# CIDR Allowlist Middleware
# ---------------------------------------------------------------------------


def _load_allowed_cidrs() -> list | None:
    """Load allowed_cidrs from api.json security section. Returns None if unconfigured."""
    try:
        from olav.core.config import ConfigLoader

        cidrs = ConfigLoader().security.allowed_cidrs
        if not cidrs:
            return None
        import ipaddress

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

    import ipaddress

    client_ip = request.client.host if request.client else "127.0.0.1"
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return await call_next(request)

    # Localhost always allowed
    if addr.is_loopback:
        return await call_next(request)

    for network in allowed:
        if addr in network:
            return await call_next(request)

    from starlette.responses import JSONResponse

    return JSONResponse({"detail": "Forbidden"}, status_code=403)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def root(request: Request):
    """Serve the built-in chat UI (all assets are inlined).

    If auth.mode != 'none' and no valid cookie/token, redirect to /login.
    """
    # P3: check session cookie when WebUI mode active
    mode = _get_auth_mode()
    if mode != "none":
        url_token = request.query_params.get("token")
        if url_token:
            # JupyterLab-style: ?token= sets cookie then redirects clean
            resp = RedirectResponse(url="/", status_code=302)
            _set_session_cookie(resp, url_token, request)
            return resp

        session_token = request.cookies.get("olav_session")
        if not session_token:
            return RedirectResponse(url="/login")

        # Verify cookie is still valid — stale cookies (e.g. after a re-init) must
        # redirect to /login rather than serving the SPA that then 401s on every API call.
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


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "olav-api"}


@app.post("/reload")
async def reload_agent():
    """Reset agent and config singletons so the next request rebuilds from disk."""
    global _agent_instance
    if _agent_instance is not None:
        try:
            await _agent_instance.close()
        except Exception:
            pass
    _agent_instance = None
    # Invalidate ConfigLoader singleton so config changes are picked up
    try:
        from olav.core.config import ConfigLoader
        ConfigLoader._loaded = False
        ConfigLoader._instance = None
    except Exception:
        pass
    # Reset semantic router so new skills are indexed
    try:
        from olav.core.router import _router_instance
        import olav.core.router as _router_mod
        _router_mod._router_instance = None
    except Exception:
        pass
    _logger.info("Agent, config, and router reset — next request will rebuild from workspace")
    return {"status": "reloaded"}


@app.get("/agents")
async def list_agents():
    """Return registered agents from workspace AGENT.md files."""
    try:
        from olav.cli.commands.refresh import _scan_agents

        workspace_root = Path(".olav") / "workspace"
        agents = _scan_agents(workspace_root)
        return [
            {"id": a["flag"], "name": a["name"], "description": a.get("description", "")}
            for a in agents
        ]
    except Exception as exc:
        _logger.warning("Failed to scan agents: %s", exc)
        return [{"id": "core", "name": "core", "description": "Core platform agent"}]


@app.get("/memory/graph", include_in_schema=False)
async def memory_graph():
    """Serve the knowledge graph visualization (vis.js HTML)."""
    graph_path = Path(".olav/knowledge/_graph.html")
    if not graph_path.exists():
        try:
            from olav.core.memory.knowledge_graph import build_graph, export_visjs

            graph_path.parent.mkdir(parents=True, exist_ok=True)
            graph_data = build_graph()
            export_visjs(graph_data, graph_path)
        except Exception as exc:
            from fastapi.responses import HTMLResponse

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
    return FileResponse(str(graph_path), media_type="text/html")


# ---------------------------------------------------------------------------
# P3: WebUI Login routes
# ---------------------------------------------------------------------------


@app.get("/login", include_in_schema=False)
async def login_page():
    """Serve the login HTML page (P3)."""
    login_html = _STATIC_DIR / "login.html"
    if login_html.exists():
        return FileResponse(str(login_html), media_type="text/html")
    return HTMLResponse(content=_minimal_login_html(), status_code=200)


class LoginRequest(BaseModel):
    token: str


@app.post("/login", include_in_schema=False)
async def login_submit(body: LoginRequest, request: Request, response: Response):
    """Validate token, write session cookie (P3, GAP-4 secure flags)."""
    from olav.core.auth import get_auth_provider

    mode = _get_auth_mode()
    if mode == "none":
        # No auth configured — redirect to home
        resp = RedirectResponse(url="/", status_code=302)
        return resp

    provider = get_auth_provider(mode)
    identity = provider.authenticate(token=body.token)
    if identity.source != "token":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )

    # GAP-4: secure cookie flags
    resp = RedirectResponse(url="/", status_code=302)
    _set_session_cookie(resp, body.token, request)
    return resp


def _set_session_cookie(
    response: Response, token: str, request: Request | None = None
) -> None:
    """Set olav_session cookie with GAP-4 security flags.

    ``secure`` is set dynamically: True only when the request arrived over
    HTTPS.  This prevents the browser from silently discarding the cookie
    when the server is accessed via plain HTTP (common in dev/LAN setups).
    """
    try:
        from olav.core.config import ConfigLoader

        ttl_hours = ConfigLoader().auth.session_ttl_hours
    except Exception:
        ttl_hours = 24
    is_https = request is not None and request.url.scheme == "https"
    response.set_cookie(
        key="olav_session",
        value=token,
        httponly=True,       # GAP-4: block JS access
        secure=is_https,     # GAP-4: only set Secure flag over HTTPS
        samesite="lax",      # "strict" drops cookie on cross-site redirects
        max_age=ttl_hours * 3600,
        path="/",
    )


def _minimal_login_html() -> str:
    """Fallback inline login page when static/login.html is missing."""
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
# Thread & run endpoints (P1: Bearer auth required)
# ---------------------------------------------------------------------------


@app.post("/threads")
async def create_thread(
    body: ThreadCreate,
    identity: UserIdentity = Depends(_require_auth),
):
    thread_id = str(uuid.uuid4())
    return {"thread_id": thread_id, "metadata": body.metadata or {}}


@app.get("/threads/search")
async def search_threads(identity: UserIdentity = Depends(_require_auth)):
    try:
        agent = await get_agent()
    except Exception:
        return {"threads": []}
    checkpointer = getattr(agent, "checkpointer", None)
    if checkpointer is None or not hasattr(checkpointer, "list_threads"):
        return {"threads": []}
    try:
        threads = await checkpointer.list_threads()
    except Exception:
        threads = []
    return {"threads": threads}


@app.post("/threads/{thread_id}/runs/stream")
async def stream_run(
    thread_id: str,
    body: RunStreamRequest,
    identity: UserIdentity = Depends(_require_auth),
):
    _check_thread_access(thread_id, identity)
    agent = await get_agent()

    # Use authenticated identity as user_id (P1)
    effective_user_id = identity.username if hasattr(identity, "username") else body.user_id

    run_id = str(uuid.uuid4())
    recorder = AuditEventRecorder()
    recorder.record_run_start(
        run_id=run_id,
        agent_id=body.assistant_id,
        user_id=effective_user_id,
        source_channel="api",
    )
    recorder.record(
        event_type="user_input_received",
        run_id=run_id,
        agent_id=body.assistant_id,
        payload=body.input,
    )
    # Record user turn in audit_messages for dataset export
    _user_content = ""
    if isinstance(body.input, dict):
        _msgs = body.input.get("messages", [])
        if _msgs:
            _last = _msgs[-1]
            _user_content = (
                _last.get("content", "") if isinstance(_last, dict)
                else str(getattr(_last, "content", ""))
            )
    if _user_content:
        recorder.record_message(run_id=run_id, role="user", content=_user_content)

    # Bind the top-level run context to AuditCallbackPlugin so tool events
    # and LLM responses are linked to this run_id.
    from olav.plugins.callbacks.audit import AuditCallbackPlugin as _AuditCBPlugin
    _audit_cbs = [
        _cb for _cb in (
            agent.plugin_registry.get_callback_plugins()
            if hasattr(agent, "plugin_registry") else []
        )
        if isinstance(_cb, _AuditCBPlugin)
    ]
    for _cb in _audit_cbs:
        _cb.bind_run(run_id, recorder)

    callbacks = (
        agent.plugin_registry.get_callback_plugins() if hasattr(agent, "plugin_registry") else []
    )

    async def event_generator():
        try:
            config = {
                "configurable": {"thread_id": thread_id},
                "callbacks": callbacks,
            }

            async for event in agent.graph.astream_events(
                body.input,
                config=config,
                version="v2",
                stream_subgraphs=True,
            ):
                event_type = event.get("event", "unknown")
                event_data = event.get("data", {})

                # Custom JSON encoder for LangChain objects
                def encode_obj(obj):
                    if hasattr(obj, "model_dump"):
                        return obj.model_dump()
                    if hasattr(obj, "dict"):
                        return obj.dict()
                    if hasattr(obj, "__dict__"):
                        return vars(obj)
                    return str(obj)

                # Serialize event data
                try:
                    json.dumps(event_data)
                    sse_event = {"event": event_type, "data": event_data}
                except (TypeError, ValueError):
                    try:
                        sse_event = {
                            "event": event_type,
                            "data": json.loads(json.dumps(event_data, default=encode_obj)),
                        }
                    except Exception:
                        sse_event = {
                            "event": event_type,
                            "data": {
                                "_serialization_error": str(type(event_data)),
                                "message": str(event_data)[:200],
                            },
                        }

                yield f"data: {json.dumps(sse_event)}\n\n"

            recorder.record(
                event_type="assistant_output_final",
                run_id=run_id,
                agent_id=body.assistant_id,
                payload={},
            )
            recorder.record_run_end(run_id=run_id, status="completed")
        except Exception as e:
            recorder.record_run_end(run_id=run_id, status="error")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            for _cb in _audit_cbs:
                _cb.unbind_run()
            recorder.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/runs/stream")
async def threadless_stream(
    body: RunStreamRequest,
    identity: UserIdentity = Depends(_require_auth),
):
    thread_id = body.thread_id or str(uuid.uuid4())
    body.thread_id = thread_id
    return await stream_run(thread_id, body, identity)


if __name__ == "__main__":
    import uvicorn

    from olav.core.defaults import DEFAULT_WEB_PORT

    uvicorn.run(app, host="0.0.0.0", port=DEFAULT_WEB_PORT)
