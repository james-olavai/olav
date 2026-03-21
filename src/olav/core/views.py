"""Semantic Views — authoritative DDL definitions for OpenConfig-aware summary views.

Provides:
    V_INTERFACES_AUTO_DDL         → SQL DDL string for v_interfaces_auto
    V_BGP_NEIGHBORS_AUTO_DDL      → SQL DDL string for v_bgp_neighbors_auto
    V_TOPO_LINKS_CLEAN_DDL        → SQL DDL string for v_topo_links_clean
    V_L2_TOPOLOGY_SUMMARY_DDL     → SQL DDL string for v_l2_topology_summary
    V_DEVICE_NEIGHBORS_SUMMARY_DDL → SQL DDL string for v_device_neighbors_summary
    ensure_semantic_views(con)    → create/replace all views in the given connection
    list_semantic_views()         → return ordered list of view names

Design notes:
    - This module is the single source of truth for all semantic view DDLs
      (AGENTS.md §3 Storage SSOT, Phase 3 view ownership).
    - ``ensure_semantic_views`` is idempotent (CREATE OR REPLACE).
    - Wrapper views ``v_interfaces`` and ``v_bgp_neighbors`` are simple
      SELECT * aliases over the ``_auto`` base views.
    - Views are applied in dependency order:
        1. v_interfaces_auto  → v_interfaces
        2. v_bgp_neighbors_auto → v_bgp_neighbors
        3. v_topo_links_clean
        4. v_l2_topology_summary      (depends on v_topo_links_clean)
        5. v_device_neighbors_summary (depends on v_topo_links_clean)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL constants — exact SQL, do not modify logic
# ---------------------------------------------------------------------------

V_INTERFACES_AUTO_DDL: str = """
CREATE OR REPLACE VIEW v_interfaces_auto AS
WITH cli_source AS (
    SELECT device_name, snapshot_id, created_at, unnest(from_json(parsed_data, '["json"]')) AS elem
    FROM parsed_outputs
    WHERE command IN ('show interfaces', 'show ip interface', 'show ip interface brief')
      AND parsed_data IS NOT NULL
      AND json_array_length(parsed_data) > 0
),
router_id_rows AS (
    SELECT
        device_name,
        'Loopback0' AS interface,
        NULLIF(
            regexp_extract(
                COALESCE(
                    json_extract_string(elem, '$."openconfig-bgp".bgp.global.config."router-id"'),
                    json_extract_string(elem, '$."openconfig-bgp".bgp.global.state."router-id"'),
                    json_extract_string(elem, '$._unmapped.router_id'),
                    json_extract_string(elem, '$.router_id')
                ),
                '([0-9]+(?:\\.[0-9]+){3})',
                1
            ),
            ''
        ) AS ip_address,
        NULL AS admin_status,
        NULL AS line_status,
        snapshot_id,
        created_at
    FROM (
        SELECT device_name, snapshot_id, created_at, unnest(from_json(parsed_data, '["json"]')) AS elem
        FROM parsed_outputs
        WHERE command IN ('show route summary', 'show ip bgp summary')
          AND parsed_data IS NOT NULL
          AND json_array_length(parsed_data) > 0
    ) AS router_id_source
),
cli_rows AS (
    SELECT
        device_name,
        COALESCE(
            NULLIF(json_extract_string(elem, '$."openconfig-interfaces".interfaces.interface[0].config.name'), ''),
            NULLIF(json_extract_string(elem, '$._unmapped.physicalinterface'), ''),
            NULLIF(json_extract_string(elem, '$._unmapped.logicalinterface'), ''),
            NULLIF(json_extract_string(elem, '$.interface'), '')
        ) AS interface,
        NULLIF(
            regexp_extract(
                COALESCE(
                    json_extract_string(elem, '$."openconfig-interfaces".interfaces.interface[0].subinterfaces.subinterface[0].ipv4.addresses.address.state.ip'),
                    json_extract_string(elem, '$."openconfig-interfaces".interfaces.interface[0].subinterfaces.subinterface[0].ipv4.addresses.address.ip'),
                    json_extract_string(elem, '$._unmapped.ipaddress'),
                    json_extract_string(elem, '$.ip_address')
                ),
                '([0-9]+(?:\\.[0-9]+){3})',
                1
            ),
            ''
        ) AS ip_address,
        COALESCE(
            NULLIF(json_extract_string(elem, '$."openconfig-interfaces".interfaces.interface[0].state."admin-status"'), ''),
            NULLIF(json_extract_string(elem, '$."openconfig-interfaces".interfaces.interface[0].config.enabled'), ''),
            NULLIF(json_extract_string(elem, '$._unmapped.enabled'), ''),
            NULLIF(json_extract_string(elem, '$.status'), '')
        ) AS admin_status,
        COALESCE(
            NULLIF(json_extract_string(elem, '$."openconfig-interfaces".interfaces.interface[0].state."oper-status"'), ''),
            NULLIF(json_extract_string(elem, '$._unmapped.proto'), ''),
            NULLIF(json_extract_string(elem, '$._unmapped.linkstatus'), ''),
            NULLIF(json_extract_string(elem, '$._unmapped.protocol_status'), ''),
            NULLIF(json_extract_string(elem, '$._unmapped.link_status'), ''),
            NULLIF(json_extract_string(elem, '$.proto'), '')
        ) AS line_status,
        snapshot_id,
        created_at
    FROM cli_source
),
netconf_source AS (
    SELECT device_name, snapshot_id, created_at,
           unnest(from_json(json_extract(parsed_data, '$."openconfig-interfaces".interfaces.interface'), '["json"]')) AS elem
    FROM parsed_outputs
    WHERE command = 'netconf_interfaces'
      AND parsed_data IS NOT NULL
      AND json_extract(parsed_data, '$."openconfig-interfaces".interfaces.interface') IS NOT NULL
),
netconf_rows AS (
    SELECT
        device_name,
        NULLIF(json_extract_string(elem, '$.name'), '') AS interface,
        NULLIF(
            regexp_extract(
                COALESCE(
                    json_extract_string(elem, '$.subinterfaces.subinterface.ipv4.addresses.address.state.ip'),
                    json_extract_string(elem, '$.subinterfaces.subinterface.ipv4.addresses.address.ip'),
                    json_extract_string(elem, '$.subinterfaces.subinterface[0].ipv4.addresses.address.state.ip'),
                    json_extract_string(elem, '$.subinterfaces.subinterface[0].ipv4.addresses.address.ip'),
                    json_extract_string(elem, '$.subinterfaces.subinterface[0].ipv4.addresses.address[0].state.ip'),
                    json_extract_string(elem, '$.subinterfaces.subinterface[0].ipv4.addresses.address[0].ip'),
                    json_extract_string(elem, '$.subinterfaces.subinterface.ipv4.addresses.address.config.ip'),
                    json_extract_string(elem, '$.subinterfaces.subinterface[0].ipv4.addresses.address.config.ip'),
                    json_extract_string(elem, '$.subinterfaces.subinterface[0].ipv4.addresses.address[0].config.ip')
                ),
                '([0-9]+(?:\\.[0-9]+){3})',
                1
            ),
            ''
        ) AS ip_address,
        COALESCE(
            NULLIF(json_extract_string(elem, '$.state."admin-status"'), ''),
            NULLIF(json_extract_string(elem, '$.config.enabled'), '')
        ) AS admin_status,
        COALESCE(
            NULLIF(json_extract_string(elem, '$.state."oper-status"'), ''),
            NULLIF(json_extract_string(elem, '$.config.enabled'), '')
        ) AS line_status,
        snapshot_id,
        created_at
    FROM netconf_source
),
ranked AS (
    SELECT *,
           row_number() OVER (
               PARTITION BY device_name, interface
               ORDER BY snapshot_id DESC, (ip_address IS NOT NULL) DESC, (line_status IS NOT NULL) DESC, created_at DESC
           ) AS rn
    FROM (
        SELECT * FROM cli_rows WHERE interface IS NOT NULL AND interface != ''
        UNION ALL
        SELECT * FROM netconf_rows WHERE interface IS NOT NULL AND interface != ''
        UNION ALL
        SELECT * FROM router_id_rows WHERE interface IS NOT NULL AND interface != '' AND ip_address IS NOT NULL
    ) AS combined
)
SELECT device_name, interface, ip_address, admin_status, line_status,
       MAX(snapshot_id) OVER () AS snapshot_id,
       created_at
FROM ranked WHERE rn = 1
"""

V_BGP_NEIGHBORS_AUTO_DDL: str = """
CREATE OR REPLACE VIEW v_bgp_neighbors_auto AS
WITH source_rows AS (
    SELECT device_name, snapshot_id, created_at, unnest(from_json(parsed_data, '["json"]')) AS elem
    FROM parsed_outputs
    WHERE command IN ('show bgp summary', 'show ip bgp summary')
      AND parsed_data IS NOT NULL
      AND json_array_length(parsed_data) > 0
),
normalized AS (
    SELECT
        device_name,
        COALESCE(
            NULLIF(json_extract_string(elem, '$."openconfig-bgp".bgp.neighbors.neighbor[0].state."neighbor-address"'), ''),
            NULLIF(json_extract_string(elem, '$."openconfig-bgp".bgp.neighbors.neighbor[0].config."neighbor-address"'), ''),
            NULLIF(json_extract_string(elem, '$._unmapped.peer'), ''),
            NULLIF(json_extract_string(elem, '$.peer'), ''),
            NULLIF(json_extract_string(elem, '$.bgp_neighbor'), ''),
            NULLIF(json_extract_string(elem, '$.neighbor'), '')
        ) AS neighbor_ip,
        COALESCE(
            NULLIF(json_extract_string(elem, '$."openconfig-bgp".bgp.neighbors.neighbor[0].state."peer-as"'), ''),
            NULLIF(json_extract_string(elem, '$."openconfig-bgp".bgp.neighbors.neighbor[0].config."peer-as"'), ''),
            NULLIF(json_extract_string(elem, '$._unmapped.peer_as'), ''),
            NULLIF(json_extract_string(elem, '$.peer_as'), ''),
            NULLIF(json_extract_string(elem, '$.neighbor_as'), ''),
            NULLIF(json_extract_string(elem, '$.as'), '')
        ) AS neighbor_as,
        COALESCE(
            NULLIF(json_extract_string(elem, '$."openconfig-bgp".bgp.neighbors.neighbor[0].state."session-state"'), ''),
            CASE
                WHEN regexp_matches(COALESCE(json_extract_string(elem, '$."openconfig-bgp".bgp.neighbors.neighbor[0].afi-safis."afi-safi".state.prefixes.received'), ''), '^[0-9]+$')
                    THEN 'Established'
                ELSE NULLIF(json_extract_string(elem, '$."openconfig-bgp".bgp.neighbors.neighbor[0].afi-safis."afi-safi".state.prefixes.received'), '')
            END,
            NULLIF(json_extract_string(elem, '$._unmapped.peerstate'), ''),
            NULLIF(json_extract_string(elem, '$.peerstate'), ''),
            CASE
                WHEN regexp_matches(COALESCE(json_extract_string(elem, '$.state_or_prefixes_received'), ''), '^[0-9]+$')
                    THEN 'Established'
                ELSE NULLIF(json_extract_string(elem, '$.state_or_prefixes_received'), '')
            END,
            NULLIF(json_extract_string(elem, '$.state'), ''),
            CASE
                WHEN COALESCE(
                    NULLIF(json_extract_string(elem, '$._unmapped.peer'), ''),
                    NULLIF(json_extract_string(elem, '$.peer'), '')
                ) IS NOT NULL THEN 'Established'
                ELSE NULL
            END
        ) AS state,
        CASE
            WHEN regexp_matches(COALESCE(
                json_extract_string(elem, '$."openconfig-bgp".bgp.neighbors.neighbor[0].afi-safis."afi-safi".state.prefixes.received'),
                json_extract_string(elem, '$.state_or_prefixes_received')
            ), '^[0-9]+$')
            THEN CAST(COALESCE(
                json_extract_string(elem, '$."openconfig-bgp".bgp.neighbors.neighbor[0].afi-safis."afi-safi".state.prefixes.received'),
                json_extract_string(elem, '$.state_or_prefixes_received')
            ) AS INTEGER)
            ELSE NULL
        END AS prefixes_received,
        snapshot_id,
        created_at
    FROM source_rows
),
ranked AS (
    SELECT *,
           row_number() OVER (
               PARTITION BY device_name, neighbor_ip
               ORDER BY snapshot_id DESC, (neighbor_as IS NOT NULL) DESC, (prefixes_received IS NOT NULL) DESC, created_at DESC
           ) AS rn
    FROM normalized
    WHERE neighbor_ip IS NOT NULL AND neighbor_ip != ''
)
SELECT device_name, neighbor_ip, neighbor_as, state, prefixes_received,
       MAX(snapshot_id) OVER () AS snapshot_id,
       created_at
FROM ranked WHERE rn = 1
"""

V_TOPO_LINKS_CLEAN_DDL: str = """
CREATE OR REPLACE VIEW v_topo_links_clean AS
WITH cleaned AS (
    SELECT
        link_id,
        SPLIT_PART(source_device, '.', 1) AS src,
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
      AND SPLIT_PART(source_device, '.', 1) IS DISTINCT FROM SPLIT_PART(destination_device, '.', 1)
      AND TRY_CAST(SPLIT_PART(source_device, '.', 1) AS INTEGER) IS NULL
      AND TRY_CAST(SPLIT_PART(destination_device, '.', 1) AS INTEGER) IS NULL
      AND SPLIT_PART(source_device, '.', 1) IN (SELECT name FROM devices)
      AND SPLIT_PART(destination_device, '.', 1) IN (SELECT name FROM devices)
      AND discovery_protocol IN ('LLDP', 'CDP')
      AND COALESCE(link_type, 'L2') = 'L2'
),
canonicalized AS (
    SELECT
        link_id,
        CASE WHEN src <= dst THEN src ELSE dst END AS src,
        CASE WHEN src <= dst THEN source_interface ELSE destination_interface END AS source_interface,
        CASE WHEN src <= dst THEN dst ELSE src END AS dst,
        CASE WHEN src <= dst THEN destination_interface ELSE source_interface END AS destination_interface,
        discovery_protocol,
        link_type,
        link_status,
        snapshot_id,
        first_seen,
        last_seen
    FROM cleaned
),
ranked AS (
    SELECT *,
           row_number() OVER (
               PARTITION BY src, source_interface, dst, destination_interface, discovery_protocol
               ORDER BY snapshot_id DESC, COALESCE(last_seen, first_seen) DESC
           ) AS rn
    FROM canonicalized
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
"""

V_L2_TOPOLOGY_SUMMARY_DDL: str = """
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
"""

V_DEVICE_NEIGHBORS_SUMMARY_DDL: str = """
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
"""

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

#: Ordered list of (view_name, ddl) pairs — applied in dependency order.
_VIEW_SEQUENCE: list[tuple[str, str]] = [
    ("v_interfaces_auto", V_INTERFACES_AUTO_DDL),
    ("v_interfaces", "CREATE OR REPLACE VIEW v_interfaces AS SELECT * FROM v_interfaces_auto"),
    ("v_bgp_neighbors_auto", V_BGP_NEIGHBORS_AUTO_DDL),
    (
        "v_bgp_neighbors",
        "CREATE OR REPLACE VIEW v_bgp_neighbors AS SELECT * FROM v_bgp_neighbors_auto",
    ),
    ("v_topo_links_clean", V_TOPO_LINKS_CLEAN_DDL),
    ("v_l2_topology_summary", V_L2_TOPOLOGY_SUMMARY_DDL),
    ("v_device_neighbors_summary", V_DEVICE_NEIGHBORS_SUMMARY_DDL),
]


def list_semantic_views() -> list[str]:
    """Return the ordered list of semantic view names managed by this module.

    The list is returned in dependency order (safe for sequential creation).

    Examples
    --------
    >>> "v_interfaces_auto" in list_semantic_views()
    True
    >>> list_semantic_views()[0]
    'v_interfaces_auto'
    """
    return [name for name, _ in _VIEW_SEQUENCE]


def ensure_semantic_views(con: duckdb.DuckDBPyConnection) -> None:
    """Create or replace all semantic views in the given DuckDB connection.

    This function is idempotent — safe to call on every platform boot or
    migration run.  Views are applied in dependency order so that views
    that reference other views (e.g. ``v_l2_topology_summary`` →
    ``v_topo_links_clean``) are created after their dependencies.

    Parameters
    ----------
    con:
        An open ``duckdb.DuckDBPyConnection``.  The caller is responsible
        for opening and closing the connection.

    Raises
    ------
    duckdb.Error
        Propagated if DuckDB rejects a DDL statement (e.g. missing base
        table ``parsed_outputs`` or ``topology_links``).
    """
    for view_name, ddl in _VIEW_SEQUENCE:
        con.execute(ddl)
        logger.debug("view ensured: %s", view_name)
    logger.info(
        "semantic views ensured: %s",
        ", ".join(list_semantic_views()),
    )
