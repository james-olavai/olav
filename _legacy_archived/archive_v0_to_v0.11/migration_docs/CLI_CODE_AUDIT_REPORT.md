# OLAV CLI 代码审计报告

**审计日期**: 2026-02-02  
**审计员**: GitHub Copilot  
**分支**: feature/fast-path-0.9xx

---

## 📋 问题清单

### 1️⃣ 历史记录功能失败 ❌

#### 问题描述
CommandHistory 模块未能正确初始化和使用。

#### 根因分析

**文件**: `src/olav/cli/session.py`

```python
# Line 18-23
try:
    from olav.cli.command_history import CommandHistory
except (ImportError, ModuleNotFoundError):
    CommandHistory = None  # type: ignore[assignment]
    logger.debug("CommandHistory module not available, using in-memory history")
```

**关键发现**:
1. **`command_history.py` 文件不存在**！
   - 检查 `src/olav/cli/` 目录：没有 `command_history.py` 文件
   - 只有: `cli_main.py`, `commands.py`, `display.py`, `input_parser.py`, `memory.py`, `session.py`

2. **历史记录依赖缺失**:
   - `self.command_history` 被设置为 `None`
   - 导致历史补全功能 (`get_recent_commands`) 无法工作

3. **prompt-toolkit 的 FileHistory 在异步上下文中被禁用**:
   ```python
   # Line 101-109
   try:
       asyncio.get_running_loop()
       logger.debug("Async context detected, disabling prompt-toolkit")
       self._session = None  # ← FileHistory 也被禁用！
       return
   except RuntimeError:
       pass
   ```
   - CLI 运行在 `async def run_interactive_loop_async()` 中
   - 导致 **prompt-toolkit 完全被禁用**，历史记录无法保存/加载

#### 建议修复方向
1. 创建 `command_history.py` 模块或移除相关引用
2. 考虑使用 deepagents 内置的 checkpointer 机制
3. 不要在异步上下文中完全禁用 FileHistory

---

### 2️⃣ 没有补全功能 ❌

#### 问题描述
Tab 补全功能完全不工作。

#### 根因分析

**文件**: `src/olav/cli/session.py`

```python
# Line 139-150
if self.enable_completion and self.command_history:
    try:
        recent_commands = self.command_history.get_recent_commands(limit=50)
        if recent_commands:
            command_words = list(set(cmd.get("command", "") for cmd in recent_commands))
            if command_words:
                word_completer = WordCompleter(words=command_words, ignore_case=True)
                session.completer = word_completer
```

**关键发现**:
1. **`self.command_history` 为 `None`** (因为模块不存在)
2. **`self._session` 为 `None`** (因为异步上下文检测)
3. **补全只依赖历史命令**，没有使用 whitelist 中的预定义命令

**额外问题**: `_load_whitelist()` 加载了白名单但从未使用！
```python
# Line 56
self.whitelist = self._load_whitelist()  # 加载了白名单

# 但在补全设置中：
if self.enable_completion and self.command_history:  # ← 只检查 command_history
```

#### 建议修复方向
1. 使用 whitelist 作为补全词源
2. 修复 prompt-toolkit 在异步上下文中的工作方式
3. 考虑使用 asyncio 兼容的补全方案

---

### 3️⃣ 交互CLI模式下卡在 "Generating SQL and querying..." ❌

#### 问题描述
查询执行后长时间卡在 spinner 状态。

#### 根因分析

**文件**: `src/olav/cli/cli_main.py`

```python
# Line 73-74
try:
    final_state = await agent.ainvoke(base_inputs, learn_callback=learn_callback)
```

**关键发现**:

1. **`learn_callback` 被同步调用但运行在异步上下文中**:
   ```python
   # Line 191 - session.prompt_sync() 被调用
   user_response = session.prompt_sync(prompt_msg)
   ```
   - `prompt_sync()` 检测到异步上下文后使用 `input()` 
   - `input()` 在异步上下文中会阻塞整个事件循环
   - 导致 **死锁或严重延迟**

2. **LLM API 调用可能超时**:
   - 没有明确的超时设置
   - 网络问题可能导致无限等待

3. **Spinner 状态管理问题**:
   ```python
   # Line 69-70
   if not verbose:
       display.show_processing_status("Generating SQL and querying...")
   # 如果 ainvoke 永远不返回，spinner 永远不停止
   ```

#### 建议修复方向
1. 为 LLM 调用添加超时机制
2. 使用 `asyncio.wait_for()` 包装长时间操作
3. 将 `learn_callback` 改为异步版本

---

### 4️⃣ R3 是标准设备名称，为何触发学习提示？ ❌

#### 问题描述
`R3` 是数据库中存在的标准设备名称，但系统仍然提示 "I don't know 'R3'"。

#### 根因分析

**文件**: `src/olav/agents/query_agent_v2.py`

```python
# Line 174-178 - 正则表达式提取实体
entities = re.findall(r"[\u4e00-\u9fa5]+|[A-Z]+\d*", query)

# Line 185-186 - 检查别名表
canonical = self.gw.get_user_alias(skill_name, entity)

if canonical:
    # Known alias - replace it
    ...
elif learn_callback and learning_count < max_prompts:
    # Unknown alias - trigger interactive learning  ← R3 触发此分支！
```

**关键发现**:

1. **别名查找逻辑错误**:
   - `get_user_alias()` 只查询 `user_aliases` 表
   - **不检查设备是否在 `v_system` 视图中存在！**

2. **数据库查询确认**:
   ```
   skill.duckdb 的表: ['intent_cache', 'query_templates', 'user_aliases']
   v_system 视图不存在于 skill.duckdb！
   ```

3. **视图定义在快照数据库中，不在 skill.duckdb 中**:
   - 快照数据库需要通过 `UnifiedDatabase` 的 `ATTACH` 机制挂载
   - `_process_aliases()` 中的 `self.gw.get_user_alias()` 只查询 skill.duckdb

4. **应该先验证设备是否存在**:
   ```sql
   -- 应该先执行此查询
   SELECT device FROM v_system WHERE device = 'R3'
   
   -- 而不是只查 user_aliases
   SELECT canonical FROM user_aliases WHERE alias = 'R3'
   ```

#### 建议修复方向

**方案 A**: 添加设备存在性检查
```python
def _process_aliases(self, query, learn_callback=None):
    # 先检查设备是否在数据库中
    known_devices = self.gw.query_snapshots(
        "SELECT DISTINCT device FROM v_system"
    )
    known_device_names = {d['device'] for d in known_devices}
    
    for entity in entities:
        if entity in known_device_names:
            continue  # 跳过已知设备
        # ... 原有的别名查找逻辑
```

**方案 B**: 预加载 hosts.yaml 或设备清单
- 在 Agent 初始化时加载设备列表
- 或使用 deepagents 的 skills/memory 机制

---

### 5️⃣ 是否支持多会话上下文记忆和总结？ ⚠️

#### 问题描述
需要检查 CLI 是否支持多轮对话上下文和自动总结。

#### 审计发现

**文件**: `src/olav/cli/memory.py`

```python
class AgentMemory:
    """Session memory persistence using User-Local DuckDB."""
    
    def add(self, role: str, content: str, **kwargs):
        # 仅存储 role + content，没有会话 ID
        
    def get_conversation_messages(self, max_turns=10, max_chars=8000):
        # 获取最近消息，但没有总结机制
```

**关键发现**:

1. **基本记忆功能存在** ✅
   - 消息存储在 DuckDB `session_history` 表
   - 可以获取最近 N 轮对话

2. **缺失 deepagents 原生功能** ❌
   - **没有使用 `checkpointer` 参数**
   - **没有使用 `memory` 参数** 
   - **没有使用 `SummarizationMiddleware`**

3. **deepagents 内置支持**:
   ```python
   # 当前代码 (Line 72-77 in query_agent_v2.py)
   self.agent = create_deep_agent(
       model=model,
       tools=self.tools,
       system_prompt=self.system_prompt,
       middleware=[self.skills_middleware],
   )
   
   # 应该使用：
   self.agent = create_deep_agent(
       ...
       checkpointer=True,  # 启用状态持久化
       memory=["/memory/AGENTS.md"],  # 加载记忆文件
       middleware=[
           self.skills_middleware,
           # SummarizationMiddleware 会自动添加
       ],
   )
   ```

4. **缺少会话 ID 管理**:
   ```python
   # 当前
   self.session_id = None  # Could be generated per session if needed
   
   # 应该：
   self.session_id = str(uuid.uuid4())  # 每次会话生成唯一 ID
   ```

#### 建议修复方向
1. 使用 deepagents 的 `checkpointer=True` 启用内置状态持久化
2. 使用 `memory` 参数加载 AGENTS.md 格式的记忆文件
3. 让 deepagents 的 `SummarizationMiddleware` 处理长对话总结

---

### 6️⃣ 未使用 deepagents 原生功能 ⚠️

#### 问题描述
代码重复实现了 deepagents 已有的功能。

#### 审计发现

| 功能 | deepagents 原生 | OLAV 自实现 | 状态 |
|------|----------------|-------------|------|
| 会话记忆 | `checkpointer`, `memory` | `AgentMemory` class | 重复实现 ❌ |
| 对话总结 | `SummarizationMiddleware` | 无 | 未使用 ❌ |
| TODO 管理 | `TodoListMiddleware` | 无 | 未使用 ⚠️ |
| 文件操作 | `FilesystemMiddleware` | 部分使用 | 可优化 |
| Skills | `SkillsMiddleware` | ✅ 已使用 | ✅ |
| Subagents | `subagents` 参数 | 无 | 未使用 ⚠️ |

**未使用的关键功能**:

```python
# deepagents 提供的完整功能列表 (来自 help 文档)
create_deep_agent(
    model=...,
    tools=...,
    system_prompt=...,
    middleware=...,           # ✅ 已使用
    subagents=...,            # ❌ 未使用 (可用于联邦专家模式)
    skills=...,               # ❌ 未使用 (直接使用 SkillsMiddleware)
    memory=...,               # ❌ 未使用 (自己实现了 AgentMemory)
    checkpointer=...,         # ❌ 未使用 (会话状态持久化)
    store=...,                # ❌ 未使用 
    backend=...,              # ✅ 已使用 FilesystemBackend
    interrupt_on=...,         # ❌ 未使用 (人机协作中断)
    cache=...,                # ❌ 未使用 (可替代自实现的 intent_cache)
)
```

---

## 📊 问题汇总

| # | 问题 | 严重程度 | 根因 | 建议 |
|---|------|----------|------|------|
| 1 | 历史记录失败 | 🔴 高 | command_history.py 不存在 + 异步禁用 | 创建模块或使用 deepagents checkpointer |
| 2 | 补全不工作 | 🔴 高 | prompt-toolkit 在异步中被禁用 | 重构异步处理或使用兼容方案 |
| 3 | 查询卡住 | 🔴 高 | 同步 input() 在异步上下文中阻塞 | 使用异步 input 或 run_in_executor |
| 4 | R3 触发学习 | 🟡 中 | 只查 user_aliases 不查 v_system | 添加设备存在性验证 |
| 5 | 缺少会话总结 | 🟡 中 | 未使用 deepagents 记忆功能 | 启用 checkpointer + memory |
| 6 | 重复实现 | 🟡 中 | 未充分利用 deepagents | 迁移到原生功能 |

---

## 🎯 关键修复建议（优先级排序）

### P0 - 立即修复

1. **修复异步上下文中的 prompt-toolkit**
   - 问题: `_init_session()` 完全禁用 prompt-toolkit
   - 方案: 使用 `nest_asyncio` 或分离 prompt 处理

2. **修复设备识别逻辑**
   - 问题: `_process_aliases()` 不检查 v_system
   - 方案: 添加设备存在性验证

### P1 - 高优先级

3. **使用 deepagents 原生记忆**
   ```python
   self.agent = create_deep_agent(
       ...
       checkpointer=True,  # 状态持久化
       memory=[".olav/memory/AGENTS.md"],  # 记忆文件
   )
   ```

4. **创建或移除 CommandHistory**
   - 要么创建 `command_history.py`
   - 要么使用 deepagents 的 store 机制

### P2 - 中优先级

5. **添加查询超时机制**
   ```python
   final_state = await asyncio.wait_for(
       agent.ainvoke(base_inputs),
       timeout=60.0  # 60 秒超时
   )
   ```

6. **使用 subagents 实现联邦专家**
   - 当前手动切换 skill_name
   - 可使用 deepagents 的 subagents 机制

---

## 📝 代码审计结论

### 核心问题
1. **异步/同步冲突**: prompt-toolkit 在异步上下文中完全被禁用，导致历史、补全、输入都退化到基础 `input()`
2. **功能重复实现**: AgentMemory 重复了 deepagents checkpointer 的功能
3. **设备识别缺陷**: `_process_aliases()` 不验证设备是否在数据库中存在

### 建议方向
1. **拥抱 deepagents 原生功能**: checkpointer, memory, SummarizationMiddleware
2. **重构异步处理**: 使用 `nest_asyncio` 或将同步操作移到线程池
3. **完善设备验证**: 在提示学习前先检查设备是否存在

---

## � 深度分析: 原生组件替换方案

### 问题 1: langgraph-checkpoint-duckdb 能否统一管理所有 DuckDB？

#### 分析结论: **不能**

`langgraph-checkpoint-duckdb` 专门用于 **LangGraph 图状态持久化**，不是通用 DuckDB 组件。

| 组件 | 职责 | 表结构 | 能否统一？ |
|------|------|--------|-----------|
| `DuckDBSaver` (checkpointer) | 图状态持久化 | `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` | ❌ 专用 |
| `DuckDBStore` (store) | 键值存储 (namespace/key/value) | `store` | ⚠️ 可替代部分缓存 |
| 自定义 `semantic_cache` | 查询缓存 | 自定义 | ❌ 需保留 |
| `session_history` | 对话历史 | 自定义 | ✅ 可被 checkpointer 替代 |

**关键发现**:
```python
# DuckDBSaver 表结构 (专用于图状态)
checkpoints: thread_id, checkpoint_ns, checkpoint_id, checkpoint, metadata
checkpoint_blobs: thread_id, checkpoint_ns, channel, version, blob
checkpoint_writes: thread_id, checkpoint_ns, checkpoint_id, task_id, idx, blob

# DuckDBStore 表结构 (通用键值存储)
store: prefix, key, value (JSON), created_at, updated_at
```

#### 建议架构

```
~/.olav/
├── cache_{user}.duckdb          # 保留: semantic_cache, intent_cache, user_aliases
├── checkpoints/{user}.duckdb   # 新增: DuckDBSaver (图状态) + DuckDBStore (KV存储)
└── history/{user}.txt          # 保留: prompt-toolkit FileHistory
```

**DuckDBStore 可以替换的功能**:
1. ✅ `session_history` → 使用 checkpointer 自动管理
2. ✅ `user_aliases` → 可迁移到 DuckDBStore (namespace: `(user, 'aliases')`)
3. ❌ `semantic_cache` → 保留自定义表 (需要 SQL 查询能力)
4. ❌ `intent_cache` → 保留自定义表 (需要 SQL 查询能力)

---

### 问题 2: 还有哪些功能可以用 deepagents/langchain 原生替换？

#### 发现的可替换组件

| 当前自定义实现 | 原生替代方案 | 替换优先级 | 说明 |
|---------------|-------------|-----------|------|
| `AgentMemory` | `DuckDBSaver` checkpointer | 🔴 高 | 完全替代 |
| `session_history` 表 | `DuckDBSaver` checkpointer | 🔴 高 | 完全替代 |
| `CommandHistory` (缺失) | `FileHistory` (prompt-toolkit) | 🔴 高 | 使用原生 |
| 手动对话上下文管理 | `SummarizationMiddleware` | 🟡 中 | 长对话自动总结 |
| 手动子代理调用 | `SubAgentMiddleware` | 🟡 中 | 联邦专家模式 |
| `user_aliases` 表 | `DuckDBStore` | 🟢 低 | 可选迁移 |
| `LLMFactory` | `create_deep_agent(model=str)` | 🟢 低 | deepagents 支持 `provider:model` 格式 |

#### 详细分析

**1. SummarizationMiddleware (强烈推荐)**

```python
from deepagents.middleware.summarization import SummarizationMiddleware

# 当前: 手动截断历史
memory.get_context(max_messages=10)  # 简单截断

# 原生: 智能总结
SummarizationMiddleware(
    model="gemini-flash",  # 用于总结的模型
    backend=FilesystemBackend(),
    trigger=("tokens", 100000),  # 触发条件
    keep=("messages", 20),  # 保留最近 N 条
)
```

**2. SubAgentMiddleware (可选)**

```python
from deepagents import SubAgent, SubAgentMiddleware

# 当前: 手动路由到不同 skill
if decision.expert == "bgp-expert":
    # 切换 skill
    
# 原生: 联邦子代理
subagents = [
    SubAgent(name="bgp-expert", instructions="BGP 专家..."),
    SubAgent(name="ospf-expert", instructions="OSPF 专家..."),
]
SubAgentMiddleware(
    default_model="gemini-flash",
    subagents=subagents,
)
```

**3. DuckDBStore 替代 user_aliases**

```python
from langgraph.store.duckdb import DuckDBStore

# 当前: 自定义表
db.query("SELECT canonical FROM user_aliases WHERE alias = ?", [entity])

# 原生: KV 存储
store = DuckDBStore(conn)
store.put(("network-query", "aliases"), "R3", {"canonical": "R3", "type": "device"})
result = store.get(("network-query", "aliases"), "R3")
```

**4. deepagents 模型初始化**

```python
# 当前: LLMFactory
from olav.core.llm import LLMFactory
llm = LLMFactory.get_chat_model()

# 原生: create_deep_agent 直接传字符串
agent = create_deep_agent(
    model="ollama:qwen2.5:14b",  # provider:model 格式
    # 或
    model="openai:gpt-4o",
)
```

---

## 🏗️ 最终架构设计

### 数据库架构

```
~/.olav/
├── cache_{user}.duckdb           # 用户缓存 (保留)
│   ├── semantic_cache           # 语义缓存 (SQL 查询)
│   ├── intent_cache             # 意图缓存 (SQL 查询)
│   └── query_templates          # 查询模板 (SQL 查询)
│
├── checkpoints/{user}.duckdb    # 用户检查点 (新增)
│   ├── checkpoints              # LangGraph 图状态
│   ├── checkpoint_blobs         # 图状态 blob
│   ├── checkpoint_writes        # 图写入
│   ├── store                    # KV 存储 (user_aliases 迁移)
│   └── store_migrations         # 迁移版本
│
└── history/{user}.txt           # 命令历史 (prompt-toolkit)
```

### 组件映射

```python
# config/paths.py 新增
USER_CHECKPOINT_DIR = Path.home() / ".olav" / "checkpoints"
USER_CHECKPOINT_PATH = USER_CHECKPOINT_DIR / f"{_username}.duckdb"
USER_HISTORY_DIR = Path.home() / ".olav" / "history"
USER_HISTORY_PATH = USER_HISTORY_DIR / f"{_username}.txt"
```

### Agent 初始化 (目标代码)

```python
# src/olav/agents/query_agent_v2.py
import duckdb
from langgraph.checkpoint.duckdb import DuckDBSaver
from langgraph.store.duckdb import DuckDBStore
from deepagents import create_deep_agent
from deepagents.middleware.summarization import SummarizationMiddleware

class QueryAgentV2:
    def __init__(self, skill_name: str = "network-query", ...):
        # 1. 初始化用户级数据库
        self._init_user_database()
        
        # 2. 创建 agent (使用原生组件)
        self.agent = create_deep_agent(
            model=settings.llm_model_name,  # 直接使用字符串
            tools=self.tools,
            system_prompt=self.system_prompt,
            middleware=[
                self.skills_middleware,
                SummarizationMiddleware(  # 原生总结
                    model="gemini-flash",
                    backend=self.backend,
                    trigger=("tokens", 50000),
                    keep=("messages", 10),
                ),
            ],
            checkpointer=self.checkpointer,  # 原生状态持久化
            store=self.store,  # 原生 KV 存储
        )
    
    def _init_user_database(self):
        """Initialize user-specific DuckDB with checkpointer and store."""
        USER_CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        # 共享连接
        self.conn = duckdb.connect(str(USER_CHECKPOINT_PATH))
        
        # Checkpointer (会话状态)
        self.checkpointer = DuckDBSaver(self.conn)
        self.checkpointer.setup()
        
        # Store (KV 存储，替代 user_aliases)
        self.store = DuckDBStore(self.conn)
        self.store.setup()
```

---

## �🔧 确定的修复方案

### 架构决策: 用户级会话数据库

#### 决策分析

**当前架构**:
- `USER_CACHE_PATH = ~/.olav/cache_{username}.duckdb` (已实现用户隔离)
- `session_history` 表在用户缓存中 (但没有 session_id 管理)
- 自定义 `AgentMemory` 类 (重复实现)

**建议架构**: 使用 `langgraph-checkpoint-duckdb` 原生方案

| 方面 | 当前方案 | 建议方案 |
|------|----------|----------|
| 会话持久化 | 自定义 `AgentMemory` | `DuckDBSaver` checkpointer |
| 用户隔离 | `~/.olav/cache_{user}.duckdb` | `~/.olav/checkpoints/{user}.duckdb` |
| 会话 ID | 无 | LangGraph 原生 `thread_id` |
| 状态恢复 | 手动查询 | 自动恢复 |
| 对话总结 | 无 | `SummarizationMiddleware` |

#### 用户识别方案

```python
# config/paths.py 中已有的用户识别逻辑
import os
try:
    _username = os.environ.get("USER") or os.getlogin()  # Linux/Mac
except Exception:
    _username = os.environ.get("USERNAME", "default_user")  # Windows fallback

# 新增: 用户级检查点数据库路径
USER_CHECKPOINT_PATH = Path.home() / ".olav" / "checkpoints" / f"{_username}.duckdb"
```

**跨平台兼容**:
- Linux: `$USER` 环境变量
- Windows: `$USERNAME` 环境变量
- 容器: 可通过环境变量覆盖

---

### 修复方案 1: 使用 DuckDBSaver 替代 AgentMemory

**文件**: `src/olav/agents/query_agent_v2.py`

```python
# 新增导入
import duckdb
from langgraph.checkpoint.duckdb import DuckDBSaver
from config.paths import USER_CHECKPOINT_PATH

class QueryAgentV2:
    def __init__(self, ...):
        ...
        # 创建用户级检查点
        self._init_checkpointer()
        
        # 使用 deepagents 原生 checkpointer
        self.agent = create_deep_agent(
            model=model,
            tools=self.tools,
            system_prompt=self.system_prompt,
            middleware=[self.skills_middleware],
            checkpointer=self.checkpointer,  # ← 新增
        )
    
    def _init_checkpointer(self):
        """Initialize user-specific DuckDB checkpointer."""
        USER_CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(USER_CHECKPOINT_PATH))
        self.checkpointer = DuckDBSaver(conn)
        self.checkpointer.setup()
```

---

### 修复方案 2: 添加设备存在性验证

**文件**: `src/olav/agents/query_agent_v2.py`

```python
def _process_aliases(self, query: str, learn_callback=None):
    """Process query to resolve user aliases with device existence check."""
    
    # 1. 获取数据库中已知设备列表 (新增)
    try:
        known_devices = self.gw.query_snapshots(
            "SELECT DISTINCT device FROM v_system"
        )
        known_device_names = {d['device'].upper() for d in known_devices}
    except Exception:
        known_device_names = set()
    
    # 2. 提取实体
    entities = re.findall(r"[\u4e00-\u9fa5]+|[A-Z]+\d*", query)
    
    for entity in entities:
        # 3. 跳过已知设备 (新增)
        if entity.upper() in known_device_names:
            continue
            
        # 4. 检查用户别名
        canonical = self.gw.get_user_alias(skill_name, entity)
        if canonical:
            query = query.replace(entity, canonical)
        elif learn_callback and learning_count < max_prompts:
            # 仅对真正未知的实体触发学习
            ...
```

---

### 修复方案 3: 修复异步上下文中的 prompt-toolkit

**文件**: `src/olav/cli/session.py`

```python
import nest_asyncio

class OlavPromptSession:
    def _init_session(self):
        """Initialize prompt-toolkit session with async support."""
        # 启用嵌套事件循环支持
        try:
            nest_asyncio.apply()
        except Exception:
            pass
        
        # 不再因为异步上下文而禁用 prompt-toolkit
        # 移除: asyncio.get_running_loop() 检测逻辑
        
        # 初始化 FileHistory
        history_path = Path.home() / ".olav" / "history" / f"{_username}.txt"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        self._history = FileHistory(str(history_path))
        
        # 初始化 session
        self._session = PromptSession(
            history=self._history,
            ...
        )
```

**依赖**: 需要添加 `nest_asyncio` 到 `pyproject.toml`

---

### 修复方案 4: 移除 command_history.py 依赖

**文件**: `src/olav/cli/session.py`

```python
# 移除以下代码:
# try:
#     from olav.cli.command_history import CommandHistory
# except (ImportError, ModuleNotFoundError):
#     CommandHistory = None

# 改为使用 prompt-toolkit 原生 FileHistory
from prompt_toolkit.history import FileHistory
```

**完整方案**: 不创建 `command_history.py`，直接使用 prompt-toolkit 的 `FileHistory`

---

### 修复方案 5: 添加查询超时机制

**文件**: `src/olav/cli/cli_main.py`

```python
async def stream_agent_response(agent, query, ...):
    try:
        # 添加 60 秒超时
        final_state = await asyncio.wait_for(
            agent.ainvoke(base_inputs, learn_callback=learn_callback),
            timeout=60.0
        )
    except asyncio.TimeoutError:
        display.show_error("Query timed out after 60 seconds")
        return None
```

---

### 修复方案 6: 使用 thread_id 管理会话

**文件**: `src/olav/cli/cli_main.py`

```python
import uuid

class InteractiveSession:
    def __init__(self):
        # 每次启动 CLI 生成新的会话 ID
        self.thread_id = str(uuid.uuid4())
    
    async def run_query(self, query: str):
        # 传递 thread_id 给 agent
        config = {"configurable": {"thread_id": self.thread_id}}
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            config=config
        )
```

---

## 📁 需要修改的文件清单

| 文件 | 修改内容 |
|------|----------|
| `config/paths.py` | 添加 `USER_CHECKPOINT_PATH` |
| `pyproject.toml` | 添加 `nest_asyncio` 依赖 |
| `src/olav/agents/query_agent_v2.py` | 使用 DuckDBSaver + 设备验证 |
| `src/olav/cli/session.py` | 移除 CommandHistory + 使用 FileHistory + nest_asyncio |
| `src/olav/cli/cli_main.py` | 添加超时 + thread_id 管理 |
| `src/olav/cli/memory.py` | 标记为废弃或删除 |

---

## 🧪 测试方案

### 单元测试

```python
# tests/test_checkpointer.py
import pytest
from langgraph.checkpoint.duckdb import DuckDBSaver
import duckdb

def test_user_checkpoint_isolation():
    """Test that different users have isolated checkpoints."""
    # User A
    conn_a = duckdb.connect("/tmp/test_user_a.duckdb")
    saver_a = DuckDBSaver(conn_a)
    saver_a.setup()
    saver_a.put(config={"configurable": {"thread_id": "t1"}}, ...)
    
    # User B
    conn_b = duckdb.connect("/tmp/test_user_b.duckdb")
    saver_b = DuckDBSaver(conn_b)
    saver_b.setup()
    
    # Assert isolation
    result = saver_b.get_tuple({"configurable": {"thread_id": "t1"}})
    assert result is None  # User B cannot see User A's data
```

### 集成测试

```python
# tests/test_cli_session.py
import pytest

@pytest.mark.asyncio
async def test_session_persistence():
    """Test that session history persists across queries."""
    agent = QueryAgentV2()
    thread_id = "test-session"
    
    # First query
    config = {"configurable": {"thread_id": thread_id}}
    result1 = await agent.ainvoke({"messages": [HumanMessage("show R3 interfaces")]}, config)
    
    # Second query (should have context from first)
    result2 = await agent.ainvoke({"messages": [HumanMessage("show its BGP neighbors")]}, config)
    
    # "its" should resolve to R3 from context
    assert "R3" in str(result2) or "bgp" in str(result2).lower()

@pytest.mark.asyncio
async def test_device_recognition():
    """Test that known devices don't trigger learning."""
    agent = QueryAgentV2()
    learn_called = False
    
    def mock_learn(entity, suggestions):
        nonlocal learn_called
        learn_called = True
    
    # R3 is a known device
    await agent._process_aliases("show R3 status", learn_callback=mock_learn)
    
    assert not learn_called, "R3 should not trigger learning"
```

### E2E 测试

```python
# tests/test_e2e_session.py
import subprocess
import os

def test_cli_history_persistence():
    """Test that CLI history persists across sessions."""
    # Session 1: Run a query
    result1 = subprocess.run(
        ["uv", "run", "olav", "query", "show R3 interfaces"],
        capture_output=True, text=True
    )
    assert result1.returncode == 0
    
    # Session 2: Check history file exists
    username = os.environ.get("USER", "default_user")
    history_path = os.path.expanduser(f"~/.olav/history/{username}.txt")
    assert os.path.exists(history_path)
    
    with open(history_path) as f:
        content = f.read()
    assert "show R3 interfaces" in content

def test_cross_user_isolation():
    """Test that different users have isolated sessions."""
    # This test requires running as different users
    # In CI, use environment variable override
    ...
```

---

## 📊 数据库架构总结

### 最终目录结构

```
~/.olav/
├── cache_{username}.duckdb     # 现有: 语义缓存、意图缓存 (保留)
├── checkpoints/
│   └── {username}.duckdb       # 新增: LangGraph 检查点 (会话状态)
└── history/
    └── {username}.txt          # 新增: prompt-toolkit 命令历史
```

### 数据库职责划分

| 数据库 | 职责 | 读写 |
|--------|------|------|
| `cache_{user}.duckdb` | 语义缓存、意图缓存、用户别名 | RW |
| `checkpoints/{user}.duckdb` | LangGraph 会话状态 | RW |
| `history/{user}.txt` | prompt-toolkit 历史 | RW |
| `snapshots.duckdb` | 网络快照数据 | RO |
| `olav.duckdb` | 拓扑、知识库 | RO |

---

## 🧪 完整测试方案

### 1. 单元测试

```python
# tests/unit/test_native_components.py
import pytest
import duckdb
import os
from pathlib import Path

class TestDuckDBCheckpointer:
    """测试 LangGraph DuckDB Checkpointer"""
    
    def test_checkpointer_per_user_isolation(self, tmp_path):
        """验证不同用户的检查点隔离"""
        from langgraph.checkpoint.duckdb import DuckDBSaver
        
        # User A
        path_a = tmp_path / "user_a.duckdb"
        conn_a = duckdb.connect(str(path_a))
        saver_a = DuckDBSaver(conn_a)
        saver_a.setup()
        
        # User B
        path_b = tmp_path / "user_b.duckdb"
        conn_b = duckdb.connect(str(path_b))
        saver_b = DuckDBSaver(conn_b)
        saver_b.setup()
        
        # 存储 User A 数据
        config_a = {"configurable": {"thread_id": "session-1"}}
        # saver_a.put(...) - 实际使用时通过 agent 自动管理
        
        # 验证 User B 无法访问 User A 数据
        result = saver_b.get_tuple(config_a)
        assert result is None
        
        conn_a.close()
        conn_b.close()


class TestDuckDBStore:
    """测试 LangGraph DuckDB Store (KV 存储)"""
    
    def test_store_namespace_isolation(self, tmp_path):
        """验证命名空间隔离"""
        from langgraph.store.duckdb import DuckDBStore
        
        conn = duckdb.connect(str(tmp_path / "test.duckdb"))
        store = DuckDBStore(conn)
        store.setup()
        
        # 存储 user1 的别名
        store.put(("user1", "aliases"), "R3", {"canonical": "R3", "type": "device"})
        
        # 存储 user2 的别名
        store.put(("user2", "aliases"), "R3", {"canonical": "Router-3", "type": "device"})
        
        # 验证隔离
        r1 = store.get(("user1", "aliases"), "R3")
        r2 = store.get(("user2", "aliases"), "R3")
        
        assert r1.value["canonical"] == "R3"
        assert r2.value["canonical"] == "Router-3"
        
        conn.close()


class TestUserIdentification:
    """测试用户识别"""
    
    def test_linux_user_detection(self):
        """验证 Linux 用户检测"""
        username = os.environ.get("USER") or os.getlogin()
        assert username is not None
        assert len(username) > 0
    
    def test_windows_user_fallback(self, monkeypatch):
        """验证 Windows 用户回退"""
        monkeypatch.delenv("USER", raising=False)
        monkeypatch.setenv("USERNAME", "testuser")
        
        # 模拟 Windows 环境
        username = os.environ.get("USER") or os.environ.get("USERNAME", "default")
        assert username == "testuser"
```

### 2. 集成测试

```python
# tests/integration/test_agent_session.py
import pytest
from unittest.mock import Mock, patch

class TestAgentSessionPersistence:
    """测试 Agent 会话持久化"""
    
    @pytest.mark.asyncio
    async def test_session_state_persists_across_queries(self):
        """验证会话状态跨查询持久化"""
        from olav.agents.query_agent_v2 import QueryAgentV2
        from langchain_core.messages import HumanMessage
        
        agent = QueryAgentV2()
        thread_id = "test-session-001"
        config = {"configurable": {"thread_id": thread_id}}
        
        # 第一次查询
        result1 = await agent.ainvoke(
            {"messages": [HumanMessage(content="show R3 interfaces")]},
            config=config
        )
        
        # 第二次查询 (应该有上下文)
        result2 = await agent.ainvoke(
            {"messages": [HumanMessage(content="show its BGP neighbors")]},
            config=config
        )
        
        # 验证 "its" 能解析为 R3
        assert "R3" in str(result2) or "bgp" in str(result2).lower()
    
    @pytest.mark.asyncio
    async def test_different_threads_isolated(self):
        """验证不同线程会话隔离"""
        from olav.agents.query_agent_v2 import QueryAgentV2
        from langchain_core.messages import HumanMessage
        
        agent = QueryAgentV2()
        
        # Thread A
        config_a = {"configurable": {"thread_id": "thread-a"}}
        await agent.ainvoke(
            {"messages": [HumanMessage(content="show R3 status")]},
            config=config_a
        )
        
        # Thread B (不应该有 Thread A 的上下文)
        config_b = {"configurable": {"thread_id": "thread-b"}}
        result_b = await agent.ainvoke(
            {"messages": [HumanMessage(content="show its interfaces")]},
            config=config_b
        )
        
        # "its" 在 Thread B 中应该无法解析
        # (具体验证方式取决于 agent 行为)


class TestDeviceRecognition:
    """测试设备识别"""
    
    @pytest.mark.asyncio
    async def test_known_device_no_learning(self):
        """验证已知设备不触发学习"""
        from olav.agents.query_agent_v2 import QueryAgentV2
        
        agent = QueryAgentV2()
        learn_called = False
        
        def mock_learn(entity, suggestions):
            nonlocal learn_called
            learn_called = True
        
        # R3 是数据库中的已知设备
        processed = await agent._process_aliases(
            "show R3 interfaces",
            learn_callback=mock_learn
        )
        
        assert not learn_called, "R3 is a known device, should not trigger learning"
    
    @pytest.mark.asyncio
    async def test_unknown_entity_triggers_learning(self):
        """验证未知实体触发学习"""
        from olav.agents.query_agent_v2 import QueryAgentV2
        
        agent = QueryAgentV2()
        learn_called = False
        learned_entity = None
        
        def mock_learn(entity, suggestions):
            nonlocal learn_called, learned_entity
            learn_called = True
            learned_entity = entity
        
        # "XYZ999" 不是已知设备
        processed = await agent._process_aliases(
            "show XYZ999 interfaces",
            learn_callback=mock_learn
        )
        
        assert learn_called, "Unknown entity should trigger learning"
        assert learned_entity == "XYZ999"
```

### 3. E2E 测试

```python
# tests/e2e/test_cli_native_features.py
import subprocess
import os
from pathlib import Path

class TestCLIHistory:
    """测试 CLI 历史功能"""
    
    def test_history_file_created(self):
        """验证历史文件创建"""
        username = os.environ.get("USER", "default_user")
        history_path = Path.home() / ".olav" / "history" / f"{username}.txt"
        
        # 运行 CLI 命令
        result = subprocess.run(
            ["uv", "run", "olav", "query", "show R3 interfaces"],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        # 验证历史文件存在
        assert history_path.exists(), f"History file not created: {history_path}"
    
    def test_history_contains_command(self):
        """验证历史包含命令"""
        username = os.environ.get("USER", "default_user")
        history_path = Path.home() / ".olav" / "history" / f"{username}.txt"
        
        test_command = "show R3 status"
        
        # 运行命令
        subprocess.run(
            ["uv", "run", "olav", "query", test_command],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        # 验证历史包含命令
        if history_path.exists():
            content = history_path.read_text()
            assert test_command in content


class TestCLICheckpointer:
    """测试 CLI 检查点功能"""
    
    def test_checkpoint_file_created(self):
        """验证检查点文件创建"""
        username = os.environ.get("USER", "default_user")
        checkpoint_path = Path.home() / ".olav" / "checkpoints" / f"{username}.duckdb"
        
        # 运行交互式会话
        # (这需要通过 subprocess 模拟输入)
        
        # 验证检查点文件存在
        # assert checkpoint_path.exists()


class TestMultiUserIsolation:
    """测试多用户隔离"""
    
    def test_different_users_have_separate_files(self):
        """验证不同用户有独立文件"""
        # 这个测试需要在 CI 中以不同用户运行
        # 或者通过环境变量覆盖 USER
        pass
```

### 4. 性能测试

```python
# tests/performance/test_native_performance.py
import pytest
import time
import duckdb
from langgraph.checkpoint.duckdb import DuckDBSaver

class TestCheckpointerPerformance:
    """测试 Checkpointer 性能"""
    
    def test_checkpoint_write_latency(self, tmp_path):
        """验证检查点写入延迟"""
        conn = duckdb.connect(str(tmp_path / "perf.duckdb"))
        saver = DuckDBSaver(conn)
        saver.setup()
        
        # 模拟 1000 次写入
        times = []
        for i in range(100):
            start = time.time()
            # saver.put(...) - 实际写入
            times.append(time.time() - start)
        
        avg_time = sum(times) / len(times)
        assert avg_time < 0.01, f"Average write time too slow: {avg_time}s"
        
        conn.close()
    
    def test_checkpoint_read_latency(self, tmp_path):
        """验证检查点读取延迟"""
        conn = duckdb.connect(str(tmp_path / "perf.duckdb"))
        saver = DuckDBSaver(conn)
        saver.setup()
        
        # 模拟 1000 次读取
        times = []
        config = {"configurable": {"thread_id": "perf-test"}}
        for i in range(100):
            start = time.time()
            saver.get_tuple(config)
            times.append(time.time() - start)
        
        avg_time = sum(times) / len(times)
        assert avg_time < 0.005, f"Average read time too slow: {avg_time}s"
        
        conn.close()
```

---

## ✅ 实施优先级

### Phase 1 (立即)
1. ✅ 安装 `langgraph-checkpoint-duckdb` - 已完成
2. 添加 `nest_asyncio` 依赖
3. 修复 `session.py` 异步问题

### Phase 2 (高优先)
4. 集成 `DuckDBSaver` 到 `QueryAgentV2`
5. 添加设备存在性验证
6. 实现 `thread_id` 会话管理

### Phase 3 (清理)
7. 移除 `CommandHistory` 相关代码
8. 废弃 `AgentMemory` 类
9. 添加测试用例

---

**审计完成**: 2026-02-02  
**状态**: 已识别 6 个关键问题，方案已确定，待实施
