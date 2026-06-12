"""``render_topology_drawio`` — adjacency-table → mxfile XML contract.

Pinned behaviour:
  * Valid table → complete ``<mxfile>...</mxfile>`` XML, well-formed
  * Distinct hostnames → distinct node positions (no two nodes at
    identical coordinates)
  * Stencil chosen by hostname prefix (R# / FW# / default switch)
  * status='down' → dashed edge style
  * Empty / malformed input → HTML-comment "diagram omitted" note,
    never invented edges
"""
from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

# Workspace script path — writer/scripts/ after scripts-化 migration.
_WRITER_SCRIPTS = Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "core" / "writer" / "scripts"
sys.path.insert(0, str(_WRITER_SCRIPTS))


from render_topology_drawio import (
    _build_xml,
    _layout_tree,
    _safe_id,
    _stencil_for,
    render_topology_drawio,
)


_SMALL_TABLE = """\
| Source | Local Intf | Dest | Remote Intf | Status |
|---|---|---|---|---|
| R1 | Eth0/0 | SW1 | Gi0/1 | up |
| R1 | Eth0/1 | SW2 | Gi0/1 | up |
| SW1 | Gi0/24 | SW2 | Gi0/24 | down |
"""


def _invoke(tool_callable, *args, **kwargs):
    """Call a @tool-decorated function (StructuredTool exposes .invoke)."""
    if hasattr(tool_callable, "invoke"):
        return tool_callable.invoke({"adjacencies_table_markdown": args[0]})
    return tool_callable(*args, **kwargs)


# ── Happy path ────────────────────────────────────────────────────────


class TestRenderHappyPath:
    def test_returns_well_formed_xml(self):
        out = _invoke(render_topology_drawio, _SMALL_TABLE)
        assert out.startswith("<mxfile"), f"prefix wrong: {out[:80]!r}"
        # Must parse cleanly.
        root = ET.fromstring(out)
        assert root.tag == "mxfile"

    def test_includes_all_three_nodes(self):
        out = _invoke(render_topology_drawio, _SMALL_TABLE)
        root = ET.fromstring(out)
        vertex_cells = [
            c for c in root.iter("mxCell") if c.get("vertex") == "1"
        ]
        labels = {c.get("value") for c in vertex_cells}
        assert labels == {"R1", "SW1", "SW2"}

    def test_includes_all_three_edges(self):
        out = _invoke(render_topology_drawio, _SMALL_TABLE)
        root = ET.fromstring(out)
        edges = [c for c in root.iter("mxCell") if c.get("edge") == "1"]
        assert len(edges) == 3

    def test_edge_carries_interface_label(self):
        out = _invoke(render_topology_drawio, _SMALL_TABLE)
        # The arrow-string ↔ should appear in the value attribute.
        assert "Eth0/0 ↔ Gi0/1" in out
        assert "Gi0/24 ↔ Gi0/24" in out

    def test_down_status_renders_dashed(self):
        out = _invoke(render_topology_drawio, _SMALL_TABLE)
        # SW1-SW2 edge is status=down — should carry dashed=1 in its style.
        root = ET.fromstring(out)
        for c in root.iter("mxCell"):
            if c.get("edge") == "1" and c.get("source") == "SW1" and c.get("target") == "SW2":
                assert "dashed=1" in (c.get("style") or "")
                break
        else:
            pytest.fail("SW1→SW2 edge not found")


# ── Layout ────────────────────────────────────────────────────────────


class TestLayout:
    def test_distinct_node_positions(self):
        out = _invoke(render_topology_drawio, _SMALL_TABLE)
        root = ET.fromstring(out)
        positions: list[tuple[str, str]] = []
        for c in root.iter("mxCell"):
            if c.get("vertex") != "1":
                continue
            geo = c.find("mxGeometry")
            positions.append((geo.get("x"), geo.get("y")))
        assert len(positions) == len(set(positions)), (
            f"two nodes share a position: {positions}"
        )

    def test_layout_handles_disconnected_components(self):
        positions = _layout_tree(
            nodes=["A", "B", "C", "D"],
            edges=[("A", "B"), ("C", "D")],
        )
        assert len(positions) == 4
        # A,B should be at small y; C,D should be below them (different row band).
        max_y_first = max(positions["A"][1], positions["B"][1])
        min_y_second = min(positions["C"][1], positions["D"][1])
        assert min_y_second > max_y_first

    def test_safe_id_strips_special_chars(self):
        assert _safe_id("R1.example.com") == "R1_example_com"
        assert _safe_id("foo-bar/baz") == "foo_bar_baz"


# ── Stencil mapping ───────────────────────────────────────────────────


class TestStencilMapping:
    def test_router_prefix(self):
        stencil, _ = _stencil_for("R1")
        assert "routers.router" in stencil

    def test_firewall_prefix(self):
        stencil, _ = _stencil_for("FW1")
        assert "firewalls.firewall" in stencil

    def test_firewall_keyword_in_name(self):
        stencil, _ = _stencil_for("dc-asa-1")
        assert "firewalls.firewall" in stencil

    def test_default_is_switch(self):
        stencil, _ = _stencil_for("foo-bp1-3850")
        assert "switches.workgroup_switch" in stencil

    def test_router_keyword_in_name(self):
        stencil, _ = _stencil_for("core-router-01")
        assert "routers.router" in stencil

    def test_router_in_middle_of_hostname(self):
        """Regression: real-world hostname like ``QS4-12S1-R1-EDGE`` should
        be detected as a router via the mid-name R\\d signal."""
        stencil, _ = _stencil_for("QS4-12S1-R1-EDGE.net.vu.edu.au")
        assert "routers.router" in stencil

    def test_edge_keyword_detected(self):
        stencil, _ = _stencil_for("foo-edge-3850")
        assert "routers.router" in stencil

    def test_border_keyword_detected(self):
        stencil, _ = _stencil_for("foo-border-1")
        assert "routers.router" in stencil

    def test_role_override_wins(self):
        """Caller-supplied role overrides hostname heuristics."""
        # Hostname suggests router; role says firewall — role wins.
        stencil, _ = _stencil_for("R1-edge", role="firewall")
        assert "firewalls.firewall" in stencil
        # Hostname suggests router; role says switch — role wins.
        stencil, _ = _stencil_for("R1-edge", role="switch")
        assert "switches.workgroup_switch" in stencil


class TestDeviceMetadataLabels:
    """Node labels include model + IP when metadata is supplied."""

    META = {
        "R1": {"model": "C9300-48UXM", "ip": "10.1.1.1", "role": "router"},
        "SW1": {"model": "WS-C3850-24XU", "ip": "10.1.1.2"},
    }

    def test_label_includes_model_and_ip(self):
        out = _invoke(render_topology_drawio, _SMALL_TABLE,
                      device_metadata=self.META)
        # XML literal newline marker for draw.io.
        assert "C9300-48UXM" in out
        assert "10.1.1.1" in out
        assert "WS-C3850-24XU" in out
        assert "10.1.1.2" in out
        assert "&#xa;" in out  # multi-line label syntax used

    def test_label_omits_lines_for_missing_fields(self):
        """SW2 has no metadata at all — label is just hostname (no &#xa;)."""
        out = _invoke(render_topology_drawio, _SMALL_TABLE,
                      device_metadata=self.META)
        # SW2 vertex label should be plain hostname, no embedded newline.
        import re as _re
        m = _re.search(r'id="SW2" value="([^"]+)"', out)
        assert m is not None
        assert "&#xa;" not in m.group(1)
        assert m.group(1) == "SW2"

    def test_metadata_role_overrides_stencil(self):
        out = _invoke(render_topology_drawio, _SMALL_TABLE,
                      device_metadata=self.META)
        # R1 has role=router → router stencil expected.
        assert "routers.router" in out
        # SW1 has no role → falls through to hostname heuristic → switch.
        # (SW1 hostname starts with SW, default is switch.)
        assert "switches.workgroup_switch" in out


def _invoke(tool_callable, *args, **kwargs):
    """Call a @tool-decorated function — late re-definition for new sigs."""
    if hasattr(tool_callable, "invoke"):
        payload = {"adjacencies_table_markdown": args[0]}
        if "device_metadata" in kwargs:
            payload["device_metadata"] = kwargs["device_metadata"]
        if "protocol" in kwargs:
            payload["protocol"] = kwargs["protocol"]
        return tool_callable.invoke(payload)
    return tool_callable(*args, **kwargs)


_BGP_TABLE = """\
| Source | Local Intf | Dest | Remote Intf | Status |
|---|---|---|---|---|
| R1 | 10.0.0.1 | R2 | 10.0.0.2 | Established |
| R1 | 10.0.1.1 | R3 | 10.0.1.2 | Idle |
"""


_OSPF_TABLE = """\
| Source | Local Intf | Dest | Remote Intf | Status |
|---|---|---|---|---|
| R1 | Eth0/0 | 2.2.2.2 | 10.0.0.2 | FULL |
| R1 | Eth0/1 | 3.3.3.3 | 10.0.1.2 | INIT |
"""


class TestProtocolBGP:
    def test_bgp_forces_router_stencil(self):
        """All nodes render with router stencil regardless of name."""
        out = _invoke(render_topology_drawio, _BGP_TABLE, protocol="bgp")
        # Both R1 and R2/R3 hit router stencil.
        assert out.count("routers.router") >= 2
        # Switch stencil never appears for BGP topology.
        assert "switches.workgroup_switch" not in out

    def test_bgp_edge_labels_include_state(self):
        """BGP edges carry the session state in parentheses."""
        out = _invoke(render_topology_drawio, _BGP_TABLE, protocol="bgp")
        assert "(Established)" in out
        assert "(Idle)" in out

    def test_bgp_non_established_renders_dashed(self):
        out = _invoke(render_topology_drawio, _BGP_TABLE, protocol="bgp")
        from xml.etree import ElementTree as ET
        root = ET.fromstring(out)
        for c in root.iter("mxCell"):
            if c.get("edge") == "1" and c.get("target") == "R3":
                # R3 is Idle ⇒ dashed.
                assert "dashed=1" in c.get("style", "")
                break
        else:
            import pytest as _pytest
            _pytest.fail("R1→R3 edge not found in BGP output")


class TestProtocolOSPF:
    def test_ospf_forces_router_stencil(self):
        out = _invoke(render_topology_drawio, _OSPF_TABLE, protocol="ospf")
        assert out.count("routers.router") >= 2
        assert "switches.workgroup_switch" not in out

    def test_ospf_edge_labels_include_state(self):
        out = _invoke(render_topology_drawio, _OSPF_TABLE, protocol="ospf")
        assert "(FULL)" in out
        assert "(INIT)" in out

    def test_ospf_full_state_is_solid_edge(self):
        """Status='FULL' counts as healthy → solid edge (no dashed)."""
        out = _invoke(render_topology_drawio, _OSPF_TABLE, protocol="ospf")
        from xml.etree import ElementTree as ET
        root = ET.fromstring(out)
        for c in root.iter("mxCell"):
            if c.get("edge") == "1" and c.get("target") == "2.2.2.2":
                assert "dashed=1" not in c.get("style", "")
                break


# ── Error / empty paths ───────────────────────────────────────────────


class TestErrorPaths:
    def test_empty_input_returns_html_comment(self):
        out = _invoke(render_topology_drawio, "")
        assert out.startswith("<!--")
        assert "diagram omitted" in out
        assert "<mxfile" not in out

    def test_unparseable_input_returns_html_comment(self):
        out = _invoke(render_topology_drawio, "this is just prose with no table\n")
        assert out.startswith("<!--")
        assert "diagram omitted" in out

    def test_table_missing_required_columns(self):
        bad = "| Foo | Bar |\n|---|---|\n| a | b |\n"
        out = _invoke(render_topology_drawio, bad)
        assert "missing required column" in out

    def test_table_with_only_separator_no_data_rows(self):
        bad = "| Source | Local Intf | Dest | Remote Intf |\n|---|---|---|---|\n"
        out = _invoke(render_topology_drawio, bad)
        # Header present but no data → "could not parse" or "no usable rows".
        assert "diagram omitted" in out


# ── XML structural sanity ─────────────────────────────────────────────


class TestXmlStructure:
    def test_root_mxgraphmodel_chain_present(self):
        out = _invoke(render_topology_drawio, _SMALL_TABLE)
        root = ET.fromstring(out)
        # mxfile > diagram > mxGraphModel > root > [mxCell id="0", mxCell id="1", …]
        diagram = root.find("diagram")
        assert diagram is not None
        model = diagram.find("mxGraphModel")
        assert model is not None
        groot = model.find("root")
        assert groot is not None
        ids = [c.get("id") for c in groot.findall("mxCell")]
        assert ids[:2] == ["0", "1"]  # required parent chain

    def test_edge_source_and_target_match_vertex_ids(self):
        out = _invoke(render_topology_drawio, _SMALL_TABLE)
        root = ET.fromstring(out)
        vertex_ids = {c.get("id") for c in root.iter("mxCell") if c.get("vertex") == "1"}
        for c in root.iter("mxCell"):
            if c.get("edge") != "1":
                continue
            src = c.get("source")
            dst = c.get("target")
            assert src in vertex_ids, f"edge references unknown source {src}"
            assert dst in vertex_ids, f"edge references unknown target {dst}"

    def test_build_xml_idempotent_with_explicit_positions(self):
        """_build_xml directly should produce the same XML for the same
        inputs (no hidden state)."""
        nodes = ["A", "B"]
        edges = [("A", "Gi0/0", "B", "Gi0/1", "up")]
        positions = {"A": (40, 40), "B": (160, 40)}
        a = _build_xml(nodes, edges, positions)
        b = _build_xml(nodes, edges, positions)
        assert a == b
