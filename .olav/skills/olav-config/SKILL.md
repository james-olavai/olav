---
name: olav-config
description: "OLAV infrastructure layer — DB init, device sync, SSH snapshot, template sync, cron scheduling. Calls Python functions directly."
metadata:
  version: 2.2.0
  author: Network AI Team
  type: agent
  category: system-administration
  capabilities:
    - DB init and schema management (sync_schemas)
    - Device inventory sync hosts.yaml → DuckDB (sync_inventory)
    - SSH data collection Map phase (take_snapshot)
    - TextFSM template sync (sync_commands)
    - Cron scheduling, snapshot and any job (manage_cron)
    - Full workspace read/write (write_file with HITL)
    - Execute shell commands (execute_shell with HITL)
    - Create and modify skills, fix bugs
  philosophy:
    - "Code as tool — call Python functions directly, no uv run olav wrappers"
    - "HITL for safety — write ops and shell execution require human confirmation"
    - "Collection layer — write to DB only, no rule evaluation (that is olav-audit)"
  tools:
    - read_file                # read_file.py
    - write_file               # write_file.py
    - execute_shell            # execute_shell.py
    - web_search               # web_search.py
    - index_knowledge_files    # index_knowledge_files.py — index .md/.pdf files into KB vector store
    - search_knowledge         # search_knowledge.py — semantic KB search with threshold filter
    - get_knowledge_status     # get_knowledge_status.py — KB index health + chunk stats
    - sync_schemas             # sync_schemas.py — create/migrate DuckDB table schemas
    - sync_inventory           # sync_inventory.py — hosts.yaml → devices table
    - take_snapshot            # take_snapshot.py — SSH collect → parsed_outputs + raw files
    - sync_commands            # sync_commands.py — scan templates → commands + schema_catalog
    - sync_all                 # sync_tools.py — full pipeline: inventory+snapshot+commands in one call
    - diff_configs             # sync_tools.py — show config diff between two dates for a device
    - manage_cron              # manage_cron.py — schedule/unschedule Cron jobs
    - get_current_datetime     # get_current_datetime.py
    # kb_manager.py — internal helper (no @tool), used by olav-config KB tools
  config:
    knowledge:
      knowledge_dir: .olav/knowledge/
      db_path: .olav/db/olav.duckdb
      search_limit: 5
      search_threshold: 0.0
      chunk_size: 1024
      chunk_overlap: 128
  permission_model:
    green:
      - read_file
      - sync_schemas
      - sync_inventory
      - sync_commands
    yellow:
      - write_file
      - execute_shell
      - take_snapshot
      - manage_cron
    forbidden:
      - system account modifications
      - credential deletion
  prompts:
    system: $ref:./prompts/system.md
  tags:
    - system-administration
    - customization
    - diy
    - codebase-access
    - monitoring
    - backup
    - scheduling
    - inspection
    - network-health
  created_at: "2026-02-08"
  updated_at: "2026-02-20"
---
