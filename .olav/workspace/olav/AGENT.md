---
name: olav-main
description: "Main OLAV Agent — Network Operations Assistant"
system_prompt_file: prompts/system.md
skills:
  - path: ../skills/olav-ops
  - path: ../skills/olav-config
  - path: ../skills/olav-audit
---

## Overview

The main OLAV Agent handles general network operations queries using skills for operations, configuration, and audit.

## Skills

1. **olav-ops** — Query operations (execute_sql, execute_cli)
2. **olav-config** — Configuration management (sync, snapshot)
3. **olav-audit** — Audit and compliance
