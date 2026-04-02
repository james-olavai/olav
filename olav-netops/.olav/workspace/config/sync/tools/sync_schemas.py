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


def _base_table_name(conn, table_name: str) -> str:
    row = conn.execute(
        """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'netops' AND table_name = ? AND table_type = 'BASE TABLE'
        """,
        [table_name],
    ).fetchone()
    return f"netops.{table_name}" if row and row[0] > 0 else table_name


def _load_rebuild_shared_contract_views():
    """Return the rebuild_shared_contract_views callable.

    Delegates to olav.core.views.ensure_semantic_views — the authoritative
    owner of all OC-aware summary view DDLs.
    """
    from olav.core.views import ensure_semantic_views  # noqa: PLC0415

    def rebuild(con, dry_run: bool = False) -> None:
        if not dry_run:
            ensure_semantic_views(con)

    return rebuild


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
    from olav.core.database import get_database  # pyright: ignore[reportMissingImports]

    db = get_database()

    if force_recreate:
        logger.warning("force_recreate=True — dropping all OLAV tables")
        for tbl in ("raw_diffs", "sync_metadata", "schema_catalog", "commands",
                    "parsed_outputs", "topology_links", "devices",
                    "routes", "bgp_neighbors", "ospf_neighbors",
                    "view_recipes"):
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
            command_name      VARCHAR NOT NULL,
            platform          VARCHAR NOT NULL,
            category          VARCHAR,
            template_path     VARCHAR,
            has_template      BOOLEAN DEFAULT FALSE,
            allowed           BOOLEAN DEFAULT TRUE,
            blacklisted       BOOLEAN DEFAULT FALSE,
            pipe_allowed      BOOLEAN DEFAULT FALSE,
            is_primary_config BOOLEAN DEFAULT FALSE,
            updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (command_name, platform)
        )
    """)
    # v0.10 migration: add is_primary_config for existing DBs where column is absent
    try:
        db.conn.execute(
            "ALTER TABLE commands ADD COLUMN IF NOT EXISTS "
            "is_primary_config BOOLEAN DEFAULT FALSE"
        )
        # Mark running-config-class commands as primary
        db.conn.execute("""
            UPDATE commands SET is_primary_config = TRUE
            WHERE lower(command_name) IN (
                'show running-config', 'show run',
                'display current-configuration', 'show configuration running'
            )
        """)
    except Exception:
        pass
    for idx, col in [("idx_cmd_platform", "platform"),
                     ("idx_cmd_category", "category"),
                     ("idx_cmd_allowed", "allowed")]:
        db.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {idx} ON commands({col})"
        )

    # ── schema_catalog ────────────────────────────────────────────────────────
    # JSON field structure index for parsed_outputs.
    # Written by sync_commands(); read by olav-ops SchemaContext at startup.
    # Enables LLM to generate: SELECT parsed_data->>'field' FROM netops.parsed_outputs
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
    parsed_outputs_table = _base_table_name(db.conn, "parsed_outputs")
    for idx, col in [("idx_po_device", "device_name"),
                     ("idx_po_command", "command"),
                     ("idx_po_snapshot", "snapshot_id")]:
        db.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {idx} ON {parsed_outputs_table}({col})"
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
            # Apply generic mappings to all platforms present in netops.devices (dynamic).
            # Fall back to a minimal seed list only if the table is not yet populated.
            try:
                _rows = db.conn.execute(
                    "SELECT DISTINCT platform FROM netops.devices WHERE platform IS NOT NULL"
                ).fetchall()
                known_platforms = [r[0] for r in _rows if r[0]]
            except Exception:
                known_platforms = []
            if not known_platforms:
                # Also seed from mapping_table itself (covers re-runs before devices are loaded)
                try:
                    _rows = db.conn.execute(
                        "SELECT DISTINCT platform FROM mapping_table WHERE platform != '_generic'"
                    ).fetchall()
                    known_platforms = [r[0] for r in _rows if r[0]]
                except Exception:
                    known_platforms = []
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
    topology_links_table = _base_table_name(db.conn, "topology_links")
    for idx, col in [("idx_tl_src", "source_device"),
                     ("idx_tl_dst", "destination_device"),
                     ("idx_tl_snapshot", "snapshot_id")]:
        db.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {idx} ON {topology_links_table}({col})"
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

    # ── view_recipes (LLM schema discovery results) ─────────────────────────
    # Populated by discover_view_schemas tool. Each row = one (command → concept)
    # mapping discovered by LLM from parsed_outputs sample data.
    # The compile_views() function reads this table to auto-generate SQL VIEWs,
    # replacing the hardcoded UNION ALL branches below with generated equivalents.
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS view_recipes (
            command        VARCHAR NOT NULL,
            concept        VARCHAR NOT NULL,  -- 'interfaces','bgp_neighbors', etc.
            vendor_hint    VARCHAR,
            field_mappings JSON    NOT NULL,  -- {"ip_address": "elem->>'ipaddress'", ...}
            filter_expr    VARCHAR,           -- optional WHERE on elem rows
            discovered_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (command, concept)
        )
    """)
    db.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_vr_concept ON view_recipes(concept)"
    )

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

    # ── topology_protocol_recipes ────────────────────────────────────────────
    # Drives _discover_topology_from_db() without hardcoded protocol logic.
    # Each row = one concept: which auto-view to query, how to classify
    # link_status from the state field, what topology link_type to assign.
    # New protocol (IS-IS, EIGRP, VXLAN): only an INSERT is needed here.
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS topology_protocol_recipes (
            concept           VARCHAR PRIMARY KEY,
            link_type         VARCHAR NOT NULL,   -- 'L2' or 'L3'
            protocol_label    VARCHAR NOT NULL,   -- stored in topology_links.discovery_protocol
            up_keywords       JSON,               -- lowercase state substrings → 'up'; NULL = always-up
            ip_device_resolve BOOLEAN DEFAULT TRUE -- JOIN v_interfaces to resolve neighbor_ip→device
        )
    """)
    for _seed in [
        ("topology_l2",    "L2", "L2",   None,         False),
        ("ospf_neighbors", "L3", "OSPF", '["full"]',   True),
        ("bgp_neighbors",  "L3", "BGP",  '["establ"]', True),
    ]:
        db.conn.execute("""
            INSERT OR IGNORE INTO topology_protocol_recipes
                (concept, link_type, protocol_label, up_keywords, ip_device_resolve)
            VALUES (?, ?, ?, ?, ?)
        """, list(_seed))

    # ── SCHEMA-ON-READ VIEWS (bootstrap, from parsed_outputs) ───────────────
    # Minimal hardcoded fallbacks active before view_recipes is populated.
    # After first onboard, v_<concept>_auto views supersede these.

    db.conn.execute("""
        CREATE OR REPLACE VIEW v_interfaces AS
        SELECT device_name,
               elem->>'interface'  AS interface,
               NULLIF(elem->>'ip_address', 'unassigned') AS ip_address,
               elem->>'status'     AS admin_status,
               elem->>'proto'      AS line_status,
               snapshot_id, created_at
        FROM (
            SELECT device_name, snapshot_id, ingested_at AS created_at,
                   unnest(from_json(parsed_data, '["json"]')) AS elem
            FROM netops.parsed_outputs
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
            SELECT device_name, snapshot_id, ingested_at AS created_at,
                   unnest(from_json(parsed_data, '["json"]')) AS elem
            FROM netops.parsed_outputs
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
            SELECT device_name, snapshot_id, ingested_at AS created_at,
                   unnest(from_json(parsed_data, '["json"]')) AS elem
            FROM netops.parsed_outputs
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
            SELECT device_name, snapshot_id, ingested_at AS created_at,
                   unnest(from_json(parsed_data, '["json"]')) AS elem
            FROM netops.parsed_outputs
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
            SELECT device_name, snapshot_id, ingested_at AS created_at,
                   unnest(from_json(parsed_data, '["json"]')) AS elem
            FROM netops.parsed_outputs
            WHERE command = 'show bgp summary'
              AND parsed_data IS NOT NULL
              AND json_array_length(parsed_data) > 0
        )
    """)

    # ── v_topo_devices ────────────────────────────────────────────────────────
    # Clean, deduplicated device list derived from topology_links.
    # SPLIT_PART strips any residual .local/.domain suffixes that slipped past ETL.
    db.conn.execute("""
        CREATE OR REPLACE VIEW v_topo_devices AS
        SELECT DISTINCT SPLIT_PART(source_device, '.', 1) AS device_name
        FROM topology_links
        WHERE source_device IS NOT NULL
        UNION
        SELECT DISTINCT SPLIT_PART(destination_device, '.', 1)
        FROM topology_links
        WHERE destination_device IS NOT NULL
    """)

    # ── v_topo_links_clean ────────────────────────────────────────────────────
    # Canonical edge table: always-clean device names, self-loops and numeric
    # OSPF subnet nodes removed.
    db.conn.execute("""
        CREATE OR REPLACE VIEW v_topo_links_clean AS
        WITH cleaned AS (
            SELECT
                link_id,
                SPLIT_PART(source_device, '.', 1)      AS src,
                source_interface,
                SPLIT_PART(destination_device, '.', 1) AS dst,
                destination_interface,
                discovery_protocol,
                link_type,
                link_status,
                snapshot_id,
                first_seen,
                last_seen
            FROM topology_links
            WHERE source_device IS DISTINCT FROM destination_device
              AND SPLIT_PART(source_device, '.', 1) IS DISTINCT FROM
                  SPLIT_PART(destination_device, '.', 1)
              AND TRY_CAST(SPLIT_PART(source_device, '.', 1) AS INTEGER) IS NULL
              AND TRY_CAST(SPLIT_PART(destination_device, '.', 1) AS INTEGER) IS NULL
              AND SPLIT_PART(source_device, '.', 1) IN (SELECT name FROM devices)
              AND SPLIT_PART(destination_device, '.', 1) IN (SELECT name FROM devices)
              AND discovery_protocol IN ('LLDP', 'CDP')
              AND COALESCE(link_type, 'L2') = 'L2'
        ),
        ranked AS (
            SELECT *,
                   row_number() OVER (
                       PARTITION BY src, source_interface, dst, destination_interface, discovery_protocol
                       ORDER BY snapshot_id DESC, COALESCE(last_seen, first_seen) DESC
                   ) AS rn
            FROM cleaned
        )
        SELECT
            link_id,
            src,
            source_interface,
            dst,
            destination_interface,
            discovery_protocol,
            link_type,
            link_status,
            MAX(snapshot_id) OVER () AS snapshot_id,
            first_seen,
            last_seen
        FROM ranked
        WHERE rn = 1
    """)

    db.conn.execute("""
        CREATE OR REPLACE VIEW v_l2_topology_summary AS
        WITH normalized AS (
            SELECT
                LEAST(src, dst) AS endpoint_a,
                GREATEST(src, dst) AS endpoint_b,
                discovery_protocol,
                COALESCE(link_status, 'up') AS link_status,
                snapshot_id
            FROM v_topo_links_clean
            WHERE discovery_protocol IN ('LLDP', 'CDP')
        ),
        ranked AS (
            SELECT *,
                   row_number() OVER (
                       PARTITION BY endpoint_a, endpoint_b, discovery_protocol
                       ORDER BY snapshot_id DESC, link_status DESC
                   ) AS rn
            FROM normalized
        )
        SELECT endpoint_a, endpoint_b, discovery_protocol, link_status,
               MAX(snapshot_id) OVER () AS snapshot_id
        FROM ranked
        WHERE rn = 1
    """)

    db.conn.execute("""
        CREATE OR REPLACE VIEW v_device_neighbors_summary AS
        WITH normalized AS (
            SELECT
                src AS device_name,
                dst AS connected_device,
                discovery_protocol,
                COALESCE(link_status, 'up') AS link_status,
                snapshot_id
            FROM v_topo_links_clean
            UNION ALL
            SELECT
                dst AS device_name,
                src AS connected_device,
                discovery_protocol,
                COALESCE(link_status, 'up') AS link_status,
                snapshot_id
            FROM v_topo_links_clean
        ),
        ranked AS (
            SELECT *,
                   row_number() OVER (
                       PARTITION BY device_name, connected_device, discovery_protocol
                       ORDER BY snapshot_id DESC, link_status DESC
                   ) AS rn
            FROM normalized
        )
        SELECT device_name, connected_device, discovery_protocol, link_status,
               MAX(snapshot_id) OVER () AS snapshot_id
        FROM ranked
        WHERE rn = 1
    """)

    rebuild_shared_contract_views = _load_rebuild_shared_contract_views()
    rebuild_shared_contract_views(db.conn)

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

    # ── raw_diffs (v0.10) ────────────────────────────────────────────────────
    # Persisted unified diffs between consecutive snapshots.
    # Written by Stage 3 of take_snapshot (diff_engine.calculate_raw_diffs).
    db.conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS raw_diffs_ts_seq START 1
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_diffs (
            snapshot_id_1   VARCHAR NOT NULL,
            snapshot_id_2   VARCHAR NOT NULL,
            device_name     VARCHAR NOT NULL,
            command         VARCHAR NOT NULL,
            diff_content    TEXT,
            diff_normalized TEXT,
            added_count     INTEGER DEFAULT 0,
            removed_count   INTEGER DEFAULT 0,
            is_pinned       BOOLEAN DEFAULT FALSE,
            timestamp       TIMESTAMP DEFAULT now(),
            PRIMARY KEY (snapshot_id_1, snapshot_id_2, device_name, command)
        )
    """)
    db.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rd_snap2 ON raw_diffs(snapshot_id_2)"
    )
    db.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rd_device ON raw_diffs(device_name)"
    )
    db.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rd_changes "
        "ON raw_diffs(added_count, removed_count)"
    )

    db.conn.commit()

    tables = ["devices", "commands", "schema_catalog",
              "parsed_outputs", "topology_links", "routes",
              "bgp_neighbors", "ospf_neighbors", "sync_metadata", "raw_diffs",
              "view_recipes"]
    views = ["v_interfaces", "v_ospf_neighbors", "v_bgp_neighbors",
             "v_topo_devices", "v_topo_links_clean",
             "v_l2_topology_summary", "v_device_neighbors_summary"]
    action = "recreated" if force_recreate else "verified"
    logger.info("sync_schemas: %s tables: %s, views: %s", action, tables, views)

    # Re-compile LLM-generated auto views from view_recipes (if any exist)
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _disco_dir = str(_Path(__file__).parent.parent.parent / "discovery" / "tools")
        if _disco_dir not in _sys.path:
            _sys.path.insert(0, _disco_dir)
        from discover_view_schemas import compile_views as _compile_views  # pyright: ignore[reportMissingImports]
        _auto_views = _compile_views(db.conn)
        if _auto_views:
            views = views + _auto_views
            logger.info("sync_schemas: compiled %d auto views: %s", len(_auto_views), _auto_views)
    except Exception as _e:
        logger.debug("sync_schemas: compile_views skipped (%s)", _e)

    return {
        "status": "success",
        "action": action,
        "tables": tables,
        "views": views,
    }
