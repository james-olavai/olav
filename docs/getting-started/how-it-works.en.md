# How It Works

Understand three core concepts and you'll have a grasp of how the entire OLAV platform operates.

!!! info "This page is a conceptual overview with no standalone Claims. Related feature claims are distributed across the individual guide pages."

---

## Three Core Concepts

### Agent

Agents are OLAV's "workforce" — each Agent is an AI assistant focused on a specific set of tasks. Think of them as different roles on a team:

- **quick** Agent: Handles fast lookups, like a responsive on-call network operator
- **config** Agent: Handles platform configuration, like a system administrator
- **core** Agent: Handles code execution and complex analysis, like a versatile engineer

Each Agent's capabilities are defined in `.olav/workspace/<agent>/AGENT.md`, including its role description, available tools, and routing keywords.

### Skill

Skills are an Agent's "toolkit" — a set of Python tool functions that give an Agent specific capabilities. For example:

- A Skill for querying network devices
- A Skill for calling the Zabbix API
- A Skill for executing SQL

You can install new Skills for an Agent to extend its capabilities, just like equipping a team member with new tools.

### Workspace

The Workspace is the `.olav/workspace/` directory — all Agent and Skill definitions live here. It can be committed to git and shared with your team. This means:

- Team members have access to the same Agent capabilities
- Agent improvements can be tracked through version control
- You can use different workspaces for different projects

---

## How a Query Is Processed

When you enter a question, OLAV goes through the following pipeline internally:

```
Your question: "Which devices have abnormal BGP neighbor states?"
    │
    ▼
┌─────────────────────────────────────────────┐
│  Semantic Router                             │
│  Analyzes the question and matches Agent     │
│  route_keywords                              │
│  → Selects the best Agent (or uses --agent)  │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  Agent Loads Tools                           │
│  Reads AGENT.md and MANIFEST.yaml            │
│  Loads all associated Skill tool functions   │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  LLM Reasoning + Tool-Call Loop              │
│  LLM analyzes the question → decides which   │
│  tool to call → receives tool results →      │
│  synthesizes a final answer                  │
│  (may call tools multiple times until it has │
│  enough information)                         │
└─────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────┐
│  Returns the result to you                   │
│  Simultaneously writes to the audit log      │
│  (audit.duckdb)                              │
└─────────────────────────────────────────────┘
```

---

## Data Storage: What Is Shared vs. Private

OLAV data falls into two categories: **project-level** (shared with the team) and **user-level** (private to you).

### Project-Level (stored under `.olav/`)

| Content | Location | Notes |
|---------|----------|-------|
| Agent and Skill definitions | `.olav/workspace/` | ✅ Can be committed to git and shared with the team |
| Audit logs | `.olav/databases/audit.duckdb` | Operation records for everyone; DuckDB supports concurrent writes |
| Business data | `.olav/databases/domain.duckdb` | Device information, parsed results, etc. |
| API keys and configuration | `.olav/config/api.json` | ⚠️ Contains secrets — do not commit to git |

### User-Level (stored under `~/.olav/`)

| Content | Location | Notes |
|---------|----------|-------|
| Authentication token | `~/.olav/token` | Your identity credential |
| Session records | `~/.olav/sessions/` | Interactive mode history; expires after 24h |
| LLM cache | `~/.olav/cache/{user}/llm_cache.db` | Avoids redundant LLM calls for identical prompts — measured at **0 tokens, <1 ms response** on cache hit (~2000x speedup) |

---

## Three Usage Interfaces

| Interface | How to Launch | Best For |
|-----------|---------------|----------|
| **CLI** | `olav "your question"` | Script integration, one-off queries |
| **TUI** | `olav` (no arguments) | Multi-turn conversations, exploratory analysis |
| **Web UI** | `olav service web start` | Team sharing, browser access |

All three interfaces use the same Agents and tools under the hood, so their capabilities are identical.

**Next:** [Deep Dive into Agents and Skills →](../concepts/agents-and-skills.md)
