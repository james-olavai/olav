"""UsageGuide YAML loader contract.

Pin the schema parsing + glob discovery so future changes don't
silently break the upsert path.  Focused unit tests — no external
dependencies (no LanceDB, no embedding).  The in-LanceDB upsert path
is covered by ``tests/unit/test_guide_kb.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest


pytest.importorskip("olav.core.memory.guide_kb")


from olav.core.memory.guide_kb import UsageGuide, discover_guides


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


VALID_YAML = """
schema_version: 1
intent: topology_visualization
agent: ops
keywords:
  - topology
  - mermaid
  - diagram
body: |
  Step 1: query topology_links.
  Step 2: build Mermaid graph TD.
  Step 3: delegate to writer.
"""


# ── from_yaml — happy path ─────────────────────────────────────────


def test_from_yaml_valid(tmp_path):
    path = _write(tmp_path / "guides" / "topology_viz.guide.yaml", VALID_YAML)
    guide = UsageGuide.from_yaml(path)
    assert guide.intent == "topology_visualization"
    assert guide.agent == "ops"
    assert guide.keywords == ["topology", "mermaid", "diagram"]
    assert "Step 1" in guide.body
    assert guide.schema_version == 1
    assert guide.source_path == path


def test_memory_id_deterministic(tmp_path):
    """Same agent+intent → same id (idempotent upsert key)."""
    g1 = UsageGuide(intent="x", agent="ops", keywords=["k"], body="b")
    g2 = UsageGuide(intent="x", agent="ops", keywords=["other"], body="other")
    assert g1.memory_id == g2.memory_id == "guide_ops_x"


def test_memory_id_differs_by_intent():
    g1 = UsageGuide(intent="topology_visualization", agent="ops", keywords=["k"], body="b")
    g2 = UsageGuide(intent="simulation_what_if", agent="ops", keywords=["k"], body="b")
    assert g1.memory_id != g2.memory_id


def test_memory_id_differs_by_agent():
    g1 = UsageGuide(intent="x", agent="ops", keywords=["k"], body="b")
    g2 = UsageGuide(intent="x", agent="audit", keywords=["k"], body="b")
    assert g1.memory_id != g2.memory_id


def test_body_stripped(tmp_path):
    """Trailing/leading whitespace from YAML block scalar is stripped."""
    path = _write(
        tmp_path / "guides" / "x.guide.yaml",
        "intent: i\nagent: ops\nkeywords: [k]\nbody: |\n  hello\n  \n",
    )
    g = UsageGuide.from_yaml(path)
    assert g.body == "hello"


# ── from_yaml — validation errors ──────────────────────────────────


@pytest.mark.parametrize("missing", ["intent", "agent", "keywords", "body"])
def test_missing_required_raises(tmp_path, missing):
    base = {
        "intent": "x", "agent": "ops",
        "keywords": ["k"], "body": "b",
    }
    base.pop(missing)
    yaml_text = "\n".join(
        f"{k}: {v}" if not isinstance(v, list)
        else f"{k}: [{', '.join(v)}]"
        for k, v in base.items()
    )
    path = _write(tmp_path / "guides" / "bad.guide.yaml", yaml_text)
    with pytest.raises(KeyError, match=missing):
        UsageGuide.from_yaml(path)


def test_keywords_must_be_list(tmp_path):
    path = _write(
        tmp_path / "guides" / "x.guide.yaml",
        "intent: x\nagent: ops\nkeywords: not-a-list\nbody: b\n",
    )
    with pytest.raises(ValueError, match="keywords"):
        UsageGuide.from_yaml(path)


def test_keywords_must_be_strings(tmp_path):
    path = _write(
        tmp_path / "guides" / "x.guide.yaml",
        "intent: x\nagent: ops\nkeywords: [42, true]\nbody: b\n",
    )
    with pytest.raises(ValueError, match="keywords"):
        UsageGuide.from_yaml(path)


# ── discover_guides — glob behaviour ───────────────────────────────


def test_discover_finds_all_under_guides_dir(tmp_path):
    _write(tmp_path / "ops" / "guides" / "a.guide.yaml", VALID_YAML)
    _write(tmp_path / "audit" / "guides" / "b.guide.yaml",
           VALID_YAML.replace("agent: ops", "agent: audit").replace(
               "intent: topology_visualization", "intent: profile_authoring",
           ))
    guides = discover_guides(tmp_path)
    assert len(guides) == 2
    intents = {g.intent for g in guides}
    assert intents == {"topology_visualization", "profile_authoring"}


def test_discover_skips_invalid_files(tmp_path, caplog):
    """Bad YAML is logged + skipped; good ones still load."""
    _write(tmp_path / "ops" / "guides" / "good.guide.yaml", VALID_YAML)
    _write(tmp_path / "ops" / "guides" / "bad.guide.yaml",
           "intent: only_intent\n# missing other required keys\n")
    guides = discover_guides(tmp_path)
    assert len(guides) == 1  # bad one skipped
    assert guides[0].intent == "topology_visualization"


def test_discover_missing_root_returns_empty(tmp_path):
    """No guides/ dir → empty list, no exception."""
    guides = discover_guides(tmp_path / "nonexistent")
    assert guides == []


def test_discover_ignores_non_guide_yaml(tmp_path):
    """Only ``*.guide.yaml`` files count, regardless of parent directory.

    As of 2026-05-14 discover_guides scans *all* ``*.guide.yaml`` under the
    workspace root (not just ``guides/`` dirs).  Non-matching extensions are
    still excluded.
    """
    _write(tmp_path / "ops" / "guides" / "real.guide.yaml", VALID_YAML)
    _write(tmp_path / "ops" / "guides" / "config.yaml", VALID_YAML)   # wrong suffix
    _write(tmp_path / "ops" / "references" / "other.guide.yaml",
           VALID_YAML.replace("intent: topology_visualization", "intent: from_references"))
    guides = discover_guides(tmp_path)
    assert len(guides) == 2  # both *.guide.yaml found; config.yaml excluded
    assert all(g.source_path.suffix == ".yaml" for g in guides)
    intents = {g.intent for g in guides}
    assert intents == {"topology_visualization", "from_references"}


def test_discover_returns_sorted_for_determinism(tmp_path):
    """Stable order across calls — important for primer's ``count``
    metric and for any test that asserts on order."""
    _write(tmp_path / "ops" / "guides" / "z.guide.yaml", VALID_YAML)
    _write(tmp_path / "ops" / "guides" / "a.guide.yaml",
           VALID_YAML.replace("intent: topology_visualization", "intent: alpha"))
    guides = discover_guides(tmp_path)
    paths = [str(g.source_path) for g in guides]
    assert paths == sorted(paths)
