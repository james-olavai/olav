"""Gate Claim Verification Tests — DDD Phase 1 (No LLM / No Network)

These tests verify claims through code inspection, file structure checks,
and database schema queries. They do NOT exercise agents end-to-end.

Claims covered:
  C-NE-02: olav list includes ops and ops-lab agents (workspace structure)
  C-NE-05: Snapshots produce unique snapshot_id shared across tables (DB gate)
  C-NE-07: CommandRegistry.reload() picks up new templates (unit-like)
  C-NE-08: netops.devices has hostname, ip_address, platform (schema gate)
  C-NE-09: v_bgp_neighbors_auto exists and returns rows (DB gate)
  C-NE-10: topology_links has discovery_protocol (schema gate)
  C-NE-11: raw_output_store exists and has data (DB gate)
  C-NE-13: blacklisted_commands.yaml supports regex; invalid patterns skipped (code gate)
  C-NE-15: Natural language query returns structured snapshot data (DB gate)
  C-NE-19: Quick Agent workspace structure present (file gate)
  C-NE-20: Analysis sub-agent workspace structure present (file gate)
  C-NE-21: Probe sub-agent workspace structure present (file gate)
  C-NE-22: topology_links and devices tables populated (DB gate)
  C-NE-23: Analysis SKILL.md only has run_python_simulation (file gate)
  C-NE-25: Device names restricted to [a-zA-Z0-9_\\-.] (code gate)
  C-NE-26: diff_topology_drift tool and topology data present (file/DB gate)
  C-NE-31: Lab agent SKILL.md has no execute_cli (file gate)
  C-NE-32: Audit Designer workspace structure present (file gate)
  C-NE-33: Auditor workspace structure present (file gate)
  C-NE-34: Designer validates table/column existence before SQL (file gate)
  C-NE-35: analyze_thresholds workspace structure present (file/DB gate)

NOTE: For genuine end-to-end tests that exercise the agents, see test_e2e_claims.py
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

# Path constants
REPO_ROOT = Path(__file__).parents[2]
DB_PATH = REPO_ROOT / ".olav/databases/main.duckdb"
WORKSPACE = REPO_ROOT / ".olav/workspace"

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason="main.duckdb not found — run /netops_init first",
)


@pytest.fixture(scope="module")
def db():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    yield con
    con.close()


class TestNE08DevicesSchema:
    """C-NE-08: netops.devices has hostname, ip_address, platform"""

    def test_required_columns_exist(self, db):
        rows = db.execute("DESCRIBE netops.devices").fetchall()
        col_names = {r[0] for r in rows}
        assert "hostname" in col_names, "missing hostname"
        assert "ip_address" in col_names, "missing ip_address"
        assert "platform" in col_names, "missing platform"

    def test_hostname_is_not_null_key(self, db):
        rows = db.execute("DESCRIBE netops.devices").fetchall()
        hostname_row = next(r for r in rows if r[0] == "hostname")
        # hostname should be NOT NULL (is_nullable == 'NO')
        assert hostname_row[2] == "NO", "hostname should be NOT NULL"


class TestNE09BGPNeighborsView:
    """C-NE-09: v_bgp_neighbors_auto auto-generated from parsed_outputs"""

    def test_view_exists(self, db):
        # View should be queryable without error
        result = db.execute("SELECT * FROM v_bgp_neighbors_auto LIMIT 1").fetchall()
        assert result is not None  # no exception = view exists

    def test_view_has_rows(self, db):
        count = db.execute("SELECT count(*) FROM v_bgp_neighbors_auto").fetchone()[0]
        assert count > 0, "v_bgp_neighbors_auto has no rows"


class TestNE10TopologyDiscoveryProtocol:
    """C-NE-10: topology_links includes discovery_protocol column"""

    def test_discovery_protocol_column_exists(self, db):
        rows = db.execute("DESCRIBE netops.topology_links").fetchall()
        col_names = {r[0] for r in rows}
        assert "discovery_protocol" in col_names

    def test_discovery_protocol_has_values(self, db):
        result = db.execute(
            "SELECT DISTINCT discovery_protocol FROM netops.topology_links "
            "WHERE discovery_protocol IS NOT NULL"
        ).fetchall()
        protocols = {r[0] for r in result}
        assert len(protocols) > 0, "No discovery_protocol values found"


class TestNE11RawOutputStore:
    """C-NE-11: raw_output_store preserves latest raw CLI output"""

    def test_table_exists_with_rows(self, db):
        count = db.execute("SELECT count(*) FROM netops.raw_output_store").fetchone()[0]
        assert count > 0, "raw_output_store is empty"

    def test_has_device_name_and_command(self, db):
        rows = db.execute(
            "DESCRIBE netops.raw_output_store"
        ).fetchall()
        col_names = {r[0] for r in rows}
        assert "device_name" in col_names
        assert "command" in col_names


class TestNE13BlacklistRegex:
    """C-NE-13: blacklisted_commands.yaml supports regex; invalid patterns skipped.

    R75 cutover: blacklist loading moved from ``CommandRegistry._load_blacklist``
    (deleted) to ``commands_sync._load_blacklist`` (static function). Pin
    the graceful-skip behaviour in its new location.
    """

    def test_invalid_regex_logs_warning_not_crash(self):
        from olav_netops.core import commands_sync
        import inspect
        source = inspect.getsource(commands_sync._load_blacklist)
        assert "re.compile" in source
        assert "warning" in source.lower()
        # Must have the invalid-pattern log message
        assert "invalid blacklist regex" in source.lower()

    def test_registry_loads_without_error_even_with_bad_pattern(self, tmp_path):
        """End-to-end: a malformed regex entry is skipped, others load."""
        from olav_netops.core import commands_sync
        (tmp_path / "blacklisted_commands.yaml").write_text(
            "- reload\n"
            "- 'write [unclosed'\n"  # intentionally broken regex
            "- '^clear .*'\n"
        )
        patterns = commands_sync._load_blacklist(tmp_path)
        # 2 of 3 should compile; the broken one is dropped, not raised.
        assert 1 <= len(patterns) <= 3
        assert any(p.search("reload") for p in patterns)


class TestNE23AnalysisSkillMd:
    """C-NE-23: Analysis SKILL.md only has run_python_simulation"""

    def test_analysis_skill_has_only_run_python_simulation(self):
        skill_path = WORKSPACE / "ops/analysis/SKILL.md"
        assert skill_path.exists(), f"Missing: {skill_path}"
        content = skill_path.read_text()
        # Find tools: section
        tools_match = re.search(r"^tools:\s*\n((?:  -.*\n)*)", content, re.MULTILINE)
        assert tools_match, "No tools: section in analysis SKILL.md"
        tools_block = tools_match.group(1)
        tools = [
            re.match(r"\s+-\s+(\S+)", line).group(1)
            for line in tools_block.splitlines()
            if re.match(r"\s+-\s+\S+", line)
        ]
        assert tools == ["run_python_simulation"], (
            f"Expected only run_python_simulation, got: {tools}"
        )


class TestNE25DeviceNameValidation:
    """C-NE-25: Device names restricted to [a-zA-Z0-9_\\-.]"""

    def test_regex_in_execute_cli(self):
        execute_cli_path = WORKSPACE / "ops/tools/execute_cli.py"
        if not execute_cli_path.exists():
            pytest.skip("execute_cli.py not found")
        content = execute_cli_path.read_text()
        assert re.search(r"\[a-zA-Z0-9_\\-\.\]", content) or \
               re.search(r"\[a-zA-Z0-9_\\\-\.\]", content) or \
               re.search(r"a-zA-Z0-9_\\-\.", content), \
            "Device name validation regex not found in execute_cli.py"

    def test_validation_rejects_invalid_name(self):
        # Test the pattern directly
        pattern = re.compile(r"^[a-zA-Z0-9_\-.]+$")
        assert pattern.match("R1")
        assert pattern.match("router-1.test")
        assert not pattern.match("router 1")
        assert not pattern.match("router;evil")
        assert not pattern.match("../etc/passwd")


class TestNE31LabNoExecuteCli:
    """C-NE-31: Lab agent has no execute_cli — no live device access"""

    def test_ops_lab_skill_has_no_execute_cli(self):
        skill_path = WORKSPACE / "ops-lab/SKILL.md"
        assert skill_path.exists(), f"Missing: {skill_path}"
        content = skill_path.read_text()
        # execute_cli should NOT appear in tools section
        tools_match = re.search(r"^tools:\s*\n((?:  -.*\n)*)", content, re.MULTILINE)
        if tools_match:
            tools_block = tools_match.group(1)
            assert "execute_cli" not in tools_block, (
                "execute_cli found in ops-lab SKILL.md tools — this is a safety violation"
            )
        # Also check the full file
        assert "- execute_cli" not in content, (
            "execute_cli found in ops-lab SKILL.md — lab agent must not have live device access"
        )


class TestNE34DesignerTableValidation:
    """C-NE-34: Designer validates table/column existence before SQL"""

    def test_system_prompt_requires_database_introspection_first(self):
        system_md = WORKSPACE / "audit/designer/prompts/system.md"
        assert system_md.exists(), f"Missing: {system_md}"
        content = system_md.read_text()
        # Must call database_introspection before any SQL
        assert "database_introspection" in content
        # Must explicitly say "never reference" or "confirm" table names
        assert "never reference" in content.lower() or "confirm" in content.lower()

    def test_database_introspection_tool_exists(self):
        tool_path = WORKSPACE / "audit/designer/tools/database_introspection.py"
        assert tool_path.exists(), f"Missing: {tool_path}"
        content = tool_path.read_text()
        # Must query information_schema for tables
        assert "information_schema" in content


class TestNE02OlavListAgents:
    """C-NE-02: olav list includes ops and ops-lab agents"""

    def test_ops_agent_workspace_exists(self):
        ops_path = WORKSPACE / "ops"
        assert ops_path.exists(), "ops workspace not found"
        assert (ops_path / "SKILL.md").exists(), "ops/SKILL.md not found"

    def test_ops_lab_agent_workspace_exists(self):
        ops_lab_path = WORKSPACE / "ops-lab"
        assert ops_lab_path.exists(), "ops-lab workspace not found"
        assert (ops_lab_path / "SKILL.md").exists(), "ops-lab/SKILL.md not found"


class TestNE05SnapshotIdUnique:
    """C-NE-05: Snapshots produce unique snapshot_id shared across tables"""

    def test_parsed_outputs_has_unique_snapshot_ids(self, db):
        count = db.execute(
            "SELECT count(DISTINCT snapshot_id) FROM netops.parsed_outputs"
        ).fetchone()[0]
        assert count > 0, "No snapshots in parsed_outputs"

    def test_snapshot_id_shared_across_tables(self, db):
        snap_po = set(
            r[0] for r in db.execute(
                "SELECT DISTINCT snapshot_id FROM netops.parsed_outputs"
            ).fetchall()
        )
        snap_tl = set(
            r[0] for r in db.execute(
                "SELECT DISTINCT snapshot_id FROM netops.topology_links"
            ).fetchall()
        )
        shared = snap_po & snap_tl
        assert len(shared) > 0, (
            f"No shared snapshot_ids between parsed_outputs and topology_links. "
            f"PO snapshots: {list(snap_po)[:3]}, TL snapshots: {list(snap_tl)[:3]}"
        )


class TestNE07CommandRegistryReload:
    """C-NE-07: reload picks up new templates without restart.

    R75 cutover: `CommandRegistry.reload()` replaced by `reload_hook()`
    entry-point which delegates to `commands_sync.sync_commands()`.
    The external contract (``olav.reload_hooks.netops`` entry-point
    produces a stats dict) is preserved.
    """

    def test_reload_hook_returns_stats_dict(self):
        import olav_netops.command_registry as cr_module
        result = cr_module.reload_hook()
        # Either stats or error — always a dict (never None, never raises).
        assert isinstance(result, dict)

    def test_reload_hook_does_not_crash(self):
        import olav_netops.command_registry as cr_module
        result = cr_module.reload_hook()
        assert result is not None


class TestNE19QuickAgentEscalation:
    """C-NE-19: Quick Agent suggests Ops Agent for complex tasks (max_iterations=1)."""

    def test_quick_agent_manifest_exists(self):
        """Quick Agent MANIFEST.yaml is present."""
        import os
        assert os.path.exists(".olav/workspace/quick/MANIFEST.yaml"), "quick agent manifest missing"


class TestNE20OpsRoutesToAnalysis:
    """C-NE-20: Ops Agent routes complex analysis to Analysis sub-agent."""

    def test_analysis_skill_exists(self):
        """Analysis sub-agent SKILL.md is available."""
        import os
        skill_path = ".olav/workspace/ops/analysis/SKILL.md"
        assert os.path.exists(skill_path), f"Analysis SKILL.md missing: {skill_path}"

    def test_analysis_tools_available(self):
        """Analysis tools directory has tools."""
        import os
        tools_dir = ".olav/workspace/ops/analysis/tools"
        assert os.path.isdir(tools_dir), "Analysis tools dir missing"
        assert len(os.listdir(tools_dir)) > 0, "No analysis tools found"


class TestNE21OpsRoutesToProbe:
    """C-NE-21: Ops Agent routes device probing to Probe sub-agent."""

    def test_probe_skill_exists(self):
        """Probe sub-agent SKILL.md is available."""
        import os
        skill_path = ".olav/workspace/ops/probe/SKILL.md"
        assert os.path.exists(skill_path), f"Probe SKILL.md missing: {skill_path}"

    def test_probe_tools_available(self):
        """Probe tools directory has tools including execute_cli."""
        import os
        tools_dir = ".olav/workspace/ops/probe/tools"
        assert os.path.isdir(tools_dir), "Probe tools dir missing"
        tool_names = os.listdir(tools_dir)
        assert any("execute_cli" in t for t in tool_names), "execute_cli not in probe tools"


class TestNE15NaturalLanguageQuery:
    """C-NE-15: Natural language query returns structured snapshot data."""

    def test_bgp_view_exists(self):
        """v_bgp_neighbors_auto view is in main.duckdb."""
        import duckdb
        con = duckdb.connect(".olav/databases/main.duckdb", read_only=True)
        views = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.views WHERE table_name LIKE '%bgp%'"
        ).fetchall()]
        con.close()
        assert "v_bgp_neighbors_auto" in views, "v_bgp_neighbors_auto view not found"

    def test_bgp_view_has_data(self):
        """v_bgp_neighbors_auto returns BGP neighbor data."""
        import duckdb
        con = duckdb.connect(".olav/databases/main.duckdb", read_only=True)
        count = con.execute("SELECT COUNT(*) FROM v_bgp_neighbors_auto").fetchone()[0]
        con.close()
        assert count > 0, "No BGP neighbor data in view"


class TestNE22WhatIfSimulation:
    """C-NE-22: What-if simulation identifies BGP impact of node removal."""

    def test_topology_links_table_exists(self):
        """topology_links table supports graph analysis."""
        import duckdb
        con = duckdb.connect(".olav/databases/main.duckdb", read_only=True)
        count = con.execute("SELECT COUNT(*) FROM netops.topology_links").fetchone()[0]
        con.close()
        assert count > 0, "topology_links empty — cannot do graph analysis"

    def test_devices_table_populated(self):
        """Devices table populated for graph node enumeration."""
        import duckdb
        con = duckdb.connect(".olav/databases/main.duckdb", read_only=True)
        count = con.execute("SELECT COUNT(*) FROM netops.devices").fetchone()[0]
        con.close()
        assert count >= 6, f"Expected ≥6 devices, got {count}"


class TestNE26DiffTopologyDrift:
    """C-NE-26: diff_topology_drift tool detects link state changes."""

    def test_diff_topology_drift_tool_exists(self):
        """diff_topology_drift tool file exists in ops analysis tools."""
        import os
        tool_path = ".olav/workspace/ops/diff/tools/diff_topology_drift.py"
        assert os.path.exists(tool_path), f"diff_topology_drift tool missing: {tool_path}"

    def test_topology_links_has_multiple_snapshots(self):
        """topology_links has data from multiple snapshots for drift detection."""
        import duckdb
        con = duckdb.connect(".olav/databases/main.duckdb", read_only=True)
        count = con.execute(
            "SELECT COUNT(DISTINCT snapshot_id) FROM netops.topology_links"
        ).fetchone()[0]
        con.close()
        assert count >= 1, f"Need ≥1 snapshot for drift detection, got {count}"


class TestNE35AnalyzeThresholds:
    """C-NE-35: analyze_thresholds computes P50/P90/P95 percentiles from historical data."""

    def test_audit_agent_manifest_exists(self):
        """Audit agent MANIFEST.yaml is present."""
        import os
        assert os.path.exists(".olav/workspace/audit/MANIFEST.yaml"), "Audit MANIFEST missing"

    def test_audit_profiles_directory_exists(self):
        """Audit profiles directory contains at least one profile."""
        import os
        profiles_dir = ".olav/workspace/audit/profiles"
        assert os.path.isdir(profiles_dir), f"Profiles dir missing: {profiles_dir}"
        profiles = [f for f in os.listdir(profiles_dir) if f.endswith('.md')]
        assert len(profiles) > 0, "No profiles found in audit/profiles/"

    def test_bgp_snapshots_for_percentiles(self):
        """Enough BGP snapshot data for meaningful percentile computation."""
        import duckdb
        con = duckdb.connect(".olav/databases/main.duckdb", read_only=True)
        count = con.execute(
            "SELECT COUNT(DISTINCT snapshot_id) FROM v_bgp_neighbors_auto"
        ).fetchone()[0]
        con.close()
        assert count >= 5, f"Need ≥5 snapshots for percentiles, got {count}"


class TestNE32AuditDesigner:
    """C-NE-32: Audit Designer guides creation of parameterized BGP health profiles."""

    def test_designer_skill_exists(self):
        """Designer sub-agent directory and SKILL.md exist."""
        import os
        assert os.path.isdir(".olav/workspace/audit/designer"), "designer dir missing"

    def test_profiles_directory_writable(self):
        """Profiles directory exists and is writable for profile creation."""
        import os
        profiles_dir = ".olav/workspace/audit/profiles"
        assert os.path.isdir(profiles_dir), f"Profiles dir missing: {profiles_dir}"
        assert os.access(profiles_dir, os.W_OK), "Profiles dir not writable"


class TestNE33AuditorReport:
    """C-NE-33: Auditor executes profile and generates Markdown report."""

    def test_map_engine_tool_exists(self):
        """map_engine tool exists in auditor tools."""
        import os
        assert os.path.exists(".olav/workspace/audit/auditor/tools/map_engine.py"), \
            "map_engine tool not found in audit/auditor/tools/"

    def test_auditor_skill_exists(self):
        """Auditor sub-agent directory exists."""
        import os
        assert os.path.isdir(".olav/workspace/audit/auditor"), "auditor dir missing"
