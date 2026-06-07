"""Unit tests for command_learner/tools/analyze_structure (R71b)."""
from __future__ import annotations

import sys
from pathlib import Path

_SKILL_TOOLS = Path(__file__).resolve().parents[1] / ".olav/workspace/command_learner/tools"
sys.path.insert(0, str(_SKILL_TOOLS))

from analyze_structure import analyze_structure, render_hints  # noqa: E402


class TestEmptyInput:
    def test_empty_string(self):
        s = analyze_structure("")
        assert s["line_count"] == 0
        assert s["non_blank_line_count"] == 0
        assert s["blank_line_blocks"] == 0
        assert s["has_aligned_columns"] is False


class TestAlignedTable:
    def test_bgp_summary_table(self):
        raw = (
            "Neighbor    V    AS MsgRcvd MsgSent\n"
            "10.0.0.1    4 65000     10      10\n"
            "10.0.0.2    4 65001     20      20\n"
            "10.0.0.3    4 65002     30      30\n"
        )
        s = analyze_structure(raw)
        assert s["has_aligned_columns"] is True
        assert s["line_count"] == 4
        assert s["non_blank_line_count"] == 4


class TestBlockStructure:
    def test_junos_peer_blocks(self):
        raw = (
            "Peer: 10.0.0.1 AS 65000\n"
            "  Type: External  State: Established\n"
            "  Flags: <Sync>\n"
            "\n"
            "Peer: 10.0.0.2 AS 65001\n"
            "  Type: External  State: Established\n"
        )
        s = analyze_structure(raw)
        assert s["blank_line_blocks"] >= 2
        assert s["indented_continuation"] >= 2


class TestKeyValueIndented:
    def test_kv_rows(self):
        raw = (
            "Version info:\n"
            "  Version: 18.4R3\n"
            "  Compiled: 2020-12-01\n"
            "  Model: vSRX\n"
            "  Hostname: R1\n"
            "  Serial: JUNOS123\n"
        )
        s = analyze_structure(raw)
        assert s["has_key_value_indented"] is True


class TestErrorDetection:
    def test_invalid_input(self):
        s = analyze_structure("% Invalid input detected at '^' marker.\n")
        assert s["looks_like_error"] is True

    def test_normal_output_not_error(self):
        s = analyze_structure("Interface status report follows\nEth0 up\nEth1 down\n")
        assert s["looks_like_error"] is False


class TestConfigDetection:
    def test_running_config_looks_like_config(self):
        lines = ["!"]
        lines += [f"interface GigabitEthernet0/{i}" for i in range(6)]
        lines += ["!", "router bgp 65000", "!", "hostname R1"]
        s = analyze_structure("\n".join(lines) + "\n")
        assert s["looks_like_config"] is True

    def test_show_version_not_config(self):
        raw = "Cisco IOS Software, Version 15.5\nProcessor: Cortex\n"
        s = analyze_structure(raw)
        assert s["looks_like_config"] is False


class TestRenderHints:
    def test_aligned_table_hint(self):
        s = analyze_structure("a b c\n1 2 3\n4 5 6\n7 8 9\n")
        out = render_hints(s)
        assert "aligned-column table" in out

    def test_block_hint(self):
        raw = "block1 line\n\nblock2 line\n\nblock3 line\n"
        s = analyze_structure(raw)
        out = render_hints(s)
        assert "blocks" in out.lower()

    def test_no_signal_returns_neutral(self):
        s = analyze_structure("single line\n")
        out = render_hints(s)
        # Either "no strong structural signal" or minimal fact-only output
        assert "lines" in out or "no strong" in out
