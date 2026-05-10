"""Tests for olav.core.cab.prod_cli — sim-side deterministic prod-form
CLI generators (R94.1).

Pins the per-vendor / per-intent CLI shape so future template changes
are intentional, and confirms the bulk dispatcher
``derive_prod_cli_from_tcf`` round-trips through a TCF correctly.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from olav.core.cab import (
    CabTcf,
    Device,
    Intent,
    derive_prod_cli_from_tcf,
    generate_ios_ebgp_config,
    generate_ios_ebgp_rollback,
    generate_junos_ebgp_config,
    generate_junos_ebgp_rollback,
)


# --- Junos generator --------------------------------------------------------


def test_junos_ebgp_config_includes_all_required_clauses():
    cli = generate_junos_ebgp_config(
        prod_intf="ge-0/0/2",
        prod_intf_ip="172.16.99.1/30",
        prod_loopback="1.1.1.1",
        local_asn=65000,
        neighbor_ip="172.16.99.2",
        neighbor_loopback="4.4.4.4",
        peer_asn=65001,
        group_name="ebgp-r4",
    )
    text = "\n".join(cli)
    # Every clause a deployable Junos eBGP needs
    assert "set interfaces ge-0/0/2 unit 0 family inet address 172.16.99.1/30" in text
    assert "set interfaces lo0 unit 0 family inet address 1.1.1.1/32" in text
    assert "set routing-options router-id 1.1.1.1" in text
    assert "set routing-options autonomous-system 65000" in text
    assert "set protocols bgp group ebgp-r4 type external" in text
    assert "set protocols bgp group ebgp-r4 peer-as 65001" in text
    assert "set protocols bgp group ebgp-r4 neighbor 172.16.99.2" in text
    assert "set protocols bgp group ebgp-r4 export bgp-export" in text
    assert "set policy-options policy-statement bgp-export" in text
    # No ellipses / no placeholders
    assert "..." not in text


def test_junos_ebgp_rollback_only_touches_change_scope():
    rb = generate_junos_ebgp_rollback(
        prod_intf="ge-0/0/2",
        group_name="ebgp-r4",
    )
    text = "\n".join(rb)
    assert "delete protocols bgp group ebgp-r4" in text
    assert "delete policy-options policy-statement bgp-export" in text
    # MUST NOT delete loopback or AS number (likely shared with other sessions)
    assert "delete interfaces lo0" not in text
    assert "delete routing-options autonomous-system" not in text


# --- IOS generator ----------------------------------------------------------


def test_ios_ebgp_config_includes_all_required_clauses():
    cli = generate_ios_ebgp_config(
        prod_intf="Ethernet0/0",
        prod_intf_ip="172.16.99.2/30",
        prod_loopback="4.4.4.4",
        local_asn=65001,
        neighbor_ip="172.16.99.1",
        peer_asn=65000,
    )
    text = "\n".join(cli)
    # /30 mask must convert to dotted form
    assert "ip address 172.16.99.2 255.255.255.252" in text
    # /32 loopback
    assert "ip address 4.4.4.4 255.255.255.255" in text
    assert "router bgp 65001" in text
    assert "neighbor 172.16.99.1 remote-as 65000" in text
    assert "neighbor 172.16.99.1 update-source Loopback0" in text
    assert "neighbor 172.16.99.1 activate" in text
    assert "..." not in text


def test_ios_ebgp_rollback_is_surgical():
    """Surgical rollback (post commit a27b560): removes ONLY this peering,
    NOT the whole BGP process — deleting `no router bgp <asn>` would
    nuke unrelated neighbors in prod."""
    rb = generate_ios_ebgp_rollback(
        local_asn=65001,
        prod_intf="Ethernet0/0",
        neighbor_ip="172.16.99.1",
        neighbor_asn=65000,
        prod_loopback="4.4.4.4",
    )
    text = "\n".join(rb)
    # Surgical: target neighbor stripped, BGP process preserved
    assert "no router bgp" not in text, "rollback nukes entire BGP process"
    assert "no neighbor 172.16.99.1 remote-as 65000" in text
    assert "no neighbor 172.16.99.1 activate" in text
    assert "no network 4.4.4.4 mask 255.255.255.255" in text
    assert "interface Ethernet0/0" in text


# --- TCF dispatcher (derive_prod_cli_from_tcf) ------------------------------


def _ebgp_seed_tcf() -> CabTcf:
    return CabTcf(
        change_id="prod_cli_test",
        title="t",
        created_by="t",
        created_at=datetime.now(UTC),
        intent=Intent(type="ebgp_direct", lab_subnet="172.16.99.0/30"),
        devices=[
            Device(name="R1", platform="juniper_junos",
                   prod_intf="ge-0/0/2", prod_loopback="1.1.1.1", prod_asn=65000),
            Device(name="R4", platform="cisco_ios",
                   prod_intf="Ethernet0/0", prod_loopback="4.4.4.4", prod_asn=65001),
        ],
    )


def test_derive_prod_cli_returns_blocks_for_each_device():
    impl, rb = derive_prod_cli_from_tcf(_ebgp_seed_tcf())
    assert len(impl) == 2
    assert len(rb) == 2
    devices = {b["device"] for b in impl}
    assert devices == {"R1", "R4"}


def test_derive_prod_cli_uses_correct_subnet_assignments():
    """R1 = first usable /30 host (.1); R4 = second (.2)."""
    impl, _ = derive_prod_cli_from_tcf(_ebgp_seed_tcf())
    r1_text = "\n".join(impl[0]["cli"])
    r4_text = "\n".join(impl[1]["cli"])
    # R1 owns 172.16.99.1, neighbor is 172.16.99.2 (R4)
    assert "172.16.99.1/30" in r1_text
    assert "neighbor 172.16.99.2" in r1_text
    # R4 owns 172.16.99.2, neighbor is 172.16.99.1 (R1)
    assert "172.16.99.2 255.255.255.252" in r4_text
    assert "neighbor 172.16.99.1" in r4_text


def test_derive_prod_cli_as_numbers_are_cross_referenced():
    """R1 advertises peer-as 65001 (R4's ASN); R4 advertises remote-as 65000 (R1's)."""
    impl, _ = derive_prod_cli_from_tcf(_ebgp_seed_tcf())
    r1_text = "\n".join(impl[0]["cli"])
    r4_text = "\n".join(impl[1]["cli"])
    assert "peer-as 65001" in r1_text
    assert "autonomous-system 65000" in r1_text
    assert "router bgp 65001" in r4_text
    assert "remote-as 65000" in r4_text


def test_derive_prod_cli_unsupported_intent_errors():
    tcf = _ebgp_seed_tcf()
    tcf.intent = Intent(type="ibgp_route_reflector")
    with pytest.raises(ValueError, match="ebgp_direct"):
        derive_prod_cli_from_tcf(tcf)


def test_derive_prod_cli_unsupported_platform_errors():
    tcf = _ebgp_seed_tcf()
    tcf.devices[0].platform = "arista_eos"
    with pytest.raises(ValueError, match="arista_eos"):
        derive_prod_cli_from_tcf(tcf)


def test_derive_prod_cli_missing_lab_subnet_errors():
    tcf = _ebgp_seed_tcf()
    tcf.intent = Intent(type="ebgp_direct")  # no lab_subnet
    with pytest.raises(ValueError, match="lab_subnet"):
        derive_prod_cli_from_tcf(tcf)


def test_derive_prod_cli_wrong_device_count_errors():
    tcf = _ebgp_seed_tcf()
    tcf.devices = [tcf.devices[0]]  # only 1 device
    with pytest.raises(ValueError, match="2 devices"):
        derive_prod_cli_from_tcf(tcf)


def test_derive_prod_cli_blocks_round_trip_into_cliblocks():
    """The dict shape must validate as CliBlock."""
    from olav.core.cab import CliBlock
    impl, rb = derive_prod_cli_from_tcf(_ebgp_seed_tcf())
    # Pydantic-validate every block
    for block in impl + rb:
        CliBlock(**block)  # raises on shape error


def test_derive_prod_cli_no_ellipses_anywhere():
    """The whole point of R94.1: zero placeholders."""
    impl, rb = derive_prod_cli_from_tcf(_ebgp_seed_tcf())
    for block in impl + rb:
        for line in block["cli"]:
            assert "..." not in line, f"placeholder in {block['device']}: {line!r}"
