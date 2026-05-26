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
import logging
import os

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Discover installed OLAV agents
# ---------------------------------------------------------------------------

try:
    from olav.core.workspace_discovery import discover_top_level_agent_names  # noqa: PLC0415

    _agents = discover_top_level_agent_names() or ["core"]
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

# Private langgraph_api env vars — all set via the compat shim so that
# version upgrades only need to touch one file.
from olav.api._lg_compat import apply_lg_env_defaults  # noqa: PLC0415
apply_lg_env_defaults()

# ---------------------------------------------------------------------------
# 3. Pre-warm graph cache and ConfigLoader BEFORE the event loop starts.
#
# langgraph_api calls make_graph(config) from the async event loop on every
# run request. If make_graph() does blocking filesystem I/O there, blockbuster
# (langgraph_api's async I/O detector) raises an exception. Solution: build
# all graphs here in the main thread (synchronous import context = no event
# loop = no blockbuster). By the time the event loop accepts the first request,
# _graph_cache is fully populated and make_graph() is a pure dict lookup.
#
# This replaces the previous workaround of LANGGRAPH_ALLOW_BLOCKING=true.
# ---------------------------------------------------------------------------

try:
    from olav.core.config import ConfigLoader  # noqa: PLC0415

    ConfigLoader()  # prime the singleton; subsequent calls are in-memory
except Exception:
    pass

try:
    from olav.server.graph_factory import _graph_cache, build_graph  # noqa: PLC0415

    for _name in _agents:
        if _name not in _graph_cache:
            try:
                _graph_cache[_name] = build_graph(_name)
                _logger.info("app.py: pre-warmed graph cache for agent=%s", _name)
            except Exception as _exc:
                _logger.warning("app.py: failed to pre-warm graph for agent=%s: %s", _name, _exc)
except Exception as _exc:
    _logger.warning("app.py: graph pre-warm skipped: %s", _exc)

# ---------------------------------------------------------------------------
# 4. Import the native langgraph_api ASGI app — reads env vars at import time
# ---------------------------------------------------------------------------

from langgraph_api.server import app  # noqa: E402, F401  # re-exported

__all__ = ["app"]
