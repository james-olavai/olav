"""OLAV ASGI entry point — boots native langgraph_api with OLAV configuration.

Sets LANGSERVE_GRAPHS, LANGGRAPH_HTTP, LANGGRAPH_AUTH and the inmem-runtime
env vars BEFORE importing langgraph_api.server, because that module reads
all configuration at import time via starlette.config.Config().

Usage:
    uvicorn olav.api.app:app --host 0.0.0.0 --port 2280

Replaces the legacy ``olav.api.server:app`` target.
"""

from __future__ import annotations

import json
import os

# ---------------------------------------------------------------------------
# 1. Discover installed OLAV agents
# ---------------------------------------------------------------------------

try:
    from olav.core.workspace_discovery import discover_agent_names  # noqa: PLC0415

    _agents = discover_agent_names() or ["core"]
except Exception:
    _agents = ["core"]

# ---------------------------------------------------------------------------
# 2. Set langgraph_api env vars BEFORE any langgraph_api import
# ---------------------------------------------------------------------------

# All agents share the same callable factory; graph_id dispatches internally.
_GRAPHS = {name: "olav.server.graph_factory:make_graph" for name in _agents}

os.environ.setdefault("LANGSERVE_GRAPHS", json.dumps(_GRAPHS))
os.environ.setdefault("LANGGRAPH_HTTP", json.dumps({"app": "olav.api.custom_router:app"}))
os.environ.setdefault(
    "LANGGRAPH_AUTH",
    json.dumps({"path": "olav.api.lg_auth:auth", "disable_studio_auth": True}),
)

# inmem runtime — no Postgres or Redis required (thread history lost on restart,
# which is acceptable per the explicit decision to defer persistence).
os.environ.setdefault("LANGGRAPH_RUNTIME_EDITION", "inmem")
os.environ.setdefault("DATABASE_URI", ":memory:")
os.environ.setdefault("REDIS_URI", "fake")
os.environ.setdefault("MIGRATIONS_PATH", "__inmem")
os.environ.setdefault("LANGSMITH_LANGGRAPH_API_VARIANT", "local_dev")

# ---------------------------------------------------------------------------
# 3. Import the native langgraph_api ASGI app — reads env vars at import time
# ---------------------------------------------------------------------------

from langgraph_api.server import app  # noqa: E402, F401  # re-exported

__all__ = ["app"]
