# 📋 OLAV E2E 测试扩展规划 - 12+ 新测试用例

**项目**: E2E 测试覆盖率提升  
**目标**: 从 50% → 82% 覆盖率 (新增 12+ 用例)  
**状态**: 📝 详细规划  
**实施时间**: 1 周

---

## 🎯 测试缺口分析

### 当前状况
```
原有测试: 12 个
├─ Snapshot 测试: 2 个
├─ Query 测试: 4 个
├─ CLI 测试: 2 个
├─ Fallback 测试: 2 个
├─ Cache 测试: 1 个
└─ Performance 测试: 1 个

覆盖率: 50%
缺口: 
- 复杂查询场景: 0 个 ❌
- 缓存污染验证: 0 个 ❌
- 真实 CLI 交互: 0 个 ❌
- 错误处理: 0 个 ❌
```

### 优化后
```
新增测试: 12+ 个
├─ 复杂查询: 4 个 ✅
├─ 缓存验证: 3 个 ✅
├─ CLI echo: 3 个 ✅
├─ 错误处理: 2 个 ✅
└─ 性能基准: 0 个 (优化现有)

总计: 30+ 个
覆盖率: 82%
改进: +64%
```

---

## 📌 12+ 新测试用例详细规划

## 第一类: 复杂查询测试 (4 个新用例)

### 用例 1.1: JOIN 查询

**用例名称**: `test_complex_join_query`

**目的**: 测试多表关联查询的正确性

**场景**:
```sql
SELECT d.name, m.cpu, m.memory 
FROM devices d 
JOIN metrics m ON d.id = m.device_id 
WHERE m.timestamp > NOW() - INTERVAL 1 DAY
ORDER BY m.cpu DESC
LIMIT 10
```

**验证点**:
- ✅ 结果集正确返回
- ✅ JOIN 逻辑正确
- ✅ 聚合结果准确
- ✅ 排序正确

**预期行为**:
```
输入: "查询过去24小时CPU最高的设备及其指标"
处理:
  1. 意图识别: 多表查询
  2. SQL 生成: 生成正确的 JOIN 语句
  3. 优化: 应用索引
  4. 执行: 返回 ≤ 10 行结果

输出: {
  "results": [
    {
      "device_name": "Router-01",
      "cpu": 85.5,
      "memory": 72.3,
      "timestamp": "2025-02-02T10:30:00Z"
    },
    ...
  ],
  "row_count": 10
}
```

**测试代码**:
```python
async def test_complex_join_query(self):
    """Test JOIN query with aggregation"""
    query = "查询过去24小时CPU最高的设备及其指标"
    
    result = await orchestrator.orchestrate(query)
    
    assert result.row_count >= 0
    assert all('device_name' in r for r in result.results)
    assert all('cpu' in r for r in result.results)
```

**执行时间**: ~9s  
**优先级**: 🔴 高  
**复杂度**: ⭐⭐⭐

---

### 用例 1.2: GROUP BY 聚合查询

**用例名称**: `test_complex_group_by_query`

**目的**: 测试分组聚合功能

**场景**:
```sql
SELECT 
  d.location,
  COUNT(*) as device_count,
  AVG(m.cpu) as avg_cpu,
  MAX(m.memory) as max_memory
FROM devices d
LEFT JOIN metrics m ON d.id = m.device_id
WHERE d.status = 'active'
GROUP BY d.location
HAVING COUNT(*) > 2
ORDER BY avg_cpu DESC
```

**验证点**:
- ✅ GROUP BY 分组正确
- ✅ 聚合函数准确 (COUNT, AVG, MAX)
- ✅ HAVING 子句工作
- ✅ LEFT JOIN 包含所有数据

**预期行为**:
```
输入: "按位置统计活跃设备数量及平均CPU"
处理:
  1. 意图识别: 聚合查询
  2. SQL 生成: 生成 GROUP BY 语句
  3. 聚合计算: 计算 COUNT/AVG/MAX
  4. 过滤: HAVING 子句过滤

输出: {
  "results": [
    {
      "location": "Shanghai",
      "device_count": 5,
      "avg_cpu": 68.4,
      "max_memory": 92.1
    },
    {
      "location": "Beijing",
      "device_count": 3,
      "avg_cpu": 45.2,
      "max_memory": 78.5
    }
  ]
}
```

**执行时间**: ~8s  
**优先级**: 🔴 高  
**复杂度**: ⭐⭐⭐

---

### 用例 1.3: 子查询

**用例名称**: `test_complex_subquery`

**目的**: 测试子查询的正确性

**场景**:
```sql
SELECT *
FROM devices d
WHERE d.id IN (
  SELECT m.device_id
  FROM metrics m
  WHERE m.cpu > (
    SELECT AVG(cpu) FROM metrics
  )
  AND m.timestamp > NOW() - INTERVAL 1 HOUR
)
```

**验证点**:
- ✅ 子查询执行正确
- ✅ IN 子句过滤准确
- ✅ 嵌套聚合正确
- ✅ 时间过滤生效

**预期行为**:
```
输入: "查询CPU高于平均值的设备"
处理:
  1. 意图识别: 子查询
  2. 内层查询: 计算平均 CPU
  3. 外层查询: 过滤设备
  4. 结果返回

输出: {
  "results": [
    {
      "id": "dev-001",
      "name": "Router-01",
      "status": "active",
      "location": "Shanghai"
    },
    ...
  ],
  "above_average_count": 8
}
```

**执行时间**: ~7s  
**优先级**: 🟡 中  
**复杂度**: ⭐⭐⭐⭐

---

### 用例 1.4: 多条件复杂过滤

**用例名称**: `test_complex_multi_condition`

**目的**: 测试复杂 WHERE 条件

**场景**:
```sql
SELECT *
FROM devices d
WHERE (d.status = 'active' OR d.status = 'warning')
  AND d.location IN ('Shanghai', 'Beijing', 'Shenzhen')
  AND (
    (d.type = 'router' AND d.cpu_cores >= 8)
    OR (d.type = 'switch' AND d.ports >= 24)
  )
ORDER BY d.cpu_cores DESC
LIMIT 20
```

**验证点**:
- ✅ OR 条件正确
- ✅ IN 列表过滤
- ✅ 复杂嵌套条件
- ✅ 排序和分页

**预期行为**:
```
输入: "查询上海、北京、深圳的活跃或警告状态的高性能设备"
处理:
  1. 意图识别: 多条件过滤
  2. SQL 生成: 复杂 WHERE 子句
  3. 优化: 使用索引
  4. 执行: 返回前 20 行

输出: {
  "results": [ /* 20 条设备记录 */ ],
  "total_count": 47
}
```

**执行时间**: ~10s  
**优先级**: 🔴 高  
**复杂度**: ⭐⭐⭐

---

## 第二类: 缓存验证测试 (3 个新用例)

### 用例 2.1: 缓存命中率验证

**用例名称**: `test_cache_hit_rate`

**目的**: 验证缓存命中率达到预期

**场景**:
```
1. 清空所有缓存
2. 运行 10 个查询
3. 重复相同 10 个查询
4. 统计命中率
```

**验证点**:
- ✅ 第一轮: 缓存未命中 (0%)
- ✅ 第二轮: 缓存全部命中 (100%)
- ✅ 平均响应时间: 第二轮 < 第一轮 50%

**实现逻辑**:
```python
async def test_cache_hit_rate(self):
    """Test cache hit rate"""
    debugger = FastPathDebugger()
    
    # Clear caches
    await debugger.clear_all_caches()
    
    # First run - warm up
    queries = [
        "查询所有活跃设备",
        "查询上海的设备",
        "查询CPU高于80的设备",
        # ... 更多查询
    ]
    
    times_first = []
    for q in queries:
        start = time.time()
        result = await orchestrator.orchestrate(q)
        times_first.append(time.time() - start)
    
    # Second run - should hit cache
    times_second = []
    for q in queries:
        start = time.time()
        result = await orchestrator.orchestrate(q)
        times_second.append(time.time() - start)
    
    avg_first = sum(times_first) / len(times_first)
    avg_second = sum(times_second) / len(times_second)
    
    assert avg_second < avg_first * 0.5  # 至少快 50%
```

**预期结果**:
```
第一轮平均: 0.594s/查询
第二轮平均: 0.261s/查询
改进: 55.9% ✅
缓存命中率: 100% ✅
```

**执行时间**: ~15s  
**优先级**: 🔴 高  
**复杂度**: ⭐⭐

---

### 用例 2.2: 缓存污染检测

**用例名称**: `test_cache_pollution_detection`

**目的**: 检测缓存是否被污染

**场景**:
```
1. 查询 A: 获得结果 R1
2. 修改数据库: INSERT new device
3. 查询 A: 应该获得新结果 R2
4. 验证 R1 != R2
```

**验证点**:
- ✅ 缓存应该自动失效
- ✅ 新查询返回最新数据
- ✅ 不会返回过期的缓存

**实现逻辑**:
```python
async def test_cache_pollution_detection(self):
    """Test cache invalidation on data change"""
    
    # Query 1: Get baseline
    query = "查询所有设备数量"
    result1 = await orchestrator.orchestrate(query)
    count1 = result1.total_count
    
    # Modify database
    await db.insert_device({
        "name": "test-device",
        "status": "active"
    })
    
    # Query 2: Should return new count
    result2 = await orchestrator.orchestrate(query)
    count2 = result2.total_count
    
    # Verify cache was invalidated
    assert count2 > count1, "Cache should be invalidated after INSERT"
    assert count2 == count1 + 1
```

**预期结果**:
```
初始设备数: 42
插入后数: 43 ✅
缓存有效性: ✓ 自动失效
```

**执行时间**: ~8s  
**优先级**: 🔴 高  
**复杂度**: ⭐⭐⭐

---

### 用例 2.3: 缓存大小监控

**用例名称**: `test_cache_size_monitoring`

**目的**: 验证缓存大小在可接受范围

**场景**:
```
1. 执行 100 个不同的查询
2. 监控缓存大小增长
3. 验证是否超过限制
4. 检查是否启用 LRU 淘汰
```

**验证点**:
- ✅ 缓存大小 < 50MB
- ✅ 缓存条目数 < 1000
- ✅ 淘汰策略正常工作
- ✅ 内存泄漏不存在

**实现逻辑**:
```python
async def test_cache_size_monitoring(self):
    """Test cache size growth"""
    debugger = FastPathDebugger()
    
    # Take baseline
    await debugger.capture_cache_state("start")
    
    # Run 100 diverse queries
    for i in range(100):
        query = f"查询设备 {i % 10} 的信息"
        await orchestrator.orchestrate(query)
    
    # Check size
    await debugger.capture_cache_state("after_100")
    
    size = debugger.cache_state["after_100"]["semantic_cache_size"]
    assert size < 1000, f"Cache too large: {size}"
    
    # Check for memory leaks
    import gc
    gc.collect()
    # ... 内存检查
```

**预期结果**:
```
初始缓存: 0 条目, 0 MB
100 查询后: 87 条目, 12 MB ✅
内存增长: 线性 ✅
淘汰工作: ✓ LRU 启用
```

**执行时间**: ~20s  
**优先级**: 🟡 中  
**复杂度**: ⭐⭐

---

## 第三类: 真实 CLI 交互测试 (3 个新用例)

### 用例 3.1: CLI 完整交互链

**用例名称**: `test_cli_full_interaction_chain`

**目的**: 测试从 CLI 输入到最终输出的完整链路

**场景**:
```
1. 启动 OLAV CLI
2. 输入查询: "查询所有活跃设备"
3. CLI 处理请求
4. 返回结果
5. 验证输出格式
```

**验证点**:
- ✅ CLI 启动成功
- ✅ 接受用户输入
- ✅ 正确路由到 orchestrator
- ✅ 返回格式化输出
- ✅ 优雅关闭

**实现逻辑**:
```python
async def test_cli_full_interaction_chain(self):
    """Test CLI end-to-end interaction"""
    
    # Start CLI with echo input
    cmd = f"echo '查询所有活跃设备' | uv run src/olav/cli_main.py"
    
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=30
    )
    
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    
    # Parse output
    output = json.loads(result.stdout)
    
    # Verify
    assert "results" in output
    assert output["status"] == "success"
    assert isinstance(output["results"], list)
```

**预期结果**:
```
CLI 输入: "查询所有活跃设备"
CLI 输出: {
  "status": "success",
  "results": [ /* 设备列表 */ ],
  "execution_time": 5.94
} ✅
```

**执行时间**: ~6s  
**优先级**: 🔴 高  
**复杂度**: ⭐⭐

---

### 用例 3.2: CLI 错误处理

**用例名称**: `test_cli_error_handling`

**目的**: 验证 CLI 能正确处理错误

**场景**:
```
1. 发送无效查询
2. 发送语法错误
3. 发送权限不足
4. 验证错误信息
```

**验证点**:
- ✅ 错误被捕获
- ✅ 返回有意义的错误消息
- ✅ CLI 不崩溃
- ✅ 错误信息可读

**实现逻辑**:
```python
async def test_cli_error_handling(self):
    """Test CLI error scenarios"""
    
    test_cases = [
        ("查询 [invalid sql]", "invalid_sql"),
        ("", "empty_query"),
        ("查询 X from Y", "syntax_error"),
    ]
    
    for query, error_type in test_cases:
        cmd = f"echo '{query}' | uv run src/olav/cli_main.py"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        output = json.loads(result.stdout)
        
        assert output["status"] == "error"
        assert "error_message" in output
        assert output["error_type"] == error_type
```

**预期结果**:
```
无效查询:
{
  "status": "error",
  "error_type": "invalid_sql",
  "error_message": "SQL syntax error at position 15",
  "suggestion": "Did you mean: SELECT ?"
} ✅
```

**执行时间**: ~8s  
**优先级**: 🟡 中  
**复杂度**: ⭐⭐⭐

---

### 用例 3.3: CLI 性能基准测试

**用例名称**: `test_cli_performance_baseline`

**目的**: 建立 CLI 响应时间基准

**场景**:
```
1. 运行 10 个查询 (不同复杂度)
2. 记录响应时间
3. 计算统计指标
4. 验证是否满足 SLA
```

**验证点**:
- ✅ 简单查询 < 3s
- ✅ 复杂查询 < 10s
- ✅ 平均响应 < 6s
- ✅ P95 < 8s

**实现逻辑**:
```python
async def test_cli_performance_baseline(self):
    """Test CLI performance baseline"""
    
    queries = [
        ("查询所有设备", "simple", 3),
        ("查询上海的活跃设备", "medium", 5),
        ("查询CPU>80的设备及其指标", "complex", 10),
    ]
    
    times = []
    for query, category, max_time in queries:
        cmd = f"echo '{query}' | time uv run src/olav/cli_main.py"
        start = time.time()
        result = subprocess.run(cmd, shell=True, capture_output=True)
        elapsed = time.time() - start
        
        times.append(elapsed)
        assert elapsed < max_time, f"{category} query too slow: {elapsed}s"
    
    # Stats
    avg = sum(times) / len(times)
    assert avg < 6.0
```

**预期结果**:
```
简单查询: 3.2s ✅
中等查询: 5.1s ✅
复杂查询: 9.8s ✅
平均: 6.0s ✅
P95: 9.8s ✅
```

**执行时间**: ~10s  
**优先级**: 🟡 中  
**复杂度**: ⭐⭐

---

## 第四类: 错误处理测试 (2 个新用例)

### 用例 4.1: SQL 执行错误

**用例名称**: `test_sql_execution_error`

**目的**: 验证 SQL 执行错误被正确处理

**场景**:
```
1. 生成导致 SQL 错误的查询
2. 监控错误处理过程
3. 验证错误被记录
4. 验证系统继续运行
```

**验证点**:
- ✅ 错误被捕获
- ✅ 错误信息返回给用户
- ✅ 错误被记录到日志
- ✅ 连接自动恢复
- ✅ 不会导致崩溃

**实现逻辑**:
```python
async def test_sql_execution_error(self):
    """Test SQL execution error handling"""
    
    # Query that causes SQL error
    query = "查询 FROM invalid_table"  # Table doesn't exist
    
    try:
        result = await orchestrator.orchestrate(query)
        assert False, "Should raise exception"
    except SQLExecutionError as e:
        # Verify error details
        assert "invalid_table" in str(e)
        assert e.error_code == "42P01"  # PostgreSQL: undefined table
        
        # Verify error was logged
        logs = get_logs()
        assert any("invalid_table" in log for log in logs)
    
    # System should recover
    query = "查询所有设备"
    result = await orchestrator.orchestrate(query)
    assert result.status == "success"
```

**预期结果**:
```
错误查询: → SQLExecutionError ✅
错误代码: 42P01 (undefined table) ✅
日志记录: ✓ 已记录
系统恢复: ✓ 正常查询可用 ✅
```

**执行时间**: ~5s  
**优先级**: 🔴 高  
**复杂度**: ⭐⭐⭐

---

### 用例 4.2: 数据库连接失败

**用例名称**: `test_database_connection_failure`

**目的**: 验证数据库连接失败的处理

**场景**:
```
1. 模拟 DB 连接失败
2. 尝试执行查询
3. 验证错误处理
4. 验证恢复机制
```

**验证点**:
- ✅ 连接失败被检测
- ✅ 重试机制触发
- ✅ 降级服务可用
- ✅ 错误信息有用
- ✅ 不会无限等待

**实现逻辑**:
```python
async def test_database_connection_failure(self):
    """Test database connection failure handling"""
    
    # Mock DB connection failure
    with patch('src.olav.db.connect') as mock_db:
        mock_db.side_effect = ConnectionError("Connection refused")
        
        try:
            result = await orchestrator.orchestrate(
                "查询所有设备"
            )
            # Should use fallback
            assert result.status == "degraded" or result.status == "error"
        except DBConnectionError as e:
            # Verify error handling
            assert e.retries > 0  # Should attempt retries
            assert hasattr(e, 'retry_after')
    
    # Verify system recovers
    mock_db.side_effect = None
    mock_db.return_value = MockDB()
    
    result = await orchestrator.orchestrate("查询所有设备")
    assert result.status == "success"
```

**预期结果**:
```
连接失败: → DBConnectionError ✅
重试次数: 3 次 ✅
降级服务: ✓ 缓存结果可用
恢复时间: < 30s ✅
错误消息: 清晰 ✅
```

**执行时间**: ~6s  
**优先级**: 🟡 中  
**复杂度**: ⭐⭐⭐

---

## 第五类: 性能基准 (现有优化)

### 不需要新增测试

**现有测试已覆盖**:
- ✅ `performance_baseline` - 基础性能测试
- ✅ `cache_fastpath` - FastPath 性能测试
- ✅ `cache_hit_validation` - 缓存效果测试

**优化策略**:
1. 增强现有性能基准测试
2. 添加性能回归检测
3. 添加性能趋势分析

---

## 📊 12+ 测试用例汇总表

| # | 用例名称 | 类别 | 时间 | 优先级 | 复杂度 | 状态 |
|----|---------|------|------|--------|--------|------|
| 1.1 | JOIN 查询 | 复杂查询 | 9s | 🔴 | ⭐⭐⭐ | 📝 待实施 |
| 1.2 | GROUP BY 聚合 | 复杂查询 | 8s | 🔴 | ⭐⭐⭐ | 📝 待实施 |
| 1.3 | 子查询 | 复杂查询 | 7s | 🟡 | ⭐⭐⭐⭐ | 📝 待实施 |
| 1.4 | 多条件过滤 | 复杂查询 | 10s | 🔴 | ⭐⭐⭐ | 📝 待实施 |
| 2.1 | 缓存命中率 | 缓存验证 | 15s | 🔴 | ⭐⭐ | 📝 待实施 |
| 2.2 | 缓存污染检测 | 缓存验证 | 8s | 🔴 | ⭐⭐⭐ | 📝 待实施 |
| 2.3 | 缓存大小监控 | 缓存验证 | 20s | 🟡 | ⭐⭐ | 📝 待实施 |
| 3.1 | CLI 完整链 | CLI 交互 | 6s | 🔴 | ⭐⭐ | 📝 待实施 |
| 3.2 | CLI 错误处理 | CLI 交互 | 8s | 🟡 | ⭐⭐⭐ | 📝 待实施 |
| 3.3 | CLI 性能基准 | CLI 交互 | 10s | 🟡 | ⭐⭐ | 📝 待实施 |
| 4.1 | SQL 执行错误 | 错误处理 | 5s | 🔴 | ⭐⭐⭐ | 📝 待实施 |
| 4.2 | DB 连接失败 | 错误处理 | 6s | 🟡 | ⭐⭐⭐ | 📝 待实施 |

**总计**: 12 个新用例，总执行时间: ~112 秒

---

## 🎯 优化方案讨论

### 问题 1: 测试执行时间

**现状**: 12 个新用例总执行时间 ~112 秒

**优化方案**:

#### 方案 A: 并行执行 (推荐)
```
优点:
- 将 112s 并行为 ~30s (4 个并行流)
- CI/CD 反馈速度快
- 资源充分利用

实施:
- 使用 pytest-xdist 插件
- 配置并行度: 4
- 隔离测试数据库
```

#### 方案 B: 分组执行
```
优点:
- 测试分为快速/标准/完整组
- CI 快速通过 (快速组 ~20s)
- PR 审核迅速反馈

分组:
- 快速组: 1.1, 2.1, 3.1 (15s)
- 标准组: 1.2, 1.4, 2.2, 3.2, 4.1 (45s)
- 完整组: 所有 (112s)
```

**建议**: 采用方案 B 分组 + 方案 A 并行
- PR: 快速组 (~15s)
- Merge: 标准组 (~45s)
- Release: 完整组 (~112s)

---

### 问题 2: 缓存污染风险

**现状**: 缓存验证测试可能互相干扰

**优化方案**:

#### 方案 A: 独立数据库 (推荐)
```
实施:
- 每个测试使用独立 DB 连接
- 测试前创建临时数据库
- 测试后销毁临时数据库

优点:
- 完全隔离，无污染
- 可并行执行
- 便于回滚

缺点:
- 轻微性能开销 (DB 创建 ~1s)
```

#### 方案 B: 事务回滚
```
实施:
- 每个测试使用事务
- 测试后 ROLLBACK
- 保持原始数据

优点:
- 快速，无数据库创建开销
- 简单实现

缺点:
- 某些 DDL 语句不支持
- 可能出现死锁
```

**建议**: 采用方案 A
- 缓存验证测试用独立 DB
- 其他测试用事务回滚

---

### 问题 3: CLI 测试的真实性

**现状**: CLI echo 测试需要真实的 CLI 环境

**优化方案**:

#### 方案 A: 子进程执行 (推荐)
```python
实施:
cmd = f"echo '{query}' | uv run src/olav/cli_main.py"
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

优点:
- 真实的 CLI 交互
- 完整的环境初始化
- 验证完整链路

缺点:
- 较慢 (~6-10s 每个)
- 可能受环境变量影响
```

#### 方案 B: 直接函数调用
```python
实施:
from src.olav.cli_main import main
result = await main(["查询所有设备"])

优点:
- 快速 (~2-3s)
- 便于 mock
- 易于调试

缺点:
- 不测试 CLI 环境初始化
- 不测试命令行参数解析
```

**建议**: 混合方案
- 快速组: 使用方案 B (快速反馈)
- 完整测试: 使用方案 A (真实验证)

---

### 问题 4: 错误场景的覆盖

**现状**: 某些错误场景难以模拟

**优化方案**:

#### 方案 A: Mock + Patch (推荐)
```python
实施:
with patch('db.connect') as mock_db:
    mock_db.side_effect = ConnectionError()
    result = await orchestrator.orchestrate(query)

优点:
- 容易测试各种错误
- 可重复性强
- 不需要真实的错误环境

缺点:
- 不测试真实错误处理
```

#### 方案 B: 真实错误环境
```
实施:
- 启用真实 DB 故障注入
- 使用 chaos engineering 工具
- 模拟网络分区

优点:
- 测试真实行为
- 发现隐蔽 bugs

缺点:
- 复杂，时间长
```

**建议**: 采用方案 A + 周期性方案 B
- 日常 CI: Mock 测试 (快速)
- 周末: 真实错误模拟 (完整)

---

### 问题 5: 性能指标追踪

**现状**: 性能基准需要历史数据进行对比

**优化方案**:

#### 方案 A: JSON 报告 (推荐)
```json
实施:
{
  "timestamp": "2025-02-02T10:00:00Z",
  "commit": "abc123",
  "test_results": [
    {
      "name": "test_cli_performance_baseline",
      "simple_query": 3.2,
      "medium_query": 5.1,
      "complex_query": 9.8,
      "average": 6.0
    }
  ]
}

优点:
- 结构化，易解析
- 可构建趋势图
- 自动告警 (性能下降)
```

#### 方案 B: Prometheus 指标
```
实施:
- 暴露 /metrics 端点
- 记录查询延迟分布
- 实时监控告警

优点:
- 实时性
- 成熟的工具链
```

**建议**: 采用方案 A
- 简单实现，立即可用
- 后期可扩展为 Prometheus

---

## 📋 实施建议

### 优先级排序

**第一阶段 (本周)** - 关键路径
```
高优先级 (🔴):
1. 复杂查询: 1.1, 1.2, 1.4
2. 缓存验证: 2.1, 2.2
3. CLI 交互: 3.1
4. 错误处理: 4.1
总计: 7 个测试
执行时间: ~50s
```

**第二阶段 (下周)** - 完整覆盖
```
中优先级 (🟡):
5. 复杂查询: 1.3
6. 缓存验证: 2.3
7. CLI 交互: 3.2, 3.3
8. 错误处理: 4.2
总计: 5 个测试
执行时间: ~62s
```

### 测试框架准备

已完成 ✅:
- `FastPathDebugger` 类 (缓存管理)
- `CLIEchoTester` 类 (CLI 交互)
- `ComplexQueryTester` 类 (复杂查询)
- `CacheValidationTester` 类 (缓存验证)
- `ErrorHandlingTester` 类 (错误处理)

待完成:
- 增强数据库隔离机制
- 添加性能指标导出
- 构建测试报告生成器

---

## 🎯 成功标准

- ✅ 12 个新测试全部通过
- ✅ 代码覆盖率 82% (从 50%)
- ✅ 执行时间 < 2 分钟 (快速组)
- ✅ 缓存命中率 ≥ 70%
- ✅ 无内存泄漏
- ✅ 所有错误场景被覆盖

---

**版本**: v1.0  
**状态**: 📝 详细规划完成  
**下一步**: 实施第一阶段 (7 个关键测试)

