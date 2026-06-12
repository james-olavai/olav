"""P-DISCOVER — three-tier platform discovery.

Tier 1: TextFSM match on show_version → vendor / model / os_version
Tier 2: TextFSM match on show_platform / show_inventory / show_chassis
Tier 3: no template matches → confidence='unknown' + sample_file for LLM
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ── Tier 1 helpers ────────────────────────────────────────────────────


def _make_host_dir(tmp_path, files: dict[str, str]) -> Path:
    """Create a single-host bundle directory with the given files."""
    host_dir = tmp_path / "devices" / "R1"
    host_dir.mkdir(parents=True)
    for name, body in files.items():
        (host_dir / name).write_text(body, encoding="utf-8")
    return host_dir


_CISCO_IOS_SV = """\
Cisco IOS Software, C3560 Software (C3560-IPBASEK9-M), Version 12.2(55)SE10, RELEASE SOFTWARE (fc2)
Technical Support: http://www.cisco.com/techsupport
Copyright (c) 1986-2015 by Cisco Systems, Inc.
Compiled Wed 10-Jun-15 15:43 by prod_rel_team

ROM: Bootstrap program is C3560 boot loader
BOOTLDR: C3560 Boot Loader (C3560-HBOOT-M) Version 12.2(53r)SE2, RELEASE SOFTWARE (fc1)

R1 uptime is 1 year, 2 weeks, 3 days, 4 hours, 5 minutes
System returned to ROM by power-on
System restarted at 12:34:56 UTC Mon Jan 1 2024
System image file is "flash:/c3560-ipbasek9-mz.122-55.SE10.bin"
Last reload reason: power-on

cisco WS-C3560-24PS (PowerPC405) processor (revision A0) with 65536K bytes of memory.
Processor board ID FOC1234ABCD
Last reset from power-on
1 Virtual Ethernet interface
24 FastEthernet interfaces
2 Gigabit Ethernet interfaces
The password-recovery mechanism is enabled.

512K bytes of flash-simulated non-volatile configuration memory.
Base ethernet MAC Address       : 00:11:22:33:44:55
Motherboard assembly number     : 73-10218-09
Power supply part number        : 341-0107-04
Motherboard serial number       : FOC1234ABCD
Power supply serial number      : LIT1234ABCD
Model revision number           : A0
Motherboard revision number     : A0
Model number                    : WS-C3560-24PS-S
System serial number            : FOC1234ABCD
Top Assembly Part Number        : 800-25861-04
Top Assembly Revision Number    : A0
Version ID                      : V03
CLEI Code Number                : COMOH00ARB
Hardware Board Revision Number  : 0x01

Switch Ports Model              SW Version            SW Image
------ ----- -----              ----------            ----------
*    1 26    WS-C3560-24PS      12.2(55)SE10          C3560-IPBASEK9-M


Configuration register is 0xF
"""


_JUNOS_SV = """\
Hostname: R1
Model: vmx
Junos: 21.4R1.12
JUNOS OS Kernel 64-bit  XEN [20220115.094901_builder_stable_11]
JUNOS OS libs [20220115.094901_builder_stable_11]
JUNOS OS runtime [20220115.094901_builder_stable_11]
JUNOS network stack and utilities [20220115.211213_builder_junos_214_r1]
JUNOS libs [20220115.211213_builder_junos_214_r1]
"""


_ARISTA_SV = """\
Arista DCS-7280SR2-48YC6-F
Hardware version: 11.03
Serial number: JPE17141234
System MAC address: 444c.a8ff.aaaa

Software image version: 4.21.5F
Architecture: i686
Internal build version: 4.21.5F-15633977.4215F
Internal build ID: 4.21.5F-15633977.4215F

Uptime: 1 week, 2 days, 3 hours and 4 minutes
Total memory: 16385464 kB
Free memory: 11000000 kB
"""


# ── Tier 0 tests ──────────────────────────────────────────────────────


class TestTier0FilenameSignature:
    """Vendor-unique safe-command filenames classify without TextFSM parse."""

    def test_wlc_wireless_mobility_summary_matches_cisco_ios(self, tmp_path):
        """The case that triggered Tier 0 — IOS-XE WLC has show_wireless_*
        but no show_version captured.  Tier 1+2 used to miss this."""
        from olav.core.ingest.platform_discovery import discover_platform
        host = _make_host_dir(tmp_path, {
            "show_wireless_mobility_summary.txt": "Mobility Summary\n",
            "show_inventory.txt": "PID: C9800-40-K9\n",
            "show_running-config.txt": "hostname WLC\n!\n",
        })
        r = discover_platform(host)
        assert r.platform == "cisco_ios"
        assert r.vendor == "Cisco"
        assert r.confidence == "filename-signature"
        # Tier 0 doesn't extract model — that's the caller's job via parsed_outputs.
        assert r.model is None

    def test_junos_chassis_hardware_matches(self, tmp_path):
        from olav.core.ingest.platform_discovery import discover_platform
        host = _make_host_dir(tmp_path, {
            "show_chassis_hardware.txt": "Hardware inventory:\n",
        })
        r = discover_platform(host)
        assert r.platform == "juniper_junos"
        assert r.confidence == "filename-signature"

    def test_nxos_feature_matches(self, tmp_path):
        from olav.core.ingest.platform_discovery import discover_platform
        host = _make_host_dir(tmp_path, {"show_feature.txt": "feature lacp ON\n"})
        r = discover_platform(host)
        assert r.platform == "cisco_nxos"
        assert r.confidence == "filename-signature"

    def test_huawei_display_version_matches(self, tmp_path):
        from olav.core.ingest.platform_discovery import discover_platform
        host = _make_host_dir(tmp_path, {
            "display_version.txt": "Huawei Versatile Routing Platform Software\n",
        })
        r = discover_platform(host)
        assert r.platform == "huawei_vrp"
        assert r.confidence == "filename-signature"

    def test_no_unique_signal_falls_through_to_tier1(self, tmp_path):
        """When the bundle only has generic commands (show version /
        running-config / inventory), Tier 0 should not fire — Tier 1
        TextFSM parse is responsible for disambiguation."""
        from olav.core.ingest.platform_discovery import discover_platform
        host = _make_host_dir(tmp_path, {
            "show_version.txt": _CISCO_IOS_SV,
            "show_inventory.txt": "PID: C9300-48UXM\n",
        })
        r = discover_platform(host)
        # Tier 1 succeeds → confidence is the TextFSM one, NOT filename-signature
        assert r.platform == "cisco_ios"
        assert r.confidence == "textfsm-show-version"


# ── Tier 1 tests ──────────────────────────────────────────────────────


class TestTier1ShowVersion:
    def test_cisco_ios_classified(self, tmp_path):
        from olav.core.ingest.platform_discovery import discover_platform
        host = _make_host_dir(tmp_path, {"show_version.txt": _CISCO_IOS_SV})
        r = discover_platform(host)
        assert r.platform == "cisco_ios"
        assert r.vendor == "Cisco"
        assert r.confidence == "textfsm-show-version"
        # Sample file is the one that matched.
        assert r.sample_file and r.sample_file.name == "show_version.txt"

    def test_junos_classified(self, tmp_path):
        from olav.core.ingest.platform_discovery import discover_platform
        host = _make_host_dir(tmp_path, {"show_version.txt": _JUNOS_SV})
        r = discover_platform(host)
        assert r.platform == "juniper_junos"
        assert r.vendor == "Juniper"
        assert r.confidence == "textfsm-show-version"

    def test_arista_classified(self, tmp_path):
        from olav.core.ingest.platform_discovery import discover_platform
        host = _make_host_dir(tmp_path, {"show_version.txt": _ARISTA_SV})
        r = discover_platform(host)
        assert r.platform == "arista_eos"
        assert r.vendor == "Arista"
        assert r.confidence == "textfsm-show-version"

    def test_model_extracted(self, tmp_path):
        from olav.core.ingest.platform_discovery import discover_platform
        host = _make_host_dir(tmp_path, {"show_version.txt": _JUNOS_SV})
        r = discover_platform(host)
        assert r.model == "vmx"
        assert r.os_version == "21.4R1.12"

    def test_olav_header_stripped_before_parse(self, tmp_path):
        """The 2-line OLAV header MUST be stripped before TextFSM sees it,
        else the regex anchors miss the real first line."""
        from olav.core.ingest.platform_discovery import discover_platform
        body_with_header = (
            "# command: show version\n"
            "# collected_at: 2026-05-15T11:08:42Z\n"
            "# pre_scrubbed: false\n"
            "\n"
            f"{_CISCO_IOS_SV}"
        )
        host = _make_host_dir(tmp_path, {"show_version.txt": body_with_header})
        r = discover_platform(host)
        assert r.platform == "cisco_ios", "TextFSM should parse despite the header"


# ── Tier 2 tests ──────────────────────────────────────────────────────


class TestTier2Fallback:
    def test_show_inventory_used_when_no_show_version(self, tmp_path):
        """When show_version is missing, fall through to show_inventory."""
        from olav.core.ingest.platform_discovery import discover_platform
        inv = """\
NAME: "1", DESCR: "WS-C3850-48P"
PID: WS-C3850-48P     , VID: V03  , SN: FOC1234ABCD
"""
        host = _make_host_dir(tmp_path, {"show_inventory.txt": inv})
        r = discover_platform(host)
        # ntc-templates ships cisco_ios_show_inventory.textfsm — should match.
        assert r.platform == "cisco_ios"
        assert r.confidence == "textfsm-show-platform"
        assert r.sample_file and r.sample_file.name == "show_inventory.txt"

    def test_unparseable_show_version_falls_through_to_tier3(self, tmp_path):
        """If show_version is present but unparseable by any candidate,
        and no Tier 2 file exists, drop to unknown."""
        from olav.core.ingest.platform_discovery import discover_platform
        host = _make_host_dir(tmp_path, {
            "show_version.txt": "random gibberish that no template will match\n",
            "show_running-config.txt": "hostname R1\n!\nversion 15.2\n",
        })
        r = discover_platform(host)
        assert r.confidence == "unknown"
        # sample_file points at running-config (banner-richest pick).
        assert r.sample_file and "running-config" in r.sample_file.name


# ── Tier 3 tests ──────────────────────────────────────────────────────


class TestTier3UnknownSamplePath:
    def test_only_running_config_yields_sample_file(self, tmp_path):
        """A bundle with only running-config + interfaces should hand a
        sample file path to the caller so the LLM can classify."""
        from olav.core.ingest.platform_discovery import discover_platform
        host = _make_host_dir(tmp_path, {
            "show_running-config.txt": "hostname R1\n!\nversion 15.2\n",
            "show_interfaces.txt": "GigabitEthernet0/1 is up, line protocol is up\n",
        })
        r = discover_platform(host)
        assert r.confidence == "unknown"
        assert r.platform is None
        assert r.sample_file and r.sample_file.name == "show_running-config.txt"
        assert r.sample_command == "show running-config"

    def test_only_show_logging_falls_through(self, tmp_path):
        from olav.core.ingest.platform_discovery import discover_platform
        host = _make_host_dir(tmp_path, {"show_logging.txt": "Jul 1 R1: foo\n"})
        r = discover_platform(host)
        assert r.confidence == "unknown"
        assert r.sample_file and r.sample_file.name == "show_logging.txt"

    def test_empty_host_dir_returns_unknown_no_sample(self, tmp_path):
        from olav.core.ingest.platform_discovery import discover_platform
        host = tmp_path / "devices" / "R-EMPTY"
        host.mkdir(parents=True)
        r = discover_platform(host)
        assert r.confidence == "unknown"
        assert r.sample_file is None
        assert r.sample_command is None

    def test_nonexistent_dir_returns_unknown(self, tmp_path):
        from olav.core.ingest.platform_discovery import discover_platform
        r = discover_platform(tmp_path / "no-such-host")
        assert r.confidence == "unknown"
        assert r.platform is None


# ── End-to-end against the captured inbox fixture ─────────────────────


class TestAgainstRealCapture:
    """Sanity — at least one real device from the inbox fixture should
    classify cleanly via Tier 1."""

    def test_inbox_smoke_fixture_classifies(self, tmp_path):
        from olav.core.ingest.platform_discovery import discover_platform
        # Reuse a known host from the smoke fixture.
        host = Path("/tmp/inbox_smoke2/devices/QS4-12S1-R1-EDGE.net.vu.edu.au")
        if not host.is_dir():
            pytest.skip("smoke2 fixture absent — run scripts/build_bundle_from_inbox_tarball.py first")
        r = discover_platform(host)
        assert r.platform == "cisco_ios"
        assert r.vendor == "Cisco"
        # IOS-XE devices (Catalyst 9k) have a model code starting with C9300.
        assert r.model and r.model.startswith("C9300")
