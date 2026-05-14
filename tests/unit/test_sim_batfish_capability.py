"""Quick unit tests for batfish_capability tool (static-table layer)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _mock_duckdb_with_devices(devices: list[tuple[str, str]]):
    """Build a mocked duckdb context-manager that returns the given
    (hostname, platform) rows."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = devices

    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    return mock_ctx


def test_all_full_support():
    """All-cisco scope → summary FULL, no unsupported."""
    ctx = _mock_duckdb_with_devices([
        ("R1", "cisco_ios"),
        ("R2", "cisco_ios"),
        ("R3", "cisco_iosxe"),
    ])
    with patch("duckdb.connect", return_value=ctx):
        from olav.core.sim.batfish_capability import batfish_capability
        r = batfish_capability.invoke({"devices": ["R1", "R2", "R3"]})

    assert r["status"] == "ok"
    assert r["summary"] == "FULL"
    assert r["unsupported_devices"] == []
    assert r["per_device"]["R1"]["capability"] == "FULL"


def test_mixed_partial():
    """Mixed Cisco + Nokia SRL → summary PARTIAL, SRL listed unsupported."""
    ctx = _mock_duckdb_with_devices([
        ("R1", "cisco_ios"),
        ("R5", "nokia_srl"),  # NONE
        ("R6", "huawei_vrp"),  # PARTIAL
    ])
    with patch("duckdb.connect", return_value=ctx):
        from olav.core.sim.batfish_capability import batfish_capability
        r = batfish_capability.invoke({"devices": ["R1", "R5", "R6"]})

    assert r["summary"] == "PARTIAL"
    assert "R5" in r["unsupported_devices"]
    assert "R6" in r["partially_supported_devices"]


def test_all_unsupported_returns_none():
    """All-SRL scope → summary NONE; analyzer should skip sim."""
    ctx = _mock_duckdb_with_devices([
        ("SW1", "nokia_srl"),
        ("SW2", "nokia_srl"),
    ])
    with patch("duckdb.connect", return_value=ctx):
        from olav.core.sim.batfish_capability import batfish_capability
        r = batfish_capability.invoke({"devices": ["SW1", "SW2"]})

    assert r["summary"] == "NONE"
    assert sorted(r["unsupported_devices"]) == ["SW1", "SW2"]


def test_unknown_platform_marked():
    """Unknown vendor → capability='UNKNOWN', listed under unknown_platform_devices."""
    ctx = _mock_duckdb_with_devices([
        ("R1", "weird_new_vendor"),
    ])
    with patch("duckdb.connect", return_value=ctx):
        from olav.core.sim.batfish_capability import batfish_capability
        r = batfish_capability.invoke({"devices": ["R1"]})

    assert r["per_device"]["R1"]["capability"] == "UNKNOWN"
    assert "R1" in r["unknown_platform_devices"]
