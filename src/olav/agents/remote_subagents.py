"""remote_subagents.py — Load remote LangGraph deployments as async subagents.

Reads the ``async_subagents`` section from the OLAV api.json config and returns
a list of CompiledSubAgent-compatible dicts with a ``RemoteGraph`` runnable.

api.json schema::

    {
        "async_subagents": [
            {
                "name": "remote-ops",
                "description": "Remote ops agent on LangGraph Cloud",
                "url": "https://my-deployment.langsmith.com",
                "assistant_id": "ops",
                "api_key_env": "LANGGRAPH_API_KEY"
            }
        ]
    }

Environment variable fallback order for API key:
    1. Value of ``api_key_env`` env var (if ``api_key_env`` is set in config)
    2. ``LANGGRAPH_API_KEY``
    3. ``LANGSMITH_API_KEY``
    4. ``LANGCHAIN_API_KEY``
    5. None (RemoteGraph will raise if auth required)
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("olav.agents.remote_subagents")

# Lazy import: langgraph-sdk is an optional transitive dep
try:
    from langgraph.pregel.remote import RemoteGraph
except ImportError:
    RemoteGraph = None  # type: ignore[assignment,misc]


def load_remote_subagents(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Load remote async subagents from api.json config dict.

    Args:
        config: Parsed api.json dict (or any dict with ``async_subagents`` key).

    Returns:
        List of CompiledSubAgent-compatible dicts:
        ``{"name": str, "description": str, "runnable": RemoteGraph}``
        Entries that fail validation or construction are skipped with a warning.
    """
    entries = config.get("async_subagents") or []
    if not entries:
        return []

    if RemoteGraph is None:
        logger.warning(
            "langgraph-sdk not available; remote subagents skipped. "
            "Install with: pip install langgraph-sdk"
        )
        return []

    result: list[dict[str, Any]] = []
    for entry in entries:
        name = entry.get("name", "<unnamed>")
        url = entry.get("url")
        assistant_id = entry.get("assistant_id")

        if not url:
            logger.warning(
                "Remote subagent '%s' skipped: missing required field 'url'", name
            )
            continue
        if not assistant_id:
            logger.warning(
                "Remote subagent '%s' skipped: missing required field 'assistant_id'", name
            )
            continue

        # Resolve API key
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

        try:
            runnable = RemoteGraph(
                assistant_id,
                url=url,
                api_key=api_key,
            )
            result.append({
                "name": name,
                "description": description,
                "runnable": runnable,
            })
            logger.info("✓ Remote subagent '%s' loaded from %s", name, url)
        except Exception as exc:
            logger.warning(
                "Remote subagent '%s' failed to initialize (%s): %s",
                name, url, exc,
            )

    return result
