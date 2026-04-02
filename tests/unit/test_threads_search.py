"""
TDD: CC-02 — /threads/search 返回真实 checkpointer thread 列表

验收标准:
  1. GET /threads/search 返回 {"threads": [...]} 非空列表（当有保存的 thread 时）
  2. 每个 thread 包含 thread_id 和 updated_at 字段
  3. 没有 thread 时返回 {"threads": []}
  4. AsyncDuckDBSaver.list_threads() 可用且返回正确结构
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Unit tests: AsyncDuckDBSaver.list_threads()
# ---------------------------------------------------------------------------


class TestAsyncDuckDBSaverListThreads:
    def test_list_threads_empty(self, tmp_path):
        """Empty DB returns empty list."""
        from olav.core.checkpointer import AsyncDuckDBSaver

        db_path = tmp_path / "test.duckdb"
        conn = duckdb.connect(str(db_path))
        saver = AsyncDuckDBSaver(conn)
        saver.setup()

        threads = asyncio.run(saver.list_threads())
        assert threads == []

    def test_list_threads_returns_thread_id_and_updated_at(self, tmp_path):
        """DB with one checkpoint returns thread with thread_id and updated_at."""
        from olav.core.checkpointer import AsyncDuckDBSaver

        db_path = tmp_path / "test.duckdb"
        conn = duckdb.connect(str(db_path))
        saver = AsyncDuckDBSaver(conn)
        saver.setup()

        # Manually insert a checkpoint row
        conn.execute(
            "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, checkpoint, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            ["thread-abc", "", "2024-01-01T00:00:00.000000+00:00", '{}', '{}'],
        )

        threads = asyncio.run(saver.list_threads())
        assert len(threads) == 1
        t = threads[0]
        assert t["thread_id"] == "thread-abc"
        assert "updated_at" in t

    def test_list_threads_deduplicates_multiple_checkpoints(self, tmp_path):
        """Multiple checkpoints for same thread → one entry with latest checkpoint_id."""
        from olav.core.checkpointer import AsyncDuckDBSaver

        db_path = tmp_path / "test.duckdb"
        conn = duckdb.connect(str(db_path))
        saver = AsyncDuckDBSaver(conn)
        saver.setup()

        # Insert two checkpoints for same thread
        for cid in ["2024-01-01T00:00:00.000000+00:00", "2024-01-02T00:00:00.000000+00:00"]:
            conn.execute(
                "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, checkpoint, metadata) "
                "VALUES (?, ?, ?, ?, ?)",
                ["thread-abc", "", cid, '{}', '{}'],
            )

        threads = asyncio.run(saver.list_threads())
        assert len(threads) == 1
        assert threads[0]["updated_at"] == "2024-01-02T00:00:00.000000+00:00"

    def test_list_threads_multiple_distinct_threads(self, tmp_path):
        """Multiple distinct threads each get their own entry."""
        from olav.core.checkpointer import AsyncDuckDBSaver

        db_path = tmp_path / "test.duckdb"
        conn = duckdb.connect(str(db_path))
        saver = AsyncDuckDBSaver(conn)
        saver.setup()

        for tid in ["thread-1", "thread-2", "thread-3"]:
            conn.execute(
                "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, checkpoint, metadata) "
                "VALUES (?, ?, ?, ?, ?)",
                [tid, "", "2024-01-01T00:00:00.000000+00:00", '{}', '{}'],
            )

        threads = asyncio.run(saver.list_threads())
        thread_ids = {t["thread_id"] for t in threads}
        assert thread_ids == {"thread-1", "thread-2", "thread-3"}


# ---------------------------------------------------------------------------
# Integration tests: GET /threads/search endpoint
# ---------------------------------------------------------------------------


class TestThreadsSearchEndpoint:
    def _make_client(self, mock_checkpointer):
        """Create a FastAPI test client with a patched checkpointer."""
        from olav.api.server import app

        return TestClient(app, raise_server_exceptions=False)

    def test_search_threads_returns_non_empty_when_threads_exist(self, tmp_path, monkeypatch):
        """GET /threads/search returns threads list when checkpointer has entries."""
        from olav.core.checkpointer import AsyncDuckDBSaver

        db_path = tmp_path / "test.duckdb"
        conn = duckdb.connect(str(db_path))
        saver = AsyncDuckDBSaver(conn)
        saver.setup()
        conn.execute(
            "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, checkpoint, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            ["thread-xyz", "", "2024-01-01T00:00:00.000000+00:00", '{}', '{}'],
        )

        from olav.api import server as server_module

        async def fake_get_agent():
            agent = MagicMock()
            agent.checkpointer = saver
            return agent

        monkeypatch.setattr(server_module, "get_agent", fake_get_agent)

        # Bypass auth
        from unittest.mock import AsyncMock
        fake_identity = MagicMock()
        fake_identity.username = "testuser"
        monkeypatch.setattr(server_module, "_require_auth", AsyncMock(return_value=fake_identity))

        from olav.api.server import app
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/threads/search")
        assert resp.status_code == 200
        data = resp.json()
        assert "threads" in data
        assert len(data["threads"]) == 1
        assert data["threads"][0]["thread_id"] == "thread-xyz"

    def test_search_threads_returns_empty_list_when_no_threads(self, monkeypatch):
        """GET /threads/search returns empty threads list when no checkpoints."""
        from olav.api import server as server_module
        from olav.core.checkpointer import AsyncDuckDBSaver
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            conn = duckdb.connect(f"{d}/test.duckdb")
            saver = AsyncDuckDBSaver(conn)
            saver.setup()

            async def fake_get_agent():
                agent = MagicMock()
                agent.checkpointer = saver
                return agent

            monkeypatch.setattr(server_module, "get_agent", fake_get_agent)

            fake_identity = MagicMock()
            fake_identity.username = "testuser"
            monkeypatch.setattr(server_module, "_require_auth", AsyncMock(return_value=fake_identity))

            from olav.api.server import app
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.get("/threads/search")
            assert resp.status_code == 200
            data = resp.json()
            assert data == {"threads": []}
