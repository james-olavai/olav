"""
Async-compatible DuckDB Checkpointer for OLAV.

LangGraph's DuckDBSaver only has sync checkpoint methods (get_tuple, list, put).
The base class raises NotImplementedError for all aget_* methods.

This module wraps DuckDBSaver with asyncio.to_thread() so that LangGraph's
async graph execution (graph.ainvoke) can work correctly with DuckDB.

Usage:
    from olav.core.checkpointer import create_checkpointer

    checkpointer = create_checkpointer(agent_id="ops")
    graph = create_deep_agent(..., checkpointer=checkpointer)
"""

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.duckdb import DuckDBSaver

logger = logging.getLogger(__name__)


class AsyncDuckDBSaver(DuckDBSaver):
    """
    DuckDBSaver with async wrappers using asyncio.to_thread().

    LangGraph requires async checkpointer methods for graph.ainvoke().
    DuckDBSaver only implements sync methods. This class bridges the gap
    by running sync DuckDB operations in a thread pool, making them
    awaitable without blocking the event loop.

    Thread safety: DuckDB connections are not thread-safe by default.
    We use a per-instance lock to ensure single-threaded DB access.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock = asyncio.Lock()

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """Async wrapper for get_tuple using asyncio.to_thread."""
        async with self._lock:
            return await asyncio.to_thread(self.get_tuple, config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """Async wrapper for list — collects all items in thread, yields async."""
        async with self._lock:
            items = await asyncio.to_thread(
                lambda: list(self.list(config, filter=filter, before=before, limit=limit))
            )
        for item in items:
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: dict[str, Any],
    ) -> RunnableConfig:
        """Async wrapper for put using asyncio.to_thread."""
        async with self._lock:
            return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: list[tuple[str, Any]],
        task_id: str,
    ) -> None:
        """Async wrapper for put_writes using asyncio.to_thread."""
        async with self._lock:
            return await asyncio.to_thread(self.put_writes, config, writes, task_id)

    async def list_threads(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return distinct threads with their latest checkpoint_id as updated_at.

        Queries the checkpoints table and returns one entry per thread_id,
        using the lexicographically maximum checkpoint_id (ISO timestamp) as
        updated_at.  This provides a lightweight thread discovery API that
        does not parse checkpoint blobs.

        Args:
            limit: Maximum number of threads to return (default 100).

        Returns:
            List of dicts with keys:
              - thread_id (str)
              - updated_at (str) — latest checkpoint_id for this thread
        """
        def _query() -> list[dict[str, Any]]:
            try:
                rows = self.conn.execute(
                    "SELECT thread_id, MAX(checkpoint_id) AS updated_at "
                    "FROM checkpoints "
                    "GROUP BY thread_id "
                    "ORDER BY updated_at DESC "
                    f"LIMIT {int(limit)}"
                ).fetchall()
                return [{"thread_id": r[0], "updated_at": r[1]} for r in rows]
            except Exception:
                return []

        async with self._lock:
            return await asyncio.to_thread(_query)


def create_checkpointer(
    agent_id: str,
    username: str | None = None,
    workspace: str = "core",
) -> AsyncDuckDBSaver | None:
    """
    Create a user-isolated AsyncDuckDBSaver for the given agent.

    Stores checkpoints in
    ~/.olav/checkpoints/{username}/{workspace}/{agent_id}/checkpoints.duckdb
    so each user + workspace combination gets its own isolated checkpoint store.
    Two workspaces with the same agent name (e.g. "quick") will never collide.

    Args:
        agent_id: Agent identifier (e.g., "ops", "quick").
        username: OS username. Defaults to $USER env var.
        workspace: Active workspace name. Defaults to "core".

    Returns:
        AsyncDuckDBSaver instance, or None if creation fails.
    """
    try:
        import duckdb

        if username is None:
            try:
                username = os.environ.get("USER") or os.getlogin()
            except Exception:
                username = os.environ.get("USERNAME", "default_user")

        checkpoint_dir = Path.home() / ".olav" / "checkpoints" / username / workspace / agent_id
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        db_path = checkpoint_dir / "checkpoints.duckdb"

        conn = duckdb.connect(str(db_path), read_only=False)
        saver = AsyncDuckDBSaver(conn)
        saver.setup()  # Create tables if not exist

        logger.info(f"✓ Checkpointer (DuckDB) initialized: {db_path}")
        return saver
    except Exception as e:
        logger.warning(f"AsyncDuckDBSaver init failed ({e}), checkpoints disabled.")
        return None
