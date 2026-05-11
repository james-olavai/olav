"""Phase F prototype tests — schema-in-config intent handler.

Verifies the rev 271 experiment: one generic Python handler walks a
per-intent YAML schema and produces TCF blocks identical in shape to
``tcf_writer._render_freeform_cli`` output. The intent under test is
``static_route_add``, exercising:

  * arg defaults + required validation
  * fact_lookups SQL via a stub db_conn (no live DuckDB needed)
  * fact_computed Python expressions (ipaddress CIDR → mask)
  * Cisco IOS + Juniper Junos CLI template rendering
  * loose platform-key matching (cisco-ios / CISCO IOS / cisco_ios)
  * per-platform post_checks command_templates

Success criteria for the experiment:
  - CLI output exactly matches what a hand-written renderer would
    produce for the same args
  - Adding a new intent (e.g. vlan_add) only requires a new
    *.intent.yaml — no edit to generic_intent_handler.py
"""

from __future__ import annotations

import pytest

from olav.core.cab.generic_intent_handler import (
    list_intents,
    load_intent_schema,
    render_intent_to_tcf_blocks,
)


# ── Stub DB connection ──────────────────────────────────────────────


class _StubCursor:
    def __init__(self, row: tuple | None):
        self._row = row

    def fetchone(self):
        return self._row


class _StubDB:
    """Duck-typed substitute for duckdb.DuckDBPyConnection.

    Maps (sql, args) → fixed row, so tests stay pure-Python without
    spinning up DuckDB.
    """

    def __init__(self, fixtures: dict[tuple, tuple]):
        # fixtures key = (normalised_sql, tuple(args))
        self._fixtures = fixtures
        self.calls: list[tuple] = []

    def execute(self, sql: str, args: list | tuple = ()):
        norm = " ".join(sql.split())
        key = (norm, tuple(args))
        self.calls.append(key)
        row = self._fixtures.get(key)
        return _StubCursor(row)


# ── 1. Schema discovery ────────────────────────────────────────────


def test_static_route_add_intent_discoverable():
    intents = list_intents()
    assert "static_route_add" in intents


def test_load_static_route_add_schema():
    spec = load_intent_schema("static_route_add")
    assert spec["intent"] == "static_route_add"
    assert "cisco_ios" in spec["cli_templates"]
    assert "juniper_junos" in spec["cli_templates"]
    # Required args declared
    assert spec["args"]["src_device"]["required"]
    assert spec["args"]["dst_prefix"]["required"]
    assert spec["args"]["next_hop_ip"]["required"]


# ── 2. Cisco IOS render ─────────────────────────────────────────────


def _cisco_db():
    return _StubDB({
        ("SELECT platform FROM netops.devices WHERE hostname = ?", ("R3",)):
            ("cisco_ios",),
    })


def test_cisco_ios_render_basic():
    out = render_intent_to_tcf_blocks(
        "static_route_add",
        args={
            "src_device": "R3",
            "dst_prefix": "192.0.2.0/24",
            "next_hop_ip": "10.0.13.1",
        },
        db_conn=_cisco_db(),
    )
    assert out["intent"] == "static_route_add"
    assert out["platform"] == "cisco_ios"
    impl = out["implementation"]
    assert len(impl) == 1
    assert impl[0]["device"] == "R3"
    assert impl[0]["cli"] == [
        "configure terminal",
        "ip route 192.0.2.0 255.255.255.0 10.0.13.1",
        "end",
        "write memory",
    ]
    rb = out["rollback"][0]["cli"]
    assert "no ip route 192.0.2.0 255.255.255.0 10.0.13.1" in rb
    # Facts captured for audit trail
    assert out["facts_used"]["src_platform"] == "cisco_ios"
    assert out["facts_used"]["dst_network"] == "192.0.2.0"
    assert out["facts_used"]["dst_mask"] == "255.255.255.0"


def test_cisco_ios_render_with_admin_distance():
    """admin_distance arg threads through the Jinja2 conditional."""
    out = render_intent_to_tcf_blocks(
        "static_route_add",
        args={
            "src_device": "R3",
            "dst_prefix": "10.99.0.0/16",
            "next_hop_ip": "10.0.13.5",
            "admin_distance": 200,
        },
        db_conn=_cisco_db(),
    )
    line = out["implementation"][0]["cli"][1]
    assert line == "ip route 10.99.0.0 255.255.0.0 10.0.13.5 200"


def test_cisco_ios_post_check_command():
    out = render_intent_to_tcf_blocks(
        "static_route_add",
        args={
            "src_device": "R3",
            "dst_prefix": "192.0.2.0/24",
            "next_hop_ip": "10.0.13.1",
        },
        db_conn=_cisco_db(),
    )
    pc = out["post_check"]
    assert len(pc) == 1
    assert pc[0]["device"] == "R3"
    assert pc[0]["command"] == "show ip route 192.0.2.0/24"
    assert pc[0]["expected_pattern"] == "10.0.13.1"
    assert pc[0]["must_match"] is True


# ── 3. Junos render ────────────────────────────────────────────────


def _junos_db():
    return _StubDB({
        ("SELECT platform FROM netops.devices WHERE hostname = ?", ("R1",)):
            ("juniper_junos",),
    })


def test_junos_render_basic():
    out = render_intent_to_tcf_blocks(
        "static_route_add",
        args={
            "src_device": "R1",
            "dst_prefix": "10.50.0.0/16",
            "next_hop_ip": "10.0.13.1",
        },
        db_conn=_junos_db(),
    )
    assert out["platform"] == "juniper_junos"
    assert out["implementation"][0]["cli"] == [
        "configure",
        "set routing-options static route 10.50.0.0/16 next-hop 10.0.13.1",
        "commit and-quit",
    ]
    assert "delete routing-options static route 10.50.0.0/16 next-hop 10.0.13.1" in \
        out["rollback"][0]["cli"]
    assert out["post_check"][0]["command"] == "show route 10.50.0.0/16"


# ── 4. Platform-key matching robustness ────────────────────────────


@pytest.mark.parametrize(
    "raw_platform",
    ["cisco_ios", "cisco-ios", "CISCO IOS", "Cisco_IOS", "ciscoios"],
)
def test_platform_key_loose_match(raw_platform):
    db = _StubDB({
        ("SELECT platform FROM netops.devices WHERE hostname = ?", ("R3",)):
            (raw_platform,),
    })
    out = render_intent_to_tcf_blocks(
        "static_route_add",
        args={
            "src_device": "R3",
            "dst_prefix": "1.2.3.0/24",
            "next_hop_ip": "10.0.0.1",
        },
        db_conn=db,
    )
    assert out["platform"] == "cisco_ios"


# ── 5. Failure modes ────────────────────────────────────────────────


def test_missing_required_arg_raises():
    with pytest.raises(ValueError, match="missing required arg"):
        render_intent_to_tcf_blocks(
            "static_route_add",
            args={"dst_prefix": "1.2.3.0/24", "next_hop_ip": "10.0.0.1"},
            db_conn=_cisco_db(),
        )


def test_unknown_intent_raises():
    with pytest.raises(FileNotFoundError, match="intent schema not found"):
        render_intent_to_tcf_blocks(
            "completely_unknown_intent_xyz",
            args={},
            db_conn=_cisco_db(),
        )


def test_unknown_platform_raises():
    db = _StubDB({
        ("SELECT platform FROM netops.devices WHERE hostname = ?", ("ALIEN-1",)):
            ("openconfig_yang",),
    })
    with pytest.raises(ValueError, match="did not match any cli_templates"):
        render_intent_to_tcf_blocks(
            "static_route_add",
            args={
                "src_device": "ALIEN-1",
                "dst_prefix": "1.2.3.0/24",
                "next_hop_ip": "10.0.0.1",
            },
            db_conn=db,
        )


def test_missing_device_in_db_raises():
    db = _StubDB({})  # empty fixture — DB returns no rows
    with pytest.raises(RuntimeError, match="no row returned"):
        render_intent_to_tcf_blocks(
            "static_route_add",
            args={
                "src_device": "NOT-IN-DB",
                "dst_prefix": "1.2.3.0/24",
                "next_hop_ip": "10.0.0.1",
            },
            db_conn=db,
        )


# ── 6. Shape compat with tcf_writer._render_freeform_cli ────────────


def test_return_shape_matches_freeform_cli_compatible():
    """Return shape must align with what tcf_writer expects so a future
    commit can drop this handler into the _INTENT_RENDERERS dispatch."""
    out = render_intent_to_tcf_blocks(
        "static_route_add",
        args={
            "src_device": "R3",
            "dst_prefix": "192.0.2.0/24",
            "next_hop_ip": "10.0.13.1",
        },
        db_conn=_cisco_db(),
    )
    # tcf_writer._render_freeform_cli returns these keys:
    assert {"intent", "implementation", "rollback", "post_check"}.issubset(out)
    # Each impl/rollback entry must have device + cli list
    for block in out["implementation"] + out["rollback"]:
        assert set(block).issuperset({"device", "phase", "action", "cli"})
        assert isinstance(block["cli"], list)
        assert all(isinstance(line, str) for line in block["cli"])
    # post_check shape
    for pc in out["post_check"]:
        assert set(pc).issuperset({
            "device", "check_id", "command", "expected_pattern", "must_match",
        })
