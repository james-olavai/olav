# OLAV Router Agent v2.0 设计文档 (Plan Agent 架构)

> **版本**: v2.0 (v0.10.0)  
> **创建日期**: 2026-02-01  
> **状态**: 架构设计方案  
> **核心特性**: Plan Agent + 执行计划缓存 + 跨 Agent 联合查询

---

## 📋 架构升级动机

### v1.0 的局限性

**当前设计**:
- ✅ 单 Agent 路由（query → agent_name）
- ✅ 学习机制（routing_patterns）
- ❌ **不支持跨 Agent 联合查询**
- ❌ **无法生成多步骤执行计划**

### v2.0 的目标

**支持复杂场景**:

```
场景 1: Log + NetBox 联合查询
用户: "R1 最近有哪些报错日志？这些报错对应的设备在 NetBox 中的配置是什么？"

需要:
1. Log Agent 查询报错日志
2. NetBox Agent 查询设备配置
3. Expert Agent 关联分析
```

```
场景 2: DB + Log + Expert 联合查询
用户: "为什么 R2 的 BGP 邻居频繁 Down？检查日志和历史数据。"

需要:
1. DB Query Agent 查询 BGP 历史状态
2. Log Agent 查询 BGP 相关日志
3. Expert Agent 根因分析
```

---

## 🏗️ 核心架构：Plan Agent + Router Cache 混合模式

### 架构图

```
User Query
    ↓
┌─────────────────────────────────────────────────┐
│ Router Agent V2 (双模式)                        │
│                                                 │
│ 1. 检查 Execution Plan Cache                   │
│    ├─ Hit → FastPath (0.2-1s)                   │
│    └─ Miss → SlowPath (Plan Agent)              │
└─────────────────────────────────────────────────┘
            ↓                      ↓
    ┌───────┘                      └────────┐
    │ FastPath                              │ SlowPath
    ▼                                       ▼
┌──────────────┐              ┌─────────────────────┐
│ 执行计划缓存  │              │ Plan Agent          │
│ - 单步计划   │              │ (DeepAgents ReAct)  │
│ - 多步计划   │              │                     │
│ - 依赖关系   │              │ 分析 → 规划 → 生成  │
└──────┬───────┘              └────────┬────────────┘
       │                               │
       └───────────┬───────────────────┘
                   ↓
       ┌───────────────────────┐
       │ Execution Orchestrator│
       │ - 单/多 Agent 执行    │
       │ - 结果传递            │
       │ - 依赖管理            │
       └───────────┬───────────┘
                   ↓
       ┌───────────────────────┐
       │ 缓存执行计划           │
       │ (下次 FastPath)       │
       └───────────────────────┘
```

### 两种模式对比

| 特性 | FastPath | SlowPath |
|:---|:---|:---|
| **触发条件** | 缓存命中 | 缓存未命中 |
| **延迟** | 0.2-1秒 | 5-10秒 |
| **LLM 调用** | 0 次 | 多次（Plan Agent） |
| **适用场景** | 重复查询 | 首次/新型查询 |
| **执行方式** | 直接执行缓存计划 | 生成计划 → 执行 → 缓存 |

---

## 🗄️ 数据库设计

### 表：execution_plan_cache

```sql
CREATE TABLE execution_plan_cache (
    id UUID PRIMARY KEY DEFAULT uuid(),
    
    -- 查询信息
    query_text TEXT NOT NULL,
    query_embedding FLOAT[768],
    query_category TEXT,
    
    -- 执行计划（核心！）
    execution_plan JSON NOT NULL,
    /* 示例：
    {
        "steps": [
            {
                "step": 1,
                "agent": "log",
                "action": "query_logs",
                "params": {"device": "R1", "level": "error"},
                "output_key": "error_logs"
            },
            {
                "step": 2,
                "agent": "netbox",
                "action": "get_device_config",
                "params": {"device": "R1"},
                "depends_on": [],
                "output_key": "device_config"
            },
            {
                "step": 3,
                "agent": "expert",
                "action": "analyze",
                "params": {
                    "logs": "${error_logs}",
                    "config": "${device_config}"
                },
                "depends_on": ["error_logs", "device_config"]
            }
        ]
    }
    */
    
    -- 元数据
    agents_involved JSON,          -- ["log", "netbox", "expert"]
    is_multi_agent BOOLEAN,        -- 是否跨 Agent
    complexity_score FLOAT,        -- 复杂度 (0-1)
    
    -- 性能指标
    success_rate FLOAT DEFAULT 1.0,
    avg_execution_time FLOAT,
    hit_count INTEGER DEFAULT 1,
    
    -- 时间信息
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 向量搜索索引
CREATE INDEX idx_plan_embedding ON execution_plan_cache 
    USING HNSW(query_embedding);

-- 多 Agent 索引
CREATE INDEX idx_multi_agent ON execution_plan_cache(is_multi_agent);
```

---

## 🛠️ 核心实现

### 1. Plan Agent (基于 DeepAgents)

```python
# src/olav/agents/plan_agent.py

from deepagents import create_deep_agent

class PlanAgent:
    """
    执行计划生成 Agent
    使用 DeepAgents ReAct 生成跨 Agent 执行计划
    """
    
    def __init__(self, agent_registry):
        self.agent_registry = agent_registry
        self.agent = create_deep_agent(
            model="gemini-2.0-flash",
            system_prompt=self._get_system_prompt()
        )
    
    def _get_system_prompt(self) -> str:
        agents_desc = "\n".join([
            f"- {name}: {agent.description}"
            for name, agent in self.agent_registry.items()
        ])
        
        return f"""
你是执行计划生成专家。

可用 Agent:
{agents_desc}

任务: 将用户查询分解为多步骤执行计划

输出格式:
{{
    "steps": [
        {{
            "step": 1,
            "agent": "agent_name",
            "action": "action_name",
            "params": {{}},
            "output_key": "result_key"
        }},
        {{
            "step": 2,
            "depends_on": ["result_key"],
            "params": {{"context": "${{result_key}}"}}
        }}
    ]
}}

规则:
1. 尽量减少步骤数（简单查询用单步）
2. 明确依赖关系（depends_on）
3. 使用变量传递（${{key}}）
4. 最后一步应该是最终结果
"""
    
    async def generate_plan(self, query: str) -> dict:
        """生成执行计划"""
        
        response = await self.agent.ainvoke(query)
        plan = json.loads(response.content)
        
        # 计算元数据
        agents = {step["agent"] for step in plan["steps"]}
        
        return {
            "plan": plan,
            "agents_involved": list(agents),
            "is_multi_agent": len(agents) > 1,
            "complexity_score": len(plan["steps"]) / 10.0
        }
```

### 2. Execution Orchestrator

```python
# src/olav/core/execution_orchestrator.py

class ExecutionOrchestrator:
    """执行计划协调器"""
    
    def __init__(self, agent_manager):
        self.agent_manager = agent_manager
    
    async def execute_plan(self, plan: dict) -> dict:
        """
        执行多步骤计划
        
        支持:
        - 单 Agent 单步
        - 单 Agent 多步
        - 跨 Agent 多步
        - 步骤依赖
        - 结果传递
        """
        
        results = {}  # 中间结果存储
        trace = []    # 执行轨迹
        
        for step_config in plan["steps"]:
            step_num = step_config["step"]
            agent_name = step_config["agent"]
            
            # 1. 检查依赖
            if "depends_on" in step_config:
                for dep in step_config["depends_on"]:
                    if dep not in results:
                        raise RuntimeError(f"依赖未满足: {dep}")
            
            # 2. 解析参数（替换变量）
            params = self._resolve_params(
                step_config["params"], 
                results
            )
            
            # 3. 执行 Agent
            agent = self.agent_manager.get_agent(agent_name)
            step_result = await agent.execute(**params)
            
            # 4. 存储结果
            output_key = step_config.get("output_key", f"step_{step_num}")
            results[output_key] = step_result
            
            # 5. 记录轨迹
            trace.append({
                "step": step_num,
                "agent": agent_name,
                "success": True
            })
        
        # 最终结果
        final_key = plan["steps"][-1].get("output_key")
        
        return {
            "final_result": results[final_key],
            "intermediate_results": results,
            "execution_trace": trace
        }
    
    def _resolve_params(self, params: dict, results: dict) -> dict:
        """解析参数中的变量引用 ${key}"""
        import re
        
        resolved = {}
        for k, v in params.items():
            if isinstance(v, str) and "${" in v:
                var = re.search(r'\$\{(\w+)\}', v).group(1)
                resolved[k] = results.get(var)
            else:
                resolved[k] = v
        
        return resolved
```

### 3. Router Agent V2 (双模式)

```python
# src/olav/agents/router_agent_v2.py

class RouterAgentV2:
    """
    Router Agent V2 - 双模式架构
    """
    
    def __init__(self, agent_manager):
        self.plan_cache = ExecutionPlanCache()
        self.plan_agent = PlanAgent(agent_manager.get_registry())
        self.orchestrator = ExecutionOrchestrator(agent_manager)
    
    async def route(self, query: str) -> dict:
        """
        智能路由 + 执行
        
        Returns:
            {
                "mode": "fastpath" | "slowpath",
                "result": {...},
                "plan": {...},
                "execution_time": float
            }
        """
        
        start_time = time.time()
        
        # Step 1: 检查执行计划缓存
        cached_plan = self.plan_cache.get_cached_plan(query)
        
        if cached_plan:
            # FastPath: 直接执行缓存计划
            print("🚀 FastPath: Using cached execution plan")
            
            result = await self.orchestrator.execute_plan(
                cached_plan["execution_plan"]
            )
            
            # 更新缓存统计
            self.plan_cache.update_hit_count(cached_plan["id"])
            
            return {
                "mode": "fastpath",
                "result": result,
                "plan": cached_plan,
                "execution_time": time.time() - start_time
            }
        
        # Step 2: SlowPath - 生成执行计划
        print("🐢 SlowPath: Generating new execution plan")
        
        plan_data = await self.plan_agent.generate_plan(query)
        plan = plan_data["plan"]
        
        # Step 3: 执行计划
        result = await self.orchestrator.execute_plan(plan)
        
        # Step 4: 缓存执行计划
        if result["execution_trace"][-1]["success"]:
            self.plan_cache.cache_plan(
                query=query,
                plan=plan,
                agents_involved=plan_data["agents_involved"],
                is_multi_agent=plan_data["is_multi_agent"],
                execution_time=time.time() - start_time
            )
            print("✅ Execution plan cached for future FastPath")
        
        return {
            "mode": "slowpath",
            "result": result,
            "plan": plan,
            "execution_time": time.time() - start_time
        }
```

---

## 📊 执行示例

### 示例 1: 单 Agent 查询（FastPath 优化）

```python
# 首次查询 (SlowPath: 5秒)
query = "查询 R1 的 BGP 邻居状态"

plan = {
    "steps": [{
        "step": 1,
        "agent": "db_query",
        "action": "query",
        "params": {"sql": "SELECT * FROM v_bgp_neighbors WHERE device='R1'"}
    }]
}

# 第二次查询 (FastPath: 0.2秒)
# 直接执行缓存的计划 ✅
```

### 示例 2: 跨 Agent 联合查询

```python
query = "R1 最近有哪些报错日志？这些报错对应的设备在 NetBox 中的配置是什么？"

# Plan Agent 生成计划
plan = {
    "steps": [
        {
            "step": 1,
            "agent": "log",
            "action": "query_logs",
            "params": {"device": "R1", "level": "error", "hours": 24},
            "output_key": "error_logs"
        },
        {
            "step": 2,
            "agent": "netbox",
            "action": "get_device_config",
            "params": {"device": "R1"},
            "output_key": "device_config"
        },
        {
            "step": 3,
            "agent": "expert",
            "action": "correlate",
            "params": {
                "logs": "${error_logs}",
                "config": "${device_config}"
            },
            "depends_on": ["error_logs", "device_config"]
        }
    ]
}

# 执行
# Step 1: Log Agent → error_logs
# Step 2: NetBox Agent → device_config
# Step 3: Expert Agent → 最终结果

# 下次类似查询 → FastPath ✅
```

---

## 🎯 架构优势

### 1. 性能优化

| 场景 | 首次 | 重复 | 优化 |
|:---|:---|:---|:---|
| 简单查询 | 5秒 | 0.2秒 | 25x |
| 复杂查询 | 10秒 | 1秒 | 10x |
| 跨 Agent 查询 | 15秒 | 2秒 | 7.5x |

### 2. 可扩展性

```python
# 新增 Agent 无需修改核心代码
agent_manager.register_agent("prometheus", PrometheusAgent())
agent_manager.register_agent("grafana", GrafanaAgent())
agent_manager.register_agent("elasticsearch", ElasticsearchAgent())

# Plan Agent 自动支持新 Agent
```

### 3. 灵活性

- ✅ 支持单 Agent 单步查询
- ✅ 支持单 Agent 多步查询
- ✅ 支持跨 Agent 联合查询
- ✅ 支持复杂依赖关系
- ✅ 支持结果传递和融合

---

## 🚀 实施路线图

### Phase 1: 核心框架（3天）

- [ ] 实现 `ExecutionPlanCache`
- [ ] 实现 `PlanAgent`（DeepAgents）
- [ ] 实现 `ExecutionOrchestrator`
- [ ] 单元测试

### Phase 2: Router 升级（2天）

- [ ] 实现 `RouterAgentV2`（双模式）
- [ ] 集成 FastPath/SlowPath
- [ ] E2E 测试

### Phase 3: Agent 扩展（按需）

- [ ] 实现 `LogAgent`
- [ ] 实现 `NetBoxAgent`
- [ ] 其他 Agent...

---

## 📚 参考文档

- `docs/02_expert_design.md` - Expert Agent 设计
- `docs/01_db_design.md` - 数据库架构
- `/tmp/cross_agent_architecture.md` - 跨 Agent 架构详细设计

---

**版本**: v2.0  
**状态**: 设计完成，准备实施  
**核心升级**: Plan Agent + 执行计划缓存 + 跨 Agent 支持
