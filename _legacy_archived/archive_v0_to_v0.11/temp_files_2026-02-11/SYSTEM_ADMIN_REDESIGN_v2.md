# System-Admin Redesign v2 - Secure DIY Sandbox

**Date**: 2026-02-11  
**Type**: Architecture Improvement  
**Status**: ✅ COMPLETED  

## Summary

Implemented **permission isolation** for system-admin agent by:
1. **Restricting file access** to `.olav/` directory only
2. **Removing system operations** (cache, task scheduling, database ops)
3. **Simplified tool set** from 19 → 7 tools
4. **Enhanced safety** through clear permission boundaries

## Problem Statement

Previous design allowed system-admin to modify:
- ❌ `src/` - Core business logic
- ❌ `config/` - Global configuration
- ❌ `tests/` - Test infrastructure
- ✅ `.olav/` - User customization (correct)

This violated principle of **least privilege** - LLM agent had broader access than necessary.

## Solution

### Permission Model (Before → After)

```
BEFORE (19 tools):
├─ 5 Code Tools        (read_file, write_file, list_files, search_code, list_ws)
├─ 4 Config Tools      (backup_config, restore_config, etc.)
├─ 2 Health Tools      (health_check, get_system_stats)
├─ 4 Database Tools    (optimize, maintenance, etc.)
└─ 4 System Tools      (cache, tasks, scheduling, etc.)

AFTER (7 tools):
├─ 5 Code Tools        (read_file, write_file, list_files, search_code, list_ws)
└─ 2 Config Tools      (backup_config, restore_config)
```

### Removed Tools (12 items)

| Tool | Reason |
|------|--------|
| health_check | System operations layer - not for DIY |
| get_system_stats | System operations layer |
| optimize_database | DBA responsibility, not user customization |
| database_maintenance | DBA responsibility |
| clean_cache | System operations layer |
| get_cache_stats | Query/monitoring, not customization |
| list_cached_queries | Query/monitoring, not customization |
| schedule_task | System operations layer |
| list_scheduled_tasks | System operations layer |
| get_task_status | System operations layer |
| cancel_task | System operations layer |
| execute_task | System operations layer |

### File Access Restriction

```python
# Before: Could access
SAFE_WRITE_DIRS = {
    WORKSPACE_ROOT / "src",           # ❌ Remove
    WORKSPACE_ROOT / ".olav",         # ✅ Keep
    WORKSPACE_ROOT / "config",        # ❌ Remove
    WORKSPACE_ROOT / "tests",         # ❌ Remove
}

# After: Only .olav/
ADMIN_DIR = WORKSPACE_ROOT / ".olav"  # ✅ Single boundary
```

## Changes Made

### 1. File Permission Restriction
- **Modified**: `.olav/skills/system-admin/tools/read_file.py`
  - Changed validation to restrict to `.olav/` only
  - Returns False for any path outside `.olav/`

- **Modified**: `.olav/skills/system-admin/tools/write_file.py`
  - Changed validation to restrict to `.olav/` only
  - Prevents modifications to src/, config/, tests/

### 2. SKILL.md Updates
- **Modified**: `.olav/skills/system-admin/SKILL.md`
  - Updated description: "Configuration and Skill Customization" (removed "System Administration")
  - Updated capabilities: Removed cache, database, task scheduling
  - Removed 12 tools from tools list (kept 7)
  - Updated permission_model: Simplified to only .olav/ operations
  - Updated prompts: Focused on .olav/ customization, not system operations

### 3. Tool Cleanup
- **Deleted**: 12 wrapper tool files:
  ```
  .olav/skills/system-admin/tools/
  ├─ health_check.py ❌
  ├─ get_system_stats.py ❌
  ├─ optimize_database.py ❌
  ├─ database_maintenance.py ❌
  ├─ clean_cache.py ❌
  ├─ get_cache_stats.py ❌
  ├─ list_cached_queries.py ❌
  ├─ schedule_task.py ❌
  ├─ list_scheduled_tasks.py ❌
  ├─ get_task_status.py ❌
  ├─ cancel_task.py ❌
  └─ execute_task.py ❌
  ```

## Verification Results

### Permission Tests ✅
```
✅ .olav/OLAV.md                       → ALLOWED
✅ .olav/skills/system-admin/SKILL.md  → ALLOWED
✅ .olav/settings.json                 → ALLOWED
✅ src/olav/agents/orchestrator.py     → DENIED
✅ config/settings.py                  → DENIED
✅ tests/test_agent.py                 → DENIED
✅ README.md                           → DENIED
```

### System Functionality ✅
```
Query: 有多少个设备?
Result: [{'total_devices': 6}]
Status: ✅ Working normally
```

## Architecture Benefits

### ✅ Security
- **Principle of Least Privilege**: Agent only accesses what it needs
- **Clear Boundaries**: `.olav/` is user customization sandbox
- **Protected Core**: `src/`, `config/`, `tests/` are write-protected

### ✅ Simplicity
- **Reduced Tool Count**: 19 → 7 (63% reduction)
- **Clear Purpose**: Focus on customization, not operations
- **Maintenance**: Fewer wrapper layers to maintain

### ✅ Responsibility Separation
- **DIY Customization**: system-admin handles `.olav/` modifications
- **System Operations**: Reserved for DevOps/Admin (future: separate agent)
- **Core Development**: Protected from agent modifications

## Remaining System Operations (Future)

These capabilities are moved to potential future `devops-admin` agent:
- System health monitoring
- Cache management and optimization
- Database maintenance
- Task scheduling and automation

## User Impact

### What Still Works ✅
- Create and modify skills (in `.olav/skills/`)
- Customize agent behavior (modify SKILL.md)
- Edit configuration (`.olav/settings.json`)
- Read and understand codebase

### What's No Longer Available ❌
- Direct file writes to `src/`, `config/`, `tests/`
- System health checks
- Cache management
- Task scheduling

## Code Quality

**Tool Count**: 7 tools (down from 19)
- Code tools: 5 (self-implemented)
- Config tools: 2 (wrapper imports)

**Source Size**: Reduced maintenance burden
- Removed: 12 wrapper files (~50 lines each)
- Total removed: ~600 lines of wrapper code

## Testing Strategy

**Manual Verification** ✅
```bash
# Permission boundary test
✅ Read .olav/ files
✅ Write to .olav/ (with HITL)
✅ Denied: src/, config/, tests/

# System functionality
✅ Query execution: "有多少个设备?" → Works
✅ Agent routing: Still responsive
```

## Rollback Plan

If needed, restore from Git:
```bash
git checkout HEAD -- .olav/skills/system-admin/
```

## Next Steps (Optional)

1. **Future**: Create `devops-admin` agent for system operations
2. **Monitor**: Track if users need system-level operations
3. **Expand**: If justified, add back specific system tools

## Design Philosophy

This redesign embodies the **KISS principle** from copilot-instructions.md:

> "Simplest solution that works"
> - Avoid over-engineering
> - Prefer clarity over cleverness
> - One way to do things

**Result**: Clear boundaries, maintainable code, secure by default.

---

**Version**: v2.0  
**Author**: GitHub Copilot  
**Status**: ✅ Ready for production
