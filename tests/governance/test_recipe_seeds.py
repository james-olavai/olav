"""ARCH-06 — view_recipes seed loader.

R70 cutover: single-file ``view_recipes_seed.yaml`` was split into
per-protocol YAML files under
``olav-netops/.olav/workspace/topology/recipes/builtin/*.yaml``.
R72 cutover: ``_KNOWN_CONCEPTS`` softened to ``_BUILTIN_CONCEPTS``
advisory list — unknown concepts are accepted with INFO log, only
malformed strings rejected.

Guards preserved (same invariants, new locations/schema):

* Every entry parses and carries required fields
* ``field_mappings`` survives JSON round-trip
* Loader is idempotent
* Core concepts remain declared in _BUILTIN_CONCEPTS
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest
import yaml


REPO = Path(__file__).resolve().parents[2]
_SEED_ROOT_CANDIDATES = [
    REPO / "olav-netops" / ".olav" / "workspace" / "netops" / "topology" / "recipes" / "builtin",
    REPO / "olav-netops" / ".olav" / "workspace" / "topology" / "recipes" / "builtin",
]
SEED_ROOT = next((p for p in _SEED_ROOT_CANDIDATES if p.exists()), _SEED_ROOT_CANDIDATES[0])


def _load_seed_entries() -> list[dict]:
    """Flatten all builtin YAML files."""
    if not SEED_ROOT.exists():
        pytest.skip(f"seed dir missing: {SEED_ROOT}")
    entries: list[dict] = []
    for yaml_path in sorted(SEED_ROOT.glob("*.yaml")):
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            entries.append(data)
        elif isinstance(data, list):
            entries.extend(e for e in data if isinstance(e, dict))
    return entries


def test_seed_yaml_parses_and_has_entries():
    entries = _load_seed_entries()
    assert len(entries) >= 7, (
        f"builtin/ has {len(entries)} entries; expected ≥7 post-R70 split."
    )


def test_every_seed_entry_has_required_fields():
    entries = _load_seed_entries()
    required = {"command", "concept", "field_mappings"}
    for i, entry in enumerate(entries):
        missing = required - set(entry)
        assert not missing, (
            f"entry #{i} {entry.get('command', '?')!r} missing: {sorted(missing)}"
        )


def test_field_mappings_json_roundtrip():
    entries = _load_seed_entries()
    for i, entry in enumerate(entries):
        fm = entry["field_mappings"]
        if not fm and not str(entry.get("command", "")).startswith("@"):
            raise AssertionError(
                f"entry #{i}: field_mappings empty for non-directive command"
            )
        assert json.loads(json.dumps(fm)) == fm


def test_loader_populates_empty_table(tmp_path):
    from olav_netops.core.recipe_seeds import load_recipe_seeds
    db = tmp_path / "main.duckdb"
    with duckdb.connect(str(db)) as con:
        stats = load_recipe_seeds(con, seed_path=SEED_ROOT, include_user=False)
        assert stats["inserted_or_updated"] >= 1
        count = con.execute("SELECT COUNT(*) FROM view_recipes").fetchone()[0]
        assert count >= 1


def test_loader_is_idempotent(tmp_path):
    from olav_netops.core.recipe_seeds import load_recipe_seeds
    db = tmp_path / "main.duckdb"
    with duckdb.connect(str(db)) as con:
        a = load_recipe_seeds(con, seed_path=SEED_ROOT, include_user=False)
        b = load_recipe_seeds(con, seed_path=SEED_ROOT, include_user=False)
        assert a["inserted_or_updated"] == b["inserted_or_updated"]


def test_loader_rejects_invalid_concept_format():
    """R72: syntactic validator accepts any [a-z][a-z0-9_]* concept;
    only uppercase/dashes rejected."""
    from olav_netops.core import recipe_seeds
    with pytest.raises(ValueError, match="invalid concept"):
        recipe_seeds._validate_entry(
            {"command": "x", "concept": "Bad-Concept", "field_mappings": {"a": "b"}},
            0,
        )


def test_loader_rejects_missing_required_field():
    from olav_netops.core import recipe_seeds
    with pytest.raises(ValueError, match="missing required fields"):
        recipe_seeds._validate_entry(
            {"concept": "bgp_neighbors", "field_mappings": {"a": "b"}}, 0
        )


def test_builtin_concepts_cover_core_topics():
    """R72: _BUILTIN_CONCEPTS is advisory;core sim/lab concepts must stay."""
    from olav_netops.core.recipe_seeds import _BUILTIN_CONCEPTS
    for required in ("bgp_neighbors", "ospf_neighbors", "topology_l2"):
        assert required in _BUILTIN_CONCEPTS
