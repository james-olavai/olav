"""Tests for olav_netops.cli.builtin.

Verifies argument parsing and edge cases for the /learn_cmd and
/netops_init slash commands.  No CLAB or real devices required.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


class TestCmdLearnArgParsing:
    """cmd_learn() is async; run via asyncio.run() (Python 3.12+ compatible)."""

    def test_empty_args_returns_usage(self):
        from olav_netops.cli.builtin import cmd_learn
        result = asyncio.run(cmd_learn(""))
        assert "Usage" in result or "usage" in result.lower() or "/learn_cmd" in result

    def test_missing_device_returns_error(self):
        from olav_netops.cli.builtin import cmd_learn
        result = asyncio.run(cmd_learn('"show version"'))
        assert "Device is required" in result or "device" in result.lower()

    def test_missing_command_returns_error(self):
        from olav_netops.cli.builtin import cmd_learn
        result = asyncio.run(cmd_learn("--device R1"))
        assert "Command is required" in result or "required" in result.lower()

    def test_invalid_timeout_returns_error(self):
        from olav_netops.cli.builtin import cmd_learn
        result = asyncio.run(cmd_learn('"show version" --device R1 --timeout notanumber'))
        assert "integer" in result.lower() or "timeout" in result.lower()

    def test_device_short_flag_accepted(self, monkeypatch):
        """--device and -d should both work. Mock the direct-call path
        (R71c: cmd_learn no longer delegates to agents — it captures
        raw via take_snapshot._run_one and calls learn_commands directly).
        """
        import sys
        import types

        # Stub `take_snapshot` module with a minimal _run_one.
        ts_stub = types.ModuleType("take_snapshot")
        def _fake_run_one(device, command, timeout, platform):
            return {"raw": "stub raw output", "platform": platform or "cisco_ios"}
        ts_stub._run_one = _fake_run_one
        monkeypatch.setitem(sys.modules, "take_snapshot", ts_stub)

        # Stub `learn_commands` with a success payload.
        lc_stub = types.ModuleType("learn_commands")
        class _FakeResult:
            newly_parsed = [{
                "device": "R1", "command": "show version",
                "parsed_data": [{"version": "15.5(3)M"}],
                "source": "test_stub",
            }]
            frozen = [{"dsl": "textfsm", "path": "/tmp/fake.textfsm"}]
            skipped = []
            failed = []
            elapsed_seconds = 0.05
        def _fake_learn(samples, **kw):
            return _FakeResult()
        lc_stub.learn_commands = _fake_learn
        monkeypatch.setitem(sys.modules, "learn_commands", lc_stub)

        from olav_netops.cli.builtin import cmd_learn
        result = asyncio.run(cmd_learn('"show version" -d R1'))

        # Direct-call path returned a Learned string.
        assert "Device is required" not in result
        assert "Learned" in result or "learned" in result.lower()


class TestNetopsInitMain:
    """netops_init_main() is sync."""

    def test_missing_script_returns_error(self, tmp_path, monkeypatch):
        """When netops_init.py is absent, a clear error is returned."""
        from olav_netops.cli.builtin import netops_init_main

        # Point the script lookup to a non-existent path by patching __file__
        import olav_netops.cli.builtin as mod
        fake_builtin = tmp_path / "cli" / "builtin.py"
        fake_builtin.parent.mkdir(parents=True)
        fake_builtin.write_text("")
        monkeypatch.setattr(mod, "__file__", str(fake_builtin))

        result = netops_init_main()
        assert "not found" in result.lower() or "❌" in result

    def test_dry_run_flag_passed_through(self, monkeypatch):
        """--dry-run arg is detected without crashing."""
        import importlib.util
        import types

        # Create a fake netops_init module
        fake_mod = types.ModuleType("_netops_init_script")
        fake_mod.run_init = lambda dry_run=False: 0  # type: ignore[attr-defined]

        from olav_netops.cli.builtin import netops_init_main
        import olav_netops.cli.builtin as mod_ref

        def fake_spec_from_file_location(name, path):
            spec = importlib.util.spec_from_loader(name, loader=None)
            return spec

        # Mock the script location and module loading
        import sys
        sys.modules["_netops_init_script"] = fake_mod

        # Patch parents[3] to point somewhere with scripts/netops_init.py
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            scripts_dir = Path(td) / "scripts"
            scripts_dir.mkdir()
            (scripts_dir / "netops_init.py").write_text(
                "def run_init(dry_run=False):\n    return 0\n"
            )
            import olav_netops.cli.builtin as _b
            monkeypatch.setattr(_b, "__file__", str(Path(td) / "src" / "olav_netops" / "cli" / "builtin.py"))
            # Ensure the path resolution works
            result = netops_init_main("--dry-run")
            assert "✅" in result or result.startswith("✅") or "completed" in result.lower()
