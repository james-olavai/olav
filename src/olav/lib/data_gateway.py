"""
Platform-agnostic Data Gateway
Compatible with: OLAV CLI, Web API, Claude Code, Gemini Agent
"""

import json
from pathlib import Path

import duckdb


class DataGateway:
    """统一数据访问接口 - 平台无关

    使用方式:
        # OLAV CLI
        gw = DataGateway(Path(".olav"))

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
        self.base_dir = base_dir or Path(".olav")
        self.db_dir = self.base_dir / "db"
        self.skills_dir = self.base_dir / "skills"

        # 确保目录存在
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    # ==================== 共享数据层 API ====================

    def query_snapshots(self, sql: str, params: list | None = None) -> list[dict]:
        """查询网络快照数据 (只读)

        Args:
            sql: DuckDB SQL 查询
            params: 查询参数

        Returns:
            查询结果列表

        Example:
            >>> gw.query_snapshots("SELECT * FROM v_interfaces WHERE device = ?", ["R1"])
        """
        conn = duckdb.connect(str(self.db_dir / "snapshots.duckdb"), read_only=True)
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
        """记录命令执行审计 (写入)

        Args:
            skill: Skill 名称 (e.g., 'network-query')
            device: 设备名称
            command: 执行的命令
            status: 'success', 'failed', 'blocked'
            error: 错误信息 (可选)
        """
        conn = duckdb.connect(str(self.db_dir / "audit_logs.duckdb"))
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

    def get_skill_cache(self, skill_name: str, key: str) -> dict | None:
        """读取 Skill 缓存 (私有数据)

        Args:
            skill_name: Skill 名称 (e.g., 'network-query')
            key: 缓存键

        Returns:
            缓存值，未找到返回 None

        Example:
            >>> plan = gw.get_skill_cache("network-query", "query:show interfaces")
        """
        # Updated: Use skill.duckdb instead of cache.duckdb
        skill_db = self.skills_dir / skill_name / "skill.duckdb"
        if not skill_db.exists():
            return None

        conn = duckdb.connect(str(skill_db), read_only=True)
        try:
            # Try intent_cache table first
            result = conn.execute(
                "SELECT execution_plan FROM intent_cache WHERE query_text = ?", [key]
            ).fetchone()

            if result:
                return json.loads(result[0])

            # Fall back to generic cache table
            result = conn.execute("SELECT value FROM cache WHERE key = ?", [key]).fetchone()
            return json.loads(result[0]) if result else None
        finally:
            conn.close()

    def save_skill_cache(self, skill_name: str, key: str, value: dict) -> None:
        """保存 Skill 缓存 (私有数据)

        Args:
            skill_name: Skill 名称
            key: 缓存键
            value: 缓存值 (JSON 可序列化)

        Example:
            >>> gw.save_skill_cache("network-query", "intent:show bgp", {
            ...     "execution_plan": {"steps": [...]}
            ... })
        """
        # Updated: Use skill.duckdb instead of cache.duckdb
        skill_db = self.skills_dir / skill_name / "skill.duckdb"
        skill_db.parent.mkdir(parents=True, exist_ok=True)

        conn = duckdb.connect(str(skill_db))
        try:
            # Try to save to intent_cache table first
            conn.execute("""
                CREATE TABLE IF NOT EXISTS intent_cache (
                    query_text TEXT PRIMARY KEY,
                    execution_plan JSON,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    hit_count INTEGER DEFAULT 1
                )
            """)

            # Insert or update intent_cache
            import time

            now = time.strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """
                INSERT INTO intent_cache (query_text, execution_plan, last_used) VALUES (?, ?, ?)
                ON CONFLICT (query_text) DO UPDATE SET
                    execution_plan = excluded.execution_plan,
                    last_used = excluded.last_used,
                    hit_count = hit_count + 1
            """,
                [key, json.dumps(value), now],
            )
        finally:
            conn.close()

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
        """保存用户别名学习

        Args:
            skill_name: Skill 名称 (e.g., 'network-query')
            alias: 用户说的词 (如 "核心路由器")
            canonical: 规范名称 (如 "R1,R2,R3")
            type: 类型 ('device', 'site', 'group')

        Example:
            >>> gw.save_user_alias("network-query", "核心路由器", "R1,R2,R3", "device")
        """
        skill_db = self.skills_dir / skill_name / "skill.duckdb"
        skill_db.parent.mkdir(parents=True, exist_ok=True)

        conn = duckdb.connect(str(skill_db))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_aliases (
                    alias TEXT PRIMARY KEY,
                    canonical TEXT,
                    type TEXT,
                    usage_count INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT current_localtimestamp(),
                    last_used TIMESTAMP DEFAULT current_localtimestamp()
                )
            """)
            conn.execute(
                """
                INSERT INTO user_aliases (alias, canonical, type)
                VALUES (?, ?, ?)
                ON CONFLICT (alias) DO UPDATE SET
                    canonical = excluded.canonical,
                    type = excluded.type,
                    usage_count = usage_count + 1,
                    last_used = current_localtimestamp()
            """,
                [alias, canonical, type],
            )
        finally:
            conn.close()

    def get_user_alias(self, skill_name: str, alias: str) -> str | None:
        """获取别名映射

        Args:
            skill_name: Skill 名称
            alias: 用户说的词

        Returns:
            规范名称，未找到返回 None

        Example:
            >>> canonical = gw.get_user_alias("network-query", "核心路由器")
            >>> assert canonical == "R1,R2,R3"
        """
        skill_db = self.skills_dir / skill_name / "skill.duckdb"
        if not skill_db.exists():
            return None

        conn = duckdb.connect(str(skill_db), read_only=True)
        try:
            result = conn.execute(
                "SELECT canonical FROM user_aliases WHERE alias = ?", [alias]
            ).fetchone()
            return result[0] if result else None
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
            skill_name: Skill 名称 (e.g., 'network-analysis')
            symptom: 症状描述
            devices_checked: 检查的设备列表
            commands_used: 执行的命令列表
            root_cause: 根因分析
            solution: 解决方案
            snapshot_id: 快照 ID (可选)

        Example:
            >>> gw.save_diagnosis_case(
            ...     "network-analysis",
            ...     "BGP neighbor down",
            ...     ["R1", "R2"],
            ...     ["show ip bgp summary", "show interface"],
            ...     "MTU mismatch",
            ...     "Set MTU to 1500"
            ... )
        """
        import json

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
            >>> cases = gw.search_similar_cases("network-analysis", "BGP")
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
        base_dir: 基础目录路径，默认 .olav

    Returns:
        DataGateway 实例
    """
    import os

    base = Path(base_dir or os.getenv("OLAV_BASE_DIR", ".olav"))
    return DataGateway(base)
