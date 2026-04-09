---
name: config-system
description: "System Doctor — Health checks, log analysis, cron management, and workspace audit"
metadata:
  version: 2.0.0
  author: Network AI Team
  type: agent
  category: system-management
  intent: system_health_cron_management
tools:
  - check_health             # Dedicated: System health checker with recommendations
  - analyze_logs             # Dedicated: Query execution history for self-learning/audit
  - audit_workspace          # Dedicated: Audit workspace for syntax errors, @tool collisions, SKILL.md drift, missing prompts, broken static_context refs
system: $ref:./prompts/system.md
---

## Overview

The System Subagent handles platform health, log analysis, cron scheduling,
and workspace self-healing. Coding and API onboarding is handled by the
`devops` agent (`olav --agent devops`).

## Use Cases

### Doctor / Self-Healing
1. **Health Check**: Diagnose OLAV (DuckDB locks, missing skills, cron status)
2. **Log Analysis**: Query execution history for self-learning and audit
3. **Workspace Audit**: Detect broken tool references, SKILL.md drift, orphaned files
4. **Cron Management**: Add, update, and remove scheduled olav tasks

## Workflow

1. **Input**: User describes a health concern, log query, or scheduling request
2. **Diagnose**: Run `check_health` or `analyze_logs` to gather data
3. **Report**: Return structured results with issue severity and fix recommendations
4. **Schedule**: Manage cron jobs via dedicated cron tools (never run_shell/crontab directly)

