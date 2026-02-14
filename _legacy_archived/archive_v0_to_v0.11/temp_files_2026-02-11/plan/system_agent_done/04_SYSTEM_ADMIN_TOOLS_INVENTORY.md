# System Admin Agent - Tool Inventory

**Date**: 2026-02-08  
**Status**: 📋 Analysis Complete

---

## 🎯 Tool Classification Methodology

### Permission Levels

| Level | Symbol | Description | HITL Required | Auto-Execute | Examples |
|-------|--------|-------------|---------------|--------------|----------|
| **Green** | 🟢 | Read-only or reversible operations | ❌ No | ✅ Yes | Health check, analytics, create snapshot |
| **Yellow** | 🟡 | Configuration writes with validation | ✅ Yes | ❌ No | Add device, update settings |
| **Red** | 🔴 | High-risk operations (suggestion-only) | ❌ No | ❌ No | Skill optimization, bulk changes |
| **Forbidden** | 🚫 | Security-sensitive operations | N/A | ❌ Never | Modify .env, delete database |

---

## 📦 Existing Tools (Re-usable)

### From `src/olav/tools/sync_tools.py`

| Tool | Permission | HITL | Description | Current Usage |
|------|-----------|------|-------------|---------------|
| `sync_all` | 🟢 Green | No | Create network snapshot (full sync) | `olav inspect` |
| `get_sync_age` | 🟢 Green | No | Get time since last sync | Query agent |
| `get_latest_sync_dir` | 🟢 Green | No | Get path to latest sync directory | Internal |

**Analysis**:
- ✅ `sync_all` is perfect for "create snapshot" command
- ✅ `get_sync_age` useful for system health monitoring
- ⚠️ Already exposed to other agents - ensure no conflicts

### From `src/olav/tools/network.py`

| Tool | Permission | HITL | Description | Current Usage |
|------|-----------|------|-------------|---------------|
| `list_devices` | 🟢 Green | No | List all devices from inventory | Query agent, Analysis agent |
| `get_device_platform` | 🟢 Green | No | Get device platform type | Query agent |
| `nornir_execute` | 🟡 Yellow | Configurable | Execute command on device | Query agent (with safeguards) |

**Analysis**:
- ✅ `list_devices` useful for inventory audits
- ⚠️ `nornir_execute` already has command blacklist - reuse security layer

### From `src/olav/tools/data_export.py`

| Tool | Permission | HITL | Description | Current Usage |
|------|-----------|------|-------------|---------------|
| `format_and_export` | 🟢 Green | No | Export data to CSV/JSON/YAML | Query agent |

**Analysis**:
- ✅ Can use for exporting system reports
- ✅ Auto-detects format from data structure

### From `src/olav/cli/cli_main.py` (CLI Commands)

| Command | Permission | HITL | Can Wrap as Tool? | Description |
|---------|-----------|------|-------------------|-------------|
| `olav clean --cache` | 🟢 Green | No | ✅ Yes | Clean query cache | 
| `olav clean --checkpoints` | 🟢 Green | No | ✅ Yes | Clean LangGraph checkpoints |
| `olav clean --databases` | 🟡 Yellow | Yes | ✅ Yes | Clean snapshot databases |
| `olav clean --all` | 🔴 Red | Yes | ⚠️ Too dangerous | Clean everything |
| `olav doctor` | 🟢 Green | No | ✅ Yes | System health diagnostics |
| `olav version` | 🟢 Green | No | ✅ Yes | Show version info |
| `olav inspect` | 🟢 Green | No | ✅ Yes | Create network snapshot |

**Implementation Strategy**:
```python
# ❌ OLD APPROACH - CLI subprocess (DO NOT USE)
@tool
def clean_cache() -> str:
    """Clean query cache files."""
    result = subprocess.run(
        ["olav", "clean", "--cache", "--force"],
        capture_output=True,
        text=True
    )
    return result.stdout

# ✅ NEW APPROACH - Programmatic API (PREFERRED)
@tool
def clean_cache(cache_type: str = "query") -> str:
    """Clean cache files.
    
    Args:
        cache_type: Type to clean ("query" | "session" | "all")
    
    Permission: 🟡 Yellow (requires approval)
    """
    from olav.api import cache
    
    # Direct Python function call (type-safe, no subprocess)
    result = cache.clean_cache(cache_type=cache_type)
    return f"✅ Cleaned {result.files_deleted} files, freed {result.bytes_freed/1024/1024:.1f} MB"

@tool
def system_health_check() -> str:
    """Run system health diagnostics.
    
    Permission: 🟢 Green (read-only)
    """
    from olav.api import system
    
    # Programmatic API (30x faster than subprocess)
    result = system.health_check()
    return format_health_report(result)
```

**Why Programmatic API over subprocess**:
- ✅ **30x faster**: 5ms vs 150ms (no subprocess overhead)
- ✅ **Type-safe**: Pydantic models validate inputs/outputs
- ✅ **No hallucination**: Python types prevent invalid flag generation
- ✅ **Better errors**: Exceptions with details, not exit codes
- ✅ **Web GUI ready**: Same API used by FastAPI layer (future)

---

## 🆕 New Tools to Implement

### Phase 1: Green Tier (Read-Only & Low-Risk) 🟢

#### 1. `system_health_check()`
```python
@tool
def system_health_check() -> str:
    """Comprehensive system health check.
    
    Permission: 🟢 Green (read-only)
    
    Returns:
        Formatted health report including:
        - Database sizes (main.duckdb, olav.duckdb)
        - Cache status (hit rate, size, last cleanup)
        - LLM API configuration
        - Last sync time
        - Device reachability summary
    
    Implementation:
        from olav.api import system
        result = system.health_check()
    """
```

**Data Sources**:
- `olav.api.system.health_check()` → Comprehensive health data
- Returns `HealthCheckResult` with structured metrics

#### 2. `analyze_skill_usage()`
```python
@tool
def analyze_skill_usage(skill_id: str = None) -> str:
    """Analyze skill execution statistics.
    
    Permission: 🟢 Green (read-only)
    
    Args:
        skill_id: Specific skill to analyze, or None for all
    
    Returns:
        Usage statistics:
        - Execution counts
        - Success/failure rates
        - Average response time
        - Most common queries
    
    Implementation:
        from olav.api import analytics
        result = analytics.get_skill_usage(skill_id)
    """
```

**Data Sources**:
- `olav.api.analytics.get_skill_usage()` → Query checkpoint database
- Returns `SkillUsageStats` with execution history

#### 3. `clean_cache()`
```python
@tool
def clean_cache(cache_type: str = "query") -> str:
    """Clean cache files.
    
    Permission: 🟡 Yellow (requires approval)
    
    Args:
        cache_type: "query" | "session" | "all"
    
    Returns:
        Cleanup report (files removed, space freed)
    
    Implementation:
        from olav.api import cache
        result = cache.clean_cache(cache_type=cache_type)
        # Returns: CacheCleanResult(files_deleted, bytes_freed, success, message)
    """
```

**Why Yellow Tier**: Deletes user data (cache), requires confirmation

#### 4. `clean_checkpoints()`
```python
@tool
def clean_checkpoints(older_than_days: int = 7) -> str:
    """Clean old LangGraph checkpoints.
    
    Permission: 🟡 Yellow (requires approval)
    
    Args:
        older_than_days: Remove checkpoints older than N days
    
    Returns:
        Cleanup report
    
    Implementation:
        from olav.api import cache
        result = cache.clean_checkpoints(older_than_days=older_than_days)
    """
```

**Implementation**:
- Query DuckDB checkpoint database
- Delete old entries: `DELETE FROM checkpoints WHERE timestamp < ...`

#### 5. `validate_inventory()`
```python
@tool
def validate_inventory() -> str:
    """Validate Nornir inventory integrity.
    
    Returns:
        Validation report:
        - Invalid IP addresses
        - Unsupported platforms
        - Missing required fields
        - Duplicate device names
        - Unreachable devices
    """
```

**Implementation**:
- Load `.olav/nornir/inventory.yaml`
- Check each device:
  - IP format with `ipaddress.ip_address()`
  - Platform in supported list
  - Required fields present
  - No duplicates

#### 6. `analyze_configuration()`
```python
@tool
def analyze_configuration(config_file: str = "all") -> str:
    """Audit configuration files for issues.
    
    Args:
        config_file: Specific config or "all"
    
    Returns:
        Configuration audit report:
        - Syntax errors
        - Deprecated settings
        - Inconsistencies
        - Security issues
    """
```

**Files to Check**:
- `.olav/settings.json` → Settings validation
- `.olav/nornir/inventory.yaml` → Inventory validation
- `.olav/skills/*/SKILL.md` → Skill configuration validation

#### 7. `rebuild_vector_index()`
```python
@tool
def rebuild_vector_index() -> str:
    """Rebuild knowledge base vector index.
    
    Returns:
        Index rebuild report:
        - Documents processed
        - Vectors created
        - Time taken
    """
```

**Implementation**:
- If OLAV uses vector DB for knowledge base
- Delete old index
- Re-index all documents in `.olav/knowledge/`

#### 8. `view_audit_log()`
```python
@tool
def view_audit_log(
    limit: int = 20,
    operation_type: str = None,
    start_date: str = None
) -> str:
    """View system administration audit log.
    
    Args:
        limit: Number of entries to show
        operation_type: Filter by operation (e.g., "ADD_DEVICE")
        start_date: Show entries since this date
    
    Returns:
        Formatted audit log entries
    """
```

**Data Source**:
- `.olav/audit/system_changes.log`
- Parse JSON entries
- Format as table

#### 9. `backup_configuration()`
```python
@tool
def backup_configuration(message: str = "Manual backup") -> str:
    """Create manual Git backup of configuration.
    
    Args:
        message: Backup commit message
    
    Returns:
        Git commit hash and timestamp
    """
```

**Implementation**:
- Same as auto-backup used by yellow-tier tools
- User can trigger manually

#### 10. `list_recent_backups()`
```python
@tool
def list_recent_backups(limit: int = 10) -> str:
    """List recent configuration backups.
    
    Args:
        limit: Number of backups to show
    
    Returns:
        List of Git commits with [AUTO-BACKUP] tag
    """
```

**Implementation**:
- `git log --grep="[AUTO-BACKUP]" --oneline -n {limit}`

---

### Phase 2: Yellow Tier (Writes with HITL) 🟡

#### 11. `add_device()` ⭐ Core Tool
```python
@tool
@require_approval(category="device_management")
def add_device(
    device_name: str,
    ip_address: str,
    platform: str,
    groups: list[str] = None,
    username: str = None,
    password: str = None,
) -> str:
    """Add device to Nornir inventory with user confirmation.
    
    Args:
        device_name: Device hostname (e.g., "R2")
        ip_address: Device IP address
        platform: Platform type (cisco_ios, arista_eos, etc.)
        groups: Device groups (default: inferred from platform)
        username: SSH username (optional, uses default)
        password: SSH password (optional, uses default)
    
    Returns:
        Success message or error description
    
    Safety:
        - Validates all inputs
        - Shows diff preview
        - Requires HITL approval (automatic via decorator)
        - Creates Git backup
        - Tests connectivity
        - Auto-rollback on failure
    """
```

**Validation Rules**:
- Device name: alphanumeric, underscore, hyphen only
- IP address: valid IPv4/IPv6
- Platform: in supported list
- No duplicate device names
- Group exists (if specified)

**Approval UI Shows**:
- Device details
- Diff of inventory.yaml
- Groups assignment
- Validation status

#### 12. `update_device()`
```python
@tool
@require_approval(category="device_management")
def update_device(
    device_name: str,
    **kwargs
) -> str:
    """Update device configuration.
    
    Args:
        device_name: Device to update
        **kwargs: Fields to update (ip_address, platform, groups, etc.)
    
    Returns:
        Success message or error
    
    Safety:
        - Same as add_device
        - Shows before/after diff
        - Tests connectivity after update
    """
```

#### 13. `remove_device()`
```python
@tool
@require_approval(category="device_management")
def remove_device(device_name: str) -> str:
    """Remove device from inventory.
    
    Args:
        device_name: Device to remove
    
    Returns:
        Success message or error
    
    Safety:
        - Shows device info before removal
        - Requires explicit confirmation
        - Creates backup
        - Cannot be undone (except via Git rollback)
    """
```

#### 14. `update_settings()`
```python
@tool
@require_approval(category="configuration_management")
def update_settings(key: str, value: Any) -> str:
    """Update settings.json configuration.
    
    Args:
        key: Setting key (dot notation, e.g., "cache.ttl")
        value: New value
    
    Returns:
        Success message or error
    
    Allowed Keys:
        - cache.ttl (60-86400)
        - cache.max_size (100-10000)
        - execution.timeout (5-300)
        - database.backup_interval (3600-604800)
    
    Forbidden Keys:
        - Any that could break system
        - Database paths
        - API credentials
    
    Safety:
        - Validates key exists
        - Validates value type and range
        - Shows before/after comparison
        - Atomic write (temp file + rename)
        - Backup before write
    """
```

#### 15. `batch_add_devices()` (Advanced)
```python
@tool
@require_approval(category="device_management")
def batch_add_devices(devices: list[dict]) -> str:
    """Add multiple devices at once.
    
    Args:
        devices: List of device configs (each has name, ip, platform)
    
    Returns:
        Batch addition report (success/failed per device)
    
    Safety:
        - Validates all devices first
        - Shows summary and full diff
        - Requires approval for all or nothing
        - Rolls back all if any fails
        - Tests connectivity for all
    """
```

---

### Phase 3: Red Tier (Suggestion Only) 🔴

#### 16. `suggest_skill_optimization()` ⭐ Core Tool
```python
@tool
def suggest_skill_optimization(skill_id: str) -> str:
    """Analyze skill and suggest improvements (does NOT modify).
    
    Args:
        skill_id: Skill to analyze
    
    Returns:
        Optimization suggestions:
        - Usage patterns analysis
        - Success/failure analysis
        - Prompt improvements
        - Tool selection optimization
        - Temperature/model suggestions
    
    Safety:
        - READ-ONLY operation
        - Only provides suggestions
        - User must manually apply changes
    """
```

**Analysis Sources**:
- LangGraph execution logs → Success/failure patterns
- SKILL.md examples → Coverage analysis
- Tool usage statistics → tool_choice optimization

**Suggestions Include**:
1. **Add Examples**: If common queries fail, suggest adding similar examples
2. **Optimize Tools**: If 90% of queries use 2 tools, suggest tool_choice list
3. **Adjust Temperature**: If high variation in responses, suggest temperature change
4. **Prompt Improvements**: Suggest clarifying vague prompts

#### 17. `analyze_failed_queries()`
```python
@tool
def analyze_failed_queries(
    limit: int = 20,
    skill_id: str = None
) -> str:
    """Analyze recent failed queries for patterns.
    
    Args:
        limit: Number of failures to analyze
        skill_id: Filter by specific skill
    
    Returns:
        Failure analysis:
        - Common error types
        - Missing capabilities
        - Improvement suggestions
    """
```

---

### Forbidden Operations 🚫

**Hard-Coded Blocking** (never implement these):

```python
FORBIDDEN_OPERATIONS = {
    "modify_env_file": "Cannot modify .env (contains API keys)",
    "delete_main_database": "Cannot delete main.duckdb (data loss)",
    "delete_all_devices": "Cannot bulk delete without specific review",
    "execute_arbitrary_shell": "Cannot run arbitrary shell commands (security risk)",
    "modify_source_code": "Cannot modify src/ directory",
    "disable_all_skills": "Cannot disable all skills (system paralysis)",
    "modify_agent_prompts": "Cannot auto-modify agent system prompts",
    "change_llm_api_key": "Cannot modify API credentials",
}

def check_forbidden_operation(operation: str) -> None:
    """Raise exception if operation is forbidden."""
    if operation in FORBIDDEN_OPERATIONS:
        raise PermissionError(
            f"🚫 Operation '{operation}' is forbidden: "
            f"{FORBIDDEN_OPERATIONS[operation]}"
        )
```

---

## 📊 Tool Summary

### By Permission Level

| Level | Count | HITL Required | Examples |
|-------|-------|---------------|----------|
| 🟢 **Green** | 10 | No | health_check, analytics, clean_cache |
| 🟡 **Yellow** | 5 | Yes | add_device, update_settings |
| 🔴 **Red** | 2 | No | suggest_optimization, analyze_failures |
| 🚫 **Forbidden** | 8 | N/A | modify_env, delete_database |

### By Phase

| Phase | Tools | Timeline | Focus |
|-------|-------|----------|-------|
| **Phase 1** | 10 green | Week 1 | Read-only & safe operations |
| **Phase 2** | 5 yellow | Week 2-3 | HITL-protected writes |
| **Phase 3** | 2 red | Week 4 | Analysis & suggestions |

### By Data Source

| Data Source | Tools Using It | Purpose |
|-------------|----------------|---------|
| `.olav/nornir/inventory.yaml` | 4 | Device management |
| `.olav/settings.json` | 3 | Settings management |
| `.olav/cache/` | 2 | Cache management |
| LangGraph checkpoints | 3 | Usage analytics |
| `.olav/audit/system_changes.log` | 2 | Audit logs |
| Git repository | 3 | Backup/rollback |
| `olav.duckdb` | 2 | System monitoring |

---

## 🔐 Security Matrix

### Input Validation

| Tool | Validates | Rejects |
|------|-----------|---------|
| `add_device` | IP format, platform, name format | Invalid IP, unsupported platform, duplicate name |
| `update_settings` | Key exists, value type, value range | Unknown keys, wrong types, out-of-range values |
| `batch_add_devices` | All devices valid | Any invalid device (all-or-nothing) |

### Auto-Backup Triggers

| Tool | Backup Before | Rollback On Failure |
|------|---------------|---------------------|
| `add_device` | ✅ Yes | ✅ Yes (connectivity test fails) |
| `update_device` | ✅ Yes | ✅ Yes (connectivity test fails) |
| `remove_device` | ✅ Yes | ❌ No (intentional removal) |
| `update_settings` | ✅ Yes | ✅ Yes (validation fails after write) |
| `batch_add_devices` | ✅ Yes | ✅ Yes (any device fails) |

### HITL Approval Timeout

| Tool | Timeout | On Timeout |
|------|---------|------------|
| All yellow-tier | 300s (5 min) | Operation cancelled, no changes made |

---

## 🚀 Implementation Priority

### Must-Have (Phase 1)
1. ✅ `system_health_check` - Core monitoring
2. ✅ `clean_cache` - User requests frequently
3. ✅ `validate_inventory` - Prevent config issues
4. ✅ `analyze_skill_usage` - Usage insights
5. ✅ `backup_configuration` - Manual backup capability

### Should-Have (Phase 2)
1. ✅ `add_device` - Most requested feature
2. ✅ `update_device` - Natural follow-up to add
3. ✅ `remove_device` - Complete CRUD operations
4. ✅ `update_settings` - Safe config changes
5. ✅ `view_audit_log` - Compliance requirement

### Nice-to-Have (Phase 3+)
1. ⏳ `suggest_skill_optimization` - Advanced feature
2. ⏳ `batch_add_devices` - Power user feature
3. ⏳ `analyze_failed_queries` - Debugging tool
4. ⏳ `rebuild_vector_index` - If needed

---

## 📚 References

- **Main Plan**: [system_admin_agent_plan.md](system_admin_agent_plan.md)
- **Existing Tools**: 
  - [src/olav/tools/sync_tools.py](../../src/olav/tools/sync_tools.py)
  - [src/olav/tools/network.py](../../src/olav/tools/network.py)
  - [src/olav/tools/data_export.py](../../src/olav/tools/data_export.py)
- **CLI Commands**: [src/olav/cli/cli_main.py](../../src/olav/cli/cli_main.py)
- **Configuration**: [config/settings.py](../../config/settings.py)

---

**Status**: 📋 Complete - Ready for Implementation  
**Total Tools Planned**: 17 (10 green, 5 yellow, 2 red)  
**Estimated Effort**: 3-4 weeks  

---

**Version**: v1.0.0 (2026-02-08)
