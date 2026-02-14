# 🛠️ Phase 1 实施检查清单

## 📋 实施前准备

- [ ] 代码审查
  - [ ] 阅读 `PERFORMANCE_OPTIMIZATION_PHASE1_ROADMAP.md`
  - [ ] 理解 4 层缓存架构
  - [ ] 明确 15% 改进目标

- [ ] 环境准备
  - [ ] 创建 feature 分支: `git checkout -b optimize/fastpath-phase1`
  - [ ] 安装依赖: `pip install sentence-transformers`
  - [ ] 备份 baseline: `uv run python tests/test_runner.py --group cache_validation > baseline_before.txt`

- [ ] 建立测试基准
  ```bash
  # 运行 5 次缓存验证，获取稳定的基准
  for i in {1..5}; do
    uv run python tests/test_runner.py --test cache_hit_validation --verbose
    sleep 3
  done 2>&1 | tee baseline_measurements.log
  ```

---

## 🔧 Stage 1.1: Smart Intent Cache (2 小时)

### Task 1.1.1: 创建 SmartIntentCache 类

**文件**: `src/olav/cache/smart_intent_cache.py`

```python
"""
Smart Intent Cache - 快速语义相似度匹配
使用 sentence-transformers 快速定位已解析的 Intent
"""

import hashlib
import logging
from typing import Callable, Optional, Dict, Any
import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

class SmartIntentCache:
    """
    使用语义相似度的 Intent 缓存
    
    特性:
    - 自动语义匹配 (不需要完全相同查询)
    - 阈值可配置
    - 内存管理 (可设置最大缓存大小)
    - 性能指标 (hit_rate, 平均查询时间)
    """
    
    def __init__(self, threshold: float = 0.90, max_cache_size: int = 1000):
        """
        Args:
            threshold: 语义相似度阈值 (0-1), 越高越严格
            max_cache_size: 最大缓存条目数
        """
        self.threshold = threshold
        self.max_cache_size = max_cache_size
        
        # 初始化模型 (一次性加载到内存)
        try:
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("SmartIntentCache: 模型加载成功")
        except Exception as e:
            logger.warning(f"SmartIntentCache: 模型加载失败 {e}, 使用降级模式")
            self.model = None
        
        # 缓存存储
        self.cache: Dict[str, Dict[str, Any]] = {}
        
        # 性能指标
        self.stats = {
            "total_lookups": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "avg_query_time": 0.0
        }
    
    def _get_hash(self, query: str) -> str:
        """生成查询哈希值"""
        return hashlib.md5(query.encode()).hexdigest()[:8]
    
    async def get_or_parse(self, query: str, parser_fn: Callable) -> Any:
        """
        获取已缓存的 Intent，或调用 parser_fn 解析新的 Intent
        
        Args:
            query: 用户查询
            parser_fn: 降级函数，如果没有缓存则调用此函数
        
        Returns:
            解析后的 Intent
        """
        import time
        start_time = time.time()
        self.stats["total_lookups"] += 1
        
        # 如果模型不可用，直接调用原始解析器
        if self.model is None:
            return await parser_fn(query)
        
        try:
            # 1. 生成查询嵌入
            query_embedding = self.model.encode(query, convert_to_numpy=True)
            
            # 2. 搜索缓存中的相似查询
            best_match = None
            best_similarity = 0.0
            
            for cache_id, cached_entry in self.cache.items():
                # 计算余弦相似度
                similarity = self._cosine_similarity(
                    query_embedding,
                    cached_entry["embedding"]
                )
                
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = cached_entry
            
            # 3. 检查是否达到阈值
            if best_similarity >= self.threshold:
                logger.debug(
                    f"Intent 缓存命中 (相似度: {best_similarity:.3f}, "
                    f"原查询: '{best_match['query']}', 当前查询: '{query}')"
                )
                self.stats["cache_hits"] += 1
                elapsed = time.time() - start_time
                self.stats["avg_query_time"] = (
                    self.stats["avg_query_time"] * (self.stats["cache_hits"] - 1) 
                    + elapsed
                ) / self.stats["cache_hits"]
                return best_match["result"]
            
            # 4. 缓存未命中，调用原始解析器
            logger.debug(f"Intent 缓存未命中，调用原始解析器")
            self.stats["cache_misses"] += 1
            intent = await parser_fn(query)
            
            # 5. 将结果加入缓存
            if len(self.cache) >= self.max_cache_size:
                # 移除最早的缓存条目 (FIFO)
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
                logger.debug(f"缓存已满，移除最早条目")
            
            cache_id = self._get_hash(query)
            self.cache[cache_id] = {
                "query": query,
                "embedding": query_embedding,
                "result": intent,
                "timestamp": time.time()
            }
            
            logger.debug(f"缓存新 Intent (查询: '{query}', 缓存大小: {len(self.cache)})")
            elapsed = time.time() - start_time
            self.stats["avg_query_time"] = (
                self.stats["avg_query_time"] * (self.stats["total_lookups"] - 1)
                + elapsed
            ) / self.stats["total_lookups"]
            
            return intent
        
        except Exception as e:
            logger.error(f"SmartIntentCache 异常: {e}, 使用原始解析器")
            return await parser_fn(query)
    
    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """计算两个向量的余弦相似度"""
        try:
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return float(np.dot(vec1, vec2) / (norm1 * norm2))
        except Exception as e:
            logger.error(f"余弦相似度计算异常: {e}")
            return 0.0
    
    def clear(self):
        """清空缓存 (测试时使用)"""
        self.cache.clear()
        logger.debug("SmartIntentCache 已清空")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return {
            **self.stats,
            "cache_size": len(self.cache),
            "hit_rate": (
                self.stats["cache_hits"] / self.stats["total_lookups"]
                if self.stats["total_lookups"] > 0 else 0.0
            )
        }
```

**检查项**:
- [ ] 文件创建: `src/olav/cache/smart_intent_cache.py`
- [ ] 类实现: `SmartIntentCache` 完成
- [ ] 导入验证: `from sentence_transformers import SentenceTransformer` ✓
- [ ] 日志配置: 使用 `logger` 而不是 `print`
- [ ] 错误处理: try/except 完整
- [ ] 文档完整: docstring 详细

---

### Task 1.1.2: 集成到 Orchestrator

**文件**: `src/olav/agents/orchestrator.py`

**修改位置**: Orchestrator 类的 `__init__` 方法

```python
# 在 orchestrator.py 中找到：
class Orchestrator:
    def __init__(self, config: OrchestratorConfig = None):
        # ... 现有初始化代码 ...
        
        # ✨ 添加以下行：
        from ..cache.smart_intent_cache import SmartIntentCache
        self.intent_cache = SmartIntentCache(
            threshold=0.90,
            max_cache_size=1000
        )
```

**修改位置**: Orchestrator 的 `orchestrate` 方法

找到这样的代码：
```python
async def orchestrate(self, query: str):
    # 第一步：解析意图
    intent = await self.parse_intent(query)
```

替换为：
```python
async def orchestrate(self, query: str):
    # 第一步：使用缓存获取意图
    intent = await self.intent_cache.get_or_parse(
        query,
        parser_fn=self.parse_intent  # 降级到原始解析器
    )
```

**检查项**:
- [ ] 导入语句添加
- [ ] SmartIntentCache 实例化
- [ ] parse_intent 调用替换为 intent_cache.get_or_parse
- [ ] 类型检查通过: `pyright src/olav/agents/orchestrator.py`
- [ ] 旧代码备份: `git diff src/olav/agents/orchestrator.py`

---

### Task 1.1.3: 单元测试

**文件**: `tests/unit/test_smart_intent_cache.py`

```python
import pytest
import asyncio
from src.olav.cache.smart_intent_cache import SmartIntentCache

@pytest.fixture
def cache():
    return SmartIntentCache(threshold=0.90)

@pytest.mark.asyncio
async def test_cache_hit_exact_match(cache):
    """测试完全相同查询的缓存命中"""
    
    async def dummy_parser(query: str):
        return {"intent": "test", "query": query}
    
    # 第一次调用 - 缓存未命中
    result1 = await cache.get_or_parse("网络设备健康状况", dummy_parser)
    stats1 = cache.get_stats()
    assert stats1["cache_misses"] == 1
    assert stats1["cache_hits"] == 0
    
    # 第二次相同查询 - 应该缓存命中
    result2 = await cache.get_or_parse("网络设备健康状况", dummy_parser)
    stats2 = cache.get_stats()
    assert stats2["cache_hits"] == 1
    assert result1 == result2

@pytest.mark.asyncio
async def test_cache_hit_semantic_match(cache):
    """测试语义相似查询的缓存命中"""
    
    async def dummy_parser(query: str):
        return {"intent": "test", "query": query}
    
    # 第一次调用
    result1 = await cache.get_or_parse("网络设备健康状况", dummy_parser)
    
    # 第二次调用 - 语义相似但措辞不同
    result2 = await cache.get_or_parse("设备健康状态", dummy_parser)
    stats = cache.get_stats()
    
    # 相似度 > 0.9，应该缓存命中
    assert stats["cache_hits"] >= 1

@pytest.mark.asyncio
async def test_cache_miss_dissimilar(cache):
    """测试不相似查询的缓存未命中"""
    
    async def dummy_parser(query: str):
        return {"intent": "test", "query": query}
    
    result1 = await cache.get_or_parse("网络设备健康", dummy_parser)
    result2 = await cache.get_or_parse("有哪些主机", dummy_parser)
    
    stats = cache.get_stats()
    assert stats["cache_misses"] == 2  # 两个都是新查询

def test_cache_clear(cache):
    """测试缓存清空"""
    cache.cache["test_key"] = {"query": "test", "embedding": None, "result": {}}
    assert len(cache.cache) == 1
    
    cache.clear()
    assert len(cache.cache) == 0

def test_cache_stats(cache):
    """测试统计信息"""
    stats = cache.get_stats()
    assert "cache_size" in stats
    assert "hit_rate" in stats
    assert "total_lookups" in stats
```

**运行测试**:
```bash
uv run pytest tests/unit/test_smart_intent_cache.py -v
```

**检查项**:
- [ ] 文件创建: `tests/unit/test_smart_intent_cache.py`
- [ ] 单元测试通过: `pytest -v`
- [ ] 代码覆盖率 > 90%

---

### Task 1.1.4: 验证性能提升

**测试脚本**: `tests/verify_phase1_1.sh`

```bash
#!/bin/bash

echo "=== Phase 1.1 验证: Smart Intent Cache ==="
echo "时间: $(date)"
echo ""

# 1. 构建基准
echo "📊 构建基准 (5 次运行)..."
echo "Cold,Hot,Gain" > phase1_1_results.csv

for i in {1..5}; do
    echo "  运行 $i/5..."
    uv run python tests/test_runner.py --test cache_hit_validation --verbose 2>&1 | grep -E "Cold|Hot|Gain" | awk -F': ' '{print $2}' | tr '\n' ',' >> phase1_1_results.csv
    echo "" >> phase1_1_results.csv
    sleep 2
done

# 2. 分析结果
echo ""
echo "📈 结果分析:"
python3 << 'EOF'
import csv
import statistics

with open('phase1_1_results.csv') as f:
    reader = csv.reader(f)
    next(reader)  # 跳过标题
    
    colds = []
    hots = []
    gains = []
    
    for row in reader:
        if len(row) >= 3:
            colds.append(float(row[0].replace('s', '')))
            hots.append(float(row[1].replace('s', '')))
            gains.append(float(row[2].replace('%', '')))
    
    print(f"Cold Start (平均): {statistics.mean(colds):.2f}s (±{statistics.stdev(colds) if len(colds) > 1 else 0:.2f}s)")
    print(f"Hot Start (平均):  {statistics.mean(hots):.2f}s (±{statistics.stdev(hots) if len(hots) > 1 else 0:.2f}s)")
    print(f"FastPath Gain:    {statistics.mean(gains):.1f}%")
    print("")
    print(f"✅ Smart Intent Cache 集成完成")
    print(f"   缓存命中率: 看 logs 中的 'cache_hits / total_lookups'")
EOF

echo ""
echo "✨ Phase 1.1 验证完成"
```

**运行验证**:
```bash
chmod +x tests/verify_phase1_1.sh
./tests/verify_phase1_1.sh
```

**检查项**:
- [ ] 验证脚本运行成功
- [ ] Cold Start 改进 ≥ 3%
- [ ] 缓存命中率显示在日志中
- [ ] 数据记录在 CSV 文件中

---

### Task 1.1.5: 代码审查 & 提交

```bash
# 1. 代码格式化
uv run ruff format src/olav/cache/smart_intent_cache.py
uv run ruff check src/olav/cache/smart_intent_cache.py --fix

# 2. 类型检查
uv run pyright src/olav/cache/smart_intent_cache.py

# 3. 查看变更
git diff src/olav/agents/orchestrator.py
git diff src/olav/cache/

# 4. 提交
git add src/olav/cache/smart_intent_cache.py
git add src/olav/agents/orchestrator.py
git commit -m "feat: Add SmartIntentCache for 3% FastPath improvement

- Implement semantic similarity matching using sentence-transformers
- Cache hits reduce Intent parsing by 95% (0.2s -> 0.01s)
- Expected improvement: 3.2% cold start time reduction
- Fallback to original parser if model unavailable"
```

**检查项**:
- [ ] 代码格式化通过
- [ ] 类型检查通过 (pyright)
- [ ] Lint 检查通过 (ruff)
- [ ] 提交信息清晰

---

## 🔧 Stage 1.2: SQL Execution Plan Cache (3 小时)

### Task 1.2.1: 创建 SQLPlanCache 类

**文件**: `src/olav/cache/sql_plan_cache.py`

```python
"""
SQL Execution Plan Cache
缓存已优化的 SQL 执行计划，避免重复的 SQL 优化
"""

import re
import hashlib
import logging
from typing import Dict, Optional, Any, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class SQLExecutionPlan:
    """SQL 执行计划"""
    sql: str
    params: Dict[str, Any]
    query_type: str  # SELECT, UPDATE, DELETE, etc.
    indexed_columns: list
    estimated_rows: int
    optimization_hints: Dict[str, Any]

class SQLPlanCache:
    """
    缓存已优化的 SQL 执行计划
    
    特性:
    - SQL 参数化签名匹配
    - 自动识别查询类型
    - 缓存统计 (命中率、大小、加载时间)
    - 内存管理
    """
    
    def __init__(self, max_cache_size: int = 500):
        """
        Args:
            max_cache_size: 最大缓存计划数
        """
        self.max_cache_size = max_cache_size
        self.cache: Dict[str, SQLExecutionPlan] = {}
        
        # 统计
        self.stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "avg_planning_time": 0.0
        }
    
    def _get_signature(self, sql: str) -> str:
        """
        生成 SQL 的参数化签名
        
        示例:
            SELECT * FROM devices WHERE status='active' AND age > 30
            →
            SELECT * FROM devices WHERE status=? AND age>?
        """
        # 移除多余空白
        normalized_sql = re.sub(r'\s+', ' ', sql.strip()).upper()
        
        # 替换字符串字面值
        normalized_sql = re.sub(r"'[^']*'", "?", normalized_sql)
        normalized_sql = re.sub(r'"[^"]*"', "?", normalized_sql)
        
        # 替换数字字面值
        normalized_sql = re.sub(r'\b\d+\b', '?', normalized_sql)
        
        # 生成哈希值
        signature = hashlib.md5(normalized_sql.encode()).hexdigest()[:16]
        return signature
    
    def _detect_query_type(self, sql: str) -> str:
        """检测 SQL 查询类型"""
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("SELECT"):
            return "SELECT"
        elif sql_upper.startswith("UPDATE"):
            return "UPDATE"
        elif sql_upper.startswith("DELETE"):
            return "DELETE"
        elif sql_upper.startswith("INSERT"):
            return "INSERT"
        else:
            return "UNKNOWN"
    
    async def get_or_plan(
        self,
        sql: str,
        params: Dict[str, Any],
        planner_fn: Callable
    ) -> SQLExecutionPlan:
        """
        获取缓存的执行计划，或调用 planner_fn 生成新计划
        
        Args:
            sql: SQL 查询
            params: 查询参数
            planner_fn: 降级函数，生成执行计划
        
        Returns:
            SQLExecutionPlan 执行计划
        """
        import time
        
        start_time = time.time()
        self.stats["total_requests"] += 1
        
        # 生成签名
        signature = self._get_signature(sql)
        
        # 检查缓存
        if signature in self.cache:
            logger.debug(f"SQL Plan 缓存命中 (签名: {signature})")
            self.stats["cache_hits"] += 1
            return self.cache[signature]
        
        # 缓存未命中，生成新计划
        logger.debug(f"SQL Plan 缓存未命中，生成新计划")
        self.stats["cache_misses"] += 1
        
        try:
            plan = await planner_fn(sql, params)
            
            # 限制缓存大小
            if len(self.cache) >= self.max_cache_size:
                # 移除最早的缓存条目
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
                logger.debug(f"SQL Plan 缓存已满，移除最早条目")
            
            # 保存到缓存
            self.cache[signature] = plan
            logger.debug(
                f"缓存新 SQL Plan (类型: {self._detect_query_type(sql)}, "
                f"缓存大小: {len(self.cache)})"
            )
            
            elapsed = time.time() - start_time
            self.stats["avg_planning_time"] = (
                self.stats["avg_planning_time"] * (self.stats["total_requests"] - 1)
                + elapsed
            ) / self.stats["total_requests"]
            
            return plan
        
        except Exception as e:
            logger.error(f"SQL Plan 生成异常: {e}")
            raise
    
    def clear(self):
        """清空缓存 (测试时使用)"""
        self.cache.clear()
        logger.debug("SQLPlanCache 已清空")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            **self.stats,
            "cache_size": len(self.cache),
            "hit_rate": (
                self.stats["cache_hits"] / self.stats["total_requests"]
                if self.stats["total_requests"] > 0 else 0.0
            ),
            "memory_kb": len(self.cache) * 2  # 近似
        }
```

**检查项**:
- [ ] 文件创建
- [ ] 类实现完整
- [ ] 签名生成逻辑正确
- [ ] 错误处理完善
- [ ] 文档详细

---

### Task 1.2.2: 集成到 QueryAgent

**修改位置**: `src/olav/agents/query_agent.py`

```python
# 在 QueryAgent 类的 __init__ 中添加：
from ..cache.sql_plan_cache import SQLPlanCache

class QueryAgent:
    def __init__(self):
        # ... 现有代码 ...
        self.sql_plan_cache = SQLPlanCache(max_cache_size=500)
```

**修改位置**: QueryAgent 的 SQL 执行逻辑

找到：
```python
async def execute(self, intent: Intent):
    sql = await self.generate_sql(intent)
    execution_plan = await self.optimize_sql_plan(sql, params)
```

替换为：
```python
async def execute(self, intent: Intent):
    sql = await self.generate_sql(intent)
    params = self.extract_params(intent)
    
    # 使用缓存获取优化计划
    execution_plan = await self.sql_plan_cache.get_or_plan(
        sql,
        params,
        planner_fn=self.optimize_sql_plan
    )
```

**检查项**:
- [ ] 导入添加
- [ ] 实例初始化
- [ ] 调用替换
- [ ] 类型检查通过

---

### Task 1.2.3: 单元测试

**文件**: `tests/unit/test_sql_plan_cache.py`

```python
import pytest
from src.olav.cache.sql_plan_cache import SQLPlanCache, SQLExecutionPlan

@pytest.fixture
def cache():
    return SQLPlanCache()

def test_signature_generation(cache):
    """测试签名生成"""
    
    sql1 = "SELECT * FROM devices WHERE status='active' AND age > 30"
    sql2 = "SELECT * FROM devices WHERE status='inactive' AND age > 40"
    sql3 = "SELECT * FROM devices WHERE city='beijing'"
    
    sig1 = cache._get_signature(sql1)
    sig2 = cache._get_signature(sql2)
    sig3 = cache._get_signature(sql3)
    
    # 参数化了数值和字符串，所以 sig1 和 sig2 应该相同
    assert sig1 == sig2
    
    # sig3 是不同的 SQL 结构
    assert sig1 != sig3

def test_query_type_detection(cache):
    """测试查询类型检测"""
    
    assert cache._detect_query_type("SELECT * FROM devices") == "SELECT"
    assert cache._detect_query_type("UPDATE devices SET status='up'") == "UPDATE"
    assert cache._detect_query_type("DELETE FROM devices WHERE id=1") == "DELETE"
    assert cache._detect_query_type("INSERT INTO devices VALUES(...)") == "INSERT"

@pytest.mark.asyncio
async def test_cache_hit(cache):
    """测试缓存命中"""
    
    async def dummy_planner(sql: str, params: dict):
        return SQLExecutionPlan(
            sql=sql,
            params=params,
            query_type="SELECT",
            indexed_columns=["id"],
            estimated_rows=100,
            optimization_hints={}
        )
    
    sql = "SELECT * FROM devices WHERE status='active'"
    params = {"status": "active"}
    
    # 第一次调用
    plan1 = await cache.get_or_plan(sql, params, dummy_planner)
    stats1 = cache.get_stats()
    assert stats1["cache_misses"] == 1
    assert stats1["cache_hits"] == 0
    
    # 第二次相同查询
    plan2 = await cache.get_or_plan(sql, params, dummy_planner)
    stats2 = cache.get_stats()
    assert stats2["cache_hits"] == 1
    assert plan1 == plan2

def test_cache_clear(cache):
    """测试缓存清空"""
    cache.cache["test"] = SQLExecutionPlan("", {}, "", [], 0, {})
    assert len(cache.cache) == 1
    
    cache.clear()
    assert len(cache.cache) == 0
```

**运行测试**:
```bash
uv run pytest tests/unit/test_sql_plan_cache.py -v
```

**检查项**:
- [ ] 文件创建
- [ ] 测试通过
- [ ] 代码覆盖率 > 90%

---

### Task 1.2.4: 验证性能提升

**脚本**: `tests/verify_phase1_2.sh`

```bash
#!/bin/bash

echo "=== Phase 1.2 验证: SQL Plan Cache ==="
echo "时间: $(date)"
echo ""

# 运行性能基准测试
echo "📊 运行性能基准..."
for i in {1..5}; do
    echo "  运行 $i/5..."
    uv run python tests/test_runner.py --test performance_baseline --verbose 2>&1
    sleep 2
done | tee phase1_2_results.log

echo ""
echo "✨ Phase 1.2 验证完成"
echo ""
echo "预期改进:"
echo "- SQL Plan 生成: 0.8s → 0.1s (-87%)"
echo "- 总时间: 5.94s → 5.05s (-15%)"
```

---

### Task 1.2.5: 完整验证 & 提交

```bash
# 1. 完整测试
uv run pytest tests/test_runner.py --group comprehensive -v

# 2. 性能验证
uv run python tests/test_runner.py --test cache_hit_validation --verbose

# 3. 查看统计
grep "hit_rate\|avg_planning_time" phase1_2_results.log

# 4. 提交
git add src/olav/cache/sql_plan_cache.py
git add src/olav/agents/query_agent.py
git commit -m "feat: Add SQLPlanCache for 12% FastPath improvement

- Implement parameterized SQL signature matching
- Cache query plans to avoid redundant optimization
- Expected improvement: 12% total cold start reduction
- Combined with SmartIntentCache: 15% improvement"

# 5. 合并到 main
git push origin optimize/fastpath-phase1
# 创建 PR 等待审核
```

---

## ✅ Phase 1 完成检查清单

**代码实施**:
- [ ] SmartIntentCache 完整实现
- [ ] SQLPlanCache 完整实现
- [ ] Orchestrator 集成
- [ ] QueryAgent 集成
- [ ] 单元测试通过 (>90% 覆盖)

**性能验证**:
- [ ] Cold Start: 5.94s → ≤ 5.1s ✅
- [ ] Hot Start: 5.22s → ≤ 4.4s ✅
- [ ] FastPath Gain: 12% → ≥ 13% ✅
- [ ] Cache Hit Rate: ≥ 70%

**质量保证**:
- [ ] 代码格式化通过 (ruff)
- [ ] 类型检查通过 (pyright)
- [ ] Lint 检查通过
- [ ] 所有测试通过 (comprehensive 组)
- [ ] 文档更新

**提交**:
- [ ] 代码审查通过
- [ ] PR 合并到 main
- [ ] 性能指标记录在案

---

## 📊 预期收益总结

```
        Baseline    Phase 1.1   Phase 1.2    Phase 1 总
────────────────────────────────────────────────────────
Cold    5.94s       5.81s       5.05s       5.05s (-15%)
Hot     5.22s       5.09s       4.33s       4.33s (-17%)
FastPath 12%        12.5%       14%         14% (+17%)

时间投入: 5 小时
性能收益: 0.89s / 5.94s = 15% 改进
ROI: 15% / 5h = 3% 改进/小时
```

---

**版本**: v1.0  
**状态**: 准备就绪  
**下一步**: 开始 Task 1.1.1
