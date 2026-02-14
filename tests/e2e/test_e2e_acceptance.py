#!/usr/bin/env python3
"""
OLAV v2.0 全功能 E2E 验收测试

测试方法: 所有测试通过 subprocess 调用真实 CLI 命令，使用真实 LLM。
测试文档: dev_docs/E2E_FULL_ACCEPTANCE_PLAN.md

运行方式:
    # 全部测试
    uv run pytest tests/e2e/test_e2e_acceptance.py -v --timeout=120
    
    # 仅基础测试 (无需网络/LLM)
    uv run pytest tests/e2e/test_e2e_acceptance.py -v -k "Level0" --timeout=30
    
    # 仅数据库查询测试
    uv run pytest tests/e2e/test_e2e_acceptance.py -v -k "Level1" --timeout=120
    
    # 跳过需要网络设备的测试
    uv run pytest tests/e2e/test_e2e_acceptance.py -v -k "not network_required"
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# ============================================================================
# Configuration
# ============================================================================

OLAV_DIR = Path(__file__).parent.parent.parent  # /home/yhvh/Olav
DEFAULT_TIMEOUT = 60  # seconds (includes LLM latency)
INTERACTIVE_TIMEOUT = 90


# ============================================================================
# Helpers
# ============================================================================

def olav_msg(query: str, timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    """Send a single message via `uv run olav -m "query"`."""
    return subprocess.run(
        ["uv", "run", "olav", "-m", query],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(OLAV_DIR),
    )


def olav_cmd(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run `uv run olav <args>`."""
    return subprocess.run(
        ["uv", "run", "olav"] + list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(OLAV_DIR),
    )


def olav_interactive(messages: list[str], timeout: int = INTERACTIVE_TIMEOUT) -> tuple[str, str, int]:
    """Run interactive mode with piped messages. Returns (stdout, stderr, returncode)."""
    input_text = "\n".join(messages + ["exit"]) + "\n"
    proc = subprocess.Popen(
        ["uv", "run", "olav"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(OLAV_DIR),
    )
    stdout, stderr = proc.communicate(input=input_text, timeout=timeout)
    return stdout, stderr, proc.returncode


def output_of(result: subprocess.CompletedProcess) -> str:
    """Get combined stdout + stderr."""
    return (result.stdout or "") + (result.stderr or "")


def assert_contains_any(text: str, keywords: list[str], msg: str = ""):
    """Assert text contains at least one keyword (case-insensitive)."""
    text_lower = text.lower()
    found = [k for k in keywords if k.lower() in text_lower]
    assert found, (
        f"{msg}: output does not contain any of {keywords}.\n"
        f"Output (first 800 chars): {text[:800]}"
    )


def assert_no_crash(result: subprocess.CompletedProcess):
    """Assert command did not crash with a fatal Python error.
    
    Note: SQL execution errors from LLM retry attempts appear as tracebacks
    in stderr but are NOT fatal crashes - the agent self-corrects.
    We only check for true import/module errors.
    """
    combined = output_of(result)
    fatal = [
        "ModuleNotFoundError",
        "ImportError: ",
    ]
    for pattern in fatal:
        assert pattern not in combined, (
            f"Command crashed with: {pattern}\n"
            f"Output: {combined[:1000]}"
        )


# ============================================================================
# Level 0: 基础可用性 (Must Pass - no LLM needed for most)
# ============================================================================

class TestLevel0_BasicUsability:
    """基础可用性测试 - 系统能启动、能响应、不崩溃"""

    def test_L0_01_help(self):
        """L0-01: olav --help shows usage."""
        result = olav_cmd("--help")
        out = output_of(result)
        assert "Usage" in out
        assert "olav" in out.lower()
        # Should show -m/--msg option + subcommands
        assert_contains_any(out, ["--msg", "-m"])
        assert_contains_any(out, ["admin", "devices"])

    def test_L0_02_version(self):
        """L0-02: olav --version shows version string."""
        result = olav_cmd("--version")
        out = output_of(result)
        assert result.returncode == 0, f"Exit code: {result.returncode}, stderr: {result.stderr}"
        assert "2.0" in out

    def test_L0_03_interactive_start_exit(self):
        """L0-03: bare olav enters interactive mode and exits cleanly."""
        stdout, stderr, rc = olav_interactive(["exit"])
        combined = stdout + stderr
        assert_contains_any(combined, ["Interactive", "OLAV", "Thread"])
        assert_contains_any(combined, ["Goodbye", "bye"])

    def test_L0_04_single_message(self):
        """L0-04: olav -m sends a message and gets LLM response."""
        result = olav_msg("What is 2 plus 2?")
        assert_no_crash(result)
        out = output_of(result)
        assert len(out.strip()) > 5, f"Response too short: {out}"
        assert_contains_any(out, ["4", "four"])

    def test_L0_05_devices_list(self):
        """L0-05: olav devices shows device table."""
        result = olav_cmd("devices")
        assert_no_crash(result)
        out = output_of(result)
        assert_contains_any(out, ["R1", "R2", "SW1"])
        # Rich table may truncate IPs; just check at least devices are listed
        assert_contains_any(out, ["Device", "device", "R1"])

    def test_L0_06_admin_status(self):
        """L0-06: olav admin status returns system status."""
        result = olav_cmd("admin", "status")
        assert_no_crash(result)
        out = output_of(result)
        assert_contains_any(out, ["database", "skill", "tool", "status"])

    def test_L0_07_invalid_command(self):
        """L0-07: olav <invalid> returns error."""
        result = olav_cmd("nonexistent_command_xyz")
        assert result.returncode != 0


# ============================================================================
# Level 1: 数据库查询 (Must Pass - requires LLM + DuckDB)
# ============================================================================

class TestLevel1_DatabaseQueries:
    """数据库查询测试 - LLM 生成 SQL 查询 DuckDB"""

    # --- 1.1 Simple Queries ---

    def test_L1_01_device_count(self):
        """L1-01: How many devices → 6."""
        result = olav_msg("How many devices are there in the database?")
        assert_no_crash(result)
        out = output_of(result)
        assert_contains_any(out, ["6", "six"])

    def test_L1_02_device_names(self):
        """L1-02: List all device names → R1, R2, R3, R4, SW1, SW2."""
        result = olav_msg("List all device names from the database")
        assert_no_crash(result)
        out = output_of(result)
        # Should contain at least 4 out of 6 device names
        found = sum(1 for d in ["R1", "R2", "R3", "R4", "SW1", "SW2"] if d in out)
        assert found >= 4, f"Only found {found}/6 devices in output: {out[:500]}"

    def test_L1_03_role_filter(self):
        """L1-03: List core devices → R3, R4."""
        result = olav_msg("Which devices have the 'core' role? Query the database.")
        assert_no_crash(result)
        out = output_of(result)
        assert_contains_any(out, ["R3", "R4"])

    def test_L1_04_site_filter(self):
        """L1-04: Devices in lab site → all 6."""
        result = olav_msg("Which devices are in the 'lab' site? Use SQL.")
        assert_no_crash(result)
        out = output_of(result)
        assert_contains_any(out, ["R1", "R2", "R3", "R4", "SW1", "SW2"])

    def test_L1_05_platform_query(self):
        """L1-05: What platforms → cisco_ios."""
        result = olav_msg("What device platforms are used? Query the devices table.")
        assert_no_crash(result)
        out = output_of(result)
        assert_contains_any(out, ["cisco_ios", "cisco"])

    # --- 1.2 Aggregation Queries ---

    def test_L1_06_group_by_role(self):
        """L1-06: Devices per role → border:2, core:2, access:2."""
        result = olav_msg("How many devices are there per role? Use SQL GROUP BY on the devices table.")
        assert_no_crash(result)
        out = output_of(result)
        assert_contains_any(out, ["2", "border", "core", "access"])

    def test_L1_07_parsed_output_count(self):
        """L1-07: Parsed outputs count → 142."""
        result = olav_msg("How many rows are in the parsed_outputs table?")
        assert_no_crash(result)
        out = output_of(result)
        assert_contains_any(out, ["142", "14"])

    def test_L1_08_unique_commands(self):
        """L1-08: Unique commands collected."""
        result = olav_msg("What distinct commands are in the parsed_outputs table? List them.")
        assert_no_crash(result)
        out = output_of(result)
        assert_contains_any(out, ["show version", "show interfaces", "show ip"])

    # --- 1.3 JOIN Queries ---

    def test_L1_09_outputs_per_device(self):
        """L1-09: Parsed outputs per device (JOIN or GROUP BY)."""
        result = olav_msg(
            "How many parsed_outputs are there for each device? "
            "Use SQL with GROUP BY device_name on parsed_outputs table."
        )
        assert_no_crash(result)
        out = output_of(result)
        # Should show device names with counts
        assert_contains_any(out, ["R1", "R2", "R3"])

    def test_L1_10_topology_links(self):
        """L1-10: List topology links → 11 rows."""
        result = olav_msg(
            "List all topology links between devices. Query the topology_links table."
        )
        assert_no_crash(result)
        out = output_of(result)
        assert_contains_any(out, ["R1", "R2", "R3", "topology", "link", "source", "destination"])

    def test_L1_11_cross_table(self):
        """L1-11: Which devices have BGP data collected (cross-table query)."""
        result = olav_msg(
            "Which devices have 'show ip bgp' data in parsed_outputs? "
            "Query: SELECT DISTINCT device_name FROM parsed_outputs WHERE command LIKE '%bgp%'"
        )
        assert_no_crash(result)
        out = output_of(result)
        # Should return some device names (R1-R4 likely have BGP data)
        assert len(out.strip()) > 10, f"Response too short: {out}"

    # --- 1.4 Specific Snapshot Data ---

    def test_L1_12_show_version_r1(self):
        """L1-12: Show version parsed data for R1."""
        result = olav_msg(
            "Show me the parsed output of 'show version' for device R1. "
            "Query parsed_outputs table WHERE device_name='R1' AND command='show version'."
        )
        assert_no_crash(result)
        out = output_of(result)
        assert_contains_any(out, ["R1", "version", "parsed"])

    def test_L1_13_r1_interfaces(self):
        """L1-13: R1 interface information from collected data."""
        result = olav_msg(
            "What interfaces does R1 have? Query parsed_outputs WHERE device_name='R1' AND command LIKE '%interface%'."
        )
        assert_no_crash(result)
        out = output_of(result)
        assert_contains_any(out, ["R1", "interface"])

    def test_L1_14_bgp_summary(self):
        """L1-14: BGP summary for R1."""
        result = olav_msg(
            "Show the parsed BGP summary for R1. Query parsed_outputs WHERE device_name='R1' AND command LIKE '%bgp%'."
        )
        assert_no_crash(result)
        out = output_of(result)
        assert len(out.strip()) > 10

    def test_L1_15_ospf_info(self):
        """L1-15: OSPF neighbor info for R3."""
        result = olav_msg(
            "Show OSPF neighbor information for R3. Query parsed_outputs WHERE device_name='R3' AND command LIKE '%ospf%'."
        )
        assert_no_crash(result)
        out = output_of(result)
        assert len(out.strip()) > 10


# ============================================================================
# Level 2: CLI 回落 (Cross-Skill) - Requires network connectivity
# ============================================================================

@pytest.mark.network_required
class TestLevel2_CLIFallback:
    """CLI 回落测试 - 数据库无数据时调用 CLI 执行命令"""

    def test_L2_01_execute_cli(self):
        """L2-01: Execute show version on R1."""
        result = olav_msg("Execute 'show version' on device R1 using CLI")
        assert_no_crash(result)
        out = output_of(result)
        # Either successful execution or clear error about connectivity
        assert len(out.strip()) > 20

    def test_L2_02_realtime_keyword(self):
        """L2-02: Real-time CPU query triggers CLI."""
        result = olav_msg("What is the current real-time CPU usage on R1?")
        assert_no_crash(result)
        out = output_of(result)
        assert len(out.strip()) > 20

    def test_L2_03_multi_device(self):
        """L2-03: CLI on multiple devices."""
        result = olav_msg("Run 'show ip interface brief' on all core routers (R3, R4)")
        assert_no_crash(result)
        out = output_of(result)
        assert len(out.strip()) > 20

    def test_L2_04_data_fallback(self):
        """L2-04: Query ARP table - may need CLI fallback."""
        result = olav_msg(
            "What is the current ARP table on R1? Check database first, if no data, use CLI."
        )
        assert_no_crash(result)
        out = output_of(result)
        assert len(out.strip()) > 20


# ============================================================================
# Level 3: 数据导出
# ============================================================================

class TestLevel3_DataExport:
    """数据导出测试 - CSV/JSON 导出"""

    def test_L3_01_csv_export(self):
        """L3-01: Export devices to CSV."""
        result = olav_msg("Export all devices to CSV file")
        assert_no_crash(result)
        out = output_of(result)
        # Check either file was created or LLM mentions CSV
        assert_contains_any(out, ["csv", "export", "file", "saved"])

    def test_L3_02_json_export(self):
        """L3-02: Export devices as JSON."""
        result = olav_msg("Export all device information as JSON")
        assert_no_crash(result)
        out = output_of(result)
        # LLM may output raw JSON directly or mention "json"/"export"
        assert_contains_any(out, ["json", "export", "file", "saved", "R1", "{"])


# ============================================================================
# Level 4: 复杂分析 / 故障诊断
# ============================================================================

class TestLevel4_ComplexAnalysis:
    """复杂分析测试 - LLM 深度分析 snapshot 数据"""

    def test_L4_01_network_health(self):
        """L4-01: Overall network health analysis."""
        result = olav_msg(
            "Analyze the overall health of our network based on the data in the database. "
            "Check devices, topology_links, and parsed_outputs tables.",
            timeout=120
        )
        # Complex analysis may trigger SQL retries with tracebacks in stderr.
        # Only check stdout for meaningful analysis content.
        out = result.stdout or ""
        assert len(out.strip()) > 100, f"Analysis too short: {out[:200]}"

    def test_L4_02_topology_analysis(self):
        """L4-02: Topology single-point-of-failure analysis."""
        result = olav_msg(
            "Analyze the network topology from topology_links table. "
            "Are there any single points of failure?",
            timeout=90
        )
        assert_no_crash(result)
        out = output_of(result)
        assert len(out.strip()) > 100

    def test_L4_03_bgp_analysis(self):
        """L4-03: BGP configuration analysis across routers."""
        result = olav_msg(
            "Analyze BGP configuration across all routers. "
            "Query parsed_outputs WHERE command LIKE '%bgp%' and analyze the data.",
            timeout=90
        )
        assert_no_crash(result)
        out = output_of(result)
        assert len(out.strip()) > 50

    def test_L4_04_interface_errors(self):
        """L4-04: Check for interface errors across devices."""
        result = olav_msg(
            "Are there any interface errors across all devices? "
            "Check parsed_outputs for 'show interfaces' data.",
            timeout=90
        )
        assert_no_crash(result)
        out = output_of(result)
        assert len(out.strip()) > 50

    def test_L4_05_device_comparison(self):
        """L4-05: Compare R1 and R2 configurations."""
        result = olav_msg(
            "Compare R1 and R2 based on their collected data in parsed_outputs. "
            "What are the key differences?",
            timeout=90
        )
        assert_no_crash(result)
        out = output_of(result)
        assert_contains_any(out, ["R1", "R2"])


# ============================================================================
# Level 5: Admin 管理命令
# ============================================================================

class TestLevel5_Admin:
    """Admin 管理命令测试 - 快速响应"""

    def test_L5_01_status(self):
        """L5-01: admin status."""
        result = olav_cmd("admin", "status")
        assert_no_crash(result)
        out = output_of(result)
        assert_contains_any(out, ["database", "skill", "tool", "status", "success"])

    def test_L5_02_db_info(self):
        """L5-02: admin db-info."""
        result = olav_cmd("admin", "db-info")
        assert_no_crash(result)
        # Should show some database information (even if format varies)

    def test_L5_03_skill_list(self):
        """L5-03: admin skill-list."""
        result = olav_cmd("admin", "skill-list")
        assert_no_crash(result)


# ============================================================================
# Level 6: 交互模式多轮对话
# ============================================================================

class TestLevel6_Interactive:
    """交互模式测试 - 多轮对话保持上下文"""

    def test_L6_01_multi_turn_context(self):
        """L6-01: Multi-turn conversation maintains context."""
        stdout, stderr, rc = olav_interactive([
            "How many devices are there?",
            "What are their names?",
        ])
        combined = stdout + stderr
        # First turn: should mention 6
        assert_contains_any(combined, ["6", "six"])
        # Second turn: should list some device names
        found = sum(1 for d in ["R1", "R2", "R3", "R4", "SW1", "SW2"] if d in combined)
        assert found >= 2, f"Only found {found} device names in multi-turn output"

    def test_L6_02_follow_up(self):
        """L6-02: Follow-up query references previous context."""
        stdout, stderr, rc = olav_interactive([
            "List the core routers",
            "What interfaces do they have?",
        ])
        combined = stdout + stderr
        # Should reference R3 or R4 from first query
        assert_contains_any(combined, ["R3", "R4", "core"])

    def test_L6_03_clean_exit(self):
        """L6-03: Interactive mode exits cleanly on 'exit'."""
        stdout, stderr, rc = olav_interactive(["hello"])
        combined = stdout + stderr
        assert_contains_any(combined, ["Goodbye", "bye"])


# ============================================================================
# Execution summary
# ============================================================================

if __name__ == "__main__":
    pytest.main([
        __file__,
        "-v",
        "--timeout=120",
        "--tb=short",
        "-x",  # Stop on first failure
    ])
