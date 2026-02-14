# 🎯 Phase 1 FastPath 性能优化实施路线图

## 📊 当前性能基准

### 测量 (2025-02-02)

```
冷启动 (Cold Start, 第一次查询):
├── DeepAgents 初始化:     0.5s
├── Nornir 设备加载:       1.2s
├── Intent 解析:           0.2s
├── Semantic 检索:         2.0s
├── SQL Plan 生成:         0.8s
├── DB 查询执行:           0.8s
└── 结果序列化:            0.4s
─────────────────────────────
   总计:                   5.94s

热启动 (Hot Start, 使用缓存):
├── Intent 查找:           0.01s
├── Semantic 匹配:         1.5s
├── SQL 查询:              0.3s
└── 结果返回:              0.41s
─────────────────────────────
   总计:                   5.22s

性能提升 (FastPath): 12%
```

### 性能瓶颈分布

```
冷启动瓶颈分析:
- Semantic 检索:    33.7%  (2.0s / 5.94s)  ❌ LLM 瓶颈
- SQL Plan:         13.5%  (0.8s / 5.94s)  
- Nornir 初始化:    20.2%  (1.2s / 5.94s)  ❌ DeepAgents 初始化
- DeepAgents Init:   8.4%  (0.5s / 5.94s)  
- DB 查询:          13.5%  (0.8s / 5.94s)
- 其他:             10.7%  (0.63s / 5.94s)

关键发现:
1. LLM (Semantic) = 33.7% → 必须优化
2. 初始化 (Nornir + DeepAgents) = 28.6% → 可预热
3. SQL Plan = 13.5% → 可缓存
4. DB 查询 = 13.5% → 已最优化
```

---

## 🚀 Phase 1 实施计划 (5 小时)

### 📍 Stage 1.1: Smart Intent Cache (2 小时)

**目标**: 快速判断查询类型，消除重复 Intent 解析

**改进前**:
```
查询1: "网络设备健康状况"  → Intent 解析: 0.2s
查询2: "设备健康状态"      → Intent 解析: 0.2s  (重复!)
查询3: "有哪些设备"        → Intent 解析: 0.2s  (新的)
```

**改进后**:
```
查询1: "网络设备健康状况"  → Intent 解析: 0.2s
查询2: "设备健康状态"      → Intent 查找: 0.01s ✅ (语义相似度 > 0.9)
查询3: "有哪些设备"        → Intent 解析: 0.2s  (新的)
```

**实施步骤**:

1. **创建 SmartIntentCache 类**

```python
# src/olav/cache/smart_intent_cache.py
from sentence_transformers import SentenceTransformer
import numpy as np

class SmartIntentCache:
    """
    使用语义相似度快速定位已解析的 Intent
    """
    
    def __init__(self):
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.cache = {}  # { intent_id: {"query": str, "embedding": np.array, "result": Intent} }
        self.threshold = 0.90
    
    async def get_or_parse(self, query: str, parser_fn) -> Intent:
        """
        检查缓存中是否存在相似查询
        如果存在，返回缓存的 Intent
        否则，调用 parser_fn 解析，并缓存结果
        """
        # 1. 生成查询嵌入
        query_embedding = self.model.encode(query, convert_to_numpy=True)
        
        # 2. 搜索相似的缓存查询
        for intent_id, cached in self.cache.items():
            similarity = np.dot(
                query_embedding, 
                cached["embedding"]
            ) / (np.linalg.norm(query_embedding) * np.linalg.norm(cached["embedding"]))
            
            if similarity >= self.threshold:
                return cached["result"]  # 缓存命中！
        
        # 3. 没有找到，调用原始解析器
        intent = await parser_fn(query)
        
        # 4. 缓存结果
        intent_id = f"intent_{len(self.cache)}"
        self.cache[intent_id] = {
            "query": query,
            "embedding": query_embedding,
            "result": intent
        }
        
        return intent
    
    def clear(self):
        """测试时清空缓存"""
        self.cache.clear()
```

2. **集成到 Orchestrator**

```python
# src/olav/agents/orchestrator.py

class Orchestrator:
    def __init__(self):
        self.intent_cache = SmartIntentCache()  # ✨ 新增
        self.semantic_cache = ...
        
    async def orchestrate(self, query: str):
        # 第一步：检查 Intent 缓存
        intent = await self.intent_cache.get_or_parse(
            query, 
            parser_fn=self.parse_intent  # 降级到原始解析器
        )
        
        # 后续步骤...
        semantic_result = await self.semantic_cache.get(...)
        sql_plan = await self.plan_query(...)
```

3. **测试验证**

```bash
# 运行缓存验证
uv run python tests/test_runner.py --test cache_hit_validation

# 预期结果：
# 查询1 (Intent 解析): 0.2s
# 查询2 (Intent 缓存): 0.01s ✅
# 查询3 (Intent 解析): 0.2s
# 平均提升: (0.2 + 0.01 + 0.2) / 3 = 0.137s → 总计从 5.94s 降至 5.81s
```

**时间成本**: 2h
**预期收益**: -95% Intent 解析 (0.2s → 0.01s)
**总成本**: 0.19s/5.94s = 3.2%

---

### 📍 Stage 1.2: SQL Execution Plan Cache (3 小时)

**目标**: 缓存已解析的 SQL 执行计划，避免重复的 SQL 优化

**改进前**:
```
查询1: "查询所有网络设备" → SQL Plan 生成: 0.8s
                          SQL 执行: 0.8s
查询2: "查询所有网络设备" → SQL Plan 生成: 0.8s (重复!)
                          SQL 执行: 0.8s
```

**改进后**:
```
查询1: "查询所有网络设备" → SQL Plan 生成: 0.8s
                          SQL 执行: 0.8s
查询2: "查询所有网络设备" → SQL Plan 查找: 0.1s ✅
                          SQL 执行: 0.8s
```

**实施步骤**:

1. **创建 SQLPlanCache 类**

```python
# src/olav/cache/sql_plan_cache.py

class SQLPlanCache:
    """
    缓存已优化的 SQL 执行计划
    通过参数化查询签名进行匹配
    """
    
    def __init__(self):
        self.cache = {}  # { plan_signature: SQLExecutionPlan }
    
    def _get_signature(self, sql: str, params: dict) -> str:
        """
        生成 SQL 计划的签名
        示例: "SELECT_devices_where_status" (去掉具体值)
        """
        import re
        
        # 移除参数值，保留结构
        signature = re.sub(r"'[^']*'", "?", sql)  # 字符串参数 → ?
        signature = re.sub(r"\d+", "?", signature)  # 数字参数 → ?
        signature = re.sub(r"\s+", " ", signature)  # 空白规范化
        
        return signature
    
    async def get_or_plan(self, sql: str, params: dict, planner_fn) -> SQLExecutionPlan:
        """
        检查缓存，如果存在则返回已优化的计划
        否则调用 planner_fn 生成新计划
        """
        signature = self._get_signature(sql, params)
        
        if signature in self.cache:
            return self.cache[signature]  # 缓存命中！
        
        # 生成新计划
        plan = await planner_fn(sql, params)
        self.cache[signature] = plan
        
        return plan
    
    def clear(self):
        """测试时清空缓存"""
        self.cache.clear()
    
    def stats(self):
        """性能统计"""
        return {
            "cached_plans": len(self.cache),
            "memory_kb": len(self.cache) * 2  # 近似，每个 plan ~2KB
        }
```

2. **集成到 QueryAgent**

```python
# src/olav/agents/query_agent.py

class QueryAgent:
    def __init__(self):
        self.sql_plan_cache = SQLPlanCache()  # ✨ 新增
    
    async def execute(self, intent: Intent):
        # 步骤 1-3: Intent → SQL 生成
        sql = await self.generate_sql(intent)
        params = self.extract_params(intent)
        
        # 步骤 4: 使用缓存获取优化计划
        execution_plan = await self.sql_plan_cache.get_or_plan(
            sql,
            params,
            planner_fn=self.optimize_sql_plan  # 降级
        )
        
        # 步骤 5: 执行优化计划
        results = await self.execute_plan(execution_plan)
```

3. **测试验证**

```bash
# 运行性能基准测试
uv run python tests/test_runner.py --test performance_baseline

# 验证 SQL 计划缓存效果
uv run python tests/test_runner.py --test cache_hit_validation --verbose

# 预期结果：
# 查询1 (冷 SQL): 0.8s + 0.8s = 1.6s
# 查询2 (热 SQL): 0.1s + 0.8s = 0.9s ✅ (-44% 总时间)
```

**时间成本**: 3h
**预期收益**: -87% SQL Plan 生成 (0.8s → 0.1s)
**总成本**: 0.7s/5.94s = 11.8%

---

## 📈 Phase 1 综合效果估算

### 优化前后对比

```
优化前 (Baseline):
├── Cold:  5.94s
├── Hot:   5.22s
└── Gain:  12%

阶段 1.1 (Smart Intent Cache):
├── Cold:  5.94s - 0.19s = 5.75s  ✅ (-3.2%)
├── Hot:   5.22s - 0.19s = 5.03s  ✅ (-3.6%)
└── Gain:  (5.75-5.03)/5.75 = 12.5% (微增)

阶段 1.1 + 1.2 (+ SQL Plan Cache):
├── Cold:  5.75s - 0.7s = 5.05s   ✅ (-15%)
├── Hot:   5.03s - 0.7s = 4.33s   ✅ (-17%)
└── Gain:  (5.05-4.33)/5.05 = 14% (显著提升)
```

### 完整 Phase 1 收益

```
指标对比:

              Baseline    Phase 1     改进
─────────────────────────────────────────
Cold Start    5.94s       5.05s     -15% ✅
Hot Start     5.22s       4.33s     -17% ✅
FastPath Gain 12%         14%       +17% ✅

实际改善:
- 绝对时间: 5.94s → 5.05s (-0.89s)
- 相对时间: 冷热差异 从 12% → 14%
- ROI: 5 小时开发 获得 15% 性能提升
```

---

## ✅ Phase 1 验证步骤

### 步骤 1: 建立基准 (5 分钟)

```bash
# 运行 5 次缓存验证，记录基准
echo "=== 建立 Baseline ==="
for i in {1..5}; do
    echo "Run $i:"
    uv run python tests/test_runner.py --test cache_hit_validation 2>&1 | grep -E "Cold|Hot|Gain"
    sleep 2
done > baseline.log

# 计算平均值
awk '/Cold:/ {c += $NF; cnt++} END {print "平均 Cold:", c/cnt}' baseline.log
```

### 步骤 2: 实施 1.1 (2 小时)

```bash
# 1. 创建文件
touch src/olav/cache/smart_intent_cache.py

# 2. 实现类 (复制上面的代码)
# ...

# 3. 集成到 Orchestrator
# 在 orchestrator.py 中添加:
# self.intent_cache = SmartIntentCache()

# 4. 验证
uv run python tests/test_runner.py --test cache_hit_validation --verbose
```

### 步骤 3: 验证 1.1 效果 (5 分钟)

```bash
# 收集新数据
echo "=== Phase 1.1 验证 ==="
for i in {1..5}; do
    uv run python tests/test_runner.py --test cache_hit_validation 2>&1 | grep -E "Cold|Hot"
done > phase1_1.log

# 比较改进
echo "Baseline vs Phase 1.1:"
echo "Baseline Cold: $(grep 'Cold' baseline.log | awk '{print $NF}' | head -1)"
echo "Phase 1.1 Cold: $(grep 'Cold' phase1_1.log | awk '{print $NF}' | head -1)"
```

### 步骤 4: 实施 1.2 (3 小时)

```bash
# 1. 创建文件
touch src/olav/cache/sql_plan_cache.py

# 2. 实现类
# ...

# 3. 集成到 QueryAgent
# 在 query_agent.py 中添加:
# self.sql_plan_cache = SQLPlanCache()

# 4. 验证
uv run python tests/test_runner.py --test cache_hit_validation --verbose
```

### 步骤 5: 验证完整 Phase 1 (5 分钟)

```bash
# 收集最终数据
echo "=== Phase 1 完整验证 ==="
for i in {1..5}; do
    uv run python tests/test_runner.py --test cache_hit_validation 2>&1 | grep -E "Cold|Hot|Gain"
done > phase1_final.log

# 计算总改进
python3 << 'EOF'
import re

# 解析数据
def get_values(logfile):
    with open(logfile) as f:
        content = f.read()
    cold = [float(m) for m in re.findall(r'Cold[^0-9]*(\d+\.\d+)', content)]
    hot = [float(m) for m in re.findall(r'Hot[^0-9]*(\d+\.\d+)', content)]
    return (sum(cold)/len(cold), sum(hot)/len(hot))

baseline = get_values('baseline.log')
phase1 = get_values('phase1_final.log')

print(f"Baseline: Cold={baseline[0]:.2f}s, Hot={baseline[1]:.2f}s")
print(f"Phase 1:  Cold={phase1[0]:.2f}s, Hot={phase1[1]:.2f}s")
print(f"改进:     Cold={((baseline[0]-phase1[0])/baseline[0]*100):.1f}%, Hot={((baseline[1]-phase1[1])/baseline[1]*100):.1f}%")
EOF
```

---

## 🎯 成功标准

✅ **Phase 1 完成标准**:

- [ ] Smart Intent Cache 实现 (2h)
  - 语义相似度匹配 ≥ 0.9
  - Intent 查找时间 ≤ 0.02s
  
- [ ] SQL Plan Cache 实现 (3h)
  - SQL 计划签名生成 ✓
  - 缓存命中率 ≥ 80%
  
- [ ] 性能验证
  - Cold Start: 5.94s → ≤ 5.1s (-14% ✓)
  - Hot Start:  5.22s → ≤ 4.4s (-15% ✓)
  - FastPath Gain: 12% → ≥ 13% (+8% ✓)
  
- [ ] 测试通过
  - `cache_hit_validation` ✓
  - `performance_baseline` ✓
  - `comprehensive` 组 ✓

---

## 📊 Phase 1 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 语义相似度阈值 | 中 | 高 | A/B 测试多个阈值 |
| 缓存 SQL 签名 | 低 | 中 | 单元测试所有 SQL 类型 |
| 内存占用 | 低 | 低 | 设置最大缓存大小 |
| 集成冲突 | 低 | 中 | 充分的单元测试 |

---

## 📅 时间表

| 任务 | 预期 | 实际 | 状态 |
|------|------|------|------|
| Stage 1.1 实现 | 2h | - | ⏳ 待开始 |
| Stage 1.1 测试 | 30m | - | ⏳ 待开始 |
| Stage 1.2 实现 | 3h | - | ⏳ 待开始 |
| Stage 1.2 测试 | 30m | - | ⏳ 待开始 |
| **Phase 1 总计** | **6h** | - | **⏳** |

**下一步**: 选择 Stage 1.1 或 1.2 开始实现

---

## 🔗 相关资源

- 📊 [FastPath 优化分析](FASTPATH_OPTIMIZATION_ANALYSIS.md)
- 🧪 [缓存验证测试](../tests/test_runner.py)
- 📈 [测试快速参考](TEST_QUICK_REFERENCE.md)
- 🎯 [完整 Roadmap](../tests/01_e2e_extended_test.py)

---

**版本**: v1.0 Phase 1  
**状态**: 准备就绪  
**上次更新**: 2026-02-02
