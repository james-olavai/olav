# System Admin Agent - Planning Summary

**Date**: 2026-02-08  
**Status**: ✅ Planning Complete  

---

## 📋 Fast Track Summary

### What We're Building
**System Administration SubAgent** - An AI assistant that can manage OLAV configuration, monitor system health, and perform administrative tasks with graduated permissions and human oversight.

### Why It's Safe
- **DeepAgents Native HITL**: Uses built-in `@require_approval` decorator
- **3-Tier Permission Model**: 🟢 Autonomous → 🟡 Requires Approval → 🔴 Suggestion Only
- **Auto-Backup**: Every config change creates Git commit
- **Auto-Rollback**: Failed operations automatically rollback
- **Audit Log**: Every operation logged to `.olav/audit/system_changes.log`

---

## 🎯 Core Use Cases

### 1. System Monitoring (Green - Autonomous)
```
User: "How is the system doing?"
Agent: [Executes without approval]
  ✓ Database: 2.3 GB
  ✓ Cache hit rate: 87%
  ✓ Last sync: 2 hours ago
  ✓ Active devices: 42/45
```

### 2. Device Management (Yellow - Requires Approval)
```
User: "Add router R2 with IP 192.168.1.2"
Agent: [Shows diff, waits for approval]
  
  📝 Proposed Device Addition:
  
  Device: R2
  IP: 192.168.1.2
  Platform: cisco_ios
  
  Diff:
  + R2:
  +   hostname: 192.168.1.2
  +   platform: cisco_ios
  
  [Approve] [Reject]
```

### 3. Skill Optimization (Red - Suggestion Only)
```
User: "Optimize the Query Agent skill"
Agent: [Analysis only, no changes]
  
  📊 Suggestions:
  1. Add example patterns (improve accuracy +5%)
  2. Optimize tool_choice (reduce latency -15%)
  3. Adjust temperature (improve consistency +8%)
  
  ⚠️ Apply manually by editing SKILL.md
```

---

## 🛠️ Tool Inventory

### Phase 1: Green Tier (10 tools, Week 1)
| Tool | Description | HITL |
|------|-------------|------|
| `system_health_check` | Database, cache, API status | ❌ No |
| `analyze_skill_usage` | Skill execution statistics | ❌ No |
| `clean_cache` | Remove cache files | ❌ No |
| `clean_checkpoints` | Remove old checkpoints | ❌ No |
| `validate_inventory` | Check inventory integrity | ❌ No |
| `analyze_configuration` | Audit config files | ❌ No |
| `rebuild_vector_index` | Rebuild knowledge index | ❌ No |
| `view_audit_log` | Show admin operations log | ❌ No |
| `backup_configuration` | Manual Git backup | ❌ No |
| `list_recent_backups` | Show backup history | ❌ No |

### Phase 2: Yellow Tier (5 tools, Week 2-3)
| Tool | Description | HITL |
|------|-------------|------|
| `add_device` | Add to Nornir inventory | ✅ **Yes** |
| `update_device` | Modify device config | ✅ **Yes** |
| `remove_device` | Remove from inventory | ✅ **Yes** |
| `update_settings` | Modify settings.json | ✅ **Yes** |
| `batch_add_devices` | Add multiple devices | ✅ **Yes** |

### Phase 3: Red Tier (2 tools, Week 4)
| Tool | Description | HITL |
|------|-------------|------|
| `suggest_skill_optimization` | Analyze and suggest improvements | ❌ No (read-only) |
| `analyze_failed_queries` | Pattern analysis of failures | ❌ No (read-only) |

### Forbidden (Never Implement)
- ❌ `modify_env_file` - Contains API keys
- ❌ `delete_main_database` - Data loss
- ❌ `execute_arbitrary_shell` - Security risk
- ❌ `modify_source_code` - Code integrity
- ❌ `disable_all_skills` - System paralysis

**Total**: 17 tools (10 green, 5 yellow, 2 red)

---

## 🔐 Safety Mechanisms

### 1. DeepAgents HITL (Native)
```python
@tool
@require_approval(category="device_management")  # ← DeepAgents decorator
def add_device(device_name: str, ip_address: str, platform: str) -> str:
    """Add device with automatic approval UI."""
    # DeepAgents shows approval modal automatically
    # Execution pauses until user approves/rejects
    # Timeout after 5 minutes (configurable)
```

**Approval UI** (DeepAgents provides):
- Shows operation details
- Displays diff preview
- Validation status
- [Approve] [Reject] [Edit] buttons
- Timeout countdown

### 2. Input Validation
```python
class ConfigValidator:
    @staticmethod
    def validate_device_config(name: str, ip: str, platform: str) -> list[str]:
        """Validate before operation."""
        errors = []
        if not re.match(r'^[A-Za-z0-9_-]+$', name):
            errors.append("Invalid device name")
        if not is_valid_ip(ip):
            errors.append("Invalid IP address")
        if platform not in SUPPORTED_PLATFORMS:
            errors.append("Unsupported platform")
        return errors
```

### 3. Auto-Backup (Git)
```python
def backup_configuration(message: str) -> str:
    """Create Git commit before every config change."""
    subprocess.run(["git", "add", ".olav/"])
    subprocess.run(["git", "commit", "-m", f"[AUTO-BACKUP] {message}"])
    return subprocess.run(["git", "rev-parse", "HEAD"]).stdout
```

### 4. Auto-Rollback
```python
try:
    apply_config(new_config)
    if not validate_after_write(new_config):
        raise ValidationError("Post-write validation failed")
except Exception as e:
    rollback_to_commit(backup_hash)
    return f"❌ Failed: {e}. Rolled back."
```

### 5. Audit Logging
```python
# .olav/audit/system_changes.log
{
  "timestamp": "2026-02-08T10:30:15Z",
  "operation": "ADD_DEVICE",
  "details": {"device": "R2", "ip": "192.168.1.2"},
  "user_confirmed": true,
  "success": true,
  "rollback": false
}
```

---

## 📦 File Structure

```
src/olav/
├── agents/
│   └── system_admin_agent.py          # Main agent (new)
├── tools/
│   └── system_admin_tools.py          # 17 tool functions (new)
└── middlewares/
    ├── validation_middleware.py        # Input validation (new)
    └── audit_middleware.py             # Operation logging (new)

.olav/
├── skills/
│   └── system_admin/
│       └── SKILL.md                    # Agent config (new)
└── audit/
    └── system_changes.log              # Audit log (new)

tests/
├── unit/
│   └── agents/
│       └── test_system_admin_agent.py  # Unit tests (new)
└── e2e/
    ├── test_system_admin_scenarios.py  # E2E tests (new)
    └── test_system_admin_hitl.py       # HITL interactive tests (new)

docs/plan/
├── system_admin_agent_plan.md          # Main plan (created)
├── system_admin_tools_inventory.md     # Tool list (created)
└── system_admin_summary.md             # This file (created)
```

---

## 🚀 Implementation Roadmap

### Phase 1: Green Operations (Week 1)
**Goal**: Read-only monitoring and safe operations

**Tasks**:
- [ ] Create `src/olav/agents/system_admin_agent.py` skeleton
- [ ] Implement 5 green-tier tools:
  - [ ] `system_health_check()`
  - [ ] `analyze_skill_usage()`
  - [ ] `clean_cache()`
  - [ ] `clean_checkpoints()`
  - [ ] `validate_inventory()`
- [ ] Create `.olav/skills/system_admin/SKILL.md`
- [ ] Write unit tests
- [ ] Write E2E tests

**Success Criteria**:
- [ ] Health check shows database, cache, API status
- [ ] Usage analytics shows top skills
- [ ] Cache cleaning works without approval
- [ ] All tests pass
- [ ] Zero HITL interactions

### Phase 2: HITL Integration (Week 2)
**Goal**: Device management with user approval

**Tasks**:
- [ ] Integrate DeepAgents `HumanInTheLoopMiddleware`
- [ ] Create `ConfigValidator` class
- [ ] Create Git backup system
- [ ] Implement 3 yellow-tier tools:
  - [ ] `add_device()` with `@require_approval`
  - [ ] `update_device()` with diff preview
  - [ ] `remove_device()` with confirmation
- [ ] Write HITL interactive tests

**Success Criteria**:
- [ ] Device addition shows approval modal
- [ ] User can approve/reject operations
- [ ] Git backup created before changes
- [ ] Rollback works on failure
- [ ] Audit log records operations

### Phase 3: Configuration Management (Week 3)
**Goal**: Safe settings updates

**Tasks**:
- [ ] Implement `update_settings()` with validation
- [ ] Add atomic file write operations
- [ ] Create settings validation schema
- [ ] Test configuration updates

**Success Criteria**:
- [ ] Settings updates show before/after
- [ ] Invalid values rejected
- [ ] Atomic writes (no partial updates)
- [ ] Configuration remains valid JSON

### Phase 4: Advanced Features (Week 4)
**Goal**: Analysis and suggestions

**Tasks**:
- [ ] Implement `suggest_skill_optimization()`
- [ ] Implement `analyze_failed_queries()`
- [ ] Add audit log viewer
- [ ] Add backup history viewer

**Success Criteria**:
- [ ] Suggestions based on usage patterns
- [ ] No automatic modifications
- [ ] Clear actionable recommendations

---

## 🧪 Testing Strategy

### Unit Tests (Fast)
```bash
# Test individual tools
uv run pytest tests/unit/agents/test_system_admin_agent.py -v

# Test validation
uv run pytest tests/unit/tools/test_config_validator.py -v
```

### E2E Tests (Real Scenarios)
```bash
# Test green operations (no approval)
uv run pytest tests/e2e/test_system_admin_scenarios.py::TestGreenOperations -v

# Test yellow operations (with mock approval)
uv run pytest tests/e2e/test_system_admin_scenarios.py::TestYellowOperations -v
```

### HITL Interactive Tests (Manual)
```bash
# Test approval flow (requires human interaction)
uv run pytest tests/e2e/test_system_admin_hitl.py -v -s
```

---

## 📊 Risk Assessment

| Risk | Severity | Mitigation | Status |
|------|----------|------------|--------|
| Invalid config breaks system | 🔴 High | Validation + backup + rollback | ✅ Addressed |
| User approves dangerous operation | 🟡 Medium | Clear diff preview, validation warnings | ✅ Addressed |
| Git backup fails | 🟡 Medium | Block operation if backup fails | ✅ Addressed |
| Concurrent modifications | 🟡 Medium | File locking, atomic writes | ⏳ TODO |
| LLM generates invalid config | 🟡 Medium | Schema validation, type checking | ✅ Addressed |
| Timeout during approval | 🟢 Low | DeepAgents handles timeout (5 min default) | ✅ Addressed |
| Audit log fills disk | 🟢 Low | Log rotation, size limits | ⏳ TODO |

**Overall Risk**: 🟢 **Low** with implemented mitigations

---

## ✅ Acceptance Criteria

### Phase 1 (Green Operations)
- [ ] Health check executes in <5 seconds
- [ ] Cache cleaning removes files successfully
- [ ] No approval prompts shown
- [ ] 100% test coverage for green tools

### Phase 2 (HITL Integration)
- [ ] Device addition shows diff preview
- [ ] Approval modal appears with details
- [ ] User can approve/reject
- [ ] Git backup created automatically
- [ ] Rollback works on failure
- [ ] Audit log records all operations

### Phase 3 (Configuration Management)
- [ ] Settings updates show before/after
- [ ] Invalid values rejected with clear error
- [ ] Atomic writes (no partial updates)
- [ ] Configuration files remain valid

### Phase 4 (Advanced Features)
- [ ] Skill optimization generates suggestions
- [ ] No automatic modifications
- [ ] Audit log viewer shows last 100 operations

---

## 🎓 Key Learnings from Planning

### 1. DeepAgents HITL is Perfect Fit
✅ **Native approval mechanism** - No need to build custom approval system  
✅ **Decorator-based** - Simple `@require_approval` decorator  
✅ **Configurable** - Timeout, categories, approval UI  
✅ **Already integrated** - OLAV has `HITLSettings` in `config/settings.py`

### 2. File I/O is Already Available
✅ **DeepAgents has native file tools** - `read_file()`, `write_file()`  
✅ **Can wrap with safety layer** - Add validation, backup, rollback  
✅ **Git integration straightforward** - subprocess calls to git commands

### 3. Existing Tools are Reusable
✅ **`sync_all`** - Perfect for "create snapshot"  
✅ **`list_devices`** - Already available for inventory queries  
✅ **CLI commands** - Can wrap as tools (`olav clean`, `olav doctor`)

### 4. 3-Tier Permission Model Works
✅ **Green (10 tools)** - Most operations are read-only or safe  
✅ **Yellow (5 tools)** - Only critical writes need approval  
✅ **Red (2 tools)** - Analysis/suggestions don't need approval  
✅ **Forbidden (8 operations)** - Hard-coded blocks for security

### 5. Safety Mechanisms are Comprehensive
✅ **Validation** - Prevent invalid configs  
✅ **Backup** - Git commit before changes  
✅ **Rollback** - Auto-revert on failure  
✅ **Audit** - Log all operations  
✅ **HITL** - Human oversight for writes

---

## 📚 Documentation Status

| Document | Status | Purpose |
|----------|--------|---------|
| [system_admin_agent_plan.md](system_admin_agent_plan.md) | ✅ Complete | Detailed implementation plan |
| [system_admin_tools_inventory.md](system_admin_tools_inventory.md) | ✅ Complete | Tool catalog with specs |
| [system_admin_summary.md](system_admin_summary.md) | ✅ Complete | Executive summary (this file) |

**Total**: 3 planning documents, ~800 lines

---

## 🚀 Next Steps

### Immediate (Today)
1. ✅ Review planning documents
2. ⏳ Get feedback on approach
3. ⏳ Confirm tool list and priorities
4. ⏳ Decide on implementation timeline

### This Week
1. ⏳ Create agent skeleton
2. ⏳ Implement first 5 green tools
3. ⏳ Write unit tests
4. ⏳ Test with real queries

### This Month
1. ⏳ Complete Phase 1 (green tier)
2. ⏳ Complete Phase 2 (HITL integration)
3. ⏳ Complete Phase 3 (config management)
4. ⏳ Complete Phase 4 (advanced features)

---

## 💡 Key Success Factors

1. **DeepAgents Native Features** - Leverage built-in HITL, don't reinvent
2. **Graduated Permissions** - Start with safe operations, add risky ones carefully
3. **Comprehensive Safety** - Validation + Backup + Rollback + Audit
4. **Clear User Experience** - Show diffs, clear approval prompts, helpful errors
5. **Thorough Testing** - Unit + E2E + HITL interactive tests

---

## 📞 Questions for Review

1. **Tool Priority**: Is the green/yellow/red tier split correct?
2. **HITL Timeout**: Is 5 minutes reasonable, or should it be configurable per operation?
3. **Audit Log**: Should we add log rotation or size limits from the start?
4. **Concurrent Access**: Should we implement file locking in Phase 1 or defer?
5. **Batch Operations**: Is `batch_add_devices` a Phase 2 or Phase 3+ feature?

---

**Status**: ✅ Planning Complete - Ready for Implementation Review  
**Next Milestone**: Phase 1 Implementation (Week 1)  
**Target Completion**: End of Month (4 weeks)  

---

**Version**: v1.0.0 (2026-02-08)  
**Author**: OLAV Development Team
