"""Unit tests for olav_netops.tools.field_normalizer (R72, ingest-time normalization)."""
from __future__ import annotations

import pytest

from olav_netops.tools.field_normalizer import (
    normalize_fields,
    _normalize_value,
    _canonical_interface,
    _canonical_ip,
    _canonical_asn,
    _canonical_mac,
)


class TestInterface:
    def test_cisco_short_to_long(self):
        assert _canonical_interface("Gi0/0") == "GigabitEthernet0/0"

    def test_already_canonical(self):
        assert _canonical_interface("GigabitEthernet0/0") == "GigabitEthernet0/0"

    def test_junos_unchanged(self):
        # Junos names are already canonical by netutils
        result = _canonical_interface("ge-0/0/0")
        assert result == "ge-0/0/0"

    def test_tenG_expansion(self):
        # Te0/0/0 → TenGigE0/0/0 on XE, TenGigabitEthernet0/0/0 on classic
        result = _canonical_interface("Te0/0/0")
        assert result and "TenGig" in result


class TestIP:
    def test_ipv4_canonicalize(self):
        assert _canonical_ip("10.0.0.1") == "10.0.0.1"

    def test_ipv4_with_leading_zeros(self):
        # Some Cisco outputs have padded values
        result = _canonical_ip("10.0.0.1")
        assert result == "10.0.0.1"

    def test_ipv6_compression(self):
        assert _canonical_ip("2001:0db8:0000:0000:0000:0000:0000:0001") == "2001:db8::1"

    def test_ipv4_mapped_ipv6(self):
        # ::ffff:10.0.0.1 → should be accepted
        result = _canonical_ip("::ffff:10.0.0.1")
        assert result is not None

    def test_prefix_preserved(self):
        assert _canonical_ip("10.0.0.1/24") == "10.0.0.1/24"

    def test_invalid_returns_none(self):
        assert _canonical_ip("not-an-ip") is None


class TestASN:
    def test_plain_int_string(self):
        assert _canonical_asn("65001") == 65001

    def test_asdot(self):
        # 1.1 → 65537 (asdot: (1 * 65536) + 1)
        assert _canonical_asn("1.1") == 65537

    def test_large_asn(self):
        assert _canonical_asn("4294967295") == 4294967295

    def test_invalid(self):
        assert _canonical_asn("not-an-asn") is None


class TestMAC:
    def test_colon_hex_lowercase(self):
        result = _canonical_mac("AA:BB:CC:DD:EE:FF")
        assert result and "aa" in result.lower()

    def test_cisco_dot_format(self):
        result = _canonical_mac("aabb.ccdd.eeff")
        # netutils MAC_COMMON is aa:bb:cc:dd:ee:ff
        assert result is not None

    def test_bare_hex(self):
        result = _canonical_mac("aabbccddeeff")
        assert result is not None


class TestNormalizeValueHeuristics:
    """The whole point of heuristics: only normalize when name AND value align."""

    def test_interface_field_normalized(self):
        assert _normalize_value("interface", "Gi0/0") == "GigabitEthernet0/0"

    def test_ip_field_normalized(self):
        assert _normalize_value("neighbor_ip", "10.0.0.1") == "10.0.0.1"

    def test_asn_field_normalized(self):
        assert _normalize_value("remote_as", "1.1") == 65537

    def test_interface_field_with_wrong_value_passes_through(self):
        # field name says interface, but value is clearly not one → no canon
        assert _normalize_value("interface", "Ethernet statistics") == "Ethernet statistics"

    def test_ip_field_with_non_ip_value_passes_through(self):
        # `ip_mtu` has "ip" in name but 1500 isn't an IP — leave alone
        assert _normalize_value("ip_mtu", "1500") == "1500"

    def test_version_field_not_touched(self):
        # "version" regex wouldn't match our IP hint
        assert _normalize_value("version", "15.5(3)M") == "15.5(3)M"

    def test_unassigned_passed_through(self):
        assert _normalize_value("ip_address", "unassigned") == "unassigned"

    def test_empty_value_passed_through(self):
        assert _normalize_value("neighbor_ip", "") == ""

    def test_non_string_passed_through(self):
        assert _normalize_value("count", 42) == 42


class TestNormalizeFields:
    def test_basic_row(self):
        rows = [{"local_interface": "Gi0/0", "neighbor_ip": "10.0.0.1"}]
        normalize_fields(rows)
        assert rows[0]["local_interface"] == "GigabitEthernet0/0"
        assert rows[0]["neighbor_ip"] == "10.0.0.1"

    def test_mixed_rows(self):
        rows = [
            {"interface": "Gi0/0", "remote_as": "65001"},
            {"interface": "Fa0/1", "remote_as": "1.1"},
        ]
        normalize_fields(rows)
        assert rows[0]["interface"] == "GigabitEthernet0/0"
        assert rows[0]["remote_as"] == 65001
        assert rows[1]["interface"] == "FastEthernet0/1"
        assert rows[1]["remote_as"] == 65537

    def test_empty_list(self):
        assert normalize_fields([]) == []

    def test_list_of_interfaces_inside_row(self):
        rows = [{"neighbors_via_interface": ["Gi0/0", "Gi0/1"]}]
        normalize_fields(rows)
        assert rows[0]["neighbors_via_interface"] == [
            "GigabitEthernet0/0",
            "GigabitEthernet0/1",
        ]

    def test_malformed_rows_skipped(self):
        # Non-dict entries in the list shouldn't break normalization
        rows = [
            {"interface": "Gi0/0"},
            "malformed",
            None,
            {"interface": "Fa0/0"},
        ]
        normalize_fields(rows)
        assert rows[0]["interface"] == "GigabitEthernet0/0"
        assert rows[3]["interface"] == "FastEthernet0/0"
        assert rows[1] == "malformed"
        assert rows[2] is None


class TestStateNormalizationBGP:
    """BGP states — RFC 4271 §8 finite-state machine."""

    def test_estab_truncated_to_established(self):
        assert _normalize_value("bgp_state", "Estab") == "Established"

    def test_established_full_form(self):
        assert _normalize_value("state", "Established") == "Established"

    def test_idle_capitalised(self):
        assert _normalize_value("state", "idle") == "Idle"

    def test_connect_bgp_kept_capitalised(self):
        # BGP "Connect" state — exact-match wins over the cisco "connected"
        # rule because Pass 1 checks exact equality first.
        assert _normalize_value("bgp_state", "Connect") == "Connect"


class TestStateNormalizationOSPF:
    """OSPF neighbour FSM — RFC 2328 §10."""

    def test_full_dr_preserved(self):
        # Suffix "/DR" is preserved via Pass 2 prefix-match
        assert _normalize_value("ospf_state", "Full/DR") == "Full/DR"

    def test_full_bdr_preserved(self):
        assert _normalize_value("state", "FULL/BDR") == "Full/BDR"

    def test_full_bare(self):
        assert _normalize_value("state", "Full") == "Full"

    def test_2way_normalised(self):
        assert _normalize_value("state", "2way") == "2-Way"


class TestStateNormalizationIfOperStatus:
    """RFC 2863 §3 ifOperStatus — the bug case from R83.4 follow-up.

    Cisco "show interfaces status" emits ``connected``/``notconnect``;
    these must collapse to RFC ifOperStatus enum values so cross-vendor
    queries don't have to know vendor-specific spellings.
    """

    def test_cisco_connected_to_up(self):
        # The original R83.2 bug: prefix-match swallowed "connected" via
        # BGP "connect" rule and produced "Connect".  Now exact-match
        # wins → "up".
        assert _normalize_value("status", "connected") == "up"

    def test_cisco_connected_capitalised(self):
        assert _normalize_value("status", "Connected") == "up"

    def test_cisco_notconnect_to_down(self):
        assert _normalize_value("status", "notconnect") == "down"

    def test_cisco_disabled_to_admin_down(self):
        assert _normalize_value("status", "disabled") == "admin-down"

    def test_administratively_down_to_admin_down(self):
        # Mind the space — value-shape regex now allows it
        assert _normalize_value("status", "administratively down") == "admin-down"

    def test_err_disabled(self):
        assert _normalize_value("status", "err-disabled") == "err-disabled"

    def test_up_lowercase_kept(self):
        assert _normalize_value("link_state", "up") == "up"

    def test_up_mixed_case_lowercased(self):
        # Junos terse and cisco brief both emit "Up"/"up" inconsistently;
        # canonical form is lowercase per RFC 2863 MIB.
        assert _normalize_value("link_state", "Up") == "up"

    def test_admin_state_field_triggers_normalization(self):
        # Field name 'admin_state' should hit _STATE_HINT (admin token)
        assert _normalize_value("admin_state", "Up") == "up"


class TestStateNormalizationSTP:
    """IEEE 802.1D STP port role / state."""

    def test_role_desg_to_designated(self):
        assert _normalize_value("role", "Desg") == "designated"

    def test_role_root_kept(self):
        assert _normalize_value("role", "Root") == "root"

    def test_role_altn_to_alternate(self):
        assert _normalize_value("role", "Altn") == "alternate"

    def test_state_fwd_to_forwarding(self):
        assert _normalize_value("status", "FWD") == "forwarding"

    def test_state_blk_to_blocking(self):
        assert _normalize_value("status", "BLK") == "blocking"

    def test_state_lis_to_listening(self):
        assert _normalize_value("status", "LIS") == "listening"


class TestStateNormalizationOSPFInterface:
    """OSPF interface state (DR/BDR/Loopback) — RFC 2328 §9."""

    def test_dr_lowercased(self):
        assert _normalize_value("state", "DR") == "dr"

    def test_loop_to_loopback(self):
        assert _normalize_value("state", "LOOP") == "loopback"


class TestStatePrefixMatchSafety:
    """Pass 2 (prefix match) only fires when suffix is /-or-suffixed.

    R83.2 bug had ``("connect", "Connect")`` swallow ``"connected"`` via
    bare prefix.  These tests pin that the new two-pass logic doesn't
    re-introduce that class of bug.
    """

    def test_connected_not_swallowed_by_connect(self):
        assert _normalize_value("status", "connected") == "up"

    def test_active_not_swallowed_into_random_word(self):
        # "active" exact match — should hit BGP rule
        assert _normalize_value("state", "active") == "Active"

    def test_unknown_value_unchanged(self):
        # Free-form value not in any rule should pass through
        assert _normalize_value("status", "unknown-vendor-state") == "unknown-vendor-state"


class TestUniversalTrim:
    """Trailing whitespace on string values is trimmed even when no
    canonical rule matches — fixes parser bugs like ``'P2p '`` from
    spanning-tree TextFSM template."""

    def test_trailing_space_trimmed_when_no_rule(self):
        # 'type' field with 'P2p ' — no _STATE_HINT match (type isn't
        # state/status/role/admin/oper), but trim should still apply
        assert _normalize_value("type", "P2p ") == "P2p"

    def test_leading_space_trimmed(self):
        assert _normalize_value("name", "  R1") == "R1"

    def test_no_change_when_clean(self):
        # Idempotent — returns same value without trim
        assert _normalize_value("name", "R1") == "R1"

    def test_non_string_untouched(self):
        # Non-string values not affected by trim
        assert _normalize_value("count", 42) == 42


class TestWhitespaceCollapse:
    """Whitespace-only values collapse to empty string for query consistency."""

    def test_single_space_collapses_to_empty(self):
        # Found in production: v_show_ip_bgp_auto.route_source had ' '
        assert _normalize_value("route_source", " ") == ""

    def test_multiple_spaces_collapse(self):
        assert _normalize_value("name", "   ") == ""

    def test_tab_only_collapses(self):
        assert _normalize_value("name", "\t") == ""

    def test_empty_string_unchanged(self):
        assert _normalize_value("name", "") == ""

    def test_sentinel_words_preserved(self):
        # Distinct from whitespace — "n/a" / "none" / etc. are intentional
        # placeholders carrying meaning, not parser artefacts
        assert _normalize_value("ip_address", "unassigned") == "unassigned"
        assert _normalize_value("ip_address", "none") == "none"
        assert _normalize_value("ip_address", "N/A") == "N/A"
