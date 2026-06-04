"""Unit tests: generate_change_plan fat tool (commit f5faa5e9).

Replaces per-device SQL loops (60-80 calls → context overflow) with a single
Python function call. Tests verify: correct SQL, BFS leaf-first ordering,
complete markdown sections, and file output.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))

# Path to the fat tool script
_SCRIPT = (
    _ROOT / "olav-netops" / ".olav" / "workspace" / "netops"
    / "analyzer" / "scripts" / "generate_change_plan.py"
)
if not _SCRIPT.exists():
    # Fallback to mirror copy
    _SCRIPT = (
        _ROOT / ".olav" / "workspace" / "netops"
        / "analyzer" / "scripts" / "generate_change_plan.py"
    )

pytestmark = pytest.mark.skipif(
    not _SCRIPT.exists(),
    reason="generate_change_plan.py not found — run olav skill install olav-netops",
)


def _import_script():
    import importlib.util
    spec = importlib.util.spec_from_file_location("generate_change_plan", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def _fake_db(tmp_path_factory):
    """Create a minimal DuckDB with netops.devices table for testing."""
    import duckdb
    db_path = tmp_path_factory.mktemp("db") / "test.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE SCHEMA netops")
    conn.execute("""
        CREATE TABLE netops.devices (
            hostname VARCHAR,
            platform VARCHAR,
            model VARCHAR,
            ip_address VARCHAR,
            role VARCHAR,
            vendor VARCHAR,
            os_version VARCHAR
        )
    """)
    # Insert test devices — mix of roles to test BFS ordering
    devices = [
        ("dist-1.example.com",    "cisco_ios", "WS-C4500X-32", "10.0.0.1", "Distribution", "Cisco", "15.2"),
        ("server-1.example.com",  "cisco_ios", "WS-C4500X-32", "10.0.0.2", "Leaf/Server",  "Cisco", "15.2"),
        ("wan-edge-1.example.com","cisco_ios", "WS-C4500X-32", "10.0.0.3", "WAN Edge",     "Cisco", "15.2"),
        ("access-1.example.com",  "cisco_ios", "WS-C4500X-32", "10.0.0.4", "Access",       "Cisco", "15.2"),
    ]
    conn.executemany(
        "INSERT INTO netops.devices VALUES (?,?,?,?,?,?,?)",
        devices
    )
    conn.close()
    return str(db_path)


class TestGenerateChangePlanCore:

    def test_returns_success(self, _fake_db, tmp_path):
        mod = _import_script()
        result = mod.generate_change_plan(
            model_pattern="%C4500X%",
            output_filename="test_plan",
            db_path=_fake_db,
        )
        assert result["status"] == "success"
        assert result["device_count"] == 4

    def test_file_is_created(self, _fake_db, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mod = _import_script()
        result = mod.generate_change_plan(
            model_pattern="%C4500X%",
            output_filename="test_plan",
            db_path=_fake_db,
        )
        out = Path(result["file"])
        assert out.exists(), f"Output file not created: {result['file']}"
        assert out.stat().st_size > 500, "File too small — content missing"

    def test_markdown_has_required_sections(self, _fake_db, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mod = _import_script()
        result = mod.generate_change_plan(
            model_pattern="%C4500X%",
            output_filename="test_sections",
            db_path=_fake_db,
        )
        content = Path(result["file"]).read_text()
        for section in ("## Summary", "## Scope", "## Upgrade Sequence",
                        "## Risks", "## Pre-conditions"):
            assert section in content, f"Missing required section: {section}"

    def test_bfs_leaf_first_ordering(self, _fake_db, tmp_path, monkeypatch):
        """BFS ordering: Leaf/Server/Access before Distribution before WAN."""
        monkeypatch.chdir(tmp_path)
        mod = _import_script()
        result = mod.generate_change_plan(
            model_pattern="%C4500X%",
            output_filename="test_bfs",
            bfs_order=True,
            db_path=_fake_db,
        )
        content = Path(result["file"]).read_text()
        # access/server should appear before distribution and WAN
        pos_access = content.find("access-1")
        pos_server = content.find("server-1")
        pos_dist   = content.find("dist-1")
        pos_wan    = content.find("wan-edge-1")
        assert pos_access > 0 and pos_dist > 0 and pos_wan > 0
        assert pos_access < pos_dist, "Access should appear before Distribution"
        assert pos_server < pos_wan,  "Server/Leaf should appear before WAN Edge"

    def test_no_model_match_returns_error(self, _fake_db, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mod = _import_script()
        result = mod.generate_change_plan(
            model_pattern="%NONEXISTENT_MODEL%",
            output_filename="empty",
            db_path=_fake_db,
        )
        assert result["status"] == "error"
        assert "No devices" in result.get("message", "")

    def test_all_devices_included(self, _fake_db, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mod = _import_script()
        result = mod.generate_change_plan(
            model_pattern="%C4500X%",
            output_filename="test_all",
            db_path=_fake_db,
        )
        content = Path(result["file"]).read_text()
        for hostname in ("dist-1", "server-1", "wan-edge-1", "access-1"):
            assert hostname in content, f"Device {hostname} missing from plan"

    def test_cli_blocks_present(self, _fake_db, tmp_path, monkeypatch):
        """Each device section should contain upgrade CLI, rollback, and post-check."""
        monkeypatch.chdir(tmp_path)
        mod = _import_script()
        result = mod.generate_change_plan(
            model_pattern="%C4500X%",
            output_filename="test_cli",
            db_path=_fake_db,
        )
        content = Path(result["file"]).read_text()
        assert "copy tftp flash" in content,      "Missing upgrade CLI"
        assert "no boot system" in content,       "Missing rollback CLI"
        assert "show version" in content,         "Missing post-checks"

    def test_stages_reported(self, _fake_db, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mod = _import_script()
        result = mod.generate_change_plan(
            model_pattern="%C4500X%",
            output_filename="test_stages",
            bfs_order=True,
            db_path=_fake_db,
        )
        assert result.get("stages", 0) >= 1
