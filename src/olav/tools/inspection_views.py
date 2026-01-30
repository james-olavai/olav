"""
DuckDB SQL View Definitions for Network Inspection

This module defines L1-L4 SQL views that extract structured data
from JSON snapshot files for network device inspection.

Architecture:
- L1: Physical Layer (device status, environment)
- L2: Data Link Layer (interfaces, CDP, ARP)
- L3: Network Layer (BGP, OSPF, routes)
- L4: System Performance (CPU, memory)

Views use:
- `filename=true` to extract device name from file path
- `regexp_extract(filename, 'parsed/([^/]+)/', 1)` to parse device name
- `unnest(data)` to flatten JSON arrays
- `json_extract_string()` to extract field values
"""

import logging

import duckdb

logger = logging.getLogger(__name__)

## L0 Infrastructure Views
CREATE_V_DEVICE_CAPABILITIES = """
CREATE OR REPLACE VIEW v_device_capabilities AS
SELECT
    hostname AS device,
    preferred_driver AS driver,
    last_success AS last_seen,
    features AS capabilities
FROM device_capabilities;
"""

## L1 Physical Layer Views
CREATE_V_DEVICE_STATUS = """
CREATE OR REPLACE VIEW v_device_status AS
SELECT
    regexp_extract(filename, 'parsed/([^/]+)/', 1) AS device,
    data[1].version AS version,
    data[1].uptime AS uptime,
    data[1].hostname AS hostname
FROM read_json_auto('exports/snapshots/latest/parsed/*/*ver*.json', filename=true);
"""

CREATE_V_ENVIRONMENT = """
CREATE OR REPLACE VIEW v_environment AS
SELECT
    regexp_extract(filename, 'parsed/([^/]+)/', 1) AS device,
    d.name AS sensor_name,
    d.state AS sensor_state,
    COALESCE(
        TRY_CAST(d.reading AS DOUBLE), 0.0
    ) AS sensor_reading
FROM (
    SELECT filename, unnest(data) AS d
    FROM read_json_auto('exports/snapshots/latest/parsed/*/show-environment*.json', filename=true)
);
"""

## L2 Data Link Layer Views
CREATE_V_INTERFACES = """
CREATE OR REPLACE VIEW v_interfaces AS
SELECT
    regexp_extract(filename, 'parsed/([^/]+)/', 1) AS device,
    json_extract_string(d, '$.interface') AS interface,
    json_extract_string(d, '$.port') AS port,
    json_extract_string(d, '$.link_status') AS link_status,
    json_extract_string(d, '$.protocol_status') AS protocol_status,
    json_extract_string(d, '$.status') AS status,
    json_extract_string(d, '$.ip_address') AS ip_address,
    json_extract_string(d, '$.vrf') AS vrf,
    json_extract_string(d, '$.proto') AS proto,
    COALESCE(try_cast(json_extract_string(d, '$.bandwidth') AS BIGINT), 0) AS bandwidth_kbps,
    COALESCE(try_cast(json_extract_string(d, '$.input_errors') AS BIGINT), 0) AS in_errors,
    COALESCE(try_cast(json_extract_string(d, '$.output_errors') AS BIGINT), 0) AS out_errors,
    COALESCE(try_cast(json_extract_string(d, '$.crc') AS BIGINT), 0) AS crc_errors
FROM (
    SELECT filename, unnest(data) AS d
    FROM read_json_auto('exports/snapshots/latest/parsed/*/*ip*int*.json', filename=true)
);
"""

CREATE_V_CDP_NEIGHBORS = """
CREATE OR REPLACE VIEW v_cdp_neighbors AS
SELECT
    regexp_extract(filename, 'parsed/([^/]+)/', 1) AS device,
    d.local_interface AS local_interface,
    d.neighbor_name AS neighbor_name,
    d.neighbor_interface AS neighbor_interface,
    d.platform AS platform
FROM (
    SELECT filename, unnest(data) AS d
    FROM read_json_auto('exports/snapshots/latest/parsed/*/show-cdp-neighbor*.json', filename=true)
);
"""

CREATE_V_ARP = """
CREATE OR REPLACE VIEW v_arp AS
SELECT
    regexp_extract(filename, 'parsed/([^/]+)/', 1) AS device,
    d.address AS address,
    d.hardware_address AS hardware_address,
    d.interface AS interface,
    d.protocol AS protocol
FROM (
    SELECT filename, unnest(data) AS d
    FROM read_json_auto('exports/snapshots/latest/parsed/*/show-*arp*.json', filename=true)
);
"""

## L3 Network Layer Views
CREATE_V_BGP_NEIGHBORS = """
CREATE OR REPLACE VIEW v_bgp_neighbors AS
SELECT
    regexp_extract(filename, 'parsed/([^/]+)/', 1) AS device,
    d.bgp_neighbor AS bgp_neighbor,
    d.neighbor_as AS neighbor_as,
    d.state_or_prefixes_received AS state_or_prefixes_received,
    d.up_down AS uptime,
    COALESCE(
        TRY_CAST(d.state_or_prefixes_received AS BIGINT), 0
    ) AS prefixes_received
FROM (
    SELECT filename, unnest(data) AS d
    FROM read_json_auto('exports/snapshots/latest/parsed/*/*bgp*sum*.json', filename=true)
);
"""

CREATE_V_OSPF_NEIGHBORS = """
CREATE OR REPLACE VIEW v_ospf_neighbors AS
SELECT
    regexp_extract(filename, 'parsed/([^/]+)/', 1) AS device,
    d.neighbor_id AS neighbor_id,
    json_extract_string(d, '$.ip_address') AS ip_address,
    d.priority AS priority,
    d.state AS state,
    d.interface AS interface,
    d.dead_time AS dead_time
FROM (
    SELECT filename, unnest(data) AS d
    FROM read_json_auto('exports/snapshots/latest/parsed/*/*ospf*nei*.json', filename=true)
);
"""

# Schema Discovery 发现的实际字段:
# Schema Discovery 发现的实际字段:
# - vrf, protocol, type, network, prefix_length
# - nexthop_ip, nexthop_if, nexthop_vrf (NOT next_hop)
# - distance, metric, uptime, flag
CREATE_V_ROUTES = """
CREATE OR REPLACE VIEW v_routes AS
SELECT
    regexp_extract(filename, 'parsed/([^/]+)/', 1) AS device,
    d.network AS network,
    d.prefix_length AS prefix_length,
    d.nexthop_ip AS nexthop_ip,
    d.nexthop_if AS nexthop_if,
    d.protocol AS protocol,
    d.type AS type,
    d.vrf AS vrf,
    d.distance AS distance,
    COALESCE(TRY_CAST(d.metric AS BIGINT), 0) AS metric,
    d.uptime AS uptime
FROM (
    SELECT filename, unnest(data) AS d
    FROM read_json_auto('exports/snapshots/latest/parsed/*/*ip*route*.json', filename=true)
);
"""

## L4 System Performance Views
CREATE_V_CPU = """
CREATE OR REPLACE VIEW v_cpu_utilization AS
SELECT
    regexp_extract(filename, 'parsed/([^/]+)/', 1) AS device,
    d.process_name AS process_name,
    COALESCE(
        TRY_CAST(d.cpu_usage_5_sec AS DOUBLE), 0.0
    ) AS cpu_5sec,
    COALESCE(
        TRY_CAST(d.cpu_usage_1_min AS DOUBLE), 0.0
    ) AS cpu_1min,
    COALESCE(
        TRY_CAST(d.cpu_usage_5_min AS DOUBLE), 0.0
    ) AS cpu_5min
FROM (
    SELECT filename, unnest(data) AS d
    FROM read_json_auto('exports/snapshots/latest/parsed/*/show-processes-cpu*.json', filename=true)
);
"""

# Schema Discovery 发现的实际字段:
# - memory_total: VARCHAR
# - memory_used: VARCHAR
# - memory_free: VARCHAR
# - process_id: [VARCHAR]
# - process_allocated: [VARCHAR]
CREATE_V_MEMORY = """
CREATE OR REPLACE VIEW v_memory_utilization AS
SELECT
    regexp_extract(filename, 'parsed/([^/]+)/', 1) AS device,
    d.memory_total AS memory_total,
    d.memory_used AS memory_used,
    d.memory_free AS memory_free,
    CASE
        WHEN TRY_CAST(d.memory_total AS BIGINT) > 0 THEN
            ROUND(100.0 * TRY_CAST(d.memory_used AS BIGINT) / TRY_CAST(d.memory_total AS BIGINT), 2)
        ELSE 0.0
    END AS memory_used_percent
FROM (
    SELECT filename, unnest(data) AS d
    FROM read_json_auto('exports/snapshots/latest/parsed/*/show-processes-memory*.json', filename=true)
);
"""

# View creation list
ALL_VIEWS = [
    ("v_device_capabilities", CREATE_V_DEVICE_CAPABILITIES),
    ("v_device_status", CREATE_V_DEVICE_STATUS),
    ("v_environment", CREATE_V_ENVIRONMENT),
    ("v_interfaces", CREATE_V_INTERFACES),
    ("v_cdp_neighbors", CREATE_V_CDP_NEIGHBORS),
    ("v_arp", CREATE_V_ARP),
    ("v_bgp_neighbors", CREATE_V_BGP_NEIGHBORS),
    ("v_ospf_neighbors", CREATE_V_OSPF_NEIGHBORS),
    ("v_routes", CREATE_V_ROUTES),
    ("v_cpu_utilization", CREATE_V_CPU),
    ("v_memory_utilization", CREATE_V_MEMORY),
]


def create_inspection_views(conn: duckdb.DuckDBPyConnection) -> None:
    """
    Create all L1-L4 inspection views in DuckDB.

    Args:
        conn: DuckDB connection

    Raises:
        RuntimeError: If view creation fails
    """
    logger.info("Creating inspection views...")

    for view_name, view_sql in ALL_VIEWS:
        try:
            conn.execute(view_sql)
            logger.info(f"✅ Created view: {view_name}")
        except Exception as e:
            # Some commands might not exist for all devices
            logger.warning(f"⚠️  Skipped view {view_name}: {str(e)[:100]}")

    logger.info("✅ View creation completed")


def test_views() -> None:  # pragma: no cover
    """Test view creation with sample data."""
    conn = duckdb.connect(":memory:")

    # Create views
    create_inspection_views(conn)

    # Test device_status view
    result = conn.execute(
        "SELECT device, version, hostname FROM v_device_status LIMIT 3"
    ).fetchall()
    print("\n=== v_device_status ===")
    for row in result:
        print(row)

    # Test cpu_utilization view
    result = conn.execute(
        "SELECT device, process_name, cpu_5sec FROM v_cpu_utilization WHERE cpu_5sec > 0 LIMIT 5"
    ).fetchall()
    print("\n=== v_cpu_utilization (CPU > 0%) ===")
    for row in result:
        print(row)

    conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_views()
