# OLAV Configuration Reference

**Version**: v1.0.0  
**Date**: 2026-02-08

---

## 🎯 Overview

This document provides a complete reference for all configuration files, paths, and environment variables in OLAV.

**Configuration Priority Chain**:
```
.env (Environment variables)          ← Highest priority
  ↓
.olav/settings.json (User overrides)
  ↓
SKILL.md frontmatter (Task-specific)
  ↓
config/settings.py (Application defaults) ← Lowest priority
```

---

## 📂 Critical Paths

### Application Structure
```
Olav/
├── .olav/                          # OLAV runtime directory
│   ├── OLAV.md                     # SubAgent registry (main config)
│   ├── settings.json               # User overrides
│   ├── skills/                     # Skill configurations
│   │   ├── orchestrator/
│   │   │   └── SKILL.md
│   │   ├── network-query/
│   │   │   ├── SKILL.md
│   │   │   └── REFERENCE.md
│   │   ├── network-expert/
│   │   │   ├── SKILL.md
│   │   │   └── REFERENCE.md
│   │   ├── network-cli/
│   │   │   ├── SKILL.md
│   │   │   └── config/
│   │   ├── network-analysis/
│   │   │   └── SKILL.md
│   │   └── network-inspection/
│   │       ├── SKILL.md
│   │       └── REFERENCE.md
│   ├── config/
│   │   └── routing_rules.yaml      # Routing rules (legacy)
│   ├── db/                         # Databases
│   │   ├── main.duckdb             # Device metadata
│   │   ├── olav.duckdb             # CLI outputs, capabilities
│   │   └── snapshots.duckdb        # Query cache
│   ├── cache/                      # Cache storage
│   │   ├── semantic_cache.db       # Semantic cache (SQLite)
│   │   └── llm_cache.db            # LLM prompt cache (SQLite)
│   ├── knowledge/                  # Knowledge base (runtime)
│   │   ├── protocols/
│   │   ├── solutions/
│   │   └── cases/
│   ├── templates/                  # TextFSM templates
│   │   └── custom/
│   └── conversations/              # Conversation history
│
├── config/                         # Application config
│   ├── __init__.py
│   ├── paths.py                    # Path constants (READ THIS)
│   ├── settings.py                 # Settings schema (READ THIS)
│   ├── logging.py                  # Logging configuration
│   ├── structured_logging.py       # Structured logging
│   └── templates/                  # Rich console templates
│
├── src/olav/                       # Source code
│   ├── agents/                     # Agent implementations
│   ├── tools/                      # Tool functions
│   ├── core/                       # Core utilities
│   └── lib/                        # External integrations
│
├── tests/                          # Test suite
│   ├── e2e/                        # End-to-end tests
│   ├── integration/                # Integration tests
│   └── unit/                       # Unit tests
│
├── exports/                        # Export outputs
│   ├── reports/                    # Generated reports
│   └── snapshots/                  # Data snapshots
│
├── logs/                           # Application logs
│   └── olav.log
│
├── .env                            # Environment variables (NOT in Git)
├── .env.example                    # Environment template
├── pyproject.toml                  # Python project config
└── uv.lock                         # Dependency lock file
```

---

## ⚙️ Environment Variables (.env)

### LLM Configuration (Required)
```bash
# LLM API Configuration
LLM_API_KEY=sk-or-v1-xxx...              # API key for LLM provider
LLM_BASE_URL=https://openrouter.ai/api/v1  # Base URL (for OpenRouter, Groq, etc.)
LLM_MODEL_NAME=x-ai/grok-beta            # Model name

# OpenAI-compatible overrides (DeepAgents/LangChain expect these)
OPENAI_API_KEY=${LLM_API_KEY}            # Auto-set by agents
OPENAI_BASE_URL=${LLM_BASE_URL}          # Auto-set by agents
OPENAI_MODEL_NAME=${LLM_MODEL_NAME}      # Auto-set by agents (OpenRouter x-ai/ prefix)
```

### Database Configuration (Optional)
```bash
# DuckDB Paths (defaults in config/paths.py)
DB_MAIN_PATH=.olav/db/main.duckdb
DB_OLAV_PATH=.olav/db/olav.duckdb
DB_SNAPSHOTS_PATH=.olav/db/snapshots.duckdb

# Cache Configuration
CACHE_DB_PATH=.olav/cache/semantic_cache.db
LLM_CACHE_ENABLED=true
LLM_CACHE_PATH=.olav/cache/llm_cache.db
```

### Network Configuration (Nornir)
```bash
# Nornir Settings
NORNIR_GROUP=all                         # Device group to target
NORNIR_INVENTORY_PATH=.olav/skills/network-cli/config/inventory.yaml
NORNIR_LOG_LEVEL=INFO

# Device Credentials (encrypted recommended)
DEVICE_USERNAME=admin
DEVICE_PASSWORD=your_password
DEVICE_ENABLE_PASSWORD=your_enable_password
```

### Health Check Thresholds (Optional)
```bash
# Health Score Weights
CRITICAL_WEIGHT=3.0                      # Weight for critical issues
WARNING_WEIGHT=1.5                       # Weight for warnings
INFO_WEIGHT=0.5                          # Weight for info messages

# Health Thresholds
HEALTH_THRESHOLD_HEALTHY=90              # Healthy threshold (%)
HEALTH_THRESHOLD_WARNING=70              # Warning threshold (%)
HEALTH_THRESHOLD_CRITICAL=50             # Critical threshold (%)
```

### Logging Configuration (Optional)
```bash
# Logging
OLAV_LOG_LEVEL=INFO                      # DEBUG, INFO, WARNING, ERROR
OLAV_LOG_PATH=logs/olav.log
OLAV_LOG_FORMAT=structured               # structured or simple
```

---

## 📄 Configuration Files

### 1. .olav/OLAV.md (SubAgent Registry)

**Purpose**: Central registry for all SubAgents

**Format**:
```markdown
# OLAV Project Context

## SubAgent Registry

### query
```yaml
---
name: query
agent_skill: network-query              # Links to .olav/skills/network-query/
description: Database query specialist
capabilities:
  - Device inventory queries
  - SQL execution
enabled: true
---
```

### expert
```yaml
---
name: expert
agent_skill: network-expert
description: CCIE-level troubleshooting
capabilities:
  - Multi-domain expertise
  - Root cause analysis
enabled: true
---
```
```

**Key Fields**:
- `name`: SubAgent identifier (lowercase, hyphen-separated)
- `agent_skill`: Skill directory name (links to `.olav/skills/{agent_skill}/`)
- `description`: What the agent does and when to use it
- `capabilities`: List of agent capabilities
- `enabled`: Toggle agent on/off (no code changes)

**Loading**: `src/olav/core/subagent_loader.py::load_subagents_from_olav()`

---

### 2. .olav/skills/*/SKILL.md (Skill Configuration)

**Purpose**: Complete specification for a skill/agent

**Structure**:
```yaml
---
name: skill-name
description: Skill description
version: 1.0.0
intent: quick_query                      # Routing intent

# System Prompt
prompts:
  system: |
    You are a specialized network agent...
    
    ## Available Tools
    - tool1: Description
    - tool2: Description
    
    ## Response Format
    Always return results as markdown tables.

# Tool Registry
tools:
  - name: query_database
    module: olav.tools.react_query
    function: query_database
    description: Execute SQL queries
    
  - name: inspect_schema
    module: olav.tools.react_query
    function: inspect_schema
    description: Inspect database structure

# Caching Configuration
caching:
  enabled: true
  backend: semantic_cache
  ttl_seconds: 3600
  cache_key_fields: [query, schema_context]
  similarity_threshold: 0.85
  
# Agent Settings
agent:
  max_iterations: 10
  enable_summarization: false
  temperature: 0.1
  timeout_seconds: 120
---

# Skill Content (Markdown)

Additional guidance, examples, troubleshooting...
```

**Critical Sections**:
- `prompts.system`: System prompt (used by SubAgent)
- `tools`: Tool registry (dynamically loaded)
- `caching`: Cache configuration
- `agent`: Agent-specific parameters

**Loading**: 
- Prompt: `src/olav/core/subagent_loader.py::_load_from_skill()`
- Tools: `src/olav/core/skill_adapter.py::load_tools_from_skill()`

---

### 3. .olav/settings.json (User Overrides)

**Purpose**: User-specific overrides (not in Git)

**Format**:
```json
{
  "llm_api_key": "sk-or-v1-xxx...",
  "llm_base_url": "https://openrouter.ai/api/v1",
  "llm_model_name": "x-ai/grok-beta",
  
  "nornir_group": "all",
  "device_username": "admin",
  
  "health_threshold_healthy": 90,
  "critical_weight": 3.0,
  
  "log_level": "INFO",
  "enable_semantic_cache": true,
  "cache_ttl_seconds": 3600
}
```

**Loading**: `config/settings.py::Settings.model_validate()`

---

### 4. config/settings.py (Application Defaults)

**Purpose**: Application-level defaults and schema

**Key Classes**:
```python
class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # LLM Configuration
    llm_api_key: str = Field(default="", env="LLM_API_KEY")
    llm_base_url: str | None = Field(default=None, env="LLM_BASE_URL")
    llm_model_name: str = Field(default="gpt-4", env="LLM_MODEL_NAME")
    
    # Database Configuration
    db_main_path: str = Field(default=".olav/db/main.duckdb")
    db_olav_path: str = Field(default=".olav/db/olav.duckdb")
    
    # Cache Configuration
    llm_cache_enabled: bool = Field(default=True)
    semantic_cache_enabled: bool = Field(default=True)
    cache_ttl_seconds: int = Field(default=3600)
    
    # Agent Configuration
    agent: AgentSettings = Field(default_factory=AgentSettings)
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
```

**AgentSettings**:
```python
class AgentSettings(BaseModel):
    """Agent-specific settings."""
    enable_summarization: bool = False
    summarization_trigger_tokens: int = 4000
    summarization_keep_messages: int = 10
    max_iterations: int = 10
    timeout_seconds: int = 120
```

**Usage**:
```python
from config.settings import settings

api_key = settings.llm_api_key
model = settings.llm_model_name
```

---

### 5. config/paths.py (Path Constants)

**Purpose**: Centralized path definitions

**Critical Constants**:
```python
from pathlib import Path

# Project Root
PROJECT_ROOT = Path(__file__).parent.parent

# OLAV Directory
OLAV_DIR = PROJECT_ROOT / ".olav"
CONFIG_DIR = OLAV_DIR / "config"
SKILL_BASE_PATH = OLAV_DIR / "skills"

# Database Paths
DB_DIR = OLAV_DIR / "db"
DB_MAIN_PATH = DB_DIR / "main.duckdb"
DB_OLAV_PATH = DB_DIR / "olav.duckdb"
DB_SNAPSHOTS_PATH = DB_DIR / "snapshots.duckdb"

# Cache Paths
CACHE_DIR = OLAV_DIR / "cache"
CACHE_DB_PATH = CACHE_DIR / "semantic_cache.db"
LLM_CACHE_PATH = CACHE_DIR / "llm_cache.db"

# Export Paths
EXPORTS_DIR = PROJECT_ROOT / "exports"
REPORTS_DIR = EXPORTS_DIR / "reports"
SNAPSHOTS_DIR = EXPORTS_DIR / "snapshots"

# Knowledge Base
KNOWLEDGE_DIR = OLAV_DIR / "knowledge"

# User Checkpoints
USER_CHECKPOINT_PATH = OLAV_DIR / "checkpoints"

# Routing Rules (legacy)
ROUTING_RULES_PATH = CONFIG_DIR / "routing_rules.yaml"
```

**Usage**:
```python
from config.paths import DB_MAIN_PATH, SKILL_BASE_PATH

skill_path = SKILL_BASE_PATH / "network-query" / "SKILL.md"
```

---

## 🗄️ Database Configuration

### Database Files

| File | Path | Purpose | Tables |
|------|------|---------|--------|
| **main.duckdb** | `.olav/db/main.duckdb` | Device metadata | `devices` |
| **olav.duckdb** | `.olav/db/olav.duckdb` | CLI outputs | `raw_outputs`, `device_capabilities` |
| **snapshots.duckdb** | `.olav/db/snapshots.duckdb` | Query cache | `query_cache` (deprecated) |

### Unified Connection Pattern (Critical)

**Problem**: Three separate database files cause routing issues

**Solution**: Unified in-memory connection with ATTACH
```python
# src/olav/lib/data_gateway.py
def _create_unified_connection(self):
    """Create unified DuckDB connection with all databases attached."""
    conn = duckdb.connect(":memory:")
    
    # Attach all databases
    conn.execute(f"ATTACH '{DB_MAIN_PATH}' AS main (READ_ONLY)")
    conn.execute(f"ATTACH '{DB_OLAV_PATH}' AS olav (READ_ONLY)")
    conn.execute(f"ATTACH '{DB_SNAPSHOTS_PATH}' AS snapshots (READ_ONLY)")
    
    # Create compatibility views
    conn.execute("CREATE VIEW devices AS SELECT * FROM main.devices")
    conn.execute("CREATE VIEW raw_outputs AS SELECT * FROM olav.raw_outputs")
    
    return conn
```

**Benefits**:
- Cross-database JOINs
- Transparent routing
- No hardcoded database names in SQL

---

## 🔧 Tool Configuration

### Tool Registration

Tools are registered in SKILL.md:
```yaml
tools:
  - name: query_database              # Tool name (for LLM)
    module: olav.tools.react_query    # Python module
    function: query_database          # Function name
    description: Execute SQL queries  # Description for LLM
    
  - name: inspect_schema
    module: olav.tools.react_query
    function: inspect_schema
    description: Inspect database structure
```

### Tool Loading

**Dynamic Loading** via SkillAdapter:
```python
from olav.core.skill_adapter import SkillAdapter

adapter = SkillAdapter()
skill = loader.get_skill("network-query")
tools = adapter.load_tools_from_skill(skill)

# tools is now a list of callable functions
```

**Tool Discovery**:
1. Reads `tools` section from SKILL.md
2. Imports module: `importlib.import_module(tool.module)`
3. Gets function: `getattr(module, tool.function)`
4. Returns callable with metadata

---

## 💾 Cache Configuration

### Semantic Cache (.olav/cache/semantic_cache.db)

**Configuration** (in SKILL.md):
```yaml
caching:
  enabled: true
  backend: semantic_cache
  ttl_seconds: 3600                   # Cache lifetime
  cache_key_fields: [query, schema]   # What to hash
  similarity_threshold: 0.85          # Similarity for cache hit
```

**Implementation**: `src/olav/core/query_cache.py`

### LLM Cache (.olav/cache/llm_cache.db)

**Configuration** (in config/settings.py):
```python
llm_cache_enabled: bool = True
llm_cache_path: str = ".olav/cache/llm_cache.db"
```

**Implementation**: `src/olav/core/llm.py::LLMFactory.configure_cache()`

**Transparent**: No code changes needed, auto-caches LLM completions

---

## 🌐 Network Configuration (Nornir)

### Inventory File (.olav/skills/network-cli/config/inventory.yaml)

**Format**:
```yaml
---
# Nornir Inventory
groups:
  all:
    data:
      platform: cisco_ios
    connection_options:
      netmiko:
        extras:
          device_type: cisco_ios

hosts:
  router-01:
    hostname: 192.168.1.1
    groups: [all]
    data:
      vendor: cisco
      model: ISR4451
      
  switch-01:
    hostname: 192.168.1.2
    groups: [all]
    data:
      vendor: cisco
      model: C9300
```

**Environment Variables**:
```bash
NORNIR_GROUP=all                      # Which group to target
DEVICE_USERNAME=admin
DEVICE_PASSWORD=your_password
```

**Usage**:
```python
from olav.lib.ncm_client import NCMClient

client = NCMClient()
result = client.execute_commands(
    target="router-01",
    commands=["show version"]
)
```

---

## 📊 Logging Configuration

### config/logging.py

**Log Levels**:
- `DEBUG`: Verbose debugging (all LLM calls, tool invocations)
- `INFO`: Standard operations (query start/end, cache hits)
- `WARNING`: Potential issues (cache misses, retries)
- `ERROR`: Failures (tool errors, LLM failures)

**Configuration**:
```python
LOGGING_CONFIG = {
    "version": 1,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": "logs/olav.log",
            "formatter": "detailed",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console", "file"],
    },
}
```

**Environment Override**:
```bash
OLAV_LOG_LEVEL=DEBUG uv run olav ask "query"
```

---

## 🔐 Security Configuration

### API Keys

**Never commit**:
- `.env` file
- `.olav/settings.json`
- Any file with credentials

**Use**:
- Environment variables (`.env`)
- Encrypted credential stores
- Key rotation policies

### Database Permissions

**Recommended**:
```bash
chmod 600 .olav/db/*.duckdb          # Owner read/write only
chmod 700 .olav/db/                  # Owner access only
```

### Network Credentials

**Best Practices**:
- Use SSH keys instead of passwords
- Rotate credentials regularly
- Limit device access (read-only for queries)
- Use TACACS+/RADIUS for centralized auth

---

## 📋 Configuration Checklist

### For Development
- [ ] Clone repository
- [ ] Copy `.env.example` to `.env`
- [ ] Set `LLM_API_KEY` in `.env`
- [ ] Set `LLM_BASE_URL` if using OpenRouter/Groq
- [ ] Configure Nornir inventory (if using CLI features)
- [ ] Run `uv sync` to install dependencies
- [ ] Test: `uv run olav ask "list all devices"`

### For Production
- [ ] All development checklist items
- [ ] Set production API keys (separate from dev)
- [ ] Configure logging to file
- [ ] Set up log rotation
- [ ] Configure database backups
- [ ] Set proper file permissions (600 for secrets)
- [ ] Test cache configuration
- [ ] Verify network access (firewalls, VLANs)
- [ ] Set up monitoring (health checks)
- [ ] Document deployment-specific settings

---

## 🔄 Configuration Migration

### From v0.9.x to v1.0.0

**Changes**:
1. `02_skill_authoring_guide.md` → `reference/SKILL_AUTHORING_GUIDE.md`
2. All docs moved to `reference/` directory
3. New `DEVELOPER_INDEX.md` for navigation

**Action Required**:
- Update any scripts referencing old doc paths
- Update bookmarks/links

---

## 📚 References

### Configuration Files
- **SubAgent Registry**: `.olav/OLAV.md`
- **Skill Configs**: `.olav/skills/*/SKILL.md`
- **App Settings**: `config/settings.py`
- **Path Constants**: `config/paths.py`
- **Environment Template**: `.env.example`

### Documentation
- **Architecture**: [ARCHITECTURE.md](ARCHITECTURE.md)
- **Skill Authoring**: [SKILL_AUTHORING_GUIDE.md](SKILL_AUTHORING_GUIDE.md)
- **Sub-Agent Dev**: [SUB_AGENT_DEVELOPMENT_GUIDE.md](SUB_AGENT_DEVELOPMENT_GUIDE.md)

---

**Version**: v1.0.0 (2026-02-08)  
**Status**: ✅ Production Reference
