# 硬编码配置扫描报告

**扫描日期**: 2026-02-13  
**扫描范围**: src/olav/**/*.py  
**总发现**: ~25+ 项硬编码值需要迁移

---

## 📍 路径相关硬编码

| 位置 | 硬编码值 | 类型 | 建议 | 优先级 |
|------|--------|------|------|--------|
| cache_manager.py | `.olav/skills` | Path | ✅ 已在 config/paths.py | 低 |
| llm_router.py | `.olav/skills/guard/SKILL.md` | Path | 迁移到 SKILLS_DIR + 常量 | 中 |
| subagent_loader.py | `.olav/OLAV.md` | Path | ✅ 用 PROJECT_ROOT 构建 | 低 |
| subagent_loader.py | `.olav/skills/{skill_name}` | Path | ✅ 用 SKILLS_DIR 构建 | 低 |
| skill_loader.py | `.olav/skills` | Path | ✅ 已在 config/paths.py | 低 |
| admin_agent.py | `.olav/config/crontab` | Path | ✅ 建议用 CRONTAB_FILE 常量 | 中 |
| data_gateway.py | `.olav` | Path | ✅ 已为 AGENT_DIR | 低 |

---

## 🔢 数值相关硬编码

### 连接池配置

| 文件 | 参数 | 当前值 | 类型 | 建议位置 |
|-----|------|--------|------|---------|
| connection_pool.py | max_size | 5 | int | DatabaseSettings |
| connection_pool.py | timeout_seconds | 5.0 | float | DatabaseSettings |
| database_enhancer.py | max_size | 100 | int | CacheSettings |
| database_enhancer.py | ttl_seconds | 3600 | float | CacheSettings |
| database_enhancer.py | timeout_seconds | 30.0 | float | DatabaseSettings |

### 查询限制

| 文件 | 参数 | 当前值 | 类型 | 建议位置 |
|-----|------|--------|------|---------|
| database.py | max_output_size | 100_000 | int | ThresholdSettings |
| command_registry.py | limit | 10 | int | APISettings |
| api/v1/devices.py | limit | 100 | int | APISettings |
| api/v1/data.py | limit | 100 | int | APISettings |
| api/v1/schema.py | limit | 10 | int | APISettings |
| api/server.py | limit | 100 | int | APISettings |

### 置信度和阈值

| 文件 | 参数 | 当前值 | 类型 | 建议位置 |
|-----|------|--------|------|---------|
| cache/__init__.py | confidence_threshold | 0.95 | float | ExecutionSettings ✅ |
| execution_dispatcher.py | confidence_threshold | 0.75 | float | ExecutionSettings ✅ |
| session.py | threshold_percent | 80.0 | float | CacheSettings |
| testing/expert_constraints.py | min_score | 0.80 | float | ValidationSettings |
| testing/expert_constraints.py | max_score | 1.0 | float | ValidationSettings |
| testing/expert_constraints.py | vague_term_threshold | 0.05 | float | ValidationSettings |

### 内容长度和大小

| 文件 | 参数 | 当前值 | 类型 | 建议位置 |
|-----|------|--------|------|---------|
| session.py | max_length | 200 | int | CacheSettings |
| session.py | max_messages | 5 | int | CacheSettings |
| session.py | max_length (conv) | 100 | int | CacheSettings |

### 数据相关参数

| 文件 | 参数 | 当前值 | 类型 | 建议位置 |
|-----|------|--------|------|---------|
| data_gateway.py | max_age_days | 30 | int | DataGatewaySettings |
| data_gateway.py | limit | 5 | int | DataGatewaySettings |

---

## 📊 按优先级分类

### 🔴 高优先级 (已暴露问题)

这些硬编码值在测试失败中直接相关：

1. **cli/display.py 缺少函数** (任务 1.1)
   - print_error
   - print_success
   - print_welcome

2. **API 默认 limit 不一致** (任务 2.3)
   - devices API: 100
   - data API: 100
   - schema API: 10
   - command_registry: 10
   - server: 100

### 🟡 中优先级 (最佳实践)

1. **连接池配置** (任务 3.1)
   - max_size = 5
   - timeout_seconds = 5.0

2. **Cache 配置** (任务 3.2)
   - max_size = 100
   - ttl_seconds = 3600
   - max_length = 200
   - threshold_percent = 80.0

3. **数据网关配置** (任务 3.3)
   - max_age_days = 30
   - limit = 5

### 🟢 低优先级 (可选优化)

1. **验证配置** (任务 3.4)
   - min_score = 0.80
   - max_score = 1.0
   - vague_term_threshold = 0.05

2. **数据库限制** (任务 3.5)
   - max_output_size = 100_000

---

## 📝 迁移方案

### Step 1: 修复高优先级硬编码

**文件**: src/olav/cli/__init__.py

```python
# ❌ 当前
from olav.cli.display import (
    print_error,
    print_success,
    print_welcome,
)

# ✅ 修复选项 A (实现函数)
# 在 display.py 中添加：
def print_error(message: str, console: Console | None = None) -> None:
    """Display error message"""
    if console is None:
        from rich.console import Console
        console = Console()
    console.print(f"[red]❌ Error:[/red] {message}")

def print_success(message: str, console: Console | None = None) -> None:
    """Display success message"""
    if console is None:
        from rich.console import Console
        console = Console()
    console.print(f"[green]✅ Success:[/green] {message}")

def print_welcome(message: str, console: Console | None = None) -> None:
    """Display welcome message"""
    if console is None:
        from rich.console import Console
        console = Console()
    console.print(f"[cyan]{message}[/cyan]")

# ✅ 修复选项 B (移除导入)
# 如果这些函数不被使用，直接从 __init__.py 移除
```

### Step 2: 添加新配置类

**文件**: config/settings.py

```python
class APISettings(BaseSettings):
    """API Configuration"""
    
    default_limit: int = Field(
        default=100,
        description="Default limit for paginated results"
    )
    device_limit: int = Field(
        default=100,
        description="Default limit for device queries"
    )
    data_limit: int = Field(
        default=100,
        description="Default limit for data queries"
    )
    schema_limit: int = Field(
        default=10,
        description="Default limit for schema queries"
    )


class DatabaseSettings(BaseSettings):
    """Database Configuration"""
    
    connection_pool_size: int = Field(
        default=5,
        description="Maximum number of connections in pool"
    )
    connection_timeout: float = Field(
        default=5.0,
        description="Connection timeout in seconds"
    )
    query_timeout: float = Field(
        default=30.0,
        description="Query execution timeout in seconds"
    )
    max_output_size: int = Field(
        default=100_000,
        description="Maximum output size for queries"
    )


class CacheSettings(BaseSettings):
    """Cache Configuration"""
    
    cache_size: int = Field(
        default=100,
        description="Maximum cache size"
    )
    cache_ttl: int = Field(
        default=3600,
        description="Cache time-to-live in seconds"
    )
    context_max_length: int = Field(
        default=200,
        description="Maximum context length"
    )
    context_threshold_percent: float = Field(
        default=80.0,
        description="Context usage threshold percentage"
    )


class DataGatewaySettings(BaseSettings):
    """Data Gateway Configuration"""
    
    max_age_days: int = Field(
        default=30,
        description="Maximum age of data in days"
    )
    result_limit: int = Field(
        default=5,
        description="Maximum number of results"
    )


class ValidationSettings(BaseSettings):
    """Validation and Scoring Configuration"""
    
    expert_min_score: float = Field(
        default=0.80,
        description="Minimum expert score"
    )
    expert_max_score: float = Field(
        default=1.0,
        description="Maximum expert score"
    )
    vague_term_threshold: float = Field(
        default=0.05,
        description="Vague term detection threshold"
    )
```

### Step 3: 迁移代码使用新配置

**示例**: database.py

```python
# ❌ 旧代码
MAX_OUTPUT_SIZE = 100_000

# ✅ 新代码
from config.settings import get_settings

def get_max_output_size() -> int:
    settings = get_settings()
    return settings.database.max_output_size
```

---

## ✅ 验证清单

- [ ] 所有硬编码值已识别
- [ ] 新配置类已添加到 settings.py
- [ ] 代码已更新使用新配置
- [ ] 环境变量覆盖测试通过
- [ ] .olav/settings.json 加载测试通过
- [ ] E2E 测试通过率 > 80%

---

## 📚 参考

- [CODE_SIMPLIFICATION_ROADMAP.md](dev_doc/CODE_SIMPLIFICATION_ROADMAP.md)
- [E2E_TEST_REPORT.md](E2E_TEST_REPORT.md)
- [E2E_TEST_FIX_PLAN.md](E2E_TEST_FIX_PLAN.md)
- [config/settings.py](config/settings.py) - 主配置文件
- [config/paths.py](config/paths.py) - 路径配置

---

**生成时间**: 2026-02-13  
**扫描工具**: grep + manual review  
**状态**: ✅ 完成且可执行
