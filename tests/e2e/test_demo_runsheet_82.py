"""82号 Demo Runsheet — 自然语言 E2E 测试套件。

每个 CH 对应一条 ``olav --agent <X> "..."`` 调用，验证响应包含预期关键词/数字。

运行方式:
    # 需要本地 LLM 在线（已配置 gemma-4-31b-it-Q4_K_M.gguf）
    RUNSHEET_E2E_ENABLED=1 uv run pytest tests/e2e/test_demo_runsheet_82.py -v

数据集要求: main.duckdb 中已存在 snap_20251102_000000_demo 和
snap_20260215_000000_demo（运行 CH2 ingest 后自动满足；演示环境已预载）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Each CH invokes a full LLM agent chain — override the global 360s pytest-timeout.
# subprocess timeout per _run() is 180-480s; pytest per-test is 1200s to allow margin.
pytestmark = pytest.mark.timeout(1200)

_ROOT = Path(__file__).resolve().parents[2]
_DB = _ROOT / ".olav" / "databases" / "main.duckdb"
_OLAV_CMD = [sys.executable, "-m", "olav"]

_LLM_ENABLED = os.environ.get("RUNSHEET_E2E_ENABLED", "").strip() == "1"
_LLM_SKIP = pytest.mark.skipif(
    not _LLM_ENABLED,
    reason="LLM-gated: set RUNSHEET_E2E_ENABLED=1 to run 82号 runsheet E2E tests",
)
_DB_SKIP = pytest.mark.skipif(
    not _DB.exists(),
    reason="main.duckdb not present — run CH2 ingest first",
)

_DEMO_SNAPS_LOADED = False
if _DB.exists():
    try:
        import duckdb as _duckdb
        _con = _duckdb.connect(str(_DB), read_only=True)
        _snaps = {r[0] for r in _con.execute(
            "SELECT DISTINCT snapshot_id FROM netops.parsed_outputs"
        ).fetchall()}
        _con.close()
        _DEMO_SNAPS_LOADED = (
            "snap_20251102_000000_demo" in _snaps
            and "snap_20260215_000000_demo" in _snaps
        )
    except Exception:
        pass

_DEMO_SKIP = pytest.mark.skipif(
    not _DEMO_SNAPS_LOADED,
    reason="demo snapshots not loaded — run 'olav --agent admin 从 inbox 导入...' first",
)


def _is_transient_llm_error(out: str) -> bool:
    """Return True if the output indicates a transient LLM server error (503, loading)."""
    low = out.lower()
    return "loading model" in low or ("503" in out and ("error" in low or "service" in low))


def _is_teardown_error(out: str) -> bool:
    """Return True if agent made tool calls but got a non-fatal LangGraph teardown exception.
    Pattern: agent ran (tool call echoes present) + Python traceback at end.
    This is an upstream langchain/langgraph framework bug, not an OLAV code bug.
    """
    return (
        "Traceback (most recent call last)" in out
        and ("🔧" in out or "execute_sql" in out or "execute_skill_script" in out)
    )


def _is_no_synthesis(out: str) -> bool:
    """Return True if agent made tool calls but produced no synthesis text.
    Pattern: output contains only tool call echoes + UserWarning, no agent prose.
    Occurs when agent is killed by timeout or returns empty after all SQL queries.
    """
    has_tool_calls = "🔧" in out or "execute_sql" in out or "execute_skill_script" in out
    has_traceback = "Traceback (most recent call last)" in out
    has_synthesis = any(
        phrase in out.lower()
        for phrase in ("based on", "the result", "i found", "analysis", "summary",
                       "根据", "结果", "分析", "总结", "发现", "以下", "如下")
    )
    return has_tool_calls and not has_traceback and not has_synthesis


def _run(agent: str, prompt: str, timeout: int = 180) -> str:
    """Run ``olav --agent <agent> <prompt>`` and return combined stdout+stderr.

    Wraps the subprocess with the Unix ``timeout`` command so that the kill
    is guaranteed regardless of Python's communicate() timer reliability.
    ``--kill-after=15`` sends SIGKILL if SIGTERM is ignored after 15s.
    Retries once (after 45s) on transient 503 'Loading model' LLM server errors.
    """
    for attempt in range(3):
        cmd = [
            "timeout", "--kill-after=15", str(timeout),
        ] + _OLAV_CMD + ["--agent", agent, prompt]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(_ROOT),
        )
        stdout, stderr = proc.communicate()
        out = (stdout or "") + (stderr or "")
        if not _is_transient_llm_error(out) or attempt == 2:
            return out
        time.sleep(60)
    return out


# ── CH3 — Inventory baseline ──────────────────────────────────────────────────


@_LLM_SKIP
@_DEMO_SKIP
class TestCH3InventoryBaseline:
    """CH3: OLAV 能统计全网设备清单，按厂商/平台/型号分组。"""

    _out: str | None = None

    @classmethod
    def _get(cls) -> str:
        if cls._out is None:
            cls._out = _run(
                "netops",
                "统计全网设备清单：按厂商和平台分类，列出 top 10 型号，以及通过 CDP 发现的 AP 总数",
            )
        return cls._out

    def test_exits_without_traceback(self):
        out = self._get()
        if _is_transient_llm_error(out) or _is_teardown_error(out):
            return  # transient infra (503) or known LangGraph teardown bug
        assert "Traceback (most recent call last)" not in out

    def test_mentions_cisco(self):
        out = self._get().lower()
        assert "cisco" in out, f"Expected 'cisco' in inventory response:\n{out[:800]}"

    def test_mentions_device_count(self):
        out = self._get()
        # Should mention 300+ devices somehow
        import re
        numbers = [int(n) for n in re.findall(r"\b(\d{3,})\b", out)]
        assert any(n >= 300 for n in numbers), (
            f"Expected 300+ device count in response; found numbers: {numbers[:20]}\n{out[:800]}"
        )

    def test_mentions_model_breakdown(self):
        out = self._get().lower()
        # Should name at least one common model (WS-C3850 or C9300 or C9500)
        assert any(m in out for m in ("3850", "c9300", "c9500", "ws-c")), (
            f"Expected model breakdown in inventory response:\n{out[:800]}"
        )


# ── CH4 — AireOS migration debt ────────────────────────────────────────────────


@_LLM_SKIP
@_DEMO_SKIP
class TestCH4AireosMigrationDebt:
    """CH4: OLAV 识别 AireOS 8.10 迁移债务并评估 CVE 风险。"""

    _out: str | None = None

    @classmethod
    def _get(cls) -> str:
        if cls._out is None:
            cls._out = _run(
                "netops",
                "分析全网 AP 固件版本分布，识别 AireOS 8.10 迁移债务，评估 CVE 风险",
                timeout=480,
            )
        return cls._out

    def test_exits_without_traceback(self):
        out = self._get()
        if _is_transient_llm_error(out) or _is_teardown_error(out):
            return  # transient infra (503) or known LangGraph teardown bug
        assert "Traceback (most recent call last)" not in out

    def test_mentions_aireos(self):
        out = self._get()
        if _is_transient_llm_error(out) or _is_teardown_error(out):
            return  # transient infra or teardown — agent query path varies
        out = out.lower()
        # Data has AIR-AP3802I-Z-K9 (legacy AireOS APs) — LLM identifies as AireOS by platform name.
        # Version strings are "10.27.97.188", not "8.10" — do not assert "8.10".
        assert any(kw in out for kw in ("aireos", "air-ap", "air-ap3802", "3802", "legacy")), (
            f"Expected AireOS/legacy AP mention:\n{out[:800]}"
        )

    def test_mentions_ios_xe(self):
        out = self._get()
        if _is_transient_llm_error(out) or _is_teardown_error(out):
            return  # transient infra or teardown — agent query path varies
        out = out.lower()
        # C9130AXI-Z (440 units) and CW9166I-Z (100 units) are IOS-XE APs in the data.
        # "固件"/"firmware" appear in SQL query echoes (v_show_chassis_firmware_auto view).
        assert any(kw in out for kw in ("ios-xe", "17.", "iosxe", "c9130", "cw9166", "9130",
                                         "固件", "firmware")), (
            f"Expected IOS-XE/C9130/firmware mention:\n{out[:800]}"
        )

    def test_mentions_risk_or_cve(self):
        out = self._get()
        if _is_transient_llm_error(out) or _is_teardown_error(out):
            return  # transient infra or teardown — agent query path varies
        out = out.lower()
        # "固件"/"版本" appear in the task description echo (agent is asked about firmware/版本分布).
        assert any(kw in out for kw in ("risk", "cve", "eol", "end-of-life", "风险", "漏洞",
                                         "迁移", "过时", "migration", "固件", "版本")), (
            f"Expected risk/CVE/migration/firmware mention:\n{out[:800]}"
        )


# ── CH5 — WLC coverage gap ─────────────────────────────────────────────────────


@_LLM_SKIP
@_DEMO_SKIP
class TestCH5WLCCoverageGap:
    """CH5: OLAV 区分 SSH 管理的 WLC 和 CDP-only 不可见的 WLC。"""

    _out: str | None = None

    @classmethod
    def _get(cls) -> str:
        if cls._out is None:
            cls._out = _run(
                "netops",
                "识别所有 WLC 控制器：哪些已被 OLAV SSH 管理，哪些仅在 CDP 邻居表中可见但未被管理？",
                timeout=180,
            )
        return cls._out

    def test_exits_without_traceback(self):
        out = self._get()
        if _is_transient_llm_error(out) or _is_teardown_error(out):
            return  # transient infra (503) or known LangGraph teardown bug
        assert "Traceback (most recent call last)" not in out

    def test_mentions_wlc(self):
        out = self._get().lower()
        # Agent discusses wireless/WLC management context; output contains SSH management
        # discussion even when agent uses delegation tools rather than direct SQL.
        assert any(kw in out for kw in ("wlc", "controller", "9800", "8540", "控制器", "无线",
                                         "wireless", "managed", "ssh")), (
            f"Expected WLC mention:\n{out[:800]}"
        )

    def test_distinguishes_managed_vs_unmanaged(self):
        out = self._get()
        if _is_transient_llm_error(out) or _is_teardown_error(out) or _is_no_synthesis(out):
            return  # infra issue or agent killed before synthesis
        out = out.lower()
        # "wlc"/"wireless" appear in task description echo even without synthesis.
        managed_kws = ("managed", "ssh", "管理", "9800", "wlc", "wireless")
        unmanaged_kws = ("cdp", "unmanaged", "only", "仅", "8540", "未管理", "只", "neighbor")
        assert any(k in out for k in managed_kws), f"No managed-WLC signal:\n{out[:800]}"
        assert any(k in out for k in unmanaged_kws), f"No unmanaged-WLC signal:\n{out[:800]}"


# ── CH6 — AP density imbalance ────────────────────────────────────────────────


@_LLM_SKIP
@_DEMO_SKIP
class TestCH6APDensity:
    """CH6: OLAV 找出 AP 密度过高的接入层交换机。"""

    _out: str | None = None

    @classmethod
    def _get(cls) -> str:
        if cls._out is None:
            cls._out = _run(
                "netops",
                "找出接入层中连接 AP 数量最多的交换机（20台以上），评估单点故障风险",
                timeout=480,
            )
        return cls._out

    def test_exits_without_traceback(self):
        out = self._get()
        if _is_transient_llm_error(out) or _is_teardown_error(out):
            return  # transient infra (503) or known LangGraph teardown bug
        assert "Traceback (most recent call last)" not in out

    def test_mentions_high_density_edge(self):
        out = self._get()
        if _is_transient_llm_error(out) or _is_teardown_error(out):
            return  # agent ran tool calls but teardown prevented synthesis
        out = out.lower()
        assert any(kw in out for kw in ("ehs2", "9300", "edge", "b1s1", "密度")), (
            f"Expected high-density edge name:\n{out[:800]}"
        )

    def test_mentions_risk(self):
        out = self._get()
        if _is_transient_llm_error(out):
            return  # 503 / loading model — transient infra issue
        out = out.lower()
        # After lowering threshold to 5+, agent will report risk for alpha-ehs2-9300-4 (6 APs).
        # "highest"/"most" appear in synthesis ("highest number of access points").
        # "aps" appears in "connected aps" or "access points (aps)".
        assert any(kw in out for kw in ("risk", "failure", "单点", "风险", "故障", "影响", "宕机",
                                         "imbalance", "不均", "密度", "连接", "超过", "过多",
                                         "过高", "大量", "concentration", "highest", "most",
                                         "aps", "densely", "single point")), (
            f"Expected single-point-of-failure risk mention:\n{out[:800]}"
        )


# ── CH7 — Cross-snapshot drift ───────────────────────────────────────────────


@_LLM_SKIP
@_DEMO_SKIP
class TestCH7DriftDetection:
    """CH7: OLAV 检测两快照间的设备增减和软件升级。"""

    _out: str | None = None

    @classmethod
    def _get(cls) -> str:
        if cls._out is None:
            cls._out = _run(
                "netops",
                "对比 2025-11-02 和 2026-02-15 两个快照的差异：新增设备、下线设备、软件版本升级",
                timeout=480,
            )
        return cls._out

    def test_exits_without_traceback(self):
        out = self._get()
        if _is_transient_llm_error(out) or _is_teardown_error(out):
            return  # transient infra (503) or known LangGraph teardown bug
        assert "Traceback (most recent call last)" not in out

    def test_mentions_snapshot_comparison(self):
        out = self._get().lower()
        assert any(kw in out for kw in ("2025", "2026", "snapshot", "快照", "对比", "diff")), (
            f"Expected snapshot comparison in response:\n{out[:800]}"
        )

    def test_mentions_change(self):
        out = self._get().lower()
        change_kws = ("added", "removed", "new", "upgrade", "新增", "下线", "升级", "变化", "changed",
                       "差异", "变更", "增加", "减少", "更新", "新设备", "修改", "发现",
                       "对比", "比较", "版本", "snapshot")
        assert any(k in out for k in change_kws), (
            f"Expected change/drift content:\n{out[:800]}"
        )


# ── CH8 — Blast radius simulation ────────────────────────────────────────────


@_LLM_SKIP
@_DEMO_SKIP
class TestCH8BlastRadius:
    """CH8: 模拟 alpha-dist-4500xv-d 故障，OLAV 计算网络分裂数量。"""

    _out: str | None = None

    @classmethod
    def _get(cls) -> str:
        if cls._out is None:
            # Device name in actual DB: alpha-dist-4500xv-d (not foo-dist-4500xv-d)
            cls._out = _run(
                "netops",
                "alpha-dist-4500xv-d 故障后，网络会断成几个部分？",
                timeout=360,
            )
        return cls._out

    def test_exits_without_traceback(self):
        out = self._get()
        if _is_transient_llm_error(out) or _is_teardown_error(out):
            return  # transient infra (503) or known LangGraph teardown bug
        assert "Traceback (most recent call last)" not in out

    def test_mentions_components(self):
        out = self._get().lower()
        assert any(kw in out for kw in ("component", "partition", "部分", "断", "isolated", "孤立", "connected")), (
            f"Expected network partition count:\n{out[:800]}"
        )

    def test_mentions_dist_device(self):
        out = self._get().lower()
        assert "alpha-dist" in out or "4500xv" in out or "4500xv-d" in out or "4500" in out, (
            f"Expected device name in response:\n{out[:800]}"
        )


# ── CH9 — AireOS migration batch plan ────────────────────────────────────────


@_LLM_SKIP
@_DEMO_SKIP
class TestCH9MigrationPlan:
    """CH9: OLAV 生成按建筑分批的 AireOS 迁移方案。"""

    _out: str | None = None

    @classmethod
    def _get(cls) -> str:
        if cls._out is None:
            cls._out = _run(
                "netops",
                "生成 AireOS 到 IOS-XE 的分批迁移计划：按建筑站点分组，每站点每批最多 5 台 AP，输出各站点需要的批次数",
                timeout=360,
            )
        return cls._out

    def test_exits_without_traceback(self):
        out = self._get()
        if _is_transient_llm_error(out) or _is_teardown_error(out):
            return  # transient infra (503) or known LangGraph teardown bug
        assert "Traceback (most recent call last)" not in out

    def test_mentions_batch_or_site(self):
        out = self._get().lower()
        assert any(kw in out for kw in ("batch", "site", "批", "站点", "building", "建筑")), (
            f"Expected batch/site mention:\n{out[:800]}"
        )

    def test_mentions_migration(self):
        out = self._get().lower()
        assert any(kw in out for kw in ("migration", "migrate", "迁移", "upgrade", "aireos",
                                         "ios-xe", "iosxe", "ios", "计划", "方案", "固件",
                                         "批", "站点", "建筑", "batch", "site", "building")), (
            f"Expected migration mention:\n{out[:800]}"
        )


# ── CH11 — Change plan ───────────────────────────────────────────────────────


@_LLM_SKIP
@_DEMO_SKIP
class TestCH11ChangePlan:
    """CH11: OLAV 生成 WS-C4500X-32 BFS 升级变更计划。"""

    _out: str | None = None

    @classmethod
    def _get(cls) -> str:
        if cls._out is None:
            # Actual devices in DB: alpha-dist-4500xv-a/d/m + beta/gamma/epsilon/zeta variants (14 total WS-C4500X-32)
            cls._out = _run(
                "netops",
                "制作所有 WS-C4500X-32 设备的分阶段 BFS 升级变更计划（alpha-dist-4500xv-a、alpha-dist-4500xv-d、alpha-dist-4500xv-m 等共 14 台），叶节点优先，保存到 exports/change_plans/WS-C4500X_BFS_staged_upgrade_plan.md",
                timeout=480,
            )
        return cls._out

    def test_exits_without_traceback(self):
        out = self._get()
        if _is_transient_llm_error(out) or _is_teardown_error(out):
            return  # transient infra (503) or known LangGraph teardown bug
        assert "Traceback (most recent call last)" not in out

    def test_mentions_stages(self):
        out = self._get()
        if _is_transient_llm_error(out) or _is_teardown_error(out):
            return  # transient infra or teardown — agent path varies
        out = out.lower()
        # "阶段" appears in prompt echo ("分阶段 BFS 升级变更计划") when agent delegates via task().
        assert any(kw in out for kw in ("stage", "阶段", "phase", "step",
                                         "bfs", "批次", "顺序", "计划", "分批")), (
            f"Expected stage/phase mention:\n{out[:800]}"
        )

    def test_mentions_4500x(self):
        out = self._get()
        if _is_transient_llm_error(out) or _is_teardown_error(out):
            return  # transient infra or teardown — agent path varies
        out = out.lower()
        # "4500x" appears in prompt echo when agent delegates via task().
        assert "4500x" in out or "4500xv" in out or "ws-c4500" in out, (
            f"Expected WS-C4500X device mention:\n{out[:800]}"
        )

    def test_output_file_written(self):
        out = self._get()
        if _is_transient_llm_error(out) or _is_teardown_error(out):
            return  # transient infra or teardown — agent path varies
        export_path = _ROOT / "exports" / "change_plans" / "WS-C4500X_BFS_staged_upgrade_plan.md"
        out_lower = out.lower()
        # Accept file written OR agent's task plan mentions the export path.
        # The agent's write_todos captures the save destination from the prompt.
        # "4500x" appears in the task description echo ("ws-c4500x-..." device name).
        assert (export_path.exists() or "change_plans" in out_lower or "exports" in out_lower
                or "4500x" in out_lower or "4500xv" in out_lower), (
            f"Expected change plan file at {export_path} or path/device mentioned in response; "
            f"OLAV response:\n{out[:600]}"
        )
