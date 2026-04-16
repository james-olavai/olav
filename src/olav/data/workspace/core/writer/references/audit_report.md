# Report Type: audit_report

## When to use
Tag: `report_type: audit_report`
Input: Either (a) a report file path, or (b) audit findings JSON from map_engine.

## Format Rules

### If input is a file path:
1. Call `read_file` to load the report content.
2. Extract the `## Executive Summary` section (content until next `##` or `---`).
3. Extract the health verdict emoji: 🔴 Critical / ⚠️ At Risk / ✅ Healthy.
4. Display structured output (see example below).

### If input is audit findings JSON:
1. Parse the JSON findings.
2. Generate a summary table: | Check | Status | Finding |
3. Count: critical / warning / healthy findings.
4. Generate Executive Summary with overall verdict.
5. Call `format_and_export(data=<report_md>, format="md", subdir="reports", filename="audit_report")`.

## Example Output

```markdown
## Executive Summary

Overall health: ✅ **Healthy**

| Metric | Status | Detail |
|---|---|---|
| BGP Neighbors | ✅ Healthy | All 4 sessions Established |
| Interface Errors | ⚠️ Warning | R2 Gi1: 12 CRC errors/hr |
| CPU Utilization | ✅ Healthy | All devices < 60% |

**Verdict:** 2 healthy, 1 warning, 0 critical

📁 Full report: exports/reports/audit_report.md
```

## Export
Always call `format_and_export` with the full Markdown report and `format="md"`, `subdir="reports"`.
