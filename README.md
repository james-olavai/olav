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
    <img src="https://img.shields.io/badge/version-v0.13.0-blue" alt="Version">
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
olav registry register http://netbox:8000      # connect any API
olav --agent infra "how many devices in NetBox?" # query immediately
olav --agent devops "write a backup script"      # generate real scripts
```

[Quick Start](#quick-start) | [Blog: v0.13 Release](https://olavai.com/blog/olav-v013) | [中文](src/README_ZH.md)

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
olav --agent infra "compare OLAV database vs NetBox — are they in sync?"
```

The `api_request` tool is **schema-aware** — it reads API reference docs generated at registration time, handles pagination (DRF/NetBox style), and manages auth (JWT/Bearer/API-key) automatically.

### Six Specialized Agents — Not One Omniscient Model

```
olav "quick question"                    → Quick Agent (80% of daily use)
olav --agent infra "query NetBox"        → Infra Agent (API read + write)
olav --agent devops "write a script"     → DevOps Agent (environment-aware)
olav --agent ops "simulate link failure" → Ops Agent (network operations)
olav --agent audit "run health check"    → Audit Agent (compliance reports)
```

Each agent has **only the tools it needs**. The analysis agent can't SSH to devices. The infra agent can't modify the network. Principle of least authority, enforced by the harness.

### DevOps Agent — Scripts for YOUR Infrastructure

The DevOps agent doesn't write templates. It queries your actual database first:

```bash
olav --agent devops "write a script to backup all router configs"
```

It discovers R1 (192.168.100.101, Juniper), R2-R4 (Cisco IOS), SW1-SW2, then generates a 158-line bash script with:
- Platform-specific commands (`show run` vs `show configuration`)
- `--dry-run` flag, error handling, dependency checks
- Exported to `exports/scripts/backup-configs.sh` — a real file, not chat text

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

7,650+ audit messages captured. Export as SFT/trajectory training data: `olav log export sft`.

---

## Quick Start

```bash
# 1. Install
pip install olav

# 2. Initialize
olav init

# 3. Configure LLM
export OLAV_LLM_API_KEY="sk-..."

# 4. Connect a service
olav registry register http://netbox:8000

# 5. Query
olav "how many devices are in NetBox?"

# 6. Generate scripts
olav --agent devops "write a backup script for all routers"
```

### Network Operations (optional)

```bash
pip install olav-netops

olav --agent ops "/netops_init"                    # collect device data via SSH
olav --agent ops "simulate R2 link failure"        # What-If analysis
olav --agent ops-lab "deploy digital twin"         # ContainerLab validation
```

### Other Interfaces

```bash
olav                            # interactive TUI
olav service web start          # web UI at localhost:2280
olav --agent core "run: df -h"  # shell commands via Core Agent
```

---

## Architecture

```
olav v0.13 (pip install olav)
├── core     — Tools: api_request, execute_sql, sandbox, export
├── quick    — Fast queries (default agent)
├── infra    — API read + write (--enable-api-write)
├── devops   — Environment-aware script generation
├── audit    — Compliance profiles + health reports
└── config   — Platform management

olav-netops v0.13 (pip install olav-netops)
├── ops orchestrator
│   ├── analysis — Dijkstra + ECMP simulation (networkx)
│   ├── probe    — Parallel SSH with command whitelist (Nornir)
│   ├── diff     — Cross-snapshot drift detection
│   └── lab      — ContainerLab digital twin + commit-validate
└── netops.*     — DuckDB tables + TextFSM collection pipeline
```

**Tech Stack**: LangChain · LangGraph · DeepAgents · DuckDB · LanceDB · FastAPI · NetworkX

---

## By the Numbers

| Metric | Value |
|--------|:-----:|
| Tests | 1,358 passing |
| DDD Claims | 44 verified |
| Issues closed | 62+ |
| Doc pages | 28 (EN + ZH) |
| Audit messages | 7,650+ |

---

## Documentation

**Docs**: [docs.olavai.com](https://docs.olavai.com) · **Website**: [olavai.com](https://olavai.com) · **Blog**: [v0.13 Release](https://olavai.com/blog/olav-v013)

---

## License

[BSL-1.1](LICENSE) — Business Source License 1.1
