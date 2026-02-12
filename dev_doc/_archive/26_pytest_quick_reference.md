# Agent 测试快速参考指南

**快速导航**: 本文档为开发者提供快速命令和常见操作。

---

## 🚀 5 秒快速开始

```bash
# 1. 运行所有 agent 单元测试
cd /home/yhvh/Olav
uv run pytest tests/unit/agents/ -v

# 2. 查看结果 → 应该看到 ✅ 108 passed in ~8s
```

---

## 📋 常用命令速查表

### 测试执行

```bash
# 运行所有 agent 单元测试
uv run pytest tests/unit/agents/ -v

# 运行特定测试文件
uv run pytest tests/unit/agents/test_orchestrator.py -v

# 运行特定测试类
uv run pytest tests/unit/agents/test_orchestrator.py::TestOrchestratorBasics -v

# 运行特定测试函数
uv run pytest tests/unit/agents/test_orchestrator.py::TestOrchestratorBasics::test_orchestrate_success_path -v

# 运行失败的测试
uv run pytest tests/unit/agents/ -v --lf

# 运行最后修改的测试
uv run pytest tests/unit/agents/ -v --ff
```

### 覆盖率报告

```bash
# 生成 HTML 覆盖率报告
uv run pytest tests/unit/agents/ --cov=src/olav/agents --cov-report=html

# 生成终端覆盖率报告 (带缺失行)
uv run pytest tests/unit/agents/ --cov=src/olav/agents --cov-report=term-missing

# 只查看 agent 模块覆盖率
uv run pytest tests/unit/agents/ --cov=src/olav/agents --cov-report=term | grep agents

# 打开 HTML 报告
open htmlcov/index.html
```

### Ruff Linting

```bash
# 检查所有 agent 代码
uv run ruff check src/olav/agents/

# 检查并显示修复建议
uv run ruff check src/olav/agents/ --show-fixes

# 自动修复所有可修复的违规
uv run ruff check src/olav/agents/ --fix

# 仅检查特定规则
uv run ruff check src/olav/agents/ --select=F,E,W

# 显示统计信息
uv run ruff check src/olav/agents/ --statistics

# 格式化代码 (黑色风格)
uv run ruff format src/olav/agents/
```

### 集成测试

```bash
# 运行集成测试
uv run pytest tests/integration/agents/ -v

# 运行特定集成测试
uv run pytest tests/integration/agents/test_agent_integration.py::TestOrchestratorQueryAgentIntegration -v
```

---

## 📂 文件位置一览

### 测试文件

| 文件 | 模块 | 测试数 |
|------|------|--------|
| test_orchestrator.py | Orchestrator | 29 |
| test_query_agent.py | QueryAgent | 21 |
| test_analyzer.py | Analyzer | 23 |
| test_agent_enhancements.py | AgentEnhancements | 21 |
| test_intent_agent.py | IntentAgent | 2 |
| test_diagnosis_cache.py | DiagnosisCache | 3 |
| test_inspector.py | Inspector | 2 |
| conftest.py | Fixtures | - |

**路径**: `/home/yhvh/Olav/tests/unit/agents/`

### 被测试的源代码

| 文件 | 行数 | 类型 |
|------|------|------|
| orchestrator.py | 445 | 核心 |
| query_agent.py | 656 | 核心 |
| analyzer.py | 646 | 核心 |
| agent_enhancements.py | 645 | 核心 |
| intent_agent.py | 454 | 支持 |
| diagnosis_cache.py | 189 | 支持 |
| inspector.py | 292 | 支持 |
| textfsm_agent.py | 535 | 支持 |

**路径**: `/home/yhvh/Olav/src/olav/agents/`

---

## 🧪 编写新测试的模板

### 基础单元测试

```python
import pytest
from unittest.mock import AsyncMock, Mock

@pytest.mark.asyncio
class TestNewAgentFeature:
    """Test description"""
    
    async def test_feature_success_path(self, mock_llm, mock_db):
        """测试正常路径"""
        # Arrange
        mock_db.query.return_value = [{"id": 1}]
        
        # Act
        result = await agent.feature()
        
        # Assert
        assert result is not None

    async def test_feature_error_handling(self, mock_llm):
        """测试错误处理"""
        mock_llm.predict.side_effect = Exception("Error")
        
        with pytest.raises(RuntimeError):
            await agent.feature()
```

### 使用可用的 Fixtures

```python
# 在 conftest.py 中定义，可直接使用：
- mock_llm          # AsyncMock LLM
- mock_db           # Mock database
- mock_cache        # AsyncMock cache
- mock_router       # Mock query router
- mock_orchestrator # Mock orchestrator
- sample_diagnostic_data  # 示例诊断数据
```

---

## 🐛 调试技巧

### 运行单个失败的测试

```bash
# 获取最后失败的测试
uv run pytest tests/unit/agents/ --lf -v

# 运行特定的测试并显示完整输出
uv run pytest tests/unit/agents/test_orchestrator.py::TestOrchestratorBasics::test_orchestrate_success_path -v -s
```

### 显示 print 输出

```bash
# -s 选项显示 print 和日志
uv run pytest tests/unit/agents/test_analyzer.py -v -s
```

### 进入 debugger

```bash
# 在测试中添加: import pdb; pdb.set_trace()
# 然后运行
uv run pytest tests/unit/agents/ -v --pdb
```

### 显示最慢的 10 个测试

```bash
uv run pytest tests/unit/agents/ -v --durations=10
```

---

## ✅ 测试检查清单

### 写新测试时

- [ ] 使用 `@pytest.mark.asyncio` 装饰异步测试
- [ ] 为 mock 对象设置合理的返回值
- [ ] 测试成功路径、失败路径和边界情况
- [ ] 添加描述性的测试名称 (test_<feature>_<scenario>)
- [ ] 为复杂逻辑添加注释
- [ ] 确保测试独立 (不依赖执行顺序)
- [ ] 避免真实的网络/数据库调用

### 提交代码前

- [ ] 所有测试通过: `uv run pytest tests/unit/agents/ -v`
- [ ] Ruff 检查通过: `uv run ruff check src/olav/agents/`
- [ ] 覆盖率未下降: `uv run pytest tests/unit/agents/ --cov`
- [ ] 代码已格式化: `uv run ruff format src/`

---

## 📊 理解测试输出

### 成功的测试运行

```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.2

collecting ... collected 108 items

tests/unit/agents/test_orchestrator.py::TestOrchestratorBasics::test_orchestrate_success_path PASSED [ 0%]
tests/unit/agents/test_orchestrator.py::TestOrchestratorBasics::test_orchestrate_with_cache_hit PASSED [ 1%]
...
============================= 108 passed in 7.98s ==============================
```

**含义**: 全部 108 个测试通过 ✅

### 失败的测试

```
FAILED tests/unit/agents/test_orchestrator.py::TestOrchestratorBasics::test_orchestrate_success_path - AssertionError: assert None is not None
```

**解决步骤**:
1. 运行失败的测试看详细错误: `pytest ... -v -s`
2. 检查 mock 设置是否正确
3. 查看函数实现是否改变
4. 运行 `--pdb` 进入 debugger

---

## 🔧 维护建议

### 定期任务

- [ ] **每周**: 运行 `pytest tests/unit/agents/ -v` 确保没有中断
- [ ] **每周**: 运行 `ruff check src/olav/agents/` 检查代码质量
- [ ] **每月**: 更新覆盖率报告并检查下降

### 代码审查检查单

- [ ] 新功能是否有对应的测试?
- [ ] 测试是否涵盖主要路径和错误情况?
- [ ] 是否遵循现有的测试模式?
- [ ] Mock 对象是否设置正确?
- [ ] 测试是否独立且可重复?

---

## 💡 常见问题

### Q: 为什么测试很慢?
A: 检查是否有真实的网络调用或 I/O 操作。确保使用了 mock:
```python
# ❌ 错误：真实调用
result = await orchestrator.orchestrate(query)

# ✅ 正确：使用 mock
result = await mock_orchestrator.orchestrate(query)
```

### Q: 测试在我的机器上失败了，但 CI 通过了
A: 可能是环境差异。检查:
- Python 版本 (应该是 3.12.3)
- 依赖版本 (运行 `uv sync`)
- 时区设置 (某些测试依赖时间)

### Q: 如何调试异步测试?
A: 使用 `pytest --pdb` 并在测试中添加:
```python
import asyncio
await asyncio.sleep(0)  # 让事件循环处理
```

### Q: Ruff 报告 ANN401，但我需要使用 Any
A: 在 pyproject.toml 中为该文件添加忽略:
```toml
"src/olav/agents/my_agent.py" = ["ANN401"]
```

---

## 📚 相关文档

- [改进计划](./24_pytest_ruff_improvement_plan.md) - 详细规划
- [实施总结](./25_pytest_implementation_summary.md) - 完整总结
- [VS Code 错误修复](./23_vscode_errors_fix_summary.md) - 前期工作
- [OLAV 开发指南](./.github/copilot-instructions.md) - 核心原则

---

## 🎯 下一步

1. **立即**: 运行 `uv run pytest tests/unit/agents/ -v` 验证所有测试通过
2. **本周**: 完善集成测试实现
3. **本月**: 修复 ruff 违规，提升覆盖率至 70%

---

**最后更新**: 2026-02-06  
**维护者**: GitHub Copilot
