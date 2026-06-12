"""Tests for §sandbox: LocalShellBackend enabled in local mode.

When no --sandbox flag is given, create_olav_agent_with_backend must return
a LocalShellBackend directly (NOT wrapped in CompositeBackend) so that
deepagents recognises it as a SandboxBackendProtocol and injects `execute`.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_mock_agent():
    agent = MagicMock()
    agent.graph = MagicMock()
    agent.plugin_registry = MagicMock()
    agent.plugin_registry.get_callback_plugins.return_value = []
    return agent


class TestLocalShellBackendInLocalMode:
    def test_local_mode_returns_local_shell_backend(self, tmp_path, monkeypatch):
        """Without --sandbox, returned backend must be LocalShellBackend."""
        monkeypatch.chdir(tmp_path)

        with patch("olav.agents.agent.OLAVAgent", return_value=_make_mock_agent()):
            from olav.cli.main import create_olav_agent_with_backend
            _, backend = create_olav_agent_with_backend("quick", sandbox=None)

        from deepagents.backends import LocalShellBackend
        assert isinstance(backend, LocalShellBackend), (
            f"Local mode must return LocalShellBackend directly, got {type(backend).__name__}"
        )

    def test_local_shell_backend_implements_sandbox_protocol(self, tmp_path, monkeypatch):
        """LocalShellBackend must implement SandboxBackendProtocol (provides execute tool)."""
        monkeypatch.chdir(tmp_path)

        with patch("olav.agents.agent.OLAVAgent", return_value=_make_mock_agent()):
            from olav.cli.main import create_olav_agent_with_backend
            _, backend = create_olav_agent_with_backend("quick", sandbox=None)

        from deepagents.backends import LocalShellBackend
        assert isinstance(backend, LocalShellBackend)
        # SandboxBackendProtocol requirement: must have execute()
        assert hasattr(backend, "execute"), "Backend must have execute() for shell tool injection"

    def test_explicit_sandbox_arg_overrides(self, tmp_path, monkeypatch):
        """An explicit sandbox arg still takes precedence over LocalShellBackend."""
        monkeypatch.chdir(tmp_path)
        custom_sandbox = MagicMock()

        with patch("olav.agents.agent.OLAVAgent", return_value=_make_mock_agent()):
            from olav.cli.main import create_olav_agent_with_backend
            _, backend = create_olav_agent_with_backend("quick", sandbox=custom_sandbox)

        from deepagents.backends import CompositeBackend
        assert isinstance(backend, CompositeBackend)
        assert backend.default is custom_sandbox

    def test_local_shell_backend_cwd_is_project_root(self, tmp_path, monkeypatch):
        """LocalShellBackend must be rooted at the current working directory."""
        monkeypatch.chdir(tmp_path)

        with patch("olav.agents.agent.OLAVAgent", return_value=_make_mock_agent()):
            from olav.cli.main import create_olav_agent_with_backend
            _, backend = create_olav_agent_with_backend("quick", sandbox=None)

        from deepagents.backends import LocalShellBackend
        assert isinstance(backend, LocalShellBackend)
        root = getattr(backend, "root_dir", None) or getattr(backend, "cwd", None)
        assert root is not None
        assert Path(root).resolve() == tmp_path.resolve()
