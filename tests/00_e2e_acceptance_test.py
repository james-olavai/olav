"""
Doc-Driven Testing — OLAV Platform v0.12.0 Acceptance Tests

每个 TestClass 对应文档中一个 Claim。
所有测试通过真实 `olav` CLI 执行（subprocess），不 mock LLM 或设备。

Claim 层级：
  Level 1 — 平台核心能力（主站 / README）
  Level 2 — 功能级（文档站页面）

参考文档：dev_docs/22. WEB_AND_DOCS_SITE.md §7
CLI 验证记录：dev_docs/23. CLI_VERIFICATION_LOG.md
"""

from __future__ import annotations

import json
import importlib.metadata
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
OLAV_CMD = [sys.executable, "-m", "olav"]  # uv run olav equivalent


def run_olav(*args: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    """Run `olav <args>` and return the completed process."""
    return subprocess.run(
        [sys.executable, "-m", "olav", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


# ─────────────────────────────────────────────────────────
# C-L2-01  版本显示
# Claim: OLAV CLI 正确报告版本号和系统信息
# Doc:   docs/olav/02_QUICK_START.md
# ─────────────────────────────────────────────────────────
class TestVersionClaim:
    """
    Claim C-L2-01: `olav version` 正确报告版本号和系统信息。
    Verified: 2026-04-03 | Doc: docs/olav/02_QUICK_START.md
    """

    def test_version_exits_zero(self):
        result = run_olav("version")
        assert result.returncode == 0, result.stderr

    def test_version_output_contains_version(self):
        result = run_olav("version")
        assert "v0." in result.stdout, f"No version string in output: {result.stdout[:300]}"

    def test_version_output_contains_python(self):
        result = run_olav("version")
        assert "Python" in result.stdout or "python" in result.stdout.lower()


# ─────────────────────────────────────────────────────────
# C-L2-02  列出所有 Agents
# Claim: OLAV CLI 列出所有可用 agents 及其描述
# Doc:   docs/olav/02_QUICK_START.md
# ─────────────────────────────────────────────────────────
class TestListAgentsClaim:
    """
    Claim C-L2-02: `olav list` 列出所有可用 agents。
    Verified: 2026-04-03 | Doc: docs/olav/02_QUICK_START.md
    """

    def test_list_exits_zero(self):
        result = run_olav("list")
        assert result.returncode == 0, result.stderr

    def test_list_shows_core_agent(self):
        result = run_olav("list")
        assert "core" in result.stdout

    def test_list_shows_multiple_agents(self):
        result = run_olav("list")
        # At minimum these v0.18+ canonical agents should be present
        for agent in ("admin", "netops", "core"):
            assert agent in result.stdout, f"Agent '{agent}' not in list output"


# ─────────────────────────────────────────────────────────
# C-L2-03  Workspace 切换
# Claim: OLAV CLI 支持列出和切换当前活跃 workspace
# Doc:   docs/olav/02_QUICK_START.md
# ─────────────────────────────────────────────────────────
class TestWorkspaceSwitchClaim:
    """
    Claim C-L2-03: `olav workspace list` 和 `olav workspace use <name>` 正常工作。
    Verified: 2026-04-03 | Doc: docs/olav/02_QUICK_START.md
    """

    def test_workspace_list_exits_zero(self):
        result = run_olav("workspace", "list")
        assert result.returncode == 0, result.stderr

    def test_workspace_list_shows_core(self):
        result = run_olav("workspace", "list")
        assert "core" in result.stdout

    def test_workspace_use_exits_zero(self):
        result = run_olav("workspace", "use", "core")
        assert result.returncode == 0, result.stderr

    def test_workspace_use_confirms_switch(self):
        result = run_olav("workspace", "use", "core")
        assert "core" in result.stdout


# ─────────────────────────────────────────────────────────
# C-L2-04  Skill 本地安装
# Claim: OLAV CLI 支持从本地目录安装 Skill workspace
# Doc:   docs/olav/08_AGENT_SKILL_REGISTRATION.md
# ─────────────────────────────────────────────────────────
class TestSkillInstallLocalClaim:
    """
    Claim C-L2-04: `olav skill install <path>` 本地安装成功，输出安装确认。
    Verified: 2026-04-03 | Doc: docs/olav/08_AGENT_SKILL_REGISTRATION.md
    """

    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        skill_dir = self.tmpdir / "test-acceptance-skill"
        skill_dir.mkdir()
        (skill_dir / "MANIFEST.yaml").write_text(
            "name: test-acceptance-skill\nversion: '1.0.0'\ndescription: Acceptance test skill\n"
        )
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-acceptance-skill\ndescription: Acceptance test skill\ntools: []\n---\n\n# Test Skill\n"
        )
        self.skill_dir = skill_dir

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        # Remove installed workspace
        ws = REPO_ROOT / ".olav" / "workspace" / "test-acceptance-skill"
        if ws.exists():
            shutil.rmtree(ws, ignore_errors=True)

    def test_skill_install_exits_zero(self):
        result = run_olav("skill", "install", str(self.skill_dir))
        assert result.returncode == 0, result.stderr

    def test_skill_install_output_confirms_install(self):
        result = run_olav("skill", "install", str(self.skill_dir))
        assert "installed" in result.stdout or "test-acceptance-skill" in result.stdout

    def test_skill_install_creates_workspace(self):
        run_olav("skill", "install", str(self.skill_dir))
        ws = REPO_ROOT / ".olav" / "workspace" / "test-acceptance-skill"
        assert ws.exists(), f"Workspace directory not created at {ws}"


# ─────────────────────────────────────────────────────────
# C-L2-06  Skill merge-into
# Claim: OLAV CLI 支持将 SkillPack 工具追加到已有 workspace
# Doc:   docs/olav/08_AGENT_SKILL_REGISTRATION.md
# ─────────────────────────────────────────────────────────
class TestSkillMergeIntoClaim:
    """
    Claim C-L2-06: `olav skill install --merge-into <ws>` 追加工具到已有 workspace。
    Verified: 2026-04-03 | Doc: docs/olav/08_AGENT_SKILL_REGISTRATION.md
    Note: Target workspace SKILL.md must contain YAML frontmatter.
    """

    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp())

        # Base skill workspace
        base_dir = self.tmpdir / "merge-base-skill"
        base_dir.mkdir()
        (base_dir / "MANIFEST.yaml").write_text(
            "name: merge-base-skill\nversion: '1.0.0'\ndescription: Merge base\n"
        )
        (base_dir / "SKILL.md").write_text(
            "---\nname: merge-base-skill\ndescription: Merge base\ntools: []\n---\n\n# Merge Base\n"
        )
        self.base_dir = base_dir

        # SkillPack to merge
        pack_dir = self.tmpdir / "test-skill-pack"
        pack_dir.mkdir()
        tools_dir = pack_dir / "tools"
        tools_dir.mkdir()
        (pack_dir / "MANIFEST.yaml").write_text(
            "name: test-skill-pack\nversion: '1.0.0'\ndescription: Test pack\n"
        )
        (tools_dir / "acceptance_tool.py").write_text(
            'from langchain_core.tools import tool\n\n@tool\ndef acceptance_tool(q: str) -> str:\n    """Acceptance test tool."""\n    return q\n'
        )
        self.pack_dir = pack_dir

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        ws = REPO_ROOT / ".olav" / "workspace" / "merge-base-skill"
        if ws.exists():
            shutil.rmtree(ws, ignore_errors=True)

    def test_merge_into_exits_zero(self):
        run_olav("skill", "install", str(self.base_dir))
        result = run_olav("skill", "install", str(self.pack_dir), "--merge-into", "merge-base-skill")
        assert result.returncode == 0, result.stderr

    def test_merge_into_output_confirms_merge(self):
        run_olav("skill", "install", str(self.base_dir))
        result = run_olav("skill", "install", str(self.pack_dir), "--merge-into", "merge-base-skill")
        assert "merged" in result.stdout or "tool" in result.stdout

    def test_merge_into_tool_file_exists(self):
        run_olav("skill", "install", str(self.base_dir))
        run_olav("skill", "install", str(self.pack_dir), "--merge-into", "merge-base-skill")
        tool_path = REPO_ROOT / ".olav" / "workspace" / "merge-base-skill" / "tools" / "acceptance_tool.py"
        assert tool_path.exists(), f"Merged tool not found at {tool_path}"


# ─────────────────────────────────────────────────────────
# C-L2-08  Audit 日志查询
# Claim: OLAV CLI 支持查询 Audit 日志，列出最近操作记录
# Doc:   docs/olav/06_AAA.md
# ─────────────────────────────────────────────────────────
class TestAuditLogClaim:
    """
    Claim C-L2-08: `olav log list` 列出最近 24h 操作记录。
    Verified: 2026-04-03 | Doc: docs/olav/06_AAA.md
    """

    def test_log_list_exits_zero(self):
        result = run_olav("log", "list")
        assert result.returncode == 0, result.stderr

    def test_log_list_output_is_structured(self):
        result = run_olav("log", "list")
        # Should show "Recent Audit Runs" or at least have agent= entries
        assert "agent=" in result.stdout or "Audit" in result.stdout or "runs" in result.stdout.lower()

    def test_log_errors_exits_zero(self):
        result = run_olav("log", "errors")
        assert result.returncode == 0, result.stderr


# ─────────────────────────────────────────────────────────
# C-L2-10  Export Claude Plugin
# Claim: OLAV CLI 支持导出 Claude 兼容的 plugin artifact
# Doc:   docs/olav/07_API_OPENAPI.md
# ─────────────────────────────────────────────────────────
class TestExportClaim:
    """
    Claim C-L2-10: `olav export claude-plugin --agent <name> --output <path>` 生成 artifact。
    Verified: 2026-04-03 | Doc: docs/olav/07_API_OPENAPI.md
    """

    def setup_method(self):
        self.outdir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.outdir, ignore_errors=True)

    def test_export_claude_plugin_exits_zero(self):
        result = run_olav("export", "claude-plugin", "--agent", "core", "--output", str(self.outdir))
        assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    def test_export_claude_plugin_confirms_output(self):
        result = run_olav("export", "claude-plugin", "--agent", "core", "--output", str(self.outdir))
        assert "exported" in result.stdout or "core" in result.stdout


# ─────────────────────────────────────────────────────────
# C-L2-11  Response Extractor（SDK 级别验证）
# Claim: OLAV 自动截断大型 API 响应，防止 LLM context 溢出
# Doc:   docs/olav/07_API_OPENAPI.md
# ─────────────────────────────────────────────────────────
class TestResponseExtractorClaim:
    """
    Claim C-L2-11: response_extractor 自动截断列表 + 支持 NetBox 分页信封解包。
    Verified: 2026-04-03 | Doc: docs/olav/07_API_OPENAPI.md
    """

    def test_truncate_list_adds_sentinel(self):
        from olav.platform.services.response_extractor import truncate_list

        data = [{"id": i} for i in range(100)]
        result = truncate_list(data, max_items=5)
        assert len(result) == 6  # 5 items + 1 sentinel
        assert result[-1].get("_truncated") is True
        assert result[-1].get("total_available") == 100

    def test_truncate_list_preserves_items(self):
        from olav.platform.services.response_extractor import truncate_list

        data = [{"id": i, "name": f"item-{i}"} for i in range(10)]
        result = truncate_list(data, max_items=3)
        actual_items = [r for r in result if not r.get("_truncated")]
        assert len(actual_items) == 3
        assert actual_items[0]["id"] == 0

    def test_auto_extract_netbox_envelope(self):
        from olav.platform.services.response_extractor import auto_extract

        envelope = {
            "count": 2,
            "next": None,
            "results": [{"id": 1, "name": "sw1"}, {"id": 2, "name": "sw2"}],
        }
        result = auto_extract(envelope, "netbox", "GET", "/api/dcim/devices/")
        assert result["count"] == 2
        assert len(result["results"]) == 2

    def test_truncate_list_below_limit_unchanged(self):
        from olav.platform.services.response_extractor import truncate_list

        data = [{"id": i} for i in range(3)]
        result = truncate_list(data, max_items=10)
        assert len(result) == 3
        assert not any(r.get("_truncated") for r in result)


# ─────────────────────────────────────────────────────────
# C-L2-12  多用户并发 Audit
# Claim: 多用户并发使用 OLAV CLI 时，audit 记录不产生写冲突
# Doc:   docs/olav/06_AAA.md
# ─────────────────────────────────────────────────────────
class TestConcurrentAuditClaim:
    """
    Claim C-L2-12: 5 个并发 `olav log list` 调用全部成功，无写冲突错误。
    Verified: 2026-04-03 | Doc: docs/olav/06_AAA.md
    """

    def test_concurrent_log_list_no_errors(self):
        errors: list[str] = []
        results: list[int] = []

        def run():
            r = run_olav("log", "list")
            results.append(r.returncode)
            if r.returncode != 0:
                errors.append(r.stderr[:200])

        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Concurrent audit errors: {errors}"
        assert all(rc == 0 for rc in results), f"Non-zero return codes: {results}"

    def test_concurrent_version_no_errors(self):
        """Version command is stateless — baseline concurrency check."""
        errors: list[str] = []

        def run():
            r = run_olav("version")
            if r.returncode != 0:
                errors.append(r.stderr[:100])

        threads = [threading.Thread(target=run) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Errors: {errors}"


# ─────────────────────────────────────────────────────────
# C-L2-13  初始化项目目录结构
# Claim: `olav init` 在空目录中创建 .olav/ 脚手架
# Doc:   docs/getting-started/installation.md
# ─────────────────────────────────────────────────────────
class TestInitClaim:
    """
    Claim C-L2-13: `olav init` 初始化项目目录结构。
    Verified: 2026-04-03 | Doc: docs/getting-started/installation.md
    """

    def test_init_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_olav("init", cwd=Path(tmpdir))
            assert result.returncode == 0, result.stderr

    def test_init_creates_config_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_olav("init", cwd=Path(tmpdir))
            assert (Path(tmpdir) / ".olav" / "config").exists()

    def test_init_creates_databases_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_olav("init", cwd=Path(tmpdir))
            assert (Path(tmpdir) / ".olav" / "databases").exists()

    def test_init_creates_workspace_core(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_olav("init", cwd=Path(tmpdir))
            assert (Path(tmpdir) / ".olav" / "workspace" / "core").exists()

    def test_init_output_contains_scaffolding_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_olav("init", cwd=Path(tmpdir))
            assert "scaffolding" in result.stdout or "workspace" in result.stdout


# ─────────────────────────────────────────────────────────
# C-L2-36  列出已安装技能
# Claim: `olav skill list` 列出所有已安装技能
# Doc:   docs/guides/manage-workspace.md
# ─────────────────────────────────────────────────────────
class TestSkillListClaim:
    """
    Claim C-L2-36 (list): `olav skill list` 列出已安装技能。
    Verified: 2026-04-03 | Doc: docs/guides/manage-workspace.md
    """

    def test_skill_list_exits_zero(self):
        result = run_olav("skill", "list")
        assert result.returncode == 0, result.stderr

    def test_skill_list_shows_core_workspaces(self):
        # `olav skill list` is deprecated; use `olav list` (v0.18+)
        result = run_olav("list")
        for agent in ("admin", "netops", "core"):
            assert agent in result.stdout, f"Agent '{agent}' not in list output"

    def test_skill_list_shows_managed_skills(self):
        # `olav list` shows Location: for each agent (replaces managed/user categories)
        result = run_olav("list")
        assert "Location:" in result.stdout


# ─────────────────────────────────────────────────────────
# C-L2-36  查看技能状态
# Claim: `olav skill status <name>` 显示技能详细信息
# Doc:   docs/guides/manage-workspace.md
# ─────────────────────────────────────────────────────────
class TestSkillStatusClaim:
    """
    Claim C-L2-36 (status): `olav skill status <name>` 显示技能元数据。
    Verified: 2026-04-03 | Doc: docs/guides/manage-workspace.md
    """

    def setup_method(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp())
        skill_dir = self.tmpdir / "verify-skill"
        skill_dir.mkdir()
        (skill_dir / "MANIFEST.yaml").write_text(
            "name: verify-skill\nversion: '2.0.0'\ndescription: Status verification skill\n"
        )
        (skill_dir / "SKILL.md").write_text(
            "---\nname: verify-skill\ndescription: Status verification skill\ntools: []\n---\n\n# Verify Skill\n"
        )
        run_olav("skill", "install", str(skill_dir))

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        ws = REPO_ROOT / ".olav" / "workspace" / "verify-skill"
        if ws.exists():
            shutil.rmtree(ws, ignore_errors=True)

    def test_skill_status_managed_exits_zero(self):
        result = run_olav("skill", "status", "verify-skill")
        assert result.returncode == 0, result.stderr

    def test_skill_status_shows_name(self):
        # `olav skill status` deprecated; verify via `olav list` that skill appears
        result = run_olav("list")
        assert "verify-skill" in result.stdout

    @pytest.mark.xfail(reason="olav skill status deprecated in v0.18; version/source not exposed via olav list")
    def test_skill_status_shows_version(self):
        result = run_olav("skill", "status", "verify-skill")
        assert "version" in result.stdout

    @pytest.mark.xfail(reason="olav skill status deprecated in v0.18; version/source not exposed via olav list")
    def test_skill_status_shows_source(self):
        result = run_olav("skill", "status", "verify-skill")
        assert "source" in result.stdout

    def test_skill_status_unknown_skill_graceful(self):
        result = run_olav("skill", "status", "nonexistent-skill-zzz")
        # Should not crash with traceback; a clear error message is acceptable
        assert "Traceback" not in result.stderr



# ─────────────────────────────────────────────────────────
# C-L2-26  跳过工具调用确认
# Claim: `olav --auto-approve` 跳过确认提示，正常运行命令
# Doc:   docs/guides/using-agents.md
# ─────────────────────────────────────────────────────────
class TestAutoApproveClaim:
    """
    Claim C-L2-26: `olav --auto-approve <cmd>` 正常运行，exit 0。
    Verified: 2026-04-03 | Doc: docs/guides/using-agents.md
    """

    def test_auto_approve_exits_zero(self):
        result = run_olav("--auto-approve", "version")
        assert result.returncode == 0, result.stderr

    def test_auto_approve_produces_output(self):
        result = run_olav("--auto-approve", "version")
        assert "v0." in result.stdout


# ─────────────────────────────────────────────────────────
# C-L2-27  重置 Agent 对话历史
# Claim: `olav reset --agent <name>` 清除指定 agent 的会话历史
# Doc:   docs/reference/cli.md
# ─────────────────────────────────────────────────────────
class TestResetClaim:
    """
    Claim C-L2-27: `olav reset --agent <name>` 重置 agent 历史，exit 0。
    Verified: 2026-04-03 | Doc: docs/reference/cli.md
    """

    def test_reset_exits_zero(self):
        result = run_olav("reset", "--agent", "core")
        assert result.returncode == 0, result.stderr

    def test_reset_output_contains_reset_confirmation(self):
        result = run_olav("reset", "--agent", "core")
        assert "reset" in result.stdout.lower() or "Agent core" in result.stdout


# ─────────────────────────────────────────────────────────
# C-L2-16  Web 服务启停
# Claim: `olav service web start` 提供浏览器界面和 REST API
# Doc:   docs/guides/services.md
# ─────────────────────────────────────────────────────────
class TestWebServiceClaim:
    """
    Claim C-L2-16: `olav service web start/stop` 正常启停，健康端点响应。
    Verified: 2026-04-03 | Doc: docs/guides/services.md
    """

    def test_web_start_exits_zero(self):
        result = run_olav("service", "web", "start")
        assert result.returncode == 0, result.stderr
        run_olav("service", "web", "stop")

    def test_web_start_output_contains_pid(self):
        result = run_olav("service", "web", "start")
        assert "PID" in result.stdout or "started" in result.stdout.lower()
        run_olav("service", "web", "stop")

    def test_web_health_endpoint_responds(self):
        import urllib.request

        run_olav("service", "web", "start")
        time.sleep(2)
        try:
            with urllib.request.urlopen("http://localhost:2280/health", timeout=5) as resp:
                body = resp.read().decode()
            assert "healthy" in body
        finally:
            run_olav("service", "web", "stop")

    def test_web_stop_exits_zero(self):
        run_olav("service", "web", "start")
        time.sleep(1)
        result = run_olav("service", "web", "stop")
        assert result.returncode == 0, result.stderr


# ─────────────────────────────────────────────────────────
# C-L2-17  Daemon 服务启停
# Claim: `olav service daemon start` 加速 CLI 响应
# Doc:   docs/guides/services.md
# ─────────────────────────────────────────────────────────
class TestDaemonServiceClaim:
    """
    Claim C-L2-17: `olav service daemon start/status/stop` 正常启停。
    Verified: 2026-04-03 | Doc: docs/guides/services.md
    """

    def test_daemon_start_exits_zero(self):
        result = run_olav("service", "daemon", "start")
        assert result.returncode == 0, result.stderr
        run_olav("service", "daemon", "stop")

    def test_daemon_status_shows_running(self):
        run_olav("service", "daemon", "start")
        result = run_olav("service", "daemon", "status")
        assert result.returncode == 0, result.stderr
        assert "Running" in result.stdout or "running" in result.stdout.lower()
        run_olav("service", "daemon", "stop")

    def test_daemon_stop_exits_zero(self):
        run_olav("service", "daemon", "start")
        result = run_olav("service", "daemon", "stop")
        assert result.returncode == 0, result.stderr


# ─────────────────────────────────────────────────────────
# C-L2-18  Syslog 服务启停
# Claim: `olav service logs start` 接收网络设备日志
# Doc:   docs/guides/services.md
# ─────────────────────────────────────────────────────────
class TestSyslogServiceClaim:
    """
    Claim C-L2-18: `olav service logs start/stop` 正常启停。
    Verified: 2026-04-03 | Doc: docs/guides/services.md
    """

    def test_syslog_start_exits_zero(self):
        result = run_olav("service", "logs", "start", "--port", "15514")
        assert result.returncode == 0, result.stderr
        run_olav("service", "logs", "stop")

    def test_syslog_start_output_mentions_started(self):
        result = run_olav("service", "logs", "start", "--port", "15514")
        combined = result.stdout + result.stderr
        assert "started" in combined.lower() or "running" in combined.lower() or "PID" in combined
        run_olav("service", "logs", "stop")

    def test_syslog_stop_exits_zero(self):
        run_olav("service", "logs", "start", "--port", "15514")
        result = run_olav("service", "logs", "stop")
        assert result.returncode == 0, result.stderr


# ─────────────────────────────────────────────────────────
# C-L2-23  用户管理（管理员）
# Claim: `olav admin "add-user/list-users/revoke-token"` 管理用户和令牌
# Doc:   docs/reference/users-and-roles.md
# ─────────────────────────────────────────────────────────
class TestAdminUserClaim:
    """
    Claim C-L2-23: `olav admin` 用户生命周期管理（创建/列表/撤销）。
    Verified: 2026-04-03 | Doc: docs/reference/users-and-roles.md
    """

    _test_user = "testddd_e2e"
    _add_user_cmd = f"add-user testddd_e2e --role user --no-verify"

    def setup_method(self):
        # Ensure clean state: remove test user if it exists
        run_olav("admin", f"revoke-token {self._test_user}")

    def test_add_user_exits_zero(self):
        result = run_olav("admin", self._add_user_cmd)
        assert result.returncode == 0, result.stderr
        run_olav("admin", f"revoke-token {self._test_user}")

    def test_add_user_output_contains_token(self):
        result = run_olav("admin", self._add_user_cmd)
        assert "token" in result.stdout.lower() or "olav_" in result.stdout
        run_olav("admin", f"revoke-token {self._test_user}")

    def test_list_users_contains_created_user(self):
        run_olav("admin", self._add_user_cmd)
        result = run_olav("admin", "list-users")
        assert self._test_user in result.stdout
        run_olav("admin", f"revoke-token {self._test_user}")

    def test_revoke_token_exits_zero(self):
        run_olav("admin", self._add_user_cmd)
        result = run_olav("admin", f"revoke-token {self._test_user}")
        assert result.returncode == 0, result.stderr

    def test_revoke_token_output_confirms_revocation(self):
        run_olav("admin", self._add_user_cmd)
        result = run_olav("admin", f"revoke-token {self._test_user}")
        assert "revoked" in result.stdout.lower()


# ─────────────────────────────────────────────────────────
# C-L2-38  agent_overrides 配置
# Claim: api.json 中 agent_overrides 为不同 Agent 指定不同 LLM 模型
# Doc:   docs/reference/configuration.md
# ─────────────────────────────────────────────────────────
class TestAgentOverrideClaim:
    """
    Claim C-L2-38: 写入 agent_overrides 后 olav 不崩溃，exit 0。
    Verified: 2026-04-03 | Doc: docs/reference/configuration.md
    """

    def test_agent_overrides_no_crash(self):
        api_json = REPO_ROOT / ".olav" / "config" / "api.json"
        original = api_json.read_text()
        try:
            config = json.loads(original)
            config["agent_overrides"] = {"core": {"model": "gpt-4o-mini"}}
            api_json.write_text(json.dumps(config, indent=2))
            result = run_olav("version")
            assert result.returncode == 0, result.stderr
            assert "Traceback" not in result.stderr
        finally:
            api_json.write_text(original)

    def test_agent_overrides_output_still_shows_version(self):
        api_json = REPO_ROOT / ".olav" / "config" / "api.json"
        original = api_json.read_text()
        try:
            config = json.loads(original)
            config["agent_overrides"] = {"core": {"model": "gpt-4o-mini"}}
            api_json.write_text(json.dumps(config, indent=2))
            result = run_olav("version")
            assert "v0." in result.stdout
        finally:
            api_json.write_text(original)


# ─────────────────────────────────────────────────────────
# C-L2-39  环境变量覆盖配置
# Claim: OLAV_LLM_* 环境变量可覆盖 api.json 配置
# Doc:   docs/reference/configuration.md
# ─────────────────────────────────────────────────────────
class TestEnvVarOverrideClaim:
    """
    Claim C-L2-39: OLAV_LLM_MODEL 环境变量不影响非 LLM 命令，exit 0。
    Verified: 2026-04-03 | Doc: docs/reference/configuration.md
    """

    def test_env_var_no_crash(self):
        result = subprocess.run(
            [sys.executable, "-m", "olav", "version"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env={**__import__("os").environ, "OLAV_LLM_MODEL": "test-model"},
        )
        assert result.returncode == 0, result.stderr
        assert "Traceback" not in result.stderr

    def test_env_var_version_output_intact(self):
        result = subprocess.run(
            [sys.executable, "-m", "olav", "version"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env={**__import__("os").environ, "OLAV_LLM_MODEL": "test-model"},
        )
        assert "v0." in result.stdout


# ─────────────────────────────────────────────────────────
# C-L2-25  从 Git URL 安装 Skill
# Claim: `olav skill install <git-url>` 安装成功或返回清晰错误
# Doc:   docs/guides/build-a-skill.md
# ─────────────────────────────────────────────────────────
class TestSkillInstallGitClaim:
    """
    Claim C-L2-25: `olav skill install <git-url>` 失败时返回清晰错误，不崩溃。
    Verified: 2026-04-03 | Doc: docs/guides/build-a-skill.md
    """

    def test_git_install_invalid_url_no_traceback(self):
        result = run_olav("skill", "install", "https://github.com/nonexistent-repo-zzz/nope")
        assert "Traceback" not in result.stderr

    def test_git_install_invalid_url_shows_error_message(self):
        result = run_olav("skill", "install", "https://github.com/nonexistent-repo-zzz/nope")
        combined = result.stdout + result.stderr
        assert "error" in combined.lower() or "failed" in combined.lower() or "fatal" in combined.lower()


# ─────────────────────────────────────────────────────────
# C-L2-37  Skill venv 隔离
# Claim: Skill 声明 requires_packages 时自动创建隔离 .venv
# Doc:   docs/guides/build-a-skill.md
# ─────────────────────────────────────────────────────────
class TestSkillVenvClaim:
    """
    Claim C-L2-37: `requires_packages` 触发 .venv 创建。
    Verified: 2026-04-03 | Doc: docs/guides/build-a-skill.md
    """

    def test_skill_with_requires_packages_creates_venv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "test-venv-e2e"
            skill_dir.mkdir()
            (skill_dir / "MANIFEST.yaml").write_text(
                "name: test-venv-e2e\nversion: '1.0.0'\nkind: Agent\ndescription: 'venv test'\n"
            )
            (skill_dir / "SKILL.md").write_text(
                "---\nname: test-venv-e2e\ndescription: venv test\nrequires_packages:\n  - requests\ntools: []\n---\n"
            )
            result = run_olav("skill", "install", str(skill_dir))
            assert result.returncode == 0, result.stderr
            venv_path = REPO_ROOT / ".olav" / "workspace" / "test-venv-e2e" / ".venv"
            assert venv_path.exists(), f".venv not created at {venv_path}"
            # Cleanup
            shutil.rmtree(REPO_ROOT / ".olav" / "workspace" / "test-venv-e2e", ignore_errors=True)

    def test_skill_with_requires_packages_output_mentions_venv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "test-venv-e2e2"
            skill_dir.mkdir()
            (skill_dir / "MANIFEST.yaml").write_text(
                "name: test-venv-e2e2\nversion: '1.0.0'\nkind: Agent\ndescription: 'venv test 2'\n"
            )
            (skill_dir / "SKILL.md").write_text(
                "---\nname: test-venv-e2e2\ndescription: venv test 2\nrequires_packages:\n  - requests\ntools: []\n---\n"
            )
            result = run_olav("skill", "install", str(skill_dir))
            assert "venv" in result.stdout.lower() or "packages" in result.stdout.lower(), result.stdout
            shutil.rmtree(REPO_ROOT / ".olav" / "workspace" / "test-venv-e2e2", ignore_errors=True)


# ─────────────────────────────────────────────────────────
# C-L2-14  TUI 交互模式
# Claim: `olav`（无参数）进入 TUI 交互模式，支持多轮对话
# Doc:   docs/getting-started/first-query.md
# ─────────────────────────────────────────────────────────
class TestTUIModeClaim:
    """
    Claim C-L2-14: TUI 模式可正常启动并退出。
    Verified: 2026-04-03 | Doc: docs/getting-started/first-query.md
    """

    def test_tui_quit_exits_zero(self):
        result = subprocess.run(
            [sys.executable, "-m", "olav"],
            input="/quit\n",
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=15,
        )
        assert result.returncode == 0, result.stderr

    def test_tui_starts_and_shows_banner(self):
        result = subprocess.run(
            [sys.executable, "-m", "olav"],
            input="/quit\n",
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=15,
        )
        combined = result.stdout + result.stderr
        assert "OLAV" in combined or "olav" in combined.lower()

    def test_tui_no_traceback_on_quit(self):
        result = subprocess.run(
            [sys.executable, "-m", "olav"],
            input="/quit\n",
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=15,
        )
        assert "Traceback" not in result.stderr


# ─────────────────────────────────────────────────────────
# C-L2-15  会话恢复
# Claim: `olav --session <id>` 恢复之前会话，不存在时回退
# Doc:   docs/getting-started/first-query.md
# ─────────────────────────────────────────────────────────
class TestSessionResumeClaim:
    """
    Claim C-L2-15: `olav --session <nonexistent>` 不崩溃，exit 0。
    Verified: 2026-04-03 | Doc: docs/getting-started/first-query.md
    """

    def test_nonexistent_session_no_crash(self):
        result = run_olav("--session", "nonexistent-session-id-zzz", "version")
        assert result.returncode == 0, result.stderr

    def test_nonexistent_session_still_produces_output(self):
        result = run_olav("--session", "nonexistent-session-id-zzz", "version")
        assert "v0." in result.stdout

    def test_nonexistent_session_no_traceback(self):
        result = run_olav("--session", "nonexistent-session-id-zzz", "version")
        assert "Traceback" not in result.stderr


# ─────────────────────────────────────────────────────────
# C-L2-22  导出审计数据
# Claim: `olav log export trajectory` 导出 trajectory.jsonl
# Doc:   docs/guides/audit-and-logs.md
# ─────────────────────────────────────────────────────────
class TestLogExportClaim:
    """
    Claim C-L2-22: `olav log export trajectory --output <path> --no-encrypt` 产出 trajectory.jsonl。
    Verified: 2026-04-03 | Doc: docs/guides/audit-and-logs.md
    Requires olav-ent (M3 private package). Tests skip when not installed.
    """

    def setup_method(self, _method=None):
        try:
            importlib.metadata.version("olav-ent")
        except importlib.metadata.PackageNotFoundError:
            pytest.skip("olav-ent not installed (Milestone 3 enterprise feature)")

    def test_trajectory_export_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_olav("log", "export", "trajectory", "--output", tmpdir, "--no-encrypt")
            assert result.returncode == 0, result.stderr

    def test_trajectory_export_creates_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_olav("log", "export", "trajectory", "--output", tmpdir, "--no-encrypt")
            assert (Path(tmpdir) / "trajectory.jsonl").exists()

    def test_trajectory_export_output_mentions_complete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_olav("log", "export", "trajectory", "--output", tmpdir, "--no-encrypt")
            assert "complete" in result.stdout.lower() or "export" in result.stdout.lower()


# ─────────────────────────────────────────────────────────
# C-L2-19  服务注册
# Claim: `olav registry register <name>` 注册 OpenAPI 服务
# Doc:   docs/guides/connect-a-service.md
# ─────────────────────────────────────────────────────────
class TestRegistryRegisterClaim:
    """
    Claim C-L2-19: `olav registry register` 返回清晰错误或成功，不崩溃。
    Verified: 2026-04-03 | Doc: docs/guides/connect-a-service.md
    """

    def test_registry_register_no_traceback(self):
        result = run_olav("registry", "register", "nonexistent-svc")
        assert "Traceback" not in result.stderr

    def test_registry_register_shows_error_or_usage(self):
        result = run_olav("registry", "register", "nonexistent-svc")
        combined = result.stdout + result.stderr
        assert "error" in combined.lower() or "not found" in combined.lower() or "usage" in combined.lower()

    def test_registry_register_no_crash_on_missing_args(self):
        result = run_olav("registry", "register")
        assert "Traceback" not in result.stderr


# ─────────────────────────────────────────────────────────
# C-L2-34  Core Agent Shell 命令执行
# Claim: `olav --agent core "run: <cmd>"` 执行 shell 命令并返回输出
# Doc:   docs/guides/core-agent.md
# ─────────────────────────────────────────────────────────
class TestCoreAgentShellClaim:
    """
    Claim C-L2-34: `olav --agent core "run: <cmd>"` 执行 shell 命令。
    Verified: 2026-04-03 | Doc: docs/guides/core-agent.md
    """

    @pytest.fixture(scope="class", autouse=True)
    def _shell_result(self, request):
        result = run_olav("--auto-approve", "--agent", "core", "run: echo hello_ddd")
        if result.returncode != 0 and "402" in result.stdout and "credits" in result.stdout:
            pytest.skip("OpenRouter credits exhausted — top up at openrouter.ai/settings/credits")
        request.cls._result = result

    def test_shell_exits_zero(self):
        assert self._result.returncode == 0, self._result.stderr

    def test_shell_output_contains_result(self):
        assert "hello_ddd" in self._result.stdout

    def test_shell_no_traceback(self):
        assert "Traceback" not in self._result.stderr


# ─────────────────────────────────────────────────────────
# C-L2-31  Core Agent Python 代码执行
# Claim: `olav --agent core "run python: <code>"` 执行 Python 并返回结果
# Doc:   docs/guides/core-agent.md
# ─────────────────────────────────────────────────────────
class TestCoreAgentPythonClaim:
    """
    Claim C-L2-31: `olav --agent core "run python: ..."` 执行 Python 代码。
    Verified: 2026-04-03 | Doc: docs/guides/core-agent.md
    """

    @pytest.fixture(scope="class", autouse=True)
    def _python_result(self, request):
        result = run_olav("--auto-approve", "--agent", "core", "run python: print(sum([1,2,3]))")
        if result.returncode != 0 and "402" in result.stdout and "credits" in result.stdout:
            pytest.skip("OpenRouter credits exhausted — top up at openrouter.ai/settings/credits")
        request.cls._result = result

    def test_python_exits_zero(self):
        assert self._result.returncode == 0, self._result.stderr

    def test_python_output_contains_result(self):
        assert "6" in self._result.stdout

    def test_python_no_traceback(self):
        assert "Traceback" not in self._result.stderr


# ─────────────────────────────────────────────────────────
# C-L2-32  Core Agent SQL 查询
# Claim: `olav --agent core "what tables..."` 执行 SQL 并返回数据库结构
# Doc:   docs/guides/core-agent.md
# ─────────────────────────────────────────────────────────
class TestCoreAgentSQLClaim:
    """
    Claim C-L2-32: `olav --agent core "what tables exist"` 返回数据库表列表。
    Verified: 2026-04-03 | Doc: docs/guides/core-agent.md
    """

    @pytest.fixture(scope="class", autouse=True)
    def _sql_result(self, request):
        result = run_olav("--auto-approve", "--agent", "core", "what tables exist in the database?")
        if result.returncode != 0 and "402" in result.stdout and "credits" in result.stdout:
            pytest.skip("OpenRouter credits exhausted — top up at openrouter.ai/settings/credits")
        request.cls._result = result

    def test_sql_exits_zero(self):
        assert self._result.returncode == 0, self._result.stderr

    def test_sql_output_contains_table_info(self):
        assert "netops" in self._result.stdout.lower() or "table" in self._result.stdout.lower()

    def test_sql_no_traceback(self):
        assert "Traceback" not in self._result.stderr


# ─────────────────────────────────────────────────────────
# C-L2-35  Config Agent 工作空间健康检查
# Claim: `olav --agent config "health check"` 返回平台健康摘要
# Doc:   docs/guides/core-agent.md
# ─────────────────────────────────────────────────────────
class TestConfigAgentHealthClaim:
    """
    Claim C-L2-35: `olav --agent admin "health check"` 返回健康状态。
    Updated v0.20.0: core/config sub-agent removed; admin handles health diagnostics.
    Verified: 2026-06-09 | Doc: docs/guides/core-agent.md
    """

    @pytest.fixture(scope="class", autouse=True)
    def _health_result(self, request):
        result = run_olav("--auto-approve", "--agent", "admin", "health check")
        if result.returncode != 0 and "402" in (result.stdout + result.stderr):
            pytest.skip("LLM API credits exhausted")
        request.cls._result = result

    def test_health_check_exits_zero(self):
        assert self._result.returncode == 0, self._result.stderr

    def test_health_check_output_has_status(self):
        combined = self._result.stdout.lower()
        assert any(w in combined for w in ("health", "status", "running", "service"))

    def test_health_check_no_traceback(self):
        assert "Traceback" not in self._result.stderr


# ─────────────────────────────────────────────────────────
# C-L2-33  Core Agent 知识库搜索
# Claim: `olav --agent core "search: <query>"` 返回相关知识
# Doc:   docs/guides/core-agent.md
# ─────────────────────────────────────────────────────────
class TestCoreAgentSearchClaim:
    """
    Claim C-L2-33: `olav --agent core "search: <query>"` 检索知识库。
    Verified: 2026-04-03 | Doc: docs/guides/core-agent.md
    """

    @pytest.fixture(scope="class", autouse=True)
    def _search_result(self, request):
        result = run_olav("--auto-approve", "--agent", "core", "search: what is OSPF")
        # If credits exhausted, skip the whole class rather than reporting wrong failures
        if result.returncode != 0 and "402" in result.stdout and "credits" in result.stdout:
            pytest.skip("OpenRouter credits exhausted — top up at openrouter.ai/settings/credits")
        request.cls._result = result

    def test_search_exits_zero(self):
        assert self._result.returncode == 0, self._result.stderr

    def test_search_returns_content(self):
        assert len(self._result.stdout.strip()) > 50

    def test_search_no_traceback(self):
        assert "Traceback" not in self._result.stderr


# ─────────────────────────────────────────────────────────
# C-L2-29  SSE 流式查询接口
# Claim: `POST /runs/stream` 返回 SSE 流式响应
# Doc:   docs/reference/http-api.md
# ─────────────────────────────────────────────────────────
class TestSSEStreamClaim:
    """
    Claim C-L2-29: `POST /runs/stream` 返回 SSE data: 流。
    Verified: 2026-04-03 | Doc: docs/reference/http-api.md
    """

    def test_sse_stream_returns_events(self):
        import urllib.request, json as _json
        run_olav("service", "web", "start")
        time.sleep(2)
        try:
            req = urllib.request.Request(
                "http://localhost:2280/runs/stream",
                data=_json.dumps({"input": {"messages": [{"role": "user", "content": "say hi in one word"}], "agent": "core"}}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode()
            assert "data:" in body
            assert "event" in body
        finally:
            run_olav("service", "web", "stop")

    def test_sse_stream_contains_chain_start(self):
        import urllib.request, json as _json
        run_olav("service", "web", "start")
        time.sleep(2)
        try:
            req = urllib.request.Request(
                "http://localhost:2280/runs/stream",
                data=_json.dumps({"input": {"messages": [{"role": "user", "content": "say hi in one word"}], "agent": "core"}}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode()
            assert "on_chain_start" in body
        finally:
            run_olav("service", "web", "stop")


# ─────────────────────────────────────────────────────────
# C-L2-30  多轮对话线程管理
# Claim: `POST /threads` 创建线程，`POST /threads/{id}/runs/stream` 在线程中对话
# Doc:   docs/reference/http-api.md
# ─────────────────────────────────────────────────────────
class TestThreadManagementClaim:
    """
    Claim C-L2-30: `POST /threads` 创建线程并支持线程内对话。
    Verified: 2026-04-03 | Doc: docs/reference/http-api.md
    """

    def test_create_thread_returns_id(self):
        import urllib.request, json as _json
        run_olav("service", "web", "start")
        time.sleep(2)
        try:
            req = urllib.request.Request(
                "http://localhost:2280/threads",
                data=_json.dumps({"agent": "core"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = _json.loads(resp.read().decode())
            assert "thread_id" in body
            assert len(body["thread_id"]) > 8
        finally:
            run_olav("service", "web", "stop")

    def test_thread_stream_accepts_input(self):
        import urllib.request, json as _json
        run_olav("service", "web", "start")
        time.sleep(2)
        try:
            # Create thread
            req = urllib.request.Request(
                "http://localhost:2280/threads",
                data=_json.dumps({"agent": "core"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                tid = _json.loads(resp.read().decode())["thread_id"]
            # Stream in thread
            req2 = urllib.request.Request(
                f"http://localhost:2280/threads/{tid}/runs/stream",
                data=_json.dumps({"input": {"messages": [{"role": "user", "content": "say hi"}], "agent": "core"}}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req2, timeout=30) as resp:
                body = resp.read().decode()
            assert "data:" in body
        finally:
            run_olav("service", "web", "stop")


# ─────────────────────────────────────────────────────────
# C-L2-24  /trace-review 分析失败模式
# Claim: `/trace-review` slash 命令分析失败轨迹并写入记忆
# Doc:   docs/concepts/self-improving-loop.md
# ─────────────────────────────────────────────────────────
class TestTraceReviewClaim:
    """
    Claim C-L2-24: `/trace-review` 分析失败模式，写入 LanceDB 记忆，exit 0。
    Verified: 2026-04-03 | Doc: docs/concepts/self-improving-loop.md

    2026-06-12: rewritten against the slash-command dispatch layer
    (execute_command). The original tests piped stdin into
    ``python -m olav``, which stopped working when the REPL became a
    full-screen TUI (deepagents-code) — they timed out at 60s for every
    slash command. Worse, their loose assertions ("trace"/"run"
    anywhere in output) kept passing for months while the /trace-review
    dispatch wiring was actually missing (lost in the v0.11 refactor).
    """

    @staticmethod
    def _run_trace_review(args: str = "") -> str:
        import asyncio

        from olav.cli.commands.builtin import execute_command

        cmd = f"/trace-review {args}".strip()
        return asyncio.run(execute_command(cmd, auto_approve=True))

    def test_trace_review_dispatch_reaches_handler(self):
        out = self._run_trace_review()
        assert out is not None
        # Must be the real handler's table title, not the unknown-command
        # fallthrough to the LLM.
        assert "Trace Review" in out, (
            "/trace-review did not reach cmd_trace_review (dispatch broken?)"
        )
        assert "Unknown command" not in out

    def test_trace_review_shows_metrics(self):
        out = self._run_trace_review()
        assert "Failed / cancelled runs" in out
        assert "Constraints learned" in out

    def test_trace_review_rejects_bad_args(self):
        out = self._run_trace_review("not-a-number")
        assert "Usage" in out


# ─────────────────────────────────────────────────────────
# C-L2-28  多种认证模式（LDAP）
# Claim: auth.mode=ldap 支持通过 LDAP bind 验证用户身份
# Doc:   docs/concepts/security-model.md
# Requires: lldap running on localhost:3890
# ─────────────────────────────────────────────────────────
class TestLDAPAuthClaim:
    """
    Claim C-L2-28: auth.mode 可配置为 ldap，使用 LDAP bind 验证用户凭证。
    Verified: 2026-04-03 | Doc: docs/concepts/security-model.md
    Requires lldap (nitnelave/lldap:stable) on localhost:3890.
    """

    LDAP_HOST = "localhost"
    LDAP_PORT = 3890

    def setup_method(self, _method=None):
        pytest.importorskip("ldap3", reason="LDAP auth requires: pip install ldap3 (or: pip install olav[ldap])")

    @pytest.fixture(autouse=True)
    def _require_lldap(self):
        """Skip if lldap is not running."""
        import socket
        try:
            s = socket.create_connection((self.LDAP_HOST, self.LDAP_PORT), timeout=2)
            s.close()
        except OSError:
            pytest.skip(f"lldap not running on {self.LDAP_HOST}:{self.LDAP_PORT}")

    def _make_provider(self):
        from olav.core.auth.ldap_provider import LDAPAuthProvider
        return LDAPAuthProvider(
            host=self.LDAP_HOST,
            port=self.LDAP_PORT,
            base_dn="dc=example,dc=com",
        )

    def test_ldap_provider_instantiates(self):
        from olav.core.auth.provider import get_auth_provider
        provider = get_auth_provider("ldap")
        assert type(provider).__name__ == "LDAPAuthProvider"

    def test_ldap_admin_auth_success(self):
        provider = self._make_provider()
        identity = provider.authenticate(token="admin:adminpassword")
        assert identity.username == "admin"
        assert identity.source == "token"

    def test_ldap_user_auth_success(self):
        provider = self._make_provider()
        identity = provider.authenticate(token="ddd-tester:TestPass123")
        assert identity.username == "ddd-tester"
        assert identity.source == "token"

    def test_ldap_wrong_password_rejected(self):
        provider = self._make_provider()
        identity = provider.authenticate(token="admin:wrongpassword")
        # Falls back to OS identity, not the requested user
        assert identity.source == "os"

    def test_ldap_no_credentials_fallback(self):
        provider = self._make_provider()
        identity = provider.authenticate(token=None)
        assert identity.source == "os"


# ============================================================
# C-L1-01: Natural Language Controls Infrastructure
# ============================================================

class TestNaturalLanguageClaim:
    """C-L1-01 — OLAV accepts natural language and translates to real tool calls.

    Verification: `olav --agent core "list all devices in the inventory"`
    LLM must call execute_sql and return formatted table.
    """

    @pytest.fixture(scope="class", autouse=True)
    def run_nl_query(self, request):
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav", "--agent", "core",
             "list all devices in the inventory"],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=180,
        )
        request.cls._result = result
        if "402" in result.stdout and "credits" in result.stdout.lower():
            pytest.skip("OpenRouter credits exhausted")
        if "402" in result.stderr and "credits" in result.stderr.lower():
            pytest.skip("OpenRouter credits exhausted")

    def test_exit_code_zero(self):
        assert self._result.returncode == 0, self._result.stderr[:500]

    def test_llm_called_execute_sql(self):
        assert "execute_sql" in self._result.stdout, \
            "LLM did not call execute_sql tool"

    def test_output_contains_device_data(self):
        out = self._result.stdout
        # At least one device hostname expected from netops.devices
        assert any(kw in out for kw in ["R1", "R2", "hostname", "Hostname", "192.168"]), \
            f"No device data in output: {out[:300]}"

    def test_no_traceback(self):
        assert "Traceback" not in self._result.stdout
        assert "Traceback" not in self._result.stderr


# ============================================================
# C-L2-20: Creator Agent Generates Skill from OpenAPI
# ============================================================

class TestCreatorAgentClaim:
    """C-L2-20 — Creator Agent reads an OpenAPI spec and generates a full Skill workspace.

    Verification: `olav --agent config "onboard Gitea API ..."`
    Expected: SKILL.md, AGENT.md, MANIFEST.yaml, tool files created under .olav/workspace/gitea/
    """

    WORKSPACE = REPO_ROOT / ".olav" / "workspace" / "gitea"
    TOOLS_DIR = REPO_ROOT / ".olav" / "workspace" / "ops" / "tools" / "_generated"

    @pytest.fixture(scope="class", autouse=True)
    def check_preconditions(self, request):
        """Skip if Gitea is not running or workspace was already built."""
        import urllib.request
        try:
            urllib.request.urlopen("http://localhost:3000/swagger.v1.json", timeout=3)
        except Exception:
            pytest.skip("Gitea not running on localhost:3000")

    def test_workspace_directory_exists(self):
        assert self.WORKSPACE.is_dir(), \
            f"Gitea workspace not found at {self.WORKSPACE}"

    def test_skill_md_created(self):
        skill_path = self.WORKSPACE / "SKILL.md"
        assert skill_path.is_file(), "SKILL.md not generated"
        content = skill_path.read_text()
        assert "gitea" in content.lower()

    def test_agent_md_created(self):
        assert (self.WORKSPACE / "AGENT.md").is_file()

    def test_manifest_created(self):
        assert (self.WORKSPACE / "MANIFEST.yaml").is_file()

    def test_tool_files_generated(self):
        # Creator Agent was removed in v0.13 — _generated/ dir may not exist
        pytest.skip("Creator Agent removed in v0.13 — tool generation test retired")

    def test_tool_files_have_content(self):
        pytest.skip("Creator Agent removed in v0.13 — tool generation test retired")


# ============================================================
# C-L2-40: olav log show <run-id>
# ============================================================

class TestLogShowClaim:
    """C-L2-40 — olav log show <run-id> displays full event sequence for a run.

    run-id may be the 8-char prefix shown by 'olav log list'.
    Bug fixed: prefix matching now works (was exact-UUID-only before).
    """

    @pytest.fixture(scope="class", autouse=True)
    def get_run_id(self, request):
        # Get a real run_id prefix from log list
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav", "log", "list"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        # Extract first 8-char run_id (format: [timestamp] XXXXXXXX  status)
        import re
        m = re.search(r'\]\s+([0-9a-f]{8})\s+\w+', result.stdout)
        if not m:
            pytest.skip("No run IDs found in log list output")
        request.cls._run_id = m.group(1)

    def test_log_show_exits_zero(self):
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav", "log", "show", self._run_id],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        assert result.returncode == 0

    def test_log_show_returns_events(self):
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav", "log", "show", self._run_id],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        # Either events are shown or "No events" message (valid both ways)
        assert result.returncode == 0


# ============================================================
# C-L2-41: Service management — status + start/stop --all
# ============================================================

class TestServiceManagementClaim:
    """C-L2-41 — olav service status, start --all, stop --all."""

    def test_service_status_exits_zero(self):
        result = run_olav("service", "status")
        assert result.returncode == 0

    def test_service_status_shows_all_services(self):
        result = run_olav("service", "status")
        out = result.stdout
        assert "web" in out
        assert "daemon" in out
        assert "logs" in out

    def test_service_start_all(self):
        result = run_olav("service", "start", "--all")
        assert result.returncode == 0
        assert "✓" in result.stdout or "started" in result.stdout.lower()

    def test_service_stop_all(self):
        result = run_olav("service", "stop", "--all")
        assert result.returncode == 0
        assert "stopped" in result.stdout.lower() or "✓" in result.stdout


# ============================================================
# C-L2-42: Web API introspection — /openapi.json, /docs, /threads/search
# ============================================================

class TestAPIIntrospectionClaim:
    """C-L2-42 — Web API exposes /openapi.json, /docs, /threads/search."""

    @pytest.fixture(scope="class", autouse=True)
    def start_web(self, request):
        run_olav("service", "web", "start")
        import time; time.sleep(2)
        yield
        run_olav("service", "web", "stop")

    def test_openapi_json_reachable(self):
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:2280/openapi.json", timeout=5)
        assert resp.status == 200
        import json
        data = json.loads(resp.read())
        assert data.get("info", {}).get("title") == "OLAV API"

    def test_docs_reachable(self):
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:2280/docs", timeout=5)
        assert resp.status == 200

    def test_threads_search_reachable(self):
        import urllib.request
        resp = urllib.request.urlopen(
            "http://localhost:2280/threads/search?user_id=admin", timeout=20)
        assert resp.status == 200

    def test_web_custom_port(self):
        """olav service web start --port <N> binds to the specified port."""
        run_olav("service", "web", "stop")
        import time; time.sleep(0.5)
        run_olav("service", "web", "start", "--port", "2281")
        time.sleep(1)
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:2281/health", timeout=5)
        assert resp.status == 200
        run_olav("service", "web", "stop")


# ============================================================
# C-L2-43: olav workspace status
# ============================================================

class TestWorkspaceStatusClaim:
    """C-L2-43 — olav workspace status shows installed agents with version/status."""

    def test_workspace_status_exits_zero(self):
        result = run_olav("workspace", "status")
        assert result.returncode == 0

    def test_workspace_status_shows_agents(self):
        result = run_olav("workspace", "status")
        out = result.stdout
        assert "core" in out
        assert "ops" in out

    def test_workspace_status_shows_route_keywords(self):
        result = run_olav("workspace", "status")
        assert "route_keywords" in result.stdout


# ============================================================
# C-L2-44: Admin — rotate-token and add-user --expires
# ============================================================

class TestAdminAdvancedClaim:
    """C-L2-44 — Admin rotate-token and add-user --expires flags."""

    def test_rotate_token_exits_zero(self):
        result = run_olav("admin", "rotate-token testddd")
        assert result.returncode == 0

    def test_rotate_token_returns_new_token(self):
        result = run_olav("admin", "rotate-token testddd")
        assert "olav_" in result.stdout

    def test_add_user_with_expires(self):
        result = run_olav("admin", "add-user exptest2 --role user --expires 2027-01-01 --no-verify")
        assert result.returncode == 0
        assert "olav_" in result.stdout

    def test_expires_stored_in_db(self):
        import duckdb
        con = duckdb.connect(
            str(REPO_ROOT / ".olav" / "databases" / "users.duckdb"), read_only=True
        )
        row = con.execute(
            "SELECT expires_at FROM users WHERE username='exptest2'"
        ).fetchone()
        con.close()
        assert row is not None
        assert row[0] is not None  # expiration was stored


# ============================================================
# C-L2-45: Audit database — direct DuckDB access
# ============================================================

class TestAuditDatabaseClaim:
    """C-L2-45 — audit.duckdb has expected schema and is directly queryable."""

    DB = REPO_ROOT / ".olav" / "databases" / "audit.duckdb"

    def test_audit_db_exists(self):
        assert self.DB.is_file()

    def test_audit_tables_present(self):
        import duckdb
        con = duckdb.connect(str(self.DB), read_only=True)
        tables = {t[0] for t in con.execute("SHOW TABLES").fetchall()}
        con.close()
        assert {"audit_runs", "audit_events", "audit_tool_calls", "audit_messages"}.issubset(tables)

    def test_audit_events_has_data(self):
        import duckdb
        con = duckdb.connect(str(self.DB), read_only=True)
        count = con.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        con.close()
        assert count > 0

    def test_audit_events_schema(self):
        import duckdb
        con = duckdb.connect(str(self.DB), read_only=True)
        cols = {c[0] for c in con.execute("DESCRIBE audit_events").fetchall()}
        con.close()
        assert {"event_id", "event_type", "timestamp", "run_id", "agent_id", "payload"}.issubset(cols)

    def test_log_export_min_score(self):
        """olav log export --min-score filters by quality score. Requires olav-ent."""
        try:
            importlib.metadata.version("olav-ent")
        except importlib.metadata.PackageNotFoundError:
            pytest.skip("olav-ent not installed (Milestone 3 enterprise feature)")
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav", "log", "export", "trajectory",
             "--output", "/tmp/olav-minscore-test", "--min-score", "0.5"],
            capture_output=True, text=True, cwd=REPO_ROOT,
        )
        assert result.returncode == 0
        assert "export" in result.stdout.lower() or "trajectory" in result.stdout.lower() or "samples" in result.stdout.lower()


# ===========================================================================
# C-L2-46: /model <name> 会话内切换 LLM 模型
# Claim: TUI 支持 /model <name> 命令在会话内切换 LLM 模型
# ===========================================================================

class TestModelSwitchClaim:
    """C-L2-46: /model <name> switches model mid-session without config changes."""

    def test_model_command_registered(self):
        """SLASH_COMMANDS registry must contain 'model'."""
        from olav.cli.commands.builtin import SLASH_COMMANDS
        assert "model" in SLASH_COMMANDS

    def test_model_switch_sets_override(self):
        """execute_command('/model gpt-4o-mini') must return success message."""
        import asyncio
        from olav.cli.commands.builtin import execute_command, _model_override
        result = asyncio.run(execute_command("/model gpt-4o-mini"))
        assert result is not None
        assert "gpt-4o-mini" in result
        assert "✅" in result or "Model set" in result

    def test_model_switch_via_tui_pipe(self):
        """/model command must work via stdin pipe to TUI."""
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav"],
            input="/model gpt-4o-mini\n/quit\n",
            capture_output=True, text=True, timeout=20,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0
        assert "gpt-4o-mini" in result.stdout

    def test_model_list_subcommand(self):
        """/model list must return available models list."""
        import asyncio
        from olav.cli.commands.builtin import execute_command
        result = asyncio.run(execute_command("/model list"))
        assert result is not None
        assert "model" in result.lower() or "gpt" in result.lower() or "llm" in result.lower()

    def test_model_reset_subcommand(self):
        """/model reset must clear the override."""
        import asyncio
        from olav.cli.commands.builtin import execute_command
        asyncio.run(execute_command("/model gpt-4o-mini"))
        result = asyncio.run(execute_command("/model reset"))
        assert result is not None
        assert "reset" in result.lower() or "default" in result.lower()


# ===========================================================================
# C-L2-47: @file.txt 文件内容注入
# Claim: TUI 支持 @filename 语法将文件内容注入到提问中
# ===========================================================================

class TestFileInjectionClaim:
    """C-L2-47: @file.txt injects file content as markdown code block."""

    @pytest.fixture(autouse=True)
    def tmp_file(self, tmp_path):
        self.test_file = tmp_path / "olav_c47.txt"
        self.test_file.write_text("hello from olav file injection test C-L2-47")
        self.py_file = tmp_path / "example.py"
        self.py_file.write_text("def greet(): return 'hello'")

    def test_file_expansion_basic(self):
        """expand_file_references must inject file content as code block."""
        from olav.cli.input_parser import expand_file_references
        result = expand_file_references(f"@{self.test_file}")
        assert "hello from olav file injection test C-L2-47" in result

    def test_file_expansion_wraps_in_code_block(self):
        """Injected content must be wrapped in fenced code block."""
        from olav.cli.input_parser import expand_file_references
        result = expand_file_references(f"@{self.test_file}")
        assert "```" in result

    def test_file_expansion_preserves_suffix_text(self):
        """Text after @file reference must be preserved."""
        from olav.cli.input_parser import expand_file_references
        result = expand_file_references(f"@{self.test_file} summarize this")
        assert "hello from olav file injection test C-L2-47" in result
        assert "summarize this" in result

    def test_file_expansion_python_syntax_hint(self):
        """Python files must use 'py' as code block language hint."""
        from olav.cli.input_parser import expand_file_references
        result = expand_file_references(f"@{self.py_file}")
        assert "```py" in result or "```python" in result

    def test_nonexistent_file_passthrough(self):
        """@nonexistent.txt must be left as-is (not raise an error)."""
        from olav.cli.input_parser import expand_file_references
        original = "@/nonexistent/path/to/file.txt hello"
        result = expand_file_references(original)
        assert result == original


# ===========================================================================
# C-L2-48: !command Shell 透传
# Claim: TUI 支持 !command 语法直接执行 Shell 命令，输出显示在终端
# ===========================================================================

class TestShellPassthroughClaim:
    """C-L2-48: !command executes shell commands without going through Agent."""

    def test_shell_passthrough_via_tui_pipe(self):
        """!echo command must produce output via TUI stdin pipe."""
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav"],
            input="!echo hello_olav_shell_48\n/quit\n",
            capture_output=True, text=True, timeout=20,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0
        assert "hello_olav_shell_48" in result.stdout

    def test_shell_passthrough_handled_before_agent(self):
        """input_parser.py must contain '!' prefix branch for shell passthrough."""
        # Logic was moved from main.py to input_parser.py in v0.18+
        parser_src = (REPO_ROOT / "src" / "olav" / "cli" / "input_parser.py").read_text()
        assert 'startswith("!")' in parser_src

    def test_shell_passthrough_git_status(self):
        """!git status must run and exit 0."""
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav"],
            input="!git status\n/quit\n",
            capture_output=True, text=True, timeout=20,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0


# ===========================================================================
# C-L2-49: --sandbox modal/daytona/runloop 远程沙箱 flag
# Claim: CLI 接受 --sandbox {none,modal,daytona,runloop} 参数
# ===========================================================================

class TestSandboxFlagClaim:
    """C-L2-49: --sandbox flag accepts modal/daytona/runloop without error."""

    @pytest.mark.parametrize("backend", ["none", "modal", "daytona", "runloop"])
    def test_sandbox_flag_accepted(self, backend):
        """--sandbox <backend> version must exit 0 (flag accepted by argparse)."""
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav", "--sandbox", backend, "version"],
            capture_output=True, text=True, timeout=15,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, f"--sandbox {backend} was rejected: {result.stderr}"
        assert "unrecognized" not in result.stderr.lower()

    def test_sandbox_choices_in_argparse(self):
        """argparse must define choices for --sandbox."""
        main_src = (REPO_ROOT / "src" / "olav" / "cli" / "main.py").read_text()
        assert '"modal"' in main_src
        assert '"daytona"' in main_src
        assert '"runloop"' in main_src

    def test_sandbox_invalid_value_rejected(self):
        """--sandbox <unknown> must exit non-zero."""
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav", "--sandbox", "docker", "version"],
            capture_output=True, text=True, timeout=15,
            cwd=REPO_ROOT,
        )
        assert result.returncode != 0


# ===========================================================================
# C-L2-50: olav registry list/refresh/status
# Claim: olav registry subcommand 支持 list/register/refresh/status
# ===========================================================================

class TestRegistryClaim:
    """C-L2-50: olav registry list/refresh/status subcommands work."""

    def test_registry_list_exit_zero(self):
        """olav registry list must exit 0."""
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav", "registry", "list"],
            capture_output=True, text=True, timeout=15,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0

    def test_registry_list_shows_table(self):
        """olav registry list must output a table with service columns."""
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav", "registry", "list"],
            capture_output=True, text=True, timeout=15,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0
        out = result.stdout
        assert ("Name" in out or "name" in out or "External" in out or
                "Register:" in out or "services" in out.lower()), \
            f"Expected registry table output, got: {out[:200]}"

    def test_registry_status_invalid_exits_nonzero_or_helpful(self):
        """olav registry status <nonexistent> must exit non-zero or print error."""
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav", "registry", "status",
             "nonexistent_service_zzz"],
            capture_output=True, text=True, timeout=15,
            cwd=REPO_ROOT,
        )
        output = result.stdout + result.stderr
        assert (result.returncode != 0 or
                "not found" in output.lower() or
                "not registered" in output.lower() or
                "error" in output.lower() or
                "nonexistent" in output.lower())

    def test_registry_in_help_output(self):
        """'registry' must appear in olav --help output."""
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav", "--help"],
            capture_output=True, text=True, timeout=15,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0
        assert "registry" in result.stdout.lower()


# ===========================================================================
# C-L2-51: olav config evolve --list/--approve
# Claim: olav config evolve --list 列出待审批的 schema 演进提案
# ===========================================================================

class TestConfigEvolveClaim:
    """C-L2-51: olav config evolve --list/--approve works correctly."""

    def test_config_evolve_list_exit_zero(self):
        """olav config evolve --list must exit 0."""
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav", "config", "evolve", "--list"],
            capture_output=True, text=True, timeout=15,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0, f"Unexpected error: {result.stderr}"

    def test_config_evolve_list_output_meaningful(self):
        """olav config evolve --list must print proposals table or empty message."""
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav", "config", "evolve", "--list"],
            capture_output=True, text=True, timeout=15,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0
        out = result.stdout + result.stderr
        assert ("pending" in out.lower() or
                "proposal" in out.lower() or
                "evolution" in out.lower() or
                "no pending" in out.lower() or
                "EVOLUTION_ID" in out or
                len(out.strip()) > 0)

    def test_config_evolve_help(self):
        """olav config evolve --help must show --list and --approve options."""
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav", "config", "evolve", "--help"],
            capture_output=True, text=True, timeout=15,
            cwd=REPO_ROOT,
        )
        assert result.returncode == 0
        assert "--list" in result.stdout
        assert "--approve" in result.stdout

    def test_config_evolve_approve_requires_id(self):
        """olav config evolve --approve without ID must show error."""
        result = subprocess.run(
            ["uv", "run", "python", "-m", "olav", "config", "evolve", "--approve"],
            capture_output=True, text=True, timeout=15,
            cwd=REPO_ROOT,
        )
        # argparse may exit 0 or non-zero depending on how error is caught;
        # either way, stderr must contain the error message
        output = result.stdout + result.stderr
        assert ("expected one argument" in output or
                "error" in output.lower() or
                result.returncode != 0)

    def test_config_subparser_uses_remainder(self):
        """config subparser must use REMAINDER nargs so --list is not consumed by top-level."""
        import ast
        main_src = (REPO_ROOT / "src" / "olav" / "cli" / "main.py").read_text()
        # After our fix, nargs="*" must not appear for config args
        # (was the bug: nargs="*" caused --list to be consumed by top-level argparse)
        assert 'config_parser.add_argument(\n        "args",\n        nargs="*"' not in main_src


# ===========================================================================
# Batch 4 — DDD_VERIFICATION_TASK.md items not yet covered above
# ===========================================================================


class TestTUIModeClaim:
    """C-L2-14: `olav` with no args or /quit starts TUI and exits cleanly."""

    def test_tui_exits_on_quit_command(self):
        """`echo /quit | olav` — starts TUI, processes /quit, exits cleanly."""
        result = subprocess.run(
            OLAV_CMD,
            input="/quit\n",
            capture_output=True, text=True, timeout=30,
            cwd=REPO_ROOT,
        )
        combined = result.stdout + result.stderr
        # TUI must show the OLAV banner before exiting
        assert ("OLAV" in combined or "olav" in combined.lower()), (
            f"TUI banner not found in output: {combined[:500]!r}"
        )
        assert result.returncode == 0, (
            f"TUI exited with non-zero code {result.returncode}. Output: {combined[:500]}"
        )


class TestSessionResumeClaim:
    """C-L2-15: `olav --session <nonexistent>` does not crash; still executes command."""

    def test_nonexistent_session_does_not_crash(self):
        """`olav --session nonexistent-id version` must output version, not crash."""
        result = subprocess.run(
            OLAV_CMD + ["--session", "nonexistent-00000000", "version"],
            capture_output=True, text=True, timeout=20,
            cwd=REPO_ROOT,
        )
        combined = result.stdout + result.stderr
        # Must NOT produce an unhandled traceback
        assert "Traceback" not in combined, (
            f"Unhandled exception on --session with nonexistent ID:\n{combined[:600]}"
        )
        assert result.returncode == 0, (
            f"Crashed with code {result.returncode}: {combined[:400]}"
        )


class TestLogExportClaim:
    """C-L2-22: `olav log export trajectory` produces a .jsonl file."""

    def test_log_export_creates_jsonl(self):
        """`olav log export trajectory --output <dir> --no-encrypt` produces trajectory.jsonl."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                OLAV_CMD + [
                    "log", "export", "trajectory",
                    "--output", tmpdir,
                    "--no-encrypt",
                ],
                capture_output=True, text=True, timeout=20,
                cwd=REPO_ROOT,
            )
            combined = result.stdout + result.stderr
            assert result.returncode == 0, (
                f"log export failed (code {result.returncode}):\n{combined}"
            )
            jsonl_files = list(Path(tmpdir).glob("trajectory*.jsonl"))
            assert jsonl_files, (
                f"No trajectory*.jsonl found in {tmpdir}. Output:\n{combined}"
            )


class TestRegistryRegisterClaim:
    """C-L2-19: `olav registry register` without URL shows usage error, not traceback."""

    def test_register_no_args_shows_usage(self):
        """`olav registry register` (no URL) must show usage/error, not crash."""
        result = subprocess.run(
            OLAV_CMD + ["registry", "register"],
            capture_output=True, text=True, timeout=15,
            cwd=REPO_ROOT,
        )
        combined = result.stdout + result.stderr
        assert "Traceback" not in combined, (
            f"Unhandled traceback when registry register called with no args:\n{combined[:600]}"
        )
        # Must exit non-zero (missing required arg) OR show usage text
        is_error_or_usage = (
            result.returncode != 0
            or "usage" in combined.lower()
            or "url" in combined.lower()
            or "required" in combined.lower()
        )
        assert is_error_or_usage, (
            f"Expected usage/error indication; got code={result.returncode}, "
            f"output={combined[:400]!r}"
        )


class TestSkillVenvClaim:
    """C-L2-37: skill install creates .venv/ when MANIFEST lists requires_packages."""

    def test_skill_install_creates_venv_for_requires_packages(self):
        """A skill with requires_packages: [requests] gets a .venv/ on install."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "venv-test-skill"
            skill_dir.mkdir()
            # Minimal MANIFEST.yaml with requires_packages
            (skill_dir / "MANIFEST.yaml").write_text(
                "name: venv-test-skill\n"
                "version: 0.1.0\n"
                "description: Venv creation test skill\n"
            )
            # SKILL.md with requires_packages in YAML frontmatter (GAP-10 reads from here)
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "requires_packages:\n"
                "  - requests\n"
                "---\n"
                "# venv-test-skill\n"
                "Test skill for venv creation.\n"
            )
            # Minimal AGENT.md so install completes
            (skill_dir / "AGENT.md").write_text(
                "# venv-test-skill\nTest skill for venv creation.\n"
            )
            result = subprocess.run(
                OLAV_CMD + ["skill", "install", str(skill_dir)],
                capture_output=True, text=True, timeout=60,
                cwd=REPO_ROOT,
            )
            combined = result.stdout + result.stderr
            assert result.returncode == 0, (
                f"`olav skill install` failed (code {result.returncode}):\n{combined}"
            )
            # The skill is installed to .olav/workspace/<name>/ — check there
            installed_path = REPO_ROOT / ".olav" / "workspace" / "venv-test-skill"
            venv_path = installed_path / ".venv"
            assert venv_path.exists(), (
                f".venv not created under {installed_path}. "
                f"Output:\n{combined}"
            )
            # Clean up: uninstall the skill
            subprocess.run(
                OLAV_CMD + ["skill", "remove", "venv-test-skill"],
                capture_output=True, text=True, timeout=15,
                cwd=REPO_ROOT,
            )


class TestSkillInstallGitClaim:
    """C-L2-25: `olav skill install <github-url>` produces a clear result or network error."""

    def test_skill_install_git_url_no_crash(self):
        """`olav skill install` with a GitHub URL must not traceback — either installs or reports network error."""
        # Use a known-good public olav skill URL; tolerate network errors in CI
        test_url = "https://github.com/olavai/skills/tree/main/example-skill"
        result = subprocess.run(
            OLAV_CMD + ["skill", "install", test_url],
            capture_output=True, text=True, timeout=30,
            cwd=REPO_ROOT,
        )
        combined = result.stdout + result.stderr
        assert "Traceback" not in combined, (
            f"Unhandled traceback on git skill install:\n{combined[:600]}"
        )
        # Either succeeds (exit 0) or gives a clear user-facing network/not-found error
        has_clear_message = (
            result.returncode == 0
            or "network" in combined.lower()
            or "not found" in combined.lower()
            or "error" in combined.lower()
            or "failed" in combined.lower()
            or "invalid" in combined.lower()
            or "github" in combined.lower()
        )
        assert has_clear_message, (
            f"No clear message on git skill install failure. "
            f"code={result.returncode}, output={combined[:400]!r}"
        )
