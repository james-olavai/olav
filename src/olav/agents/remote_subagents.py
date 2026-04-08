"""remote_subagents.py — Load remote LangGraph deployments as async subagents.

Reads the ``async_subagents`` section from the OLAV api.json config and returns
a list of native ``AsyncSubAgent`` dicts (deepagents 0.5+).

Unlike the old approach (wrapping RemoteGraph as CompiledSubAgent), AsyncSubAgent
is non-blocking: the main agent dispatches tasks and can continue working while
the subagent runs in the background on a LangGraph Platform or self-hosted server.

api.json schema::

    {
        "async_subagents": [
            {
                "name": "remote-ops",
                "description": "Remote ops agent on LangGraph Cloud",
                "url": "https://my-deployment.langsmith.com",
                "graph_id": "ops",
                "api_key_env": "LANGGRAPH_API_KEY"
            }
        ]
    }

Fields:
    name:        Unique subagent name (used by main agent's task() tool).
    description: What the subagent does (shown to main agent for delegation).
    url:         Agent Protocol server URL (LangGraph Platform or self-hosted).
    graph_id:    Graph name or assistant ID on the remote server.
    api_key_env: (optional) Env var name to read the API key from.
                 Falls back to LANGGRAPH_API_KEY / LANGSMITH_API_KEY / LANGCHAIN_API_KEY.

Note: ``assistant_id`` is accepted as an alias for ``graph_id`` for backward compatibility.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("olav.agents.remote_subagents")


def load_remote_subagents(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Load remote async subagents from api.json config dict.

    Returns native ``AsyncSubAgent`` dicts (deepagents 0.5+ format).
    The deepagents ``AsyncSubAgentMiddleware`` handles authentication and
    non-blocking task dispatch via the LangGraph SDK.

    Args:
        config: Parsed api.json dict (or any dict with ``async_subagents`` key).

    Returns:
        List of AsyncSubAgent-compatible dicts:
        ``{"name": str, "description": str, "graph_id": str, "url": str, "headers": dict}``
        Entries that fail validation are skipped with a warning.
    """
    entries = config.get("async_subagents") or []
    if not entries:
        return []

    result: list[dict[str, Any]] = []
    for entry in entries:
        name = entry.get("name", "<unnamed>")
        url = entry.get("url")
        # Accept both graph_id (new) and assistant_id (backward compat)
        graph_id = entry.get("graph_id") or entry.get("assistant_id")

        if not url:
            logger.warning(
                "Remote subagent '%s' skipped: missing required field 'url'", name
            )
            continue
        if not graph_id:
            logger.warning(
                "Remote subagent '%s' skipped: missing required field 'graph_id'", name
            )
            continue

        # Resolve API key → inject as Authorization header if found
        api_key: str | None = None
        api_key_env = entry.get("api_key_env")
        if api_key_env:
            api_key = os.environ.get(api_key_env)
        if not api_key:
            api_key = (
                os.environ.get("LANGGRAPH_API_KEY")
                or os.environ.get("LANGSMITH_API_KEY")
                or os.environ.get("LANGCHAIN_API_KEY")
            )

        description = entry.get("description", f"Remote subagent: {name}")

        sa: dict[str, Any] = {
            "name": name,
            "description": description,
            "graph_id": graph_id,
            "url": url,
        }
        if api_key:
            sa["headers"] = {"x-api-key": api_key}

        result.append(sa)
        logger.info("✓ AsyncSubAgent '%s' registered → %s (graph: %s)", name, url, graph_id)

    return result
