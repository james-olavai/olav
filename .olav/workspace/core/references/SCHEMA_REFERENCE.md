# 📊 Quick SQL Reference & Examples (R82)

> **CRITICAL**: Column names and view names below are authoritative.
> Use only the table/view names listed here — do NOT guess or extend.

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

## 🗄️ netops.* Auto Views — two layers

### Layer 1: Cross-vendor semantic views (manual recipes)

For BGP / OSPF / L2 — vendor-normalised, state-canonicalised:

| View | Key Columns |
|---|---|
| **`netops.v_bgp_neighbors_auto`** | `device`, `neighbor_ip`, `neighbor_as`, `local_as`, `router_id`, `state`, `uptime`, `snapshot_id` |
| **`netops.v_ospf_neighbors_auto`** | `device`, `neighbor_id`, `neighbor_ip`, `interface`, `area`, `state`, `dead_time`, `snapshot_id` |
| **`netops.v_l2_links_auto`** | `source_device`, `source_interface`, `destination_device`, `destination_interface`, `discovery_protocol`, `link_status`, `snapshot_id` |

These views handle Junos `Estab` vs IOS `Established` etc. via SQL CASE.

### Layer 2: Per-command zero-ETL views (auto-generated, R83)

**For every command in ``netops.parsed_outputs``**, `/netops_init` creates
a typed view ``netops.v_<safe_command>_auto`` via DuckDB's
``unnest(from_json(parsed_data, …), recursive := true)``.  No field
mappings, no recipes — columns are exactly what the parser emitted.

Examples:

| Command | Auto-view |
|---|---|
| `show ip interface brief` | `netops.v_show_ip_interface_brief_auto` (cols: `device_name`, `snapshot_id`, `INTERFACE`, `IP_ADDRESS`, `STATUS`, `PROTO`) |
| `show ip arp` | `netops.v_show_ip_arp_auto` (cols: `PROTOCOL`, `IP_ADDRESS`, `MAC_ADDRESS`, `INTERFACE`, …) |
| `show interfaces description` | `netops.v_show_interfaces_description_auto` (cols: `PORT`, `STATUS`, `PROTOCOL`, `DESCRIPTION`) |
| `show interfaces terse` (Junos) | `netops.v_show_interfaces_terse_auto` (cols: `interface`, `admin_state`, `link_state`, `proto`, `ip_address`) |

**Discover columns**: `DESCRIBE netops.v_show_ip_interface_brief_auto`.
The view auto-filters to the latest snapshot per (device, command);
just `SELECT * FROM <view> WHERE <column> ...`.

> **List all available views**: `SHOW TABLES` or
> `SELECT table_name FROM information_schema.views WHERE table_schema='netops' AND table_name LIKE 'v_%_auto'`.

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

## 🧰 Querying parsed_data — preferred flow

```
1. List available views:
   SELECT table_name FROM information_schema.views
   WHERE table_schema='netops' AND table_name LIKE 'v_%_auto'
   ORDER BY 1;

2. Inspect a view's columns:
   DESCRIBE netops.v_show_ip_interface_brief_auto;

3. Query directly (latest-snapshot filter is built in):
   SELECT device_name, INTERFACE, STATUS
   FROM netops.v_show_ip_interface_brief_auto
   WHERE STATUS LIKE '%down%';
```

That's the whole flow.  No `LATERAL`, no `json_each`, no
`json_extract_string` —  DuckDB unnests + types the JSON at view
creation time.

### Field-name conventions

* **cisco_ios** parsers (ntc-templates) emit **UPPERCASE** keys:
  `INTERFACE`, `IP_ADDRESS`, `STATUS`, `PROTO`, `MAC_ADDRESS`,
  `DESCRIPTION`, …
* **juniper_junos** seed parsers tend to emit **lowercase**:
  `interface`, `admin_state`, `link_state`, `proto`, `ip_address`.

Always run `DESCRIBE` first if unsure.

### Fallback — when no auto-view exists yet

If a command was just collected but `/netops_init` hasn't rebuilt
views, or the command's parsed_data isn't a list of objects, you can
still extract directly:

```sql
SELECT p.device_name,
       json_extract_string(t.entry, '$.INTERFACE') AS interface,
       json_extract_string(t.entry, '$.STATUS') AS status
FROM netops.parsed_outputs p,
     LATERAL (SELECT value AS entry FROM json_each(p.parsed_data)) t
WHERE p.command = 'show ip interface brief'
  AND p.snapshot_id = (SELECT MAX(snapshot_id) FROM netops.parsed_outputs s
                       WHERE s.device_name = p.device_name AND s.command = p.command);
```

The fallback always works but is slower to compose and easier to get
wrong; prefer the auto-view path.

---

## ⛔ Common SQL mistakes (and the right form)

| ❌ Wrong | ✅ Right |
|---|---|
| `SELECT mgmt_ip FROM devices` | `SELECT ip_address FROM netops.devices` |
| `SELECT management_ip FROM devices` | `SELECT ip_address FROM netops.devices` |
| `SELECT device_type FROM devices` | `SELECT platform FROM netops.devices` |
| `SELECT device_role FROM devices` | `SELECT role FROM netops.devices` |
| `SELECT * FROM devices WHERE is_active = true` | (no `is_active`) `SELECT * FROM netops.devices` |
| `SELECT mac_address FROM v_*` | JSON-extract from `netops.parsed_outputs WHERE command='show mac address-table'` |
| `FROM bgp_sessions` | `FROM netops.v_bgp_neighbors_auto` |
| `FROM ospf_adjacencies` | `FROM netops.v_ospf_neighbors_auto` |
| `FROM devices` (no schema prefix) | `FROM netops.devices` (always prefix) |

For neighbors / adjacencies / topology data the only valid sources are:
* `netops.topology_links` (CDP/LLDP base table)
* `netops.v_l2_links_auto` (cleaned topology view)
* `netops.v_bgp_neighbors_auto` (BGP sessions, cross-vendor)
* `netops.v_ospf_neighbors_auto` (OSPF adjacencies, cross-vendor)

If a name like `v_topology_l2_auto` / `v_topo_links_clean` / `v_topo_*`
/ `v_device_neighbors_summary` comes to mind — STOP, those don't
exist; use one of the four canonical names above.
