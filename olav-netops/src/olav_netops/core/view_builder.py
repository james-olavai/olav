"""View builder — DuckDB-native zero-ETL.

R83.2 (P1) cleanup
==================

Pre-R83.2 this module hosted **two** view layers:

* **L1 — recipe-based semantic views** (``v_bgp_neighbors_auto`` /
  ``v_ospf_neighbors_auto`` / ``v_l2_links_auto``) built from
  ``view_recipes`` rows that hard-mapped ``(concept, command, vendor)``
  → ``(canonical_field_names, state_canonicalisation)``.  9 entries
  hand-curated; each new vendor / parser version required a recipe edit.
* **L2 — per-command zero-ETL views** (``v_show_<safe_command>_auto``)
  auto-generated from any non-empty ``parsed_outputs.command`` via
  DuckDB's ``unnest(from_json(parsed_data, json_structure(...)),
  recursive := true)``.

The L1 layer was the same hardcoded mapping that R78 deleted from
Python's ``_DISCOVERY_INTENTS`` / ``_PLATFORM_CONFIG_CMDS``,
re-spelled in YAML.  The user pushback in R83.2 ("A reverts to
hardcoding") was correct and applies to **all** L1 recipes — keeping
BGP/OSPF/L2 was a comfortable historical exception, not a principled
choice.

This file now keeps only:

* :func:`build_per_command_views`  — every command in parsed_outputs
  becomes a typed view via JSON-structure inference.  Pure
  introspection, zero recipes.
* :func:`build_l2_topology_view`   — minimal projection of
  ``netops.topology_links`` as ``netops.v_l2_links_auto`` (hand-coded
  but trivial — no field mappings, no vendor split, just column
  rename for backwards compatibility with consumers).
* :func:`finalise_ingest`          — the single public entry-point
  called by ``/netops_init`` Stage 3.7 and ``take_snapshot``
  post-bulk-load.

State canonicalisation (``Estab`` → ``Established``, ``FULL/DR`` →
``Full/DR``) moved to :mod:`olav_netops.tools.field_normalizer`
applied at ingest time; ``parsed_outputs.parsed_data`` already holds
the RFC names by the time any view reads it.

What was removed
----------------

* ``_BGP_STATE_CASE`` / ``_OSPF_STATE_CASE`` (SQL CASE expressions)
* ``_bgp_branch`` / ``_ospf_branch`` / ``_custom_branch`` (per-vendor
  branch builders)
* ``_BRANCH_BUILDERS`` dispatch + ``_generate_sql_branch``
* ``_fetch_recipes`` / ``ensure_view_recipes_table``
* ``_PROTOCOL_VIEW_NAMES`` / ``view_name_for``
* ``build_one_view`` / ``build_all_views``
* ``rebuild_views_for_command`` (no recipes to match against)

The orphan ``view_recipes`` table is left in the schema for now —
empty after the migration — and can be DROPped on the next round
once any external readers (audit profiles, devops scripts) have
been audited to confirm they don't reference it.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


_VIEW_NAME_RE = re.compile(r"[^a-zA-Z0-9_]+")


def _safe_view_name(command: str) -> str:
    """Turn a CLI command into a safe view-name suffix.

    ``"show ip interface brief"`` → ``"show_ip_interface_brief"``;
    ``"show bgp summary | display set"`` → ``"show_bgp_summary_display_set"``.
    Strips leading/trailing underscores; lower-cases.
    """
    return _VIEW_NAME_RE.sub("_", command.strip().lower()).strip("_")


# ── L2 topology view (minimal projection) ───────────────────────────────

def build_l2_topology_view(con: Any) -> dict[str, int]:
    """Create / refresh ``netops.v_l2_links_auto``.

    Pure column-rename projection of ``netops.topology_links`` —  no
    field mappings, no vendor split.  Kept as a stable name so
    downstream consumers (analyze skill SQL examples, audit profiles)
    don't have to know about the ``topology_links`` table directly.
    """
    try:
        con.execute(
            """
            CREATE OR REPLACE VIEW netops.v_l2_links_auto AS
            SELECT
                source_device,
                source_interface,
                destination_device,
                destination_interface,
                discovery_protocol,
                link_status,
                snapshot_id
            FROM netops.topology_links
            """
        )
        n = con.execute("SELECT COUNT(*) FROM netops.v_l2_links_auto").fetchone()[0]
        return {"v_l2_links_auto": int(n)}
    except Exception as exc:
        logger.warning("build_l2_topology_view failed: %s", exc)
        return {}


# ── DuckDB-native zero-ETL: per-command auto-views ──────────────────────
#
# For every command in ``netops.parsed_outputs``, materialise (as a
# VIEW, so no storage cost) a typed table where each column
# corresponds to a key in the parser's JSON output.
#
# Pattern (DuckDB-native, no field mappings, no recipes):
#
#   CREATE OR REPLACE VIEW netops.v_<safe_command>_auto AS
#   SELECT p.device_name, p.snapshot_id,
#          unnest(from_json(p.parsed_data, '<inferred-structure>'),
#                 recursive := true)
#   FROM netops.parsed_outputs p
#   WHERE p.command = '<command>'
#     AND p.snapshot_id = (SELECT MAX(snapshot_id) FROM netops.parsed_outputs s
#                          WHERE s.device_name = p.device_name AND s.command = p.command)
#
# ``json_structure`` infers the JSON shape from a sample row; the
# resulting view has typed columns and DESCRIBE works natively.  Agent
# can ``SELECT col FROM v_show_ip_interface_brief_auto WHERE status LIKE '%down%'``
# without any LATERAL+json_each gymnastics.

def build_per_command_views(con: Any) -> dict[str, int]:
    """Auto-create ``v_<safe_command>_auto`` views from parsed_outputs.

    Iterates every distinct command that has at least one parsed row,
    detects the JSON structure with ``json_structure(parsed_data)``,
    and CREATE OR REPLACE VIEW with ``unnest(from_json(...), recursive
    := true)`` — DuckDB exposes typed columns identical to the
    parser's output schema.

    Per-(device, command) latest-snapshot filter is applied inside the
    view so consumers don't need to know about snapshots.

    Idempotent; safe to re-run on every ``/netops_init`` and after any
    new parser is learned.

    Returns ``{view_name: row_count}`` for each successfully-created
    view; commands whose JSON structure couldn't be inferred (empty
    arrays, scalars, etc.) are silently skipped.
    """
    results: dict[str, int] = {}
    try:
        # Pick the most-recent non-empty parsed row per command and
        # ask DuckDB for its JSON structure.  ``json_structure``
        # returns a string like ``'[{"interface":"VARCHAR",...}]'``
        # which becomes the constant we bake into the view DDL.
        rows = con.execute(
            """
            WITH ranked AS (
                SELECT command, parsed_data,
                       ROW_NUMBER() OVER (PARTITION BY command ORDER BY ingested_at DESC NULLS LAST) AS rn
                FROM netops.parsed_outputs
                WHERE parsed_data IS NOT NULL
                  AND parsed_data::VARCHAR NOT IN ('[]', 'null')
            )
            SELECT command, json_structure(parsed_data)::VARCHAR AS struct
            FROM ranked
            WHERE rn = 1
            """
        ).fetchall()
    except Exception as exc:
        logger.warning("build_per_command_views: parsed_outputs scan failed: %s", exc)
        return results

    for command, structure in rows:
        if not command or not structure:
            continue
        # Only object-list shapes work — scalar / mixed shapes can't be
        # unnested into named columns.  Skip silently.
        if not structure.startswith("[{"):
            continue

        view_suffix = _safe_view_name(command)
        if not view_suffix:
            continue
        view_name = f"v_{view_suffix}_auto"

        cmd_lit = command.replace("'", "''")
        struct_lit = structure.replace("'", "''")

        ddl = f"""
            CREATE OR REPLACE VIEW netops.{view_name} AS
            SELECT p.device_name,
                   p.snapshot_id,
                   unnest(from_json(p.parsed_data, '{struct_lit}'), recursive := true)
            FROM netops.parsed_outputs p
            WHERE p.command = '{cmd_lit}'
              AND p.parsed_data IS NOT NULL
              AND p.snapshot_id = (
                  SELECT MAX(snapshot_id)
                  FROM netops.parsed_outputs s
                  WHERE s.device_name = p.device_name
                    AND s.command = p.command
              )
        """
        try:
            con.execute(ddl)
            count = con.execute(f"SELECT COUNT(*) FROM netops.{view_name}").fetchone()[0]
            results[view_name] = int(count)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "build_per_command_views: skipping %s (cmd=%r): %s",
                view_name, command, exc,
            )
    return results


# ── Finalise-ingest entry point ─────────────────────────────────────────

def finalise_ingest(con: Any) -> dict[str, Any]:
    """Rebuild every view consumers query, in the right order.

    Called after any code path that writes to ``netops.parsed_outputs``
    or ``netops.topology_links`` (``/netops_init`` Stage 3.7 and
    ``take_snapshot`` post-bulk-load).  Idempotent — safe to call
    repeatedly; CREATE OR REPLACE handles schema drift in either
    direction.

    Returns a stat dict::

        {
          "l2": {"v_l2_links_auto": N},
          "per_command": {<v_show_..._auto>: N, ...},
        }

    Failures in either layer log at WARN but don't raise — view
    building is advisory; raw ``parsed_outputs`` queries always work.
    """
    out: dict[str, Any] = {"l2": {}, "per_command": {}}
    try:
        out["l2"] = build_l2_topology_view(con)
    except Exception as exc:
        logger.warning("finalise_ingest: build_l2_topology_view failed: %s", exc)
    try:
        out["per_command"] = build_per_command_views(con)
    except Exception as exc:
        logger.warning("finalise_ingest: build_per_command_views failed: %s", exc)
    return out


__all__ = [
    "build_l2_topology_view",
    "build_per_command_views",
    "finalise_ingest",
]
