# 企业级 Agentic 平台

OLAV 不只是一个 AI 聊天工具——它是一个完整的 **企业 Agentic 平台**，具备多层记忆与缓存、多用户隔离、审计驱动的 LLM 微调、以及联邦 Specialist Agent 架构。本页系统介绍这些生产级特性及其实测性能数据。

!!! abstract "功能声明"
    | ID | 声明 | 状态 |
    |----|------|------|
    | C-L2-38 | Per-Agent 模型分配（`agent_overrides`） | ✅ v0.10.0 |
    | C-L2-22 | 审计数据导出为训练格式（trajectory/sft/atif） | ✅ v0.10.0 |
    | C-L2-12 | 多用户并发 Audit 无写冲突 | ✅ v0.10.0 |
    | C-L2-21 | 知识库语义搜索（向量 + BM25 混合） | ✅ v0.10.0 |

---

## 多层 Agentic 架构

```
用户请求
    ↓
┌─────────────────────────────────────────────┐
│  Tier-0  SemanticCache (LanceDB)             │  ← 向量相似命中，10ms 返回
│  同一语义的查询不再触发任何 LLM 调用           │
└─────────────────────────────────────────────┘
    ↓ miss
┌─────────────────────────────────────────────┐
│  Tier-1  LLM SQLiteCache                    │  ← 精确 prompt 命中，<1ms 返回
│  相同对话上下文不重复调用 API                  │
└─────────────────────────────────────────────┘
    ↓ miss
┌─────────────────────────────────────────────┐
│  Tier-2  LLM API 调用（OpenAI / OpenRouter） │  ← 真正的网络请求，~2-30s
└─────────────────────────────────────────────┘
    ↓ 结果
┌─────────────────────────────────────────────┐
│  Episodic Memory (LanceDB)                  │  ← 运行结果写入长期记忆
│  LangGraph Checkpoint (DuckDB)              │  ← 对话状态持久化
│  Audit Log (audit.duckdb)                   │  ← 全量可审计轨迹
└─────────────────────────────────────────────┘
```

---

## 多层缓存详解

### Tier-1：LLM SQLiteCache（精确匹配）

每个用户有独立的 SQLite 缓存，位于 `~/.olav/cache/{username}/llm_cache.db`。当 Agent 发送完全相同的 prompt 时，直接从本地数据库返回，**零 token 消耗**。

**实测性能（2026-04-03，模型：x-ai/grok-4.1-fast）：**

| 场景 | 响应时间 | Token 消耗 | 加速比 |
|------|---------|------------|--------|
| 冷调用（无缓存） | 2.78s | 323 tokens (in: 171 + out: 152) | baseline |
| 热调用（SQLiteCache 命中） | **0.001s** | **0 tokens** | **2259x** |

```bash
# 缓存文件位置
ls ~/.olav/cache/$(whoami)/llm_cache.db

# 查看缓存统计
sqlite3 ~/.olav/cache/$(whoami)/llm_cache.db \
  "SELECT COUNT(*) as entries FROM full_llm_cache"
```

!!! tip "多次运行同一 Agent 查询"
    Agent 整体（含 LangGraph 推理和工具调用）的加速效果：
    
    | 运行次数 | 耗时 | 加速比 |
    |---------|------|--------|
    | 第 1 次（冷启动） | ~28s | 1x |
    | 第 2 次 | ~19s | 1.5x |
    | 第 3 次+ | ~14s | **2x** |
    
    因 LangGraph 消息历史包含动态 ID，加速效果随运行次数递增，趋于稳定后可达 2x。

### Tier-0：SemanticCache（向量相似匹配）

SemanticCache 存储于 `.olav/databases/memory.lance`（LanceDB），对 Knowledge Base 查询、Hybrid Search 等向量检索操作进行语义级缓存。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `cache_similarity_threshold` | `0.02` | cosine distance 阈值（≤0.02 = 99%+ 相似） |
| `cache_ttl_hours` | `24` | 缓存条目过期时间 |
| `cache_max_entries` | `500` | 最大条目数（超出后按 LRU 淘汰） |

```bash
# 调整阈值以覆盖更多语义相似查询（推荐 0.10~0.20）
export OLAV_MEMORY_CACHE_SIMILARITY_THRESHOLD=0.15
```

!!! warning "阈值调优建议"
    默认阈值 `0.02` 仅命中近似重复查询。若需覆盖"Show BGP settings for R1" 与 "What is the BGP config of R1?"这类语义相似但措辞不同的查询（实测 distance ≈ 0.78），需将阈值提高到 `0.15~0.20`。

### Anthropic Prompt Caching（企业专属）

当使用 Anthropic 模型时，OLAV 通过 `deepagents.AnthropicPromptCachingMiddleware` 自动在 system prompt 和 static context 上添加 `cache_control` 标记：

```json
{
  "llm": {
    "provider": "anthropic",
    "model": "claude-3-5-sonnet-20241022"
  }
}
```

Anthropic Prompt Caching 对系统提示词（通常数千 token）只计算一次费用，后续命中仅收取 10% 的读取费用。对大型 static_context（如 Network Schema 参考文档）特别有效。

---

## 多层记忆系统

OLAV 使用 LanceDB 向量数据库存储两类持久化记忆：

### Episodic Memory（情景记忆）

Agent 在运行过程中自动积累的知识，存储于 `.olav/databases/memory.lance`（`memory` 表）。

| 类别 | 描述 | 示例 |
|------|------|------|
| `fact` | 环境事实 | "R1@192.168.100.101 是 Juniper 边界路由器" |
| `decision` | 决策记录 | "选择 OSPF 而非 BGP 用于 DC 内部" |
| `preference` | 用户偏好 | "用户偏好 JSON 格式输出" |
| `audit` | 约束教训 | "调用 execute_sql 必须用 schema.table 格式" |

```python
# memory 表结构
id, text, vector (384/1536-dim), category, scope (global|agent),
metadata, timestamp, access_count, weight (time-decay)
```

### LangGraph Checkpoint（会话状态）

每个用户的每个 Agent 有独立的 DuckDB checkpoint 文件，实现跨会话的对话持续性：

```
~/.olav/checkpoints/{username}/{workspace}/{agent_id}/checkpoints.duckdb
```

重启 OLAV 后，Agent 可以恢复上次的对话上下文，无需用户重新说明背景。

---

## 多用户隔离（企业安全）

OLAV 设计为多用户并发环境，不同用户的数据严格隔离：

```
用户 Alice                    用户 Bob
~/.olav/cache/alice/         ~/.olav/cache/bob/
~/.olav/checkpoints/alice/   ~/.olav/checkpoints/bob/
~/.olav/token                ~/.olav/token
        ↓                            ↓
        └──────────┬─────────────────┘
                   ↓
          .olav/databases/        ← 只读：全局共享
          .olav/logs/             ← 集中：所有用户审计
          .olav/workspace/        ← 只读：Agent 定义
```

| 数据类型 | 隔离级别 | 存储位置 |
|---------|---------|---------|
| LLM 响应缓存 | 用户私有 | `~/.olav/cache/{user}/` |
| 对话 Checkpoint | 用户私有 | `~/.olav/checkpoints/{user}/` |
| 审计日志 | 集中记录 | `.olav/databases/audit.duckdb` |
| Agent 定义 | 全局共享 | `.olav/workspace/` |
| 业务数据 | 全局共享 | `.olav/databases/main.duckdb` |

认证模式、角色权限、用户管理的详细说明见 [安全模型 →](security-model.md)。

---

## 联邦 Specialist Agent 架构

OLAV 使用 `deepagents.SkillsMiddleware` 动态绑定 Skill 到 Agent，形成**联邦专家体系**：

```
用户请求
    ↓
OLAVAgent（语义路由器）
    ├── quick  — 快速 SQL/CLI 查询
    ├── ops    — 深度运维（路由、拓扑、日志分析、diff）
    ├── config — 库存同步、快照采集、API 注册
    └── core   — Python/SQL/Shell 代码执行、Web 搜索
         └── sandbox（SubAgent）— 高并发计算隔离环境
```

每个 Agent 的工具集通过 `SKILL.md` 的 `required_params` 元数据声明**必要信息检查**协议——在缺少必要参数时（如目标设备、凭据），Agent 会停下来询问用户而不是盲目执行。

---

## 企业级 LLM 微调

OLAV 的审计数据库不仅是日志，还是**持续积累的微调数据集**。三种导出格式和具体命令详见 [审计与日志 →](../guides/audit-and-logs.md)。

### 微调目标

| 微调类型 | 数据来源 | 用途 |
|---------|---------|------|
| **工具调用**（Tool Call FT） | 成功的工具调用轨迹 | 提升 LLM 直接生成正确 SQL/CLI 的能力 |
| **领域知识**（Domain FT） | 设备信息、网络拓扑、告警规则 | 减少 RAG 查询，让 LLM 内化业务知识 |
| **约束学习**（Constraint FT） | `/trace-review` 提取的失败教训 | 防止已知的工具滥用模式 |

微调后的模型可替换 `api.json` 中的 `llm.model` 字段，无需修改任何 Agent 逻辑：

```json
{
  "llm": {
    "provider": "custom",
    "model": "your-org/olav-finetuned-v1",
    "base_url": "https://your-inference-server/v1",
    "api_key": "..."
  },
  "agent_overrides": {
    "ops": {
      "model": "your-org/olav-ops-specialist-v1"
    }
  }
}
```

### Per-Agent 模型分配

不同 Agent 可以使用不同的微调模型，实现**成本与能力的精细平衡**：

```json
{
  "llm": {
    "model": "gpt-4o-mini"
  },
  "agent_overrides": {
    "ops":    { "model": "your-ops-specialist" },
    "config": { "model": "claude-3-5-sonnet-20241022" },
    "quick":  { "model": "gpt-4o-mini" },
    "core":   { "model": "gpt-4o" }
  }
}
```

高频次的 `quick` Agent 使用低成本模型；需要深度推理的 `ops` Agent 使用专用微调模型，**整体 Token 成本可降低 40–70%**。

---

## 可观测性

所有 Agent 活动写入 `.olav/databases/audit.duckdb`，可直接用 DuckDB 查询：

```bash
# 查询最近 24h Token 消耗
duckdb .olav/databases/audit.duckdb "
  SELECT 
    agent_id,
    COUNT(*) AS runs,
    SUM(CAST(json_extract(payload, '$.tokens_total') AS INT)) AS total_tokens
  FROM audit_events
  WHERE event_type = 'chain_end'
    AND timestamp > NOW() - INTERVAL 24 HOURS
  GROUP BY agent_id
  ORDER BY total_tokens DESC
"

# 查看缓存命中率（semantic_cache_hit 事件）
duckdb .olav/databases/audit.duckdb "
  SELECT 
    DATE_TRUNC('hour', timestamp) AS hour,
    COUNT(*) AS cache_hits
  FROM audit_events
  WHERE event_type = 'semantic_cache_hit'
  GROUP BY 1
  ORDER BY 1 DESC
  LIMIT 24
"
```

这让你可以精确回答：
- 哪个 Agent 消耗了最多 Token？
- 缓存命中率趋势如何？
- 哪类查询最频繁？
- 哪次运行出错了，原因是什么？

---

## 下一步

- [Agent Harness →](agent-harness.md) — 沙箱执行、HITL 审批、注入防护
- [自我改进循环 →](self-improving-loop.md) — 如何用审计数据持续改进 Agent
- [审计与日志 →](../guides/audit-and-logs.md) — 详细的日志查询与导出指南
- [配置参考 →](../reference/configuration.md) — 完整的 api.json 配置说明
- [用户与角色 →](../reference/users-and-roles.md) — RBAC 权限控制
