"""`olav catalog` — three-level drill-down over the OLAV data model.

Answers the "what can I query?" question without forcing a user to open
a DuckDB shell. Mirrors the subcommand pattern of ``olav kb``.

Levels:

* ``olav catalog``                 — list topics (inventory / topology / ...)
* ``olav catalog <topic>``         — list tables + short example per topic
* ``olav catalog describe <table>``— full schema + any ``view_recipes`` rows

**Domain-agnostic**: topics come from the ``olav.catalog_topics``
entry-point group. Each domain package (olav-netops, a future k8sops,
etc.) registers its own topics. The platform core ships no topics itself.

ARCH-12 (Sprint 5), made domain-agnostic in R70 / ADR-0002 compliance.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Topic → table map ────────────────────────────────────────────────────────


@dataclass
class _TableInfo:
    fqname: str
    summary: str
    example: str = ""


def _load_entry_point_topics() -> dict[str, list[_TableInfo]]:
    """Aggregate topics registered by domain packages.

    Each entry-point callable returns a mapping
    ``{topic_label: [{"fqname": ..., "summary": ..., "example": ...}, ...]}``.
    Domain order in the output follows discovery order (stable per
    importlib.metadata semantics).
    """
    try:
        from importlib.metadata import entry_points
    except Exception:
        return {}
    topics: dict[str, list[_TableInfo]] = {}
    try:
        eps = entry_points(group="olav.catalog_topics")
    except Exception:
        return topics
    for ep in eps:
        try:
            obj = ep.load()
            domain_topics = obj() if callable(obj) else obj
            if not isinstance(domain_topics, dict):
                continue
            for label, entries in domain_topics.items():
                if not isinstance(entries, list):
                    continue
                bucket = topics.setdefault(label, [])
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    fqname = entry.get("fqname")
                    if not fqname:
                        continue
                    bucket.append(_TableInfo(
                        fqname=str(fqname),
                        summary=str(entry.get("summary", "")),
                        example=str(entry.get("example", "")),
                    ))
        except Exception as exc:  # noqa: BLE001
            logger.debug("catalog entry-point %s failed: %s", ep.name, exc)
    return topics


def _registry_topics() -> dict[str, list[_TableInfo]]:
    """Fallback: list every table in TableRegistry under a generic topic.

    Used when no domain registered catalog topics — at least the user
    sees what tables exist. Entries have no hand-written summary.
    """
    try:
        from olav.platform.ingest_base import TableRegistry
    except Exception:
        return {}
    out: list[_TableInfo] = []
    try:
        for tbl in TableRegistry.all_tables().values():
            out.append(_TableInfo(
                fqname=tbl.qualified_name,
                summary=f"{len(tbl.columns)} columns, conflict key: "
                        f"{tbl.conflict_key}",
                example=f"SELECT * FROM {tbl.qualified_name} LIMIT 10;",
            ))
    except Exception as exc:  # noqa: BLE001
        logger.debug("TableRegistry.all_tables failed: %s", exc)
    return {"Registered Tables": out} if out else {}


def _get_topics() -> dict[str, list[_TableInfo]]:
    """Aggregate catalog topics from every installed domain.

    Priority:
      1. ``olav.catalog_topics`` entry-points (domains' hand-curated map)
      2. ``TableRegistry.list_all()`` (fallback — mechanical listing)
    """
    topics = _load_entry_point_topics()
    if topics:
        return topics
    return _registry_topics()


# ── DB helpers ───────────────────────────────────────────────────────────────


def _resolve_main_db() -> Path | None:
    try:
        from olav.core.config import MAIN_DB_PATH
    except Exception:
        return None
    p = Path(MAIN_DB_PATH)
    return p if p.exists() else None


def _table_schema(db_path: Path, fqname: str) -> list[dict[str, str]]:
    """Return a list of ``{name, type, nullable}`` for the table's columns."""
    import duckdb

    if "." in fqname:
        schema, name = fqname.split(".", 1)
    else:
        schema, name = "main", fqname

    with duckdb.connect(str(db_path), read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = ? AND table_name = ?
            ORDER BY ordinal_position
            """,
            [schema, name],
        ).fetchall()
    return [{"name": r[0], "type": r[1], "nullable": r[2]} for r in rows]


def _view_recipes_for(db_path: Path, command_like: str) -> list[dict[str, Any]]:
    """Return view_recipes rows whose command is related to a hint string."""
    import duckdb

    try:
        with duckdb.connect(str(db_path), read_only=True) as conn:
            conn.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'view_recipes' LIMIT 1"
            ).fetchone()
            rows = conn.execute(
                "SELECT command, concept FROM view_recipes "
                "WHERE command ILIKE ? LIMIT 10",
                [f"%{command_like}%"],
            ).fetchall()
    except Exception:
        return []
    return [{"command": r[0], "concept": r[1]} for r in rows]


# ── Rendering ────────────────────────────────────────────────────────────────


def _render_topics() -> str:
    topics = _get_topics()
    if not topics:
        return (
            "No catalog topics registered.\n"
            "Install a domain extension (e.g. olav-netops) or register a "
            "topic via the `olav.catalog_topics` entry-point group."
        )
    lines = ["Topics:"]
    width = max(len(t) for t in topics) if topics else 20
    for topic, tables in topics.items():
        n = len(tables)
        lines.append(f"  {topic:<{width}} — {n} table{'s' if n != 1 else ''}")
    lines.append("")
    lines.append('Use `olav catalog <topic>` to drill down.')
    first_topic = next(iter(topics))
    lines.append(f'  e.g. olav catalog "{first_topic}"')
    return "\n".join(lines)


def _render_topic(topic: str) -> str:
    topics = _get_topics()
    tables = topics.get(topic)
    if tables is None:
        known = ", ".join(repr(t) for t in topics) if topics else "(none)"
        return f"Unknown topic: {topic!r}\nAvailable: {known}"

    lines = [f"Topic: {topic}", ""]
    for t in tables:
        lines.append(f"  {t.fqname}")
        lines.append(f"    {t.summary}")
        if t.example:
            lines.append(f"    Example: {t.example}")
        lines.append("")
    lines.append(
        f'Use `olav catalog describe <table>` for full schema — e.g. '
        f'`olav catalog describe {tables[0].fqname}`.'
    )
    return "\n".join(lines)


def _render_describe(table: str) -> str:
    db_path = _resolve_main_db()
    if db_path is None:
        return (
            f"error: main DuckDB not found. Run `olav init` first, then retry."
        )

    columns = _table_schema(db_path, table)
    if not columns:
        return (
            f"Table {table!r} not found. Try `olav catalog` for a list of "
            "known topics and tables."
        )

    lines = [f"Table: {table}", ""]
    width = max(len(c["name"]) for c in columns)
    lines.append(f"  {'Column'.ljust(width)}   Type                 Nullable")
    lines.append(f"  {'-' * width}   -------------------  --------")
    for c in columns:
        nullable = "YES" if c["nullable"].upper() in ("YES", "TRUE") else "NO"
        lines.append(f"  {c['name'].ljust(width)}   {c['type']:<20} {nullable}")

    # Show related view_recipes if any
    hint = table.split(".")[-1]
    recipes = _view_recipes_for(db_path, hint)
    if recipes:
        lines.append("")
        lines.append("Related view_recipes:")
        for r in recipes:
            concept = r["concept"] or "—"
            lines.append(f"  {r['command']:<40} [{concept}]")

    return "\n".join(lines)


# ── Argparse wiring ──────────────────────────────────────────────────────────


def build_catalog_parser(parent_subparsers) -> argparse.ArgumentParser:
    """Register `catalog` subcommand on a parent argparse subparsers object."""
    parser = parent_subparsers.add_parser(
        "catalog",
        help="Browse the OLAV data model (topics → tables → schemas)",
    )
    sub = parser.add_subparsers(dest="catalog_command", help="catalog subcommand")

    show = sub.add_parser("show", help="List tables in a topic")
    show.add_argument("topic", help="Topic label — see `olav catalog` for choices")

    desc = sub.add_parser("describe", help="Show schema + view_recipes for a table")
    desc.add_argument("table", help="Fully-qualified table name, e.g. netops.devices")

    return parser


def handle_catalog_command(args) -> int:
    """Dispatch catalog subcommands from parsed argparse namespace.

    When ``args.catalog_command`` is None the bare ``olav catalog`` call
    lists topics. The routing mirrors the ``handle_kb_command`` idiom so
    cli/main.py can treat the two commands identically.
    """
    sub_cmd = getattr(args, "catalog_command", None)

    if sub_cmd is None:
        print(_render_topics())
        return 0
    if sub_cmd == "show":
        print(_render_topic(args.topic))
        return 0
    if sub_cmd == "describe":
        out = _render_describe(args.table)
        print(out)
        return 0 if not out.startswith("error:") and "not found" not in out else 1

    print(f"Unknown catalog subcommand: {sub_cmd}")
    return 2
