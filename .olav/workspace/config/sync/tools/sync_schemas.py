"""init_db — Initialize or migrate OLAV DuckDB schema.

olav-config is the infrastructure layer.  Any table creation or schema
migration lives here, not in src/olav/core/database.py.

Call init_db() on first setup or after a schema change.
It is idempotent — safe to call multiple times.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Default mappings for common platform-specific keys
DEFAULT_MAPPINGS = {
    # Cisco IOS -> Unified
    "cisco_ios": {
        "neighbor_id": "neighbor_router_id",
        "neighbor_address": "neighbor_ip_address",
        "local_interface": "local_port",
        "device_id": "device_identifier",
        "holding_time": "neighbor_hold_time",
        "capabilities": "neighbor_capabilities",
        "platform": "neighbor_platform",
        "port_id": "neighbor_port",
    },
    # Juniper JunOS -> Unified
    "juniper_junos": {
        "peer_id": "neighbor_router_id",
        "peer_address": "neighbor_ip_address",
        "interface_name": "local_port",
        "peer_device_id": "device_identifier",
        "dead_after": "neighbor_hold_time",
        "peer_state": "neighbor_state",
    },
    # Arista EOS -> Unified
    "arista_eos": {
        "peer": "neighbor_router_id",
        "peer_ip": "neighbor_ip_address",
        "interface": "local_port",
        "state": "neighbor_state",
    },
    # Generic/Common mappings
    "_generic": {
        "ip_address": "ip_addr",
        "mac_address": "mac_addr",
        "interface": "port",
        "status": "state",
        "hostname": "device_name",
        "uptime": "device_uptime",
    },
}


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()



@tool
def sync_schemas(force_recreate: bool = False) -> dict:
    """Create or migrate all OLAV DuckDB table schemas.

    Ensures the following tables exist in .olav/databases/main.duckdb:
      - devices           : device inventory (populated by sync_inventory)
      - commands          : command registry — which commands to collect per platform
      - schema_catalog    : JSON field index for parsed_outputs (used by olav-ops LLM)
      - parsed_outputs    : TextFSM-parsed output blobs (written by take_snapshot)
      - topology_links    : CDP/LLDP neighbour relationships
      - sync_metadata     : snapshot run metadata (timing, device count, errors)

    NOTE: audit_results table is intentionally NOT created here.
    olav-audit is a read-only governance layer; findings are written to KB instead.

    Idempotent — uses CREATE TABLE IF NOT EXISTS.
    Call this on first setup or after adding a new table definition.

    Args:
        force_recreate: DROP and recreate all tables. DESTRUCTIVE.
                        Use only in dev/test to reset state.

    Returns:
        {"status": "success", "tables": [...], "action": "created" | "verified"}
    """
    from olav.core.database import get_database

    db = get_database()

    if force_recreate:
        logger.warning("force_recreate=True — dropping all OLAV tables")
        for tbl in ("sync_metadata", "schema_catalog", "commands",
                    "parsed_outputs", "topology_links", "devices",
                    "routes", "bgp_neighbors", "ospf_neighbors"):
            try:
                db.conn.execute(f"DROP TABLE IF EXISTS {tbl}")
            except Exception as e:
                logger.debug(f"Drop {tbl}: {e}")

    # ── devices ──────────────────────────────────────────────────────────────
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            device_id    VARCHAR PRIMARY KEY,
            name         VARCHAR,
            hostname     VARCHAR,
            platform     VARCHAR,
            mgmt_ip      VARCHAR,
            device_type  VARCHAR,
            device_role  VARCHAR,
            site         VARCHAR,
            location     VARCHAR,
            vendor       VARCHAR,
            model        VARCHAR,
            site_id      VARCHAR,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active    BOOLEAN DEFAULT TRUE
        )
    """)

    # ── commands ─────────────────────────────────────────────────────────────
    # Command registry — which CLI commands to collect per platform.
    # Written by sync_commands(); read by take_snapshot() and olav-ops.
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS commands (
            command_name   VARCHAR NOT NULL,
            platform       VARCHAR NOT NULL,
            category       VARCHAR,
            template_path  VARCHAR,
            has_template   BOOLEAN DEFAULT FALSE,
            allowed        BOOLEAN DEFAULT TRUE,
            blacklisted    BOOLEAN DEFAULT FALSE,
            pipe_allowed   BOOLEAN DEFAULT FALSE,
            updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (command_name, platform)
        )
    """)
    for idx, col in [("idx_cmd_platform", "platform"),
                     ("idx_cmd_category", "category"),
                     ("idx_cmd_allowed", "allowed")]:
        db.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {idx} ON commands({col})"
        )

    # ── schema_catalog ────────────────────────────────────────────────────────
    # JSON field structure index for parsed_outputs.
    # Written by sync_commands(); read by olav-ops SchemaContext at startup.
    # Enables LLM to generate: SELECT parsed_data->>'field' FROM parsed_outputs
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_catalog (
            source_type    VARCHAR NOT NULL,
            source_name    VARCHAR NOT NULL,
            platform       VARCHAR NOT NULL,
            fields         JSON    NOT NULL,
            description    VARCHAR,
            updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (source_name, platform, source_type)
        )
    """)
    for idx, col in [("idx_sc_platform", "platform"),
                     ("idx_sc_source_type", "source_type")]:
        db.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {idx} ON schema_catalog({col})"
        )

    # ── parsed_outputs ────────────────────────────────────────────────────────
    db.conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS parsed_outputs_id_seq START 1
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS parsed_outputs (
            id            INTEGER PRIMARY KEY DEFAULT nextval('parsed_outputs_id_seq'),
            device_name   VARCHAR NOT NULL,
            command       VARCHAR NOT NULL,
            parsed_data   JSON    NOT NULL,
            raw_output    VARCHAR,
            snapshot_id   VARCHAR NOT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(device_name, command, snapshot_id)
        )
    """)
    for idx, col in [("idx_po_device", "device_name"),
                     ("idx_po_command", "command"),
                     ("idx_po_snapshot", "snapshot_id")]:
        db.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {idx} ON parsed_outputs({col})"
        )

    # ── mapping_table ────────────────────────────────────────────────────────
    # Unified field mapping for cross-platform data normalization.
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS mapping_table (
            platform      VARCHAR NOT NULL,
            platform_key  VARCHAR NOT NULL,
            unified_key   VARCHAR NOT NULL,
            description   VARCHAR,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(platform, platform_key)
        )
    """)
    # Seed mapping_table defaults
    for platform, mappings in DEFAULT_MAPPINGS.items():
        if platform == "_generic":
            # Apply generic mappings to all known platforms
            known_platforms = ["cisco_ios", "juniper_junos", "arista_eos", "huawei_vrp", "linux"]
            for p in known_platforms:
                for p_key, u_key in mappings.items():
                    db.conn.execute("""
                        INSERT OR IGNORE INTO mapping_table (platform, platform_key, unified_key, description)
                        VALUES (?, ?, ?, ?)
                    """, [p, p_key, u_key, f"Generic mapping: {p_key} -> {u_key}"])
        else:
            for p_key, u_key in mappings.items():
                db.conn.execute("""
                    INSERT OR IGNORE INTO mapping_table (platform, platform_key, unified_key, description)
                    VALUES (?, ?, ?, ?)
                """, [platform, p_key, u_key, f"Default mapping: {p_key} -> {u_key}"])
    db.conn.commit()

    # ── topology_links ────────────────────────────────────────────────────────
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS topology_links (
            link_id              VARCHAR PRIMARY KEY,
            source_device        VARCHAR NOT NULL,
            source_interface     VARCHAR NOT NULL,
            destination_device   VARCHAR NOT NULL,
            destination_interface VARCHAR NOT NULL,
            discovery_protocol   VARCHAR,
            link_type            VARCHAR,
            link_status          VARCHAR DEFAULT 'up',
            link_speed           VARCHAR,
            first_seen           TIMESTAMP NOT NULL,
            last_seen            TIMESTAMP NOT NULL,
            last_verified        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status_changes       INTEGER DEFAULT 0,
            snapshot_id          VARCHAR NOT NULL,
            platform             VARCHAR,
            UNIQUE(source_device, source_interface,
                   destination_device, destination_interface, snapshot_id)
        )
    """)
    for idx, col in [("idx_tl_src", "source_device"),
                     ("idx_tl_dst", "destination_device"),
                     ("idx_tl_snapshot", "snapshot_id")]:
        db.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {idx} ON topology_links({col})"
        )


    # ── routes ───────────────────────────────────────────────────────────────
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS routes (
            device_name  VARCHAR NOT NULL,
            network      VARCHAR NOT NULL,
            mask         VARCHAR,
            next_hop     VARCHAR,
            interface    VARCHAR,
            protocol     VARCHAR,
            metric       INTEGER,
            snapshot_id  VARCHAR NOT NULL,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (device_name, network, mask, snapshot_id)
        )
    """)

    # ── bgp_neighbors ────────────────────────────────────────────────────────
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS bgp_neighbors (
            device_name       VARCHAR NOT NULL,
            neighbor_ip       VARCHAR NOT NULL,
            neighbor_as       VARCHAR,
            state             VARCHAR,
            prefixes_received INTEGER,
            snapshot_id       VARCHAR NOT NULL,
            created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (device_name, neighbor_ip, snapshot_id)
        )
    """)

    # ── ospf_neighbors ───────────────────────────────────────────────────────
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS ospf_neighbors (
            device_name    VARCHAR NOT NULL,
            neighbor_id    VARCHAR NOT NULL,
            neighbor_ip    VARCHAR,
            interface      VARCHAR,
            state          VARCHAR,
            priority       INTEGER,
            snapshot_id    VARCHAR NOT NULL,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (device_name, neighbor_id, snapshot_id)
        )
    """)

    # ── interfaces (IPAM) ───────────────────────────────────────────────────
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS interfaces (
            device_name  VARCHAR NOT NULL,
            interface    VARCHAR NOT NULL,
            ip_address   VARCHAR,
            status       VARCHAR,
            description  VARCHAR,
            snapshot_id  VARCHAR NOT NULL,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (device_name, interface, snapshot_id)
        )
    """)
    db.conn.execute("CREATE INDEX IF NOT EXISTS idx_intf_ip ON interfaces(ip_address)")

    # ── bgp_routes (RIB) ────────────────────────────────────────────────────
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS bgp_routes (
            device_name   VARCHAR NOT NULL,
            network       VARCHAR NOT NULL,
            mask          VARCHAR,
            next_hop      VARCHAR,
            as_path       VARCHAR,
            local_pref    INTEGER,
            metric        INTEGER,
            weight        INTEGER,
            communities   VARCHAR,
            path_type     VARCHAR,
            best_path     BOOLEAN,
            snapshot_id   VARCHAR NOT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (device_name, network, mask, next_hop, snapshot_id)
        )
    """)

    # ── ENRICHED VIEWS ──────────────────────────────────────────────────────

    # 1. Enriched Interfaces (IP -> Device mapping)
    db.conn.execute("""
        CREATE OR REPLACE VIEW v_interfaces_enriched AS
        SELECT 
            i.*,
            d.hostname AS device_hostname,
            d.device_role,
            d.site
        FROM interfaces i
        LEFT JOIN devices d ON i.device_name = d.name
    """)

    # 2. Enriched BGP Neighbors (IPs resolved to Device names)
    db.conn.execute("""
        CREATE OR REPLACE VIEW v_bgp_neighbors_enriched AS
        SELECT 
            b.*,
            b.device_name AS local_device,
            i_dst.device_name AS peer_device_name
        FROM bgp_neighbors b
        LEFT JOIN interfaces i_dst ON b.neighbor_ip = i_dst.ip_address
    """)

    # 3. Enriched Routes (Next-hop resolved to Device names)
    db.conn.execute("""
        CREATE OR REPLACE VIEW v_routes_enriched AS
        SELECT 
            r.*,
            i.device_name AS next_hop_device
        FROM routes r
        LEFT JOIN interfaces i ON r.next_hop = i.ip_address
    """)

    # ── SCHEMA-ON-READ VIEWS (from parsed_outputs) ──────────────────────────
    # These replace the empty normalized tables with zero-ETL DuckDB VIEWs.
    # Each VIEW unnests the JSON array from parsed_outputs and maps vendor
    # field names to a unified schema at query time (OLAV LLM-Native principle).

    db.conn.execute("""
        CREATE OR REPLACE VIEW v_interfaces AS
        SELECT device_name,
               elem->>'interface'  AS interface,
               NULLIF(elem->>'ip_address', 'unassigned') AS ip_address,
               elem->>'status'     AS admin_status,
               elem->>'proto'      AS line_status,
               snapshot_id, created_at
        FROM (
            SELECT device_name, snapshot_id, created_at,
                   unnest(from_json(parsed_data, '["json"]')) AS elem
            FROM parsed_outputs
            WHERE command = 'show ip interface brief'
              AND parsed_data IS NOT NULL
              AND json_array_length(parsed_data) > 0
        )
        UNION ALL
        SELECT device_name,
               elem->>'interface'   AS interface,
               NULLIF(split_part(elem->>'local_ip', '/', 1), '') AS ip_address,
               elem->>'admin_state' AS admin_status,
               elem->>'link_state'  AS line_status,
               snapshot_id, created_at
        FROM (
            SELECT device_name, snapshot_id, created_at,
                   unnest(from_json(parsed_data, '["json"]')) AS elem
            FROM parsed_outputs
            WHERE command = 'show interfaces terse'
              AND parsed_data IS NOT NULL
              AND json_array_length(parsed_data) > 0
        )
    """)

    db.conn.execute("""
        CREATE OR REPLACE VIEW v_ospf_neighbors AS
        SELECT device_name,
               elem->>'neighbor_id' AS neighbor_id,
               elem->>'ip_address'  AS neighbor_ip,
               elem->>'interface'   AS interface,
               elem->>'state'       AS state,
               elem->>'priority'    AS priority,
               elem->>'dead_time'   AS dead_time,
               snapshot_id, created_at
        FROM (
            SELECT device_name, snapshot_id, created_at,
                   unnest(from_json(parsed_data, '["json"]')) AS elem
            FROM parsed_outputs
            WHERE command IN ('show ospf neighbor', 'show ip ospf neighbor')
              AND parsed_data IS NOT NULL
              AND json_array_length(parsed_data) > 0
        )
    """)

    db.conn.execute("""
        CREATE OR REPLACE VIEW v_bgp_neighbors AS
        SELECT device_name,
               elem->>'bgp_neighbor' AS neighbor_ip,
               elem->>'neighbor_as'  AS neighbor_as,
               CASE WHEN regexp_matches(COALESCE(elem->>'state_or_prefixes_received',''), '^[0-9]+$')
                    THEN 'Established'
                    ELSE COALESCE(elem->>'state_or_prefixes_received', 'Unknown')
               END AS state,
               CASE WHEN regexp_matches(COALESCE(elem->>'state_or_prefixes_received',''), '^[0-9]+$')
                    THEN (elem->>'state_or_prefixes_received')::INTEGER
               END AS prefixes_received,
               snapshot_id, created_at
        FROM (
            SELECT device_name, snapshot_id, created_at,
                   unnest(from_json(parsed_data, '["json"]')) AS elem
            FROM parsed_outputs
            WHERE command = 'show ip bgp summary'
              AND parsed_data IS NOT NULL
              AND json_array_length(parsed_data) > 0
        )
        UNION ALL
        SELECT device_name,
               elem->>'peer'     AS neighbor_ip,
               elem->>'peer_as'  AS neighbor_as,
               elem->>'state'    AS state,
               NULL::INTEGER     AS prefixes_received,
               snapshot_id, created_at
        FROM (
            SELECT device_name, snapshot_id, created_at,
                   unnest(from_json(parsed_data, '["json"]')) AS elem
            FROM parsed_outputs
            WHERE command = 'show bgp summary'
              AND parsed_data IS NOT NULL
              AND json_array_length(parsed_data) > 0
        )
    """)

    db.conn.execute("""
        CREATE OR REPLACE VIEW v_routes AS
        SELECT device_name,
               elem->>'network'       AS network,
               elem->>'prefix_length' AS mask,
               elem->>'nexthop_ip'    AS next_hop,
               elem->>'nexthop_if'    AS interface,
               elem->>'protocol'      AS protocol,
               elem->>'distance'      AS distance,
               elem->>'metric'        AS metric,
               snapshot_id, created_at
        FROM (
            SELECT device_name, snapshot_id, created_at,
                   unnest(from_json(parsed_data, '["json"]')) AS elem
            FROM parsed_outputs
            WHERE command = 'show ip route'
              AND parsed_data IS NOT NULL
              AND json_array_length(parsed_data) > 0
        )
    """)

    db.conn.execute("""
        CREATE OR REPLACE VIEW v_topology_from_parsed AS
        -- Deduplicate: prefer 'detail' commands over 'brief' for each link.
        -- For LLDP: use neighbor_name (not neighbor_port_id) as destination.
        WITH all_links AS (
            -- LLDP neighbors
            SELECT device_name AS source_device,
                   elem->>'local_interface'    AS source_interface,
                   NULLIF(elem->>'neighbor_name', '') AS destination_device,
                   elem->>'neighbor_interface' AS destination_interface,
                   'LLDP'                      AS discovery_protocol,
                   elem->>'chassis_id'         AS chassis_id,
                   snapshot_id,
                   CASE WHEN command LIKE '%detail%' THEN 1 ELSE 2 END AS priority
            FROM (
                SELECT device_name, snapshot_id, command,
                       unnest(from_json(parsed_data, '["json"]')) AS elem
                FROM parsed_outputs
                WHERE command LIKE '%lldp%neighbor%'
                  AND parsed_data IS NOT NULL
                  AND json_array_length(parsed_data) > 0
            )
            UNION ALL
            -- CDP neighbors
            SELECT device_name              AS source_device,
                   elem->>'local_interface'    AS source_interface,
                   NULLIF(elem->>'neighbor_name', '') AS destination_device,
                   elem->>'neighbor_interface' AS destination_interface,
                   'CDP'                       AS discovery_protocol,
                   NULL                        AS chassis_id,
                   snapshot_id,
                   CASE WHEN command LIKE '%detail%' THEN 1 ELSE 2 END AS priority
            FROM (
                SELECT device_name, snapshot_id, command,
                       unnest(from_json(parsed_data, '["json"]')) AS elem
                FROM parsed_outputs
                WHERE command LIKE '%cdp%neighbor%'
                  AND parsed_data IS NOT NULL
                  AND json_array_length(parsed_data) > 0
            )
        ),
        ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY source_device, destination_device, discovery_protocol
                       ORDER BY priority
                   ) AS rn
            FROM all_links
            WHERE destination_device IS NOT NULL
        )
        SELECT source_device, source_interface, destination_device,
               destination_interface, discovery_protocol, chassis_id, snapshot_id
        FROM ranked WHERE rn = 1
    """)

    # ── sync_metadata ─────────────────────────────────────────────────────────
    # Snapshot run metadata: timing, device counts, errors.
    # Previously created at runtime in sync_tools.py; now pre-defined here.
    db.conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS sync_metadata_id_seq START 1
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_metadata (
            id            INTEGER PRIMARY KEY DEFAULT nextval('sync_metadata_id_seq'),
            sync_type     VARCHAR NOT NULL,
            start_time    TIMESTAMP NOT NULL,
            end_time      TIMESTAMP,
            status        VARCHAR NOT NULL,
            device_count  INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            error_count   INTEGER DEFAULT 0,
            error_details JSON,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sm_type ON sync_metadata(sync_type)"
    )
    db.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sm_time ON sync_metadata(start_time)"
    )

    db.conn.commit()

    tables = ["devices", "commands", "schema_catalog",
              "parsed_outputs", "topology_links", "routes",
              "bgp_neighbors", "ospf_neighbors", "sync_metadata"]
    views = ["v_interfaces", "v_ospf_neighbors", "v_bgp_neighbors",
             "v_routes", "v_topology_from_parsed",
             "v_interfaces_enriched", "v_bgp_neighbors_enriched", "v_routes_enriched"]
    action = "recreated" if force_recreate else "verified"
    logger.info(f"sync_schemas: {action} tables: {tables}, views: {views}")
    action = "recreated" if force_recreate else "verified"
    logger.info(f"sync_schemas: {action} tables: {tables}")

    return {
        "status": "success",
        "action": action,
        "tables": tables,
        "views": views,
    }
