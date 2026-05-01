---
name: devops
kind: Agent
description: "DevOps automation — production-grade scripts (bash/python/ansible) using real device + service data from OLAV DB. Spun out from ops sub-agent → top-level (2026-05-01) to lighten ops orchestrator prompt."
version: "1.0.0"
system_prompt_file: prompts/system.md
route_keywords:
  - script
  - bash
  - python
  - ansible
  - automation
  - backup
  - bulk operation
  - migrate
  - generate code
  - 脚本
  - 自动化
  - 备份
  - 批量
static_context:
  - path: ./references/BASELINE_SCHEMA.md
  - path: ./references/OLAV_PLATFORM_HEALTH.md
  - path: ./references/schema_discovery_patterns.md
  - path: ./references/system_health_patterns.md
static_context_mode: on_intent
---

# DevOps Automation Agent

Top-level agent (was `ops/devops/` sub-agent, promoted 2026-05-01 per
conversation re-org).

## Capabilities

* Generate bash / python / ansible scripts using real device + service
  data from OLAV DB (no placeholder `10.0.0.1` / `CHANGEME`).
* Backup / restore / migration script templates.
* Bulk-ops scripts (multi-device parallel execution).
* Monitoring setup snippets.

## Workflow

See `prompts/system.md` for the full mandatory environment-discovery
flow before any script gets written.

## Cross-agent dependencies

* For service registry / API tokens: delegate to `services` agent
  via `olav_delegate(subagent_name="services", ...)`.
* For network topology data: read `netops.topology_links` directly
  via `execute_sql` (inherited core tool).
