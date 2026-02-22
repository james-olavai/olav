# OLAV - Network Operations AI Assistant

**Version**: v0.9.9

OLAV is an AI-powered network operations assistant built on DeepAgents + LangGraph.

## Quick Start

```bash
# Interactive mode
uv run olav

# Single query (natural language)
uv run olav "How many devices are in the database?"

# Multi-agent support
uv run olav --agent ops "Check network status"

# Remote execution (sandbox)
uv run olav --sandbox modal "Deploy configuration"
```

## CLI Options (deepagents-cli compatible)

| Flag | Description |
|------|-------------|
| `--agent` | Agent identifier for separate memory stores |
| `--sandbox` | Remote sandbox (none, modal, daytona, runloop) |
| `--sandbox-id` | Existing sandbox ID to reuse |
| `--auto-approve` | Skip human-in-the-loop prompts |
| `--no-splash` | Disable startup banner |
| `--verbose` | Enable debug logging |

## Architecture

- **Framework**: DeepAgents + LangGraph
- **CLI**: Minimal deepagents-cli wrapper
- **Database**: DuckDB
- **Network**: Nornir + Netmiko

## Skills

OLAV uses skills loaded from `.olav/skills/`:

- `olav-ops` - Query operations (execute_sql, execute_cli)
- `olav-config` - Configuration management (sync, snapshot)
- `olav-audit` - Audit and compliance

## Design Philosophy

**Domain functionality through tools, not CLI commands:**

```bash
# ❌ Old way: Hardcoded CLI commands
olav devices
olav db status
olav inspect

# ✅ New way: Natural language + tools
olav "List all devices"
olav "Show database status"
olav "Run a network snapshot"
```

The Agent automatically selects the appropriate tool based on the query.

## License

MIT
