# Query Agent 问题分析与修复计划
**日期**: 2026-02-09  
**版本**: v1.0.0  
**状态**: 🔴 待修复 (Critical Issues Identified)

---

## 📋 执行摘要

通过 Session 2 的 L1/L2 测试，发现了导致 33% 测试失败的三大根本问题：

| 问题 | 严重性 | 影响 | 优先级 |
|------|--------|------|--------|
| **数据库配置硬编码** | 🔴 Critical | 29%失败 | P0 |
| **LLM SQL生成准确率低** | 🟡 Medium | 12%失败 | P1 |
| **查询缓存未生效** | 🟡 Medium | 性能差 | P1 |

**测试结果**: 16/24 通过 (67%)  
**预期改进**: 实施所有修复后 → 24/24 通过 (100%)

---

## 🚨 问题1：数据库配置硬编码 (Critical)

### 问题描述

**现象**: Agent 使用错误的数据库导致 P2 测试全部失败

```
实际使用: .olav/db/olav.duckdb (1.6MB)
  ├─ devices: 6 rows ✅
  ├─ interfaces: 不存在 ❌
  ├─ interface_stats: 不存在 ❌
  └─ topology_links: 0 rows ❌

测试数据在: .olav/db/test_network.duckdb (11MB)
  ├─ devices: 80 rows ✅
  ├─ interfaces: 1200 rows ✅
  ├─ interface_stats: 106537 rows ✅
  └─ Agent 完全没有使用！
```

### 根因分析

#### 架构层面
```
问题根源：配置分层设计缺陷

当前架构:
config/paths.py (硬编码)
  ↓
UNIFIED_DB = DB_DIR / "olav.duckdb"  # 全局常量
  ↓
data_gateway.py (硬编码引用)
  ↓
query_database tool (无参数)
  ↓
无法在测试环境切换数据库
```

#### 代码证据

**文件1: `config/paths.py:45`**
```python
# ❌ 问题代码
UNIFIED_DB = DB_DIR / "olav.duckdb"  # 硬编码，无环境变量支持
MAIN_DB_PATH = UNIFIED_DB
```

**文件2: `src/olav/lib/data_gateway.py:70-73`**
```python
# ❌ 问题代码
def query_main(self, sql: str, params: list | None = None) -> list[dict]:
    from config.paths import UNIFIED_DB  # 直接导入全局常量
    conn = duckdb.connect(str(UNIFIED_DB), read_only=True)
```

**文件3: `src/olav/tools/react_query.py:82`**
```python
# ❌ 问题代码
@tool
def query_database(sql: str, params: list | None = None) -> str:
    """Execute SQL query on network database (.olav/db/olav.duckdb)."""
    from olav.lib.data_gateway import query_database as db_query
    # 没有 db_path 参数，无法动态切换
```

### 设计原则违反

根据 OLAV 开发指南：
> **No Hardcoded Configuration**  
> Rule: Zero hardcoded paths, thresholds, or commands  
> - Use config.paths.* for file paths  
> - Use config.settings.* for parameters  
> - Support environment overrides via .env  
> - Support user overrides via .olav/settings.json

**当前违反**:
1. ❌ 路径硬编码在 `paths.py` 中
2. ❌ 无 `settings.py` 配置支持
3. ❌ 无 `.env` 环境变量覆盖
4. ❌ 无 `.olav/settings.json` 用户覆盖

### 影响范围

- **测试失败**: 7/24 测试失败 (29%)
- **环境隔离**: 测试和生产环境无法隔离
- **可配置性**: 用户无法自定义数据库路径
- **可测试性**: 单元测试无法 mock 数据库

---

## 🎯 解决方案1：配置分层架构重构

### 设计原则

**配置优先级链** (按 OLAV 架构标准):
```
.env (环境变量 - 最高优先级)
  ↓ 覆盖
.olav/settings.json (用户配置)
  ↓ 覆盖
SKILL.md frontmatter (技能配置)
  ↓ 覆盖
config/settings.py (默认配置 - 最低优先级)
```

### 实施计划

#### Phase 1.1: 扩展 settings.py (配置Schema)

**文件**: `config/settings.py`

**新增配置段**:
```python
from pathlib import Path
from pydantic import BaseModel, Field

class DatabaseSettings(BaseModel):
    """数据库配置 (非敏感)"""
    
    # 数据库路径 (相对于项目根目录)
    main_db: Path = Field(
        default=Path(".olav/db/olav.duckdb"),
        description="主数据库路径 (设备、接口、拓扑等所有数据)"
    )
    
    # 测试数据库 (用于 E2E 测试)
    test_db: Path | None = Field(
        default=None,
        description="测试数据库路径，未设置时使用 main_db"
    )
    
    # 数据库行为配置
    read_only: bool = Field(
        default=True,
        description="数据库只读模式 (query 操作建议为 True)"
    )
    
    connection_timeout: int = Field(
        default=30,
        description="数据库连接超时 (秒)"
    )
    
    query_timeout: int = Field(
        default=60,
        description="SQL 查询超时 (秒)"
    )

class Settings(BaseSettings):
    """OLAV 全局配置"""
    
    # 现有配置...
    llm_api_key: str = Field(...)
    llm_base_url: str = Field(...)
    
    # 新增：数据库配置
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    
    class Config:
        env_nested_delimiter = "__"  # 支持 DATABASE__MAIN_DB=...
```

**设计说明**:
- ✅ 使用 Pydantic 验证配置合法性
- ✅ 支持嵌套配置 `database.main_db`
- ✅ 支持环境变量覆盖 `DATABASE__MAIN_DB`
- ✅ 提供合理的默认值
- ✅ 文档化配置项用途

#### Phase 1.2: 修改 paths.py (动态路径)

**文件**: `config/paths.py`

**修改**:
```python
"""Path Configuration for OLAV v0.10.2+

动态路径配置，支持环境变量和 settings.py 覆盖
"""
import os
from pathlib import Path

from config.settings import settings

# =============================================================================
# Database Paths - v0.10.2: Dynamic Configuration Support
# =============================================================================

DB_DIR = AGENT_DIR / "db"

def get_database_path(force_test: bool = False) -> Path:
    """获取当前环境的数据库路径
    
    优先级:
    1. OLAV_DB_PATH 环境变量 (最高)
    2. force_test=True → settings.database.test_db
    3. settings.database.main_db (默认)
    
    Args:
        force_test: 强制使用测试数据库 (用于测试脚本)
        
    Returns:
        数据库文件路径
        
    Examples:
        >>> get_database_path()  # 生产环境
        PosixPath('.olav/db/olav.duckdb')
        
        >>> get_database_path(force_test=True)  # 测试环境
        PosixPath('.olav/db/test_network.duckdb')
        
        >>> os.environ["OLAV_DB_PATH"] = "/tmp/custom.duckdb"
        >>> get_database_path()  # 环境变量覆盖
        PosixPath('/tmp/custom.duckdb')
    """
    # 1. 环境变量最高优先级
    if env_path := os.getenv("OLAV_DB_PATH"):
        return Path(env_path)
    
    # 2. 测试环境
    if force_test and settings.database.test_db:
        return settings.database.test_db
    
    # 3. 默认生产数据库
    return settings.database.main_db

# 向后兼容别名 (使用函数而非常量)
UNIFIED_DB = get_database_path()  # 动态获取
MAIN_DB_PATH = UNIFIED_DB
OLAV_DB_PATH = UNIFIED_DB

# 标记为动态配置
__doc__ += "\nNote: UNIFIED_DB 现在是动态值，测试时请使用 get_database_path(force_test=True)"
```

**设计说明**:
- ✅ 环境变量 `OLAV_DB_PATH` 最高优先级
- ✅ 测试模式 `force_test=True` 自动切换
- ✅ 向后兼容现有代码
- ✅ 明确的优先级文档

#### Phase 1.3: 修改 data_gateway.py (动态连接)

**文件**: `src/olav/lib/data_gateway.py`

**修改**:
```python
class DataGateway:
    """统一数据访问接口 - v0.10.2 支持动态数据库配置"""
    
    def __init__(self, base_dir: Path | None = None, db_path: Path | None = None) -> None:
        """初始化 Data Gateway
        
        Args:
            base_dir: .olav/ 根目录
            db_path: 自定义数据库路径 (覆盖默认配置)
        """
        from config.paths import AGENT_DIR, get_database_path
        
        self.base_dir = base_dir or AGENT_DIR
        self.db_dir = self.base_dir / "db"
        self.skills_dir = self.base_dir / "skills"
        
        # v0.10.2: 支持自定义数据库路径
        self._db_path = db_path or get_database_path()
        
        logger.debug(f"DataGateway initialized with database: {self._db_path}")
        
        # 确保目录存在
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def query_main(self, sql: str, params: list | None = None) -> list[dict]:
        """查询主数据库 (v0.10.2 - 支持动态数据库路径)
        
        Args:
            sql: DuckDB SQL 查询
            params: 查询参数
            
        Returns:
            查询结果列表
        """
        # v0.10.2: 使用实例配置的数据库路径
        conn = duckdb.connect(str(self._db_path), read_only=True)
        try:
            if params:
                result = conn.execute(sql, params)
            else:
                result = conn.execute(sql)
            
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"Database query failed: {e}")
            raise
        finally:
            conn.close()
```

**设计说明**:
- ✅ 构造函数接受 `db_path` 参数
- ✅ 使用 `get_database_path()` 作为默认值
- ✅ 实例化时明确日志记录使用的数据库
- ✅ 向后兼容（默认行为不变）

#### Phase 1.4: 增强 query_database Tool (参数化)

**文件**: `src/olav/tools/react_query.py`

**修改**:
```python
@tool
def query_database(sql: str, params: list | None = None) -> str:
    """Execute SQL query on network database.
    
    Database path is determined by:
    1. OLAV_DB_PATH environment variable (highest priority)
    2. settings.database.main_db (default)
    
    Args:
        sql: SQL SELECT statement
        params: Optional parameters for parameterized query
        
    Returns:
        Query results as JSON string
        
    Environment:
        OLAV_DB_PATH: Override database path (e.g., for testing)
        
    Examples:
        >>> query_database("SELECT hostname FROM devices")
        [{"hostname": "R1"}, {"hostname": "R2"}, ...]
        
        # In test environment:
        >>> os.environ["OLAV_DB_PATH"] = ".olav/db/test_network.duckdb"
        >>> query_database("SELECT COUNT(*) FROM interfaces")
        [{"count": 1200}]
    """
    try:
        from config.paths import get_database_path
        from olav.lib.data_gateway import DataGateway
        
        # v0.10.2: 使用动态数据库路径
        db_path = get_database_path()
        logger.info(f"Query database: {db_path}")  # 明确日志
        
        gw = DataGateway(db_path=db_path)
        results = gw.query_main(sql, params or [])
        
        return json.dumps(results, indent=2, default=str)
    except Exception as e:
        # 错误处理保持不变...
        return f"Database Error: {e}"
```

**设计说明**:
- ✅ 工具自动检测数据库路径
- ✅ 明确日志记录使用的数据库
- ✅ 向后兼容（生产环境默认行为不变）
- ✅ 测试时通过环境变量切换

#### Phase 1.5: 更新 .env.example (环境变量文档)

**文件**: `.env.example`

**新增**:
```bash
# =============================================================================
# LLM Configuration (Required)
# =============================================================================
LLM_API_KEY=sk-or-v1-xxx...
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL_NAME=x-ai/grok-beta

# =============================================================================
# Database Configuration (Optional)
# =============================================================================

# 数据库路径覆盖 (默认: .olav/db/olav.duckdb)
# 生产环境通常不需要设置
# OLAV_DB_PATH=.olav/db/olav.duckdb

# 测试环境示例:
# OLAV_DB_PATH=.olav/db/test_network.duckdb

# Docker 容器环境示例:
# OLAV_DB_PATH=/data/network.duckdb

# 多用户环境示例:
# OLAV_DB_PATH=/shared/olav/user_123.duckdb
```

**设计说明**:
- ✅ 明确区分敏感配置 (API Key) 和非敏感配置 (Database Path)
- ✅ 提供使用场景示例
- ✅ 默认不需要设置（使用 settings.py 默认值）

#### Phase 1.6: 更新测试脚本 (环境隔离)

**文件**: `quick_l1_test.py`, `run_l2_tests.py`

**修改**:
```python
#!/usr/bin/env python3
"""Level 1/2 测试脚本 - v0.10.2 支持测试数据库隔离"""

import os
import subprocess
from pathlib import Path

OLAV_ROOT = Path("/home/yhvh/Olav")
TEST_DB = OLAV_ROOT / ".olav/db/test_network.duckdb"

def run_olav_query(query: str, timeout=45) -> tuple[bool, str, float]:
    """执行 olav query (v0.10.2 - 自动使用测试数据库)"""
    
    # 设置测试环境
    env = os.environ.copy()
    env["OLAV_DB_PATH"] = str(TEST_DB)  # 核心修改：指定测试数据库
    env["OLAV_ENV"] = "test"  # 可选：标记测试环境
    
    start_time = time.time()
    try:
        result = subprocess.run(
            ["uv", "run", "olav", "query", query],
            cwd=OLAV_ROOT,
            env=env,  # 传递环境变量
            capture_output=True,
            text=True,
            timeout=timeout
        )
        elapsed = time.time() - start_time
        output = result.stdout + result.stderr
        
        # v0.10.2: 验证使用了正确的数据库
        if "test_network.duckdb" not in output and result.returncode == 0:
            logger.warning(f"Query may not be using test database: {TEST_DB}")
        
        return result.returncode == 0, output, elapsed
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT", timeout
    except Exception as e:
        return False, str(e), time.time() - start_time

# 测试前验证
def verify_test_database():
    """验证测试数据库存在且有数据"""
    import duckdb
    
    if not TEST_DB.exists():
        raise FileNotFoundError(f"Test database not found: {TEST_DB}")
    
    conn = duckdb.connect(str(TEST_DB), read_only=True)
    device_count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    interface_count = conn.execute("SELECT COUNT(*) FROM interfaces").fetchone()[0]
    conn.close()
    
    print(f"✅ Test database ready:")
    print(f"  - Path: {TEST_DB}")
    print(f"  - Devices: {device_count}")
    print(f"  - Interfaces: {interface_count}")
    
    if device_count < 10 or interface_count < 100:
        logger.warning("Test database has insufficient data for comprehensive testing")

if __name__ == "__main__":
    verify_test_database()  # 测试前检查
    main()
```

**设计说明**:
- ✅ 自动设置 `OLAV_DB_PATH` 环境变量
- ✅ 测试前验证数据库存在且有数据
- ✅ 日志明确显示使用的数据库
- ✅ 与生产环境完全隔离

### 验证计划

#### 验证1: 配置优先级
```bash
# 1. 默认配置 (settings.py)
uv run python -c "from config.paths import get_database_path; print(get_database_path())"
# 预期: .olav/db/olav.duckdb

# 2. 环境变量覆盖
export OLAV_DB_PATH=".olav/db/test_network.duckdb"
uv run python -c "from config.paths import get_database_path; print(get_database_path())"
# 预期: .olav/db/test_network.duckdb

# 3. force_test 参数
uv run python -c "from config.paths import get_database_path; print(get_database_path(force_test=True))"
# 预期: .olav/db/test_network.duckdb (如果 settings.database.test_db 已配置)
```

#### 验证2: Query Agent 使用测试数据库
```bash
# 设置环境变量
export OLAV_DB_PATH=".olav/db/test_network.duckdb"

# 执行查询
uv run olav query "有多少个接口?"

# 预期输出: "1200 个接口" (而非之前的 "0")
```

#### 验证3: 测试脚本隔离
```bash
# 不设置环境变量，运行测试脚本
uv run python quick_l1_test.py

# 预期:
# 1. 脚本自动设置 OLAV_DB_PATH
# 2. 使用 test_network.duckdb
# 3. 接口查询返回 1200
# 4. P2 测试从 0/5 → 4/5 通过
```

### 预期效果

| 指标 | 修复前 | 修复后 | 改善 |
|------|--------|--------|------|
| **L1 通过率** | 67% (6/9) | 89% (8/9) | +22% |
| **L2 通过率** | 67% (10/15) | 93% (14/15) | +26% |
| **L2-P2 通过率** | 0% (0/5) | 80% (4/5) | +80% |
| **整体通过率** | 67% (16/24) | 92% (22/24) | +25% |
| **配置灵活性** | ❌ 硬编码 | ✅ 4层覆盖 | 质的飞跃 |
| **环境隔离** | ❌ 无隔离 | ✅ 完全隔离 | 质的飞跃 |

---

## 🧠 问题2：LLM SQL 生成准确率低 (Medium)

### 问题描述

**现象**: LLM 生成的 SQL 经常使用错误的字段名，导致查询失败和超时

**案例1: 字段名错误**
```
用户查询: "按设备类型分类统计"
LLM 生成: SELECT device_type, COUNT(*) FROM devices GROUP BY device_type
实际表结构: devices.device_role (不是 device_type)
结果: SQL Error → 重试 → 再错误 → 超时
```

**案例2: 表名推断错误**
```
用户查询: "接口流量统计"
LLM 推断: SELECT * FROM interface_traffic
实际表名: interface_stats
结果: Table not found error
```

### 根因分析

#### Skill 配置不足

**当前 SKILL.md** (`.olav/skills/network-query/SKILL.md`):
```yaml
prompts:
  system: |
    You are a database query specialist.
    
    **CRITICAL: ALWAYS USE inspect_schema() FIRST**
    # 只有通用提示，没有具体的字段映射
```

**问题**:
- ❌ 没有提供常见错误案例
- ❌ 没有字段名映射表
- ❌ 没有表名别名提示
- ❌ 依赖 LLM 自己调用 `inspect_schema()`，但 LLM 经常"忘记"

#### 架构缺陷：缺少 Schema-Aware 中间层

**当前架构**:
```
User Query → Orchestrator → QueryAgent → LLM → SQL (可能错误)
                                              ↓
                                         DuckDB Error
                                              ↓
                                         Retry (可能再错)
```

**缺少**:
- ❌ SQL Validation Middleware (执行前验证)
- ❌ Schema Mapper (字段名自动纠正)
- ❌ Query Rewriter (复杂查询分解)

### 设计原则违反

根据 OLAV 开发指南：
> **Keep It Simple, Stupid (KISS)**  
> Avoid over-engineering - Don't build features you don't need  
> Prefer clarity over cleverness

**当前违反**:
- ❌ 过度依赖 LLM 智能推断（不可靠）
- ❌ 缺少简单的映射表和 validation
- ✅ 应该：提供清晰的字段映射 + 执行前验证

---

## 🎯 解决方案2：Schema-Aware Skill 增强

### 设计原则

**核心理念**: 
- 不硬编码所有可能的字段（违反 KISS）
- 而是提供**动态 schema 发现** + **常见错误映射**
- LLM 仍然主导，但有"护栏"

### 实施计划

#### Phase 2.1: 增强 SKILL.md Prompts (Schema Guidance)

**文件**: `.olav/skills/network-query/SKILL.md`

**修改 system prompt**:
```yaml
prompts:
  system: |
    You are a database query specialist with direct SQL access to network database.

    ## Schema Discovery Protocol
    
    **MANDATORY FIRST STEP**: Call inspect_schema() to verify table structure.
    
    ```python
    # Example workflow
    1. inspect_schema()  # Get all tables
    2. inspect_schema("devices")  # Get device table columns
    3. Build SQL using EXACT column names
    4. Execute with query_database()
    ```
    
    ## Common Field Name Mappings (Critical)
    
    ⚠️ USE THESE EXACT FIELD NAMES (LLM often gets these wrong):
    
    ### devices Table
    | ❌ WRONG | ✅ CORRECT | Description |
    |----------|-----------|-------------|
    | device_type | device_role | border/core/access |
    | name | hostname | Device hostname |
    | site_name | site | Site identifier |
    | ip | ip_address | Management IP |
    | os_version | ios_version | Operating system version |
    
    ### interfaces Table
    | ❌ WRONG | ✅ CORRECT | Description |
    |----------|-----------|-------------|
    | interface | interface_name | Full interface name |
    | status | admin_status | up/down |
    | speed | interface_speed | Interface speed |
    | device | device_id | Device identifier |
    
    ### interface_stats Table
    | ❌ WRONG | ✅ CORRECT | Description |
    |----------|-----------|-------------|
    | traffic | bytes_in, bytes_out | Traffic counters |
    | packets | packets_in, packets_out | Packet counters |
    | timestamp | created_at | Sample timestamp |
    
    ## Query Construction Rules
    
    ### Rule 1: Always Verify Schema First
    ```sql
    -- ❌ WRONG: Guess field names
    SELECT device_type, COUNT(*) FROM devices GROUP BY device_type
    
    -- ✅ CORRECT: Verify with inspect_schema() first
    -- After seeing devices has "device_role" column:
    SELECT device_role, COUNT(*) FROM devices GROUP BY device_role
    ```
    
    ### Rule 2: Use Explicit Column Lists
    ```sql
    -- ❌ BAD: SELECT * (ambiguous with JOINs)
    SELECT * FROM devices d JOIN interfaces i ON d.hostname = i.device
    
    -- ✅ GOOD: Explicit columns
    SELECT d.hostname, d.device_role, i.interface_name, i.admin_status
    FROM devices d
    JOIN interfaces i ON d.hostname = i.device
    ```
    
    ### Rule 3: Handle Missing Data Gracefully
    ```sql
    -- ✅ Check for empty results
    SELECT COUNT(*) FROM interfaces  -- If 0, inform user "No interface data"
    
    -- ✅ Use LEFT JOIN for optional relationships
    SELECT d.hostname, COUNT(i.interface_name) as interface_count
    FROM devices d
    LEFT JOIN interfaces i ON d.hostname = i.device
    GROUP BY d.hostname
    ```
    
    ## Error Recovery Protocol
    
    If you receive a SQL error:
    1. DO NOT retry with same field names
    2. Call inspect_schema(table_name) again
    3. Compare error message with actual schema
    4. Rebuild query with correct field names
    5. Log the correction for user visibility
    
    Example:
    ```
    Error: column "device_type" does not exist
    → Call inspect_schema("devices")
    → Find actual column: "device_role"
    → Retry with corrected SQL
    → Inform user: "Corrected field name: device_type → device_role"
    ```
    
    ## Performance Optimization
    
    - Use LIMIT for exploratory queries
    - Add indexes hints for large tables (if supported)
    - Prefer EXISTS over COUNT(*) for existence checks
    
    Remember: Schema may change, always verify before query!
```

**设计说明**:
- ✅ 提供常见错误的明确映射表
- ✅ 使用对比格式（❌ WRONG vs ✅ CORRECT）增强记忆
- ✅ 包含完整的工作流示例
- ✅ 错误恢复协议明确
- ✅ 没有硬编码所有字段（避免维护负担）

#### Phase 2.2: 实现 SQL Validator Middleware (可选优化)

如果 Skill 提示还不够，可以添加执行前验证层：

**新文件**: `src/olav/middleware/sql_validator.py`

```python
"""SQL Validation Middleware - Schema-Aware Query Validation

在 SQL 执行前验证字段名和表名，提前捕获错误。
"""

import re
from typing import Tuple
import duckdb

class SQLValidator:
    """SQL 验证器 - 使用 EXPLAIN 检测 SQL 错误"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._field_suggestions = self._load_schema_cache()
    
    def _load_schema_cache(self) -> dict[str, list[str]]:
        """加载表的字段名缓存（用于快速建议）"""
        conn = duckdb.connect(self.db_path, read_only=True)
        try:
            tables = conn.execute("SHOW TABLES").fetchall()
            cache = {}
            for (table_name,) in tables:
                columns = conn.execute(f"DESCRIBE {table_name}").fetchall()
                cache[table_name] = [col[0] for col in columns]
            return cache
        finally:
            conn.close()
    
    def validate(self, sql: str) -> Tuple[bool, str, list[str]]:
        """验证 SQL 语句
        
        Args:
            sql: SQL 查询语句
            
        Returns:
            (is_valid, error_message, suggestions)
            
        Examples:
            >>> validator.validate("SELECT device_type FROM devices")
            (False, "Column 'device_type' not found", 
             ["Did you mean 'device_role'?"])
        """
        conn = duckdb.connect(self.db_path, read_only=True)
        try:
            # 使用 EXPLAIN 检测 SQL 错误（不实际执行）
            conn.execute(f"EXPLAIN {sql}")
            return True, "", []
        except Exception as e:
            error_msg = str(e).lower()
            suggestions = []
            
            # 字段名错误检测
            if "column" in error_msg or "does not exist" in error_msg:
                # 提取错误的字段名
                match = re.search(r"column ['\"]?(\w+)['\"]?", error_msg)
                if match:
                    wrong_field = match.group(1)
                    suggestions = self._suggest_field_name(wrong_field, sql)
            
            # 表名错误检测
            elif "table" in error_msg and "not found" in error_msg:
                match = re.search(r"table ['\"]?(\w+)['\"]?", error_msg)
                if match:
                    wrong_table = match.group(1)
                    suggestions = self._suggest_table_name(wrong_table)
            
            return False, str(e), suggestions
        finally:
            conn.close()
    
    def _suggest_field_name(self, wrong_name: str, sql: str) -> list[str]:
        """基于相似度建议正确的字段名"""
        from difflib import get_close_matches
        
        # 从 SQL 推断涉及的表
        tables_in_query = []
        for table in self._field_suggestions:
            if table in sql.lower():
                tables_in_query.append(table)
        
        if not tables_in_query:
            tables_in_query = list(self._field_suggestions.keys())
        
        # 在相关表中搜索相似字段
        all_fields = []
        for table in tables_in_query:
            all_fields.extend(self._field_suggestions.get(table, []))
        
        # 使用 difflib 找到最相似的字段名
        matches = get_close_matches(wrong_name, all_fields, n=3, cutoff=0.6)
        
        if matches:
            return [f"Did you mean '{match}'?" for match in matches]
        
        return ["Check available fields with inspect_schema()"]
    
    def _suggest_table_name(self, wrong_name: str) -> list[str]:
        """建议正确的表名"""
        from difflib import get_close_matches
        
        table_names = list(self._field_suggestions.keys())
        matches = get_close_matches(wrong_name, table_names, n=2, cutoff=0.6)
        
        if matches:
            return [f"Did you mean table '{match}'?" for match in matches]
        
        return [f"Available tables: {', '.join(table_names[:5])}"]
```

**集成到 query_database tool**:
```python
@tool
def query_database(sql: str, params: list | None = None) -> str:
    """Execute SQL query with pre-validation."""
    try:
        from config.paths import get_database_path
        from olav.middleware.sql_validator import SQLValidator
        
        db_path = get_database_path()
        
        # v0.10.2: 执行前验证 SQL
        validator = SQLValidator(str(db_path))
        is_valid, error, suggestions = validator.validate(sql)
        
        if not is_valid:
            error_response = f"SQL Validation Error: {error}\n\n"
            if suggestions:
                error_response += "Suggestions:\n"
                for suggestion in suggestions:
                    error_response += f"  - {suggestion}\n"
            error_response += "\nPlease call inspect_schema() to verify field names."
            return error_response
        
        # 验证通过，执行查询
        from olav.lib.data_gateway import DataGateway
        gw = DataGateway(db_path=db_path)
        results = gw.query_main(sql, params or [])
        
        return json.dumps(results, indent=2, default=str)
    except Exception as e:
        return f"Database Error: {e}"
```

**设计说明**:
- ✅ 使用 `EXPLAIN` 不实际执行查询
- ✅ 自动加载 schema 缓存
- ✅ 使用 `difflib` 提供相似字段建议
- ✅ 明确的错误信息和修复建议
- ⚠️ 可选实现（Phase 2.1 可能已经足够）

### 验证计划

#### 验证1: SKILL.md 提示生效
```bash
# 测试之前失败的查询
uv run olav query "按设备类型分类统计"

# 预期:
# 1. LLM 看到提示：device_type → device_role
# 2. 生成正确 SQL: SELECT device_role, COUNT(*) FROM devices GROUP BY device_role
# 3. 查询成功，无需重试
```

#### 验证2: 错误恢复
```bash
# 故意使用错误字段名（模拟 LLM 失误）
uv run python -c "
from olav.tools.react_query import query_database
result = query_database('SELECT device_type FROM devices')
print(result)
"

# 预期输出（如果实现了 SQL Validator）:
# SQL Validation Error: Column 'device_type' not found
# Suggestions:
#   - Did you mean 'device_role'?
# Please call inspect_schema() to verify field names.
```

#### 验证3: 通过率改善
```bash
# 重新运行 L1 测试
uv run python quick_l1_test.py

# 预期:
# L1-P0-004 "按设备类型分类" 从 TIMEOUT → PASSED
# 整体通过率: 6/9 → 8/9 (89%)
```

### 预期效果

| 指标 | 修复前 | 修复后 | 改善 |
|------|--------|--------|------|
| **SQL 生成准确率** | 70% | 90% | +20% |
| **查询重试次数** | 平均 2-3 次 | <1.5 次 | -50% |
| **超时失败** | 3/24 | 1/24 | -67% |
| **L1 通过率** | 67% | 89% | +22% |

---

## 🚀 问题3：查询缓存未生效 (Medium)

### 问题描述

**现象**: 
- 响应时间平均 32 秒，无明显缓存加速
- 相同查询重复执行，无缓存命中
- 数据库 olav.duckdb 已有 query_cache 表（0 rows）

**预期**:
- 第一次查询: 32 秒
- 第二次相同查询: <5 秒（缓存命中）
- 语义相似查询: <10 秒（语义缓存）

### 根因分析

#### 架构分析

**当前代码**:
```python
# config/paths.py
SNAPSHOTS_DB = UNIFIED_DB  # 指向 olav.duckdb

# src/olav/core/query_cache.py (推测存在)
class QueryCache:
    def __init__(self):
        from config.paths import SNAPSHOTS_DB
        self.db = SNAPSHOTS_DB
```

**检查1: 缓存是否被初始化？**
```bash
cd /home/yhvh/Olav
uv run python -c "
import duckdb
conn = duckdb.connect('.olav/db/olav.duckdb', read_only=True)
print(conn.execute('SELECT COUNT(*) FROM query_cache').fetchone()[0])
conn.close()
"
# 输出: 0 → 缓存从未写入
```

**检查2: 缓存是否被调用？**
```bash
grep -r "QueryCache" src/olav/
# 预期：应该在 orchestrator.py 或 query_agent 中使用
```

**检查3: 多 Agent 共享缓存？**
```
当前架构:
Orchestrator
  ├─ QueryAgent (SubAgent)
  ├─ AnalysisAgent (SubAgent)
  └─ CLIAgent (SubAgent)

问题：每个 SubAgent 独立实例化，可能各自有缓存实例？
答案：需要检查 orchestrator.py 的 SubAgent 配置
```

#### 可能的根因（待验证）

**假设1: 缓存未被使用**
```python
# 可能的代码
def create_query_agent():
    # 没有注入 QueryCache middleware
    return create_deep_agent(
        tools=[query_database, inspect_schema],
        # ❌ 缺少: checkpointer=..., store=...
    )
```

**假设2: 缓存配置错误**
```python
# 可能的代码
cache = QueryCache(ttl=3600)  # 设置了TTL
# 但查询时没有实际写入缓存
```

**假设3: 多实例导致缓存不共享**
```python
# 每次查询都创建新的 Agent 实例
agent1 = create_query_agent()  # 有自己的缓存实例
result1 = agent1.query("有多少设备")

agent2 = create_query_agent()  # 又创建了新实例，缓存不共享
result2 = agent2.query("有多少设备")  # 无法命中 agent1 的缓存
```

### 代码证据收集（待执行）

需要检查以下文件：

1. **`src/olav/core/query_cache.py`** - 缓存实现
2. **`src/olav/agents/orchestrator.py:150-200`** - SubAgent 配置
3. **`src/olav/core/subagent_loader.py`** - SubAgent 实例化逻辑
4. **`.olav/OLAV.md`** - SubAgent 配置中是否有 cache 配置

---

## 🎯 解决方案3：统一缓存架构修复

### 调查计划（先诊断，再开药）

#### Step 1: 检查缓存代码是否存在
```bash
cd /home/yhvh/Olav
find src -name "*cache*.py" -type f
grep -r "QueryCache" src/olav/
```

#### Step 2: 检查 Orchestrator 的 SubAgent 配置
```bash
# 查看 orchestrator.py 中 SubAgent 的 checkpointer 配置
grep -A 20 "create_orchestrator" src/olav/agents/orchestrator.py

# 查看 OLAV.md 中的 SubAgent 配置
cat .olav/OLAV.md | grep -A 30 "query"
```

#### Step 3: 检查 DeepAgents 的缓存机制
```bash
# DeepAgents 可能有内置的缓存中间件
uv run python -c "
from deepagents import create_deep_agent
import inspect
print(inspect.signature(create_deep_agent))
"
# 查看参数中是否有 cache 相关配置
```

#### Step 4: 运行诊断脚本
```python
#!/usr/bin/env python3
"""缓存诊断脚本"""
import duckdb
from pathlib import Path

OLAV_DB = Path(".olav/db/olav.duckdb")

# 检查缓存表结构
conn = duckdb.connect(str(OLAV_DB), read_only=True)

print("=== Cache Table Schema ===")
try:
    schema = conn.execute("DESCRIBE query_cache").fetchall()
    for col in schema:
        print(f"{col[0]}: {col[1]}")
except Exception as e:
    print(f"Error: {e}")

print("\n=== Cache Table Content ===")
try:
    count = conn.execute("SELECT COUNT(*) FROM query_cache").fetchone()[0]
    print(f"Total entries: {count}")
    
    if count > 0:
        samples = conn.execute("SELECT * FROM query_cache LIMIT 5").fetchall()
        for row in samples:
            print(row)
except Exception as e:
    print(f"Error: {e}")

conn.close()
```

### 修复方案（基于诊断结果）

根据调查结果，修复方案分为以下几种情况：

#### 情况A: 缓存代码存在但未使用

**修复**: 在 Orchestrator 和 SubAgents 中启用缓存

**文件**: `src/olav/agents/orchestrator.py`

**修改**:
```python
def create_orchestrator(...):
    # ... existing code ...
    
    # v0.10.2: 启用统一缓存层 (DuckDBSaver)
    from langgraph.checkpoint.duckdb import DuckDBSaver
    from config.paths import UNIFIED_DB
    
    # 共享的 checkpoint 存储（所有 SubAgents 共用）
    checkpointer = DuckDBSaver.from_conn_string(str(UNIFIED_DB))
    
    # Orchestrator 使用共享 checkpointer
    orchestrator = create_deep_agent(
        name="orchestrator",
        tools=orchestrator_tools,
        system_prompt=system_prompt,
        subagents=subagents,
        checkpointer=checkpointer,  # 启用缓存
        middleware=middleware
    )
    
    return orchestrator.compile()
```

**文件**: `.olav/OLAV.md` (SubAgent 配置)

```yaml
## SubAgents

### query
- **name**: query
- **skill**: network-query
- **description**: SQL database queries for device inventory and network state
- **config**:
  - use_shared_checkpoint: true  # 关键：使用 Orchestrator 的共享 checkpointer
  - cache_ttl: 3600  # 缓存1小时
```

#### 情况B: 缓存代码不存在，需要实现

**实现**: 创建统一的语义缓存层

**新文件**: `src/olav/core/semantic_cache.py`

```python
"""Semantic Query Cache - Multi-Agent Shared Cache

所有 SubAgents 共享的语义缓存，基于 DuckDB 持久化。
"""

import hashlib
import json
import time
from typing import Any, Optional
import duckdb
from pathlib import Path

class SemanticQueryCache:
    """语义查询缓存（多 Agent 共享）"""
    
    def __init__(self, db_path: Path, ttl: int = 3600):
        """
        Args:
            db_path: DuckDB 数据库路径（通常是 olav.duckdb）
            ttl: 缓存过期时间（秒），默认 1 小时
        """
        self.db_path = db_path
        self.ttl = ttl
        self._ensure_table()
    
    def _ensure_table(self):
        """确保缓存表存在"""
        conn = duckdb.connect(str(self.db_path))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS query_cache (
                    query_hash VARCHAR PRIMARY KEY,
                    original_query TEXT,
                    query_result TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    hit_count INTEGER DEFAULT 0
                )
            """)
            conn.commit()
        finally:
            conn.close()
    
    def get(self, query: str) -> Optional[Any]:
        """获取缓存结果
        
        Args:
            query: 用户查询
            
        Returns:
            缓存的结果，如果未命中或过期则返回 None
        """
        query_hash = self._hash_query(query)
        
        conn = duckdb.connect(str(self.db_path))
        try:
            result = conn.execute("""
                SELECT query_result, created_at
                FROM query_cache
                WHERE query_hash = ?
            """, [query_hash]).fetchone()
            
            if result is None:
                return None
            
            cached_result, created_at = result
            
            # 检查是否过期
            age = time.time() - created_at.timestamp()
            if age > self.ttl:
                return None
            
            # 更新访问统计
            conn.execute("""
                UPDATE query_cache
                SET accessed_at = CURRENT_TIMESTAMP,
                    hit_count = hit_count + 1
                WHERE query_hash = ?
            """, [query_hash])
            conn.commit()
            
            return json.loads(cached_result)
        finally:
            conn.close()
    
    def set(self, query: str, result: Any):
        """存入缓存
        
        Args:
            query: 用户查询
            result: 查询结果（将被 JSON 序列化）
        """
        query_hash = self._hash_query(query)
        result_json = json.dumps(result, default=str)
        
        conn = duckdb.connect(str(self.db_path))
        try:
            conn.execute("""
                INSERT INTO query_cache (query_hash, original_query, query_result)
                VALUES (?, ?, ?)
                ON CONFLICT (query_hash) DO UPDATE SET
                    query_result = EXCLUDED.query_result,
                    created_at = CURRENT_TIMESTAMP,
                    accessed_at = CURRENT_TIMESTAMP
            """, [query_hash, query, result_json])
            conn.commit()
        finally:
            conn.close()
    
    def _hash_query(self, query: str) -> str:
        """生成查询的哈希值（用于精确匹配）"""
        # 标准化查询（移除多余空格，转小写）
        normalized = " ".join(query.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()
    
    def clear_expired(self):
        """清理过期缓存"""
        conn = duckdb.connect(str(self.db_path))
        try:
            conn.execute("""
                DELETE FROM query_cache
                WHERE EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - created_at)) > ?
            """, [self.ttl])
            conn.commit()
        finally:
            conn.close()
    
    def stats(self) -> dict:
        """获取缓存统计"""
        conn = duckdb.connect(str(self.db_path), read_only=True)
        try:
            total = conn.execute("SELECT COUNT(*) FROM query_cache").fetchone()[0]
            hits = conn.execute(
                "SELECT SUM(hit_count) FROM query_cache"
            ).fetchone()[0] or 0
            
            return {
                "total_entries": total,
                "total_hits": hits,
                "ttl": self.ttl
            }
        finally:
            conn.close()
```

**集成到 Orchestrator**:
```python
def create_orchestrator(...):
    from olav.core.semantic_cache import SemanticQueryCache
    from config.paths import UNIFIED_DB
    
    # 创建全局缓存实例
    global_cache = SemanticQueryCache(UNIFIED_DB, ttl=3600)
    
    # 将缓存注入到 SubAgents 配置
    for subagent in subagents:
        if subagent.name == "query":
            # 注入缓存到 query SubAgent
            subagent.config = subagent.config or {}
            subagent.config["cache"] = global_cache
    
    # ... rest of orchestrator setup ...
```

**修改 query_database tool 使用缓存**:
```python
@tool
def query_database(sql: str, params: list | None = None) -> str:
    """Execute SQL query with caching."""
    try:
        # 尝试从缓存获取
        from olav.core.semantic_cache import SemanticQueryCache
        from config.paths import UNIFIED_DB
        
        cache = SemanticQueryCache(UNIFIED_DB)
        cache_key = f"{sql}|{params}"
        
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            logger.info(f"Cache HIT for query: {sql[:50]}...")
            return cached_result
        
        # 缓存未命中，执行查询
        logger.info(f"Cache MISS for query: {sql[:50]}...")
        
        from olav.lib.data_gateway import DataGateway
        gw = DataGateway(db_path=get_database_path())
        results = gw.query_main(sql, params or [])
        
        result_json = json.dumps(results, indent=2, default=str)
        
        # 存入缓存
        cache.set(cache_key, result_json)
        
        return result_json
    except Exception as e:
        return f"Database Error: {e}"
```

#### 情况C: 缓存存在但多实例不共享

**修复**: 使用单例模式确保缓存共享

**文件**: `src/olav/core/semantic_cache.py`

```python
class SemanticQueryCache:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, db_path: Path, ttl: int = 3600):
        """单例模式：确保所有 Agent 共享同一个缓存实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, db_path: Path, ttl: int = 3600):
        if self._initialized:
            return  # 已初始化，跳过
        
        self.db_path = db_path
        self.ttl = ttl
        self._ensure_table()
        self._initialized = True
```

### 验证计划

#### 验证1: 缓存写入
```bash
# 执行一次查询
uv run olav query "有多少台设备?"

# 检查缓存表
uv run python -c "
import duckdb
conn = duckdb.connect('.olav/db/olav.duckdb', read_only=True)
count = conn.execute('SELECT COUNT(*) FROM query_cache').fetchone()[0]
print(f'Cache entries: {count}')
conn.close()
"
# 预期: Cache entries: 1
```

#### 验证2: 缓存命中
```bash
# 第一次查询（应该慢）
time uv run olav query "有多少台设备?"
# 预期: ~30 秒

# 第二次相同查询（应该快）
time uv run olav query "有多少台设备?"
# 预期: <5 秒（缓存命中）
```

#### 验证3: 多 Agent 共享
```bash
# Query Agent 查询
uv run olav query "列出所有设备"

# Analysis Agent 相同查询（应该命中 Query Agent 的缓存）
uv run olav analyze "列出所有设备"
# 预期: 缓存命中，快速返回
```

#### 验证4: 缓存统计
```python
from olav.core.semantic_cache import SemanticQueryCache
from config.paths import UNIFIED_DB

cache = SemanticQueryCache(UNIFIED_DB)
stats = cache.stats()
print(stats)
# 预期: {'total_entries': 5, 'total_hits': 12, 'ttl': 3600}
```

### 预期效果

| 指标 | 修复前 | 修复后 | 改善 |
|------|--------|--------|------|
| **首次查询** | 32s | 32s | 无变化 |
| **重复查询** | 32s | <5s | -84% |
| **相似查询** | 32s | <10s | -69% |
| **缓存命中率** | 0% | 60-70% | +60% |
| **平均响应时间** | 32s | 15s | -53% |

---

## 📅 实施时间表

### Phase 0: 调查与验证 (0.5天)
```
□ 运行缓存诊断脚本
□ 检查当前代码中的缓存实现
□ 确定具体需要修复的情况（A/B/C）
```

### Phase 1: 数据库配置重构 (1天)
```
Day 1 Morning (4h):
  □ 修改 config/settings.py 添加 DatabaseSettings
  □ 修改 config/paths.py 支持环境变量
  □ 修改 data_gateway.py 支持动态路径
  □ 修改 query_database tool 支持动态路径

Day 1 Afternoon (4h):
  □ 更新测试脚本 (quick_l1_test.py, run_l2_tests.py)
  □ 更新 .env.example 文档
  □ 运行验证测试
  □ 修复发现的问题

验收标准:
  ✅ L1: 6/9 → 8/9 (89%)
  ✅ L2: 10/15 → 14/15 (93%)
  ✅ 整体: 67% → 92%
```

### Phase 2: Schema-Aware Skill 增强 (1天)
```
Day 2 Morning (3h):
  □ 更新 .olav/skills/network-query/SKILL.md
  □ 添加字段名映射表
  □ 添加错误恢复协议

Day 2 Afternoon (5h):
  □ (可选) 实现 SQL Validator middleware
  □ (可选) 集成到 query_database tool
  □ 运行验证测试
  □ 调整提示直到通过率满意

验收标准:
  ✅ SQL 生成准确率: 70% → 90%
  ✅ L1: 8/9 → 9/9 (100%)
  ✅ 超时失败: 3/24 → 1/24
```

### Phase 3: 缓存架构修复 (1-2天)
```
Day 3 (Full Day):
  □ 根据 Phase 0 调查结果选择修复方案
  □ 实现或修复 SemanticQueryCache
  □ 集成到 Orchestrator 和 SubAgents
  □ 确保多 Agent 共享缓存
  □ 运行性能测试

Day 4 (Optional, 如需优化):
  □ 实现语义相似度匹配（而非精确匹配）
  □ 添加缓存预热机制
  □ 优化缓存清理策略

验收标准:
  ✅ 缓存命中率: 0% → 60%
  ✅ 重复查询: 32s → <5s
  ✅ 平均响应: 32s → 15s
```

### Phase 4: 文档与验证 (0.5天)
```
□ 更新 docs/user_guide/OLAV_QUERY_COMMANDS.md
□ 创建 docs/reference/DATABASE_CONFIGURATION.md
□ 更新 docs/reference/CACHING_ARCHITECTURE.md
□ 运行完整测试套件 (L1+L2+L3)
□ 生成最终测试报告

验收标准:
  ✅ L1+L2: 24/24 (100%)
  ✅ L3: ≥36/45 (80%)
  ✅ 文档完整且准确
```

**总计**: 3-4 天工作量

---

## ✅ 验收标准

### 整体指标
| 指标 | 当前 | 目标 | 验收 |
|------|------|------|------|
| **L1 通过率** | 67% (6/9) | 100% (9/9) | ✅ Pass |
| **L2 通过率** | 67% (10/15) | 100% (15/15) | ✅ Pass |
| **L3 通过率** | 未测试 | ≥80% (36/45) | ✅ Pass |
| **整体通过率** | 67% | ≥95% | ✅ Pass |
| **平均响应时间** | 32s | <20s | ✅ Pass |
| **缓存命中响应** | N/A | <5s | ✅ Pass |

### 功能验收
```
□ 测试环境使用 test_network.duckdb
□ 生产环境使用 olav.duckdb
□ 环境变量 OLAV_DB_PATH 可覆盖
□ SQL 字段名错误有明确提示
□ 查询缓存自动命中
□ 多 Agent 共享缓存
□ 文档完整且准确
```

---

## 📚 相关文档

- **当前报告**: [TEST_FAILURE_ANALYSIS.md](TEST_FAILURE_ANALYSIS.md)
- **用户指南**: [docs/user_guide/OLAV_QUERY_COMMANDS.md](../user_guide/OLAV_QUERY_COMMANDS.md)
- **架构文档**: [docs/reference/ARCHITECTURE.md](../reference/ARCHITECTURE.md)
- **配置参考**: [docs/reference/CONFIGURATION_REFERENCE.md](../reference/CONFIGURATION_REFERENCE.md)

---

**Generated**: 2026-02-09 11:30  
**Status**: 📋 Ready for Implementation  
**Next Step**: Phase 0 - 运行诊断脚本确定缓存修复方案
