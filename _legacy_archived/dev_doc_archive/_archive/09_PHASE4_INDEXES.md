# Phase 4 Day 3: 索引优化设计与执行

**日期**: 2026-02-03  
**任务**: 识别缺失索引，创建最优索引策略  
**参考**: EXPLAIN 查询计划分析  

---

## 📊 EXPLAIN 分析结果

### 问题识别

#### 1. v_interfaces 查询 - 全表扫描
```
Query: SELECT * FROM v_interfaces WHERE device = 'R1'
Plan: FILTER(device = 'R1') → COLUMN_DATA_SCAN
Issue: 缺失 (device) 索引，无法使用索引下推
```

**性能影响**: 
- 需要遍历所有行，应用过滤条件
- 对于大表（7行示例），在生产环境可能有百万行

#### 2. v_bgp_neighbors 查询 - 全表扫描
```
Query: SELECT COUNT(*) FROM v_bgp_neighbors WHERE state = 'Established'
Plan: FILTER(state = 'Established') → COLUMN_DATA_SCAN
Issue: 缺失 (state) 索引
```

**性能影响**: 聚合查询仍需扫描全表来应用 WHERE 条件

#### 3. v_routes 查询 - 全表扫描
```
Query: SELECT * FROM v_routes WHERE device = 'R1'
Plan: FILTER(device = 'R1') → COLUMN_DATA_SCAN
Issue: 缺失 (device) 索引
```

#### 4. 缺失：snapshot_date 索引
当前所有表都在 snapshot_date 字段上有 UNIQUE 约束但无单独索引：
```sql
UNIQUE(snapshot_date, device_name, ...)  -- 组合唯一约束
```
这意味着如果查询时使用 `WHERE snapshot_date = LATEST` 来获取最新快照，仍需扫描全表。

---

## 🎯 索引优化策略

### 优先级索引清单

| 表名 | 索引字段 | 类型 | 优先级 | 预期收益 |
|------|---------|------|--------|---------|
| v_interfaces | (device, snapshot_date) | 复合 | P1 | 90% ↓ 扫描行数 |
| v_interfaces | (status) | 单列 | P1 | 80% ↓ 扫描行数 |
| v_bgp_neighbors | (state) | 单列 | P1 | 95% ↓ 扫描行数 |
| v_bgp_neighbors | (device, snapshot_date) | 复合 | P2 | 85% ↓ 扫描行数 |
| v_routes | (device, snapshot_date) | 复合 | P1 | 90% ↓ 扫描行数 |
| v_routes | (protocol) | 单列 | P2 | 70% ↓ 扫描行数 |
| * | (snapshot_date) | 单列（全表） | P2 | 40% ↓ 时间序列查询 |

### 索引设计原则

1. **选择性优先**: 度数高的列优先（state: Established/Idle/Down 3值 → 选择性低）
2. **复合索引排序**: (过滤字段, snapshot_date)，利用 snapshot_date 做 LIMIT/ORDER BY
3. **避免冗余**: 若已有 (device, snapshot_date)，则 (device) 可省略
4. **大表优先**: v_interfaces、v_routes、v_bgp_neighbors 优先建立

---

## 💾 索引创建 SQL

### 立即执行（P1）

```sql
-- v_interfaces: 按设备查询 + 最新快照
CREATE INDEX IF NOT EXISTS idx_v_interfaces_device_snapshot 
ON v_interfaces(device, snapshot_date DESC);

-- v_interfaces: 按状态统计（聚合查询优化）
CREATE INDEX IF NOT EXISTS idx_v_interfaces_status 
ON v_interfaces(status);

-- v_bgp_neighbors: 按状态过滤（高频查询）
CREATE INDEX IF NOT EXISTS idx_v_bgp_neighbors_state 
ON v_bgp_neighbors(state, snapshot_date DESC);

-- v_bgp_neighbors: 按设备查询
CREATE INDEX IF NOT EXISTS idx_v_bgp_neighbors_device_snapshot 
ON v_bgp_neighbors(device, snapshot_date DESC);

-- v_routes: 按设备查询
CREATE INDEX IF NOT EXISTS idx_v_routes_device_snapshot 
ON v_routes(device, snapshot_date DESC);
```

### 可选执行（P2，后续优化）

```sql
-- v_routes: 按协议分析
CREATE INDEX IF NOT EXISTS idx_v_routes_protocol 
ON v_routes(protocol, snapshot_date DESC);

-- 全表时间序列查询（如：获取特定日期快照）
CREATE INDEX IF NOT EXISTS idx_v_interfaces_snapshot_date 
ON v_interfaces(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_v_bgp_neighbors_snapshot_date 
ON v_bgp_neighbors(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_v_routes_snapshot_date 
ON v_routes(snapshot_date DESC);
```

---

## 📈 预期性能改进

### Query 1: 设备接口查询
```sql
SELECT * FROM v_interfaces WHERE device = 'R1'
```
- **前**: COLUMN_DATA_SCAN (全表 ~1M 行)
- **后**: INDEX SCAN (idx_v_interfaces_device_snapshot) → ~100 行
- **收益**: 20-50 ms → 1-2 ms (10-20x 加速) ✅

### Query 2: BGP 状态聚合
```sql
SELECT COUNT(*) FROM v_bgp_neighbors WHERE state = 'Established'
```
- **前**: COLUMN_DATA_SCAN → FILTER → AGGREGATE (~1M 行扫描)
- **后**: INDEX RANGE SCAN (idx_v_bgp_neighbors_state) → AGGREGATE (~10k 行)
- **收益**: 30-100 ms → 2-5 ms (10-20x 加速) ✅

### Query 3: 路由表快照查询
```sql
SELECT * FROM v_routes WHERE device = 'R1' ORDER BY snapshot_date DESC LIMIT 1
```
- **前**: SORT(COLUMN_DATA_SCAN) ~50 ms
- **后**: INDEX RANGE SCAN DESC LIMIT 1 ~1 ms
- **收益**: 50 ms → 1 ms (50x 加速) ✅

### 总体预期
- **单查询**: 20-100 ms → 1-5 ms (10-20x 加速)
- **批量查询（10 queries）**: 200-1000 ms → 10-50 ms (10-20x 加速)
- **缓存命中率**: 应提升至 80%+（更快的 warm cache）

---

## 🔧 实施计划

### Step 1: 确认数据库位置（已完成）
- ✅ 表定义位置: [src/olav/core/database.py](src/olav/core/database.py#L638-L870)
- ✅ 使用 DuckDB ATTACH 多库模式
- ✅ v_interfaces/v_bgp_neighbors/v_routes 存储在 commands.db

### Step 2: 创建索引管理脚本
- 新建 `src/olav/core/index_manager.py`
- 功能: 检测已有索引，创建缺失索引，验证索引有效性

### Step 3: 执行索引创建
- 在 UnifiedDatabase.__init__() 或专用初始化函数中调用
- 捕获 "already exists" 异常（安全）

### Step 4: EXPLAIN 验证
- 重新运行 EXPLAIN 确认索引被使用
- 预期: FILTER → INDEX RANGE SCAN

### Step 5: 性能基准对比
- 运行 test_query_performance.py 对比前后性能
- 预期改进: >5x 加速

---

## 📝 检查清单

- [ ] 创建 index_manager.py
- [ ] 在 UnifiedDatabase 中集成索引创建
- [ ] 执行索引创建 SQL（P1 优先）
- [ ] EXPLAIN 验证 (device, state, protocol 查询)
- [ ] 性能基准对比
- [ ] 文档更新（本文件 + Phase 4 Plan）

---

**状态**: 📝 设计完成，待实施  
**预计工时**: 2h (Step 2-5)  
**完成时间**: 2026-02-03 下午
