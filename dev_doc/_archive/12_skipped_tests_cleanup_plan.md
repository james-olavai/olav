# Skipped测试处理规划 - v0.10.0

## 总体策略

**淘汰**: 删除架构/设计无关的测试（3个）  
**改造**: 保留LLM相关，但改为e2e框架（5个）  
**保留**: 保留基础验证（8个正常运行）

---

## 第1类：淘汰（删除不需要的）- 3个

### 1.1 test_query_agent_marked_deprecated ❌ DELETE
**文件**: `tests/unit/test_query_subagent_migration.py`

**理由**: 
- 非功能性测试（仅检查deprecation warning）
- QueryAgent已标记废弃，decorator已存在
- 单元测试不需要验证warning message
- 集成测试中可间接验证

**处理**: 删除此测试

---

### 1.2 test_analysis_accuracy_parity ⏭️ ALREADY SKIPPED
**文件**: `tests/unit/test_analyzer_subagent_migration.py`

**理由**:
- Analyzer已迁移为graph-based SubAgent
- create_analyzer_agent()函数无法存在（架构决定）
- 无法做"对等性"比较（不同架构）
- 已正确设计为skip

**处理**: 保持SKIPPED (无需修复)

---

### 1.3 test_analyzer_marked_deprecated ⏭️ ALREADY SKIPPED
**文件**: `tests/unit/test_analyzer_subagent_migration.py`

**理由**:
- Analyzer已迁移完成，是SubAgent而非废弃对象
- SubAgent本身不需要deprecation warning
- 非功能性测试

**处理**: 保持SKIPPED (无需修复)

---

## 第2类：改造为e2e（需要LLM）- 5个

### 2.1 test_template_iteration 🔄 MOVE TO E2E
**原位置**: `tests/unit/test_textfsm_agent.py`  
**新位置**: `tests/e2e/test_textfsm_complete_flow.py`

**改造内容**:
```python
# 原: 单元测试，mock一切
# 新: e2e测试，调用真实LLM

class TestTextFSMIterationFlow:
    @pytest.mark.skipif(not has_llm_api(), reason="需要LLM API")
    async def test_template_iteration_with_llm(self):
        """生成模板 → 改进反馈 → 再次生成"""
        # 需要: OPENAI_API_KEY 或 LLM_API_KEY
        # 流程: 
        # 1. 用户: "为Cisco生成show interfaces模板"
        # 2. TextFSM agent生成初版
        # 3. 用户反馈: "需要VLAN支持"
        # 4. Agent改进模板
        # 5. 验证改进版本有效
```

**工作量**: 2小时  
**优先级**: 🟡 Medium

---

### 2.2 test_template_testing_node 🔄 MOVE TO E2E
**原位置**: `tests/unit/test_textfsm_agent.py`  
**新位置**: `tests/e2e/test_textfsm_complete_flow.py`

**改造内容**:
```python
class TestTextFSMTestNode:
    @pytest.mark.skipif(not has_llm_api(), reason="需要LLM API")
    async def test_template_testing_with_real_data(self):
        """生成模板 → 用真实数据测试"""
        # 需要: 真实网络命令输出样本
        # 流程:
        # 1. 获取样本输出: show interfaces output
        # 2. TextFSM生成模板
        # 3. 用样本数据测试模板
        # 4. 验证parsing结果正确率 > 95%
```

**工作量**: 2小时  
**优先级**: 🟡 Medium

---

### 2.3 test_template_analysis_node 🔄 MOVE TO E2E
**原位置**: `tests/unit/test_textfsm_agent.py`  
**新位置**: `tests/e2e/test_textfsm_complete_flow.py`

**改造内容**:
```python
class TestTextFSMAnalysisNode:
    @pytest.mark.skipif(not has_llm_api(), reason="需要LLM API")
    async def test_template_analysis_with_llm(self):
        """生成 → 测试 → 分析改进建议"""
        # 需要: LLM的分析和建议能力
        # 流程:
        # 1. TextFSM生成初版模板
        # 2. 用测试数据验证
        # 3. LLM分析: "匹配率95%，建议支持边界情况X"
        # 4. 验证建议有效性
```

**工作量**: 3小时  
**优先级**: 🟡 Medium

---

### 2.4 test_cache_invalidation_after_ttl 🔄 ENHANCE
**原位置**: `tests/unit/test_query_subagent_migration.py`  
**方案**: 添加time mock实现

**改造内容**:
```python
import time
from unittest.mock import patch

def test_cache_invalidation_after_ttl():
    """TTL过期后缓存失效"""
    # 1. 存入缓存，TTL=2秒
    cache.set(key, value, ttl=2)
    
    # 2. 立即读取 → hit
    assert cache.get(key) == value
    
    # 3. Mock time.time()快进3秒
    with patch('time.time', return_value=time.time() + 3):
        # 4. 再次读取 → miss (过期)
        assert cache.get(key) is None
```

**工作量**: 1小时  
**优先级**: 🟡 Medium

---

### 2.5 test_references_similar_cases 🔄 NEEDS KB
**原位置**: `tests/unit/test_analyzer_subagent_migration.py`  
**方案**: 先创建测试知识库

**改造内容**:
```python
# 需要: 测试知识库中有历史案例
# 流程:
# 1. 初始化知识库 (Knowledge base setup)
# 2. 插入示例案例: "设备CPU高" → "内存泄漏诊断"
# 3. 用户询问: "CPU高的原因"
# 4. Analyzer检索相似案例
# 5. 验证返回的案例相关性 > 0.8
```

**依赖**: Task #3 (创建测试知识库)  
**工作量**: 2小时  
**优先级**: 🟡 Medium

---

## 实施步骤

### 阶段1: 淘汰（第1类）- 30分钟
```bash
# 1. 删除test_query_agent_marked_deprecated
pytest tests/unit/test_query_subagent_migration.py -v
# → 应该还是有7/7通过（删除后）

# 2. 验证其他2个保持SKIPPED状态
pytest tests/unit/test_analyzer_subagent_migration.py -v
# → 应该显示 6/8通过，2个SKIPPED (by design)
```

### 阶段2: 改造为e2e（第2类）- 8-10小时
1. **配置LLM** (1小时)
   - 设置环境变量: LLM_API_KEY, LLM_BASE_URL
   - 验证API连接

2. **创建e2e框架** (1小时)
   - 补充test_textfsm_complete_flow.py中的3个test_*方法
   - 添加skip条件: `@pytest.mark.skipif(not has_llm_api(), reason="...")`

3. **实现TextFSM e2e** (4小时)
   - test_template_iteration_with_llm
   - test_template_testing_with_real_data
   - test_template_analysis_with_llm
   - 调用真实LLM，验证流程完整性

4. **补充缓存TTL测试** (1小时)
   - 添加time mock
   - 验证TTL失效机制

5. **补充知识库测试** (2小时)
   - 先完成task #3
   - 实现test_references_similar_cases

### 阶段3: 最终验证（第3部分）
```bash
# 最后运行完整测试
pytest tests/unit/ tests/e2e/test_textfsm_complete_flow.py -v
# 预期:
# - unit: 25 passed, 3 skipped (by design) ✅
# - e2e: 3+ passed (需LLM, 可能skip如果无API)
```

---

## 预期结果

### 删除前 (当前)
```
✅ Unit: 25 passed, 8 skipped
❌ 其中3个skip是"淘汰设计"
❌ 其中5个skip需要改造为e2e
```

### 删除后 (目标)
```
✅ Unit: 24 passed, 3 skipped (都是"by design")
✅ E2E: 3+ passed (需LLM)
✅ 所有skip都有明确理由和计划
```

---

## 相关文件

- `tests/unit/test_query_subagent_migration.py` - 删除test_query_agent_marked_deprecated
- `tests/unit/test_textfsm_agent.py` - 删除3个test_*_node
- `tests/e2e/test_textfsm_complete_flow.py` - 添加3个真实测试
- `tests/unit/test_query_subagent_migration.py` - 增强test_cache_invalidation_after_ttl

---

**预计总工作量**: 8-10小时  
**优先级排序**: LLM配置 → TextFSM e2e → 缓存TTL → 知识库测试  
**版本**: v0.10.0
