"""ARCH-22 A: ``olav refresh`` sweeps ``*.disabled`` residue from workspaces.

When a vendored workspace tool is retired, the source file is deleted from
``src/olav/data/workspace/`` but existing user deployments keep a renamed
``<tool>.disabled`` copy. The refresh command now removes those so
deployments stay aligned with the current release.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REFRESH_PATH = REPO / "src" / "olav" / "cli" / "commands" / "refresh.py"


def _load_refresh_module():
    spec = importlib.util.spec_from_file_location("refresh_command_for_test", REFRESH_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


refresh_mod = _load_refresh_module()
_cleanup_disabled_files = refresh_mod._cleanup_disabled_files
refresh_workspace = refresh_mod.refresh_workspace


def _make_agent(dir_path: Path, name: str) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "AGENT.md").write_text(
        f"---\nname: {name}\ndescription: test agent\nkind: Agent\n---\n# {name}\n",
        encoding="utf-8",
    )


def test_cleanup_removes_top_level_disabled(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    (workspace / "foo.disabled").write_text("stale", encoding="utf-8")

    removed = _cleanup_disabled_files(workspace)

    assert removed == [Path("foo.disabled")]
    assert not (workspace / "foo.disabled").exists()


def test_cleanup_is_recursive(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "core" / "scripts").mkdir(parents=True)
    (workspace / "core" / "scripts" / "old_tool.py.disabled").write_text("x", encoding="utf-8")
    (workspace / "ops" / "nested" / "deep").mkdir(parents=True)
    (workspace / "ops" / "nested" / "deep" / "gone.disabled").write_text("y", encoding="utf-8")

    removed = sorted(_cleanup_disabled_files(workspace))

    assert removed == [
        Path("core/scripts/old_tool.py.disabled"),
        Path("ops/nested/deep/gone.disabled"),
    ]
    # Both should be gone and no other files affected.
    assert list(workspace.rglob("*.disabled")) == []


def test_cleanup_is_noop_when_clean(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert _cleanup_disabled_files(workspace) == []


def test_cleanup_preserves_non_disabled_files(tmp_path):
    workspace = tmp_path / "workspace"
    tools = workspace / "core" / "scripts"
    tools.mkdir(parents=True)

    keep = tools / "keep.py"
    keep.write_text("# real tool", encoding="utf-8")
    (tools / "stale.disabled").write_text("", encoding="utf-8")

    _cleanup_disabled_files(workspace)

    assert keep.exists()
    assert keep.read_text(encoding="utf-8") == "# real tool"
    assert not (tools / "stale.disabled").exists()


def test_refresh_invokes_cleanup(tmp_path):
    workspace = tmp_path / "workspace"
    _make_agent(workspace / "core", "core")
    (workspace / "core" / "stale.disabled").write_text("", encoding="utf-8")

    summary = refresh_workspace(workspace)

    assert not (workspace / "core" / "stale.disabled").exists()
    # Summary must advertise the cleanup so operators notice it in logs.
    assert "cleaned 1 stale .disabled file" in summary
