---
name: config-creator
description: "Skill Creator — Autonomously onboards external APIs by discovering schemas, generating platform-native tools, and deploying workspaces"
metadata:
  version: 2.0.0
  author: Network AI Team
  type: agent
  category: system-integration
  intent: skill_deployment_external_system_onboarding
tools:
  - list_platform_services     # Discover what services are already registered
  - read_api_schema            # Fetch and parse an OpenAPI schema from URL or file
  - create_service_config      # Write a new service entry to services.yaml
  - register_api_service       # Trigger platform tool generation via tool_generator pipeline
  - create_skill_workspace     # Create workspace dir + SKILL.md, register in PLATFORM.md
  - read_file                  # Read any file for reference or verification
  - write_file                 # Write custom files (prompts, docs, configs)
system: $ref:./prompts/system.md
---

## Overview

The Skill Creator autonomously onboards external APIs into OLAV.
It discovers API schemas, uses the platform's tool generation pipeline to produce
production-quality per-endpoint tools, and deploys a ready-to-use workspace —
all without hardcoding and without human intervention.

## Workflow

1. **Explore** — `list_platform_services()` → understand current state
2. **Analyze** — `read_api_schema(url)` → discover endpoints, tags, auth
3. **Configure** — `create_service_config(...)` → write services.yaml entry
4. **Generate** — `register_api_service(name)` → platform builds per-endpoint tools
5. **Deploy** — `create_skill_workspace(...)` → workspace + SKILL.md + PLATFORM.md
6. **Verify** — `read_file(generated_tool_path)` → confirm quality

## Design Principles

- **LLM-Native**: tag groups, auth type, workspace structure all inferred from schema semantics
- **No hardcoding**: tools are generic; LLM decides all service-specific parameters
- **Platform pipeline**: generated tools use `service_call()` — never write raw Python code
