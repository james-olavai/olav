---
name: devops
description: "DevOps & Infrastructure orchestrator — automation script generation (bash/python/ansible) + infrastructure integrations (NetBox DCIM/IPAM, InfluxDB metrics) + bulk change scripts. Pure delegation; sub-agents own all write/query work."
system_prompt_file: prompts/orchestrator.md
route_keywords:
  - script bash python ansible automation backup bulk operation migrate generate code
  - 脚本 自动化 备份 批量
  - netbox dcim ipam influxdb metrics inventory bulk change
  - 网管 资源 库存
# Patch D' Step 2.5 (2026-05-08) pattern: orchestrator is pure
# delegation. No direct execute_sql, no write-class tools.
# Whitelist 2 low-risk reads only; everything else delegates.
tools:
  - recall_memory
  - web_search
subagents:
  - path: ./scripts/SKILL.md
  - path: ./infra/SKILL.md
---

# DevOps Orchestrator

R-AGENT-HIERARCHY Phase A (2026-05-09): merged from former
top-level `devops_scripts` + `devops_infra` agents.  Both were
spun out from the netops `ops` orchestrator on 2026-05-01 to
lighten that orchestrator's prompt; Patch D' (2026-05-08)
removed the prompt-bloat reason, so they're now nested under
this single domain orchestrator.

## Delegation table

| Request | First call |
|---|---|
| Bash / Python / Ansible script generation | `task("scripts", req)` |
| Backup / restore / migration / monitoring scripts | `task("scripts", req)` |
| Bulk multi-device operation script | `task("scripts", req)` |
| NetBox DCIM device / interface / circuit query | `task("infra", req)` |
| NetBox IPAM prefix / IP query | `task("infra", req)` |
| InfluxDB metric query (latency / health timeseries) | `task("infra", req)` |
| Bulk-change CSV / changeset generation from infra data | `task("infra", req)` |

## Boundary

* For `services/` deploy/stop/auth: tell user `olav --agent services "..."`
* For network device CLI / topology queries: tell user `olav --agent netops "..."`
