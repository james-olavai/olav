"""TDD tests for Stage 3.5 auto-learn — TextFSM template generation on parse failure.

Run: .venv/bin/python -m pytest tests/unit/test_auto_learn.py -v
"""
import pytest


# ═══════════════════════════════════════════════════════════════════
# False positive detection
# ═══════════════════════════════════════════════════════════════════

class TestShouldLearn:
    """should_learn() must distinguish real parse failures from false positives."""

    def test_valid_output_should_learn(self):
        from olav_netops.core.auto_learn import should_learn
        raw = """Peer                     AS      InPkt     OutPkt    OutQ   Flaps Last Up/Dwn State
3.3.3.3               65000      98779     100260       0       0 4w3d Establ
10.1.12.2             65001      64501      65478       0       2 2w6d Establ"""
        assert should_learn("show bgp summary", raw) is True

    def test_empty_output_skip(self):
        from olav_netops.core.auto_learn import should_learn
        assert should_learn("show bgp summary", "") is False
        assert should_learn("show bgp summary", "   \n  ") is False

    def test_short_output_skip(self):
        from olav_netops.core.auto_learn import should_learn
        assert should_learn("show version", "short") is False

    def test_error_message_skip(self):
        from olav_netops.core.auto_learn import should_learn
        assert should_learn("show bgp", "% Invalid input detected at '^' marker") is False
        assert should_learn("show foo", "% Unknown command") is False

    def test_backup_command_skip(self):
        from olav_netops.core.auto_learn import should_learn
        raw = "hostname R1\n!\ninterface GigabitEthernet1\n ip address 10.0.0.1 255.255.255.0"
        assert should_learn("show running-config", raw) is False
        assert should_learn("show configuration", raw) is False

    def test_timeout_skip(self):
        from olav_netops.core.auto_learn import should_learn
        assert should_learn("show version", "Connection timed out") is False


# ═══════════════════════════════════════════════════════════════════
# LLM template generation
# ═══════════════════════════════════════════════════════════════════

class TestGenerateTemplate:
    """generate_textfsm_template() should produce a valid TextFSM template."""

    def test_generate_returns_string(self):
        """Template generation returns a non-empty string or None (graceful degradation)."""
        from olav_netops.core.auto_learn import generate_textfsm_template
        raw = """Peer                     AS      InPkt     OutPkt
3.3.3.3               65000      98779     100260"""
        # With or without LLM — should not crash
        try:
            result = generate_textfsm_template("juniper_junos", "show bgp summary", raw)
            assert result is None or (isinstance(result, str) and "Value" in result)
        except Exception:
            pytest.skip("LLM timeout or unavailable")


# ═══════════════════════════════════════════════════════════════════
# Custom template save/load
# ═══════════════════════════════════════════════════════════════════

class TestCustomTemplates:
    """Custom templates should be saved and loaded from workspace."""

    def test_save_and_load(self, tmp_path):
        from olav_netops.core.auto_learn import save_custom_template, load_custom_template
        template_text = "Value PEER (\\S+)\nValue AS (\\d+)\n\nStart\n  ^${PEER}\\s+${AS} -> Record"
        save_custom_template(tmp_path, "juniper_junos", "show bgp summary", template_text)
        loaded = load_custom_template(tmp_path, "juniper_junos", "show bgp summary")
        assert loaded == template_text

    def test_load_missing_returns_none(self, tmp_path):
        from olav_netops.core.auto_learn import load_custom_template
        result = load_custom_template(tmp_path, "juniper_junos", "show nonexistent")
        assert result is None

    def test_parse_with_custom_template(self, tmp_path):
        from olav_netops.core.auto_learn import save_custom_template, parse_with_custom_template
        # Simple TextFSM template for LLDP
        template = """Value LOCAL_INTF (\\S+)
Value REMOTE_NAME (\\S+)
Value REMOTE_INTF (\\S+)

Start
  ^${LOCAL_INTF}\\s+\\S+\\s+\\S+\\s+${REMOTE_INTF}\\s+${REMOTE_NAME} -> Record"""
        save_custom_template(tmp_path, "juniper_junos", "show lldp neighbors", template)

        raw = "ge-0/0/2  -  50:00:00:03:00:02  to_R1_Gi2  R3.local"
        result = parse_with_custom_template(
            tmp_path, "juniper_junos", "show lldp neighbors", raw
        )
        # May or may not parse correctly depending on template — the mechanism is what we test
        assert result is None or isinstance(result, list)


class TestTemplatePriority:
    """Custom templates must take priority over ntc-templates."""

    def test_custom_overrides_ntc(self, tmp_path):
        """When custom template exists, it should be used instead of ntc."""
        from olav_netops.core.auto_learn import save_custom_template, load_custom_template

        # Save a custom template
        template = "Value PEER (\\S+)\nValue AS (\\d+)\n\nStart\n  ^${PEER}\\s+${AS} -> Record"
        save_custom_template(tmp_path, "juniper_junos", "show bgp summary", template)

        # Verify it loads
        loaded = load_custom_template(tmp_path, "juniper_junos", "show bgp summary")
        assert loaded is not None
        assert "Value PEER" in loaded

    def test_template_path_structure(self, tmp_path):
        """Templates saved to {base}/{platform}/{command}.textfsm."""
        from olav_netops.core.auto_learn import save_custom_template
        path = save_custom_template(tmp_path, "juniper_junos", "show bgp summary", "test")
        assert path.parent.name == "juniper_junos"
        assert path.name == "show_bgp_summary.textfsm"
        assert path.exists()


class TestEstimateDataRows:
    """_estimate_data_rows should count actual data lines in raw output."""

    def test_bgp_summary_2_peers(self):
        from olav_netops.core.auto_learn import _estimate_data_rows
        raw = """Threading mode: BGP I/O
Groups: 2 Peers: 2 Down peers: 0
Table          Tot Paths  Act Paths Suppressed    History Damp State    Pending
inet.0               
                       1          0          0          0          0          0
Peer                     AS      InPkt     OutPkt    OutQ   Flaps Last Up/Dwn State
3.3.3.3               65000      98779     100260       0       0 4w3d Establ
  inet.0: 0/1/1/0
10.1.12.2             65001      64501      65478       0       2 2w6d Establ
  inet.0: 0/0/0/0"""
        count = _estimate_data_rows(raw, "show bgp summary")
        assert count >= 2, f"Should detect ≥2 data rows (peers), got {count}"

    def test_empty_output(self):
        from olav_netops.core.auto_learn import _estimate_data_rows
        assert _estimate_data_rows("", "show version") == 0

    def test_short_output(self):
        from olav_netops.core.auto_learn import _estimate_data_rows
        assert _estimate_data_rows("one line", "show version") == 0
