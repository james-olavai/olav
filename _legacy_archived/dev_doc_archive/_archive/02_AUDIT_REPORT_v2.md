# OLAV v0.10.0 代码审计报告 - 文档与代码一致性审计

**审计日期**: 2026-02-04  
**审计范围**: docs/*.md (除 *_v2.md) 与当前代码对比  
**审计结论**: ⚠️ **多处文档与代码严重脱节，CLI 实际不可用**

---

## 📋 文档对比审计总览

| 文档 | 声称状态 | 实际状态 | 结论 |
|------|---------|---------|------|
| 00_README.md | 133 ruff错误 | 120 错误 | ⚠️ 数据过时 |
| 01_PLAN_INDEX.md | E2E 72.6% 通过 | 0 tests collected | ❌ 严重过时 |
| 02_AUDIT_REPORT.md | 版本 0.8.2 | 版本 0.9.8 | ✅ 已修复 |
| 03_EXECUTION_PLAN.md | orchestrator_old.py 存在 | 已删除 | ✅ 已修复 |
| 04_ISSUES.md | P0 全部完成 | CLI 不可用 | ❌ 虚假完成 |
| 05_TRACKING.md | Phase 0-5 100% 完成 | CLI 无法使用 | ❌ 虚假进度 |
| 06_FUTURE_ROADMAP.md | 规划文档 | 未实施 | ✅ 正常 (规划) |
| 07_ARCHITECTURE_EVOLUTION.md | 架构规划 | 未实施 | ✅ 正常 (规划) |
| 08_TESTING_GIT_CICD_GUIDE.md | 测试规范 | 未遵循 | ⚠️ 规范未执行 |
| 09_PHASE4_INDEXES.md | 索引存在 | 视图不存在 | ❌ 虚假 |
| 09_test_coverage_mapping.md | 覆盖度 85%+ | 未验证真实场景 | ⚠️ 误导 |
| 13_v0.10.0_final_summary.md | 迁移完成 | 架构正确，功能不通 | ⚠️ 部分正确 |

---

## 🔍 逐文档详细审计

### 00_README.md - 数据过时

| 声称 | 实际 | 状态 |
|------|------|------|
| "Ruff错误: 133个" | `uv run ruff check src/` = 120个 | ⚠️ 过时 |
| "E2E通过率: 72.6% (45/62)" | `pytest 00_e2e*.py` = 0 tests collected | ❌ 严重过时 |
| "总工时: 236h (10周)" | 计划存在，执行效果存疑 | ⚠️ |

### 01_PLAN_INDEX.md - 严重过时

| 声称 | 实际 | 状态 |
|------|------|------|
| "E2E测试通过率 72.6%" | 当前收集 0 个测试 | ❌ 测试文件结构变化 |
| "29 Issues" | 核心阻塞问题未列出 | ❌ Issue 清单不完整 |
| "Orchestrator迁移 ✅ 完成" | 架构正确，功能不通 | ⚠️ |

### 02_AUDIT_REPORT.md - 部分过时

| 声称 | 实际 | 状态 |
|------|------|------|
| "pyproject.toml: 0.8.2" | pyproject.toml: 0.9.8 | ✅ 已修复 |
| "__init__.py: 0.8.0" | __init__.py: 0.9.8 | ✅ 已修复 |
| "orchestrator_old.py 存在" | 已删除 | ✅ 已修复 |
| "133个lint错误" | 120个错误 | ⚠️ 改善中 |

### 03_EXECUTION_PLAN.md - 任务声称完成但CLI不可用

| Phase | 文档状态 | 实际状态 | 问题 |
|-------|---------|---------|------|
| Phase 0 | ✅ 已完成 | 部分完成 | ruff 仍有 120 错误 |
| Phase 1 | ✅ 已完成 | 不可验证 | E2E 测试无法运行 |
| Phase 2 | ✅ 已完成 | 部分完成 | 代码结构OK，功能不通 |
| Phase 3 | ✅ 已完成 | 不可验证 | 测试通过但CLI不可用 |
| Phase 4 | ✅ 已完成 | ❌ 虚假 | 索引基于不存在的视图 |
| Phase 5 | ✅ 已完成 | 部分完成 | 可观测性框架存在 |
| Phase 6 | ⏸️ 待开始 | - | 未开始 |

### 04_ISSUES.md - Issue 清单不完整

**文档声称 P0 全部完成**:
- ✅ ISSUE-001: 版本号统一 → 确实完成
- ✅ ISSUE-002: LLM配置文档 → 确实完成
- ✅ ISSUE-003: 删除冗余代码 → 确实完成
- ✅ ISSUE-004: 修复Ruff错误 → ⚠️ 仍有120个
- ✅ ISSUE-005: 测试收集错误 → ❌ 当前0个测试被收集

**文档遗漏的关键 Issue**:
- ❌ v_system 视图不存在 (阻塞设备识别)
- ❌ TAB 补全显示正则 (用户体验)
- ❌ DataGateway 数据库连接错误 (核心功能)

### 05_TRACKING.md - 虚假进度

| 声称 | 实际验证 | 结论 |
|------|---------|------|
| "设备识别 6 个设备" | `_known_devices = set()` (空) | ❌ **虚假** |
| "版本号已修复" | pyproject.toml = 0.9.8 | ✅ 正确 |
| "E2E 83 passed" | 0 tests collected | ❌ **虚假** |
| "SubAgent迁移完成" | 架构代码存在 | ✅ 正确 |
| "Phase 0-5 100% 完成" | CLI 无法使用 | ❌ **虚假** |

### 06_FUTURE_ROADMAP.md - 规划文档 (无问题)

这是 v0.11.0+ 的规划文档，描述未来能力，当前无需实施。

### 07_ARCHITECTURE_EVOLUTION.md - 规划文档 (无问题)

这是架构演进规划，当前无需实施。

### 08_TESTING_GIT_CICD_GUIDE.md - 规范未执行

| 规范要求 | 实际执行 | 状态 |
|---------|---------|------|
| "测试金字塔: E2E 10%" | E2E 测试无法运行 | ❌ |
| "tests目录结构" | 结构存在但测试不通 | ⚠️ |
| "覆盖率 >80%" | 无法验证 | ❌ |

### 09_PHASE4_INDEXES.md - 基于不存在的视图

**文档描述的索引**:
```sql
CREATE INDEX idx_v_interfaces_device_snapshot ON v_interfaces(...);
CREATE INDEX idx_v_bgp_neighbors_state ON v_bgp_neighbors(...);
CREATE INDEX idx_v_routes_device_snapshot ON v_routes(...);
```

**实际状态**: `v_interfaces`, `v_bgp_neighbors`, `v_routes` 视图**全部不存在**！

### 09_test_coverage_mapping.md - 误导性覆盖报告

| 场景 | 声称覆盖度 | 实际情况 | 状态 |
|------|-----------|---------|------|
| CLI交互 | 85% ✅ | 未测试真实交互 | ⚠️ 误导 |
| 多Agent系统 | 90% ✅ | 架构测试，非功能测试 | ⚠️ 误导 |
| Query Agent | 92% ✅ | 未测试 _known_devices 加载 | ❌ 虚假 |

### 13_v0.10.0_final_summary.md - 部分正确

| 声称 | 实际 | 状态 |
|------|------|------|
| "26 passed, 5 skipped" | 架构测试通过 | ✅ |
| "SubAgent架构完成" | 代码结构正确 | ✅ |
| "query SubAgent迁移" | 代码存在 | ✅ |
| "CLI功能验证" | CLI 无法使用 | ❌ 未验证实际功能 |

---

## 🚨 核心问题：测试驱动的虚假质量

### 问题本质

| 维度 | E2E 测试状态 | 真实 CLI 状态 | 差距 |
|------|-------------|--------------|------|
| 设备识别 | ✅ 通过 (Mock) | ❌ 全部失败 | 测试未验证真实数据库 |
| TAB 补全 | ❌ 未测试 | ❌ 乱码 | 从未测试 |
| 查询响应 | ✅ 通过 (subprocess) | ❌ 无响应 | 测试绕过 QueryAgent |
| 数据库视图 | ✅ 通过 (raw_outputs) | ❌ v_system 不存在 | 测试使用不同表 |

### 根本原因

**E2E 测试使用的是 subprocess 管道**:
```python
# tests/e2e/test_acceptance.py
result = subprocess.run(
    ["uv", "run", "olav", "query", "show interfaces"],
    capture_output=True,
    text=True,
)
```

**真实 CLI 使用的是交互式 prompt-toolkit**:
```python
# src/olav/cli/cli_main.py
user_input = await session.prompt_async("OLAV> ")
agent = QueryAgent()  # 这里加载设备列表失败
```

---

## 📊 代码与 SKILL.md 对比审计

### SKILL.md 声称 vs 代码实际状态

| SKILL.md 声称 | 代码验证 | 结论 |
|--------------|---------|------|
| "v_system 视图可用" | `v_system` 不存在于 `snapshots.duckdb` | ❌ **虚假** |
| "v_interfaces 视图可用" | 不存在 | ❌ **虚假** |
| "v_routes 视图可用" | 不存在 | ❌ **虚假** |
| "v_bgp_neighbors 视图可用" | 不存在 | ❌ **虚假** |
| "v_ospf_neighbors 视图可用" | 不存在 | ❌ **虚假** |
| "v_device_status 视图可用" | 不存在 | ❌ **虚假** |
| "v_arp 视图可用" | 不存在 | ❌ **虚假** |

### 数据库结构问题

**期望 (SKILL.md 和代码引用)**:
```sql
-- 代码引用的视图
SELECT * FROM v_system      -- QueryAgent._load_known_devices()
SELECT * FROM v_interfaces  -- routing_rules.yaml
SELECT * FROM v_routes      -- 多处引用
SELECT * FROM v_bgp         -- 多处引用
```

**实际 (2026-02-04 验证)**:
```sql
-- snapshots.duckdb (DataGateway.query_snapshots 连接此库)
Tables: ['query_cache', 'schema_version']  -- ❌ 无视图!

-- olav.duckdb (设备数据实际位置)
Tables: ['audit_logs', 'command_cache', 'device_capabilities', 
         'knowledge_chunks', 'knowledge_sources', 'raw_outputs', 
         'sync_metadata', 'v_device_capabilities']
Devices: ['R1', 'R2', 'R3', 'R4', 'SW1', 'SW2']  -- ✅ 数据存在
```

### 3. 代码流程断点分析

```
用户输入: "list ip addresses on R2"
    │
    ▼
cli_main.py → OlavPromptSession.prompt_async()
    │
    ▼
QueryAgent.__init__()
    │
    ├── _load_known_devices() ← 从 v_system 查询
    │       │
    │       ▼
    │   DataGateway.query_snapshots("SELECT DISTINCT device FROM v_system")
    │       │
    │       ▼
    │   连接 snapshots.duckdb ← v_system 不存在!
    │       │
    │       ▼
    │   CatalogException → 捕获异常 → 返回 set()
    │
    ▼
_process_aliases("list ip addresses on R2")
    │
    ├── 提取实体: ["R2"]
    │
    ├── R2 not in self._known_devices (空集)  ← 判断失败!
    │
    ▼
learn_callback("R2")  ← 触发学习提示
    │
    ▼
"🎓 Learning: I don't know 'R2'. Which devices do you mean?"
```

---

## 📋 测试缺陷清单

### 缺陷 1: 测试不验证数据库结构

**现状**:
```python
# test_acceptance.py::TestPhase4DatabaseStructure
def test_raw_outputs_table_exists(self):
    # ✅ 只检查 raw_outputs 表，不检查视图
    result = db.query("SELECT * FROM raw_outputs LIMIT 1")
```

**应该**:
```python
def test_required_views_exist(self):
    required_views = ['v_system', 'v_interfaces', 'v_routes', 'v_bgp']
    for view in required_views:
        result = db.query(f"SELECT * FROM {view} LIMIT 1")
        assert result is not None, f"视图 {view} 不存在"
```

### 缺陷 2: 测试绕过 QueryAgent

**现状**:
```python
# test_acceptance.py::TestPhase5QueryTools
def test_interface_status_query(self):
    # ✅ 使用 subprocess 调用，绕过 QueryAgent
    result = subprocess.run(["uv", "run", "olav", "query", "..."])
```

**应该**:
```python
def test_query_agent_device_recognition(self):
    agent = QueryAgent()
    assert len(agent._known_devices) > 0, "设备列表不能为空"
    assert "R1" in agent._known_devices
```

### 缺陷 3: TAB 补全从未测试

**现状**: 无相关测试

**应该**:
```python
def test_tab_completion_sanity(self):
    session = OlavPromptSession()
    completions = list(session.whitelist.keys())
    # 验证补全项是用户友好的命令，而非正则
    for c in completions:
        assert not re.search(r'[\.\*\+\?]', c), f"补全项包含正则: {c}"
```

---

## 🔧 修复优先级 (按阻塞程度)

### P0: 完全阻塞用户使用

| # | Issue | 根因 | 修复方案 | 工时 |
|---|-------|------|---------|------|
| 1 | 设备不识别 | v_system 视图不存在 | 修改 `_load_known_devices()` 查询 `olav.duckdb/raw_outputs` | 1h |
| 2 | 查询无响应 | 学习循环卡住 | 跳过已知设备模式 (R1-R9, SW1-SW9) | 30min |

### P1: 严重影响体验

| # | Issue | 根因 | 修复方案 | 工时 |
|---|-------|------|---------|------|
| 3 | TAB 补全乱码 | `WordCompleter(whitelist.keys())` 使用正则 | 移除 WordCompleter 或改用历史 | 30min |
| 4 | 目录扫描警告 | 未过滤 `_archive/`, `test/` | 添加目录过滤 | 30min |

### P2: 代码质量

| # | Issue | 根因 | 修复方案 | 工时 |
|---|-------|------|---------|------|
| 5 | 120 ruff 错误 | 代码未格式化 | `uv run ruff check --fix && ruff format` | 15min |
| 6 | 测试不验证真实场景 | 测试设计缺陷 | 添加集成测试 | 4h |

---

## ✅ 已验证正确的部分

| 组件 | 状态 | 验证方式 |
|------|------|---------|
| Orchestrator SubAgent 架构 | ✅ 正确 | 代码结构检查 |
| DeepAgents 集成 | ✅ 正确 | import 检查 |
| DuckDBSaver 持久化 | ✅ 正确 | 代码存在 |
| 版本号 0.9.8 | ✅ 统一 | `grep version pyproject.toml` |
| .env.example | ✅ 存在 | 文件检查 |
| orchestrator_old.py | ✅ 已删除 | 文件不存在 |
| raw_outputs 数据 | ✅ 存在 | `SELECT DISTINCT device FROM raw_outputs` |
| 设备数据 | ✅ 6台设备 | R1, R2, R3, R4, SW1, SW2 |

---

## 📈 建议行动

### 立即修复 (2小时内可完成)

1. **修复 `_load_known_devices()`** - 改为查询 `olav.duckdb`
   ```python
   # src/olav/agents/query_agent.py
   def _load_known_devices(self) -> set[str]:
       try:
           devices = self.gw.query_main("SELECT DISTINCT device FROM raw_outputs")
           return {str(d["device"]).upper() for d in devices}
       except Exception as e:
           logger.debug(f"No device data: {e}")
           return set()
   ```

2. **移除 TAB 补全的 WordCompleter** - 只保留 AutoSuggestFromHistory
   ```python
   # src/olav/cli/session.py
   # 删除: completer = WordCompleter(words=whitelist.keys(), ...)
   # 保留: auto_suggest = AutoSuggestFromHistory()
   ```

3. **运行 ruff format**
   ```bash
   uv run ruff check src/ --fix
   uv run ruff format src/
   ```

### 后续改进 (本周)

4. **更新 SKILL.md** - 移除不存在的视图声明
5. **添加真实 CLI 集成测试** - 测试 QueryAgent 设备加载
6. **同步所有文档** - 删除过时的进度声明

---

## 📝 结论

### 文档与代码脱节总结

| 文档类型 | 数量 | 状态 |
|---------|------|------|
| 已过时/错误 | 6 | 00, 01, 04, 05, 09_PHASE4, 09_coverage |
| 规划文档 (无需更新) | 2 | 06, 07 |
| 部分正确 | 3 | 02, 03, 13 |
| 规范文档 (未执行) | 1 | 08 |

### 核心教训

1. **E2E 测试必须模拟真实用户交互**，而非 subprocess 调用
2. **测试必须验证端到端数据流**，包括数据库结构
3. **功能测试应该在相同环境下运行**，而非隔离的测试数据库
4. **文档应该由代码生成或自动验证**，而非手动维护

### 真实可用性评估

| 维度 | 评分 | 说明 |
|------|------|------|
| 架构设计 | ⭐⭐⭐⭐ | SubAgent 架构正确，DeepAgents 集成良好 |
| 代码质量 | ⭐⭐⭐ | 120 ruff 错误，但核心逻辑完整 |
| 功能可用性 | ⭐ | CLI 无法使用，核心流程断裂 |
| 文档准确性 | ⭐⭐ | 大量过时信息，误导性进度报告 |
| 测试覆盖 | ⭐⭐ | 测试存在但不验证真实场景 |

**总体评分**: ⭐⭐ (2/5) - 架构良好但功能不可用

---

**审计人**: Copilot  
**审计日期**: 2026-02-04
