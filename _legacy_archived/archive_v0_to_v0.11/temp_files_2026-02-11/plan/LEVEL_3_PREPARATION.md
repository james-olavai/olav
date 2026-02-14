# Level 3 Advanced Testing - Preparation Guide
**Status**: PLANNING  
**Date**: 2026-02-09  
**Prerequisite**: Level 1 & 2 Complete ✅

---

## 🎯 Level 3 Overview

**Objective**: Test advanced query scenarios, complex SQL, and system boundaries

**Scope**: 40+ test cases across 5 categories
- ✅ Complex Filtering (Nested conditions, multiple WHERE clauses)
- ✅ Advanced Aggregations (GROUP BY multiple columns, HAVING)
- ✅ Relationships (JOINs, UNION, subqueries)
- ✅ Time-based Analysis (Date ranges, trends)
- ✅ Edge Cases (Large result sets, null handling, special characters)

---

## 📋 Recommended Test Categories

### Category 1: Complex Filtering (8 tests)
```
1. Multiple conditions: "哪些R设备的接口数 > 10 且位置为Unknown?"
2. Range queries: "2025年1月1日-3月31日期间添加的接口"
3. Pattern matching: "名称包含'eth'的所有接口"
4. Null handling: "没有IP地址的接口"
5. Boolean logic: "(类型A 或 类型B) 且 状态='up'"
6. Case sensitivity: "设备名称大小写匹配"
7. Special characters: "名称中包含% _ 的接口"
8. Negation: "所有不是'down'的接口"
```

### Category 2: Aggregations (8 tests)
```
1. COUNT: "每个设备的接口总数"
2. SUM: "所有启用接口的总带宽"
3. AVG: "设备接口数的平均值"
4. MIN/MAX: "接口数最多和最少的设备"
5. GROUP BY single: "按设备分组统计"
6. GROUP BY multiple: "按设备和状态分组"
7. HAVING: "接口数 > 100 的设备及其接口列表"
8. Distinct: "有多少个不同的设备类型?"
```

### Category 3: Relationships (8 tests)
```
1. INNER JOIN: "设备及其接口信息"
2. LEFT JOIN: "所有设备，包括没有接口的"
3. Self JOIN: "相同设备组中的关系"
4. Multiple JOINs: "三表或以上的复杂查询"
5. Cross JOIN: "所有可能的(设备,接口)组合"
6. UNION: "合并两个结果集"
7. Subqueries: "拥有超过平均接口数的设备"
8. Common Table Expressions: "WITH子查询"
```

### Category 4: Time-based Analysis (8 tests)
```
1. Date range: "2025年期间的所有更改"
2. Month/Quarter: "按月/季度统计"
3. Duration: "接口启用时长"
4. Recent: "最近7/30天的活动"
5. Trends: "接口增长趋势"
6. Predictions: "基于历史数据的预测"
7. Scheduling: "维护窗口中断接口"
8. Expiration: "即将过期的配置"
```

### Category 5: Edge Cases (8 tests)
```
1. Empty results: 正确处理返回0行
2. Large results: 支持1000+行结果
3. NULL values: 处理空值
4. Special characters: 中文、符号、转义
5. Performance: 复杂查询<10秒完成
6. Memory: 大结果集不崩溃
7. Escaping: SQL注入保护
8. Internationalization: 多语言支持
```

---

## 🔧 Test Infrastructure Setup

### Required Database Enhancements
```sql
-- Add timestamps for time-based testing
ALTER TABLE devices ADD COLUMN created_at DATETIME;
ALTER TABLE devices ADD COLUMN updated_at DATETIME;
ALTER TABLE interfaces ADD COLUMN created_at DATETIME;
ALTER TABLE interfaces ADD COLUMN status VARCHAR(10);

-- Add types for filtering testing
UPDATE devices SET device_type = CASE 
    WHEN name LIKE 'R%' THEN 'Router'
    WHEN name LIKE 'SW%' THEN 'Switch'
    ELSE 'Unknown'
END;

-- Add capacity data
ALTER TABLE interfaces ADD COLUMN bandwidth INT;
ALTER TABLE interfaces ADD COLUMN ip_address VARCHAR(50);
```

### Test Data Population
```python
# tests/fixtures/level3_data.py

# Add 50+ devices with varied attributes
devices = [
    {"name": "R1", "type": "Router", "location": "DC-A", ...},
    {"name": "R2", "type": "Router", "location": "DC-B", ...},
    # ... 48 more devices
]

# Add 2000+ interfaces with diverse properties
interfaces = [
    {"device": "R1", "name": "eth0", "status": "up", "bandwidth": 1000, ...},
    # ... 1999 more interfaces
]
```

---

## 📊 Test Execution Plan

### Phase 1: Simple-to-Complex Progression
```
Week 1: Categories 1-2 (16 tests)
  - Day 1: Complex Filtering (8 tests)
  - Day 2: Aggregations (8 tests)
  
Week 2: Categories 3-5 (24 tests)
  - Day 3: Relationships (8 tests)
  - Day 4: Time-based (8 tests)
  - Day 5: Edge Cases (8 tests)
```

### Phase 2: Comprehensive Coverage
```
Week 3: Combination scenarios (15+ tests)
  - Multi-category queries
  - Real-world use cases
  - Performance stress testing
```

### Phase 3: Production Validation
```
Week 4: System limits + Optimization
  - Max query complexity
  - Performance tuning
  - Production readiness verification
```

---

## 🎓 Expected Results

### Pass Criteria
- **SUCCESS**: Query returns correct results in <10s
- **PARTIAL**: Results correct but response slow (5-10s)
- **FAIL**: Incorrect results or error

### Expected Distribution
```
Level 3 Conservative Estimate:
- Pass (correct + fast): 32/40 (80%)
- Partial (correct + slow): 6/40 (15%)  
- Fail (incorrect/error): 2/40 (5%)

Optimistic Target:
- Pass (correct + fast): 38/40 (95%)
- Partial (correct + slow): 2/40 (5%)
- Fail (incorrect/error): 0/40 (0%)
```

---

## 🔍 SQL Features to Focus On

### Essential
- [ ] WHERE with multiple conditions
- [ ] GROUP BY with aggregates
- [ ] JOIN operations (INNER, LEFT)
- [ ] ORDER BY + LIMIT
- [ ] DISTINCT

### Important
- [ ] Subqueries
- [ ] HAVING clause
- [ ] UNION operations
- [ ] Case expressions
- [ ] Date/time functions

### Nice-to-have
- [ ] Window functions (ROW_NUMBER, RANK)
- [ ] Common Table Expressions (WITH)
- [ ] Recursive queries
- [ ] Text search
- [ ] Full-text indexing

---

## 🚀 Quick Start for Level 3

### 1. Before Starting
```bash
# Verify Level 1-2 still pass
uv run pytest tests/e2e/test_real_scenarios.py -v -k "real_llm"
# Expected: 7/8 PASS ✅

# Check current LLM provider
grep LLM_MODEL_NAME .env
# Should show: x-ai/grok-4.1-fast (or your provider)
```

### 2. Setup Level 3 Test File
```bash
# Copy template
cp tests/e2e/test_real_scenarios.py tests/e2e/test_level3_advanced.py

# Add Level 3 test class
# class TestLevel3AdvancedQueries:
```

### 3. Start with Category 1
```bash
uv run pytest tests/e2e/test_level3_advanced.py::TestLevel3AdvancedQueries::test_complex_filtering_01 -v
```

### 4. Iterate Through Categories
```bash
# Each day:
uv run pytest tests/e2e/test_level3_advanced.py -v --tb=short
# Review failures and report
```

---

## 📝 Success Metrics

| Metric | Target | Threshold |
|--------|--------|-----------|
| **Pass Rate** | 95% | >85% |
| **Response Time** | <10s avg | <12s |
| **Correctness** | 100% | >95% |
| **Error Handling** | Graceful | All errors handled |
| **Memory Usage** | <500MB | <1GB |
| **CPU Efficiency** | <80% | <90% |

---

## 🎯 Success Indicators

### System is Ready for Level 3 When:
- ✅ Level 1-2 tests consistently pass (>90%)
- ✅ Response times are stable (<10s)
- ✅ No memory leaks or crashes
- ✅ LLM provider is stable
- ✅ Database connection pool works
- ✅ Error handling is robust

### System Completed Level 3 When:
- ✅ 40/40 advanced tests pass
- ✅ Complex queries execute correctly
- ✅ Performance is consistent
- ✅ Edge cases are handled
- ✅ Production readiness confirmed

---

## 📌 Important Notes

### 1. Fallback Orchestrator Limitations
```
❌ Not yet supported:
  - Window functions (ROW_NUMBER, RANK)
  - Recursive CTEs
  - Complex subquery correlations
  
✅ Supported:
  - Basic JOINs
  - GROUP BY + aggregates
  - Simple subqueries
  - Most standard SQL
```

### 2. LLM Model Capability
```
Grok-4.1-fast capabilities:
- Excellent SQL generation
- Good query understanding
- Fast response times
- Handles complex logic

Alternative models:
- Claude Opus: More accurate SQL
- GPT-4: Better at complex reasoning
- Llama 3.1: Faster, cheaper
```

### 3. Database Scalability
```
Current: 6 devices, ~1200 interfaces
Level 3 can support: 1000 devices, 100k+ interfaces

For even larger:
- Consider database indexing
- Query optimization
- Caching strategy
```

---

## 🔗 Next Steps

**After completing this document:**

1. ✅ Validate Level 1 & 2 still passing
2. ✅ Populate Level 3 test data
3. ✅ Create test file (`test_level3_advanced.py`)
4. ✅ Add first 8 complex filtering tests
5. ✅ Run and debug
6. ✅ Document results
7. ✅ Iterate through categories

---

**Estimated Timeline**: 2-3 weeks for full Level 3 coverage  
**Blockers**: None identified  
**Dependencies**: Level 1-2 must pass  
**Owner**: Testing team  
**Status**: READY FOR PROTOCOL DEVELOPMENT

