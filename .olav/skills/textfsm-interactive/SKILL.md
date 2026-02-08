---
name: TextFSM Interactive Agent
version: 1.0.0
author: Network AI Team
description: Interactive TextFSM template generation with user approval workflow
type: agent
category: textfsm

# Configuration Parameters
config:
  # Workflow Parameters (User-configurable)
  success_threshold: 0.8
  max_iterations: 3
  auto_approve_fields: false
  approval_timeout: 300
  
  # Template Management
  template_dir: .olav/templates/custom
  cache_db: .olav/cache/semantic_cache.db
  
  # NTC Integration
  use_ntc_references: true
  
  # Multi-Tier Caching Configuration (Phase 3+ Optimization)
  caching:
    # Enable Tier 0 template cache (65-80% hit rate expected)
    enable_template_cache: true
    
    # Enable field analysis cache (reduces LLM calls 5-10x)
    enable_field_analysis_cache: false
    
    # L1 Memory cache size (entries)
    memory_cache_size: 100
    
    # L2 DuckDB persistence (unlimited)
    db_cache_enabled: true
    
    # Output similarity threshold for matching (0-1)
    # Higher = stricter matching, lower = more hits
    similarity_threshold: 0.85
    
    # Cache TTL (delete entries older than N days, 0 = never)
    cache_ttl_days: 30
    
    # Performance tracking
    track_cache_stats: true
  
  # LLM Provider Configuration
  llm_config:
    # Provider (openrouter, openai, etc.)
    provider: "openrouter"
    
    # Model name (read from .env if not specified)
    # model: "x-ai/grok-2-vision"
    
    # LLM parameters
    temperature: 0.3
    max_tokens: 4096
    timeout: 120
  
  # Timeout Configuration
  timeouts:
    command_execution: 30
    field_analysis: 60
    ntc_search: 30
    template_generation: 120
    template_testing: 30

# Activation Events
activation:
  # User mentions learning/generating templates
  keywords:
    - "learn this command"
    - "generate template"
    - "textfsm"
    - "learn_cmd"
  
  # CLI integration
  cli_commands:
    - "/learn_cmd"
    - "/template"
  
  # Exact intent matching
  intents:
    - intent_id: "textfsm.learn"
      priority: 100
      description: "Learn a new custom command template"

# Input/Output Specifications
input_spec:
  required:
    - host: "Target host (format: hostname:group)"
    - command: "Command to learn (e.g., 'show ip custom')"
    - platform: "Network OS platform (cisco_ios, arista_eos, etc.)"
  
  optional:
    - sample_outputs: "Pre-collected command outputs for analysis"
    - approval_timeout: "User approval timeout in seconds (default: 300)"
    - iterations_limit: "Max ReAct iterations (overrides config.max_iterations)"

output_spec:
  success_response:
    template: "Generated TextFSM template string"
    metadata:
      command_name: "Learned command name"
      platform: "Network platform"
      file_path: "Location where template was saved"
      success_rate: "Template success rate (0-1)"
      iterations: "Number of ReAct iterations used"
  
  error_response:
    error: "Error message"
    workflow_path: "Steps completed before error"
    suggestions: "Recovery suggestions"

# 6-Step Workflow Definition
workflow:
  steps:
    - name: "Execute Command"
      step_number: 1
      description: "Execute command on target host"
      timeout: 30
      retry_count: 2
      
    - name: "Analyze Fields"
      step_number: 2
      description: "LLM analysis of output fields"
      timeout: 60
      llm_provider: "openrouter"
      
    - name: "User Approval"
      step_number: 3
      description: "User review and modification of fields"
      timeout: 300
      interactive: true
      
    - name: "Fetch NTC References"
      step_number: 4
      description: "Search NTC template library"
      timeout: 30
      optional: true
      
    - name: "Generate Template"
      step_number: 5
      description: "ReAct template generation loop"
      timeout: 120
      max_iterations: 3
      
    - name: "Save Template"
      step_number: 6
      description: "Save template and metadata"
      timeout: 10

# Tools and Integrations
tools:
  - name: "execute_command_tool"
    description: "Execute command on network device"
    implementation: "tools.execute_command_tool"
  
  - name: "analyze_output_tool"
    description: "Analyze command output and extract fields"
    implementation: "tools.analyze_output_tool"
  
  - name: "generate_template_tool"
    description: "Generate TextFSM template from analysis"
    implementation: "tools.generate_template_tool"
  
  - name: "test_template_tool"
    description: "Test template against sample outputs"
    implementation: "tools.test_template_tool"
  
  - name: "save_template_tool"
    description: "Save template to file with metadata"
    implementation: "tools.save_template_tool"

# Data Models
data_models:
  - AnalysisResult
  - ApprovalResult
  - GenerationMetrics
  - TemplateMetadata

# Prerequisite Skills
requires_skills:
  - "network-cli"  # For command execution

# Performance Characteristics
performance:
  typical_duration_seconds: 60
  typical_llm_calls: 2
  success_rate_threshold: 0.8
  typical_iterations: 2

# Rollback Strategy
rollback:
  enabled: true
  save_drafts: true
  history_dir: ".olav/templates/drafts"

# Integration Points
integration:
  - type: "cli_command"
    command: "/learn_cmd"
    handler: "cmd_learn_cmd"
  
  - type: "skill_invocation"
    entry_point: "TextFSMWorkflowOrchestrator.run_workflow"
  
  - type: "knowledge_base"
    location: ".olav/knowledge/templates"
    auto_index: true

# Monitoring and Logging
monitoring:
  log_level: "INFO"
  track_metrics: true
  metrics_db: ".olav/reports/textfsm_metrics.db"
  
  metrics_tracked:
    - success_rate
    - generation_time
    - iterations_count
    - field_coverage
    - template_quality

# Testing and Validation
testing:
  e2e_tests: "tests/e2e/test_textfsm_interactive_e2e.py"
  cleanup_checklist: "cleanup_checklist.py"
  
  # Acceptance criteria
  acceptance_criteria:
    - All 8 E2E tests pass
    - Cleanup checklist passes
    - No redundant code warnings
    - Template success rate >= 0.8

# Version History
changelog:
  v1.0.0:
    - Initial complete redesign
    - 6-step interactive workflow
    - Auto-approval support
    - Full E2E test coverage (8/8 passing)
    - NTC reference integration
    - ReAct-based template generation
---

## Overview

The TextFSM Interactive Agent provides a complete workflow for learning new custom network device commands and automatically generating accurate TextFSM templates.

## Key Features

✅ **6-Step Interactive Workflow**
- Step 1: Execute command on target host
- Step 2: Auto-analyze output fields (LLM)
- Step 3: User approval/modification workflow
- Step 4: Fetch NTC-template references
- Step 5: ReAct-based template generation
- Step 6: Save template with metadata

✅ **Intelligent Field Analysis**
- Automatic field detection from command output
- Data type inference (int, float, string, list, dict)
- Coverage calculation for output parsing

✅ **User Approval Workflow**
- Interactive field review
- Field modification capabilities
- Rejection support with optional notes

✅ **NTC Template Integration**
- Reference search for similar commands
- Pattern reuse from known templates
- Fallback to pure LLM generation

✅ **Quality Metrics**
- Parse success rate tracking
- Value coverage calculation
- Regex accuracy scoring
- State machine completeness measurement

## Usage

### CLI Integration

```bash
# Learn a custom command
/learn_cmd R1:core cisco_ios "show running-config | include bgp"

# Get help
/learn_cmd
```

### Python API

```python
from olav.agents.textfsm_interactive_agent import TextFSMWorkflowOrchestrator

orchestrator = TextFSMWorkflowOrchestrator(
    success_threshold=0.8,
    max_iterations=3,
)

result = await orchestrator.run_workflow(
    host="R1.cisco_ios",
    command="show ip custom",
    platform="cisco_ios",
    sample_outputs=["output1", "output2"],
)

if result["success"]:
    print(result["template"])
    print(f"Success rate: {result['generation_result']['metrics']['parse_success']:.1%}")
```

## Configuration

### Environment Variables

```bash
# Auto-approve fields (dev mode)
TEXTFSM_AUTO_APPROVE=true

# Template directory
TEXTFSM_TEMPLATE_DIR=.olav/templates/custom

# Success threshold
TEXTFSM_SUCCESS_THRESHOLD=0.8
```

### Settings Override

Edit `.olav/settings.json`:

```json
{
  "textfsm_interactive": {
    "success_threshold": 0.8,
    "max_iterations": 3,
    "auto_approve_fields": false
  }
}
```

## Architecture

```
TextFSM Interactive Agent (v1.0.0)
├── Orchestrator (6-step workflow coordinator)
├── DeepAgent (ReAct template generator)
├── Tools (execute, analyze, generate, test, save)
├── Models (data validation and serialization)
└── Cleanup Checklist (migration verification)
```

## Quality Gates

✅ **Testing**: 8/8 E2E tests passing
✅ **Coverage**: Workflow steps validated
✅ **Performance**: ~60 seconds typical duration
✅ **Rollback**: Draft history with rollback support

## Status

**Phase**: Integration Phase (Phase 4)
**Status**: ✅ Complete
**Last Updated**: 2026-02-07
