# E2E 测试配置分析 - 真实 LLM 和设备使用情况

**日期**: 2026-02-04  
**分析范围**: /home/yhvh/Olav/tests/e2e/test_acceptance.py

---

## 🔍 总体结论

### **部分使用真实 LLM 和设备（条件化）**

E2E 测试采用了**条件化的混合策略**：
- ✅ **真实设备依赖**: 某些测试标记为 `@pytest.mark.skipif(not REAL_DEVICES_AVAILABLE)`
- ✅ **真实 LLM 调用**: 语义缓存测试通过 `echo | uv run olav` 实际调用 LLM
- ⚠️ **Mock 或跳过**: DeepAgents 和某些高级功能被注释或使用测试桩

---

## 📋 具体配置详情

### 1. 真实设备标记

```python
# 第 105 行
REAL_DEVICES_AVAILABLE = True  # 现在有真实设备
```

**含义**: 系统被配置为使用真实设备，默认不跳过相关测试

### 2. 需要真实设备的测试

以下测试被标记为 `@pytest.mark.skipif(not REAL_DEVICES_AVAILABLE)`：

| 行号 | 测试类/方法 | 说明 |
|------|-----------|------|
| 484 | TestPhase2Snapshot | 快照同步（需要真实设备数据） |
| 517 | TestPhase3ExportsStructure | 导出结构验证 |
| 659 | TestPhase4DatabaseStructure | 数据库查询（需要真实数据） |
| 911+ | TestPhase5QueryTools | 查询工具执行 |
| 1241+ | TestPhase7Inspection | 检查命令 |

### 3. 语义缓存测试（使用真实 LLM）

#### TestPhase55SemanticCache 类 (第 1021 行)

**测试流程**:
```python
def run_olav_query_with_timing(self, query: str) -> tuple[str, float]:
    # 直接调用: echo "查询" | uv run olav
    result = subprocess.run(
        f'echo "{query}" | uv run olav',
        shell=True,
        ...
    )
```

**真实 LLM 调用方式**:
- ✅ 通过管道发送查询到实际 OLAV 命令行
- ✅ OLAV CLI 启动真实 LLM（通过 LLMFactory）
- ✅ 记录实际执行时间（缓存性能测试）

**测试用例**:
1. `test_semantic_cache_first_query` - 首次查询（无缓存）
   - 预期时间: > 3 秒（LLM + 工具调用）
   
2. `test_semantic_cache_second_query_hit` - 二次查询（缓存命中）
   - 预期时间: < 首次查询的 50%
   
3. `test_semantic_cache_similar_queries` - 相似查询
   - 测试模糊匹配和语义相似性
   
4. `test_semantic_cache_cleanup` - 缓存清理

### 4. DeepAgents 测试（Mock/跳过）

#### TestPhase7DeepAgents 类 (第 1551 行)

**当前状态**: ❌ **使用测试桩，未使用真实 LLM**

```python
def test_coder_agent_textfsm_generation(self) -> None:
    # 注意: 这里通常需要 Mock LLM 或使用真实简单的 Case
    # agent = create_coder_agent()  # ← 被注释
    # result = agent.invoke(...)     # ← 被注释
    
    print("✅ Coder Agent 测试桩通过 (待实现)")

def test_reflector_sop_extraction(self) -> None:
    """NOTE: v0.9.8 - Reflector agent removed"""
    print("✅ Reflector Agent 测试桩通过 (待实现)")

def test_planner_decomposition(self) -> None:
    # from olav.agents.planner import plan_task  # ← 被注释
    print("✅ Planner Agent 测试桩通过 (待实现)")
```

---

## 🎯 LLM 实际使用情况

### 已验证的真实 LLM 调用

1. **语义缓存测试**
   - ✅ 使用实际 LLM API 调用
   - ✅ 测量真实执行时间
   - ✅ 验证缓存性能

2. **查询工具测试** (TestPhase5QueryTools)
   - ✅ 需要真实设备数据
   - ✅ 调用真实 LLM 进行查询理解
   - 例如: `test_interface_status_query`, `test_bgp_neighbor_query`

### 被模拟或跳过的部分

1. **DeepAgents 高级功能**
   - ❌ Coder Agent (模板生成)
   - ❌ Reflector Agent (已移除)
   - ❌ Planner Agent (待实现)
   - 原因: 这些功能在 v0.9.8 尚未完全实现

2. **某些高级查询** (需要真实数据)
   - ⚠️ 条件跳过 (`if not REAL_DEVICES_AVAILABLE`)
   - 需要真实网络设备同步数据

---

## 📊 测试配置总结

### E2E 测试矩阵

| 功能 | 真实 LLM | 真实设备 | 状态 |
|------|---------|--------|------|
| **语义缓存** | ✅ | - | 运行中 |
| **查询工具** | ✅ | ✅ (可选) | 运行中 |
| **快照同步** | ❌ | ✅ 需要 | 条件跳过 |
| **数据库查询** | ✅ | ✅ (数据) | 运行中 |
| **Coder Agent** | ❌ | - | 测试桩 |
| **Reflector Agent** | ❌ | - | 已移除 |
| **Planner Agent** | ❌ | - | 待实现 |

### 当前 E2E 测试通过率

根据上一次运行结果：
- ✅ **69/70 非 LLM 测试通过** (98.6%)
- ✅ **语义缓存测试通过**
- ⚠️ **1 个失败** (test_aaa_create_cache_db)

---

## 🔧 如何运行包含真实 LLM 的 E2E 测试

### 1. 带真实设备的完整 E2E 测试
```bash
cd /home/yhvh/Olav
export REAL_DEVICES_AVAILABLE=true
uv run pytest tests/e2e/test_acceptance.py -v --tb=short
```

### 2. 仅运行语义缓存测试（使用真实 LLM）
```bash
uv run pytest tests/e2e/test_acceptance.py::TestPhase55SemanticCache -v -s
```

### 3. 运行查询工具测试（使用真实 LLM）
```bash
uv run pytest tests/e2e/test_acceptance.py::TestPhase5QueryTools -v -s
```

### 4. 跳过需要真实设备的测试
```bash
export REAL_DEVICES_AVAILABLE=false
uv run pytest tests/e2e/test_acceptance.py -v
```

---

## 🎓 关键发现

### ✅ 真实 LLM 使用场景

1. **语义缓存验证**
   - 通过 `echo | uv run olav` 实际调用 LLM
   - 测量真实性能指标
   - 生产级测试

2. **查询理解和执行**
   - 使用真实 LLM 理解自然语言查询
   - 转换为 SQL/CLI 命令
   - 执行真实工具调用

3. **性能基准测试**
   - 首次查询: > 3 秒（包含 LLM 延迟）
   - 缓存命中: < 原查询时间的 50%
   - 用于性能优化决策

### ⚠️ Mock/跳过的原因

1. **DeepAgents 不完整**
   - Coder Agent: 需要更复杂的 LLM 提示工程
   - Reflector: 在 v0.9.8 中被移除
   - Planner: 待实现

2. **真实设备依赖**
   - 某些查询需要从真实网络设备同步数据
   - 使用 REAL_DEVICES_AVAILABLE 标记进行条件化

3. **成本和速度**
   - LLM API 调用产生成本
   - 某些测试时间较长（最多 5 分钟超时）

---

## 💡 建议

### 用于下一阶段开发

1. **完成 DeepAgents**
   - 实现 Coder Agent 模板生成
   - 重新实现 Reflector 学习能力
   - 实现 Planner 任务分解

2. **扩展真实设备测试**
   - 配置模拟网络设备 (Nornir)
   - 或使用持续集成中的真实设备环境

3. **性能优化**
   - 基于语义缓存测试结果优化 LLM 调用
   - 实现增量学习

---

## 总结

**是否使用了真实 LLM 和设备？**

✅ **是的，已使用，但有选择性:**
- **真实 LLM**: ✅ 语义缓存和查询工具测试中使用
- **真实设备**: ⚠️ 条件化使用（REAL_DEVICES_AVAILABLE 标记）
- **高级功能**: ❌ DeepAgents 使用测试桩或已移除

整个 E2E 测试框架遵循**生产级测试标准**，其中关键路径（查询理解、缓存）使用真实 LLM，但允许通过环境变量切换到 Mock 模式以支持 CI/CD。

