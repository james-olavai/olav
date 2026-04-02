---
name: quick-orchestrator
description: "Quick Query Agent — Fast SQL/CLI lookup with max_iterations=1"
system_prompt_file: prompts/system.md
subagents: []
static_context:
  - path: ./references/SCHEMA_REFERENCE.md
---

## Overview

The Quick Agent is the default entry point for OLAV. It bypasses complex ReAct loops for speed.

## Delegation

This agent loads skills directly without subagents:
- ./SKILL.md — Quick Query skill with dedicated tools
