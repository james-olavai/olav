# ☃️ OLAV - Network Operations AI Assistant

**Version**: v0.9.8  
**Status**: ✅ Production Ready  
**Framework**: DeepAgents Native

OLAV is an intelligent, **agentic** network assistant designed for production environments. It bridges the gap between **generative AI** and **deterministic network automation** (Nornir/Netmiko).

**[中文文档 (Chinese)](README_ZH.md)** | **[English Documentation](README_ZH.md)**

---

## Quick Start

```bash
# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your LLM API key and device credentials

# Run interactive CLI
uv run olav

# Or ask a question directly
uv run olav ask "show all BGP neighbors status"
```

## Features

- 🧠 **Agentic System** - Goal-oriented autonomous agents with planning, execution, and self-correction
- 🔄 **Claude Code Compatible** - Standard `.olav/` structure (compatible with `.claude/`)
- 📊 **Structured Parsing** - TextFSM templates for CLI output → JSON schema
- 🔐 **Enterprise Security** - 3-tier knowledge architecture + HITL approval gates
- 🚀 **Production Ready** - Real-world tested with multi-vendor networks

## Architecture

```
User Query → Orchestrator → SubAgents (Query/Expert/CLI/Analysis)
              ↓
           Tools (Nornir/DuckDB/TextFSM/LLM)
              ↓
           Structured Output (CSV/JSON/Markdown)
```

## Documentation

See [README_ZH.md](README_ZH.md) for comprehensive documentation (Chinese).

## Testing

```bash
# Unit tests
uv run pytest tests/unit/ -v

# E2E tests (requires LLM API key)
uv run pytest tests/e2e/ -v
```

## License

MIT License - See [LICENSE](LICENSE)
