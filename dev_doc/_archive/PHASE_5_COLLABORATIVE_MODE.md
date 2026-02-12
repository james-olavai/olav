# Phase 5: Collaborative Mode (Declarative Dependencies)

## Overview

Collaborative Mode enables SubAgents to work together with explicit dependency declarations. Instead of hardcoding execution order, SubAgents declare their dependencies in SKILL.md frontmatter, and the Orchestrator automatically:

1. **Builds a dependency graph** (DAG) from declarations
2. **Detects circular dependencies** and rejects invalid configs
3. **Executes SubAgents in correct order** (dependencies first)
4. **Passes context between SubAgents** (previous outputs → next inputs)

## SKILL.md Syntax

### Basic Structure

```yaml
---
name: orchestrator
description: Central coordination agent

collaborative_mode:
  dependencies:
    # SubAgent 1: No dependencies
    - subagent: query
      task_template: "查询网络设备数据"
      output_context_key: network_devices_data
    
    # SubAgent 2: Depends on SubAgent 1's output
    - subagent: netbox
      task_template: "查询NetBox数据库"
      output_context_key: netbox_data
      requires:
        - network_devices_data
    
    # SubAgent 3: Depends on both previous outputs
    - subagent: analyzer
      task_template: "对比差异并生成报告"
      output_context_key: diff_report
      requires:
        - network_devices_data
        - netbox_data
---

(Markdown content...)
```

### Field Specification

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `subagent` | string | Yes | SubAgent name (must exist in agents/) |
| `task_template` | string | Yes | Task description/template for SubAgent |
| `output_context_key` | string | Yes | Key name for storing result in context dict |
| `requires` | list[string] | No | List of output_context_key values from other SubAgents |

### Dependency Rules

1. **output_context_key is the dependency unit** - `requires` references other SubAgents' outputs, not their names
2. **No circular dependencies** - Orchestrator rejects cycles (A→B→A)
3. **Topological order** - SubAgents executed after their dependencies
4. **Context passing** - Previous SubAgent outputs available as context dict

## Execution Flow

### 1. Parsing Phase
```
Load SKILL.md → Extract collaborative_mode → Validate structure
```

### 2. Graph Building Phase
```
For each dependency:
  - Map output_context_key → SubAgent name
  - Extract requires → Convert to subagent dependencies
  - Check for cycles (DFS)
```

### 3. Topological Sort Phase
```
Calculate in-degree for each node
While nodes exist:
  - Pick nodes with in-degree=0 (no dependencies)
  - Append to execution order
  - Reduce in-degree for dependents
```

### 4. Execution Phase
```
For each subagent in execution order:
  - Verify required context keys are available
  - Invoke subagent with context
  - Store output in context[output_context_key]
  - Continue to next subagent
```

## Example Scenarios

### Scenario 1: Sequential Chain (A→B→C)

```yaml
collaborative_mode:
  dependencies:
    - subagent: query
      output_context_key: network_data
    
    - subagent: netbox
      output_context_key: netbox_data
      requires: [network_data]
    
    - subagent: sync
      output_context_key: sync_result
      requires: [network_data, netbox_data]
```

**Execution order**: `[query, netbox, sync]`

**Context flow**:
1. query executes → context = {network_data: ...}
2. netbox executes with context → context = {..., netbox_data: ...}
3. sync executes with context → context = {..., sync_result: ...}

### Scenario 2: Parallel Branches

```yaml
collaborative_mode:
  dependencies:
    - subagent: query
      output_context_key: network_data
    
    - subagent: config_backup
      output_context_key: backup_status
      # No requires - can run in parallel with others
    
    - subagent: analyzer
      output_context_key: analysis
      requires: [network_data]
```

**Execution order**: `[query, config_backup, analyzer]`
- query and config_backup can execute in parallel (no dependencies)
- analyzer waits for network_data (from query)

### Scenario 3: Invalid (Circular Dependency)

```yaml
collaborative_mode:
  dependencies:
    - subagent: A
      output_context_key: A_out
      requires: [C_out]
    
    - subagent: B
      output_context_key: B_out
      requires: [A_out]
    
    - subagent: C
      output_context_key: C_out
      requires: [B_out]
```

**Result**: ValueError - "Circular dependency detected"

## Implementation Details

### Functions

| Function | Purpose |
|----------|---------|
| `_parse_collaborative_mode(skill_dict)` | Extract collaborative_mode from SKILL.md frontmatter |
| `_build_dependency_graph(dependencies)` | Build DAG with cycle detection |
| `_topological_sort(graph_dict)` | Determine execution order (dependencies first) |
| `_execute_with_dependencies_order(dependencies)` | Get execution order as list[str] |
| `_execute_subagents_with_context(subagents, deps, query)` | Execute with context passing |
| `create_collaborative_orchestrator()` | Factory function with Phase 5 support |

### Error Handling

- **Missing output_context_key**: Logged warning, SubAgent skipped
- **Circular dependency**: ValueError raised during graph building
- **Missing SubAgent**: Logged warning, execution continues
- **Missing context**: Logged warning, SubAgent skipped
- **Execution error**: Logged error, execution continues with other SubAgents

## Testing

### RED Tests Covered

✅ SKILL.md frontmatter parsing
✅ Dependency structure validation
✅ Requires field validation
✅ Basic DAG construction
✅ Topological sort ordering
✅ Circular dependency detection
✅ SubAgent execution in order
✅ Context passing between agents
✅ Partial context availability
✅ Orchestrator loads dependencies
✅ Orchestrator builds execution plan
✅ NetBox sync scenario
✅ Single SubAgent (no deps)
✅ Multiple independent SubAgents (parallel)
✅ Deep dependency chains (A→B→C→D)

## Future Enhancements

1. **Parallel execution** - Execute independent SubAgents concurrently
2. **Conditional execution** - If/then logic for SubAgent selection
3. **Aggregation** - Combine outputs from multiple SubAgents
4. **Retry logic** - Automatic retry with backoff for failed SubAgents
5. **Monitoring** - Track execution metrics (duration, errors, context size)

## Version History

| Version | Date | Changes |
|---------|------|---------|
| v0.10.3 | 2025-02-07 | Initial Phase 5 implementation |

