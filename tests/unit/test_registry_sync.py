"""Unit tests for olav.platform.services.registry_sync.

Covers:
  * upsert_service writes to api_registry.services
  * delete_service removes the row
  * bootstrap_from_yaml syncs all entries from services.yaml
  * bootstrap_from_yaml is idempotent (re-run = no duplicates)
  * missing services.yaml returns empty summary
  * malformed entry is skipped, others still sync
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers — in-memory DuckDB fixture
# ---------------------------------------------------------------------------


class _NoCloseConn:
    """Wrapper that forwards all DuckDB calls except close() to avoid
    destroying the shared in-memory connection between test calls."""
    def __init__(self, con):
        self._con = con

    def execute(self, *a, **kw):
        return self._con.execute(*a, **kw)

    def close(self):
        pass  # intentionally suppress — fixture owns the lifecycle


@pytest.fixture()
def mem_db(monkeypatch, tmp_path):
    """Patch registry_sync to use an in-memory DuckDB instead of main.duckdb."""
    import duckdb

    con = duckdb.connect(":memory:")

    from contextlib import contextmanager

    @contextmanager
    def _open_main_db(read_only: bool = False):
        # Production _open_main_db is a @contextmanager (ADR-0018/0019 write seam);
        # the fake mirrors that contract, yielding a shared no-close connection.
        from olav.platform.services.registry_sync import _DDL
        for stmt in _DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                con.execute(stmt)
        yield _NoCloseConn(con)

    import olav.platform.services.registry_sync as mod
    monkeypatch.setattr(mod, "_open_main_db", _open_main_db)
    yield con
    con.close()


def _rows(con) -> list[tuple]:
    return con.execute(
        "SELECT name, endpoint, readonly_only, auth_type FROM api_registry.services ORDER BY name"
    ).fetchall()


# ---------------------------------------------------------------------------
# upsert_service
# ---------------------------------------------------------------------------


class TestUpsertService:
    def test_inserts_new_row(self, mem_db):
        from olav.platform.services.registry_sync import upsert_service
        upsert_service("netbox", {"endpoint": "http://localhost:8000", "readonly_only": True,
                                   "auth": {"type": "bearer", "token_env": "NETBOX_TOKEN"}})
        rows = _rows(mem_db)
        assert len(rows) == 1
        assert rows[0][0] == "netbox"
        assert rows[0][1] == "http://localhost:8000"
        assert rows[0][2] is True
        assert rows[0][3] == "bearer"

    def test_updates_existing_row(self, mem_db):
        from olav.platform.services.registry_sync import upsert_service
        upsert_service("svc", {"endpoint": "http://old:8000"})
        upsert_service("svc", {"endpoint": "http://new:9000"})
        rows = _rows(mem_db)
        assert len(rows) == 1
        assert rows[0][1] == "http://new:9000"

    def test_readonly_only_defaults_false(self, mem_db):
        from olav.platform.services.registry_sync import upsert_service
        upsert_service("svc", {"endpoint": "http://x"})
        rows = _rows(mem_db)
        assert rows[0][2] is False

    def test_db_failure_is_silent(self, monkeypatch):
        """upsert_service must not raise when DuckDB is unavailable."""
        import olav.platform.services.registry_sync as mod
        monkeypatch.setattr(mod, "_open_main_db", lambda **kw: (_ for _ in ()).throw(Exception("db down")))
        # Should not raise
        mod.upsert_service("svc", {"endpoint": "http://x"})


# ---------------------------------------------------------------------------
# delete_service
# ---------------------------------------------------------------------------


class TestDeleteService:
    def test_removes_existing_row(self, mem_db):
        from olav.platform.services.registry_sync import upsert_service, delete_service
        upsert_service("svc", {"endpoint": "http://x"})
        assert len(_rows(mem_db)) == 1
        delete_service("svc")
        assert len(_rows(mem_db)) == 0

    def test_delete_nonexistent_is_noop(self, mem_db):
        from olav.platform.services.registry_sync import delete_service
        delete_service("does-not-exist")  # must not raise
        assert len(_rows(mem_db)) == 0

    def test_db_failure_is_silent(self, monkeypatch):
        import olav.platform.services.registry_sync as mod
        monkeypatch.setattr(mod, "_open_main_db", lambda **kw: (_ for _ in ()).throw(Exception("db down")))
        mod.delete_service("svc")  # must not raise


# ---------------------------------------------------------------------------
# bootstrap_from_yaml
# ---------------------------------------------------------------------------


def _make_services_yaml(tmp_path: Path, services: dict) -> Path:
    import yaml
    path = tmp_path / "services.yaml"
    path.write_text(yaml.safe_dump({"services": services}), encoding="utf-8")
    return path


class TestBootstrapFromYaml:
    def test_syncs_all_entries(self, mem_db, monkeypatch, tmp_path):
        import olav.platform.services.registry_sync as mod
        yaml_path = _make_services_yaml(tmp_path, {
            "netbox": {"endpoint": "http://netbox:8000", "readonly_only": True,
                       "auth": {"type": "bearer", "token_env": "NETBOX_TOKEN"}},
            "gitea":  {"endpoint": "http://gitea:3000"},
        })
        monkeypatch.setattr(mod, "_load_services_yaml",
                            lambda: __import__("yaml").safe_load(yaml_path.read_text())["services"])
        result = mod.bootstrap_from_yaml()
        assert result["status"] == "ok"
        assert result["synced"] == 2
        assert len(_rows(mem_db)) == 2

    def test_is_idempotent(self, mem_db, monkeypatch, tmp_path):
        import olav.platform.services.registry_sync as mod
        yaml_path = _make_services_yaml(tmp_path, {
            "svc": {"endpoint": "http://svc:1234"},
        })
        loader = lambda: __import__("yaml").safe_load(yaml_path.read_text())["services"]
        monkeypatch.setattr(mod, "_load_services_yaml", loader)
        mod.bootstrap_from_yaml()
        mod.bootstrap_from_yaml()  # second run
        assert len(_rows(mem_db)) == 1  # no duplicate

    def test_empty_yaml_returns_empty_summary(self, mem_db, monkeypatch):
        import olav.platform.services.registry_sync as mod
        monkeypatch.setattr(mod, "_load_services_yaml", lambda: {})
        result = mod.bootstrap_from_yaml()
        assert result["synced"] == 0

    def test_partial_failure_reported(self, mem_db, monkeypatch, tmp_path):
        """If one entry errors, others still sync and status is 'partial'."""
        import olav.platform.services.registry_sync as mod

        call_count = [0]
        original_upsert = mod.upsert_service

        def flaky_upsert(name, entry):
            call_count[0] += 1
            if name == "bad":
                raise RuntimeError("boom")
            original_upsert(name, entry)

        monkeypatch.setattr(mod, "upsert_service", flaky_upsert)
        monkeypatch.setattr(mod, "_load_services_yaml", lambda: {
            "good": {"endpoint": "http://good"},
            "bad":  {"endpoint": "http://bad"},
        })
        result = mod.bootstrap_from_yaml()
        assert result["status"] == "partial"
        assert result["synced"] == 1
        assert result["skipped"] == 1
