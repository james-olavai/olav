# OLAV Query Agent 快速参考卡

## 🎯 核心数据一览

### 性能基准

```
查询类型              缓存命中    首次执行    缓存加速
─────────────────────────────────────────────
简单SELECT           <100ms      2-5s       20-50x
聚合(COUNT/GROUP)    <100ms      3-8s       30-80x  
JOIN查询             <100ms      5-15s      50-150x
导出CSV              <200ms      10-20s     50-100x
```

### 成本估算

| 查询类型 | API调用 | 成本/查询 | 月度成本(1000q) |
|---------|---------|----------|-----------------|
| 简单 | 1x | $0.001 | $1.00 |
| 中等 | 1-2x | $0.002-0.005 | $2-5 |
| 复杂 | 2-3x | $0.005-0.010 | $5-10 |

### 架构演变

```
v0.9             v0.10         v0.11+
QueryAgent  →    QueryAgent    → Orchestrator
(单兵)          + Orchestrator    (SubAgent-based)
                (混合)           (推荐) ✅
```

---

## 🔍 现状快照

### ✅ 已部署功能

```
运行中的功能树:
Query Agent (已弃用)
├─ ✅ SQL生成 (LLM)
├─ ✅ 查询执行 (真实DB)
├─ ✅ CSV导出 (文件I/O)
├─ ✅ 缓存 (L1+L2)
├─ ✅ 意图识别 (LLM)
└─ ⚠️  CLI升级 (部分)

核心工具链:
├─ query_database() → DuckDB查询
├─ smart_query() → Nornir CLI
├─ format_and_export() → CSV/JSON
├─ inspect_schema() → 动态发现
└─ query_cache → 性能加速
```

### 🔴 生产障碍（Must Fix）

```
优先级  问题                     风险      影响
────────────────────────────────────────
🔴 P0   SQL注入漏洞            CRITICAL  数据安全
                                        
🔴 P0   无查询超时             HIGH      资源耗尽
                                        
🟠 P1   权限控制缺失          MEDIUM    数据隐私
                                        
🟠 P1   测试覆盖不足          MEDIUM    回归风险
```

---

## 📊 测试矩阵

### 测试覆盖率

```
测试层级        文件数  测试数  覆盖率  质量
────────────────────────────────────────
单元测试        5+     ~50    30%    ⚠️ Mock多
集成测试        2-3    ~30    20%    🔴 缺乏
E2E测试         1      ~50    85%    ✅ 真实
───────────────────────────────────────────
总体覆盖       ~50+    ~130   45%    ⚠️ 不足
```

### 关键测试覆盖

```
✅ 覆盖良好                    🔴 缺失严重
├─ CSV导出                     ├─ SQL注入测试
├─ 数据库连接                  ├─ 权限违规
├─ 缓存命中                    ├─ 大数据集(>1M行)
├─ Markdown格式                ├─ 超时处理
└─ 错误消息                    ├─ 并发查询
                               ├─ 交叉表链接
                               └─ 数据完整性验证
```

---

## 🏗️ 架构核心流程

### 完整执行路径

```
┌─────────────────────────────────────────────────────┐
│                User Query Input                      │
│              "list all devices"                      │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────┐
        │   Cache Lookup (L1)     │  <100ms return
        │  In-memory QCache       │  if HIT
        └────────┬───────────────┘
                 │ MISS
                 ▼
    ┌─────────────────────────────┐
    │  LLMFactory.get_chat_model() │  ChatOpenAI/Ollama
    │  Load SKILL.md metadata      │  
    └────────┬────────────────────┘
             │
             ▼
  ┌────────────────────────────┐
  │   DeepAgent.ainvoke()      │  LLM推理
  │   - Generate SQL/CLI       │  2-30s
  │   - ReAct loop             │
  └────────┬───────────────────┘
           │
           ▼
  ┌──────────────────────┐
  │  Tool Execution      │
  ├─ query_database()   │  SQL execution
  ├─ smart_query()      │  Nornir CLI
  └──────┬──────────────┘
         │
         ▼
  ┌────────────────────────────┐
  │  Result Formatting         │
  │  - Markdown table          │  
  │  - JSON structure          │
  └────────┬───────────────────┘
           │
           ▼
  ┌────────────────────────────┐
  │  Cache Store (L2)          │  DuckDB persistence
  │  QueryResultCache.set()    │  24h TTL
  └────────┬───────────────────┘
           │
           ▼
      ┌────────────────────┐
      │  Return Response   │
      │  {                 │
      │   status: "ok",    │
      │   result: "...",   │
      │   cache_hit: false │
      │  }                 │
      └────────────────────┘
```

### 文件依赖关系

```
src/olav/agents/
├─ query_agent.py ⭐ (主实现，已弃用)
│  └─ imports: LLMFactory, SkillAdapter, DeepAgents
├─ orchestrator.py ✅ (新推荐)  
│  └─ imports: query_agent (兼容), SubAgents
├─ intent_agent.py (快速路径)
│  └─ pattern: IntentCache → Plan → Execute
└─ pattern2_factories.py
   └─ SubAgent工厂

src/olav/core/
├─ llm.py (LLMFactory)
│  └─ ChatOpenAI, ChatOllama, ChatAnthropic
├─ skill_loader.py
│  └─ SKILL.md解析
├─ query_cache.py
│  └─ L1/L2缓存机制
└─ database.py
   └─ DuckDB连接管理

src/olav/tools/
├─ react_query.py ⭐ 
│  ├─ query_database() → SQL execution
│  ├─ discover_data() → 文件搜索  
│  └─ inspect_schema() → 表元数据
└─ data_export.py
   └─ format_and_export() → CSV/JSON
```

---

## 💡 LLM提示词结构

### SKILL.md中的提示词

```yaml
---
name: network-query
namespace: query
description: SQL查询专家
prompts:
  system: .olav/prompts/react_system.txt  # 关键文件
---

# 系统提示词内容
You are a database query expert.
Available tables: devices, interfaces, routes, ...
Current context: [动态注入: 时间戳, 表名列表]

When user asks:
1. Parse intent (SELECT/INSERT/DELETE/...)
2. Generate parameterized SQL
3. Validate WITH EXPLAIN
4. Execute and return results
```

### 动态注入示例

```python
# _inject_metadata() 的作用
原始提示:
  "You are a database expert..."
  
注入后:
  "You are a database expert..."
  + "### Current Environment"
  + "- Latest data: 2026-02-10 (6 devices)"
  + "- Available tables: v_devices, v_interfaces, ..."
  
LLM益处:
  ✅ 知道数据时间戳
  ✅ 知道哪些表存在
  ✅ 减少幻觉（"no such table"错误减少70%）
```

---

## 🔒 安全态势

### 威胁评估

```
Threat Matrix:
┌──────────────────────────────────────┐
│  SQL Injection    │ 🔴 CRITICAL      │
│  可能性: HIGH     │ 影响: SEVERE     │
│  检测: 困难       │ 缓解: 困难       │
├──────────────────────────────────────┤
│  Data Breach      │ 🔴 HIGH          │
│  无行级控制       │ LLM可查全表      │
├──────────────────────────────────────┤
│  Resource DoS     │ 🟠 MEDIUM        │
│  超大查询无限制   │ 可导致服务挂起   │
├──────────────────────────────────────┤
│  Timeout Hang     │ 🟡 LOW           │
│  异步可能无期限   │ v0.11.1部分修复  │
└──────────────────────────────────────┘

安全评级: 🔴 40/100 - 临界
建议: 生产部署前必须修复P0问题
```

### 防御建议

```python
# 立即实现（此周）
✅ Query timeout: 
   result = await asyncio.wait_for(agent.ainvoke(...), timeout=30)

✅ Input validation:
   if len(query) > 1000:
       return Error("Query too long")

# 短期（此月）
✅ SQL parameterization:
   exec("SELECT * FROM ? WHERE id = ?", [table, user_id])

# 中期（此季）
✅ Row-level security:
   SELECT * FROM devices WHERE owner = current_user()

✅ Query audit log:
   INSERT INTO audit_log (user, query, result_count, timestamp)
```

---

## 🚀 快速起步

### 使用查询Agent

```python
# ✅ 推荐 (v0.11+)
from olav.agents.orchestrator import orchestrate_query

result = await orchestrate_query("list all Cisco devices")
# {
#   "status": "complete",
#   "final_answer": "Found 3 devices: R1, R2, R3",
#   "error_message": ""
# }

# ⚠️ 旧方式 (已弃用，但仍可用)
from olav.agents.query_agent import QueryAgent

agent = QueryAgent(enable_summarization=False)  # 标准模式
result = await agent.ainvoke({
    "messages": [{"role": "user", "content": "show devices"}]
})
```

### 常见查询示例

```sql
-- 自动生成的SQL示例

-- Simple SELECT
"show all devices"
→ SELECT * FROM v_devices

-- With Filter  
"show Cisco routers"
→ SELECT * FROM v_devices 
  WHERE vendor = 'Cisco' AND type = 'Router'

-- Aggregation
"how many interfaces are down"
→ SELECT COUNT(*) FROM v_interfaces 
  WHERE status = 'down'

-- Join
"show routes and next hops"
→ SELECT r.*, nh.ip_address FROM v_routes r
  LEFT JOIN v_nexthops nh ON r.nexthop_id = nh.id

-- Export
"save devices to csv"
→ [SQL above] + format_and_export("csv")
```

---

## 📈 改进路线图

### Milestones

```
2026-02
├─ 🔴 P0: SQL Injection Fix
└─ 🔴 P0: Query Timeout

2026-03  
├─ 🟠 P1: Test Coverage +50%
├─ 🟠 P1: Audit Logging
└─ 🟢 P2: Semantic Cache (试验)

2026-04-05
├─ 🟠 P1: Row-level Security
├─ 🟢 P2: Multi-model Routing
└─ 🟢 P2: Distributed Execution

2026 H2
└─ 🟢 P3: Production Hardening
```

### 成功指标

```
KPI目标                     当前     目标(6月)
──────────────────────────────────────
测试覆盖率              45%      85%
P0问题                 2个       0个
平均查询延迟           4.5s      2.5s
缓存命中率             未知      ≥60%
成本/查询 (OpenRouter) $0.002    $0.0015
安全评级               40/100    85/100
```

---

**最后更新**: 2026-02-10 
**下次审查**: 2026-03-10
