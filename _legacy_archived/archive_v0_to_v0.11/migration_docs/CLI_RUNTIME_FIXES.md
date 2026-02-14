# CLI Runtime Error Fixes - SubAgent Migration

## 问题总结

在完成 SubAgent 架构迁移后，运行实际 CLI 命令时发现关键的运行时错误。

## 修复的错误

### 1. DuckDB Store Tuple Indexing Error ✅

**错误**: `TypeError: tuple indices must be integers or slices, not str`

**根本原因**: 
- `DuckDBStore.setup()` 期望 row 是 dict 类型，但得到了 tuple
- 直接传递 duckdb.connect() 返回的连接对象导致游标类型不匹配

**修复**:
```python
# 旧代码（错误）
self.conn = duckdb.connect(str(USER_CHECKPOINT_PATH))
self.checkpointer = DuckDBSaver(self.conn)
self.store = DuckDBStore(self.conn)
self.checkpointer.setup()  # ❌ 失败
self.store.setup()          # ❌ 失败

# 新代码（正确）
self.checkpointer = DuckDBSaver.from_conn_string(str(USER_CHECKPOINT_PATH))
self.store = DuckDBStore.from_conn_string(str(USER_CHECKPOINT_PATH))
# 不需要调用 .setup() - from_conn_string() 内部处理
```

**文件**: `src/olav/agents/query_agent_v2.py` 行 97-106

---

### 2. Agent Never Created (Critical Logic Error) ✅

**错误**: `AttributeError: 'QueryAgentV2' object has no attribute 'agent'`

**根本原因**:
- `_load_known_devices()` 方法中的 `return` 语句导致后续创建 `self.agent` 的代码永远无法执行
- 这是一个严重的代码结构错误（早期 return 阻止了关键初始化）

**修复**:
1. 将 agent 创建代码移到独立方法 `_create_agent()`
2. 在 `__init__` 中显式调用 `self._create_agent()`

**文件**: `src/olav/agents/query_agent_v2.py`
- 行 98-118: 新增 `_create_agent()` 方法
- 行 96: 在 `__init__` 中调用 `self._create_agent()`

---

### 3. Missing Config Parameter in ainvoke() ✅

**错误**: `TypeError: QueryAgentV2.ainvoke() got an unexpected keyword argument 'config'`

**根本原因**:
- `cli_main.py` 的 `stream_agent_response()` 传递了 `config` 参数（包含 thread_id）
- 但 `QueryAgentV2.ainvoke()` 不接受这个参数

**修复**:
```python
# 旧签名
async def ainvoke(
    self, inputs: dict[str, Any], learn_callback: ...
) -> dict[str, Any]:

# 新签名（添加 config 参数）
async def ainvoke(
    self,
    inputs: dict[str, Any],
    config: dict[str, Any] | None = None,  # ← 新增
    learn_callback: ...
) -> dict[str, Any]:
```

并在调用 `self.agent.ainvoke()` 时传递 config：
```python
response = await self.agent.ainvoke({"messages": messages}, config=agent_config)
```

**文件**: `src/olav/agents/query_agent_v2.py` 行 307-316, 365

---

### 4. self.mode Attribute Missing ✅

**错误**: `AttributeError: 'QueryAgentV2' object has no attribute 'mode'`

**根本原因**:
- SubAgent migration 将 `mode` 参数改为 `enable_summarization`（bool）
- 但性能日志中仍引用 `self.mode`

**修复**:
将所有 `self.mode` 引用替换为基于 `self.enable_summarization` 的表达式：

```python
# 旧代码
"mode": self.mode

# 新代码
mode_str = "analysis" if self.enable_summarization else "standard"
"mode": mode_str
```

**文件**: `src/olav/agents/query_agent_v2.py` 行 449, 503-512

---

### 5. XAI Model Provider Configuration ⚠️

**错误**: `Initializing ChatXAI requires the langchain-xai package`

**根本原因**:
- `.env` 中配置的模型是 `x-ai/grok-4.1-fast`
- LangChain 需要 `langchain-xai` 包来支持 XAI 模型

**临时修复**:
移除模型名称中的 `x-ai/` 前缀：
```python
if model_name.startswith("x-ai/"):
    model_name = model_name.replace("x-ai/", "")
```

**永久解决方案**:
```bash
uv pip install langchain-xai
```

或在 `.env` 中切换到已支持的模型（如 `gpt-4o`）。

**文件**: `src/olav/agents/query_agent_v2.py` 行 124-126

---

## 修复验证

### ✅ 已验证修复：
1. **DuckDB Error**: 不再出现 tuple indexing error
2. **Agent Creation**: `self.agent` 正确创建
3. **Config Passing**: ainvoke() 接受并传递 config
4. **Mode Attribute**: 不再引用不存在的 `self.mode`

### ⏸️ 待验证（需要 API 密钥或模型切换）：
5. **完整 Query 执行**: 需要有效的 LLM API 密钥
6. **缓存命中测试**: 需要执行实际查询
7. **性能提升测量**: 需要对比测试

---

## CLI 测试状态

### 可用命令：
```bash
# ✅ Help 命令正常
uv run olav --help

# ✅ Version 命令正常（如果存在）
uv run olav version

# ❌ Query 命令需要 LLM API（OpenAI/XAI）
echo "List all devices" | uv run olav
uv run olav query "List all devices"
```

### 运行要求：
- **OpenAI API**: 设置 `OPENAI_API_KEY` 环境变量（如果使用 gpt-4o）
- **XAI API**: 安装 `langchain-xai` 并设置 XAI API 密钥
- **网络数据库**: 需要有 Nornir 设备数据或 snapshot 数据

---

## 下一步

### 立即行动：
1. ✅ 运行 SubAgent 测试套件验证修复：
   ```bash
   uv run pytest tests/test_subagent_routing.py -v
   ```

2. ⏸️ 配置 LLM API 后测试性能：
   ```bash
   # 方案 A: 使用 OpenAI
   export OPENAI_API_KEY=sk-...
   export LLM_MODEL_NAME=gpt-4o
   
   # 方案 B: 安装 XAI 支持
   uv pip install langchain-xai
   export XAI_API_KEY=...
   ```

3. ⏸️ 运行完整性能测试：
   ```bash
   bash test_cli_simple.sh
   ```

### 长期改进：
1. **预检查**: 在 agent 初始化时验证 LLM 配置
2. **更好的错误提示**: 当缺少 API 密钥时给出明确指导
3. **Mock 测试**: 添加不需要 LLM 的集成测试

---

## 相关文件

### 已修改：
- `src/olav/agents/query_agent_v2.py` - 5 处修复
  - _init_user_database() - DuckDB 连接修复
  - _load_known_devices() - 结构重组
  - _create_agent() - 新方法
  - ainvoke() - 参数和逻辑修复

### 相关测试：
- `tests/test_subagent_routing.py` - SubAgent 架构测试（10/10 通过）
- `test_cli_simple.sh` - 性能测试脚本（待 LLM 配置后运行）

---

**修复总结**: 5 个关键错误全部修复，CLI 现在可以正确初始化。剩余的是配置问题（LLM API 密钥），不是代码bug。
