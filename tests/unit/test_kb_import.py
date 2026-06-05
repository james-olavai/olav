"""Unit tests for olav.core.memory.kb_import (ADR-0015).

Covers:
  - test_import_kb_markdown: import a .md file, assert row in LanceDB
  - test_import_kb_skips_empty_dir: empty dir → imported=0
  - test_reflection_has_expires_at: reflection row always has expires_at set
  - test_expert_knowledge_no_expires_at: expert_knowledge row has expires_at=None
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest


DIM = 32


def _embed_stub(text: str) -> list[float]:
    return [0.1] * DIM


def _make_store(tmp_path: Path):
    from olav.core.memory import LanceDBStore

    store = LanceDBStore(db_path=str(tmp_path / "kb_test.db"), embedding_dim=DIM)
    store.create_table()
    return store


# ---------------------------------------------------------------------------
# test_import_kb_markdown
# ---------------------------------------------------------------------------


def test_import_kb_markdown(tmp_path: Path):
    """Create a tmp dir with a .md file, call import_kb, assert row in LanceDB."""
    from olav.core.memory.kb_import import import_kb

    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    md_file = kb_dir / "guide.md"
    md_file.write_text(
        "# BGP state guide\n\nBGP neighbor state 'active' on SRL means TCP failed.\n",
        encoding="utf-8",
    )

    store = _make_store(tmp_path)
    with patch("olav.core.memory.kb_import._embed", side_effect=_embed_stub):
        result = import_kb(kb_dir, store=store)

    assert result["imported"] >= 1, f"Expected at least 1 imported chunk; got: {result}"
    assert result["skipped"] == 0 or result["imported"] >= 1

    memories = store.get_memories(category="expert_knowledge", limit=100)
    assert len(memories) >= 1, "Expected at least one expert_knowledge row in LanceDB"
    assert any(m["origin"] == "import" for m in memories), "Expected origin='import'"


# ---------------------------------------------------------------------------
# test_import_kb_skips_empty_dir
# ---------------------------------------------------------------------------


def test_import_kb_skips_empty_dir(tmp_path: Path):
    """Empty directory returns imported=0."""
    from olav.core.memory.kb_import import import_kb

    kb_dir = tmp_path / "empty_kb"
    kb_dir.mkdir()

    store = _make_store(tmp_path)
    result = import_kb(kb_dir, store=store)

    assert result["imported"] == 0
    assert result["errors"] == []


# ---------------------------------------------------------------------------
# test_import_kb_missing_dir
# ---------------------------------------------------------------------------


def test_import_kb_missing_dir(tmp_path: Path):
    """Non-existent directory returns an error."""
    from olav.core.memory.kb_import import import_kb

    store = _make_store(tmp_path)
    result = import_kb(tmp_path / "does_not_exist", store=store)

    assert result["imported"] == 0
    assert len(result["errors"]) >= 1


# ---------------------------------------------------------------------------
# test_reflection_has_expires_at
# ---------------------------------------------------------------------------


def test_reflection_has_expires_at(tmp_path: Path):
    """Writing a reflection row always sets expires_at ~30 days from now."""
    from olav.core.memory import LanceDBStore, MemoryCategory

    store = LanceDBStore(db_path=str(tmp_path / "ref.db"), embedding_dim=DIM)
    store.create_table()

    now = datetime.now(UTC)
    result = store.add_memory(
        id="ref-test-001",
        text="SSH must be verified before running execute_cli.",
        vector=[0.1] * DIM,
        category=MemoryCategory.REFLECTION,
        scope="shared:audit",
        origin="agent",
    )
    assert result.get("status") == "success", f"add_memory failed: {result}"

    # Read row back directly
    row = store.get_memory("ref-test-001")
    assert row is not None, "Row not found after write"
    expires_at = row.get("expires_at")
    assert expires_at is not None, "expires_at must be set for reflection rows"

    # Should be approximately 30 days from now
    if isinstance(expires_at, datetime):
        # Allow tz-aware vs naive comparison
        if expires_at.tzinfo is not None:
            delta = expires_at - now
        else:
            delta = expires_at - now.replace(tzinfo=None)
        assert timedelta(days=28) <= delta <= timedelta(days=32), (
            f"expires_at should be ~30 days from now; got delta={delta}"
        )


# ---------------------------------------------------------------------------
# test_expert_knowledge_no_expires_at
# ---------------------------------------------------------------------------


def test_expert_knowledge_no_expires_at(tmp_path: Path):
    """Writing an expert_knowledge row leaves expires_at as None."""
    from olav.core.memory import LanceDBStore, MemoryCategory

    store = LanceDBStore(db_path=str(tmp_path / "ek.db"), embedding_dim=DIM)
    store.create_table()

    result = store.add_memory(
        id="ek-test-001",
        text="SRL BGP active = TCP failed, not 'trying'.",
        vector=[0.1] * DIM,
        category=MemoryCategory.EXPERT_KNOWLEDGE,
        scope="global",
        origin="import",
        confidence=1.0,
    )
    assert result.get("status") == "success", f"add_memory failed: {result}"

    row = store.get_memory("ek-test-001")
    assert row is not None, "Row not found after write"
    expires_at = row.get("expires_at")
    assert expires_at is None, (
        f"expert_knowledge rows must NOT have expires_at set; got {expires_at!r}"
    )


# ---------------------------------------------------------------------------
# test_import_kb_txt_file
# ---------------------------------------------------------------------------


def test_import_kb_txt_file(tmp_path: Path):
    """Plain .txt files are imported."""
    from olav.core.memory.kb_import import import_kb

    kb_dir = tmp_path / "kb_txt"
    kb_dir.mkdir()
    txt_file = kb_dir / "notes.txt"
    txt_file.write_text("Always check BGP neighbor state before reporting PASS.\n", encoding="utf-8")

    store = _make_store(tmp_path)
    with patch("olav.core.memory.kb_import._embed", side_effect=_embed_stub):
        result = import_kb(kb_dir, store=store)

    assert result["imported"] >= 1, f"Expected at least 1 imported chunk; got: {result}"
