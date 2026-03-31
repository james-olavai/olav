---
name: core
description: "Core platform tools — available globally in all agents and workspaces."
tools:
  - run_python_code          # run_python_code.py — Execute arbitrary Python in isolated subprocess
  - recall_memory            # recall_memory.py   — Semantic memory recall (LanceDB)
  - web_search               # web_search.py      — DuckDuckGo web search
metadata:
  version: 1.0.0
  type: core
  category: platform
---

# Core Workspace

These tools are globally available to all agents regardless of active workspace.
They provide general-purpose capabilities that any agent may need.

## run_python_code

Execute arbitrary Python code in an isolated subprocess. Use this to:
- Run docker/docker-compose commands
- Call REST APIs via httpx/requests
- Write and read files
- Run any CLI tool (git, curl, olav, etc.)
- Process data with any installed Python package

## recall_memory

Recall information from semantic memory (LanceDB vector store).

## web_search

Search the web via DuckDuckGo for external documentation, examples, or information.
