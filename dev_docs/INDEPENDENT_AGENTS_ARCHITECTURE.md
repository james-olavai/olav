# Independent Agents Architecture - OLAV v2.1

**Date**: 2026-02-15  
**Status**: 🟡 Design Phase  
**Version**: v2.1.0  
**Rationale**: Decoupled, portable, independently deployable agents

---

## 📋 Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Design Principles](#design-principles)
3. [Agent Specifications](#agent-specifications)
4. [Communication & Routing](#communication--routing)
5. [State Management](#state-management)
6. [Deployment Scenarios](#deployment-scenarios)
7. [Migration from v2.0](#migration-from-v20)
8. [Implementation Roadmap](#implementation-roadmap)

---

## 🏗️ Architecture Overview

### Three Independent Agents

```
┌─────────────────────────────────────────────────────────────────┐
│                        OLAV v2.1 Ecosystem                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────┐ │
│  │   Main Agent    │  │ Command Learner │  │  Admin Agent   │ │
│  │                 │  │     Agent       │  │                │ │
│  │   (OLAV)        │  │                 │  │  (OLAV Admin)  │ │
│  └─────────────────┘  └─────────────────┘  └────────────────┘ │
│         │                     │                     │          │
│         │                     │                     │          │
│  ┌──────▼─────────┐  ┌───────▼────────┐  ┌────────▼────────┐ │
│  │ Tools:         │  │ Tools:         │  │ Tools:          │ │
│  │ - database     │  │ - execute_cmd  │  │ - read_file     │ │
│  │ - network      │  │ - analyze_out  │  │ - write_file    │ │
│  │ - inspection   │  │ - generate_tpl │  │ - execute_olav  │ │
│  │                │  │ - ntc_search   │  │ - search_code   │ │
│  │                │  │ - save_tpl     │  │ - git_ops       │ │
│  └────────────────┘  └────────────────┘  └─────────────────┘ │
│         │                     │                     │          │
│  ┌──────▼─────────┐  ┌───────▼────────┐  ┌────────▼────────┐ │
│  │ State:         │  │ State:         │  │ State:          │ │
│  │ main.duckdb    │  │ learner.duckdb │  │ admin.duckdb    │ │
│  └────────────────┘  └────────────────┘  └─────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

CLI Router (.olav CLI commands route to appropriate agent)
```

### Key Characteristics

| Aspect | v2.0 (Single Agent) | v2.1 (Independent Agents) |
|--------|---------------------|---------------------------|
| **Architecture** | 1 Agent + Skills | 3 Independent Agents |
| **Coupling** | Skills tightly coupled | Zero coupling between agents |
| **Deployment** | Monolithic | Microservice-ready |
| **Reusability** | Project-specific | Portable to other projects |
| **State** | Shared checkpointer | Independent state per agent |
| **Parallel Execution** | Serial (one Agent) | True parallel (3 Agents) |

---

## 🎯 Design Principles

### 1. Zero Coupling
```python
# ✅ Each agent is self-contained
from olav.agents.main_agent import main_agent
from olav.agents.command_learner_agent import command_learner_agent
from olav.agents.admin_agent import admin_agent

# Can use independently
result = command_learner_agent.invoke("learn show ip bgp")
```

### 2. Portable & Reusable
```bash
# ✅ Can be extracted and published separately
$ pip install olav-command-learner  # Standalone package
$ pip install olav-admin-agent      # Standalone package
```

### 3. Clear Responsibilities

| Agent | Responsibility | When to Use |
|-------|---------------|-------------|
| **Main Agent** | Network query, analysis, CLI execution | General network operations |
| **Command Learner** | TextFSM template learning and generation | When adding new commands |
| **Admin** | System maintenance, skill management | System administration tasks |

### 4. Declarative Routing (Not LLM-based)
```python
# ✅ Simple prefix-based routing (no LLM cost)
if query.startswith("/learn"):
    return command_learner_agent.invoke(query)
elif query.startswith("/admin"):
    return admin_agent.invoke(query)
else:
    return main_agent.invoke(query)
```

---

## 📦 Agent Specifications

### 1. Main Agent (OLAV)

**Purpose**: Network query, analysis, and operations  
**Location**: `src/olav/agents/main_agent.py` (existing)  
**Status**: ✅ Already implemented (v2.0)

```python
main_agent = create_deep_agent(
    name="OLAV",
    tools=[
        execute_sql,              # Database queries (smart schema-aware)
        execute_cli,              # Execute commands on devices
        list_devices_inventory,   # List devices
        manage_inspection_schedule # Schedule inspections
    ],
    skills_path=".olav/skills",
    checkpointer=DuckDBSaver(".olav/databases/main.duckdb"),
    middleware=[
        TodoListMiddleware(),
        SummarizationMiddleware()
    ]
)
```

**No changes needed** - Keep existing implementation.

---

### 2. Command Learner Agent

**Purpose**: Learn new commands and generate TextFSM templates  
**Location**: `src/olav/agents/command_learner_agent.py` (new)  
**Detailed Spec**: [COMMAND_LEARNER_AGENT_SPEC.md](./COMMAND_LEARNER_AGENT_SPEC.md)

**Key Features**:
- ✅ Autonomous 6-step workflow (LLM-guided)
- ✅ NTC-templates directory search for reference
- ✅ HITL approval for generated templates
- ✅ Custom + NTC template priority
- ✅ Portable to other projects

**CLI Interface**:
```bash
# New command format
$ olav /learn_cmd "show ip bgp summary" --device R1

# Or in interactive mode
> /learn_cmd show ip route --device R1
```

---

### 3. Admin Agent

**Purpose**: System maintenance, skill management, code operations  
**Location**: `src/olav/agents/admin_agent.py` (new)  
**Detailed Spec**: [ADMIN_AGENT_SPEC.md](./ADMIN_AGENT_SPEC.md)

**Key Features**:
- ✅ Full access to OLAV documentation as reference
- ✅ Can modify skills, create tools
- ✅ Execute OLAV commands (subprocess)
- ✅ Git operations (with HITL approval)
- ✅ Minimalist design (no complex abstractions)

**CLI Interface**:
```bash
# Admin commands
$ olav /admin create-skill monitoring
$ olav /admin reload-commands
$ olav /admin backup

# Or in interactive mode
> /admin show documentation about skills
> /admin modify skill network-query to add example
```

---

## 🔄 Communication & Routing

### CLI-Level Routing (Simple & Declarative)

```python
# src/olav/cli/agent_v2.py

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, message: str = typer.Option(None, "-m")):
    """Route to appropriate agent based on command prefix."""
    
    if message:
        # Declarative routing (no LLM cost)
        if message.startswith("/learn"):
            from olav.agents.command_learner_agent import command_learner_agent
            result = command_learner_agent.invoke(message)
        
        elif message.startswith("/admin"):
            from olav.agents.admin_agent import admin_agent
            result = admin_agent.invoke(message)
        
        else:
            # Default: main agent
            from olav.agents.main_agent import main_agent
            result = main_agent.invoke(message)
        
        print(result)
```

**Why Command Prefixes?**
- ✅ Zero LLM cost (no routing decision needed)
- ✅ Predictable (user knows which agent handles request)
- ✅ Fast (no LLM call overhead)
- ✅ Debuggable (clear agent selection)

---

## 💾 State Management

### Independent Checkpointers

```python
# Each agent has isolated state
main.duckdb           # Main agent conversations
command_learner.duckdb # Learning sessions
admin.duckdb          # Admin operations

# Benefits:
# ✅ No state pollution
# ✅ Independent backup/restore
# ✅ Parallel execution safe
```

### State Isolation Example

```python
# Can clear one agent's state without affecting others
command_learner_agent.checkpointer.clear()  # Only clears learner
main_agent.checkpointer.clear()            # Only clears main
admin_agent.checkpointer.clear()           # Only clears admin

# Can run concurrently without conflicts
await asyncio.gather(
    main_agent.ainvoke("query devices"),
    command_learner_agent.ainvoke("learn command"),
    admin_agent.ainvoke("backup system")
)
```

---

## 🚀 Deployment Scenarios

### Scenario 1: Monolithic (Default)
```bash
# All three agents in one process
$ uv run olav
> /learn_cmd show version --device R1
> What devices do we have?
> /admin backup
```

### Scenario 2: Microservices
```bash
# Each agent as separate service
$ uv run olav serve main --port 8001
$ uv run olav serve command-learner --port 8002
$ uv run olav serve admin --port 8003

# API Gateway routes requests
POST /api/main/invoke
POST /api/learner/invoke
POST /api/admin/invoke
```

### Scenario 3: Standalone CLI Tools
```bash
# Command learner as standalone tool
$ pip install olav-command-learner
$ olav-learn "show ip bgp" --device R1 --platform cisco_ios

# Admin as standalone tool
$ pip install olav-admin
$ olav-admin reload-commands
```

---

## 🔄 Migration from v2.0

### What Stays the Same
- ✅ Main agent implementation (no changes)
- ✅ Skills directory structure
- ✅ Tools in `.olav/tools/`
- ✅ Database schemas
- ✅ 39/39 E2E tests

### What Changes
- ➕ Add `command_learner_agent.py` (new file)
- ➕ Add `admin_agent.py` (new file)
- ✏️ Update CLI routing in `agent_v2.py`
- ➕ Add `/learn_cmd` and `/admin` commands
- ➕ Add `reload-commands` functionality

### Migration Steps
1. ✅ Keep existing `main_agent.py` as-is
2. ➕ Create `command_learner_agent.py` (Phase 1)
3. ➕ Create `admin_agent.py` (Phase 2)
4. ✏️ Update CLI router (Phase 3)
5. ✅ Verify 39/39 tests still pass

---

## 📋 Implementation Roadmap

### Phase 1: Command Learner Agent (Week 1-2)
- [ ] Create `command_learner_agent.py`
- [ ] Implement 6-step workflow
- [ ] Integrate NTC-templates search
- [ ] Add `/learn_cmd` CLI command
- [ ] E2E tests (8 test cases)

### Phase 2: Admin Agent (Week 3-4)
- [ ] Create `admin_agent.py`
- [ ] Implement tools (read/write/execute/git)
- [ ] Load OLAV documentation as reference
- [ ] Add `/admin` CLI commands
- [ ] Security & HITL middleware
- [ ] E2E tests (10 test cases)

### Phase 3: Integration & Testing (Week 5)
- [ ] Update CLI router
- [ ] Parallel execution tests
- [ ] State isolation tests
- [ ] Verify 39/39 original tests pass
- [ ] Performance benchmarks

### Phase 4: Documentation & Polish (Week 6)
- [ ] API documentation
- [ ] User guide for new commands
- [ ] Migration guide
- [ ] Release v2.1.0

---

## 🎯 Success Criteria

### Functional
- ✅ Command Learner can learn new commands autonomously
- ✅ Admin can modify skills and execute OLAV commands
- ✅ All three agents can run concurrently
- ✅ 39/39 original E2E tests pass

### Architectural
- ✅ Zero coupling between agents
- ✅ Each agent can be imported independently
- ✅ Each agent has isolated state
- ✅ Command Learner can be extracted as standalone package

### Performance
- ✅ No performance regression from v2.0
- ✅ Parallel execution shows speedup
- ✅ CLI routing < 50ms overhead

---

## 📚 Related Documents

- [COMMAND_LEARNER_AGENT_SPEC.md](./COMMAND_LEARNER_AGENT_SPEC.md) - Detailed Command Learner design
- [ADMIN_AGENT_SPEC.md](./ADMIN_AGENT_SPEC.md) - Detailed Admin Agent design
- [DEEPAGENTS_SIMPLIFICATION_PLAN.md](./DEEPAGENTS_SIMPLIFICATION_PLAN.md) - v2.0 architecture rationale
- [CODE_AUDIT_2026_02_14.md](./CODE_AUDIT_2026_02_14.md) - Issues driving v2.1 design

---

**Version**: v2.1.0-design  
**Author**: OLAV Architecture Team  
**Last Updated**: 2026-02-15
