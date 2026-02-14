# OLAV Development Guide

**Version**: v2.0.0 (2026-02-14) - 🚨 **架构重构中**  
**Previous**: v1.0.0 (2026-02-08)

---

## 🚨 重要通知：v2.0 架构重构进行中

**状态**: 设计完成，实施准备中（2026-02-14）  
**分支**: `refactor/v2.0-deepagents`  
**预计完成**: 2026-02-28

### ⚠️ 开发者必读

#### 如果你在开发新功能

1. **暂缓添加新 SubAgent** - v2.0 将从 5 个 SubAgent 精简到 1 个 Agent
2. **工具放在 `.olav/tools/`** - 不是 `src/olav/tools/` 或 `.olav/shared/tools/`
3. **创建 Skills 而非 SubAgent** - 参考 DEEPAGENTS_SIMPLIFICATION_PLAN.md
4. **使用 DuckDB 统一数据层** - 新集成先导入 DuckDB，90% 无需新工具

#### 如果你在修复 Bug

1. **避免修改 orchestrator.py** - 该文件将被完全删除（1,077 行正则路由）
2. **直接修改工具代码** - `.olav/shared/tools/` 中的工具逻辑
3. **更新测试** - 确保 `tests/e2e/test_real_scenarios.py` 通过

#### 关键变更速查

| 组件 | v0.11 (当前) | v2.0 (目标) | 状态 |
|------|-------------|------------|------|
| **架构** | 5 SubAgents + 正则路由 | 1 Agent + Skills | 🟡 设计完成 |
| **路由** | orchestrator.py (1,077行) | 零路由（Agent直接调用tools） | ⏳ 待实施 |
| **工具位置** | `.olav/shared/tools/` | `.olav/tools/` | ⏳ 待迁移 |
| **工具数量** | 6 个工具 (1,376行) | 3 个工具 (620行, -55%) | ⏳ 待合并 |
| **Admin** | admin_agent.py | CLI命令 + olav-admin skill | ⏳ 待实施 |
| **Cron** | 175 YAML定时任务 | python-crontab tool | ✅ 已设计 |
| **数据库** | main.duckdb + network.duckdb | main.duckdb 统一 | ⏳ 待合并 |

---

## 📚 Documentation Hub

### 🆕 v2.0 重构文档（必读）

**开始这里** → [dev_docs/INDEX.md](../dev_docs/INDEX.md) - 文档导航和阅读顺序

**核心设计** → [dev_docs/DEEPAGENTS_SIMPLIFICATION_PLAN.md](../dev_docs/DEEPAGENTS_SIMPLIFICATION_PLAN.md) ⭐  
- 1 Agent + Skills 架构
- DuckDB 统一数据层
- 零路由设计理念
- 阅读时间：40-50 分钟

**进度追踪** → [dev_docs/REFACTOR_TRACKING.md](../dev_docs/REFACTOR_TRACKING.md) 📊  
- 当前阶段：Phase 0 准备中
- 70+ 详细任务清单
- 每日更新

**其他设计文档**:
- [OLAV_DIRECTORY_REFACTOR_ANALYSIS.md](../dev_docs/OLAV_DIRECTORY_REFACTOR_ANALYSIS.md) - 目录重构
- [ADMIN_AND_CRON_DESIGN_v2.md](../dev_docs/ADMIN_AND_CRON_DESIGN_v2.md) - Admin & Cron 设计
- [TOOLS_LOCATION_RATIONALE.md](../dev_docs/TOOLS_LOCATION_RATIONALE.md) - 工具位置理由

### 📖 v1.0 用户文档（参考）

**New Developer?** → Start with [QUICK_START_DEVELOPER.md](../docs/reference/QUICK_START_DEVELOPER.md) (5-minute onboarding)

**Complete Documentation** → See [DEVELOPER_INDEX.md](../docs/DEVELOPER_INDEX.md)

**Essential References**:
- 🏗️ [ARCHITECTURE.md](../docs/reference/ARCHITECTURE.md) - System architecture (⚠️ 即将过时)
- ⚙️ [CONFIGURATION_REFERENCE.md](../docs/reference/CONFIGURATION_REFERENCE.md) - All config files
- 🔧 [SUB_AGENT_DEVELOPMENT_GUIDE.md](../docs/reference/SUB_AGENT_DEVELOPMENT_GUIDE.md) - Agent implementation (⚠️ v2.0 改为 Skill)
- 📝 [SKILL_AUTHORING_GUIDE.md](../docs/reference/SKILL_AUTHORING_GUIDE.md) - Skill configuration
- 🧪 [TESTING_QUICK_REFERENCE.md](../docs/reference/TESTING_QUICK_REFERENCE.md) - Testing standards

---

## 🎯 Core Principles (v2.0 更新)

### 0. v2.0 架构核心理念（新增）

**零路由原则**:
- ❌ 不要创建任何形式的路由逻辑（正则、LLM判断、条件分支）
- ✅ Agent 直接访问 3 个 tools: database.py, network.py, inspection.py
- ✅ LLM 通过 tool docstring 自然选择合适工具

**Skills = 领域知识，不是路由**:
```python
# ❌ 错误：Skill 不应包含路由逻辑
if query_type == "device_count":
    use smart_sql_query
elif query_type == "cli_command":
    use nornir_execute

# ✅ 正确：Skill 提供操作指南
"""
Instructions for network-query skill:
1. Check database schema first (smart_sql_query)
2. If data insufficient, use nornir_execute for live collection
3. Combine results for comprehensive answer
"""
```

**DuckDB 优先策略**:
- 新数据源（NetBox、Zabbix）→ 先导入 DuckDB → 加 Skill
- 90% 场景无需新工具（schema-aware SQL 足够）
- 只有真正需要 live 交互才创建新工具

**Tool 在 `.olav/tools/`**:
```bash
# ✅ 正确位置
.olav/tools/
├── database.py      # SQL查询
├── network.py       # 设备操作
└── inspection.py    # 定时任务管理

# ❌ 错误位置（即将废弃）
.olav/shared/tools/  # 旧位置，待迁移
src/olav/tools/      # 框架代码，工具不在这
```

### 1. Skill-Centric Architecture
**Rule**: All configuration flows from SKILL.md files
- **Location**: `.olav/skills/*/SKILL.md`
- **Authority**: SKILL.md frontmatter is the single source of truth
- **Fallback Chain**: .env > .olav/settings.json > SKILL.md > settings.py

### 2. No Hardcoded Configuration
**Rule**: Zero hardcoded paths, thresholds, or commands
- Use `config.paths.*` for file paths
- Use `config.settings.*` for parameters
- Support environment overrides via `.env`
- Support user overrides via `.olav/settings.json`

### 3. Test-Driven Development (TDD)
**Rule**: Write tests first, then implement
- **Write failing test** → Define expected behavior
- **Implement feature** → Make test pass
- **Refactor** → Clean up while tests stay green
- **Benefits**: Clear requirements, regression prevention, better design

**Example TDD Flow**:
```python
# Step 1: Write failing test (Red)
async def test_export_devices_to_csv(self):
    """User Story: Export devices to CSV without CLI execution."""
    result = await orchestrate_query("export devices to csv")
    assert Path("exports/devices.csv").exists()  # ❌ Fails

# Step 2: Implement feature (Green)
# ... implement export logic ...

# Step 3: Test passes
assert Path("exports/devices.csv").exists()  # ✅ Passes

# Step 4: Refactor
# ... clean up code while test stays green ...
```

### 4. Keep It Simple, Stupid (KISS)
**Rule**: Simplest solution that works
- **Avoid over-engineering** - Don't build features you don't need
- **Prefer clarity over cleverness** - Code is read more than written
- **Delete over abstract** - Remove unused code immediately
- **One way to do things** - Consistency reduces cognitive load

**Examples**:
```python
# ❌ COMPLEX - Over-engineered factory pattern
class AgentFactoryBuilder:
    def with_cache(self): ...
    def with_persistence(self): ...
    def build(self): ...

# ✅ SIMPLE - Direct function call
agent = create_query_agent()
```

```python
# ❌ COMPLEX - Unnecessary abstraction
class ConfigurationManager:
    def get_nested_value(self, path: list): ...
    
config_mgr.get_nested_value(["database", "main", "path"])

# ✅ SIMPLE - Direct access
from config.paths import DB_MAIN_PATH
```

### 5. Use Native Tools & Existing Libraries
**Rule**: Don't reinvent the wheel
- **DeepAgents** - Use native SubAgent, TodoListMiddleware (not custom wrappers)
- **LangGraph** - Use DuckDBSaver, DuckDBStore (not custom persistence)
- **DuckDB** - Use native SQL, no ORMs
- **Standard Library** - Use pathlib, logging, asyncio (not third-party equivalents)

**Examples**:
```python
# ❌ CUSTOM - Reinventing persistence
class CustomCheckpointer:
    def save_state(self): ...

# ✅ NATIVE - Use LangGraph's DuckDBSaver
from langgraph.checkpoint.duckdb import DuckDBSaver
checkpointer = DuckDBSaver(conn=duck_conn)
```

```python
# ❌ CUSTOM - Building own caching
class CustomCache:
    def get_or_compute(self): ...

# ✅ NATIVE - Use existing semantic cache
from olav.core.query_cache import QueryCache
cache = QueryCache()
```

### 6. No Redundant Code
**Rule**: Delete unused code immediately
- Remove unused imports, commented code, dead branches
- Archive to Git history, not codebase
- Each code change must pass E2E tests

---

## 🚫 Anti-Patterns

### 0. DO NOT Create Routing Logic (v2.0 Critical)
```python
# ❌ FORBIDDEN - Any form of routing
if "设备" in query or "device" in query:
    return query_agent.invoke(query)
elif "命令" in query or "cli" in query:
    return cli_agent.invoke(query)

# ❌ FORBIDDEN - LLM-based routing
routing_prompt = "判断这个问题应该给哪个Agent..."
agent_choice = llm.invoke(routing_prompt)

# ❌ FORBIDDEN - Conditional tool selection in code
if needs_database:
    use smart_sql_query
else:
    use nornir_execute

# ✅ CORRECT - Agent directly has all tools, LLM chooses
agent = create_agent(tools=[database, network, inspection])
result = agent.invoke(query)  # LLM自然选择合适工具
```

### 0.1 DO NOT Create New SubAgents (v2.0 Critical)
```python
# ❌ FORBIDDEN - Creating new SubAgent
class NetBoxAgent(SubAgent):
    def invoke(self, query): ...

# ✅ CORRECT - Import to DuckDB + Add Skill
# 1. Import NetBox data to DuckDB
import_netbox_to_duckdb()

# 2. Create Skill (not SubAgent)
# .olav/skills/netbox/SKILL.md
"""
name: netbox
allowed-tools: smart_sql_query
Instructions: Query netbox_* tables for DCIM/IPAM data
"""
```

### 0.2 DO NOT Put Tools in src/ (v2.0 Critical)
```python
# ❌ FORBIDDEN - Framework directory for tools
src/olav/tools/
├── my_new_tool.py

# ✅ CORRECT - Business logic directory
.olav/tools/
├── database.py      # Schema-aware SQL
├── network.py       # Device operations
├── inspection.py    # Cron management
└── my_new_tool.py   # Your tool (if truly needed)
```

### 1. DO NOT Create Redundant Components
```python
# ❌ FORBIDDEN - Unnecessary abstractions
class QualityChecker: pass
class ResultMerger: pass
class PlanAgent: pass

# ✅ CORRECT - Unified in Orchestrator
# (see ARCHITECTURE.md)
```

### 2. DO NOT Use Hard Time Windows
```python
# ❌ FORBIDDEN - Arbitrary time limits
WHERE age_days <= 30

# ✅ CORRECT - Let LLM judge relevance
ORDER BY created_at DESC LIMIT 10
```

### 3. DO NOT Use Draft/Review Workflows
```python
# ❌ FORBIDDEN - Manual review process
.olav/drafts/ → Human Review → .olav/knowledge/

# ✅ CORRECT - Direct edit + Git rollback
.olav/knowledge/ → Git commit → Auto-vectorize
```

### 4. DO NOT Create Documentation Unless Requested
**Rule**: Focus on code quality, not docs
- **Exception**: Only `docs/99_audit.md` is maintained
- **Reason**: Reduces clutter, forces clear code

### 5. DO NOT Write Mock-Heavy Tests
```python
# ❌ FORBIDDEN - Tests component existence
def test_agent_exists():
    agent = create_query_agent()
    assert agent is not None  # Useless test

# ✅ CORRECT - Tests real user scenarios
async def test_export_devices_csv():
    result = await orchestrate_query("export devices to csv")
    assert Path("exports/devices.csv").exists()
    # Verify no CLI execution, correct data, etc.
```

---

## ✅ Real E2E Testing (New Standard)

**Location**: `tests/e2e/test_real_scenarios.py`

**Principles**:
1. **No mocks for business logic** - Test actual code paths
2. **Monitor side effects** - Track CLI, database, file I/O
3. **Test user scenarios** - Not component existence
4. **Validate data flow** - Check output correctness

**Example**:
```python
@pytest.mark.e2e
class TestRealUserScenarios:
    @pytest.mark.asyncio
    async def test_export_devices_version_no_cli_execution(self):
        """
        User Story: Export devices' version to CSV
        
        Acceptance Criteria:
        1. Query succeeds
        2. CSV created
        3. NO CLI executed (pure database query)
        4. Uses main.duckdb, not olav.duckdb
        """
        cli_tracker = CLICommandTracker()
        
        with cli_tracker:
            result = await orchestrate_query(
                "save all devices' version info to a csv file"
            )
            assert result is not None
        
        cli_tracker.assert_no_commands()  # Critical validation
        assert Path("exports/devices_version.csv").exists()
```

**Reference**: [TESTING_QUICK_REFERENCE.md](../docs/reference/TESTING_QUICK_REFERENCE.md)

---

## 🔧 Essential Commands

### v2.0 Development Workflow (New)
```bash
# 1. Check refactor progress
cat dev_docs/REFACTOR_TRACKING.md

# 2. Switch to refactor branch
git checkout refactor/v2.0-deepagents

# 3. Test new inspection tool
echo '{"action":"list"}' | python3 .olav/tools/inspection.py

# 4. Test admin CLI (after Phase 1)
olav admin status
olav admin inspect list

# 5. Commit frequently (Git is backup)
git add .
git commit -m "feat: implement database.py tool"
git push

# 6. Run E2E tests before PR
uv run pytest tests/e2e/test_real_scenarios.py -v
```

### Development
```bash
# Run real E2E tests (acceptance criteria)
uv run pytest tests/e2e/test_real_scenarios.py -v

# Run specific test
uv run pytest tests/e2e/test_real_scenarios.py::TestRealUserScenarios::test_export_devices_version_no_cli_execution -v

# Test query
uv run olav ask "your query"

# Debug mode
OLAV_LOG_LEVEL=DEBUG uv run olav ask "your query"
```

### Code Quality (Optional - Not Required for Acceptance)
```bash
# Format & lint
uv run ruff check src/ --fix
uv run ruff format src/

# Type checking
uv run pyright src/
```

### Configuration
```bash
# Setup
cp .env.example .env
nano .env  # Add LLM_API_KEY

# Check database
uv run python -c "import duckdb; print(duckdb.connect('.olav/db/main.duckdb').execute('SELECT COUNT(*) FROM devices').fetchone())"
```

---

## 📋 Quick Reference

### Critical Files (v2.0)
- **v2.0 设计**:
  - `dev_docs/INDEX.md` - 文档导航（必读）
  - `dev_docs/DEEPAGENTS_SIMPLIFICATION_PLAN.md` - 核心架构设计 ⭐
  - `dev_docs/REFACTOR_TRACKING.md` - 进度追踪 📊
  - `.olav/tools/inspection.py` - 定时任务管理工具
- **v1.0 参考**（即将过时）:
  - `.olav/OLAV.md` - SubAgent registry (→ 将废弃)
  - `src/olav/core/orchestrator.py` - 路由器 (→ 将删除)
  - `.olav/shared/tools/` - 工具目录 (→ 迁移到 .olav/tools/)
- **保持不变**:
  - `.olav/skills/*/SKILL.md` - Skill configurations
  - `config/paths.py` - Path constants (READ THIS)
  - `config/settings.py` - Settings schema (READ THIS)
  - `tests/e2e/test_real_scenarios.py` - Real E2E tests

### Configuration Priority
```
.env (highest)
  ↓
.olav/settings.json
  ↓
SKILL.md frontmatter
  ↓
config/settings.py (lowest)
```

### LLM API Configuration (Critical)
```bash
# Required in .env
LLM_API_KEY=sk-or-v1-xxx...
LLM_BASE_URL=https://openrouter.ai/api/v1  # For OpenRouter, Groq, etc.
LLM_MODEL_NAME=x-ai/grok-beta
```

**DeepAgents Compatibility**: Agents auto-set `OPENAI_API_KEY`, `OPENAI_BASE_URL` environment variables

---

## 🚀 v2.0 开发流程指南

### 准备工作（必须）

1. **阅读核心文档**（总计 60 分钟）
   ```bash
   # 第一优先级
   cat dev_docs/INDEX.md  # 5分钟 - 文档导航
   
   # 第二优先级
   cat dev_docs/DEEPAGENTS_SIMPLIFICATION_PLAN.md  # 40分钟 - 核心设计
   
   # 第三优先级
   cat dev_docs/REFACTOR_TRACKING.md  # 10分钟 - 进度追踪
   ```

2. **切换到重构分支**
   ```bash
   git fetch origin
   git checkout refactor/v2.0-deepagents
   git pull origin refactor/v2.0-deepagents
   ```

3. **安装依赖**
   ```bash
   uv sync  # 包含 python-crontab
   ```

### 开发原则（重要）

#### 1. 零路由原则
```python
# ❌ 不要写这样的代码
def route_query(query: str):
    if "设备" in query:
        return query_agent.invoke(query)
    elif "命令" in query:
        return cli_agent.invoke(query)

# ✅ 应该这样写
agent = create_agent(tools=[database, network, inspection])
result = agent.invoke(query)  # LLM自然选择工具
```

#### 2. DuckDB 优先策略
```python
# ❌ 不要立即创建新工具
class NetBoxTool:
    def query_devices(self): ...

# ✅ 先导入数据到 DuckDB
import_netbox_to_duckdb()  # 创建 netbox_* 表

# ✅ 然后创建 Skill（不是工具）
# .olav/skills/netbox/SKILL.md
"""
Instructions:
- Use smart_sql_query to query netbox_* tables
- Tables: netbox_sites, netbox_racks, netbox_devices
"""
```

#### 3. Skills 不是路由
```python
# ❌ Skill 不应包含条件逻辑
"""
If query about devices:
    use query_agent
elif query about CLI:
    use cli_agent
"""

# ✅ Skill 应提供操作指南
"""
Instructions for network-query:
1. First check database schema (tool: smart_sql_query)
2. If data insufficient, collect live (tool: nornir_execute)
3. Combine both sources for comprehensive answer
"""
```

### 工作流程

#### 开发新功能
```bash
# 1. 查看当前阶段
cat dev_docs/REFACTOR_TRACKING.md | grep "当前阶段"

# 2. 查看待认领任务
cat dev_docs/REFACTOR_TRACKING.md | grep "待认领" -A 5

# 3. 认领任务（在 REFACTOR_TRACKING.md 中更新）
# - [ ] 任务 → - [x] 任务
#   - **责任人**: 你的名字

# 4. TDD 开发
# 4.1 写测试
cat > tests/unit/test_my_feature.py << 'EOF'
def test_my_feature():
    assert my_feature() == expected_result  # ❌ 先失败
EOF

# 4.2 实现功能
# ... 编写代码 ...

# 4.3 测试通过
uv run pytest tests/unit/test_my_feature.py  # ✅ 通过

# 5. Git commit（替代手动备份）
git add .
git commit -m "feat: implement my_feature"
git push

# 6. 更新进度
# 在 REFACTOR_TRACKING.md 的"每日更新日志"中添加
```

#### 修复 Bug
```bash
# 1. 避免修改即将删除的文件
# ❌ 不要修改: src/olav/core/orchestrator.py (1,077行，将删除)
# ❌ 不要修改: src/olav/agents/*_agent.py (5个，将删除)

# ✅ 应该修改: .olav/shared/tools/*.py (工具逻辑)
# ✅ 应该修改: .olav/skills/*/SKILL.md (Skill 配置)

# 2. 写 E2E 测试验证修复
uv run pytest tests/e2e/test_real_scenarios.py -v

# 3. Git commit
git add .
git commit -m "fix: correct device count query"
git push
```

#### 添加新数据源（例如 NetBox）
```bash
# 1. 先导入数据到 DuckDB（90% 场景）
# .olav/scripts/import_netbox.py
import duckdb
conn = duckdb.connect('.olav/db/main.duckdb')
conn.execute("CREATE TABLE netbox_devices AS SELECT * FROM read_json('netbox_export.json')")

# 2. 创建 Skill（不是工具）
mkdir -p .olav/skills/netbox
cat > .olav/skills/netbox/SKILL.md << 'EOF'
name: netbox
allowed-tools: smart_sql_query
Instructions: |
  Query NetBox DCIM/IPAM data from netbox_* tables:
  - netbox_sites: Site information
  - netbox_racks: Rack allocation
  - netbox_devices: Device inventory
EOF

# 3. 测试
uv run olav ask "查询 NetBox 中的设备数量"

# 4. 只有真正需要 live API 调用才创建新工具
# 例如: 需要实时修改 NetBox 数据（10% 场景）
```

### 每日检查清单

- [ ] 查看 REFACTOR_TRACKING.md 更新
- [ ] Git commit 代码（不要手动备份）
- [ ] E2E 测试通过
- [ ] 更新任务状态（认领、完成）
- [ ] 上报阻塞项（如有）

### 代码审查标准

**合并到重构分支前**:
- ✅ 零路由逻辑（无 if/elif 判断 Agent）
- ✅ 工具在 `.olav/tools/`（不在 src/）
- ✅ E2E 测试通过
- ✅ Git commit message 规范
- ✅ 无死代码、无 TODO 注释

---

## 🎓 Learning Path

### v2.0 快速上手（推荐）

#### Day 1: 理解重构动机（1 小时）
1. Read [dev_docs/INDEX.md](../dev_docs/INDEX.md) - 文档导航
2. Read [dev_docs/CODE_AUDIT_2026_02_14.md](../dev_docs/CODE_AUDIT_2026_02_14.md) - 问题诊断
3. Review [dev_docs/REFACTOR_TRACKING.md](../dev_docs/REFACTOR_TRACKING.md) - 当前进度

#### Day 2: 掌握核心设计（2 小时）
1. **必读**: [dev_docs/DEEPAGENTS_SIMPLIFICATION_PLAN.md](../dev_docs/DEEPAGENTS_SIMPLIFICATION_PLAN.md)
   - 零路由原则
   - 1 Agent + Skills 架构
   - DuckDB 统一数据层
2. Explore `.olav/tools/inspection.py` - 理解 Tool 模式
3. Review `.olav/skills/*/SKILL.md` - 理解 Skill 配置

#### Day 3: 实践开发（2-3 小时）
1. Switch to `refactor/v2.0-deepagents` branch
2. 认领一个 Phase 1 小任务
3. TDD 开发 → Git commit → Push
4. Review PR 要求

#### Day 4-5: 贡献代码
1. 实施认领的任务
2. E2E 测试通过
3. 更新 REFACTOR_TRACKING.md
4. Pull Request

---

### v1.0 学习路径（仅供参考）

#### Day 1: Setup & First Query
1. Read [QUICK_START_DEVELOPER.md](../docs/reference/QUICK_START_DEVELOPER.md)
2. Clone, setup `.env`, run first query
3. Run E2E tests

### Day 2: Understand Architecture
1. Read [ARCHITECTURE.md](../docs/reference/ARCHITECTURE.md)
2. Understand component hierarchy, data flow, caching
3. Explore `.olav/` directory structure

### Day 3: Configuration Mastery
1. Read [CONFIGURATION_REFERENCE.md](../docs/reference/CONFIGURATION_REFERENCE.md)
2. Understand SKILL.md, settings.py, paths.py
3. Practice modifying configurations

### Day 4: Build Your First Agent
1. Read [SUB_AGENT_DEVELOPMENT_GUIDE.md](../docs/reference/SUB_AGENT_DEVELOPMENT_GUIDE.md)
2. Create simple SubAgent with ReAct pattern
3. Test with real E2E test

### Day 5: Write Skills
1. Read [SKILL_AUTHORING_GUIDE.md](../docs/reference/SKILL_AUTHORING_GUIDE.md)
2. Create SKILL.md for your agent
3. Register tools, configure prompts

---

**Version**: v1.0.0 (2026-02-08)  
**Documentation**: Complete reference library in `docs/reference/`  
**Principles**: TDD, KISS, Native Tools, No Redundancy
---

## 🔧 Known Issues & Troubleshooting (v0.11.1)

### Issue: DeepAgents async/await timeout with OpenRouter API

**Problem**: 
- Agent.ainvoke() hangs indefinitely when using OpenRouter (or other OpenAI-compatible APIs)
- Symptom: Query starts with spinner but never completes, times out after 30+ seconds
- Root Cause: DeepAgents library has compatibility issues with non-standard OpenAI endpoints in async context

**Configuration Context**:
```bash
# .env setup with OpenRouter
LLM_PROVIDER=openai
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL_NAME=x-ai/grok-4.1-fast  # or any other OpenRouter model
```

**Why This Happens**:
1. LangChain's ChatOpenAI class is initialized correctly with custom base_url
2. Synchronous calls (model.invoke()) work fine  
3. DeepAgents' async middleware doesn't properly handle async initialization for custom endpoints
4. Result: ainvoke() call enters deadlock during async tool/middleware execution

**Solutions** (in priority order):

#### Solution 1: Use Synchronous Wrapper (⭐ IMPLEMENTED IN v0.11.1 - DEFAULT)
```python
# In src/olav/agents/orchestrator.py
def orchestrate_query_sync(
    user_query: str,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Synchronous fallback orchestrator - bypasses DeepAgents async deadlock.
    
    Features:
    - Direct LLM + Database Query approach
    - No DeepAgents middleware complexity
    - ~3-5 second execution time
    - Fully functional for Level 1/2 queries
    """
    # Execution flow:
    # 1. Creates LLM via LLMFactory (supports all providers)
    # 2. Queries database schema
    # 3. Sends query + context to LLM
    # 4. Parses LLM response for SQL
    # 5. Executes query and returns results
```

**Status**: ✅ **ACTIVE - This is the current implementation**
- CLI uses this directly
- Async version delegates to this via executor
- Works with ALL providers (OpenAI, OpenRouter, Grok, Ollama, etc.)

#### Solution 2: Use Ollama Locally (RECOMMENDED FOR DEV)
```bash
# .env - use local Ollama instead of remote API
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434
LLM_MODEL_NAME=mistral:latest
```

Advantages:
- No API costs
- No rate limits
- Full autonomy
- No internet required

#### Solution 3: File DeepAgents Issue (LONG-TERM FIX)
Report to: https://github.com/geekan/deepagents/issues
- Title: "ainvoke() hangs with custom OpenAI base_url (OpenRouter, etc.)"
- Key evidence: sync invoke() works, async ainvoke() deadlocks

#### Solution 4: Replace with Raw LangGraph
- Remove DeepAgents SubAgent middleware
- Implement routing directly in LangGraph
- Avoids async compatibility issues

**Verification**:
```bash
uv run olav query "有多少个设备?"
# Should complete in 3-10 seconds
# Output: Query Result: [{ "count_star()": 6 }]
```

---

## 🌐 Multi-Provider LLM Support

**Current Implementation** (v0.11.1):
The fallback orchestrator (`orchestrate_query_sync`) uses `LLMFactory.get_chat_model()` which supports:

### Supported Providers

| Provider | LLM_PROVIDER | LLM_BASE_URL | Status | Notes |
|----------|-------------|-------------|--------|-------|
| **OpenAI** | `openai` | Default | ✅ Tested | Standard OpenAI API |
| **OpenRouter** | `openai` | `https://openrouter.ai/api/v1` | ✅ Tested | Grok, Claude, Llama, etc. |
| **Together AI** | `openai` | `https://api.together.xyz/v1` | ✅ Compatible | Custom OpenAI endpoint |
| **Groq** | `openai` | `https://api.groq.com/openai/v1` | ✅ Compatible | Ultra-fast inference |
| **xAI Grok** | `xai` or `openai` | `https://openrouter.ai/api/v1` | ✅ Tested | Via OpenRouter |
| **Azure OpenAI** | `azure` | Azure endpoint | ✅ Compatible | Enterprise Azure |
| **Ollama (Local)** | `ollama` | `http://localhost:11434` | ✅ Tested | Zero-cost local |
| **Anthropic Claude** | `anthropic` | Default | ✅ Compatible | Claude family models |

### Configuration Examples

**OpenRouter (Any Model)**:
```bash
LLM_PROVIDER=openai
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-v1-xxx...
LLM_MODEL_NAME=meta-llama/llama-3.1-405b-instruct  # Any OpenRouter model
```

**Together AI**:
```bash
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.together.xyz/v1
LLM_API_KEY=xxx...
LLM_MODEL_NAME=meta-llama/Llama-3.1-405B-Instruct-Turbo
```

**Groq (Very Fast)**:
```bash
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=gsk_xxx...
LLM_MODEL_NAME=mixtral-8x7b-32768  # or llama-3.1-70b
```

**Local Ollama**:
```bash
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434
LLM_MODEL_NAME=mistral:latest  # Pull via: ollama pull mistral
```

**Anthropic Claude**:
```bash
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-xxx...
LLM_MODEL_NAME=claude-opus-4-1-20250805
```

### Provider Selection Strategy

**For Production** (Recommended):
1. OpenRouter (best cost/performance balance)
2. Groq (fastest inference)
3. Together AI (good models, low cost)

**For Development** (Recommended):
- Ollama + Mistral (local, free)
- Or: Groq (free tier available)

**Why Non-Standard API Support Works**:
The fallback orchestrator doesn't depend on DeepAgents' SubAgentMiddleware (which hangs), so:
- ✅ Works with ANY OpenAI-compatible endpoint
- ✅ Works with provider-specific SDKs (Anthropic, Ollama)
- ✅ No async/await complexity
- ✅ Direct sync LLM.invoke() calls

**Testing Different Providers**:
```bash
# Test 1: OpenRouter
export LLM_PROVIDER=openai
export LLM_BASE_URL=https://openrouter.ai/api/v1
export LLM_MODEL_NAME=meta-llama/llama-3.1-405b-instruct
uv run olav query "有多少个设备?"

# Test 2: Groq (very fast)
export LLM_PROVIDER=openai
export LLM_BASE_URL=https://api.groq.com/openai/v1
export LLM_MODEL_NAME=mixtral-8x7b-32768
uv run olav query "有多少个设备?"

# Test 3: Local Ollama (no cost)
export LLM_PROVIDER=ollama
export LLM_BASE_URL=http://localhost:11434
export LLM_MODEL_NAME=mistral:latest
uv run olav query "有多少个设备?"
```

---

**Version**: v2.0.0 (2026-02-14) - 架构重构中  
**Previous**: v1.0.0 (2026-02-08)  
**Documentation**: Complete reference library in `docs/reference/` + `dev_docs/`  
**Principles**: TDD, KISS, Native Tools, No Redundancy, Zero Routing

---

**Last Updated**: 2026-02-14  
**Status**: ✅ Design complete, implementation in progress  
**Next Milestone**: Phase 0 (Safety & Cleanup) - 2026-02-15

