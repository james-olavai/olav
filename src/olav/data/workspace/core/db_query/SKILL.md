---
name: db_query
description: "Database queries — complex multi-step DuckDB SQL workflows"
tools:
  - execute_sql
  - describe_table
references:
  - path: ./references/RAW_FALLBACK.md
---

## Known columns (write SQL directly — do NOT call describe_table first)

These are the stable, frequently-queried columns.  Use them as the
authoritative reference when composing SQL — calling
`describe_table` first wastes a tool round-trip.

### `netops.devices` — device inventory (one row per host)
`hostname`, `ip_address` (mgmt IP from nornir hosts.yaml), `platform`
(netmiko/ntc-templates name: `cisco_ios` / `juniper_junos` / …),
`vendor`, `model`, `os_version`, `role`, `site`, `environment`,
`last_seen`, `metadata` (JSON: `groups`, `aliases`, `loopback_ip`).

> **Common mistakes:** the column is **`ip_address`** (NOT
> `management_ip`, `mgmt_ip`, or `ip`); **`platform`** (NOT
> `device_type`, `os`, `vendor_os`); **`role`** (NOT `device_role`).

### `netops.topology_links` — physical connectivity
`source_device`, `source_interface`, `destination_device`,
`destination_interface`, `discovery_protocol` (CDP/LLDP),
`link_status`, `link_type`, `link_speed`, `first_seen`, `last_seen`,
`snapshot_id`, `platform`.

### `netops.parsed_outputs` — structured per-command output
`device_name`, `command`, `parsed_data` (JSON array of dicts —
field names come from the parser, ntc-templates lowercase
convention: e.g. `interface`, `ip_address`, `state`),
`raw_output_hash`, `snapshot_id`, `ingested_at`.

### `netops.raw_output_store` — verbatim CLI text
`device_name`, `command`, `raw_output` (text), `snapshot_id`,
`updated_at`.  PK: `(device_name, command)` — one row per pair, latest
wins.

### `netops.commands` — command registry (R73 SSOT)
`platform`, `command`, `safe_command`, `parser_type`
(`ntc` / `custom_textfsm` / `pac` / `raw_only`), `parser_path`,
`blacklisted`, `pipe_allowed`, `backup_only`, `synced_at`.

### Auto views (vendor-normalised, state-canonicalised)
* `netops.v_bgp_neighbors_auto` — `device`, `neighbor_ip`,
  `neighbor_as`, `local_as`, `router_id`, `state`, `uptime`,
  `snapshot_id`
* `netops.v_ospf_neighbors_auto` — `device`, `neighbor_id`,
  `neighbor_ip`, `interface`, `area`, `state`, `dead_time`,
  `snapshot_id`
* `netops.v_l2_links_auto` — `source_device`, `source_interface`,
  `destination_device`, `destination_interface`,
  `discovery_protocol`, `link_status`, `snapshot_id`

> Use `describe_table` only when the user asks about a column not
> listed above OR a custom table outside `netops.*`.

## Output Rules

1. When the user asks to **list / enumerate / 列出 / 显示所有**, display **ALL rows** returned — do not summarize, truncate, or show only representative examples.
2. Format tabular results as Markdown tables with column headers matching the query fields.
3. If result exceeds 50 rows, show first 20 rows and note: "共 N 条记录，已截断显示前 20 条".
4. Always include row count: "共 N 条记录".
5. Never paraphrase or condense multi-row results into prose when the user asked for a list.

## Data access policy (R72 raw-fallback strategy)

Follow this **three-tier chain** when the user asks about device data:

**Tier 1 — semantic views** (fastest, structured)
```sql
SELECT * FROM netops.v_bgp_neighbors_auto WHERE ...
SELECT * FROM netops.v_ospf_neighbors_auto WHERE ...
SELECT * FROM netops.v_l2_links_auto WHERE ...
```
If the view exists and returns rows → done.

**Tier 2 — parsed_outputs JSON** (structured for less-common concepts)
```sql
SELECT device_name, command, parsed_data
  FROM netops.parsed_outputs
 WHERE command = 'show ip route' AND device_name = 'R1';
```
`parsed_data` is a JSON array of dicts. Read it, extract what you need.

**Tier 3 — raw fallback** (last resort, works for anything captured)
```sql
SELECT raw_output
  FROM netops.raw_output_store
 WHERE device_name = 'R1' AND command LIKE '%bgp%';
```
Read the raw CLI text yourself and extract the answer by reasoning.
**Never answer "I cannot parse this command"** — raw is always available.

Details and examples: see `references/RAW_FALLBACK.md`.
