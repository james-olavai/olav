---
name: command_learner
version: 1.0.0
author: Network AI Team
description: Interactive command learning with automatic TextFSM template generation and user approval workflow
type: agent
category: command_learning

prompts:
  generation: $ref:./reference/textfsm_generation.md
  analysis: $ref:./reference/textfsm_analysis.md

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
  llm_config:
    provider: "openrouter"
    temperature: 0.3
    max_tokens: 4096
    timeout: 120

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
      tool: "ntc_search" # $ref:./scripts/ntc_search.py
    - name: "Generate Template"
      step_number: 5
      timeout: 120
      max_iterations: 3
    - name: "Save Template"
      step_number: 6
      timeout: 10

tools:
  - name: "execute_command_tool"
    implementation: "src/olav/agents/command_learner_agent/tools.py"
  - name: "analyze_output_tool"
    implementation: "src/olav/agents/command_learner_agent/tools.py"
  - name: "generate_template_tool"
    implementation: "src/olav/agents/command_learner_agent/tools.py"
  - name: "test_template_tool"
    implementation: "src/olav/agents/command_learner_agent/tools.py"
  - name: "save_template_tool"
    implementation: "src/olav/agents/command_learner_agent/tools.py"
  - name: "ntc_search"
    description: "Local NTC-Templates search (no internet required)"
    implementation: "./scripts/ntc_search.py"
    method: "search_ntc_templates(platform, command, approved_fields, limit)"

requires_skills:
  - "network-cli"

performance:
  typical_duration_seconds: 60
  typical_llm_calls: 2
  success_rate_threshold: 0.8

monitoring:
  log_level: "INFO"
  track_metrics: true
  metrics_tracked:
    - success_rate
    - generation_time
    - iterations_count

testing:
  e2e_tests: "tests/e2e/test_command_learner_e2e.py"
  acceptance_criteria:
    - All 8 E2E tests pass
    - Template success rate >= 0.8

---

## Overview

The Command Learner Agent provides a complete workflow for learning new custom network device commands and automatically generating accurate TextFSM templates.

## Key Features

✅ **6-Step Interactive Workflow**
- Execute command on target host
- Auto-analyze output fields (LLM)
- User approval/modification workflow
- Fetch NTC-template references (local search, no internet)
- ReAct-based template generation
- Save template with metadata

✅ **Local NTC-Templates Search**
- Searches local `ntc-templates` pip package
- No internet requirement
- Platform and command keyword matching
- Field coverage scoring
- Available as standalone CLI tool or agent tool

✅ **Intelligent Field Analysis**
- Automatic field detection from command output
- Data type inference (int, float, string, list, dict)
- Coverage calculation for output parsing

✅ **User Approval Workflow**
- Interactive field review
- Field modification capabilities

## Local NTC-Templates Search Tool

### Standalone Usage (CLI)

```bash
# Search for cisco_ios templates for 'show bgp summary'
./scripts/ntc_search.py \
  --platform cisco_ios \
  --command "show bgp summary" \
  --fields "router_id,neighbors,state" \
  --limit 3

# Verbose output
./scripts/ntc_search.py \
  --platform cisco_ios \
  --command "show bgp summary" \
  --fields "router_id,neighbors" \
  --limit 3 \
  -v
```

### Python API Usage

```python
from olav.skills.command_learner.scripts.ntc_search import search_ntc_templates

result = search_ntc_templates(
    platform="cisco_ios",
    command="show bgp summary",
    approved_fields=["router_id", "neighbors", "state"],
    limit=3
)

# Access results
for ref in result["references"]:
    print(f"Template: {ref['template_name']}")
    print(f"Score: {ref['relevance_score']}")
    print(f"Field Coverage: {ref['field_coverage']}")
```

### Agent Integration

The search tool is automatically called during Step 4 of the workflow:

```
Step 4: Fetch NTC References
  ↓
  Calls: get_ntc_references_tool()
  ↓
  Uses: ./scripts/ntc_search.py
  ↓
  Returns: Top 2-3 matching templates
```

## Usage

### CLI Integration

```bash
/learn_cmd R1:core cisco_ios "show running-config | include bgp"
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
)
```

## Configuration

Edit `.olav/settings.json`:

```json
{
  "textfsm_interactive": {
    "success_threshold": 0.8,
    "max_iterations": 3,
    "auto_approve_fields": false,
    "use_ntc_references": true
  }
}
```

### NTC-Templates Setup

1. **Install ntc-templates package**:
   ```bash
   pip install ntc-templates
   ```

2. **Verify installation**:
   ```bash
   python -c "import ntc_templates; print(ntc_templates.__file__)"
   ```

3. **The skill's search tool will automatically find them**

## Architecture

```
command_learner/
├── SKILL.md                 (Skill configuration)
├── reference/               (Reference documentation)
│   ├── textfsm_generation.md   (Generation prompt with NTC guidance)
│   ├── textfsm_analysis.md     (Analysis prompt with NTC integration)
│   └── ARCHITECTURE.md         (Design decisions)
├── scripts/                 (Skill-specific tools)
│   ├── __init__.py
│   └── ntc_search.py        (Local NTC-Templates search)
└── [implementation]
    src/olav/agents/command_learner_agent/
    ├── tools.py             (Calls scripts/ntc_search.py)
    ├── orchestrator.py      (6-step workflow)
    └── ...
```

## Status

**Phase:** Integration (Phase 4)
**Status:** ✅ Complete
**Quality:** 8/8 E2E tests passing
