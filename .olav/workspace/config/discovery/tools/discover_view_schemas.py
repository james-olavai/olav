#!/usr/bin/env python3
"""
Schema Discovery Tool — LLM-native replacement for hardcoded sync_schemas views.

Architecture
============
Instead of manually adding a new UNION ALL branch to v_interfaces / v_bgp_neighbors
every time a new vendor or command appears, this tool:

  1. Scans parsed_outputs for commands not yet mapped in view_recipes
  2. Samples 3 rows of JSON data per command
  3. Asks the LLM: "what concept is this? which fields map to canonical columns?"
  4. Stores the answer in view_recipes (cached — never re-runs for known commands)
  5. Calls compile_views() which assembles UNION ALL SQL and runs CREATE OR REPLACE VIEW

Result: v_interfaces_auto, v_bgp_neighbors_auto, v_ospf_neighbors_auto, etc.
are always up-to-date with zero manual hardcoding.

Concepts recognised
===================
  interfaces      → network interfaces: ip_address, interface, admin/line status
  bgp_neighbors   → BGP sessions: neighbor_ip, neighbor_as, state
  ospf_neighbors  → OSPF adjacencies: neighbor_id, neighbor_ip, interface, state
  topology_l2     → CDP/LLDP: local_interface, destination_device, destination_interface
  routes          → routing table: network, next_hop, protocol, metric
  arp             → ARP table: ip_address, mac_address, interface
  unknown         → does not map to any known concept (skipped by compiler)
"""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from datetime import UTC, datetime, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


sys.path.insert(0, str(_find_project_root() / "src"))

from olav.core.config import MAIN_DB_PATH
from olav.core.llm import LLMFactory

# ── Canonical schema per concept ────────────────────────────────────────────
_CONCEPTS: dict[str, list[str]] = {
    "interfaces":    ["interface", "ip_address", "admin_status", "line_status"],
    "bgp_neighbors": ["neighbor_ip", "neighbor_as", "state"],
    "ospf_neighbors":["neighbor_id", "neighbor_ip", "interface", "state"],
    "topology_l2":   ["local_interface", "destination_device",
                      "destination_interface", "discovery_protocol"],
    "routes":        ["network", "next_hop", "protocol", "metric"],
    "arp":           ["ip_address", "mac_address", "interface"],
}

# Maps concept name → generated view name
_VIEW_NAMES: dict[str, str] = {
    c: f"v_{c}_auto" for c in _CONCEPTS
}


# ── LLM prompt ───────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = dedent("""\
You are a network data schema analyst.
You receive sample rows (parsed from CLI output via TextFSM, stored as JSON).
Your job: identify the canonical concept and produce DuckDB JSON extraction expressions.

Respond with ONLY valid JSON, no explanation.
""")

def _get_known_vendors() -> str:
    """Build vendor hint enum from platforms present in netops.devices.

    Strips the OS suffix (e.g. 'cisco_ios' → 'cisco', 'juniper_junos' → 'juniper')
    so the LLM gets a vendor-level hint, not a platform-level one.
    Falls back to 'unknown' only if the DB cannot be queried.
    """
    try:
        from olav.core.database import get_database as _gdb  # noqa: PLC0415
        _rows = _gdb().conn.execute(
            "SELECT DISTINCT platform FROM netops.devices WHERE platform IS NOT NULL"
        ).fetchall()
        vendors: list[str] = []
        for (plat,) in _rows:
            # 'cisco_ios' → 'cisco', 'juniper_junos' → 'juniper', 'nokia_srlinux' → 'nokia'
            vendor = plat.split("_")[0] if "_" in plat else plat
            if vendor and vendor not in vendors:
                vendors.append(vendor)
        if vendors:
            return "|".join(vendors) + "|unknown"
    except Exception:
        pass
    return "cisco|juniper|arista|huawei|nokia|unknown"


def _build_user_prompt(command: str, sample_rows: list[dict]) -> str:
    concept_list = "\n".join(
        f"  - {c}: canonical fields = {', '.join(fields)}"
        for c, fields in _CONCEPTS.items()
    )
    vendor_enum = _get_known_vendors()
    return dedent(f"""\
Command: {command!r}
Sample data (up to 3 rows from parsed_outputs):
{json.dumps(sample_rows[:3], indent=2)}

Available concepts:
{concept_list}
  - unknown: does not match any concept above

Output JSON schema:
{{
  "concept": "<concept name or 'unknown'>",
  "vendor_hint": "<{vendor_enum}>",
  "field_mappings": {{
    "<canonical_field>": "<DuckDB expression using 'elem' — e.g. elem->>'ip_address'>"
  }},
  "filter_expr": "<optional SQL WHERE condition on elem rows, or null>"
}}

Rules:
- field_mappings only needs entries for fields that ARE present in the data.
  Missing canonical fields will default to NULL.
- Use NULLIF(expr, '') to suppress empty strings.
- For ip_address fields that may contain prefix notation (e.g. '10.1.1.1/24'),
  use NULLIF(split_part(elem->>'field', '/', 1), '').
- NEVER use the || operator for string concatenation. Always use CONCAT() instead.
  WRONG: "elem->>'ip_address' || '/' || elem->>'prefix_length'"
  RIGHT: "NULLIF(CONCAT(elem->>'ip_address','/',elem->>'prefix_length'),'/')"
  This is required because DuckDB's || operator has lower precedence than ->>,
  causing incorrect SQL parses in compound expressions.
- NEVER use (elem->'field')->>N to extract array elements. This is invalid DuckDB syntax.
  If a field is a JSON array, use: elem->>'field'   (extract as text, first/only value)
  or skip it entirely. Example of WRONG syntax: (elem->'ipv6_address')->>0
- ALWAYS use ->> (double arrow) for text extraction, never -> (single arrow) in field_mappings.
- filter_expr: set to null. Do not generate filter expressions.
- For topology_l2 concept, ALWAYS set discovery_protocol to a string literal:
  - If command contains 'cdp': "discovery_protocol": "'CDP'"
  - If command contains 'lldp': "discovery_protocol": "'LLDP'"
  - Otherwise use the protocol name found in the data as an UPPERCASE literal.
""")


# ── LLM call ────────────────────────────────────────────────────────────────
def _ask_llm(command: str, sample_rows: list[dict]) -> dict:
    """Ask LLM to classify a command's JSON data and produce field mappings."""
    try:
        llm = LLMFactory.get_chat_model(agent_id="discover_view_schemas")
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_build_user_prompt(command, sample_rows)),
        ]
        response = llm.invoke(messages)
        raw = response.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        logger.warning("LLM schema discovery failed for %r: %s", command, e)
        return {"concept": "unknown", "vendor_hint": "unknown",
                "field_mappings": {}, "filter_expr": None}


# ── View compiler ────────────────────────────────────────────────────────────
def compile_views(con) -> list[str]:
    """Read view_recipes and CREATE OR REPLACE VIEW for each known concept.

    Each generated view is named v_{concept}_auto.
    Returns list of view names created/updated.
    """
    try:
        recipes = con.execute("""
            SELECT concept, command, vendor_hint, field_mappings, filter_expr
            FROM view_recipes
            WHERE concept != 'unknown'
            ORDER BY concept, command
        """).fetchall()
    except Exception as e:
        logger.warning("compile_views: could not read view_recipes: %s", e)
        return []

    if not recipes:
        return []

    by_concept: dict[str, list[dict]] = defaultdict(list)
    for concept, command, vendor, fm_json, filter_expr in recipes:
        if concept not in _CONCEPTS:
            continue
        try:
            field_mappings = json.loads(fm_json) if isinstance(fm_json, str) else fm_json
        except Exception:
            continue
        by_concept[concept].append({
            "command": command,
            "vendor": vendor,
            "fields": field_mappings,
            "filter": filter_expr,
        })

    # Primary key field per concept — used to generate a safe NULL-check WHERE clause
    _PK_FIELD: dict[str, str] = {
        "interfaces":     "interface",
        "bgp_neighbors":  "neighbor_ip",
        "ospf_neighbors": "neighbor_id",
        "topology_l2":    "destination_device",
        "routes":         "network",
        "arp":            "ip_address",
    }

    views_created = []
    for concept, recipe_list in by_concept.items():
        canonical = _CONCEPTS[concept]
        view_name = _VIEW_NAMES[concept]

        union_parts = []
        for recipe in recipe_list:
            fm = recipe["fields"]
            select_cols = ",\n               ".join(
                f"{fm.get(f, 'NULL')} AS {f}" for f in canonical
            )
            # Build a safe WHERE clause from the PK field's mapping expression.
            # We intentionally ignore the LLM's filter_expr because it may
            # produce invalid SQL due to DuckDB operator-precedence issues
            # (e.g. "X IS NOT NULL AND elem->>'y'" gets mis-parsed as
            #  "(X IS NOT NULL AND elem)->>'y'", causing a type-cast error).
            pk_field = _PK_FIELD.get(concept, canonical[0])
            pk_expr = fm.get(pk_field)
            if pk_expr:
                # Strip NULLIF wrapper if present so we get a clean expression
                raw_pk = pk_expr
                if raw_pk.upper().startswith("NULLIF("):
                    # e.g. NULLIF(elem->>'foo', '') → elem->>'foo'
                    inner = raw_pk[7:].rsplit(",", 1)[0].strip()
                    where_clause = f"WHERE ({inner}) IS NOT NULL AND ({inner}) != ''"
                else:
                    where_clause = f"WHERE ({raw_pk}) IS NOT NULL"
            else:
                where_clause = ""
            cmd = recipe["command"].replace("'", "''")  # escape for SQL literal
            union_parts.append(f"""\
        SELECT device_name,
               {select_cols},
               snapshot_id, created_at
        FROM (
            SELECT device_name, snapshot_id, ingested_at AS created_at,
                   unnest(from_json(parsed_data, '["json"]')) AS elem
            FROM netops.parsed_outputs
            WHERE command = '{cmd}'
              AND parsed_data IS NOT NULL
              AND json_array_length(parsed_data) > 0
        )
        {where_clause}""")

        view_sql = (
            f"CREATE OR REPLACE VIEW {view_name} AS\n"
            + "\nUNION ALL\n".join(union_parts)
        )
        try:
            con.execute(view_sql)
            views_created.append(view_name)
            logger.info("compiled view: %s (%d commands)", view_name, len(recipe_list))
        except Exception as e:
            logger.warning("failed to compile %s: %s", view_name, e)

    return views_created


# ── Main tool ────────────────────────────────────────────────────────────────
class DiscoverViewSchemasInput(BaseModel):
    force_refresh: bool = Field(
        default=False,
        description="Re-run LLM discovery even for commands already in view_recipes.",
    )
    concepts_filter: list[str] | None = Field(
        default=None,
        description="Only discover/compile these concepts. None = all.",
    )


@tool(args_schema=DiscoverViewSchemasInput)
def discover_view_schemas(
    force_refresh: bool = False,
    concepts_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Discover schema mappings for parsed CLI outputs using LLM, then compile SQL views.

    Scans parsed_outputs for new commands, asks LLM to identify which canonical
    concept each command represents (interfaces, bgp_neighbors, etc.) and which
    JSON fields map to canonical columns. Results are cached in view_recipes and
    used to generate v_{concept}_auto views via UNION ALL SQL.

    This replaces the hardcoded UNION branches in sync_schemas.py with a
    self-updating, vendor-agnostic mechanism.

    Returns:
        new_recipes:   number of new commands discovered by LLM
        views_compiled: list of view names created/updated
        skipped:       commands LLM labelled as 'unknown'
    """
    import duckdb

    results: dict[str, Any] = {
        "new_recipes": 0,
        "views_compiled": [],
        "skipped": [],
        "errors": [],
    }

    with duckdb.connect(str(MAIN_DB_PATH)) as con:
        # ── ensure view_recipes table exists ────────────────────────────────
        con.execute("""
            CREATE TABLE IF NOT EXISTS view_recipes (
                command        VARCHAR NOT NULL,
                concept        VARCHAR NOT NULL,
                vendor_hint    VARCHAR,
                field_mappings JSON    NOT NULL,
                filter_expr    VARCHAR,
                discovered_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (command, concept)
            )
        """)

        # ── find commands not yet in view_recipes ────────────────────────────
        if force_refresh:
            new_commands = con.execute("""
                SELECT DISTINCT command FROM netops.parsed_outputs
                WHERE parsed_data IS NOT NULL
                  AND json_array_length(parsed_data) > 0
                ORDER BY command
            """).fetchall()
        else:
            new_commands = con.execute("""
                SELECT DISTINCT p.command
                FROM netops.parsed_outputs p
                WHERE p.parsed_data IS NOT NULL
                  AND json_array_length(p.parsed_data) > 0
                  AND NOT EXISTS (
                      SELECT 1 FROM view_recipes r WHERE r.command = p.command
                  )
                ORDER BY p.command
            """).fetchall()

        new_commands = [r[0] for r in new_commands]
        logger.info("discover_view_schemas: %d new commands to process", len(new_commands))

        # ── run LLM discovery for each new command ───────────────────────────
        for command in new_commands:
            try:
                # Sample up to 3 distinct non-empty rows
                rows = con.execute("""
                    SELECT parsed_data FROM netops.parsed_outputs
                    WHERE command = ?
                      AND parsed_data IS NOT NULL
                      AND json_array_length(parsed_data) > 0
                    LIMIT 1
                """, [command]).fetchone()
                if not rows:
                    continue
                sample_data = json.loads(rows[0])[:3]
                if not sample_data:
                    continue

                mapping = _ask_llm(command, sample_data)
                concept = mapping.get("concept", "unknown")

                if concepts_filter and concept not in concepts_filter:
                    continue

                # Store in view_recipes (upsert)
                con.execute("""
                    INSERT INTO view_recipes
                        (command, concept, vendor_hint, field_mappings, filter_expr, discovered_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (command, concept) DO UPDATE SET
                        vendor_hint    = EXCLUDED.vendor_hint,
                        field_mappings = EXCLUDED.field_mappings,
                        filter_expr    = EXCLUDED.filter_expr,
                        discovered_at  = EXCLUDED.discovered_at
                """, [
                    command,
                    concept,
                    mapping.get("vendor_hint", "unknown"),
                    json.dumps(mapping.get("field_mappings", {})),
                    mapping.get("filter_expr"),
                    datetime.now(UTC),
                ])

                if concept == "unknown":
                    results["skipped"].append(command)
                else:
                    results["new_recipes"] += 1
                    logger.info("  %r → concept=%s vendor=%s",
                                command, concept, mapping.get("vendor_hint"))

            except Exception as e:
                results["errors"].append(f"{command}: {e}")
                logger.warning("Error processing %r: %s", command, e)

        # ── compile all recipes into SQL views ───────────────────────────────
        views = compile_views(con)
        results["views_compiled"] = views

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = discover_view_schemas.func()
    print(json.dumps(result, indent=2, default=str))
