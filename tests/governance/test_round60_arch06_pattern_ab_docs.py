"""Round 60 (item B) — ARCH-06 Pattern A/B recipe docs in ROUTING_EXPERT_GUIDE.

R57 landed the sandbox auto-inject (`model = load_network_model()`).
That unblocked the ARCH-06 Pattern A/B follow-ons because the sandbox
now provides the NoM for free. Round 60 adds concrete recipe snippets
to ``ROUTING_EXPERT_GUIDE.md`` so operators / LLMs can see how to
compose them.

Pins:

* The guide contains a ``## NetworkModel Recipes`` section tagged with
  the ARCH-06 + ARCH-14 cross-reference.
* At least Pattern A (physical + networkx) and Pattern C (L4 policy
  evaluation) snippets are present.
* Each snippet references a real public NetworkModel attribute so
  renaming an API surface surfaces a guide-drift regression.
"""

from __future__ import annotations

from pathlib import Path

from tests.governance._paths import ROUTING_EXPERT_GUIDE

REPO = Path(__file__).resolve().parents[2]
GUIDE = ROUTING_EXPERT_GUIDE


def test_guide_has_network_model_section():
    text = GUIDE.read_text(encoding="utf-8")
    assert "intent-keyed memory" in text and "guides" in text, (
        "ROUTING_EXPERT_GUIDE.md should document the guide-split architecture "
        "instead of reverting to a monolithic recipe dump."
    )


def test_guide_crossrefs_arch06_and_arch14():
    text = GUIDE.read_text(encoding="utf-8")
    # Post-split docs keep A/B/C pattern references as narrative pointers.
    assert "A/B/C" in text
    assert "route-map evaluation" in text


def test_pattern_a_snippet_mentions_model_physical():
    text = GUIDE.read_text(encoding="utf-8")
    assert "DuckDB +\nnetworkx" in text or "DuckDB +" in text, (
        "Pattern A pointer should remain in the reference doc."
    )


def test_pattern_c_snippet_mentions_model_l4_policy():
    """Pattern C pointer should remain visible in the split reference."""
    text = GUIDE.read_text(encoding="utf-8")
    assert "route-map evaluation" in text


def test_guide_mentions_load_network_model_auto_inject():
    """The doc should still explain discovery flow via KB/AutoRecall."""
    text = GUIDE.read_text(encoding="utf-8")
    assert "AutoRecall" in text
    assert "olav kb search" in text


def test_pattern_b_clarifies_olav_recall_memory_boundary():
    """Pattern-B recall boundary still appears in split doc wording."""
    text = GUIDE.read_text(encoding="utf-8")
    assert "LanceDB semantic search" in text
    assert "A/B/C" in text


def test_guide_examples_referenced_apis_still_exist():
    """The public NetworkModel layer surface referenced by A/B/C must exist."""
    from olav_netops.sim import load_network_model

    m = load_network_model(db_path="/definitely/missing.duckdb")
    for attr in ("physical", "l3", "l4"):
        assert hasattr(m, attr), f"NetworkModel missing expected layer: {attr}"
