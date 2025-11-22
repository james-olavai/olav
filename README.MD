# OLAV (Omni-Layer Autonomous Verifier)

Enterprise Network Operations ChatOps Platform using LangGraph + DeepAgents.

## Quick Start

```bash
# Install dependencies
uv sync --dev

# Start Docker infrastructure
docker-compose up -d opensearch postgres redis

# Initialize databases
docker-compose --profile init up olav-init

# Run CLI
uv run python -m olav.main chat

# Run tests
uv run pytest
```

## Architecture

- **Schema-Aware Design**: Zero tool proliferation via dynamic schema discovery
- **Funnel Debugging (漏斗式排错)**: Macro (SuzieQ) → Micro (NETCONF)
- **HITL Safety**: Human-in-the-Loop for all write operations
- **DeepAgents**: Multi-agent orchestration with SubAgent pattern

See `DESIGN.md` for full architecture details.
