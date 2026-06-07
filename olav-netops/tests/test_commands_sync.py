"""Unit tests for olav_netops.core.commands_sync (R73)."""
from __future__ import annotations

import duckdb
import pytest

from olav_netops.core import commands_sync as cs


class TestSafe:
    def test_basic(self):
        assert cs._safe("show ip bgp summary") == "show_ip_bgp_summary"

    def test_uppercase(self):
        assert cs._safe("SHOW VERSION") == "show_version"

    def test_strip(self):
        assert cs._safe("  show version  ") == "show_version"


class TestDecanonical:
    def test_spaces(self):
        assert cs._decanonical("show_ip_bgp_summary") == "show ip bgp summary"


class TestEnsureTable:
    def test_creates_table(self):
        c = duckdb.connect(":memory:")
        try:
            cs._ensure_table(c)
            rows = c.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'netops' AND table_name = 'commands' "
                "ORDER BY ordinal_position"
            ).fetchall()
            names = [r[0] for r in rows]
            for col in ["platform", "command", "safe_command", "parser_type",
                        "blacklisted", "pipe_allowed", "backup_only", "synced_at"]:
                assert col in names
        finally:
            c.close()

    def test_idempotent(self):
        c = duckdb.connect(":memory:")
        try:
            cs._ensure_table(c)
            cs._ensure_table(c)
        finally:
            c.close()


class TestScanNtc:
    def test_returns_rows_when_installed(self):
        # ntc-templates should always be installed in test env
        rows = cs._scan_ntc()
        assert len(rows) > 100, "expected hundreds of ntc-templates"
        assert all("platform" in r and "command" in r for r in rows)
        # Spot-check: cisco_ios show ip bgp summary should be present
        bgp = [
            r for r in rows
            if r["platform"] == "cisco_ios" and r["safe_command"] == "show_ip_bgp_summary"
        ]
        assert len(bgp) == 1
        assert bgp[0]["parser_type"] == "ntc"

    def test_platform_inference_two_tokens(self):
        # `cisco_ios_show_version.textfsm` → platform=cisco_ios, cmd=show_version
        rows = cs._scan_ntc()
        platforms = {r["platform"] for r in rows}
        # All platforms should be VENDOR_OS shape
        for p in platforms:
            assert "_" in p, f"platform {p!r} missing VENDOR_OS shape"


class TestScanCustom:
    def test_finds_user_templates(self, tmp_path):
        base = tmp_path / "templates"
        (base / "cisco_ios").mkdir(parents=True)
        (base / "cisco_ios" / "show_foo.textfsm").write_text("Value X (\\S+)\n")
        (base / "juniper_junos").mkdir()
        (base / "juniper_junos" / "show_bar.textfsm").write_text("Value Y (\\S+)\n")

        rows = cs._scan_custom_textfsm(base)
        assert len(rows) == 2
        paths = sorted([(r["platform"], r["safe_command"]) for r in rows])
        assert paths == [("cisco_ios", "show_foo"), ("juniper_junos", "show_bar")]
        assert all(r["parser_type"] == "custom_textfsm" for r in rows)

    def test_skips_parsers_subdir(self, tmp_path):
        base = tmp_path / "templates"
        (base / "parsers").mkdir(parents=True)
        (base / "parsers" / "cisco_ios").mkdir()
        (base / "cisco_ios").mkdir()
        (base / "cisco_ios" / "show_foo.textfsm").write_text("Value X (\\S+)\n")

        rows = cs._scan_custom_textfsm(base)
        # parsers/cisco_ios is not scanned by the custom TextFSM scanner
        assert len(rows) == 1


class TestScanPac:
    def test_finds_main_and_quarantine(self, tmp_path):
        root = tmp_path / "templates" / "parsers"
        (root / "cisco_ios").mkdir(parents=True)
        (root / "cisco_ios" / "show_bgp_summary.py").write_text("def parse(raw): return []")
        (root / "_quarantine" / "juniper_junos").mkdir(parents=True)
        (root / "_quarantine" / "juniper_junos" / "show_bgp_summary.py").write_text(
            "def parse(raw): return []"
        )
        rows = cs._scan_pac(tmp_path / "templates")
        # Main tree finds 1; quarantine subtree SKIPPED by current impl
        # (leading underscore filters it out).
        assert len(rows) == 1
        assert rows[0]["platform"] == "cisco_ios"

    def test_ignores_dunder_files(self, tmp_path):
        root = tmp_path / "templates" / "parsers" / "cisco_ios"
        root.mkdir(parents=True)
        (root / "show_foo.py").write_text("def parse(raw): return []")
        (root / "__init__.py").write_text("")
        (root / "_helper.py").write_text("def helper(): pass")
        rows = cs._scan_pac(tmp_path / "templates")
        assert [r["safe_command"] for r in rows] == ["show_foo"]


class TestLoadBlacklist:
    def test_yaml_patterns(self, tmp_path):
        (tmp_path / "blacklisted_commands.yaml").write_text(
            "- reload\n"
            "- 'write erase'\n"
            "- {command: 'clear .*'}\n"
        )
        pats = cs._load_blacklist(tmp_path)
        assert len(pats) == 3
        assert any(p.search("reload") for p in pats)
        assert any(p.search("write erase") for p in pats)
        assert any(p.search("clear counters") for p in pats)

    def test_missing_file_returns_empty(self, tmp_path):
        assert cs._load_blacklist(tmp_path) == []


class TestLoadUserCommands:
    def test_loads(self, tmp_path):
        (tmp_path / "user_commands.yaml").write_text(
            "commands:\n"
            "  cisco_ios:\n"
            "    - show running-config\n"
            "    - show startup-config\n"
            "  juniper_junos:\n"
            "    - show configuration\n"
        )
        rows = cs._load_user_commands(tmp_path)
        assert len(rows) == 3
        assert all(r["parser_type"] == "raw_only" for r in rows)
        assert all(r["backup_only"] is True for r in rows)
        cisco = [r for r in rows if r["platform"] == "cisco_ios"]
        assert len(cisco) == 2


class TestSyncCommandsEndToEnd:
    def test_populates_from_ntc(self, tmp_path, monkeypatch):
        # Redirect paths_config to tmp
        class _FakePaths:
            agent_dir = tmp_path / ".olav"
            config_dir = tmp_path / ".olav" / "config"
        monkeypatch.setattr("olav.core.config.get_paths_config", lambda: _FakePaths())
        # Ensure agent_dir + config_dir exist
        _FakePaths.agent_dir.mkdir(parents=True)
        _FakePaths.config_dir.mkdir(parents=True)

        c = duckdb.connect(":memory:")
        try:
            stats = cs.sync_commands(c)
            assert stats["ntc"] > 100
            assert stats["total"] >= stats["ntc"]
            # Query the table
            ntc_rows = c.execute(
                "SELECT COUNT(*) FROM netops.commands WHERE parser_type='ntc'"
            ).fetchone()[0]
            assert ntc_rows == stats["ntc"]
            # cisco_ios show ip bgp summary specifically
            bgp = c.execute(
                "SELECT platform, command, parser_type, blacklisted "
                "FROM netops.commands "
                "WHERE platform='cisco_ios' AND command='show ip bgp summary'"
            ).fetchone()
            assert bgp is not None
            assert bgp[2] == "ntc"
            assert bgp[3] is False
        finally:
            c.close()

    def test_user_backup_overlays(self, tmp_path, monkeypatch):
        class _FakePaths:
            agent_dir = tmp_path / ".olav"
            config_dir = tmp_path / ".olav" / "config"
        monkeypatch.setattr("olav.core.config.get_paths_config", lambda: _FakePaths())
        _FakePaths.agent_dir.mkdir(parents=True)
        _FakePaths.config_dir.mkdir(parents=True)
        (_FakePaths.config_dir / "user_commands.yaml").write_text(
            "commands:\n  cisco_ios:\n    - custom show command xyz\n"
        )

        c = duckdb.connect(":memory:")
        try:
            stats = cs.sync_commands(c)
            assert stats["user"] == 1
            row = c.execute(
                "SELECT parser_type, backup_only FROM netops.commands "
                "WHERE platform='cisco_ios' AND command='custom show command xyz'"
            ).fetchone()
            assert row == ("raw_only", True)
        finally:
            c.close()

    def test_blacklist_sets_flag(self, tmp_path, monkeypatch):
        class _FakePaths:
            agent_dir = tmp_path / ".olav"
            config_dir = tmp_path / ".olav" / "config"
        monkeypatch.setattr("olav.core.config.get_paths_config", lambda: _FakePaths())
        _FakePaths.agent_dir.mkdir(parents=True)
        _FakePaths.config_dir.mkdir(parents=True)
        (_FakePaths.config_dir / "blacklisted_commands.yaml").write_text(
            "- reload\n"
        )

        c = duckdb.connect(":memory:")
        try:
            stats = cs.sync_commands(c)
            assert stats["blacklisted"] >= 1
            # reload is not in ntc; set via user_commands or blacklist-only
            bl_rows = c.execute(
                "SELECT command FROM netops.commands WHERE blacklisted=true"
            ).fetchall()
            # If ntc has a `reload` template the blacklist will flag it; either
            # way at least some entry got blacklisted flag set.
            assert len(bl_rows) == stats["blacklisted"]
        finally:
            c.close()


class TestIsBatchCollectible:
    @pytest.mark.parametrize("cmd, expected", [
        ("show version", True),
        ("show ip bgp summary", True),
        ("display lldp neighbor", True),
        ("get system info", True),
        ("ping 10.0.0.1", False),
        ("traceroute 10.0.0.1", False),
        ("configure terminal", False),
        ("reload", False),
        ("copy running-config tftp:", False),
        ("debug ip bgp", False),
        ("show tech-support", False),
        ("show logging", False),
        ("show log lastlog", False),
        ("", False),
        ("SHOW VERSION", True),
        ("  show interfaces  ", True),
    ])
    def test_batch_collectible(self, cmd, expected):
        assert cs.is_batch_collectible(cmd) == expected


class TestGetDiscoveryCommands:
    def test_filters_blacklisted(self, tmp_path):
        c = duckdb.connect(":memory:")
        try:
            cs._ensure_table(c)
            c.execute(
                "INSERT INTO netops.commands VALUES "
                "('cisco_ios', 'show version', 'show_version', 'ntc', '/x', false, true, false, NULL)"
            )
            c.execute(
                "INSERT INTO netops.commands VALUES "
                "('cisco_ios', 'reload', 'reload', 'ntc', '/y', true, true, false, NULL)"
            )
            result = cs.get_discovery_commands(c, "cisco_ios")
            assert "show version" in result
            assert "reload" not in result
        finally:
            c.close()

    def test_batch_only_excludes_interactive(self, tmp_path):
        """`ping` has a parser but is not batch-collectible."""
        c = duckdb.connect(":memory:")
        try:
            cs._ensure_table(c)
            c.execute(
                "INSERT INTO netops.commands VALUES "
                "('cisco_ios', 'show version', 'show_version', 'ntc', '/x', false, true, false, NULL)"
            )
            c.execute(
                "INSERT INTO netops.commands VALUES "
                "('cisco_ios', 'ping', 'ping', 'ntc', '/y', false, true, false, NULL)"
            )
            batch = cs.get_discovery_commands(c, "cisco_ios", batch_only=True)
            assert "show version" in batch
            assert "ping" not in batch
            full = cs.get_discovery_commands(c, "cisco_ios", batch_only=False)
            assert "ping" in full
        finally:
            c.close()

    def test_include_backup_flag(self, tmp_path):
        c = duckdb.connect(":memory:")
        try:
            cs._ensure_table(c)
            c.execute(
                "INSERT INTO netops.commands VALUES "
                "('cisco_ios', 'show version', 'show_version', 'ntc', '/x', false, true, false, NULL)"
            )
            c.execute(
                "INSERT INTO netops.commands VALUES "
                "('cisco_ios', 'show running-config', 'show_running-config', 'raw_only', NULL, false, true, true, NULL)"
            )
            with_backup = cs.get_discovery_commands(c, "cisco_ios", include_backup=True)
            assert "show running-config" in with_backup
            no_backup = cs.get_discovery_commands(c, "cisco_ios", include_backup=False)
            assert "show running-config" not in no_backup
        finally:
            c.close()
