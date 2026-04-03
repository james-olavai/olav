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

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from olav.core.audit_recorder import AuditEventRecorder
from olav.core.auth import UserIdentity, get_auth_provider

_STATIC_DIR = Path(__file__).parent / "static"

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
    credentials: HTTPAuthorizationCredentials | None = None,
) -> UserIdentity:
    if credentials is None:
        credentials = await _bearer_scheme(Request({"type": "http", "headers": []}))
    return _verify_bearer(credentials)


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
# Routes
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def root(request: Request):
    """Serve the built-in chat UI (all assets are inlined).

    If auth.mode != 'none' and no valid cookie/token, redirect to /login.
    """
    # P3: check session cookie when WebUI mode active
    if _get_auth_mode() != "none":
        session_token = request.cookies.get("olav_session")
        if not session_token:
            url_token = request.query_params.get("token")
            if url_token:
                # JupyterLab-style: ?token= sets cookie then redirects clean
                resp = RedirectResponse(url="/", status_code=302)
                _set_session_cookie(resp, url_token)
                return resp
            return RedirectResponse(url="/login")
    index = _STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index), media_type="text/html")
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "olav-api"}


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
async def login_submit(body: LoginRequest, response: Response):
    """Validate token, write session cookie (P3, GAP-4 secure flags)."""
    from olav.core.auth import get_auth_provider

    mode = _get_auth_mode()
    if mode == "none":
        # No auth configured — redirect to home
        resp = RedirectResponse(url="/", status_code=302)
        return resp

    identity = get_auth_provider(mode).authenticate(token=body.token, source_channel="webui")
    if identity.source != "token":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )

    # GAP-4: secure cookie flags
    resp = RedirectResponse(url="/", status_code=302)
    _set_session_cookie(resp, body.token)
    return resp


def _set_session_cookie(response: Response, token: str) -> None:
    """Set olav_session cookie with GAP-4 security flags."""
    try:
        from olav.core.config import ConfigLoader

        ttl_hours = ConfigLoader().auth.session_ttl_hours
    except Exception:
        ttl_hours = 24
    response.set_cookie(
        key="olav_session",
        value=token,
        httponly=True,  # GAP-4: block JS access
        secure=False,  # Set True in production (HTTPS)
        samesite="strict",  # GAP-4: CSRF protection
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
    identity: Any | None = None,
):
    if identity is None:
        identity = await _require_auth()
    thread_id = str(uuid.uuid4())
    return {"thread_id": thread_id, "metadata": body.metadata or {}}


@app.get("/threads/search")
async def search_threads(identity: Any | None = None):
    if identity is None:
        identity = await _require_auth()
    agent = await get_agent()
    checkpointer = getattr(agent, "checkpointer", None)
    if checkpointer is None or not hasattr(checkpointer, "list_threads"):
        return {"threads": []}
    threads = await checkpointer.list_threads()
    return {"threads": threads}


@app.post("/threads/{thread_id}/runs/stream")
async def stream_run(
    thread_id: str,
    body: RunStreamRequest,
    identity: Any | None = None,
):
    if identity is None:
        identity = await _require_auth()
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
    identity: Any | None = None,
):
    if identity is None:
        identity = await _require_auth()
    thread_id = body.thread_id or str(uuid.uuid4())
    body.thread_id = thread_id
    return await stream_run(thread_id, body, identity)


if __name__ == "__main__":
    import uvicorn

    from olav.core.defaults import DEFAULT_WEB_PORT

    uvicorn.run(app, host="0.0.0.0", port=DEFAULT_WEB_PORT)
