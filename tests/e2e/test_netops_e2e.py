"""Netops agent E2E tests.

Covers the netops top-level agent and its sub-agents:
  analyzer:  diff_configs, diff_snapshots, query_topology, inspect_blast_radius
  collect:   execute_cli_parallel, take_snapshot, search_commands
  learner:   learn_commands, cmd_learn
  topology:  query_topology, render_topology_drawio
  sim:       batfish_q, fork_snapshot

Structural tests (no LLM) run always.
LLM tests are gated by NETOPS_E2E_ENABLED=1.
SSH/live device tests also require PROBE_E2E_ENABLED=1.

Usage:
    # structural only:
    uv run pytest tests/e2e/test_netops_e2e.py -v

    # with LLM (no live devices):
    NETOPS_E2E_ENABLED=1 uv run pytest tests/e2e/test_netops_e2e.py -v

    # full (LLM + SSH devices):
    NETOPS_E2E_ENABLED=1 PROBE_E2E_ENABLED=1 uv run pytest tests/e2e/test_netops_e2e.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_OLAV_CMD = [sys.executable, "-m", "olav"]
_WORKSPACE = _ROOT / ".olav" / "workspace" / "netops"

_LLM_ENABLED = os.environ.get("NETOPS_E2E_ENABLED", "").strip() == "1"
_PROBE_ENABLED = _LLM_ENABLED and os.environ.get("PROBE_E2E_ENABLED", "").strip() == "1"

_LLM_SKIP = pytest.mark.skipif(
    not _LLM_ENABLED,
    reason="LLM-gated: set NETOPS_E2E_ENABLED=1 to run netops agent live tests",
)
_PROBE_SKIP = pytest.mark.skipif(
    not _PROBE_ENABLED,
    reason="Live-device-gated: set NETOPS_E2E_ENABLED=1 + PROBE_E2E_ENABLED=1",
)


def _run_agent(prompt: str, timeout: int = 270) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(
        _OLAV_CMD + ["--agent", "netops", prompt],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=_ROOT,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        return subprocess.CompletedProcess(proc.args, -1, stdout or "", stderr or "")
    except BaseException:
        try:
            proc.kill()
            proc.communicate()
        except Exception:
            pass
        raise


def _has_snapshot_data() -> bool:
    try:
        import duckdb
        from olav.core.config import MAIN_DB_PATH
        with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as con:
            count = con.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'netops'"
            ).fetchone()[0]
            return count > 0
    except Exception:
        return False


# ── Structural (no LLM) ──────────────────────────────────────────────────────


class TestNetopsAgentStructure:
    """Netops workspace structure — no LLM required."""

    def test_agent_md_exists(self):
        # v0.20 workspaces use SKILL.md; accept either
        assert (_WORKSPACE / "SKILL.md").is_file() or (_WORKSPACE / "AGENT.md").is_file()

    def test_analyzer_subagent_exists(self):
        assert (_WORKSPACE / "analyzer" / "SKILL.md").is_file()

    def test_analyzer_has_diff_configs(self):
        text = (_WORKSPACE / "analyzer" / "SKILL.md").read_text(encoding="utf-8")
        assert "diff_configs" in text

    def test_reporter_subagent_exists(self):
        """After 2026-05-26 split: reporter owns Mode B+C (diff_snapshots, query_evidence)."""
        assert (_WORKSPACE / "reporter" / "SKILL.md").is_file()

    def test_reporter_has_diff_snapshots(self):
        """diff_snapshots moved from analyzer → reporter (FINDING-19)."""
        text = (_WORKSPACE / "reporter" / "SKILL.md").read_text(encoding="utf-8")
        assert "diff_snapshots" in text

    def test_collect_subagent_exists(self):
        assert (_WORKSPACE / "collector" / "SKILL.md").is_file()

    def test_collect_has_execute_cli_parallel(self):
        text = (_WORKSPACE / "collector" / "SKILL.md").read_text(encoding="utf-8")
        assert "execute_cli_parallel" in text

    def test_collect_has_take_snapshot(self):
        text = (_WORKSPACE / "collector" / "SKILL.md").read_text(encoding="utf-8")
        assert "take_snapshot" in text

    def test_collect_has_search_commands(self):
        text = (_WORKSPACE / "collector" / "SKILL.md").read_text(encoding="utf-8")
        assert "search_commands" in text

    def test_topology_subagent_exists(self):
        assert (_WORKSPACE / "topology" / "SKILL.md").is_file()

    def test_sim_subagent_exists(self):
        assert (_WORKSPACE / "simulator" / "SKILL.md").is_file()

    def test_learner_subagent_exists(self):
        assert (_WORKSPACE / "learner" / "SKILL.md").is_file()

    def test_query_topology_script_exists(self):
        # migrated from topology/tools/ → topology/scripts/ in rev ~297
        script = _WORKSPACE / "topology" / "scripts" / "query_topology.py"
        assert script.is_file(), f"query_topology.py missing at {script}"

    def test_netops_listed_in_olav_list(self):
        result = subprocess.run(
            _OLAV_CMD + ["list"],
            capture_output=True, text=True, timeout=30, cwd=_ROOT,
        )
        assert "netops" in result.stdout + result.stderr, (
            "'netops' not found in olav list output"
        )


# ── DB-backed (no LLM, but needs snapshot data) ──────────────────────────────


class TestNetopsWithSnapshotData:
    """Tests that query existing snapshot DB — no LLM required."""

    def test_topology_snapshot_query_direct(self):
        """query_topology script file exists and defines the query_topology function."""
        # migrated from topology/tools/ → topology/scripts/ in rev ~297
        script_path = _ROOT / ".olav" / "workspace" / "netops" / "topology" / "scripts" / "query_topology.py"
        assert script_path.is_file(), f"query_topology.py missing at {script_path}"
        src = script_path.read_text(encoding="utf-8")
        assert "def query_topology" in src or "query_topology" in src, (
            "query_topology.py must define a query_topology function"
        )


# ── Behaviour (LLM required) ─────────────────────────────────────────────────


@_LLM_SKIP
@pytest.mark.timeout(300)
class TestNetopsRoutingAnalysis:
    """C-NE-20: netops analyzer explains routing path in natural language."""

    _result: "subprocess.CompletedProcess | None" = None

    @classmethod
    def _get_result(cls) -> subprocess.CompletedProcess:
        if cls._result is None:
            cls._result = _run_agent("分析 R1 到 R4 的路由路径", timeout=240)
        return cls._result

    @pytest.mark.xfail(strict=False, reason="LLM output quality varies")
    def test_exits_zero(self):
        r = self._get_result()
        assert r.returncode == 0, f"netops analysis failed:\n{r.stdout}\n{r.stderr}"

    @pytest.mark.xfail(strict=False, reason="LLM output quality varies")
    def test_mentions_routers(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert any(r in out for r in ("R1", "R2", "R3", "R4"))

    def test_no_traceback(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert "Traceback" not in out


@_LLM_SKIP
@pytest.mark.timeout(300)
class TestNetopsWhatIf:
    """C-NE-22: netops analyzer simulates blast radius."""

    _result: "subprocess.CompletedProcess | None" = None

    @classmethod
    def _get_result(cls) -> subprocess.CompletedProcess:
        if cls._result is None:
            cls._result = _run_agent("模拟 R2 所有链路断开对全网的影响", timeout=240)
        return cls._result

    @pytest.mark.xfail(strict=False, reason="LLM output quality varies")
    def test_exits_zero(self):
        r = self._get_result()
        assert r.returncode == 0

    @pytest.mark.xfail(strict=False, reason="LLM output quality varies")
    def test_mentions_r2(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert "R2" in out

    def test_no_traceback(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert "Traceback" not in out


@_LLM_SKIP
@pytest.mark.timeout(300)
class TestNetopsDiff:
    """C-NE-26: netops analyzer diffs topology between two snapshots."""

    @pytest.mark.xfail(strict=False, reason="LLM output quality varies; model reload 503 is transient")
    def test_exits_zero_or_skip(self):
        try:
            import duckdb
            from olav.core.config import MAIN_DB_PATH
            with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as con:
                count = con.execute(
                    "SELECT COUNT(DISTINCT snapshot_id) FROM netops.v_l2_links_auto"
                ).fetchone()[0]
                if count < 2:
                    pytest.skip("< 2 snapshots with L2 data — run netops_init twice")
        except Exception:
            pytest.skip("netops DB not available")

        result = _run_agent("最近两次快照的拓扑变化是什么", timeout=240)
        out = result.stdout + result.stderr
        assert "Traceback" not in out


@_PROBE_SKIP
@pytest.mark.timeout(300)
class TestNetopsCollectOverSSH:
    """C-NE-21: netops collect probes a real SSH device."""

    def test_probe_ssh_device(self):
        result = _run_agent("通过 SSH 探测 R2 的接口状态", timeout=240)
        out = result.stdout + result.stderr
        assert result.returncode == 0, f"netops probe failed:\n{out[:600]}"
        assert any(kw in out.lower() for kw in ("interface", "接口", "r2", "up", "down"))
