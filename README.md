<p align="center">
  <img src="src/olav_logo.png" alt="OLAV Logo" width="200">
</p>

<h1 align="center">OLAV 🐺</h1>

<p align="center">
  <strong>Online Analytical Vertex for Agentic Operations</strong><br>
  AI-native platform for autonomous infrastructure operations.
</p>

<p align="center">
  <a href="https://pypi.org/project/olav/">
    <img src="https://img.shields.io/badge/version-v0.22.0-blue" alt="Version">
  </a>
  <a href="">
    <img src="https://img.shields.io/badge/license-BSL--1.1-green" alt="License">
  </a>
  <a href="">
    <img src="https://img.shields.io/badge/python-3.11+-yellow" alt="Python">
  </a>
  <a href="https://docs.olavai.com">
    <img src="https://img.shields.io/badge/docs-docs.olavai.com-blue" alt="Docs">
  </a>
  <a href="https://olavai.com">
    <img src="https://img.shields.io/badge/website-olavai.com-blueviolet" alt="Website">
  </a>
</p>

<p align="center">
  <a href="src/README_ZH.md">中文文档</a>
</p>

> Control your infrastructure with natural language. Connect any REST API in one command, query it instantly, generate environment-aware automation scripts — no MCP servers, no code generation, no runtime complexity.

```bash
pip install olav
olav                                              # first run sets itself up — just paste your LLM key
olav registry register http://netbox:8000        # connect any API
olav "how many devices are in NetBox?"            # query immediately
olav --agent netops "write a backup script"          # generate real scripts
```

[Quick Start](#quick-start) | [Docs](https://docs.olavai.com) | [中文](src/README_ZH.md)

---

## Why OLAV?

### API-as-Service — Beyond MCP

MCP requires a server process per service, stdio/HTTP transport, and framework-specific adapters. OLAV takes a different approach:

```
MCP:   Service → MCP server process → stdio/HTTP → adapter → agent
OLAV:  Service → olav registry register → reference markdown → api_request → done
```

One command. No server processes. No generated code. No runtime overhead.

```bash
# Register once
olav registry register http://netbox:8000

# Query from any agent, forever
olav "how many devices are in NetBox?"
olav --agent netops "compare OLAV database vs NetBox — are they in sync?"
```

The `api_request` tool is **schema-aware** — it reads API reference docs generated at registration time, handles pagination (DRF/NetBox style), and manages auth (JWT/Bearer/API-key) automatically.

### Three Agents — Strict Tool Isolation

```
olav "list all devices"                  → Core Agent (database + knowledge base)
olav --agent netops "simulate link failure" → Ops Agent (network operations + SSH)
olav --agent audit "run health check"    → Audit Agent (compliance + learning)
```

Core agent uses a **subagent architecture** — the orchestrator sees only 5 tools:

```
core orchestrator (5 tools: execute_sql, olav_recall_memory, web_search, format_and_export, olav_delegate)
  ├── db_query    — database queries, knowledge base, web search, export
  ├── api_query   — API requests, health checks, web search, export
  ├── remote      — SSH to servers, local shell commands
  └── admin       — platform management, deployment, cron
```

Each subagent has **only the tools it needs**. `execute_sql` and `api_request` are in different subagents — the LLM cannot confuse them. Principle of least authority, enforced by the harness.

### 7-Layer Write Security

AI agents that can write to production need more than HITL approval:

| Layer | Defense | Bypassable? |
|-------|---------|:-----------:|
| `--enable-api-write` | Write mode locked by default | No |
| `services.yaml readonly_only` | Per-service read/write control | Config only |
| Dry-run simulation | Must pass before approval offered | No |
| HITL approval | User sees diff, then confirms | **Not skippable** |
| `sandbox_guard hard_block` | HTTP writes in isolated sandbox | **Not skippable** |
| `unshare --net` | Kernel-level network isolation | **Not skippable** |
| Audit trail | Every api_request logged | — |

`--dangerously-skip-permissions` bypasses tool approval for testing — but **cannot** bypass API write approval. Network devices are always read-only.

### Agent Harness — The OS for AI Agents

Every agent decision passes through a mandatory execution control layer:

```
Layer 0: AAA        Token/LDAP/OIDC auth → RBAC → full audit trail
Layer 1: Middleware  HITL interception + memory injection
Layer 2: Sandbox    Pre-scan → DuckDB read-only → network namespace isolation
Layer 3: Output     Credential redaction + SSE encoding
```

### Self-Improving Loop

```
Use OLAV → audit log captures every tool call
    → failure patterns extracted → written to LanceDB memory
    → future runs recall constraints before acting
```

Export as SFT/trajectory training data: `olav log export sft`.

### The Software Understands You — Not the Other Way Around

You should never need to read a manual before OLAV is useful, and never
need to hand-edit JSON to recover from a mistake:

- **Zero-ritual onboarding** — the first bare `olav` builds everything
  itself (directories, databases, agents, local embedding model) and asks
  for exactly one thing: your LLM API key. No separate init step, no
  config file editing.
- **A first screen that knows your state** — instead of generic tips, the
  welcome screen tells you what's actually true: *"embedding backend
  unavailable — memory features limited"*, *"netops installed but no
  device data yet — import a snapshot"*, *"welcome back — last time:
  'why is R1's BGP flapping?'"*.
- **Health checks anywhere** — `olav doctor` from the shell or `/doctor`
  inside the TUI: zero-LLM probes of scaffolding, LLM, and embedding,
  each failure paired with the fix.
- **Change config by talking** — *"switch my LLM to deepseek-chat"* is
  validated against the live provider **before** it's saved; a bad key or
  model name is rejected with the real error and your working config
  untouched. Every change snapshots the previous one — *"rollback my LLM
  config"* undoes it.
- **Undo for agent actions** — file writes and cron changes are
  journaled; *"undo that"* reverts the most recent one.
- **Failures tell you what to do next** — a mid-session 401 or quota
  error prints the diagnosis path and the rollback phrase, not a stack
  trace.

---

## Quick Start

```bash
# 1. Install
pip install olav

# 2. Run — first launch sets everything up and asks for your LLM API key
olav

# 3. Connect a service
olav registry register http://netbox:8000

# 4. Query
olav "how many devices are in NetBox?"
```

> Scripted/CI setup: `olav init` still performs the same bootstrap
> non-interactively (set `OPENAI_API_KEY` or edit `.olav/config/api.json`
> for the key). Check any installation's health with `olav doctor`.

### Network Operations (optional)

```bash
olav agent install /path/to/olav-netops/          # adds netops + devops workspaces
                                                   # (legacy alias: `olav skill install`)

olav --agent netops "/netops_init"                 # collect device data via SSH
olav --agent netops "simulate R2 link failure"     # What-If analysis
olav --agent netops "deploy digital twin"          # ContainerLab validation
```

### Other Interfaces

```bash
olav                            # interactive TUI
olav service start --all        # web UI at localhost:2280
olav --agent core "run: df -h"  # shell commands via Core Agent
```

---

## Architecture

```
olav v0.18.0 (pip install olav)
├── core orchestrator (5 tools)
│   ├── db_query    — execute_sql, olav_recall_memory, web_search, format_and_export
│   ├── api_query   — api_request, service_health, web_search, format_and_export
│   ├── remote      — remote_execute (SSH), run_shell
│   └── admin       — workspace_health, bulk_ingest, deploy/stop_service, cron, ...
│
olav-netops v0.19.0 (olav agent install olav-netops/)
├── netops orchestrator
│   ├── probe    — Parallel SSH with command whitelist (Nornir)
│   ├── analysis — Dijkstra + ECMP simulation (networkx)
│   ├── diff     — Cross-snapshot drift detection
│   └── lab      — ContainerLab digital twin + commit-validate
├── audit
│   ├── design   — Compliance profiles + health reports
│   └── learn    — TextFSM template learning
└── netops.*     — DuckDB tables + TextFSM collection pipeline
```

**Tech Stack**: LangChain · LangGraph · DeepAgents · DuckDB · LanceDB · FastAPI · NetworkX

---

## Documentation

**Docs**: [docs.olavai.com](https://docs.olavai.com) · **Website**: [olavai.com](https://olavai.com)

---

## License

[BSL-1.1](LICENSE) — Business Source License 1.1
