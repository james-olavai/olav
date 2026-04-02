---
name: config-learner
description: "Command Learner — Interactive TextFSM template generation with user approval workflow"
metadata:
  version: 1.1.0
  author: Network AI Team
  type: agent
  category: command_learning
  prompts:
    system: $ref:./prompts/system.md
    generation: $ref:./references/textfsm_generation.md
    analysis: $ref:./references/textfsm_analysis.md
config:
  success_threshold: 0.8
  max_iterations: 3
  auto_approve_fields: false
  approval_timeout: 300
  template_dir: .olav/templates/custom
  cache_db: .olav/cache/semantic_cache.db
  use_ntc_references: true
  caching:
    enable_template_cache: true
    memory_cache_size: 100
    db_cache_enabled: true
    similarity_threshold: 0.85
    cache_ttl_days: 30
workflow:
  steps:
    - name: "Execute Command"
      step_number: 1
      timeout: 30
    - name: "Analyze Fields"
      step_number: 2
      timeout: 60
    - name: "User Approval"
      step_number: 3
      timeout: 300
      interactive: true
    - name: "Fetch NTC References"
      step_number: 4
      timeout: 30
      optional: true
      tool: "ntc_search"
    - name: "Generate Template"
      step_number: 5
      timeout: 120
      max_iterations: 3
    - name: "Save Template"
      step_number: 6
      timeout: 10
tools:
  - execute_command         # Dedicated: Execute command on target device
  - analyze_output          # Dedicated: Analyze command output fields
  - browse_ntc_directory   # Dedicated: Browse local NTC templates
  - search_ntc_templates   # Dedicated: Search NTC templates by platform/command
  - generate_template       # Dedicated: Generate TextFSM template
  - read_template_file     # Dedicated: Read template file
  - save_template          # Dedicated: Save template to disk
  - repair_template        # Dedicated: Zero-touch template auto-repair (Stage 5 self-healing)
system: $ref:./prompts/system.md
static_context:
  - path: ./references/TEXTFSM_BEST_PRACTICES.md
---

## Overview

The Command Learner provides a complete workflow for learning new network device commands and automatically generating accurate TextFSM templates.

## 6-Step Workflow

1. **Execute Command**: Run command on target host
2. **Analyze Fields**: LLM analyzes output fields
3. **User Approval**: Interactive field review/modification
4. **Fetch NTC References**: Search local NTC templates
5. **Generate Template**: ReAct-based template generation
6. **Save Template**: Save with metadata

## NTC-Templates Integration

- Searches local `ntc-templates` pip package
- No internet requirement
- Platform and command keyword matching
- Field coverage scoring
