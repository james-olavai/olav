"""ARCH-08 Phase 2: tools scope SSH dispatch by ``environment`` tag.

Phase 1 (earlier round) tagged every Nornir host with
``data.environment``. Phase 2 makes execute_cli / take_snapshot consult
that tag so a lab-only caller can't accidentally hit prod hardware, and
``check_approval`` logs the env label in its reason string.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _disable_bypass_mode():
    """Ensure approval gate isn't short-circuited by prior tests that toggled
    --dangerously-skip-permissions. Tests in the same session pool may leave
    bypass mode on; reset it explicitly so approval logic actually runs."""
    try:
        from olav.platform.safety.permissions import set_bypass
        set_bypass(False)
    except Exception:
        pass


def test_check_approval_accepts_environment_kwarg():
    _disable_bypass_mode()
    from olav.platform.safety.approval import check_approval

    # Non-read-only command should trigger approval; env should appear in reason.
    result = check_approval(
        "no router bgp 65000", device="R1", environment="prod"
    )
    assert result.requires_approval is True
    assert "env=prod" in result.reason, (
        f"approval reason missing env marker: {result.reason!r}"
    )


def test_check_approval_without_environment_keeps_legacy_reason():
    _disable_bypass_mode()
    from olav.platform.safety.approval import check_approval

    result = check_approval("no router bgp 65000", device="R1")
    assert result.requires_approval is True
    assert "env=" not in result.reason


def test_check_approval_read_only_still_passes_with_env():
    from olav.platform.safety.approval import check_approval

    result = check_approval("show version", device="R1", environment="lab")
    assert result.requires_approval is False


def test_execute_cli_advertises_environment_param():
    """Source-level guard: the environment kwarg must appear in the tool signature."""
    src = (REPO / ".olav" / "workspace" / "netops" / "tools" / "execute_cli_parallel.py").read_text(
        encoding="utf-8"
    )
    assert "environment: str | None" in src
    assert "environment mismatch" in src


def test_take_snapshot_advertises_environment_param_and_skipped():
    src = (REPO / ".olav" / "workspace" / "netops" / "tools" / "take_snapshot.py").read_text(
        encoding="utf-8"
    )
    assert "environment: str | None" in src
    assert "skipped" in src
    assert "environment mismatch" in src


def test_take_snapshot_returns_skipped_on_mismatch(tmp_path, monkeypatch):
    """End-to-end: take_snapshot must drop hosts whose env tag differs."""
    pytest.importorskip("nornir")  # tool's module-level import requires Nornir

    path = REPO / ".olav" / "workspace" / "netops" / "tools" / "take_snapshot.py"
    spec = importlib.util.spec_from_file_location("take_snapshot_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Stub inventory with two hosts in different environments.
    class _Host:
        def __init__(self, name, env):
            self.name = name
            self.platform = "cisco_ios"
            self.data = {"environment": env}

    class _Inv:
        def __init__(self):
            self.hosts = {"R1": _Host("R1", "lab"), "R2": _Host("R2", "prod")}

    class _Nr:
        def __init__(self):
            self.inventory = _Inv()

    monkeypatch.setattr(mod, "_get_nornir", lambda: _Nr())

    # Short-circuit the network execution + DB writes to keep the test
    # pure; we only care about the filter logic.
    monkeypatch.setattr(
        mod,
        "_run_one",
        lambda dev, cmd, timeout, platform: {
            "status": "success", "device": dev, "command": cmd,
            "raw": "", "parsed": [],
        },
    )
    monkeypatch.setattr(mod, "_write_staging_json", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "_write_raw_file", lambda *a, **kw: None)

    # Force the auto-ingest branch to skip (IngestManager import would pull DB).
    tool_obj = mod.take_snapshot
    invoker = tool_obj.invoke if hasattr(tool_obj, "invoke") else tool_obj
    args = {
        "devices": ["R1", "R2"],
        "commands": ["show version"],
        "timeout": 5,
        "max_workers": 1,
        "environment": "lab",
    }
    result = invoker(args) if hasattr(tool_obj, "invoke") else invoker(**args)

    skipped = result.get("skipped", [])
    assert len(skipped) == 1, f"expected 1 skipped host, got {skipped}"
    assert skipped[0]["device"] == "R2"
    assert "environment mismatch" in skipped[0]["reason"]
    # R1 (lab) should have proceeded — total_tasks = 1 device × 1 command.
    assert result.get("total_tasks") == 1
