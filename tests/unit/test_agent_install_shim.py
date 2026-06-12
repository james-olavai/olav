"""
tests/unit/test_agent_install_shim.py
─────────────────────────────────────
Unit coverage for src/olav/cli/commands/agent_install.py — the v0.20.0
``olav agent install`` verb shim.

Guarantees:
  1. The shim is importable and exposes AgentInstallCommand.
  2. `execute("")` prints usage, doesn't error.
  3. `execute("install <args>")` forwards to SkillCommand.execute
     with ``install`` prefixed and args shell-quoted.
  4. Unknown sub-verbs return a usage string.

We stub SkillCommand so tests don't trigger the heavy installer path
(subprocess, pip install, workspace copy).
"""

from __future__ import annotations

import pytest


class _FakeSkillCommand:
    """Captures what the shim forwards so we can assert on it."""

    last_args: str | None = None

    async def execute(self, args: str = "") -> str:
        type(self).last_args = args
        return f"(forwarded: {args})"


@pytest.fixture(autouse=True)
def _stub_skill(monkeypatch: pytest.MonkeyPatch):
    """Replace olav.cli.commands.skill.SkillCommand with the fake."""
    import olav.cli.commands.skill as skill_mod

    monkeypatch.setattr(skill_mod, "SkillCommand", _FakeSkillCommand)
    _FakeSkillCommand.last_args = None


def test_agent_install_importable() -> None:
    from olav.cli.commands.agent_install import AgentInstallCommand

    cmd = AgentInstallCommand()
    assert cmd.name == "agent"


def test_empty_args_returns_usage() -> None:
    import asyncio

    from olav.cli.commands.agent_install import AgentInstallCommand

    result = asyncio.run(AgentInstallCommand().execute(""))
    assert "usage" in result.lower()
    # Usage message should mention both verbs — "agent" as the top
    # verb and "install" as the sub-verb — though not necessarily
    # adjacent.
    assert "agent" in result and "install" in result
    assert _FakeSkillCommand.last_args is None


def test_install_with_path_forwards_to_skillcommand() -> None:
    import asyncio

    from olav.cli.commands.agent_install import AgentInstallCommand

    result = asyncio.run(
        AgentInstallCommand().execute("install /path/to/olav-netops")
    )

    assert "forwarded:" in result
    assert _FakeSkillCommand.last_args == "install /path/to/olav-netops"


def test_install_quotes_paths_with_spaces() -> None:
    import asyncio

    from olav.cli.commands.agent_install import AgentInstallCommand

    result = asyncio.run(
        AgentInstallCommand().execute("install '/path/with spaces/pkg'")
    )

    assert "forwarded:" in result
    # SkillCommand should see the path as a single token even after
    # the shim re-joins and shell-quotes.
    import shlex

    reparsed = shlex.split(_FakeSkillCommand.last_args or "")
    assert reparsed == ["install", "/path/with spaces/pkg"]


def test_install_preserves_merge_into_flag() -> None:
    import asyncio

    from olav.cli.commands.agent_install import AgentInstallCommand

    asyncio.run(
        AgentInstallCommand().execute(
            "install /path/pkg --merge-into target-ws"
        )
    )

    import shlex

    reparsed = shlex.split(_FakeSkillCommand.last_args or "")
    assert reparsed == ["install", "/path/pkg", "--merge-into", "target-ws"]


def test_install_without_source_returns_usage() -> None:
    import asyncio

    from olav.cli.commands.agent_install import AgentInstallCommand

    result = asyncio.run(AgentInstallCommand().execute("install"))
    assert "usage" in result.lower()
    # Must NOT call SkillCommand with a dangerous empty argument.
    assert _FakeSkillCommand.last_args is None


def test_unknown_subverb_returns_error_and_usage() -> None:
    import asyncio

    from olav.cli.commands.agent_install import AgentInstallCommand

    result = asyncio.run(AgentInstallCommand().execute("uninstall"))
    assert "unknown agent action: uninstall" in result
    assert "usage" in result.lower()
    assert _FakeSkillCommand.last_args is None
