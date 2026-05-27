"""Admin agent E2E tests.

Covers admin top-level agent (platform self-management):
  admin.ops sub-agent:       check_health, export_logs, manage_cron
  admin.developer sub-agent: skill list/install, audit_workspace

Structural tests (no LLM required) run always.
Behaviour tests (require LLM) are gated by ADMIN_E2E_ENABLED=1.

Usage:
    # structural only (always safe):
    uv run pytest tests/e2e/test_admin_e2e.py -v

    # full LLM tests:
    ADMIN_E2E_ENABLED=1 uv run pytest tests/e2e/test_admin_e2e.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_OLAV_CMD = [sys.executable, "-m", "olav"]
_WORKSPACE = _ROOT / ".olav" / "workspace" / "admin"

_LLM_ENABLED = os.environ.get("ADMIN_E2E_ENABLED", "").strip() == "1"
_LLM_SKIP = pytest.mark.skipif(
    not _LLM_ENABLED,
    reason="LLM-gated: set ADMIN_E2E_ENABLED=1 to run admin agent live tests",
)


def _run_agent(prompt: str, timeout: int = 120) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(
        _OLAV_CMD + ["--agent", "admin", prompt],
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


# ── Structural (no LLM) ──────────────────────────────────────────────────────


class TestAdminAgentStructure:
    """Admin agent workspace structure is correct — no LLM required."""

    def test_agent_md_exists(self):
        assert (_WORKSPACE / "AGENT.md").is_file()

    def test_agent_md_declares_name_admin(self):
        text = (_WORKSPACE / "AGENT.md").read_text(encoding="utf-8")
        assert "name: admin" in text

    def test_ops_subagent_exists(self):
        assert (_WORKSPACE / "ops" / "SKILL.md").is_file()

    def test_ops_subagent_has_check_health(self):
        text = (_WORKSPACE / "ops" / "SKILL.md").read_text(encoding="utf-8")
        assert "check_health" in text

    def test_ops_subagent_has_export_logs(self):
        text = (_WORKSPACE / "ops" / "SKILL.md").read_text(encoding="utf-8")
        assert "export_logs" in text

    def test_ops_subagent_has_manage_cron(self):
        text = (_WORKSPACE / "ops" / "SKILL.md").read_text(encoding="utf-8")
        assert "manage_cron" in text

    def test_editor_subagent_exists(self):
        # formerly 'developer' — renamed to 'editor' in rev ~282
        assert (_WORKSPACE / "editor" / "SKILL.md").is_file()

    def test_admin_listed_in_olav_list(self):
        result = subprocess.run(
            _OLAV_CMD + ["list"],
            capture_output=True, text=True, timeout=30, cwd=_ROOT,
        )
        assert result.returncode == 0, f"olav list failed: {result.stderr}"
        assert "admin" in result.stdout + result.stderr, (
            "'admin' not found in olav list output"
        )

    def test_admin_check_health_tool_exists(self):
        tool = _WORKSPACE / "ops" / "scripts" / "check_health.py"
        assert tool.is_file(), f"check_health.py missing at {tool}"

    def test_admin_export_logs_tool_exists(self):
        tool = _WORKSPACE / "ops" / "scripts" / "export_logs.py"
        assert tool.is_file(), f"export_logs.py missing at {tool}"

    def test_admin_installer_scripts_exist(self):
        scripts = _WORKSPACE / "installer" / "scripts"
        for name in ("skill_query.py", "skill_install.py", "adapt_skill.py", "analyze_skill.py"):
            assert (scripts / name).is_file(), f"admin/installer/scripts/{name} missing"

    def test_admin_editor_scripts_exist(self):
        scripts = _WORKSPACE / "editor" / "scripts"
        for name in ("audit_workspace.py", "scaffold_skill.py", "write_workspace_file.py",
                     "tool_help.py", "load_reference.py", "get_static_context.py"):
            assert (scripts / name).is_file(), f"admin/editor/scripts/{name} missing"

    def test_admin_installer_subagent_declares_scripts(self):
        text = (_WORKSPACE / "installer" / "SKILL.md").read_text(encoding="utf-8")
        for name in ("skill_query", "skill_install"):
            assert name in text, f"admin/installer/SKILL.md must declare {name}"

    def test_admin_editor_subagent_declares_scripts(self):
        text = (_WORKSPACE / "editor" / "SKILL.md").read_text(encoding="utf-8")
        for name in ("audit_workspace", "scaffold_skill", "write_workspace_file"):
            assert name in text, f"admin/editor/SKILL.md must declare {name}"


# ── Behaviour (LLM required) ─────────────────────────────────────────────────


@_LLM_SKIP
class TestAdminHealthCheck:
    """admin agent check_health: platform status check."""

    _result: "subprocess.CompletedProcess | None" = None

    @classmethod
    def _get_result(cls) -> subprocess.CompletedProcess:
        if cls._result is None:
            cls._result = _run_agent("check platform health", timeout=90)
        return cls._result

    def test_exits_zero(self):
        r = self._get_result()
        assert r.returncode == 0, f"admin check_health failed:\n{r.stdout}\n{r.stderr}"

    def test_mentions_health_status(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert any(kw in out.lower() for kw in ("health", "ok", "running", "status", "error", "healthy")), (
            f"Response does not mention health status:\n{out[:600]}"
        )

    def test_no_traceback(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert "Traceback" not in out


@_LLM_SKIP
class TestAdminSkillList:
    """admin agent developer sub-agent: list installed skills."""

    _result: "subprocess.CompletedProcess | None" = None

    @classmethod
    def _get_result(cls) -> subprocess.CompletedProcess:
        if cls._result is None:
            cls._result = _run_agent("list installed skills and their status", timeout=90)
        return cls._result

    def test_exits_zero(self):
        r = self._get_result()
        assert r.returncode == 0, f"admin skill list failed:\n{r.stdout}\n{r.stderr}"

    def test_mentions_skills_or_workspace(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert any(kw in out.lower() for kw in ("skill", "workspace", "installed", "agent", "plugin")), (
            f"Response does not mention skills or workspace:\n{out[:600]}"
        )

    def test_no_traceback(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert "Traceback" not in out


@_LLM_SKIP
class TestAdminCronList:
    """admin agent ops sub-agent: list cron schedules."""

    _result: "subprocess.CompletedProcess | None" = None

    @classmethod
    def _get_result(cls) -> subprocess.CompletedProcess:
        if cls._result is None:
            cls._result = _run_agent("list current cron schedules", timeout=90)
        return cls._result

    def test_exits_zero(self):
        r = self._get_result()
        assert r.returncode == 0, f"admin cron list failed:\n{r.stdout}\n{r.stderr}"

    def test_no_traceback(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert "Traceback" not in out
