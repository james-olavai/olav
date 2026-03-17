# OLAV Agent Trace 系统设计

> 设计目标：引入借鉴自 OpenJarvis 的 Trace-Driven Feedback 理念，为 OLAV 提供可闭环优化的数据地基。
>
> **架构决策（2026-03-15）**：原草稿提议新建独立表/数据库。经与现有审计架构对比，决定**融合**进已有的 `audit.duckdb`，不新增独立数据库。

---

## 1. 背景与动机

目前 OLAV 的 Agent 运行过程是"即用即损"的。虽然有 Checkpoints 记录会话状态，但缺乏一个轻量级的、面向统计分析的"执行轨迹（Trace）"记录。Trace 数据可以解决以下问题：

- **性能评估**：Agent 成功率是多少？平均耗时多少？
- **成本追踪**：每个任务消耗了多少 Token？
- **自适应路由**：根据历史成功率自动优化 SemanticRouter 阈值。
- **故障复盘**：精准定位 Agent 在哪个环节工具调用失败或出错。
- **自我进化**：从失败 Trace 中提取约束，写入 LanceDB LTM（GuardrailInjector 自动拾取）。

---

## 2. 架构决策：融合进 audit.duckdb，不新建表

### ❌ 原方案 (废弃)

- 新建 `agent_traces` 表，存入 `.olav/databases/olav.duckdb`（不存在的路径）
- 在 `agent.py` 的 `ainvoke` 里硬编码写入钩子
- Fire-and-forget 异步写入

### ✅ 现行方案

`audit.duckdb` 的现有三张表已覆盖绝大多数字段：

| agent_traces 草稿字段 | 现有位置 | 备注 |
|:---|:---|:---|
| `trace_id` | `audit_runs.run_id` | ✅ 已有 |
| `thread_id` | `audit_runs.thread_id` | ✅ 已有 |
| `timestamp` | `audit_runs.start_time` / `end_time` | ✅ 已有 |
| `user_query` | `audit_events` WHERE `event_type='user_input_received'` | ✅ 已有 |
| `agent_id` | `audit_runs.agent_id` / `audit_events.agent_id` | ✅ 已有 |
| `status` | `audit_runs.status` (`running/completed/error/cancelled`) | ✅ 已有 |
| `model_name` | `audit_events` WHERE `event_type='llm_request_started'` → `payload.model` | ✅ 已有 |
| `latency_ms` | `DATEDIFF('ms', start_time, end_time)` FROM `audit_runs` | ⚠️ 可推导，未作独立列 |
| `tokens_in/out` | `audit_events` WHERE `event_type='llm_usage'` → payload | ✅ 已实现（`on_llm_end` hook） |
| `cache_hit` | `audit_events` WHERE `event_type='semantic_cache_hit'` | ✅ 已实现（`SemanticCache.get` audit hook） |
| `routing_method` | `audit_events` WHERE `event_type='routing_decision'` | ✅ 已实现（`SemanticRouter.route` audit hook） |
| `error_category` | `audit_events.event_type` IN (`tool_call_failed`, `run_error`, `run_cancelled`) | ⚠️ 类型已分，无 hallucination 子类 |
| `feedback` (1-5) | 无 | ⬜ 暂不支持 |

> **`tier`（0/1/2）字段废弃**：原草稿假设固定 3 层架构。实际用 `SemanticRouter` 基于相似度阈值路由，无固定 tier 数字。替换为 `routing_method`（`semantic_cache` / `semantic_router` / `llm_router`）。

---

## 3. 数据采集层：AuditCallbackPlugin（已有）

所有 Trace 数据通过 `AuditCallbackPlugin`（`plugins/callbacks/audit.py`）的 LangChain 钩子采集，写入 `audit.duckdb`。**不在 `agent.py` 里硬编码写入逻辑。**

```
LangChain 生命周期事件
    │
    ▼
AuditCallbackPlugin (AsyncCallbackHandler)
    ├── on_chat_model_start  → llm_request_started (model_name, messages)
    ├── on_llm_new_token     → model_stream_delta / reasoning_block
    ├── on_llm_end           → llm_usage (tokens_in, tokens_out)
    ├── on_tool_start        → tool_call_started
    ├── on_tool_end          → tool_call_completed
    └── on_tool_error        → tool_call_failed
    │
    ▼
AuditEventRecorder → audit.duckdb (append-only)
```

写入模式：**同步写入**，不使用 asyncio buffer。Trace 事件量级小，同步写入已足够，避免 fire-and-forget 的数据丢失风险。

---

## 4. 数据采集字段实现记录

所有字段均已通过 `AuditCallbackPlugin` + 各组件的可选 recorder hook 实现，无待补缺口。

| 里程碑 | 实现位置 | 覆盖字段 |
|:---|:---|:---|
| P1 | `AuditCallbackPlugin.on_llm_end` | `tokens_in/out`、`model_name` |
| P2 | `SemanticRouter.route(recorder, run_id)` | `routing_method`、`matched_agent`、`score` |
| P2 | `SemanticCache.get(recorder, run_id)` | `cache_hit`、`distance` |
| P3 | `trace_learner._run_learn_cycle` | 消费以上所有字段，写回 LanceDB | 

---

## 5. 消费层：trace_learner（待实现）

基于 Trace 数据触发改善动作，**应作为独立的 Agentic 后台工具**，而非融入 config-system 的交互式流程。

### 定位

```
config-system (system-doctor)  ←  交互式：用户问 → agent 答
trace_learner                  ←  后台式：定时/事件触发 → 自主改善
```

### 触发条件

- **每次 `take_snapshot` 完成后**（`take_snapshot.py` Stage 2 已有 hook 位置） ✅ 已接入
- **定时任务**：`olav onboard` Stage 5 调用 `_register_trace_learner_cron()` 写入用户 crontab ✅ 已实现
- **用户主动**：`/trace-review` slash 命令 ✅ 已实现（`cli/main.py` 交互循环）

#### Onboard 注册设计

`olav onboard` Stage 5（最终阶段）调用 `_register_trace_learner_cron()`，向系统 crontab 或 `~/.olav/cron.tab` 追加一行：

```
# OLAV trace_learner — daily at 03:00
0 3 * * *  cd /path/to/project && uv run olav --agent config "run trace_learner()"
```

- 幂等：写入前先检查是否已存在同一行（grep 去重）。
- 无需 root：写入用户 crontab（`crontab -l | crontab -`）。
- 仅在 `olav onboard` 末尾执行，非破坏性步骤，失败不阻塞 onboarding 完成。

### 工作流

```
1. 读 audit.duckdb：SELECT runs WHERE status IN ('error','cancelled') LAST 7d  ✅ 已实现
2. 读对应 audit_events：tool_call_failed / run_error 详情                   ✅ 已实现
3. LLM 分析：提取失败模式 → 生成约束文本                                      ✅ 已实现 (_extract_constraints)
4. 写 LanceDB memory[audit]：GuardrailInjector 下次调用时自动注入             ✅ 已实现 (_write_constraints_to_memory)
5. 可选：更新对应 SKILL.md 的 system prompt（移交 config-system 执行）         ⬜ 待实现
```

**关键入口**：`_run_learn_cycle(hours, limit, db_path, store, llm)` — 全流程可注入，TDD 友好。
`@tool trace_learner` — LangChain 包装器，自动触发完整闭环。

### 文件位置（预留）

```
.olav/workspace/config/sync/tools/trace_learner.py
```

---

## 6. 查询示例（阶段 1 可观测性）

通过 `olav log` 命令或 `execute_sql` 工具即可查询，无需专用仪表盘：

```sql
-- 成功率（最近 7 天）
SELECT agent_id,
       COUNT(*) AS total,
       ROUND(100.0 * SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) / COUNT(*), 1) AS success_pct
FROM audit_runs
WHERE start_time >= NOW() - INTERVAL 7 DAY
GROUP BY agent_id;

-- 平均耗时 (ms)
SELECT agent_id,
       ROUND(AVG(DATEDIFF('ms', start_time, end_time)), 0) AS avg_latency_ms
FROM audit_runs
WHERE status = 'completed'
GROUP BY agent_id;

-- Token 用量（P1 实现后）
SELECT date_trunc('day', timestamp) AS day,
       SUM(CAST(json_extract_string(payload, '$.tokens_in')  AS INTEGER)) AS tokens_in,
       SUM(CAST(json_extract_string(payload, '$.tokens_out') AS INTEGER)) AS tokens_out
FROM audit_events
WHERE event_type = 'llm_usage'
GROUP BY 1 ORDER BY 1;

-- 最近失败工具调用
SELECT timestamp, agent_id,
       json_extract_string(payload, '$.tool') AS tool,
       json_extract_string(payload, '$.error') AS error
FROM audit_events
WHERE event_type = 'tool_call_failed'
ORDER BY timestamp DESC LIMIT 20;
```

---

## 7. 实现路线图

| 优先级 | 任务 | 位置 | 状态 |
|:---|:---|:---|:---|
| **P1** | `on_llm_end` 捕获 token 用量 | `plugins/callbacks/audit.py` | ✅ 完成 |
| **P1** | `analyze_logs` 重写为查 `audit.duckdb` | `config/system/tools/analyze_logs.py` | ✅ 完成 |
| **P2** | SemanticRouter 路由决策写入 audit | `core/router.py` | ✅ 完成 |
| **P2** | SemanticCache 命中写入 audit | `core/memory/__init__.py` | ✅ 完成 |
| **P2** | CLI call site 传入 recorder → `route_query()` | `cli/main.py` | ✅ 完成 (146 tests) |
| **P3** | `trace_learner` 后台工具（Step 1-4 完整闭环） | `config/sync/tools/trace_learner.py` | ✅ 完成 (135 tests) |
| **P4** | 用户反馈评分 `feedback` (1-5) | CLI / API 端点 | ⬜ 待实现 |
| **P4** | Onboard Stage 5 注册 trace_learner cron | `cli/commands/onboard.py` | ✅ 完成 (146 tests) |
| **P4** | `/trace-review` slash 命令 | `cli/main.py` + `cli/commands/trace_review.py` | ✅ 完成 (146 tests) |

---

## 8. 参考

- `src/olav/plugins/callbacks/audit.py` — AuditCallbackPlugin（当前采集入口）
- `src/olav/core/audit_recorder.py` — AuditEventRecorder（写入接口）
- `.olav/databases/audit.duckdb` — 审计数据库（SSOT）
- `src/olav/core/router.py` — SemanticRouter（`routing_decision` 事件已接入）
- `.olav/workspace/config/sync/tools/take_snapshot.py` — Stage 2 已有 trace_learner hook
- `.olav/workspace/config/system/tools/analyze_logs.py` — analyze_logs（已重写为查 audit.duckdb）
- `src/olav/cli/commands/onboard.py` — Stage 5 cron 注册（`_register_trace_learner_cron`）
- `src/olav/cli/commands/trace_review.py` — `/trace-review` 命令业务逻辑（`_handle_trace_review`）
- `.olav/workspace/config/sync/tools/trace_learner.py` — `_run_learn_cycle` 完整闭环
