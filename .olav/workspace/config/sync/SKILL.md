---
name: config-sync
description: "Snapshot & Sync — Device sync, SSH data collection, TextFSM templates, cron scheduling"
metadata:
  version: 2.2.0
  author: Network AI Team
  type: agent
  category: system-administration
interrupt_on:
  execute_shell: true
  write_file: true
  take_snapshot: true
  manage_cron: true
capabilities:
  - DB init and schema management (sync_schemas)
  - Device inventory sync hosts.yaml → DuckDB (sync_inventory)
  - SSH data collection Map phase (take_snapshot)
  - TextFSM template sync (sync_commands)
  - Cron scheduling (manage_cron)
  - Full workspace read/write (write_file with HITL)
  - Execute shell commands (execute_shell with HITL)
philosophy:
  - "Code as tool — call Python functions directly"
  - "HITL for safety — write ops and shell execution require human confirmation"
  - "Collection layer — write to DB only, no rule evaluation"
tools:
  - read_file                # Dedicated: Read files
  - write_file               # Dedicated: Write files (with HITL)
  - execute_shell            # Dedicated: Execute shell commands (with HITL)
  - sync_schemas             # Dedicated: Create/migrate DuckDB table schemas
  - sync_inventory           # Dedicated: hosts.yaml → devices table
  - take_snapshot            # Dedicated: SSH collect → parsed_outputs + raw files
  - sync_commands            # Dedicated: Scan templates → commands + schema_catalog
  - sync_all                 # Dedicated: Full pipeline: inventory+snapshot+commands
  - reparse_outputs          # Dedicated: Re-parse local raw files with new templates (no SSH)
  - diff_configs             # Dedicated: Show config diff between two dates
  - manage_cron              # Dedicated: Schedule/unschedule Cron jobs
  - get_current_datetime     # Dedicated: Get current datetime
  - analyze_logs             # Dedicated: Query execution history for audit
  - check_health             # Dedicated: System health checker
system: $ref:./prompts/system.md
---

## Overview

The Sync Subagent handles device synchronization, SSH data collection, and template management.

## Tools

### Data Sync
- `sync_schemas`: Create/migrate DuckDB table schemas
- `sync_inventory`: Sync hosts.yaml → devices table
- `sync_commands`: Scan templates → commands + schema_catalog
- `sync_all`: Full pipeline (inventory+snapshot+commands)

### Data Collection
- `take_snapshot`: SSH collect → parsed_outputs + raw files
- `reparse_outputs`: Re-parse local raw files with new templates (no SSH required)
- `diff_configs`: Show config diff between two dates

### System Operations
- `manage_cron`: Schedule/unschedule Cron jobs
- `execute_shell`: Execute shell commands (with HITL)
- `analyze_logs`: Query execution history
- `check_health`: System health checker

## Permission Model

- **Green** (no approval): read_file, sync_schemas, sync_inventory, sync_commands, analyze_logs, check_health
- **Yellow** (HITL required): write_file, execute_shell, take_snapshot, manage_cron
- **Forbidden**: System account modifications, credential deletion
