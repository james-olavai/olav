"""View builder — ARCH-28 / ARCH-29 (Path B).

Reads ``view_recipes`` + ``netops.topology_links`` and emits
``CREATE OR REPLACE VIEW netops.v_<concept>_auto`` for each concept.

Architecture principle: all canonical normalization lives in **declarative
SQL CASE** expressions here — no LLM, no Python ETL, no runtime
observation. LLM is only used once to **draft** recipe YAML; thereafter
this builder consumes the YAML (via the `view_recipes` DB table) using
pure SQL.

Public API used by:
* ``netops_init/run.py`` Stage 3.7 — ``build_all_views``
* ``take_snapshot._run_one`` post-hook — ``rebuild_views_for_command``
* topology skill tools — ``build_one_view`` + ``_generate_sql_branch``

ARCH-24 is gone (Round 70 deletion) — no parallel drift check anymore.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ── Concept → target view name ───────────────────────────────────────────

_PROTOCOL_VIEW_NAMES: dict[str, str] = {
    "bgp_neighbors": "v_bgp_neighbors_auto",
    "ospf_neighbors": "v_ospf_neighbors_auto",
    "topology_l2": "v_l2_links_auto",
}


def view_name_for(concept: str) -> str:
    """Return the canonical ``v_*_auto`` view name for a concept.

    Custom concepts (BFD / HSRP / ISIS / ...) default to
    ``v_<concept>_auto``.
    """
    return _PROTOCOL_VIEW_NAMES.get(concept, f"v_{concept}_auto")


# ── state canonicalization (SQL CASE fragments) ──────────────────────────

_BGP_STATE_CASE = """
CASE
    WHEN {src} ~ '^[0-9]+$' THEN 'Established'
    WHEN LOWER(CAST({src} AS VARCHAR)) LIKE 'establ%' THEN 'Established'
    WHEN LOWER(CAST({src} AS VARCHAR)) LIKE 'idle%' THEN 'Idle'
    WHEN LOWER(CAST({src} AS VARCHAR)) LIKE 'active%' THEN 'Active'
    WHEN LOWER(CAST({src} AS VARCHAR)) LIKE 'connect%' THEN 'Connect'
    WHEN LOWER(CAST({src} AS VARCHAR)) LIKE 'opensent%' THEN 'OpenSent'
    WHEN LOWER(CAST({src} AS VARCHAR)) LIKE 'openconfirm%' THEN 'OpenConfirm'
    WHEN LOWER(CAST({src} AS VARCHAR)) LIKE 'down%' THEN 'Down'
    ELSE CAST({src} AS VARCHAR)
END
""".strip()

_OSPF_STATE_CASE = """
CASE
    WHEN LOWER(CAST({src} AS VARCHAR)) LIKE 'full%' THEN
        CASE
            WHEN CAST({src} AS VARCHAR) LIKE '%/%' THEN CAST({src} AS VARCHAR)
            ELSE 'Full'
        END
    WHEN LOWER(CAST({src} AS VARCHAR)) LIKE '2way%' OR LOWER(CAST({src} AS VARCHAR)) LIKE '2-way%' THEN '2-Way'
    WHEN LOWER(CAST({src} AS VARCHAR)) LIKE 'init%' THEN 'Init'
    WHEN LOWER(CAST({src} AS VARCHAR)) LIKE 'exstart%' THEN 'ExStart'
    WHEN LOWER(CAST({src} AS VARCHAR)) LIKE 'exchange%' THEN 'Exchange'
    WHEN LOWER(CAST({src} AS VARCHAR)) LIKE 'loading%' THEN 'Loading'
    WHEN LOWER(CAST({src} AS VARCHAR)) LIKE 'down%' THEN 'Down'
    ELSE CAST({src} AS VARCHAR)
END
""".strip()


# ── Helpers ──────────────────────────────────────────────────────────────

def ensure_view_recipes_table(con: Any) -> None:
    """Create ``view_recipes`` if absent. Idempotent."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS view_recipes (
            command       VARCHAR NOT NULL,
            concept       VARCHAR NOT NULL,
            vendor_hint   VARCHAR,
            field_mappings JSON NOT NULL,
            filter_expr   VARCHAR,
            discovered_at TIMESTAMP,
            PRIMARY KEY (command, concept, vendor_hint)
        )
        """
    )


def _fetch_recipes(con: Any, concept: str) -> list[dict[str, Any]]:
    """Return ``view_recipes`` rows for a given concept as dicts."""
    try:
        rows = con.execute(
            "SELECT command, vendor_hint, field_mappings, filter_expr "
            "FROM view_recipes WHERE concept = ?",
            [concept],
        ).fetchall()
    except Exception as exc:
        logger.warning("view_builder: view_recipes query for %s failed: %s", concept, exc)
        return []
    out: list[dict[str, Any]] = []
    for cmd, vendor, fm, flt in rows:
        mappings = json.loads(fm) if isinstance(fm, str) else (fm or {})
        out.append({
            "command": cmd,
            "vendor_hint": vendor,
            "field_mappings": mappings,
            "filter_expr": flt,
        })
    return out


def _json_extract(field: str) -> str:
    """Case-tolerant ``json_extract_string(entry, '$.<field>')``.

    ntc-templates versions differ on field-name casing (BGP uses
    lowercase; older OSPF uses UPPERCASE). Try both via COALESCE.
    """
    lower = field.lower()
    upper = field.upper()
    if lower == upper:
        return f"json_extract_string(entry, '$.{field}')"
    return (
        f"COALESCE("
        f"json_extract_string(entry, '$.{lower}'), "
        f"json_extract_string(entry, '$.{upper}')"
        f")"
    )


def _json_extract_any(*candidates: str) -> str:
    """COALESCE across multiple source field names (for cross-version schemas)."""
    parts = [_json_extract(f) for f in candidates]
    if len(parts) == 1:
        return parts[0]
    return "COALESCE(" + ", ".join(parts) + ")"


def _vendor_filter_clause(vendor_hint: str | None) -> str:
    """SQL AND clause to restrict rows to a specific vendor.

    ``universal`` / None → no restriction.
    """
    if not vendor_hint or vendor_hint == "universal":
        return ""
    return (
        f" AND p.device_name IN (SELECT hostname FROM netops.devices "
        f"WHERE platform = '{vendor_hint}') "
    )


def _escape_sql_literal(value: str) -> str:
    """Minimal single-quote escape for embedding literals in CREATE VIEW."""
    return value.replace("'", "''")


# Latest-per-(device,command) snapshot filter.  Without this, every
# auto view returns N×M rows where N = snapshots accumulated since
# last cleanup — a `/netops_init` retry, repeated `take_snapshot`,
# or `/learn_cmd` would multiply view rowcount and produce wrong NL
# answers ("18 BGP neighbors" instead of "6").  Applied to every
# branch that reads ``netops.parsed_outputs``.
_LATEST_SNAPSHOT_FILTER = (
    " AND p.snapshot_id = (SELECT MAX(snapshot_id) "
    "FROM netops.parsed_outputs s "
    "WHERE s.device_name = p.device_name AND s.command = p.command) "
)


# ── Per-concept SQL branch generators ────────────────────────────────────

def _bgp_branch(recipe: dict[str, Any]) -> str:
    fm = recipe["field_mappings"]
    neighbor_src = fm.get("neighbor_ip", "neighbor_ip")
    as_src = fm.get("neighbor_as", "neighbor_as")
    local_as_src = fm.get("local_as")
    router_id_src = fm.get("router_id")
    state_src = fm.get("state", "state")
    uptime_src = fm.get("uptime", "uptime")
    command = _escape_sql_literal(recipe["command"])

    # Different parsers (ntc-templates versions, LLM-learned, Junos
    # custom) produce the same concept under different field names.
    # COALESCE across the known variants so the view populates
    # regardless of which parser produced the JSON. `_json_extract`
    # itself folds upper/lower case.
    neighbor_expr = _json_extract_any(
        neighbor_src, "neighbor_ip", "neighbor", "peer_address", "peer",
        "bgp_neighbor",  # ntc-templates new naming (BGP_NEIGHBOR)
    )
    as_expr = _json_extract_any(as_src, "neighbor_as", "remote_as", "peer_as")
    state_expr_src = _json_extract_any(
        state_src, "state", "state_pfxrcd", "state_pfx_rcd", "session_state",
        "state_or_prefixes_received",  # ntc-templates new naming
    )
    state_expr = _BGP_STATE_CASE.format(src=state_expr_src)
    uptime_expr = _json_extract_any(
        uptime_src, "uptime", "up_down", "elapsed_time",
    )

    select = f"""
SELECT
    p.device_name AS device,
    {neighbor_expr} AS neighbor_ip,
    TRY_CAST({as_expr} AS INTEGER) AS neighbor_as,
    {'TRY_CAST(' + _json_extract(local_as_src) + ' AS INTEGER)' if local_as_src else 'NULL::INTEGER'} AS local_as,
    {_json_extract(router_id_src) if router_id_src else 'NULL::VARCHAR'} AS router_id,
    {state_expr} AS state,
    {uptime_expr} AS uptime,
    p.snapshot_id AS snapshot_id
FROM netops.parsed_outputs p,
     LATERAL (SELECT value AS entry FROM json_each(p.parsed_data)) t
WHERE p.command = '{command}'
  AND p.parsed_data IS NOT NULL
  AND {neighbor_expr} IS NOT NULL
  AND {neighbor_expr} != ''
  {_LATEST_SNAPSHOT_FILTER}
  {_vendor_filter_clause(recipe["vendor_hint"])}
""".strip()
    if recipe.get("filter_expr"):
        select += f" AND ({recipe['filter_expr']})"
    return "(\n" + select + "\n)"


def _ospf_branch(recipe: dict[str, Any]) -> str:
    fm = recipe["field_mappings"]
    nid_src = fm.get("neighbor_id", "neighbor_id")
    ip_src = fm.get("neighbor_ip", "address")
    iface_src = fm.get("interface", "interface")
    state_src = fm.get("state", "state")
    area_src = fm.get("area")
    dead_src = fm.get("dead_time", "dead_time")
    command = _escape_sql_literal(recipe["command"])

    # COALESCE across ntc-templates' naming variants so the view
    # populates regardless of which parser wrote the JSON.
    nid_expr = _json_extract_any(nid_src, "neighbor_id", "id")
    ip_expr = _json_extract_any(ip_src, "address", "ip_address", "neighbor_ip")
    iface_expr = _json_extract_any(iface_src, "interface", "local_interface")
    state_expr_src = _json_extract_any(state_src, "state")
    state_expr = _OSPF_STATE_CASE.format(src=state_expr_src)
    dead_expr = _json_extract_any(dead_src, "dead_time", "dead")

    select = f"""
SELECT
    p.device_name AS device,
    {nid_expr} AS neighbor_id,
    {ip_expr} AS neighbor_ip,
    {iface_expr} AS interface,
    {_json_extract(area_src) if area_src else 'NULL::VARCHAR'} AS area,
    {state_expr} AS state,
    {dead_expr} AS dead_time,
    p.snapshot_id AS snapshot_id
FROM netops.parsed_outputs p,
     LATERAL (SELECT value AS entry FROM json_each(p.parsed_data)) t
WHERE p.command = '{command}'
  AND p.parsed_data IS NOT NULL
  AND {nid_expr} IS NOT NULL
  AND {nid_expr} != ''
  {_LATEST_SNAPSHOT_FILTER}
  {_vendor_filter_clause(recipe["vendor_hint"])}
""".strip()
    if recipe.get("filter_expr"):
        select += f" AND ({recipe['filter_expr']})"
    return "(\n" + select + "\n)"


def _l2_branch(recipe: dict[str, Any]) -> str:
    """L2 topology comes straight from ``netops.topology_links``.

    Recipe's ``command`` is the ``@topology_links`` sentinel; we ignore
    vendor_hint (L2 is universal) and project the table directly.
    """
    return """
SELECT
    source_device,
    source_interface,
    destination_device,
    destination_interface,
    discovery_protocol,
    link_status,
    snapshot_id
FROM netops.topology_links
""".strip()


def _custom_branch(recipe: dict[str, Any]) -> str:
    """Generic projector for user-extended concepts.

    Emits one column per canonical name in ``field_mappings``, using
    ``_json_extract`` on the declared source key. ``state`` (if present)
    is passed through raw (no CASE) — custom concepts have no universal
    canonicalization rule.
    """
    fm = recipe["field_mappings"]
    if not fm:
        return ""  # nothing to project
    command = _escape_sql_literal(recipe["command"])
    cols = []
    first_not_null_src = None
    for canonical, source in fm.items():
        cols.append(f"{_json_extract(source)} AS {canonical}")
        if first_not_null_src is None:
            first_not_null_src = source
    cols_sql = ",\n    ".join(cols)
    not_null_clause = (
        f"AND {_json_extract(first_not_null_src)} IS NOT NULL"
        if first_not_null_src else ""
    )
    select = f"""
SELECT
    p.device_name AS device,
    {cols_sql},
    p.snapshot_id AS snapshot_id
FROM netops.parsed_outputs p,
     LATERAL (SELECT value AS entry FROM json_each(p.parsed_data)) t
WHERE p.command = '{command}'
  AND p.parsed_data IS NOT NULL
  {not_null_clause}
  {_LATEST_SNAPSHOT_FILTER}
  {_vendor_filter_clause(recipe["vendor_hint"])}
""".strip()
    if recipe.get("filter_expr"):
        select += f" AND ({recipe['filter_expr']})"
    return "(\n" + select + "\n)"


_BRANCH_BUILDERS = {
    "bgp_neighbors": _bgp_branch,
    "ospf_neighbors": _ospf_branch,
    "topology_l2": _l2_branch,
}


def _generate_sql_branch(recipe: dict[str, Any], concept: str) -> str:
    """Return the SQL ``SELECT`` fragment for one recipe entry.

    For built-in concepts uses the typed branch generator; for user-added
    concepts falls back to ``_custom_branch``.
    """
    builder = _BRANCH_BUILDERS.get(concept, _custom_branch)
    return builder(recipe)


# ── Per-concept view builders ────────────────────────────────────────────

def build_one_view(con: Any, concept: str) -> dict[str, int]:
    """Build one concept's view from its ``view_recipes`` rows.

    For built-in concepts (bgp_neighbors / ospf_neighbors), UNION ALL
    across all vendor branches. For topology_l2, the single
    ``@topology_links`` recipe generates a thin projection.
    For custom concepts (BFD / HSRP / ...), UNION ALL per-vendor branches
    using :func:`_custom_branch`.

    Returns ``{view_name: row_count}`` on success, empty dict on failure.
    """
    recipes = _fetch_recipes(con, concept)
    if not recipes:
        logger.info("build_one_view: no recipes for concept %s; view skipped", concept)
        return {}

    # topology_l2 is special: single row defines a table-based projection
    if concept == "topology_l2":
        branch = _l2_branch(recipes[0])
        view_name = view_name_for(concept)
        ddl = f"CREATE OR REPLACE VIEW netops.{view_name} AS\n{branch};"
        try:
            con.execute(ddl)
            n = con.execute(f"SELECT COUNT(*) FROM netops.{view_name}").fetchone()[0]
            return {view_name: int(n)}
        except Exception as exc:
            logger.warning("build_one_view: %s failed: %s", view_name, exc)
            return {}

    branches = [_generate_sql_branch(r, concept) for r in recipes]
    branches = [b for b in branches if b]  # drop empties
    if not branches:
        return {}
    body = "\nUNION ALL\n".join(branches)
    view_name = view_name_for(concept)
    ddl = f"CREATE OR REPLACE VIEW netops.{view_name} AS\n{body};"
    try:
        con.execute(ddl)
        n = con.execute(f"SELECT COUNT(*) FROM netops.{view_name}").fetchone()[0]
        return {view_name: int(n)}
    except Exception as exc:
        logger.warning("build_one_view: %s failed: %s", view_name, exc)
        return {}


def build_all_views(con: Any) -> dict[str, int]:
    """Build every view for every concept present in ``view_recipes``.

    Idempotent. Returns ``{view_name: row_count}`` for each built view.
    """
    results: dict[str, int] = {}
    try:
        concept_rows = con.execute(
            "SELECT DISTINCT concept FROM view_recipes"
        ).fetchall()
    except Exception as exc:
        logger.warning("build_all_views: view_recipes query failed: %s", exc)
        return results
    for (concept,) in concept_rows:
        results.update(build_one_view(con, concept))
    return results


# ── Post-snapshot incremental rebuild (take_snapshot hook) ───────────────

def rebuild_views_for_command(
    con: Any,
    command: str,
    platform: str | None = None,
) -> dict[str, int]:
    """Rebuild the views whose recipes reference ``command``.

    Used by ``take_snapshot._run_one`` post-hook to refresh affected
    views after a single-command capture. Pure SQL, zero LLM.

    Args:
        con: open DuckDB read-write connection.
        command: CLI command just captured (e.g. ``show bgp summary``).
        platform: captured device platform (cisco_ios / juniper_junos / ...).
            Used to skip recipes whose vendor_hint doesn't match.

    Returns a dict of rebuilt ``{view_name: row_count}``.
    """
    try:
        matching = con.execute(
            "SELECT DISTINCT concept FROM view_recipes WHERE command = ?",
            [command],
        ).fetchall()
    except Exception:
        return {}

    results: dict[str, int] = {}
    for (concept,) in matching:
        results.update(build_one_view(con, concept))
    return results
