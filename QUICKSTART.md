# OLAV 快速启动指南 (简化版)

面向首次部署，按顺序执行，避免遗漏。保持 `.env` 只存敏感变量，其它应用配置在 `config/settings.py`。

---
## 1. 安装与准备
```bash
# 安装 uv（Linux/Mac）
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows 已用 venv，可选: pip install uv

# 克隆仓库
git clone <repo-url>
cd Olav

# 安装依赖（含开发工具）
uv sync --dev

# 复制环境文件并编辑敏感变量
cp .env.example .env
# 必改：LLM_API_KEY / NETBOX_TOKEN（若使用 NetBox 集成）
```

---
## 2. 准备设备清单
编辑 `config/inventory.csv`（示例字段）：
```
name,mgmt_ip,platform,role
R1,192.168.100.101,cisco_ios,core
R2,192.168.100.102,cisco_ios,core
SW1,192.168.100.105,cisco_ios,access
```
保证列名一致，IP 可 ping。

---
## 3. 一次性整体启动（含 NetBox 闸门）
现在推荐直接启动全栈，`olav-init` 会在真正执行 ETL 前自动检测 NetBox 连接与 Token，有问题直接失败并阻止其它服务继续。
```bash
# 启动全栈（含 netbox profile）
docker-compose --profile netbox up -d
```
行为说明：
- `olav-init` 首先运行 `scripts/check_netbox.py` 校验 `NETBOX_URL` 与 `NETBOX_TOKEN`。
- 校验失败：`olav-init` 退出，`olav-app` / `suzieq` / `olav-embedder` 不会进入 healthy。
- 校验成功：继续执行 Postgres 表初始化与 Schema 索引生成，完成后写入 `data/bootstrap/init.ok` 哨兵文件。

快速查看状态：
```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | findstr init
docker logs olav-init | tail -n 60
```
常见失败原因与处理：
- 401/403：Token 不正确或权限不足 → 重新在 NetBox 创建 API Token 并更新 `.env`。
- 404 `/api/`：`NETBOX_URL` 写错（本地容器应为 `http://localhost:8080` 访问，内部互联用 `http://netbox:8080`）。
- 必需对象缺失：需在 NetBox 创建至少 1 个 Site / Device Role / Tag 后重试。

---
## 4. 验证初始化完成
初始化成功标志：`olav-init` 处于 healthy 且存在哨兵文件。
```bash
docker exec olav-init ls -l /app/data/bootstrap/init.ok
```
额外验证：
```bash
docker-compose exec postgres psql -U olav -d olav -c "\dt"
curl -s http://localhost:9200/_cat/indices?v | grep -E "schema|episodic|docs" || echo "索引后续可在扩展阶段创建"
```

---
## 5. 应用与嵌入服务日志
已在整体启动中自动拉起（依赖 `olav-init` 健康）。
```bash
docker logs -n 50 olav-app
docker logs -n 50 olav-embedder
```
快速运行时健康确认：
```bash
docker-compose exec olav-app uv run python -c "from olav.core.settings import settings;from config.settings import Paths;print('env=',settings.environment,'inventory=',Paths.INVENTORY_CSV.exists())"
```

---
## 6. 使用 OLAV 交互式对话（含 ReAct 模式）

### 6.1 启动交互式对话（推荐）
```bash
# 方案 A: 自研 CLI 对话工具（当前实现，默认 ReAct）
uv run python -m olav.main chat                # ReAct 模式（推荐）
uv run python -m olav.main chat -m legacy      # 旧 SubAgent 架构
uv run python -m olav.main chat "查询接口状态"   # 单次查询（ReAct）

# 方案 B: LangChain Studio（推荐用于开发调试）
# 1. 启动 LangGraph Agent Server
uv add langgraph-cli[inmem]
langgraph dev

# 2. 浏览器访问 Studio
# https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024

# 或使用简化命令（需在项目根目录）
uv run olav chat

# 显示工具调用与推理链（调试模式）
uv run python -m olav.main chat --verbose      # ReAct 模式日志
uv run python -m olav.main chat -m legacy --verbose
```

**方案对比**：

| 维度 | 自研 CLI (`olav chat`) | LangChain Studio |
|------|----------------------|------------------|
| **性能分析** | ❌ 无可视化工具 | ✅ **内置性能剖析**（节点耗时、LLM 延迟） |
| **调试能力** | ⚠️ 文本日志 + --verbose | ✅ **图可视化 + 断点调试** |
| **HITL 审批** | ⚠️ 需自己实现终端菜单 | ✅ **原生 UI 审批界面** |
| **用户体验** | ✅ 终端原生，快速启动 | ⚠️ 需浏览器，多一步跳转 |
| **生产部署** | ✅ 适合 SSH 远程运维 | ❌ 开发环境专用 |
| **离线使用** | ✅ 完全离线 | ⚠️ 需 LangSmith 连接（可设 `LANGSMITH_TRACING=false`） |
| **代码侵入性** | ⚠️ 需实现 CLI UI | ✅ **零代码改动** |

**推荐策略**：
- **开发调试阶段**：使用 **LangChain Studio**
  - ✅ 可视化性能瓶颈（LLM 调用、Checkpointer、SubAgent 委托）
  - ✅ 图形化调试工作流（查看 LangGraph 执行路径）
  - ✅ 内置 HITL 审批界面（无需自己实现终端菜单）
  - ✅ 实时监控 Thread 状态
- **生产运维阶段**：保留 **自研 CLI**
  - ✅ SSH 远程访问友好
  - ✅ 脚本自动化集成
  - ✅ 无需浏览器依赖

**性能分析优势**（Studio 特有）：
- **节点耗时追踪**：查看每个 SubAgent 的执行时间
- **LLM 调用统计**：Token 使用、API 延迟、并发情况
- **Checkpointer 写入监控**：识别频繁的 `aget_tuple()` / `aput()` 调用
- **内存使用分析**：State 大小、消息历史长度
- **瓶颈可视化**：红色高亮慢速节点

**实现建议**：
1. **立即启用 Studio**（用于性能排查）：
   ```bash
   # 安装 LangGraph CLI
   uv add langgraph-cli[inmem]
   
   # 启动开发服务器
   langgraph dev --debug-port 5678
   
   # 访问 Studio
   # https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
   ```

2. **保留自研 CLI**（用于生产运维）：
   - 添加简化的 Y/N 菜单（HITL）
   - 添加性能埋点（输出到日志）
   - 添加 `--profile` 参数（调用 cProfile）

3. **双轨并行**：
   - 开发环境：`langgraph dev` + Studio UI
   - 生产环境：`uv run olav chat` + 审计日志

**当前重点：验证并巩固 ReAct 性能收益**

首轮基准（接口状态查询）：`legacy ≈ 72.5s` → `react ≈ 16.3s`（↓ 77.5%）。
来源：`scripts/benchmark_agents.py` 初始运行结果。

**ReAct 为什么更快**：
- 单一推理循环：移除多层 SubAgent 委托和上下文裁剪
- Prompt 更短：减少 token 处理与系统指令注入
- 工具直接调用：无额外中间态翻译层

**快速自测基准**：
```powershell
# 运行 3 次对比（接口 / BGP / 路由 概要）
uv run python scripts/benchmark_agents.py --modes react legacy --queries basic

# 导出 markdown 报告（默认写入 benchmark_report.md）
uv run python scripts/benchmark_agents.py --export md

# 仅测 ReAct（扩展查询集）
uv run python scripts/benchmark_agents.py --modes react --queries extended
```

生成的表格包含：`query` | `mode` | `latency_sec` | `tokens_in/out`（如启用统计）| `tool_calls`。

**建议判定标准**：
- 简单查询（单表 summarize）：`react < 20s`，`legacy > 60s` 即通过
- 中等查询（多设备聚合）：`react < 35s`
- 复合诊断（多工具链路）：`react < 50s`（需要后续运行扩展集）

**发现超标怎么办**：
1. 加 `--verbose` 查看是否出现不必要的重复工具调用
2. 检查 Prompt 是否被意外扩展（新增大段上下文）
3. 检查 Parquet 是否落入 raw 而非 coalesced 分区
4. 查看 PostgreSQL Checkpointer 写入次数是否异常（> 4 次）

**何时仍用 Legacy**：
- 需要验证旧复杂多阶段推理行为是否保留
- 想回归多 SubAgent 分工的调试视角
（否则日常一律使用 `react`）

**后续优化路线**（按优先级）：
1. 提前终止：ReAct 推理到首个可执行工具计划即可调用，不等待额外思考轮
2. Tool result 精简：限制返回列集合，缩短后续思考输入长度
3. Prompt 缓存：静态系统指令固定，可复用编译后的 embedding（视模型能力）
4. Token 削减：移除低价值注释段落；保留安全与 Schema 指令

> Tip: 运行完基准后，可将结果追加到 README Performance 表中，形成趋势跟踪。

**交互模式功能**：
- 持续对话：无需每次重新启动，支持上下文记忆
- 内置命令：
  - `help` - 显示可用命令
  - `status` - 查看系统状态
  - `clear` - 清屏
  - `exit` / `quit` / `q` - 退出对话
- **会话持久化**：所有对话通过 PostgreSQL Checkpointer 保存，可随时恢复

**示例对话**：
```
OLAV v1.0.0 - Network Operations ChatOps
LLM: openai (gpt-4-turbo)
HITL: Enabled

Type 'exit' or 'quit' to end session
Type 'help' for available commands

Session ID: cli-interactive-1732215600

You: 查询设备 R1 的接口状态

╭─ OLAV ────────────────────────────────────────╮
│ 正在查询设备 R1 的接口状态...                     │
│                                                │
│ Interface    IP-Address    Status    Protocol │
│ Gi0/0        10.1.1.1      up        up       │
│ Gi0/1        10.1.2.1      up        up       │
│ Gi0/2        unassigned    down      down     │
╰────────────────────────────────────────────────╯

You: 创建一台新设备在 NetBox

╭─ OLAV ────────────────────────────────────────╮
│ ⚠️ 需要人工审批                                 │
│                                                │
│ 操作: 创建设备                                  │
│ 站点: DC1                                      │
│ 设备名: R10                                    │
│                                                │
│ 请选择: [approve / edit / reject]              │
╰────────────────────────────────────────────────╯

You: exit
Goodbye!
```

### 6.2 单次查询模式（快速查询）
```bash
# 执行单个查询后退出
uv run python -m olav.main chat "查询设备 R1 的接口状态"

# 恢复之前的会话继续对话
uv run python -m olav.main chat --thread-id "cli-interactive-1732215600"
```

### 6.3 其他命令
```bash
# 查看版本信息
uv run python -m olav.main version

# 占位 API 服务（尚未集成 FastAPI）
uv run python -m olav.main serve
```

**Windows 用户注意**：
- OLAV 已自动配置 `SelectorEventLoop` 以兼容 psycopg 异步操作
- 如遇到 `ProactorEventLoop` 错误，请参考 `docs/CHECKPOINTER_SETUP.md`

---
## 7. 开发工作流
```bash
# 代码格式化
uv run ruff format src/ tests/

# 代码检查与自动修复
uv run ruff check src/ tests/ --fix

# 类型检查
uv run mypy src/ --strict

# 运行测试
uv run pytest -v

# 测试覆盖率
uv run pytest --cov=src/olav --cov-report=html
```
添加依赖：
```bash
uv add langchain-openai
uv add --dev pytest-asyncio
```

---
## 8. 下一步建设建议
1. NetBox 自动基线对齐脚本（inventory.csv ↔ NetBox 差异报告）
2. SuzieQ 采集与查询验证（填充 parquet 真实数据）
3. FastAPI /health /chat /devices 路由替换占位 serve 循环
4. 嵌入流水线：文档分块 + 向量索引（`olav-docs` / `olav-episodic-memory`）
5. HITL 写操作审批与审计索引（已实现 NetBox Agent HITL，参考 `docs/NETBOX_AGENT_HITL.md`）
6. 初始化重试与指数回退（NetBox 短暂不可用场景）
7. 状态查询命令：`uv run python -m olav.main status`（显示各哨兵与索引）

**已完成功能**：
- ✅ 交互式 CLI 对话界面（支持上下文记忆、会话恢复）
- ✅ 优雅的 UI 界面（思考过程可视化、工具调用追踪）
- ✅ LLM 流式输出（实时显示推理过程）
- ✅ NetBox Agent HITL 审批机制（写操作需人工批准）
- ✅ NetBox 工具集成（设备查询、API 调用、批量导入）
- ✅ 自主执行能力（Agent 主动规划多步操作）
- ✅ PostgreSQL Checkpointer 状态持久化
- ✅ Windows 平台异步兼容性修复
- ✅ CLI Agent 与 NetBox Agent 集成
- ✅ 日志分层管理（--verbose 调试模式）
- ✅ NAPALM 驱动修复（统一使用 ios 平台）

更详细架构说明参见 `README.MD` 与 `docs/` 目录。

**重要文档**:
- `docs/CHECKPOINTER_SETUP.md` - PostgreSQL Checkpointer 配置指南
- `docs/NETBOX_AGENT_HITL.md` - NetBox Agent HITL 审批流程详解
- `docs/CHECKPOINTER_FIX_SUMMARY.md` - Checkpointer 问题解决方案总结

---
## 9. 已知问题与限制

### 9.1 OpenRouter/DeepSeek 与 TodoListMiddleware 不兼容

**问题描述**:  
使用 OpenRouter + DeepSeek模型 时,`TodoListMiddleware` 会导致工具调用验证错误:
```
ValidationError: 1 validation error for AIMessage
invalid_tool_calls.0.args
  Input should be a valid string [type=string_type, input_value={'todos': [...]}, input_type=dict]
```

**根本原因**:  
- OpenRouter/DeepSeek 返回的 `tool_calls[].function.arguments` 是 JSON **字符串** 而非字典
- LangChain 的 `TodoListMiddleware` 在解析这些工具调用时产生格式不正确的 `invalid_tool_calls`
- `InvalidToolCall.args` 字段必须是 `str`,但中间件生成的是 `dict`

**临时解决方案** (已应用):  
在 `src/olav/agents/simple_agent.py` 中禁用了 `TodoListMiddleware`:
```python
middleware=[], # TODO: Re-enable TodoListMiddleware after switching to native OpenAI
```

**长期解决方案** (推荐选其一):

1. **切换到原生 OpenAI API** (推荐)
   ```bash
   # .env 配置
   LLM_PROVIDER=openai
   LLM_API_KEY=sk-...
   LLM_MODEL_NAME=gpt-4-turbo
   ```
   原生 OpenAI API 返回的工具调用格式完全兼容 LangChain。

2. **使用本地 Ollama**
   ```bash
   # 启动 Ollama 服务
   ollama serve
   ollama pull qwen2.5:32b
   
   # .env 配置
   LLM_PROVIDER=ollama
   LLM_MODEL_NAME=qwen2.5:32b
   ```

3. **保持 OpenRouter 但接受无 TodoList 功能**  
   当前配置已自动修复工具调用 JSON 解析问题 (`src/olav/core/llm.py` 中的 `FixedChatOpenAI`),  
   但 TodoListMiddleware 仍然不可用。适用于不需要自动任务分解的场景。

**影响范围**:
- ❌ 无法使用自动任务列表分解功能
- ✅ 其他工具调用 (NETCONF/CLI) 正常工作
- ✅ 基础对话和查询功能不受影响

**追踪Issue**: https://github.com/your-org/olav/issues/XXX (TODO: 创建实际issue)

---
### 9.2 Windows 平台 ProactorEventLoop 问题

**问题**: `psycopg` 异步模式在 Windows 默认事件循环下报错。

**解决方案** (已应用):  
在所有异步脚本开头添加:
```python
import sys
import asyncio

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

参考: `docs/CHECKPOINTER_SETUP.md` 第 2 节。

