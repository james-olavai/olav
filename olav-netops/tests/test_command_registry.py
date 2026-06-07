"""Unit tests for olav_netops.command_registry (R75 thin-shim version).

After R75, ``command_registry`` is a 2-function entry-point layer
delegating to :mod:`olav_netops.core.commands_sync`. The original
``CommandRegistry`` singleton (whitelist / blacklist / template
globbing) was deleted — its tests have been retired alongside.

These tests verify:
* ``reload_hook()`` calls ``sync_commands`` and returns its stats dict
* ``get_config_commands()`` queries ``netops.commands WHERE backup_only=true``
  and returns a sorted distinct list
* Both handle missing table / DB unavailable gracefully (fail-safe empty)
"""
from __future__ import annotations

import duckdb
import pytest

from olav_netops import command_registry as cr


# ──────────────────────────────────────────────────────────────────────────
# reload_hook
# ──────────────────────────────────────────────────────────────────────────

class TestReloadHook:
    def test_delegates_to_sync_commands(self, monkeypatch, tmp_path):
        """reload_hook opens MAIN_DB_PATH and forwards to sync_commands."""
        fake_db = tmp_path / "main.duckdb"
        monkeypatch.setattr("olav.core.config.MAIN_DB_PATH", str(fake_db))

        called = []
        def _fake_sync(conn):
            called.append(conn)
            return {
                "ntc": 100, "custom": 2, "pac": 1, "user": 5,
                "blacklisted": 0, "total": 108, "seeded": 2,
            }
        monkeypatch.setattr(
            "olav_netops.core.commands_sync.sync_commands", _fake_sync,
        )

        result = cr.reload_hook()
        assert result == {
            "ntc": 100, "custom": 2, "pac": 1, "user": 5,
            "blacklisted": 0, "total": 108, "seeded": 2,
        }
        assert len(called) == 1

    def test_db_error_returns_error_dict(self, monkeypatch):
        """Broken DB path → graceful ``{"error": ...}`` return."""
        monkeypatch.setattr(
            "olav.core.config.MAIN_DB_PATH",
            "/nonexistent/path/missing.duckdb",
        )
        def _boom(conn):
            raise RuntimeError("simulated failure")
        monkeypatch.setattr(
            "olav_netops.core.commands_sync.sync_commands", _boom,
        )
        result = cr.reload_hook()
        assert "error" in result

    def test_import_failure_returns_error_dict(self, monkeypatch):
        """Missing olav.core.config import → error dict, no exception."""
        import sys
        # Temporarily sabotage the import so reload_hook's try/except kicks in.
        saved = sys.modules.get("olav.core.config")
        sys.modules["olav.core.config"] = None  # makes `from ... import` fail
        try:
            result = cr.reload_hook()
            assert "error" in result
        finally:
            if saved is not None:
                sys.modules["olav.core.config"] = saved
            else:
                sys.modules.pop("olav.core.config", None)


# ──────────────────────────────────────────────────────────────────────────
# get_config_commands
# ──────────────────────────────────────────────────────────────────────────

class TestGetConfigCommands:
    def _setup_table(self, db_path, rows):
        with duckdb.connect(str(db_path)) as c:
            c.execute("CREATE SCHEMA IF NOT EXISTS netops")
            c.execute(
                "CREATE TABLE netops.commands ("
                "platform VARCHAR, command VARCHAR, safe_command VARCHAR, "
                "parser_type VARCHAR, parser_path VARCHAR, "
                "blacklisted BOOLEAN, pipe_allowed BOOLEAN, "
                "backup_only BOOLEAN, synced_at TIMESTAMP)"
            )
            for row in rows:
                c.execute(
                    "INSERT INTO netops.commands VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                    row,
                )

    def test_returns_backup_only_commands(self, tmp_path, monkeypatch):
        db = tmp_path / "main.duckdb"
        self._setup_table(db, [
            ("cisco_ios", "show running-config", "show_running_config",
             "raw_only", None, False, True, True),
            ("cisco_ios", "show version", "show_version",
             "ntc", "/p", False, True, False),
            ("juniper_junos", "show configuration", "show_configuration",
             "raw_only", None, False, True, True),
        ])
        monkeypatch.setattr("olav.core.config.MAIN_DB_PATH", str(db))
        result = cr.get_config_commands()
        assert result == ["show configuration", "show running-config"]

    def test_returns_empty_when_table_absent(self, tmp_path, monkeypatch):
        db = tmp_path / "main.duckdb"
        # Create an empty DB — no netops.commands table
        with duckdb.connect(str(db)) as c:
            c.execute("CREATE SCHEMA netops")
        monkeypatch.setattr("olav.core.config.MAIN_DB_PATH", str(db))
        assert cr.get_config_commands() == []

    def test_returns_empty_on_db_path_missing(self, monkeypatch):
        monkeypatch.setattr(
            "olav.core.config.MAIN_DB_PATH",
            "/nonexistent/really/missing.duckdb",
        )
        assert cr.get_config_commands() == []

    def test_filters_non_backup_rows(self, tmp_path, monkeypatch):
        """Commands with backup_only=false must not appear."""
        db = tmp_path / "main.duckdb"
        self._setup_table(db, [
            ("cisco_ios", "show ip bgp summary", "show_ip_bgp_summary",
             "ntc", "/p", False, True, False),
            ("cisco_ios", "show interfaces", "show_interfaces",
             "ntc", "/p", False, True, False),
        ])
        monkeypatch.setattr("olav.core.config.MAIN_DB_PATH", str(db))
        assert cr.get_config_commands() == []

    def test_deduplicates_across_platforms(self, tmp_path, monkeypatch):
        """Same command on two platforms appears once."""
        db = tmp_path / "main.duckdb"
        self._setup_table(db, [
            ("cisco_ios", "show running-config", "show_running_config",
             "raw_only", None, False, True, True),
            ("cisco_xe", "show running-config", "show_running_config",
             "raw_only", None, False, True, True),
            ("cisco_nxos", "show running-config", "show_running_config",
             "raw_only", None, False, True, True),
        ])
        monkeypatch.setattr("olav.core.config.MAIN_DB_PATH", str(db))
        assert cr.get_config_commands() == ["show running-config"]


# ──────────────────────────────────────────────────────────────────────────
# Module surface — nothing else should be importable
# ──────────────────────────────────────────────────────────────────────────

class TestModuleSurface:
    def test_no_commandregistry_class(self):
        """R75: CommandRegistry singleton was deleted — no callers left."""
        assert not hasattr(cr, "CommandRegistry")

    def test_retired_helpers_gone(self):
        """Dead private helpers removed."""
        for name in ("_load_templates", "_load_whitelist", "_load_blacklist",
                     "_load_platform_commands", "_scan_templates"):
            assert not hasattr(cr, name), f"{name} should have been deleted"
