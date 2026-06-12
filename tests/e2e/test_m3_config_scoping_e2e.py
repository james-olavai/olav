"""M3 config scoping E2E tests — real LLM agent validation.

Validates that after ISSUE-M3-OPS-CONFIG-NOT-SKILL-SCOPED fix, agents can
still correctly access their scoped config files from new locations:
  - ops/netops_init/config/: cron_schedules.yaml, backup_only_commands.yaml,
    discovery_commands.yaml
  - netops/collect/: command registry via search_commands tool

dev_docs/85 rename history:
  config agent → admin agent   (platform self-management)
  ops agent    → netops agent  (network domain)

These tests invoke real LLM agents to confirm end-to-end config path resolution.

Usage:
    uv run pytest tests/e2e/test_m3_config_scoping_e2e.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_OLAV_CMD = [sys.executable, "-m", "olav"]

_PROBE_E2E_ENABLED = os.environ.get("PROBE_E2E_ENABLED", "").strip() == "1"
pytestmark = pytest.mark.skipif(
    not _PROBE_E2E_ENABLED,
    reason="M3 config scoping E2E: set PROBE_E2E_ENABLED=1 and ensure LLM API key is present",
)


def _run_agent(
    agent: str, prompt: str, timeout: int = 120
) -> subprocess.CompletedProcess:
    """Run `olav --agent <agent> --auto-approve <prompt>` and return result."""
    return subprocess.run(
        _OLAV_CMD + ["--agent", agent, "--auto-approve", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=_ROOT,
    )


# ---------------------------------------------------------------------------
# Test 1 — admin agent can read cron_schedules.yaml from netops_init/config/
# ---------------------------------------------------------------------------


class TestAdminAgentCronAccess:
    """Admin agent can access cron_schedules.yaml from its M3 location.

    Verifies that after moving cron_schedules.yaml to
    ops/netops_init/config/cron_schedules.yaml, the admin agent (ops sub-agent)
    can still list the configured cron jobs (snapshot, trace_learner, audit_weekly).

    dev_docs/85: 'config' agent renamed to 'admin'.
    """

    def test_exits_zero(self):
        result = _run_agent("admin", "list the current cron job schedules")
        assert result.returncode == 0, (
            f"admin agent exited {result.returncode}:\n"
            f"stdout: {result.stdout[-600:]}\n"
            f"stderr: {result.stderr[-400:]}"
        )

    def test_response_mentions_cron_jobs(self):
        result = _run_agent("admin", "list the current cron job schedules")
        combined = result.stdout + result.stderr
        assert any(kw in combined.lower() for kw in ("snapshot", "cron", "schedule", "audit")), (
            f"Response does not mention any known cron jobs:\n{combined[:800]}"
        )


# ---------------------------------------------------------------------------
# Test 2 — netops agent command registry loads from collect/
# ---------------------------------------------------------------------------


class TestNetopsAgentCommandRegistry:
    """Netops agent can access command registry via search_commands tool.

    Verifies that after migrating command config from ops/probe/config/ to
    netops/collect/, the netops agent (collector sub-agent) can still
    return available commands for cisco_ios.

    dev_docs/85: 'ops' agent renamed to 'netops'.
    """

    def test_exits_zero(self):
        result = _run_agent("netops", "what CLI commands are available for cisco_ios devices?")
        assert result.returncode == 0, (
            f"netops agent exited {result.returncode}:\n"
            f"stdout: {result.stdout[-600:]}\n"
            f"stderr: {result.stderr[-400:]}"
        )

    def test_response_mentions_commands(self):
        result = _run_agent("netops", "what CLI commands are available for cisco_ios devices?")
        combined = result.stdout + result.stderr
        assert any(kw in combined.lower() for kw in ("show", "command", "cisco", "version", "interface")), (
            f"Response does not mention any CLI commands:\n{combined[:800]}"
        )


# ---------------------------------------------------------------------------
# Test 3 — netops agent can answer questions about backup commands
# ---------------------------------------------------------------------------


class TestNetopsAgentBackupCommandsAccess:
    """Netops agent can answer questions about backup command coverage.

    Verifies that after migrating backup_only_commands.yaml to
    ops/netops_init/config/backup_only_commands.yaml, the netops agent
    (via search_commands / olav_recall_memory) can still describe which commands
    are used for configuration backup/snapshot.

    dev_docs/85: 'config' agent renamed to 'admin'; backup command queries
    route to 'netops' which owns the collector and command registry.
    """

    def test_exits_zero(self):
        result = _run_agent(
            "netops", "which commands are used to collect configuration backups from network devices?"
        )
        assert result.returncode == 0, (
            f"netops agent exited {result.returncode}:\n"
            f"stdout: {result.stdout[-600:]}\n"
            f"stderr: {result.stderr[-400:]}"
        )

    def test_response_mentions_config_commands(self):
        result = _run_agent(
            "netops", "which commands are used to collect configuration backups from network devices?"
        )
        combined = result.stdout + result.stderr
        assert any(kw in combined.lower() for kw in ("running-config", "backup", "snapshot", "configuration", "show")), (
            f"Response does not mention backup/config commands:\n{combined[:800]}"
        )
