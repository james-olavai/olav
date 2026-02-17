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

### 3. 动态加载 - 配置驱动，严禁硬编码

**规则**: 所有 Tools、Skills、Prompts 必须从 `.olav/` 动态加载，严禁硬编码

**架构原则**:
```python
# ✅ Tools 动态加载（从 .olav/tools/）
def _load_tools(self) -> list:
    """Dynamically load tools from .olav/tools/."""
    tools = []
    tools_path = Path(".olav/tools")
    
    # Import tools dynamically using importlib
    spec = importlib.util.spec_from_file_location("database", tools_path / "database.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    if hasattr(module, "execute_sql"):
        tools.append(module.execute_sql)
    
    return tools

# ✅ Skills 动态加载（从 .olav/skills/）
def _load_skills(self) -> dict:
    """Dynamically load skills from .olav/skills/."""
    skills = {}
    skills_path = Path(".olav/skills")
    
    for skill_dir in skills_path.iterdir():
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            with open(skill_file) as f:
                post = frontmatter.load(f)  # Parse YAML + content
                skills[skill_dir.name] = post.metadata
    
    return skills

# ✅ Prompts 动态加载（从 .olav/skills/*/prompts/system.md）
def _get_system_prompt() -> str:
    """Load system prompt from skill configuration."""
    skill_path = Path(".olav/skills/command_learner")
    system_prompt_path = skill_path / "prompts" / "system.md"
    
    if system_prompt_path.exists():
        prompt = system_prompt_path.read_text(encoding="utf-8")
        # 可以动态注入变量
        prompt = prompt.replace("{ntc_path}", find_ntc_templates_path())
        return prompt
    
    # Fallback 必须简洁（< 30 行）
    return """Minimal fallback prompt..."""

# ❌ 硬编码 Tools（禁止）
def execute_sql_hardcoded(query: str):
    """This tool should be in .olav/tools/database.py, not in agent code!"""
    pass

# ❌ 硬编码 Prompts（禁止）
system_prompt = """You are OLAV...
[148 lines of hardcoded prompt]
"""  # 应该在 .olav/skills/*/prompts/system.md

# ❌ 硬编码 Skill 配置（禁止）
skill_config = {
    "name": "network-query",
    "description": "...",
    "tools": ["execute_sql"]
}  # 应该在 .olav/skills/network-query/SKILL.md
```

**为什么？**
- **可维护性**: 修改 prompt 只需编辑 markdown 文件，无需改 Python 代码
- **可复制性**: `.olav/` 目录可以复制到其他环境直接使用
- **版本控制**: Prompts 和代码分开提交，变更历史清晰
- **用户定制**: 用户可以修改 `.olav/skills/` 而不触碰框架代码
- **测试友好**: 可以替换 `.olav/` 目录进行 A/B 测试

**实施检查清单**:
- [ ] 所有 Agent 从 `.olav/skills/*/prompts/system.md` 加载 prompt
- [ ] 所有 Tools 从 `.olav/tools/*.py` 动态导入
- [ ] 所有 Skill 配置从 `.olav/skills/*/SKILL.md` 解析
- [ ] Fallback prompt < 30 行（仅用于容错）
- [ ] 无大段 `"""..."""` 硬编码字符串（>10行视为可疑）

**审计命令**:
```bash
# 查找可疑的硬编码 prompt（超过10行的多行字符串）
grep -rn '""".*You are' src/olav/agents/

# 查找硬编码的 tool 实现（应该在 .olav/tools/）
grep -rn 'def execute_' src/olav/agents/

# 验证所有 agents 都使用 _get_system_prompt()
grep -rn '_get_system_prompt\|read_text.*system.md' src/olav/agents/
```

**当前实施状态** (2026-02-16):
- ✅ Tools: 100% 动态加载（agent.py._load_tools()）
- ✅ Skills: 100% 动态加载（agent.py._load_skills()）
- ⚠️ Prompts: 66% 动态加载
  - ✅ admin_agent_v3.py - 从 olav-admin/prompts/system.md 加载
  - ✅ command_learner_agent_v3.py - 从 command_learner/prompts/system.md 加载
  - ⚠️ agent.py - 34行硬编码（待优化）

---

### 3.5. Intent-Based Configuration - 声明意图，不声明命令 ⭐ 新增 (2026-02-17)

**规则**: 用户定义"要检查什么"（WHAT），系统自动找命令（HOW）

**反模式** ❌ 硬编码命令：
```yaml
# ❌ 错误：硬编码平台特定命令
inspection_commands:
  - "show version"           # 只适用 cisco_ios
  - "show processes cpu"     # juniper 是 "show chassis routing-engine"
  - "show interfaces"        # arista 是 "show interfaces status"
```

**问题**:
- 不同平台命令不同（cisco_ios vs juniper_junos vs arista_eos）
- 新增设备需要手动更新命令列表
- 无法适应多厂商环境

**正确做法** ✅ Intent-Based配置：
```yaml
# ✅ 正确：定义意图，系统自动解析命令
intents:
  cpu_utilization:
    description: "CPU利用率和进程信息"
    layer: "L1"
    keywords: ["cpu", "processes", "processor"]
    required_fields:
      - cpu_percent
      - cpu_5min
    thresholds:
      warning: 70
      critical: 90
      
  interface_status:
    description: "接口状态和统计"
    layer: "L2"
    keywords: ["interface", "port", "link"]
    required_fields:
      - interface
      - status
      - protocol
```

**命令解析流程**:
```python
# 1. 从Nornir inventory获取设备平台
device_platform = inventory["R1"]["platform"]  # "cisco_ios"

# 2. 从NTC templates数据库查找最佳命令
resolver = InspectionCommandResolver()
cmd = resolver.resolve_intent("cpu_utilization", device_platform)
# cisco_ios → "show processes cpu" (76% confidence)
# juniper_junos → "show chassis routing-engine" (fallback)

# 3. 执行平台特定命令
execute_cli(device="R1", command=cmd.command)
```

**架构优势**:
- ✅ **平台无关**: 同一intent配置支持所有平台
- ✅ **自动适应**: 新平台加入时，从NTC自动找命令
- ✅ **可扩展**: 添加新intent只需编辑YAML，无需改代码
- ✅ **置信度跟踪**: 系统报告匹配质量（31%-80%）
- ✅ **Fallback机制**: NTC找不到时使用预设命令

**实施规范**:

```bash
# Intent配置文件
.olav/skills/network-inspection/config/inspection_intents.yaml

# 命令解析器
.olav/skills/network-inspection/config/command_resolver.py

# 使用方式
uv run python3 scripts/run_real_inspection.py --template quick
# 自动检测平台 → 解析命令 → 执行
```

**验证命令**:
```bash
# 测试命令解析
cd .olav/skills/network-inspection/config
uv run python3 command_resolver.py

# 检查是否有硬编码命令
grep -rn '"show ' .olav/skills/network-inspection/config/*.yaml
# 应该只在 platform_fallbacks 部分出现

# 验证intent覆盖度
cat .olav/skills/network-inspection/config/inspection_intents.yaml | grep -A2 "^  [a-z_]*:" | grep description
```

**禁止的做法** ❌:
- 在配置中硬编码命令列表
- 在代码中硬编码 platform → command 映射
- 为每个平台维护独立的命令文件
- 命令与检查项目强耦合

**实施检查清单** (2026-02-17):
- ✅ Intent配置文件创建 (18个intents, 6个templates)
- ✅ InspectionCommandResolver实现 (NTC查询 + fallback)
- ✅ 集成到 run_real_inspection.py (动态解析)
- ✅ 真实设备测试通过 (R1, cisco_ios, 5/5命令from NTC)
- ✅ 旧硬编码文件归档 (inspection_commands.yaml.OLD_HARDCODED)
- ✅ 文档完成 (PHASE7_INTELLIGENT_COMMAND_SELECTION_COMPLETE.md)

---

### 4. 使用成熟库，不要造轮子

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

### 5. 使用 LLM 能力，不要写复杂逻辑

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

### 6. 配置分离 - 无硬编码

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

### 7. 不留垃圾代码 - 彻底清理

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

### 8. TDD 开发 - 测试驱动，不绕过

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

### 9. E2E 测试方法论 - 真实环境测试 ⚠️ 必读

**规则**: E2E 测试必须测试真实用户场景，不是测试组件存在

#### ❌ 虚假的 E2E 测试（2026-02-14 审计发现）

```python
# ❌ 只测试 Python API - 不是真实用户场景
def test_agent_query():
    from olav.agents.agent import create_olav_agent
    agent = create_olav_agent()
    result = agent.invoke("Hello")  # 用户不会这样调用
    assert result is not None

# ❌ 只测试组件存在 - 不测试功能
def test_cli_help():
    result = subprocess.run(["python3", "-m", "olav", "--help"])
    assert result.returncode == 0  # 只测试能运行，不测试功能
```

**问题**: 这些测试通过了，但用户运行 `uv run olav ask "..."` 时完全崩溃！

#### ✅ 正确的 E2E 测试

**必须测试所有用户入口点**:

```python
# ✅ 测试真实的 CLI 命令（subprocess）
@pytest.mark.e2e
def test_olav_ask_command_real():
    """测试用户实际使用的命令：uv run olav ask"""
    result = subprocess.run(
        ["uv", "run", "olav", "ask", "What is 2+2?"],
        capture_output=True,
        text=True,
        timeout=30
    )
    
    # 测试命令成功执行
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    
    # 测试输出包含预期内容
    assert "4" in result.stdout or "four" in result.stdout.lower()
    
    # 测试没有错误消息
    assert "Error:" not in result.stderr
    assert "Failed to load" not in result.stderr

# ✅ 测试所有 CLI 命令
@pytest.mark.e2e
@pytest.mark.parametrize("command,expected", [
    (["olav", "admin", "status"], "databases"),
    (["olav", "devices"], "device"),
    (["olav", "--help"], "OLAV"),
    (["olav", "interactive", "--help"], "interactive"),
])
def test_all_cli_commands(command, expected):
    """确保所有声称可用的命令都真实可用"""
    result = subprocess.run(
        ["uv", "run"] + command,
        capture_output=True,
        text=True,
        timeout=10
    )
    assert result.returncode == 0
    assert expected in result.stdout or expected in result.stderr
```

**E2E 测试检查清单**:

1. **✅ 测试真实命令调用**
   - 使用 `subprocess.run(["uv", "run", "olav", ...])`
   - 不要直接 `import` Python 模块

2. **✅ 测试所有入口点**
   - 检查 `pyproject.toml [project.scripts]` 中的所有命令
   - `olav`, `olav2`, `olav-legacy` 等所有脚本

3. **✅ 测试完整用户场景**
   - 不只测试 `--help`
   - 测试实际业务功能（ask, admin, devices, interactive）

4. **✅ 测试失败情况**
   - 无 API key 时的错误提示
   - 无效参数时的错误处理
   - 超时处理

5. **✅ 测试输出正确性**
   - 不只检查 `returncode == 0`
   - 验证 stdout/stderr 内容
   - 检查生成的文件（CSV, JSON 等）

#### 审计教训（2026-02-14）

**错误假设链**:
- "Python API 测试通过" → ❌ "CLI 命令可用"
- "单元测试覆盖 80%" → ❌ "用户场景可用"
- "测试 19/19 通过" → ❌ "项目可发布"

**真实情况**:
- Python API (`agent.invoke()`) ≠ CLI 命令 (`uv run olav ask`)
- 单元测试 ≠ E2E 集成测试
- 测试框架内工作 ≠ 生产环境工作

**正确的测试金字塔**:
```
        / E2E测试 \          ← 少量，测真实用户场景
       /  (subprocess) \       uv run olav ask "..."
      /_________________\
     /   集成测试          \   ← 中等数量，测组件集成
    /   (agent.invoke)   \     agent.invoke(query)
   /_____________________\
  /      单元测试           \  ← 大量，测单个函数
 / (test_database_query)  \    test_sql_query()
/___________________________\
```

**开发流程**:
1. TDD: 先写单元测试 → 实现功能
2. 集成测试: 测试 Python API (`agent.invoke()`)
3. **E2E 测试: 测试真实 CLI 命令（subprocess）**
4. 手动测试: 实际运行 `uv run olav ask "..."`
5. 只有 E2E 测试全部通过，才算完成

---

### 10. Skill-aware Tool Loading - 工具与技能一致性 ⭐ 必须遵守

**规则**: 所有 Tools 必须在 Skill 中注册，Tool 加载必须感知 Skill 上下文

#### 问题（2026-02-17 发现）

```
当前架构混乱:
❌ .olav/tools/network.py (包装器)  → 只是代理
❌ .olav/tools/database.py (包装器) → 只是代理
❌ .olav/tools/inspection.py        → 单独维护
✅ .olav/skills/shared/tools/ (实现) → 真正的实现集中地

❌ Skills 定义中的 Tools 被忽略:
   network-inspection/SKILL.md:
   tools: [inspect_schema, query_database, discover_data]
   但 Agent 实际加载: [execute_sql, execute_cli, list_devices_inventory]

❌ MapReduce 逻辑被隐藏在函数中，不是 Tool:
   report_formatter.generate_professional_inspection_report()
   # 这是函数，不是 @tool，Agent 无法调用
```

#### 正确做法 ✅

**1️⃣ 工具单源加载**
```python
# ❌ 错误：从多个地方加载，代码重复
agent.tools = [
    load_from(".olav/tools/network.py"),      # 包装器
    load_from(".olav/tools/database.py"),     # 包装器
    load_from(".olav/tools/inspection.py"),   # 独立
]

# ✅ 正确：单源，从 shared/tools 加载
agent.tools = load_from_shared_tools()

def _load_tools(self) -> list:
    """Load ALL tools from .olav/skills/shared/tools/"""
    tools = []
    shared_tools_path = self.olav_base_path / "skills" / "shared" / "tools"
    
    for tool_file in shared_tools_path.glob("*.py"):
        if tool_file.name.startswith("_"):
            continue
        tool = load_tool_from_file(tool_file)
        if tool:
            tools.append(tool)
    
    return tools
```

**2️⃣ Skill-aware Tool Loading**
```python
# ✅ Agent 初始化时感知 Skills
def _load_tools(self) -> list:
    """Load tools with Skill awareness"""
    tools = {}
    
    # 从共享工具库加载
    shared_tools = self._load_shared_tools()
    
    # 按 Skill 组织工具
    for skill_name, skill_data in self.skills.items():
        fm = skill_data.get("frontmatter", {})
        skill_tools = fm.get("tools", [])
        
        # 为每个 Skill 的工具创建上下文感知别名
        for tool_name in skill_tools:
            tool = self._find_tool(tool_name, shared_tools)
            if tool:
                # 添加 Skill 上下文信息
                tool.skill_context = {
                    "skill_name": skill_name,
                    "skill_description": fm.get("description"),
                    "skill_instructions": skill_data.get("content")
                }
                tools[tool_name] = tool
    
    return list(tools.values())
```

**3️⃣ MapReduce 作为 Tool**
```python
# ❌ 错误：隐藏的函数
def generate_professional_inspection_report(...):
    # Agent 不知道这个能力
    pass

# ✅ 正确：显式的 Tool
@tool
def aggregate_inspection_results(
    results: list[dict],
    inspection_type: str = "network-inspection"
) -> dict:
    """Reduce: Aggregate inspection results into final report.
    
    Use this after parallel inspection execution to:
    - Combine individual device results
    - Calculate health scores
    - Generate markdown report
    - Identify anomalies
    """
    # 调用 report_formatter 生成报告
    return generate_professional_inspection_report(...)
```

**4️⃣ Tool 注册清单**
```python
# .olav/skills/shared/tools/__init__.py
"""Export all tools for dynamic loading"""

from .network_executor import execute_cli, nornir_execute
from .data_gateway import execute_sql, query_database
from .aggregation import aggregate_inspection_results  # NEW: MapReduce
from .report_formatter import generate_professional_inspection_report
from .sync_tools import sync_all
from .inspection_scheduler import manage_inspection_schedule

__all__ = [
    "execute_cli",
    "nornir_execute", 
    "execute_sql",
    "query_database",
    "aggregate_inspection_results",  # ← Reduce Tool
    "generate_professional_inspection_report",
    "sync_all",
    "manage_inspection_schedule",
]
```

#### 工具位置规范

```bash
# ✅ 标准位置
.olav/skills/shared/tools/
├── __init__.py                           # 导出所有 Tools
├── network_executor.py    (@tool 执行)
├── data_gateway.py        (@tool 查询)  
├── aggregation.py         (@tool NEW: 聚合)
├── batch_executor.py      (@tool NEW: 批量)
├── report_formatter.py    (辅助函数)
├── inspection_scheduler.py (@tool)
└── sync_tools.py          (@tool)

# ❌ 不要有
.olav/tools/network.py     # 包装器→应该删除
.olav/tools/database.py    # 包装器→应该删除
.olav/tools/inspection.py  # 应该合并到 shared
```

#### Skills ↔ Tools 对齐检查清单

在添加或修改 Skill 时，必须检查：

```yaml
# .olav/skills/network-inspection/SKILL.md
name: network-inspection
version: 2.2.0

# MUST: 这些 Tools 必须存在于 shared/tools 中
tools:
  - execute_sql              # ✓ shared/tools/data_gateway.py
  - query_database           # ✓ shared/tools/data_gateway.py
  - list_devices_inventory   # ✓ shared/tools/network_executor.py
  - aggregate_inspection_results  # ✓ shared/tools/aggregation.py

# MUST: 每个 tool 必须有 @tool decorator 和清晰的 docstring
# MUST: 工具名称必须匹配 Skill 定义中的名称
```

**验证命令**:
```bash
# 查看加载了哪些 Tools
uv run python3 -c "
from src.olav.agents.agent import OLAVAgent
agent = OLAVAgent()
for tool in agent.tools:
    print(f'✓ {tool.name}')
"

# 查看 Skills 中定义了哪些 Tools
uv run python3 -c "
from src.olav.agents.agent import OLAVAgent
agent = OLAVAgent()
for skill_name, skill_data in agent.skills.items():
    fm = skill_data.get('frontmatter', {})
    tools = fm.get('tools', [])
    if tools:
        print(f'{skill_name}: {tools}')
"

# 检查不匹配
# 如果某个 Skill 的 tool 不在加载的 Tools 中，说明对齐失败
```

---

### 11. 禁止Mock测试 - 必须使用真实设备和LLM ⛔ 强制规则

**规则**: E2E测试必须连接真实设备、调用真实LLM、执行真实Map-Reduce流程

#### ❌ 严禁的Mock测试模式（2026-02-17 重大发现）

```python
# ❌ 硬编码假数据
mock_results = [
    {"device": "router-core-01", "cpu": 45},  # 假设备名
    {"device": "router-edge-02", "cpu": 60},  # 不存在的设备
]

# ❌ 绕过Map-Reduce流程
conn = duckdb.connect(".olav/db/main.duckdb")
devices = conn.execute("SELECT * FROM devices LIMIT 6").fetchall()  # 硬编码LIMIT
# 直接构造结果，没有经过execute_commands_in_parallel()

# ❌ Mock掉真实工具
@patch('network.nornir_execute')
def test_inspection(mock_execute):
    mock_execute.return_value = {"status": "success", "output": "fake"}
    # 没有测试真实的网络执行

# ❌ 使用测试数据库代替真实inventory
db_devices = ["SW001", "SW002", ...]  # 80个模拟设备
# 真实设备在 hosts.yaml 中只有6个！
```

**为什么这些是错误的？**
1. **数据不一致**: 测试用假数据，生产用真数据 → 测试通过但生产失败
2. **流程绕过**: 没有测试完整的Map-Reduce pipeline → 集成问题无法发现
3. **设备分离**: inventory有6个设备，DB有80个设备 → 数据来源混乱
4. **硬编码数量**: `LIMIT 6` 写死 → 设备增减时测试失败

#### ✅ 正确的真实测试流程

**完整的Inspection Pipeline测试**:

```python
# ✅ STEP 1: 从真实Nornir inventory获取设备清单
from network import list_devices_inventory

devices_result = list_devices_inventory()  # 查询 hosts.yaml
assert devices_result["status"] == "success"
device_list = [d["name"] for d in devices_result["devices"]]
# 返回: ["R1", "R2", "R3", "R4", "SW1", "SW2"] - 动态获取

# ✅ STEP 2: Map Phase - 真实并行执行
from batch_executor import execute_commands_in_parallel
from network import nornir_execute

def real_executor(device: str, command: str) -> tuple[bool, str]:
    """使用真实Nornir执行器"""
    result = nornir_execute(command=command, device=device, timeout=30)
    if result["status"] == "success":
        return (True, result["result"][device]["output"])
    return (False, result.get("error", "Failed"))

map_results = execute_commands_in_parallel(
    devices=device_list,          # 动态设备清单
    command="show version",       # 真实命令
    executor_func=real_executor,  # 真实执行器，不是mock
    timeout_seconds=30
)

assert map_results["total_devices"] == len(device_list)
assert map_results["successful"] > 0  # 至少有设备成功

# ✅ STEP 3: Reduce Phase - 真实聚合
from aggregation import aggregate_inspection_results

# 转换Map结果为Reduce输入格式
device_results = {}
for result in map_results["results"]:
    device = result["device"]
    if device not in device_results:
        device_results[device] = {"device": device, "commands": []}
    device_results[device]["commands"].append({
        "cmd": result["command"],
        "output": result.get("output", ""),
        "status": result["status"]
    })

reduce_input = list(device_results.values())

# 真实的聚合和健康评分
aggregated = aggregate_inspection_results(
    results=reduce_input,
    inspection_type="network-inspection"
)

assert aggregated["device_count"] == len(device_list)
assert "overall_health_score" in aggregated
assert "anomalies" in aggregated

# ✅ STEP 4: LLM分析（如果需要）
# LLM会基于真实输出分析异常，不是基于mock数据

# ✅ STEP 5: 生成生产级报告
from report_formatter import format_inspection_report_l1_l4

report = format_inspection_report_l1_l4(aggregated)

# 验证报告包含真实设备名称
for device in device_list:
    assert device in report, f"Report missing device {device}"

# 验证报告不包含假设备名称
assert "router-core-01" not in report  # 假设备
assert "router-edge-02" not in report  # 假设备

# 保存报告
report_path = Path("exports/reports/inspection_real.md")
report_path.write_text(report)
assert report_path.exists()
```

#### 强制规则

**测试编写规则**:
1. **✅ MUST**: 从 `hosts.yaml` 动态加载设备清单（不能硬编码）
2. **✅ MUST**: 调用 `execute_commands_in_parallel()` 执行Map phase
3. **✅ MUST**: 调用 `aggregate_inspection_results()` 执行Reduce phase  
4. **✅ MUST**: 验证真实设备名称出现在报告中
5. **✅ MUST**: 验证假设备名称不出现在报告中

**❌ MUST NOT**:
1. **❌ 禁止**: 硬编码设备清单 `devices = ["R1", "R2"]`
2. **❌ 禁止**: 硬编码数量 `LIMIT 6`
3. **❌ 禁止**: 跳过Map phase，直接构造结果
4. **❌ 禁止**: Mock `nornir_execute` 等核心工具
5. **❌ 禁止**: 使用测试数据库代替真实inventory

#### 数据来源统一规则

**唯一真实来源** (Single Source of Truth):

```
Nornir Inventory: .olav/config/nornir/hosts.yaml
├─ 6个真实设备: R1, R2, R3, R4, SW1, SW2
├─ 包含: hostname, platform, role, site
└─ 这是唯一的设备清单来源

DuckDB: .olav/db/main.duckdb
├─ 从Nornir同步数据: sync_all()
├─ 存储历史数据: parsed_outputs, inspection_results
└─ 设备清单: 与hosts.yaml同步，不能独立维护
```

**数据同步流程**:
```python
# ✅ 正确：DB从Nornir同步
from sync_tools import sync_all

# 第一次同步：从hosts.yaml导入设备
sync_all()  # 读取hosts.yaml，写入devices表

# 后续查询：DB和Nornir一致
db_devices = query("SELECT name FROM devices")
nornir_devices = list_devices_inventory()
assert set(db_devices) == set(nornir_devices)  # 必须一致
```

**❌ 错误做法**:
```python
# ❌ DB中有80个设备，hosts.yaml只有6个
# ❌ 独立维护两份设备清单
# ❌ 测试用DB数据，生产用hosts.yaml
```

#### 测试执行脚本

**使用真实inspection脚本测试**:

```bash
# ✅ 运行真实inspection（连接真实设备）
uv run python3 scripts/run_real_inspection.py

# ✅ 运行E2E测试（调用真实inspection脚本）
uv run pytest tests/e2e/test_real_inspection_pipeline.py -v

# ✅ 验证报告质量
cat exports/reports/inspection_real_*.md
grep "R1\|R2\|R3\|R4\|SW1\|SW2" exports/reports/inspection_real_*.md
```

**删除旧的Mock测试**:
```bash
# ❌ 删除：使用硬编码mock数据的测试
rm tests/e2e/test_inspection_report_complete.py  # 已归档

# ❌ 删除：模拟数据库
mv .olav/db/main.duckdb _legacy_archived/  # 已备份

# ✅ 保留：真实设备的E2E测试
# scripts/run_real_inspection.py - 真实流程
# tests/e2e/test_real_inspection_pipeline.py - 真实测试
```

#### 验收标准

**E2E测试必须满足**:
- [ ] 从 `hosts.yaml` 动态获取设备清单（不硬编码）
- [ ] 调用 `execute_commands_in_parallel()` 执行真实Map
- [ ] 调用 `aggregate_inspection_results()` 执行真实Reduce
- [ ] 连接真实设备执行命令（或明确标记为mock环境）
- [ ] 生成的报告包含真实设备名称
- [ ] 报告不包含任何假设备名称
- [ ] 数据库与inventory同步（设备数量一致）

**审计命令**:
```bash
# 查找Mock用法
grep -rn "mock\|Mock\|fake\|FAKE" tests/e2e/

# 查找硬编码设备清单
grep -rn 'devices = \[' tests/e2e/

# 查找硬编码LIMIT
grep -rn 'LIMIT [0-9]' tests/e2e/

# 查找@patch装饰器
grep -rn '@patch\|@mock' tests/e2e/
```

#### 异常情况处理

**当真实设备不可用时**:

```python
# ✅ 方案1: 跳过E2E测试，添加说明
@pytest.mark.e2e
@pytest.mark.skipif(not is_nornir_available(), reason="Nornir devices not available")
def test_real_inspection():
    """Real inspection pipeline - requires network devices"""
    pass

# ✅ 方案2: 使用mock环境但明确标记
@pytest.mark.mock_environment
def test_inspection_with_mock_devices():
    """MOCK ENVIRONMENT: Testing pipeline logic, not real devices
    
    WARNING: This test uses simulated devices, not real network equipment.
    For production validation, run test_real_inspection() instead.
    """
    pass

# ❌ 方案3: 静默使用mock但声称是E2E测试 - 禁止！
```

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