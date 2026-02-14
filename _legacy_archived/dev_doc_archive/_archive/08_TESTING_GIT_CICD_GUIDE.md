# 测试、Git与CI/CD集成指南

**文档编号**: 08  
**版本**: 1.0  
**创建日期**: 2026-02-03  
**适用范围**: OLAV v0.9.8 → v0.10.0  

> 📖 **目标**: 建立标准化的测试、版本控制和持续集成流程，确保代码质量和团队协作效率。

---

## 📋 目录

1. [测试规范](#测试规范)
2. [tests目录结构](#tests目录结构)
3. [测试编写指南](#测试编写指南)
4. [Git工作流](#git工作流)
5. [CI/CD流水线](#cicd流水线)
6. [代码审查规范](#代码审查规范)
7. [常见问题](#常见问题)

---

## 🧪 测试规范

### 测试金字塔

```
           ┌─────────────┐
           │   E2E Tests │  10% - 完整用户流程
           │   (10个)    │
           ├─────────────┤
           │Integration  │  30% - 组件交互
           │   (30个)    │
           ├─────────────┤
           │ Unit Tests  │  60% - 单元测试
           │   (60个)    │
           └─────────────┘
```

### 测试覆盖率要求

| 阶段 | 单元测试 | 集成测试 | E2E测试 | 总覆盖率 |
|------|---------|---------|---------|---------|
| Phase 0 | >30% | >10% | >50% | >40% |
| Phase 1 | >50% | >20% | >60% | >50% |
| Phase 2 | >70% | >30% | >80% | >70% |
| Phase 3 | >80% | >40% | >90% | >80% |
| v0.10.0 | >85% | >50% | >95% | >85% |

### 测试命名规范

```python
# ✅ 正确命名
def test_inspect_device_returns_health_data():
    """测试inspect_device返回健康数据"""
    pass

def test_cache_hit_returns_cached_result():
    """测试缓存命中返回缓存结果"""
    pass

def test_orchestrator_routes_to_correct_agent():
    """测试Orchestrator路由到正确的Agent"""
    pass

# ❌ 错误命名
def test1():  # 无意义的名称
    pass

def test_function():  # 不清晰的意图
    pass

def testInspect():  # 违反命名规范（驼峰）
    pass
```

---

## 📁 tests目录结构

### 当前结构（待清理）

```
tests/
├── 00_e2e_acceptance_test.py      # ✅ 保留 - E2E验收测试
├── test_*.py                      # ⚠️ 需规范化
├── conftest.py                    # ⚠️ 需增强
├── fixtures/                      # ❌ 缺失
├── mocks/                         # ❌ 缺失
└── data/                          # ❌ 缺失
```

### 目标结构（Phase 0完成后）

```
tests/
├── conftest.py                    # 全局fixtures和配置
│
├── unit/                          # 单元测试
│   ├── test_agent_orchestrator.py
│   ├── test_agent_inspector.py
│   ├── test_agent_analyzer.py
│   ├── test_agent_coder.py
│   ├── test_agent_query_agent.py
│   ├── test_tools_inspector.py
│   ├── test_tools_analyzer.py
│   ├── test_tools_health_score.py
│   ├── test_cache_semantic.py
│   ├── test_cache_diagnosis.py
│   └── test_database_connection.py
│
├── integration/                   # 集成测试
│   ├── test_orchestrator_pipeline.py
│   ├── test_agent_tool_integration.py
│   ├── test_cache_database_integration.py
│   ├── test_nornir_integration.py
│   └── test_llm_integration.py
│
├── e2e/                           # 端到端测试
│   ├── test_acceptance.py         # 验收测试（核心）
│   ├── test_device_inspection.py
│   ├── test_health_check.py
│   └── test_diagnosis_workflow.py
│
├── fixtures/                      # 测试数据fixtures
│   ├── devices.yaml               # 设备配置
│   ├── queries.json               # 查询示例
│   ├── responses.json             # 期望响应
│   └── mock_llm_responses.json    # Mock LLM响应
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
└── README.md                      # 测试文档
```

### Phase 0 清理任务

**在ISSUE-005之前添加 ISSUE-000: 清理tests目录** (2h)

```bash
# 1. 备份当前测试
cd /home/yhvh/Olav
mkdir -p tests_backup
cp -r tests/* tests_backup/

# 2. 创建新结构
mkdir -p tests/{unit,integration,e2e,fixtures,mocks,data,utils}

# 3. 移动现有测试到正确位置
# E2E测试
mv tests/00_e2e_acceptance_test.py tests/e2e/test_acceptance.py

# 单元测试（需逐个审查）
mv tests/test_orchestrator.py tests/unit/test_agent_orchestrator.py
mv tests/test_cache.py tests/unit/test_cache_semantic.py

# 4. 创建基础文件
touch tests/fixtures/devices.yaml
touch tests/mocks/mock_llm.py
touch tests/utils/helpers.py
touch tests/README.md

# 5. 删除过时/重复测试
rm tests/test_old_*.py
rm tests/test_deprecated_*.py
```

---

## 📝 测试编写指南

### 1. 单元测试模板

```python
"""
tests/unit/test_agent_inspector.py

单元测试: Inspector Agent
测试范围: 单个方法的逻辑
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from olav.agent.inspector import InspectorAgent
from olav.tools.inspector import InspectorTool


class TestInspectorAgent:
    """Inspector Agent单元测试套件"""
    
    @pytest.fixture
    def mock_llm(self):
        """Mock LLM客户端"""
        llm = AsyncMock()
        llm.ainvoke.return_value.content = "Inspection complete"
        return llm
    
    @pytest.fixture
    def mock_tool(self):
        """Mock Inspector Tool"""
        tool = AsyncMock(spec=InspectorTool)
        tool.inspect_device.return_value = {
            "device": "R1",
            "health": 85.0,
            "interfaces": []
        }
        return tool
    
    @pytest.fixture
    def agent(self, mock_llm, mock_tool):
        """创建测试用Agent"""
        agent = InspectorAgent(llm=mock_llm)
        agent.tools = [mock_tool]
        return agent
    
    @pytest.mark.asyncio
    async def test_inspect_device_success(self, agent, mock_tool):
        """测试成功巡检设备"""
        # Arrange
        device_name = "R1"
        
        # Act
        result = await agent.inspect(device_name)
        
        # Assert
        assert result is not None
        assert result["device"] == "R1"
        assert result["health"] == 85.0
        mock_tool.inspect_device.assert_called_once_with(device_name)
    
    @pytest.mark.asyncio
    async def test_inspect_device_not_found(self, agent, mock_tool):
        """测试设备不存在"""
        # Arrange
        mock_tool.inspect_device.side_effect = ValueError("Device not found")
        
        # Act & Assert
        with pytest.raises(ValueError, match="Device not found"):
            await agent.inspect("NONEXISTENT")
    
    @pytest.mark.asyncio
    async def test_inspect_device_timeout(self, agent, mock_tool):
        """测试设备连接超时"""
        # Arrange
        mock_tool.inspect_device.side_effect = TimeoutError("Connection timeout")
        
        # Act & Assert
        with pytest.raises(TimeoutError):
            await agent.inspect("R1")
    
    def test_agent_initialization(self):
        """测试Agent初始化"""
        # Act
        agent = InspectorAgent()
        
        # Assert
        assert agent.name == "inspector"
        assert len(agent.tools) > 0
    
    @pytest.mark.parametrize("device,expected_health", [
        ("R1", 85.0),
        ("R2", 72.5),
        ("R3", 90.0),
    ])
    @pytest.mark.asyncio
    async def test_inspect_multiple_devices(self, agent, mock_tool, device, expected_health):
        """参数化测试：多设备巡检"""
        # Arrange
        mock_tool.inspect_device.return_value = {
            "device": device,
            "health": expected_health
        }
        
        # Act
        result = await agent.inspect(device)
        
        # Assert
        assert result["health"] == expected_health
```

### 2. 集成测试模板

```python
"""
tests/integration/test_orchestrator_pipeline.py

集成测试: Orchestrator完整流程
测试范围: 多组件交互
"""
import pytest
from pathlib import Path
import tempfile

from olav.agent.orchestrator import Orchestrator
from olav.agent.inspector import InspectorAgent
from olav.agent.analyzer import AnalyzerAgent


class TestOrchestratorPipeline:
    """Orchestrator流程集成测试"""
    
    @pytest.fixture
    def temp_db(self):
        """临时数据库"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.duckdb"
            yield str(db_path)
    
    @pytest.fixture
    def orchestrator(self, temp_db):
        """创建测试用Orchestrator"""
        orch = Orchestrator(db_path=temp_db)
        return orch
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_full_inspection_pipeline(self, orchestrator):
        """测试完整巡检流程"""
        # Arrange
        query = "巡检R1设备"
        
        # Act
        result = await orchestrator.orchestrate(query)
        
        # Assert
        assert "result" in result
        assert "device" in result["result"]
        assert result["result"]["device"] == "R1"
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_routing_to_inspector(self, orchestrator):
        """测试路由到Inspector"""
        # Arrange
        query = "查看R1接口状态"
        
        # Act
        result = await orchestrator.orchestrate(query)
        
        # Assert
        assert result["agent_used"] == "inspector"
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_routing_to_analyzer(self, orchestrator):
        """测试路由到Analyzer"""
        # Arrange
        query = "分析R1 CPU高的原因"
        
        # Act
        result = await orchestrator.orchestrate(query)
        
        # Assert
        assert result["agent_used"] == "analyzer"
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_cache_integration(self, orchestrator):
        """测试缓存集成"""
        # Arrange
        query = "巡检R1设备"
        
        # Act - 第一次查询（无缓存）
        result1 = await orchestrator.orchestrate(query)
        
        # Act - 第二次查询（应该命中缓存）
        result2 = await orchestrator.orchestrate(query)
        
        # Assert
        assert result1 == result2
        assert result2.get("from_cache") is True
```

### 3. Real E2E测试模板（新标准 v0.9.8+）

**关键原则**:
1. **NO Mocks for Business Logic** - 测试实际代码路径，不mock业务逻辑
2. **Monitor Side Effects** - 使用CLICommandTracker、DatabaseAccessMonitor监控副作用
3. **Test User Scenarios** - 测试用户场景（"导出设备版本信息到CSV"），而非"component exists"
4. **Validate Data Flow** - 检查数据库访问、文件创建、输出正确性

```python
"""
tests/e2e/test_real_scenarios.py

真正的E2E测试: 完整用户场景验证
标准: No mocks for business logic, Monitor side effects, Test real workflows
"""
import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch
import asyncio


class CLICommandTracker:
    """监控测试过程中执行的CLI命令"""
    
    def __init__(self):
        self.commands = []
        self.original_execute = None
    
    def __enter__(self):
        from olav.tools import network
        self.original_execute = network.nornir_execute
        
        async def tracked_execute(command, device_filter=None, **kwargs):
            self.commands.append({
                "command": command,
                "devices": device_filter
            })
            return {"status": "success", "output": "mocked"}
        
        network.nornir_execute = tracked_execute
        return self
    
    def __exit__(self, *args):
        from olav.tools import network
        if self.original_execute:
            network.nornir_execute = self.original_execute
    
    def assert_no_commands(self):
        """验证未执行任何CLI命令"""
        assert len(self.commands) == 0, (
            f"Expected NO CLI commands, but executed: {self.get_commands()}"
        )
    
    def get_commands(self):
        return [cmd["command"] for cmd in self.commands]


@pytest.mark.e2e
class TestRealUserScenarios:
    """完整用户场景端到端测试"""
    
    @pytest.mark.asyncio
    async def test_export_devices_version_no_cli_execution(self):
        """
        用户故事: 导出所有设备的版本信息到CSV
        
        验收标准:
        1. 查询成功
        2. 生成CSV文件
        3. 未执行任何CLI命令（纯数据库查询）
        4. 使用main.duckdb（不使用olav.duckdb）
        """
        cli_tracker = CLICommandTracker()
        
        db_accesses = []
        
        try:
            import duckdb
            original_connect = duckdb.connect
            
            def tracked_connect(database, *args, **kwargs):
                db_accesses.append(str(database))
                return original_connect(database, *args, **kwargs)
            
            duckdb.connect = tracked_connect
            
            with cli_tracker:
                from olav.agents.orchestrator import orchestrate_query
                result = await orchestrate_query(
                    "save all devices' version info to a csv file"
                )
                assert result is not None
        
        finally:
            import duckdb
            duckdb.connect = original_connect
        
        # 关键验证: 未执行CLI命令
        cli_tracker.assert_no_commands()
        
        # 验证使用正确数据库
        assert any("main.duckdb" in db for db in db_accesses)
    
    @pytest.mark.asyncio
    async def test_list_devices_query_no_cli(self):
        """
        用户故事: 列表显示所有设备
        
        路由到query SubAgent，不路由到analyzer
        不执行任何CLI命令
        """
        cli_tracker = CLICommandTracker()
        
        with cli_tracker:
            from olav.agents.orchestrator import orchestrate_query
            result = await orchestrate_query("list all devices")
            assert result is not None
        
        cli_tracker.assert_no_commands()
    
    @pytest.mark.asyncio
    async def test_intent_agent_calls_real_orchestrator(self):
        """
        验证: IntentAgent调用真实的Orchestrator
        
        这个测试会发现"虚假Orchestrator"bug！
        """
        from olav.agents.intent_agent import IntentAgent
        from unittest.mock import patch, AsyncMock
        
        intent_agent = IntentAgent()
        
        with patch("olav.agents.orchestrator.orchestrate_query") as mock_orch:
            mock_orch.return_value = "test result"
            
            result = await intent_agent._orchestrate_query("test query")
            
            mock_orch.assert_called_once_with("test query")
            assert result == "test result"
    
    @pytest.mark.asyncio
    async def test_analyzer_skips_cli_for_export_queries(self):
        """
        验证: Analyzer对数据库查询跳过CLI执行
        
        这个测试会发现"always execute CLI"bug！
        """
        from olav.agents.analyzer import cli_verify_node, AnalyzerState
        
        state = AnalyzerState(
            user_query="save all devices' version info to csv",
            status="db_query"
        )
        
        cli_tracker = CLICommandTracker()
        
        with cli_tracker:
            result_state = await cli_verify_node(state)
            assert result_state.status == "analyzing"
        
        cli_tracker.assert_no_commands()


@pytest.mark.e2e
class TestDatabasePathConfiguration:
    """验证数据库路径配置正确"""
    
    def test_main_db_path_in_config(self):
        """验证MAIN_DB_PATH在config.paths中定义"""
        from config.paths import MAIN_DB_PATH
        assert MAIN_DB_PATH is not None
        assert "main.duckdb" in str(MAIN_DB_PATH)
    
    def test_data_gateway_uses_main_db_path(self):
        """验证data_gateway使用config中的MAIN_DB_PATH"""
        from olav.lib.data_gateway import get_connection
        
        conn = get_connection()
        assert conn is not None
        
        result = conn.execute("SELECT 1 as test").fetchone()
        assert result[0] == 1
```

**运行Real E2E测试**:
```bash
# 运行所有Real E2E测试
uv run pytest tests/e2e/test_real_scenarios.py -v

# 运行特定测试
uv run pytest tests/e2e/test_real_scenarios.py::TestRealUserScenarios::test_export_devices_version_no_cli_execution -v

# 不运行旧的虚假E2E测试
uv run pytest tests/e2e/test_real_scenarios.py -v --ignore=tests/e2e/test_*.py
```

### 4. Fixture最佳实践

```python
"""
tests/conftest.py

全局Fixtures和配置
"""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock
import duckdb


@pytest.fixture(scope="session")
def test_data_dir():
    """测试数据目录"""
    return Path(__file__).parent / "data"


@pytest.fixture
def mock_llm():
    """Mock LLM客户端"""
    llm = AsyncMock()
    llm.ainvoke.return_value.content = "Mocked LLM response"
    return llm


@pytest.fixture
def temp_db():
    """临时测试数据库"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.duckdb"
        conn = duckdb.connect(str(db_path))
        
        # 创建测试Schema
        conn.execute("""
            CREATE TABLE IF NOT EXISTS queries (
                id VARCHAR PRIMARY KEY,
                query_text VARCHAR,
                result_json VARCHAR
            )
        """)
        conn.commit()
        
        yield str(db_path)
        
        conn.close()


@pytest.fixture(autouse=True)
def reset_environment():
    """每个测试后重置环境"""
    yield
    # 清理操作
    import gc
    gc.collect()


@pytest.fixture
def sample_device_output(test_data_dir):
    """示例设备输出"""
    output_file = test_data_dir / "device_outputs" / "r1_show_version.txt"
    if output_file.exists():
        return output_file.read_text()
    return "Mocked device output"


# Pytest配置
def pytest_configure(config):
    """Pytest全局配置"""
    config.addinivalue_line(
        "markers", "e2e: 端到端测试（慢）"
    )
    config.addinivalue_line(
        "markers", "integration: 集成测试"
    )
    config.addinivalue_line(
        "markers", "slow: 慢速测试"
    )
    config.addinivalue_line(
        "markers", "real_llm: 需要真实LLM API"
    )
    config.addinivalue_line(
        "markers", "real_device: 需要真实设备"
    )


def pytest_addoption(parser):
    """添加命令行选项"""
    parser.addoption(
        "--run-slow", action="store_true", default=False, help="运行慢速测试"
    )
    parser.addoption(
        "--run-real-llm", action="store_true", default=False, help="运行真实LLM测试"
    )


def pytest_collection_modifyitems(config, items):
    """根据命令行选项过滤测试"""
    if not config.getoption("--run-slow"):
        skip_slow = pytest.mark.skip(reason="需要 --run-slow 选项")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
    
    if not config.getoption("--run-real-llm"):
        skip_real_llm = pytest.mark.skip(reason="需要 --run-real-llm 选项")
        for item in items:
            if "real_llm" in item.keywords:
                item.add_marker(skip_real_llm)
```

---

## 🔀 Git工作流

### 分支策略

```
main (生产分支)
  ├── develop (开发分支)
  │   ├── feature/issue-001-fix-ruff-errors
  │   ├── feature/issue-006-orchestrator-migration
  │   ├── bugfix/cache-connection-issue
  │   └── hotfix/critical-bug
  └── release/v0.10.0
```

### 分支命名规范

```bash
# Feature分支
feature/issue-001-fix-ruff-errors
feature/issue-006-orchestrator-migration
feature/phase-0-emergency-fix

# Bugfix分支
bugfix/cache-connection-issue
bugfix/test-failure-orchestrator

# Hotfix分支（紧急修复）
hotfix/critical-security-issue
hotfix/production-crash

# Release分支
release/v0.10.0
release/v0.10.1
```

### Git提交规范

遵循 [Conventional Commits](https://www.conventionalcommits.org/)：

```bash
<type>(<scope>): <subject>

<body>

<footer>
```

**Type类型**:
- `feat`: 新功能
- `fix`: Bug修复
- `refactor`: 重构
- `test`: 测试相关
- `docs`: 文档更新
- `style`: 代码格式（不影响逻辑）
- `perf`: 性能优化
- `chore`: 构建/工具链更新

**示例**:
```bash
# 功能开发
git commit -m "feat(orchestrator): 迁移Executor到SubAgent"

# Bug修复
git commit -m "fix(cache): 修复DuckDB连接泄漏问题

- 实现连接池单例模式
- 添加连接数验证测试
- 关闭: ISSUE-002"

# 测试
git commit -m "test(agent): 添加Inspector单元测试

- 测试inspect_device成功场景
- 测试设备不存在错误处理
- 测试连接超时场景
- 覆盖率提升至85%"

# 重构
git commit -m "refactor(agent): 删除冗余PlanAgent组件

- 迁移功能到Orchestrator
- 删除plan_agent.py和相关测试
- 更新文档
- 完成: ISSUE-007"
```

### Git工作流程

```bash
# 1. 从develop分支创建feature分支
git checkout develop
git pull origin develop
git checkout -b feature/issue-001-fix-ruff-errors

# 2. 进行开发
vim src/olav/agent/orchestrator.py

# 3. 运行测试
uv run pytest tests/ -v
uv run ruff check src/ --fix
uv run pyright src/

# 4. 提交代码
git add src/olav/agent/orchestrator.py
git commit -m "fix(agent): 修复Orchestrator F841错误"

# 5. 推送到远程
git push origin feature/issue-001-fix-ruff-errors

# 6. 创建Pull Request (GitHub)
# - 填写PR模板
# - 关联Issue
# - 请求代码审查

# 7. 合并后清理
git checkout develop
git pull origin develop
git branch -d feature/issue-001-fix-ruff-errors
```

### .gitignore配置

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# 测试
.pytest_cache/
.coverage
htmlcov/
.tox/
.hypothesis/

# OLAV特定
.olav/cache/*.duckdb
.olav/cache/*.duckdb.wal
exports/reports/*.html
exports/snapshots/*.json
logs/*.log

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# 环境
.env
.env.local
venv/
env/
ENV/

# 临时文件
*.tmp
*.bak
.DS_Store
```

---

## 🚀 CI/CD流水线

### GitHub Actions配置

#### 1. CI流水线 (`.github/workflows/ci.yml`)

```yaml
name: CI Pipeline

on:
  push:
    branches: [ develop, main ]
  pull_request:
    branches: [ develop, main ]

env:
  PYTHON_VERSION: "3.11"
  UV_VERSION: "0.1.0"

jobs:
  lint:
    name: 代码质量检查
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: 安装uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      
      - name: 设置Python环境
        run: uv python install ${{ env.PYTHON_VERSION }}
      
      - name: 安装依赖
        run: uv sync
      
      - name: Ruff检查
        run: uv run ruff check src/
      
      - name: Ruff格式检查
        run: uv run ruff format src/ --check
      
      - name: Pyright类型检查
        run: uv run pyright src/
        continue-on-error: true  # Phase 0阶段允许失败

  test:
    name: 测试套件
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    
    steps:
      - uses: actions/checkout@v4
      
      - name: 安装uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      
      - name: 设置Python ${{ matrix.python-version }}
        run: uv python install ${{ matrix.python-version }}
      
      - name: 安装依赖
        run: uv sync
      
      - name: 运行单元测试
        run: |
          uv run pytest tests/unit/ -v \
            --cov=src/olav \
            --cov-report=xml \
            --cov-report=html \
            --junitxml=junit.xml
      
      - name: 运行集成测试
        run: |
          uv run pytest tests/integration/ -v -m "not real_device"
      
      - name: 上传覆盖率报告
        uses: codecov/codecov-action@v3
        with:
          files: ./coverage.xml
          flags: unittests
          name: codecov-${{ matrix.python-version }}
      
      - name: 上传测试报告
        uses: actions/upload-artifact@v3
        if: always()
        with:
          name: test-results-${{ matrix.python-version }}
          path: |
            htmlcov/
            junit.xml

  e2e:
    name: E2E测试
    runs-on: ubuntu-latest
    needs: [lint, test]
    if: github.event_name == 'pull_request'
    
    steps:
      - uses: actions/checkout@v4
      
      - name: 安装uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      
      - name: 设置Python环境
        run: uv python install ${{ env.PYTHON_VERSION }}
      
      - name: 安装依赖
        run: uv sync
      
      - name: 运行E2E测试
        run: |
          uv run pytest tests/e2e/ -v \
            -m "not real_llm and not real_device" \
            --tb=short
      
      - name: 上传E2E报告
        uses: actions/upload-artifact@v3
        if: always()
        with:
          name: e2e-results
          path: |
            logs/
            exports/

  quality-gate:
    name: 质量门禁
    runs-on: ubuntu-latest
    needs: [lint, test]
    
    steps:
      - uses: actions/checkout@v4
      
      - name: 检查测试覆盖率
        run: |
          # 下载覆盖率报告
          # 检查是否达到阈值
          # Phase 0: >40%, Phase 1: >50%, Phase 2: >70%, Phase 3+: >80%
          echo "检查测试覆盖率是否达标"
      
      - name: 检查代码质量
        run: |
          # 检查Ruff错误数
          # Phase 0目标: 0错误
          echo "检查代码质量是否达标"
```

#### 2. 发布流水线 (`.github/workflows/release.yml`)

```yaml
name: Release Pipeline

on:
  push:
    tags:
      - 'v*.*.*'

jobs:
  build:
    name: 构建发布包
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: 安装uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      
      - name: 设置Python环境
        run: uv python install 3.11
      
      - name: 安装依赖
        run: uv sync
      
      - name: 运行完整测试
        run: |
          uv run pytest tests/ -v \
            --cov=src/olav \
            --cov-report=xml \
            -m "not real_llm and not real_device"
      
      - name: 构建Docker镜像
        run: |
          docker build -t olav:${{ github.ref_name }} .
          docker tag olav:${{ github.ref_name }} olav:latest
      
      - name: 推送Docker镜像
        run: |
          echo "${{ secrets.DOCKER_PASSWORD }}" | docker login -u "${{ secrets.DOCKER_USERNAME }}" --password-stdin
          docker push olav:${{ github.ref_name }}
          docker push olav:latest
      
      - name: 创建GitHub Release
        uses: actions/create-release@v1
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        with:
          tag_name: ${{ github.ref }}
          release_name: Release ${{ github.ref }}
          draft: false
          prerelease: false
```

#### 3. 定时任务 (`.github/workflows/scheduled.yml`)

```yaml
name: Scheduled Tasks

on:
  schedule:
    # 每日凌晨2点运行
    - cron: '0 2 * * *'
  workflow_dispatch:  # 允许手动触发

jobs:
  nightly-tests:
    name: 夜间完整测试
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: 安装环境
        run: |
          curl -LsSf https://astral.sh/uv/install.sh | sh
          uv python install 3.11
          uv sync
      
      - name: 运行完整测试套件
        run: |
          uv run pytest tests/ -v \
            --run-slow \
            --cov=src/olav \
            --cov-report=html
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      
      - name: 生成测试报告
        run: |
          # 生成趋势报告
          # 上传到S3/Cloud Storage
          echo "生成测试趋势报告"
      
      - name: 发送通知
        if: failure()
        run: |
          # 发送邮件/Slack通知
          echo "测试失败，发送告警"
```

### 本地Pre-commit Hook

```bash
# .git/hooks/pre-commit (chmod +x)
#!/bin/bash

echo "运行pre-commit检查..."

# 1. Ruff检查
echo "1. 运行Ruff检查..."
uv run ruff check src/ --fix
if [ $? -ne 0 ]; then
    echo "❌ Ruff检查失败"
    exit 1
fi

# 2. Ruff格式化
echo "2. 运行Ruff格式化..."
uv run ruff format src/
if [ $? -ne 0 ]; then
    echo "❌ Ruff格式化失败"
    exit 1
fi

# 3. 运行相关测试
echo "3. 运行受影响的测试..."
# 获取修改的文件
CHANGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep "\.py$")

if [ -n "$CHANGED_FILES" ]; then
    # 只运行受影响的测试
    uv run pytest tests/unit/ -v -x
    if [ $? -ne 0 ]; then
        echo "❌ 测试失败"
        exit 1
    fi
fi

echo "✅ 所有检查通过"
exit 0
```

安装pre-commit hook:
```bash
cp scripts/pre-commit.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

---

## 👀 代码审查规范

### Pull Request模板

```markdown
## 变更描述
[简要描述本PR的目的和变更内容]

## 关联Issue
- Closes #XXX
- Related to #YYY

## 变更类型
- [ ] Bug修复
- [ ] 新功能
- [ ] 重构
- [ ] 测试增强
- [ ] 文档更新

## 测试清单
- [ ] 添加了单元测试
- [ ] 添加了集成测试
- [ ] 通过所有测试
- [ ] 测试覆盖率 ≥80%
- [ ] 手动测试通过

## 代码质量
- [ ] Ruff检查通过
- [ ] Pyright检查通过
- [ ] 代码已格式化
- [ ] 添加了类型注解

## 文档
- [ ] 更新了相关文档
- [ ] 添加了Docstring
- [ ] 更新了CHANGELOG

## 截图/日志
[如果适用，添加截图或日志]

## 审查要点
[提示审查者重点关注的地方]

## 部署说明
[如果有特殊部署要求，在此说明]
```

### Code Review检查清单

#### 功能正确性
- [ ] 代码实现符合需求
- [ ] 边界条件处理正确
- [ ] 错误处理完善
- [ ] 无明显Bug

#### 代码质量
- [ ] 命名清晰（变量、函数、类）
- [ ] 逻辑简洁，无重复代码
- [ ] 符合SOLID原则
- [ ] 无过度设计

#### 测试覆盖
- [ ] 单元测试覆盖核心逻辑
- [ ] 集成测试覆盖交互场景
- [ ] 测试用例有意义
- [ ] 测试可维护

#### 性能考虑
- [ ] 无明显性能问题
- [ ] 数据库查询优化
- [ ] 适当使用缓存
- [ ] 异步操作正确使用

#### 安全性
- [ ] 无SQL注入风险
- [ ] 无XSS风险
- [ ] 敏感信息未硬编码
- [ ] 权限验证到位

#### 文档完整性
- [ ] Docstring完整
- [ ] 复杂逻辑有注释
- [ ] README更新
- [ ] 变更日志更新

---

## ❓ 常见问题

### Q1: 测试失败怎么办？

```bash
# 1. 查看详细错误
uv run pytest tests/unit/test_xxx.py -v --tb=long

# 2. 单独运行失败的测试
uv run pytest tests/unit/test_xxx.py::test_function_name -v

# 3. 使用pdb调试
uv run pytest tests/unit/test_xxx.py::test_function_name --pdb

# 4. 查看覆盖率缺失
uv run pytest tests/ --cov=src/olav --cov-report=html
# 打开 htmlcov/index.html
```

### Q2: 如何Mock LLM调用？

```python
from unittest.mock import AsyncMock

@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.ainvoke.return_value.content = "Mocked response"
    return llm

async def test_with_mock_llm(mock_llm):
    # 使用mock_llm
    result = await some_function(llm=mock_llm)
    assert result is not None
```

### Q3: 如何测试异步代码？

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await async_function()
    assert result == expected
```

### Q4: 测试覆盖率不达标怎么办？

```bash
# 1. 查看未覆盖代码
uv run pytest --cov=src/olav --cov-report=term-missing

# 2. 生成HTML报告
uv run pytest --cov=src/olav --cov-report=html

# 3. 针对性补充测试
# - 查看htmlcov/index.html
# - 找到未覆盖的分支
# - 编写测试覆盖
```

### Q5: CI流水线失败怎么处理？

```bash
# 1. 查看GitHub Actions日志
# 点击失败的job查看详细输出

# 2. 本地复现
# 使用相同的命令在本地运行

# 3. 常见问题
# - 环境变量缺失: 检查secrets配置
# - 依赖安装失败: 检查pyproject.toml
# - 测试超时: 增加timeout或优化测试
```

### Q6: 如何运行特定标记的测试？

```bash
# 只运行单元测试
uv run pytest tests/unit/ -v

# 只运行集成测试
uv run pytest -m integration

# 只运行E2E测试
uv run pytest -m e2e

# 排除慢速测试
uv run pytest -m "not slow"

# 运行慢速测试
uv run pytest --run-slow

# 运行真实LLM测试
uv run pytest --run-real-llm -m real_llm
```

---

## 📚 参考资料

### 测试框架
- Pytest文档: https://docs.pytest.org/
- Pytest-asyncio: https://pytest-asyncio.readthedocs.io/
- Coverage.py: https://coverage.readthedocs.io/
- unittest.mock: https://docs.python.org/3/library/unittest.mock.html

### Git工作流
- Conventional Commits: https://www.conventionalcommits.org/
- Git Flow: https://nvie.com/posts/a-successful-git-branching-model/
- GitHub Flow: https://guides.github.com/introduction/flow/

### CI/CD
- GitHub Actions: https://docs.github.com/en/actions
- Docker: https://docs.docker.com/
- Codecov: https://docs.codecov.com/

### 代码质量
- Ruff: https://docs.astral.sh/ruff/
- Pyright: https://github.com/microsoft/pyright
- Pre-commit: https://pre-commit.com/

---

## 🎯 检查清单

### Phase 0 测试清理完成标准

- [ ] tests目录重新组织 (unit/integration/e2e)
- [ ] conftest.py增强（全局fixtures）
- [ ] 创建Mock对象（mock_llm.py, mock_nornir.py）
- [ ] 创建测试数据fixtures
- [ ] 所有测试迁移到新结构
- [ ] 删除过时/重复测试
- [ ] tests/README.md编写完成
- [ ] Pre-commit hook安装
- [ ] GitHub Actions CI配置
- [ ] 测试通过率100%

### 测试质量检查

- [ ] 每个新功能有对应单元测试
- [ ] 每个Bug修复有回归测试
- [ ] 测试命名清晰（test_xxx_should_yyy）
- [ ] 测试独立（无依赖顺序）
- [ ] 测试稳定（无flaky test）
- [ ] 测试快速（单元测试<1s）
- [ ] 覆盖率达标（Phase目标）

---

**文档版本**: 1.0  
**最后更新**: 2026-02-03  
**维护者**: OLAV开发团队  
**下一步**: 参见 [03_EXECUTION_PLAN.md](03_EXECUTION_PLAN.md) 执行Phase 0 测试清理任务
