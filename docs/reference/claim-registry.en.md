# Feature Claim Registry

This page is the single index of all Feature Claims for the OLAV platform. Each Claim corresponds to a verifiable platform capability.

**Methodology:** Doc-Driven Testing (see `dev_docs/22. WEB_AND_DOCS_SITE.md` §7)

```
Document claims feature → CLI verification → E2E test → Verified or Narrowed/Removed
```

**Status legend:**

- ✅ Verified — Passed CLI end-to-end verification, recorded in `dev_docs/23. CLI_VERIFICATION_LOG.md`
- ⬜ Pending — Code implemented, awaiting CLI verification
- ⚠️ Narrowed — Available under limited conditions; Claim scope has been narrowed
- 🔶 Env-Blocked — Requires an external environment (running service, CLAB, etc.) to verify

---

## Level 1 — Platform Core Capabilities

| ID | Claim | Doc Page | Status |
|----|-------|----------|--------|
| C-L1-01 | OLAV lets you control infrastructure with natural language | [Home](../index.md) | ✅ | v0.10.0 |

---

## Level 2 — Feature-Level Claims

### Basic Commands

| ID | Claim | CLI Command | Doc Page | Status | Version |
|----|-------|-------------|----------|--------|---------|
| C-L2-01 | CLI correctly reports version and system info | `olav version` | [Installation](../getting-started/installation.md) | ✅ | v0.10.0 |
| C-L2-02 | CLI lists all available Agents with descriptions | `olav list` | [First Query](../getting-started/first-query.md) | ✅ | v0.10.0 |
| C-L2-03 | List and switch the active workspace | `olav workspace list/use` | [Manage Workspaces](../guides/manage-workspace.md) | ✅ | v0.10.0 |
| C-L2-13 | Initialize project directory structure | `olav init` | [Installation](../getting-started/installation.md) | ✅ | v0.10.0 |
| C-L2-27 | Reset Agent conversation history | `olav reset --agent <name>` | [CLI Commands](cli.md) | ✅ | v0.10.0 |

### Skill Management

| ID | Claim | CLI Command | Doc Page | Status | Version |
|----|-------|-------------|----------|--------|---------|
| C-L2-04 | Install a Skill from a local directory | `olav skill install <path>` | [Build a Skill](../guides/build-a-skill.md) | ✅ | v0.10.0 |
| C-L2-25 | Install a Skill from a Git URL | `olav skill install <url>` | [Build a Skill](../guides/build-a-skill.md) | ✅ | v0.10.0 |
| C-L2-06 | Append tools to an existing workspace | `olav skill install --merge-into` | [Build a Skill](../guides/build-a-skill.md) | ✅ ⚠️ | v0.10.0 |
| C-L2-36 | List and view installed skill status | `olav skill list/status` | [Manage Workspaces](../guides/manage-workspace.md) | ✅ | v0.10.0 |
| C-L2-37 | Skills declaring Python dependencies auto-create an isolated venv | `requires_packages` in MANIFEST | [Build a Skill](../guides/build-a-skill.md) | ✅ | v0.10.0 |

### Service Registry

| ID | Claim | CLI Command | Doc Page | Status | Version |
|----|-------|-------------|----------|--------|---------|
| C-L2-19 | Register an OpenAPI service with one command | `olav registry register <url>` | [Connect a Service](../guides/connect-a-service.md) | ✅ | v0.10.0 |
| C-L2-20 | Creator Agent generates Skill code from OpenAPI | `olav --agent config "onboard..."` | [Creator Agent](../guides/creator-agent.md) | ✅ | v0.10.0 |

### Audit and Logs

| ID | Claim | CLI Command | Doc Page | Status | Version |
|----|-------|-------------|----------|--------|---------|
| C-L2-08 | Query audit logs and list recent operations | `olav log list/errors` | [Audit and Logs](../guides/audit-and-logs.md) | ✅ | v0.10.0 |
| C-L2-22 | Export audit data in training formats | `olav log export trajectory/sft/atif` | [Audit and Logs](../guides/audit-and-logs.md) | ✅ | v0.10.0 |
| C-L2-12 | Multi-user concurrent audit with no write conflicts | 5 concurrent `olav log list` | [Audit and Logs](../guides/audit-and-logs.md) | ✅ | v0.10.0 |

### Background Services

| ID | Claim | CLI Command | Doc Page | Status | Version |
|----|-------|-------------|----------|--------|---------|
| C-L2-16 | Web service provides browser UI and REST API | `olav service web start` | [Background Services](../guides/services.md) | ✅ | v0.10.0 |
| C-L2-17 | Daemon accelerates CLI responses | `olav service daemon start` | [Background Services](../guides/services.md) | ✅ | v0.10.0 |
| C-L2-18 | Syslog receiver accepts network device logs | `olav service logs start` | [Background Services](../guides/services.md) | ✅ | v0.10.0 |

### HTTP API

| ID | Claim | CLI Command | Doc Page | Status | Version |
|----|-------|-------------|----------|--------|---------|
| C-L2-29 | SSE streaming query endpoint | `POST /runs/stream` | [HTTP API](http-api.md) | ✅ | v0.10.0 |
| C-L2-30 | Multi-turn conversation thread management | `POST /threads` | [HTTP API](http-api.md) | ✅ | v0.10.0 |

### Interactive Mode

| ID | Claim | CLI Command | Doc Page | Status | Version |
|----|-------|-------------|----------|--------|---------|
| C-L2-14 | TUI interactive mode supports multi-turn conversations | `olav` (no arguments) | [First Query](../getting-started/first-query.md) | ✅ | v0.10.0 |
| C-L2-15 | Resume a previous session | `olav --session <id>` | [First Query](../getting-started/first-query.md) | ✅ | v0.10.0 |
| C-L2-24 | /trace-review analyzes failure patterns and writes to memory | `/trace-review` | [Self-Improving Loop](../concepts/self-improving-loop.md) | ✅ | v0.10.0 |
| C-L2-26 | Skip tool call confirmation | `olav --auto-approve` | [Using Agents](../guides/using-agents.md) | ✅ | v0.10.0 |

### Knowledge Base and Memory

| ID | Claim | CLI Command | Doc Page | Status | Version |
|----|-------|-------------|----------|--------|---------|
| C-L2-21 | Knowledge base indexes documents and supports semantic search | `olav --agent config "index..."` | [Knowledge Base](../guides/knowledge-base.md) | ✅ | v0.10.0 |

### Users and Authentication

| ID | Claim | CLI Command | Doc Page | Status | Version |
|----|-------|-------------|----------|--------|---------|
| C-L2-23 | Admin creates/manages users and tokens | `olav admin "add-user..."` | [Users and Roles](users-and-roles.md) | ✅ | v0.10.0 |
| C-L2-28 | Supports multiple authentication modes | `auth.mode` config | [Security Model](../concepts/security-model.md) | ✅ | v0.10.0 |

### Core Agent Tools

| ID | Claim | CLI Command | Doc Page | Status | Version |
|----|-------|-------------|----------|--------|---------|
| C-L2-31 | Core Agent executes Python code | `olav --agent core "run python:..."` | [Core Agent](../guides/core-agent.md) | ✅ | v0.10.0 |
| C-L2-32 | Core Agent executes SQL queries | `olav --agent core "what tables..."` | [Core Agent](../guides/core-agent.md) | ✅ | v0.10.0 |
| C-L2-33 | Core Agent web search | `olav --agent core "search:..."` | [Core Agent](../guides/core-agent.md) | ✅ | v0.10.0 |
| C-L2-34 | Core Agent executes shell commands | `olav --agent core "run: df -h"` | [Core Agent](../guides/core-agent.md) | ✅ | v0.10.0 |
| C-L2-35 | Config Agent workspace health check | `olav --agent config "health check"` | [Core Agent](../guides/core-agent.md) | ✅ | v0.10.0 |

### Export and Integration

| ID | Claim | CLI Command | Doc Page | Status | Version |
|----|-------|-------------|----------|--------|---------|
| C-L2-10 | Export Claude-compatible plugin | `olav export claude-plugin` | [CLI Commands](cli.md) | ✅ | v0.10.0 |
| C-L2-11 | Auto-truncate large API responses | Python SDK | [CLI Commands](cli.md) | ✅ | v0.10.0 |

### Configuration

| ID | Claim | CLI Command | Doc Page | Status | Version |
|----|-------|-------------|----------|--------|---------|
| C-L2-38 | Assign different LLM models to different Agents | `agent_overrides` in api.json | [Configuration](configuration.md) | ✅ | v0.10.0 |
| C-L2-39 | Environment variables override config file | `OLAV_LLM_*` | [Configuration](configuration.md) | ✅ | v0.10.0 |
| C-L2-40 | `olav log show <run-id>` displays full event sequence | `olav log show <id>` | [Audit and Logs](../guides/audit-and-logs.md) | ✅ | v0.10.0 |
| C-L2-41 | Service management: status / start --all / stop --all | `olav service status/start --all/stop --all` | [Background Services](../guides/services.md) | ✅ | v0.10.0 |
| C-L2-42 | Web API introspection: /openapi.json, /docs, /threads/search | `GET /openapi.json` `GET /docs` | [HTTP API](http-api.md) | ✅ | v0.10.0 |
| C-L2-43 | `olav workspace status` shows Agent status | `olav workspace status` | [Manage Workspaces](../guides/manage-workspace.md) | ✅ | v0.10.0 |
| C-L2-44 | Admin rotate-token and add-user --expires | `olav admin "rotate-token <n>"` | [Users and Roles](users-and-roles.md) | ✅ | v0.10.0 |
| C-L2-45 | Audit database queryable directly via DuckDB | `duckdb .olav/databases/audit.duckdb` | [Audit and Logs](../guides/audit-and-logs.md) | ✅ | v0.10.0 |
| C-L2-46 | `/model <name>` switches LLM model within a session | TUI: `/model gpt-4o-mini` | [CLI Reference](cli.md) | ✅ | v0.10.0 |
| C-L2-47 | `@file.txt` file content injection | TUI: `@/path/to/file.txt` | [CLI Reference](cli.md) | ✅ | v0.10.0 |
| C-L2-48 | `!command` shell passthrough | TUI: `!echo hello` | [CLI Reference](cli.md) | ✅ | v0.10.0 |
| C-L2-49 | `--sandbox modal/daytona/runloop` remote sandbox flag | `olav --sandbox modal version` | [Agent Harness](../concepts/agent-harness.md) | ✅ | v0.10.0 |
| C-L2-50 | `olav registry list/refresh/status` | `olav registry list` | [Connect a Service](../guides/connect-a-service.md) | ✅ | v0.10.0 |
| C-L2-51 | `olav config evolve --list/--approve` | `olav config evolve --list` | [CLI Reference](cli.md) | ✅ | v0.10.0 |

---

## Statistics

| Status | Count |
|--------|-------|
| ✅ Verified | 50 |
| ⬜ Pending | 0 |
| 🔶 Env-Blocked | 0 |
| **Total** | **50** |

---

## Verification Process

```bash
# For each ⬜ Claim:
# 1. Run the CLI command
olav <command for the claim>

# 2. Record the result in dev_docs/23. CLI_VERIFICATION_LOG.md
# 3. Pass → change status to ✅, add version number
# 4. Fail → fix code, narrow the claim, or remove the Claim

# For 🔶 Claims: set up the environment first (LLM API Key / running external service)
```
