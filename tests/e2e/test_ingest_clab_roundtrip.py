"""E2E — portable snapshot ingest against the live 6-node CLAB lab.

Two complementary tests:

  1. ``test_real_clab_fixture_ingests_cleanly`` — uses the committed
     fixture at ``tests/fixtures/portable_ingest/real_clab_capture/``
     (captured from the live lab during plan-Phase-0a).  Always runnable
     (no SSH dependency); guards the structural invariants of the full
     landing pipeline.

  2. ``test_live_recapture_then_ingest`` — re-collects raw output from
     R1-SW2 via netmiko (cisco/<redacted-lab-password>), repackages into a §3 bundle
     on the fly, ingests into a tmp DB, and asserts row counts match
     the captured raw.  Gated by ``INGEST_E2E_ENABLED=1`` so it does
     not fire in default CI.

Both run on isolated tmp_path DBs so production state is untouched.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import duckdb
import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "olav-netops" / "src"))


_FIXTURE_DIR = (
    _ROOT / "tests" / "fixtures" / "portable_ingest" / "real_clab_capture"
)


# ── 1. Always-runnable fixture roundtrip ──────────────────────────────


class TestRealFixtureIngest:
    def test_lands_all_6_hosts(self, tmp_path):
        from olav.core.ingest.landing import ingest_snapshot
        result = ingest_snapshot(
            _FIXTURE_DIR,
            db_path=tmp_path / "main.duckdb",
            staging_dir=tmp_path / "staging",
            collection_source="bundle:olav-collector:0.0.0-fixture",
        )
        assert result.hosts == 6, f"expected 6 hosts, got {result.hosts}"
        assert result.commands == 21, f"expected 21 commands, got {result.commands}"

    def test_raw_output_store_has_all_rows(self, tmp_path):
        from olav.core.ingest.landing import ingest_snapshot
        ingest_snapshot(
            _FIXTURE_DIR,
            db_path=tmp_path / "main.duckdb",
            staging_dir=tmp_path / "staging",
            collection_source="bundle:olav-collector:0.0.0-fixture",
        )
        with duckdb.connect(str(tmp_path / "main.duckdb")) as conn:
            rows = conn.execute(
                "SELECT device_name, command "
                "FROM netops.raw_output_store "
                "ORDER BY device_name, command"
            ).fetchall()
        # R1 (junos) has 1 command (show version); R2-SW2 each have 4.
        assert len(rows) == 21
        hosts = {r[0] for r in rows}
        assert hosts == {"R1", "R2", "R3", "R4", "SW1", "SW2"}

    def test_devices_table_populated(self, tmp_path):
        from olav.core.ingest.landing import ingest_snapshot
        ingest_snapshot(
            _FIXTURE_DIR,
            db_path=tmp_path / "main.duckdb",
            staging_dir=tmp_path / "staging",
            collection_source="bundle:olav-collector:0.0.0-fixture",
        )
        with duckdb.connect(str(tmp_path / "main.duckdb")) as conn:
            devs = sorted(r[0] for r in conn.execute(
                "SELECT hostname FROM netops.devices"
            ).fetchall())
        assert devs == ["R1", "R2", "R3", "R4", "SW1", "SW2"]

    def test_views_built_after_ingest(self, tmp_path):
        from olav.core.ingest.landing import ingest_snapshot
        ingest_snapshot(
            _FIXTURE_DIR,
            db_path=tmp_path / "main.duckdb",
            staging_dir=tmp_path / "staging",
            collection_source="bundle:olav-collector:0.0.0-fixture",
        )
        with duckdb.connect(str(tmp_path / "main.duckdb")) as conn:
            view_names = {
                r[0] for r in conn.execute(
                    "SELECT table_name FROM information_schema.views "
                    "WHERE table_schema = 'netops'"
                ).fetchall()
            }
        # Sanity — finalise_ingest should have built at least the auto views.
        assert any("v_" in v and "_auto" in v for v in view_names), (
            f"no v_*_auto views found; view_builder may have failed silently; "
            f"got views = {sorted(view_names)}"
        )

    def test_bundle_ingest_provenance_recorded(self, tmp_path):
        from olav.core.ingest.landing import ingest_snapshot
        result = ingest_snapshot(
            _FIXTURE_DIR,
            db_path=tmp_path / "main.duckdb",
            staging_dir=tmp_path / "staging",
            collection_source="bundle:olav-collector:0.0.0-fixture",
        )
        with duckdb.connect(str(tmp_path / "main.duckdb")) as conn:
            row = conn.execute(
                "SELECT bundle_id, hosts_count, commands_count, "
                "       pre_scrubbed, parser_fill_summary "
                "FROM netops.bundle_ingests WHERE bundle_id = ?",
                [result.bundle_id],
            ).fetchone()
        assert row is not None
        assert row[1] == 6
        assert row[2] == 21
        assert row[3] is True
        # parser_fill_summary is JSON; if any parser fired it'll be non-empty.
        assert row[4] is not None


# ── 2. Live recapture + ingest (gated) ────────────────────────────────


_LIVE_GATE = pytest.mark.skipif(
    os.environ.get("INGEST_E2E_ENABLED", "").strip() != "1",
    reason="set INGEST_E2E_ENABLED=1 to re-collect from the CLAB lab",
)


def _ssh_alive(host: str, port: int = 22, timeout: float = 1.5) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.mark.e2e
@_LIVE_GATE
class TestLiveCaptureThenIngest:
    HOSTS: dict[str, tuple[str, str]] = {
        # host_label : (mgmt_ip, platform)
        "R2": ("192.168.100.102", "cisco_ios"),
        "R3": ("192.168.100.103", "cisco_ios"),
    }

    def test_capture_two_hosts_and_ingest(self, tmp_path):
        # Sanity: reachability
        for host, (ip, _) in self.HOSTS.items():
            assert _ssh_alive(ip), f"{host} ({ip}) SSH unreachable"

        # Re-collect via netmiko
        from netmiko import ConnectHandler
        commands = ["show version", "show ip interface brief"]
        captures: dict[str, dict[str, str]] = {}
        for host, (ip, platform) in self.HOSTS.items():
            conn = ConnectHandler(
                device_type=platform, host=ip,
                username="cisco", password="<redacted-lab-password>", timeout=30,
            )
            try:
                captures[host] = {
                    cmd: conn.send_command(cmd) or ""
                    for cmd in commands
                }
            finally:
                conn.disconnect()

        # Build minimal bundle on the fly
        import hashlib
        from datetime import UTC, datetime
        import yaml

        bundle = tmp_path / "live_bundle"
        (bundle / "devices").mkdir(parents=True)
        for host, (ip, platform) in self.HOSTS.items():
            host_dir = bundle / "devices" / host
            host_dir.mkdir()
            ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            (host_dir / "_meta.yaml").write_text(yaml.safe_dump({
                "hostname": host,
                "mgmt_ip": ip,
                "platform": platform,
                "vendor": "Cisco",
                "commands_attempted": len(commands),
                "commands_succeeded": len(commands),
                "commands_failed": 0,
                "collected_at": ts,
            }), encoding="utf-8")
            for cmd, body in captures[host].items():
                safe = cmd.replace(" ", "_") + ".txt"
                content = (
                    f"# command: {cmd}\n"
                    f"# collected_at: {ts}\n"
                    f"# pre_scrubbed: false\n"
                    f"\n"
                    f"{body}"
                )
                (host_dir / safe).write_text(content, encoding="utf-8")

        # Recompute hash using the same on-disk walk as the validator.
        from olav.core.ingest.validators import _hash_bundle_contents
        content_sha256, _, _ = _hash_bundle_contents(bundle)
        (bundle / "manifest.yaml").write_text(yaml.safe_dump({
            "schema_version": 1,
            "collector": {"name": "live-e2e", "version": "0.0.0"},
            "collected_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hosts_collected": len(self.HOSTS),
            "redaction": {"pre_scrubbed": False},
            "content_sha256": content_sha256,
        }), encoding="utf-8")

        # Ingest
        from olav.core.ingest.landing import ingest_snapshot
        result = ingest_snapshot(
            bundle,
            db_path=tmp_path / "main.duckdb",
            staging_dir=tmp_path / "staging",
            collection_source="bundle:live-e2e:0.0.0",
        )

        assert result.hosts == len(self.HOSTS)
        assert result.commands == len(self.HOSTS) * len(commands)

        with duckdb.connect(str(tmp_path / "main.duckdb")) as conn:
            rows = conn.execute(
                "SELECT DISTINCT device_name FROM netops.raw_output_store "
                "ORDER BY device_name"
            ).fetchall()
        assert [r[0] for r in rows] == sorted(self.HOSTS.keys())
