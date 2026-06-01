"""Diff + netmiko injection E2E tests.

Covers:
  C-NE-26 — diff_sql_state detects real interface changes injected via netmiko
           — diff_topology_drift handles stable topology (0 changes = correct)

Gate: DIFF_E2E_ENABLED=1 (+ LLM-capable env optional for topology path)

Usage:
    DIFF_E2E_ENABLED=1 uv run pytest tests/e2e/test_diff_netmiko_e2e.py -v

Design:
  1. Reuse latest netops_init snapshot from DB as snap_before (R2 data, no Loopback99)
  2. netmiko injects Loopback99 (10.255.255.99/32) on R2
  3. Run show ip interface brief + show interfaces via netmiko directly
  4. Insert fresh rows into netops.parsed_outputs under a new test snapshot_id → snap_after
  5. rollback Loopback99 in finally (guaranteed)
  6. diff_sql_state("netops.parsed_outputs", snap_before, snap_after) → Loopback99 appears
  7. diff_topology_drift on pre-existing topology_links snapshots → status=success
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / ".olav/workspace/ops/tools"))
sys.path.insert(0, str(_ROOT / ".olav/workspace/ops/diff/tools"))

_DIFF_E2E_ENABLED = os.environ.get("DIFF_E2E_ENABLED", "").strip() == "1"

_DIFF_SKIP = pytest.mark.skipif(
    not _DIFF_E2E_ENABLED,
    reason="Diff E2E: set DIFF_E2E_ENABLED=1 to run (requires dev network access)",
)

# ── Device under test ───────────────────────────────────────────────────────
_R2_HOST = "192.168.100.102"
_R2_USER = "cisco"
_R2_PASS = "<redacted-lab-password>"
_TEST_LOOPBACK_NUM = 99
_TEST_LOOPBACK_IP = "10.255.255.99"
_TEST_LOOPBACK_MASK = "255.255.255.255"
_TEST_LOOPBACK_DESC = "OLAV-DIFF-TEST"


def _netmiko_r2() -> "ConnectHandler":
    from netmiko import ConnectHandler
    return ConnectHandler(
        device_type="cisco_ios",
        host=_R2_HOST,
        username=_R2_USER,
        password=_R2_PASS,
        timeout=30,
    )


def _inject_loopback() -> str:
    conn = _netmiko_r2()
    try:
        return conn.send_config_set([
            f"interface Loopback{_TEST_LOOPBACK_NUM}",
            f"description {_TEST_LOOPBACK_DESC}",
            f"ip address {_TEST_LOOPBACK_IP} {_TEST_LOOPBACK_MASK}",
            "no shutdown",
        ])
    finally:
        conn.disconnect()


def _rollback_loopback() -> str:
    conn = _netmiko_r2()
    try:
        return conn.send_config_set([f"no interface Loopback{_TEST_LOOPBACK_NUM}"])
    finally:
        conn.disconnect()


def _make_snap_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:6]
    return f"snap_{ts}_{uid}"


# ── Main test class ──────────────────────────────────────────────────────────

@_DIFF_SKIP
@pytest.mark.timeout(300)
class TestDiffNetmikoE2E:
    """C-NE-26: diff_sql_state detects real device change injected via netmiko.

    Strategy: reuse latest netops_init snapshot from DB as snap_before (no Loopback99),
    then inject Loopback99 via netmiko, collect output directly, and INSERT into
    netops.parsed_outputs under a fresh snapshot_id. The diff EXCEPT query can then
    find Loopback99 in the new rows.
    """

    _snap_before: str = ""
    _snap_after: str = ""

    @classmethod
    def _ensure_snapshots(cls) -> None:
        """Set up before/after snapshots in netops.parsed_outputs."""
        if cls._snap_before and cls._snap_after:
            return

        import duckdb
        from olav.core.config import MAIN_DB_PATH

        # ── before: reuse latest netops_init snapshot from DB ───────
        with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as con:
            row = con.execute(
                """
                SELECT snapshot_id FROM netops.parsed_outputs
                WHERE device_name = 'R2'
                  AND command = 'show ip interface brief'
                  AND (raw_output NOT LIKE '%Loopback99%' OR raw_output IS NULL)
                ORDER BY ingested_at DESC
                LIMIT 1
                """
            ).fetchone()
        assert row, "No existing R2 snapshot in netops.parsed_outputs — run netops_init first"
        cls._snap_before = row[0]

        # ── inject Loopback99 ────────────────────────────────────────
        try:
            _inject_loopback()

            # Collect fresh output via direct netmiko (bypasses staging pipeline)
            conn = _netmiko_r2()
            try:
                raw_brief = conn.send_command("show ip interface brief")
                raw_intf = conn.send_command("show interfaces")
            finally:
                conn.disconnect()

            # Persist fresh output via IngestManager staging pipeline
            cls._snap_after = _make_snap_id()
            _rows = [
                {
                    "snapshot_id": cls._snap_after,
                    "device_name": "R2",
                    "command": cmd,
                    "raw_output": raw,
                    "parsed_data": None,
                }
                for cmd, raw in [
                    ("show ip interface brief", raw_brief),
                    ("show interfaces", raw_intf),
                ]
            ]

            from olav.core.config import MAIN_DB_PATH, SNAPSHOTS_STAGING_JSON
            from olav.core.ingest_manager import IngestManager
            import json as _json

            SNAPSHOTS_STAGING_JSON.mkdir(parents=True, exist_ok=True)
            staging_file = SNAPSHOTS_STAGING_JSON / f"{cls._snap_after}.staging.json"
            staging_file.write_text(_json.dumps(_rows))
            IngestManager(db_path=MAIN_DB_PATH, staging_dir=SNAPSHOTS_STAGING_JSON).bulk_load()
        finally:
            # ── rollback (always runs) ───────────────────────────────
            _rollback_loopback()

    def test_snapshot_before_created(self) -> None:
        """Before-snapshot must be non-empty."""
        self._ensure_snapshots()
        assert self._snap_before, "before snapshot_id is empty"

    def test_snapshot_after_created(self) -> None:
        """After-snapshot must be non-empty."""
        self._ensure_snapshots()
        assert self._snap_after, "after snapshot_id is empty"
        assert self._snap_after != self._snap_before, "before and after snapshots must differ"

    def test_diff_detects_loopback_addition(self) -> None:
        """diff_sql_state must detect Loopback99 in the after snapshot."""
        self._ensure_snapshots()

        from diff_sql_state import diff_sql_state

        result = diff_sql_state.invoke({
            "table": "netops.parsed_outputs",
            "snapshot_id_1": self._snap_before,
            "snapshot_id_2": self._snap_after,
        })
        assert result.get("status") == "success", f"diff_sql_state failed: {result}"

        new_rows = result.get("new_in_t2", [])
        loopback_seen = any(
            f"Loopback{_TEST_LOOPBACK_NUM}" in str(row)
            for row in new_rows
        )
        assert loopback_seen, (
            f"diff did not detect Loopback{_TEST_LOOPBACK_NUM} in new_in_t2. "
            f"Got {len(new_rows)} new rows. First 3: {new_rows[:3]}"
        )

    def test_diff_loopback_absent_in_before(self) -> None:
        """Loopback99 must NOT appear in before snapshot (validates test setup)."""
        self._ensure_snapshots()

        import duckdb
        from olav.core.config import MAIN_DB_PATH

        with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as con:
            rows = con.execute(
                """
                SELECT raw_output FROM netops.parsed_outputs
                WHERE snapshot_id = ? AND device_name = 'R2'
                """,
                [self._snap_before],
            ).fetchall()

        loopback_in_before = any(
            f"Loopback{_TEST_LOOPBACK_NUM}" in (r[0] or "") for r in rows
        )
        assert not loopback_in_before, (
            f"Loopback{_TEST_LOOPBACK_NUM} unexpectedly found in before-snapshot {self._snap_before}"
        )


# ── Topology drift test (stable network = 0 changes) ────────────────────────

@_DIFF_SKIP
@pytest.mark.timeout(120)
class TestDiffTopologyDriftStable:
    """C-NE-26: diff_topology_drift returns success on two successive CDP/LLDP snapshots."""

    _snap1: str = ""
    _snap2: str = ""

    @classmethod
    def _ensure_two_topology_snapshots(cls) -> None:
        """Use two distinct snapshot_ids from topology_links (from prior netops_init runs)."""
        if cls._snap1 and cls._snap2:
            return

        import duckdb
        from olav.core.config import MAIN_DB_PATH

        with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as con:
            rows = con.execute(
                """
                SELECT DISTINCT snapshot_id
                FROM netops.topology_links
                WHERE discovery_protocol IN ('CDP', 'LLDP')
                ORDER BY snapshot_id
                """
            ).fetchall()

        if len(rows) >= 2:
            cls._snap1 = rows[0][0]
            cls._snap2 = rows[-1][0]
        elif len(rows) == 1:
            cls._snap1 = rows[0][0]
            cls._snap2 = rows[0][0]
        else:
            pytest.skip("No topology_links rows found — run netops_init first")

    def test_two_cdp_lldp_snapshots_exist(self) -> None:
        """At least one topology snapshot with CDP/LLDP data must exist."""
        self._ensure_two_topology_snapshots()
        assert self._snap1, "No CDP/LLDP snapshot found in topology_links"

    def test_topology_drift_returns_success(self) -> None:
        """diff_topology_drift must return status=success on stable topology."""
        self._ensure_two_topology_snapshots()

        from olav_netops.core.diff import diff_topology_drift

        result = diff_topology_drift(snapshot_id_1=self._snap1, snapshot_id_2=self._snap2)
        assert result.get("status") == "success", (
            f"diff_topology_drift returned error: {result.get('error')}"
        )

    def test_topology_drift_stable_has_zero_changes(self) -> None:
        """Stable network: diff on same or back-to-back snapshots should report 0 changes."""
        self._ensure_two_topology_snapshots()

        from olav_netops.core.diff import diff_topology_drift

        # Same snapshot compared against itself → always 0 changes
        result = diff_topology_drift(snapshot_id_1=self._snap1, snapshot_id_2=self._snap1)
        assert result.get("total_changes", 0) == 0, (
            f"self-diff returned non-zero changes: {result.get('total_changes')}"
        )
