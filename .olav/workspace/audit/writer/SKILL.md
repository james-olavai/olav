---
name: audit-writer
description: "Rule Writer — Translates user intent into YAML audit configurations with file system write access"
metadata:
  version: 1.0.0
  author: Network AI Team
  type: agent
  category: network-audit
  intent: rule_definition
permission:
  filesystem_write: true  # Can write audit YAML files
tools:
  - list_audits               # Dedicated: List available audit configs
  - validate_audit_config     # Dedicated: Validate YAML with Pydantic
  - create_audit_config       # Dedicated: LLM writes audit YAML from intent
  - write_file                # Dedicated: Write audit YAML files to config/
system: $ref:./prompts/system.md
static_context:
  - path: ./references/AUDIT_DSL_REFERENCE.md
---

## Overview

The Rule Writer translates user intent ("Ensure all edge ports have BPDU guard") into YAML audit configurations.

## Use Cases

1. **Intent Translation**: Convert natural language to audit rules
2. **Config Creation**: Generate valid YAML audit configurations
3. **Config Validation**: Validate audit YAML with Pydantic
4. **Config Management**: List, create, update audit configs

## Workflow

1. User expresses audit intent (e.g., "Check all routers have NTP configured")
2. Use `create_audit_config` to generate YAML from intent
3. Use `validate_audit_config` to verify the config
4. Use `write_file` to save to `config/AUDIT_<name>.yaml`

## Audit Types

- **health_check**: CPU, memory, interface health monitoring
- **consistency**: Cross-device consistency (VLANs, routing, neighbors)
- **compliance**: Configuration compliance (descriptions, naming, security)
- **custom**: User-defined audit with any supported targets
