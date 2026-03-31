"""Unit tests for run_migrate() in olav-netops/scripts/netops_migrate.py.

Contracts:
1. run_migrate is importable from netops_migrate.py
2. Returns 0 when migration succeeds on a valid (tmp) DuckDB file
3. Returns 0 with explicit --db path (custom db_path argument)
4. Calls migrate(conn) exactly once per invocation
5. Script __name__ guard prevents execution on import
"""

from __future__ import annotations

import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import helper — netops_migrate.py is a script (not a package module)
# ---------------------------------------------------------------------------


def _load_migrate() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "olav-netops" / "scripts" / "netops_migrate.py"
    spec = importlib.util.spec_from_file_location("netops_migrate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@contextmanager
def _mock_deps(db_file: Path):
    """Context manager that mocks duckdb + migration module together.

    Yields (fake_migrate, fake_conn) so callers can assert on them.
    """
    fake_migrate = MagicMock()
    fake_conn = MagicMock()
    fake_conn.__enter__ = MagicMock(return_value=fake_conn)
    fake_conn.__exit__ = MagicMock(return_value=False)

    fake_duckdb = MagicMock()
    fake_duckdb.connect.return_value = fake_conn

    fake_migration_mod = MagicMock()
    fake_migration_mod.migrate = fake_migrate

    with patch.dict(
        sys.modules,
        {
            "duckdb": fake_duckdb,
            "olav_netops.migrations.v0_12_schema_split": fake_migration_mod,
        },
    ):
        yield fake_migrate, fake_conn, fake_duckdb


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_migrate_function_exists() -> None:
    """run_migrate must be importable from netops_migrate.py."""
    mod = _load_migrate()
    assert hasattr(mod, "run_migrate"), "run_migrate not found in netops_migrate.py"


def test_run_migrate_returns_zero_on_success(tmp_path: Path) -> None:
    """Returns 0 when migration completes without errors."""
    mod = _load_migrate()
    db_file = tmp_path / "test.duckdb"

    with _mock_deps(db_file) as (fake_migrate, _, __):
        result = mod.run_migrate(db_path=str(db_file))

    assert result == 0


def test_run_migrate_calls_migrate_once(tmp_path: Path) -> None:
    """migrate(conn) is called exactly once per run_migrate() call."""
    mod = _load_migrate()
    db_file = tmp_path / "test.duckdb"

    with _mock_deps(db_file) as (fake_migrate, _, __):
        mod.run_migrate(db_path=str(db_file))

    assert fake_migrate.call_count == 1


def test_run_migrate_uses_provided_db_path(tmp_path: Path) -> None:
    """run_migrate resolves and uses the db_path argument correctly."""
    mod = _load_migrate()
    db_file = tmp_path / "custom.duckdb"

    with _mock_deps(db_file) as (_, __, fake_duckdb):
        mod.run_migrate(db_path=str(db_file))

    # duckdb.connect was called once
    assert fake_duckdb.connect.call_count == 1
    # The path passed to connect contains the expected filename
    connect_arg = str(fake_duckdb.connect.call_args[0][0])
    assert "custom.duckdb" in connect_arg


def test_run_migrate_idempotent(tmp_path: Path) -> None:
    """Calling run_migrate twice returns 0 both times."""
    mod = _load_migrate()
    db_file = tmp_path / "test.duckdb"

    with _mock_deps(db_file) as (fake_migrate, _, __):
        r1 = mod.run_migrate(db_path=str(db_file))
        r2 = mod.run_migrate(db_path=str(db_file))

    assert r1 == 0
    assert r2 == 0
    assert fake_migrate.call_count == 2
