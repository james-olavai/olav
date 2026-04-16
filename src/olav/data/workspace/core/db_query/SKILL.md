---
name: db_query
description: "Database queries — complex multi-step DuckDB SQL workflows"
tools:
  - execute_sql
---

## Output Rules

1. When the user asks to **list / enumerate / 列出 / 显示所有**, display **ALL rows** returned — do not summarize, truncate, or show only representative examples.
2. Format tabular results as Markdown tables with column headers matching the query fields.
3. If result exceeds 50 rows, show first 20 rows and note: "共 N 条记录，已截断显示前 20 条".
4. Always include row count: "共 N 条记录".
5. Never paraphrase or condense multi-row results into prose when the user asked for a list.
