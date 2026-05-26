# Profile Authoring Reference

Load this reference when the user asks to **create / extend / retune** a
Profile (not *run* one).

## Authoring workflow (Create)

```
1. execute_sql(get_schema_context=True)
   → Learn real table/column names from the DB. Never guess.

2. test_map_query(job_type="sql", query=..., params={"window": "1h"})
   → Validate SQL syntax for each job. Zero rows is fine; errors are not.

3. create_profile_atomic(name=..., jobs=[ProfileJob, ...])
   → One-call: introspect + validate + write atomically.
   → Preferred for fresh profiles.
```

Alternatively, for step-by-step with user confirmation:
```
3. write_profile(name=..., jobs=[{...}], mode="create", markdown_body=...)
   → Show preview to user → wait for confirmation → write.
```

For data-driven thresholds: call `analyze_thresholds` between steps 2 and 3.

## The three authoring sub-modes

| Sub-mode | When to use | Key scripts |
|---|---|---|
| **Create** | User asks for a fresh profile | `execute_sql` → `test_map_query` → `create_profile_atomic` |
| **Retune** | Existing profile thresholds need updating | `load_profile(action='list')` → `load_profile(action='read')` → `analyze_thresholds` → `write_profile(mode='create')` |
| **Append** | Add new jobs to an existing profile | `load_profile(action='read')` → `test_map_query` → `write_profile(mode='append')` |

## Script reference (current names)

| Script | Purpose |
|---|---|
| `execute_sql` | Inspect DB schema (use `get_schema_context=True`) |
| `test_map_query` | Validate SQL/LanceDB query before writing to Profile |
| `analyze_thresholds` | Compute P50/P90/P95/P99 + recommend warning/critical thresholds |
| `load_profile` | `action='list'` → enumerate; `action='read'` → parse full profile |
| `list_profiles` | Terminal list operation — call once, present table, stop |
| `create_profile_atomic` | One-call: introspect + validate + write atomically |
| `write_profile` | `mode='create'` → overwrite; `mode='append'` → add jobs without touching existing |

## Authoring rules

- Skill infrastructure (SKILL.md, tool code, YAML keys, SQL) is always in English.
- Conversational output and `section_prompt` values match the user's request language.
- Always use `INTERVAL :window` in SQL queries (engine handles parameterization as `$cutoff`).
- Use `analyze_thresholds` when the user requests data-driven thresholds.
- `write_profile(mode='create')` overwrites — always wait for user confirmation before calling.
- SQL must return columns `device, metric_value, metric_name, severity_hint`.

See `prompts/system.md` for the complete mode decision tree.
