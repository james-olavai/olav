---
name: config-system
description: "System Doctor & Skill Builder — Self-healing, log analysis, and external system onboarding"
metadata:
  version: 1.0.0
  author: Network AI Team
  type: agent
  category: system-integration
  intent: system_health_external_system_onboarding
tools:
  - check_health             # Dedicated: System health checker with recommendations
  - analyze_logs             # Dedicated: Query execution history for self-learning/audit
  - read_api_schema          # Dedicated: Read and parse API schema files (OpenAPI/WSDL)
  - write_skill_code         # Dedicated: Generate Python skill code from analyzed schema
  - generate_skill_config    # Dedicated: Create SKILL.md from API schema
  - audit_workspace          # Dedicated: Audit workspace for syntax errors, @tool collisions, SKILL.md drift, missing prompts, broken static_context refs
system: $ref:./prompts/system.md
---

## Overview

The System Subagent handles self-healing, log analysis, and external system onboarding.

## Use Cases

### Doctor / Self-Healing
1. **Health Check**: Diagnose OLAV (DuckDB locks, missing skills, cron status)
2. **Log Analysis**: Query execution history for self-learning and audit
3. **Recommendations**: Provide fix suggestions for common issues

### Skill Builder
1. **NetBox Integration**: Auto-generate skill from NetBox API
2. **ServiceNow Integration**: Create skill for ITSM workflows
3. **Custom API Integration**: Support any REST/OpenAPI API
4. **WSDL Support**: Generate skills from SOAP/WSDL definitions

## Workflow

1. **Input**: User provides API schema (OpenAPI.yaml, WSDL, or URL)
2. **Analyze**: Parse schema to identify endpoints, authentication, data models
3. **Generate**: Create skill code with proper tool wrappers
4. **Configure**: Generate SKILL.md with metadata and tool definitions
5. **Test**: Verify the generated skill works correctly
