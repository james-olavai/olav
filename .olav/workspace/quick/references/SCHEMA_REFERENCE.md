# 📊 Quick SQL Reference & Examples

> **CRITICAL**: Column names below are authoritative. Never guess column names.
> If a query fails with "column not found", call `execute_sql(explain_only=True)` immediately.

**Latest Snapshot Filter**: Each table/view has its own snapshot timeline. Always use `snapshot_id = (SELECT MAX(snapshot_id) FROM <same_table>)`.
Examples: `WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_bgp_neighbors)`, `WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_interfaces)`.
**NEVER** cross-reference `parsed_outputs` snapshot IDs when filtering other tables — they may differ.
**Never use** `sync_metadata` for snapshot filtering — it tracks sync jobs, not data snapshots.

---

## 🗄️ Core Table & View Schema

| Object | Type | Key Columns | Notes |
| :--- | :--- | :--- | :--- |
| **`devices`** | VIEW | `name`, `hostname`, `platform`, `mgmt_ip`, `device_type`, `device_role`, `site`, `vendor`, `model`, `is_active` | `name` = display name. `mgmt_ip` = management IP (not `ip`, not `management_ip`). |
| **`interfaces`** | TABLE | `device_name`, `interface`, `ip_address`, `status`, `description`, `snapshot_id` |  |
| **`v_interfaces`** | VIEW | `device_name`, `interface`, `ip_address`, `prefix_length`, `admin_status`, `line_status`, `snapshot_id` | Preferred for interface status queries. `prefix_length` is the CIDR mask bits (e.g. `30` for a /30). For loopback inventory, prefer one primary loopback per device (`Loopback0`/`lo0`/`lo0.0`). |
| **`bgp_neighbors`** | TABLE | `device_name`, `neighbor_ip`, `neighbor_as`, `state`, `prefixes_received`, `snapshot_id` |  |
| **`v_bgp_neighbors`** | VIEW | `device_name`, `neighbor_ip`, `neighbor_as`, `state`, `prefixes_received`, `local_as`, `router_id`, `snapshot_id` | Preferred for BGP queries. `local_as` = device's own AS number; `router_id` = BGP router-id. Both sourced from `parsed_outputs` raw data. |
| **`ospf_neighbors`** | TABLE | `device_name`, `neighbor_id`, `neighbor_ip`, `interface`, `state`, `priority`, `snapshot_id` |  |
| **`v_ospf_neighbors`** | VIEW | `device_name`, `neighbor_id`, `neighbor_ip`, `interface`, `state`, `priority`, `dead_time`, `snapshot_id` | Preferred; includes `dead_time`. |
| **`routes`** | TABLE | `device_name`, `network`, `mask`, `next_hop`, `interface`, `protocol`, `metric`, `snapshot_id` |  |
| **`v_routes_auto`** | VIEW | `device_name`, `network`, `next_hop`, `protocol`, `metric`, `snapshot_id` |  |
| **`bgp_routes`** | TABLE | `device_name`, `network`, `mask`, `next_hop`, `as_path`, `local_pref`, `metric`, `weight`, `communities`, `path_type`, `best_path`, `snapshot_id` |  |
| **`topology_links`** | VIEW | `source_device`, `source_interface`, `destination_device`, `destination_interface`, `discovery_protocol`, `link_type`, `link_status`, `snapshot_id`, `platform` | `source_*` / `destination_*` — NOT `local_*` or `remote_*`. |
| **`v_topo_links_clean`** | VIEW | `src`, `source_interface`, `dst`, `destination_interface`, `discovery_protocol`, `link_type`, `link_status`, `snapshot_id` | Compact alias: use `src`/`dst` for shorter queries. For L2 topology summaries, normalize device pairs with `LEAST(src,dst)` / `GREATEST(src,dst)` and `SELECT DISTINCT`. |
| **`v_l2_topology_summary`** | VIEW | `endpoint_a`, `endpoint_b`, `discovery_protocol`, `link_status`, `snapshot_id` | Preferred for deterministic L2 topology summaries. |
| **`v_device_neighbors_summary`** | VIEW | `device_name`, `connected_device`, `discovery_protocol`, `link_status`, `snapshot_id` | Preferred for deterministic per-device neighbor queries. |
| **`parsed_outputs`** | VIEW | `device_name`, `command`, `parsed_data`, `raw_output`, `snapshot_id` | Column is `parsed_data` NOT `output`; device key is `device_name` NOT `device_id`. Treat this as explicit raw snapshot query path only. Field names are vendor-specific — use `schema_catalog` for OC mapping. |
| **`schema_catalog`** | TABLE | `platform`, `source_name`, `source_type`, `fields` | **S3 SSOT**: OpenConfig mapping authority. `fields` is a JSON array of `{name, openconfig_path, mapping_confidence, mapping_source}`. Pipeline Stage 5 writes validated mappings here. |
| **`mapping_cache`** | TABLE | `platform`, `src_field`, `oc_path`, `confidence`, `stage`, `hit_count`, `validated` | Stage 2 lookup cache. Seeded from `mapping_rules`, updated by pipeline. Use for fast deterministic OC path lookup. |
| **`mapping_candidates`** | TABLE | `platform`, `src_field`, `oc_path`, `confidence`, `stage`, `needs_review` | Medium-confidence (0.55-0.70) LLM decisions. Audit Agent reviews and promotes valid entries to `schema_catalog`. |
| **`yang_leaves`** | TABLE | `yang_path`, `leaf_name`, `leaf_type`, `description`, `module` | OpenConfig YANG leaf registry (806 rows, 31 modules). Ground truth for all OC paths. Modules: interfaces, bgp, ospfv2, system, platform, lldp, network-instance, vlan, acl, qos, spanning-tree, isis, mpls, lacp, probes, segment-routing, macsec, optical-amplifier, terminal-device, etc. |
| **`mapping_rules`** | COMPAT TABLE | `vendor`, `command`, `src_field`, `oc_path`, `confidence` | **Derived compatibility shim — do NOT query directly.** Read from `schema_catalog` or `mapping_cache` instead. Serves as seed data source for pipeline. |

### Contract Priority (Phase 1)

1. Query semantic views first (`v_interfaces`, `v_bgp_neighbors`, `v_l2_topology_summary`, `v_device_neighbors_summary`).
2. Use `schema_catalog` to find OpenConfig mapping for a field: `SELECT fields FROM schema_catalog WHERE platform='...' AND source_name='...'`.
3. Use `parsed_outputs` only when raw snapshot inspection is explicitly required.
4. Do NOT use `mapping_rules` as primary analytical query source (legacy compat shim).

### OpenConfig YANG Module Prefixes

`openconfig_path` values in `schema_catalog` and `yang_leaves` use these module prefixes:

| Module prefix | Domain | Example path |
|---|---|---|
| `openconfig-interfaces:` | Interface config/state | `openconfig-interfaces:interfaces/interface/config/name` |
| `openconfig-bgp:` | BGP global, peers, policy | `openconfig-bgp:bgp/neighbors/neighbor/config/peer-as` |
| `openconfig-network-instance:` | VRFs, L3 protocols | `openconfig-network-instance:network-instances/network-instance/protocols/protocol/bgp/...` |
| `openconfig-ospf:` / `openconfig-ospfv2:` | OSPF adjacency/areas | `openconfig-ospfv2:...` |
| `openconfig-lldp:` | LLDP neighbors | `openconfig-lldp:lldp/interfaces/interface/neighbors/neighbor/state/system-name` |

Paths without a module prefix are also valid (module implied by context). To look up exact paths:
```sql
SELECT yang_path, leaf_name, module FROM yang_leaves WHERE module LIKE 'openconfig-%' AND leaf_name = 'peer-as';
SELECT openconfig_path FROM schema_catalog sc, json_each(sc.fields) f WHERE f.value->>'name' = 'neighbor_ip';
```

---

## 💡 Verified SQL Examples

### 1. List all devices with IP and platform
```sql
SELECT name, mgmt_ip, platform, device_role
FROM devices
WHERE is_active = true;
```

### 2. List down interfaces on a specific device
```sql
SELECT device_name, interface, admin_status, line_status
FROM v_interfaces
WHERE device_name = 'SW1'
  AND (admin_status != 'up' OR line_status != 'up')
  AND snapshot_id = (SELECT MAX(snapshot_id) FROM v_interfaces);
```

### 3. Find device by IP address
```sql
SELECT device_name, interface, ip_address
FROM interfaces
WHERE ip_address = '10.1.1.1'
  AND snapshot_id = (SELECT MAX(snapshot_id) FROM interfaces);
```

### 4. BGP neighbors in Established state
```sql
SELECT device_name, neighbor_ip, neighbor_as, state, prefixes_received
FROM v_bgp_neighbors
WHERE state = 'Established'
  AND snapshot_id = (SELECT MAX(snapshot_id) FROM v_bgp_neighbors);
```

### 4a. Primary loopback inventory
```sql
WITH ranked AS (
    SELECT device_name, interface, ip_address,
           row_number() OVER (
               PARTITION BY device_name
               ORDER BY CASE
                   WHEN lower(interface) IN ('loopback0', 'lo0', 'lo0.0') THEN 0
                   WHEN lower(interface) LIKE '%loopback0%' THEN 1
                   WHEN lower(interface) LIKE '%loop%' THEN 2
                   ELSE 3
               END,
               snapshot_id DESC
           ) AS rn
    FROM v_interfaces
    WHERE ip_address IS NOT NULL
      AND lower(interface) LIKE '%loop%'
      AND snapshot_id = (SELECT MAX(snapshot_id) FROM v_interfaces)
)
SELECT device_name, interface, ip_address
FROM ranked
WHERE rn = 1
ORDER BY device_name;
```

### 5. OSPF neighbors for a device
```sql
SELECT device_name, neighbor_id, neighbor_ip, interface, state
FROM v_ospf_neighbors
WHERE device_name = 'R1'
  AND snapshot_id = (SELECT MAX(snapshot_id) FROM v_ospf_neighbors);
```

### 6. Network topology links
```sql
SELECT endpoint_a, endpoint_b, discovery_protocol
FROM v_l2_topology_summary
WHERE discovery_protocol IN ('LLDP', 'CDP')
  AND snapshot_id = (SELECT MAX(snapshot_id) FROM v_l2_topology_summary)
ORDER BY endpoint_a, endpoint_b;
```

### 6b. Raw LLDP/CDP links (with interface detail)
```sql
SELECT LEAST(src, dst) AS a, GREATEST(src, dst) AS b, discovery_protocol
FROM v_topo_links_clean
WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM v_topo_links_clean)
GROUP BY a, b, discovery_protocol
ORDER BY a, b;
```

### 6a. Device neighbor summary
```sql
SELECT connected_device, discovery_protocol
FROM v_device_neighbors_summary
WHERE device_name = 'R2'
  AND snapshot_id = (SELECT MAX(snapshot_id) FROM v_device_neighbors_summary)
ORDER BY connected_device, discovery_protocol;
```

### 7. Routing table for a device
```sql
SELECT device_name, network, next_hop, protocol, metric
FROM v_routes_auto
WHERE device_name = 'R3'
  AND snapshot_id = (SELECT MAX(snapshot_id) FROM v_routes_auto);
```

### 8. Extract fields from parsed JSON output
```sql
SELECT device_name,
       json_extract_string(item, '$.interface') AS iface,
       json_extract_string(item, '$.status') AS status
FROM parsed_outputs,
     UNNEST(json_extract(parsed_data, '$[*]')::JSON[]) AS t(item)
WHERE command LIKE '%interface%'
  AND snapshot_id = (SELECT MAX(snapshot_id) FROM parsed_outputs);
```

### 8. Find OpenConfig mapping for a field
```sql
-- Get all OC mappings for a platform's "show interface" command
SELECT json_extract_string(field, '$.name') AS field_name,
       json_extract_string(field, '$.openconfig_path') AS oc_path,
       json_extract(field, '$.mapping_confidence') AS confidence
FROM schema_catalog,
     UNNEST(json_extract(fields, '$[*]')::JSON[]) AS t(field)
WHERE platform = 'cisco_ios'
  AND source_name = 'show interface'
  AND json_extract_string(field, '$.openconfig_path') IS NOT NULL;
```

### 9. Check mapping_cache for a field
```sql
-- Fast lookup: what OC path does "mtu" map to on cisco_ios?
SELECT oc_path, confidence, stage, hit_count
FROM mapping_cache
WHERE platform = 'cisco_ios'
  AND src_field = 'mtu';
```

### 10. Review mapping_candidates pending audit
```sql
-- See medium-confidence decisions awaiting review
SELECT platform, src_field, oc_path, confidence
FROM mapping_candidates
WHERE needs_review = TRUE
ORDER BY confidence DESC
LIMIT 20;
```

---

## 🚫 Common Mistakes to Avoid

| DO NOT USE | USE INSTEAD | Reason |
| :--- | :--- | :--- |
| `devices.ip` | `devices.mgmt_ip` | Column is named `mgmt_ip` |
| `devices.management_ip` | `devices.mgmt_ip` | Column is named `mgmt_ip` |
| `topology_links.local_device` | `topology_links.source_device` | Correct column name |
| `topology_links.local_port` | `topology_links.source_interface` | Correct column name |
| `topology_links.remote_device` | `topology_links.destination_device` | Correct column name |
| `topology_links.remote_port` | `topology_links.destination_interface` | Correct column name |
| `topology_links.hostname_a` | `topology_links.source_device` | `hostname_a` does not exist |
| `parsed_outputs.output` | `parsed_outputs.parsed_data` | Column is `parsed_data` |
| `parsed_outputs.device_id` | `parsed_outputs.device_name` | Column is `device_name` |
| `interfaces.device_id` | `interfaces.device_name` | Column is `device_name` |
| `sync_metadata` for snapshot | `(SELECT MAX(snapshot_id) FROM <same_table>)` | `sync_metadata` has no snapshot_id |
| `v_bgp_neighbors_enriched` | `v_bgp_neighbors` | Enriched view does not exist |
| `v_routes_enriched` | `v_routes_auto` | Enriched view does not exist |

---

## 🛠️ Schema Validation Rule
On any `Binder Error: Referenced column "X" not found`:
1. call `execute_sql(explain_only=True)` to fetch live schema
2. regenerate SQL with exact column names
3. rerun query without switching to other tables as implicit fallback
