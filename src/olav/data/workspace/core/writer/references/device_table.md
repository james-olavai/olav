# Report Type: device_table

## When to use
Tag: `report_type: device_table`
Input: SQL query result — list of device records (hostname, ip, platform, vendor, model, role, etc.)

## Format Rules

1. Output a **Markdown table** with ALL rows from the input data — never summarize or truncate.
2. Column headers must match the field names in the data (hostname, ip_address, platform, etc.)
3. Right-align numeric columns, left-align text columns.
4. End with: **"共 N 条记录"**
5. If rows > 50: show first 20 rows, add note "共 N 条记录，已截断显示前 20 条", then call `format_and_export(data=<full_json>, format="csv", filename="devices")` to export full CSV.
6. If rows ≤ 50: show all rows in Markdown table AND call `format_and_export(data=<full_json>, format="csv", filename="devices")`.

## Example Output

```markdown
| hostname | ip_address | platform | vendor | model | role |
|---|---|---|---|---|---|
| R1 | 192.168.100.101 | juniper_junos | Juniper | vSRX | border |
| R2 | 192.168.100.102 | cisco_ios | Cisco | ISRv | border |
| R3 | 192.168.100.103 | cisco_ios | Cisco | — | core |

共 3 条记录
```

## Export
Always call `format_and_export` with the raw JSON data and `format="csv"`.
