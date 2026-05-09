-- create_cross_vendor_views.sql — vendor-agnostic BGP / OSPF / loopback
-- views.  Idempotent (CREATE OR REPLACE).
--
-- Run from a workspace root with .olav/databases/main.duckdb, or via
-- the helper script scripts/create_cross_vendor_views.py.

-- ------------------------------------------------------------------------
-- v_bgp_neighbors_auto — unified BGP session table across vendors.
--
-- Columns (uniform across vendors):
--   device_name        — local hostname
--   snapshot_id        — the snapshot this row was captured in
--   neighbor_ip        — peer's IP address
--   neighbor_as        — peer's AS (UBIGINT)
--   state              — normalised: "Established" / "Idle" / "Active" / etc.
--   prefixes_received  — INTEGER, only set when state = Established
--
-- Sources unioned:
--   * Cisco IOS / NX-OS / IOS-XR / ASA — ``show ip bgp summary``
--     (or vendor-specific equivalent), parsed_data shape:
--       {bgp_neighbor, neighbor_as, state_or_prefixes_received, ...}
--     state_or_prefixes_received is OVERLOADED: numeric → Established
--     with that prefix count; non-numeric → state name.
--   * Juniper Junos — ``show bgp summary``, parsed_data shape:
--     {peer, peer_as, state, uptime, ...}
--     state is already a name like "Established" or "Idle".
CREATE OR REPLACE VIEW netops.v_bgp_neighbors_auto AS

-- Cisco-family.  After the platform-column denormalisation
-- (R-VERTICAL-SLICE 2026-05-09, migrate_add_platform_column.py),
-- the vendor filter is a direct WHERE on parsed_outputs.platform,
-- not a JOIN/EXISTS to netops.devices.
SELECT
    p.device_name,
    p.snapshot_id,
    p.platform,
    CAST(json_extract_string(elem, '$.bgp_neighbor') AS VARCHAR)
        AS neighbor_ip,
    CAST(json_extract_string(elem, '$.neighbor_as') AS UBIGINT)
        AS neighbor_as,
    CASE
        WHEN regexp_matches(
                COALESCE(json_extract_string(elem, '$.state_or_prefixes_received'), ''),
                '^[0-9]+$'
             )
        THEN 'Established'
        ELSE COALESCE(json_extract_string(elem, '$.state_or_prefixes_received'), 'Unknown')
    END AS state,
    CASE
        WHEN regexp_matches(
                COALESCE(json_extract_string(elem, '$.state_or_prefixes_received'), ''),
                '^[0-9]+$'
             )
        THEN CAST(json_extract_string(elem, '$.state_or_prefixes_received') AS INTEGER)
        ELSE NULL
    END AS prefixes_received,
    'cisco' AS vendor_family
FROM netops.parsed_outputs p,
     LATERAL (
         SELECT unnest(
             CAST(p.parsed_data AS JSON[])
         ) AS elem
     )
WHERE p.platform LIKE 'cisco%'
  AND p.command IN (
      'show ip bgp summary',
      'show bgp summary vrf all',
      'show bgp instance all summary'
  )
  AND p.parsed_data IS NOT NULL

UNION ALL

-- Juniper Junos
SELECT
    p.device_name,
    p.snapshot_id,
    p.platform,
    CAST(json_extract_string(elem, '$.peer') AS VARCHAR)        AS neighbor_ip,
    CAST(json_extract_string(elem, '$.peer_as') AS UBIGINT)     AS neighbor_as,
    CAST(json_extract_string(elem, '$.state') AS VARCHAR)       AS state,
    -- Junos doesn't expose prefix count in summary; null is honest.
    NULL                                                        AS prefixes_received,
    'juniper' AS vendor_family
FROM netops.parsed_outputs p,
     LATERAL (
         SELECT unnest(
             CAST(p.parsed_data AS JSON[])
         ) AS elem
     )
WHERE p.platform LIKE '%junos%'
  AND p.command = 'show bgp summary'
  AND p.parsed_data IS NOT NULL
;
