"""langgraph_api private env-var compatibility shim.

All private/undocumented ``langgraph_api`` env vars are set HERE, in one
place, so that ``langgraph-api`` version upgrades only need to touch this
file.  Each var is annotated with the version it was verified against.

Called by ``olav.api.app`` BEFORE any ``langgraph_api`` import, because
``langgraph_api.server`` reads these at import time via
``starlette.config.Config()``.
"""

from __future__ import annotations

import os


def apply_lg_env_defaults() -> None:
    """Set langgraph_api private env vars if not already present.

    Uses ``os.environ.setdefault`` so that operator overrides via the
    process environment are respected.

    Verified against: langgraph-api>=0.7.100
    """
    # inmem runtime — no Postgres or Redis required.
    # Thread history is lost on restart; that's an explicit design choice
    # (deferred persistence per ADR-0001).
    os.environ.setdefault("LANGGRAPH_RUNTIME_EDITION", "inmem")  # verified 0.7.100
    os.environ.setdefault("DATABASE_URI", ":memory:")             # verified 0.7.100
    os.environ.setdefault("REDIS_URI", "fake")                    # verified 0.7.100
    os.environ.setdefault("MIGRATIONS_PATH", "__inmem")           # verified 0.7.100

    # Selects the local-dev variant of the LangSmith/LangGraph API surface.
    # Controls which SSE event shapes are emitted and which auth flows are
    # active.  "local_dev" disables cloud-only billing hooks.
    os.environ.setdefault(
        "LANGSMITH_LANGGRAPH_API_VARIANT", "local_dev"            # verified 0.7.100
    )
