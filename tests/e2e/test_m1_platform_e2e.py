"""M1 Platform (C-L1) E2E tests.

Tests core platform CLI commands via real subprocess calls.
All tests are always-run (no LLM, no external services required).

Always-run:
  C-L1-01 — olav version → output contains version string matching installed package
  C-L1-02 — olav list → returns at least one agent name
  C-L1-03 — olav --help → exits 0 and lists subcommands
  C-L1-04 — olav refresh → outputs N agents registered + exit 0

Usage:
    uv run pytest tests/e2e/test_m1_platform_e2e.py -v
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import importlib.metadata

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PYTHON = sys.executable
_CURRENT_VERSION = importlib.metadata.version("olav")


def _run(*args, timeout=60):
    """Run `python -m olav.cli.main <args>` and return (rc, stdout, stderr)."""
    r = subprocess.run(
        [_PYTHON, "-m", "olav.cli.main", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(_ROOT),
    )
    return r.returncode, r.stdout, r.stderr


# ---------------------------------------------------------------------------
# C-L1-01 — olav version prints version string
# ---------------------------------------------------------------------------


class TestPlatformVersion:
    """C-L1-01: `olav version` outputs the current version number."""

    @pytest.fixture(scope="class", autouse=True)
    def result(self, request):
        rc, out, err = _run("version")
        request.cls._rc = rc
        request.cls._out = out + err

    def test_exits_zero(self):
        assert self._rc == 0, f"olav version exited {self._rc}"

    def test_version_string_present(self):
        """Version line must contain the current installed version."""
        assert _CURRENT_VERSION in self._out, (
            f"Expected '{_CURRENT_VERSION}' in version output, got:\n{self._out[:400]}"
        )

    def test_olav_branding_present(self):
        """Output must mention OLAV."""
        assert "OLAV" in self._out.upper(), (
            f"Expected 'OLAV' branding in version output, got:\n{self._out[:400]}"
        )


# ---------------------------------------------------------------------------
# C-L1-02 — olav list returns agent entries
# ---------------------------------------------------------------------------


class TestPlatformList:
    """C-L1-02: `olav list` outputs at least one agent."""

    @pytest.fixture(scope="class", autouse=True)
    def result(self, request):
        rc, out, err = _run("list")
        request.cls._rc = rc
        request.cls._out = out + err

    def test_exits_zero(self):
        assert self._rc == 0, f"olav list exited {self._rc}"

    def test_at_least_one_agent(self):
        """At least one agent (e.g. 'core') must appear in the output."""
        combined = self._out.lower()
        assert any(
            kw in combined for kw in ["core", "audit", "ops", "agent", "•", "location"]
        ), f"olav list produced no agent info:\n{self._out[:600]}"

    def test_available_agents_header(self):
        """Output should contain 'Agent' keyword."""
        assert "agent" in self._out.lower() or "available" in self._out.lower(), (
            f"Expected agent listing header, got:\n{self._out[:400]}"
        )


# ---------------------------------------------------------------------------
# C-L1-03 — olav --help exits 0 and lists subcommands
# ---------------------------------------------------------------------------


class TestPlatformHelp:
    """C-L1-03: `olav --help` exits 0 and includes known subcommands."""

    @pytest.fixture(scope="class", autouse=True)
    def result(self, request):
        rc, out, err = _run("--help")
        request.cls._rc = rc
        request.cls._out = out + err

    def test_exits_zero(self):
        assert self._rc == 0, f"olav --help exited {self._rc}"

    def test_known_subcommands_listed(self):
        """Core subcommands must appear in help output."""
        out = self._out
        for cmd in ("version", "list", "init", "refresh", "service", "kb"):
            assert cmd in out, f"Subcommand '{cmd}' missing from --help output"

    def test_usage_line_present(self):
        assert "usage:" in self._out.lower() or "olav" in self._out.lower(), (
            f"Expected usage line in help output, got:\n{self._out[:400]}"
        )


# ---------------------------------------------------------------------------
# C-L1-04 — olav refresh registers agents
# ---------------------------------------------------------------------------


class TestPlatformRefresh:
    """C-L1-04: `olav refresh` registers agents and updates PLATFORM.md."""

    @pytest.fixture(scope="class", autouse=True)
    def result(self, request):
        rc, out, err = _run("refresh", timeout=30)
        request.cls._rc = rc
        request.cls._out = out + err

    def test_exits_zero(self):
        assert self._rc == 0, f"olav refresh exited {self._rc}\nstderr: {self._out}"

    def test_agents_registered_message(self):
        """Output must mention agents registered."""
        out = self._out.lower()
        assert "agent" in out and "registered" in out, (
            f"Expected 'agents registered' in refresh output, got:\n{self._out[:400]}"
        )

    def test_nonzero_agent_count(self):
        """At least one agent must be registered."""
        import re

        m = re.search(r"(\d+)\s+agents?\s+registered", self._out, re.IGNORECASE)
        assert m, f"Could not find agent count in refresh output:\n{self._out[:400]}"
        count = int(m.group(1))
        assert count >= 1, f"Expected ≥1 agents registered, got {count}"
