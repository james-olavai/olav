"""Unit tests for inspect_devices, inspect_interfaces, inspect_routing scripts.

These scripts were migrated from @tool (netops/tools/) to script
(netops/analyzer/scripts/) per ADR-0007 rev ~301: all three are
stateless reads that satisfy none of the 4 @tool criteria.

Tests cover:
- Core function logic with mocked dependencies
- __main__ block (stdin JSON → stdout JSON) via importlib
- Unknown device / discovery-mode edge cases
"""
from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "olav-netops" / ".olav" / "workspace" / "netops" / "analyzer" / "scripts"
DEV_SCRIPTS = REPO / ".olav" / "workspace" / "netops" / "analyzer" / "scripts"


def _load(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# inspect_devices
# ---------------------------------------------------------------------------


class TestInspectDevices:
    def _mock_model(self, facts: dict) -> MagicMock:
        m = MagicMock()
        m.facts = facts
        return m

    def test_found_device_returns_resolved_fields(self):
        mod = _load("inspect_devices")
        facts = {
            "R1": {"platform": "cisco_ios", "loopback": "1.1.1.1",
                   "local_as": 65001, "mgmt_ip": "192.168.1.1", "role": "border"},
        }
        with patch.object(mod, "load_network_model", return_value=self._mock_model(facts)):
            result = mod.inspect_devices(["R1"])
        assert result["found"]["R1"]["platform"] == "cisco_ios"
        assert result["found"]["R1"]["local_as"] == 65001
        assert result["unknown_devices"] == []

    def test_unknown_device_goes_to_unknown_devices(self):
        mod = _load("inspect_devices")
        with patch.object(mod, "load_network_model", return_value=self._mock_model({})):
            result = mod.inspect_devices(["Rfoo"])
        assert "Rfoo" in result["unknown_devices"]
        assert result["found"] == {}

    def test_missing_fields_reported_in_unknown_facts(self):
        mod = _load("inspect_devices")
        facts = {"R2": {"platform": "juniper_junos", "mgmt_ip": "10.0.0.2"}}
        with patch.object(mod, "load_network_model", return_value=self._mock_model(facts)):
            result = mod.inspect_devices(["R2"])
        missing = result["unknown_facts"].get("R2", [])
        assert "loopback" in missing
        assert "local_as" in missing

    def test_discovery_mode_empty_list_returns_all(self):
        mod = _load("inspect_devices")
        facts = {
            "R1": {"platform": "cisco_ios"},
            "R2": {"platform": "juniper_junos"},
        }
        with patch.object(mod, "load_network_model", return_value=self._mock_model(facts)):
            result = mod.inspect_devices([])
        assert set(result["found"].keys()) == {"R1", "R2"}

    def test_none_values_excluded_from_found(self):
        mod = _load("inspect_devices")
        facts = {"R3": {"platform": "cisco_ios", "loopback": None}}
        with patch.object(mod, "load_network_model", return_value=self._mock_model(facts)):
            result = mod.inspect_devices(["R3"])
        assert "loopback" not in result["found"]["R3"]

    def test_function_signature_has_devices_param(self):
        mod = _load("inspect_devices")
        sig = inspect.signature(mod.inspect_devices)
        assert "devices" in sig.parameters

    def test_both_workspace_copies_identical(self):
        auth = (SCRIPTS / "inspect_devices.py").read_bytes()
        dev = (DEV_SCRIPTS / "inspect_devices.py").read_bytes()
        assert auth == dev, "inspect_devices.py dev mirror diverged from authoritative"


# ---------------------------------------------------------------------------
# inspect_interfaces
# ---------------------------------------------------------------------------


class TestInspectInterfaces:
    def _make_con(self, ios_rows=None, jun_rows=None, ios_snap="snap1", jun_snap=None):
        con = MagicMock()

        def _execute(sql, params=None):
            cur = MagicMock()
            sql_stripped = " ".join(sql.split())
            if "MAX(snapshot_id)" in sql and "v_show_ip_interface_brief_auto" in sql:
                cur.fetchone.return_value = (ios_snap,) if ios_snap else (None,)
            elif "MAX(snapshot_id)" in sql and "v_show_interfaces_terse_auto" in sql:
                cur.fetchone.return_value = (jun_snap,) if jun_snap else (None,)
            elif "v_show_ip_interface_brief_auto" in sql and "ORDER BY" in sql:
                cur.fetchall.return_value = ios_rows or []
            elif "v_show_interfaces_terse_auto" in sql and "ORDER BY" in sql:
                cur.fetchall.return_value = jun_rows or []
            elif "DISTINCT device_name" in sql:
                cur.fetchall.return_value = [("R1",)]
            else:
                cur.fetchall.return_value = []
                cur.fetchone.return_value = (None,)
            return cur

        con.execute.side_effect = _execute
        con.__enter__ = lambda s: s
        con.__exit__ = MagicMock(return_value=False)
        return con

    def test_found_ios_interfaces(self, tmp_path):
        mod = _load("inspect_interfaces")
        db = tmp_path / ".olav" / "databases" / "main.duckdb"
        db.parent.mkdir(parents=True)
        db.touch()
        con = self._make_con(
            ios_rows=[("Ethernet0/0", "10.1.1.1", "up", "up")],
            ios_snap="snap1",
        )
        with patch.object(mod, "_db_path", return_value=db), \
             patch("duckdb.connect", return_value=con):
            result = mod.inspect_interfaces(["R1"])
        assert "R1" in result["found"]
        assert result["found"]["R1"][0]["ip_address"] == "10.1.1.1"
        assert result["unknown_devices"] == []

    def test_unassigned_filtered_by_default(self, tmp_path):
        mod = _load("inspect_interfaces")
        db = tmp_path / "main.duckdb"
        db.touch()
        con = self._make_con(
            ios_rows=[
                ("Ethernet0/0", "unassigned", "up", "up"),
                ("Loopback0", "1.1.1.1", "up", "up"),
            ],
        )
        with patch.object(mod, "_db_path", return_value=db), \
             patch("duckdb.connect", return_value=con):
            result = mod.inspect_interfaces(["R1"])
        ifaces = result["found"].get("R1", [])
        inames = [i["interface"] for i in ifaces]
        assert "Loopback0" in inames
        assert "Ethernet0/0" not in inames

    def test_missing_db_returns_error(self, tmp_path):
        mod = _load("inspect_interfaces")
        with patch.object(mod, "_db_path", return_value=tmp_path / "nonexistent.duckdb"):
            result = mod.inspect_interfaces(["R1"])
        assert "error" in result
        assert result["unknown_devices"] == ["R1"]

    def test_function_signature(self):
        mod = _load("inspect_interfaces")
        sig = inspect.signature(mod.inspect_interfaces)
        assert "devices" in sig.parameters
        assert "include_unassigned" in sig.parameters

    def test_both_workspace_copies_identical(self):
        auth = (SCRIPTS / "inspect_interfaces.py").read_bytes()
        dev = (DEV_SCRIPTS / "inspect_interfaces.py").read_bytes()
        assert auth == dev, "inspect_interfaces.py dev mirror diverged from authoritative"


# inspect_routing was removed from analyzer (2026-05-27, commit 53825f92):
# routing state is queried via execute_sql on BGP/OSPF views directly.
# See tests/governance/test_step_c_analyze_merge.py::test_inspect_routing_moved_to_reporter_or_dropped


class _REMOVED_TestInspectRouting:
    def _mock_model(
        self,
        graph_nodes: list[str] | None = None,
        edges: dict | None = None,
        facts: dict | None = None,
    ) -> MagicMock:
        import networkx as nx
        g = nx.DiGraph()
        for n in (graph_nodes or []):
            g.add_node(n)
        for (src, dst), attrs in (edges or {}).items():
            g.add_edge(src, dst, **attrs)
        m = MagicMock()
        m.graph = g
        m.facts = facts or {}
        return m

    def test_bgp_session_from_graph(self):
        mod = _load("inspect_routing")
        model = self._mock_model(
            graph_nodes=["R1", "R2"],
            edges={("R1", "R2"): {"bgp_session": True, "bgp_neighbor_ip": "2.2.2.2",
                                   "bgp_neighbor_as": 65002, "bgp_session_state": "Established",
                                   "bgp_prefixes_received": 10}},
        )
        with patch.object(mod, "load_network_model", return_value=model), \
             patch("duckdb.connect") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.return_value.execute.return_value.fetchall.return_value = []
            result = mod.inspect_routing(["R1"], protocol="bgp")
        assert "R1" in result
        bgp = result["R1"]["bgp"]
        assert len(bgp) == 1
        assert bgp[0]["neighbor"] == "R2"
        assert bgp[0]["state"] == "Established"
        assert bgp[0]["resolved"] is True

    def test_device_not_in_graph_skipped(self):
        mod = _load("inspect_routing")
        model = self._mock_model(graph_nodes=["R1"])
        with patch.object(mod, "load_network_model", return_value=model), \
             patch("duckdb.connect") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.return_value.execute.return_value.fetchall.return_value = []
            result = mod.inspect_routing(["R999"], protocol="bgp")
        assert "R999" not in result

    def test_ospf_only_protocol_filter(self):
        mod = _load("inspect_routing")
        model = self._mock_model(
            graph_nodes=["R1", "R2"],
            edges={("R1", "R2"): {"bgp_session": True, "ospf_state": "FULL"}},
        )
        with patch.object(mod, "load_network_model", return_value=model), \
             patch("duckdb.connect") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            result = mod.inspect_routing(["R1"], protocol="ospf")
        assert result["R1"]["bgp"] == []
        assert result["R1"]["ospf"][0]["neighbor"] == "R2"

    def test_function_signature(self):
        mod = _load("inspect_routing")
        sig = inspect.signature(mod.inspect_routing)
        assert "devices" in sig.parameters
        assert "protocol" in sig.parameters

    def test_duckdb_opened_read_only(self):
        src = (SCRIPTS / "inspect_routing.py").read_text(encoding="utf-8")
        assert "read_only=True" in src

    def test_both_workspace_copies_identical(self):
        auth = (SCRIPTS / "inspect_routing.py").read_bytes()
        dev = (DEV_SCRIPTS / "inspect_routing.py").read_bytes()
        assert auth == dev, "inspect_routing.py dev mirror diverged from authoritative"


# ---------------------------------------------------------------------------
# SKILL.md declarations
# ---------------------------------------------------------------------------


class TestSkillMdDeclarations:
    """Verify both workspace copies declare the three scripts in SKILL.md."""

    @pytest.mark.parametrize("workspace", [
        REPO / "olav-netops" / ".olav" / "workspace" / "netops" / "analyzer",
        REPO / ".olav" / "workspace" / "netops" / "analyzer",
    ])
    @pytest.mark.parametrize("script_name", [
        "inspect_devices", "inspect_interfaces",
    ])
    def test_script_declared_in_skill_md(self, workspace, script_name):
        skill_md = workspace / "SKILL.md"
        assert skill_md.exists(), f"SKILL.md not found: {skill_md}"
        text = skill_md.read_text(encoding="utf-8")
        assert script_name in text, (
            f"{script_name} not declared in {skill_md.relative_to(REPO)}"
        )

    @pytest.mark.parametrize("workspace", [
        REPO / "olav-netops" / ".olav" / "workspace" / "netops" / "analyzer",
        REPO / ".olav" / "workspace" / "netops" / "analyzer",
    ])
    def test_skill_md_frontmatter_has_all_three_in_scripts_block(self, workspace):
        import yaml
        skill_md = workspace / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        front = text.split("---", 2)[1]
        meta = yaml.safe_load(front) or {}
        script_names = {s["name"] for s in meta.get("scripts", []) if isinstance(s, dict)}
        for name in ("inspect_devices", "inspect_interfaces"):
            assert name in script_names, (
                f"{name} not in scripts: block of {skill_md.relative_to(REPO)}"
            )

    @pytest.mark.parametrize("workspace", [
        REPO / "olav-netops" / ".olav" / "workspace" / "netops" / "analyzer",
        REPO / ".olav" / "workspace" / "netops" / "analyzer",
    ])
    def test_inspect_tool_files_removed_from_netops_tools(self, workspace):
        tools_dir = workspace.parent / "tools"
        for name in ("inspect_devices.py", "inspect_interfaces.py", "inspect_routing.py"):
            assert not (tools_dir / name).exists(), (
                f"@tool file still present after migration: {tools_dir / name}"
            )
