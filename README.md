# OLAV

**Enterprise AI-native platform for autonomous infrastructure operations.**

[![Version](https://img.shields.io/badge/version-v0.10.0-blue)]()
[![License](https://img.shields.io/badge/license-BSL--1.1-green)]()
[![Python](https://img.shields.io/badge/python-3.11+-yellow)]()
[![Docs](https://img.shields.io/badge/docs-docs.olavplatform.com-informational)](https://docs.olavplatform.com)

> Control your infrastructure with natural language. Connect any API, deploy specialized AI agents, orchestrate operational workflows — without writing SQL or memorizing CLI flags.

```bash
olav "how many devices are online?"
olav "which BGP neighbors are down?"
olav --agent core "run a health check on all endpoints"
```

[Documentation](https://docs.olavplatform.com) | [Quick Start](#quick-start) | [中文](README_ZH.md)

---

## Why OLAV?

### API-as-Tool — Any API Becomes an Agent Tool in One Command

No code, no MCP servers. Register an OpenAPI service once, query it in natural language forever:

```bash
olav registry register http://netbox.example.com/api/schema/
olav "how many devices are in rack A1?"   # works immediately
```

The Creator Agent can also generate editable Python `@tool` functions from any OpenAPI schema for deep customization.

### Agent Harness — Four-Layer Execution Governance

Every Agent decision passes through a mandatory execution control layer:

```
Layer 0: AAA        Token/LDAP/OIDC auth → RBAC → full audit trail
Layer 1: Middleware  HITL dangerous-command interception + memory injection
Layer 2: Sandbox    Pre-scan → DuckDB read-only enforcement → network namespace isolation
Layer 3: Output     Credential auto-redaction + SSE JSON encoding + HttpOnly cookies
```

Hard constraints (DuckDB read-only) cannot be bypassed. Soft constraints (injection scanning, network isolation) are configurable.

### Self-Improving Loop — Agents Get Better Over Time

```
Use OLAV → audit log captures every tool call and error
    → /trace-review extracts failure constraints → writes to LanceDB memory
    → future runs recall constraints before acting → known pitfalls avoided
```

Data-driven improvement, not manual prompt tuning. Export audit traces as SFT / Trajectory / ATIF training data to fine-tune your own models.

### Multi-Layer Cache — Measured 2000x+ Speedup

```
Tier-0: SemanticCache (LanceDB vector similarity, ~10ms)
Tier-1: LLM SQLiteCache (exact prompt match, <1ms, 0 tokens)
Tier-2: LLM API call (real network request)
```

Per-user isolation. Anthropic models automatically use prompt caching (system prompt billed once).

### Federated Specialist Agents

Not one omniscient Agent — **multiple specialists collaborating**:

- Semantic router dispatches queries to the best-fit Agent based on `route_keywords`
- Each Agent holds only its own tools (least privilege)
- Per-Agent model assignment: cheap models for frequent queries, powerful models for complex analysis — 40-70% token cost reduction
- Hot-swappable Skills: `olav skill install` extends capabilities instantly

### Enterprise AAA — Authentication, Authorization, Audit

- **Auth**: none / token / LDAP / AD / OIDC; tokens stored as salted SHA256 hashes
- **RBAC**: 3 roles (admin/user/readonly) × 5 actions, fine-grained per Agent/Skill
- **Audit**: Every operation recorded to DuckDB (4 tables), SHA256 tamper-proofing (NIST AU-9), credentials auto-redacted

### Full-Stack Observability — Audit as Data Asset

Audit logs are not just compliance — they're a **continuously growing data asset**:

- Query any dimension with DuckDB SQL (token usage, cache hit rate, tool call frequency, error patterns)
- Export to training data; swap in fine-tuned models by changing one field in `api.json`
- Multi-user concurrent-safe (DuckDB atomic writes, each record tagged with `user_id`)

---

## Quick Start

```bash
# Install
git clone https://github.com/olav-ai/olav.git && cd olav
uv sync

# Initialize
olav init

# Configure LLM (edit .olav/config/api.json or use env vars)
export OLAV_LLM_API_KEY="sk-..."
export OLAV_LLM_MODEL="gpt-4o"

# Run
olav "how many devices are in the database?"
olav                          # interactive TUI
olav service web start        # web UI at http://localhost:2280
```

See [Installation Guide](https://docs.olavplatform.com/getting-started/installation/) for details.

---

## Three Interfaces

| Interface | Command | Best For |
|-----------|---------|----------|
| **CLI** | `olav "your query"` | Scripting, one-off queries, CI/CD |
| **TUI** | `olav` | Multi-turn conversations, exploration |
| **Web UI** | `olav service web start` | Team sharing, browser access |

---

## Architecture

```
User Query
    ↓
Semantic Router → selects best Agent (or --agent override)
    ↓
Agent Harness → AAA → Middleware → Sandbox
    ↓
LLM + Tool Loop (calls tools, gets results, synthesizes response)
    ↓
Response + Audit Log (automatic, every run)
```

**Tech Stack**: LangChain + LangGraph + DeepAgents + DuckDB + LanceDB + FastAPI

---

## Repository Structure

```
src/olav/          ← OLAV core platform (this repo)
olav-netops/       ← Network operations extension (separate package, public)
olav-ent/          ← Enterprise features (separate package, private)
docs/              ← Documentation (EN/ZH bilingual, MkDocs Material)
tests/             ← E2E acceptance tests + unit tests
.olav/workspace/   ← Agent & Skill definitions (committed to git)
.olav/config/      ← Runtime config (gitignored — contains API keys)
.olav/databases/   ← Runtime data (gitignored — audit logs, domain data)
```

---

## Documentation

Full documentation at **[docs.olavplatform.com](https://docs.olavplatform.com)** (English + Chinese):

- [Getting Started](https://docs.olavplatform.com/getting-started/installation/) — Install and run your first query
- [Guides](https://docs.olavplatform.com/guides/connect-a-service/) — Connect services, build skills, manage workspaces
- [Concepts](https://docs.olavplatform.com/concepts/agents-and-skills/) — Agents, Skills, Security Model, Agent Harness
- [Reference](https://docs.olavplatform.com/reference/cli/) — CLI, Configuration, HTTP API

---

## License

[BSL-1.1](LICENSE) — Business Source License 1.1
