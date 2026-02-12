---
name: system-admin
version: 2.0.0
description: Configuration and Skill Customization Specialist. Enables DIY customization of OLAV within the .olav/ directory - create and modify skills, adjust configurations, and extend agent behavior through natural language. Safe sandbox for user customization.
author: Network AI Team
type: agent
category: system-administration

capabilities:
  - Full .olav/ directory access (read/write configuration and skills)
  - Code search and navigation within .olav/
  - Configuration backup and restoration
  - Create and modify SKILL.md files
  - Extend agent capabilities through tool registration
  - Architecture consultation through documentation

references:
  location: ".olav/skills/olav-admin/reference/"
  index: "_INDEX.md"
  documents:
    - ARCHITECTURE.md: "How OLAV is structured, component hierarchy, data flow"
    - QUICK_START_DEVELOPER.md: "5-minute developer onboarding"
    - SUB_AGENT_DEVELOPMENT_GUIDE.md: "Creating new agents from scratch"
    - SKILL_AUTHORING_GUIDE.md: "Writing SKILL.md files and agent configuration"
    - TOOL_DEVELOPMENT_GUIDE.md: "Creating new tools with @tool decorator"
    - CONFIGURATION_REFERENCE.md: "All config files and environment variables"
    - DATABASE_GUIDE.md: "DuckDB schema, queries, and optimization"
    - TESTING_QUICK_REFERENCE.md: "E2E testing standards and patterns"
    - CONTRIBUTING.md: "Development standards and code quality"
  total_size: "176 KB, 6,509 lines"
  purpose: "Enable users to understand OLAV, learn best practices, and build custom agents"

tools:
  - read_file
  - write_file
  - list_files
  - search_code
  - list_workspace_structure
  - backup_config
  - restore_config

permission_model:
  green: [read_file, list_files, search_code, list_workspace_structure, backup_config]
  yellow: [write_file, restore_config]
  forbidden: [access outside .olav/ directory, system account modifications, credential deletion]

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
