"""Platform-side guide_kb module — TDD red bar.

Pins the contract for ``olav.core.memory.guide_kb`` after moving
``UsageGuide`` / ``discover_guides`` / ``prime_guides_from_dir`` from
``olav_netops.core``.  See dev_docs/62 § "Platform-KB refactor".

Mirrors ``tests/unit/test_uks_import.py`` patterns:
* ``LanceDBStore(db_path=..., embedding_dim=32)`` for tmp store
* ``patch("olav.core.memory.guide_kb._embed", ...)`` to avoid
  external embedding API
* ``tmp_path`` fixture for filesystem isolation
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


DIM = 32


VALID_GUIDE_YAML = """
schema_version: 1
intent: topology_visualization
agent: ops
keywords: [topology, mermaid, diagram]
body: |
  Pull L2 links, build Mermaid graph, delegate to writer.
"""

VALID_GUIDE_YAML_2 = """
schema_version: 1
intent: drift_detection
agent: ops
keywords: [drift, diff, compare]
body: |
  Delegate to ops-analyze for snapshot diff.
"""


def _embed_stub(text: str) -> list[float]:
    return [float(len(text) % 100) / 100.0] * DIM


def _make_store(tmp_path):
    from olav.core.memory import LanceDBStore
    store = LanceDBStore(db_path=str(tmp_path / "guide.db"), embedding_dim=DIM)
    store.create_table()
    return store


def _write_guide(workspace_root: Path, agent: str, name: str, body: str) -> Path:
    """Write to <workspace_root>/<agent>/guides/<name>.guide.yaml."""
    p = workspace_root / agent / "guides" / f"{name}.guide.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# ── discover_guides ─────────────────────────────────────────────────


def test_discover_guides_finds_yaml(tmp_path):
    """Globs *.guide.yaml under any depth of workspace_root."""
    from olav.core.memory.guide_kb import discover_guides

    _write_guide(tmp_path, "ops", "topology_viz", VALID_GUIDE_YAML)
    _write_guide(tmp_path, "ops", "drift_detection", VALID_GUIDE_YAML_2)

    guides = discover_guides(tmp_path)
    assert len(guides) == 2
    intents = sorted(g.intent for g in guides)
    assert intents == ["drift_detection", "topology_visualization"]


def test_discover_guides_returns_empty_when_dir_missing(tmp_path):
    """Missing dir → empty list, no exception."""
    from olav.core.memory.guide_kb import discover_guides
    out = discover_guides(tmp_path / "does-not-exist")
    assert out == []


def test_discover_guides_skips_invalid(tmp_path, caplog):
    """One bad guide doesn't block the rest — logs + skips."""
    from olav.core.memory.guide_kb import discover_guides

    _write_guide(tmp_path, "ops", "valid", VALID_GUIDE_YAML)
    _write_guide(tmp_path, "ops", "invalid", "{ not: valid: yaml :")

    guides = discover_guides(tmp_path)
    assert len(guides) == 1
    assert guides[0].intent == "topology_visualization"


# ── UsageGuide.from_yaml ────────────────────────────────────────────


def test_usage_guide_memory_id_deterministic(tmp_path):
    """memory_id = guide_<agent>_<intent> — idempotent on re-prime."""
    from olav.core.memory.guide_kb import UsageGuide
    p = _write_guide(tmp_path, "ops", "x", VALID_GUIDE_YAML)
    g1 = UsageGuide.from_yaml(p)
    g2 = UsageGuide.from_yaml(p)
    assert g1.memory_id == "guide_ops_topology_visualization"
    assert g1.memory_id == g2.memory_id


def test_usage_guide_missing_required_field_raises(tmp_path):
    """Missing intent / agent / keywords / body → KeyError."""
    from olav.core.memory.guide_kb import UsageGuide
    p = _write_guide(tmp_path, "ops", "bad", "intent: x\nagent: y\nbody: z\n")
    with pytest.raises(KeyError):
        UsageGuide.from_yaml(p)


# ── prime_guides_from_dir ───────────────────────────────────────────


def test_prime_guides_writes_one_memory_per_guide(tmp_path):
    """No chunking — body stays whole.  2 guides → 2 memories."""
    from olav.core.memory.guide_kb import prime_guides_from_dir

    _write_guide(tmp_path, "ops", "topology_viz", VALID_GUIDE_YAML)
    _write_guide(tmp_path, "ops", "drift_detection", VALID_GUIDE_YAML_2)

    store = _make_store(tmp_path)
    with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
        result = prime_guides_from_dir(tmp_path, store=store)

    assert result["guide_entries"] == 2
    assert result["skipped"] == 0

    memories = store.get_memories(limit=10)
    guide_memories = [m for m in memories if m["category"] == "usage_guide"]
    assert len(guide_memories) == 2


def test_prime_guides_uses_deterministic_id(tmp_path):
    """Stored memory id is guide_<agent>_<intent>."""
    from olav.core.memory.guide_kb import prime_guides_from_dir

    _write_guide(tmp_path, "ops", "topology_viz", VALID_GUIDE_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
        prime_guides_from_dir(tmp_path, store=store)

    memories = store.get_memories(limit=10)
    ids = [m["id"] for m in memories]
    assert "guide_ops_topology_visualization" in ids


def test_prime_guides_category_is_usage_guide(tmp_path):
    """Category preserved for AutoRecallMiddleware quota routing."""
    from olav.core.memory.guide_kb import prime_guides_from_dir

    _write_guide(tmp_path, "ops", "topology_viz", VALID_GUIDE_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
        prime_guides_from_dir(tmp_path, store=store)

    memories = store.get_memories(limit=10)
    assert all(m["category"] == "usage_guide" for m in memories)


def test_prime_guides_idempotent_upsert(tmp_path):
    """Re-prime same dir → same count, no duplicates."""
    from olav.core.memory.guide_kb import prime_guides_from_dir

    _write_guide(tmp_path, "ops", "topology_viz", VALID_GUIDE_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
        r1 = prime_guides_from_dir(tmp_path, store=store)
        r2 = prime_guides_from_dir(tmp_path, store=store)

    assert r1["guide_entries"] == r2["guide_entries"] == 1
    memories = store.get_memories(limit=10)
    # exactly one entry under the deterministic id
    matching = [m for m in memories if m["id"] == "guide_ops_topology_visualization"]
    assert len(matching) == 1


def test_prime_guides_returns_count_dict(tmp_path):
    """{'guide_entries': N, 'skipped': K}."""
    from olav.core.memory.guide_kb import prime_guides_from_dir

    _write_guide(tmp_path, "ops", "topology_viz", VALID_GUIDE_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
        result = prime_guides_from_dir(tmp_path, store=store)

    assert isinstance(result, dict)
    assert "guide_entries" in result
    assert "skipped" in result


def test_prime_guides_no_workspace_returns_zero(tmp_path):
    """Missing workspace dir → {'guide_entries': 0, 'skipped': 0}."""
    from olav.core.memory.guide_kb import prime_guides_from_dir
    store = _make_store(tmp_path)

    result = prime_guides_from_dir(tmp_path / "does-not-exist", store=store)
    assert result["guide_entries"] == 0


def test_prime_guides_metadata_preserves_intent_agent(tmp_path):
    """Stored metadata exposes intent/agent for downstream consumers."""
    from olav.core.memory.guide_kb import prime_guides_from_dir

    _write_guide(tmp_path, "ops", "topology_viz", VALID_GUIDE_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
        prime_guides_from_dir(tmp_path, store=store)

    memories = store.get_memories(limit=10)
    [g] = memories
    md = g["metadata"]
    if isinstance(md, str):
        md = json.loads(md)
    assert md["intent"] == "topology_visualization"
    assert md["agent"] == "ops"


def test_prime_guides_tags_contain_keywords(tmp_path):
    """Tags JSON contains agent + intent + all keywords (for future Tags FTS)."""
    from olav.core.memory.guide_kb import prime_guides_from_dir

    _write_guide(tmp_path, "ops", "topology_viz", VALID_GUIDE_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
        prime_guides_from_dir(tmp_path, store=store)

    memories = store.get_memories(limit=10)
    [g] = memories
    tags = g["tags"]
    if isinstance(tags, str):
        tags = json.loads(tags)
    assert "topology" in tags
    assert "mermaid" in tags
    assert "ops" in tags
    assert "topology_visualization" in tags
