"""Round 59 — ARCH-14 P3 BGP neighbor→route-map resolution.

Last piece of ARCH-14 policy evaluation: parse ``neighbor X.X.X.X
route-map NAME in|out`` from the running-config captured in Round 56
and wire ``model.l4.policy(device, neighbor, direction)`` to resolve
the policy name, then delegate to ``model.l4.walk()``.

Pins:

* ``_extract_bgp_neighbor_policies_cisco_ios`` returns structured rows.
* ``L4Layer.neighbor_policies`` dict is populated alongside
  ``.clauses`` from the same layer materialisation pass.
* ``L4Layer.policy_for_neighbor`` returns the policy name or None.
* ``L4Layer.policy`` integrates with walk() end-to-end.
* Unbound neighbor/direction returns Cisco permit-all semantics
  (``unbound=True``, ``action="permit"``, empty sets/trace).
* Round 52 etc. pins that used to expect ``.policy()`` to raise have
  been updated elsewhere — this file is the positive-surface pin.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import duckdb
import pytest

from olav_netops.sim import load_network_model

HAS_NETWORKX = importlib.util.find_spec("networkx") is not None


_SAMPLE_R1_CONFIG = """\
!
hostname R1
!
route-map EXPORT_CUSTOMERS permit 10
 match ip address prefix-list CUST_PREFIXES
 set local-preference 200
!
route-map EXPORT_CUSTOMERS deny 20
 match ip address prefix-list RESERVED
!
route-map IMPORT_INTERNET permit 10
 match as-path 50
 set community 65001:200
!
router bgp 65001
 bgp router-id 1.1.1.1
 neighbor 10.0.12.2 remote-as 65002
 neighbor 10.0.12.2 route-map EXPORT_CUSTOMERS out
 neighbor 10.0.12.2 route-map IMPORT_INTERNET in
 neighbor 10.0.13.3 remote-as 65003
 neighbor 10.0.13.3 route-map EXPORT_CUSTOMERS out
!
"""


@pytest.fixture()
def policy_db(tmp_path: Path) -> Path:
    db = tmp_path / "p59.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("CREATE SCHEMA netops")
        conn.execute(
            """
            CREATE TABLE netops.raw_output_store (
                device_name VARCHAR,
                command     VARCHAR,
                raw_output  TEXT,
                snapshot_id VARCHAR,
                created_at  TIMESTAMP
            )
            """
        )
        conn.execute(
            "INSERT INTO netops.raw_output_store VALUES "
            "('R1', 'show running-config', ?, 'snap_a', NOW())",
            [_SAMPLE_R1_CONFIG],
        )
    return db


# ── Extractor pins ──────────────────────────────────────────────────────


def test_extractor_pulls_every_neighbor_route_map():
    from olav_netops.sim.network_model import (
        _extract_bgp_neighbor_policies_cisco_ios,
    )
    bindings = _extract_bgp_neighbor_policies_cisco_ios(_SAMPLE_R1_CONFIG)
    # Three neighbor route-map lines in the fixture.
    assert len(bindings) == 3
    by_key = {(b["neighbor_ip"], b["direction"]): b["policy_name"] for b in bindings}
    assert by_key[("10.0.12.2", "out")] == "EXPORT_CUSTOMERS"
    assert by_key[("10.0.12.2", "in")] == "IMPORT_INTERNET"
    assert by_key[("10.0.13.3", "out")] == "EXPORT_CUSTOMERS"


def test_extractor_ignores_remote_as_and_unrelated_lines():
    """``neighbor 10.0.12.2 remote-as 65002`` must not confuse the
    parser into producing a policy row."""
    from olav_netops.sim.network_model import (
        _extract_bgp_neighbor_policies_cisco_ios,
    )
    cfg = (
        "neighbor 10.0.12.2 remote-as 65002\n"
        "neighbor 10.0.12.2 description uplink\n"
        "neighbor 10.0.12.2 update-source Loopback0\n"
    )
    assert _extract_bgp_neighbor_policies_cisco_ios(cfg) == []


def test_extractor_tolerates_indentation():
    """The extractor must match both unindented (odd configs) and
    properly-indented ``neighbor ... route-map`` lines."""
    from olav_netops.sim.network_model import (
        _extract_bgp_neighbor_policies_cisco_ios,
    )
    cfg = "neighbor 10.0.12.2 route-map X out\n    neighbor 10.0.13.3 route-map Y in\n"
    bindings = _extract_bgp_neighbor_policies_cisco_ios(cfg)
    assert len(bindings) == 2
    assert {b["policy_name"] for b in bindings} == {"X", "Y"}


def test_extractor_empty_input_graceful():
    from olav_netops.sim.network_model import (
        _extract_bgp_neighbor_policies_cisco_ios,
    )
    assert _extract_bgp_neighbor_policies_cisco_ios("") == []


# ── L4Layer integration pins ────────────────────────────────────────────


def test_neighbor_policies_populated_on_materialisation(policy_db):
    m = load_network_model(db_path=policy_db)
    layer = m.l4
    if not HAS_NETWORKX:
        assert layer.neighbor_policies == {}
        assert layer.clauses == []
        return
    assert "R1" in layer.neighbor_policies
    assert layer.neighbor_policies["R1"][("10.0.12.2", "out")] == "EXPORT_CUSTOMERS"
    assert layer.neighbor_policies["R1"][("10.0.12.2", "in")] == "IMPORT_INTERNET"


def test_policy_for_neighbor_accessor(policy_db):
    m = load_network_model(db_path=policy_db)
    if not HAS_NETWORKX:
        assert m.l4.policy_for_neighbor("R1", "10.0.12.2", "out") is None
        assert m.l4.policy_for_neighbor("R1", "10.0.12.2", "in") is None
        return
    assert m.l4.policy_for_neighbor("R1", "10.0.12.2", "out") == "EXPORT_CUSTOMERS"
    assert m.l4.policy_for_neighbor("R1", "10.0.12.2", "in") == "IMPORT_INTERNET"
    # Unknown binding → None (NOT a raise).
    assert m.l4.policy_for_neighbor("R1", "10.0.99.99", "out") is None
    assert m.l4.policy_for_neighbor("NoSuchDevice", "10.0.12.2", "out") is None


# ── End-to-end policy evaluation pins ───────────────────────────────────


def test_policy_end_to_end_permits_matching_customer_prefix(policy_db):
    """R1→10.0.12.2 out uses EXPORT_CUSTOMERS. A prefix that matches
    CUST_PREFIXES must be permitted with the local-preference set."""
    m = load_network_model(db_path=policy_db)
    result = m.l4.policy(
        device="R1", neighbor="10.0.12.2", direction="out",
        matches={"ip address prefix-list CUST_PREFIXES": True},
    )
    if not HAS_NETWORKX:
        assert result["unbound"] is True
        assert result["policy_name"] is None
        assert result["action"] == "permit"
        return
    assert result["action"] == "permit"
    assert result["policy_name"] == "EXPORT_CUSTOMERS"
    assert result["neighbor"] == "10.0.12.2"
    assert result["direction"] == "out"
    assert result["unbound"] is False
    assert "local-preference 200" in result["sets"]


def test_policy_end_to_end_denies_reserved_prefix(policy_db):
    m = load_network_model(db_path=policy_db)
    result = m.l4.policy(
        device="R1", neighbor="10.0.12.2", direction="out",
        matches={
            "ip address prefix-list CUST_PREFIXES": False,
            "ip address prefix-list RESERVED": True,
        },
    )
    if not HAS_NETWORKX:
        assert result["unbound"] is True
        assert result["policy_name"] is None
        assert result["action"] == "permit"
        return
    assert result["action"] == "deny"
    assert result["policy_name"] == "EXPORT_CUSTOMERS"
    assert result["sets"] == []


def test_policy_end_to_end_inbound_binding(policy_db):
    """10.0.12.2 in → IMPORT_INTERNET; match as-path 50 permits + sets community."""
    m = load_network_model(db_path=policy_db)
    result = m.l4.policy(
        device="R1", neighbor="10.0.12.2", direction="in",
        matches={"as-path 50": True},
    )
    if not HAS_NETWORKX:
        assert result["unbound"] is True
        assert result["policy_name"] is None
        assert result["action"] == "permit"
        return
    assert result["action"] == "permit"
    assert result["policy_name"] == "IMPORT_INTERNET"
    assert "community 65001:200" in result["sets"]


def test_policy_unbound_returns_permit_all(policy_db):
    """R1 has no route-map on 10.0.99.99 — Cisco default is permit-all."""
    m = load_network_model(db_path=policy_db)
    result = m.l4.policy(
        device="R1", neighbor="10.0.99.99", direction="out",
        matches={"anything": True},
    )
    assert result["unbound"] is True
    assert result["action"] == "permit"
    assert result["policy_name"] is None
    assert result["sets"] == []
    assert result["trace"] == []
    assert "permit-all" in result["reason"].lower() or "default" in result["reason"].lower()


def test_policy_unknown_device_returns_unbound(policy_db):
    m = load_network_model(db_path=policy_db)
    result = m.l4.policy(
        device="NoSuchDevice", neighbor="10.0.12.2", direction="out",
    )
    assert result["unbound"] is True
    assert result["action"] == "permit"


def test_policy_forwards_matches_to_walker(policy_db):
    """Verify matches= passthrough — a callable matcher for
    .policy() should reach the underlying walk() and influence the
    decision."""
    m = load_network_model(db_path=policy_db)

    seen: list[str] = []

    def _matcher(cond: str) -> bool:
        seen.append(cond)
        return "CUST_PREFIXES" in cond

    result = m.l4.policy(
        device="R1", neighbor="10.0.12.2", direction="out", matches=_matcher,
    )
    if not HAS_NETWORKX:
        assert result["unbound"] is True
        assert seen == []
        return
    assert result["action"] == "permit"
    assert "ip address prefix-list CUST_PREFIXES" in seen


def test_policy_trace_structure_matches_walker(policy_db):
    """The trace shape returned by .policy() must match what walk()
    returns — callers shouldn't have to branch on which entry point
    they used."""
    m = load_network_model(db_path=policy_db)
    result = m.l4.policy(
        device="R1", neighbor="10.0.12.2", direction="out",
        matches={"ip address prefix-list CUST_PREFIXES": True},
    )
    if not HAS_NETWORKX:
        assert result["trace"] == []
        assert result["unbound"] is True
        return
    assert "trace" in result
    assert result["trace"]
    first = result["trace"][0]
    for key in ("seq", "action", "matched", "match_results", "set", "reason"):
        assert key in first


# ── Negative / graceful-empty pins ──────────────────────────────────────


def test_policy_missing_db_graceful():
    """Bad DB path → layer has empty neighbor_policies → all
    .policy() calls return unbound/permit-all rather than raising."""
    m = load_network_model(db_path="/definitely/missing.duckdb")
    result = m.l4.policy(device="R1", neighbor="10.0.12.2", direction="out")
    assert result["unbound"] is True
    assert result["action"] == "permit"


def test_policy_result_keys_are_stable(policy_db):
    """Lock the full key-set returned by .policy() so callers can rely
    on the structure without defensive .get() everywhere."""
    m = load_network_model(db_path=policy_db)
    result = m.l4.policy(
        device="R1", neighbor="10.0.12.2", direction="out",
        matches={"ip address prefix-list CUST_PREFIXES": True},
    )
    expected_keys = {
        "policy_name", "device", "neighbor", "direction",
        "action", "sets", "trace", "missing", "unbound",
    }
    assert expected_keys.issubset(result.keys()), (
        f"policy() result missing keys: {expected_keys - set(result.keys())}"
    )


def test_unbound_result_keys_include_reason():
    """The unbound path should also include a human-readable reason
    string so operators / LLMs can surface it in UIs."""
    m = load_network_model(db_path="/definitely/missing.duckdb")
    result = m.l4.policy(device="R1", neighbor="X", direction="out")
    assert "reason" in result
    assert isinstance(result["reason"], str) and result["reason"]
