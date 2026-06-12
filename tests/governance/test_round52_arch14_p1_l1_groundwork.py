"""Round 52 — ARCH-14 P1 L1 NetworkModel groundwork pins.

Ships the minimum viable slice of the multi-layer Network Object Model
(``olav_netops.sim``):

* Lazy-proxy ``NetworkModel`` — construction does NO DB work.
* Real ``PhysicalLayer`` materialisation wrapping ``netops.topology_links``
  via ``networkx.Graph`` (reads ``MAX(snapshot_id)`` by default, honours
  the ``snapshot=`` kwarg and ``scope=`` host filter).
* Stub layers (``model.l2``, ``model.l3.ospf``, ``model.l3.bgp``,
  ``model.l4.policy``) that raise ``NotImplementedError`` with a
  pointer to the follow-on round so the public surface is discoverable
  now.

These pins protect the P1 contract so subsequent rounds can fill in L2+
without a signature drift breaking existing callers.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PKG_DIR = REPO / "olav-netops" / "src" / "olav_netops" / "sim"
HAS_NETWORKX = importlib.util.find_spec("networkx") is not None


def test_sim_package_files_exist():
    assert (PKG_DIR / "__init__.py").is_file()
    assert (PKG_DIR / "network_model.py").is_file()


def test_public_api_exports():
    from olav_netops.sim import NetworkModel, PhysicalLayer, load_network_model
    assert NetworkModel is not None
    assert PhysicalLayer is not None
    assert callable(load_network_model)


def test_construction_is_lazy_no_db_touch():
    """Building a NetworkModel must not open the DuckDB file — point the
    ``db_path`` at a guaranteed-missing path and confirm construction
    still succeeds."""
    from olav_netops.sim import load_network_model

    m = load_network_model(
        snapshot="dummy_snap",
        scope=["R1", "R2"],
        db_path="/definitely/not/a/real/path.duckdb",
    )
    assert m.snapshot == "dummy_snap"
    assert m.scope == ["R1", "R2"]
    # devices respects explicit scope without touching the DB.
    assert m.devices == ["R1", "R2"]


def test_physical_layer_returns_graceful_empty_on_missing_db():
    """Bad DB path must yield an empty PhysicalLayer, not raise —
    operators often run sim against partially-bootstrapped DBs while
    developing."""
    from olav_netops.sim import load_network_model

    m = load_network_model(db_path="/definitely/not/a/real/path.duckdb")
    phys = m.physical
    # Empty but well-formed.
    assert phys.links == []
    assert phys.graph is None
    assert phys.neighbors("R1") == []
    assert phys.devices() == []


def test_physical_layer_cached_on_instance(monkeypatch):
    """Second access of .physical must reuse the cache, not re-query."""
    from olav_netops.sim import network_model as nm

    call_count = {"n": 0}

    def _fake_build(db, snap, scope):
        call_count["n"] += 1
        return nm.PhysicalLayer(links=[], graph=None)

    monkeypatch.setattr(nm, "_build_physical_layer", _fake_build)
    m = nm.NetworkModel(db_path=Path("/nowhere"))
    m.physical  # first access — triggers build
    m.physical  # second access — cache hit
    m.physical  # third
    assert call_count["n"] == 1, (
        f"PhysicalLayer was rebuilt {call_count['n']} times; must cache"
    )


def test_l2_is_l2layer_not_stub():
    """Round 55 filled in model.l2. Must now be an L2Layer instance,
    not a NotImplementedError stub. Behaviour coverage lives in
    test_round55_arch14_l2_layer.py."""
    from olav_netops.sim import L2Layer, load_network_model

    m = load_network_model(db_path="/definitely/missing.duckdb")
    layer = m.l2
    assert isinstance(layer, L2Layer), (
        f"model.l2 must return an L2Layer instance; got {type(layer)!r}"
    )


def test_l3_bgp_is_bgplayer_not_stub():
    """Round 54 filled in model.l3.bgp. The returned object must be a
    real ``BgpLayer`` (tested for behaviour in
    ``test_round54_arch14_bgp_layer.py``), not a NotImplementedError
    stub. If the BGP layer regresses to a stub this pin will surface
    that immediately."""
    from olav_netops.sim import BgpLayer, load_network_model

    m = load_network_model(db_path="/definitely/missing.duckdb")
    # Attribute access must not raise — missing-DB contract is "empty
    # layer", not exception.
    layer = m.l3.bgp
    assert isinstance(layer, BgpLayer), (
        f"model.l3.bgp must return a BgpLayer instance; got {type(layer)!r}"
    )


def test_l4_is_fully_live_post_round_59():
    """Round 56 landed ``model.l4`` clause extraction; Round 58 added
    the deterministic walker; Round 59 wired end-to-end ``.policy(...)``
    via BGP neighbor→route-map resolution. This pin guards that all
    three surfaces stay live on an empty-DB model (graceful-empty
    contract — no raising)."""
    from olav_netops.sim import L4Layer, load_network_model

    m = load_network_model(db_path="/definitely/missing.duckdb")
    assert isinstance(m.l4, L4Layer)
    # Walker surface exists and returns a structured result.
    walk = m.l4.walk("R1", "POLICY", matches={})
    assert walk["missing"] is True
    # End-to-end .policy(...) is live — empty config → unbound permit-all.
    policy = m.l4.policy(device="R1", neighbor="10.0.12.2", direction="out")
    assert policy["unbound"] is True
    assert policy["action"] == "permit"


def test_build_physical_layer_handles_real_graph(tmp_path):
    """End-to-end: build a minimal DuckDB with topology_links rows and
    verify the networkx graph reflects the edges."""
    import duckdb
    from olav_netops.sim import load_network_model

    db = tmp_path / "test.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("CREATE SCHEMA netops")
        conn.execute(
            """
            CREATE TABLE netops.topology_links (
                link_id VARCHAR,
                source_device VARCHAR,
                source_interface VARCHAR,
                destination_device VARCHAR,
                destination_interface VARCHAR,
                discovery_protocol VARCHAR,
                link_type VARCHAR,
                link_status VARCHAR,
                first_seen TIMESTAMP,
                last_seen TIMESTAMP,
                snapshot_id VARCHAR
            )
            """
        )
        conn.execute(
            "INSERT INTO netops.topology_links VALUES "
            "('l1', 'R1', 'Gi0/1', 'R2', 'Gi0/2', 'LLDP', 'ethernet', 'up', "
            "NOW(), NOW(), 'snap_a'),"
            "('l2', 'R2', 'Gi0/3', 'R3', 'Gi0/4', 'LLDP', 'ethernet', 'up', "
            "NOW(), NOW(), 'snap_a'),"
            "('l3', 'R3', 'Gi0/5', 'R1', 'Gi0/6', 'LLDP', 'ethernet', 'up', "
            "NOW(), NOW(), 'snap_a')"
        )

    m = load_network_model(snapshot="snap_a", db_path=db)
    phys = m.physical

    if not HAS_NETWORKX:
        assert phys.links == []
        assert phys.graph is None
        return

    assert len(phys.links) == 3
    assert phys.graph is not None
    assert phys.graph.number_of_nodes() == 3
    assert phys.graph.number_of_edges() == 3
    assert set(phys.devices()) == {"R1", "R2", "R3"}
    assert set(phys.neighbors("R2")) == {"R1", "R3"}


def test_scope_filter_applied(tmp_path):
    """scope=[hosts] must restrict the edges loaded into the graph."""
    import duckdb
    from olav_netops.sim import load_network_model

    db = tmp_path / "test.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("CREATE SCHEMA netops")
        conn.execute(
            """
            CREATE TABLE netops.topology_links (
                link_id VARCHAR,
                source_device VARCHAR,
                source_interface VARCHAR,
                destination_device VARCHAR,
                destination_interface VARCHAR,
                discovery_protocol VARCHAR,
                link_type VARCHAR,
                link_status VARCHAR,
                first_seen TIMESTAMP,
                last_seen TIMESTAMP,
                snapshot_id VARCHAR
            )
            """
        )
        conn.execute(
            "INSERT INTO netops.topology_links VALUES "
            "('l1', 'R1', 'a', 'R2', 'b', 'LLDP', 'ethernet', 'up', NOW(), NOW(), 's1'),"
            "('l2', 'R3', 'c', 'R4', 'd', 'LLDP', 'ethernet', 'up', NOW(), NOW(), 's1')"
        )

    m = load_network_model(snapshot="s1", scope=["R1", "R2"], db_path=db)
    phys = m.physical
    if not HAS_NETWORKX:
        assert phys.links == []
        assert phys.graph is None
        return
    # Only the R1-R2 edge survives the scope filter.
    assert len(phys.links) == 1
    assert set(phys.graph.nodes) == {"R1", "R2"}


def test_devices_defaults_to_all_topology_nodes(tmp_path):
    """Without ``scope``, model.devices enumerates every hostname in the
    physical topology — sanity for operators running "show me the whole
    graph"."""
    import duckdb
    from olav_netops.sim import load_network_model

    db = tmp_path / "test.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("CREATE SCHEMA netops")
        conn.execute(
            """
            CREATE TABLE netops.topology_links (
                link_id VARCHAR,
                source_device VARCHAR,
                source_interface VARCHAR,
                destination_device VARCHAR,
                destination_interface VARCHAR,
                discovery_protocol VARCHAR,
                link_type VARCHAR,
                link_status VARCHAR,
                first_seen TIMESTAMP,
                last_seen TIMESTAMP,
                snapshot_id VARCHAR
            )
            """
        )
        conn.execute(
            "INSERT INTO netops.topology_links VALUES "
            "('l1', 'Rx', 'a', 'Ry', 'b', 'LLDP', '', 'up', NOW(), NOW(), 'snap')"
        )

    m = load_network_model(db_path=db)
    if not HAS_NETWORKX:
        assert m.devices == []
        return
    assert set(m.devices) == {"Rx", "Ry"}
