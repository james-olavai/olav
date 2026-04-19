# Report Type: diff_report

## When to use
Tag: `report_type: diff_report`
Input: drift detection results — JSON with missing/new/changed items between two snapshots.

## Format Rules

1. Start with **Summary** — what changed between snapshots, overall severity.
2. **Changes Table** — limit to 20 most significant changes:

| Type | Item | Before | After | Impact |
|---|---|---|---|---|
| REMOVED | R2 BGP neighbor 10.0.0.1 | Established | — | High |
| ADDED | SW2 VLAN 100 | — | active | Low |
| CHANGED | R1 ge-0/0/2 status | up | down | Critical |

3. **Impact Assessment** — 1-2 sentences on operational impact.
4. If >20 changes: show first 20, note total, export full diff as CSV.
5. Call `format_and_export` with both the Markdown report (`format="md"`) and the full data (`format="csv"`).

## Example Output

```markdown
## Drift Report: snap_20260416 vs snap_20260415

**Summary:** 3 changes detected. 1 critical (interface down), 1 high (BGP lost), 1 low (VLAN added).

| Type | Item | Before | After | Impact |
|---|---|---|---|---|
| CHANGED | R1 ge-0/0/2 status | up | down | 🔴 Critical |
| REMOVED | R2 BGP 10.0.0.1 | Established | — | 🟡 High |
| ADDED | SW2 VLAN 100 | — | active | 🟢 Low |

**Impact:** R1 ge-0/0/2 down affects R1↔R3 link. BGP session loss on R2 may indicate upstream issue.

共 3 条变更
```

## Export
Call `format_and_export` for both MD report and CSV full data.
