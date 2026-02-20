---
# ============================================================
# OLAV Agent Configuration (v3.4)
# OLAVAgent reads this at startup. Edit here to add/remove SubAgents.
#
# Fields per subagent entry:
#   name         — identifier used by the orchestrator task tool (required)
#   description  — shown to orchestrator LLM for routing (required)
#   skills       — scan these skill dirs for @tool functions (required)
#   prompt       — path relative to .olav/skills/ (REQUIRED, must exist)
#   model        — optional LLM override; two forms:
#                    literal:  claude-opus-4-5
#                    env ref:  ${OLAV_INSPECTION_MODEL}   (resolved at startup)
#                  Omit to share the orchestrator's model (LLM_MODEL_NAME).
#   include_tools / exclude_tools — filter loaded tools by name (mutually exclusive)
#   interrupt_on — map of tool_name: true to require human approval (HITL)
# ============================================================

orchestrator:
  # Pure orchestrator — 0 direct tools, delegates everything via `task`
  prompt: olav-ops/prompts/system.md

subagents:
  - name: olav-ops
    description: >
      Handles all read/query operations: SQL queries against DuckDB,
      live CLI commands on network devices, knowledge base search,
      and data export. Use for device lookups, show commands, reporting.
    skills: [olav-ops]
    prompt: olav-ops/prompts/network_ops_subagent.md

  - name: network-inspection
    description: >
      Runs network health inspections: SSH snapshot collection, config sync,
      health scoring and anomaly detection. Use for health checks,
      config comparison, snapshot collection, and inspection reports.
    skills: [network-inspection]
    prompt: network-inspection/prompts/system.md

  - name: olav-config
    description: >
      基础设施层（Infrastructure Layer）。负责 DB 初始化、设备清单同步、SSH 数据采集（take_snapshot）、
      TextFSM 模板刷新、Cron 调度管理。嵌入 DuckDB 的唯一写入方（parsed_outputs/devices）。
      直接调用 Python 函数，不通过 uv run olav 子进程。写操作和 SSH 采集需要人工确认。
    skills: [olav-config]
    prompt: olav-config/prompts/system.md
    interrupt_on:
      execute_shell: true
      write_file: true
      take_snapshot: true
      manage_inspection_schedule: true

  - name: olav-audit
    description: >
      治理层（Governance Layer）。读取 olav-config 采集的数据，执行配置驱动的合规、健康、一致性检查。
      不写 parsed_outputs（只读 DB）。支持 raw_contains/raw_not_contains 规则读取原始文件。
      分析结果写入 audit_results 表，生成 Markdown 报告。
    skills: [olav-audit]
    prompt: olav-audit/prompts/system.md
---

# OLAV Project Context

## Overview
OLAV is a network operations assistant that answers natural language questions about network devices, topology, protocol state, and performs fault analysis. It combines a DuckDB database (ground truth), live CLI access, a knowledge base, and web search.

## Architecture (v3.4)
- **Framework**: DeepAgents (`create_deep_agent` + SubAgents)
- **Pattern**: OLAVAgent is a pure orchestrator — 0 direct tools, all work delegated to SubAgents
- **Registration**: All SubAgents defined in this file's YAML frontmatter
- **HITL**: `olav-config` SubAgent requires human approval for write/execute operations
- **Cache**: Shared SQLiteCache at `.olav/databases/llm_cache.db`

## SubAgents (1 per Skill)

| SubAgent | Skill | HITL Tools |
|----------|-------|------------|
| `olav-ops` | `olav-ops` | — |
| `olav-config` | `olav-config` | execute_shell, write_file, take_snapshot, manage_inspection_schedule |
| `olav-audit` | `olav-audit` | — |

## Skills

| Skill | Role | Tools |
|-------|------|-------|
| `olav-ops` | 查询/CLI | execute_sql, execute_cli, search_knowledge, format_and_export |
| `olav-config` | 基础设施（写入层） | sync_schemas, sync_inventory, sync_commands, take_snapshot, manage_inspection_schedule, read_file, write_file, execute_shell, kb_manager, web_search |
| `olav-audit` | 治理（只读层） | run_audit, list_audits, validate_audit_config, create_audit_config, schema_inspector |

## Database
Path: `.olav/databases/main.duckdb`
Tables: `devices`, `parsed_outputs`, `topology_links`, `indexed_files`, `knowledge_chunks`
Devices: R1–R4 (border/core routers), SW1–SW2 (access switches), all cisco_ios, site=lab

## User Preferences
- Output format: Markdown tables (Rich for TTY, plain Markdown for pipe)
- Language: Chinese for interaction, English for code and file names

## Device Aliases
<!-- OLAVAgent maintains device alias mappings in DuckDBStore -->
