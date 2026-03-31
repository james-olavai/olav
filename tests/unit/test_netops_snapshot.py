"""Unit tests for run_snapshot() in olav-netops/scripts/netops_snapshot.py.

Contracts:
1. Returns 0 on successful snapshot (no parse errors)
2. Returns 0 on successful snapshot with parse errors but --repair not set
3. Returns 0 on successful snapshot with --repair and parse errors fixed
4. Returns 1 when collect_commands tool is not importable
5. run_snapshot is callable from the script (importable as a module)
6. Script __name__ guard prevents execution on import
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Import helper — netops_snapshot.py is a script (not a package module)
# ---------------------------------------------------------------------------


def _load_snapshot() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "olav-netops" / "scripts" / "netops_snapshot.py"
    spec = importlib.util.spec_from_file_location("netops_snapshot", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_snapshot_function_exists() -> None:
    """run_snapshot must be importable from netops_snapshot.py."""
    mod = _load_snapshot()
    assert hasattr(mod, "run_snapshot"), "run_snapshot not found in netops_snapshot.py"


def test_run_snapshot_returns_zero_on_success() -> None:
    """Returns 0 when collect_commands succeeds with no parse errors."""
    mod = _load_snapshot()

    fake_collect = MagicMock()
    fake_collect.func.return_value = {
        "snapshot_id": "snap-001",
        "devices": ["R1", "R2"],
        "parse_errors": [],
    }

    fake_agent_dir = MagicMock()
    fake_agent_dir.__truediv__ = lambda self, other: Path("/tmp") / other

    with patch.dict(
        sys.modules,
        {
            "olav.core.config": MagicMock(AGENT_DIR=Path("/tmp")),
            "collect_commands": MagicMock(collect_commands=fake_collect),
        },
    ):
        result = mod.run_snapshot(repair=False)

    assert result == 0


def test_run_snapshot_returns_zero_with_parse_errors_no_repair() -> None:
    """Returns 0 even with parse errors when repair=False."""
    mod = _load_snapshot()

    fake_collect = MagicMock()
    fake_collect.func.return_value = {
        "snapshot_id": "snap-002",
        "devices": ["R1"],
        "parse_errors": [{"sample_device": "R1", "command": "show version"}],
    }

    with patch.dict(
        sys.modules,
        {
            "olav.core.config": MagicMock(AGENT_DIR=Path("/tmp")),
            "collect_commands": MagicMock(collect_commands=fake_collect),
        },
    ):
        result = mod.run_snapshot(repair=False)

    assert result == 0


def test_run_snapshot_repair_calls_repair_template() -> None:
    """With repair=True and parse errors, calls repair_template for each gap."""
    mod = _load_snapshot()

    fake_collect = MagicMock()
    fake_collect.func.return_value = {
        "snapshot_id": "snap-003",
        "devices": ["R1"],
        "parse_errors": [
            {"sample_device": "R1", "command": "show version"},
            {"sample_device": "R1", "command": "show ip int brief"},
        ],
    }

    fake_repair = MagicMock()
    fake_repair.func.return_value = {"success": True}

    with patch.dict(
        sys.modules,
        {
            "olav.core.config": MagicMock(AGENT_DIR=Path("/tmp")),
            "collect_commands": MagicMock(collect_commands=fake_collect),
            "repair_template": MagicMock(repair_template=fake_repair),
        },
    ):
        result = mod.run_snapshot(repair=True)

    assert result == 0
    assert fake_repair.func.call_count == 2


def test_run_snapshot_returns_one_when_collect_commands_missing() -> None:
    """Returns 1 when collect_commands tool cannot be imported."""
    mod = _load_snapshot()

    # Remove collect_commands from sys.modules so the import inside run_snapshot fails
    modules_without_collect = {k: v for k, v in sys.modules.items() if "collect_commands" not in k}

    with patch.dict(
        sys.modules,
        {
            **modules_without_collect,
            "olav.core.config": MagicMock(AGENT_DIR=Path("/tmp")),
            "collect_commands": None,  # None causes ImportError on "from collect_commands import ..."
        },
        clear=False,
    ):
        # Patch builtins.__import__ to raise ImportError for collect_commands
        original_import = (
            __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
        )

        def _fake_import(name, *args, **kwargs):
            if name == "collect_commands":
                raise ImportError("collect_commands not found")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_fake_import):
            result = mod.run_snapshot(repair=False)

    assert result == 1
