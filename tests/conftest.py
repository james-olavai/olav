"""Shared test fixtures for OLAV v3.4 test suite.

Architecture under test:
- OLAVAgent: 1 orchestrator + 3 SubAgents (olav-ops, network-inspection, olav-config)
- SubAgents defined in .olav/OLAV.md frontmatter
- Tools loaded dynamically from .olav/workspace/*/tools/
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Project root
PROJECT_ROOT = Path(__file__).parent.parent


OLAV_BIN = str(PROJECT_ROOT / ".venv" / "bin" / "olav")


def run_olav(*args, timeout: int = 15, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run the installed `olav` binary from the project venv and return CompletedProcess.

    stdin is always set to DEVNULL so that rich.prompt.Confirm and other interactive
    prompts that guard on sys.stdin.isatty() will see a non-tty and use their defaults,
    preventing the process from blocking in CI or test environments.
    """
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [OLAV_BIN, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        cwd=str(PROJECT_ROOT),
        env=merged_env,
    )


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def olav_dir() -> Path:
    return PROJECT_ROOT / ".olav"


@pytest.fixture(scope="session")
def db_path() -> Path:
    return PROJECT_ROOT / ".olav" / "databases" / "main.duckdb"
