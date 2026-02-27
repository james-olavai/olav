---
name: audit-orchestrator
description: "Audit & Compliance Agent — Rule generation and compliance checking"
system_prompt_file: prompts/orchestrator.md
subagents:
  - path: ./writer/SKILL.md
  - path: ./auditor/SKILL.md
---

## Overview

The Audit Agent handles rule generation and compliance checking. It decouples rule definition from rule execution.

## Subagents

1. **writer** — Rule Writer: Translates user intent into YAML audit configurations
2. **auditor** — Rule Executor: Runs audits and formats markdown reports
