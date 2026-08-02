"""Platform-side guide_kb module — TDD red bar.

Pins the contract for ``olav.core.memory.guide_kb`` after moving
``UsageGuide`` / ``discover_guides`` / ``prime_guides_from_dir`` from
``olav_netops.core``.  See dev_docs/58 § "Platform-KB refactor".

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


# ── Patch C1 (2026-05-08): orphan-prune on prime ─────────────────────


def test_prime_guides_prunes_orphan_when_source_deleted(tmp_path):
    """If a guide YAML is deleted from source, its memory entry must
    be removed on next prime — prevents AutoRecall ghost entries
    (regression: cab_revise.guide leak broke emit_tcf ranking 2026-05-07).
    """
    from olav.core.memory.guide_kb import prime_guides_from_dir

    p1 = _write_guide(tmp_path, "ops", "topology_viz", VALID_GUIDE_YAML)
    p2 = _write_guide(tmp_path, "ops", "drift_detection", VALID_GUIDE_YAML_2)
    store = _make_store(tmp_path)

    # First prime: 2 guides land in memory
    with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
        result1 = prime_guides_from_dir(tmp_path, store=store)
    assert result1["guide_entries"] == 2
    assert result1["pruned"] == 0

    # Delete one source file
    p2.unlink()

    # Second prime: 1 guide remains, the other is pruned
    with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
        result2 = prime_guides_from_dir(tmp_path, store=store)
    assert result2["guide_entries"] == 1
    assert result2["pruned"] == 1

    # Confirm the orphan memory entry is gone
    remaining_ids = [m["id"] for m in store.get_memories(category="usage_guide", limit=10)]
    assert "guide_ops_topology_visualization" in remaining_ids
    assert "guide_ops_drift_detection" not in remaining_ids


def test_prime_guides_prune_skips_non_config_origin(tmp_path):
    """Manually-curated memories (origin != config) must NOT be pruned
    even if their id starts with guide_."""
    from olav.core.memory.guide_kb import prime_guides_from_dir

    _write_guide(tmp_path, "ops", "topology_viz", VALID_GUIDE_YAML)
    store = _make_store(tmp_path)

    # Inject a user-authored memory with guide_-style id
    store.add_memory(
        id="guide_user_custom_pattern",
        text="User-curated content",
        vector=_embed_stub("user content"),
        category="usage_guide",
        scope="global",
        metadata={"intent": "user", "agent": "ops"},
        origin="user",  # <-- not config
        confidence=1.0,
        tags="[]",
    )

    with patch("olav.core.memory.guide_kb._embed", side_effect=_embed_stub):
        result = prime_guides_from_dir(tmp_path, store=store)

    # User entry survives even though its source isnt in workspace
    assert result["guide_entries"] == 1
    assert result["pruned"] == 0
    remaining_ids = [m["id"] for m in store.get_memories(category="usage_guide", limit=10)]
    assert "guide_user_custom_pattern" in remaining_ids


# --- unchanged guides must not be re-embedded (2026-08-02) ------------------
#
# Re-priming used to re-embed every guide on every call: 54 guides x 2-9s of
# real embedding on each `olav init`, each `skill install`, and each ingest.
# That is why a unit test calling finalise_ingest ran for minutes. Embedding is
# the only expensive step here, so an unchanged guide must never reach it.
# --- unchanged guides must not be re-embedded -------------------------------


class _FakeStore:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.added = []

    def get_memories(self, category=None, limit=None):
        return self.rows

    def delete_memory(self, id=None, **_k):
        pass

    def add_memory(self, **kw):
        self.added.append(kw)
        self.rows.append({"id": kw["id"], "origin": "config",
                          "metadata": kw.get("metadata") or {}})


def _guide_dir(tmp_path):
    d = tmp_path / "netops" / "references"
    d.mkdir(parents=True)
    (d / "a.guide.yaml").write_text(
        "schema_version: 1\nintent: thing_a\nagent: netops\n"
        "keywords: [alpha]\nbody: |\n  body of a\n", encoding="utf-8")
    (d / "b.guide.yaml").write_text(
        "schema_version: 1\nintent: thing_b\nagent: netops\n"
        "keywords: [beta]\nbody: |\n  body of b\n", encoding="utf-8")
    return tmp_path


def test_a_second_prime_re_embeds_nothing(monkeypatch, tmp_path):
    """Re-priming used to re-embed every guide every time — 54 guides x 2-9s on
    every `olav init`, `skill install` and ingest. Embedding is the only
    expensive step, so an unchanged guide must never reach it."""
    import olav.core.memory.guide_kb as G

    embeds = {"n": 0}

    def _fake_embed(_text):
        embeds["n"] += 1
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(G, "_embed", _fake_embed)
    root = _guide_dir(tmp_path)
    store = _FakeStore()

    first = G.prime_guides_from_dir(root, store=store)
    assert first["guide_entries"] == 2 and first["embedded"] == 2
    assert embeds["n"] == 2

    second = G.prime_guides_from_dir(root, store=store)
    assert second["unchanged"] == 2
    assert second["embedded"] == 0
    # ...and `guide_entries` still means "present and current", so a caller
    # reporting it does not suddenly show 0 after a no-op re-prime
    assert second["guide_entries"] == 2
    assert embeds["n"] == 2, "an unchanged guide was re-embedded"


def test_an_edited_guide_is_re_embedded(monkeypatch, tmp_path):
    """The skip must be driven by content, not by presence."""
    import olav.core.memory.guide_kb as G

    embeds = {"n": 0}
    monkeypatch.setattr(G, "_embed", lambda _t: (embeds.__setitem__("n", embeds["n"] + 1), [0.1])[1])

    root = _guide_dir(tmp_path)
    store = _FakeStore()
    G.prime_guides_from_dir(root, store=store)
    assert embeds["n"] == 2

    (root / "netops" / "references" / "a.guide.yaml").write_text(
        "schema_version: 1\nintent: thing_a\nagent: netops\n"
        "keywords: [alpha]\nbody: |\n  body of a, revised\n", encoding="utf-8")
    res = G.prime_guides_from_dir(root, store=store)
    assert embeds["n"] == 3, "the edited guide was not re-embedded"
    assert res["unchanged"] == 1


def test_switching_embedding_model_re_embeds_everything(monkeypatch, tmp_path):
    """Content alone as the key would serve vectors from the previous model —
    the dimension-mismatch class CLAUDE.md treats as fail-fast, quietly
    reintroduced through a cache."""
    import olav.core.memory.guide_kb as G

    embeds = {"n": 0}
    monkeypatch.setattr(G, "_embed", lambda _t: (embeds.__setitem__("n", embeds["n"] + 1), [0.1])[1])

    class _Cfg:
        mode = "api"
        openai_model = "model-one"

    monkeypatch.setattr("olav.core.config.get_embedding_config", lambda: _Cfg())
    root = _guide_dir(tmp_path)
    store = _FakeStore()
    G.prime_guides_from_dir(root, store=store)
    assert embeds["n"] == 2

    _Cfg.openai_model = "model-two"
    G.prime_guides_from_dir(root, store=store)
    assert embeds["n"] == 4, "a model switch reused the old model's vectors"


def test_the_store_returns_metadata_as_json_so_it_must_be_parsed(monkeypatch, tmp_path):
    """The real store round-trips `metadata` as a JSON string. Reading it with
    `.get()` silently yields nothing — which is how the first version of the
    unchanged check looked correct while re-embedding everything every run."""
    import json as _json

    import olav.core.memory.guide_kb as G

    embeds = {"n": 0}
    monkeypatch.setattr(G, "_embed", lambda _t: (embeds.__setitem__("n", embeds["n"] + 1), [0.1])[1])

    class _JsonMetaStore(_FakeStore):
        def add_memory(self, **kw):
            self.added.append(kw)
            self.rows.append({"id": kw["id"], "origin": "config",
                              "metadata": _json.dumps(kw.get("metadata") or {})})

    root = _guide_dir(tmp_path)
    store = _JsonMetaStore()
    G.prime_guides_from_dir(root, store=store)
    assert embeds["n"] == 2

    res = G.prime_guides_from_dir(root, store=store)
    assert res["unchanged"] == 2, "JSON-encoded metadata defeated the check"
    assert embeds["n"] == 2
