---
name: network-analysis
version: 1.0.0
description: Network health analysis, anomaly detection, performance baseline analysis, and trend detection. Identifies deviations from normal behavior and provides optimization recommendations.
author: Network AI Team
type: agent
category: network-analysis
intent: health_analysis

tools:
  - query_database
  - nornir_execute
  - list_devices

prompts:
  system: $ref:./prompts/system.md

analysis_workflow:
  step_1: "Scope Definition - Identify devices, protocols, or systems to analyze"
  step_2: "Baseline Query - Get historical baseline metrics"
  step_3: "Current State - Compare with real-time data"
  step_4: "Anomaly Calculation - Identify deviations from thresholds"
  step_5: "Verification - Use CLI commands to confirm findings"
  step_6: "Recommendations - Suggest adjustments or improvements"

failure_path: |
  If analysis requires cross-device correlation or topology awareness:
  → Inform orchestrator to upgrade to Expert.

standard_queries:
  device_health_baseline: |
    SELECT hostname, ROUND(AVG(cpu_percent), 2) as avg_cpu, 
           ROUND(AVG(memory_percent), 2) as avg_mem
    FROM system_metrics
    WHERE created_at > NOW() - INTERVAL 7 DAYS
    GROUP BY hostname

  interface_error_trends: |
    SELECT device, interface, ROUND(SUM(in_errors)::numeric, 2) as total_errors
    FROM interface_stats
    WHERE created_at > NOW() - INTERVAL 24 HOURS
    GROUP BY device, interface
    ORDER BY total_errors DESC

  protocol_state_stability: |
    SELECT protocol, COUNT(*) as state_changes
    FROM protocol_events
    WHERE created_at > NOW() - INTERVAL 7 DAYS
    GROUP BY protocol
    HAVING COUNT(*) > 0

tags:
  - network-analysis
  - health-diagnostics
  - anomaly-detection
  - performance
---

## Quick Start: Analysis Workflow

1. **Scope Definition**: Devices, protocols, or systems
2. **Baseline Query**: Historical metrics
3. **Current State**: Real-time data
4. **Anomaly Calculation**: Compare against thresholds
5. **Verification**: CLI confirmation
6. **Recommendations**: Suggested improvements
