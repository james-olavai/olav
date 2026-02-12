# Architecture Cleanup Plan - 2026-02-05

## 发现的核心架构问题

### 1. ❌ Orchestrator没有使用Skill-Based工具发现

**现状**:
```python
# src/olav/agents/orchestrator.py (Line 42-60)
from olav.tools.react_query import (
    query_database,    # 硬编码导入
    inspect_schema,    
    discover_data,     
)
database_tools = [query_database, inspect_schema, discover_data]  # 手动列表
```

**问题**:
- SKILL.md中声明了工具：`query_database`, `inspect_schema`, `smart_query`, `get_cached_sql`
- Orchestrator**硬编码导入**工具，没有使用SkillAdapter
- 违反了v0.9.8设计原则："All configuration flows from SKILL.md"

**应该是**:
```python
from olav.core.skill_adapter import SkillAdapter

skill = skill_loader.get_skill("network-query")
database_tools = SkillAdapter.load_tools_from_skill(skill)
```

**影响**: 
- SKILL.md修改不会生效
- 无法动态添加/移除工具
- 违反skill-centric架构

---

### 2. ❌ 数据库路径大量硬编码

**硬编码位置** (36处):
- `src/olav/lib/data_gateway.py` - `.olav/db/main.duckdb`
- `src/olav/tools/react_query.py` - 文档字符串中
- `src/olav/agents/orchestrator.py` - system_prompt中
- `tests/e2e/test_units.py` - 测试代码中

**config/paths.py缺失**:
```python
# 不存在！
MAIN_DB_PATH = DB_DIR / "main.duckdb"
```

**应该是**:
```python
# config/paths.py
MAIN_DB_PATH = DB_DIR / "main.duckdb"

# src/olav/lib/data_gateway.py
from config.paths import MAIN_DB_PATH
db_path = str(MAIN_DB_PATH)
```

---

### 3. ❌ Orchestrator路由逻辑不清晰

**System Prompt问题**:
```python
Routing Strategy:
- Simple queries (list/show/get) → query SubAgent (Fast Path, <1s)
- Health/diagnostics/analysis → analysis SubAgent  # ⚠️ "analysis"模糊
```

**"save devices' version"被误路由原因**:
- LLM可能认为"version"需要"analysis"
- 没有明确"export/save"类查询的路由规则
- 路由依赖LLM推理，不可靠

**应该是**:
```python
Routing Strategy (EXPLICIT):
- Device list/inventory queries → query SubAgent
  Examples: "list devices", "show version", "save device info to csv"
- Export/save queries → query SubAgent + format_and_export
  Keywords: save, export, list all, get all
- Real-time diagnostics → analysis SubAgent
  Examples: "check BGP health", "diagnose OSPF down"
- Command execution → cli SubAgent
- Complex troubleshooting → expert SubAgent
```

---

### 4. ❌ IntentAgent有大量死代码

**未使用的代码**:
- `_execute_plan()` - MVP stub从未完成
- `_supplement_results()` - 结果补充逻辑未实现
- `_render_markdown()` - Markdown渲染未使用

**当前流程**:
```
IntentAgent.process_query() 
  → _check_intent_cache() (总是miss)
  → _orchestrate_query() (直接调用orchestrator)
  → 返回结果
```

**简化后**:
```python
async def process_query(self, query: str) -> str:
    # 简化：直接调用orchestrator（缓存由orchestrator内部处理）
    from olav.agents.orchestrator import orchestrate_query
    return await orchestrate_query(query)
```

**或者完全移除IntentAgent**（QueryAgent已经有缓存机制）

---

### 5. ❌ Analyzer不应该在query SubAgent中使用

**问题**:
- "save devices' version" → query SubAgent → 但system prompt说analysis也可以处理
- Analyzer设计用于**诊断**，不是数据导出
- Analyzer的CLI执行增加了不必要的复杂性

**应该是**:
- query SubAgent: 数据检索 + 导出（纯SQL + 文件写入）
- analysis SubAgent: 健康诊断 + 异常检测（需要CLI验证时才用）
- 明确分离职责

---

## 修复优先级

### Priority 1: 立即修复（影响核心功能）

1. **添加MAIN_DB_PATH到config/paths.py**
   ```python
   MAIN_DB_PATH = DB_DIR / "main.duckdb"
   ```

2. **修复Orchestrator路由system_prompt**
   - 明确"export/save"查询路由规则
   - 移除模糊的"analysis"描述

3. **简化IntentAgent或移除**
   - 如果仅作为orchestrator的wrapper，直接调用orchestrator
   - 或完全移除，让QueryAgent直接调用orchestrator

### Priority 2: 架构改进（提升可维护性）

4. **Orchestrator使用SkillAdapter加载工具**
   ```python
   from olav.core.skill_adapter import SkillAdapter
   from olav.core.skill_loader import get_skill_loader
   
   skill_loader = get_skill_loader()
   query_skill = skill_loader.get_skill("network-query")
   database_tools = SkillAdapter.load_tools_from_skill(query_skill)
   ```

5. **替换所有硬编码数据库路径**
   - 使用`from config.paths import MAIN_DB_PATH`
   - 清理docstring中的硬编码示例

### Priority 3: 死代码清理

6. **清理IntentAgent未使用代码**
   - 删除`_execute_plan()` stub
   - 删除`_supplement_results()` 
   - 删除`_render_markdown()`

7. **清理Analyzer不必要的CLI逻辑**
   - 已部分修复（跳过database-only queries）
   - 进一步简化：移除CLI作为默认路径

---

## 设计原则验证

### v0.9.8 Design Principles (from copilot-instructions.md)

1. ✅ **Skill-Centric Architecture** 
   - ❌ 违反：Orchestrator硬编码工具列表
   - 修复：使用SkillAdapter

2. ✅ **No Hardcoded Configuration**
   - ❌ 违反：36处硬编码`.olav/db/main.duckdb`
   - 修复：使用config.paths.MAIN_DB_PATH

3. ✅ **Configuration Priority**: .env > .olav/settings.json > SKILL.md > settings.py
   - ❌ 违反：数据库路径没有配置化
   - 修复：添加到paths.py并支持环境变量

---

## 建议的正确流程

### "save all devices' version info to csv"

**期望流程**:
```
User Query
  ↓
QueryAgent (with IntentAgent fallback)
  ↓
Orchestrator
  ↓
Route to: query SubAgent (simple list query)
  ↓
query SubAgent: query_database("SELECT hostname, ios_version FROM devices")
  ↓
Orchestrator: format_and_export(data, format="csv")
  ↓
Return: "✅ Saved to exports/devices_version.csv"
```

**当前流程** (buggy):
```
User Query
  ↓
QueryAgent → IntentAgent (cache miss)
  ↓
IntentAgent._orchestrate_query() (刚修复，之前是fake)
  ↓
orchestrate_query()
  ↓
LLM routing: "version" → 可能误路由到 analysis SubAgent ❌
  ↓
Analyzer: db_query + cli_verify
  ↓
cli_verify: 执行 "show version" ❌ (已修复skip logic)
  ↓
错误：database lock, 执行不必要的CLI命令
```

---

## 立即行动项

1. ✅ **已完成**: IntentAgent调用真正orchestrator
2. ✅ **已完成**: Analyzer跳过database-only queries的CLI执行
3. 🔄 **进行中**: 添加MAIN_DB_PATH到config/paths.py
4. 🔄 **进行中**: 优化Orchestrator routing system_prompt
5. ⏳ **待办**: Orchestrator使用SkillAdapter加载工具
6. ⏳ **待办**: 清理IntentAgent死代码
7. ⏳ **待办**: 替换所有硬编码数据库路径

---

## 测试验证

完成修复后，应该通过以下测试：

1. **单元测试**: 29/29 PASSED (已通过)
2. **手动测试**: 
   ```bash
   uv run olav query "save all devices' version info to csv"
   ```
   - ✅ 查询devices表
   - ✅ 无CLI命令执行
   - ✅ 生成CSV文件
   - ✅ 无数据库锁错误

3. **路由验证**:
   ```bash
   # 应该路由到query SubAgent
   uv run olav query "list all devices"
   
   # 应该路由到analysis SubAgent
   uv run olav query "diagnose BGP peering issues"
   ```

---

## 结论

主要问题根源：
1. **架构偏离设计原则** - Orchestrator没有遵循skill-centric设计
2. **配置硬编码泛滥** - 违反"no hardcoded config"原则
3. **路由逻辑不清晰** - 依赖LLM推理而非明确规则
4. **代码未清理** - IntentAgent有大量死代码

修复策略：
- Priority 1: 立即修复影响功能的bug（已完成2/3）
- Priority 2: 重构架构违反问题（使用SkillAdapter）
- Priority 3: 清理死代码和技术债务

**当前状态**: 核心功能bug已修复，但架构需要重构以符合v0.9.8设计原则。
