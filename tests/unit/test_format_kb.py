"""R85 δ2: format_guide memory category — TDD red bar.

Pin the contract for ``olav.core.memory.format_kb`` — a sibling to
guide_kb.py.  Format guides are short workflow specs for "how to
save this kind of output" (topology diagram, audit report, diff
report, ...).  They surface in the diversifier as
``category="format_guide"`` so the agent always knows the right
format_and_export call without the cross-agent delegation step.

Schema (one entry per file, ``*.format.yaml``)::

    schema_version: 1
    tag: topology_diagram
    keywords: [mermaid, topology, diagram, graph]
    body: |
      Mermaid graph TD format.  Save:
      format_and_export(data=mermaid_text, format='mmd', subdir='diagrams')

memory_id = ``format_<tag>``, category = ``format_guide``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


DIM = 32


VALID_FORMAT_YAML = """
schema_version: 1
tag: topology_diagram
keywords: [mermaid, topology, diagram]
body: |
  Mermaid graph TD format.  Build src→dst edges + summary table.
  Save: format_and_export(data=mermaid_text, format='mmd', subdir='diagrams')
"""

VALID_FORMAT_YAML_2 = """
schema_version: 1
tag: query_result
keywords: [csv, table, query]
body: |
  CSV layout for SQL result rows.
  Save: format_and_export(data=rows_json, format='csv')
"""


def _embed_stub(text: str) -> list[float]:
    return [float(len(text) % 100) / 100.0] * DIM


def _make_store(tmp_path):
    from olav.core.memory import LanceDBStore
    store = LanceDBStore(db_path=str(tmp_path / "fkb.db"), embedding_dim=DIM)
    store.create_table()
    return store


def _write_format(workspace_root: Path, name: str, body: str) -> Path:
    """Write a format YAML file.  Lives under ``<root>/formats/`` like
    guides live under ``<root>/<agent>/guides/``.
    """
    p = workspace_root / "formats" / f"{name}.format.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# ── discover_formats ───────────────────────────────────────────────


def test_discover_formats_finds_yaml(tmp_path):
    """Globs ``*.format.yaml`` under ``<workspace>/formats/``."""
    from olav.core.memory.format_kb import discover_formats

    _write_format(tmp_path, "topology_diagram", VALID_FORMAT_YAML)
    _write_format(tmp_path, "query_result", VALID_FORMAT_YAML_2)

    formats = discover_formats(tmp_path)
    assert len(formats) == 2
    tags = sorted(f.tag for f in formats)
    assert tags == ["query_result", "topology_diagram"]


def test_discover_formats_returns_empty_when_dir_missing(tmp_path):
    from olav.core.memory.format_kb import discover_formats
    out = discover_formats(tmp_path / "missing")
    assert out == []


def test_discover_formats_skips_invalid(tmp_path, caplog):
    from olav.core.memory.format_kb import discover_formats

    _write_format(tmp_path, "valid", VALID_FORMAT_YAML)
    _write_format(tmp_path, "invalid", "{ not: valid: yaml :")

    formats = discover_formats(tmp_path)
    assert len(formats) == 1


# ── FormatGuide.from_yaml ──────────────────────────────────────────


def test_format_guide_memory_id_deterministic(tmp_path):
    """memory_id = format_<tag> — idempotent."""
    from olav.core.memory.format_kb import FormatGuide
    p = _write_format(tmp_path, "x", VALID_FORMAT_YAML)
    f1 = FormatGuide.from_yaml(p)
    f2 = FormatGuide.from_yaml(p)
    assert f1.memory_id == "format_topology_diagram"
    assert f1.memory_id == f2.memory_id


def test_format_guide_missing_required_field_raises(tmp_path):
    from olav.core.memory.format_kb import FormatGuide
    p = _write_format(tmp_path, "bad", "tag: x\nkeywords: [a]\n")  # no body
    import pytest
    with pytest.raises(KeyError):
        FormatGuide.from_yaml(p)


# ── prime_formats_from_dir ─────────────────────────────────────────


def test_prime_formats_writes_one_memory_per_file(tmp_path):
    from olav.core.memory.format_kb import prime_formats_from_dir

    _write_format(tmp_path, "topology_diagram", VALID_FORMAT_YAML)
    _write_format(tmp_path, "query_result", VALID_FORMAT_YAML_2)

    store = _make_store(tmp_path)
    with patch("olav.core.memory.format_kb._embed", side_effect=_embed_stub):
        result = prime_formats_from_dir(tmp_path, store=store)

    assert result["format_entries"] == 2
    assert result["skipped"] == 0

    memories = store.get_memories(limit=10)
    fmts = [m for m in memories if m["category"] == "format_guide"]
    assert len(fmts) == 2


def test_prime_formats_uses_deterministic_id(tmp_path):
    from olav.core.memory.format_kb import prime_formats_from_dir

    _write_format(tmp_path, "topology_diagram", VALID_FORMAT_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.format_kb._embed", side_effect=_embed_stub):
        prime_formats_from_dir(tmp_path, store=store)

    memories = store.get_memories(limit=10)
    ids = [m["id"] for m in memories]
    assert "format_topology_diagram" in ids


def test_prime_formats_category_is_format_guide(tmp_path):
    from olav.core.memory.format_kb import prime_formats_from_dir

    _write_format(tmp_path, "topology_diagram", VALID_FORMAT_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.format_kb._embed", side_effect=_embed_stub):
        prime_formats_from_dir(tmp_path, store=store)

    memories = store.get_memories(limit=10)
    assert all(m["category"] == "format_guide" for m in memories)


def test_prime_formats_idempotent_upsert(tmp_path):
    from olav.core.memory.format_kb import prime_formats_from_dir

    _write_format(tmp_path, "topology_diagram", VALID_FORMAT_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.format_kb._embed", side_effect=_embed_stub):
        r1 = prime_formats_from_dir(tmp_path, store=store)
        r2 = prime_formats_from_dir(tmp_path, store=store)

    assert r1["format_entries"] == r2["format_entries"] == 1
    memories = store.get_memories(limit=10)
    matching = [m for m in memories if m["id"] == "format_topology_diagram"]
    assert len(matching) == 1


def test_prime_formats_returns_count_dict(tmp_path):
    from olav.core.memory.format_kb import prime_formats_from_dir

    _write_format(tmp_path, "topology_diagram", VALID_FORMAT_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.format_kb._embed", side_effect=_embed_stub):
        result = prime_formats_from_dir(tmp_path, store=store)

    assert isinstance(result, dict)
    assert "format_entries" in result
    assert "skipped" in result


def test_prime_formats_tags_carry_keywords(tmp_path):
    """Stored tags include the format tag + all keywords (mirrors
    guide_kb's tagging convention so a tag-FTS index can hit cleanly)."""
    from olav.core.memory.format_kb import prime_formats_from_dir

    _write_format(tmp_path, "topology_diagram", VALID_FORMAT_YAML)
    store = _make_store(tmp_path)

    with patch("olav.core.memory.format_kb._embed", side_effect=_embed_stub):
        prime_formats_from_dir(tmp_path, store=store)

    memories = store.get_memories(limit=10)
    [m] = memories
    tags = m["tags"]
    if isinstance(tags, str):
        tags = json.loads(tags)
    assert "topology_diagram" in tags
    assert "mermaid" in tags
    assert "diagram" in tags
