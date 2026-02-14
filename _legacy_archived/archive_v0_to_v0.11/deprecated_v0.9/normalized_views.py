"""Standardized DuckDB views for cross-vendor network data.

This module creates DuckDB views that provide a standardized interface
to query network data across different vendors. The views use JSON functions
to extract and normalize data from the command_outputs table.

Architecture:
    command_outputs table → JSON extraction → Normalized views

Views Created:
    - v_bgp_neighbors: Standardized BGP neighbor data
    - v_ospf_neighbors: Standardized OSPF neighbor data
    - v_route_entries: Standardized routing table entries
    - v_interface_status: Standardized interface information
    - v_cdp_neighbors: Standardized CDP/LLDP neighbor data

Usage:
    from olav.core.normalized_views import create_normalized_views

    conn = duckdb.connect("network.duckdb")
    create_normalized_views(conn)

    # Query normalized BGP neighbors across all vendors
    result = conn.execute("SELECT * FROM v_bgp_neighbors WHERE state = 'Established'")
"""

import logging

import duckdb

logger = logging.getLogger(__name__)


# =============================================================================
# View Definitions - Using DuckDB JSON array extraction syntax
# =============================================================================

# BGP Neighbors View - normalizes across Cisco/Juniper/Arista
BGP_NEIGHBORS_VIEW = """
CREATE OR REPLACE VIEW v_bgp_neighbors AS
SELECT
    c.snapshot_date,
    c.device_name,
    c.platform,
    -- Cisco IOS: BGP_NEIGHBOR, Juniper: Peer, Arista: neighborAddress
    COALESCE(
        json_extract_string(row_data, '$.BGP_NEIGHBOR'),
        json_extract_string(row_data, '$.NEIGHBOR'),
        json_extract_string(row_data, '$.Peer'),
        json_extract_string(row_data, '$.PeerAddress'),
        json_extract_string(row_data, '$.neighborAddress'),
        json_extract_string(row_data, '$.peerAddress')
    ) AS neighbor_ip,
    -- Remote AS
    TRY_CAST(COALESCE(
        json_extract_string(row_data, '$.AS'),
        json_extract_string(row_data, '$.REMOTE_AS'),
        json_extract_string(row_data, '$.ASNum'),
        json_extract_string(row_data, '$.asn'),
        json_extract_string(row_data, '$.remoteAs')
    ) AS INTEGER) AS remote_as,
    -- State normalization
    CASE
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.STATE_PFXRCD'),
            json_extract_string(row_data, '$.State'),
            json_extract_string(row_data, '$.state')
        )) IN ('established', 'up') THEN 'Established'
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.STATE_PFXRCD'),
            json_extract_string(row_data, '$.State'),
            json_extract_string(row_data, '$.state')
        )) IN ('idle', 'down') THEN 'Idle'
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.STATE_PFXRCD'),
            json_extract_string(row_data, '$.State'),
            json_extract_string(row_data, '$.state')
        )) = 'active' THEN 'Active'
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.STATE_PFXRCD'),
            json_extract_string(row_data, '$.State'),
            json_extract_string(row_data, '$.state')
        )) = 'connect' THEN 'Connect'
        ELSE COALESCE(
            json_extract_string(row_data, '$.STATE_PFXRCD'),
            json_extract_string(row_data, '$.State'),
            json_extract_string(row_data, '$.state')
        )
    END AS state,
    -- Prefixes received (try to extract from STATE_PFXRCD if numeric)
    TRY_CAST(COALESCE(
        json_extract_string(row_data, '$.STATE_PFXRCD'),
        json_extract_string(row_data, '$.InPfx'),
        json_extract_string(row_data, '$.prefixReceived')
    ) AS INTEGER) AS prefixes_received,
    -- Uptime
    COALESCE(
        json_extract_string(row_data, '$.UP_DOWN'),
        json_extract_string(row_data, '$.Up/Down'),
        json_extract_string(row_data, '$.upDownTime'),
        json_extract_string(row_data, '$.UPTIME')
    ) AS uptime
FROM command_outputs c,
     UNNEST(json_extract(c.parsed_data, '$.data')::JSON[]) AS t(row_data)
WHERE c.parse_success = TRUE
  AND c.command LIKE '%bgp%summary%'
  AND COALESCE(
    json_extract_string(row_data, '$.BGP_NEIGHBOR'),
    json_extract_string(row_data, '$.NEIGHBOR'),
    json_extract_string(row_data, '$.Peer'),
    json_extract_string(row_data, '$.PeerAddress'),
    json_extract_string(row_data, '$.neighborAddress')
  ) IS NOT NULL
"""

# OSPF Neighbors View
OSPF_NEIGHBORS_VIEW = """
CREATE OR REPLACE VIEW v_ospf_neighbors AS
SELECT
    c.snapshot_date,
    c.device_name,
    c.platform,
    -- Neighbor ID
    COALESCE(
        json_extract_string(row_data, '$.NEIGHBOR_ID'),
        json_extract_string(row_data, '$.NEIGHBOR'),
        json_extract_string(row_data, '$.NeighborID'),
        json_extract_string(row_data, '$.RouterID'),
        json_extract_string(row_data, '$.neighborRouterId')
    ) AS neighbor_id,
    -- Neighbor Address
    COALESCE(
        json_extract_string(row_data, '$.ADDRESS'),
        json_extract_string(row_data, '$.IP_ADDRESS'),
        json_extract_string(row_data, '$.NeighborAddress'),
        json_extract_string(row_data, '$.neighborIpAddress')
    ) AS neighbor_address,
    -- State normalization
    CASE
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.STATE'),
            json_extract_string(row_data, '$.State'),
            json_extract_string(row_data, '$.adjacencyState')
        )) LIKE 'full%' THEN 'Full'
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.STATE'),
            json_extract_string(row_data, '$.State'),
            json_extract_string(row_data, '$.adjacencyState')
        )) = '2way' THEN '2-Way'
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.STATE'),
            json_extract_string(row_data, '$.State'),
            json_extract_string(row_data, '$.adjacencyState')
        )) = 'init' THEN 'Init'
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.STATE'),
            json_extract_string(row_data, '$.State'),
            json_extract_string(row_data, '$.adjacencyState')
        )) = 'down' THEN 'Down'
        ELSE COALESCE(
            json_extract_string(row_data, '$.STATE'),
            json_extract_string(row_data, '$.State'),
            json_extract_string(row_data, '$.adjacencyState')
        )
    END AS state,
    -- Interface
    COALESCE(
        json_extract_string(row_data, '$.INTERFACE'),
        json_extract_string(row_data, '$.Interface'),
        json_extract_string(row_data, '$.interface')
    ) AS interface,
    -- Priority
    TRY_CAST(COALESCE(
        json_extract_string(row_data, '$.PRIORITY'),
        json_extract_string(row_data, '$.Priority'),
        json_extract_string(row_data, '$.priority')
    ) AS INTEGER) AS priority,
    -- Dead time
    COALESCE(
        json_extract_string(row_data, '$.DEAD_TIME'),
        json_extract_string(row_data, '$.DEAD'),
        json_extract_string(row_data, '$.DeadTimer'),
        json_extract_string(row_data, '$.deadTime')
    ) AS dead_time
FROM command_outputs c,
     UNNEST(json_extract(c.parsed_data, '$.data')::JSON[]) AS t(row_data)
WHERE c.parse_success = TRUE
  AND c.command LIKE '%ospf%neighbor%'
  AND COALESCE(
    json_extract_string(row_data, '$.NEIGHBOR_ID'),
    json_extract_string(row_data, '$.NEIGHBOR'),
    json_extract_string(row_data, '$.NeighborID'),
    json_extract_string(row_data, '$.neighborRouterId')
  ) IS NOT NULL
"""

# Route Entries View
ROUTE_ENTRIES_VIEW = """
CREATE OR REPLACE VIEW v_route_entries AS
SELECT
    c.snapshot_date,
    c.device_name,
    c.platform,
    -- Network
    COALESCE(
        json_extract_string(row_data, '$.NETWORK'),
        json_extract_string(row_data, '$.Destination'),
        json_extract_string(row_data, '$.Route'),
        json_extract_string(row_data, '$.network')
    ) AS network,
    -- Protocol normalization
    CASE
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.PROTOCOL'),
            json_extract_string(row_data, '$.TYPE'),
            json_extract_string(row_data, '$.Protocol'),
            json_extract_string(row_data, '$.routeType')
        )) IN ('c', 'connected') THEN 'connected'
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.PROTOCOL'),
            json_extract_string(row_data, '$.TYPE'),
            json_extract_string(row_data, '$.Protocol'),
            json_extract_string(row_data, '$.routeType')
        )) IN ('s', 'static') THEN 'static'
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.PROTOCOL'),
            json_extract_string(row_data, '$.TYPE'),
            json_extract_string(row_data, '$.Protocol'),
            json_extract_string(row_data, '$.routeType')
        )) IN ('b', 'bgp') THEN 'bgp'
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.PROTOCOL'),
            json_extract_string(row_data, '$.TYPE'),
            json_extract_string(row_data, '$.Protocol'),
            json_extract_string(row_data, '$.routeType')
        )) IN ('o', 'ospf') THEN 'ospf'
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.PROTOCOL'),
            json_extract_string(row_data, '$.TYPE'),
            json_extract_string(row_data, '$.Protocol'),
            json_extract_string(row_data, '$.routeType')
        )) IN ('e', 'eigrp') THEN 'eigrp'
        ELSE COALESCE(
            json_extract_string(row_data, '$.PROTOCOL'),
            json_extract_string(row_data, '$.TYPE'),
            json_extract_string(row_data, '$.Protocol'),
            json_extract_string(row_data, '$.routeType')
        )
    END AS protocol,
    -- Next hop
    COALESCE(
        json_extract_string(row_data, '$.NEXT_HOP'),
        json_extract_string(row_data, '$.NEXTHOP_IP'),
        json_extract_string(row_data, '$.NextHop'),
        json_extract_string(row_data, '$.Via'),
        json_extract_string(row_data, '$.nexthopAddr')
    ) AS next_hop,
    -- Metric
    TRY_CAST(COALESCE(
        json_extract_string(row_data, '$.METRIC'),
        json_extract_string(row_data, '$.Metric'),
        json_extract_string(row_data, '$.metric')
    ) AS INTEGER) AS metric,
    -- Admin distance
    TRY_CAST(COALESCE(
        json_extract_string(row_data, '$.DISTANCE'),
        json_extract_string(row_data, '$.AD'),
        json_extract_string(row_data, '$.Preference'),
        json_extract_string(row_data, '$.preference')
    ) AS INTEGER) AS admin_distance,
    -- Outgoing interface
    COALESCE(
        json_extract_string(row_data, '$.NEXTHOP_IF'),
        json_extract_string(row_data, '$.INTERFACE'),
        json_extract_string(row_data, '$.Interface'),
        json_extract_string(row_data, '$.interface')
    ) AS interface
FROM command_outputs c,
     UNNEST(json_extract(c.parsed_data, '$.data')::JSON[]) AS t(row_data)
WHERE c.parse_success = TRUE
  AND (c.command LIKE '%route%' OR c.command LIKE '%routing%')
  AND COALESCE(
    json_extract_string(row_data, '$.NETWORK'),
    json_extract_string(row_data, '$.Destination'),
    json_extract_string(row_data, '$.Route'),
    json_extract_string(row_data, '$.network')
  ) IS NOT NULL
"""

# Interface Status View
INTERFACE_STATUS_VIEW = """
CREATE OR REPLACE VIEW v_interface_status AS
SELECT
    c.snapshot_date,
    c.device_name,
    c.platform,
    -- Interface name
    COALESCE(
        json_extract_string(row_data, '$.INTERFACE'),
        json_extract_string(row_data, '$.INTF'),
        json_extract_string(row_data, '$.Interface'),
        json_extract_string(row_data, '$.interface')
    ) AS interface,
    -- IP address
    COALESCE(
        json_extract_string(row_data, '$.IP_ADDRESS'),
        json_extract_string(row_data, '$.IPADDR'),
        json_extract_string(row_data, '$.Address'),
        json_extract_string(row_data, '$.ipAddress')
    ) AS ip_address,
    -- Admin status normalization
    CASE
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.STATUS'),
            json_extract_string(row_data, '$.Status'),
            json_extract_string(row_data, '$.interfaceStatus')
        )) IN ('up', 'enabled') THEN 'up'
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.STATUS'),
            json_extract_string(row_data, '$.Status'),
            json_extract_string(row_data, '$.interfaceStatus')
        )) LIKE '%admin%down%' THEN 'admin-down'
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.STATUS'),
            json_extract_string(row_data, '$.Status'),
            json_extract_string(row_data, '$.interfaceStatus')
        )) IN ('down', 'disabled') THEN 'down'
        ELSE COALESCE(
            json_extract_string(row_data, '$.STATUS'),
            json_extract_string(row_data, '$.Status'),
            json_extract_string(row_data, '$.interfaceStatus')
        )
    END AS status,
    -- Protocol/Link status
    CASE
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.PROTOCOL'),
            json_extract_string(row_data, '$.LinkStatus'),
            json_extract_string(row_data, '$.linkStatus')
        )) IN ('up', 'enabled') THEN 'up'
        WHEN LOWER(COALESCE(
            json_extract_string(row_data, '$.PROTOCOL'),
            json_extract_string(row_data, '$.LinkStatus'),
            json_extract_string(row_data, '$.linkStatus')
        )) IN ('down', 'disabled') THEN 'down'
        ELSE COALESCE(
            json_extract_string(row_data, '$.PROTOCOL'),
            json_extract_string(row_data, '$.LinkStatus'),
            json_extract_string(row_data, '$.linkStatus')
        )
    END AS protocol_status,
    -- Description
    COALESCE(
        json_extract_string(row_data, '$.DESCRIPTION'),
        json_extract_string(row_data, '$.Description'),
        json_extract_string(row_data, '$.description')
    ) AS description
FROM command_outputs c,
     UNNEST(json_extract(c.parsed_data, '$.data')::JSON[]) AS t(row_data)
WHERE c.parse_success = TRUE
  AND (c.command LIKE '%interface%' OR c.command LIKE '%interfaces%')
  AND COALESCE(
    json_extract_string(row_data, '$.INTERFACE'),
    json_extract_string(row_data, '$.INTF'),
    json_extract_string(row_data, '$.Interface'),
    json_extract_string(row_data, '$.interface')
  ) IS NOT NULL
"""

# CDP/LLDP Neighbors View
CDP_NEIGHBORS_VIEW = """
CREATE OR REPLACE VIEW v_cdp_neighbors AS
SELECT
    c.snapshot_date,
    c.device_name,
    c.platform,
    -- Determine discovery protocol
    CASE
        WHEN c.command LIKE '%cdp%' THEN 'cdp'
        WHEN c.command LIKE '%lldp%' THEN 'lldp'
        ELSE 'unknown'
    END AS discovery_protocol,
    -- Neighbor name
    COALESCE(
        json_extract_string(row_data, '$.NEIGHBOR'),
        json_extract_string(row_data, '$.DEVICE_ID'),
        json_extract_string(row_data, '$.NEIGHBOR_NAME'),
        json_extract_string(row_data, '$.SystemName'),
        json_extract_string(row_data, '$.systemName')
    ) AS neighbor_name,
    -- Local interface
    COALESCE(
        json_extract_string(row_data, '$.LOCAL_PORT'),
        json_extract_string(row_data, '$.LOCAL_INTERFACE'),
        json_extract_string(row_data, '$.LocalInterface'),
        json_extract_string(row_data, '$.LocalPort')
    ) AS local_interface,
    -- Remote interface
    COALESCE(
        json_extract_string(row_data, '$.REMOTE_PORT'),
        json_extract_string(row_data, '$.PORT_ID'),
        json_extract_string(row_data, '$.NEIGHBOR_PORT_ID'),
        json_extract_string(row_data, '$.PortID'),
        json_extract_string(row_data, '$.RemotePort')
    ) AS remote_interface,
    -- Platform/Model
    COALESCE(
        json_extract_string(row_data, '$.PLATFORM'),
        json_extract_string(row_data, '$.SYSTEM_DESCRIPTION'),
        json_extract_string(row_data, '$.SystemDescription'),
        json_extract_string(row_data, '$.systemDescription')
    ) AS platform_model,
    -- Management IP
    COALESCE(
        json_extract_string(row_data, '$.MANAGEMENT_IP'),
        json_extract_string(row_data, '$.IP_ADDRESS'),
        json_extract_string(row_data, '$.ManagementAddress'),
        json_extract_string(row_data, '$.managementAddress')
    ) AS management_ip,
    -- Capabilities
    COALESCE(
        json_extract_string(row_data, '$.CAPABILITIES'),
        json_extract_string(row_data, '$.Capabilities'),
        json_extract_string(row_data, '$.capabilities')
    ) AS capabilities
FROM command_outputs c,
     UNNEST(json_extract(c.parsed_data, '$.data')::JSON[]) AS t(row_data)
WHERE c.parse_success = TRUE
  AND (c.command LIKE '%cdp%neighbor%' OR c.command LIKE '%lldp%neighbor%')
  AND COALESCE(
    json_extract_string(row_data, '$.NEIGHBOR'),
    json_extract_string(row_data, '$.DEVICE_ID'),
    json_extract_string(row_data, '$.NEIGHBOR_NAME'),
    json_extract_string(row_data, '$.SystemName')
  ) IS NOT NULL
"""


# =============================================================================
# View Creation Functions
# =============================================================================


def create_normalized_views(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all normalized views in the database.

    Args:
        conn: DuckDB connection object

    Example:
        >>> conn = duckdb.connect("network.duckdb")
        >>> create_normalized_views(conn)
        >>> # Views are now available for querying
    """
    views = [
        ("v_bgp_neighbors", BGP_NEIGHBORS_VIEW),
        ("v_ospf_neighbors", OSPF_NEIGHBORS_VIEW),
        ("v_route_entries", ROUTE_ENTRIES_VIEW),
        ("v_interface_status", INTERFACE_STATUS_VIEW),
        ("v_cdp_neighbors", CDP_NEIGHBORS_VIEW),
    ]

    for view_name, view_sql in views:
        try:
            conn.execute(view_sql)
            logger.info(f"Created normalized view: {view_name}")
        except Exception as e:
            logger.error(f"Failed to create view {view_name}: {e}")
            raise


def drop_normalized_views(conn: duckdb.DuckDBPyConnection) -> None:
    """Drop all normalized views from the database.

    Args:
        conn: DuckDB connection object
    """
    views = [
        "v_bgp_neighbors",
        "v_ospf_neighbors",
        "v_route_entries",
        "v_interface_status",
        "v_cdp_neighbors",
    ]

    for view_name in views:
        try:
            conn.execute(f"DROP VIEW IF EXISTS {view_name}")
            logger.info(f"Dropped normalized view: {view_name}")
        except Exception as e:
            logger.warning(f"Failed to drop view {view_name}: {e}")


def get_view_info(conn: duckdb.DuckDBPyConnection) -> dict[str, dict]:
    """Get information about normalized views.

    Args:
        conn: DuckDB connection object

    Returns:
        Dictionary mapping view names to their metadata

    Example:
        >>> info = get_view_info(conn)
        >>> print(info["v_bgp_neighbors"]["row_count"])
    """
    views = [
        "v_bgp_neighbors",
        "v_ospf_neighbors",
        "v_route_entries",
        "v_interface_status",
        "v_cdp_neighbors",
    ]

    info = {}
    for view_name in views:
        try:
            # Check if view exists
            # Note: view_name is from a hardcoded list, so this is safe
            check_sql = (
                f"SELECT COUNT(*) FROM information_schema.tables WHERE table_name = '{view_name}'"  # noqa: S608
            )
            result = conn.execute(check_sql).fetchone()

            if result and result[0] > 0:
                # Get row count
                count_sql = f"SELECT COUNT(*) FROM {view_name}"  # noqa: S608
                row_count = conn.execute(count_sql).fetchone()

                # Get columns
                describe_sql = f"DESCRIBE {view_name}"  # noqa: S608
                columns = conn.execute(describe_sql).fetchall()

                info[view_name] = {
                    "exists": True,
                    "row_count": row_count[0] if row_count else 0,
                    "columns": [col[0] for col in columns],
                }
            else:
                info[view_name] = {"exists": False, "row_count": 0, "columns": []}
        except Exception as e:
            info[view_name] = {"exists": False, "error": str(e)}

    return info


# =============================================================================
# Convenience Query Functions
# =============================================================================


def query_bgp_neighbors(
    conn: duckdb.DuckDBPyConnection,
    device_name: str | None = None,
    state: str | None = None,
    snapshot_date: str | None = None,
) -> list[dict]:
    """Query normalized BGP neighbors.

    Args:
        conn: DuckDB connection object
        device_name: Filter by device name (optional)
        state: Filter by BGP state (optional)
        snapshot_date: Filter by snapshot date (optional)

    Returns:
        List of BGP neighbor dictionaries
    """
    conditions: list[str] = []
    params: list[str] = []

    if device_name:
        conditions.append("device_name = ?")
        params.append(device_name)
    if state:
        conditions.append("state = ?")
        params.append(state)
    if snapshot_date:
        conditions.append("snapshot_date = ?")
        params.append(snapshot_date)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Note: where_clause is built from a controlled list of column conditions
    query = f"""
        SELECT * FROM v_bgp_neighbors
        WHERE {where_clause}
        ORDER BY device_name, neighbor_ip
    """  # noqa: S608

    result = conn.execute(query, params).fetchall()
    columns = [
        "snapshot_date",
        "device_name",
        "platform",
        "neighbor_ip",
        "remote_as",
        "state",
        "prefixes_received",
        "uptime",
    ]

    return [dict(zip(columns, row, strict=False)) for row in result]


def query_ospf_neighbors(
    conn: duckdb.DuckDBPyConnection,
    device_name: str | None = None,
    state: str | None = None,
    snapshot_date: str | None = None,
) -> list[dict]:
    """Query normalized OSPF neighbors.

    Args:
        conn: DuckDB connection object
        device_name: Filter by device name (optional)
        state: Filter by OSPF state (optional)
        snapshot_date: Filter by snapshot date (optional)

    Returns:
        List of OSPF neighbor dictionaries
    """
    conditions: list[str] = []
    params: list[str] = []

    if device_name:
        conditions.append("device_name = ?")
        params.append(device_name)
    if state:
        conditions.append("state = ?")
        params.append(state)
    if snapshot_date:
        conditions.append("snapshot_date = ?")
        params.append(snapshot_date)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Note: where_clause is built from a controlled list of column conditions
    query = f"""
        SELECT * FROM v_ospf_neighbors
        WHERE {where_clause}
        ORDER BY device_name, neighbor_id
    """  # noqa: S608

    result = conn.execute(query, params).fetchall()
    columns = [
        "snapshot_date",
        "device_name",
        "platform",
        "neighbor_id",
        "neighbor_address",
        "state",
        "interface",
        "priority",
        "dead_time",
    ]

    return [dict(zip(columns, row, strict=False)) for row in result]


def get_normalized_summary(conn: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Get summary counts for all normalized views.

    Args:
        conn: DuckDB connection object

    Returns:
        Dictionary with counts per view

    Example:
        >>> summary = get_normalized_summary(conn)
        >>> print(summary)
        {'bgp_neighbors': 15, 'ospf_neighbors': 8, ...}
    """
    views = {
        "bgp_neighbors": "v_bgp_neighbors",
        "ospf_neighbors": "v_ospf_neighbors",
        "route_entries": "v_route_entries",
        "interface_status": "v_interface_status",
        "cdp_neighbors": "v_cdp_neighbors",
    }

    summary: dict[str, int] = {}
    for key, view_name in views.items():
        try:
            # Note: view_name is from a hardcoded dict, so this is safe
            count_sql = f"SELECT COUNT(*) FROM {view_name}"  # noqa: S608
            result = conn.execute(count_sql).fetchone()
            summary[key] = result[0] if result else 0
        except Exception:
            summary[key] = 0

    return summary
