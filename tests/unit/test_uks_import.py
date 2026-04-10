"""Phase 3 TDD — kb import: markdown file → origin="document".

C-KB-21: importing a .md file creates a memory entry with origin='document',
         confidence=1.0, and the correct text content
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

DIM = 32


def _make_store(tmp_path):
    from olav.core.memory import LanceDBStore
    return LanceDBStore(db_path=str(tmp_path / "import.db"), embedding_dim=DIM)


def _embed_stub(text: str) -> list[float]:
    return [float(len(text) % 100) / 100.0] * DIM


# ─── C-KB-21: import .md → origin="document" ─────────────────────────────────

def test_import_md_creates_document_memory(tmp_path):
    """C-KB-21: kb_import() of a .md file must create memory with origin='document'."""
    store = _make_store(tmp_path)
    store.create_table()

    md_file = tmp_path / "guide.md"
    md_file.write_text("# BGP Troubleshooting\n\nWhen BGP flaps, check MTU settings.\n")

    from olav.core.memory.sync import kb_import
    with patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
        result = kb_import(store, md_file)

    assert result["status"] == "success", f"Expected success, got {result}"
    memories = store.get_memories(limit=10)
    assert len(memories) >= 1
    doc_memories = [m for m in memories if m["origin"] == "document"]
    assert len(doc_memories) >= 1, (
        f"Expected at least 1 memory with origin='document', got origins={[m['origin'] for m in memories]}"
    )


def test_import_md_confidence_is_1(tmp_path):
    """C-KB-21: imported documents must have confidence=1.0."""
    store = _make_store(tmp_path)
    store.create_table()

    md_file = tmp_path / "reference.md"
    md_file.write_text("RFC 7752 defines BGP-LS. It allows distributing topology info.\n")

    from olav.core.memory.sync import kb_import
    with patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
        result = kb_import(store, md_file)

    assert result["status"] == "success"
    memories = store.get_memories(limit=10)
    for m in memories:
        assert abs(float(m["confidence"]) - 1.0) < 1e-4, (
            f"Imported memory confidence must be 1.0, got {m['confidence']}"
        )


def test_import_md_text_content(tmp_path):
    """C-KB-21: imported memory must contain the file's text content."""
    store = _make_store(tmp_path)
    store.create_table()

    content = "spine01 interface Ethernet49/1 has MTU 9214 configured.\n"
    md_file = tmp_path / "notes.md"
    md_file.write_text(content)

    from olav.core.memory.sync import kb_import
    with patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
        kb_import(store, md_file)

    memories = store.get_memories(limit=10)
    texts = [m["text"] for m in memories]
    assert any("spine01 interface" in t for t in texts), (
        f"File content not found in memories. Texts: {texts}"
    )


def test_import_md_with_frontmatter_tags(tmp_path):
    """C-KB-21: if the .md file has frontmatter tags, they must be stored."""
    store = _make_store(tmp_path)
    store.create_table()

    md_file = tmp_path / "tagged.md"
    md_file.write_text(
        "---\ntags: [bgp, troubleshooting]\n---\n\nBGP keepalive timer mismatch causes flap.\n"
    )

    from olav.core.memory.sync import kb_import
    with patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
        kb_import(store, md_file)

    memories = store.get_memories(limit=10)
    assert len(memories) >= 1
    # Tags should be set from frontmatter
    all_tags = []
    for m in memories:
        all_tags.extend(json.loads(m.get("tags", "[]")))
    assert "bgp" in all_tags or "troubleshooting" in all_tags, (
        f"Expected frontmatter tags in memory, got tags across all chunks: {all_tags}"
    )


def test_import_empty_file_returns_error(tmp_path):
    """C-KB-21: importing an empty file must return an error status (not crash)."""
    store = _make_store(tmp_path)
    store.create_table()

    empty_file = tmp_path / "empty.md"
    empty_file.write_text("")

    from olav.core.memory.sync import kb_import
    with patch("olav.core.memory.sync._embed", side_effect=_embed_stub):
        result = kb_import(store, empty_file)

    assert result["status"] == "error", (
        f"Expected error status for empty file, got {result}"
    )
