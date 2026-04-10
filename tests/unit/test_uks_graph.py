"""Phase 3 TDD — Knowledge Graph materialization.

C-KB-10: materialize_graph returns nodes and edges dicts
C-KB-11: vector similarity creates implicit edges
C-KB-12: shared tags create explicit edges
C-KB-15: graspologic unavailable → cluster_knowledge returns None
"""

import json
import pytest

DIM = 32
DUMMY_VECTOR = [0.0] * DIM


def _make_store(tmp_path):
    from olav.core.memory import LanceDBStore
    return LanceDBStore(db_path=str(tmp_path / "graph.db"), embedding_dim=DIM)


def _add(store, id_, text, tags, vector=None, origin="agent"):
    import pyarrow as pa
    from datetime import datetime
    from olav.core.memory import MEMORY_TABLE

    if not store.table_exists(MEMORY_TABLE):
        store.create_table()

    v = vector if vector is not None else DUMMY_VECTOR
    tbl = store.get_table()
    ts = datetime.now()
    record = pa.table(
        [pa.array([id_]), pa.array([text]), pa.array([v]),
         pa.array(["fact"]), pa.array(["global"]), pa.array(["{}"]),
         pa.array([ts]), pa.array([ts]),
         pa.array([1]), pa.array([1.0]),
         pa.array([origin]), pa.array([0.8], type=pa.float32()), pa.array([json.dumps(tags)])],
        schema=store._get_schema(),
    )
    tbl.add(record)


# ─── C-KB-10: materialize_graph returns correct structure ────────────────────

def test_materialize_graph_returns_nodes_and_edges(tmp_path):
    """C-KB-10: materialize_graph() must return a dict with 'nodes' and 'edges' keys."""
    store = _make_store(tmp_path)
    _add(store, "n1", "BGP session established.", ["bgp"])
    _add(store, "n2", "OSPF neighbour up.", ["ospf"])

    from olav.core.memory.knowledge_graph import materialize_graph
    result = materialize_graph(store)

    assert isinstance(result, dict), "materialize_graph must return a dict"
    assert "nodes" in result, "result must have 'nodes' key"
    assert "edges" in result, "result must have 'edges' key"
    assert isinstance(result["nodes"], list), "'nodes' must be a list"
    assert isinstance(result["edges"], list), "'edges' must be a list"


def test_materialize_graph_node_count(tmp_path):
    """C-KB-10: each memory becomes a node (plus entity nodes for unique tags)."""
    store = _make_store(tmp_path)
    _add(store, "n1", "Fact about BGP.", ["bgp"])
    _add(store, "n2", "Fact about OSPF.", ["ospf"])

    from olav.core.memory.knowledge_graph import materialize_graph
    result = materialize_graph(store)

    memory_node_ids = {n["id"] for n in result["nodes"]}
    assert "n1" in memory_node_ids
    assert "n2" in memory_node_ids


def test_materialize_graph_node_fields(tmp_path):
    """C-KB-10: each node must have id, label, origin, category, confidence."""
    store = _make_store(tmp_path)
    _add(store, "n1", "Fact A.", ["bgp"], origin="document")

    from olav.core.memory.knowledge_graph import materialize_graph
    result = materialize_graph(store)

    mem_nodes = [n for n in result["nodes"] if n["id"] == "n1"]
    assert len(mem_nodes) == 1
    node = mem_nodes[0]
    assert "label" in node
    assert node.get("origin") == "document"
    assert "category" in node
    assert "confidence" in node


# ─── C-KB-11: implicit edges via vector similarity ───────────────────────────

def test_similar_vectors_create_implicit_edges(tmp_path):
    """C-KB-11: memories with similar vectors get implicit 'similar' edges."""
    store = _make_store(tmp_path)
    # Two identical vectors → max similarity
    v_close = [1.0] + [0.0] * (DIM - 1)
    _add(store, "sim-1", "BGP MTU issue on spine01.", ["bgp", "spine01"], vector=v_close)
    _add(store, "sim-2", "MTU mismatch causes BGP flap.", ["bgp", "mtu"], vector=v_close)
    # Orthogonal vector → no similarity edge
    v_far = [0.0] * (DIM - 1) + [1.0]
    _add(store, "far-1", "DNS lookup failed.", ["dns"], vector=v_far)

    from olav.core.memory.knowledge_graph import materialize_graph
    result = materialize_graph(store, similarity_threshold=0.9)

    similar_edges = [
        e for e in result["edges"]
        if e.get("type") == "similar"
        and {e["source"], e["target"]} == {"sim-1", "sim-2"}
    ]
    assert len(similar_edges) >= 1, (
        f"Expected at least 1 similar edge between sim-1 and sim-2, "
        f"got edges: {result['edges']}"
    )


def test_similar_edges_have_weight(tmp_path):
    """C-KB-11: similar edges must have a 'weight' field (0.0-1.0)."""
    store = _make_store(tmp_path)
    v = [1.0] + [0.0] * (DIM - 1)
    _add(store, "w1", "Fact one.", ["a"], vector=v)
    _add(store, "w2", "Fact two.", ["b"], vector=v)

    from olav.core.memory.knowledge_graph import materialize_graph
    result = materialize_graph(store, similarity_threshold=0.9)

    sim_edges = [e for e in result["edges"] if e.get("type") == "similar"]
    for e in sim_edges:
        w = e.get("weight")
        assert w is not None, "similar edge must have 'weight'"
        assert 0.0 <= w <= 1.0, f"weight must be in [0,1], got {w}"


# ─── C-KB-12: explicit edges via shared tags ─────────────────────────────────

def test_shared_tags_create_explicit_edges(tmp_path):
    """C-KB-12: memories sharing a tag both connect to the same entity node."""
    store = _make_store(tmp_path)
    v_a = [1.0] + [0.0] * (DIM - 1)
    v_b = [0.0] + [1.0] + [0.0] * (DIM - 2)
    # Different vectors → no similarity edge; shared tag "spine01" → entity edge
    _add(store, "t1", "spine01 BGP config.", ["spine01"], vector=v_a)
    _add(store, "t2", "spine01 interface stats.", ["spine01"], vector=v_b)
    _add(store, "t3", "Unrelated memo.", ["ospf"], vector=[0.0] * (DIM - 1) + [1.0])

    from olav.core.memory.knowledge_graph import materialize_graph
    result = materialize_graph(store, similarity_threshold=0.0)  # disable sim edges

    tagged_edges = [e for e in result["edges"] if e.get("type") == "tagged"]
    t1_to_entity = [e for e in tagged_edges if e["source"] == "t1" and "spine01" in e["target"]]
    t2_to_entity = [e for e in tagged_edges if e["source"] == "t2" and "spine01" in e["target"]]
    assert len(t1_to_entity) >= 1, "t1 must have a 'tagged' edge to spine01 entity"
    assert len(t2_to_entity) >= 1, "t2 must have a 'tagged' edge to spine01 entity"


def test_entity_nodes_present_for_tags(tmp_path):
    """C-KB-12: each unique tag must produce an entity node in the graph."""
    store = _make_store(tmp_path)
    _add(store, "e1", "BGP note.", ["bgp", "r1"])
    _add(store, "e2", "Another BGP note.", ["bgp"])

    from olav.core.memory.knowledge_graph import materialize_graph
    result = materialize_graph(store)

    node_ids = {n["id"] for n in result["nodes"]}
    # Entity nodes must exist for both tags
    bgp_entity = any("bgp" in nid for nid in node_ids)
    r1_entity = any("r1" in nid for nid in node_ids)
    assert bgp_entity, f"Expected entity node for 'bgp', nodes: {node_ids}"
    assert r1_entity, f"Expected entity node for 'r1', nodes: {node_ids}"


# ─── C-KB-15: graspologic unavailable → cluster_knowledge returns None ───────

def test_cluster_knowledge_returns_none_without_graspologic(tmp_path):
    """C-KB-15: cluster_knowledge() returns None if graspologic is not installed."""
    store = _make_store(tmp_path)
    _add(store, "c1", "Node 1.", ["a"])
    _add(store, "c2", "Node 2.", ["b"])
    _add(store, "c3", "Node 3.", ["c"])

    from olav.core.memory.knowledge_graph import materialize_graph, cluster_knowledge
    import unittest.mock as mock

    graph_data = materialize_graph(store)

    # Simulate graspologic not installed
    with mock.patch.dict("sys.modules", {"graspologic": None,
                                          "graspologic.partition": None}):
        result = cluster_knowledge(graph_data)

    # Must return None (not raise) when graspologic unavailable
    assert result is None, (
        f"cluster_knowledge must return None when graspologic unavailable, got {result!r}"
    )


def test_cluster_knowledge_returns_none_for_tiny_graph(tmp_path):
    """C-KB-15: cluster_knowledge returns None if graph has < 3 nodes."""
    store = _make_store(tmp_path)
    _add(store, "tiny1", "Only node.", ["a"])

    from olav.core.memory.knowledge_graph import materialize_graph, cluster_knowledge
    graph_data = materialize_graph(store)
    result = cluster_knowledge(graph_data)

    # Should return None for trivial graphs (< 3 nodes)
    assert result is None
