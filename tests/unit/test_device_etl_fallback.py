"""``populate_devices`` model/platform fallback chain.

Pinned behaviour:
  * When ``show version`` parsed_outputs row is missing, fall back to
    ``show inventory`` parsed_outputs and extract PID → model.  Cisco
    PID prefixes (C9800-, C9300, etc.) infer ``platform = cisco_ios``.
  * When neither show_version nor show_inventory exist, trust
    ``raw_output_store.platform`` (auto-discovery already wrote it).
  * Was the WLC fix — both Catalyst 9800 WLCs in the inbox dataset
    had show_inventory but no show_version, so the old chain left
    ``netops.devices.platform = 'unknown'`` even though
    raw_output_store correctly tagged them ``cisco_ios``.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest


def _bootstrap_db(tmp_path: Path) -> Path:
    """Fresh main.duckdb with empty netops.* tables."""
    db = tmp_path / "main.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("CREATE SCHEMA netops")
        # raw_output_store
        conn.execute("""
            CREATE TABLE netops.raw_output_store (
                device_name  VARCHAR NOT NULL,
                command      VARCHAR NOT NULL,
                raw_output   TEXT,
                snapshot_id  VARCHAR,
                updated_at   TIMESTAMP,
                platform     VARCHAR,
                bundle_id    VARCHAR,
                bundle_sha256 VARCHAR,
                ingested_via VARCHAR,
                UNIQUE (device_name, command)
            )
        """)
        # parsed_outputs
        conn.execute("""
            CREATE TABLE netops.parsed_outputs (
                device_name      VARCHAR NOT NULL,
                command          VARCHAR NOT NULL,
                parsed_data      JSON,
                snapshot_id      VARCHAR,
                raw_output       TEXT,
                raw_output_hash  VARCHAR,
                ingested_at      TIMESTAMP,
                platform         VARCHAR,
                UNIQUE (device_name, command, snapshot_id)
            )
        """)
        # devices
        conn.execute("""
            CREATE TABLE netops.devices (
                hostname     VARCHAR NOT NULL,
                ip_address   VARCHAR,
                platform     VARCHAR,
                site         VARCHAR,
                role         VARCHAR,
                vendor       VARCHAR,
                model        VARCHAR,
                os_version   VARCHAR,
                environment  VARCHAR,
                last_seen    TIMESTAMP,
                metadata     JSON,
                UNIQUE (hostname)
            )
        """)
    return db


def _stub_load_host_metadata(monkeypatch):
    """No nornir inventory in test — short-circuit to empty dict."""
    monkeypatch.setattr(
        "olav_netops.core.device_etl.load_host_metadata",
        lambda *a, **kw: {},
    )


# ── Fallback Tier A: show_inventory PID extraction ────────────────────


class TestShowInventoryFallback:
    """The WLC case — show_version absent, show_inventory present.

    cisco_ios_show_inventory.textfsm normalises field names to
    lowercase (R83); parsed_data rows look like::

        [{"name": "Chassis 1", "descr": "Cisco C9800-40-K9 Chassis",
          "pid": "C9800-40-K9", "vid": "V06", "sn": "TTM..."}]
    """

    def test_wlc_pid_inferred_as_cisco_ios_with_model(self, tmp_path, monkeypatch):
        from olav_netops.core.device_etl import populate_devices
        _stub_load_host_metadata(monkeypatch)
        db = _bootstrap_db(tmp_path)
        host = "foo-wlc-9800-l.net.vu.edu.au"

        with duckdb.connect(str(db)) as conn:
            # raw_output_store row (auto-discovery wrote platform=cisco_ios)
            conn.execute(
                "INSERT INTO netops.raw_output_store "
                "(device_name, command, raw_output, snapshot_id, platform) "
                "VALUES (?, ?, ?, ?, ?)",
                [host, "show inventory", "PID: C9800-40-K9\n", "snap1", "cisco_ios"],
            )
            # parsed_outputs row with the cisco_ios_show_inventory result
            inv = [
                {
                    "name": "Chassis 1",
                    "descr": "Cisco C9800-40-K9 Chassis",
                    "pid": "C9800-40-K9",
                    "vid": "V06",
                    "sn": "TTM253502WJ",
                },
                {
                    "name": "module R0",
                    "descr": "Cisco C9800-40-K9 Route Processor",
                    "pid": "C9800-40-K9",
                },
            ]
            conn.execute(
                "INSERT INTO netops.parsed_outputs "
                "(device_name, command, parsed_data, snapshot_id, platform) "
                "VALUES (?, ?, ?::JSON, ?, ?)",
                [host, "show inventory", json.dumps(inv), "snap1", "cisco_ios"],
            )

        populate_devices(db, "snap1")

        with duckdb.connect(str(db), read_only=True) as conn:
            row = conn.execute(
                "SELECT hostname, platform, vendor, model, os_version "
                "FROM netops.devices WHERE hostname = ?", [host],
            ).fetchone()
        assert row is not None
        assert row[1] == "cisco_ios"
        assert row[2] == "Cisco"
        assert row[3] == "C9800-40-K9"

    def test_catalyst_pid_also_resolves_cisco_ios(self, tmp_path, monkeypatch):
        """Same fallback should fire for non-WLC Catalyst missing
        show_version (rare but happens with partial captures)."""
        from olav_netops.core.device_etl import populate_devices
        _stub_load_host_metadata(monkeypatch)
        db = _bootstrap_db(tmp_path)
        host = "edge-9300.example"
        with duckdb.connect(str(db)) as conn:
            conn.execute(
                "INSERT INTO netops.raw_output_store "
                "(device_name, command, raw_output, snapshot_id, platform) "
                "VALUES (?, 'show inventory', 'x', 'snap1', 'cisco_ios')",
                [host],
            )
            conn.execute(
                "INSERT INTO netops.parsed_outputs "
                "(device_name, command, parsed_data, snapshot_id, platform) "
                "VALUES (?, 'show inventory', ?::JSON, 'snap1', 'cisco_ios')",
                [host, json.dumps([{"pid": "C9300-48UXM", "name": "Chassis 1"}])],
            )

        populate_devices(db, "snap1")

        with duckdb.connect(str(db), read_only=True) as conn:
            row = conn.execute(
                "SELECT platform, model FROM netops.devices WHERE hostname = ?",
                [host],
            ).fetchone()
        assert row[0] == "cisco_ios"
        assert row[1] == "C9300-48UXM"


# ── Fallback Tier B: raw_output_store.platform ────────────────────────


class TestRawOutputStorePlatformFallback:
    """When even show_inventory is absent, trust auto-discovery."""

    def test_platform_inherited_from_raw_output_store(self, tmp_path, monkeypatch):
        from olav_netops.core.device_etl import populate_devices
        _stub_load_host_metadata(monkeypatch)
        db = _bootstrap_db(tmp_path)
        host = "exotic-device.example"
        with duckdb.connect(str(db)) as conn:
            # raw_output_store has only show_running-config (config doesn't
            # parse via TextFSM), but auto-discovery still set platform
            # via filename signature.
            conn.execute(
                "INSERT INTO netops.raw_output_store "
                "(device_name, command, raw_output, snapshot_id, platform) "
                "VALUES (?, 'show running-config', 'hostname X', 'snap1', 'juniper_junos')",
                [host],
            )

        populate_devices(db, "snap1")

        with duckdb.connect(str(db), read_only=True) as conn:
            row = conn.execute(
                "SELECT platform FROM netops.devices WHERE hostname = ?", [host],
            ).fetchone()
        assert row[0] == "juniper_junos"

    def test_no_signal_at_all_stays_unknown(self, tmp_path, monkeypatch):
        from olav_netops.core.device_etl import populate_devices
        _stub_load_host_metadata(monkeypatch)
        db = _bootstrap_db(tmp_path)
        host = "blind.example"
        with duckdb.connect(str(db)) as conn:
            # raw_output_store has rows but platform is NULL — auto-discovery
            # never figured it out.
            conn.execute(
                "INSERT INTO netops.raw_output_store "
                "(device_name, command, raw_output, snapshot_id, platform) "
                "VALUES (?, 'show running-config', 'foo', 'snap1', NULL)",
                [host],
            )

        populate_devices(db, "snap1")

        with duckdb.connect(str(db), read_only=True) as conn:
            row = conn.execute(
                "SELECT platform FROM netops.devices WHERE hostname = ?", [host],
            ).fetchone()
        assert row[0] == "unknown"
