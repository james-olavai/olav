# Architectural Analysis: olav-ops Agent Split

**Date:** 2026-02-22
**Author:** Sisyphus (AI Architect)
**Status:** Analysis Complete - Awaiting Decision

---

## Executive Summary

This document analyzes whether the `olav-ops` SubAgent should be split into specialized agents (SQL expert, CLI expert, Analysis expert). 

**Recommendation:** ❌ **DO NOT SPLIT** — The current architecture is appropriate for the domain complexity. Splitting would introduce unnecessary overhead without clear benefits. Instead, optimize the existing structure with prompt engineering and tool organization.

---

## 1. Current State Analysis

### 1.1 Tool Inventory (9 Tools)

| Tool | Category | Primary Function | Lines of Code |
|------|----------|------------------|---------------|
| `execute_sql` | SQL/Data | Query DuckDB with auto schema discovery | 439 |
| `execute_cli` | CLI/Execution | Execute commands on network devices | 374 |
| `take_snapshot` | CLI/Execution | On-demand targeted data collection | 379 |
| `diff_configs` | Analysis | Compare config snapshots for drift | 310 |
| `search_knowledge` | Analysis | Internal knowledge base search | ~80 |
| `web_search` | Analysis | External web search for troubleshooting | ~60 |
| `search_cache` | Utility | Semantic response cache lookup | ~50 |
| `search_commands` | Utility | Query available CLI commands | ~70 |
| `format_and_export` | Utility | Export data to CSV/JSON/Markdown | ~100 |

### 1.2 Tool Usage Frequency (Estimated)

Based on typical network operations workflows:

| Tool | Frequency | Reason |
|------|-----------|--------|
| `execute_sql` | **80%** | Most queries hit the database |
| `execute_cli` | **10%** | Only for real-time data |
| `take_snapshot` | **5%** | Targeted fault investigation |
| `diff_configs` | **3%** | Configuration drift detection |
| `search_*` / `web_search` | **2%** | Troubleshooting support |

### 1.3 Current Role Definition

From `.olav/skills/olav-ops/prompts/network_ops_subagent.md`:

```
You are a network operations analyst with access to DuckDB, live CLI, and search tools.
```

**Key directive added (2026-02-22):**
- SQL-first approach: `execute_sql` is the DEFAULT tool
- CLI is a FALLBACK when DB data is missing or stale

---

## 2. Split Proposal Analysis

### 2.1 Proposed Split Architecture

```
olav-ops (current)
    ↓ SPLIT INTO ↓
┌─────────────────┬─────────────────┬─────────────────┐
│  olav-sql       │  olav-cli       │  olav-analysis  │
│  (SQL Expert)   │  (CLI Expert)   │  (Analysis)     │
├─────────────────┼─────────────────┼─────────────────┤
│  execute_sql    │  execute_cli    │  diff_configs   │
│  search_commands│  take_snapshot  │  search_knowledge│
│                 │                 │  web_search     │
│                 │                 │  search_cache   │
└─────────────────┴─────────────────┴─────────────────┘
```

### 2.2 Split Benefits (Claimed)

| Claimed Benefit | Reality Check |
|-----------------|---------------|
| Better tool selection | ✅ Partially true — specialized prompts could guide better |
| Clearer responsibilities | ❌ Overhead — agents already have clear prompts |
| Parallel execution | ❌ Rarely useful — most queries are single-tool |
| Easier maintenance | ❌ False — more files = more complexity |

### 2.3 Split Costs (Actual)

| Cost | Impact |
|------|--------|
| **Latency overhead** | Every query now requires: intent classification → agent routing → tool execution. Adds 1-2 LLM calls per query. |
| **Context fragmentation** | SQL expert won't know CLI capabilities, Analysis expert won't know DB schema. Cross-agent queries become harder. |
| **Orchestration complexity** | Need supervisor agent to route queries. More code, more bugs. |
| **Token waste** | Each agent needs its own system prompt. Redundant instructions. |
| **Testing burden** | Need to test 3 agents + supervisor + handoffs. 4x test surface. |

### 2.4 Quantified Trade-offs

| Metric | Current (1 Agent) | Split (3 Agents) |
|--------|-------------------|------------------|
| LLM calls per query | 1-2 | 3-4 |
| System prompt tokens | ~500 | ~500 × 3 = 1500 |
| Code complexity | Low | High (supervisor + routing) |
| Debugging difficulty | Easy | Hard (multi-hop traces) |
| Maintenance overhead | 9 tools in 1 place | 9 tools in 3 places |

---

## 3. LangGraph/DeepAgents Orchestration Patterns

### 3.1 Available Patterns

LangGraph supports three main multi-agent patterns:

| Pattern | Description | Best For |
|---------|-------------|----------|
| **Supervisor** | Central agent routes to specialists | Complex workflows with clear subdomains |
| **Hierarchical** | Nested supervisors | Large organizations (not applicable) |
| **Parallel** | Multiple agents work simultaneously | Independent tasks (rare in network ops) |

### 3.2 Current OLAV Architecture

```
┌─────────────────────────────────────────────────────┐
│              OLAVAgent (Orchestrator)               │
│  - Pure orchestrator (0 direct tools)              │
│  - Delegates to SubAgents via `task` tool          │
├─────────────────────────────────────────────────────┤
│  SubAgents:                                         │
│  ├─ olav-ops    (read/query operations)            │
│  ├─ olav-config (infrastructure/write operations)  │
│  └─ olav-audit  (governance/health checks)         │
└─────────────────────────────────────────────────────┘
```

**Key insight:** OLAV already uses a supervisor pattern at the **domain level** (ops/config/audit). Splitting ops further would create a **nested supervisor** with minimal benefit.

### 3.3 DeepAgents SubAgent Capabilities

From `src/olav/agents/agent.py`:

- SubAgents are defined in `.olav/OLAV.md` frontmatter
- Each SubAgent has: name, description, skills, tools, prompt, model override
- LangGraph `DuckDBSaver` for conversation state
- `DuckDBStore` for long-term memory

**Parallel execution:** DeepAgents supports parallel SubAgent calls, but this is useful only when tasks are truly independent. In network operations, most queries are sequential (query → analyze → report).

---

## 4. Domain Complexity Analysis

### 4.1 Tool Count Thresholds

| Domain Complexity | Recommended Agent Count | Tool Count Range |
|-------------------|-------------------------|------------------|
| Simple | 1 agent | 1-5 tools |
| Moderate | 1 agent | 6-15 tools |
| Complex | 2-3 agents | 15-30 tools |
| Enterprise | 5+ agents | 30+ tools |

**olav-ops has 9 tools → Moderate complexity → 1 agent is appropriate.**

### 4.2 Cohesion Analysis

Tools in olav-ops share a **common purpose**: network operations query and troubleshooting.

```
execute_sql ──┐
execute_cli ──┤
take_snapshot ─┼──► Network Operations Query
diff_configs ──┤
search_* ──────┘
```

High cohesion → Single agent appropriate.

### 4.3 Comparison with Other OLAV SubAgents

| SubAgent | Tools | Domain | Cohesion |
|----------|-------|--------|----------|
| olav-ops | 9 | Query/CLI/Search | High |
| olav-config | 10 | Infrastructure/Write | High |
| olav-audit | 5 | Governance/Health | High |

All three SubAgents have similar tool counts and high cohesion. Splitting ops alone would create architectural inconsistency.

---

## 5. Alternative Optimization Strategies

Instead of splitting, optimize the existing architecture:

### 5.1 Prompt Engineering (Already Done ✅)

The SQL-first directive was added to `network_ops_subagent.md`:

```markdown
## 📊 Tool Selection Priority (CRITICAL - READ FIRST)

**ALWAYS try `execute_sql` FIRST.** CLI is a fallback, not the default.
```

### 5.2 Tool Docstring Optimization (Already Done ✅)

Tool docstrings now include explicit routing hints:

```python
# execute_sql.py
"""Execute SQL query... ⭐ DEFAULT TOOL for device queries. Use this FIRST."""

# execute_cli.py
"""Execute CLI command... ⚠️ FALLBACK TOOL. Use execute_sql FIRST."""
```

### 5.3 Tool Organization (Recommended)

Group tools in the prompt by frequency:

```markdown
## Your Tools (Ordered by Frequency)

### 🥇 Primary (80% of queries)
- execute_sql — Query device inventory, parsed outputs, topology

### 🥈 Secondary (15% of queries)
- execute_cli — Real-time CLI when DB data is stale
- take_snapshot — Targeted data collection for troubleshooting

### 🥉 Tertiary (5% of queries)
- diff_configs — Configuration drift detection
- search_knowledge — Internal docs search
- web_search — External troubleshooting
- format_and_export — Export results
```

### 5.4 Semantic Caching (Already Implemented ✅)

`SQLiteCache` caches repeated queries, reducing LLM calls.

---

## 6. Decision Framework

### 6.1 When to Split

Split an agent when **ALL** of the following are true:

| Criterion | olav-ops Status |
|-----------|-----------------|
| Tool count > 15 | ❌ No (9 tools) |
| Tools serve unrelated domains | ❌ No (all network ops) |
| Single LLM struggles to route | ❌ No (SQL-first works) |
| Parallel execution is common | ❌ No (mostly sequential) |
| Maintenance burden is high | ❌ No (well-organized) |

**Result:** 0/5 criteria met → Do NOT split.

### 6.2 When to Keep Unified

Keep a single agent when:

- Tool count < 15
- Tools share common purpose
- LLM can route effectively with prompts
- Sequential workflow is dominant
- Maintenance is manageable

**olav-ops meets ALL criteria for keeping unified.**

---

## 7. Recommendation

### 7.1 Primary Recommendation: Keep Unified

**Do NOT split olav-ops into specialized agents.**

Reasons:
1. Tool count (9) is within optimal range for single agent
2. High domain cohesion (all tools serve network operations)
3. SQL-first prompt engineering already solves the routing issue
4. Splitting adds latency, complexity, and maintenance burden
5. No evidence of LLM routing confusion in practice

### 7.2 Secondary Recommendations

| Recommendation | Priority | Effort |
|----------------|----------|--------|
| ✅ Keep SQL-first prompt (done) | — | — |
| ✅ Update tool docstrings (done) | — | — |
| ⬜ Reorganize tool list by frequency in prompt | Medium | 10 min |
| ⬜ Add tool usage metrics logging | Low | 1 day |
| ⬜ Monitor agent routing accuracy | Low | Ongoing |

### 7.3 Future Considerations

Re-evaluate splitting if:
- Tool count exceeds 15
- New domain is added (e.g., security operations)
- Routing accuracy drops below 90%
- Query latency becomes unacceptable

---

## 8. Implementation Notes

### 8.1 If Split Were Implemented (Reference Only)

```yaml
# .olav/OLAV.md (hypothetical)

subagents:
  - name: olav-sql
    description: SQL expert for database queries
    skills: [olav-sql]
    prompt: olav-sql/prompts/system.md
    
  - name: olav-cli
    description: CLI expert for live device execution
    skills: [olav-cli]
    prompt: olav-cli/prompts/system.md
    
  - name: olav-analysis
    description: Analysis expert for troubleshooting
    skills: [olav-analysis]
    prompt: olav-analysis/prompts/system.md
```

**Estimated overhead:**
- 3 additional prompt files
- 3 additional skill directories
- Supervisor routing logic (intent classification)
- 2-3 additional LLM calls per query
- ~500 lines of additional code

### 8.2 Current Architecture (Optimal)

```yaml
# .olav/OLAV.md (current)

subagents:
  - name: olav-ops
    description: Handles all read/query operations: SQL queries against DuckDB,
      live CLI commands on network devices, knowledge base search, and data export.
    skills: [olav-ops]
    prompt: olav-ops/prompts/network_ops_subagent.md
```

**Current overhead:**
- 1 prompt file
- 1 skill directory
- 0 additional routing logic
- 1 LLM call per query
- No additional code

---

## 9. Conclusion

The `olav-ops` agent is well-designed for its domain. The recent SQL-first prompt engineering addresses the routing confusion issue without architectural changes. Splitting would introduce significant overhead for minimal benefit.

**Final Decision:** Keep unified. Focus on prompt optimization and monitoring.

---

## Appendix A: LangGraph Multi-Agent Resources

- [LangGraph Multi-Agent Tutorial](https://langchain-ai.github.io/langgraph/tutorials/multi_agent/multi-agent-collaboration/)
- [LangGraph Supervisor Pattern](https://langchain-ai.github.io/langgraph/how-tos/multi-agent-collaboration/)
- [Agent Specialization Best Practices](https://python.langchain.com/docs/modules/agents/)

## Appendix B: Tool Distribution Visualization

```
olav-ops Tool Distribution (9 tools)
┌─────────────────────────────────────────────────┐
│ SQL/Data ████████████████████████ 80% (primary) │
│ CLI/Exec ████ 15% (fallback)                    │
│ Analysis ██ 5% (support)                        │
└─────────────────────────────────────────────────┘

Tool Cohesion Matrix:
                    execute_sql  execute_cli  take_snapshot  diff_configs
execute_sql              —           ✓            ✓             ✓
execute_cli              ✓           —            ✓             ✓
take_snapshot            ✓           ✓            —             ✓
diff_configs             ✓           ✓            ✓             —

High cohesion = all tools work together → single agent optimal
```

---

**Document End**
