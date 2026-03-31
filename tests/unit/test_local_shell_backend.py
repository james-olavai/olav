"""Tests for §sandbox: LocalShellBackend enabled in local mode.

When no --sandbox flag is given, create_olav_agent_with_backend must use
LocalShellBackend (which implements SandboxBackendProtocol and injects an
`execute` shell tool), not the bare FilesystemBackend.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_mock_agent():
    """Return a minimal mock that satisfies create_olav_agent_with_backend."""
    agent = MagicMock()
    agent.graph = MagicMock()
    agent.plugin_registry = MagicMock()
    agent.plugin_registry.get_callback_plugins.return_value = []
    return agent


class TestLocalShellBackendInLocalMode:
    def test_local_mode_uses_local_shell_backend(self, tmp_path, monkeypatch):
        """Without --sandbox, backend must be LocalShellBackend."""
        monkeypatch.chdir(tmp_path)

        with patch("olav.agents.agent.OLAVAgent", return_value=_make_mock_agent()):
            from olav.cli.main import create_olav_agent_with_backend
            _, backend = create_olav_agent_with_backend("quick", sandbox=None)

        from deepagents.backends import CompositeBackend, LocalShellBackend
        assert isinstance(backend, CompositeBackend)
        assert isinstance(backend.default, LocalShellBackend), (
            f"Local mode must use LocalShellBackend, got {type(backend.default).__name__}"
        )

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

    def test_local_shell_backend_root_dir_is_cwd(self, tmp_path, monkeypatch):
        """LocalShellBackend root_dir must be the current working directory."""
        monkeypatch.chdir(tmp_path)

        with patch("olav.agents.agent.OLAVAgent", return_value=_make_mock_agent()):
            from olav.cli.main import create_olav_agent_with_backend
            _, backend = create_olav_agent_with_backend("quick", sandbox=None)

        from deepagents.backends import LocalShellBackend, CompositeBackend
        assert isinstance(backend.default, LocalShellBackend)
        # root_dir is stored as 'cwd' on the backend
        root = getattr(backend.default, "root_dir", None) or getattr(backend.default, "cwd", None)
        assert root is not None
        assert Path(root).resolve() == tmp_path.resolve()
