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
        # v0.20 workspaces use SKILL.md; accept either
        assert (_WORKSPACE / "SKILL.md").is_file() or (_WORKSPACE / "AGENT.md").is_file()

    def test_agent_md_declares_name_admin(self):
        agent_file = (
            _WORKSPACE / "SKILL.md" if (_WORKSPACE / "SKILL.md").is_file()
            else _WORKSPACE / "AGENT.md"
        )
        text = agent_file.read_text(encoding="utf-8")
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

    def test_admin_editor_update_config_tool_exists(self):
        # dev_docs/99 §3.4/§3.5 — self-configuration + rollback
        tool = _WORKSPACE / "editor" / "tools" / "update_config.py"
        assert tool.is_file(), f"update_config.py missing at {tool}"

    def test_admin_editor_subagent_declares_update_config_tools(self):
        text = (_WORKSPACE / "editor" / "SKILL.md").read_text(encoding="utf-8")
        for name in ("update_llm_config", "update_embedding_config", "rollback_config"):
            assert name in text, f"admin/editor/SKILL.md must declare {name}"

    def test_admin_editor_undo_last_action_script_exists(self):
        # dev_docs/99 §7.4 — generalized undo for agent write-actions
        script = _WORKSPACE / "editor" / "scripts" / "undo_last_action.py"
        assert script.is_file(), f"undo_last_action.py missing at {script}"

    def test_admin_editor_subagent_declares_undo_last_action(self):
        text = (_WORKSPACE / "editor" / "SKILL.md").read_text(encoding="utf-8")
        assert "undo_last_action" in text, "admin/editor/SKILL.md must declare undo_last_action"


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

    @pytest.mark.xfail(strict=False, reason="health check exits non-zero when env has errors (nornir missing, services down)")
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


# ── self-configuration (dev_docs/99 §3.4/§3.5) ───────────────────────────────
#
# Safety: these tests must NEVER leave this repo's real .olav/config/api.json
# (or its .lastgood snapshot) mutated as a side effect of running the test
# suite — that config is shared dev-environment state, not test fixture data.
# The prompts are deliberately narrow (call this one exact tool, once, with
# this one value, then stop) rather than open-ended — an open-ended prompt
# ("update my key, tell me if it worked") observed the agent retrying with
# *other* field values after the first rejection (including one that
# happened to validate and commit for real, since a same-as-current value is
# a legitimately valid candidate). `_protect_api_json` is a second,
# independent safety net regardless of prompt behaviour: it snapshots both
# api.json and any .lastgood file before the LLM call and hard-fails
# (restoring the original state first) if either changed.

_API_JSON_PATH = _ROOT / ".olav" / "config" / "api.json"
_API_JSON_SNAPSHOT_PATH = _ROOT / ".olav" / "config" / "api.json.lastgood"


def _read_bytes_or_none(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def _restore_bytes_or_delete(path: Path, content: bytes | None) -> None:
    if content is not None:
        path.write_bytes(content)
    else:
        path.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def _protect_api_json():
    original = _read_bytes_or_none(_API_JSON_PATH)
    original_snapshot = _read_bytes_or_none(_API_JSON_SNAPSHOT_PATH)
    yield
    current = _read_bytes_or_none(_API_JSON_PATH)
    current_snapshot = _read_bytes_or_none(_API_JSON_SNAPSHOT_PATH)
    if current != original or current_snapshot != original_snapshot:
        _restore_bytes_or_delete(_API_JSON_PATH, original)
        _restore_bytes_or_delete(_API_JSON_SNAPSHOT_PATH, original_snapshot)
        pytest.fail(
            "api.json and/or api.json.lastgood were mutated by this test run "
            "and have been restored — the agent must have committed a "
            "candidate config. Investigate before re-running."
        )


@_LLM_SKIP
class TestAdminUpdateLLMConfigRejection:
    """admin agent editor sub-agent: update_llm_config rejects a bad candidate."""

    _result: "subprocess.CompletedProcess | None" = None

    @classmethod
    def _get_result(cls) -> subprocess.CompletedProcess:
        if cls._result is None:
            cls._result = _run_agent(
                "Call the update_llm_config tool exactly once with "
                "api_key='sk-test-intentionally-invalid-000' and nothing else. "
                "Report only the result of that single call. Do not retry "
                "with a different api_key, model, or any other field, and do "
                "not call rollback_config.",
                timeout=90,
            )
        return cls._result

    def test_exits_zero(self):
        r = self._get_result()
        assert r.returncode == 0, f"update_llm_config request failed:\n{r.stdout}\n{r.stderr}"

    def test_mentions_rejection_or_failure(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert any(
            kw in out.lower()
            for kw in ("reject", "fail", "invalid", "unauthorized", "401", "error", "unchanged")
        ), f"Response does not indicate the candidate was rejected:\n{out[:600]}"

    def test_no_traceback(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert "Traceback" not in out


@_LLM_SKIP
class TestAdminRollbackConfig:
    """admin agent editor sub-agent: rollback_config (no-op when no snapshot exists)."""

    _result: "subprocess.CompletedProcess | None" = None

    @classmethod
    def _get_result(cls) -> subprocess.CompletedProcess:
        if cls._result is None:
            cls._result = _run_agent("Undo my most recent LLM configuration change.", timeout=90)
        return cls._result

    def test_exits_zero(self):
        r = self._get_result()
        assert r.returncode == 0, f"rollback_config request failed:\n{r.stdout}\n{r.stderr}"

    def test_mentions_rollback_outcome(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert any(
            kw in out.lower()
            for kw in ("restore", "rollback", "snapshot", "undo", "no last-known-good", "nothing to")
        ), f"Response does not mention a rollback outcome:\n{out[:600]}"

    def test_no_traceback(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert "Traceback" not in out


# ── generalized undo (dev_docs/99 §7.4) ──────────────────────────────────────
#
# Behavioural proof that "undo my last file change" flows through a real
# conversation: admin router → editor sub-agent → undo_last_action script →
# journal revert. State is fully controlled: the test seeds ONE synthetic
# journal entry pointing at a scratch file it owns under .olav/run/, and
# `_protect_undo_journal` snapshots/restores the whole journal dir so the
# run can neither consume a real user's pending undo entry nor leave its
# own seed behind.

_UNDO_JOURNAL_DIR = _ROOT / ".olav" / "run" / "undo"
_UNDO_SCRATCH = _ROOT / ".olav" / "run" / "e2e_undo_scratch.txt"


@pytest.fixture(autouse=True)
def _protect_undo_journal():
    saved = {}
    if _UNDO_JOURNAL_DIR.is_dir():
        saved = {p.name: p.read_bytes() for p in _UNDO_JOURNAL_DIR.glob("*.json")}
    yield
    if _UNDO_JOURNAL_DIR.is_dir():
        for p in _UNDO_JOURNAL_DIR.glob("*.json"):
            p.unlink(missing_ok=True)
    _UNDO_JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in saved.items():
        (_UNDO_JOURNAL_DIR / name).write_bytes(content)
    _UNDO_SCRATCH.unlink(missing_ok=True)


@_LLM_SKIP
class TestAdminUndoLastAction:
    """admin agent editor sub-agent: undo_last_action reverts a seeded write."""

    _result: "subprocess.CompletedProcess | None" = None
    _scratch_after: "str | None" = None
    """Scratch-file content captured immediately after the agent run —
    the per-test `_protect_undo_journal` teardown deletes the file, so
    later tests in this class must assert on this snapshot, not the disk."""

    @classmethod
    def _get_result(cls) -> subprocess.CompletedProcess:
        if cls._result is None:
            from olav.core.undo_journal import record_action

            _UNDO_SCRATCH.parent.mkdir(parents=True, exist_ok=True)
            _UNDO_SCRATCH.write_text("MODIFIED", encoding="utf-8")
            assert record_action(
                "file_write",
                f"overwrote {_UNDO_SCRATCH}",
                {"path": str(_UNDO_SCRATCH), "existed": True, "previous_content": "ORIGINAL"},
            )
            cls._result = _run_agent(
                "Undo my last file change and tell me what was undone.", timeout=90
            )
            cls._scratch_after = (
                _UNDO_SCRATCH.read_text(encoding="utf-8") if _UNDO_SCRATCH.exists() else None
            )
        return cls._result

    def test_exits_zero(self):
        r = self._get_result()
        assert r.returncode == 0, f"undo request failed:\n{r.stdout}\n{r.stderr}"

    def test_scratch_file_actually_reverted(self):
        self._get_result()
        assert self._scratch_after == "ORIGINAL", (
            f"the seeded write was not reverted (content after run: "
            f"{self._scratch_after!r}) — undo_last_action did not run"
        )

    def test_mentions_undo_outcome(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert any(
            kw in out.lower() for kw in ("undo", "undone", "revert", "restore")
        ), f"Response does not mention an undo outcome:\n{out[:600]}"

    def test_no_traceback(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert "Traceback" not in out


# ── runtime failure → actionable hint (dev_docs/99 §7.2) ─────────────────────


@_LLM_SKIP  # needs the real provider endpoint reachable (to return the 401)
class TestRuntimeFailureHint:
    """A broken key on a real query yields the doctor/rollback hint, not a bare error."""

    _result: "subprocess.CompletedProcess | None" = None

    @classmethod
    def _get_result(cls) -> subprocess.CompletedProcess:
        if cls._result is None:
            env = {**os.environ, "OLAV_LLM_API_KEY": "sk-broken-for-e2e"}
            proc = subprocess.run(
                _OLAV_CMD + ["hello, e2e recovery-hint check"],
                capture_output=True, text=True, timeout=120, cwd=_ROOT, env=env,
            )
            cls._result = proc
        return cls._result

    def test_hint_names_doctor(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert "olav doctor" in out, f"No actionable hint in failure output:\n{out[:800]}"

    def test_hint_names_rollback_path(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert "rollback my LLM config" in out

    def test_no_traceback_noise(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert "Traceback (most recent call last)" not in out


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
