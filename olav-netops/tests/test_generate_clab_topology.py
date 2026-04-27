"""Unit tests for the R88-A generate_clab_topology tool (v2).

R88-A v2 contract:
  * Tool returns RAW YAML string (no JSON envelope) — eliminates the
    small-model JSON-stringify bug observed in R88-B v1.
  * Lab port numbering is sequential per node (e1-1, e1-2, ...) —
    matches the CAB Lab Substitution Table convention; ignores prod
    port numbers.
  * Warnings + snapshot_id appear as ``# WARNING:`` / ``# snapshot_id:``
    comments at the top — CLAB's YAML parser ignores them.

Covers:
  * interface validation (bundle / empty / numeric heuristic)
  * bidirectional link dedup
  * full pipeline against in-memory DuckDB with v_l2_links_auto rows
  * empty-result behaviour (no snapshot, no links)
  * yaml string contains both nodes: AND links: sections (the v2 failure)
  * sequential port numbering across multi-link labs
"""
from __future__ import annotations


import duckdb
import pytest


import olav.core.lab.topology as _gct


# --- _validate_iface --------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "ge-0/0/2",
        "GigabitEthernet0/0",
        "ethernet-1/1",
        "Et0/0",
        "e1-1",
        "Eth 0/1",
    ],
)
def test_validate_iface_accepts_known_forms(raw):
    assert _gct._validate_iface(raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        "Bundle-Ether10",
        "Port-Channel1",
        "ae0",
        "ae-1",
    ],
)
def test_validate_iface_rejects_bundles(raw):
    warn = _gct._validate_iface(raw)
    assert warn is not None and "bundle" in warn.lower()


def test_validate_iface_rejects_empty():
    assert _gct._validate_iface("") is not None


def test_validate_iface_rejects_non_numeric():
    """e.g. weird discovery noise — a name with no digit at all means we
    can't confidently treat it as a port."""
    warn = _gct._validate_iface("WeirdName")
    assert warn is not None


@pytest.mark.parametrize(
    "raw",
    [
        "512",         # LLDP port-id TLV in netops snapshot
        "0",
        "1234567",
    ],
)
def test_validate_iface_rejects_port_id_only(raw):
    """LLDP port-id-only values (no interface name) must be rejected
    so they don't end up as bogus extra links between two nodes."""
    warn = _gct._validate_iface(raw)
    assert warn is not None
    assert "port-id" in warn.lower()


# --- _dedupe_bidirectional --------------------------------------------------


def test_dedupe_collapses_reverse_link():
    rows = [
        ("R1", "ge-0/0/2", "R4", "Ethernet0/0"),
        ("R4", "Ethernet0/0", "R1", "ge-0/0/2"),
    ]
    out = _gct._dedupe_bidirectional(rows)
    assert len(out) == 1
    assert out[0] == ("R1", "ge-0/0/2", "R4", "Ethernet0/0")


def test_dedupe_keeps_distinct_links():
    rows = [
        ("R1", "ge-0/0/2", "R4", "Ethernet0/0"),
        ("R1", "ge-0/0/3", "R4", "Ethernet0/1"),
    ]
    out = _gct._dedupe_bidirectional(rows)
    assert len(out) == 2


def test_dedupe_handles_no_reverse():
    rows = [("R1", "ge-0/0/2", "R4", "Ethernet0/0")]
    out = _gct._dedupe_bidirectional(rows)
    assert len(out) == 1


# --- _build_yaml — sequential per-node port numbering -----------------------


def test_build_yaml_two_node_single_link_starts_at_one():
    """Single link: both nodes use e1-1 (CAB Lab Substitution convention).

    Lab node names are LOWERCASED (CLAB convention) — prod 'R1'
    becomes lab 'r1'.
    """
    links = [("R1", "ge-0/0/2", "R4", "Ethernet0/0")]
    yaml = _gct._build_yaml("cab_test", ["R1", "R4"], _gct._DEFAULT_IMAGE, links, [])
    assert "topology:" in yaml
    assert "nodes:" in yaml
    assert "links:" in yaml
    assert "r1:" in yaml and "r4:" in yaml
    assert "kind: nokia_srlinux" in yaml
    assert "endpoints: [r1:e1-1, r4:e1-1]" in yaml
    # Mapping comment surfaces the rename
    assert "# prod → lab node mapping:" in yaml
    assert "#   R1 → r1" in yaml
    assert "#   R4 → r4" in yaml


def test_build_yaml_two_links_increments_per_node():
    """Two links between R1 and R4 use e1-1 and e1-2 on each side."""
    links = [
        ("R1", "ge-0/0/2", "R4", "Ethernet0/0"),
        ("R1", "ge-0/0/3", "R4", "Ethernet0/1"),
    ]
    yaml = _gct._build_yaml("cab_test", ["R1", "R4"], _gct._DEFAULT_IMAGE, links, [])
    assert "endpoints: [r1:e1-1, r4:e1-1]" in yaml
    assert "endpoints: [r1:e1-2, r4:e1-2]" in yaml


def test_build_yaml_triangle_topology_per_node_counters():
    """Three nodes, three links — each node's port counter is independent."""
    links = [
        ("R1", "ge-0/0/2", "R2", "ge-0/0/1"),
        ("R1", "ge-0/0/3", "R3", "ge-0/0/1"),
        ("R2", "ge-0/0/2", "R3", "ge-0/0/2"),
    ]
    yaml = _gct._build_yaml(
        "cab_tri", ["R1", "R2", "R3"], _gct._DEFAULT_IMAGE, links, []
    )
    assert "endpoints: [r1:e1-1, r2:e1-1]" in yaml
    assert "endpoints: [r1:e1-2, r3:e1-1]" in yaml
    assert "endpoints: [r2:e1-2, r3:e1-2]" in yaml


def test_build_yaml_lowercases_already_lowercase_idempotent():
    """If caller already passed lowercase names, output is unchanged."""
    links = [("r1", "ge-0/0/2", "r4", "Ethernet0/0")]
    yaml = _gct._build_yaml("cab_test", ["r1", "r4"], _gct._DEFAULT_IMAGE, links, [])
    assert "endpoints: [r1:e1-1, r4:e1-1]" in yaml


def test_build_yaml_empty_links_still_emits_section():
    yaml = _gct._build_yaml("cab_test", ["R1", "R4"], _gct._DEFAULT_IMAGE, [], [])
    assert "nodes:" in yaml
    assert "links: []" in yaml


def test_build_yaml_warns_on_bundle_link_and_skips():
    warnings: list[str] = []
    links = [
        ("R1", "Bundle-Ether10", "R4", "Ethernet0/0"),
        ("R1", "ge-0/0/2", "R4", "Ethernet0/1"),
    ]
    yaml = _gct._build_yaml(
        "cab_test", ["R1", "R4"], _gct._DEFAULT_IMAGE, links, warnings
    )
    assert any("bundle" in w.lower() for w in warnings)
    # Bundle link is skipped; the valid link uses e1-1 (port counter not
    # bumped by the skipped link). Endpoints are lowercased.
    assert "endpoints: [r1:e1-1, r4:e1-1]" in yaml
    assert "Bundle-Ether" not in yaml


# --- _wrap_with_comments ----------------------------------------------------


def test_wrap_emits_snapshot_and_warnings():
    yaml_body = "name: test\ntopology: ...\n"
    out = _gct._wrap_with_comments(
        yaml_body, "snap-001", 2, ["something fishy", "another warn"]
    )
    assert out.startswith("# snapshot_id: snap-001\n")
    assert "# links_found: 2" in out
    assert "# WARNING: something fishy" in out
    assert "# WARNING: another warn" in out
    assert yaml_body in out


def test_wrap_with_no_warnings_still_has_links_found():
    yaml_body = "name: test\n"
    out = _gct._wrap_with_comments(yaml_body, "snap-001", 1, [])
    assert "# links_found: 1" in out
    assert "# WARNING:" not in out


# --- end-to-end: tool returns RAW YAML, not JSON ----------------------------


@pytest.fixture
def db_with_links(tmp_path, monkeypatch):
    db_path = tmp_path / "main.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE SCHEMA netops")
    con.execute(
        "CREATE TABLE netops.v_l2_links_auto ("
        "  source_device VARCHAR, source_interface VARCHAR, "
        "  destination_device VARCHAR, destination_interface VARCHAR, "
        "  discovery_protocol VARCHAR, link_status VARCHAR, "
        "  snapshot_id VARCHAR"
        ")"
    )
    con.executemany(
        "INSERT INTO netops.v_l2_links_auto VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("R1", "ge-0/0/2", "R4", "Ethernet0/0", "lldp", "up", "snap-001"),
            ("R4", "Ethernet0/0", "R1", "ge-0/0/2", "lldp", "up", "snap-001"),
            ("R1", "ge-0/0/3", "R4", "Ethernet0/1", "lldp", "up", "snap-001"),
            ("R2", "ge-0/0/1", "R3", "Ethernet0/2", "lldp", "up", "snap-001"),
        ],
    )
    con.close()

    import olav.core.config as _cfg
    monkeypatch.setattr(_cfg, "MAIN_DB_PATH", db_path)
    return db_path


def test_e2e_returns_raw_yaml_not_json(db_with_links):
    """Tool result must be parseable directly as YAML — no JSON envelope.

    This is the R88-A v2 contract that fixes the small-model
    JSON-stringify bug from R88-B v1.
    """
    import yaml as _yaml
    result = _gct.generate_clab_topology(**{
        "nodes": ["R1", "R4"],
        "lab_name": "cab_r1_r4",
    })
    # Must be a string (not JSON-wrapped)
    assert isinstance(result, str)
    # First non-comment line must be `name: <lab_name>`
    body_lines = [ln for ln in result.splitlines() if not ln.startswith("#") and ln.strip()]
    assert body_lines[0] == "name: cab_r1_r4"
    # Must parse as YAML and have the expected structure (lab node names lowercased)
    parsed = _yaml.safe_load(result)
    assert parsed["name"] == "cab_r1_r4"
    assert "r1" in parsed["topology"]["nodes"]
    assert "r4" in parsed["topology"]["nodes"]
    assert "R1" not in parsed["topology"]["nodes"]
    assert len(parsed["topology"]["links"]) == 2


def test_e2e_two_node_lab_uses_sequential_ports(db_with_links):
    result = _gct.generate_clab_topology(**{
        "nodes": ["R1", "R4"],
        "lab_name": "cab_r1_r4",
    })
    assert "endpoints: [r1:e1-1, r4:e1-1]" in result
    assert "endpoints: [r1:e1-2, r4:e1-2]" in result
    # snapshot comment present
    assert "# snapshot_id: snap-001" in result
    # mapping comment surfaced
    assert "#   R1 → r1" in result
    assert "#   R4 → r4" in result


def test_e2e_filters_links_outside_node_set(db_with_links):
    result = _gct.generate_clab_topology(**{
        "nodes": ["R1", "R4"],
        "lab_name": "cab_r1_r4",
    })
    # Body refers only to requested nodes (lowercased lab forms)
    body = "\n".join(
        ln for ln in result.splitlines() if not ln.startswith("#")
    )
    assert "r2" not in body.lower() or "endpoints: [r2" not in body
    assert "endpoints: [r3" not in body
    # And the prod-name forms must not appear in the body either
    assert "R2" not in body
    assert "R3" not in body


def test_e2e_empty_node_list_returns_error_comment(db_with_links):
    result = _gct.generate_clab_topology(**{
        "nodes": [],
        "lab_name": "cab_test",
    })
    assert "# ERROR" in result
    assert "empty" in result.lower()


def test_e2e_no_matching_links_emits_empty_section(db_with_links):
    result = _gct.generate_clab_topology(**{
        "nodes": ["LonelyA", "LonelyB"],
        "lab_name": "cab_lonely",
    })
    assert "# links_found: 0" in result
    # Lab node names are lowercased
    assert "lonelya:" in result
    assert "lonelyb:" in result
    assert "links: []" in result
