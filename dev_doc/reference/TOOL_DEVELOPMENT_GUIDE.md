# OLAV Tool Development Guide

**Version**: v1.0.0  
**Date**: 2026-02-08  
**Target**: Developers creating new tool functions

---

## 🎯 Overview

This guide covers how to create tool functions for OLAV agents. Tools are Python functions that agents can invoke to perform specific actions (query databases, execute CLI commands, analyze data, etc.).

**Tool Lifecycle**:
```
1. Design tool function → 2. Implement in src/olav/tools/ → 3. Register in SKILL.md → 4. Test with agent → 5. Deploy
```

---

## 📋 Tool Design Principles

### 1. Single Responsibility
**Rule**: Each tool does ONE thing well

```python
# ✅ GOOD - Single responsibility
def query_database(sql: str) -> dict:
    """Execute SQL query against database."""
    pass

# ❌ BAD - Multiple responsibilities
def query_and_export_and_analyze(sql: str, format: str, analysis_type: str):
    """Query database, export to file, and run analysis."""
    pass
```

### 2. Clear Input/Output Contract
**Rule**: Type hints + docstrings define the contract

```python
def inspect_schema(
    database: str = "main",
    table_name: str | None = None
) -> dict[str, list[str]]:
    """Inspect database schema.
    
    Args:
        database: Database name (main, olav, snapshots)
        table_name: Specific table to inspect (None for all)
    
    Returns:
        Dictionary mapping table names to column lists
        
    Raises:
        ValueError: If database doesn't exist
    """
    pass
```

### 3. Agent-Friendly Errors
**Rule**: Return structured errors, not exceptions

```python
# ✅ GOOD - Structured error
def query_database(sql: str) -> dict:
    try:
        result = conn.execute(sql).fetchdf()
        return {"status": "success", "data": result, "rows": len(result)}
    except Exception as e:
        return {"status": "error", "message": str(e), "sql": sql}

# ❌ BAD - Throws exception (agent crashes)
def query_database(sql: str) -> pd.DataFrame:
    return conn.execute(sql).fetchdf()  # Exception kills agent
```

### 4. Minimal External Dependencies
**Rule**: Prefer standard library, avoid heavy dependencies

```python
# ✅ GOOD - Standard library
from pathlib import Path
import json
import logging

# ⚠️ CAREFUL - Heavy dependencies (justify them)
import pandas as pd  # OK if needed for data manipulation
import torch  # Only if ML is essential
```

---

## 🏗️ Tool Implementation

### Naming Conventions

**Pattern**: `verb_noun` (action + target)

| Good | Bad | Reason |
|------|-----|--------|
| `query_database` | `db_query` | Verb-first is clearer |
| `execute_command` | `run_cli` | Explicit action |
| `inspect_schema` | `get_tables` | Describes what it does |
| `analyze_topology` | `topology` | Missing verb |
| `export_to_csv` | `save_file` | Specific format |

### Function Signature

**Template**:
```python
async def tool_name(
    required_param: str,
    optional_param: str = "default",
    *,  # Force keyword-only arguments after this
    flag: bool = False
) -> dict[str, Any]:
    """One-line summary.
    
    Longer description explaining what the tool does,
    when to use it, and any important behavior.
    
    Args:
        required_param: Description of required parameter
        optional_param: Description with default behavior
        flag: Description of boolean flag
    
    Returns:
        Dictionary with:
            - status: "success" or "error"
            - data: Result data (if success)
            - message: Error message (if error)
    
    Raises:
        ValueError: When validation fails
    
    Example:
        >>> result = await tool_name("input", flag=True)
        >>> print(result["status"])
        success
    """
    pass
```

**Key Points**:
- Use `async def` for I/O-bound operations
- Type hints for all parameters and return value
- Keyword-only args (`*,`) for clarity
- Structured return value (dict with status)

### Error Handling Pattern

**Standard Pattern**:
```python
from config.logging import logger

async def my_tool(param: str) -> dict[str, Any]:
    """Tool description."""
    try:
        # Validate input
        if not param:
            return {
                "status": "error",
                "message": "Parameter 'param' cannot be empty"
            }
        
        # Main logic
        result = await perform_operation(param)
        
        logger.info(f"Tool executed successfully: {param}")
        
        return {
            "status": "success",
            "data": result,
            "metadata": {"rows": len(result)}
        }
        
    except ValueError as e:
        logger.warning(f"Validation error in my_tool: {e}")
        return {"status": "error", "message": f"Validation failed: {e}"}
        
    except Exception as e:
        logger.error(f"Unexpected error in my_tool: {e}", exc_info=True)
        return {"status": "error", "message": f"Internal error: {str(e)}"}
```

**Benefits**:
- Agent can continue even if tool fails
- Logs capture full error context
- User sees meaningful error messages

---

## 📁 File Organization

### Tool Categories

Tools are organized by domain:

```
src/olav/tools/
├── react_query.py          # Database query tools
│   ├── query_database()
│   ├── inspect_schema()
│   └── discover_data()
│
├── react_expert.py         # Expert analysis tools
│   ├── search_knowledge_base()
│   ├── analyze_topology()
│   └── expand_scope_by_role()
│
├── react_cli.py            # CLI execution tools
│   ├── execute_command()
│   └── test_connectivity()
│
├── react_analysis.py       # Data analysis tools
│   ├── analyze_distribution()
│   └── find_anomalies()
│
└── react_export.py         # Export tools
    ├── export_to_csv()
    └── format_and_export()
```

### Creating a New Tool File

**Template** (`src/olav/tools/react_my_category.py`):

```python
"""Tools for [category description].

This module provides tools for [detailed description of what these tools do].
All tools follow the standard pattern: async functions returning dict[str, Any].
"""

import logging
from typing import Any

from config.logging import logger

__all__ = ["tool_function_1", "tool_function_2"]


async def tool_function_1(param: str) -> dict[str, Any]:
    """Tool description."""
    try:
        # Implementation
        logger.info(f"Executing tool_function_1 with {param}")
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Error in tool_function_1: {e}")
        return {"status": "error", "message": str(e)}


async def tool_function_2(param: int) -> dict[str, Any]:
    """Another tool description."""
    # Implementation
    pass
```

---

## 🔧 Tool Registration

### Register in SKILL.md

Tools must be registered in the appropriate SKILL.md file:

**Location**: `.olav/skills/[agent-name]/SKILL.md`

**Example**:
```yaml
---
name: network-query
description: Database query specialist

tools:
  - name: query_database              # Tool name (for LLM)
    module: olav.tools.react_query    # Python module path
    function: query_database          # Function name
    description: |                    # Description for LLM
      Execute SQL queries against DuckDB databases.
      Use for device inventory queries, data exploration.
      Returns results as markdown table.
    
  - name: inspect_schema
    module: olav.tools.react_query
    function: inspect_schema
    description: |
      Inspect database schema (tables, columns).
      Use before writing SQL to understand available data.
      
  - name: my_new_tool
    module: olav.tools.react_my_category
    function: my_new_tool
    description: |
      What this tool does and when to use it.
---
```

**Critical Fields**:
- `name`: How LLM refers to the tool
- `module`: Python import path
- `function`: Function name (must match exactly)
- `description`: Tells LLM when/how to use the tool

### Dynamic Loading

Tools are loaded dynamically via `SkillAdapter`:

```python
# src/olav/core/skill_adapter.py
from olav.core.subagent_loader import SubAgentLoader
from olav.core.skill_adapter import SkillAdapter

loader = SubAgentLoader()
adapter = SkillAdapter()

skill = loader.get_skill("network-query")
tools = adapter.load_tools_from_skill(skill)

# tools is now a list of callable functions
```

**How it works**:
1. Reads `tools` section from SKILL.md
2. Imports module: `importlib.import_module(tool.module)`
3. Gets function: `getattr(module, tool.function)`
4. Returns callable with original docstring

---

## 📚 Tool Categories & Examples

### 1. Database Tools (react_query.py)

**Purpose**: Query and inspect databases

**Example**:
```python
from config.paths import DB_MAIN_PATH
import duckdb

async def query_database(
    sql: str,
    database: str = "main"
) -> dict[str, Any]:
    """Execute SQL query.
    
    Args:
        sql: SQL query string
        database: Database name (main, olav, snapshots)
    
    Returns:
        Dictionary with status, data (as records), row count
    """
    try:
        from olav.lib.data_gateway import DataGateway
        
        gateway = DataGateway()
        result = gateway.query(sql)
        
        return {
            "status": "success",
            "data": result.to_dict("records"),
            "rows": len(result),
            "columns": list(result.columns)
        }
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return {
            "status": "error",
            "message": str(e),
            "sql": sql
        }
```

---

### 2. CLI Tools (react_cli.py)

**Purpose**: Execute network commands

**Example**:
```python
async def execute_command(
    command: str,
    target: str,
    *,
    timeout: int = 30
) -> dict[str, Any]:
    """Execute CLI command on network device.
    
    Args:
        command: CLI command to execute
        target: Device hostname or IP
        timeout: Command timeout in seconds
    
    Returns:
        Dictionary with status, output, execution time
    """
    try:
        from olav.lib.ncm_client import NCMClient
        
        client = NCMClient()
        result = client.execute_commands(
            target=target,
            commands=[command],
            timeout=timeout
        )
        
        return {
            "status": "success",
            "output": result.get("output", ""),
            "device": target,
            "command": command
        }
    except Exception as e:
        logger.error(f"Command execution failed: {e}")
        return {
            "status": "error",
            "message": str(e),
            "device": target,
            "command": command
        }
```

---

### 3. Analysis Tools (react_analysis.py)

**Purpose**: Analyze data patterns

**Example**:
```python
async def analyze_distribution(
    data: list[dict],
    field: str
) -> dict[str, Any]:
    """Analyze value distribution in dataset.
    
    Args:
        data: List of records
        field: Field name to analyze
    
    Returns:
        Dictionary with distribution statistics
    """
    try:
        from collections import Counter
        
        values = [record.get(field) for record in data]
        distribution = Counter(values)
        
        return {
            "status": "success",
            "field": field,
            "unique_values": len(distribution),
            "most_common": distribution.most_common(10),
            "total_records": len(data)
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

---

### 4. Export Tools (react_export.py)

**Purpose**: Export data to files

**Example**:
```python
from pathlib import Path
from config.paths import EXPORTS_DIR

async def export_to_csv(
    data: list[dict],
    filename: str,
    *,
    include_headers: bool = True
) -> dict[str, Any]:
    """Export data to CSV file.
    
    Args:
        data: List of records to export
        filename: Output filename (without path)
        include_headers: Include column headers
    
    Returns:
        Dictionary with status, file path, row count
    """
    try:
        import csv
        
        # Ensure exports directory exists
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        
        filepath = EXPORTS_DIR / filename
        
        with open(filepath, "w", newline="") as f:
            if not data:
                return {
                    "status": "error",
                    "message": "No data to export"
                }
            
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            
            if include_headers:
                writer.writeheader()
            
            writer.writerows(data)
        
        logger.info(f"Exported {len(data)} rows to {filepath}")
        
        return {
            "status": "success",
            "path": str(filepath),
            "rows": len(data),
            "columns": len(data[0]) if data else 0
        }
        
    except Exception as e:
        logger.error(f"Export failed: {e}")
        return {"status": "error", "message": str(e)}
```

---

## 🧪 Testing Tools

### Unit Test Template

**Location**: `tests/unit/test_tools_[category].py`

```python
import pytest
from olav.tools.react_my_category import my_tool_function

class TestMyToolFunction:
    """Test suite for my_tool_function."""
    
    @pytest.mark.asyncio
    async def test_success_case(self):
        """Test normal successful execution."""
        result = await my_tool_function("valid_input")
        
        assert result["status"] == "success"
        assert "data" in result
        assert isinstance(result["data"], list)
    
    @pytest.mark.asyncio
    async def test_empty_input(self):
        """Test error handling for empty input."""
        result = await my_tool_function("")
        
        assert result["status"] == "error"
        assert "message" in result
    
    @pytest.mark.asyncio
    async def test_invalid_input(self):
        """Test error handling for invalid input."""
        result = await my_tool_function("invalid")
        
        assert result["status"] == "error"
        assert "message" in result
```

### Integration Test with Agent

**Location**: `tests/integration/test_agent_tool_integration.py`

```python
@pytest.mark.asyncio
async def test_agent_uses_tool():
    """Test agent can invoke tool successfully."""
    from olav.agents.query_agent import create_query_agent
    
    agent = create_query_agent()
    
    # Agent should use tool to answer query
    result = await agent.ainvoke({
        "messages": [{"role": "user", "content": "use my_tool"}]
    })
    
    assert "error" not in result.lower()
```

### E2E Test

**Location**: `tests/e2e/test_real_scenarios.py`

```python
@pytest.mark.asyncio
async def test_my_tool_workflow(self):
    """
    User Story: Use my_tool to accomplish task
    
    Acceptance Criteria:
    1. Query succeeds
    2. Tool executes without errors
    3. Output is correct format
    """
    from olav.agents.orchestrator import orchestrate_query
    
    result = await orchestrate_query("use my tool to do something")
    
    assert result is not None
    assert "error" not in result.lower()
```

---

## 🎨 Best Practices

### 1. Use Path Constants
```python
# ✅ GOOD
from config.paths import DB_MAIN_PATH, EXPORTS_DIR

conn = duckdb.connect(str(DB_MAIN_PATH))

# ❌ BAD  
conn = duckdb.connect(".olav/db/main.duckdb")
```

### 2. Structured Logging
```python
from config.logging import logger

# ✅ GOOD
logger.info(
    "Tool executed",
    extra={"tool": "my_tool", "param": param, "duration": duration}
)

# ❌ BAD
print(f"Tool executed: {param}")
```

### 3. Async/Await for I/O
```python
# ✅ GOOD - Async for I/O operations
async def query_database(sql: str) -> dict:
    result = await async_query(sql)
    return result

# ⚠️ SYNC OK - For pure computation
def calculate_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
```

### 4. Return Structured Data
```python
# ✅ GOOD - Structured, predictable
return {
    "status": "success",
    "data": result,
    "metadata": {"rows": 10}
}

# ❌ BAD - Inconsistent return types
if success:
    return result
else:
    return None
```

### 5. Validate Inputs
```python
def my_tool(param: str) -> dict:
    # ✅ GOOD - Validate early
    if not param or not param.strip():
        return {"status": "error", "message": "param is required"}
    
    if len(param) > 1000:
        return {"status": "error", "message": "param too long (max 1000)"}
    
    # Main logic...
```

---

## 🚫 Anti-Patterns

### 1. DO NOT Hardcode Paths
```python
# ❌ BAD
db_path = ".olav/db/main.duckdb"
export_path = "exports/data.csv"

# ✅ GOOD
from config.paths import DB_MAIN_PATH, EXPORTS_DIR
db_path = DB_MAIN_PATH
export_path = EXPORTS_DIR / "data.csv"
```

### 2. DO NOT Silently Fail
```python
# ❌ BAD
def my_tool(param: str):
    try:
        result = risky_operation(param)
        return result
    except:
        return None  # Agent doesn't know what went wrong

# ✅ GOOD
def my_tool(param: str) -> dict:
    try:
        result = risky_operation(param)
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Tool failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
```

### 3. DO NOT Mix Concerns
```python
# ❌ BAD - Mixing query, export, analysis
def query_and_export_and_analyze(sql: str):
    data = query_db(sql)
    export_csv(data)
    analyze(data)

# ✅ GOOD - Separate tools
def query_database(sql: str): ...
def export_to_csv(data: list): ...
def analyze_data(data: list): ...
```

### 4. DO NOT Use Print
```python
# ❌ BAD
def my_tool(param: str):
    print(f"Executing tool with {param}")
    return result

# ✅ GOOD
from config.logging import logger

def my_tool(param: str):
    logger.info(f"Executing tool with {param}")
    return result
```

---

## 📋 Tool Development Checklist

### Design Phase
- [ ] Tool has single clear responsibility
- [ ] Tool name follows `verb_noun` pattern
- [ ] Input/output contract is clear
- [ ] Error cases are identified

### Implementation Phase
- [ ] Function signature has type hints
- [ ] Docstring includes Args, Returns, Raises, Example
- [ ] Uses async for I/O operations
- [ ] Returns structured dict with status
- [ ] Error handling returns status="error"
- [ ] Logging uses logger, not print
- [ ] Uses path constants from config.paths
- [ ] Input validation is performed

### Registration Phase
- [ ] Tool registered in appropriate SKILL.md
- [ ] Description tells LLM when to use tool
- [ ] Module path is correct
- [ ] Function name matches exactly

### Testing Phase
- [ ] Unit tests cover success case
- [ ] Unit tests cover error cases
- [ ] Integration test with agent
- [ ] E2E test for user workflow

### Deployment Phase
- [ ] Tool works in agent context
- [ ] Logs are helpful for debugging
- [ ] Documentation updated (if needed)

---

## 📚 References

### Related Documentation
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [SUB_AGENT_DEVELOPMENT_GUIDE.md](SUB_AGENT_DEVELOPMENT_GUIDE.md) - Agent development
- [SKILL_AUTHORING_GUIDE.md](SKILL_AUTHORING_GUIDE.md) - SKILL.md configuration
- [CONFIGURATION_REFERENCE.md](CONFIGURATION_REFERENCE.md) - Path constants

### Example Tools
- `src/olav/tools/react_query.py` - Database query tools
- `src/olav/tools/react_expert.py` - Expert analysis tools
- `src/olav/tools/react_cli.py` - CLI execution tools

---

**Version**: v1.0.0 (2026-02-08)  
**Status**: ✅ Production Reference
