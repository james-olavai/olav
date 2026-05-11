# Profile Authoring Mode (merged from v0.18.0 audit-designer)

Load this reference when the user asks to **create / extend / retune** a
Profile (not *run* one). The default Audit Executor workflow (Steps 1–4
in SKILL.md) does not apply — follow the authoring workflow below
instead.

## Authoring workflow

```
1. database_introspection(db_type="duckdb")
   → Learn real table/column names. Never guess.

2. test_map_query(job_type="sql", query=..., params={"window": "1h"})
   → Validate SQL syntax for each job. Zero rows is fine; errors are not.

3. save_profile(name=..., yaml_jobs=[...], markdown_body=...)
   → Validate + write profiles/<name>.md after schema validation passes.
```

For data-driven thresholds: call `analyze_thresholds` between steps 2 and 3.
For extending an existing profile: use `read_profile` + `append_jobs`
instead of `save_profile`.

## Authoring rules

- Skill infrastructure (SKILL.md, tool code, YAML keys, SQL) is always in
  English.
- Conversational output and generated `section_prompt` values are written
  in the same language as the user's request.
- Never write a Profile without first calling `database_introspection`.
- Always use `INTERVAL :window` in SQL queries (engine handles
  parameterization).
- Use `analyze_thresholds` when the user requests data-driven thresholds.
- Use `read_profile` + `append_jobs` when extending an existing profile.

## The three authoring sub-modes

| Sub-mode | When to use | Key tools |
|---|---|---|
| **Intelligent Threshold** | User asks for a fresh profile with "smart" thresholds based on past observations | `database_introspection` → `analyze_thresholds` → `save_profile` |
| **Dynamic Retuning** | Existing profile produces too many false positives or misses known incidents | `read_profile` → `analyze_thresholds` → `save_profile` (overwrite) |
| **Append Jobs** | User wants to add new jobs to an existing profile without touching old ones | `read_profile` → compose new jobs → `append_jobs` |

See `prompts/system.md` "Profile Authoring Mode" section for the full
three-mode decision tree and example prompts.
