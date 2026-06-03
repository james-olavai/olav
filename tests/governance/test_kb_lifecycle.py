"""Governance — KB lifecycle (dev_docs/79).

Covers:
* SOURCE_TIERS table is the source of truth for priority + weight
* UsageGuide.from_yaml derives priority from source_tier
* Schema v1 YAML without source_tier defaults to "user" (lowest)
* Schema v1 YAML with explicit ``priority:`` field is preserved
  (backward-compat)
* Tombstone files (``*.guide.yaml.removed``) skip discovery
* commit_to_memory writes schema_version=2 + source_tier=user
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from olav.core.memory.guide_kb import (
    DEFAULT_SOURCE_TIER,
    SOURCE_TIERS,
    UsageGuide,
    _tier_priority,
    _tier_weight,
    discover_guides,
)


def test_source_tiers_priority_monotonic() -> None:
    """vendor > platform > team > user in priority."""
    p = lambda t: SOURCE_TIERS[t]["priority"]
    assert p("vendor") > p("platform") > p("team") > p("user")


def test_source_tiers_weight_band() -> None:
    """All weights stay inside [0.5, 2.0] band."""
    for tier, info in SOURCE_TIERS.items():
        w = info["weight"]
        assert 0.5 <= w <= 2.0, f"{tier} weight {w} outside band"


def test_default_tier_is_lowest() -> None:
    """Unknown / un-tagged YAML falls back to the lowest-trust tier."""
    assert DEFAULT_SOURCE_TIER == "user"
    assert _tier_priority(DEFAULT_SOURCE_TIER) == min(
        info["priority"] for info in SOURCE_TIERS.values()
    )


def test_tier_priority_fallback() -> None:
    """Junk tier name falls back to user-tier."""
    assert _tier_priority("typo_tier_name") == _tier_priority("user")
    assert _tier_weight("typo_tier_name") == _tier_weight("user")


def _write_guide(p: Path, body: dict) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(body, sort_keys=False, allow_unicode=True))
    return p


def test_schema_v2_with_source_tier(tmp_path: Path) -> None:
    """v2 YAML with source_tier=platform → priority 8, weight 1.67."""
    p = _write_guide(tmp_path / "g.guide.yaml", {
        "schema_version": 2,
        "intent": "t",
        "agent": "core",
        "source_tier": "platform",
        "keywords": ["k"],
        "body": "b",
    })
    g = UsageGuide.from_yaml(p)
    assert g.source_tier == "platform"
    assert g.priority == 8


def test_schema_v1_untagged_defaults_to_user(tmp_path: Path) -> None:
    """v1 YAML without source_tier + without priority → user tier (priority 3)."""
    p = _write_guide(tmp_path / "g.guide.yaml", {
        "schema_version": 1,
        "intent": "t",
        "agent": "core",
        "keywords": ["k"],
        "body": "b",
    })
    g = UsageGuide.from_yaml(p)
    assert g.source_tier == "user"
    assert g.priority == 3


def test_schema_v1_with_explicit_priority_preserved(tmp_path: Path) -> None:
    """v1 YAML with explicit priority: 10 keeps priority 10 (back-compat for
    the 5 schema guides shipped 2026-05-15 commit 7f1ae71d that pre-date
    source_tier)."""
    p = _write_guide(tmp_path / "g.guide.yaml", {
        "schema_version": 1,
        "intent": "t",
        "agent": "core",
        "priority": 10,
        "keywords": ["k"],
        "body": "b",
    })
    g = UsageGuide.from_yaml(p)
    assert g.source_tier == "user"  # untagged
    assert g.priority == 10         # but explicit hint honoured


def test_invalid_tier_rejected(tmp_path: Path) -> None:
    """Misspelled source_tier raises ValueError."""
    p = _write_guide(tmp_path / "g.guide.yaml", {
        "schema_version": 2,
        "intent": "t",
        "agent": "core",
        "source_tier": "platfrom",  # typo
        "keywords": ["k"],
        "body": "b",
    })
    with pytest.raises(ValueError, match="source_tier"):
        UsageGuide.from_yaml(p)


def test_tombstone_skips_discovery(tmp_path: Path) -> None:
    """``<intent>.guide.yaml.removed`` files cause that intent to be skipped."""
    workspace = tmp_path / "ws"
    g_dir = workspace / "core" / "guides"

    # Active guide
    _write_guide(g_dir / "keep.guide.yaml", {
        "schema_version": 2,
        "intent": "keep",
        "agent": "core",
        "source_tier": "team",
        "keywords": ["k"],
        "body": "b",
    })
    # Tombstoned guide (same dir, .removed suffix)
    _write_guide(g_dir / "gone.guide.yaml.removed", {
        "schema_version": 2,
        "intent": "gone",
        "agent": "core",
        "source_tier": "user",
        "keywords": ["k"],
        "body": "b",
    })

    discovered = discover_guides(workspace)
    ids = sorted(g.memory_id for g in discovered)
    assert ids == ["guide_core_keep"]


def test_commit_to_memory_writes_v2_user_tier(tmp_path: Path, monkeypatch) -> None:
    """R102 commit_to_memory should emit schema_version=2 + source_tier=user."""
    monkeypatch.setenv("OLAV_WORKSPACE_ROOT", str(tmp_path / "ws"))

    # Import the helper after env var is set so workspace_root resolves correctly.
    # The 'memory-curator' skill dir uses a hyphen (SkillsMiddleware spec) which
    # is an invalid Python module path — load by file path, not dotted import.
    import importlib.util
    _cm = (
        Path(__file__).resolve().parents[2]
        / "src/olav/data/workspace/core/memory-curator/scripts/commit_to_memory.py"
    )
    _spec = importlib.util.spec_from_file_location("commit_to_memory", _cm)
    ct = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(ct)

    # Bypass embedder + LanceDB by replacing prime with a no-op.
    monkeypatch.setattr(
        "olav.core.memory.guide_kb.prime_guides_from_dir",
        lambda *a, **k: {"guide_entries": 1, "skipped": 0, "pruned": 0},
    )

    result = ct._commit_usage_guide(
        intent="contract_test",
        keywords=["a", "b"],
        body="hello world",
        agent="services",
        scope="global",
    )
    assert result["status"] == "success"
    assert result["source_tier"] == "user"

    yaml_path = Path(result["file"])
    data = yaml.safe_load(yaml_path.read_text())
    assert data["schema_version"] == 2
    assert data["source_tier"] == "user"
    assert data["intent"] == "contract_test"

    # Audit row written under kb_audit/
    audit_dir = Path(tmp_path / "ws" / "kb_audit")
    audit_files = list(audit_dir.glob("*_commit_contract_test.yaml"))
    assert len(audit_files) == 1
    audit_row = yaml.safe_load(audit_files[0].read_text())
    assert audit_row["action"] == "commit"
    assert audit_row["source_tier"] == "user"
    assert audit_row["intent"] == "contract_test"
    assert audit_row["body_sha256"]  # non-empty
