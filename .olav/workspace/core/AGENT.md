---
name: core
kind: Agent
description: "Core OLAV platform agent — skill development, service registration, and platform operations"
version: "0.2.0"
system_prompt_file: prompts/system.md
static_context:
  - path: ./references/SKILL_DEVELOPMENT.md
---

# Core Workspace

Platform-level agent providing built-in capabilities.
Always present; cannot be uninstalled.

This agent helps users build and operate the OLAV platform itself — developing new skills,
registering external service APIs, and running arbitrary code to explore integrations.

## Built-in Tools

- `run_python_code` — Execute arbitrary Python in an isolated subprocess
- `recall_memory` — Semantic memory recall (LanceDB)
- `web_search` — DuckDuckGo web search
- `execute` — Shell tool injected by LocalShellBackend (native shell access)
