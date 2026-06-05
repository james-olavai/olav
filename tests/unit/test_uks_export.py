"""Phase 3 TDD — Obsidian and vis.js export.

C-KB-13: export_obsidian generates .md files with YAML frontmatter
C-KB-14: export_visjs generates an HTML file with vis.js content
"""

import json
import pytest
from pathlib import Path

DIM = 32
DUMMY_VECTOR = [0.0] * DIM


def _make_store(tmp_path):
    from olav.core.memory import LanceDBStore
    return LanceDBStore(db_path=str(tmp_path / "export.db"), embedding_dim=DIM)


def _add(store, id_, text, tags, origin="agent"):
    import pyarrow as pa
    from datetime import datetime
    from olav.core.memory import MEMORY_TABLE

    if not store.table_exists(MEMORY_TABLE):
        store.create_table()

    tbl = store.get_table()
    ts = datetime.now()
    record = pa.table(
        [pa.array([id_]), pa.array([text]), pa.array([DUMMY_VECTOR]),
         pa.array(["fact"]), pa.array(["global"]), pa.array(["{}"]),
         pa.array([ts]), pa.array([ts]),
         pa.array([1]), pa.array([1.0]),
         pa.array([origin]), pa.array([0.8], type=pa.float32()), pa.array([json.dumps(tags)]),
         pa.array([None], type=pa.timestamp("us", tz="UTC"))],  # expires_at (ADR-0015)
        schema=store._get_schema(),
    )
    tbl.add(record)


# ─── C-KB-13: export_obsidian ─────────────────────────────────────────────────

def test_export_obsidian_creates_md_files(tmp_path):
    """C-KB-13: export_obsidian writes one .md file per memory."""
    store = _make_store(tmp_path)
    _add(store, "obs-001", "BGP config note.", ["bgp"])
    _add(store, "obs-002", "OSPF area design.", ["ospf", "area"])

    vault_dir = tmp_path / "vault"
    from olav.core.memory.knowledge_graph import export_obsidian
    export_obsidian(store, vault_dir)

    md_files = list(vault_dir.rglob("*.md"))
    md_ids = {f.stem for f in md_files if not f.stem.startswith("entity_")}
    assert "obs-001" in md_ids, f"obs-001.md not found in {[f.name for f in md_files]}"
    assert "obs-002" in md_ids, f"obs-002.md not found in {[f.name for f in md_files]}"


def test_export_obsidian_frontmatter(tmp_path):
    """C-KB-13: each .md file must start with YAML frontmatter containing id, origin, category."""
    store = _make_store(tmp_path)
    _add(store, "fm-001", "Important fact.", ["routing"], origin="document")

    vault_dir = tmp_path / "vault"
    from olav.core.memory.knowledge_graph import export_obsidian
    export_obsidian(store, vault_dir)

    md_files = list(vault_dir.rglob("fm-001.md"))
    assert len(md_files) == 1, f"Expected fm-001.md, found: {[f.name for f in vault_dir.rglob('*.md')]}"

    content = md_files[0].read_text()
    assert content.startswith("---"), "File must start with YAML frontmatter (---)"
    assert "id: fm-001" in content, "Frontmatter must contain 'id:'"
    assert "origin: document" in content, "Frontmatter must contain 'origin:'"
    assert "category:" in content, "Frontmatter must contain 'category:'"


def test_export_obsidian_contains_text(tmp_path):
    """C-KB-13: the .md body must contain the original memory text."""
    store = _make_store(tmp_path)
    _add(store, "txt-001", "spine01 BGP peer flapping due to MTU.", ["bgp"])

    vault_dir = tmp_path / "vault"
    from olav.core.memory.knowledge_graph import export_obsidian
    export_obsidian(store, vault_dir)

    md_files = list(vault_dir.rglob("txt-001.md"))
    assert md_files
    content = md_files[0].read_text()
    assert "spine01 BGP peer flapping" in content, "Memory text must appear in the .md body"


def test_export_obsidian_entity_index(tmp_path):
    """C-KB-13: entity nodes must produce index .md files under _entities/."""
    store = _make_store(tmp_path)
    _add(store, "ent-001", "A BGP note.", ["spine01", "bgp"])
    _add(store, "ent-002", "Another spine01 note.", ["spine01"])

    vault_dir = tmp_path / "vault"
    from olav.core.memory.knowledge_graph import export_obsidian
    export_obsidian(store, vault_dir)

    entities_dir = vault_dir / "_entities"
    entity_files = {f.name for f in entities_dir.glob("*.md")} if entities_dir.exists() else set()
    assert any("spine01" in f for f in entity_files), (
        f"Expected entity_spine01.md in _entities/, found: {entity_files}"
    )


# ─── C-KB-14: export_visjs ────────────────────────────────────────────────────

def test_export_visjs_creates_html_file(tmp_path):
    """C-KB-14: export_visjs writes a single HTML file."""
    store = _make_store(tmp_path)
    _add(store, "vis-001", "Node one.", ["alpha"])
    _add(store, "vis-002", "Node two.", ["beta"])

    from olav.core.memory.knowledge_graph import materialize_graph, export_visjs
    graph_data = materialize_graph(store)
    output_html = tmp_path / "graph.html"
    export_visjs(graph_data, output_html)

    assert output_html.exists(), "export_visjs must create an HTML file"
    assert output_html.stat().st_size > 100, "HTML file must not be empty"


def test_export_visjs_html_contains_visjs(tmp_path):
    """C-KB-14: generated HTML must reference or embed vis.js/vis-network."""
    store = _make_store(tmp_path)
    _add(store, "vis-h1", "Graph node A.", ["a"])

    from olav.core.memory.knowledge_graph import materialize_graph, export_visjs
    graph_data = materialize_graph(store)
    output_html = tmp_path / "graph.html"
    export_visjs(graph_data, output_html)

    content = output_html.read_text()
    assert "vis" in content.lower(), "HTML must reference vis.js"
    assert "<html" in content.lower() or "<!doctype" in content.lower(), (
        "Output must be valid HTML"
    )


def test_export_visjs_embeds_node_data(tmp_path):
    """C-KB-14: the HTML file must embed the node IDs as JSON data."""
    store = _make_store(tmp_path)
    _add(store, "embed-001", "Embedded node.", ["tag1"])

    from olav.core.memory.knowledge_graph import materialize_graph, export_visjs
    graph_data = materialize_graph(store)
    output_html = tmp_path / "graph.html"
    export_visjs(graph_data, output_html)

    content = output_html.read_text()
    assert "embed-001" in content, "Node ID must appear in HTML content"
