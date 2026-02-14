# OLAV E2E 测试方法论

**文档版本**: v1.0  
**创建日期**: 2026-02-14  
**适用项目**: OLAV v2.0 及所有 CLI 应用  
**最后审计**: 2026-02-14 22:30

---

## 📖 目录

1. [问题背景](#问题背景)
2. [核心原则](#核心原则)
3. [E2E 测试定义](#e2e-测试定义)
4. [测试分层架构](#测试分层架构)
5. [E2E 测试检查清单](#e2e-测试检查清单)
6. [常见陷阱](#常见陷阱)
7. [OLAV 实战案例](#olav-实战案例)
8. [测试模板](#测试模板)

---

## 问题背景

### 审计发现的严重问题（2026-02-14）

**现象**:
- 测试报告显示 19/19 E2E 测试通过 (100%)
- 开发团队认为项目可以交付
- 用户运行 `uv run olav ask "..."` **完全失败**（挂起/超时）

**根本原因**:
测试只测了 **Python API**，从未测试**真实 CLI 命令**：

```python
# ❌ 虚假的 E2E 测试（审计前）
def test_agent_query():
    from olav.agents.agent import create_olav_agent
    agent = create_olav_agent()
    result = agent.invoke("Hello")  # 不是真实用户场景
    assert result is not None

# 用户实际使用：
$ uv run olav ask "Hello"
# 结果：挂起 30 秒... ❌
```

**教训**:
> **Python API 工作 ≠ CLI 命令可用**

---

## 核心原则

### 原则 1: 测试真实用户入口点

**必须测试所有用户会使用的方式**:

```python
# ✅ 正确：测试真实 CLI 命令
import subprocess

def test_cli_command():
    result = subprocess.run(
        ["uv", "run", "olav", "ask", "Hello"],
        capture_output=True,
        text=True,
        timeout=30
    )
    assert result.returncode == 0
    assert "response" in result.stdout
```

**检查入口点**:
1. 查看 `pyproject.toml` 中的 `[project.scripts]`
2. 测试**每一个**定义的命令
3. 测试命令的**各种组合**

```toml
# pyproject.toml
[project.scripts]
olav = "olav.cli.agent_v2:app"        # 必须测试
olav-legacy = "olav.cli:main"         # 必须测试
olav-admin = "olav.cli.admin:main"    # 必须测试
```

### 原则 2: 测试完整用户场景

**不只测试 `--help`**:

```python
# ❌ 不充分：只测试 help
def test_cli_help():
    result = subprocess.run(["olav", "--help"])
    assert result.returncode == 0

# ✅ 完整：测试实际功能
def test_cli_real_usage():
    # 1. 无参数调用
    result = subprocess.run(["uv", "run", "olav"])
    assert result.returncode in [0, 2]  # 0=success, 2=help shown
    assert "Usage:" in result.stdout or "Usage:" in result.stderr
    
    # 2. 实际业务功能
    result = subprocess.run(["uv", "run", "olav", "ask", "test"])
    assert result.returncode == 0
    assert "Response" in result.stdout or "Error" in result.stderr
    
    # 3. 错误处理
    result = subprocess.run(["uv", "run", "olav", "invalid-command"])
    assert result.returncode != 0
    assert "Error" in result.stderr or "invalid" in result.stderr.lower()
```

### 原则 3: 验证输出内容，不只检查退出码

**常见错误**:

```python
# ❌ 虚假通过：只检查退出码
def test_ask_command():
    result = subprocess.run(["uv", "run", "olav", "ask", "test"])
    assert result.returncode == 0  # 通过！

# 实际输出：
# stderr: "Binder Error: checkpoint_ns not found"
# stdout: ""
# returncode: 0 (因为异常被捕获了)
```

**正确做法**:

```python
# ✅ 验证实际输出
def test_ask_command():
    result = subprocess.run(
        ["uv", "run", "olav", "ask", "What is 2+2?"],
        capture_output=True,
        text=True,
        timeout=30
    )
    
    # 1. 检查退出码
    assert result.returncode == 0, f"Command failed: {result.stderr}"
    
    # 2. 检查 stderr 无错误
    assert "Error" not in result.stderr, f"Errors in stderr: {result.stderr}"
    assert "Failed" not in result.stderr
    
    # 3. 检查 stdout 有预期内容
    assert "4" in result.stdout or "four" in result.stdout.lower()
    
    # 4. 检查响应格式
    assert "Response" in result.stdout or "✓" in result.stdout
```

### 原则 4: 测试所有关键场景

**E2E 测试矩阵**:

| 场景 | 测试内容 | 示例 |
|------|---------|------|
| 正常使用 | 主要功能 | `olav ask "query"` |
| 无参数 | 默认行为 | `olav` → 显示帮助 |
| 帮助信息 | --help | `olav --help` |
| 版本信息 | --version | `olav --version` |
| 错误命令 | 错误处理 | `olav invalid` |
| 缺少参数 | 参数验证 | `olav ask` (无 query) |
| 环境变量 | 配置检查 | 无 API key 时的提示 |
| 超时处理 | 长时间操作 | 30s 超时 |
| 并发调用 | 多进程 | 同时运行 5 个命令 |

---

## E2E 测试定义

### 什么是真正的 E2E 测试？

**定义**: 从用户角度测试完整的使用路径，包括：
- 真实的入口点（CLI 命令、Web 请求、GUI 操作）
- 真实的数据存储（数据库、文件系统）
- 真实的外部依赖（API 调用、网络请求）
- 真实的执行环境（subprocess、容器、服务器）

### OLAV 项目中的测试分层

```
┌─────────────────────────────────────────────────────────┐
│ E2E 测试 (tests/e2e/test_cli_real_commands.py)        │
│ - subprocess.run(["uv", "run", "olav", ...])          │
│ - 测试真实 CLI 命令                                    │
│ - 测试完整用户场景                                     │
│ - 覆盖率: 少量，关键场景                               │
└─────────────────────────────────────────────────────────┘
           ↓ 调用
┌─────────────────────────────────────────────────────────┐
│ 集成测试 (tests/integration/test_agent_api.py)        │
│ - agent = create_olav_agent()                         │
│ - result = agent.invoke(query)                        │
│ - 测试 Python API                                     │
│ - 覆盖率: 中等，主要功能                               │
└─────────────────────────────────────────────────────────┘
           ↓ 调用
┌─────────────────────────────────────────────────────────┐
│ 单元测试 (tests/unit/test_database.py)                │
│ - test_sql_query()                                    │
│ - test_parse_query()                                  │
│ - 测试单个函数                                         │
│ - 覆盖率: 大量，所有函数                               │
└─────────────────────────────────────────────────────────┘
```

---

## E2E 测试检查清单

### ✅ 开发阶段

在编写代码前：

- [ ] 列出所有用户入口点（CLI、API、GUI）
- [ ] 为每个入口点编写至少 1 个 E2E 测试
- [ ] 定义验收标准（退出码、输出内容、性能）

### ✅ 测试编写

测试代码必须：

- [ ] 使用 `subprocess.run()` 调用真实命令（CLI）
- [ ] 测试所有 `pyproject.toml [project.scripts]` 入口点
- [ ] 验证 stdout/stderr 内容，不只检查 returncode
- [ ] 包含错误场景测试（无效参数、缺少配置）
- [ ] 设置合理的超时时间（防止挂起）
- [ ] 清理测试产生的文件（临时文件、数据库）

### ✅ 测试运行

每次发布前：

- [ ] 在干净环境中运行 E2E 测试（无缓存）
- [ ] 所有 E2E 测试必须通过（0 skipped）
- [ ] 手动验证至少 3 个关键场景
- [ ] 检查所有测试日志（确保无警告/错误）

### ✅ 审计验证

代码审计时：

- [ ] 运行所有测试并保存日志
- [ ] 手动运行用户最常用的 3 个命令
- [ ] 检查测试是否覆盖所有入口点
- [ ] 验证测试是真实场景，不是组件测试

---

## 常见陷阱

### 陷阱 1: 只测试 Python API

**问题**:
```python
# ❌ 这不是 E2E 测试
def test_agent():
    from olav.agents.agent import create_olav_agent
    agent = create_olav_agent()
    result = agent.invoke("Hello")
    assert result["status"] == "success"
```

**为什么错**:
- Python API 工作 ≠ CLI 命令工作
- 没有测试 CLI 参数解析
- 没有测试 typer 配置
- 没有测试 subprocess 环境

**解决**:
```python
# ✅ 真正的 E2E 测试
def test_cli_command():
    result = subprocess.run(
        ["uv", "run", "olav", "ask", "Hello"],
        capture_output=True,
        text=True,
        timeout=30
    )
    assert result.returncode == 0
    assert "Response" in result.stdout
```

### 陷阱 2: 只检查退出码

**问题**:
```python
# ❌ 虚假通过
def test_query():
    result = subprocess.run(["olav", "ask", "test"])
    assert result.returncode == 0  # 通过了！

# 实际 stderr: "Database connection failed"
# 但退出码是 0（因为异常被捕获了）
```

**解决**:
```python
# ✅ 验证输出内容
def test_query():
    result = subprocess.run(
        ["olav", "ask", "test"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "Error" not in result.stderr  # 检查 stderr
    assert "Response" in result.stdout   # 检查 stdout
```

### 陷阱 3: 过度 Mock

**问题**:
```python
# ❌ Mock 太多，测不到真实场景
@patch('olav.core.database.get_connection')
@patch('olav.agents.agent.LLMFactory')
@patch('olav.cli.admin.admin_handler')
def test_everything_mocked(mock1, mock2, mock3):
    # 所有真实代码都被 Mock 了，测试毫无意义
    result = subprocess.run(["olav", "ask", "test"])
    assert result.returncode == 0
```

**解决**:
```python
# ✅ 最小 Mock，测试真实代码
def test_with_real_dependencies():
    # 只 Mock 外部 API（LLM、网络设备）
    with patch('olav.core.llm.ChatOpenAI') as mock_llm:
        mock_llm.return_value.invoke.return_value = {"content": "4"}
        
        result = subprocess.run(
            ["uv", "run", "olav", "ask", "What is 2+2?"],
            capture_output=True,
            text=True
        )
        
        assert result.returncode == 0
        assert "4" in result.stdout
```

### 陷阱 4: 忽略边界情况

**常被忽略的场景**:

```python
# ✅ 必须测试的边界情况
def test_no_arguments():
    """无参数调用"""
    result = subprocess.run(["olav"])
    assert "Usage:" in result.stdout or result.stderr

def test_invalid_command():
    """无效命令"""
    result = subprocess.run(["olav", "invalid-cmd"])
    assert result.returncode != 0

def test_missing_required_arg():
    """缺少必需参数"""
    result = subprocess.run(["olav", "ask"])  # 缺少 query
    assert result.returncode != 0

def test_timeout():
    """超时处理"""
    result = subprocess.run(
        ["olav", "ask", "complex query"],
        timeout=5  # 5 秒超时
    )
    # 应该在 5 秒内返回或超时

def test_no_api_key():
    """缺少 API key"""
    env = os.environ.copy()
    env.pop('LLM_API_KEY', None)
    
    result = subprocess.run(
        ["olav", "ask", "test"],
        env=env,
        capture_output=True,
        text=True
    )
    
    assert "API" in result.stderr or "key" in result.stderr.lower()
```

---

## OLAV 实战案例

### 问题 1: `olav ask` 命令挂起（2026-02-14）

**发现过程**:
1. E2E 测试报告 19/19 通过
2. 用户运行 `uv run olav ask "Hello"` → 挂起 30 秒
3. 审计发现：测试只测了 Python API，从未测 CLI

**根本原因**:
- Agent 中 3 个核心 Bug:
  1. tool_node 无法调用普通 Python 函数
  2. async 阻塞事件循环
  3. should_continue 死循环

**修复**:
1. 创建真实 E2E 测试 (subprocess)
2. 修复 3 个 Bug
3. 8/9 测试通过

**教训**:
- 必须测试真实 CLI 命令
- 测试要验证输出内容
- Async 代码必须用 `ainvoke()` 不能用 `invoke()`

### 问题 2: `uv run olav` 无参数提示不友好（2026-02-14）

**现象**:
```bash
$ uv run olav
╭─ Error ──────────────────────────╮
│ Missing command.                 │
╰──────────────────────────────────╯
```

**问题**:
- Typer 配置 `no_args_is_help=False`
- 新用户不知道有哪些命令

**修复**:
```python
# agent_v2.py
app = typer.Typer(
    no_args_is_help=True,  # 显示帮助
)
```

**现在**:
```bash
$ uv run olav
Usage: olav [OPTIONS] COMMAND [ARGS]...

Commands:
  ask          Ask OLAV a question...
  admin        Execute admin commands...
  devices      List network devices...
  interactive  Start interactive mode...
```

**测试**:
```python
def test_no_args_shows_help():
    """Test olav without arguments shows help"""
    result = subprocess.run(
        ["uv", "run", "olav"],
        capture_output=True,
        text=True
    )
    
    # Typer 显示帮助时返回 2
    assert result.returncode in [0, 2]
    assert "Usage:" in result.stdout or "Usage:" in result.stderr
    assert "Commands:" in result.stdout or "Commands:" in result.stderr
```

---

## 测试模板

### 模板 1: 基础 CLI E2E 测试

```python
"""
E2E 测试模板 - CLI 应用

运行: pytest tests/e2e/test_cli.py -v
"""

import subprocess
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
CLI_COMMAND = ["uv", "run", "myapp"]  # 替换为你的命令
TIMEOUT = 30  # 秒


class TestCLIBasic:
    """基础 CLI 功能测试"""
    
    def test_no_args(self):
        """无参数调用应显示帮助或进入默认模式"""
        result = subprocess.run(
            CLI_COMMAND,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        # 退出码 0 (成功) 或 2 (help)
        assert result.returncode in [0, 2]
        
        # 应包含使用说明
        output = result.stdout + result.stderr
        assert "Usage:" in output or "help" in output.lower()
    
    def test_help(self):
        """--help 应显示帮助信息"""
        result = subprocess.run(
            CLI_COMMAND + ["--help"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        assert result.returncode in [0, 2]
        assert "Usage:" in result.stdout
        assert "Commands:" in result.stdout or "Options:" in result.stdout
    
    def test_version(self):
        """--version 应显示版本"""
        result = subprocess.run(
            CLI_COMMAND + ["--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        assert result.returncode == 0
        # 检查版本号格式
        assert any(char.isdigit() for char in result.stdout)
    
    def test_invalid_command(self):
        """无效命令应报错"""
        result = subprocess.run(
            CLI_COMMAND + ["invalid-command-xyz"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        assert result.returncode != 0
        error_output = result.stderr.lower()
        assert "error" in error_output or "invalid" in error_output


class TestCLIFunctions:
    """实际功能测试"""
    
    def test_main_function(self):
        """测试主要功能"""
        result = subprocess.run(
            CLI_COMMAND + ["command", "arg1", "arg2"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT
        )
        
        # 1. 检查退出码
        assert result.returncode == 0, \
            f"Command failed: {result.stderr}"
        
        # 2. 检查 stderr 无错误
        assert "Error" not in result.stderr
        
        # 3. 检查 stdout 有预期内容
        assert "expected_output" in result.stdout
    
    def test_error_handling(self):
        """测试错误处理"""
        result = subprocess.run(
            CLI_COMMAND + ["command", "--invalid-flag"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        assert result.returncode != 0
        assert "Error" in result.stderr or "invalid" in result.stderr.lower()


class TestCLIEnvironment:
    """环境和配置测试"""
    
    def test_missing_config(self):
        """缺少必需配置时应友好提示"""
        import os
        env = os.environ.copy()
        env.pop('REQUIRED_ENV_VAR', None)
        
        result = subprocess.run(
            CLI_COMMAND + ["command"],
            env=env,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        assert result.returncode != 0
        assert "REQUIRED_ENV_VAR" in result.stderr


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

### 模板 2: 带 LLM 的 CLI E2E 测试

```python
"""
E2E 测试模板 - 带 LLM 的 CLI 应用

测试策略：
- Mock 外部 LLM API（避免实际调用）
- 测试真实 CLI 命令（subprocess）
- 验证输出格式和内容
"""

import subprocess
import pytest
from unittest.mock import patch, MagicMock
import json


class TestCLIWithLLM:
    """测试带 LLM 的 CLI 功能"""
    
    @pytest.fixture
    def mock_llm_response(self):
        """Mock LLM 响应"""
        with patch('your_app.llm.ChatOpenAI') as mock:
            mock_instance = MagicMock()
            mock_instance.invoke.return_value = {
                "content": "Mocked LLM response"
            }
            mock.return_value = mock_instance
            yield mock
    
    def test_query_with_llm(self, mock_llm_response):
        """测试带 LLM 的查询"""
        result = subprocess.run(
            ["uv", "run", "myapp", "ask", "What is 2+2?"],
            capture_output=True,
            text=True,
            timeout=30,
            env={"LLM_API_KEY": "test-key"}  # 提供测试 key
        )
        
        assert result.returncode == 0
        assert "Mocked LLM response" in result.stdout or "Error" not in result.stderr
    
    def test_no_api_key(self):
        """测试缺少 API key 时的提示"""
        import os
        env = os.environ.copy()
        env.pop('LLM_API_KEY', None)
        
        result = subprocess.run(
            ["uv", "run", "myapp", "ask", "test"],
            capture_output=True,
            text=True,
            timeout=5,
            env=env
        )
        
        assert result.returncode != 0
        assert "API" in result.stderr or "key" in result.stderr.lower()
```

---

## 总结

### 关键要点

1. **E2E 测试 = 测试真实用户场景**
   - 使用 subprocess 调用 CLI
   - 测试所有入口点
   - 验证输出内容

2. **不要假设**
   - Python API 工作 ≠ CLI 可用
   - 测试通过 ≠ 用户可用
   - 退出码 0 ≠ 功能正确

3. **完整覆盖**
   - 正常场景 + 错误场景
   - 所有命令 + 所有参数组合
   - 边界情况 + 环境问题

4. **持续验证**
   - 每次发布前手动验证
   - CI/CD 运行 E2E 测试
   - 审计时运行真实命令

### 审计检查清单

发布前必须：

- [ ] 所有 E2E 测试通过（0 failures, 0 skipped）
- [ ] 手动运行至少 3 个常用命令
- [ ] 测试日志保存到文件
- [ ] 代码审计确认测试覆盖所有入口点
- [ ] 在干净环境中测试（无缓存）

---

**文档维护**:
- 每次审计后更新本文档
- 记录新发现的陷阱和案例
- 保持模板与最佳实践同步

**相关文档**:
- [copilot-instructions.md](../.github/copilot-instructions.md#8-e2e-测试方法论)
- [CODE_AUDIT_REPORT_2026_02_14.md](CODE_AUDIT_REPORT_2026_02_14.md)
- [E2E_TESTING_FIX_SUMMARY.md](E2E_TESTING_FIX_SUMMARY.md)
