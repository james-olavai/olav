# Pytest + Ruff 改进计划 (v0.10.2+)

**制定日期**: 2026年2月6日  
**目标**: 提升核心代码测试覆盖率，强化 ruff linting，特别是 agent 模块

---

## 📊 当前状态分析

### 测试覆盖率现状

**整体覆盖率**: 8.54% (E2E 真实场景测试)

**Agent 模块覆盖情况**:
```
高优先级模块 (需要重点覆盖):
├── agent_enhancements.py        254 行, 0% 覆盖 ❌ (CRITICAL)
├── analyzer.py                   249 行, 15% 覆盖 ❌ (CRITICAL)
├── diagnosis_cache.py             74 行, 0% 覆盖 ❌
├── inspector.py                 128 行, 0% 覆盖 ❌
├── intent_agent.py              167 行, 15% 覆盖 ❌
├── orchestrator.py               94 行, 67% 覆盖 ✅ (部分覆盖)
├── query_agent.py               275 行, 10% 覆盖 ❌ (CRITICAL)
├── relevance_checker.py           24 行, 0% 覆盖 ❌
├── subagent_pool.py              37 行, 0% 覆盖 ❌
├── textfsm_agent.py             167 行, 20% 覆盖 ❌
├── tool_loader.py                26 行, 50% 覆盖 ⚠️
└── query_agent_v2.py (archived)  - 已弃用
```

**总计**: 1,197 行 agent 代码，平均 11% 覆盖率

---

### Ruff Linting 现状

**当前规则配置**:
```ini
[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "ANN", "ASYNC", "S", "B"]
ignore = ["E402", "E501"]

# Agent 模块当前忽略规则:
"src/olav/agents/intent_agent.py" = ["ANN401"]  # 动态类型
"src/olav/agents/orchestrator.py" = ["ANN401"]  # Agent 包装器
```

**问题**:
- ❌ 未启用 PEP 8 风格 (E)、安全 (S)、最佳实践 (B)
- ❌ 过度忽略 ANN401，导致类型注解不完整
- ❌ 无模块级文档检查 (D)
- ❌ 无复杂度检查 (C)

---

## 🎯 改进目标

### 短期目标 (v0.10.2, 2-3周)

| 目标 | 当前 | 目标 | 优先级 |
|------|------|------|--------|
| Agent 模块覆盖率 | 11% | **50%** | 🔴 HIGH |
| 高优先级模块覆盖 | 0-15% | **70%** | 🔴 HIGH |
| Ruff 违规数 | ~50 | **0** | 🟡 MEDIUM |
| 类型注解完整度 | 70% | **90%** | 🟡 MEDIUM |

### 长期目标 (v0.10.3+)

- Agent 模块覆盖率达到 80%+
- Ruff 启用 strict 模式
- 引入 mypy strict 检查

---

## 📋 实施计划

### Phase 1: 核心 Agent 模块单元测试 (优先级: 🔴 HIGH)

#### 1.1 orchestrator.py 强化 (已部分覆盖)

**当前状态**: 67% 覆盖 ✅

**需要补充**:
- [ ] 异常路径测试 (缓存失败、LLM 超时)
- [ ] 评估模块边界情况
- [ ] 结果缓存/输出验证

**测试文件**: `tests/unit/agents/test_orchestrator.py`

```python
@pytest.mark.asyncio
class TestOrchestrator:
    """Orchestrator 单元测试 (augment existing)"""
    
    async def test_orchestrate_with_cache_miss(self):
        """缓存未命中 → 路由 → 执行 → 缓存"""
        
    async def test_orchestrate_with_llm_timeout(self):
        """LLM 超时 → 降级处理"""
        
    async def test_evaluate_decides_upgrade(self):
        """评估模块决定是否升级结果"""
```

**目标覆盖率**: 95%

---

#### 1.2 query_agent.py 单元测试 (CRITICAL)

**当前状态**: 10% 覆盖 ❌

**需要覆盖的关键函数**:
```python
- async query_database(sql, params)      # 275 行模块 - 核心数据查询
- async prepare_context()                # 上下文准备
- async route_query()                    # 查询路由
```

**测试文件**: `tests/unit/agents/test_query_agent.py`

```python
@pytest.mark.asyncio
class TestQueryAgent:
    """QueryAgent 数据库查询和路由测试"""
    
    async def test_query_database_with_valid_sql(self):
        """有效 SQL → 返回结果字典列表"""
        
    async def test_query_database_with_invalid_sql(self):
        """无效 SQL → RuntimeError"""
        
    async def test_query_database_with_params(self):
        """参数化查询 → 正确替换"""
        
    async def test_prepare_context_with_schema(self):
        """数据库模式 → 上下文字符串"""
        
    async def test_route_query_intent_classification(self):
        """意图分类 → 路由到正确agent"""
```

**目标覆盖率**: 80%

---

#### 1.3 analyzer.py 单元测试 (CRITICAL)

**当前状态**: 15% 覆盖 ❌

**需要覆盖的关键函数**:
```python
- async diagnose_issue()                 # 核心诊断逻辑
- async analyze_output()                 # 输出分析
- async run_nornir_checks()              # Nornir 网络命令
```

**测试文件**: `tests/unit/agents/test_analyzer.py`

```python
@pytest.mark.asyncio
class TestAnalyzer:
    """Analyzer 网络诊断测试"""
    
    async def test_diagnose_issue_with_known_symptom(self):
        """已知症状 → 诊断路径"""
        
    async def test_analyze_output_parsing(self):
        """原始输出 → 结构化分析"""
        
    async def test_run_nornir_checks_device_filter(self):
        """设备过滤 → Nornir 命令执行"""
        
    async def test_run_nornir_checks_timeout(self):
        """超时处理 → 优雅降级"""
```

**目标覆盖率**: 70%

---

#### 1.4 agent_enhancements.py 单元测试 (CRITICAL)

**当前状态**: 0% 覆盖 ❌ (254 行关键代码)

**需要覆盖的关键增强**:
```python
- enrich_with_embeddings()               # 嵌入式增强
- cache_diagnosis_result()               # 诊断缓存
- format_for_llm()                       # LLM 格式化
```

**测试文件**: `tests/unit/agents/test_agent_enhancements.py`

```python
class TestAgentEnhancements:
    """Agent 增强功能单元测试"""
    
    def test_enrich_with_embeddings(self):
        """数据 → 嵌入向量"""
        
    def test_cache_diagnosis_result(self):
        """诊断结果 → 缓存存储"""
        
    def test_format_for_llm_with_context(self):
        """上下文 → LLM 格式化文本"""
```

**目标覆盖率**: 75%

---

#### 1.5 其他 Agent 模块 (优先级: MEDIUM)

| 模块 | 行数 | 覆盖 | 测试文件 | 目标 |
|------|------|------|---------|------|
| intent_agent.py | 167 | 15% | test_intent_agent.py | 60% |
| diagnosis_cache.py | 74 | 0% | test_diagnosis_cache.py | 80% |
| inspector.py | 128 | 0% | test_inspector.py | 60% |
| textfsm_agent.py | 167 | 20% | test_textfsm_agent.py | 65% |
| relevance_checker.py | 24 | 0% | test_relevance_checker.py | 90% |
| subagent_pool.py | 37 | 0% | test_subagent_pool.py | 80% |

---

### Phase 2: Agent 集成测试 (优先级: 🟡 MEDIUM)

**文件**: `tests/integration/agents/test_agent_integration.py`

```python
@pytest.mark.asyncio
class TestAgentIntegration:
    """Agent 协作集成测试"""
    
    async def test_orchestrator_with_query_agent(self):
        """Orchestrator → QueryAgent 集成"""
        
    async def test_orchestrator_with_analyzer(self):
        """Orchestrator → Analyzer 集成"""
        
    async def test_full_diagnostic_workflow(self):
        """完整诊断流程: 路由 → 执行 → 评估"""
        
    async def test_agent_error_handling_chain(self):
        """Agent 错误处理链"""
```

**目标**: 覆盖 agent 间协作流程

---

### Phase 3: Ruff Linting 强化

#### 3.1 更新 Ruff 配置

**文件**: `pyproject.toml` [tool.ruff.lint]

```toml
# 新增规则
select = ["E", "F", "I", "N", "W", "UP", "ANN", "ASYNC", "S", "B", "D100", "D101", "C901"]

# 更新忽略规则（更严格）
ignore = ["E402", "E501"]

# Agent 模块: 移除过度忽略
"src/olav/agents/intent_agent.py" = ["S104"]  # 仅忽略特定规则
"src/olav/agents/orchestrator.py" = ["S104"]

# 新增模块级检查
"src/olav/agents/*.py" = ["D100"]  # 需要模块文档
```

#### 3.2 修复现有 Ruff 违规

**预计工作量**: ~50-100 个违规修复

主要违规类型:
```
- [ ] 未使用的导入 (F401)
- [ ] 缺少类型注解 (ANN001, ANN201)
- [ ] 不安全的代码 (S602, S608)
- [ ] PEP 8 风格 (E741, W605)
```

**实施步骤**:
```bash
# 1. 运行 ruff 检查
uv run ruff check src/olav/agents/ --select=F,E,W --show-fixes

# 2. 自动修复
uv run ruff check src/olav/agents/ --fix

# 3. 手工修复 (需要开发者介入)
# - ANN001/ANN201 类型注解
# - 安全相关问题 (S602, S608)
```

---

## 🛠️ 实施步骤

### Week 1: Agent 单元测试基础

- [ ] 创建测试文件结构
  ```
  tests/unit/agents/
  ├── __init__.py
  ├── test_orchestrator.py (强化)
  ├── test_query_agent.py (新)
  ├── test_analyzer.py (新)
  ├── test_agent_enhancements.py (新)
  ├── test_intent_agent.py (新)
  ├── test_diagnosis_cache.py (新)
  └── conftest.py (agent fixtures)
  ```

- [ ] 实现 orchestrator 强化测试
- [ ] 实现 query_agent 单元测试
- [ ] 实现 analyzer 单元测试

### Week 2: 补充测试 + Ruff 强化

- [ ] 实现 agent_enhancements 单元测试
- [ ] 实现其他 agent 模块单元测试
- [ ] 更新 ruff 配置
- [ ] 修复现有 ruff 违规

### Week 3: 集成测试 + 验证

- [ ] 实现 agent 集成测试
- [ ] 运行完整测试套件验证覆盖率
- [ ] 性能基准测试 (可选)
- [ ] 文档更新

---

## 📊 成功指标

| 指标 | 当前 | 目标 | 检查方式 |
|------|------|------|---------|
| Agent 覆盖率 | 11% | **50%** | `pytest --cov=src/olav/agents` |
| orchestrator 覆盖率 | 67% | **95%** | htmlcov/z_*.html |
| query_agent 覆盖率 | 10% | **80%** | htmlcov 报告 |
| analyzer 覆盖率 | 15% | **70%** | htmlcov 报告 |
| Ruff violations | ~50 | **0** | `ruff check src/` |
| 测试通过率 | 100% | **100%** | pytest 输出 |

---

## 📚 测试编写指南

### 单元测试模板

```python
import pytest
from unittest.mock import Mock, AsyncMock, patch
from src.olav.agents.target_module import TargetClass

@pytest.fixture
def mock_llm():
    """Mock LLM for testing"""
    return AsyncMock()

@pytest.fixture
def mock_db(monkeypatch):
    """Mock database"""
    mock = Mock()
    mock.query.return_value = [{"id": 1, "name": "test"}]
    return mock

@pytest.mark.asyncio
class TestTargetAgent:
    """目标 Agent 测试"""
    
    async def test_success_path(self, mock_llm, mock_db):
        """正常路径测试"""
        # Arrange
        agent = TargetClass(llm=mock_llm, db=mock_db)
        
        # Act
        result = await agent.execute(...)
        
        # Assert
        assert result is not None
        mock_llm.predict.assert_called_once()
    
    async def test_error_handling(self, mock_llm):
        """异常处理测试"""
        # Arrange
        mock_llm.predict.side_effect = Exception("LLM error")
        agent = TargetClass(llm=mock_llm)
        
        # Act & Assert
        with pytest.raises(RuntimeError):
            await agent.execute(...)
```

### Fixture 约定

```python
# conftest.py
@pytest.fixture
def agent_dependencies():
    """Agent 依赖"""
    return {
        "llm": AsyncMock(),
        "db": Mock(),
        "cache": AsyncMock(),
    }

@pytest.fixture
def sample_diagnostic_data():
    """示例诊断数据"""
    return {
        "symptom": "Interface down",
        "device": "router1",
        "timestamp": "2026-02-06T10:00:00Z",
    }
```

---

## 🚀 快速开始

### 命令参考

```bash
# 1. 运行 agent 单元测试
uv run pytest tests/unit/agents/ -v --cov=src/olav/agents

# 2. 生成覆盖率报告
uv run pytest tests/unit/agents/ --cov=src/olav/agents --cov-report=html

# 3. 检查 ruff 违规
uv run ruff check src/olav/agents/

# 4. 自动修复 ruff 问题
uv run ruff check src/olav/agents/ --fix

# 5. 运行所有测试（包含集成）
uv run pytest tests/ -v --cov=src/

# 6. 性能基准
uv run pytest tests/performance/ -v --benchmark
```

---

## 📝 文档更新清单

- [ ] 更新测试编写指南 (tests/README.md)
- [ ] 记录 agent 测试最佳实践
- [ ] 更新 CI/CD 流程支持新测试
- [ ] 添加测试覆盖率要求到 PR 检查清单

---

## 🎯 里程碑时间表

| 里程碑 | 时间 | 状态 |
|--------|------|------|
| Phase 1 起始 | 2026-02-06 | ⏳ 待开始 |
| Week 1 完成 | 2026-02-13 | ⏳ |
| Week 2 完成 | 2026-02-20 | ⏳ |
| Week 3 完成 | 2026-02-27 | ⏳ |
| v0.10.2 发布 | 2026-03-03 | ⏳ |

---

## 💡 备注

**为什么优先 Agent 模块?**
- Agent 是 OLAV 的核心业务逻辑
- 低覆盖率 (11%) 导致隐藏 bug
- E2E 测试无法覆盖所有 agent 路径
- 易于修复（与 CLI/API 相比）

**为什么强化 Ruff?**
- 早期发现代码质量问题
- 提升代码可维护性
- 遵循 PEP 8 标准
- 为 strict mypy 检查做准备

**关于性能测试:**
- 非本轮优先级（可 v0.10.3 添加）
- 建议后期使用 pytest-benchmark 框架

---

**计划制定者**: GitHub Copilot  
**审核日期**: 2026-02-06
