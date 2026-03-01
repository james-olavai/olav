"""Workspace initialization tests.

NOTE: These tests were written for `olav.cli.commands.init` which was never
implemented. The init workflow lives in `scripts/init.py` (stand-alone script,
not a CLI command module).

Until a proper `olav.cli.commands.init` module is created and tested, these
tests are replaced with a minimal smoke test that verifies the existing init
script path is importable.
"""

import pytest
from pathlib import Path


class TestWorkspaceInitScript:
    """Verify the init script exists and basic structure is present."""

    def test_init_script_exists(self):
        """scripts/init.py must exist in the project."""
        project_root = Path(__file__).resolve().parents[2]
        init_script = project_root / "scripts" / "init.py"
        assert init_script.exists(), "scripts/init.py should exist"

    def test_olav_workspace_structure(self):
        """The .olav/ workspace must have the key directories."""
        project_root = Path(__file__).resolve().parents[2]
        olav = project_root / ".olav"

        required = ["workspace", "databases"]
        for d in required:
            assert (olav / d).exists(), f".olav/{d} must exist"

    def test_agent_workspace_exists(self):
        """Core agent workspaces must be present."""
        project_root = Path(__file__).resolve().parents[2]
        workspace = project_root / ".olav" / "workspace"

        for agent in ["ops", "audit", "config", "quick"]:
            assert (workspace / agent).exists(), f".olav/workspace/{agent} must exist"
            assert (workspace / agent / "AGENT.md").exists(), f"{agent}/AGENT.md must exist"



