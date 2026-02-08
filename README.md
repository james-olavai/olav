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

### For Users
- **[中文文档 (Chinese)](README_ZH.md)** - Comprehensive user documentation
- **Quick Start** - See above

### For Developers
- **[Developer Documentation Index](docs/DEVELOPER_INDEX.md)** - 📚 **Complete developer guide hub**
- **[Sub-Agent Development](docs/SUB_AGENT_DEVELOPMENT_GUIDE.md)** - Build new agents
- **[Skill Authoring](docs/02_skill_authoring_guide.md)** - Write SKILL.md files
- **[Testing Guide](docs/TESTING_QUICK_REFERENCE.md)** - Write and run tests

See [Developer Index](docs/DEVELOPER_INDEX.md) for complete documentation navigation.

## Testing

```bash
# Unit tests
uv run pytest tests/unit/ -v

# E2E tests (requires LLM API key)
uv run pytest tests/e2e/ -v
```

## License

MIT License - See [LICENSE](LICENSE)
