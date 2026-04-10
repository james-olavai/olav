"""UKS Full E2E Tests — Real end-to-end knowledge lifecycle without LLM.

Covers the complete pipeline:
  1. Import → search returns document-origin entries
  2. Vault sync lifecycle (insert/update/delete diff)
  3. Graph generation and vis.js HTML export
  4. Obsidian vault export structure
  5. Origin integrity (document vs user vs agent)
  6. CLI pipeline: import → status → sync → graph via subprocess

No LLM or API key required: `_embed()` is patched to return deterministic
vectors so all search/similarity logic exercises real code paths.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PYTHON = sys.executable
DIM = 32

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_store(tmp_path, dim=DIM):
    from olav.core.memory import LanceDBStore
    return LanceDBStore(db_path=str(tmp_path / "e2e.db"), embedding_dim=dim)


def _unit_vec(i: int, dim: int = DIM) -> list[float]:
    """Return a deterministic unit-ish vector with peak at position i % dim."""
    v = [0.0] * dim
    v[i % dim] = 1.0
    return v


def _embed_stub(text: str) -> list[float]:
    """Deterministic stub: vector uniquely encodes text hash so similar texts cluster."""
    import hashlib
    h = int(hashlib.md5(text.encode()).hexdigest(), 16)
    v = [0.0] * DIM
    v[h % DIM] = 1.0
    v[(h // DIM) % DIM] = 0.5
    total = sum(v)
    return [x / total for x in v]


def _run_kb(*args, env_extra=None, cwd=None, timeout=30):
    """Run `python -m olav.cli.main kb <args>` and return (rc, stdout, stderr)."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [_PYTHON, "-m", "olav.cli.main", "kb", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd or _ROOT),
        env=env,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def _write_md(directory: Path, filename: str, content: str) -> Path:
    """Write a markdown file and return its path."""
    p = directory / filename
    p.write_text(content, encoding="utf-8")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# 1. Import-to-Search Pipeline
# ─────────────────────────────────────────────────────────────────────────────


class TestImportToSearch:
    """Import a markdown file → search returns entries with origin='document'."""

    def test_import_single_file_creates_document_entries(self, tmp_path):
        """kb_import() inserts chunks with origin='document' into the store."""
        store = _make_store(tmp_path)
        store.create_table()

        md_file = _write_md(tmp_path, "bgp_guide.md", """\
---
tags: [bgp, routing]
category: fact
---

# BGP Routing Guide

Border Gateway Protocol (BGP) is the routing protocol of the Internet.
It operates on TCP port 179 and uses autonomous system numbers.

## BGP Session States

BGP sessions progress through several states: Idle, Connect, Active,
OpenSent, OpenConfirm, and Established.
""")
        with mock.patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
            from olav.core.memory.sync import kb_import
            result = kb_import(store, md_file)

        assert result["status"] == "success", f"Import failed: {result}"
        assert result["chunks"] >= 1, f"Expected ≥1 chunk, got {result['chunks']}"

        memories = store.get_memories(limit=100)
        doc_entries = [m for m in memories if m.get("origin") == "document"]
        assert len(doc_entries) >= 1, (
            f"No document-origin entries found. Origins: "
            f"{[m.get('origin') for m in memories]}"
        )

    def test_import_preserves_tags_from_frontmatter(self, tmp_path):
        """kb_import() extracts tags from YAML frontmatter and stores them."""
        store = _make_store(tmp_path)
        store.create_table()

        md_file = _write_md(tmp_path, "ospf.md", """\
---
tags: [ospf, igp, routing]
---

# OSPF Design

OSPF is a link-state routing protocol that uses Dijkstra's SPF algorithm.
""")
        with mock.patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
            from olav.core.memory.sync import kb_import
            kb_import(store, md_file)

        memories = store.get_memories(limit=100)
        assert memories, "No entries after import"
        tags_found = False
        for m in memories:
            tags_raw = m.get("tags", "[]")
            try:
                tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
            except Exception:
                tags = []
            if tags:
                tags_found = True
                break
        assert tags_found, (
            f"No tags found in any imported entry. "
            f"tags values: {[m.get('tags') for m in memories]}"
        )

    def test_search_finds_imported_content(self, tmp_path):
        """After kb_import(), search_by_vector() returns the imported entry."""
        store = _make_store(tmp_path)
        store.create_table()

        content = "EVPN Type-5 route leaking between VRFs requires BGP configuration."
        md_file = _write_md(tmp_path, "evpn.md", f"# EVPN\n\n{content}\n")

        query_vec = _embed_stub(content)
        with mock.patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
            from olav.core.memory.sync import kb_import
            kb_import(store, md_file)

        results = store.search_by_vector(query_vector=query_vec, limit=10)
        assert results, "search_by_vector returned no results after import"
        origins = {r.get("origin") for r in results}
        assert "document" in origins, (
            f"Expected 'document' in search results. Origins: {origins}"
        )

    def test_import_confidence_defaults_to_1_0_for_document(self, tmp_path):
        """Imported document entries must have confidence=1.0 by default."""
        store = _make_store(tmp_path)
        store.create_table()

        md_file = _write_md(tmp_path, "fact.md", "# Facts\n\nSome factual content here.\n")
        with mock.patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
            from olav.core.memory.sync import kb_import
            kb_import(store, md_file, origin="document")

        memories = store.get_memories(limit=100)
        doc_entries = [m for m in memories if m.get("origin") == "document"]
        assert doc_entries, "No document entries found"
        for entry in doc_entries:
            conf = float(entry.get("confidence") or 0)
            assert conf == 1.0, (
                f"Expected confidence=1.0 for document entry, got {conf}"
            )

    def test_import_multiple_files_all_searchable(self, tmp_path):
        """Multiple imported files should all be findable via search."""
        store = _make_store(tmp_path)
        store.create_table()

        files = {
            "bgp.md": "# BGP\n\nBGP autonomous systems and path selection.\n",
            "ospf.md": "# OSPF\n\nOSPF link-state database synchronization.\n",
            "isis.md": "# IS-IS\n\nIS-IS intermediate system routing protocol.\n",
        }
        with mock.patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
            from olav.core.memory.sync import kb_import
            for fname, content in files.items():
                result = kb_import(store, _write_md(tmp_path, fname, content))
                assert result["status"] == "success", f"Failed to import {fname}: {result}"

        memories = store.get_memories(limit=100)
        doc_entries = [m for m in memories if m.get("origin") == "document"]
        assert len(doc_entries) >= len(files), (
            f"Expected ≥{len(files)} document entries, got {len(doc_entries)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Vault Sync Lifecycle
# ─────────────────────────────────────────────────────────────────────────────


class TestSyncLifecycle:
    """Full insert → update → delete diff sync lifecycle."""

    def test_sync_inserts_new_files(self, tmp_path):
        """First sync: new .md files are inserted into LanceDB."""
        store = _make_store(tmp_path)
        store.create_table()
        vault = tmp_path / "vault"
        vault.mkdir()

        _write_md(vault, "bgp.md", "# BGP\n\nBGP path selection algorithm.\n")
        _write_md(vault, "ospf.md", "# OSPF\n\nOSPF SPF calculation.\n")

        with mock.patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
            from olav.core.memory.sync import sync_from_files
            result = sync_from_files(store, vault)

        assert result["inserted"] == 2, f"Expected 2 inserted, got {result}"
        assert result["errors"] == 0, f"Errors: {result}"

        memories = store.get_memories(limit=100)
        assert len(memories) >= 2, f"Expected ≥2 entries in store, got {len(memories)}"

    def test_sync_unchanged_files_are_skipped(self, tmp_path):
        """Second sync with no changes: all files skipped (0 inserted)."""
        store = _make_store(tmp_path)
        store.create_table()
        vault = tmp_path / "vault"
        vault.mkdir()

        _write_md(vault, "bgp.md", "# BGP\n\nBGP sessions use TCP port 179.\n")

        with mock.patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
            from olav.core.memory.sync import sync_from_files
            sync_from_files(store, vault)
            result2 = sync_from_files(store, vault)

        assert result2["inserted"] == 0, f"Expected 0 inserted on unchanged, got {result2}"
        assert result2["skipped"] == 1, f"Expected 1 skipped, got {result2}"

    def test_sync_modified_file_updates_entries(self, tmp_path):
        """Modified file on second sync: old entries deleted, new ones inserted."""
        store = _make_store(tmp_path)
        store.create_table()
        vault = tmp_path / "vault"
        vault.mkdir()

        f = _write_md(vault, "bgp.md", "# BGP\n\nOriginal content about BGP.\n")

        with mock.patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
            from olav.core.memory.sync import sync_from_files
            sync_from_files(store, vault)
            count_before = len(store.get_memories(limit=100))

            # Modify the file
            f.write_text("# BGP Updated\n\nUpdated content — BGP route reflectors explained.\n")
            result2 = sync_from_files(store, vault)

        assert result2["updated"] == 1, f"Expected 1 updated, got {result2}"
        assert result2["errors"] == 0, f"Update errors: {result2}"

        memories_after = store.get_memories(limit=100)
        # Text should reflect the new content
        texts = [m.get("text", "") for m in memories_after]
        assert any("Updated" in t or "reflector" in t for t in texts), (
            f"Updated content not found in store. Texts: {texts}"
        )

    def test_sync_deleted_file_removes_entries(self, tmp_path):
        """File deleted from vault: entries removed from LanceDB on next sync."""
        store = _make_store(tmp_path)
        store.create_table()
        vault = tmp_path / "vault"
        vault.mkdir()

        to_delete = _write_md(vault, "temp.md", "# Temporary\n\nThis file will be deleted.\n")
        keeper = _write_md(vault, "keeper.md", "# Keeper\n\nThis file stays.\n")

        with mock.patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
            from olav.core.memory.sync import sync_from_files
            sync_from_files(store, vault)
            ids_before = {m["id"] for m in store.get_memories(limit=100)}

            to_delete.unlink()
            result2 = sync_from_files(store, vault)

        assert result2["deleted"] == 1, f"Expected 1 deleted, got {result2}"
        ids_after = {m["id"] for m in store.get_memories(limit=100)}
        assert len(ids_after) < len(ids_before), (
            f"Expected fewer entries after delete. Before: {len(ids_before)}, After: {len(ids_after)}"
        )

    def test_sync_dry_run_does_not_modify_store(self, tmp_path):
        """dry_run=True reports changes but does NOT write to LanceDB."""
        store = _make_store(tmp_path)
        store.create_table()
        vault = tmp_path / "vault"
        vault.mkdir()

        _write_md(vault, "bgp.md", "# BGP\n\nBGP policy configuration.\n")

        with mock.patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
            from olav.core.memory.sync import sync_from_files
            result = sync_from_files(store, vault, dry_run=True)

        assert result["dry_run"] is True
        assert result["inserted"] == 1, f"Dry run should report 1 would-be insert, got {result}"

        memories = store.get_memories(limit=100)
        assert len(memories) == 0, (
            f"dry_run=True must not write to store. Found {len(memories)} entries."
        )

    def test_sync_origin_user_for_user_vault(self, tmp_path):
        """sync_from_files() with origin='user' tags all entries as origin='user'."""
        store = _make_store(tmp_path)
        store.create_table()
        vault = tmp_path / "vault"
        vault.mkdir()

        _write_md(vault, "notes.md", "# My Notes\n\nPersonal networking notes.\n")

        with mock.patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
            from olav.core.memory.sync import sync_from_files
            sync_from_files(store, vault, origin="user")

        memories = store.get_memories(limit=100)
        user_entries = [m for m in memories if m.get("origin") == "user"]
        assert user_entries, (
            f"Expected user-origin entries. Got: {[m.get('origin') for m in memories]}"
        )

    def test_sync_state_file_created(self, tmp_path):
        """After sync, a .olav_sync_state.json state file is created in vault dir."""
        store = _make_store(tmp_path)
        store.create_table()
        vault = tmp_path / "vault"
        vault.mkdir()

        _write_md(vault, "doc.md", "# Doc\n\nContent.\n")

        with mock.patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
            from olav.core.memory.sync import sync_from_files
            sync_from_files(store, vault)

        state_file = vault / ".olav_sync_state.json"
        assert state_file.exists(), "Sync state file not created"
        state = json.loads(state_file.read_text())
        assert "doc.md" in state, f"doc.md not in state: {state}"
        assert "hash" in state["doc.md"], "State entry missing 'hash' field"
        assert "ids" in state["doc.md"], "State entry missing 'ids' field"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Graph Generation and vis.js Export
# ─────────────────────────────────────────────────────────────────────────────


class TestGraphExport:
    """materialize_graph → export_visjs produces valid HTML."""

    def _populate_store(self, store):
        """Seed the store with a set of related knowledge entries."""
        store.create_table()
        entries = [
            ("bgp-001", "BGP AS path selection and route advertisement.", [1.0, 0.1] + [0.0] * (DIM - 2), ["bgp", "routing"]),
            ("bgp-002", "BGP session establishment on TCP port 179.", [0.9, 0.2] + [0.0] * (DIM - 2), ["bgp", "tcp"]),
            ("ospf-001", "OSPF link-state database synchronization.", [0.0, 1.0] + [0.0] * (DIM - 2), ["ospf", "igp"]),
            ("ospf-002", "OSPF SPF algorithm and shortest path tree.", [0.1, 0.9] + [0.0] * (DIM - 2), ["ospf", "algorithm"]),
            ("evpn-001", "EVPN type-5 prefix advertisement.", [0.5, 0.5] + [0.0] * (DIM - 2), ["evpn", "bgp"]),
        ]
        for mem_id, text, vector, tags in entries:
            store.add_memory(
                id=mem_id,
                text=text,
                vector=vector,
                category="fact",
                scope="global",
                origin="document",
                confidence=1.0,
                tags=json.dumps(tags),
            )

    def test_materialize_graph_produces_nodes_and_edges(self, tmp_path):
        """materialize_graph() returns a dict with 'nodes' and 'edges' lists."""
        store = _make_store(tmp_path)
        self._populate_store(store)

        from olav.core.memory.knowledge_graph import materialize_graph
        graph = materialize_graph(store, similarity_threshold=0.5)

        assert "nodes" in graph, "materialize_graph missing 'nodes' key"
        assert "edges" in graph, "materialize_graph missing 'edges' key"
        # Memory nodes (non-entity) should match the 5 seeded entries
        memory_nodes = [n for n in graph["nodes"] if n.get("type") != "entity"]
        assert len(memory_nodes) == 5, (
            f"Expected 5 memory nodes, got {len(memory_nodes)} "
            f"(total nodes={len(graph['nodes'])})"
        )
        assert isinstance(graph["edges"], list)

    def test_export_visjs_creates_html_file(self, tmp_path):
        """export_visjs() writes a .html file with vis.js network content."""
        store = _make_store(tmp_path)
        self._populate_store(store)
        output_html = tmp_path / "knowledge_graph.html"

        from olav.core.memory.knowledge_graph import materialize_graph, export_visjs
        graph = materialize_graph(store)
        export_visjs(graph, output_html)

        assert output_html.exists(), f"HTML file not created at {output_html}"
        content = output_html.read_text()
        assert "<html" in content.lower() or "<!DOCTYPE" in content.lower() or "vis" in content.lower(), (
            f"HTML file doesn't look like HTML: {content[:200]}"
        )

    def test_export_visjs_html_contains_node_ids(self, tmp_path):
        """vis.js HTML must embed the node IDs from the knowledge store."""
        store = _make_store(tmp_path)
        self._populate_store(store)
        output_html = tmp_path / "kg.html"

        from olav.core.memory.knowledge_graph import materialize_graph, export_visjs
        graph = materialize_graph(store)
        export_visjs(graph, output_html)

        content = output_html.read_text()
        # At least some node IDs should appear in the HTML
        found = sum(1 for node in graph["nodes"] if node["id"] in content)
        assert found >= 1, (
            f"No node IDs found in HTML. Nodes: {[n['id'] for n in graph['nodes']]}"
        )

    def test_graph_edges_reflect_vector_similarity(self, tmp_path):
        """BGP entries with similar vectors should have a similarity edge."""
        store = _make_store(tmp_path)
        self._populate_store(store)

        from olav.core.memory.knowledge_graph import materialize_graph
        # Low threshold to catch BGP-001/BGP-002 (cos~0.97)
        graph = materialize_graph(store, similarity_threshold=0.8)

        bgp_edges = [
            e for e in graph["edges"]
            if ("bgp-001" in (e.get("source"), e.get("target"))
                and "bgp-002" in (e.get("source"), e.get("target")))
        ]
        assert bgp_edges, (
            f"Expected similarity edge between bgp-001 and bgp-002. "
            f"All edges: {graph['edges']}"
        )

    def test_graph_empty_store_returns_empty_structure(self, tmp_path):
        """materialize_graph() on empty store returns nodes=[] edges=[]."""
        store = _make_store(tmp_path)
        store.create_table()

        from olav.core.memory.knowledge_graph import materialize_graph
        graph = materialize_graph(store)

        assert graph["nodes"] == [], f"Empty store should yield no nodes: {graph['nodes']}"
        assert graph["edges"] == [], f"Empty store should yield no edges: {graph['edges']}"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Obsidian Vault Export
# ─────────────────────────────────────────────────────────────────────────────


class TestObsidianExport:
    """export_obsidian() creates a valid Obsidian-compatible vault."""

    def _seed_mixed_store(self, store):
        """Seed entries with document and agent origins."""
        store.create_table()
        entries = [
            ("doc-net-001", "BGP route reflector configuration guide.", "document", ["bgp", "routing"]),
            ("doc-net-002", "OSPF area design best practices.", "document", ["ospf"]),
            ("agent-001", "BGP session flapped on spine01.", "agent", ["bgp", "alert"]),
        ]
        for mem_id, text, origin, tags in entries:
            store.add_memory(
                id=mem_id,
                text=text,
                vector=[0.1] * DIM,
                category="fact",
                scope="global",
                origin=origin,
                confidence=1.0 if origin == "document" else 0.8,
                tags=json.dumps(tags),
            )

    def test_export_creates_output_directory(self, tmp_path):
        """export_obsidian() must create the output directory."""
        store = _make_store(tmp_path)
        self._seed_mixed_store(store)
        output_dir = tmp_path / "vault_export"

        from olav.core.memory.knowledge_graph import export_obsidian
        result = export_obsidian(store, output_dir)

        assert output_dir.exists(), f"Output directory not created: {output_dir}"
        assert result["written"] >= 1, f"Expected ≥1 written, got {result}"

    def test_export_creates_subdirectories_by_origin(self, tmp_path):
        """export_obsidian() organises entries into subdirs by origin."""
        store = _make_store(tmp_path)
        self._seed_mixed_store(store)
        output_dir = tmp_path / "vault"

        from olav.core.memory.knowledge_graph import export_obsidian
        export_obsidian(store, output_dir)

        subdirs = {p.name for p in output_dir.iterdir() if p.is_dir()}
        assert len(subdirs) >= 1, f"Expected origin subdirs, got: {list(output_dir.iterdir())}"

    def test_export_writes_markdown_files(self, tmp_path):
        """export_obsidian() writes .md files for entries."""
        store = _make_store(tmp_path)
        self._seed_mixed_store(store)
        output_dir = tmp_path / "vault"

        from olav.core.memory.knowledge_graph import export_obsidian
        result = export_obsidian(store, output_dir)

        md_files = list(output_dir.rglob("*.md"))
        assert len(md_files) >= 1, (
            f"No .md files in vault export. result={result}, "
            f"files found: {list(output_dir.rglob('*'))}"
        )

    def test_export_result_counts_match_store(self, tmp_path):
        """export_obsidian() result['written'] equals number of entries in store."""
        store = _make_store(tmp_path)
        self._seed_mixed_store(store)
        output_dir = tmp_path / "vault"

        from olav.core.memory.knowledge_graph import export_obsidian
        result = export_obsidian(store, output_dir)

        memories = store.get_memories(limit=100)
        assert result["written"] == len(memories), (
            f"written={result['written']} != store entries={len(memories)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Origin Integrity
# ─────────────────────────────────────────────────────────────────────────────


class TestOriginIntegrity:
    """Origin values are preserved correctly throughout the full pipeline."""

    def test_kb_import_always_document_origin(self, tmp_path):
        """kb_import() always produces origin='document' regardless of file content."""
        store = _make_store(tmp_path)
        store.create_table()
        md = _write_md(tmp_path, "x.md", "# X\n\nSome content.\n")

        with mock.patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
            from olav.core.memory.sync import kb_import
            kb_import(store, md, origin="document")

        for m in store.get_memories(limit=100):
            assert m.get("origin") == "document", (
                f"Expected origin='document', got '{m.get('origin')}'"
            )

    def test_sync_user_origin_propagated_to_entries(self, tmp_path):
        """sync_from_files(..., origin='user') → all entries have origin='user'."""
        store = _make_store(tmp_path)
        store.create_table()
        vault = tmp_path / "vault"
        vault.mkdir()
        _write_md(vault, "notes.md", "# Notes\n\nUser notes content.\n")

        with mock.patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
            from olav.core.memory.sync import sync_from_files
            sync_from_files(store, vault, origin="user")

        for m in store.get_memories(limit=100):
            assert m.get("origin") == "user", (
                f"Expected origin='user', got '{m.get('origin')}'"
            )

    def test_frontmatter_origin_overrides_default(self, tmp_path):
        """Frontmatter 'origin: document' overrides the default sync origin='user'."""
        store = _make_store(tmp_path)
        store.create_table()
        vault = tmp_path / "vault"
        vault.mkdir()
        _write_md(vault, "doc.md", """\
---
origin: document
---

# Official Doc

Published specification content.
""")

        with mock.patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
            from olav.core.memory.sync import sync_from_files
            sync_from_files(store, vault, origin="user")

        for m in store.get_memories(limit=100):
            assert m.get("origin") == "document", (
                f"Frontmatter origin override failed. Got '{m.get('origin')}'"
            )

    def test_agent_entry_coexists_with_document_in_search(self, tmp_path):
        """store has agent + document entries; search returns both."""
        store = _make_store(tmp_path)
        store.create_table()

        v = [1.0] + [0.0] * (DIM - 1)
        store.add_memory(
            id="agent-e2e-001",
            text="BGP peer down on spine01.",
            vector=v,
            category="fact",
            scope="global",
            origin="agent",
            confidence=0.9,
            tags="[]",
        )

        md = _write_md(tmp_path, "bgp.md", "# BGP\n\nBGP peer configuration guide.\n")
        with mock.patch("olav.core.memory.sync._embed", return_value=v):
            from olav.core.memory.sync import kb_import
            kb_import(store, md, origin="document")

        results = store.search_by_vector(query_vector=v, limit=10)
        origins = {r.get("origin") for r in results}
        assert "agent" in origins, f"agent origin missing from search: {origins}"
        assert "document" in origins, f"document origin missing from search: {origins}"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Full CLI Pipeline (subprocess)
# ─────────────────────────────────────────────────────────────────────────────


class TestFullCLIPipeline:
    """End-to-end CLI: import → status → sync → graph via subprocess."""

    def test_cli_import_then_status_shows_document_count(self, tmp_path):
        """CLI: `kb import <file>` then `kb status` shows document entries."""
        md_file = _write_md(tmp_path, "bgp_guide.md", """\
# BGP Guide

BGP (Border Gateway Protocol) is the routing protocol of the Internet.
It uses TCP port 179 and maintains routing tables across AS boundaries.
""")
        env = {
            "OLAV_MEMORY_DB_PATH": str(tmp_path / "mem.db"),
        }
        rc, stdout, stderr = _run_kb("import", str(md_file), env_extra=env)
        assert rc == 0, f"kb import failed: rc={rc}\nstdout={stdout}\nstderr={stderr}"
        assert "chunk" in (stdout + stderr).lower(), (
            f"Expected 'chunk' in import output:\n{stdout}\n{stderr}"
        )

        rc2, stdout2, stderr2 = _run_kb("status", env_extra=env)
        assert rc2 == 0, f"kb status failed: rc={rc2}\nstdout={stdout2}\nstderr={stderr2}"
        combined = stdout2 + stderr2
        # After import, should show total > 0
        nums = re.findall(r"\d+", combined)
        has_nonzero = any(int(n) > 0 for n in nums)
        assert has_nonzero, (
            f"kb status shows all zeros after import:\n{combined}"
        )

    def test_cli_sync_then_status(self, tmp_path):
        """CLI: `kb sync --dir <vault>` then `kb status` reflects synced entries."""
        vault = tmp_path / "vault"
        vault.mkdir()
        _write_md(vault, "ospf.md", "# OSPF\n\nOSPF routing protocol design.\n")
        _write_md(vault, "bgp.md", "# BGP\n\nBGP inter-domain routing.\n")

        env = {
            "OLAV_MEMORY_DB_PATH": str(tmp_path / "mem.db"),
        }
        rc, stdout, stderr = _run_kb("sync", "--dir", str(vault), env_extra=env)
        assert rc == 0, f"kb sync failed: rc={rc}\nstdout={stdout}\nstderr={stderr}"
        assert "inserted" in (stdout + stderr).lower(), (
            f"Expected 'inserted' in sync output:\n{stdout}\n{stderr}"
        )

        rc2, stdout2, _ = _run_kb("status", env_extra=env)
        assert rc2 == 0
        nums = re.findall(r"\d+", stdout2)
        assert any(int(n) > 0 for n in nums), (
            f"kb status shows all zeros after sync:\n{stdout2}"
        )

    def test_cli_graph_creates_html_after_import(self, tmp_path):
        """CLI: after `kb import`, `kb graph --output <file>` creates an HTML file."""
        md_file = _write_md(tmp_path, "evpn.md", """\
# EVPN

EVPN is a BGP address family for Ethernet VPN services.
It supports Type-2 (MAC/IP) and Type-5 (IP prefix) routes.
""")
        output_html = tmp_path / "kg.html"
        env = {
            "OLAV_MEMORY_DB_PATH": str(tmp_path / "mem.db"),
        }

        _run_kb("import", str(md_file), env_extra=env)
        rc, stdout, stderr = _run_kb("graph", "--output", str(output_html), env_extra=env)

        assert rc == 0, f"kb graph failed: rc={rc}\nstdout={stdout}\nstderr={stderr}"
        assert output_html.exists(), (
            f"Graph HTML not created at {output_html}\nstdout={stdout}\nstderr={stderr}"
        )
        html_content = output_html.read_text()
        assert len(html_content) > 100, f"HTML file too small: {len(html_content)} bytes"

    def test_cli_export_after_import(self, tmp_path):
        """CLI: after `kb import`, `kb export --dir <dir>` creates vault structure."""
        md_file = _write_md(tmp_path, "isis.md", """\
# IS-IS Routing

IS-IS is a link-state IGP used in large service provider networks.
""")
        export_dir = tmp_path / "export"
        env = {
            "OLAV_MEMORY_DB_PATH": str(tmp_path / "mem.db"),
            "OLAV_KB_EXPORT_DIR": str(export_dir),
        }

        _run_kb("import", str(md_file), env_extra=env)
        rc, stdout, stderr = _run_kb("export", "--dir", str(export_dir), env_extra=env)

        assert rc == 0, f"kb export failed: rc={rc}\nstdout={stdout}\nstderr={stderr}"
        combined = stdout + stderr
        assert any(kw in combined.lower() for kw in ("exported", "written", "entries", "0")), (
            f"Unexpected export output:\n{combined}"
        )

    def test_cli_migrate_runs_cleanly(self, tmp_path):
        """CLI: `kb migrate` runs with exit 0 even on empty store."""
        env = {
            "OLAV_MEMORY_DB_PATH": str(tmp_path / "mem.db"),
        }
        rc, stdout, stderr = _run_kb("migrate", env_extra=env)
        assert rc == 0, f"kb migrate failed: rc={rc}\nstdout={stdout}\nstderr={stderr}"
        combined = stdout + stderr
        assert "migration" in combined.lower() or "updated" in combined.lower(), (
            f"Unexpected migrate output:\n{combined}"
        )

    def test_cli_sync_dry_run_reports_changes_without_writing(self, tmp_path):
        """CLI: `kb sync --dry-run` reports changes without modifying the store."""
        vault = tmp_path / "vault"
        vault.mkdir()
        _write_md(vault, "bgp.md", "# BGP\n\nBGP policy routing.\n")

        env = {
            "OLAV_MEMORY_DB_PATH": str(tmp_path / "mem.db"),
        }
        rc, stdout, stderr = _run_kb(
            "sync", "--dir", str(vault), "--dry-run", env_extra=env
        )
        assert rc == 0, f"kb sync --dry-run failed: rc={rc}\n{stdout}\n{stderr}"
        combined = stdout + stderr
        assert "dry" in combined.lower() or "inserted" in combined.lower(), (
            f"Expected dry run indicator:\n{combined}"
        )

        # Store should still be empty
        env2 = {
            "OLAV_MEMORY_DB_PATH": str(tmp_path / "mem.db"),
        }
        rc2, stdout2, _ = _run_kb("status", env_extra=env2)
        # Total entries = 0
        assert "0" in stdout2 or "empty" in stdout2.lower(), (
            f"Store should be empty after dry-run, but status shows:\n{stdout2}"
        )
