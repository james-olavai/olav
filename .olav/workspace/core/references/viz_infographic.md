# Infographic / KPI Card Templates — Quick Reference

Use for score-card, KPI dashboard, and timeline visualizations. Load only when needed.

## Score Card (YAML format)

```yaml
type: scorecard
title: "Network Health Summary"
generated_at: "2026-04-12"
kpis:
  - label: "BGP Sessions Up"
    value: 14
    total: 16
    status: warning      # ok / warning / critical
    trend: up            # up / down / stable
  - label: "Interface Errors (24h)"
    value: 3
    unit: ""
    status: ok
    trend: stable
  - label: "Avg Latency"
    value: 12.4
    unit: "ms"
    status: ok
    trend: down
```

## Timeline Card

```yaml
type: timeline
title: "Recent Changes"
events:
  - timestamp: "2026-04-12T08:00:00Z"
    event: "BGP session R1→R2 went down"
    severity: critical
  - timestamp: "2026-04-12T08:15:00Z"
    event: "BGP session R1→R2 restored"
    severity: ok
  - timestamp: "2026-04-12T09:00:00Z"
    event: "Snapshot collected — 16 devices"
    severity: info
```

## Table Card

```yaml
type: table
title: "Top 5 Devices by Interface Errors"
columns: ["Device", "Errors", "Status"]
rows:
  - ["R3", 142, "⚠️ Warning"]
  - ["SW4", 87, "⚠️ Warning"]
  - ["R1", 0, "✅ OK"]
  - ["R2", 0, "✅ OK"]
  - ["SW1", 0, "✅ OK"]
```

## Gauge Card

```yaml
type: gauge
title: "Reachability Score"
value: 87.5
unit: "%"
min: 0
max: 100
thresholds:
  critical: 60
  warning: 80
  ok: 90
```

## Rendering

Infographic YAML is:
1. Wrapped in ` ```infographic ` fenced code blocks in Markdown reports
2. Or exported as a standalone file: `format_and_export(content=yaml_str, format="infographic")`

The OLAV frontend renders these blocks as interactive cards. In plain terminal output, the YAML is displayed as-is and remains human-readable.

## Best Practices

- Keep KPI labels short (< 30 chars) for clean rendering
- Always include `status` field for colour coding
- Use `trend` only when you have comparative data (current vs previous period)
- Combine score-card + table + timeline for a complete dashboard section
