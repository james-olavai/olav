# OLAV Developer Reference

**Version**: v2.1.0  
**Date**: 2026-02-15  
**Audience**: Developers, Maintainers, Admin Agent  
**Purpose**: Technical reference for maintaining and extending OLAV

---

## 📋 Overview

This reference is designed for **Admin Agent** to understand OLAV's architecture and perform maintenance tasks. It's NOT a user guide—it's a developer/maintainer manual.

### What Admin Agent Can Do

- ✅ Create new skills
- ✅ Modify existing skills
- ✅ Create/modify tools
- ✅ Fix bugs
- ✅ Update configurations
- ✅ Extend functionality
- ✅ Debug issues

### How to Use This Reference

1. **Creating Skills**: See [Skill Development](#skill-development)
2. **Creating Tools**: See [Tool Development](#tool-development)
3. **Understanding Architecture**: See [Architecture](#architecture)
4. **Debugging**: See [Debugging Guide](#debugging-guide)
5. **Configuration**: See [Configuration](#configuration)

---

## 🏗️ Architecture

### Project Structure

```
Olav/
├── .olav/                    # User data directory (portable)
│   ├── skills/               # Skill definitions
│   │   ├── network-query/    # Example skill
│   │   │   ├── SKILL.md      # Skill configuration
│   │   │   └── tools/        # Skill-specific tools
│   │   ├── command_learner/  # Command Learner Agent
│   │   ├── olav-admin/       # Admin Agent
│   │   └── shared/           # Shared tools
│   ├── databases/            # DuckDB files
│   │   ├── main.duckdb       # Main agent state
│   │   ├── command_learner.duckdb
│   │   └── admin.duckdb
│   ├── templates/            # TextFSM templates
│   │   └── custom/           # User-created templates
│   ├── config/               # User configurations
│   └── settings.json         # User settings
│
├── src/olav/                 # Framework code (pip installed)
│   ├── agents/               # Agent implementations
│   │   ├── agent.py          # Main agent (v2.0)
│   │   ├── command_learner_agent.py  # Command Learner (v2.1)
│   │   └── admin_agent.py    # Admin agent (v2.1)
│   ├── core/                 # Core logic
│   ├── cli/                  # CLI commands
│   └── ...
│
├── config/                   # Framework config (settings, paths, etc.)
├── dev_docs/                 # Developer documentation
├── docs/                     # User documentation
└── tests/                    # Test suite
```

### Core Concepts

#### 1. Skills

**What**: Declarative configurations that define agent capabilities

**Location**: `.olav/skills/<skill-name>/SKILL.md`

**Structure**:
```yaml
---
name: network-query
description: Query network device data from database
version: 1.0.0
author: OLAV Team
tools:
  - query_database
  - inspect_schema
  - smart_sql_query
---

# Instructions

When user asks about network data:
1. First check schema with inspect_schema
2. Build SQL query with smart_sql_query
3. Execute with query_database
4. Format results clearly

# Examples

Input: "How many devices?"
→ smart_sql_query("Count devices")
→ query_database("SELECT COUNT(*) FROM devices")

Input: "Show devices in 192.168.1.0/24"
→ inspect_schema("devices")
→ smart_sql_query("Filter by IP range")
→ query_database("SELECT * FROM devices WHERE ip LIKE '192.168.1.%'")
```

#### 2. Tools

**What**: Python functions that agents can call

**Location**: `.olav/skills/<skill-name>/tools/<tool-name>.py`

**Template**:
```python
from langchain_core.tools import tool

@tool
def my_tool(param1: str, param2: int) -> dict:
    """Tool description (this becomes the tool docstring for LLM).
    
    Args:
        param1: Description of param1
        param2: Description of param2
    
    Returns:
        dict with results
    
    Example:
        my_tool("value", 42)
    """
    # Implementation
    result = do_something(param1, param2)
    return {"result": result}
```

#### 3. Agents

**What**: LLM-powered autonomous systems that use skills/tools

**Types**:
- **Main Agent** (`agent.py`): General-purpose network automation
- **Command Learner** (`command_learner_agent.py`): Create TextFSM templates
- **Admin Agent** (`admin_agent.py`): Maintain and extend OLAV

**Creation**:
```python
from deepagents import create_deep_agent
from langgraph.checkpoint.duckdb import DuckDBSaver

agent = create_deep_agent(
    name="MyAgent",
    tools=[tool1, tool2, tool3],
    skills_path=".olav/skills/my-agent",
    system_prompt="You are...",
    checkpointer=DuckDBSaver(".olav/databases/my_agent.duckdb"),
)
```

---

## 📝 Skill Development

### Creating a New Skill

**Step 1: Create Directory Structure**

```bash
mkdir -p .olav/skills/my-new-skill/tools
cd .olav/skills/my-new-skill
```

**Step 2: Create SKILL.md**

```yaml
---
name: my-new-skill
description: What this skill does
version: 1.0.0
author: Your Name
tools:
  - tool1
  - tool2
---

# Instructions

When to use this skill:
- Condition 1
- Condition 2

How to use:
1. Step 1
2. Step 2
3. Step 3

# Examples

Input: "Example query"
→ tool1(args)
→ tool2(results)
→ Return formatted response
```

**Step 3: Create Tools**

```python
# .olav/skills/my-new-skill/tools/tool1.py

from langchain_core.tools import tool

@tool
def tool1(param: str) -> dict:
    """Tool description for LLM."""
    # Implementation
    return {"result": "..."}
```

**Step 4: Register Skill**

```python
# .olav/skills/index.json (update if exists, or auto-discovered)
{
  "skills": [
    "network-query",
    "network-cli",
    "my-new-skill"  # Add here
  ]
}
```

**Step 5: Test**

```bash
# Test skill
olav ask "query that uses my new skill"
```

### Modifying Existing Skill

**Step 1: Read Current Skill**
```bash
cat .olav/skills/network-query/SKILL.md
```

**Step 2: Modify SKILL.md or Tools**
- Update instructions
- Add/remove tools
- Update examples

**Step 3: Test Changes**
```bash
olav ask "test query"
```

---

## 🔧 Tool Development

### Tool Template

```python
# .olav/skills/<skill>/tools/<tool_name>.py

from langchain_core.tools import tool
from pathlib import Path
import duckdb

@tool
def my_tool(param1: str, param2: int = 10) -> dict:
    """One-line description of what this tool does.
    
    This docstring is shown to the LLM. Be clear and concise.
    
    Args:
        param1: What is param1 (required)
        param2: What is param2 (optional, default: 10)
    
    Returns:
        dict: {
            "result": "...",
            "error": null or error message
        }
    
    Example:
        result = my_tool("value", 20)
        # Returns: {"result": "...", "error": null}
    """
    try:
        # Implementation
        result = do_something(param1, param2)
        
        return {
            "result": result,
            "error": None
        }
    
    except Exception as e:
        return {
            "result": None,
            "error": str(e)
        }
```

### Common Tool Patterns

#### Database Query Tool

```python
@tool
def query_database(sql: str) -> dict:
    """Execute SQL query on DuckDB."""
    from config.paths import DB_MAIN_PATH
    import duckdb
    
    conn = duckdb.connect(str(DB_MAIN_PATH))
    result = conn.execute(sql).fetchall()
    columns = [desc[0] for desc in conn.description]
    
    return {
        "rows": result,
        "columns": columns,
        "count": len(result)
    }
```

#### Network Command Tool

```python
@tool
def execute_command(device: str, command: str) -> dict:
    """Execute command on network device."""
    from nornir import InitNornir
    
    nr = InitNornir(config_file=".olav/config/nornir_config.yaml")
    device_obj = nr.filter(name=device)
    
    result = device_obj.run(
        task=netmiko_send_command,
        command_string=command
    )
    
    return {
        "output": result[device][0].result,
        "failed": result[device].failed
    }
```

#### File Operation Tool

```python
@tool
def read_config_file(filename: str) -> dict:
    """Read configuration file."""
    from config.paths import OLAV_CONFIG_DIR
    
    file_path = OLAV_CONFIG_DIR / filename
    if not file_path.exists():
        return {"error": f"File not found: {filename}"}
    
    content = file_path.read_text()
    return {"content": content, "path": str(file_path)}
```

### Tool Best Practices

1. **Always return dict**: LLM expects structured output
2. **Include error handling**: Return `{"error": "..."}` on failure
3. **Clear docstrings**: This is what LLM sees
4. **Use type hints**: Helps LLM understand parameters
5. **Keep tools focused**: One tool = one clear purpose
6. **Use config paths**: Import from `config.paths`, don't hardcode

---

## ⚙️ Configuration

### Settings Location

```
.olav/settings.json         # User settings (portable)
config/settings.py          # Default settings (framework)
config/paths.py             # Path configurations
```

### .olav/settings.json

```json
{
  "llm": {
    "model_name": "grok-beta",
    "temperature": 0.1,
    "max_tokens": 32768
  },
  "network": {
    "timeout": 60,
    "max_workers": 10
  },
  "database": {
    "main_db": ".olav/databases/main.duckdb"
  }
}
```

### config/settings.py

```python
from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    # LLM settings
    llm_model_name: str = "grok-beta"
    llm_temperature: float = 0.1
    
    # Network settings
    network_timeout: int = 60
    
    # Database settings
    db_main_path: Path = Path(".olav/databases/main.duckdb")
    
    class Config:
        env_file = ".env"
        env_prefix = "OLAV_"

# Singleton
_settings = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
```

### config/paths.py

```python
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# .olav directory
OLAV_DIR = PROJECT_ROOT / ".olav"
SKILLS_DIR = OLAV_DIR / "skills"
DB_DIR = OLAV_DIR / "databases"
TEMPLATES_DIR = OLAV_DIR / "templates"
CONFIG_DIR = OLAV_DIR / "config"

# Databases
DB_MAIN_PATH = DB_DIR / "main.duckdb"
DB_COMMAND_LEARNER_PATH = DB_DIR / "command_learner.duckdb"
DB_ADMIN_PATH = DB_DIR / "admin.duckdb"

# Templates
TEXTFSM_CUSTOM_DIR = TEMPLATES_DIR / "custom"
TEXTFSM_LEGACY_DIR = TEMPLATES_DIR
```

---

## 🐛 Debugging Guide

### Common Issues

#### Issue 1: Skill Not Found

**Symptom**: `Error: Skill 'my-skill' not found`

**Diagnosis**:
```bash
# Check if skill directory exists
ls -la .olav/skills/my-skill/

# Check if SKILL.md exists
cat .olav/skills/my-skill/SKILL.md
```

**Fix**:
1. Create missing SKILL.md
2. Verify directory structure
3. Check skills index: `cat .olav/skills/index.json`

#### Issue 2: Tool Not Working

**Symptom**: Tool called but no output or error

**Diagnosis**:
```bash
# Check tool file
cat .olav/skills/my-skill/tools/my_tool.py

# Check tool is decorated with @tool
grep "@tool" .olav/skills/my-skill/tools/my_tool.py

# Test tool directly
python3 -c "
from olav.skills.my_skill.tools.my_tool import my_tool
result = my_tool('test')
print(result)
"
```

**Fix**:
1. Add `@tool` decorator
2. Fix import errors
3. Add error handling

#### Issue 3: Database Connection Failed

**Symptom**: `Error connecting to database`

**Diagnosis**:
```bash
# Check database file exists
ls -la .olav/databases/main.duckdb

# Check permissions
ls -l .olav/databases/

# Test connection
python3 -c "
import duckdb
conn = duckdb.connect('.olav/databases/main.duckdb')
print(conn.execute('SELECT COUNT(*) FROM devices').fetchone())
"
```

**Fix**:
1. Create missing database directory
2. Fix file permissions
3. Initialize database schema

### Debug Tools

#### Enable Debug Logging

```python
# config/logging.py
import logging

logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

#### Check Agent State

```bash
# View agent checkpoints
python3 -c "
from langgraph.checkpoint.duckdb import DuckDBSaver
import duckdb

conn = duckdb.connect('.olav/databases/main.duckdb')
checkpoints = conn.execute('SELECT * FROM checkpoints ORDER BY created_at DESC LIMIT 10').fetchall()
for cp in checkpoints:
    print(cp)
"
```

#### Inspect Tool Execution

```python
# Add logging to tools
import logging
logger = logging.getLogger(__name__)

@tool
def my_tool(param: str) -> dict:
    logger.debug(f"my_tool called with param={param}")
    # ... implementation
    logger.debug(f"my_tool returning {result}")
    return result
```

---

## 📊 Database Schema

### Main Database: main.duckdb

```sql
-- Devices table
CREATE TABLE devices (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    ip TEXT NOT NULL,
    platform TEXT,
    role TEXT,
    location TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Interfaces table  
CREATE TABLE interfaces (
    id INTEGER PRIMARY KEY,
    device_id INTEGER REFERENCES devices(id),
    name TEXT NOT NULL,
    ip TEXT,
    status TEXT,
    description TEXT
);

-- BGP neighbors table
CREATE TABLE bgp_neighbors (
    id INTEGER PRIMARY KEY,
    device_id INTEGER REFERENCES devices(id),
    neighbor_ip TEXT NOT NULL,
    asn INTEGER,
    state TEXT,
    uptime TEXT
);

-- Commands history
CREATE TABLE command_history (
    id INTEGER PRIMARY KEY,
    device_id INTEGER REFERENCES devices(id),
    command TEXT NOT NULL,
    output TEXT,
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- LangGraph checkpoints
CREATE TABLE checkpoints (
    thread_id TEXT,
    checkpoint_id TEXT,
    parent_checkpoint_id TEXT,
    checkpoint BLOB,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (thread_id, checkpoint_id)
);
```

### Query Examples

```sql
-- Count devices by platform
SELECT platform, COUNT(*) as count
FROM devices
GROUP BY platform;

-- Find devices with BGP issues
SELECT d.name, b.neighbor_ip, b.state
FROM devices d
JOIN bgp_neighbors b ON d.id = b.device_id
WHERE b.state != 'Established';

-- Recent command history
SELECT d.name, c.command, c.executed_at
FROM command_history c
JOIN devices d ON c.device_id = d.id
ORDER BY c.executed_at DESC
LIMIT 10;
```

---

## 🧪 Testing

### Running Tests

```bash
# All tests
uv run pytest

# E2E tests only
uv run pytest tests/e2e/

# Specific test
uv run pytest tests/e2e/test_admin_agent.py -v

# With coverage
uv run pytest --cov=src/olav --cov-report=html
```

### Writing Tests

```python
# tests/e2e/test_my_skill.py

import pytest
from olav.agents.agent import create_olav_agent

@pytest.mark.e2e
async def test_my_skill():
    """Test my skill functionality."""
    agent = create_olav_agent()
    
    # Test query
    result = await agent.ainvoke("test query for my skill")
    
    # Assertions
    assert result is not None
    assert "expected output" in result.lower()

@pytest.mark.e2e
async def test_my_tool():
    """Test my tool directly."""
    from olav.skills.my_skill.tools.my_tool import my_tool
    
    result = my_tool("test input")
    
    assert result["error"] is None
    assert result["result"] == "expected"
```

---

## � Shell Commands for Admin Agent

Admin Agent uses `execute_command` to run shell commands directly. Here are common patterns:

### List and Find Files

```bash
# List all skills
find .olav/skills -type d -maxdepth 1

# Find all SKILL.md files
find .olav/skills -name "SKILL.md"

# List all Python tools
find .olav/skills -name "*.py" -path "*/tools/*"

# List with details
ls -la .olav/skills/*/SKILL.md
```

### Search Code

```bash
# Search for function definition
grep -r "def execute_sql" .olav/

# Search in Python files only
grep -r "execute_sql" .olav/ --include="*.py"

# Search with line numbers and context
grep -n -C 3 "class Agent" src/olav/agents/

# Search for pattern with word boundary
grep -r "\bDuckDB\b" .olav/
```

### Git Operations

```bash
# Check status
git status

# View history
git log --oneline -10

# Add files
git add .olav/skills/network-query/

# Commit (HITL approval required)
git commit -m "feat: add network-query skill"

# Push (HITL approval required)
git push origin refactor/v2.0-deepagents

# View diff
git diff dev_docs/ADMIN_AGENT_SPEC.md
```

### Python Execution

```bash
# Run OLAV command (or use execute_olav tool)
uv run olav ask "What is 2+2?"

# Run tests
python3 -m pytest tests/e2e/test_admin.py -v

# Run script
python3 .olav/tools/database.py --query "SELECT * FROM devices"
```

### Backup and Restore

```bash
# Create timestamped backup
tar -czf backup_$(date +%Y%m%d_%H%M%S).tar.gz .olav/

# List backup contents
tar -tzf backup_20260215_153000.tar.gz | head -20

# Restore backup
tar -xzf backup_20260215_153000.tar.gz

# Backup to specific location
tar -czf ~/backups/olav_$(date +%Y%m%d).tar.gz .olav/
```

### Utilities

```bash
# Count lines of code
find .olav/skills -name "*.py" | xargs wc -l

# Check file sizes
du -sh .olav/skills/*

# View file permissions
ls -la .olav/skills/network-query/

# Create directory structure
mkdir -p .olav/skills/new-skill/tools

# Copy files
cp .olav/skills/network-query/SKILL.md .olav/skills/new-skill/SKILL.md
```

---

## �📋 Common Tasks Reference

### Task: Create a Monitoring Skill

```bash
# 1. Create structure
mkdir -p .olav/skills/device-monitoring/tools

# 2. Create SKILL.md
cat > .olav/skills/device-monitoring/SKILL.md << 'EOF'
---
name: device-monitoring
description: Monitor device health metrics
version: 1.0.0
tools:
  - check_health
  - get_metrics
---

# Instructions

Monitor device CPU, memory, and interface status.

# Examples

Input: "Check device R1 health"
→ check_health("R1")
→ get_metrics("R1")
→ Report status
EOF

# 3. Create tool
cat > .olav/skills/device-monitoring/tools/check_health.py << 'EOF'
from langchain_core.tools import tool

@tool
def check_health(device: str) -> dict:
    """Check device health status."""
    # Implementation
    return {"status": "healthy", "cpu": 45, "memory": 60}
EOF

# 4. Test
olav ask "Check device R1 health"
```

### Task: Fix a Bug in Tool

```bash
# 1. Read tool
cat .olav/skills/network-query/tools/query_database.py

# 2. Identify issue (example: SQL injection)
# Before: f"SELECT * FROM devices WHERE ip='{ip}'"
# After: "SELECT * FROM devices WHERE ip=?" with parameters

# 3. Apply fix
cat > .olav/skills/network-query/tools/query_database.py << 'EOF'
@tool
def query_database(sql: str, params: list = None) -> dict:
    """Execute parameterized SQL query."""
    conn = duckdb.connect(DB_MAIN_PATH)
    result = conn.execute(sql, params or []).fetchall()
    return {"rows": result}
EOF

# 4. Test fix
olav ask "Show device with IP 192.168.1.1"
```

### Task: Backup and Restore

```bash
# Backup .olav directory
tar -czf olav_backup_$(date +%Y%m%d).tar.gz .olav/

# Restore from backup
tar -xzf olav_backup_20260215.tar.gz

# Verify
ls -la .olav/
```

---

## 🚀 Advanced Topics

### Creating a New Agent

```python
# src/olav/agents/my_agent.py

from deepagents import create_deep_agent
from langgraph.checkpoint.duckdb import DuckDBSaver
from pathlib import Path

def create_my_agent():
    """Create independent agent."""
    
    # Load tools from skill
    from olav.skills.my_skill.tools import tool1, tool2
    
    return create_deep_agent(
        name="MyAgent",
        tools=[tool1, tool2],
        skills_path=".olav/skills/my-agent",
        system_prompt="""
        You are an autonomous agent that...
        
        Your capabilities:
        - Capability 1
        - Capability 2
        """,
        checkpointer=DuckDBSaver(".olav/databases/my_agent.duckdb"),
    )

# CLI entry point
if __name__ == "__main__":
    agent = create_my_agent()
    result = agent.invoke("Hello")
    print(result)
```

### Hot-Reloading Templates

```python
# src/olav/core/command_registry.py

from pathlib import Path
from typing import Dict

class CommandRegistry:
    """Registry for TextFSM templates with hot-reload."""
    
    def __init__(self):
        self.templates: Dict[str, str] = {}
        self.load_templates()
    
    def load_templates(self):
        """Load all templates."""
        template_dirs = [
            Path(".olav/config/textfsm"),
            Path(".olav/templates/custom"),
            Path(".olav/templates"),
        ]
        
        for dir in template_dirs:
            if dir.exists():
                for template_file in dir.glob("*.textfsm"):
                    key = template_file.stem
                    self.templates[key] = template_file.read_text()
    
    def reload(self):
        """Hot-reload templates without restart."""
        self.templates.clear()
        self.load_templates()
        return len(self.templates)

# Singleton
_registry = None

def get_registry() -> CommandRegistry:
    global _registry
    if _registry is None:
        _registry = CommandRegistry()
    return _registry

def reload_commands():
    """Public API for hot-reloading."""
    registry = get_registry()
    count = registry.reload()
    return {"reloaded": count, "status": "success"}
```

---

## 📖 API Reference

### Key Modules

```python
# Agent creation
from deepagents import create_deep_agent

# Tools
from langchain_core.tools import tool

# Checkpointer
from langgraph.checkpoint.duckdb import DuckDBSaver

# Configuration
from config.settings import get_settings
from config.paths import *

# Database
import duckdb

# Network automation
from nornir import InitNornir
from nornir_netmiko.tasks import netmiko_send_command
```

---

**Last Updated**: 2026-02-15  
**Version**: v2.1.0  
**Maintained By**: OLAV Development Team
