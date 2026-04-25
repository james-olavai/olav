# Profile Authoring Mode

Load when the user's request is to **create / extend / retune** an
audit Profile (rather than *run* one).  Authoring mode and execution
mode (`map_engine` + `render_report`) are mutually exclusive — one
user turn is either running or authoring, never both.

## Hard constraints

- **Never** use `ls`, `glob`, `grep`, or any filesystem tool to search
  for reference files or legacy files.
- All Profile content must be generated from the user's job
  specification plus `database_introspection` results — never look up
  existing files.
- Call `database_introspection` immediately — don't search or ask
  questions first.
- **Language rule:** detect the user's input language.  Write all
  `section_prompt` values and conversational responses in that
  language.  Internal YAML keys, SQL, and code always remain in
  English regardless.

## Authoring tool-call workflow (strict order)

```
1. database_introspection(db_type="duckdb")      ← FIRST — run immediately
   → Learn real table and column names. Never guess.

2. test_map_query(job_type="sql", query=..., params={"window": "1h"})
   → Validate SQL syntax for each job. Zero rows is fine; errors are not.

3. save_profile(name=..., yaml_jobs=[...], markdown_body=...)
   → Write to profiles/<name>.md after schema validation passes.
```

For data-driven thresholds, call `analyze_thresholds` between steps 2
and 3.  For extending an existing profile, use `read_profile` +
`append_jobs` instead of `save_profile`.

## The three authoring sub-modes

| Sub-mode | When to use | Key tools |
|---|---|---|
| **Intelligent Threshold** | Fresh profile with "smart" thresholds from past observations | `database_introspection` → `analyze_thresholds` → `save_profile` |
| **Dynamic Retuning** | Existing profile produces too many false positives / misses known incidents | `read_profile` → `analyze_thresholds` → `save_profile` (overwrite) |
| **Append Jobs** | Add new jobs to an existing profile without touching old ones | `read_profile` → compose new jobs → `append_jobs` |

### Mode 1: Intelligent Threshold Suggestion

```
1. database_introspection(db_type="duckdb")
   → Confirm which tables and columns are available for the metric.

2. analyze_thresholds(
       metric_query="SELECT <numeric_column> AS value FROM <table> WHERE ...",
       metric_name="<MetricName>",
       higher_is_worse=True/False,
       unit="%"
   )
   → Obtain P50/P90/P95/P99 distribution + recommended thresholds.

3. Present results to the user and wait for confirmation:
   "Suggested Warning = XX%, Critical = YY%. Proceed?"

4. After user confirms (or adjusts), call save_profile.
```

Rules:
- `metric_query` must return a single column named `value` (numeric).
- If sample count < 10, lower confidence and inform the user of
  insufficient data.
- Call `analyze_thresholds` once per metric; batch results before
  confirming with user.

### Mode 2: Dynamic Threshold Tuning

```
1. list_profiles()           → Show available profiles.
2. read_profile(name=...)    → Retrieve current jobs and thresholds.
3. analyze_thresholds(...)   → Compute latest P90/P95 for each numeric job.
4. Present diff table → user confirms → save_profile (full overwrite).
```

Rules:
- Skip jobs whose SQL cannot be reduced to a numeric distribution —
  mark "skipped".
- `save_profile` overwrite MUST wait for explicit user confirmation
  (HMITL gate).
- Highlight any threshold change greater than ±20%.

### Mode 3: Appending Check Items

```
1. read_profile(name=...)          → Confirm existing job names (avoid duplicates).
2. database_introspection(...)     → Verify table/column names for new job.
3. test_map_query(query=...)       → Validate new job SQL.
4. analyze_thresholds(...) [opt]   → Data-driven thresholds if requested.
5. append_jobs(profile_name=..., new_jobs=[...])
   → Atomic append without touching existing jobs.
```

Rules:
- `append_jobs` auto-detects name conflicts; rename and retry on error.
- After appending, report new job names + total job count.

## Profile job field specification

Each job must include:

| Field | Spec |
|---|---|
| `name` | Unique UPPER_SNAKE_CASE identifier |
| `duckdb_query` | DuckDB SQL — must return `device, metric_value, metric_name, severity_hint` |
| `warning_threshold` | Numeric warning level |
| `critical_threshold` | Numeric critical level |
| `operator` | `>` for high-is-bad, `<` for low-is-bad |
| `unit` | e.g. `%`, `ms`, or empty string |
| `description` | What this job monitors |
| `remediation` | Recommended remediation steps (markdown) |

## Known database schema (reference only — always confirm via `database_introspection`)

- `interfaces`: `device_name`, `interface`, `status`, `description`, `snapshot_id`, `created_at`
  - `v_interfaces`: adds `admin_status`, `line_status`
- `bgp_neighbors`: `device_name`, `neighbor_ip`, `neighbor_as`, `state`, `prefixes_received`, `created_at`
- `ospf_neighbors`: `device_name`, `neighbor_id`, `neighbor_ip`, `interface`, `state`, `priority`, `created_at`
- `parsed_outputs`: `device_name`, `command`, `parsed_data` (JSON), `raw_output`, `created_at`
- `raw_diffs`: `snapshot_id_1`, `snapshot_id_2`, `device_name`, `command`, `diff_content`, `added_count`, `removed_count`, `timestamp`
- `devices`: `device_id`, `name`, `hostname`, `platform`, `device_role`, `site`, `is_active`

## SQL writing rules

- Time filter: `created_at >= NOW() - INTERVAL :window`
- Exclude virtual interfaces:
  `interface NOT ILIKE 'Loopback%' AND interface NOT ILIKE 'Management%'`
- Never reference tables not confirmed by `database_introspection`.

## Authoring output requirements

After completion, report in the user's language:

1. Verified table/column names used
2. `test_map_query` result for each job (valid / error)
3. Profile file save path
