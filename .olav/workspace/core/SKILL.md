---
name: core
description: "Core platform tools — available globally in all agents and workspaces."
tools:
  - run_python_code          # run_python_code.py — Pure-computation Python sandbox (no IO/shell)
  # recall_memory and web_search are provided by agent-specific tools/ dirs (ops, quick, config)
  # They are listed here for documentation; actual files resolved at agent runtime
static_context:
  - path: ./references/SKILL_DEVELOPMENT.md
metadata:
  version: 1.0.0
  type: core
  category: platform
---

# Core Workspace

These tools are globally available to all agents regardless of active workspace.
They provide general-purpose capabilities that any agent may need.

## run_python_code

Execute Python code for **pure computation**: data parsing, format conversion,
mathematical analysis, graph algorithms, JSON/YAML manipulation.

**Scope is intentionally limited to computation — not IO.** For anything beyond:
- Shell / docker commands → `run_shell` (declare in workspace SKILL.md to enable)
- Writing files → `write_workspace_file` (declare in workspace SKILL.md to enable)
- Service deployment → `deploy_service` (declare in workspace SKILL.md to enable)

IO capabilities are opt-in per workspace, not globally available.

## recall_memory

Recall information from semantic memory (LanceDB vector store).

## web_search

Search the web via DuckDuckGo for external documentation, examples, or information.
