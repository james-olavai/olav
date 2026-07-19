"""batfish export config-command fallback — ISSUE-BATFISH-EXPORT-NEEDS-COMMANDS-WHITELIST.

export_configs picks each device's running-config from raw_output_store using
the netops.commands backup_only whitelist. When that whitelist is missing
(main.duckdb wiped, only device data re-imported) or unsynced, the export used
to feed Batfish zero configs → cryptic "No valid configurations found". It now
falls back to built-in per-platform defaults so a stripped DB still works.
"""
from __future__ import annotations

import duckdb
import pytest

from olav_netops.export.batfish import (
    _DEFAULT_BACKUP_COMMANDS,
    _candidate_backup_commands,
    _pick_config,
)


def _db_with_raw(tmp_path, *, with_commands_whitelist: bool):
    db = duckdb.connect(str(tmp_path / "main.duckdb"))
    db.execute("CREATE SCHEMA netops")
    db.execute(
        "CREATE TABLE netops.raw_output_store "
        "(device_name VARCHAR, command VARCHAR, raw_output VARCHAR, "
        " snapshot_id VARCHAR, updated_at TIMESTAMP)"
    )
    db.execute(
        "INSERT INTO netops.raw_output_store VALUES "
        "('r1', 'show running-config', 'hostname r1\\nrouter bgp 65000', 'snap1', NOW())"
    )
    if with_commands_whitelist:
        db.execute(
            "CREATE TABLE netops.commands "
            "(platform VARCHAR, command VARCHAR, backup_only BOOLEAN, blacklisted BOOLEAN)"
        )
        db.execute(
            "INSERT INTO netops.commands VALUES ('cisco_ios', 'show running-config', TRUE, FALSE)"
        )
    return db


def test_uses_db_whitelist_when_present(tmp_path):
    conn = _db_with_raw(tmp_path, with_commands_whitelist=True)
    cands, used_fallback = _candidate_backup_commands(conn, "cisco_ios")
    assert cands == ["show running-config"] and used_fallback is False


def test_falls_back_when_commands_table_missing(tmp_path):
    """The VM Ch4 failure: no netops.commands table at all → catalog error
    must be swallowed and defaults used, not propagated."""
    conn = _db_with_raw(tmp_path, with_commands_whitelist=False)
    cands, used_fallback = _candidate_backup_commands(conn, "cisco_ios")
    assert "show running-config" in cands and used_fallback is True


def test_falls_back_when_whitelist_has_no_backup_only(tmp_path):
    """Table exists but backup_only whitelist empty (unsynced overlay)."""
    conn = _db_with_raw(tmp_path, with_commands_whitelist=False)
    conn.execute(
        "CREATE TABLE netops.commands "
        "(platform VARCHAR, command VARCHAR, backup_only BOOLEAN, blacklisted BOOLEAN)"
    )
    conn.execute(
        "INSERT INTO netops.commands VALUES ('cisco_ios', 'show version', FALSE, FALSE)"
    )
    cands, used_fallback = _candidate_backup_commands(conn, "cisco_ios")
    assert cands == list(_DEFAULT_BACKUP_COMMANDS["cisco_ios"]) and used_fallback is True


def test_pick_config_resolves_running_config_via_fallback(tmp_path):
    """End-to-end for _pick_config: with NO whitelist, it still finds the
    device's running-config in raw_output_store via the default command."""
    conn = _db_with_raw(tmp_path, with_commands_whitelist=False)
    result = _pick_config(conn, "r1", "cisco_ios", snapshot_id="snap1")
    assert result is not None
    cmd, raw = result
    assert cmd == "show running-config" and "router bgp 65000" in raw


def test_unknown_platform_no_fallback(tmp_path):
    """A platform with no default and no whitelist yields nothing (correct —
    we don't guess a config command for vendors we don't model)."""
    conn = _db_with_raw(tmp_path, with_commands_whitelist=False)
    cands, used_fallback = _candidate_backup_commands(conn, "some_exotic_os")
    assert cands == [] and used_fallback is True
