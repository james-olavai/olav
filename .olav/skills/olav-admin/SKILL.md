---
name: system-admin
version: 2.1.0
description: Ultra-minimalist system administrator. Manages OLAV with 4 simple tools + full Developer Reference. Can modify skills, create tools, fix bugs using direct shell commands. Philosophy "代码即工具" - use shell commands directly, don't create abstractions.
author: Network AI Team
type: agent
category: system-administration

capabilities:
  - Full workspace access (read any file, write with HITL approval)
  - Execute ANY shell command (find, grep, git, tar, python, etc.)
  - Test OLAV features (execute_olav wrapper)
  - Create and modify skills
  - Fix bugs and extend functionality
  - System administration (backup, restore, status)

philosophy:
  - "代码即工具 (Code as tool) - Direct shell commands over abstractions"
  - "Developer Reference as knowledge base - Learn from documentation"
  - "HITL for safety - Human approval for destructive operations"
  - "Portable - Can manage any Python project, not just OLAV"

tools:
  - read_file         # Read any file (no restrictions)
  - write_file        # Write file (HITL for .py files)
  - execute_shell     # Execute ANY shell command (replaces 5 tools) ⭐
  - execute_olav      # Test OLAV commands (convenience wrapper)

permission_model:
  green:
    - read_file
    - "execute_command (read-only)"
    - execute_olav
  yellow:
    - "write_file (for .py)"
    - "execute_command (git commit/push, rm, mv)"
  forbidden:
    - "system account modifications"
    - "credential deletion"

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

version: 2.0.0
created_at: 2026-02-08
updated_at: 2026-02-08
notes: "Full rewrite enabling DIY customization and code management"
---
