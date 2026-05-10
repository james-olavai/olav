"""Auto-sync SCHEMA_REFERENCE.md with the live DuckDB schema.

Regenerates the 'Core Table & View Schema' section by querying
``information_schema.columns``; preserves human-written sections.
Per ADR-0007 + ADR-0008, called from curator skill scripts;
not registered as an MCP tool.

Returns ``{"status": "updated"|"up_to_date"|"error", "message": ...}``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# ─── Core objects to include in the schema reference, in display order ───────
# Tuple: (table_or_view_name, display_type)
# "display_type" is what appears in the Type column ("TABLE" or "VIEW").
# For BASE TABLEs exposed via a VIEW we write "VIEW"; for raw storage tables
# that the LLM should query directly we write "TABLE".
_CORE_OBJECTS: list[tuple[str, str]] = [
    ("devices",            "VIEW"),
    ("interfaces",         "TABLE"),
    ("v_interfaces",       "VIEW"),
    ("bgp_neighbors",      "TABLE"),
    ("v_bgp_neighbors",    "VIEW"),
    ("ospf_neighbors",     "TABLE"),
    ("v_ospf_neighbors",   "VIEW"),
    ("routes",             "TABLE"),
    ("v_routes_auto",      "VIEW"),
    ("bgp_routes",         "TABLE"),
    ("topology_links",     "VIEW"),
    ("v_topo_links_clean", "VIEW"),
    ("parsed_outputs",     "VIEW"),
]

# Columns that are purely implementation-internal and should never appear in
# query-focused documentation (scheduling metadata, auto-increments, etc.)
_GLOBAL_SKIP: frozenset[str] = frozenset({"created_at", "updated_at", "ingested_at"})

# Additional per-table skips (internal surrogate keys, low-value admin fields).
_TABLE_SKIP: dict[str, frozenset[str]] = {
    "devices":            frozenset({"device_id", "location", "site_id"}),
    "parsed_outputs":     frozenset({"id"}),
    "topology_links":     frozenset({"link_id", "first_seen", "last_seen",
                                     "last_verified", "status_changes", "link_speed"}),
    "v_topo_links_clean": frozenset({"link_id", "first_seen", "last_seen"}),
}

# Guidance notes shown in the "Notes" column of the generated table.
_OBJECT_NOTES: dict[str, str] = {
    "devices": (
        "`name` = display name. `mgmt_ip` = management IP "
        "(not `ip`, not `management_ip`)."
    ),
    "v_interfaces":    "Preferred for interface status queries.",
    "v_bgp_neighbors": "Preferred for BGP queries.",
    "v_ospf_neighbors": "Preferred; includes `dead_time`.",
    "topology_links": (
        "`source_*` / `destination_*` — NOT `local_*` or `remote_*`."
    ),
    "v_topo_links_clean": "Compact alias: use `src`/`dst` for shorter queries.",
    "parsed_outputs": (
        "Column is `parsed_data` NOT `output`; "
        "device key is `device_name` NOT `device_id`."
    ),
}

# Exact heading that marks the auto-generated section.
_SECTION_HEADING = "## 🗄️ Core Table & View Schema"

# Separator line that terminates each section in the Markdown file.
_SECTION_SEPARATOR = "\n---\n"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


def _get_columns(conn: Any, table_name: str) -> list[str]:
    """Return ordered column names for *table_name*, excluding skip sets."""
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'main' AND table_name = ? "
        "ORDER BY ordinal_position",
        [table_name],
    ).fetchall()
    skip = _GLOBAL_SKIP | _TABLE_SKIP.get(table_name, frozenset())
    return [r[0] for r in rows if r[0] not in skip]


def _build_schema_table(conn: Any) -> str:
    """Generate the Markdown table string from live DB columns."""
    lines: list[str] = [
        "| Object | Type | Key Columns | Notes |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for name, obj_type in _CORE_OBJECTS:
        cols = _get_columns(conn, name)
        if not cols:
            continue
        col_str = ", ".join(f"`{c}`" for c in cols)
        note = _OBJECT_NOTES.get(name, "")
        lines.append(f"| **`{name}`** | {obj_type} | {col_str} | {note} |")
    return "\n".join(lines) + "\n"


def _replace_section(content: str, new_table: str) -> tuple[str, bool]:
    """Replace the auto-generated section in *content*.

    Returns (updated_content, was_changed).
    Raises ValueError if the section heading is not found.
    """
    idx = content.find(_SECTION_HEADING)
    if idx == -1:
        raise ValueError(
            f"Section heading not found: {_SECTION_HEADING!r}. "
            "Ensure SCHEMA_REFERENCE.md contains this heading verbatim."
        )
    end_idx = content.find(_SECTION_SEPARATOR, idx)
    if end_idx == -1:
        raise ValueError(
            "Could not find terminating '---' separator after the schema table section."
        )

    new_section = f"{_SECTION_HEADING}\n\n{new_table}"
    updated = content[:idx] + new_section + content[end_idx:]
    return updated, updated != content


# ─── Core sync function ───────────────────────────────────────────────────────

def _sync(db_path: str, schema_ref_path: str) -> dict[str, Any]:
    import duckdb

    ref_file = Path(schema_ref_path)
    if not ref_file.exists():
        return {"status": "error", "message": f"Schema reference file not found: {schema_ref_path}"}

    original = ref_file.read_text(encoding="utf-8")

    try:
        with duckdb.connect(db_path, read_only=True) as conn:
            new_table = _build_schema_table(conn)
    except Exception as exc:
        return {"status": "error", "message": f"DB connection failed: {exc}"}

    try:
        updated, changed = _replace_section(original, new_table)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    if not changed:
        return {"status": "up_to_date", "message": "Schema reference already matches live DB."}

    ref_file.write_text(updated, encoding="utf-8")
    return {
        "status": "updated",
        "message": f"Schema reference regenerated: {schema_ref_path}",
        "path": schema_ref_path,
    }


def sync_schema_reference(
    db_path: str = "",
    schema_ref_path: str = "",
) -> dict:
    """Sync ``SCHEMA_REFERENCE.md`` with the live DuckDB schema.

    Regenerates the 'Core Table & View Schema' table by querying
    ``information_schema.columns`` for every core table and view.
    Human-written sections (SQL examples, common mistakes, fallback
    rule) are preserved. Idempotent.

    Returns ``{"status": "updated"|"up_to_date"|"error", "message": ..., "path": ...}``.
    """
    from olav.core.config import MAIN_DB_PATH

    project_root = _find_project_root()
    resolved_db = db_path or str(MAIN_DB_PATH)
    resolved_ref = schema_ref_path or str(
        project_root / ".olav" / "workspace" / "quick" / "references" / "SCHEMA_REFERENCE.md"
    )
    return _sync(db_path=resolved_db, schema_ref_path=resolved_ref)
