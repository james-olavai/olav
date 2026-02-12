# Items 1-7 快速参考指南

快速了解和使用Phase 6.4-10的7个模块

---

## 📌 Item 1: Plan Execution Bridge

**用途**: 批准和执行计划

```python
from olav.core.plan_execution_bridge import get_plan_execution_bridge

bridge = get_plan_execution_bridge()

# 创建计划
plan = bridge.create_execution_plan(
    plan_id="demo_1",
    user_intent="Query devices and analyze",
    steps=[
        {"name": "QueryAgent", "subagent": "query_subagent"},
        {"name": "AnalyzerAgent", "subagent": "analyzer_subagent"}
    ]
)

# 执行计划
async def my_executor(step):
    # 实现SubAgent执行逻辑
    return {"status": "success", "data": "..."}

results = await bridge.approve_and_execute(plan, my_executor)
```

**关键方法**:
- `create_execution_plan()` → ExecutionPlan
- `approve_and_execute()` → 执行结果
- `get_execution_history()` → 历史查询

---

## 📌 Item 2: Execution History Storage

**用途**: 持久化执行历史到SQLite

```python
from olav.core.execution_history_storage import get_execution_history_storage

storage = get_execution_history_storage()

# 存储计划执行
storage.store_execution(
    plan_id="demo_1",
    user_intent="Query analysis",
    execution_data={
        "execution_started": "2025-01-xx...",
        "execution_ended": "2025-01-xx...",
        "total_duration": 2.5,
        "success_count": 2,
        "error_count": 0,
        "status": "completed"
    }
)

# 存储步骤执行(自动计算时序数据)
storage.store_step_execution(
    plan_id="demo_1",
    step_name="QueryAgent",
    step_order=0,
    subagent_name="query_subagent",
    actual_duration=1.2,
    estimated_duration=1.0,
    status="completed"
)

# 查询时序数据
timing_history = storage.get_step_timing_history("QueryAgent", limit=100)

# 查询平均耗时
avg_duration = storage.get_average_step_duration("QueryAgent")

# 查询风险评估
risk_records = storage.get_risk_assessments(limit=50)

# 清理90天前的数据
storage.clear_old_data(days=90)
```

**关键方法**:
- `store_execution()` → 计划级存储
- `store_step_execution()` → 步骤级存储
- `get_step_timing_history()` → 时序查询
- `clear_old_data()` → 数据保留

---

## 📌 Item 3: Time Estimation Learner

**用途**: 从历史数据学习改进时间估计

```python
from olav.core.time_estimation_learner import TimeEstimationLearner

learner = TimeEstimationLearner(min_samples=5)

# 分析时序记录
timing_records = [
    {"estimated_ms": 1000, "actual_ms": 1050, "error_percent": 5},
    {"estimated_ms": 1000, "actual_ms": 1100, "error_percent": 10},
    # ... 更多记录
]

analysis = learner.analyze_timing_history(timing_records)

# 返回:
# {
#     "sufficient_data": True,      # 数据充足?
#     "confidence": 0.85,           # 置信度 0-1
#     "adjusted_estimate": 1075,    # 调整后估计
#     "recommendation": "..."       # 建议
# }

if analysis["sufficient_data"]:
    new_estimate = analysis["adjusted_estimate"]
```

**关键方法**:
- `analyze_timing_history()` → 完整分析

---

## 📌 Item 4: Risk Prediction Learner

**用途**: 评估风险预测准确性

```python
from olav.core.risk_prediction_learner import RiskPredictionLearner

learner = RiskPredictionLearner(min_samples=10)

# 分析风险预测历史
risk_records = [
    {"estimated_risk_score": 8.0, "actual_risk_occurred": True},
    {"estimated_risk_score": 4.0, "actual_risk_occurred": False},
    # ... 更多记录
]

analysis = learner.analyze_risk_history(risk_records)

# 返回:
# {
#     "sufficient_data": True,
#     "overall_accuracy": 0.85,
#     "high_risk_accuracy": 0.9,
#     "confidence": 0.82,
#     "recommendation": "..."
# }
```

**关键方法**:
- `analyze_risk_history()` → 完整分析

---

## 📌 Item 5: Execution Dashboard

**用途**: 计算性能指标和生成报告

```python
from olav.core.execution_dashboard import ExecutionDashboard, PerformanceMetrics

dashboard = ExecutionDashboard()

# 计算指标
execution_records = [
    {
        "execution_id": "exec_1",
        "status": "completed",
        "duration": 5.2,
        "created_at": datetime.now()
    },
    # ... 更多记录
]

metrics = dashboard.calculate_metrics(execution_records, period="daily")

# 生成报告
report = dashboard.generate_performance_report(metrics)
# 返回: Markdown格式报告

# 查询趋势
trend = dashboard.get_trend_data(execution_records, days=30)

# 生成摘要卡片
summary = dashboard.generate_summary_card()
```

**关键方法**:
- `calculate_metrics()` → PerformanceMetrics
- `generate_performance_report()` → Markdown

---

## 📌 Item 6: Performance Optimizer

**用途**: 缓存、并行执行、内存优化

### 子模块1: 缓存管理
```python
from olav.core.performance_optimizer import PlanCacheManager

cache = PlanCacheManager(ttl_seconds=3600)

# 存储
cache.set("query_key", {"result": [...]})

# 检索
result = cache.get("query_key")

# 统计
stats = cache.get_stats()
# {"cached_items": 10, "hits": 45, "misses": 5, "hit_rate": 90.0}
```

### 子模块2: 并行执行
```python
from olav.core.performance_optimizer import ParallelExecutor

executor = ParallelExecutor(max_workers=4)

steps = [
    {"name": "step_1", "requires": []},
    {"name": "step_2", "requires": []},
    {"name": "step_3", "requires": ["step_1"]},  # 依赖step_1
]

async def task_func(step):
    # 执行逻辑
    return {"status": "success"}

results = await executor.execute_parallel_steps(steps, task_func)
# 自动处理依赖和并行化
```

### 子模块3: 内存优化
```python
from olav.core.performance_optimizer import MemoryOptimizer

optimizer = MemoryOptimizer()

# 内存估计
estimated = optimizer.estimate_memory_usage("query", param_count=100)

# 流式决策
should_stream = optimizer.should_stream_results(data_size_mb=100)
```

### 完整协调器
```python
from olav.core.performance_optimizer import PerformanceOptimizer

optimizer = PerformanceOptimizer()

# 集成优化
results = await optimizer.optimize_execution(steps, executor, cache)
```

**关键类**:
- `PlanCacheManager` → 缓存
- `ParallelExecutor` → 并行
- `MemoryOptimizer` → 内存
- `PerformanceOptimizer` → 协调

---

## 📌 Item 7: Internationalization

**用途**: 多语言支持

```python
from olav.core.i18n_manager import LocalizationManager, Language

# 创建管理器
i18n = LocalizationManager(Language.CHINESE_SIMPLIFIED)

# 获取消息
msg = i18n.get_message("execution_completed")
# → "执行完成"

# 格式化数据
duration = i18n.format_duration(45.0)
# 中文: "45.0秒"
# 英文: "45.0s"

percentage = i18n.format_percentage(0.95)
# → "95.0%"

number = i18n.format_number(12345.6789, decimal_places=2)
# → 根据语言格式化
```

**支持的语言**:
```python
Language.ENGLISH              # 英文 ✅
Language.CHINESE_SIMPLIFIED   # 简体中文 ✅
Language.CHINESE_TRADITIONAL  # 繁体中文
Language.SPANISH              # 西班牙语
Language.FRENCH               # 法语
Language.GERMAN               # 德语
Language.JAPANESE             # 日语
```

**关键方法**:
- `get_message()` → 获取翻译
- `format_duration()` → 时间格式
- `format_percentage()` → 百分比格式
- `format_number()` → 数字格式

---

## 🔗 集成示例: 完整工作流

```python
import asyncio
from datetime import datetime, timedelta
from olav.core.plan_execution_bridge import get_plan_execution_bridge
from olav.core.execution_history_storage import get_execution_history_storage
from olav.core.time_estimation_learner import TimeEstimationLearner
from olav.core.execution_dashboard import ExecutionDashboard
from olav.core.performance_optimizer import PerformanceOptimizer
from olav.core.i18n_manager import LocalizationManager, Language

async def complete_workflow():
    # 1. 创建和执行计划
    bridge = get_plan_execution_bridge()
    plan = bridge.create_execution_plan(
        plan_id="workflow_1",
        user_intent="Complete analysis",
        steps=[{"name": "Query", "subagent": "query_sa"}]
    )
    
    async def executor(step):
        await asyncio.sleep(0.1)
        return {"status": "success"}
    
    results = await bridge.approve_and_execute(plan, executor)
    
    # 2. 存储历史
    storage = get_execution_history_storage()
    storage.store_execution(
        plan_id="workflow_1",
        user_intent="Complete analysis",
        execution_data={
            "execution_started": datetime.now().isoformat(),
            "execution_ended": datetime.now().isoformat(),
            "total_duration": 0.1,
            "success_count": 1,
            "error_count": 0,
            "status": "completed"
        }
    )
    
    # 3. 学习时间估计
    timing_records = [
        {"estimated_ms": 100, "actual_ms": 105, "error_percent": 5},
    ]
    learner = TimeEstimationLearner()
    time_analysis = learner.analyze_timing_history(timing_records)
    
    # 4. 生成报告
    dashboard = ExecutionDashboard()
    records = [{"execution_id": "workflow_1", "status": "completed", 
                "duration": 0.1, "created_at": datetime.now()}]
    metrics = dashboard.calculate_metrics(records)
    report = dashboard.generate_performance_report(metrics)
    
    # 5. 国际化输出
    i18n = LocalizationManager(Language.CHINESE_SIMPLIFIED)
    translated_report = i18n.get_message("execution_completed")
    
    print(f"✅ 工作流完成")
    print(f"   时间学习: {time_analysis}")
    print(f"   报告大小: {len(report)}字符")

# 运行
asyncio.run(complete_workflow())
```

---

## 📊 快速查询表

| 需求 | 模块 | 方法 |
|------|------|------|
| 执行计划 | Item 1 | `create_execution_plan()` |
| 保存执行历史 | Item 2 | `store_execution()` |
| 查询执行历史 | Item 2 | `get_step_timing_history()` |
| 改进时间估计 | Item 3 | `analyze_timing_history()` |
| 评估风险预测 | Item 4 | `analyze_risk_history()` |
| 计算性能指标 | Item 5 | `calculate_metrics()` |
| 生成性能报告 | Item 5 | `generate_performance_report()` |
| 缓存查询结果 | Item 6 | `cache.set()` / `cache.get()` |
| 并行执行步骤 | Item 6 | `execute_parallel_steps()` |
| 模内存使用 | Item 6 | `estimate_memory_usage()` |
| 国际化输出 | Item 7 | `get_message()` |
| 格式化数据 | Item 7 | `format_duration()` 等 |

---

## ⚡ 常见任务

### 保存执行结果并立即分析
```python
storage.store_execution(plan_id, intent, exec_data)
storage.store_step_execution(plan_id, step_name, 0, subagent, actual, estimated, "completed")

timing_history = storage.get_step_timing_history(step_name)
learner = TimeEstimationLearner()
analysis = learner.analyze_timing_history(timing_history)
```

### 生成周报告
```python
all_executions = storage.get_all_executions(days=7)
dashboard = ExecutionDashboard()
metrics = dashboard.calculate_metrics(all_executions, period="weekly")
report = dashboard.generate_performance_report(metrics)

# 国际化版本
i18n = LocalizationManager(Language.CHINESE_SIMPLIFIED)
# 在报告中使用i18n.format_duration()等
```

### 优化下一次执行
```python
# 获取学习建议
time_analysis = learner.analyze_timing_history(timing_records)
new_estimated_time = time_analysis["adjusted_estimate"]

risk_analysis = risk_learner.analyze_risk_history(risk_records)
new_risk_score = risk_analysis["confidence"]

# 使用缓存加速
if cached_result := cache.get("similar_query"):
    return cached_result
```

---

Generated: 2025年1月
