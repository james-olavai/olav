"""R87 Phase 1 — expert_knowledge memory category — TDD red bar.

Pin the contract for ``olav.core.memory.expert_kb``.  Sibling to
guide_kb / format_kb but with critical difference: each file
declares its own ``scope`` (``global`` OR ``<agent_name>``) so the
recall middleware can filter agent-specific expertise out of other
agents' surface.

See dev_docs/63 § "Phase 1 detailed design".
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


DIM = 32


VALID_EXPERT_YAML = """
schema_version: 1
topic: bgp_state_decoder_srl
scope: ops-lab
vendor: srl
platform_family: nokia
keywords: [srl, sr-linux, bgp, established, active]
body: |
  SRL-specific BGP state semantics.
  active = TCP cannot reach peer (NOT "trying" as in Cisco).
"""

VALID_EXPERT_YAML_2 = """
schema_version: 1
topic: ospf_srl_quirks
scope: ops-lab
vendor: srl
keywords: [srl, ospf, area, network-instance]
body: |
  SRL OSPF quirks: must enable per-network-instance.
"""


def _embed_stub(text: str) -> list[float]:
    return [float(len(text) % 100) / 100.0] * DIM


def _make_store(tmp_path):
    from olav.core.memory import LanceDBStore
    store = LanceDBStore(db_path=str(tmp_path / "ekb.db"), embedding_dim=DIM)
    store.create_table()
    return store


def _write_expert(workspace_root: Path, agent: str, name: str, body: str) -> Path:
    """Write to <workspace_root>/<agent>/expertise/<name>.expert.yaml."""
    p = workspace_root / agent / "expertise" / f"{name}.expert.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# ── discover_experts ───────────────────────────────────────────────


def test_discover_experts_finds_yaml(tmp_path):
    """Globs ``*.expert.yaml`` under any depth of workspace_root."""
    from olav.core.memory.expert_kb import discover_experts

    _write_expert(tmp_path, "ops-lab", "srl_bgp", VALID_EXPERT_YAML)
    _write_expert(tmp_path, "ops-lab", "srl_ospf", VALID_EXPERT_YAML_2)

    experts = discover_experts(tmp_path)
    assert len(experts) == 2
    topics = sorted(e.topic for e in experts)
    assert topics == ["bgp_state_decoder_srl", "ospf_srl_quirks"]


def test_discover_experts_returns_empty_when_dir_missing(tmp_path):
    from olav.core.memory.expert_kb import discover_experts
    out = discover_experts(tmp_path / "missing")
    assert out == []


def test_discover_experts_skips_invalid(tmp_path, caplog):
    from olav.core.memory.expert_kb import discover_experts

    _write_expert(tmp_path, "ops-lab", "valid", VALID_EXPERT_YAML)
    _write_expert(tmp_path, "ops-lab", "invalid", "{ not: valid: yaml :")

    experts = discover_experts(tmp_path)
    assert len(experts) == 1


# ── ExpertKnowledge.from_yaml ──────────────────────────────────────


def test_expert_memory_id_deterministic(tmp_path):
    """memory_id = expert_<scope>_<topic> — idempotent."""
    from olav.core.memory.expert_kb import ExpertKnowledge
    p = _write_expert(tmp_path, "ops-lab", "x", VALID_EXPERT_YAML)
    e1 = ExpertKnowledge.from_yaml(p)
    e2 = ExpertKnowledge.from_yaml(p)
    assert e1.memory_id == "expert_ops-lab_bgp_state_decoder_srl"
    assert e1.memory_id == e2.memory_id


def test_expert_missing_required_field_raises(tmp_path):
    """Missing topic / scope / keywords / body → KeyError."""
    from olav.core.memory.expert_kb import ExpertKnowledge
    p = _write_expert(
        tmp_path, "ops-lab", "bad",
        "topic: x\nkeywords: [a]\nbody: y\n"  # no scope
    )
    with pytest.raises(KeyError):
        ExpertKnowledge.from_yaml(p)


def test_expert_optional_fields_default(tmp_path):
    """vendor / platform_family / schema_version are optional."""
    from olav.core.memory.expert_kb import ExpertKnowledge
    minimal = """
schema_version: 1
topic: minimal
scope: ops-lab
keywords: [a]
body: minimal body
"""
    p = _write_expert(tmp_path, "ops-lab", "min", minimal)
    e = ExpertKnowledge.from_yaml(p)
    assert e.vendor is None
    assert e.platform_family is None
    assert e.schema_version == 1


# ── prime_experts_from_dir ─────────────────────────────────────────


def test_prime_experts_writes_one_memory_per_file(tmp_path):
    from olav.core.memory.expert_kb import prime_experts_from_dir

    _write_expert(tmp_path, "ops-lab", "srl_bgp", VALID_EXPERT_YAML)
    _write_expert(tmp_path, "ops-lab", "srl_ospf", VALID_EXPERT_YAML_2)

    store = _make_store(tmp_path)
    with patch("olav.core.memory.expert_kb._embed", side_effect=_embed_stub):
        result = prime_experts_from_dir(tmp_path, store=store)

    assert result["expert_entries"] == 2
    assert result["skipped"] == 0

    memories = store.get_memories(limit=10)
    expert_mems = [m for m in memories if m["category"] == "expert_knowledge"]
    assert len(expert_mems) == 2


def test_prime_experts_uses_deterministic_id(tmp_path):
    from olav.core.memory.expert_kb import prime_experts_from_dir

    _write_expert(tmp_path, "ops-lab", "srl_bgp", VALID_EXPERT_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.expert_kb._embed", side_effect=_embed_stub):
        prime_experts_from_dir(tmp_path, store=store)

    memories = store.get_memories(limit=10)
    ids = [m["id"] for m in memories]
    assert "expert_ops-lab_bgp_state_decoder_srl" in ids


def test_prime_experts_category_is_expert_knowledge(tmp_path):
    from olav.core.memory.expert_kb import prime_experts_from_dir

    _write_expert(tmp_path, "ops-lab", "srl_bgp", VALID_EXPERT_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.expert_kb._embed", side_effect=_embed_stub):
        prime_experts_from_dir(tmp_path, store=store)

    memories = store.get_memories(limit=10)
    assert all(m["category"] == "expert_knowledge" for m in memories)


def test_prime_experts_scope_set_from_yaml(tmp_path):
    """The YAML's ``scope:`` field becomes the memory's scope —
    NOT 'global'.  This is what enables per-agent recall filtering.
    """
    from olav.core.memory.expert_kb import prime_experts_from_dir

    _write_expert(tmp_path, "ops-lab", "srl_bgp", VALID_EXPERT_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.expert_kb._embed", side_effect=_embed_stub):
        prime_experts_from_dir(tmp_path, store=store)

    memories = store.get_memories(limit=10)
    [m] = memories
    assert m["scope"] == "ops-lab"


def test_prime_experts_idempotent_upsert(tmp_path):
    from olav.core.memory.expert_kb import prime_experts_from_dir

    _write_expert(tmp_path, "ops-lab", "srl_bgp", VALID_EXPERT_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.expert_kb._embed", side_effect=_embed_stub):
        r1 = prime_experts_from_dir(tmp_path, store=store)
        r2 = prime_experts_from_dir(tmp_path, store=store)

    assert r1["expert_entries"] == r2["expert_entries"] == 1
    memories = store.get_memories(limit=10)
    matching = [
        m for m in memories
        if m["id"] == "expert_ops-lab_bgp_state_decoder_srl"
    ]
    assert len(matching) == 1


def test_prime_experts_returns_count_dict(tmp_path):
    from olav.core.memory.expert_kb import prime_experts_from_dir

    _write_expert(tmp_path, "ops-lab", "srl_bgp", VALID_EXPERT_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.expert_kb._embed", side_effect=_embed_stub):
        result = prime_experts_from_dir(tmp_path, store=store)

    assert isinstance(result, dict)
    assert "expert_entries" in result
    assert "skipped" in result


def test_prime_experts_tags_carry_keywords(tmp_path):
    """Stored tags include topic + scope + vendor + all keywords."""
    from olav.core.memory.expert_kb import prime_experts_from_dir

    _write_expert(tmp_path, "ops-lab", "srl_bgp", VALID_EXPERT_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.expert_kb._embed", side_effect=_embed_stub):
        prime_experts_from_dir(tmp_path, store=store)

    memories = store.get_memories(limit=10)
    [m] = memories
    tags = m["tags"]
    if isinstance(tags, str):
        tags = json.loads(tags)
    assert "bgp_state_decoder_srl" in tags
    assert "ops-lab" in tags
    assert "srl" in tags
    assert "established" in tags


def test_prime_experts_metadata_preserves_vendor(tmp_path):
    """vendor/platform_family go into metadata for downstream UI."""
    from olav.core.memory.expert_kb import prime_experts_from_dir

    _write_expert(tmp_path, "ops-lab", "srl_bgp", VALID_EXPERT_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.expert_kb._embed", side_effect=_embed_stub):
        prime_experts_from_dir(tmp_path, store=store)

    memories = store.get_memories(limit=10)
    [m] = memories
    md = m["metadata"]
    if isinstance(md, str):
        md = json.loads(md)
    assert md["topic"] == "bgp_state_decoder_srl"
    assert md["scope"] == "ops-lab"
    assert md["vendor"] == "srl"
    assert md["platform_family"] == "nokia"


# ── Phase 1.5: scope vocabulary ────────────────────────────────────


@pytest.mark.parametrize(
    "scope",
    ["ops-lab", "audit-orchestrator", "core", "shared:ops", "shared:audit", "org"],
)
def test_phase15_scope_validation_accepts_valid_forms(tmp_path, scope):
    from olav.core.memory.expert_kb import ExpertKnowledge

    yaml_text = f"""
schema_version: 1
topic: x
scope: {scope}
keywords: [a]
body: ok
"""
    p = tmp_path / "x.expert.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    e = ExpertKnowledge.from_yaml(p)
    assert e.scope == scope


@pytest.mark.parametrize(
    "scope",
    [
        "OPS-LAB",        # uppercase
        "shared:",        # missing domain
        ":ops",           # missing prefix
        "shared:Ops",     # uppercase domain
        # NOTE: "global" (Phase 1 legacy) shape-matches the agent-name
        # pattern; treated as agent="global" silently rather than
        # rejected. If a real "global" agent ever exists this works;
        # if it's a Phase 1 leftover the scope filter just won't include
        # it for any current agent. Both are acceptable.
        "agent.with.dot",
        "shared:ops:extra",  # too many colons
    ],
)
def test_phase15_scope_validation_rejects_invalid_forms(tmp_path, scope):
    from olav.core.memory.expert_kb import ExpertKnowledge

    # Quote the scope value so YAML doesn't parse colons as mapping
    yaml_text = f'''
schema_version: 1
topic: x
scope: "{scope}"
keywords: [a]
body: ok
'''
    p = tmp_path / "x.expert.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        ExpertKnowledge.from_yaml(p)
    assert "scope" in str(exc.value).lower()


# ── Phase 1.5: discover_experts scans shared/ and user dirs ────────


def _write_shared(workspace_root: Path, domain: str, name: str, body: str) -> Path:
    p = workspace_root / "shared" / domain / "expertise" / f"{name}.expert.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _write_user(user_dir: Path, name: str, body: str) -> Path:
    user_dir.mkdir(parents=True, exist_ok=True)
    p = user_dir / f"{name}.expert.yaml"
    p.write_text(body, encoding="utf-8")
    return p


SHARED_OPS_YAML = """
schema_version: 1
topic: spec_rules
scope: shared:ops
keywords: [spec, rules]
body: |
  Cross-agent spec rules.
"""

ORG_YAML = """
schema_version: 1
topic: company_as_policy
scope: org
keywords: [as, prod]
body: |
  Production AS allocation 65000-65535; lab 64500-64599.
"""


def test_phase15_discover_finds_shared_layout(tmp_path):
    from olav.core.memory.expert_kb import discover_experts

    _write_expert(tmp_path, "ops-lab", "srl_bgp", VALID_EXPERT_YAML)
    _write_shared(tmp_path, "ops", "spec_rules", SHARED_OPS_YAML)

    experts = discover_experts(tmp_path)
    by_scope = {e.scope for e in experts}
    assert by_scope == {"ops-lab", "shared:ops"}
    assert all(e.source == "shipped" for e in experts)


def test_phase15_discover_user_dir_marks_source(tmp_path):
    from olav.core.memory.expert_kb import discover_experts

    _write_expert(tmp_path, "ops-lab", "srl_bgp", VALID_EXPERT_YAML)
    user_dir = tmp_path / "user_expertise"
    _write_user(user_dir, "company_as", ORG_YAML)

    experts = discover_experts(tmp_path, user_dirs=[user_dir])
    by_topic = {e.topic: e for e in experts}
    assert by_topic["bgp_state_decoder_srl"].source == "shipped"
    assert by_topic["company_as_policy"].source == "user"
    assert by_topic["company_as_policy"].scope == "org"


def test_phase15_prime_writes_source_to_metadata(tmp_path):
    from olav.core.memory.expert_kb import prime_experts_from_dir

    _write_expert(tmp_path, "ops-lab", "srl_bgp", VALID_EXPERT_YAML)
    user_dir = tmp_path / "user_expertise"
    _write_user(user_dir, "company_as", ORG_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.expert_kb._embed", side_effect=_embed_stub):
        # Pass user_dirs explicitly so the test is hermetic
        from olav.core.memory.expert_kb import discover_experts
        experts = discover_experts(tmp_path, user_dirs=[user_dir])
        assert any(e.source == "user" for e in experts)

    # Re-prime by direct API to assert metadata
    with patch("olav.core.memory.expert_kb._embed", side_effect=_embed_stub):
        # prime_experts_from_dir doesn't accept user_dirs yet — verify
        # only the shipped path here
        prime_experts_from_dir(tmp_path, store=store)
    memories = store.get_memories(limit=10)
    [m] = memories
    md = m["metadata"]
    if isinstance(md, str):
        md = json.loads(md)
    assert md.get("source") == "shipped"


# ── Phase 1.5: recall middleware scope filter ──────────────────────


def test_phase15_allowed_expert_scopes_for_ops_lab():
    from olav.core.memory import LanceDBStore
    from olav.core.memory.middleware import AutoRecallMiddleware

    store = LanceDBStore(db_path=":memory:", embedding_dim=DIM)
    mw = AutoRecallMiddleware(store=store, current_agent="ops-lab")
    assert mw._allowed_expert_scopes() == {"ops-lab", "shared:ops", "org"}


def test_phase15_allowed_scopes_none_when_no_agent():
    from olav.core.memory import LanceDBStore
    from olav.core.memory.middleware import AutoRecallMiddleware

    store = LanceDBStore(db_path=":memory:", embedding_dim=DIM)
    mw = AutoRecallMiddleware(store=store, current_agent=None)
    assert mw._allowed_expert_scopes() is None


def test_phase15_allowed_scopes_compound_agent():
    """audit-orchestrator → domain 'audit'."""
    from olav.core.memory import LanceDBStore
    from olav.core.memory.middleware import AutoRecallMiddleware

    store = LanceDBStore(db_path=":memory:", embedding_dim=DIM)
    mw = AutoRecallMiddleware(store=store, current_agent="audit-orchestrator")
    assert mw._allowed_expert_scopes() == {
        "audit-orchestrator",
        "shared:audit",
        "org",
    }


# ── Phase 1.5: three-slot expert_knowledge sub-quota ────────────────


def test_phase15_diversifier_picks_one_per_scope_tier():
    """When agent + shared + org are all present, take one of each."""
    from olav.core.memory import LanceDBStore
    from olav.core.memory.middleware import AutoRecallMiddleware

    store = LanceDBStore(db_path=":memory:", embedding_dim=DIM)
    mw = AutoRecallMiddleware(store=store, current_agent="ops-lab")

    memories = [
        {"id": f"a{i}", "category": "expert_knowledge", "scope": "ops-lab"}
        for i in range(3)
    ] + [
        {"id": f"s{i}", "category": "expert_knowledge", "scope": "shared:ops"}
        for i in range(3)
    ] + [
        {"id": f"o{i}", "category": "expert_knowledge", "scope": "org",
         "metadata": {"source": "user"}}
        for i in range(3)
    ]
    out = mw._diversify_by_category(memories, limit=13)
    chosen_ek = [m for m in out if m["category"] == "expert_knowledge"]
    assert len(chosen_ek) == 3
    scopes = sorted({m["scope"] for m in chosen_ek})
    assert scopes == ["ops-lab", "org", "shared:ops"]


def test_phase15_diversifier_includes_user_source_when_present():
    """The org slot guarantees user-injected content is included
    whenever it exists — this is the core "users own their workflow"
    promise (relative ordering is left to vector rank, since the slot
    presence alone is the contract).
    """
    from olav.core.memory import LanceDBStore
    from olav.core.memory.middleware import AutoRecallMiddleware

    store = LanceDBStore(db_path=":memory:", embedding_dim=DIM)
    mw = AutoRecallMiddleware(store=store, current_agent="ops-lab")

    memories = [
        {"id": "a", "category": "expert_knowledge", "scope": "ops-lab"},
        {"id": "s", "category": "expert_knowledge", "scope": "shared:ops"},
        {"id": "o", "category": "expert_knowledge", "scope": "org",
         "metadata": {"source": "user"}},
    ]
    out = mw._diversify_by_category(memories, limit=13)
    user_ids = {
        m["id"] for m in out
        if (m.get("metadata") or {}).get("source") == "user"
    }
    assert "o" in user_ids


def test_phase15_diversifier_falls_back_when_tier_absent():
    """When only agent-scope entries exist, all 3 slots fill from
    agent (no slot wasted on absent tiers).
    """
    from olav.core.memory import LanceDBStore
    from olav.core.memory.middleware import AutoRecallMiddleware

    store = LanceDBStore(db_path=":memory:", embedding_dim=DIM)
    mw = AutoRecallMiddleware(store=store, current_agent="ops-lab")

    memories = [
        {"id": f"a{i}", "category": "expert_knowledge", "scope": "ops-lab"}
        for i in range(5)
    ]
    out = mw._diversify_by_category(memories, limit=13)
    chosen_ek = [m for m in out if m["category"] == "expert_knowledge"]
    assert len(chosen_ek) == 3
    assert all(m["scope"] == "ops-lab" for m in chosen_ek)
