# OLAV Onboarding Architecture & Development Plan

**Date**: 2026-03-01  
**Status**: Design Phase → TDD Implementation  
**Priority**: Critical Infrastructure  

---

## 1. Architecture Overview

### 1.1 Phase Distribution

```
Phase 1: Cold Bootstrap (Python — Traditional)
  ├─ api.json 存在性 + 合法性检查
  ├─ hosts.yaml 存在性 + 格式检查
  ├─ parallel_tcp_check() — SSH 连通性测试
  └─ LLMFactory.test_connectivity() — LLM 启动检验
  
Phase 2-7: Intelligent Orchestration (LLM-Driven Agent)
  └─ Config Agent 通过 DuckDB 查询驱动智能决策
     ├─ 状态查询 (execute_sql)
     ├─ 增量采集 (take_snapshot with devices=[...])
     ├─ 模板修复 (learner sub-agent)
     ├─ 文件重解析 (reparse_outputs — NEW)
     └─ 拓扑重建 (discovery sub-agent)
```

### 1.2 Data Flow

```
用户: uv run olav onboard
    │
    └─► onboard.py Phase 1 (Python)
            ├─ 检查 api.json
            ├─ 检查 hosts.yaml
            ├─ TCP 连通检查
            ├─ LLM 连通检查 ← 成功时才继续
            └─ 生成 preflight_report.json
                │ {llm: ok, inventory_count: 4, reachable_devices: [...], db_state: {...}}
                │
                ▼
            TUI 启动 (--initial-message preflight_report.json)
                │
                ▼
            Config Agent ReadS preflight_report
                │
                └─► 根据 onboard intent 机制自动编排后续步骤
                    ├─ 查询 DB: 是否已初始化 (sync_schemas)？
                    ├─ 查询 DB: 设备表是否为空？需要 sync_inventory？
                    ├─ 查询 DB: 命令表是否为空？需要 sync_commands？
                    ├─ 查询 DB: 有哪些 (device, command) gap？
                    ├─ 只对 gap 目标: take_snapshot(devices=[...])
                    ├─ 若 parsing 仍失败: learner agent 修复
                    ├─ 修复后: reparse_outputs() 重解析本地 raw 文件 (不 SSH)
                    └─ 最后: generate_topology() 重建链接
```

---

## 2. Architecture Decisions

### 决策1：Phase 1 与 Phase 2 边界清晰划分

**Phase 1 (Python, onboard.py)**
- ✅ 检查文件存在性 (api.json, hosts.yaml)
- ✅ 检查网络连通性 (parallel_tcp_check)
- ✅ 检查 LLM 可用性 (LLMFactory.test_connectivity)
- ✅ 生成 preflight 上下文报告

**Phase 2-7 (LLM Agent, Config Agent)**
- ✅ 所有业务逻辑通过 Agent 驱动
- ✅ 决策基于 DuckDB 状态查询，不是 Python 条件
- ✅ 子 Agent (sync/learner/discovery) 通过工具调用

### 决策2：增量执行，仅修复 Gap

当前（错误）：
```
onboard → take_snapshot(all_devices, all_commands)
          └─ 无论哪个设备/命令有问题，全部重新采集
```

正确的方式：
```
onboard → 查询 parsed_outputs WHERE parsed_data = '{}' 
          └─ 得到 {device, command} gap 列表
              └─ 仅对 gap 目标: take_snapshot(devices=[R3], commands=["show interfaces"])
                  └─ 节省网络资源，加快流程
```

### 决策3：模板修复后使用 reparse_only，不重连设备

当前（浪费）：
```
learner 修复模板.textfsm
    └─ 无法验证 → 必须重新 SSH 采集
```

正确的方式：
```
learner 修复模板.textfsm
    └─ reparse_outputs(device, command)
        └─ 读 exports/snapshots/latest/raw/R3/show_interfaces_terse.txt
            └─ 用新模板重跑 TextFSM
                └─ UPDATE parsed_outputs (同一 snapshot_id)
                    └─ 不需要任何 SSH！
```

---

## 3. Current State Analysis

### 3.1 Config Agent 已有能力

✅ **完全可用**:
- `execute_sql` — 查询 DB 状态 ← Orchestrator 目前需要委托给 Discovery 子 Agent
- `sync_schemas` — 初始化表结构
- `sync_inventory` — 导入设备清单
- `sync_commands` — 同步命令模板
- `take_snapshot(devices=[...])` — 增量采集（签名已支持）
- `generate_template` + `save_template` — 模板生成和保存（learner）
- `generate_topology` — 拓扑生成（discovery）

### 3.2 关键缺口

| 缺口 | 影响 | 优先级 |
|---|---|---|
| **缺口1：无 `reparse_outputs` 工具** | 模板修复后必须重连 SSH | 🔴 Critical |
| **缺口2：Orchestrator 无 `onboard` 意图处理** | Agent 不知道 onboard 流程的特殊规则 | 🔴 Critical |
| **缺口3：Orchestrator 无直接 `execute_sql`** | 状态查询必须委托子 Agent，低效 | 🟡 High |

### 3.3 完整特性清单

需要在 Orchestrator 的 system.md 里编织规则：

```markdown
## Onboard Intent

When user or preflight_context indicates "onboard":

**Step 1: Infrastructure Check**
  ├─ execute_sql("SELECT COUNT(*) FROM devices") 
  ├─ if empty → sync_inventory()
  └─ if not empty → skip

**Step 2: Command Registry**
  ├─ execute_sql("SELECT COUNT(*) FROM commands")
  ├─ if empty → sync_commands()
  └─ if not empty → skip

**Step 3: Gap Analysis**
  └─ execute_sql("""
       SELECT DISTINCT device_name, command 
       FROM parsed_outputs
       WHERE parsed_data = '{}' OR json_array_length(parsed_data) = 0
     """)
  └─ if gap_list is empty → all_done ✅
  └─ if gap_count < 20% of all → proceed to targeted collection

**Step 4: Targeted Collection**
  └─ Call Sync Agent: take_snapshot(devices=[gap_devices], categories=[gap_commands])

**Step 5: Post-Collection Status**
  └─ Re-run gap analysis
  └─ if new_gaps exist → proceed to repair

**Step 6: Template Repair Loop**
  └─ Call Learner Agent: generate_template() for gap[device, command]
  └─ Save new template
  └─ Call NEW reparse_outputs(device, command) ← CRITICAL MISSING TOOL
  └─ Re-check if gap[device, command] now has data

**Step 7: Topology Rebuild**
  └─ Call Discovery Agent: generate_topology()

**Final: Report Quality**
  └─ execute_sql coverage query
  └─ Report: "Onboarding Complete: X% coverage, Y topology links"
```

---

## 4. Gap Closure Roadmap (TDD)

### 4.1 Gap #1: New Tool `reparse_outputs`

**Location**: `.olav/workspace/config/sync/tools/reparse_outputs.py`

**TDD Test**: `tests/sync/test_reparse_outputs.py`

```python
# TEST FIRST: Verify new tool behavior
def test_reparse_outputs_basic():
    """Test that reparse_outputs updates parsed_outputs without SSH."""
    # Setup: R1 has raw file + old broken template
    raw_file = Path("exports/snapshots/2026-03-01/raw/R1/show_interfaces_terse.txt")
    assert raw_file.exists()
    
    # Before: parsed_data is {}
    before = db.execute("SELECT parsed_data FROM parsed_outputs WHERE device_name='R1'").fetchone()
    assert before['parsed_data'] == '{}'
    
    # Action: Call reparse_outputs with fixed template
    result = reparse_outputs(device='R1', command='show interfaces terse')
    
    # After: parsed_data contains actual records
    after = db.execute("SELECT parsed_data FROM parsed_outputs WHERE device_name='R1'").fetchone()
    assert after['parsed_data'] != '{}'
    assert json.loads(after['parsed_data'])[0]['INTERFACE'] is not None
```

**Tool Signature**:
```python
@tool
def reparse_outputs(device: str, command: str) -> dict:
    """Re-parse local raw output files using current TextFSM template.
    
    Args:
        device: Device name (e.g. "R1")
        command: Command name (e.g. "show interfaces terse")
    
    Returns:
        {
            "success": True|False,
            "records": int,  # 新解析出的记录数
            "error": str|None,
            "snapshot_id": str  # 更新到的 snapshot_id
        }
    
    Reads:
      - Template from .olav/templates/{platform}_{command}.textfsm
      - Raw output from exports/snapshots/latest/raw/{device}/*.txt
    
    Writes:
      - Updates parsed_outputs table (same snapshot_id, new parsed_data)
    
    No SSH Connection Required!
    """
```

### 4.2 Gap #2: Orchestrator `onboard` Intent in system.md

**Location**: `.olav/workspace/config/prompts/orchestrator.md`

**TDD Test**: `tests/config/test_onboard_intent.py`

```python
def test_onboard_intent_empty_db():
    """Test that Agent recognizes empty DB and runs sync_schemas."""
    preflight = {
        "db_state": {
            "devices_table": 0,
            "commands_table": 0,
            "parsed_outputs": 0
        }
    }
    
    # Initialize with empty DB context
    agent = ConfigAgent(initial_context=preflight)
    result = agent.invoke("onboard")
    
    # Should have called sync_schemas
    assert "sync_schemas" in result.get("tools_called", [])
```

**Changes to orchestrator.md**:

```markdown
## Intent: Onboarding (New Section)

### Recognition
- User says "onboard", "initialize", "setup"
- System receives preflight_report.json with empty DB indicators

### Behavioral Rules
1. Always call sync_schemas first (idempotent)
2. Before each optional step, query DB state
3. Only deploy take_snapshot for gap devices (not all devices)
4. After learner fixes template, call reparse_outputs (not SSH)
5. At end, call generate_topology only once

### CRITICAL RULE
Never run full snapshot if gaps < 20% of device/command matrix.
Always prefer targeted + reparse over global refresh.
```

### 4.3 Gap #3: Add `execute_sql` to Orchestrator Direct Tools

**Location**: `.olav/workspace/config/AGENT.md`

**Changes**:

```yaml
# BEFORE
subagents:
  - path: ./sync/SKILL.md

# AFTER
subagents:
  - path: ./sync/SKILL.md

tools:  # NEW: Orchestrator direct tools
  - execute_sql      # ← Can query DB for state decisions
  - read_file        # ← Read config/reports
  - format_and_export # ← Generate reports
```

**TDD Test**: `tests/config/test_orchestrator_tools.py`

```python
def test_orchestrator_has_execute_sql():
    """Verify Orchestrator can directly query DB without sub-agent."""
    agent = ConfigAgent()
    
    # Should have execute_sql in direct tools
    assert "execute_sql" in agent.tools
    
    # Should be able to call it
    result = agent.tools["execute_sql"](
        query="SELECT COUNT(*) as cnt FROM devices"
    )
    assert "cnt" in result[0]
```

---

## 5. Implementation Roadmap (TDD)

### Phase A: Foundation (Week 1)

**PR A1: New Tool `reparse_outputs`**
- [ ] Write test: `tests/sync/test_reparse_outputs.py`
  - [ ] Test basic reparse
  - [ ] Test with multiple devices
  - [ ] Test error handling (missing raw file)
- [ ] Implement: `.olav/workspace/config/sync/tools/reparse_outputs.py`
- [ ] Register in: `sync/SKILL.md` (add to tools list)
- [ ] Test passes ✅

**PR A2: Agent Direct SQL Tool**
- [ ] Write test: `tests/config/test_orchestrator_tools.py`
- [ ] Update: `config/AGENT.md` (add execute_sql)
- [ ] Update: `config/tools/execute_sql.py` registration
- [ ] Test passes ✅

### Phase B: Intelligence (Week 2)

**PR B1: Onboard Intent in Orchestrator**
- [ ] Write test: `tests/config/test_onboard_intent.py`
  - [ ] Test preflight JSON parsing
  - [ ] Test gap detection flow
  - [ ] Test gap-only snapshot calling
- [ ] Update: `config/prompts/orchestrator.md`
  - [ ] Add "Intent: Onboarding" section
  - [ ] Add "Behavioral Rules" with reparse emphasis
  - [ ] Add "State Query Pattern" examples
- [ ] Test passes ✅

**PR B2: TUI Integration**
- [ ] Modify: `src/olav/cli/commands/onboard.py`
  - [ ] Phase 1 → generate preflight_report.json
  - [ ] Phase 2 → TUI with --initial-message flag
  - [ ] Content reading from preflight JSON
- [ ] Integration test: TUI receives preflight and starts Agent ✅

### Phase C: E2E Validation (Week 3)

**Test Suite: Full Onboarding Flow**
- [ ] `tests/e2e/test_onboard_empty_db.py`
  - Setup: Empty DB
  - Action: uv run olav onboard
  - Assert: sync_schemas + sync_inventory + sync_commands + take_snapshot all called
  - Assert: No redundant operations
  
- [ ] `tests/e2e/test_onboard_with_gaps.py`
  - Setup: Partial DB (some devices, some gaps)
  - Action: uv run olav onboard
  - Assert: Only gap devices called take_snapshot
  - Assert: reparse_outputs called for failed templates
  - Assert: No full dataset refresh
  
- [ ] `tests/e2e/test_onboard_idempotent.py`
  - Action: Run onboard twice
  - Assert: No duplicate data, idempotent

---

## 6. File Changes Index

### New Files
- `tests/sync/test_reparse_outputs.py`
- `tests/config/test_onboard_intent.py`
- `tests/config/test_orchestrator_tools.py`
- `tests/e2e/test_onboard_*.py` (3 files)
- `.olav/workspace/config/sync/tools/reparse_outputs.py`

### Modified Files
- `.olav/workspace/config/AGENT.md` (add execute_sql)
- `.olav/workspace/config/prompts/orchestrator.md` (add onboard intent)
- `.olav/workspace/config/sync/SKILL.md` (add reparse_outputs tool)
- `src/olav/cli/commands/onboard.py` (simplify Phase 1, add preflight JSON)

### No Changes
- `generate_template.py` — ReAct + Reflection already complete ✅
- `take_snapshot.py` — Signatures support devices=[...] ✅
- `sync_*.py` — All utilities already present ✅

---

## 7. Critical Success Criteria

✅ **Passing Tests**:
- All new tests pass (100% coverage for reparse_outputs, onboard intent)
- E2E onboarding completes without human intervention after Phase 1
- No redundant SSH calls (gap-only snapshots verified)

✅ **Code Quality**:
- `ruff check` passes
- `pyright` strict mode passes
- All new tools documented in docstrings

✅ **Architecture**:
- Orchestrator directly owns execute_sql (not delegated)
- reparse_outputs used by learner repair loop (no SSH on 2nd attempt)
- Onboard intent produces gap-only take_snapshot calls

✅ **User Experience**:
- TUI shows preflight report + begins agent loop
- User can see which steps are running (sync vs. snapshot vs. repair)
- All critical decisions logged to `.olav/logs/users/{user}.log`

---

## 8. Risk & Mitigation

| 风险 | 影响 | 缓解 |
|---|---|---|
| reparse_outputs 写入错误位置 | 数据丢失 | test with dry-run mode; verify snapshot_id match |
| Orchestrator 规则过于复杂 | Agent 决策失误 | start with simple rules; expand incrementally |
| 增量采集逻辑 Bug | 部分设备数据遗漏 | comprehensive gap detection tests |

---

## 9. Rolling Back Failed Steps

If onboard fails at any point, the design ensures **incremental state preservation**:

```
Failed at Step 3 (sync_commands)?
  → Re-run onboard → Agent queries DB → sees commands already synced → skips to next step

Failed at Step 5 (take_snapshot for R3)?
  → Re-run onboard → Agent queries DB → sees R3 still has gaps → retries just R3

Failed at Step 6 (template repair)?
  → Learner agent fixes → reparse_outputs only touches R3's data → no cross-device impact
```

**Zero side effects** if each tool reads state before acting.

---

## 10. Next Steps

1. **Create this document** in dev_docs/ (✅ done)
2. **Write Phase A tests first** (TDD) — start with test_reparse_outputs.py
3. **Implement tools** to pass tests
4. **Review Orchestrator prompt** — enhance onboard intent
5. **Run integrated E2E** — full flow once per milestone
6. **Update CHANGELOG.md** with each PR

**Target Completion**: 3 weeks (1 week per phase: Foundation → Intelligence → E2E)
