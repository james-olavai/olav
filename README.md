# OLAV - Network Operations AI Assistant

**Version**: v0.9.9

OLAV is an AI-powered network operations assistant built on DeepAgents + LangGraph.

## Quick Start

```bash
# Interactive mode
uv run olav

# Single query
uv run olav ask "How many devices are in the database?"

# List devices
uv run olav devices

# Database operations
uv run olav db status
uv run olav db query "SELECT * FROM devices LIMIT 10"

# System status
uv run olav status
```

## Architecture

- **Framework**: DeepAgents + LangGraph
- **CLI**: argparse (deepagents-cli style)
- **Database**: DuckDB
- **Network**: Nornir + Netmiko

## Skills

OLAV uses skills loaded from `.olav/skills/`:

- `olav-ops` - Query operations
- `olav-config` - Configuration management
- `olav-audit` - Audit and compliance

## License

MIT
