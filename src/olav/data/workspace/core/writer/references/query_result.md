# Report Type: query_result

## When to use
Tag: `report_type: query_result`
Input: any SQL query result — generic tabular data (not specifically devices or topology).

## Format Rules

1. Output a **Markdown table** with ALL rows — never summarize.
2. Column headers from the query field names.
3. End with: **"共 N 条记录"**
4. If rows > 50: show first 20 + note total + export CSV.
5. If the data contains JSON fields (e.g. `parsed_data`), show a readable summary per row, not raw JSON.
6. Always export raw data as CSV: `format_and_export(data=<json>, format="csv")`.

## Example Output

```markdown
| device_name | command | parsed_data_summary | collected_at |
|---|---|---|---|
| R1 | show bgp summary | 3 neighbors, all Established | 2026-04-16 |
| R2 | show bgp summary | 2 neighbors, 1 Active | 2026-04-16 |

共 2 条记录

📁 Full data: exports/query_result.csv
```

## Export
Always export CSV alongside the Markdown table.
