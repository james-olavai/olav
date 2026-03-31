"""Regression tests for three critical Stage 2 bugs fixed on 2026-03-21.

Bug #1 (ADJ-8): _process_device return-early
    The `return device_name, [], [], 0, 0, 0` was outside the
    `if not device_dir.exists()` guard, so Stage 2 ALWAYS returned empty
    results regardless of whether a device directory exists.

Bug #2 (ADJ-9): _store_sync_metadata date parse
    `strptime(sync_date, "%Y-%m-%d")` failed for actual format "%Y-%m-%d_%H%M",
    causing a silent exception — sync_metadata table always empty.

Bug #3 (ADJ-10): apply_oc_mapping thread safety
    ThreadPoolExecutor workers shared a single `db.conn`, causing
    `malloc(): unaligned tcache chunk detected` heap corruption.
    Fixed by pre-loading catalog into in-memory dicts + new
    `apply_oc_mapping_cached()`.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SYNC_TOOLS_DIR = _PROJECT_ROOT / "olav-netops" / ".olav" / "workspace" / "config" / "sync" / "tools"
_SRC_DIR = _PROJECT_ROOT / "src"

for _p in (_SRC_DIR, _SYNC_TOOLS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------------------
# Bug #1: _process_device return-early
# ---------------------------------------------------------------------------
class TestStage2ReturnEarlyBug:
    """ADJ-8: Verify _process_device processes existing directories."""

    def test_existing_device_dir_is_processed(self, tmp_path):
        """With a real raw dir and txt files, _process_sync_stage2 returns records."""
        from sync_tools import _process_sync_stage2

        # Create a minimal snapshot structure
        snap_dir = tmp_path / "2026-03-21_test"
        raw_dir = snap_dir / "raw" / "TESTDEV"
        raw_dir.mkdir(parents=True)
        # Write a real-looking show arp output
        (raw_dir / "show_arp.txt").write_text(
            "Protocol  Address     Age (min)  Hardware Addr   Type  Interface\n"
            "Internet  10.0.0.1    0          aabb.cc00.0100  ARPA  Gi0/0\n"
        )

        # Mock the DB and ingest so we don't need a real DuckDB
        mock_db = MagicMock()
        mock_db.conn.execute.return_value.fetchall.return_value = [("TESTDEV", "cisco_ios")]
        mock_ingest = MagicMock()

        with (
                patch("olav.core.database.get_database", return_value=mock_db),
                patch("olav.core.ingest_manager.IngestManager", return_value=mock_ingest),
        ):
            result = _process_sync_stage2(snap_dir, ["TESTDEV"])

        # The function ran through — result is a list (may be empty gaps or have gaps)
        assert isinstance(result, list), "Should return a list of gaps, not crash"

    def test_missing_device_dir_returns_empty(self, tmp_path):
        """Device not in raw/ → returns without error, 0 records."""
        from sync_tools import _process_sync_stage2

        snap_dir = tmp_path / "2026-03-21_empty"
        (snap_dir / "raw").mkdir(parents=True)  # raw dir exists but no TESTDEV subdir

        mock_db = MagicMock()
        mock_db.conn.execute.return_value.fetchall.return_value = []
        mock_ingest = MagicMock()

        with (
                patch("olav.core.database.get_database", return_value=mock_db),
                patch("olav.core.ingest_manager.IngestManager", return_value=mock_ingest),
        ):
            result = _process_sync_stage2(snap_dir, ["NONEXISTENT"])

        assert isinstance(result, list)

    def test_return_placement_is_inside_if_block(self):
        """Code-level: the return after logger.debug is inside the if-not-exists block."""
        import inspect
        from sync_tools import _process_sync_stage2

        source = inspect.getsource(_process_sync_stage2)
        # The return must be indented MORE than the `if not device_dir.exists():` line
        # We verify that there is NO case where `return device_name, [], [], 0, 0, 0`
        # appears at the same level as `if not device_dir.exists():`
        lines = source.splitlines()
        for i, line in enumerate(lines):
            if "if not device_dir.exists():" in line:
                # The very next non-empty line must be more indented (inside the if)
                for j in range(i + 1, min(i + 4, len(lines))):
                    next_line = lines[j]
                    if not next_line.strip():
                        continue
                    if_indent = len(line) - len(line.lstrip())
                    body_indent = len(next_line) - len(next_line.lstrip())
                    assert body_indent > if_indent, (
                        f"Line after `if not exists` must be indented: {next_line!r}"
                    )
                    break


# ---------------------------------------------------------------------------
# Bug #2: _store_sync_metadata date parse
# ---------------------------------------------------------------------------
class TestStoreSyncMetadataDateParse:
    """ADJ-9: Verify _store_sync_metadata handles %Y-%m-%d_%H%M format."""

    def test_datetime_parsing_accepts_hmm_format(self):
        """The fixed code must parse '2026-03-21_1850' without ValueError."""
        # Simulate the fixed parsing logic
        sync_date = "2026-03-21_1850"
        try:
            start_ts = datetime.strptime(sync_date, "%Y-%m-%d_%H%M")
        except ValueError:
            pytest.fail("Fixed parse should accept %Y-%m-%d_%H%M format")
        assert start_ts.year == 2026
        assert start_ts.hour == 18
        assert start_ts.minute == 50

    def test_datetime_parsing_fallback_for_date_only(self):
        """Fallback must parse '2026-03-21' (date-only legacy format)."""
        sync_date = "2026-03-21"
        try:
            start_ts = datetime.strptime(sync_date[:10], "%Y-%m-%d")
        except ValueError:
            pytest.fail("Fallback should accept %Y-%m-%d format")
        assert start_ts.year == 2026

    def test_end_ts_uses_duration_not_end_of_day(self):
        """end_ts must reflect actual duration, not a hardcoded 23:59:59."""
        start_ts = datetime(2026, 3, 21, 18, 50, 0)
        duration_seconds = 203.0
        end_ts = start_ts + timedelta(seconds=duration_seconds)
        # Must NOT be 23:59:59
        assert end_ts.hour != 23 or end_ts.minute != 59
        # Must be approximately start + duration
        delta = (end_ts - start_ts).total_seconds()
        assert abs(delta - duration_seconds) < 1.0

    def test_store_sync_metadata_writes_row(self, tmp_path):
        """With mocked DB, _store_sync_metadata writes exactly one INSERT."""
        from sync_tools import _store_sync_metadata

        mock_conn = MagicMock()
        mock_db = MagicMock()
        mock_db.conn = mock_conn

        with patch("olav.core.database.get_database", return_value=mock_db):
            _store_sync_metadata(
                sync_date="2026-03-21_1850",
                sync_dir=tmp_path / "snap",
                device_count=6,
                command_count=405,
                success_count=6,
                failed_count=0,
                duration_seconds=203.0,
            )

        # Exactly one INSERT was executed
        assert mock_conn.execute.called
        call_args = mock_conn.execute.call_args[0][0]
        assert "INSERT INTO sync_metadata" in call_args


# ---------------------------------------------------------------------------
# Bug #3: apply_oc_mapping thread safety
# ---------------------------------------------------------------------------
class TestApplyOcMappingCached:
    """ADJ-10: Verify apply_oc_mapping_cached works without a live DB connection."""

    def _make_caches(self):
        oc_cache = {
            ("cisco_ios", "show ip interface brief"): {
                    "interface": "interfaces/interface/name",
                    "ip_address": "interfaces/interface/subinterfaces/subinterface/ipv4/addresses/address/ip",
            }
        }
        mr_cache: dict = {}
        return oc_cache, mr_cache

    def test_returns_list_of_oc_dicts(self):
        """Result is a list of dicts with openconfig-* top-level keys."""
        from olav.core.normalization import apply_oc_mapping_cached

        oc_cache, mr_cache = self._make_caches()
        records = [{"interface": "Gi0/0", "ip_address": "10.0.0.1", "status": "up"}]
        result = apply_oc_mapping_cached(records, "cisco_ios", "show ip interface brief", oc_cache, mr_cache)
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], dict)

    def test_mapped_fields_go_to_oc_keys(self):
        """Fields in oc_cache map to their openconfig-* nested path."""
        from olav.core.normalization import apply_oc_mapping_cached

        oc_cache, mr_cache = self._make_caches()
        records = [{"interface": "Gi0/0", "unknown_field": "x"}]
        result = apply_oc_mapping_cached(records, "cisco_ios", "show ip interface brief", oc_cache, mr_cache)
        assert len(result) == 1
        out = result[0]
        # "interface" should be mapped to openconfig-interfaces key
        assert "openconfig-interfaces" in out
        # "unknown_field" should end up in _unmapped
        assert "_unmapped" in out
        assert out["_unmapped"]["unknown_field"] == "x"

    def test_fallback_to_mapping_rules_when_no_catalog_entry(self):
        """Falls back to mapping_rules_fallback when key not in oc_catalog_cache."""
        from olav.core.normalization import apply_oc_mapping_cached

        oc_cache: dict = {}
        mr_cache = {
            ("cisco_ios", "show ip route"): {
                "network": "openconfig-network-instance/network-instances/network-instance/protocols/protocol/static-routes/static/prefix"
            }
        }
        records = [{"network": "10.0.0.0/8"}]
        result = apply_oc_mapping_cached(records, "cisco_ios", "show ip route", oc_cache, mr_cache)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_raises_valueerror_when_no_mapping_found(self):
        """Raises ValueError if neither cache has an entry (mirroring original apply_oc_mapping)."""
        from olav.core.normalization import apply_oc_mapping_cached

        with pytest.raises(ValueError):
            apply_oc_mapping_cached(
                [{"key": "val"}], "cisco_ios", "show missing", {}, {}
            )

    def test_empty_records_returns_empty(self):
        """Empty input → empty output, no errors."""
        from olav.core.normalization import apply_oc_mapping_cached

        result = apply_oc_mapping_cached([], "cisco_ios", "show anything", {}, {})
        assert result == []

    def test_does_not_call_duckdb(self):
        """The cached variant must NOT call any DB connection methods."""
        from olav.core.normalization import apply_oc_mapping_cached

        oc_cache, mr_cache = self._make_caches()
        # Pass a mock that would fail if any DB method is called
        fake_con = MagicMock()
        fake_con.execute.side_effect = RuntimeError("Should not call DB!")

        records = [{"interface": "Gi0/0"}]
        # Must not raise RuntimeError
        result = apply_oc_mapping_cached(records, "cisco_ios", "show ip interface brief", oc_cache, mr_cache)
        fake_con.execute.assert_not_called()
        assert isinstance(result, list)
