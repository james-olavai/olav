"""Phase 0-1 integration test: write a memory → recall → assert it can be found.

Uses a real LanceDB store at a temp path.
Does NOT require a live LLM — embedding step uses a zero-vector placeholder so
the test stays fast. The goal is to verify the storage roundtrip (write path +
read path) works end-to-end through the same db_path.
"""
from __future__ import annotations

import uuid
from pathlib import Path


def test_memory_add_and_search_by_text(tmp_path):
    """Memory written via add_memory() must be retrievable via search_by_text()."""
    from olav.core.memory import LanceDBStore, MEMORY_TABLE

    db_path = tmp_path / "memory.lance"
    store = LanceDBStore(db_path=str(db_path))

    mem_id = str(uuid.uuid4())
    text = "BGP neighbor 10.0.0.1 flapped three times in the last hour"
    vector = [0.0] * store.embedding_dim

    result = store.add_memory(
        id=mem_id,
        text=text,
        vector=vector,
        category="fact",
        scope="test",
    )
    assert result.get("status") == "success", f"add_memory failed: {result}"

    results = store.search_by_text(text[:30], limit=5, scope="test")
    ids = [r["id"] for r in results]
    assert mem_id in ids, (
        f"Memory {mem_id!r} not found after add. search returned: {results}"
    )


def test_memory_store_uses_consistent_path(tmp_path):
    """Two stores opened at the same path must share the same data.

    The test uses ``store.embedding_dim`` to size the test vector
    because the auto-detected dimension (read from ``api.json``
    ``embedding`` section) varies between local BGE (768) and
    remote OpenAI-compatible endpoints (1536).  Hardcoding 384
    broke the test on any install with either default.
    """
    from olav.core.memory import LanceDBStore

    db_path = tmp_path / "memory.lance"
    mem_id = str(uuid.uuid4())
    text = "Interface GigabitEthernet0/0 is down due to physical link failure"

    # Writer
    writer = LanceDBStore(db_path=str(db_path))
    vector = [0.0] * writer.embedding_dim
    writer.add_memory(id=mem_id, text=text, vector=vector, scope="test2")

    # Independent reader (same path, new object)
    reader = LanceDBStore(db_path=str(db_path))
    results = reader.search_by_text("GigabitEthernet0/0", limit=5, scope="test2")
    ids = [r["id"] for r in results]

    assert mem_id in ids, (
        f"Memory not visible from second store object. "
        f"writer path={db_path}, results={results}"
    )


def test_agent_store_and_core_store_share_same_db_path():
    """OLAVAgent.store and olav.core.memory path must both point to databases/memory.lance."""
    import re
    from pathlib import Path

    # Read agent.py to confirm db_path construction
    agent_src = (Path(__file__).parents[2] / "src" / "olav" / "agents" / "agent.py").read_text()
    # Should reference "databases/memory.lance" or similar
    assert "memory.lance" in agent_src, (
        "agent.py must use 'memory.lance' path (see BUG-1 fix)"
    )

    # Read core memory __init__ to confirm DEFAULT_MEMORY_DB
    mem_src = (
        Path(__file__).parents[2] / "src" / "olav" / "core" / "memory" / "__init__.py"
    ).read_text()
    # Extract DEFAULT_MEMORY_DB value
    m = re.search(r'DEFAULT_MEMORY_DB\s*=\s*["\']([^"\']+)["\']', mem_src)
    assert m is not None, "DEFAULT_MEMORY_DB not found in core/memory/__init__.py"
    core_path = m.group(1)  # e.g. ".olav/databases/memory.lance"

    assert "memory.lance" in core_path, f"DEFAULT_MEMORY_DB={core_path!r} does not use memory.lance"

    # Both must agree on the "memory.lance" suffix
    agent_match = re.search(r'"databases"\s*/\s*"memory\.lance"', agent_src)
    assert agent_match or '"memory.lance"' in agent_src, (
        "agent.py path construction must match core DEFAULT_MEMORY_DB"
    )
