"""Ops NL (natural-language) E2E tests.

Covers:
  C-NE-20 — ops analysis: "分析 R1→R4 的路由路径"
  C-NE-22 — ops What-If: "模拟 R2 所有链路断开"
  C-NE-26 — ops diff: "最近两次快照拓扑变化"
  C-NE-32 — audit-designer: "创建 BGP 健康检查 profile"
  C-NE-39 — infra write full flow (requires NetBox — marked skip)
  C-NE-21 — probe NL (requires LLM + SSH device — marked skip)

Gate: tests only run when OPS_NL_E2E_ENABLED=1 is set (or OLAV_API_KEY is present).
Without the env var every test is skipped automatically.

Usage:
    OPS_NL_E2E_ENABLED=1 uv run pytest tests/e2e/test_ops_nl_e2e.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_OLAV_CMD = [sys.executable, "-m", "olav"]

_LLM_ENABLED = os.environ.get("OPS_NL_E2E_ENABLED", "").strip() == "1" or bool(
    os.environ.get("OLAV_API_KEY") or os.environ.get("OPENAI_API_KEY")
)

_LLM_SKIP = pytest.mark.skipif(
    not _LLM_ENABLED,
    reason="LLM-gated: set OPS_NL_E2E_ENABLED=1 or provide an API key to run",
)

_PROBE_ENABLED = _LLM_ENABLED and os.environ.get("PROBE_E2E_ENABLED", "").strip() == "1"
_PROBE_SKIP = pytest.mark.skipif(
    not _PROBE_ENABLED,
    reason="Probe E2E: set PROBE_E2E_ENABLED=1 and ensure LLM API key is present",
)

_NETBOX_ENABLED = _LLM_ENABLED and os.environ.get("NETBOX_E2E_ENABLED", "").strip() == "1"
_NETBOX_SKIP = pytest.mark.skipif(
    not _NETBOX_ENABLED,
    reason="NetBox E2E: set NETBOX_E2E_ENABLED=1 and ensure LLM API key is present",
)


def _run_agent(agent: str, prompt: str, timeout: int = 180) -> subprocess.CompletedProcess:
    """Run `olav --agent <agent> <prompt>` and return the CompletedProcess."""
    return subprocess.run(
        _OLAV_CMD + ["--agent", agent, prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=_ROOT,
    )


# ---------------------------------------------------------------------------
# C-NE-20 — ops analysis NL
# ---------------------------------------------------------------------------
@_LLM_SKIP
@pytest.mark.timeout(300)
class TestOpsAnalysisNLE2E:
    """C-NE-20: ops agent can explain routing path from R1 to R4 in natural language."""

    _result: "subprocess.CompletedProcess | None" = None

    @classmethod
    def _get_result(cls) -> subprocess.CompletedProcess:
        if cls._result is None:
            cls._result = _run_agent("ops", "分析 R1 到 R4 的路由路径")
        return cls._result

    def test_exits_zero(self):
        result = self._get_result()
        assert result.returncode == 0, (
            f"ops analysis exited {result.returncode}:\n"
            f"{result.stdout}\n{result.stderr}"
        )

    def test_response_mentions_routers(self):
        combined = self._get_result().stdout + self._get_result().stderr
        assert any(r in combined for r in ("R1", "R2", "R3", "R4")), (
            f"Response does not mention any routers:\n{combined[:800]}"
        )

    def test_no_traceback(self):
        combined = self._get_result().stdout + self._get_result().stderr
        assert "Traceback" not in combined, (
            f"Unhandled exception in ops analysis:\n{combined[:800]}"
        )


# ---------------------------------------------------------------------------
# C-NE-22 — ops What-If NL
# ---------------------------------------------------------------------------
@_LLM_SKIP
@pytest.mark.timeout(300)
class TestOpsWhatIfNLE2E:
    """C-NE-22: ops agent can simulate 'what-if R2 loses all links'."""

    _result: "subprocess.CompletedProcess | None" = None

    @classmethod
    def _get_result(cls) -> subprocess.CompletedProcess:
        if cls._result is None:
            cls._result = _run_agent("ops", "模拟 R2 所有链路断开对全网的影响")
        return cls._result

    def test_exits_zero(self):
        result = self._get_result()
        assert result.returncode == 0, (
            f"ops what-if exited {result.returncode}:\n"
            f"{result.stdout}\n{result.stderr}"
        )

    def test_response_mentions_r2(self):
        combined = self._get_result().stdout + self._get_result().stderr
        assert "R2" in combined, (
            f"Response does not mention R2:\n{combined[:800]}"
        )

    def test_no_traceback(self):
        combined = self._get_result().stdout + self._get_result().stderr
        assert "Traceback" not in combined, (
            f"Unhandled exception in ops what-if:\n{combined[:800]}"
        )


# ---------------------------------------------------------------------------
# C-NE-26 — ops diff NL
# ---------------------------------------------------------------------------
@_LLM_SKIP
class TestOpsDiffNLE2E:
    """C-NE-26: ops agent summarises topology changes between two snapshots."""

    def _has_two_snapshots(self) -> bool:
        try:
            import duckdb
            from olav.core.config import MAIN_DB_PATH

            with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as con:
                tables = {r[0] for r in con.execute(
                    "SELECT table_name FROM information_schema.tables"
                ).fetchall()}
                if "topology_snapshots" not in tables:
                    return False
                count = con.execute(
                    "SELECT COUNT(*) FROM topology_snapshots"
                ).fetchone()[0]
                return count >= 2
        except Exception:
            return False

    def test_exits_zero(self):
        if not self._has_two_snapshots():
            pytest.skip("< 2 topology snapshots in DB — create two snapshots first")
        result = _run_agent("ops", "最近两次快照的拓扑变化是什么")
        assert result.returncode == 0, (
            f"ops diff exited {result.returncode}:\n"
            f"{result.stdout}\n{result.stderr}"
        )

    def test_response_mentions_changes(self):
        if not self._has_two_snapshots():
            pytest.skip("< 2 topology snapshots in DB — create two snapshots first")
        result = _run_agent("ops", "最近两次快照的拓扑变化是什么")
        combined = result.stdout + result.stderr
        has_content = (
            "变化" in combined
            or "change" in combined.lower()
            or "diff" in combined.lower()
            or "snapshot" in combined.lower()
        )
        assert has_content, f"Response does not mention topology changes:\n{combined[:800]}"

    def test_no_traceback(self):
        if not self._has_two_snapshots():
            pytest.skip("< 2 topology snapshots in DB — create two snapshots first")
        result = _run_agent("ops", "最近两次快照的拓扑变化是什么")
        combined = result.stdout + result.stderr
        assert "Traceback" not in combined, (
            f"Unhandled exception in ops diff:\n{combined[:800]}"
        )


# ---------------------------------------------------------------------------
# C-NE-32 — audit-designer NL
# ---------------------------------------------------------------------------
@_LLM_SKIP
@pytest.mark.timeout(300)
class TestAuditDesignerNLE2E:
    """C-NE-32: audit-designer agent creates a BGP health-check profile."""

    _result: "subprocess.CompletedProcess | None" = None

    @classmethod
    def _get_result(cls) -> subprocess.CompletedProcess:
        if cls._result is None:
            cls._result = _run_agent("audit-designer", "创建 BGP 健康检查 profile")
        return cls._result

    def test_exits_zero(self):
        result = self._get_result()
        assert result.returncode == 0, (
            f"audit-designer exited {result.returncode}:\n"
            f"{result.stdout}\n{result.stderr}"
        )

    def test_response_mentions_bgp(self):
        combined = self._get_result().stdout + self._get_result().stderr
        assert "BGP" in combined or "bgp" in combined.lower(), (
            f"Response does not mention BGP:\n{combined[:800]}"
        )

    def test_no_traceback(self):
        combined = self._get_result().stdout + self._get_result().stderr
        assert "Traceback" not in combined, (
            f"Unhandled exception in audit-designer:\n{combined[:800]}"
        )


# ---------------------------------------------------------------------------
# C-NE-39 — infra write full flow (requires NetBox — env-var gated)
# ---------------------------------------------------------------------------
class TestInfraWriteFlowClaim:
    """C-NE-39: full write flow requires a NetBox instance."""

    @_NETBOX_SKIP
    def test_infra_write_full_flow(self):
        """Full infra write flow with real NetBox instance."""
        result = _run_agent(
            "devops",
            "sync OLAV devices to NetBox at localhost:8000",
            timeout=180,
        )
        assert result.returncode == 0, f"devops agent failed:\n{result.stderr}"
        output = result.stdout + result.stderr
        assert any(kw in output.lower() for kw in ["netbox", "device", "sync", "script"]), (
            f"devops output does not mention NetBox sync:\n{output[:500]}"
        )


# ---------------------------------------------------------------------------
# C-NE-21 — probe NL (requires LLM + SSH device — env-var gated)
# ---------------------------------------------------------------------------
class TestProbeNLClaim:
    """C-NE-21: probe agent requires an LLM and a live SSH-accessible device."""

    @_PROBE_SKIP
    @pytest.mark.timeout(300)
    def test_probe_nl_over_ssh(self):
        """Probe NL over SSH to a real device (R2 at 192.168.100.102)."""
        result = _run_agent(
            "ops",
            "通过 SSH 探测 R2 的接口状态",
            timeout=240,
        )
        assert result.returncode == 0, f"ops probe agent failed:\n{result.stderr}"
        output = result.stdout + result.stderr
        assert any(kw in output.lower() for kw in ["interface", "接口", "r2", "status", "up", "down"]), (
            f"probe output does not contain interface info:\n{output[:500]}"
        )
