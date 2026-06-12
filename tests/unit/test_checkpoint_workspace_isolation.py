"""Tests for §11.4: checkpoint workspace isolation.

create_checkpointer(agent_id, workspace) must store checkpoints under
~/.olav/checkpoints/{user}/{workspace}/{agent_id}/checkpoints.duckdb
so two workspaces with the same agent name (e.g. "quick") don't collide.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch


class TestCreateCheckpointerWorkspaceIsolation:
    def test_workspace_param_included_in_path(self, tmp_path, monkeypatch):
        """Checkpoint path includes workspace segment when workspace is given."""
        monkeypatch.setenv("USER", "testuser")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        with patch("olav.core.checkpointer.AsyncDuckDBSaver") as mock_saver_cls:
            mock_saver_cls.return_value = MagicMock()
            import importlib
            import olav.core.checkpointer as cp_mod
            importlib.reload(cp_mod)

            cp_mod.create_checkpointer(agent_id="quick", workspace="netops")

        # The checkpoint dir should contain the workspace segment
        expected = tmp_path / ".olav" / "checkpoints" / "testuser" / "netops" / "quick"
        assert expected.exists(), f"Expected checkpoint dir {expected} to exist"

    def test_different_workspaces_get_different_paths(self, tmp_path, monkeypatch):
        """Two workspaces with same agent_id use separate checkpoint dirs."""
        monkeypatch.setenv("USER", "testuser")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        with patch("olav.core.checkpointer.AsyncDuckDBSaver") as mock_saver_cls:
            mock_saver_cls.return_value = MagicMock()
            import importlib
            import olav.core.checkpointer as cp_mod
            importlib.reload(cp_mod)

            cp_mod.create_checkpointer(agent_id="quick", workspace="netops")
            cp_mod.create_checkpointer(agent_id="quick", workspace="itsm")

        netops_dir = tmp_path / ".olav" / "checkpoints" / "testuser" / "netops" / "quick"
        itsm_dir = tmp_path / ".olav" / "checkpoints" / "testuser" / "itsm" / "quick"
        assert netops_dir.exists()
        assert itsm_dir.exists()
        assert netops_dir != itsm_dir

    def test_default_workspace_is_core(self, tmp_path, monkeypatch):
        """Without workspace param, defaults to 'core' (not flat path)."""
        monkeypatch.setenv("USER", "testuser")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        with patch("olav.core.checkpointer.AsyncDuckDBSaver") as mock_saver_cls:
            mock_saver_cls.return_value = MagicMock()
            import importlib
            import olav.core.checkpointer as cp_mod
            importlib.reload(cp_mod)

            cp_mod.create_checkpointer(agent_id="quick")

        # Default workspace = "core"
        expected = tmp_path / ".olav" / "checkpoints" / "testuser" / "core" / "quick"
        assert expected.exists(), f"Expected default workspace 'core' in path"

    def test_returns_saver_with_workspace(self, tmp_path, monkeypatch):
        """create_checkpointer returns non-None and creates the workspace checkpoint dir."""
        monkeypatch.setenv("USER", "testuser")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        with patch("olav.core.checkpointer.AsyncDuckDBSaver") as mock_saver_cls:
            mock_saver_cls.return_value = MagicMock()
            import importlib
            import olav.core.checkpointer as cp_mod
            importlib.reload(cp_mod)

            result = cp_mod.create_checkpointer(agent_id="ops", workspace="netops")

        assert result is not None
        expected = tmp_path / ".olav" / "checkpoints" / "testuser" / "netops" / "ops"
        assert expected.exists()
