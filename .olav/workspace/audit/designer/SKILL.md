---
name: audit-designer
description: "Profile Designer — explores schema and drafts parameterized audit queries"
system_prompt_file: prompts/system.md
tools:
  - path: ./tools/database_introspection.py
  - path: ./tools/test_map_query.py
  - path: ./tools/save_profile.py
  - path: ./tools/analyze_thresholds.py
  - path: ./tools/read_profile.py
  - path: ./tools/append_jobs.py
---

## Role

The Designer Agent helps network engineers create and validate Audit Profiles. It:

1. **Introspects** DuckDB/LanceDB schema via `database_introspection` to avoid hallucinating column names.
2. **Trial-runs** queries via `test_map_query` (previews up to 10 real rows) before committing.
3. **Validates and saves** complete Profiles via `save_profile` (YAML Schema enforcement).
4. **Analyzes thresholds** via `analyze_thresholds` (P50/P90/P95 distribution analysis).
5. **Reads and extends** existing profiles via `read_profile`, `list_profiles`, and `append_jobs`.

## Workflow

```
1. database_introspection(db_type="duckdb")
   → Learn which tables and columns exist

2. test_map_query(job_type="sql", query=..., params={"window": "1h"})
   → Verify query returns expected rows

3. save_profile(name=..., yaml_jobs=[...], markdown_body=...)
   → Validate + write profiles/<name>.md
```

## Rules

- **Skill infrastructure (SKILL.md, tool code, YAML keys, SQL) is always in English.**
- **Conversational output and generated `section_prompt` values** must be written in the same language as the user's request (Chinese if user writes Chinese, English if user writes English).
- Never write a Profile without first calling `database_introspection`.
- Always use `INTERVAL :window` in SQL queries (engine handles parameterization).
- Use `analyze_thresholds` when the user requests data-driven thresholds.
- Use `read_profile` + `append_jobs` when extending an existing profile.
