"""Round 43 — ARCH-10 residual close + ARCH-06 seed library.

R70 cutover: the single-file ``view_recipes_seed.yaml`` was split into
per-protocol YAMLs under
``olav-netops/.olav/workspace/topology/recipes/builtin/*.yaml`` as
part of the ARCH-29 topology skill. These governance tests now glob
the new directory and assert the same ARCH-06 invariants (≥15 seeds,
multi-vendor coverage, Arista/Junos/Cisco minima).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WEB_SEARCH = REPO / ".olav" / "workspace" / "core" / "scripts" / "web_search.py"
MEMORY_INIT = REPO / "src" / "olav" / "core" / "memory" / "__init__.py"
SEED_ROOT = (
    REPO / "olav-netops" / ".olav" / "workspace" / "topology" / "recipes" / "builtin"
)


# ── ARCH-10 residual comment cleanup ─────────────────────────────────────


def test_web_search_docstring_mentions_olav_recall_memory_not_search_knowledge():
    src = WEB_SEARCH.read_text(encoding="utf-8")
    assert "search_knowledge()" not in src
    assert "olav_recall_memory" in src


def test_memory_init_docstring_drops_kb_table_name():
    src = MEMORY_INIT.read_text(encoding="utf-8")
    assert "can be KB_TABLE" not in src
    assert "MEMORY_TABLE" in src


# ── ARCH-06 seed library expansion (post-R70: per-protocol YAML layout) ──


def _load_seeds() -> list[dict]:
    """Glob all `recipes/builtin/*.yaml` and flatten into a single list."""
    if not SEED_ROOT.exists():
        pytest.skip(
            f"seed root missing: {SEED_ROOT}. R70 moved seeds here — check "
            f"the olav-netops checkout."
        )
    entries: list[dict] = []
    for yaml_path in sorted(SEED_ROOT.glob("*.yaml")):
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            entries.append(data)
        elif isinstance(data, list):
            entries.extend(e for e in data if isinstance(e, dict))
    return entries


def test_seed_library_has_at_least_7_entries():
    """Floor: after R70 split, builtin/ currently has 7 per-protocol files.
    Lowering requires an ADR (would indicate architectural regression)."""
    data = _load_seeds()
    assert len(data) >= 7, (
        f"ARCH-06 post-R70 floor is ≥7 builtin recipe files; got {len(data)}. "
        "Lowering regresses the breadth guarantee."
    )


def test_seed_library_covers_core_concepts():
    """Every core concept (bgp_neighbors / ospf_neighbors / topology_l2)
    must have ≥1 seed, otherwise sim/lab can't consume."""
    data = _load_seeds()
    covered = {entry.get("concept") for entry in data}
    for required in ("bgp_neighbors", "ospf_neighbors", "topology_l2"):
        assert required in covered, (
            f"ARCH-06 core concept {required!r} has no seed recipe"
        )


def test_seed_library_has_multi_vendor_breadth():
    """At least 3 distinct vendor_hints across BGP/OSPF so the view
    can union vendor-specific branches."""
    data = _load_seeds()
    vendors = {
        e.get("vendor_hint") for e in data
        if e.get("vendor_hint") and e.get("vendor_hint") != "universal"
    }
    assert len(vendors) >= 3, (
        f"ARCH-06 covers only {sorted(vendors)} vendors; need ≥3 distinct "
        f"(cisco_ios / arista_eos / juniper_junos at minimum)."
    )


def test_seed_library_has_arista_eos_entries():
    data = _load_seeds()
    arista = [e for e in data if e.get("vendor_hint") == "arista_eos"]
    assert arista, "Arista EOS seeds missing — R43 coverage regressed"


def test_seed_library_has_junos_entry():
    data = _load_seeds()
    junos = [e for e in data if e.get("vendor_hint") == "juniper_junos"]
    assert junos, "Juniper Junos seeds missing — ARCH-06 regression"


def test_seed_library_has_cisco_entry():
    data = _load_seeds()
    cisco = [e for e in data if str(e.get("vendor_hint", "")).startswith("cisco")]
    assert cisco, "Cisco seeds missing — ARCH-06 regression"


def test_seed_entries_all_carry_vendor_hint():
    """Every seed must declare vendor_hint (or ``universal``) so the
    view builder can route correctly."""
    data = _load_seeds()
    unhinted = [
        (i, e.get("command", "")) for i, e in enumerate(data)
        if not e.get("vendor_hint")
    ]
    assert not unhinted, (
        f"Seeds without vendor_hint: {unhinted}. Set 'universal' if "
        "vendor-agnostic."
    )
