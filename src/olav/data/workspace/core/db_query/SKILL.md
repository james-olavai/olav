---
name: db_query
description: "Database queries — complex multi-step DuckDB SQL workflows"
tools:
  - execute_sql
  - describe_table
references:
  - path: ./references/RAW_FALLBACK.md
---

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
