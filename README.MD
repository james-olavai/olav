# OLAV (Omni-Layer Autonomous Verifier)

Enterprise Network Operations ChatOps Platform using LangGraph + DeepAgents.

## Agent Modes

OLAV 现支持两种可选代理架构，通过 `--agent-mode` 选择：

| Mode | 架构 | 特点 | 适用场景 |
|------|------|------|----------|
| `react` (默认) | 单一 create_deep_agent + 直接工具调用 | 扁平、低延迟、推理链清晰 | 生产 & 日常运维 |
| `legacy` | DeepAgents + 多 SubAgent 分层 | 结构化分工、历史兼容 | 回归测试/对照基准 |

切换示例：
```powershell
uv run python -m olav.main chat                         # 默认 ReAct
uv run python -m olav.main chat --agent-mode legacy     # 使用旧架构
uv run python -m olav.main chat "查询接口状态" -m react # 单次查询
```

## ReAct 架构概述

ReAct 模式使用单一 `create_deep_agent(model, tools=[...], subagents=[])`，直接暴露 8 个核心工具：
```
SuzieQ: suzieq_query, suzieq_schema_search
RAG   : search_episodic_memory, search_openconfig_schema
NetCONF/CLI: netconf_tool, cli_tool (HITL 对写操作自动中断)
NetBox: netbox_api_call, netbox_schema_search
```
关键策略：
- 漏斗式排错：先宏观 `suzieq_query` → 再微观 `netconf_tool`
- Schema-Aware：不确定表/字段/XPath 先调用 `*_schema_search`
- 降级链：NETCONF → CLI（提示无原子回滚能力）
- HITL：`netconf_tool` / `cli_tool` 写操作触发人工审批

单步简单查询示例：
```
输入: 查询接口状态
调用: suzieq_query(table="interfaces", method="summarize")
输出: 总 222 接口，91% up，类型分布...
耗时: ~16s (对比 legacy ~72s)
```

## 性能对比 (示例基准)

| Query | ReAct (s) | Legacy (s) | Speedup |
|-------|-----------|------------|---------|
| 查询接口状态 | 16.3 | 72.5 | 77.5% |

运行完整基准：
```powershell
uv run python scripts/benchmark_agents.py --mode both -n 8
Get-Content benchmark_results.md | Select-Object -First 20
```

## Quick Start

## Quick Start

```bash
# Install dependencies
uv sync --dev

# Start Docker infrastructure
docker-compose up -d opensearch postgres redis

# Initialize databases
docker-compose --profile init up olav-init

# Run CLI (ReAct 默认)
uv run python -m olav.main chat

# Use legacy mode (对照测试)
uv run python -m olav.main chat --agent-mode legacy

# Run tests
uv run pytest
```

## Architecture

| Layer | Purpose | Implementation |
|-------|---------|---------------|
| Prompt | 统一策略/安全规范 | `config/prompts/agents/root_agent_react.yaml` |
| Agent  | 推理 + 工具调用 | `create_deep_agent(subagents=[])` |
| Tools  | Schema-Aware 网络数据 & 控制 | `src/olav/tools/*.py` |
| Safety | 写操作 HITL 审批 & 审计 | Interrupt + OpenSearch Logs |
| State  | 会话与多轮推理持久化 | PostgreSQL Async Checkpointer |

核心原则：
- **Schema-Aware**：减少工具数量（SuzieQ/NetBox/YANG 动态发现）
- **漏斗式排错**：宏观 → 微观，避免盲目深入
- **最小信任**：写操作必须人工审批 (HITL)
- **可追溯性**：工具调用路径 + 结果审计

更多细节见 `DESIGN.md` 与 `docs/` 内部文档。

## 常用命令 (PowerShell)
```powershell
# 初始化（首次）
docker-compose --profile netbox up -d

# 查看健康状态
docker ps --format "table {{.Names}}\t{{.Status}}" | findstr olav

# 运行单次查询 (ReAct)
uv run python -m olav.main chat "查询接口状态"

# 基准测试
uv run python scripts/benchmark_agents.py --mode both

# 查看最近提交
git log --oneline -n 5
```

## 安全与合规
- 所有写操作工具自动进入审批等待（HITL）
- NETCONF 优先，失败后才降级 CLI 并提示风险
- 审计日志包含：时间戳、设备、操作类型、结果
- 推荐在生产启用 OpenSearch 索引生命周期管理（ILM）

## 后续路线
- 完整 100 查询基准测试覆盖
- 引入 Prompt 结果缓存减少 token
- 复杂任务早停 (early stopping) 策略
- WebUI 展示工具调用链路

---
如需更多帮助：运行 `uv run python -m olav.main chat --verbose` 查看推理与工具调用细节。
