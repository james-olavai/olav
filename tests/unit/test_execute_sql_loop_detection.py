"""Unit tests: execute_sql per-device loop detection (commit c79d536a).

gemma4 queried devices one-by-one (60-80 calls, same column different value)
causing context overflow. _check_sql_loop() detects repeated structural stems
and returns a hard-stop message after _SQL_LOOP_DETECT_THRESHOLD identical stems.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


@pytest.fixture(autouse=True)
def reset_loop_state():
    """Reset thread-local loop detection state before each test."""
    from olav.data.workspace.core.tools.execute_sql import reset_sql_call_counter
    reset_sql_call_counter()
    yield
    reset_sql_call_counter()


def _stem(sql: str) -> str:
    from olav.data.workspace.core.tools.execute_sql import _sql_stem
    return _sql_stem(sql)


def _check(sql: str):
    from olav.data.workspace.core.tools.execute_sql import _check_sql_loop
    return _check_sql_loop(sql)


class TestSqlStem:
    """_sql_stem() strips WHERE values but keeps column names — same column
    repeated = loop; different column = legitimate variation."""

    def test_strips_string_value(self):
        s1 = _stem("SELECT * FROM netops.devices WHERE hostname = 'R1'")
        s2 = _stem("SELECT * FROM netops.devices WHERE hostname = 'R2'")
        assert s1 == s2, "Same column, different value must produce same stem"

    def test_preserves_different_columns(self):
        s1 = _stem("SELECT * FROM netops.devices WHERE model = 'C4500X'")
        s2 = _stem("SELECT * FROM netops.devices WHERE platform = 'cisco_ios'")
        assert s1 != s2, "Different column names must produce different stems"

    def test_strips_in_clause(self):
        s1 = _stem("SELECT * FROM t WHERE x IN ('a', 'b')")
        s2 = _stem("SELECT * FROM t WHERE x IN ('c', 'd', 'e')")
        assert s1 == s2

    def test_different_tables_differ(self):
        s1 = _stem("SELECT * FROM netops.devices WHERE h = 'x'")
        s2 = _stem("SELECT * FROM netops.topology_links WHERE h = 'x'")
        assert s1 != s2


class TestLoopDetection:
    """_check_sql_loop() returns None until threshold, then returns stop message."""

    def test_no_loop_on_first_calls(self):
        sql = "SELECT hostname FROM netops.devices WHERE hostname = 'R1'"
        for _ in range(4):       # threshold is 5 — should be safe
            result = _check(sql)
        assert result is None

    def test_loop_detected_at_threshold(self):
        sql = "SELECT hostname FROM netops.devices WHERE hostname = 'alpha-dist'"
        for _ in range(4):
            _check(sql)
        result = _check(sql)     # 5th identical stem
        assert result is not None, "Loop not detected at threshold=5"
        assert "LOOP" in result.upper() or "STOP" in result.upper()

    def test_stop_message_contains_bulk_query_hint(self):
        sql = "SELECT * FROM netops.devices WHERE hostname = 'R%d'"
        for i in range(5):
            result = _check(sql % i)   # same structural stem (hostname = '?')
        assert result is not None
        assert "WHERE" in result or "model" in result.lower() or "LIKE" in result

    def test_different_columns_no_false_positive(self):
        """Real investigation queries with different columns should not trigger."""
        queries = [
            "SELECT * FROM netops.devices WHERE model LIKE '%C4500X%'",
            "SELECT * FROM netops.devices WHERE platform = 'cisco_ios'",
            "SELECT * FROM netops.devices WHERE role = 'distribution'",
            "SELECT * FROM netops.topology_links WHERE source_device = 'R1'",
            "SELECT * FROM netops.devices WHERE vendor = 'Cisco'",
        ]
        for q in queries:
            result = _check(q)
        assert result is None, (
            f"False positive loop detection on different-column queries. "
            f"Last result: {result}"
        )

    def test_reset_clears_state(self):
        from olav.data.workspace.core.tools.execute_sql import reset_sql_call_counter
        sql = "SELECT * FROM t WHERE h = 'x'"
        for _ in range(5):
            _check(sql)
        reset_sql_call_counter()
        # After reset, same SQL should not trigger immediately
        result = _check(sql)
        assert result is None, "Loop state not cleared by reset_sql_call_counter()"

    def test_ch11_device_loop_pattern(self):
        """Reproduce the exact CH11 failure: 14 devices queried individually."""
        devices = [
            f"alpha-dist-4500xv-{c}.net.demo.internal"
            for c in ["a", "b", "c", "d", "e", "f", "g",
                      "h", "i", "j", "k", "l", "m", "n"]
        ]
        fired = False
        for i, d in enumerate(devices):
            sql = (
                f"SELECT hostname, model, ip_address FROM netops.devices "
                f"WHERE hostname = '{d}'"
            )
            result = _check(sql)
            if result is not None:
                fired = True
                assert i < len(devices) - 1, "Loop not caught early enough"
                break
        assert fired, (
            "CH11 device loop not detected. gemma4's per-device SQL pattern "
            "should trigger after 5 identical column-stem repetitions."
        )
