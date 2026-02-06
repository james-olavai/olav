"""
Platform-agnostic Data Gateway
Compatible with: OLAV CLI, Web API, Claude Code, Gemini Agent
"""

import json
from pathlib import Path
from typing import Any

import duckdb

from config.logging import get_logger

logger = get_logger(__name__)


class DataGateway:
    """统一数据访问接口 - 平台无关

    使用方式:
        from config.paths import OLAV_BASE_DIR
        
        # OLAV CLI
        gw = DataGateway(OLAV_BASE_DIR)

        # Claude Code  
        gw = DataGateway(Path(".claude"))

        # Web API
        gw = DataGateway(Path(os.getenv("BASE_DIR", ".olav")))
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        """初始化 Data Gateway

        Args:
            base_dir: .olav/ 或 .claude/ 或 .gemini/ 根目录
        """
        from config.paths import AGENT_DIR
        
        self.base_dir = base_dir or AGENT_DIR
        self.db_dir = self.base_dir / "db"
        self.skills_dir = self.base_dir / "skills"

        # 确保目录存在
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    # ==================== 共享数据层 API ====================

    def query_main(self, sql: str, params: list | None = None) -> list[dict]:
        """查询主数据库 olav.duckdb (包含所有核心数据 - v0.10.1统一架构)

        Args:
            sql: DuckDB SQL 查询
            params: 查询参数

        Returns:
            查询结果列表

        Example:
            >>> gw.query_main("SELECT DISTINCT device FROM devices")
            [{'device': 'R1'}, {'device': 'R2'}, ...]

        NOTE (v0.10.1): All data is now in single UNIFIED_DB
        """
        from config.paths import UNIFIED_DB
        
        conn = duckdb.connect(str(UNIFIED_DB), read_only=True)
        try:
            if params:
                result = conn.execute(sql, params)
            else:
                result = conn.execute(sql)

            # Get column names from description
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()

            # Convert to list of dicts
            return [dict(zip(columns, row, strict=False)) for row in rows]
        finally:
            conn.close()

    def query_snapshots(self, sql: str, params: list | None = None) -> list[dict]:
        """查询网络快照数据 (只读) - 现在指向UNIFIED_DB (v0.10.1)

        Args:
            sql: DuckDB SQL 查询
            params: 查询参数

        Returns:
            查询结果列表

        Example:
            >>> gw.query_snapshots("SELECT * FROM topology_links WHERE local_device = ?", ["R1"])

        NOTE (v0.10.1): All data consolidated into single UNIFIED_DB
        """
        from config.paths import UNIFIED_DB
        
        conn = duckdb.connect(str(UNIFIED_DB), read_only=True)
        try:
            if params:
                result = conn.execute(sql, params)
            else:
                result = conn.execute(sql)

            # Get column names from description
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()

            # Convert to list of dicts
            return [dict(zip(columns, row, strict=False)) for row in rows]
        finally:
            conn.close()

    def get_topology(self, device: str | None = None) -> list[dict]:
        """获取拓扑数据 (只读)

        Args:
            device: 可选，指定设备名称

        Returns:
            拓扑数据
        """
        conn = duckdb.connect(str(self.db_dir / "topology.duckdb"), read_only=True)
        try:
            if device:
                sql = "SELECT * FROM devices WHERE name = ?"
                result = conn.execute(sql, [device])
            else:
                result = conn.execute("SELECT * FROM devices")

            # Get column names and convert to list of dicts
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            return [dict(zip(columns, row, strict=False)) for row in rows]
        finally:
            conn.close()

    def log_command(
        self, skill: str, device: str, command: str, status: str, error: str | None = None
    ) -> None:
        """记录命令执行审计 (写入) - 使用 UNIFIED_DB (v0.10.1)

        Args:
            skill: Skill 名称 (e.g., 'network-query')
            device: 设备名称
            command: 执行的命令
            status: 'success', 'failed', 'blocked'
            error: 错误信息 (可选)

        NOTE (v0.10.1): Audit logs now in UNIFIED_DB instead of separate audit_logs.duckdb
        """
        from config.paths import UNIFIED_DB
        
        conn = duckdb.connect(str(UNIFIED_DB))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS command_audit (
                    id UUID PRIMARY KEY DEFAULT uuid(),
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    skill TEXT,
                    device TEXT,
                    command TEXT,
                    status TEXT,
                    error TEXT
                )
            """)
            conn.execute(
                """
                INSERT INTO command_audit (skill, device, command, status, error)
                VALUES (?, ?, ?, ?, ?)
            """,
                [skill, device, command, status, error],
            )
        finally:
            conn.close()

    # ==================== Skill 私有数据 API ====================

    def query_skill_memory(
        self, skill_name: str, sql: str, params: list | None = None
    ) -> list[dict]:
        """查询 Skill 私有记忆数据库

        Args:
            skill_name: Skill 名称 (e.g., 'network-expert')
            sql: SQL 查询
            params: 查询参数

        Returns:
            查询结果

        Example:
            >>> cases = gw.query_skill_memory(
            ...     "network-expert",
            ...     "SELECT * FROM diagnosis_cases WHERE symptom LIKE ?",
            ...     ["%BGP%"]
            ... )
        """
        # Updated: Use skill.duckdb instead of memory.duckdb
        memory_db = self.skills_dir / skill_name / "skill.duckdb"
        if not memory_db.exists():
            return []

        conn = duckdb.connect(str(memory_db), read_only=True)
        try:
            if params:
                result = conn.execute(sql, params)
            else:
                result = conn.execute(sql)

            # Get column names and convert to list of dicts
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            return [dict(zip(columns, row, strict=False)) for row in rows]
        finally:
            conn.close()

    def save_skill_memory(self, skill_name: str, table: str, data: dict) -> None:
        """写入 Skill 私有记忆数据

        Args:
            skill_name: Skill 名称
            table: 表名
            data: 数据字典

        Example:
            >>> gw.save_skill_memory("network-expert", "diagnosis_cases", {
            ...     "symptom": "BGP neighbor down",
            ...     "root_cause": "MTU mismatch",
            ...     "solution": "Set MTU to 1500"
            ... })
        """
        # Updated: Use skill.duckdb instead of memory.duckdb
        memory_db = self.skills_dir / skill_name / "skill.duckdb"
        memory_db.parent.mkdir(parents=True, exist_ok=True)

        conn = duckdb.connect(str(memory_db))
        try:
            # 动态插入数据
            columns = ", ".join(data.keys())
            placeholders = ", ".join(["?"] * len(data))
            values = list(data.values())

            conn.execute(
                f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",  # noqa: S608
                values,
            )
        finally:
            conn.close()

    # ==================== Agentic Learning API ====================

    def save_user_alias(
        self, skill_name: str, alias: str, canonical: str, type: str = "device"
    ) -> None:
        """保存用户别名学习（使用 DuckDBStore）

        存储在 USER_CHECKPOINT_PATH 的 DuckDBStore 中。

        Args:
            skill_name: Skill 名称 (e.g., 'network-query')
            alias: 用户说的词 (如 "核心路由器")
            canonical: 规范名称 (如 "R1,R2,R3")
            type: 类型 ('device', 'site', 'group')

        Example:
            >>> gw.save_user_alias("network-query", "核心路由器", "R1,R2,R3", "device")
        """
        from datetime import datetime

        import duckdb
        from langgraph.store.duckdb import DuckDBStore

        from config.paths import USER_CHECKPOINT_PATH

        USER_CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Use read-write connection
        conn = duckdb.connect(str(USER_CHECKPOINT_PATH))

        try:
            store = DuckDBStore(conn)
            # Only setup if tables don't exist
            try:
                store.setup()
            except Exception as e:
                # Tables likely already exist from previous setup
                logger.debug(f"DuckDBStore setup skipped (likely already exists): {e}")

            namespace = (skill_name, "aliases")
            key = alias.upper()  # 大小写不敏感

            # 尝试获取现有记录
            existing = store.get(namespace, key)
            usage_count = 1
            created_at = datetime.now().isoformat()

            if existing:
                usage_count = existing.value.get("usage_count", 0) + 1
                created_at = existing.value.get("created_at", created_at)

            # 存储/更新别名
            store.put(
                namespace,
                key,
                {
                    "canonical": canonical.upper(),
                    "type": type,
                    "usage_count": usage_count,
                    "created_at": created_at,
                    "last_used": datetime.now().isoformat(),
                },
            )
        finally:
            conn.close()

    # Alias for backward compatibility
    learn_user_alias = save_user_alias

    def get_user_alias(self, skill_name: str, alias: str) -> str | None:
        """获取别名映射（使用 DuckDBStore）

        Args:
            skill_name: Skill 名称
            alias: 用户说的词

        Returns:
            规范名称，未找到返回 None

        Example:
            >>> canonical = gw.get_user_alias("network-query", "核心路由器")
            >>> assert canonical == "R1,R2,R3"
        """
        import duckdb
        from langgraph.store.duckdb import DuckDBStore

        from config.paths import USER_CHECKPOINT_PATH

        if not USER_CHECKPOINT_PATH.exists():
            return None

        conn = duckdb.connect(str(USER_CHECKPOINT_PATH), read_only=True)
        try:
            store = DuckDBStore(conn)
            namespace = (skill_name, "aliases")
            key = alias.upper()  # 大小写不敏感

            item = store.get(namespace, key)
            return item.value.get("canonical") if item else None
        finally:
            conn.close()

    def save_diagnosis_case(
        self,
        skill_name: str,
        symptom: str,
        devices_checked: list,
        commands_used: list,
        root_cause: str,
        solution: str,
        snapshot_id: str | None = None,
    ) -> None:
        """保存诊断案例学习

        Args:
            skill_name: Skill 名称 (e.g., 'network-expert')
            symptom: 症状描述
            devices_checked: 检查的设备列表
            commands_used: 执行的命令列表
            root_cause: 根因分析
            solution: 解决方案
            snapshot_id: 快照 ID (可选)

        Example:
            >>> gw.save_diagnosis_case(
            ...     "network-expert",
            ...     "BGP neighbor down",
            ...     ["R1", "R2"],
            ...     ["show ip bgp summary", "show interface"],
            ...     "MTU mismatch",
            ...     "Set MTU to 1500"
            ... )
        """

        skill_db = self.skills_dir / skill_name / "skill.duckdb"
        skill_db.parent.mkdir(parents=True, exist_ok=True)

        conn = duckdb.connect(str(skill_db))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history_cases (
                    id UUID PRIMARY KEY DEFAULT uuid(),
                    symptom TEXT NOT NULL,
                    devices_checked JSON,
                    commands_used JSON,
                    diagnosis_steps TEXT,
                    root_cause TEXT,
                    solution TEXT,
                    snapshot_id TEXT,
                    created_at TIMESTAMP DEFAULT current_localtimestamp()
                )
            """)
            conn.execute(
                """
                INSERT INTO history_cases
                (symptom, devices_checked, commands_used, root_cause, solution, snapshot_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                [
                    symptom,
                    json.dumps(devices_checked, ensure_ascii=False),
                    json.dumps(commands_used, ensure_ascii=False),
                    root_cause,
                    solution,
                    snapshot_id,
                ],
            )
        finally:
            conn.close()

    def search_similar_cases(
        self, skill_name: str, symptom: str, max_age_days: int = 30, limit: int = 5
    ) -> list[dict]:
        """检索相似诊断案例

        Args:
            skill_name: Skill 名称
            symptom: 症状关键词
            max_age_days: 最大案例年龄 (天)
            limit: 返回数量

        Returns:
            案例列表

        Example:
            >>> cases = gw.search_similar_cases("network-expert", "BGP")
            >>> for case in cases:
            ...     print(f"{case['symptom']}: {case['root_cause']}")
        """
        skill_db = self.skills_dir / skill_name / "skill.duckdb"
        if not skill_db.exists():
            return []

        conn = duckdb.connect(str(skill_db), read_only=True)
        try:
            # 使用 LIKE 进行简单匹配，搜索 symptom 和 root_cause
            results = conn.execute(
                """
                SELECT
                    symptom,
                    root_cause,
                    solution,
                    created_at,
                    DATEDIFF('day', created_at, CURRENT_TIMESTAMP) as age_days
                FROM history_cases
                WHERE symptom LIKE ? OR root_cause LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
            """,
                [f"%{symptom}%", f"%{symptom}%", limit],
            ).fetchall()

            # 转换为字典列表
            columns = ["symptom", "root_cause", "solution", "created_at", "age_days"]
            cases = [dict(zip(columns, row, strict=False)) for row in results]

            # 应用时间过滤
            return [c for c in cases if c.get("age_days", 0) <= max_age_days]
        finally:
            conn.close()


# ==================== 便捷工厂函数 ====================


def get_gateway(base_dir: str | None = None) -> DataGateway:
    """获取 DataGateway 实例 (单例模式可选)

    Args:
        base_dir: 基础目录路径，默认使用 config.paths.AGENT_DIR

    Returns:
        DataGateway 实例
    """
    import os
    from config.paths import AGENT_DIR

    base = Path(base_dir or os.getenv("OLAV_BASE_DIR") or str(AGENT_DIR))
    return DataGateway(base)


# ==================== 通用查询函数 ====================


def get_connection(db_path: str | None = None):
    """获取数据库连接 (支持 Mock)

    Args:
        db_path: 数据库文件路径

    Returns:
        DuckDB 连接对象
    """
    if not db_path:
        from config.paths import MAIN_DB_PATH
        db_path = str(MAIN_DB_PATH)

    return duckdb.connect(db_path)


def _create_unified_connection() -> duckdb.DuckDBPyConnection:
    """Create a read-only connection to the unified database (v0.10.1).

    v0.10.1 Architecture: All data (devices, raw_outputs, audit, knowledge) 
    is now consolidated into a single UNIFIED_DB (olav.duckdb).
    
    This function provides direct access without multi-database attachment,
    since all tables now exist in one file.
    """
    import logging

    logger = logging.getLogger(__name__)

    from config.paths import UNIFIED_DB

    # Connect directly to unified database
    # No attachment needed - all tables in one file
    conn = duckdb.connect(str(UNIFIED_DB), read_only=True)
    logger.debug(f"Connected to unified database: {UNIFIED_DB}")
    
    return conn


def query_database(sql: str, params: list[Any] | None = None, db_path: str | None = None) -> list[dict[str, Any]]:
    """执行通用数据库查询 (线程安全、参数化)

    Features:
    - 参数化查询防护 SQL 注入
    - 自动行转换为字典列表
    - 错误处理和日志记录
    - 支持自定义数据库路径
    - 统一数据库访问（自动挂载 main.duckdb + olav.duckdb + snapshots.duckdb）

    Args:
        sql: DuckDB SQL 查询语句
        params: 查询参数列表（用于参数化查询）
        db_path: 数据库文件路径（None = 统一路由，明确路径 = 强制使用）

    Returns:
        查询结果列表（每个元素为字典）

    Raises:
        ValueError: SQL 为空
        RuntimeError: 数据库连接/执行错误

    Example:
        >>> result = query_database(
        ...     "SELECT * FROM devices WHERE hostname = ?",
        ...     ["R1"]
        ... )
        >>> print(result)
        [{'device_id': 'R1', 'hostname': 'R1', 'ip_address': '192.168.100.101', ...}]
    """
    import logging

    logger = logging.getLogger(__name__)

    if not sql or not sql.strip():
        raise ValueError("SQL query cannot be empty")

    try:
        # Use explicit path if provided, otherwise unified connection
        if db_path is not None:
            conn = get_connection(db_path)
        else:
            conn = _create_unified_connection()

        try:
            # 参数化查询（防护 SQL 注入）
            if params:
                logger.debug(f"Executing parameterized query with {len(params)} params")
                result = conn.execute(sql, params)
            else:
                logger.debug("Executing query without parameters")
                result = conn.execute(sql)

            # 获取列名
            columns = [desc[0] for desc in result.description] if result.description else []

            # 获取所有行
            rows = result.fetchall()

            # 转换为字典列表
            results = [dict(zip(columns, row, strict=False)) for row in rows]

            logger.debug(f"Query returned {len(results)} rows with columns: {columns}")

            return results

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Database query failed: {e}", exc_info=True)

        # Provide helpful error messages for common issues
        error_msg = str(e)
        if "does not exist" in error_msg:
            # Try to list available tables from unified connection
            try:
                diag_conn = _create_unified_connection()
                available_tables = diag_conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'main' ORDER BY table_name"
                ).fetchall()
                diag_conn.close()

                table_list = ", ".join([t[0] for t in available_tables])
                raise RuntimeError(
                    f"Query failed: {error_msg}. "
                    f"Available tables: {table_list}. "
                    f"Use inspect_schema() to check table columns."
                ) from e
            except RuntimeError:
                raise
            except Exception:
                raise RuntimeError(
                    f"Database query failed: {error_msg}."
                ) from e
        else:
            raise RuntimeError(f"Database query failed: {error_msg}") from e
