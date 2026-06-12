"""ARCH-12: ``olav catalog`` three-level data-model drill-down.

Tests the rendering / dispatch layer directly — each rendering helper
takes plain data, so no real CLI invocation is needed. One end-to-end
check drives ``handle_catalog_command`` via argparse-style namespaces.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import duckdb
import pytest

REPO = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO / "src" / "olav" / "cli" / "commands" / "catalog.py"


def _load_catalog_module():
    spec = importlib.util.spec_from_file_location("catalog_command_for_test", CATALOG_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


catalog_mod = _load_catalog_module()
_get_topics = catalog_mod._get_topics  # R72 V2: dynamic entry-point discovery.
_render_describe = catalog_mod._render_describe
_render_topic = catalog_mod._render_topic
_render_topics = catalog_mod._render_topics
build_catalog_parser = catalog_mod.build_catalog_parser
handle_catalog_command = catalog_mod.handle_catalog_command


# ── Topic listing ────────────────────────────────────────────────────────────


def test_topics_listing_contains_core_categories():
    """Topics visible when an extension (olav-netops) is installed."""
    out = _render_topics()
    topics = _get_topics()
    if not topics:
        pytest.skip(
            "No olav.catalog_topics entry-point registered "
            "(install olav-netops to populate)."
        )
    assert "Topics:" in out
    for topic in ("Device Inventory", "Topology", "Recipes & Views"):
        assert topic in out


def test_topic_drill_down_lists_known_table():
    if not _get_topics():
        pytest.skip("catalog_topics entry-point not registered")
    out = _render_topic("Topology")
    assert "netops.topology_links" in out
    assert "Example:" in out


def test_unknown_topic_returns_helpful_error():
    topics = _get_topics()
    out = _render_topic("Does Not Exist")
    assert "Unknown topic" in out
    if topics:
        # Must advertise at least one real option so the user can retry.
        # Use any known topic name from the dynamic set.
        assert any(t in out for t in topics)


def test_every_topic_has_at_least_one_table():
    """Guard: any registered topic must have tables."""
    topics = _get_topics()
    if not topics:
        pytest.skip("no topics registered")
    for topic, tables in topics.items():
        assert tables, f"Topic {topic!r} has no tables mapped"


# ── Describe (needs a DB) ────────────────────────────────────────────────────


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    db = tmp_path / "main.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("CREATE SCHEMA netops")
        conn.execute(
            """
            CREATE TABLE netops.devices (
                hostname VARCHAR PRIMARY KEY,
                platform VARCHAR,
                vendor VARCHAR,
                site VARCHAR
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE view_recipes (
                command VARCHAR,
                concept VARCHAR
            )
            """
        )
        conn.execute(
            "INSERT INTO view_recipes VALUES "
            "('show ip bgp neighbors', 'bgp_state'),"
            "('show ip interface brief', 'interface_state')"
        )

    # Point the catalog command at the fixture DB by monkeypatching
    # _resolve_main_db (it normally pulls from olav.core.config).
    monkeypatch.setattr(catalog_mod, "_resolve_main_db", lambda: db)
    return db


def test_describe_emits_columns_and_types(seeded_db):
    out = _render_describe("netops.devices")
    assert "Table: netops.devices" in out
    # Every column from the DDL should appear verbatim.
    for col in ("hostname", "platform", "vendor", "site"):
        assert col in out
    assert "VARCHAR" in out


def test_describe_handles_unknown_table(seeded_db):
    out = _render_describe("netops.does_not_exist")
    assert "not found" in out
    # Still hints at the catalog for recovery.
    assert "olav catalog" in out


def test_describe_lists_related_recipes_when_hint_matches(seeded_db):
    out = _render_describe("netops.devices")
    # "devices" doesn't appear in any recipe — section is omitted.
    assert "Related view_recipes" not in out


# ── End-to-end argparse dispatch ─────────────────────────────────────────────


def _build_namespace(**kwargs) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    build_catalog_parser(sub)
    return argparse.Namespace(**kwargs)


def test_handle_bare_catalog_lists_topics(capsys):
    rc = handle_catalog_command(argparse.Namespace(catalog_command=None))
    captured = capsys.readouterr()
    assert rc == 0
    if _get_topics():
        assert "Topics:" in captured.out
    else:
        assert "No catalog topics registered." in captured.out


def test_handle_catalog_show_topic(capsys):
    topics = _get_topics()
    if not topics:
        pytest.skip("catalog_topics entry-point not registered")
    topic = "Topology" if "Topology" in topics else next(iter(topics))
    rc = handle_catalog_command(
        argparse.Namespace(catalog_command="show", topic=topic)
    )
    captured = capsys.readouterr()
    assert rc == 0
    for item in topics[topic]:
        assert item.fqname in captured.out


def test_handle_catalog_describe_dispatches(capsys, seeded_db):
    rc = handle_catalog_command(
        argparse.Namespace(catalog_command="describe", table="netops.devices")
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "Table: netops.devices" in captured.out


def test_handle_catalog_describe_unknown_returns_nonzero(capsys, seeded_db):
    rc = handle_catalog_command(
        argparse.Namespace(catalog_command="describe", table="netops.nope")
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "not found" in captured.out


# ── CLI registration ─────────────────────────────────────────────────────────


def test_catalog_registered_in_main_cli():
    """Smoke-check that main.py wires `olav catalog` through argparse."""
    main_py = Path(__file__).resolve().parents[2] / "src" / "olav" / "cli" / "main.py"
    text = main_py.read_text(encoding="utf-8")
    assert "build_catalog_parser" in text, (
        "main.py no longer calls build_catalog_parser — `olav catalog` CLI "
        "is unreachable (ARCH-12 regression)."
    )
    assert 'args.command == "catalog"' in text, (
        "main.py lost the runtime dispatch branch for `catalog`."
    )
