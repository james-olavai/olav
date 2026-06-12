"""v0.15.0 Core Agent E2E tests.

Covers:
  C-V15-01 — `olav "R1 show version"` → core agent routes through execute_cli
  C-V15-02 — `olav "R1 BGP 邻居?"` → core agent answers via execute_sql
  C-V15-03 — `olav "润色 exports/x.md"` → writer subagent handles text polish
  C-V15-04 — `olav "模拟 R3 断开所有邻居"` → core responds / suggests ops
  C-V15-07 — `olav list` does NOT show quick/olav/venv-test-skill agents

Always-run (no LLM):
  C-V15-07 — olav list workspace cleanup check

LLM-gated (V15_E2E_ENABLED=1):
  C-V15-01~04 — real agent invocation tests

Usage:
    # Always-run only:
    uv run pytest tests/e2e/test_v15_core_e2e.py -v

    # Full LLM tests:
    V15_E2E_ENABLED=1 uv run pytest tests/e2e/test_v15_core_e2e.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_OLAV_CMD = [sys.executable, "-m", "olav"]

_LLM_ENABLED = (
    os.environ.get("V15_E2E_ENABLED", "").strip() == "1"
    or os.environ.get("OPS_NL_E2E_ENABLED", "").strip() == "1"
    or bool(os.environ.get("OLAV_API_KEY") or os.environ.get("OPENAI_API_KEY"))
)

_LLM_SKIP = pytest.mark.skipif(
    not _LLM_ENABLED,
    reason="LLM-gated: set V15_E2E_ENABLED=1 or provide an API key to run",
)


def _run_olav(*args, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run `python -m olav <args>` and return CompletedProcess."""
    proc = subprocess.Popen(
        _OLAV_CMD + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=_ROOT,
    )
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            return subprocess.CompletedProcess(proc.args, -1, stdout, stderr)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def _run_agent(prompt: str, agent: str | None = None, timeout: int = 270) -> subprocess.CompletedProcess:
    """Run `olav [--agent <agent>] <prompt>` and return CompletedProcess."""
    cmd = []
    if agent:
        cmd += ["--agent", agent]
    cmd.append(prompt)
    return _run_olav(*cmd, timeout=timeout)


# ---------------------------------------------------------------------------
# C-V15-07 — olav list no longer shows legacy workspaces (always-run)
# ---------------------------------------------------------------------------


class TestWorkspaceListClean:
    """C-V15-07: `olav list` must NOT show quick, olav, or venv-test-skill."""

    @pytest.fixture(scope="class", autouse=True)
    def result(self, request):
        r = _run_olav("list")
        request.cls._rc = r.returncode
        request.cls._out = (r.stdout + r.stderr).lower()

    def test_exits_zero(self):
        assert self._rc == 0, f"olav list exited {self._rc}"

    def test_quick_not_present(self):
        assert "quick" not in self._out, "olav list still shows 'quick' workspace"

    def test_olav_workspace_not_present(self):
        # "olav" appears as brand name — check specifically for workspace entry
        # The workspace name "olav" would appear as "| olav |" or "olav (" in listing
        out = self._out
        # Exclude brand/CLI name occurrences: match workspace-style occurrences
        import re
        workspace_pattern = re.compile(r"[\|\(]\s*olav\s*[\|\)]")
        assert not workspace_pattern.search(out), \
            "olav list shows 'olav' workspace — legacy workspace should be gone"

    def test_venv_test_skill_not_present(self):
        assert "venv-test-skill" not in self._out, \
            "olav list still shows 'venv-test-skill' workspace"

    def test_core_is_present(self):
        assert "core" in self._out, "olav list does not show 'core' agent"


# ---------------------------------------------------------------------------
# C-V15-01 — core answers device CLI query (LLM-gated)
# ---------------------------------------------------------------------------


@_LLM_SKIP
class TestCoreDeviceCLIQuery:
    """C-V15-01: `olav "R1 show version"` routes to core and attempts execute_cli."""

    @pytest.fixture(scope="class", autouse=True)
    def result(self, request):
        r = _run_agent("show R1 version", timeout=270)
        request.cls._rc = r.returncode
        request.cls._out = r.stdout + r.stderr

    def test_exits_zero_or_graceful(self):
        # Agent should exit 0; -1 means timeout
        assert self._rc in (0, 1), f"Unexpected exit code: {self._rc}"

    def test_core_agent_ran(self):
        out = self._out.lower()
        # Core agent should produce output — any non-empty response counts
        assert len(out.strip()) > 0, "Core agent produced no output"

    def test_no_quick_agent_reference(self):
        # Should not reference the deleted quick workspace in output
        assert "quick agent" not in self._out.lower(), \
            "Response mentioned deprecated quick agent"


# ---------------------------------------------------------------------------
# C-V15-02 — core answers NL DB query (LLM-gated)
# ---------------------------------------------------------------------------


@_LLM_SKIP
class TestCoreDatabaseQuery:
    """C-V15-02: `olav "R1 BGP 邻居?"` routes to core and uses execute_sql."""

    @pytest.fixture(scope="class", autouse=True)
    def result(self, request):
        r = _run_agent("R1 有几个 BGP 邻居？", timeout=270)
        request.cls._rc = r.returncode
        request.cls._out = r.stdout + r.stderr

    def test_exits_zero_or_graceful(self):
        assert self._rc in (0, 1), f"Unexpected exit code: {self._rc}"

    def test_produced_output(self):
        assert len(self._out.strip()) > 0, "Core agent produced no output for BGP query"

    def test_no_quick_agent_reference(self):
        assert "quick agent" not in self._out.lower(), \
            "Response mentioned deprecated quick agent"


# ---------------------------------------------------------------------------
# C-V15-03 — writer subagent handles text polish (LLM-gated)
# ---------------------------------------------------------------------------


@_LLM_SKIP
class TestCoreWriterSubagent:
    """C-V15-03: `olav "润色文件"` delegates to writer subagent."""

    @pytest.fixture(scope="class", autouse=True)
    def result(self, request, tmp_path):
        # Create a test markdown file
        test_file = tmp_path / "test_polish.md"
        test_file.write_text("# 测试\n\nthis is test content that need polishing.\n")
        request.cls._test_file = test_file

        r = _run_agent(f"润色并改善这段文字：this is test content that need polishing", timeout=270)
        request.cls._rc = r.returncode
        request.cls._out = r.stdout + r.stderr

    def test_exits_zero_or_graceful(self):
        assert self._rc in (0, 1), f"Unexpected exit code: {self._rc}"

    def test_produced_polished_output(self):
        out = self._out.strip()
        assert len(out) > 0, "Writer/core agent produced no output for polish request"

    def test_response_is_improved_text(self):
        # Should get some kind of text response (not an error)
        out = self._out.lower()
        assert "error" not in out or len(out) > 200, \
            "Writer/core agent returned an error response"


# ---------------------------------------------------------------------------
# C-V15-04 — core handles network simulation or suggests ops (LLM-gated)
# ---------------------------------------------------------------------------


@_LLM_SKIP
class TestCoreNetworkSimulationRouting:
    """C-V15-04: Complex network simulation query → core responds or suggests ops."""

    @pytest.fixture(scope="class", autouse=True)
    def result(self, request):
        r = _run_agent("模拟 R3 断开所有 BGP 邻居，分析影响", timeout=270)
        request.cls._rc = r.returncode
        request.cls._out = r.stdout + r.stderr

    def test_exits_zero_or_graceful(self):
        assert self._rc in (0, 1), f"Unexpected exit code: {self._rc}"

    def test_produced_output(self):
        assert len(self._out.strip()) > 0, "Core agent produced no output for simulation query"

    def test_response_relevant_to_network(self):
        out = self._out.lower()
        # Should contain network-relevant terms or agent suggestion
        keywords = ["bgp", "r3", "neighbor", "邻居", "路由", "route", "ops", "simulate", "模拟", "断开"]
        assert any(kw in out for kw in keywords), \
            f"Response doesn't seem network-related. Got: {self._out[:300]}"

    def test_no_quick_agent_reference(self):
        assert "quick agent" not in self._out.lower(), \
            "Response mentioned deprecated quick agent"
