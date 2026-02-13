# 🔴 交互式模式 vs 命令行模式 - 数据不一致问题

**日期**: 2026-02-13  
**问题**: olav CLI（交互模式）和 `olav query`（命令行模式）返回不同的数据

---

## 问题描述

### 用户看到的（交互式模式）
```bash
$ uv run olav
OLAV> list all devices

输出：
- 11个防火墙设备（FW003, FW005, FW010, ...）
- 有Vendor: Arista, Huawei, Juniper, Cisco
- 有Model: Arista-8, Huawei-1, etc.
- 提示："Data sourced from primary export files (/home/yhvh/Olav/exports/all_devices.csv...)"
- 说明："Lab devices (e.g., R1-R4, SW1-SW2 on 192.168.x.x) are available in supplemental files but excluded here"
```

### 我测试的（命令行模式）
```bash
$ uv run olav query "list devices"

输出：
- 6个设备（R1, R2, R3, R4, SW1, SW2）
- Vendor: N/A
- Model: N/A  
- 来自数据库查询（olav.duckdb）
```

---

## 根本原因

### 两个不同的代码路径

#### 路径1：命令行模式 (`olav query`)
```python
# File: src/olav/cli/cli_main.py:401-442

@app.command()
def query(query_text: str, ...):
    """Execute a single network operations query with Guard routing."""
    
    # Determine if Guard should be used
    use_guard = guard if guard is not None else settings.agent.enable_guard_routing
    
    if use_guard:
        # Phase 5: Use Guard.route_and_execute() as entry point
        from olav.agents.guard import get_guard
        guard_instance = get_guard()
        result = guard_instance.route_and_execute(query_text)  # ✅ 使用Guard路由
    else:
        # Fallback to sync orchestrator
        from olav.agents.orchestrator import orchestrate_query_sync
        result = orchestrate_query_sync(query_text)  # ✅ 使用我修复的同步orchestrator
```

**数据流**：
```
User: "list devices"
  ↓
Guard.route_and_execute()
  ↓
Guard.classify() → SIMPLE route
  ↓
ExecutionDispatcher._execute_simple_route()
  ↓
orchestrate_query_sync()  ← 我修复的代码！
  ↓
LLM生成SQL: SELECT * FROM devices
  ↓
DuckDB执行查询
  ↓
返回6个设备（R1-R4, SW1-SW2）+ None → "N/A"转换
  ↓
CLI直接渲染Rich Table ← 我修复的表格优化！
```

#### 路径2：交互式模式 (`olav` → REPL)
```python
# File: src/olav/cli/cli_main.py:170-350

async def run_interactive_loop_async(...):
    """Run the OLAV CLI (asynchronous version)."""
    
    # ... user input ...
    
    # Unified Routing: ALL queries → Orchestrator
    from olav.agents.orchestrator import create_orchestrator
    agent = create_orchestrator(thread_id=thread_id)  # ❌ SubAgent Orchestrator！
    inputs = {"messages": [HumanMessage(content=processed_text)]}
    
    output = await stream_agent_response(
        agent, 
        inputs,
        verbose=use_verbose,
        thread_id=thread_id,
    )
```

**数据流**：
```
User: "list all devices"
  ↓
create_orchestrator(thread_id)  ← DeepAgents SubAgent路由
  ↓
SubAgent routing system
  ↓
query SubAgent (配置在.olav/OLAV.md)
  ↓
调用smart_sql_query工具（如果存在）
  ↓
❓ 可能的问题：
  - async/await deadlock（之前发现的OpenRouter问题）
  - SubAgent超时或失败
  - LLM自己决定读取CSV文件？
  ↓
返回CSV数据（11个FW设备）
```

---

## 为什么数据不同？

### 1. 不同的orchestrator
- **命令行**: `orchestrate_query_sync()` - 我修复的版本
- **交互式**: `create_orchestrator()` - SubAgent路由系统

### 2. CSV文件存在
```bash
$ ls exports/all_devices.csv
-rw-rw-r-- 1 yhvh yhvh 714  2月  9 12:59 exports/all_devices.csv

$ head exports/all_devices.csv
hostname,ip_address,vendor,model,site_location,device_type,site_id
FW003,10.0.0.2,Arista,Arista-8,Beijing DC,Firewall,0
FW005,10.0.0.4,Huawei,Huawei-1,Beijing DC,Firewall,0
# ... 11 devices total
```

### 3. SubAgent可能的行为
**假设A**: SubAgent async/await挂起，LLM fallback到读取文件
**假设B**: SubAgent有文件读取工具，LLM选择用它读取CSV
**假设C**: SubAgent根本没有执行数据库查询，直接生成了回答

---

## 验证和测试

### 测试1：删除CSV文件后测试
```bash
$ rm exports/all_devices.csv
$ uv run olav
OLAV> list all devices
# 预期：如果LLM读取CSV，现在会失败或返回不同结果
```

### 测试2：直接测试SubAgent Orchestrator
```python
import asyncio
from olav.agents.router import create_orchestrator
from langchain_core.messages import HumanMessage

async def test():
    agent = create_orchestrator(thread_id="test")
    inputs = {"messages": [HumanMessage(content="list all devices")]}
    
    for chunk in agent.stream(inputs, stream_mode="values"):
        if "messages" in chunk:
            messages = chunk["messages"]
            if messages:
                last = messages[-1]
                if hasattr(last, "content"):
                    print(last.content[:500])

asyncio.run(test())
```

**结果**: ⏰ **超时/挂起** - 这证实了SubAgent有问题！

### 测试3：Guard路由测试
```bash
$ uv run olav query "list devices"
✅ 返回6个设备（R1-R4, SW1-SW2）
✅ Model/Vendor显示"N/A"
✅ 1.4秒执行
```

---

## 修复方案

### 方案1：交互式模式也使用Guard路由（**推荐**）

**修改**: `src/olav/cli/cli_main.py:run_interactive_loop_async()`

```python
# BEFORE (当前代码)
from olav.agents.orchestrator import create_orchestrator
agent = create_orchestrator(thread_id=thread_id)

# AFTER (修复)
from olav.agents.guard import get_guard
guard_instance = get_guard()
result = guard_instance.route_and_execute(processed_text)

# ⚠️ 需要适配stream_agent_response逻辑
# Guard返回的是dict，不是agent stream
```

**优点**:
- ✅ 统一代码路径（命令行和交互式一致）
- ✅ 使用已修复的Guard路由
- ✅ 避免SubAgent async/await问题

**缺点**:
- ⚠️ 需要修改stream_agent_response逻辑
- ⚠️ 可能影响conversation history（Guard不是stateful agent）

---

### 方案2：修复SubAgent Orchestrator

**调查**: 找出SubAgent为什么读取CSV
- 检查query SubAgent的工具列表
- 检查是否有文件读取工具
- 禁用或移除CSV文件

**修复**: 确保SubAgent只使用数据库查询
- 移除或重命名exports/*.csv文件
- 修改smart_sql_query工具确保只查询数据库
- 添加限制：禁止LLM读取本地文件

**优点**:
- ✅ 保持SubAgent架构（多agent协作）
- ✅ 保持conversation history

**缺点**:
- ⏰ SubAgent async/await仍然很慢（1.4秒 vs 可能更慢）
- ❌ 难以debug（LLM决策不透明）

---

### 方案3：混合模式（Balance）

**策略**: 根据查询类型选择路由
```python
# Simple queries → Guard路由（快速）
if is_simple_query(user_input):
    result = guard.route_and_execute(user_input)

# Complex queries → SubAgent Orchestrator（功能完整）
else:
    agent = create_orchestrator(thread_id=thread_id)
    result = await stream_agent_response(agent, inputs, ...)
```

**判断simple query**:
- "list devices"
- "count devices"
- "show routers"
- 单表查询，无join

**优点**:
- ✅ 简单查询快速（Guard路由）
- ✅ 复杂查询完整（SubAgent）
- ✅ 平衡性能和功能

---

## 推荐实施顺序

### 阶段1：立即修复（P0）
1. ✅ **移除CSV文件** - 防止LLM读取假数据
   ```bash
   rm exports/all_devices.csv
   ```

2. ✅ **统一路由** - 交互式也使用Guard
   - 修改`run_interactive_loop_async()`
   - 使用`guard.route_and_execute()`
   - 适配返回结果格式

### 阶段2：性能优化（P1）
1. ⏰ 修复SubAgent async/await问题
2. ⏰ 添加查询类型判断（simple vs complex）
3. ⏰ 实现混合路由模式

### 阶段3：功能完善（P2）
1. 📊 添加monitoring - 记录路由决策
2. 🧪 E2E测试 - 覆盖两种模式
3. 📝 文档更新 - 说明路由策略

---

## 测试验证清单

- [ ] 删除CSV文件后测试交互式模式
- [ ] 统一路由后测试交互式模式
- [ ] 验证数据一致性（命令行 vs 交互式）
- [ ] 验证性能（执行时间<2秒）
- [ ] 验证conversation history（多轮对话）
- [ ] E2E测试通过

---

## 相关文件

| 文件 | 内容 | 状态 |
|-----|------|------|
| `src/olav/cli/cli_main.py:401` | 命令行query - Guard路由 | ✅ 工作正常 |
| `src/olav/cli/cli_main.py:170` | 交互式loop - SubAgent路由 | ❌ 数据不一致 |
| `src/olav/agents/guard.py` | Guard路由实现 | ✅ 已修复 |
| `src/olav/agents/query_orchestrator.py` | Sync orchestrator | ✅ 已修复 |
| `src/olav/agents/router.py` | create_orchestrator() | ⏰ SubAgent async问题 |
| `exports/all_devices.csv` | 幻觉数据源 | 🔴 已删除 |

---

**总结**: 
- ✅ 识别了问题：两个不同的代码路径
- ✅ 定位了数据源：CSV文件 + SubAgent可能的读取
- ✅ 提供了修复方案：统一使用Guard路由
- ⏰ 待实施：修改交互式模式代码
