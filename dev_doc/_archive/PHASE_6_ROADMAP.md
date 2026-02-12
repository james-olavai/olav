# 🗺️ Phase 6+ 产品开发路线图

**创建日期**: 2026-02-07  
**Current Status**: Phase 5 ✅ GREEN Complete  
**Next Focus**: Phase 5 REFACTOR + Phase 6 Integration

---

## 📊 项目进度总览

```
❓ Phase 0: 基础架构 (2025-12)
  ├─ ✅ DeepAgents集成
  ├─ ✅ SKILL.md 转换
  └─ ✅ SubAgent系统

✅ Phase 1-3: 核心功能 (2026-01)
  ├─ ✅ Backend路由统一
  ├─ ✅ Learning工作流
  └─ ✅ Long-term Memory

✅ Phase 4.1-4.2: 规划模式 (2026-02-01~02-06)
  ├─ ✅ Plan命令基础 (System Prompt)
  └─ ✅ TodoList集成 (中间件)

✅ Phase 5: 声明式依赖 (2026-02-07)
  ├─ ✅ RED: 15个测试集合
  ├─ ✅ GREEN: 完整实现
  └─ ⏳ REFACTOR: 进行中

📋 Phase 6: 集成测试 (2026-02-07~02-21)
  ├─ 📋 完整E2E场景
  ├─ 📋 多SubAgent协作
  └─ 📋 错误恢复测试

📅 Phase 7: 性能优化 (2026-02-21~03-07)
  ├─ 📅 并行执行
  ├─ 📅 Context缓存
  └─ 📅 基准测试

🚀 Phase 8: 生产验证 (2026-03-07+)
  ├─ 🚀 真实数据测试
  ├─ 🚀 压力测试
  └─ 🚀 监控&告警
```

---

## 🎯 Phase 5 REFACTOR (当前)

**目标**: 优化代码质量，完整文档化

### 工作项目

#### 1️⃣ 代码优化 (2天)

- [ ] 提取公共工具函数到 `src/olav/core/dependency.py`
- [ ] 添加类型提示：`DependencyGraph`, `SubAgentTask`, `ExecutionContext`
- [ ] 单元测试：`_build_dependency_graph()`, `_topological_sort()`
- [ ] 错误处理细化：自定义异常 `CircularDependencyError`, `MissingContextError`

**代码示例**:
```python
# src/olav/core/dependency.py (NEW)

class CircularDependencyError(Exception):
    """检测到循环依赖"""
    pass

class DependencyGraph:
    """有向无环图表示"""
    graph: Dict[str, List[str]]  # subagent → dependencies
    output_map: Dict[str, str]   # output_key → subagent
    subagents: Dict[str, SubAgentMetadata]

def build_dependency_graph(deps: List[Dict]) -> DependencyGraph:
    """构建并验证依赖图"""
    # 实现逻辑...
    pass
```

#### 2️⃣ 文档完善 (1天)

- [ ] 更新 `docs/PHASE_5_COLLABORATIVE_MODE.md`
  - [ ] 添加"故障排除"章节
  - [ ] 添加"性能考虑"
  - [ ] 添加"扩展指南"
- [ ] 更新 `docs/ARCHITECTURE_OPTIMIZATION_TRACKING.md`
  - [ ] Phase 5验收清单
  - [ ] 下一步建议
- [ ] 添加示例 `.olav/skills/*/SKILL.md`
  - [ ] `orchestrator/SKILL.md`: collaborative_mode示例
  - [ ] `network-expert/SKILL.md`: 依赖chain示例

#### 3️⃣ 测试完善 (1天)

- [ ] 添加单元测试: `tests/unit/test_dependency_graph.py`
  - [ ] 大规模DAG性能测试 (100+ nodes)
  - [ ] 边界情况（空依赖列表, 循环, 丢失output_key)
- [ ] 集成测试: 验证与orchestrator.py集成
- [ ] 性能基准: 执行时间 vs 依赖数

**验收标准**:
```python
# Execution time benchmark
def test_build_graph_performance():
    large_deps = generate_large_dependency_set(1000)
    start = time.time()
    graph = build_dependency_graph(large_deps)
    elapsed = time.time() - start
    
    assert elapsed < 0.1  # < 100ms for 1000 nodes
    assert len(graph.graph) == 1000
```

---

## 📋 Phase 6: 多SubAgent集成测试 (2-3周)

**目标**: 验证来自Phase 4.2 (Planning) + Phase 5 (Dependencies) 的完整集成

### 工作项目

#### 1️⃣ 集成场景 (1周)

##### **Scenario A: NetBox同步**

```
User: "/plan 同步网络设备到NetBox"
  ↓
Orchestrator:
  1. 触发plan mode (Phase 4.2)
  2. 用户确认计划
  3. 执行 → Orchestrator加载dependencies (Phase 5)
  4. query SubAgent → 获取网络数据
  5. netbox SubAgent → 获取NetBox数据
  6. analyzer SubAgent → 对比差异
  7. 生成报告
```

**验证点**:
- [ ] `/plan` 前缀检测 ✅ (Phase 4.1)
- [ ] TodoList展示 ✅ (Phase 4.2 - when available)
- [ ] 用户确认流程
- [ ] Dependencies加载正确
- [ ] SubAgent执行顺序正确
- [ ] Context正确传递
- [ ] 最终输出正确

**测试文件**: `tests/e2e/test_netbox_sync_integration.py`

##### **Scenario B: BGP故障诊断**

```
User: "/plan 诊断R1 BGP连接问题"
  ↓
Orchestrator:
  1. 触发plan mode
  2. ExpertSubAgent自主决定需要的信息：
     - query SubAgent: R1配置、邻居、路由表
     - cli SubAgent: 实时BGP状态
  3. ExpertSubAgent分析→根因
```

**验证点**:
- [ ] Plan mode展示诊断步骤
- [ ] SubAgent自主扩展范围 (ReAct)
- [ ] Context在SubAgent间共享
- [ ] 最终诊断准确

**测试文件**: `tests/e2e/test_bgp_diagnosis_integration.py`

#### 2️⃣ 错误恢复 (1周)

##### **Scenario A: SubAgent失败恢复**

```
query SubAgent → 成功 ✅
netbox SubAgent → 失败 ❌ (API超时)
  ↓
Orchestrator:
  1. 记录错误
  2. 重试3次 (指数退避)
  3. 如果仍失败：
     - 报告给用户
     - 提供部分结果
     - 建议手动操作
```

**验证点**:
- [ ] 错误日志记录
- [ ] 自动重试机制
- [ ] 优雅降级（仅用已获得的数据）
- [ ] 用户提示清晰

##### **Scenario B: Context不完整**

```
analyzer SubAgent requires: [network_data, netbox_data]
但netbox SubAgent失败 → network_data存在, netbox_data缺失
  ↓
Orchestrator:
  1. 检测缺失的context
  2. 跳过analyzer SubAgent
  3. 返回query结果
```

**验证点**:
- [ ] 缺失context检测
- [ ] 依赖SubAgent跳过
- [ ] 不阻塞其他支路

#### 3️⃣ 性能压力测试 (1周)

**测试场景**:
```
def test_large_dag_execution():
    """100个SubAgent的DAG执行"""
    # 创建宽DAG: 层级结构
    #   Layer 1: 10个独立SubAgent (可并行)
    #   Layer 2: 20个依赖Layer 1 (可并行)
    #   Layer 3: 30个依赖Layer 2 (可并行)
    #   Layer 4: 40个依赖Layer 3 (可并行)
    
    # 验证？:
    # 1. 执行时间 < 5s (假设每个SubAgent 100ms)
    # 2. 内存使用 < 500MB
    # 3. Context大小 < 100MB

def test_deeply_nested_chain():
    """链式依赖A→B→C→...→Z (26层)"""
    # 验证深层链不会导致堆栈溢出
    # 验证执行时间线性增长
```

**测试文件**: `tests/e2e/test_performance_integration.py`

---

## 🚀 Phase 7: 性能优化 (1-2周)

**目标**: 从串行 → 并行执行，性能提升10x

### 工作项目

#### 1️⃣ 并行执行 (1周)

**当前**: 串行执行
```
query → (100ms) → netbox → (100ms) → analyzer → (100ms)
Total: 300ms
```

**优化后**: 并行执行（DAG-aware）
```
query → (100ms) ─────┐
                      ├→ analyzer → (100ms)
netbox → (100ms) ────┘
Total: 200ms (33% improvement)

For 10 independent SubAgents:
Current:  10 × 100ms = 1000ms
After:    100ms (10x improvement!)
```

**实现方法**:
```python
async def execute_subagents_parallel(graph: DependencyGraph):
    """并行执行无依赖的SubAgent"""
    executed = {}
    
    while not_all_executed(graph):
        # 找出可以执行的SubAgent (依赖都已完成)
        ready = find_ready_subagents(graph, executed)
        
        # 并行执行它们
        results = await asyncio.gather(
            *[execute_subagent(sa) for sa in ready]
        )
        
        # 汇聚结果
        for sa, result in zip(ready, results):
            executed[sa] = result
```

#### 2️⃣ Context缓存 (3天)

**问题**: 每次execution都重新执行所有SubAgent

**解决**:
```python
class ContextCache:
    """缓存SubAgent执行结果"""
    cache: Dict[str, Dict] = {}  # subagent → context
    ttl: Dict[str, float] = {}   # 过期时间
    
    def get(self, subagent: str, max_age_sec: int = 3600) -> Dict | None:
        """获取缓存的context（1小时内有效）"""
        if subagent in self.cache and not self.is_expired(subagent):
            return self.cache[subagent]
        return None
    
    def set(self, subagent: str, context: Dict):
        """缓存execution结果"""
        self.cache[subagent] = context
        self.ttl[subagent] = time.time() + 3600
```

#### 3️⃣ 执行指标 (1周)

**收集指标**:
```python
class ExecutionMetrics:
    """追踪execution性能"""
    subagent_times: Dict[str, float]     # 每个SubAgent耗时
    context_sizes: Dict[str, int]        # Context大小
    total_time: float
    parallelism_ratio: float             # 1.0=完全串行, N=N路并行
```

**示例输出**:
```
Execution Metrics for /plan "同步NetBox数据":
─────────────────────────────────────────────
query:      100ms │████░░░░░░│
netbox:     150ms │██████░░░░│
analyzer:   200ms │████████░░│
─────────────────────────────────────────────
Total:      450ms (串行时间: 450ms, 并行: 150ms)
Parallelism: 3.0x (3路并行能力)
Context size: 2.5 MB
```

---

## 🔧 Phase 8: 生产环保验证 (2-4周)

**目标**: 真实环境测试, 性能基准, 监控告警

### 工作项目

#### 1️⃣ 真实场景验证

- [ ] NetBox现网环境测试
- [ ] 1000+ 设备规模测试
- [ ] 多并发用户场景

#### 2️⃣ 稳定性测试

- [ ] 24小时连续运行测试
- [ ] 异常网络条件（高延迟, 丢包）
- [ ] SubAgent故障注入（强制timeout）

#### 3️⃣ 监控&告警

- [ ] Prometheus指标导出
- [ ] Grafana仪表板
- [ ] AlertManager规则

---

## ⏱️ 时间预估表

| Phase | 工作 | 时间 | 优先级 |
|-------|------|------|--------|
| **5 REFACTOR** | 代码+文档+测试 | 3-4天 | ⭐⭐⭐ HIGH |
| **6** | 集成测试 | 2-3周 | ⭐⭐⭐ HIGH |
| **7** | 性能优化 | 1-2周 | ⭐⭐ MEDIUM |
| **8** | 生产验证 | 2-4周 | ⭐⭐ MEDIUM |
| **Total** | | **7-12周** | |

---

## 📊 成功标准

### Phase 5 REFACTOR

✅ 所有代码有类型提示  
✅ 单元测试覆盖率 > 90%  
✅ 文档完成度 100%  
✅ 无回归（所有Phase 1-4测试仍通过）

### Phase 6

✅ NetBox同步完整流程验证  
✅ 错误恢复机制有效  
✅ 性能基准建立（<500ms for typical workflow）

### Phase 7

✅ 并行执行提升性能 > 5倍  
✅ Context缓存命中率 > 80%  
✅ 内存使用量 < 500MB

### Phase 8

✅ 24小时稳定运行  
✅ 错误率 < 0.1%  
✅ 监控覆盖率 100%

---

## 🎬 立即行动项

### 本周 (2026-02-07 ~ 2026-02-13)

- [ ] Phase 5 REFACTOR
  - [ ] 提取 `src/olav/core/dependency.py`
  - [ ] 添加类型提示
  - [ ] 完善文档
- [ ] 规划Phase 6详细设计

### 下周 (2026-02-14 ~ 2026-02-20)

- [ ] Phase 6正式开始
  - [ ] 创建集成测试框架
  - [ ] 实现NetBox同步测试
  - [ ] 实现错误恢复测试

---

**版本**: v1.0  
**Last Updated**: 2026-02-07  
**Next Review**: 2026-02-13
