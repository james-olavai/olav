# Agents and Skills

Understanding the relationship between Agents and Skills is the key to mastering OLAV.

!!! info "This is a conceptual overview. For related Feature Claims, see [Using Agents](../guides/using-agents.md), [Build a Skill](../guides/build-a-skill.md), and [Manage Workspace](../guides/manage-workspace.md)."

---

## Agent: An AI Assistant Focused on a Specific Task

Think of Agents as different roles on a team. Each Agent has a clear responsibility and dedicated tools, and excels at handling a specific type of problem.

An Agent consists of three parts:

| Component | Description | Corresponding File |
|-----------|-------------|-------------------|
| **System Prompt** | Defines the Agent's role, behavioral guidelines, and output style | `system_prompt_file` in `AGENT.md` |
| **Toolset** | Functions the Agent can call (query databases, invoke APIs, execute code...) | Loaded via SubAgents and Skills |
| **Route Keywords** | When a user's question matches these keywords, OLAV automatically selects this Agent | `route_keywords` in `MANIFEST.yaml` |

### AGENT.md Example

```yaml
---
name: quick-orchestrator
description: "Quick Query Agent — fast SQL/CLI queries"
system_prompt_file: prompts/system.md
subagents: []
static_context:
  - path: ./references/SCHEMA_REFERENCE.md
---

## Overview
Quick Agent is the default entry point for OLAV.
It skips complex multi-step reasoning loops in favor of immediate, single-step responses.
```

The `static_context` field specifies reference materials (such as database schemas) that the Agent automatically loads on each run, helping the LLM understand the problem more accurately.

---

## Skill: A Toolkit That Gives Agents New Capabilities

A Skill is a collection of Python `@tool` functions that can be independently developed, installed, and shared. Skills fall into three categories by origin:

| Type | Description | Example |
|------|-------------|---------|
| **Built-in** | Shipped with OLAV | `core` (code execution), `config` (system management) |
| **Generated** | Auto-generated from OpenAPI by the Creator Agent | Zabbix tools, NetBox tools |
| **Custom** | Written by you, installed via `olav skill install` | Ticket queries, automation scripts |

### MANIFEST.yaml Example

```yaml
kind: Agent
name: quick
version: "0.11.0"
description: "Quick Agent — fast SQL queries, CLI execution, knowledge base search"
route_keywords:
  - quick query
  - show me
  - list devices
  - what is
  - how many
tools_dir: tools/
requires:
  - olav-platform>=0.11
```

`route_keywords` determines when the semantic router assigns a question to this Agent. `tools_dir` specifies the directory containing the tool functions.

---

## How Agents Load Tools

Agents acquire tools in two ways:

### Static Binding (Declared in AGENT.md)

```yaml
subagents:
  - path: ./creator/SKILL.md
  - path: ./knowledge/SKILL.md
```

Suitable for built-in, stable tool bindings. The Agent loads these sub-skills every time it starts.

### Dynamic Discovery (Via `olav skill install`)

```bash
olav skill install ./my-tools/
```

After installation, tools are written to `.olav/workspace/<name>/`. When OLAV starts an Agent, it automatically scans the workspace, discovers and injects all installed skill tools. No manual modification of AGENT.md is needed.

---

## Tool Call Loop

When you ask a question, the Agent's internal processing flow is as follows:

```
Your question
    |
Agent sees all available tools (each with a name and description)
    |
LLM decides which tool to call and passes in arguments
    |
Tool executes and returns results
    |
LLM analyzes results and decides whether more tools are needed
    |
Once all information is sufficient, synthesizes a final answer
    |
Each tool call is automatically written to the audit log
```

---

## Built-in Agents Overview

| Agent | Role | Strengths |
|-------|------|-----------|
| `quick` *(default)* | Quick query assistant | Single-step queries, one question one answer |
| `config` | System administrator | Service registration, skill generation, workspace health checks |
| `core` | Full-stack engineer | Code execution, SQL, Shell, web search |

```bash
olav list   # View all available Agents
```

---

## When Should You Create What?

| Need | Solution |
|------|----------|
| Add new capabilities to an existing Agent | Install a new **Skill** |
| Need a completely different AI assistant role | Create a new **Agent** (new AGENT.md) |
| Add a few tools to an existing Skill | `olav skill install --merge-into` |

In most scenarios, you only need to install a new Skill. You only need to create a new Agent when you require a different system prompt or different behavioral patterns.
