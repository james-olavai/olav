# 📊 Quick SQL Reference & Examples (R82)

> **CRITICAL**: Column names below are authoritative.  Pre-R82 versions
> of this file referenced columns / views that **no longer exist**
> (`mgmt_ip`, `device_type`, `device_role`, `is_active`,
> `v_interfaces`, `v_topo_links_clean`, `v_device_neighbors_summary`,
> `v_l2_topology_summary`, `v_routes_auto`).  All listed below match
> current production schema.

**Latest snapshot filter**: Each table has its own snapshot timeline.
Always use `snapshot_id = (SELECT MAX(snapshot_id) FROM <same_table>)`.

---

## 🗄️ netops.* Tables (the data plane)

| Table | Key Columns | Notes |
|---|---|---|
| **`netops.devices`** | `hostname`, `ip_address`, `platform`, `vendor`, `model`, `os_version`, `role`, `site`, `environment`, `last_seen`, `metadata` | `ip_address` = mgmt IP (NOT `mgmt_ip`/`management_ip`/`ip`); `platform` = netmiko driver name (`cisco_ios`/`juniper_junos`/…) (NOT `device_type`/`os`); `role` (NOT `device_role`); `metadata` = JSON with `groups`, `aliases`, `loopback_ip` |
| **`netops.parsed_outputs`** | `device_name`, `command`, `parsed_data` (JSON array), `raw_output_hash`, `snapshot_id`, `ingested_at` | Field names inside `parsed_data` follow ntc-templates lowercase convention. Interface / IP / ASN / MAC are auto-canonicalised at ingest (R72). |
| **`netops.raw_output_store`** | `device_name`, `command`, `raw_output`, `snapshot_id`, `updated_at` | One row per `(device, command)`, latest wins. Use as Tier-3 fallback when `parsed_data` is NULL. |
| **`netops.topology_links`** | `source_device`, `source_interface`, `destination_device`, `destination_interface`, `discovery_protocol`, `link_status`, `link_type`, `link_speed`, `first_seen`, `last_seen`, `snapshot_id`, `platform` | Use `source_*`/`destination_*` (NOT `local_*`/`remote_*`). |
| **`netops.commands`** | `platform`, `command`, `safe_command`, `parser_type`, `parser_path`, `blacklisted`, `pipe_allowed`, `backup_only`, `synced_at` | R73 SSOT — populated by `commands_sync` from ntc-templates + custom + PaC + YAML overlays. |

## 🗄️ netops.* Auto Views (vendor-normalised, state-canonicalised)

| View | Key Columns |
|---|---|
| **`netops.v_bgp_neighbors_auto`** | `device`, `neighbor_ip`, `neighbor_as`, `local_as`, `router_id`, `state`, `uptime`, `snapshot_id` |
| **`netops.v_ospf_neighbors_auto`** | `device`, `neighbor_id`, `neighbor_ip`, `interface`, `area`, `state`, `dead_time`, `snapshot_id` |
| **`netops.v_l2_links_auto`** | `source_device`, `source_interface`, `destination_device`, `destination_interface`, `discovery_protocol`, `link_status`, `snapshot_id` |

> **No view for interfaces / ARP / routes / VLANs.**  JSON-extract from
> `netops.parsed_outputs.parsed_data` for the matching command.  The
> agent then reads + reasons over the structured rows.

---

## 💡 Verified SQL Examples (R82 — all run against current schema)

### 1. List all devices with IP, platform, role
```sql
SELECT hostname, ip_address, platform, role, site
FROM netops.devices
ORDER BY hostname;
```

### 2. Find devices by alias / group (Chinese alias supported)
```sql
SELECT hostname, ip_address
FROM netops.devices
WHERE metadata LIKE '%核心路由器%';
-- or by group:
SELECT hostname FROM netops.devices WHERE metadata LIKE '%"groups":%"core_routers"%';
```

### 3. BGP neighbor state across the fleet
```sql
SELECT device, neighbor_ip, neighbor_as, state
FROM netops.v_bgp_neighbors_auto
WHERE state != 'Established'
ORDER BY device;
```

### 4. OSPF adjacencies by area
```sql
SELECT area, device, neighbor_id, state
FROM netops.v_ospf_neighbors_auto
ORDER BY area, device;
```

### 5. L2 topology (deduplicated — one row per physical link)
```sql
SELECT source_device, source_interface, destination_device, destination_interface,
       discovery_protocol
FROM netops.v_l2_links_auto
ORDER BY source_device, source_interface;
```

### 6. Latest snapshot per device
```sql
SELECT device_name, MAX(snapshot_id) AS latest
FROM netops.parsed_outputs
GROUP BY 1
ORDER BY 1;
```

### 7. JSON-extract interface IPs (no `v_interfaces_auto` view exists)
```sql
SELECT device_name,
       json_extract(parsed_data, '$[*].INTERFACE') AS ifaces,
       json_extract(parsed_data, '$[*].IP_ADDRESS') AS ips
FROM netops.parsed_outputs
WHERE command = 'show ip interface brief'
  AND device_name = 'R3';
```

The above returns whole-array projections.  When you need to **filter
by per-row attributes** (e.g. "all interfaces where status='down'")
use the LATERAL pattern in the cookbook below.

### 8. Raw fallback when no parser ran
```sql
SELECT device_name, command, raw_output
FROM netops.raw_output_store
WHERE command = 'show vlan brief'
  AND device_name = 'SW1';
```

---

## 🧰 parsed_data JSON-extract cookbook

When no `v_*_auto` view covers the concept (interfaces, ARP, VLAN, routes,
…) extract per-row fields from `parsed_outputs.parsed_data` using
**`LATERAL json_each(...)` + `json_extract_string`**.  Always pin to
the latest snapshot per (device, command).

**Field names come from ntc-templates** and are **UPPERCASE** for
cisco_ios commands (`INTERFACE`, `IP_ADDRESS`, `STATUS`, `PROTO`,
`MAC_ADDRESS`, …).  Junos parsers tend to emit lowercase. When in
doubt, run `SELECT json_extract_string(parsed_data, '$[0]') ...` on
one row to inspect keys.

### Recipe — down interfaces across the fleet

```sql
SELECT p.device_name,
       json_extract_string(t.entry, '$.INTERFACE') AS interface,
       json_extract_string(t.entry, '$.IP_ADDRESS') AS ip_address,
       json_extract_string(t.entry, '$.STATUS') AS status,
       json_extract_string(t.entry, '$.PROTO') AS proto
FROM netops.parsed_outputs p,
     LATERAL (SELECT value AS entry FROM json_each(p.parsed_data)) t
WHERE p.command = 'show ip interface brief'
  AND p.snapshot_id = (SELECT MAX(snapshot_id) FROM netops.parsed_outputs s
                       WHERE s.device_name = p.device_name
                         AND s.command = p.command)
  AND (lower(json_extract_string(t.entry, '$.STATUS')) LIKE '%down%'
       OR lower(json_extract_string(t.entry, '$.PROTO')) = 'down');
```

Returns rows like `('R2', 'GigabitEthernet3', 'unassigned', 'administratively down', 'down')`.

### Recipe — ARP table for a device

```sql
SELECT json_extract_string(t.entry, '$.IP_ADDRESS') AS ip,
       json_extract_string(t.entry, '$.MAC_ADDRESS') AS mac,
       json_extract_string(t.entry, '$.INTERFACE') AS interface,
       json_extract_string(t.entry, '$.AGE') AS age_min
FROM netops.parsed_outputs p,
     LATERAL (SELECT value AS entry FROM json_each(p.parsed_data)) t
WHERE p.command = 'show ip arp'
  AND p.device_name = 'R3'
  AND p.snapshot_id = (SELECT MAX(snapshot_id) FROM netops.parsed_outputs s
                       WHERE s.device_name = p.device_name
                         AND s.command = p.command);
```

### Recipe — interfaces by description (find a port by purpose)

```sql
SELECT p.device_name,
       json_extract_string(t.entry, '$.PORT') AS interface,
       json_extract_string(t.entry, '$.STATUS') AS status,
       json_extract_string(t.entry, '$.DESCRIPTION') AS description
FROM netops.parsed_outputs p,
     LATERAL (SELECT value AS entry FROM json_each(p.parsed_data)) t
WHERE p.command = 'show interfaces description'
  AND p.snapshot_id = (SELECT MAX(snapshot_id) FROM netops.parsed_outputs s
                       WHERE s.device_name = p.device_name
                         AND s.command = p.command)
  AND lower(json_extract_string(t.entry, '$.DESCRIPTION')) LIKE '%uplink%';
```

### Recipe — Junos interfaces (custom seed parser, keys differ)

Junos `show interfaces terse` ships its own seed TextFSM (see
`olav-netops/.olav/workspace/ops/netops_init/seed_templates/juniper_junos/`)
which emits **lowercase** keys (`interface`, `admin_state`,
`link_state`, `proto`, `ip_address`):

```sql
SELECT p.device_name,
       json_extract_string(t.entry, '$.interface') AS interface,
       json_extract_string(t.entry, '$.admin_state') AS admin_state,
       json_extract_string(t.entry, '$.link_state') AS link_state,
       json_extract_string(t.entry, '$.ip_address') AS ip_address
FROM netops.parsed_outputs p,
     LATERAL (SELECT value AS entry FROM json_each(p.parsed_data)) t
WHERE p.command = 'show interfaces terse'
  AND p.device_name = 'R1'
  AND p.snapshot_id = (SELECT MAX(snapshot_id) FROM netops.parsed_outputs s
                       WHERE s.device_name = p.device_name
                         AND s.command = p.command)
  AND json_extract_string(t.entry, '$.admin_state') = 'down';
```

### Discovering keys for a command

```sql
-- Show the JSON keys that any parser produced for this command across
-- the fleet — useful when you don't know whether to query INTERFACE
-- or interface, STATUS or status, etc.
SELECT DISTINCT json_keys(parsed_data->0) AS keys, device_name
FROM netops.parsed_outputs
WHERE command = 'show ip interface brief'
LIMIT 5;
```

> ⚠️ Always include the per-(device, command) snapshot filter in any
> cookbook query — without it, every `/netops_init` rerun multiplies
> rowcount, and per-row filters silently match across stale snapshots.

---

## ⛔ Common SQL mistakes (and the right form)

| ❌ Wrong | ✅ Right |
|---|---|
| `SELECT mgmt_ip FROM devices` | `SELECT ip_address FROM netops.devices` |
| `SELECT management_ip FROM devices` | `SELECT ip_address FROM netops.devices` |
| `SELECT device_type FROM devices` | `SELECT platform FROM netops.devices` |
| `SELECT device_role FROM devices` | `SELECT role FROM netops.devices` |
| `SELECT * FROM devices WHERE is_active = true` | (no `is_active`) `SELECT * FROM netops.devices` |
| `SELECT * FROM v_interfaces` (deleted) | JSON-extract from `netops.parsed_outputs WHERE command='show ip interface brief'` |
| `SELECT * FROM v_topo_links_clean` (deleted) | `SELECT * FROM netops.v_l2_links_auto` |
| `SELECT * FROM v_device_neighbors_summary` (deleted) | `SELECT * FROM netops.v_l2_links_auto` |
| `SELECT * FROM bgp_sessions` (deleted in R70) | `SELECT * FROM netops.v_bgp_neighbors_auto` |
| `SELECT * FROM ospf_adjacencies` (deleted in R70) | `SELECT * FROM netops.v_ospf_neighbors_auto` |
| `FROM devices` (no schema prefix) | `FROM netops.devices` (always prefix) |

---

## What's *not* in the schema anymore

R70 deleted these in favour of declarative `view_recipes`:
* `netops.bgp_sessions` / `netops.ospf_adjacencies` (materialised L3 tables)
* `v_interfaces` / `v_topology_l2` / `v_topo_links_clean` / `v_arp` / `v_routes_enriched`
* `v_device_neighbors_summary` / `v_l2_topology_summary`
* `view_recipes_seed.yaml` monolith (split into per-protocol files)

R72 deleted `auto_learn.py` batch learner; use `/learn_cmd` for
interactive parser learning.
