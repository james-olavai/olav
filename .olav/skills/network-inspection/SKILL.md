---
name: network-inspection
version: 2.2.0
description: Multi-layer network health inspection (L1-L4) with health scoring and markdown report generation. Detects anomalies, calculates health scores, and generates compliance-ready reports. Use for health checks, SLA validation, compliance monitoring, and production reporting.
author: Network AI Team
type: agent
category: network-analysis
intent: inspection

tools:
  - inspect_schema
  - query_database
  - discover_data

prompts:
  system: $ref:./prompts/system.md

inspection:
  layers:
    - name: L1_Physical
      description: Device health and basic status
      queries:
        - SELECT hostname, is_active, version FROM devices
        - SELECT device_name, MAX(created_at) as last_sync FROM parsed_outputs GROUP BY device_name
    - name: L2_Interfaces
      description: Interface status and error detection
      queries:
        - SELECT COUNT(*) as up_count FROM interfaces WHERE state = 'up'
    - name: L2_Neighbors
      description: Neighbor discovery (CDP/LLDP)
      queries:
        - SELECT COUNT(DISTINCT neighbor) as neighbor_count FROM neighbors
    - name: L3_Protocols
      description: Routing protocol states
      queries:
        - SELECT COUNT(*) as established FROM ospf_neighbors WHERE state = 'established'
    - name: L3_Routes
      description: Routing table completeness
      queries:
        - SELECT COUNT(*) as route_count FROM routes
    - name: L4_Performance
      description: CPU and memory utilization
      queries:
        - SELECT hostname, cpu_percent, memory_percent FROM system_metrics

scoring:
  max_score: 100
  critical_weight: 20
  warning_weight: 5
  thresholds:
    healthy: 90
    warning: 70
    critical: 0

tags:
  - network-inspection
  - health-check
  - compliance
  - reporting
---

## Three-Step Workflow

**Step 1: Schema Discovery**
- Call `inspect_schema()` to discover available tables
- Match discovered tables to layer templates (L1-L4)
- Determine what data is available for analysis

**Step 2: Health Analysis**
- Execute queries for each layer
- Calculate health score: `score = 100 - (critical * 20 + warning * 5)`
- Identify critical and warning issues

**Step 3: Report Generation**
- Generate markdown report with findings
- Include layer breakdown and recommendations
- Format results as structured data or markdown
