# 🚀 Agent 测试框架快速开始

**框架版本**: v1.0 (Phase 1 完成)  
**创建时间**: 2026年2月6日  
**状态**: ✅ 可以开始编写测试

---

## 📦 已安装的测试框架

### 目录结构
```
tests/
├── unit/
│   └── agents/
│       ├── __init__.py
│       ├── conftest.py              ⭐ 14 个可复用 fixtures
│       ├── test_orchestrator.py     (16 个测试类)
│       ├── test_query_agent.py      (24 个测试)
│       ├── test_analyzer.py         (22 个测试)
│       ├── test_agent_enhancements.py (21 个测试)
│       ├── test_intent_agent.py     (2 个测试)
│       ├── test_diagnosis_cache.py  (3 个测试)
│       ├── test_inspector.py        (2 个测试)
│       ├── test_textfsm_agent.py    (2 个测试)
│       ├── test_relevance_checker.py (2 个测试)
│       └── test_subagent_pool.py    (3 个测试)
└── integration/
    └── agents/
        ├── __init__.py
        ├── conftest.py              ⭐ 3 个集成测试 fixtures
        └── test_agent_integration.py (7 个集成测试)
```

---

## 🔥 5 分钟快速开始

### 1. 运行现有测试框架
```bash
# 检查测试文件是否创建成功
cd /home/yhvh/Olav
ls -la tests/unit/agents/

# 运行单元测试 (现在都是骨架，会 PASS)
uv run pytest tests/unit/agents/ -v --tb=short

# 运行集成测试
uv run pytest tests/integration/agents/ -v
```

### 2. 查看可用的 Fixtures
```bash
# 列出所有可用 fixtures
uv run pytest tests/unit/agents/conftest.py --collect-only -q

# 输出示例：
# - mock_llm
# - mock_db
# - mock_cache
# - mock_router
# - sample_diagnostic_data
# - sample_query_data
# - ... 等共 14 个
```

### 3. 编写你的第一个测试

**文件**: `tests/unit/agents/test_orchestrator.py`

```python
# 用这个替换第一个测试函数的 pass:

async def test_orchestrate_success_path(self, mock_llm, mock_db, mock_cache):
    """Test successful query orchestration from start to finish."""
    # Arrange
    query = "What is the version of router1?"
    mock_cache.get.return_value = None  # Cache miss
    mock_db.query.return_value = [{"device": "router1", "version": "15.2(4)M5a"}]
    
    # Act
    # TODO: 导入并调用实际的 orchestrator
    # from src.olav.agents.orchestrator import Orchestrator
    # orchestrator = Orchestrator(llm=mock_llm, db=mock_db, cache=mock_cache)
    # result = await orchestrator.orchestrate(query)
    
    # Assert
    # assert result is not None
    # assert "version" in str(result)
```

### 4. 运行单个测试
```bash
# 运行特定测试
uv run pytest tests/unit/agents/test_orchestrator.py::TestOrchestratorBasics::test_orchestrate_success_path -v

# 看到测试跳过或失败是正常的，因为还没导入实际代码
```

---

## 📋 可用的 Fixtures 列表

### 基础 Mock Fixtures

**`mock_llm`** - LLM 模型 mock
```python
async def test_example(self, mock_llm):
    mock_llm.predict.return_value = {"intent": "query"}
    mock_llm.invoke.return_value = {"output": "result"}
```

**`mock_db`** - 数据库 mock
```python
async def test_example(self, mock_db):
    mock_db.query.return_value = [{"id": 1, "name": "router1"}]
    mock_db.execute.return_value = True
```

**`mock_cache`** - 缓存 mock
```python
async def test_example(self, mock_cache):
    mock_cache.get.return_value = None  # 缓存未命中
    mock_cache.set.return_value = True
```

**`mock_nornir`** - Nornir 执行器 mock
```python
async def test_example(self, mock_nornir):
    mock_nornir.run_command.return_value = {
        "router1": {"output": "Command result"}
    }
```

### 数据样本 Fixtures

**`sample_diagnostic_data`** - 诊断数据样本
```python
async def test_example(self, sample_diagnostic_data):
    # 包含: symptom, device, interface, timestamp, severity
    print(sample_diagnostic_data)
```

**`sample_query_data`** - 查询结果样本
```python
async def test_example(self, sample_query_data):
    # 包含: 2 个设备记录，每个有 device_id, device_name, version, ip_address
```

**`sample_nornir_output`** - Nornir 输出样本
```python
async def test_example(self, sample_nornir_output):
    # 包含: router1 的 show interfaces 输出
```

### 组合 Fixtures

**`agent_dependencies`** - 所有依赖的组合
```python
async def test_example(self, agent_dependencies):
    # 返回: {"llm": mock_llm, "db": mock_db, "cache": mock_cache, "router": mock_router}
    agent = MyAgent(**agent_dependencies)
```

---

## 🎯 编写测试的三步模式

### 模板
```python
@pytest.mark.asyncio
async def test_feature_description(self, mock_db, mock_llm, mock_cache):
    """Test description."""
    
    # === ARRANGE (准备) ===
    input_data = {"query": "test"}
    mock_db.query.return_value = [{"result": "data"}]
    
    # === ACT (执行) ===
    # result = await target_function(input_data)
    
    # === ASSERT (断言) ===
    # assert result["status"] == "success"
```

### 示例 1: 数据库查询测试
```python
async def test_query_devices(self, mock_db):
    """Test querying devices from database."""
    # Arrange
    sql = "SELECT * FROM devices"
    mock_db.query.return_value = [
        {"id": 1, "name": "router1"},
        {"id": 2, "name": "router2"},
    ]
    
    # Act
    # result = await query_agent.query_database(sql)
    
    # Assert
    # assert len(result) == 2
    # assert result[0]["name"] == "router1"
```

### 示例 2: 缓存测试
```python
async def test_cache_hit(self, mock_cache):
    """Test cache hit returns fast."""
    # Arrange
    query = "What is the version?"
    cached_result = {"version": "15.2"}
    mock_cache.get.return_value = cached_result
    
    # Act
    # result = await orchestrator.orchestrate(query)
    
    # Assert
    # mock_cache.get.assert_called()
    # assert result == cached_result
```

### 示例 3: 异常处理测试
```python
async def test_error_handling(self, mock_llm):
    """Test handling LLM errors."""
    # Arrange
    mock_llm.predict.side_effect = RuntimeError("LLM failed")
    
    # Act & Assert
    # with pytest.raises(RuntimeError):
    #     await agent.execute(query)
```

---

## ✅ 常用命令速查表

```bash
# 测试相关
uv run pytest tests/unit/agents/ -v                    # 运行所有 unit 测试
uv run pytest tests/unit/agents/ -v -k "orchestrator"  # 运行特定模块测试
uv run pytest tests/unit/agents/ --co -q               # 列出所有测试
uv run pytest tests/unit/agents/ --cov=src/olav/agents # 生成覆盖率报告

# Ruff 相关
uv run ruff check src/olav/agents/                      # 检查 ruff 违规
uv run ruff check src/olav/agents/ --fix               # 自动修复
uv run ruff format src/olav/agents/                    # 格式化代码

# 查看覆盖率
uv run pytest tests/unit/agents/ --cov --cov-report=html
open htmlcov/index.html  # macOS
firefox htmlcov/index.html  # Linux
```

---

## 🔗 后续步骤

### 立即可做 (今天)
- [ ] 按照上面的"3 个 fixtures" 示例编写一个真实测试
- [ ] 把 conftest.py 中的 mock 对象导入到你的测试
- [ ] 运行 `uv run pytest tests/unit/agents/ -v` 验证框架可用

### 本周
- [ ] 实现 test_orchestrator.py 中的 16 个测试
- [ ] 实现 test_query_agent.py 中的 8 个关键测试
- [ ] 验证 mock 配置是否正确

### 后续
- [ ] 补充其他 agent 模块测试
- [ ] 修复剩余 ruff 违规
- [ ] 运行完整的测试覆盖率检查

---

## 📚 参考资源

### 框架文档
- [完整改进计划](docs/24_pytest_ruff_improvement_plan.md)
- [框架实施总结](docs/25_agent_testing_framework_complete.md)

### 测试文件位置
- 单元测试: `tests/unit/agents/`
- 集成测试: `tests/integration/agents/`
- Fixtures 库: `tests/unit/agents/conftest.py`

### 代码覆盖率目标
- orchestrator: 67% → 95%
- query_agent: 10% → 80%
- analyzer: 15% → 70%
- agent_enhancements: 0% → 75%

---

## 🆘 常见问题

**Q: 我导入 fixture 后，IDE 说找不到？**  
A: Pytest 会自动从 conftest.py 发现 fixtures。确保你的文件在 tests/ 目录下，然后重新启动 IDE。

**Q: 怎样 mock 一个异步函数？**  
A: 使用 `AsyncMock()` 而不是 `Mock()`，参考 conftest.py 中的 `mock_llm`。

**Q: 我想添加新的 fixture？**  
A: 在 `tests/unit/agents/conftest.py` 中添加 `@pytest.fixture` 函数，整个 tests/ 目录都能使用。

**Q: 如何跳过某个测试？**  
A: 使用 `@pytest.mark.skip` 或 `@pytest.mark.skip(reason="Not ready")`

---

## 📞 下一步帮助

需要帮助实现某个特定的测试？说出你想测试的:
- "实现 test_orchestrator.py 的第一个测试"
- "为 query_agent 数据库操作添加测试"
- "修复 ruff 中的 ANN401 错误"

---

**框架版本**: v1.0  
**最后更新**: 2026-02-06  
**可以开始**: ✅ 立即开始编写测试
