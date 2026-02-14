# OLAV Development Guide

**Version**: v2.0.0 (2026-02-14) - 架构重构中  
**Status**: 设计完成，实施准备中

---

## 🚨 当前状态

**重构分支**: `refactor/v2.0-deepagents`  
**核心变更**: 5 SubAgents → 1 Agent + Skills  
**预计完成**: 2026-02-28

**关键文档**:
- 📖 [dev_docs/INDEX.md](../dev_docs/INDEX.md) - 文档导航（必读）
- ⭐ [dev_docs/DEEPAGENTS_SIMPLIFICATION_PLAN.md](../dev_docs/DEEPAGENTS_SIMPLIFICATION_PLAN.md) - 核心架构设计
- 📊 [dev_docs/REFACTOR_TRACKING.md](../dev_docs/REFACTOR_TRACKING.md) - 进度追踪

---

## 🎯 核心开发原则

### 1. Skill 与 Agent 解耦

**规则**: 业务逻辑与框架代码严格分离

```bash
# ✅ 正确位置
.olav/
├── skills/           # Skill 配置和领域知识
│   └── network-query/SKILL.md
├── tools/            # 业务工具（可执行脚本）
│   ├── database.py
│   ├── network.py
│   └── inspection.py
└── workflows/        # 工作流定义

src/olav/
├── agents/           # Agent 框架代码
│   └── agent.py      # 1 个统一 Agent
├── core/             # 核心逻辑
└── cli/              # CLI 接口

# ❌ 错误做法
src/olav/tools/       # 不要在框架代码中放工具
.olav/agents/         # 不要在 .olav 中放 Agent 实现
```

**为什么？**
- `.olav/` 是用户数据目录，可跨平台迁移（复制即可）
- `src/` 是框架代码，需要 uv/pip 安装
- MCP 标准兼容

---

### 2. KISS 原则 - Keep It Simple, Stupid

**规则**: 最简单能工作的方案就是最好的

```python
# ❌ 过度设计 - 5 个 SubAgent + 正则路由
if "设备" in query:
    return query_agent.invoke(query)
elif "命令" in query:
    return cli_agent.invoke(query)
# ... 1,077 行路由代码

# ✅ 简单 - 1 个 Agent，LLM 自然选择工具
agent = create_agent(tools=[database, network, inspection])
result = agent.invoke(query)  # LLM 看工具 docstring 自己选
```

```python
# ❌ 过度抽象
class ConfigurationManager:
    def get_nested_value(self, path: list): ...

# ✅ 直接访问
from config.paths import DB_MAIN_PATH
```

**经验**:
- 单领域（网络）不需要多 SubAgent
- 工具少于 10 个，不需要复杂路由
- 90% 新集成只需导入 DuckDB + 加 Skill，无需新工具

---

### 3. 使用成熟库，不要造轮子

**规则**: 优先使用 DeepAgents、LangChain、标准库

```python
# ❌ 自己造轮子
class CustomCheckpointer:
    def save_state(self): ...

# ✅ 使用 LangGraph 原生组件
from langgraph.checkpoint.duckdb import DuckDBSaver
checkpointer = DuckDBSaver(conn=duck_conn)
```

```python
# ❌ 自己实现缓存
class CustomCache:
    def get_or_compute(self): ...

# ✅ 使用现有语义缓存
from langchain_community.cache import SQLiteCache
```

```python
# ❌ 自己管理定时任务
class TaskScheduler: ...

# ✅ 使用 python-crontab
from crontab import CronTab
cron = CronTab(user=True)
```

**必须使用的库**:
- **DeepAgents**: create_deep_agent(), TodoListMiddleware, Skills
- **LangGraph**: DuckDBSaver, Checkpointer
- **LangChain**: ChatOpenAI, Tool decorators
- **python-crontab**: Cron 管理
- **标准库**: pathlib, logging, asyncio

---

### 4. 使用 LLM 能力，不要写复杂逻辑

**规则**: 让 LLM 做判断，不要写正则/条件判断

```python
# ❌ 复杂正则路由（orchestrator.py 的错误）
if re.match(r'.*设备.*数量.*', query):
    return query_agent.invoke(query)
elif re.match(r'.*执行.*命令.*', query):
    return cli_agent.invoke(query)

# ✅ LLM 自然判断
# Agent 看到 3 个 tools 的 docstring 自己选择
# database.py: "Execute SQL query on DuckDB"
# network.py: "Execute CLI on network devices"
# inspection.py: "Manage inspection schedules"
```

```python
# ❌ 硬编码时间窗口
WHERE age_days <= 30  # 为什么是 30 天？

# ✅ 让 LLM 判断相关性
ORDER BY created_at DESC LIMIT 10
# LLM 会基于内容判断是否相关
```

**原则**:
- 路由 → LLM 基于 tool docstring 选择
- 时间过滤 → LLM 基于语义相关性判断
- 数据不足 → LLM 看 Skill Instructions 决定是否 fallback

---

### 5. 配置分离 - 无硬编码

**规则**: 敏感数据 .env，配置 settings，Prompt 在 Skill

```bash
# .env - 敏感数据（不入 Git）
LLM_API_KEY=sk-xxx
NETWORK_USERNAME=admin
NETWORK_PASSWORD=secret

# .olav/settings.json - 用户配置
{
  "llm": {"model_name": "grok-beta", "temperature": 0.1},
  "network": {"timeout": 60}
}

# .olav/skills/network-query/SKILL.md - Prompt
Instructions: |
  When querying device data:
  1. First check schema with smart_sql_query
  2. If data insufficient, use nornir_execute
  3. Combine results
```

```python
# ❌ 硬编码
db_path = "/home/user/.olav/db/main.duckdb"  # 不同用户路径不同
threshold = 80  # 为什么是 80？

# ✅ 使用配置
from config.paths import DB_MAIN_PATH
from config.settings import get_settings
settings = get_settings()
threshold = settings.alerts.cpu_threshold
```

**配置优先级**（高到低）:
1. 环境变量 `OLAV_*`
2. `.olav/settings.json`
3. `SKILL.md` frontmatter
4. `config/settings.py` 默认值

---

### 6. 不留垃圾代码 - 彻底清理

**规则**: 发现死代码立即删除，不要标记"废弃"

```python
# ❌ 标记废弃但不删除
# @deprecated  # 将在 v2.0 删除
class OldQueryOptimizer: pass

# ❌ 注释掉的代码
# def old_method():
#     ...

# ✅ 直接删除，Git 历史可找回
rm src/olav/core/query_optimizer.py
git commit -m "refactor: remove unused QueryOptimizer"
```

**审计发现的垃圾代码**:
- `query_optimizer.py` (369 行) - Never used
- `database_enhancer.py` (184 行) - Never used  
- `quality_checker.py` (90 行) - Custom, redundant
- `result_merger.py` (73 行) - Custom, redundant
- `orchestrator.py` (1,077 行) - 正则路由，v2.0 删除
- 175 个 YAML 定时任务 (920KB) - 改用 python-crontab

**清理原则**:
- 遇到死代码 → 立即删除，不要"留着以防万一"
- Git 历史是备份，不要在代码里备份
- 注释掉的代码 → 删除
- TODO 注释 → 要么现在做，要么删掉

---

### 7. TDD 开发 - 测试驱动，不绕过

**规则**: 先写测试，测试失败才说明发现问题

```python
# 标准 TDD 流程
# 1. Red - 写失败的测试
def test_export_devices_csv():
    result = orchestrate_query("export devices to csv")
    assert Path("exports/devices.csv").exists()  # ❌ 失败

# 2. Green - 实现功能使测试通过
def export_devices_csv(query):
    # ... 实现 ...
    pass

# 3. Refactor - 重构代码保持测试通过
```

**❌ 禁止的作弊方式**:

```python
# ❌ 绕过系统架构
if "export" in query:
    # 直接写 CSV，不走 Agent
    return export_csv_directly()

# ❌ Fallback 掩盖问题
try:
    result = proper_way()
except:
    result = hacky_fallback()  # 问题还在，只是被掩盖了

# ❌ Mock 掉业务逻辑
@patch('olav.core.database')  # Mock 太多，测不到真实场景
def test_query():
    pass
```

**✅ 正确做法**:

```python
# ✅ E2E 测试真实场景
@pytest.mark.e2e
async def test_export_devices_csv_no_cli_execution():
    """验收标准: 
    1. CSV 生成成功
    2. 无 CLI 执行（纯数据库查询）
    3. 数据正确
    """
    cli_tracker = CLICommandTracker()
    
    with cli_tracker:
        result = await orchestrate_query("export devices to csv")
    
    cli_tracker.assert_no_commands()  # 确保无作弊
    assert Path("exports/devices.csv").exists()
    # 验证数据正确性...
```

**测试原则**:
- E2E 测试 > 单元测试（测真实场景）
- 少用 Mock（测实际代码路径）
- 测试失败 → 修代码，不要改测试
- Fallback 要有明确理由（数据不足），不是掩盖 bug

---

## 🚫 代码审计发现的问题（必须避免）

### 1. 架构问题

❌ **绕过 DeepAgents** - orchestrator.py 用 1,077 行正则路由替代 Agent  
✅ **正确**: 1 Agent + Skills，LLM 选工具

❌ **过度设计** - 5 SubAgents 在单领域（网络）只用 3 个工具  
✅ **正确**: 单 Agent 足够，工具 < 10 个无需多 Agent

❌ **自定义组件** - QualityChecker, ResultMerger 等自己造轮子  
✅ **正确**: 用 DeepAgents 原生 TodoListMiddleware

### 2. 数据库问题

❌ **SQL 注入** - `f"SELECT * FROM devices WHERE ip='{user_input}'"`  
✅ **正确**: 参数化查询 `execute("SELECT * FROM devices WHERE ip=?", [user_input])`

❌ **数据库分散** - main.duckdb + network.duckdb  
✅ **正确**: 统一 main.duckdb，schema 区分业务

### 3. 配置问题

❌ **硬编码路径** - `"/home/user/.olav/db/main.duckdb"`  
✅ **正确**: `config.paths.DB_MAIN_PATH`

❌ **硬编码阈值** - `if cpu > 80:`  
✅ **正确**: `if cpu > settings.alerts.cpu_threshold:`

❌ **Prompt 散落** - prompts 在 Python 代码中  
✅ **正确**: 所有 Prompt 在 `SKILL.md`

### 4. 代码质量问题

❌ **死代码** - 369 行从未被调用  
✅ **正确**: 立即删除

❌ **注释代码** - 大量 `# old_function()`  
✅ **正确**: 删除，Git 可找回

❌ **TODO 注释** - `# TODO: fix this later`  
✅ **正确**: 要么现在修，要么删掉

### 5. 测试问题

❌ **Mock-Heavy** - Mock 整个数据库层  
✅ **正确**: E2E 测试真实数据库

❌ **测试组件存在** - `assert agent is not None`  
✅ **正确**: 测试用户场景 `assert CSV 正确`

---

## 🔧 开发命令速查

```bash
# 查看进度
cat dev_docs/REFACTOR_TRACKING.md

# 切换重构分支
git checkout refactor/v2.0-deepagents

# TDD 开发
# 1. 写测试
cat > tests/e2e/test_my_feature.py << 'EOF'
def test_my_feature():
    assert my_feature() == expected  # 先失败
EOF

# 2. 运行测试（失败）
uv run pytest tests/e2e/test_my_feature.py -v  # ❌

# 3. 实现功能
# ... 写代码 ...

# 4. 运行测试（通过）
uv run pytest tests/e2e/test_my_feature.py -v  # ✅

# 5. Git commit（替代手动备份）
git add .
git commit -m "feat: implement my_feature"
git push

# 运行所有 E2E 测试
uv run pytest tests/e2e/test_real_scenarios.py -v

# 测试 query
uv run olav ask "有多少个设备？"
```

---

## 📋 开发检查清单

**每次提交前**:
- [ ] E2E 测试全部通过
- [ ] 无死代码（删除，不要注释）
- [ ] 无硬编码（配置在 .env/settings/SKILL.md）
- [ ] 无自己造轮子（用成熟库）
- [ ] 无绕过架构的 hack
- [ ] Git commit message 清晰

**代码审查标准**:
- [ ] 遵循 7 大原则
- [ ] 修复审计发现的问题类型
- [ ] TDD 开发（测试先行）
- [ ] 避免重复审计中的错误

---

## 🎓 新人快速上手

1. **理解重构动机**（30 分钟）
   - 阅读 [CODE_AUDIT_2026_02_14.md](../dev_docs/CODE_AUDIT_2026_02_14.md)
   - 了解现有问题

2. **掌握目标架构**（1 小时）
   - 阅读 [DEEPAGENTS_SIMPLIFICATION_PLAN.md](../dev_docs/DEEPAGENTS_SIMPLIFICATION_PLAN.md)
   - 理解 1 Agent + Skills 设计

3. **开始贡献**
   - 查看 [REFACTOR_TRACKING.md](../dev_docs/REFACTOR_TRACKING.md) 认领任务
   - TDD 开发 → Git commit → PR

---

**Version**: v2.0.0 (2026-02-14)  
**Principles**: KISS, 用成熟库, LLM能力, 配置分离, 无垃圾代码, TDD, 架构不妥协  
**Last Updated**: 2026-02-14