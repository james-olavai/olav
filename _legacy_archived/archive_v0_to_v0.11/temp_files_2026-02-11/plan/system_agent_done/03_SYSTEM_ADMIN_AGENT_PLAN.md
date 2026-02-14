# System Admin Agent Implementation Plan

**Date**: 2026-02-08  
**Version**: v1.0.0  
**Status**: 🟡 Planning  

---

## 📋 Executive Summary

**Goal**: Implement System Administration SubAgent with graduated permissions using DeepAgents native HITL (Human-in-the-Loop) mechanism and file I/O capabilities.

**Core Principle**: **Human-Machine Collaboration** with strict permission boundaries:
- 🟢 **Green**: Autonomous execution (read-only, low-risk)
- 🟡 **Yellow**: Requires user confirmation (writes, config changes)
- 🔴 **Red**: Suggestion-only mode (critical operations)
- 🚫 **Forbidden**: Hard-coded blocking (security-sensitive)

**Key Technologies**:
- DeepAgents `HumanInTheLoopMiddleware` (native approval mechanism)
- DeepAgents file I/O tools (read/write capabilities)  
- Existing OLAV HITL configuration (`config/settings.py::HITLSettings`)
- Git-based automatic backup system
- **Semantic Task Scheduling** (natural language → cron, auto-lifecycle)

**Extended Capabilities**:
- 🤖 **Automated Operations**: Cron integration for scheduled tasks
- 🗣️ **Natural Language Scheduling**: "Monitor R1 BGP every 10 mins for 24 hours"
- 📊 **Active Monitoring**: Event-driven alerts and threshold-based notifications
- 🔄 **Task Lifecycle Management**: Auto-creation, execution, expiration, archival
- 🌐 **Web API Ready**: Schema-aware programmatic API (not subprocess) for Web GUI integration

---

## 🌐 Web API Integration Strategy

**Context**: OLAV plans to add Web GUI in future releases (see [Web API Architecture](web_api_architecture.md))

**System Admin Agent Role**: Provide programmatic API for both CLI agents and Web frontend

### Three-Layer API Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 Layer 3: Web GUI (Future)                    │
│              React Frontend + Real-time Query                │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP REST
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              Layer 2: FastAPI (Future Phase 2)               │
│           Schema-Aware REST Endpoints + WebSocket            │
│                                                               │
│  GET /api/schema/{table}  - Dynamic schema discovery         │
│  GET /api/data/{table}    - Schema-aware queries             │
│  POST /api/query          - Natural language                 │
│  WebSocket /ws/query      - Streaming responses              │
└───────────────────────────┬─────────────────────────────────┘
                            │ Python Calls
                            ▼
┌─────────────────────────────────────────────────────────────┐
│          Layer 1: Programmatic API (IMMEDIATE)               │
│               olav.api.* Python Functions                    │
│                                                               │
│  🔧 System Admin Agent tools call these directly:            │
│     • olav.api.cache.clean_cache(type="query")               │
│     • olav.api.devices.list_devices()                        │
│     • olav.api.system.health_check()                         │
│     • olav.api.schema.list_tables() (schema-aware)           │
│                                                               │
│  ✅ Benefits:                                                 │
│     • Type-safe (Pydantic models)                            │
│     • No subprocess overhead                                 │
│     • Shared by agents AND Web GUI                           │
│     • 30x faster than CLI subprocess                         │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    DuckDB (Zero-ETL)                         │
│           Schema-Aware, No Hardcoded Endpoints               │
└─────────────────────────────────────────────────────────────┘
```

### Why Programmatic API (Not Subprocess)

**Problem with subprocess CLI calls**:
```python
# ❌ System Admin Agent calling CLI (OLD APPROACH - DON'T DO THIS)
@tool
def clean_cache():
    import subprocess
    result = subprocess.run(
        ["olav", "clean", "--cache", "--force"],
        capture_output=True, text=True
    )
    # Issues:
    # 1. Slow (150ms subprocess overhead)
    # 2. Fragile (CLI flag changes break tools)
    # 3. String parsing (exit codes, stdout)
    # 4. LLM hallucination (generates invalid flags)
    return result.stdout
```

**Solution with Programmatic API**:
```python
# ✅ System Admin Agent calling API (NEW APPROACH)
@tool
def clean_cache():
    """Clean query cache."""
    from olav.api import cache
    
    result = cache.clean_cache(cache_type="query")
    # Benefits:
    # 1. Fast (5ms direct call, 30x speedup)
    # 2. Type-safe (Pydantic validates inputs)
    # 3. Structured output (CacheCleanResult object)
    # 4. No LLM hallucination (Python types)
    return f"✅ {result.message}"
```

### Schema-Aware API Design

**OLAV's Core Principle**: Zero-ETL, schema-aware architecture

**Apply to Web API**:
- ❌ **NOT**: Hardcode 50+ REST endpoints (one per table)
- ✅ **YES**: 2 dynamic endpoints for ALL tables

```python
# src/olav/api/schema.py
def list_tables() -> SchemaDiscoveryResult:
    """Discover all DuckDB tables and views.
    
    Returns schema metadata from information_schema.
    Web GUI queries this to build navigation menu dynamically.
    """
    # Query: SELECT * FROM information_schema.tables
    # Returns: List[TableSchema] with columns, types, row counts
    pass

# src/olav/api/data.py
def query_table(table_name: str, filters: QueryFilters) -> QueryResult:
    """Query any table with dynamic filters.
    
    No hardcoded endpoints needed!
    
    Examples:
        query_table("devices")
        query_table("v_interfaces", filters={"where": "device='R1'"})
        query_table("v_bgp", filters={"where": "status='Established'"})
    
    Web GUI uses single endpoint for all tables.
    """
    pass
```

**Benefit**: When you add new DuckDB view, Web UI auto-discovers and renders it (no code changes)

### Implementation Priority

**Phase 1 (Week 1)**: Create Programmatic API  
**Critical** - Blocks System Admin Agent implementation

```
src/olav/api/
├── __init__.py       # Public exports
├── schema.py         # list_tables, get_table_schema (schema-aware)
├── data.py           # query_table (dynamic data access)
├── cache.py          # clean_cache, get_metrics
├── devices.py        # list_devices, add_device
├── query.py          # run_query (orchestrator wrapper)
├── system.py         # health_check, version
├── database.py       # init_database, clean_snapshots
└── models.py         # Pydantic response models
```

**Phase 2 (Week 2)**: Refactor System Admin Tools  
Update 17 tools to use `olav.api.*` instead of subprocess

**Phase 3 (Future)**: FastAPI HTTP Layer  
Add REST endpoints wrapping Programmatic API

**Phase 4 (Future)**: Web GUI  
React frontend with schema-driven UI generation

### Tool Implementation Pattern

**All System Admin Agent tools follow this pattern**:

```python
# src/olav/agents/system_admin_tools.py

from olav.api import cache, devices, system
from langchain.agents import tool

@tool
def system_health_check() -> str:
    """Run comprehensive system health check.
    
    Permission: 🟢 Green (read-only)
    """
    # Call programmatic API (not subprocess)
    result = system.health_check()
    return format_health_report(result)

@tool
@require_approval(category="cache_management")
def clean_cache(cache_type: str = "query") -> str:
    """Clean cache files.
    
    Permission: 🟡 Yellow (requires approval)
    
    Args:
        cache_type: "query" | "session" | "all"
    """
    # Call programmatic API (type-safe)
    result = cache.clean_cache(cache_type=cache_type)
    return f"✅ Cleaned {result.files_deleted} files, freed {result.bytes_freed/1024/1024:.1f} MB"

@tool
def list_devices() -> str:
    """List all network devices.
    
    Permission: 🟢 Green (read-only)
    """
    # Call programmatic API (returns List[Device])
    devices_list = devices.list_devices()
    return format_device_table(devices_list)
```

**No subprocess calls** - All tools use type-safe Python functions

---

## 🎯 Use Cases & User Stories

### Phase 1: System Monitoring (Green - Read-Only) 🟢

**UC-1.1: System Health Check**
```
User: "How is the system doing?"
Agent: 
  ✓ Database size: 2.3 GB (main.duckdb)
  ✓ Cache hit rate: 87%
  ✓ Last sync: 2 hours ago
  ✓ LLM API: Configured (OpenRouter)
  ✓ Active devices: 42/45 reachable
```

**UC-1.2: Configuration Audit**
```
User: "Check my configuration"
Agent:
  ✓ Nornir inventory: 45 devices
  ✓ Skills: 8 enabled, 2 disabled
  ✓ Database connections: All healthy
  ✓ Export directory: /home/user/exports/ (3.2 GB)
  ⚠️ Warning: Cache not cleaned in 14 days
```

**UC-1.3: Usage Analytics**
```
User: "Which skills are most used?"
Agent:
  1. Query Agent: 234 executions (67%)
  2. Analysis Agent: 78 executions (22%)
  3. TextFSM Agent: 38 executions (11%)
  
  Top commands:
  - show ip interface brief: 145 times
  - show running-config: 89 times
```

### Phase 2: Low-Risk Operations (Green - Autonomous) 🟢

**UC-2.1: Create Snapshot**
```
User: "Create a snapshot of current network state"
Agent: [Executes without confirmation]
  ✓ Running sync_all with full_sync=True...
  ✓ Collected 42 devices
  ✓ Saved to: .olav/data/sync/2026-02-08/
  ✓ Imported to database: 834 records
  ✓ Snapshot created successfully
```

**UC-2.2: Clean Cache**
```
User: "Clean the cache"
Agent: [Executes without confirmation]
  ✓ Removing .olav/cache/*.pkl
  ✓ Removed 127 cache files (543 MB)
  ✓ Cache cleaned successfully
```

**UC-2.3: Rebuild Index**
```
User: "Rebuild vector database"
Agent: [Executes without confirmation]
  ✓ Re-indexing knowledge base...
  ✓ Processed 345 documents
  ✓ Index rebuilt successfully
```

### Phase 3: Device Management (Yellow - Confirmation Required) 🟡

**UC-3.1: Add Device**
```
User: "Add router R2 with IP 192.168.1.2, cisco_ios platform"
Agent: [Shows diff, waits for approval]

📝 Proposed Device Addition:

Device: R2
IP: 192.168.1.2
Platform: cisco_ios
Driver: netmiko
Groups: [routers]

Diff (.olav/nornir/inventory.yaml):
+ R2:
+   hostname: 192.168.1.2
+   platform: cisco_ios
+   groups: [routers]

⚠️ This will modify inventory configuration.
✅ Configuration validated (IP format OK, platform supported)
🔄 Git backup will be created before applying

[Approve] [Reject] [Edit]
```

**UC-3.2: Update Device Groups**
```
User: "Move R1 to core-routers group"
Agent: [Shows diff]

📝 Proposed Change:

Device: R1
Current groups: [routers]
New groups: [routers, core-routers]

Diff:
  R1:
    hostname: 192.168.1.1
    platform: cisco_ios
-   groups: [routers]
+   groups: [routers, core-routers]

[Approve] [Reject]
```

### Phase 4: Configuration Optimization (Yellow/Red) 🟡🔴

**UC-4.1: Update Settings (Yellow - Requires Approval)**
```
User: "Increase cache TTL to 2 hours"
Agent: [Shows diff]

📝 Proposed Settings Change:

File: .olav/settings.json
Field: cache.ttl
Current: 3600 (1 hour)
New: 7200 (2 hours)

Impact: Cache entries will live longer
Risk: Low (reversible)

Diff:
  "cache": {
-   "ttl": 3600,
+   "ttl": 7200,
    "max_size": 1000
  }

✅ Validation passed (value in range 60-86400)

[Approve] [Reject]
```

**UC-4.2: Skill Optimization (Red - Suggestion Only)**
```
User: "Optimize the Query Agent skill"
Agent: [Analysis and suggestions only]

📊 Query Agent Analysis:

Usage: 234 executions in last 30 days
Success rate: 91% (212/234)
Failed queries: 22 (need analysis)

🔍 Suggestions:

1. **Add example patterns** (improve accuracy +5%)
   Add to SKILL.md examples:
   - "show device X interface Y"
   - "compare config between A and B"

2. **Optimize tool_choice** (reduce latency -15%)
   Current: auto
   Suggested: ["sql_query", "nornir_execute"]
   Reason: 87% of queries use only these 2 tools

3. **Adjust temperature** (improve consistency +8%)
   Current: 0.0
   Suggested: 0.1
   Reason: Need slight creativity for query variation

⚠️ These are SUGGESTIONS ONLY
Apply manually by editing .olav/skills/query/SKILL.md

[Show Detailed Analysis] [Export to File]
```

---

## 🛠️ Tool Inventory & Permission Matrix

### Existing Tools (Re-usable)

| Tool | Current Location | Permission Level | HITL Required | Description |
|------|-----------------|------------------|---------------|-------------|
| `sync_all` | `tools/sync_tools.py` | 🟢 Green | No | Create network snapshot |
| `get_sync_age` | `tools/sync_tools.py` | 🟢 Green | No | Check last sync time |
| `list_devices` | `tools/network.py` | 🟢 Green | No | List all devices |
| `nornir_execute` | `tools/network.py` | 🟡 Yellow | Configurable | Execute network command |
| `format_and_export` | `tools/data_export.py` | 🟢 Green | No | Export data to CSV/JSON |

### New Tools (To Be Implemented)

| Tool Name | Permission | HITL | Input | Output | Description |
|-----------|-----------|------|-------|--------|-------------|
| `system_health_check` | 🟢 Green | No | `None` | SystemHealthReport | Check database, cache, API status |
| `analyze_skill_usage` | 🟢 Green | No | `skill_id?: str` | SkillUsageStats | Show skill execution statistics |
| `clean_cache` | 🟢 Green | No | `cache_type: str` | CleanReport | Clean query cache, LLM cache |
| `clean_checkpoints` | 🟢 Green | No | `None` | CleanReport | Clean LangGraph checkpoints |
| `rebuild_vector_index` | 🟢 Green | No | `None` | IndexStats | Rebuild knowledge base index |
| `add_device` | 🟡 Yellow | **Yes** | DeviceConfig | ApprovalRequired | Add to Nornir inventory |
| `update_device` | 🟡 Yellow | **Yes** | DeviceUpdate | ApprovalRequired | Modify device config |
| `remove_device` | 🟡 Yellow | **Yes** | `device_name: str` | ApprovalRequired | Remove from inventory |
| `update_settings` | 🟡 Yellow | **Yes** | SettingsUpdate | ApprovalRequired | Modify settings.json |
| `analyze_configuration` | 🟢 Green | No | `config_file: str` | ConfigReport | Audit configuration files |
| `suggest_skill_optimization` | 🔴 Red | No | `skill_id: str` | OptimizationSuggestions | Analyze and suggest improvements |
| `validate_inventory` | 🟢 Green | No | `None` | ValidationReport | Check inventory integrity |
| `backup_configuration` | 🟢 Green | No | `message: str` | GitCommitHash | Create Git backup |

### Forbidden Operations (Hard-Coded Block)

```python
FORBIDDEN_OPERATIONS = [
    "modify_env_file",           # .env contains API keys
    "delete_main_database",      # main.duckdb is critical
    "execute_arbitrary_shell",   # Security risk
    "modify_source_code",        # src/ directory
    "bulk_device_delete",        # Too dangerous without review
    "disable_all_skills",        # System paralysis
]
```

---

## 🏗️ Architecture Design

### Agent Structure

```
SystemAdminAgent (SubAgent)
├── Tools (16 functions)
│   ├── 🟢 Green (10): health_check, analytics, clean_cache, etc.
│   ├── 🟡 Yellow (5): add/update/remove_device, update_settings
│   └── 🔴 Red (1): suggest_optimization
│
├── Middleware
│   ├── HumanInTheLoopMiddleware (DeepAgents native)
│   ├── ValidationMiddleware (custom)
│   └── AuditLogMiddleware (custom)
│
├── SKILL.md Configuration
│   ├── Tool list
│   ├── Permission matrix
│   ├── HITL rules
│   └── Examples
│
└── Safety Mechanisms
    ├── Input validation
    ├── Git auto-backup
    ├── Operation rollback
    └── Audit logging
```

### DeepAgents HITL Integration

**Leverage Existing HITL Configuration**:
```python
# config/settings.py (already exists)
class HITLSettings(BaseSettings):
    require_approval_for_write: bool = True  # ← Use this
    require_approval_for_skill_update: bool = True
    approval_timeout_seconds: int = 300
```

**Tool Decorator with HITL**:
```python
from deepagents.core import tool, require_approval

@tool
@require_approval(category="device_management")  # DeepAgents native
def add_device(
    device_name: str,
    ip_address: str,
    platform: str,
    groups: list[str] = None,
) -> str:
    """Add device to Nornir inventory with user confirmation.
    
    Safety:
        - Validates all inputs
        - Shows diff preview
        - Requires HITL approval (automatic via decorator)
        - Creates Git backup
        - Tests connectivity
        - Auto-rollback on failure
    """
    # 1. Validate inputs
    errors = validate_device_config(device_name, ip_address, platform)
    if errors:
        return f"❌ Validation failed: {errors}"
    
    # 2. Generate configuration
    config = generate_nornir_config(device_name, ip_address, platform, groups)
    
    # 3. Create diff preview (shown in approval UI)
    diff = generate_inventory_diff(current_inventory, config)
    
    # 4. DeepAgents HITL automatically shows approval dialog here
    #    User sees: diff, validation status, rollback info
    #    Agent pauses until user approves/rejects
    
    # 5. If approved, create backup
    backup_hash = backup_configuration(f"Add device {device_name}")
    
    # 6. Apply configuration
    try:
        apply_inventory_change(config)
    except Exception as e:
        rollback_to_commit(backup_hash)
        return f"❌ Failed to apply: {e}. Rolled back."
    
    # 7. Validate connectivity
    if not test_device_connectivity(device_name):
        rollback_to_commit(backup_hash)
        return f"❌ Device unreachable. Rolled back."
    
    # 8. Log success
    log_audit("ADD_DEVICE", device_name, success=True)
    
    return f"✅ Device {device_name} added successfully"
```

**Native Approval Flow** (DeepAgents handles this):
```
User: "Add router R2 with IP 192.168.1.2"
  ↓
Orchestrator → SystemAdminAgent
  ↓
SystemAdminAgent calls add_device()
  ↓
@require_approval decorator triggers
  ↓
DeepAgents shows approval modal:
  ┌─────────────────────────────────────┐
  │ 📝 Approval Required                │
  │                                     │
  │ Operation: add_device               │
  │ Device: R2                          │
  │ IP: 192.168.1.2                     │
  │ Platform: cisco_ios                 │
  │                                     │
  │ Diff Preview:                       │
  │ + R2:                               │
  │ +   hostname: 192.168.1.2           │
  │ +   platform: cisco_ios             │
  │                                     │
  │ [✓ Approve] [✗ Reject] [📝 Edit]   │
  └─────────────────────────────────────┘
  ↓
User clicks [Approve]
  ↓
Tool execution continues
  ↓
Result returned to user
```

### File I/O with DeepAgents

**DeepAgents Native File Tools** (use these instead of custom implementation):
```python
from deepagents.tools.file import read_file, write_file, list_files

# Example: Read inventory
inventory_content = await read_file(".olav/nornir/inventory.yaml")

# Example: Write settings (with validation)
new_settings = {...}
await write_file(".olav/settings.json", json.dumps(new_settings, indent=2))

# Example: List config files
config_files = await list_files(".olav/", pattern="*.json")
```

**Safety Wrapper** (add validation layer):
```python
async def safe_write_config(
    file_path: str,
    content: str,
    validate_fn: callable,
) -> str:
    """Write configuration file with validation and backup.
    
    Args:
        file_path: Target file path
        content: New file content
        validate_fn: Validation function (returns errors or None)
    
    Returns:
        Success/error message
    
    Safety:
        - Validates content before writing
        - Creates Git backup
        - Atomic write (temp file + rename)
        - Rollback on validation failure after write
    """
    # 1. Validate content
    errors = validate_fn(content)
    if errors:
        return f"❌ Validation failed: {errors}"
    
    # 2. Backup current file
    backup_hash = backup_configuration(f"Before modifying {file_path}")
    
    # 3. Write to temp file
    temp_path = f"{file_path}.tmp"
    await write_file(temp_path, content)
    
    # 4. Validate written file
    written_content = await read_file(temp_path)
    if validate_fn(written_content):
        os.remove(temp_path)
        rollback_to_commit(backup_hash)
        return f"❌ Validation failed after write. Rolled back."
    
    # 5. Atomic rename
    os.rename(temp_path, file_path)
    
    # 6. Log success
    log_audit("WRITE_CONFIG", file_path, success=True)
    
    return f"✅ Successfully updated {file_path}"
```

---

## 🔐 Safety Mechanisms

### 1. Input Validation Layer

```python
class ConfigValidator:
    """Validate all configuration changes before applying."""
    
    @staticmethod
    def validate_device_config(device_name: str, ip: str, platform: str) -> list[str]:
        """Validate device configuration."""
        errors = []
        
        # Name validation
        if not re.match(r'^[A-Za-z0-9_-]+$', device_name):
            errors.append("Device name must be alphanumeric")
        
        # IP validation
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            errors.append(f"Invalid IP address: {ip}")
        
        # Platform validation
        valid_platforms = [
            "cisco_ios", "cisco_nxos", "arista_eos",
            "juniper_junos", "nokia_sros"
        ]
        if platform not in valid_platforms:
            errors.append(f"Unsupported platform: {platform}")
        
        # Check for duplicates
        existing_devices = list_devices()
        if device_name in existing_devices:
            errors.append(f"Device {device_name} already exists")
        
        return errors
    
    @staticmethod
    def validate_settings_update(key: str, value: Any) -> list[str]:
        """Validate settings.json updates."""
        errors = []
        
        # Define allowed keys and their constraints
        SETTINGS_SCHEMA = {
            "cache.ttl": {"type": int, "min": 60, "max": 86400},
            "cache.max_size": {"type": int, "min": 100, "max": 10000},
            "execution.timeout": {"type": int, "min": 5, "max": 300},
            "database.backup_interval": {"type": int, "min": 3600, "max": 604800},
        }
        
        if key not in SETTINGS_SCHEMA:
            errors.append(f"Unknown setting: {key}")
            return errors
        
        schema = SETTINGS_SCHEMA[key]
        
        # Type check
        if not isinstance(value, schema["type"]):
            errors.append(f"Invalid type for {key}: expected {schema['type'].__name__}")
        
        # Range check
        if "min" in schema and value < schema["min"]:
            errors.append(f"Value {value} below minimum {schema['min']}")
        if "max" in schema and value > schema["max"]:
            errors.append(f"Value {value} above maximum {schema['max']}")
        
        return errors
```

### 2. Git Auto-Backup System

```python
import subprocess
from datetime import datetime
from pathlib import Path

def backup_configuration(message: str) -> str:
    """Create Git commit backup before configuration changes.
    
    Args:
        message: Commit message
    
    Returns:
        Git commit hash (for rollback)
    """
    try:
        # Add all .olav config files
        subprocess.run(
            ["git", "add", ".olav/nornir/", ".olav/settings.json", ".olav/skills/"],
            check=True,
            cwd=Path(__file__).parent.parent.parent
        )
        
        # Commit with timestamp
        timestamp = datetime.now().isoformat()
        full_message = f"[AUTO-BACKUP] {message} ({timestamp})"
        
        result = subprocess.run(
            ["git", "commit", "-m", full_message],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent
        )
        
        # Extract commit hash
        commit_hash = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).parent.parent.parent
        ).stdout.strip()
        
        logger.info(f"Created backup: {commit_hash} - {message}")
        return commit_hash
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Backup failed: {e}")
        raise RuntimeError(f"Cannot proceed without backup: {e}")


def rollback_to_commit(commit_hash: str) -> None:
    """Rollback to previous Git commit.
    
    Args:
        commit_hash: Target commit to rollback to
    """
    try:
        subprocess.run(
            ["git", "reset", "--hard", commit_hash],
            check=True,
            cwd=Path(__file__).parent.parent.parent
        )
        logger.info(f"Rolled back to {commit_hash}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Rollback failed: {e}")
        raise RuntimeError(f"Manual recovery required: {e}")
```

### 3. Audit Logging

```python
import json
from datetime import datetime
from pathlib import Path
from config.paths import OLAV_DIR

AUDIT_LOG = OLAV_DIR / "audit" / "system_changes.log"

def log_audit(
    operation: str,
    details: dict,
    success: bool,
    user_confirmed: bool = False,
    rollback: bool = False,
) -> None:
    """Log all system administration operations.
    
    Args:
        operation: Operation type (e.g., "ADD_DEVICE")
        details: Operation details
        success: Whether operation succeeded
        user_confirmed: Whether user approved via HITL
        rollback: Whether rollback occurred
    """
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    
    entry = {
        "timestamp": datetime.now().isoformat(),
        "operation": operation,
        "details": details,
        "success": success,
        "user_confirmed": user_confirmed,
        "rollback": rollback,
    }
    
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    
    logger.info(f"Audit log: {operation} - {'SUCCESS' if success else 'FAILED'}")
```

### 4. Rollback Testing

```python
def test_device_connectivity(device_name: str, timeout: int = 10) -> bool:
    """Test if newly added device is reachable.
    
    Args:
        device_name: Device hostname
        timeout: Connection timeout
    
    Returns:
        True if device is reachable, False otherwise
    """
    from olav.tools.network_executor import get_nornir
    
    try:
        nr = get_nornir()
        device = nr.filter(name=device_name)
        
        if not device.inventory.hosts:
            logger.error(f"Device {device_name} not in inventory")
            return False
        
        # Simple TCP check to SSH port
        import socket
        host_obj = device.inventory.hosts[device_name]
        hostname = host_obj.hostname
        port = host_obj.port or 22
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        
        result = sock.connect_ex((hostname, port))
        sock.close()
        
        if result == 0:
            logger.info(f"Device {device_name} is reachable")
            return True
        else:
            logger.error(f"Device {device_name} unreachable (port {port})")
            return False
            
    except Exception as e:
        logger.error(f"Connectivity test failed: {e}")
        return False
```

---

## 📦 Implementation Phases

### Phase 1: Foundation (Week 1) 🟢

**Deliverables**:
- [ ] Create `src/olav/agents/system_admin_agent.py`
- [ ] Create `src/olav/tools/system_admin_tools.py`
- [ ] Create `.olav/skills/system_admin/SKILL.md`
- [ ] Implement 5 green-tier tools:
  - [ ] `system_health_check`
  - [ ] `analyze_skill_usage`
  - [ ] `clean_cache`
  - [ ] `clean_checkpoints`
  - [ ] `validate_inventory`

**Testing**:
```bash
uv run pytest tests/unit/agents/test_system_admin_agent.py -v
uv run pytest tests/e2e/test_system_admin_scenarios.py -v
```

**Test Coverage**:
- Read-only operations
- No HITL needed
- Fast execution (<5s)

### Phase 2: HITL Integration (Week 2) 🟡

**Deliverables**:
- [ ] Integrate DeepAgents `HumanInTheLoopMiddleware`
- [ ] Implement validation layer (`ConfigValidator`)
- [ ] Implement Git backup system
- [ ] Implement 3 yellow-tier tools with HITL:
  - [ ] `add_device` (with confirmation)
  - [ ] `update_device` (with diff preview)
  - [ ] `remove_device` (with safety check)

**Testing**:
```bash
# Interactive test (requires user approval)
uv run python -m pytest tests/e2e/test_system_admin_hitl.py -v -s
```

**Test Coverage**:
- HITL approval flow
- Git backup creation
- Rollback on failure
- Validation errors

### Phase 3: Configuration Management (Week 3) 🟡

**Deliverables**:
- [ ] Implement `update_settings` with validation
- [ ] Implement `backup_configuration` CLI integration
- [ ] Add atomic file write operations
- [ ] Add configuration diff previews

**Testing**:
```bash
# Test settings update with HITL
uv run olav query "increase cache TTL to 2 hours"
```

### Phase 4: Advanced Features (Week 4) 🔴

**Deliverables**:
- [ ] Implement `suggest_skill_optimization` (analysis only)
- [ ] Implement `analyze_configuration` (audit report)
- [ ] Add audit log viewer
- [ ] Add rollback history viewer

**Testing**:
```bash
# Test suggestion mode (no writes)
uv run olav query "suggest optimizations for Query Agent skill"
```

---

## 🧪 Testing Strategy

### Unit Tests

```python
# tests/unit/agents/test_system_admin_agent.py
import pytest
from olav.agents.system_admin_agent import SystemAdminAgent
from olav.tools.system_admin_tools import (
    system_health_check,
    add_device,
    validate_device_config,
)

class TestSystemAdminAgent:
    """Test system admin agent functionality."""
    
    @pytest.mark.asyncio
    async def test_health_check_no_approval_needed(self):
        """Green-tier operation should not require approval."""
        result = await system_health_check()
        
        assert "database" in result.lower()
        assert "cache" in result.lower()
        # Should execute without user interaction
    
    def test_validate_device_config_valid(self):
        """Valid device config should pass validation."""
        errors = validate_device_config(
            device_name="R2",
            ip="192.168.1.2",
            platform="cisco_ios"
        )
        assert len(errors) == 0
    
    def test_validate_device_config_invalid_ip(self):
        """Invalid IP should fail validation."""
        errors = validate_device_config(
            device_name="R2",
            ip="999.999.999.999",
            platform="cisco_ios"
        )
        assert "Invalid IP" in errors[0]
    
    @pytest.mark.asyncio
    @pytest.mark.hitl
    async def test_add_device_requires_approval(self, mock_approval):
        """Yellow-tier operation should require HITL approval."""
        # Mock user approves
        mock_approval.return_value = True
        
        result = await add_device(
            device_name="R2",
            ip_address="192.168.1.2",
            platform="cisco_ios"
        )
        
        assert "✅" in result
        assert "R2" in result
        # Verify approval was requested
        assert mock_approval.called
```

### E2E Tests

```python
# tests/e2e/test_system_admin_scenarios.py
import pytest
from tests.utils.cli_tester import CLITester, CLIAssertions

@pytest.mark.e2e
class TestSystemAdminScenarios:
    """Test real user scenarios with system admin agent."""
    
    @pytest.mark.asyncio
    async def test_health_check_via_query(self):
        """User asks for system health check."""
        tester = CLITester(timeout=30.0)
        result = tester.run_query("How is the system doing?")
        
        CLIAssertions.assert_success(result)
        CLIAssertions.assert_contains(result, "database")
        CLIAssertions.assert_contains(result, "cache")
    
    @pytest.mark.asyncio
    async def test_clean_cache_autonomous(self):
        """Clean cache should execute without approval."""
        tester = CLITester(timeout=30.0)
        result = tester.run_query("clean the cache")
        
        CLIAssertions.assert_success(result)
        CLIAssertions.assert_contains(result, "cache cleaned")
        # Should complete quickly (autonomous)
        assert result.duration < 10.0
```

### HITL Interactive Tests

```python
# tests/e2e/test_system_admin_hitl.py
import pytest
from tests.utils.hitl_tester import HITLTester

@pytest.mark.e2e
@pytest.mark.hitl
@pytest.mark.interactive
class TestSystemAdminHITL:
    """Test HITL approval flows (requires human interaction)."""
    
    @pytest.mark.asyncio
    async def test_add_device_approval_flow(self):
        """Test device addition with approval."""
        tester = HITLTester()
        
        # Start operation
        with tester.approval_context():
            result = await tester.execute_query(
                "Add router R2 with IP 192.168.1.2"
            )
            
            # Verify approval UI shown
            approval = tester.wait_for_approval(timeout=60)
            assert approval.operation == "add_device"
            assert "R2" in approval.details
            assert "192.168.1.2" in approval.details
            
            # Simulate user approval
            approval.approve()
            
            # Verify result
            assert result.success
            assert "R2" in result.message
```

---

## 📋 Acceptance Criteria

### Phase 1 (Green Operations)
- [ ] Health check shows database size, cache status, API config
- [ ] Usage analytics shows top 5 skills and commands
- [ ] Clean cache removes files without confirmation
- [ ] All operations execute in <5 seconds
- [ ] Zero HITL approvals required
- [ ] 100% test coverage for green-tier tools

### Phase 2 (HITL Integration)
- [ ] Device addition shows diff preview
- [ ] User approval required before writing
- [ ] Git backup created automatically
- [ ] Rollback works on failure
- [ ] Connectivity test validates new devices
- [ ] Audit log records all operations
- [ ] HITL timeout error after 5 minutes

### Phase 3 (Configuration Management)
- [ ] Settings updates show before/after comparison
- [ ] Invalid values rejected with clear error
- [ ] Atomic writes (no partial updates)
- [ ] Configuration files remain valid YAML/JSON
- [ ] User can reject and cancel operation

### Phase 4 (Advanced Features)
- [ ] Skill optimization generates actionable suggestions
- [ ] Configuration audit identifies issues
- [ ] Audit log viewer shows last 100 operations
- [ ] Rollback history shows last 10 backups

---

## 🤖 Semantic Task Scheduling & Automation

### Overview

**Vision**: Transform OLAV from reactive tool to proactive network operations manager by enabling natural language task scheduling with automatic lifecycle management.

**User Experience**:
```
User: "每10分钟监控R1的BGP状态和接口流量，持续24小时，邮件通知我"

Agent: [Parses intent → Creates task → Schedules execution → Auto-expires]

✅ Scheduled task created: monitor_r1_bgp_240208_103000
- Device: R1
- Checks: BGP status, Interface traffic
- Frequency: Every 10 minutes
- Duration: 24 hours (expires 2026-02-09 10:30)
- Notification: Email (hourly aggregation)

Task will auto-expire and send completion report after 24 hours.
```

### Architecture Components

#### 1. Task Configuration (`.olav/tasks/scheduled/*.yaml`)

**YAML Schema**:
```yaml
---
task_id: monitor_r1_bgp_240208_103000
task_name: "Monitor R1 BGP Status"
task_type: monitoring  # monitoring | inspection | backup | maintenance
status: active  # active | paused | expired | cancelled | archived
created_at: 2026-02-08T10:30:00Z
created_by: user_query  # user_query | manual | system
expires_at: 2026-02-09T10:30:00Z

# Execution Schedule
schedule:
  type: cron  # cron | interval | event_triggered
  expression: "*/10 * * * *"
  description: "Every 10 minutes for 24 hours"
  timezone: Asia/Shanghai
  start_time: 2026-02-08T10:30:00Z
  end_time: 2026-02-09T10:30:00Z

# What to Execute
execution:
  agent: query_agent
  action: monitor_device
  parameters:
    device: R1
    checks:
      - type: bgp_status
        threshold:
          established_sessions_min: 2
      - type: interface_traffic
        interfaces: [Gi0/0, Gi0/1]
        threshold:
          utilization_max: 80
  timeout: 60
  retry_on_failure: 2

# Notification
notification:
  on_success: false
  on_failure: true
  on_threshold_breach: true
  on_completion: true
  channels:
    - type: email
      to: admin@example.com
      aggregation: hourly
    - type: slack
      channel: "#network-ops"
      aggregation: every_5_executions

# Storage & Archival
storage:
  save_results: true
  results_path: .olav/data/task_results/monitor_r1_bgp_240208_103000/
  retention_days: 30
  archive_on_expire: true

# Documentation (Human-readable)
documentation:
  original_request: "每10分钟监控R1的BGP状态和接口流量，持续24小时，邮件通知我"
  parsed_intent:
    device: R1
    checks: [bgp_status, interface_traffic]
    frequency: every_10_minutes
    duration: 24_hours
    notification: email
```

#### 2. Directory Structure

```
.olav/
├── tasks/
│   ├── scheduled/           # Active & paused tasks
│   │   ├── monitor_r1_bgp_240208_103000.yaml
│   │   ├── daily_backup_240207.yaml
│   │   └── weekly_inspection.yaml
│   │
│   ├── templates/           # User-defined task templates
│   │   ├── device_monitoring.yaml
│   │   ├── config_backup.yaml
│   │   └── health_inspection.yaml
│   │
│   └── archived/            # Expired/cancelled tasks
│       └── 2026-02/
│           └── monitor_r1_bgp_240208_103000.yaml
│
├── data/
│   └── task_results/        # Task execution results
│       └── monitor_r1_bgp_240208_103000/
│           ├── execution_001.json
│           ├── execution_002.json
│           └── summary.md
│
└── settings.json            # Notification channels config
    └── notification:
        ├── email: {...}
        ├── slack: {...}
        └── webhook: {...}
```

#### 3. Task Management Tools

**New Tools for System Admin Agent**:

| Tool | Permission | Description |
|------|-----------|-------------|
| `create_scheduled_task` | 🟡 Yellow | Create task from natural language |
| `list_scheduled_tasks` | 🟢 Green | Show active/paused/expired tasks |
| `show_task_details` | 🟢 Green | Get task config and execution history |
| `modify_scheduled_task` | 🟡 Yellow | Update frequency/duration/notification |
| `pause_scheduled_task` | 🟡 Yellow | Temporarily pause task |
| `resume_scheduled_task` | 🟡 Yellow | Resume paused task |
| `cancel_scheduled_task` | 🟡 Yellow | Stop and archive task |

**Tool Implementation Example**:
```python
@tool
@require_approval(category="task_management")
async def create_scheduled_task(
    description: str,
    device: str = None,
    checks: list[str] = None,
    frequency: str = None,
    duration_hours: int = None,
    notification_channel: str = "email",
    notification_email: str = None,
) -> str:
    """Create scheduled task from natural language.
    
    Args:
        description: Natural language task description
        device: Target device (e.g., "R1")
        checks: Monitoring checks (e.g., ["bgp_status", "interface_traffic"])
        frequency: Execution frequency (e.g., "every 10 minutes", "*/10 * * * *")
        duration_hours: Task lifetime in hours (e.g., 24)
        notification_channel: Where to send results ("email", "slack", "webhook")
        notification_email: Email address for notifications
    
    Example:
        User: "每10分钟监控R1的BGP状态，持续24小时，邮件通知"
        
        Agent parses and calls:
        create_scheduled_task(
            description="Monitor R1 BGP status every 10 minutes for 24 hours",
            device="R1",
            checks=["bgp_status"],
            frequency="*/10 * * * *",
            duration_hours=24,
            notification_channel="email"
        )
    
    Safety:
        - Requires HITL approval (yellow tier)
        - Rate limit: 10 tasks/day per user
        - Max duration: 7 days
        - Validates device exists
        - Creates Git backup of task configs
    """
    # Parse natural language with LLM if parameters missing
    if not all([device, checks, frequency, duration_hours]):
        parsed = await llm_parse_task_description(description)
        device = device or parsed["device"]
        checks = checks or parsed["checks"]
        frequency = frequency or parsed["frequency"]
        duration_hours = duration_hours or parsed["duration_hours"]
    
    # Validate inputs
    errors = validate_task_params(device, checks, frequency, duration_hours)
    if errors:
        return f"❌ Validation failed: {', '.join(errors)}"
    
    # Generate task config
    task_id = f"monitor_{device}_{datetime.now().strftime('%y%m%d_%H%M%S')}"
    task_config = {
        "task_id": task_id,
        "task_name": f"Monitor {device}",
        "status": "active",
        "created_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(hours=duration_hours)).isoformat(),
        "schedule": {
            "expression": parse_frequency_to_cron(frequency),
            "description": frequency,
        },
        "execution": {
            "agent": "query_agent",
            "parameters": {"device": device, "checks": checks},
        },
        "notification": {
            "channels": [{"type": notification_channel, "to": notification_email}],
        },
        "documentation": {
            "original_request": description,
        }
    }
    
    # Save task config
    task_file = Path(f".olav/tasks/scheduled/{task_id}.yaml")
    save_yaml(task_file, task_config)
    
    # Register with scheduler
    register_task_with_scheduler(task_id)
    
    return f"""✅ Scheduled task created

Task ID: {task_id}
Device: {device}
Checks: {', '.join(checks)}
Frequency: {frequency}
Duration: {duration_hours} hours
Expires: {task_config['expires_at']}

Commands:
- View: olav task show {task_id}
- Modify: olav task modify {task_id}
- Cancel: olav task cancel {task_id}
- List all: olav task list
"""
```

#### 4. Task Scheduler (Background Service)

**Location**: `src/olav/cron/task_scheduler.py`

**Responsibilities**:
- Monitor `.olav/tasks/scheduled/` for active tasks
- Execute tasks at scheduled times
- Check task expiration and auto-archive
- Store execution results
- Trigger notifications on thresholds/failures/completion

**Execution Flow**:
```
┌─────────────────────────────────────────────────────────────┐
│              Task Scheduler (Background Loop)                │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  1. Scan .olav/tasks/scheduled/*.yaml (every 60s)           │
│     ↓                                                         │
│  2. For each active task:                                    │
│     - Check if expired → Archive + Send completion report    │
│     - Check if due → Execute task                            │
│     ↓                                                         │
│  3. Execute task:                                            │
│     - Call orchestrator with task parameters                 │
│     - Store result to .olav/data/task_results/               │
│     - Check thresholds                                       │
│     ↓                                                         │
│  4. Notification:                                            │
│     - On failure: Immediate alert                            │
│     - On threshold breach: Alert with details                │
│     - On success: Aggregate (hourly/per-N-executions)        │
│     - On expiration: Completion summary                      │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

**Scheduler Startup**:
```bash
# Option 1: Run as background process
uv run python -m olav.cron.scheduler &

# Option 2: Run as systemd service
sudo systemctl start olav-scheduler

# Option 3: Include in OLAV main process
# (Scheduler runs in separate asyncio task)
```

#### 5. Natural Language Task Parser

**LLM-Powered Intent Extraction**:
```python
async def llm_parse_task_description(description: str) -> dict:
    """Parse natural language task request.
    
    Example:
        Input: "每10分钟监控R1的BGP状态和接口流量，持续24小时，邮件通知"
        
        Output: {
            "device": "R1",
            "checks": ["bgp_status", "interface_traffic"],
            "frequency": "*/10 * * * *",
            "duration_hours": 24,
            "notification_channel": "email"
        }
    """
    prompt = f"""Parse this monitoring task request into structured parameters:

"{description}"

Extract:
1. device: Target device name (e.g., "R1", "SW1", "all")
2. checks: List of monitoring checks:
   - bgp_status: BGP session state
   - interface_traffic: Interface utilization
   - cpu_memory: CPU and memory usage
   - ospf_neighbors: OSPF adjacency
   - config_changes: Configuration drift
3. frequency: Cron expression:
   - "every 10 minutes" → "*/10 * * * *"
   - "every hour" → "0 * * * *"
   - "every 6 hours" → "0 */6 * * *"
   - "daily at 2am" → "0 2 * * *"
4. duration_hours: Task lifetime (extract from "持续24小时", "for 48 hours")
5. notification_channel: "email", "slack", "webhook"

Return JSON only, no explanation.
"""
    
    response = await llm.ainvoke(prompt)
    return json.loads(response.content)
```

### Use Cases

#### UC-5.1: Post-Implementation Monitoring
```
Scenario: User completed network change, needs temporary monitoring

User: "我刚完成R1的BGP配置升级，每10分钟检查BGP状态和接口流量，监控24小时，有问题邮件通知我"

Agent: [Parses intent]
- Device: R1
- Checks: BGP status, interface traffic
- Frequency: Every 10 minutes
- Duration: 24 hours
- Alert on: Threshold breach, failures
- Report: Email completion summary after 24 hours

[Creates task with approval]

✅ Task 'monitor_r1_bgp_240208_103000' created
Next execution: 2026-02-08 10:40:00
Will auto-expire: 2026-02-09 10:30:00
```

#### UC-5.2: Task Management Queries
```
User: "现在有哪些自动化任务在运行？"

Agent: [Calls list_scheduled_tasks()]

## Active Scheduled Tasks (3)

### Monitor R1 BGP Status (`monitor_r1_bgp_240208_103000`)
- Device: R1
- Schedule: Every 10 minutes
- Created: 2026-02-08 10:30
- Expires: 2026-02-09 10:30 (14 hours remaining)
- Status: Active (12 executions so far)

### Daily Config Backup (`daily_backup_240207`)
- Device: All devices
- Schedule: Daily at 2:00 AM
- Created: 2026-02-07
- Expires: Never
- Status: Active

### Weekly Health Inspection (`weekly_inspection`)
- Device: Core routers
- Schedule: Every Sunday at 8:00 AM
- Created: 2026-02-01
- Expires: Never
- Status: Active
```

#### UC-5.3: Task Modification
```
User: "把R1监控改成每5分钟一次"

Agent: [Parses: task=R1监控, modify=frequency, new_value=5分钟]

[Calls modify_scheduled_task with approval]

📝 Proposed Change:

Task: monitor_r1_bgp_240208_103000
Field: Frequency
Current: Every 10 minutes (*/10 * * * *)
New: Every 5 minutes (*/5 * * * *)

Impact: More frequent monitoring (2x executions)
Remaining duration: 14 hours → ~168 executions

[Approve] [Reject]

[After approval]
✅ Task updated. Next execution: 10:35:00
```

#### UC-5.4: Task Cancellation
```
User: "取消R1的监控任务"

Agent: [Identifies task by device name]

[Shows confirmation]
⚠️ Cancel Task?

Task: monitor_r1_bgp_240208_103000
Device: R1
Executions completed: 45/144
Data collected: 45 results

[Approve] [Reject]

[After approval]
✅ Task cancelled and archived
Completion report sent to admin@example.com
Results saved to: .olav/tasks/archived/2026-02/monitor_r1_bgp_240208_103000/
```

### Integration with Notification Channels

**Email Configuration** (`.olav/settings.json`):
```json
{
  "notification": {
    "email": {
      "enabled": true,
      "smtp_host": "smtp.gmail.com",
      "smtp_port": 587,
      "smtp_user": "olav@example.com",
      "smtp_password_env": "EMAIL_PASSWORD",
      "from_address": "olav@example.com",
      "templates": {
        "task_completion": ".olav/notification/templates/task_completion.html",
        "threshold_breach": ".olav/notification/templates/threshold_breach.html"
      }
    },
    "slack": {
      "enabled": true,
      "webhook_url_env": "SLACK_WEBHOOK_URL",
      "default_channel": "#network-ops",
      "mention_on_critical": "@oncall"
    },
    "webhook": {
      "enabled": false,
      "endpoints": [
        {
          "name": "pagerduty",
          "url": "https://events.pagerduty.com/v2/enqueue",
          "auth_token_env": "PAGERDUTY_TOKEN"
        }
      ]
    }
  }
}
```

### Task Templates

**Pre-defined Templates** (`.olav/tasks/templates/device_monitoring.yaml`):
```yaml
---
# Template: Device Monitoring
# Usage: olav task create --template device_monitoring --device R1 --duration 24

template_id: device_monitoring
template_name: "Device Health Monitoring"
description: "Comprehensive device monitoring (BGP, interfaces, CPU/memory)"

# User needs to provide
required_parameters:
  - device
  - duration_hours

# Default values (user can override)
defaults:
  frequency: "*/10 * * * *"  # Every 10 minutes
  checks:
    - type: bgp_status
      threshold:
        established_sessions_min: 2
    - type: interface_traffic
      threshold:
        utilization_max: 80
    - type: cpu_memory
      threshold:
        cpu_max: 80
        memory_max: 80
  notification:
    on_threshold_breach: true
    on_completion: true
    channels:
      - type: email
        aggregation: hourly

# Generated task will use this structure
task_structure: |
  task_id: monitor_{{device}}_{{timestamp}}
  task_name: "Monitor {{device}} Health"
  task_type: monitoring
  ...
```

**Using Templates**:
```
User: "用设备监控模板创建一个R1的任务，持续48小时"

Agent: [Loads template, fills parameters]
✅ Created task from template 'device_monitoring'
- Device: R1
- Duration: 48 hours
- Checks: BGP status, Interface traffic, CPU/Memory
- Frequency: Every 10 minutes (default from template)
```

### Implementation Phases

**Phase 1: Basic Task Scheduling** (Week 2-3)
- [ ] Implement task configuration schema (YAML)
- [ ] Create `.olav/tasks/` directory structure
- [ ] Implement 7 task management tools
- [ ] Add task parsing with LLM
- [ ] Task lifecycle: create → execute → expire → archive

**Phase 2: Scheduler Integration** (Week 3-4)
- [ ] Implement TaskScheduler background service
- [ ] Cron expression parser and executor
- [ ] Task execution via orchestrator
- [ ] Result storage and history

**Phase 3: Notifications** (Week 4)
- [ ] Email notification integration
- [ ] Slack webhook integration
- [ ] Threshold-based alerts
- [ ] Aggregated reporting

**Phase 4: Advanced Features** (Post-MVP)
- [ ] Task templates system
- [ ] Event-driven tasks (not just cron)
- [ ] Task dependencies (Task B runs after Task A)
- [ ] Conditional execution (run if threshold met)

### Benefits

1. **Natural Language Operations** ✅
   - No need to learn cron syntax
   - No need to manually clean up tasks
   - Speak in terms of business operations

2. **Automatic Lifecycle Management** ✅
   - Auto-expire after duration
   - Auto-archive completed tasks
   - Auto-send completion reports

3. **Proactive Monitoring** ✅
   - Schedule post-implementation checks
   - Continuous monitoring during critical windows
   - Alert on anomalies without manual checking

4. **Configuration as Code** ✅
   - Task configs in Git-trackable YAML
   - User and agent can both edit
   - Version controlled, auditable

5. **Multi-Channel Notifications** ✅
   - Email for detailed reports
   - Slack for real-time alerts
   - Webhook for external integrations

---

## 🚀 Future Enhancements (Post-MVP)

### Advanced HITL Features
- **Batch approvals**: Approve multiple similar operations
- **Approval templates**: Pre-approve specific operation types
- **Delegation**: Assign approval to team members
- **Timeout handling**: Default action on no response

### Intelligent Automation
- **Learning mode**: Track approved patterns, auto-approve similar
- **Risk scoring**: Calculate risk score for each operation
- **Anomaly detection**: Flag unusual operations for review

### Integration
- **Slack/Teams notifications**: Send approval requests to chat
- **Web UI**: Graphical approval interface
- **API mode**: RESTful approval endpoints
- **Audit dashboard**: Visual audit log viewer

---

## 📚 References

- **DeepAgents HITL**: [Documentation](https://deepagents.ai/docs/hitl)
- **OLAV Architecture**: [docs/reference/ARCHITECTURE.md](../reference/ARCHITECTURE.md)
- **OLAV Configuration**: [docs/reference/CONFIGURATION_REFERENCE.md](../reference/CONFIGURATION_REFERENCE.md)
- **SubAgent Development**: [docs/reference/SUB_AGENT_DEVELOPMENT_GUIDE.md](../reference/SUB_AGENT_DEVELOPMENT_GUIDE.md)
- **OLAV HITL Settings**: [config/settings.py](../../config/settings.py) (Lines 253-263)

---

**Status**: 🟡 Planning Complete - Ready for Implementation  
**Next Step**: Create `src/olav/agents/system_admin_agent.py` skeleton  
**Owner**: OLAV Development Team  
**Target Date**: Phase 1 by 2026-02-15

---

**Version**: v1.0.0 (2026-02-08)
