"""OLAV CLI invocation for E2E tests (programmatic, no subprocess)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


async def run_single_query(query: str, agent: str = "config") -> str:
    """Invoke OLAV agent programmatically.

    This is a thin wrapper around OLAV's CLI infrastructure.
    Uses deepagents_cli.execution directly (no subprocess).

    Args:
        query: Natural language query
        agent: Target agent ("config", "quick", "ops", etc.)

    Returns:
        Final assistant response as string

    Raises:
        ImportError: If OLAV dependencies are missing
    """
    try:
        from deepagents_cli.execution import execute_task
        from deepagents_cli.input import SessionState
        from deepagents_cli.ui import TokenTracker

        from olav.cli.main import create_olav_agent_with_backend
    except ImportError as exc:
        raise ImportError(
            "OLAV CLI dependencies missing. Ensure 'src' and 'olav-netops' are in PYTHONPATH."
        ) from exc

    # Create agent graph and backend
    agent_graph, backend = create_olav_agent_with_backend(agent)

    # Auto-approve all tools in dev/test mode
    session_state = SessionState(auto_approve=True)
    token_tracker = TokenTracker()

    # Execute query through OLAV's full pipeline
    result = await execute_task(
        query,
        agent_graph,
        agent,
        session_state,
        token_tracker,
        backend=backend,
    )

    return str(result) if result is not None else ""


def run_query_sync(query: str, agent: str = "config") -> str:
    """Synchronous wrapper for run_single_query (for non-async contexts)."""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(run_single_query(query, agent))
