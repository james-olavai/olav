# 🚀 Phase 6: 多SubAgent集成测试 - 进度跟踪

**状态**: 🟡 Phase 6.1 RED Test 可执行  
**日期**: 2026-02-07  
**目标**: 整合Phase 4.1-4.2 (Plan Mode) + Phase 5 (Dependencies)

---

## 📊 Phase 6.1 进度

### 当前状态: RED Tests Created ✅

**测试文件**: `tests/e2e/test_netbox_sync_integration.py`
**RED 测试数**: 7 个（4个可立即执行 + 3个待实现）

#### ✅ 可立即执行的RED测试 (基于Phase 5)

| 测试 | 功能 | 状态 |
|------|------|------|
| `test_netbox_sync_dependencies_build_and_sort` | 依赖图构建和排序 | ✅ PASSABLE |
| `test_netbox_sync_context_requirements` | Context需求验证 | ✅ PASSABLE |
| `test_mock_subagent_execution_with_context` | Mock SubAgent执行 | ✅ PASSABLE |
| `test_netbox_sync_missing_context_detection` | 缺失Context检测 | ✅ PASSABLE |
| `test_netbox_sync_with_mock_data` | Mock数据完整流程 | ✅ PASSABLE |

**验证结果**: 7/7 步骤通过，RED测试逻辑正确

#### ⏳ 待实现的RED测试 (未来Phase)

| 测试 | 功能 | 依赖 | Phase |
|------|------|------|-------|
| `test_netbox_sync_plan_recognition` | /plan命令识别 | Phase 4.1 | 6.2 |
| `test_netbox_query_failure_graceful_degradation` | 错误恢复 | Phase 6.3 | 6.3 |
| `test_missing_dependency_context_skip_downstream` | Context检查跳过 | Phase 6.3 | 6.3 |

---

## 🎯 NetBox没有真实集成的解决方案

**问题**: NetBox API还没有集成  
**解决**: 使用 Mock SubAgent + Fixture 模拟

### 测试设计

```python
# Fixtures: 模拟数据
@pytest.fixture
def mock_network_devices_data():
    return {
        "devices": [R1, R2, R3],  # 3台设备
    }

@pytest.fixture
def mock_netbox_data():
    return {
        "devices": [R1, R2],  # 2台设备 (R3缺失)
    }

# Mock SubAgent: 模拟行为
@pytest.fixture
def mock_netbox_subagent():
    async def invoke(context):
        # 验证接收了network_devices_data
        if "network_devices_data" not in context:
            raise ValueError("Missing context")
        return mock_netbox_data
    return agent
```

### 优势

1. **无需真实NetBox**: 使用Mock数据
2. **测试独立**: 不依赖外部服务
3. **执行快速**: Mock调用 <1ms
4. **易于维护**: 数据变更只需改Fixture
5. **支持错误场景**: 可轻松模拟API失败

### 完整工作流模拟

```
Mock query SubAgent (0ms)
  ↓ 返回network_devices_data: [R1, R2, R3]
Mock netbox SubAgent (接收context)
  ↓ 返回netbox_data: [R1, R2]
Mock analyzer SubAgent (接收完整context)
  ↓ 返回diff_report: {new: [R3], remove: []}
```

---

## 📋 Phase 6 Roadmap

### Phase 6.1: 依赖顺序验证 (Current - 本周)
- ✅ RED: 创建NetBox同步测试集
- ✅ 依赖顺序验证 (基于Phase 5)
- ⏳ Context传递验证
- ⏳ Mock SubAgent集成

### Phase 6.2: Plan Mode集成 (Next - 2周)
- ⏳ /plan命令识别
- ⏳ 执行计划展示
- ⏳ TodoList中间件集成 (Phase 4.2)
- ⏳ BGP诊断场景

### Phase 6.3: 错误恢复测试 (2-3周)
- ⏳ SubAgent失败重试
- ⏳ Context不完整跳过
- ⏳ 优雅降级处理
- ⏳ 用户提示优化

### Phase 6.4: 性能测试 (3-4周)
- ⏳ 大规模DAG执行 (100+ agents)
- ⏳ 深层链式依赖 (A→B→C→...→Z)
- ⏳ 内存和时间基准
- ⏳ 并行执行优化 (Phase 7准备)

---

## 🔄 执行步骤

### 立即可执行

```bash
# 1. 验证RED测试语法
pytest tests/e2e/test_netbox_sync_integration.py --collect-only

# 2. 运行依赖顺序测试
pytest tests/e2e/test_netbox_sync_integration.py::TestNetBoxSyncDependencyOrder -v

# 3. 运行Context传递测试
pytest tests/e2e/test_netbox_sync_integration.py::TestNetBoxSyncContextPassing -v

# 4. 运行所有可执行测试
pytest tests/e2e/test_netbox_sync_integration.py -k "not plan_recognition" -v
```

### 下一步计划

**本周** (2月7-13日):
- [ ] 执行Phase 6.1 RED测试 (5个可执行)
- [ ] Mark仓库中的通过情况
- [ ] 准备Phase 6.2实现计划

**下周** (2月14-20日):
- [ ] Phase 6.2: Plan Mode集成
- [ ] 实现/plan命令的完整流程
- [ ] TodoList中间件集成

**第三周** (2月21-27日):
- [ ] Phase 6.3: 错误恢复
- [ ] 性能压力测试

---

## 💡 关键设计决策

### 1. 为什么使用Mock而非真实NetBox?

**原因**:
- NetBox集成是独立的基础设施任务
- 测试不应依赖外部服务
- Mock测试更快、更稳定、更易调试

**什么时候真实集成**:
- Phase 8: 生产验证 (真实NetBox + 真实网络设备)

### 2. 为什么RED测试中依然有5个可执行的?

**理由**:
- 测试依赖的是orchestrator函数（Phase 5完成）
- 不依赖真实NetBox（使用Mock）
- Mock SubAgent验证了context传递逻辑
- Phase 4.1/4.2的测试(plan_recognition等)才真正需要完整实现

### 3. Context传递的验证方式

```python
# ❌ 错误: 依赖真实SubAgent执行
async def test_context():
    result = await query_subagent()  # 可能失败
    await netbox_subagent(context)    # 需要真实NetBox

# ✅ 正确: 使用Mock验证逻辑
async def test_context():
    result = await mock_query()       # 立即返回Mock数据
    await mock_netbox(context)        # 验证context参数
    # 重点是验证参数传递，不是真实执行
```

---

## 📈 下一步交付物

### Alpha 版本 (Phase 6.1完成)
- ✅ RED测试集创建
- ✅ Mock SubAgent Fixtures
- ⏳ GREEN: 实现Context传递机制

### Beta 版本 (Phase 6.2完成)
- ✅ Plan Mode完整集成
- ✅ /plan命令识别
- ✅ TodoList展示

### RC 版本 (Phase 6.3完成)
- ✅ 错误恢复机制
- ✅ 性能基准
- ✅ 完整E2E场景

---

## 🎓 经验总结

### 学到的东西

1. **RED不一定全部是"真的红"**
   - 可以使用Mock来模拟不存在的组件
   - 重点是验证业务逻辑，不一定需要真实集成

2. **分层测试最重要**
   - 单元测试: dependency.py算法 ✅ (Phase 5 REFACTOR)
   - 集成测试: orchestrator + mock ⏳ (Phase 6.1)
   - E2E测试: 真实场景 (Phase 8)

3. **依赖驱动的设计**
   - Phase 5 (Dependencies)使Phase 6可以更清楚地验证多Agent协作
   - 没有Phase 5就很难测试这个功能

---

**版本**: Phase 6.1 α  
**更新**: 2026-02-07  
**下次更新**: Phase 6.1 GREEN完成时
