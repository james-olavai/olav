# OLAV v0.8.0 - Release Notes

## Summary

OLAV v0.8.0 is a production-ready, enterprise-grade Network Operations AI Assistant built on the DeepAgents framework. This release provides comprehensive network automation capabilities with human-in-the-loop safety features.

## What's New in v0.8.0

### Core Features
- **Agentic AI Architecture**: Built on DeepAgents for autonomous planning and execution
- **Multi-Vendor Support**: Cisco, Huawei, Juniper, Arista, and SSH-compatible devices
- **TextFSM Integration**: Automatic structured output parsing from CLI commands
- **Human-in-the-Loop**: Mandatory approval for sensitive operations
- **RAG Knowledge Base**: Embedding-powered semantic search for network knowledge
- **3-Layer Knowledge Brain**: Skills (procedures), Knowledge (facts), Capabilities (tools)

### Code Quality
- **79.75% Test Coverage**: 864 unit tests, all passing
- **Zero Linting Errors**: Clean ruff and pyright checks
- **Type Safety**: Comprehensive type annotations with pyright validation
- **Security Hardened**: No hardcoded secrets, proper .gitignore configuration

### Installation Improvements
- **Dual Installation Methods**: Support for both `uv` (fast) and `pip/venv` (standard)
- **Enhanced Documentation**: Clear step-by-step setup instructions
- **Template Files**: `.env.example` and `hosts.yaml.example` for easy configuration

## Installation

### Quick Start (uv - Recommended)
```bash
pip install uv
uv sync
cp .env.example .env
# Edit .env with your API keys
cp .olav/config/nornir/hosts.yaml.example .olav/config/nornir/hosts.yaml
# Edit hosts.yaml with your devices
uv run python scripts/init.py
uv run olav
```

### Standard Installation (pip/venv)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Edit .env with your API keys
cp .olav/config/nornir/hosts.yaml.example .olav/config/nornir/hosts.yaml
# Edit hosts.yaml with your devices
python scripts/init.py
olav
```

## Requirements

- **Python**: 3.11 or higher
- **LLM API**: OpenAI, OpenRouter, or local Ollama
- **Network Devices**: SSH-accessible network gear
- **Database**: DuckDB (included)

## Configuration

### Environment Variables (.env)
- `LLM_PROVIDER`: openai, ollama
- `LLM_API_KEY`: Your LLM provider API key
- `LLM_MODEL_NAME`: Model to use (e.g., gpt-4, llama3)
- `EMBEDDING_PROVIDER`: ollama, openai
- `EMBEDDING_MODEL`: Embedding model (e.g., nomic-embed-text)

### Network Inventory (hosts.yaml)
Define devices with:
- hostname
- platform (cisco_ios, huawei_vrp, juniper_junos, etc.)
- credentials
- groups

## Documentation

- **User Guide**: README.MD
- **Architecture**: docs/DESIGN_V0.8.md
- **Quick Start**: docs/QUICKSTART_V0.8.md
- **Chinese Guide**: README_ZH.md

## Testing

Run tests:
```bash
# Unit tests
pytest tests/unit/

# With coverage
pytest tests/unit/ --cov=src/olav --cov-report=html

# Specific test file
pytest tests/unit/test_database.py -v
```

## Linting & Type Checking

```bash
# Ruff linting
ruff check src/

# Auto-fix issues
ruff check --fix src/

# Pyright type checking
pyright src/
```

## Security

- **No Hardcoded Secrets**: All credentials via environment config
- **Gitignored Files**: .env, hosts.yaml, settings.json, databases
- **Command Whitelisting**: Only approved commands can execute
- **HITL Gates**: Sensitive operations require human approval
- **Prompt Guard**: Blocks non-network queries

## Known Limitations

1. **CLI Entry Points**: Lower test coverage for interactive CLI components (acceptable)
2. **External Library Types**: Some type warnings from langchain/deepagents (expected)
3. **Print Statements**: Used throughout CLI tools (intentional for user feedback)

## Troubleshooting

### Import Errors
```bash
# Reinstall dependencies
pip install -e ".[dev]"
```

### Database Issues
```bash
# Reinitialize databases
python scripts/init.py --force
```

### Network Connection
```bash
# Test device connectivity
python -m olav.tools.network
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Write tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

MIT License - See LICENSE file for details

## Support

For issues, questions, or contributions, please visit the project repository.

---

**Version**: 0.8.0
**Release Date**: January 12, 2025
**Status**: Production Ready ✅
