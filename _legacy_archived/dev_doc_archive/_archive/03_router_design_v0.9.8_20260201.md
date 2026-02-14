# OLAV Orchestrator 设计文档

> **版本**: v0.9.8  
> **创建日期**: 2026-02-01  
> **状态**: 架构设计方案  
> **核心职责**: 路由 + 执行协调 + 质量评估 + Markdown 输出

---

## 📋 执行摘要

### Orchestrator 核心职责

**统一协调器：路由、评估、执行、输出**

- 🎯 **路由决策**: 将用户查询路由到最合适的 Agent
- 🧠 **学习机制**: 从成功/失败中学习，持续优化
- 📋 **执行协调**: 支持单 Agent 和跨 Agent 联合查询
- 📊 **质量评估**: 评估结果质量，决定是否升级
- 📝 **Markdown 输出**: 统一的用户友好格式输出
- 🚀 **双模式**: FastPath（缓存命中）+ SlowPath（计划生成）

**设计原则**:
- ✅ **单一 LLM 入口**: 避免过多 LLM 调用导致性能下降
- ✅ **职责统一**: 路由、评估、输出都由 Orchestrator 负责
- ✅ **简洁高效**: 去掉冗余组件（QualityChecker、ResultMerger 等）

---

## 🏗️ 架构设计

### 统一 Orchestrator 架构

```
User Query
    ↓
┌─────────────────────────────────────────────────┐
│ Orchestrator (统一协调器)                       │
│                                                 │
│ 1. 检查执行计划缓存                             │
│    ├─ Hit → FastPath (0.2-2s)                   │
│    └─ Miss → SlowPath                           │
│                                                 │
│ 2. SlowPath 流程                                │
│    ├─ 路由决策（LLM）                           │
│    ├─ 执行 Agent(s)                             │
│    ├─ 质量评估（LLM）                           │
│    ├─ 升级决策（如需要）                        │
│    └─ Markdown 输出（LLM）                      │
│                                                 │
│ 3. 学习和缓存                                   │
│    └─ 记录执行计划 → 下次 FastPath              │
└─────────────────────────────────────────────────┘
```

**关键设计**:
- ❌ **去掉独立的 QualityChecker**: 质量评估集成到 Orchestrator
- ❌ **去掉独立的 ResultMerger**: 结果融合由 Orchestrator LLM 处理
- ❌ **去掉独立的 PlanAgent**: 计划生成集成到 Orchestrator
- ✅ **单一 LLM 决策点**: Orchestrator 是唯一的 LLM 调用入口

---

## 🗄️ 数据库设计

### execution_plan_cache（统一执行计划缓存）

```sql
CREATE TABLE execution_plan_cache (
    id UUID PRIMARY KEY DEFAULT uuid(),
    
    -- 查询信息
    query_text TEXT NOT NULL,
    query_embedding FLOAT[768],
    query_category TEXT,
    
    -- 执行计划（简化）
    execution_plan JSON NOT NULL,
    /* 示例 1: 单 Agent
    {
        "steps": [{
            "step": 1,
            "agent": "db_query",
            "params": {"query": "查询 R1 BGP 邻居"}
        }]
    }
    
    示例 2: 跨 Agent
    {
        "steps": [
            {
                "step": 1,
                "agent": "log",
                "params": {"device": "R1", "level": "error"},
                "output_key": "logs"
            },
            {
                "step": 2,
                "agent": "expert",
                "params": {"context": "${logs}"},
                "depends_on": ["logs"]
            }
        ]
    }
    */
    
    -- 元数据
    agents_involved JSON,               -- ["db_query"] 或 ["log", "expert"]
    is_multi_agent BOOLEAN,
    complexity_score FLOAT,
    
    -- 路由学习
    initial_route TEXT,                 -- 初始路由目标
    final_route TEXT,                   -- 最终路由目标（可能升级）
    was_upgraded BOOLEAN,
    
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
    USING HNSW(query_embedding) WITH (M=16, EFC=200);

-- 多 Agent 索引
CREATE INDEX idx_multi_agent ON execution_plan_cache(is_multi_agent);

-- 类别索引
CREATE INDEX idx_category ON execution_plan_cache(query_category);
```

---

## 🛠️ 核心实现

### Orchestrator 主类（统一协调器）

```python
# src/olav/agents/orchestrator.py

from pathlib import Path
import duckdb
import time
from typing import Optional
from olav.core.llm_helper import get_llm, get_embedding

class Orchestrator:
    """
    统一协调器
    
    职责:
    1. 路由决策（单 Agent / 跨 Agent）
    2. 执行协调（单步 / 多步）
    3. 质量评估（是否升级）
    4. Markdown 输出（用户友好格式）
    5. 学习缓存（优化未来查询）
    """
    
    def __init__(self, agent_manager):
        self.agent_manager = agent_manager
        self.llm = get_llm()
        
        # 执行计划缓存
        self.db_path = Path(".olav/db/orchestrator.duckdb")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        conn = duckdb.connect(str(self.db_path))
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS execution_plan_cache (
                id UUID PRIMARY KEY DEFAULT uuid(),
                query_text TEXT NOT NULL,
                query_embedding FLOAT[768],
                query_category TEXT,
                execution_plan JSON NOT NULL,
                agents_involved JSON,
                is_multi_agent BOOLEAN,
                complexity_score FLOAT,
                initial_route TEXT,
                final_route TEXT,
                was_upgraded BOOLEAN,
                success_rate FLOAT DEFAULT 1.0,
                avg_execution_time FLOAT,
                hit_count INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_plan_embedding 
            ON execution_plan_cache 
            USING HNSW(query_embedding);
        """)
        
        conn.close()
    
    async def orchestrate(self, query: str) -> dict:
        """
        协调查询执行
        
        Returns:
            {
                "mode": "fastpath" | "slowpath",
                "result": {...},
                "markdown": str,  # 用户友好输出
                "execution_time": float
            }
        """
        
        start_time = time.time()
        
        # Step 1: 检查缓存
        cached_plan = self._get_cached_plan(query)
        
        if cached_plan:
            # FastPath
            result = await self._execute_plan(cached_plan["execution_plan"])
            self._update_cache_hit(cached_plan["id"])
            
            # Markdown 输出
            markdown = await self._generate_markdown_output(query, result)
            
            return {
                "mode": "fastpath",
                "result": result,
                "markdown": markdown,
                "execution_time": time.time() - start_time
            }
        
        # Step 2: SlowPath - 完整流程
        return await self._slowpath_orchestrate(query, start_time)
    
    async def _slowpath_orchestrate(self, query: str, start_time: float) -> dict:
        """SlowPath: 路由 → 执行 → 评估 → 升级（可选）→ 输出"""
        
        # Step 1: 评估复杂度
        complexity = await self._assess_complexity(query)
        
        # Step 2: 路由决策（单 LLM 调用）
        route_decision = await self._llm_route_and_plan(query, complexity)
        # 返回:
        # {
        #     "initial_route": "db_query",
        #     "execution_plan": {...},
        #     "complexity_score": 0.3
        # }
        
        # Step 3: 执行计划
        result = await self._execute_plan(route_decision["execution_plan"])
        
        # Step 4: 质量评估 + 升级决策（单 LLM 调用）
        final_result = result
        was_upgraded = False
        final_route = route_decision["initial_route"]
        
        if route_decision["initial_route"] != "expert":
            evaluation = await self._llm_evaluate_and_decide(query, result)
            # 返回:
            # {
            #     "quality_score": 0.4,
            #     "should_upgrade": True,
            #     "reason": "数据量过大，需要 Expert 分析"
            # }
            
            if evaluation["should_upgrade"]:
                # 升级到 Expert
                expert_result = await self._execute_agent(
                    "expert", 
                    query, 
                    context=result
                )
                final_result = expert_result
                final_route = "expert"
                was_upgraded = True
        
        # Step 5: Markdown 输出（单 LLM 调用）
        markdown = await self._generate_markdown_output(query, final_result)
        
        # Step 6: 缓存学习
        self._cache_plan(
            query=query,
            execution_plan=route_decision["execution_plan"],
            initial_route=route_decision["initial_route"],
            final_route=final_route,
            was_upgraded=was_upgraded,
            execution_time=time.time() - start_time
        )
        
        return {
            "mode": "slowpath",
            "result": final_result,
            "markdown": markdown,
            "was_upgraded": was_upgraded,
            "execution_time": time.time() - start_time
        }
    
    async def _llm_route_and_plan(
        self, 
        query: str, 
        complexity: float
    ) -> dict:
        """
        单 LLM 调用：路由决策 + 执行计划生成
        
        复杂查询 → 多步计划
        简单查询 → 单步计划
        """
        
        agents_desc = "\n".join([
            f"- {name}: {agent.description}"
            for name, agent in self.agent_manager.get_registry().items()
        ])
        
        prompt = f"""
你是查询协调器。根据用户查询生成执行计划。

用户查询: {query}
复杂度评分: {complexity}

可用 Agent:
{agents_desc}

任务:
1. 判断初始路由目标（db_query / cli / expert / log / netbox / ...）
2. 生成执行计划（单步或多步）

简单查询（complexity < 0.5）→ 单步计划:
{{
    "initial_route": "db_query",
    "execution_plan": {{
        "steps": [{{
            "step": 1,
            "agent": "db_query",
            "params": {{"query": "{query}"}}
        }}]
    }},
    "complexity_score": {complexity}
}}

复杂查询（complexity >= 0.5）→ 多步计划:
{{
    "initial_route": "log",
    "execution_plan": {{
        "steps": [
            {{
                "step": 1,
                "agent": "log",
                "params": {{"device": "R1"}},
                "output_key": "logs"
            }},
            {{
                "step": 2,
                "agent": "expert",
                "params": {{"context": "${{logs}}"}},
                "depends_on": ["logs"]
            }}
        ]
    }},
    "complexity_score": {complexity}
}}

仅输出 JSON，不要额外说明。
"""
        
        response = await self.llm.ainvoke(prompt)
        import json
        return json.loads(response.content)
    
    async def _llm_evaluate_and_decide(
        self, 
        query: str, 
        result: dict
    ) -> dict:
        """
        单 LLM 调用：质量评估 + 升级决策
        """
        
        row_count = result.get("row_count", 0)
        
        # 简单规则过滤
        if row_count > 1000:
            return {
                "quality_score": 0.3,
                "should_upgrade": True,
                "reason": "数据量过大（> 1000 行），需要 Expert 分析"
            }
        
        if row_count == 0:
            return {
                "quality_score": 0.2,
                "should_upgrade": False,
                "reason": "无数据"
            }
        
        # LLM 判断
        prompt = f"""
用户查询: {query}
查询结果行数: {row_count}
结果摘要: {str(result)[:500]}

评估:
1. 质量分数（0-1）: 这个结果是否充分回答了用户问题？
2. 是否需要升级到 Expert Agent？

判断标准:
- 数据量过大（> 1000 行）→ 升级
- 需要深度分析（差异、趋势、根因）→ 升级
- 简单的数据呈现 → 不升级

输出 JSON:
{{
    "quality_score": 0.8,
    "should_upgrade": false,
    "reason": "数据清晰，可直接理解"
}}

仅输出 JSON。
"""
        
        response = await self.llm.ainvoke(prompt)
        import json
        return json.loads(response.content)
    
    async def _generate_markdown_output(
        self, 
        query: str, 
        result: dict
    ) -> str:
        """
        单 LLM 调用：生成用户友好的 Markdown 输出
        """
        
        prompt = f"""
用户查询: {query}
查询结果: {result}

请生成用户友好的 Markdown 格式输出，包括:
1. 简洁的问题回答
2. 关键数据呈现（表格/列表）
3. 可选的进一步建议

示例输出:
# R1 BGP 邻居状态

## 当前状态
| 邻居 | 状态 | Uptime |
|:---|:---|:---|
| 10.0.0.2 | Established | 3d2h |
| 10.0.0.3 | Established | 1d5h |

## 总结
所有 BGP 邻居状态正常。

## 建议
- 监控 10.0.0.3 邻居（重启时间较短）

生成 Markdown 输出:
"""
        
        response = await self.llm.ainvoke(prompt)
        return response.content
    
    async def _execute_plan(self, plan: dict) -> dict:
        """执行多步骤计划"""
        
        results = {}
        
        for step in plan["steps"]:
            agent_name = step["agent"]
            params = step.get("params", {})
            
            # 解析变量引用 ${key}
            resolved_params = self._resolve_params(params, results)
            
            # 执行 Agent
            agent = self.agent_manager.get_agent(agent_name)
            step_result = await agent.execute(**resolved_params)
            
            # 存储结果
            output_key = step.get("output_key", f"step_{step['step']}")
            results[output_key] = step_result
        
        # 返回最终结果
        final_key = plan["steps"][-1].get("output_key", f"step_{len(plan['steps'])}")
        return results.get(final_key, results)
    
    async def _execute_agent(
        self, 
        agent_name: str, 
        query: str, 
        context: Optional[dict] = None
    ) -> dict:
        """执行单个 Agent"""
        
        agent = self.agent_manager.get_agent(agent_name)
        
        if context:
            return await agent.execute(query=query, context=context)
        else:
            return await agent.execute(query=query)
    
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
    
    async def _assess_complexity(self, query: str) -> float:
        """评估查询复杂度（简单规则）"""
        
        # 关键词检测
        complex_signals = ["为什么", "差异", "对比", "趋势", "根因"]
        multi_agent_signals = ["日志", "配置", "NetBox"]
        
        score = 0.0
        
        if any(sig in query for sig in complex_signals):
            score += 0.4
        
        if any(sig in query for sig in multi_agent_signals):
            score += 0.3
        
        return min(score, 1.0)
    
    def _get_cached_plan(self, query: str) -> Optional[dict]:
        """获取缓存的执行计划"""
        
        conn = duckdb.connect(str(self.db_path), read_only=True)
        embedding = get_embedding(query)
        
        result = conn.execute("""
            SELECT 
                id, execution_plan, agents_involved,
                array_cosine_similarity(query_embedding, ?) as similarity
            FROM execution_plan_cache
            WHERE array_cosine_similarity(query_embedding, ?) > 0.85
            ORDER BY success_rate DESC, hit_count DESC
            LIMIT 1
        """, [embedding, embedding]).fetchone()
        
        conn.close()
        
        if result:
            plan_id, plan_json, agents, similarity = result
            print(f"🚀 FastPath: {agents} (sim={similarity:.2f})")
            
            import json
            return {
                "id": plan_id,
                "execution_plan": json.loads(plan_json)
            }
        
        return None
    
    def _cache_plan(
        self,
        query: str,
        execution_plan: dict,
        initial_route: str,
        final_route: str,
        was_upgraded: bool,
        execution_time: float
    ):
        """缓存执行计划"""
        
        conn = duckdb.connect(str(self.db_path))
        embedding = get_embedding(query)
        
        import json
        agents_involved = list(set(
            step["agent"] for step in execution_plan["steps"]
        ))
        
        # 查找相似计划
        similar = conn.execute("""
            SELECT id, hit_count, success_rate, avg_execution_time
            FROM execution_plan_cache
            WHERE array_cosine_similarity(query_embedding, ?) > 0.90
            LIMIT 1
        """, [embedding]).fetchone()
        
        if similar:
            # 更新现有计划
            plan_id, old_hits, old_rate, old_time = similar
            new_hits = old_hits + 1
            new_rate = (old_rate * old_hits + 1.0) / new_hits
            new_time = (old_time * old_hits + execution_time) / new_hits
            
            conn.execute("""
                UPDATE execution_plan_cache
                SET 
                    final_route = ?,
                    was_upgraded = ?,
                    success_rate = ?,
                    avg_execution_time = ?,
                    hit_count = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, [final_route, was_upgraded, new_rate, new_time, new_hits, plan_id])
            
            print(f"📝 Updated plan: {final_route} (hits={new_hits})")
        else:
            # 创建新计划
            conn.execute("""
                INSERT INTO execution_plan_cache
                (query_text, query_embedding, execution_plan, 
                 agents_involved, is_multi_agent, initial_route, 
                 final_route, was_upgraded, avg_execution_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                query,
                embedding,
                json.dumps(execution_plan),
                json.dumps(agents_involved),
                len(agents_involved) > 1,
                initial_route,
                final_route,
                was_upgraded,
                execution_time
            ])
            
            print(f"✨ Created plan: {final_route}")
        
        conn.close()
    
    def _update_cache_hit(self, plan_id: str):
        """更新缓存命中统计"""
        
        conn = duckdb.connect(str(self.db_path))
        
        conn.execute("""
            UPDATE execution_plan_cache
            SET 
                hit_count = hit_count + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, [plan_id])
        
        conn.close()
```

---

## 📊 执行示例

### 示例 1: 简单查询（FastPath）

```python
query = "查询 R1 的 BGP 邻居状态"

# 首次 (SlowPath: 3秒)
# LLM 调用 3 次:
# 1. 路由 + 计划生成
# 2. 质量评估（不升级）
# 3. Markdown 输出
# 缓存计划

# 第二次 (FastPath: 0.2秒)
# LLM 调用 1 次:
# 1. Markdown 输出
# 总时间: 0.2秒
```

### 示例 2: 升级场景

```python
query = "R1 和 R2 的 BGP 路由有什么差异？"

# SlowPath
# 1. 路由: db_query
# 2. 执行: 返回 10000 条路由
# 3. 评估: quality_score=0.3, should_upgrade=True
# 4. 升级: expert 分析差异
# 5. Markdown 输出
# LLM 调用 3 次，总时间约 5秒
```

### 示例 3: 跨 Agent 查询

```python
query = "R1 最近有哪些报错日志？这些报错在 NetBox 中有记录吗？"

# SlowPath
# 1. 复杂度评估: 0.6
# 2. 路由 + 计划生成:
#    Step 1: log
#    Step 2: netbox
#    Step 3: expert
# 3. 执行多步计划
# 4. Markdown 输出
# LLM 调用 2 次，总时间约 10秒
```

---

## 🎯 架构优势

### 1. 性能优化

| 场景 | LLM 调用次数 | 延迟 |
|:---|:---:|:---:|
| FastPath | 1 次 | 0.2秒 |
| 简单查询（SlowPath） | 3 次 | 3秒 |
| 升级查询 | 3 次 | 5秒 |
| 跨 Agent 查询 | 2 次 | 10秒 |

**对比旧架构**:
- ❌ 旧: Router (1 LLM) + QualityChecker (1 LLM) + ResultMerger (1 LLM) + PlanAgent (多 LLM) = 4-6 次
- ✅ 新: Orchestrator (2-3 LLM) = 2-3 次
- **减少 50% 的 LLM 调用！**

### 2. 职责清晰

```
Orchestrator 统一负责:
✅ 路由决策
✅ 执行协调
✅ 质量评估
✅ 升级决策
✅ Markdown 输出
✅ 学习缓存

Agent 只负责:
✅ 具体任务执行
✅ 返回结构化数据
```

### 3. 可扩展性

```python
# 添加新 Agent
agent_manager.register_agent("prometheus", PrometheusAgent())

# Orchestrator 自动支持:
# 1. 单 Agent 路由
# 2. 跨 Agent 联合查询
# 3. 学习缓存优化
```

---

## 🚀 实施路线图

### Phase 1: Orchestrator 核心（3天）

- [ ] 实现 `Orchestrator` 主类
- [ ] 实现执行计划缓存
- [ ] 实现 FastPath/SlowPath
- [ ] 单元测试

### Phase 2: LLM 集成（2天）

- [ ] 实现路由 + 计划生成（单 LLM 调用）
- [ ] 实现质量评估 + 升级决策（单 LLM 调用）
- [ ] 实现 Markdown 输出（单 LLM 调用）
- [ ] E2E 测试

### Phase 3: Agent 扩展（按需）

- [ ] 实现 `LogAgent`
- [ ] 实现 `NetBoxAgent`
- [ ] 其他 Agent...

---

## 📚 参考文档

- `docs/02_expert_design.md` - Expert Agent 设计
- `docs/01_db_design.md` - 数据库架构

---

**版本**: v0.9.8  
**状态**: 设计完成，准备实施  
**核心升级**: 单一 Orchestrator 替代多组件架构
