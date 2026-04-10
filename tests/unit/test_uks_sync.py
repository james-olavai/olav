"""Phase 3 TDD — sync.py: Markdown-vault ↔ LanceDB differential sync.

C-KB-17: sync_from_files() UPDATEs entries that have changed on disk
C-KB-18: sync_from_files() INSERTs entries for new files
C-KB-19: sync_from_files() DELETEs entries when the file is removed
C-KB-20: sync_from_files(dry_run=True) does NOT modify data
"""

import json
import pytest
from pathlib import Path
import pyarrow as pa
from datetime import datetime

DIM = 32
DUMMY_VECTOR = [0.0] * DIM


def _make_store(tmp_path, sub="sync.db"):
    from olav.core.memory import LanceDBStore
    return LanceDBStore(db_path=str(tmp_path / sub), embedding_dim=DIM)


def _make_md(directory: Path, name: str, content: str,
             tags: list | None = None, origin: str = "user") -> Path:
    """Write a minimal knowledge markdown file."""
    path = directory / name
    frontmatter = f"---\norigin: {origin}\ntags: {json.dumps(tags or [])}\n---\n\n"
    path.write_text(frontmatter + content)
    return path


def _embed_stub(text: str) -> list[float]:
    """Deterministic stub: return a vector based on text length."""
    base = float(len(text) % 100) / 100.0
    v = [base] * DIM
    return v


# ─── C-KB-18: INSERT new files ────────────────────────────────────────────────

def test_sync_inserts_new_file(tmp_path):
    """C-KB-18: sync_from_files() stores a new markdown file as a memory."""
    store = _make_store(tmp_path)
    store.create_table()

    kb_dir = tmp_path / "knowledge" / "user"
    kb_dir.mkdir(parents=True)
    _make_md(kb_dir, "note1.md", "spine01 loopback is 10.255.0.1.", tags=["spine01"])

    from olav.core.memory.sync import sync_from_files
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "olav.core.memory.sync._embed", side_effect=_embed_stub
    ):
        result = sync_from_files(store, kb_dir)

    assert result["inserted"] >= 1, f"Expected >=1 insert, got {result}"
    memories = store.get_memories(limit=10)
    texts = [m["text"] for m in memories]
    assert any("spine01 loopback" in t for t in texts), (
        f"Inserted memory not found. Memories: {texts}"
    )


def test_sync_sets_origin_from_directory(tmp_path):
    """C-KB-18: memories synced from the 'user' directory must have origin='user'."""
    store = _make_store(tmp_path)
    store.create_table()

    kb_dir = tmp_path / "knowledge" / "user"
    kb_dir.mkdir(parents=True)
    _make_md(kb_dir, "note2.md", "Important user note about lab.", tags=["lab"])

    from olav.core.memory.sync import sync_from_files
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "olav.core.memory.sync._embed", side_effect=_embed_stub
    ):
        sync_from_files(store, kb_dir, origin="user")

    memories = store.get_memories(limit=10)
    assert len(memories) >= 1
    origins = {m["origin"] for m in memories}
    assert "user" in origins, f"Expected origin='user', got origins={origins}"


# ─── C-KB-17: UPDATE changed files ───────────────────────────────────────────

def test_sync_updates_changed_file(tmp_path):
    """C-KB-17: when a markdown file is edited, sync re-embeds and updates the entry."""
    store = _make_store(tmp_path)
    store.create_table()

    kb_dir = tmp_path / "knowledge" / "user"
    kb_dir.mkdir(parents=True)
    md_file = _make_md(kb_dir, "updatable.md", "Original content v1.", tags=[])

    from olav.core.memory.sync import sync_from_files
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "olav.core.memory.sync._embed", side_effect=_embed_stub
    ):
        r1 = sync_from_files(store, kb_dir)
    assert r1["inserted"] >= 1

    # Modify the file
    md_file.write_text("---\norigin: user\ntags: []\n---\n\nUpdated content v2.")

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "olav.core.memory.sync._embed", side_effect=_embed_stub
    ):
        r2 = sync_from_files(store, kb_dir)
    assert r2["updated"] >= 1, f"Expected >= 1 update on second sync, got {r2}"

    memories = store.get_memories(limit=10)
    texts = [m["text"] for m in memories]
    assert any("Updated content v2" in t for t in texts), (
        f"Updated text not found. Memories: {texts}"
    )


# ─── C-KB-19: DELETE removed files ───────────────────────────────────────────

def test_sync_deletes_removed_file(tmp_path):
    """C-KB-19: when a tracked file is deleted from disk, sync removes it from LanceDB."""
    store = _make_store(tmp_path)
    store.create_table()

    kb_dir = tmp_path / "knowledge" / "user"
    kb_dir.mkdir(parents=True)
    md_file = _make_md(kb_dir, "to_delete.md", "This will be deleted.", tags=[])

    from olav.core.memory.sync import sync_from_files
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "olav.core.memory.sync._embed", side_effect=_embed_stub
    ):
        r1 = sync_from_files(store, kb_dir)
    assert r1["inserted"] >= 1

    # Delete the file
    md_file.unlink()

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "olav.core.memory.sync._embed", side_effect=_embed_stub
    ):
        r2 = sync_from_files(store, kb_dir)
    assert r2["deleted"] >= 1, f"Expected >= 1 deletion, got {r2}"

    memories = store.get_memories(limit=10)
    texts = [m["text"] for m in memories]
    assert not any("This will be deleted" in t for t in texts), (
        "Deleted memory still present in LanceDB"
    )


# ─── C-KB-20: dry_run does not write ─────────────────────────────────────────

def test_sync_dry_run_does_not_modify(tmp_path):
    """C-KB-20: sync_from_files(dry_run=True) reports changes without touching data."""
    store = _make_store(tmp_path)
    store.create_table()

    kb_dir = tmp_path / "knowledge" / "user"
    kb_dir.mkdir(parents=True)
    _make_md(kb_dir, "dry_note.md", "Should not be stored in dry run.", tags=[])

    from olav.core.memory.sync import sync_from_files
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "olav.core.memory.sync._embed", side_effect=_embed_stub
    ):
        result = sync_from_files(store, kb_dir, dry_run=True)

    assert result.get("dry_run") is True, "dry_run result must have dry_run=True"
    assert result.get("inserted", 0) >= 1, "dry_run should still report what would be inserted"

    memories = store.get_memories(limit=10)
    assert len(memories) == 0, (
        f"dry_run must not write any data, found {len(memories)} memories"
    )
