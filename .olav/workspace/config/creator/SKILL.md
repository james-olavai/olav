---
name: config-creator
description: "Skill Creator — Automating new external system onboarding, API integration, and skill deployment"
metadata:
  version: 1.0.0
  author: Network AI Team
  type: agent
  category: system-integration
  intent: skill_deployment_external_system_onboarding
tools:
  - read_api_schema          # Dedicated: Read and parse API schema files (OpenAPI/Swagger, WSDL)
  - write_skill_code         # Dedicated: Generate Python skill code from analyzed API schema
  - generate_skill_config    # Dedicated: Create SKILL.md configuration from API schema
  - read_file                # Dedicated: Read existing skill files for reference
  - write_file               # Dedicated: Write generated skill files to .olav/skills/
system: $ref:./prompts/system.md
---

## Overview

The Skill Creator automates the process of integrating external systems into OLAV by analyzing API schemas and generating ready-to-use skill code.

## Use Cases

1. **NetBox Integration**: Auto-generate skill from NetBox API
2. **ServiceNow Integration**: Create skill for ITSM workflows
3. **Custom API Integration**: Support any REST/OpenAPI API
4. **WSDL Support**: Generate skills from SOAP/WSDL definitions
5. **New Skill Deployment**: Package and deploy custom skills

## Workflow

1. **Input**: User provides API schema (OpenAPI.yaml, WSDL, or API documentation URL)
2. **Analyze**: Parse schema to identify endpoints, authentication, data models
3. **Generate**: Create skill code with proper tool wrappers
4. **Configure**: Generate SKILL.md with metadata and tool definitions
5. **Write**: Write all files to `.olav/skills/<skill-name>/`
6. **Register**: Add skill to OLAV configuration

## Tools

### read_api_schema
Read and parse API schema files to understand the API structure.
- Supports OpenAPI/Swagger (JSON/YAML)
- Supports WSDL for SOAP APIs
- Extracts endpoints, authentication, data models

### write_skill_code
Generate Python skill code from analyzed API schema.
- Creates tool wrappers for each endpoint
- Handles authentication automatically
- Follows OLAV skill patterns

### generate_skill_config
Create SKILL.md configuration from API schema.
- Generates metadata (name, description, version)
- Lists available tools
- Defines database schemas

## Integration Examples

### NetBox
```python
# Read NetBox OpenAPI spec
schema = read_api_schema(source="netbox.yaml")

# Generate skill
skill = write_skill_code(schema=schema, template="network_inventory")

# Output: complete skill in .olav/skills/netbox/
```

### ServiceNow
```python
# Read ServiceNow REST API schema
schema = read_api_schema(source="servicenow.yaml")

# Generate skill
skill = write_skill_code(schema=schema, template="itsm_workflow")
```
