# OLAV 测试套件

**版本**: 1.0  
**最后更新**: 2026-02-03  
**测试框架**: Pytest + Coverage.py  

> 📖 **完整测试指南**: 参见 [docs/08_TESTING_GIT_CICD_GUIDE.md](../docs/08_TESTING_GIT_CICD_GUIDE.md)

---

## 🎯 快速开始

### 运行所有测试
```bash
# 运行所有测试
uv run pytest tests/ -v

# 带覆盖率报告
uv run pytest tests/ --cov=src/olav --cov-report=html

# 只运行失败的测试
uv run pytest tests/ --lf
```

### 按类型运行
```bash
# 单元测试（快速）
uv run pytest tests/unit/ -v

# 集成测试
uv run pytest tests/integration/ -v

# E2E测试（慢）
uv run pytest tests/e2e/ -v --run-slow
```

### 按标记运行
```bash
# 排除慢速测试
uv run pytest tests/ -m "not slow"

# 只运行真实LLM测试
uv run pytest tests/ --run-real-llm -m real_llm

# 只运行真实设备测试
uv run pytest tests/ --run-real-device -m real_device
```

---

## 📁 目录结构

```
tests/
├── conftest.py                    # 全局fixtures和配置
│
├── unit/                          # 单元测试（快速，隔离）
│   ├── test_agent_orchestrator.py
│   ├── test_agent_inspector.py
│   ├── test_agent_analyzer.py
│   ├── test_tools_inspector.py
│   └── test_cache_semantic.py
│
├── integration/                   # 集成测试（组件交互）
│   ├── test_orchestrator_pipeline.py
│   ├── test_agent_tool_integration.py
│   └── test_cache_database_integration.py
│
├── e2e/                           # 端到端测试（完整流程）
│   ├── test_acceptance.py         # 验收测试（核心）
│   ├── test_device_inspection.py
│   └── test_diagnosis_workflow.py
│
├── fixtures/                      # 测试数据fixtures
│   ├── devices.yaml               # 设备配置
│   ├── queries.json               # 查询示例
│   └── responses.json             # 期望响应
│
├── mocks/                         # Mock对象
│   ├── mock_llm.py                # Mock LLM客户端
│   ├── mock_nornir.py             # Mock Nornir客户端
│   └── mock_database.py           # Mock数据库
│
├── data/                          # 测试数据
│   ├── device_outputs/            # 设备命令输出
│   ├── snapshots/                 # 预期快照
│   └── test_databases/            # 测试数据库
│
├── utils/                         # 测试工具函数
│   ├── assertions.py              # 自定义断言
│   ├── helpers.py                 # 测试辅助函数
│   └── factories.py               # 测试数据工厂
│
└── README.md                      # 本文档
```

---

## 🧪 测试类型说明

### 单元测试 (Unit Tests)
- **目标**: 测试单个函数/方法的逻辑
- **特点**: 快速（<1s），无外部依赖，使用Mock
- **覆盖率要求**: >85%
- **示例**: `tests/unit/test_agent_inspector.py`

### 集成测试 (Integration Tests)
- **目标**: 测试多个组件的交互
- **特点**: 中等速度（1-5s），有限外部依赖
- **覆盖率要求**: >50%
- **示例**: `tests/integration/test_orchestrator_pipeline.py`

### E2E测试 (End-to-End Tests)
- **目标**: 测试完整用户流程
- **特点**: 慢（5-30s），真实环境或接近真实
- **覆盖率要求**: >95%（关键路径）
- **示例**: `tests/e2e/test_acceptance.py`

---

## 📝 测试编写规范

### 测试命名
```python
# ✅ 好的命名
def test_inspect_device_returns_health_data():
    """测试inspect_device返回健康数据"""
    pass

def test_cache_hit_returns_cached_result():
    """测试缓存命中返回缓存结果"""
    pass

# ❌ 不好的命名
def test1():  # 无意义
    pass

def test_function():  # 不清晰
    pass
```

### 测试结构（AAA模式）
```python
def test_example():
    """测试示例"""
    # Arrange（准备）
    input_data = {"device": "R1"}
    
    # Act（执行）
    result = function_under_test(input_data)
    
    # Assert（断言）
    assert result["success"] is True
    assert result["device"] == "R1"
```

### 使用Fixtures
```python
@pytest.fixture
def mock_llm():
    """Mock LLM客户端"""
    llm = AsyncMock()
    llm.ainvoke.return_value.content = "Mocked response"
    return llm

def test_with_fixture(mock_llm):
    """使用fixture的测试"""
    result = await some_function(llm=mock_llm)
    assert result is not None
```

---

## 🎯 覆盖率目标

| Phase | 单元测试 | 集成测试 | E2E测试 | 总覆盖率 |
|-------|---------|---------|---------|---------|
| Phase 0 | >30% | >10% | >50% | >40% |
| Phase 1 | >50% | >20% | >60% | >50% |
| Phase 2 | >70% | >30% | >80% | >70% |
| Phase 3+ | >85% | >50% | >95% | >80% |

### 查看覆盖率
```bash
# 生成HTML报告
uv run pytest tests/ --cov=src/olav --cov-report=html

# 打开报告
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux

# 查看未覆盖代码
uv run pytest tests/ --cov=src/olav --cov-report=term-missing
```

---

## 🔧 常用命令

### 调试测试
```bash
# 运行单个测试
uv run pytest tests/unit/test_agent_inspector.py::test_inspect_device_success -v

# 使用pdb调试
uv run pytest tests/unit/test_agent_inspector.py::test_inspect_device_success --pdb

# 显示完整错误信息
uv run pytest tests/unit/test_agent_inspector.py -v --tb=long

# 只运行失败的测试
uv run pytest tests/ --lf -v
```

### 性能分析
```bash
# 显示最慢的10个测试
uv run pytest tests/ --durations=10

# 并行运行测试（需要pytest-xdist）
uv run pytest tests/ -n auto
```

### 测试标记
```bash
# 运行特定标记的测试
uv run pytest -m integration
uv run pytest -m e2e
uv run pytest -m "not slow"

# 查看所有标记
uv run pytest --markers
```

---

## ✅ 测试检查清单

### 新功能开发
- [ ] 编写单元测试（覆盖核心逻辑）
- [ ] 编写集成测试（覆盖组件交互）
- [ ] 更新E2E测试（如果影响用户流程）
- [ ] 测试覆盖率 ≥80%
- [ ] 所有测试通过

### Bug修复
- [ ] 编写回归测试（重现Bug）
- [ ] 修复Bug
- [ ] 验证测试通过
- [ ] 检查相关测试是否受影响

### 代码审查
- [ ] 测试命名清晰
- [ ] 测试独立（无依赖顺序）
- [ ] 使用合适的fixtures
- [ ] 断言有意义
- [ ] 无flaky test（不稳定测试）

---

## 🆘 常见问题

### Q: 测试失败怎么办？
```bash
# 1. 查看详细错误
uv run pytest tests/unit/test_xxx.py -v --tb=long

# 2. 单独运行失败的测试
uv run pytest tests/unit/test_xxx.py::test_function_name -v

# 3. 使用pdb调试
uv run pytest tests/unit/test_xxx.py::test_function_name --pdb
```

### Q: 如何Mock异步函数？
```python
from unittest.mock import AsyncMock

@pytest.fixture
def mock_async_func():
    mock = AsyncMock()
    mock.return_value = "result"
    return mock

@pytest.mark.asyncio
async def test_with_async_mock(mock_async_func):
    result = await mock_async_func()
    assert result == "result"
```

### Q: 如何测试异常？
```python
def test_function_raises_error():
    """测试函数抛出异常"""
    with pytest.raises(ValueError, match="Invalid input"):
        function_that_raises("invalid")
```

### Q: 如何参数化测试？
```python
@pytest.mark.parametrize("input,expected", [
    ("R1", 85.0),
    ("R2", 72.5),
    ("R3", 90.0),
])
def test_device_health(input, expected):
    """参数化测试：多设备健康度"""
    result = get_health(input)
    assert result == expected
```

---

## 📚 参考资料

- **完整测试指南**: [docs/08_TESTING_GIT_CICD_GUIDE.md](../docs/08_TESTING_GIT_CICD_GUIDE.md)
- **执行计划**: [docs/03_EXECUTION_PLAN.md](../docs/03_EXECUTION_PLAN.md)
- **Issue清单**: [docs/04_ISSUES.md](../docs/04_ISSUES.md)

### 外部资源
- Pytest文档: https://docs.pytest.org/
- Pytest-asyncio: https://pytest-asyncio.readthedocs.io/
- Coverage.py: https://coverage.readthedocs.io/
- unittest.mock: https://docs.python.org/3/library/unittest.mock.html

---

**最后更新**: 2026-02-03  
**维护者**: OLAV开发团队  
**状态**: ✅ Phase 0 Day 0完成后生效
