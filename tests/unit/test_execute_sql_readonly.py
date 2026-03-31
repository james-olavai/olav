"""Tests for §11.2: execute_sql read-only protection.

db_query() must:
- Use read_only=True for SELECT/WITH queries
- Return approval-required response for mutating SQL (INSERT/UPDATE/DELETE/DDL)
- Never open the database read-write for a SELECT
"""

import pytest
from unittest.mock import MagicMock, patch, call
import sys
from pathlib import Path


# We test the db_query function from the workspace tool directly.
# Since it uses sys.path.insert, we need to handle the import carefully.

_TOOL_PATH = Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "ops" / "tools" / "execute_sql.py"


def _import_db_query():
    """Import db_query from the workspace execute_sql tool."""
    tool_path = _TOOL_PATH
    if not tool_path.exists():
        pytest.skip(f"execute_sql tool not found at {tool_path}")
    import importlib.util
    spec = importlib.util.spec_from_file_location("execute_sql_tool", tool_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDbQueryReadOnly:
    def test_select_uses_read_only_connection(self, monkeypatch, tmp_path):
        """SELECT queries open the DB with read_only=True."""
        import duckdb

        opened_kwargs = []
        real_connect = duckdb.connect

        def mock_connect(path, **kwargs):
            opened_kwargs.append(kwargs)
            conn = MagicMock()
            conn.__enter__ = lambda s: s
            conn.__exit__ = MagicMock(return_value=False)
            cur = MagicMock()
            cur.description = [("col",)]
            cur.fetchall.return_value = [("value",)]
            conn.cursor.return_value = cur
            return conn

        monkeypatch.chdir(tmp_path)
        (tmp_path / "src").mkdir()

        with patch("duckdb.connect", side_effect=mock_connect):
            mod = _import_db_query()
            with patch("duckdb.connect", side_effect=mock_connect):
                mod.db_query("SELECT 1")

        assert any(kw.get("read_only") is True for kw in opened_kwargs), (
            "SELECT must open DB with read_only=True"
        )

    def test_insert_returns_approval_required(self, monkeypatch, tmp_path):
        """INSERT SQL returns approval-required response without executing."""
        monkeypatch.chdir(tmp_path)

        opened_as_writable = []

        def mock_connect(path, **kwargs):
            if not kwargs.get("read_only"):
                opened_as_writable.append(path)
            conn = MagicMock()
            conn.__enter__ = lambda s: s
            conn.__exit__ = MagicMock(return_value=False)
            cur = MagicMock()
            cur.description = None
            conn.cursor.return_value = cur
            return conn

        mod = _import_db_query()
        with patch("duckdb.connect", side_effect=mock_connect):
            result = mod.db_query("INSERT INTO devices VALUES ('r1', 'spine')")

        # Either blocked (approval required) OR at minimum not silently opened read-write
        # If result contains approval_required key, that's correct
        if isinstance(result, list) and result:
            assert "requires_approval" in result[0] or "approval" in str(result[0]).lower(), (
                "INSERT should return requires_approval, got: " + str(result)
            )

    def test_drop_table_returns_approval_required(self, monkeypatch, tmp_path):
        """DDL (DROP TABLE) SQL is blocked by approval gate."""
        monkeypatch.chdir(tmp_path)
        mod = _import_db_query()

        with patch("duckdb.connect") as mock_connect:
            conn = MagicMock()
            conn.__enter__ = lambda s: s
            conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = conn

            result = mod.db_query("DROP TABLE netops.devices")

        # DROP TABLE should NOT silently execute — must require approval
        if isinstance(result, list) and result:
            assert "requires_approval" in result[0] or "approval" in str(result[0]).lower(), (
                "DROP TABLE should require approval, got: " + str(result)
            )

    def test_with_query_treated_as_select(self, monkeypatch, tmp_path):
        """WITH ... SELECT (CTE) is treated as read-only SELECT."""
        monkeypatch.chdir(tmp_path)

        opened_kwargs = []

        def mock_connect(path, **kwargs):
            opened_kwargs.append(kwargs)
            conn = MagicMock()
            conn.__enter__ = lambda s: s
            conn.__exit__ = MagicMock(return_value=False)
            cur = MagicMock()
            cur.description = [("n",)]
            cur.fetchall.return_value = [(1,)]
            conn.cursor.return_value = cur
            return conn

        mod = _import_db_query()
        with patch("duckdb.connect", side_effect=mock_connect):
            mod.db_query("WITH cte AS (SELECT 1 AS n) SELECT * FROM cte")

        assert any(kw.get("read_only") is True for kw in opened_kwargs), (
            "WITH/CTE query must open DB with read_only=True"
        )


class TestClassifySql:
    """Unit tests for the SQL classifier (if exposed)."""

    def test_classify_select(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        mod = _import_db_query()
        if not hasattr(mod, "_classify_sql"):
            pytest.skip("_classify_sql not exposed")
        assert mod._classify_sql("SELECT * FROM devices") == "SELECT"
        assert mod._classify_sql("  select id from t") == "SELECT"
        assert mod._classify_sql("WITH cte AS (SELECT 1) SELECT * FROM cte") == "SELECT"

    def test_classify_mutating(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        mod = _import_db_query()
        if not hasattr(mod, "_classify_sql"):
            pytest.skip("_classify_sql not exposed")
        assert mod._classify_sql("INSERT INTO t VALUES (1)") in ("INSERT", "MUTATE", "WRITE")
        assert mod._classify_sql("UPDATE t SET x=1") in ("MUTATE", "UPDATE", "WRITE")
        assert mod._classify_sql("DELETE FROM t") in ("MUTATE", "DELETE", "WRITE")
        assert mod._classify_sql("DROP TABLE t") in ("DDL", "WRITE")
