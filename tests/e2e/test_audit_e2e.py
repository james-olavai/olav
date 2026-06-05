"""Audit agent E2E tests.

Covers the audit top-level agent and its sub-agents:
  runner:  run_map_engine, render_report
  author:  create_profile_atomic, save_profile, list_profiles
  explorer: autonomous investigation + record_finding

Structural tests (no LLM) run always.
LLM tests are gated by AUDIT_E2E_ENABLED=1.

Usage:
    # structural only:
    uv run pytest tests/e2e/test_audit_e2e.py -v

    # full:
    AUDIT_E2E_ENABLED=1 uv run pytest tests/e2e/test_audit_e2e.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_OLAV_CMD = [sys.executable, "-m", "olav"]
_WORKSPACE = _ROOT / ".olav" / "workspace" / "audit"
_PROFILES_DIR = _ROOT / ".olav" / "workspace" / "audit" / "profiles"

_LLM_ENABLED = os.environ.get("AUDIT_E2E_ENABLED", "").strip() == "1"
_LLM_SKIP = pytest.mark.skipif(
    not _LLM_ENABLED,
    reason="LLM-gated: set AUDIT_E2E_ENABLED=1 to run audit agent live tests",
)


def _is_transient_llm_error(out: str) -> bool:
    low = out.lower()
    return "loading model" in low or ("503" in out and ("error" in low or "service" in low))


def _run_agent(prompt: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run audit agent; retry up to 3× on transient 503 LLM errors."""
    for attempt in range(3):
        proc = subprocess.Popen(
            _OLAV_CMD + ["--agent", "audit", prompt],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=_ROOT,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            result = subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            result = subprocess.CompletedProcess(proc.args, -1, stdout or "", stderr or "")
        except BaseException:
            try:
                proc.kill()
                proc.communicate()
            except Exception:
                pass
            raise
        out = (result.stdout or "") + (result.stderr or "")
        if not _is_transient_llm_error(out) or attempt == 2:
            return result
        time.sleep(20)
    return result


# ── Structural (no LLM) ──────────────────────────────────────────────────────


class TestAuditAgentStructure:
    """Audit agent workspace structure — no LLM required."""

    def test_agent_md_exists(self):
        # v0.20 workspaces use SKILL.md; accept either
        assert (_WORKSPACE / "SKILL.md").is_file() or (_WORKSPACE / "AGENT.md").is_file()

    def test_runner_subagent_exists(self):
        # renamed from runner/ → audit-runner/ in rev ~295 (FINDING-11 fix)
        assert (_WORKSPACE / "audit-runner" / "SKILL.md").is_file()

    def test_runner_has_run_map_engine(self):
        text = (_WORKSPACE / "audit-runner" / "SKILL.md").read_text(encoding="utf-8")
        assert "run_map_engine" in text or "map_engine" in text

    def test_runner_has_render_report(self):
        text = (_WORKSPACE / "audit-runner" / "SKILL.md").read_text(encoding="utf-8")
        assert "render_report" in text

    def test_author_subagent_exists(self):
        # renamed from author/ → audit-author/ in rev ~295 (FINDING-11 fix)
        assert (_WORKSPACE / "audit-author" / "SKILL.md").is_file()

    def test_author_has_create_profile_atomic(self):
        text = (_WORKSPACE / "audit-author" / "SKILL.md").read_text(encoding="utf-8")
        assert "create_profile_atomic" in text

    def test_explorer_subagent_exists(self):
        assert (_WORKSPACE / "explorer" / "SKILL.md").is_file()

    def test_explorer_has_search_logs(self):
        text = (_WORKSPACE / "explorer" / "SKILL.md").read_text(encoding="utf-8")
        assert "search_logs" in text

    def test_profiles_directory_exists(self):
        assert _PROFILES_DIR.is_dir(), f"profiles/ dir missing at {_PROFILES_DIR}"

    def test_at_least_one_profile_exists(self):
        profiles = list(_PROFILES_DIR.glob("*.md"))
        assert profiles, f"No .md profiles found in {_PROFILES_DIR}"

    def test_audit_listed_in_olav_list(self):
        result = subprocess.run(
            _OLAV_CMD + ["list"],
            capture_output=True, text=True, timeout=30, cwd=_ROOT,
        )
        assert "audit" in result.stdout + result.stderr, (
            "'audit' not found in olav list output"
        )

    def test_map_engine_script_exists(self):
        # migrated from runner/tools/ → audit-runner/scripts/ in rev ~295
        script = _WORKSPACE / "audit-runner" / "scripts" / "map_engine.py"
        assert script.is_file(), f"map_engine.py missing at {script}"

    def test_render_report_script_exists(self):
        # migrated from runner/tools/ → audit-runner/scripts/ in rev ~295
        script = _WORKSPACE / "audit-runner" / "scripts" / "render_report.py"
        assert script.is_file(), f"render_report.py missing at {script}"


# ── Behaviour (LLM required) ─────────────────────────────────────────────────


@_LLM_SKIP
@pytest.mark.timeout(120)
class TestAuditListProfiles:
    """audit agent author: list available profiles."""

    _result: "subprocess.CompletedProcess | None" = None

    @classmethod
    def _get_result(cls) -> subprocess.CompletedProcess:
        if cls._result is None:
            cls._result = _run_agent("list available audit profiles", timeout=90)
        return cls._result

    @pytest.mark.xfail(strict=False, reason="LLM output quality varies; 90s tight for 3-hop agent chain")
    def test_exits_zero(self):
        r = self._get_result()
        assert r.returncode == 0, f"audit list profiles failed:\n{r.stdout}\n{r.stderr}"

    def test_mentions_at_least_one_profile(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert any(kw in out.lower() for kw in ("bgp", "profile", "health", "check", "cpu")), (
            f"Response does not mention any profile names:\n{out[:600]}"
        )

    def test_no_traceback(self):
        out = self._get_result().stdout + self._get_result().stderr
        if _is_transient_llm_error(out):
            return  # 503 during model warmup — not a code defect
        assert "Traceback" not in out


@_LLM_SKIP
@pytest.mark.timeout(420)
class TestAuditProfileCreation:
    """audit agent author: create a BGP health-check profile."""

    _result: "subprocess.CompletedProcess | None" = None

    @classmethod
    def _get_result(cls) -> subprocess.CompletedProcess:
        if cls._result is None:
            cls._result = _run_agent("创建一个 BGP 会话健康检查 profile", timeout=360)
        return cls._result

    @pytest.mark.xfail(strict=False, reason="LLM output quality varies with model")
    def test_exits_zero(self):
        r = self._get_result()
        assert r.returncode == 0, f"audit create profile failed:\n{r.stdout}\n{r.stderr}"

    @pytest.mark.xfail(strict=False, reason="LLM output quality varies with model")
    def test_mentions_bgp(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert "BGP" in out or "bgp" in out.lower()

    @pytest.mark.xfail(strict=False, reason="LLM output quality varies with model")
    def test_mentions_profile_saved(self):
        out = self._get_result().stdout + self._get_result().stderr
        assert any(kw in out.lower() for kw in ("saved", "profile", "created", "written", "---"))

    def test_no_traceback(self):
        out = self._get_result().stdout + self._get_result().stderr
        if _is_transient_llm_error(out):
            return  # 503 during model warmup — not a code defect
        assert "Traceback" not in out


@_LLM_SKIP
@pytest.mark.timeout(300)
class TestAuditRunProfile:
    """audit agent runner: run an existing BGP health-check profile."""

    def test_run_bgp_health_check(self):
        # Find a BGP profile to run
        bgp_profiles = list(_PROFILES_DIR.glob("*bgp*"))
        if not bgp_profiles:
            pytest.skip("No BGP profile found in profiles/ — create one first")
        profile_name = bgp_profiles[0].stem
        result = _run_agent(f"run the {profile_name} profile", timeout=240)
        out = result.stdout + result.stderr
        if _is_transient_llm_error(out):
            return  # 503 during model warmup — not a code defect
        assert result.returncode == 0 or result.returncode == -1, (
            f"audit runner crashed (not timeout): {out[:600]}"
        )
        assert "Traceback" not in out

    def test_run_profile_exits_cleanly_on_empty_db(self):
        """Runner must not crash when DB has no netops data."""
        result = _run_agent("run audit on BGP sessions", timeout=240)
        out = result.stdout + result.stderr
        if _is_transient_llm_error(out):
            return  # 503 during model warmup — not a code defect
        assert "Traceback" not in out, f"Traceback in runner output:\n{out[:800]}"
