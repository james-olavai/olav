---
name: command_learner
version: 1.0.0
author: Network AI Team
description: Interactive command learning with automatic TextFSM template generation and user approval workflow
type: agent
category: command_learning

prompts:
  generation: |
    You are a TextFSM template expert. Generate high-quality TextFSM templates that accurately parse network device CLI output.
    Focus on:
    1. Accurate regex patterns for field extraction
    2. State machine transitions for multi-line output
    3. Value definitions BEFORE the Start state
    4. Correct state names (alphanumeric and underscore only)
    5. Proper response filtering and cleanup
    Return ONLY the valid TextFSM template code, ready to use.
  analysis: |
    You are a network command output analyzer. Analyze the given command output and identify:
    1. Field names and their values
    2. Data types (string, integer, float, IP address, MAC address, etc.)
    3. Repeating data structures (lists, tables)
    4. Field coverage percentage
    5. Potential regex patterns for extraction
    Return a structured analysis with recommended TextFSM field definitions.

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
    enable_field_analysis_cache: false
    memory_cache_size: 100
    db_cache_enabled: true
    similarity_threshold: 0.85
    cache_ttl_days: 30
    track_cache_stats: true
  llm_config:
    provider: "openrouter"
    temperature: 0.3
    max_tokens: 4096
    timeout: 120
  timeouts:
    command_execution: 30
    field_analysis: 60
    ntc_search: 30
    template_generation: 120
    template_testing: 30

activation:
  keywords:
    - "learn this command"
    - "generate template"
    - "textfsm"
    - "learn_cmd"

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

data_models:
  - AnalysisResult
  - ApprovalResult
  - GenerationMetrics
  - TemplateMetadata

requires_skills:
  - "network-cli"

performance:
  typical_duration_seconds: 60
  typical_llm_calls: 2
  success_rate_threshold: 0.8
  typical_iterations: 2

rollback:
  enabled: true
  save_drafts: true
  history_dir: ".olav/templates/drafts"

integration:
  - type: "cli_command"
    command: "/learn"
    handler: "cmd_learn"
  - type: "skill_invocation"
    entry_point: "CommandLearnerOrchestrator.run_workflow"
  - type: "knowledge_base"
    location: ".olav/knowledge/templates"
    auto_index: true

monitoring:
  log_level: "INFO"
  track_metrics: true
  metrics_db: ".olav/reports/command_learner_metrics.db"
  metrics_tracked:
    - success_rate
    - generation_time
    - iterations_count
    - field_coverage
    - template_quality

testing:
  e2e_tests: "tests/e2e/test_command_learner_e2e.py"
  cleanup_checklist: "cleanup_checklist.py"
  acceptance_criteria:
    - All 8 E2E tests pass
    - Cleanup checklist passes
    - No redundant code warnings
    - Template success rate >= 0.8

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

The Command Learner Agent provides a complete workflow for learning new custom network device commands and automatically generating accurate TextFSM templates.

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
