"""
LLM Experiment Sandbox - 完全隔离的LLM自由实验环境

允许LLM在严格隔离的沙箱中：
- 自由编写Python代码
- 查询生产数据库（只读）
- 执行网络仿真
- 执行CLI命令并解析
- 创建和迭代实验

核心原则：
1. 不受预定义模板限制
2. 完整的编程自由度
3. 严格的安全隔离（只读数据库，子进程执行）
4. 完整的执行审计和可重复性
"""

import asyncio
import json
import logging
import os
import subprocess
import tempfile
import traceback
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Template injected textually into every subprocess script — no serialization needed.
# Uses __DB_PATH__ placeholder replaced by _execute_subprocess at runtime.
_SIM_PROXY_TEMPLATE = r'''
import duckdb as _duckdb

class SimulationProxy:
    """Writable in-memory DuckDB, populated on demand by the LLM."""
    def __init__(self, db_path):
        self._db_path = db_path
        self._conn = None

    def _ensure_conn(self):
        if self._conn is None:
            self._conn = _duckdb.connect(":memory:")
            self._conn.execute("ATTACH '" + self._db_path + "' AS prod_db (READ_ONLY);")

    def clone(self, tables):
        """Clone prod tables into sim_<table>. Idempotent."""
        self._ensure_conn()
        for table in tables:
            sim_name = "sim_" + table
            exists = self._conn.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
                [sim_name]
            ).fetchone()[0]
            if not exists:
                self._conn.execute(
                    "CREATE TABLE " + sim_name + " AS SELECT * FROM prod_db." + table + ";"
                )

    def execute(self, sql, params=None):
        """Parameterized SQL against the writable in-memory sim DB."""
        self._ensure_conn()
        return self._conn.execute(sql, params) if params else self._conn.execute(sql)

sim = SimulationProxy(r"__DB_PATH__")
'''


@dataclass
class SandboxExecutionResult:
    """沙箱执行结果"""

    status: str  # "success" or "error"
    result: Any | None = None
    error: str | None = None
    error_trace: str | None = None
    execution_time: float = 0.0
    artifacts: dict[str, Path] | None = None

    def to_dict(self) -> dict:
        """转换为字典（artifacts转为字符串）"""
        data = asdict(self)
        if self.artifacts:
            data["artifacts"] = {k: str(v) for k, v in self.artifacts.items()}
        return data


@dataclass
class ExecutionTrace:
    """记录每次实验执行"""

    experiment_id: str
    timestamp: datetime
    code: str
    result: SandboxExecutionResult
    metadata: dict[str, Any]


class SandboxEnvironment:
    """LLM代码执行的隔离环境"""

    def __init__(
        self,
        sandbox_id: str,
        db_interface: "DatabaseInterface",
        cli_executor: "CLIExecutor",
        simulator_engine: "SimulatorEngine",
        work_dir: str | None = None,
        db_path: Path | None = None,
    ):
        self.sandbox_id = sandbox_id
        self.db = db_interface
        self.cli = cli_executor
        self.simulator = simulator_engine
        self.db_path = db_path
        self.work_dir = Path(work_dir or f"/tmp/ollm_sandbox_{sandbox_id}")
        self.work_dir.mkdir(parents=True, exist_ok=True)

        self.execution_log = []

    async def execute(
        self, code: str, timeout: int = 600, metadata: dict | None = None
    ) -> SandboxExecutionResult:
        """
        在隔离环境中执行LLM生成的Python代码

        Args:
            code: LLM生成的Python代码
            timeout: 执行超时时间（秒，默认10分钟）
            metadata: 执行元数据

        Returns:
            SandboxExecutionResult - 执行结果
        """

        start_time = datetime.now()

        try:
            # 1️⃣ 验证代码安全性（避免明显的危险操作）
            self._validate_code(code)

            # 2️⃣ 准备执行环境
            exec_env = self._prepare_environment()

            # 3️⃣ 在子进程中执行代码（最大隔离）
            result = await asyncio.wait_for(
                self._execute_subprocess(code, exec_env), timeout=timeout
            )

            execution_time = (datetime.now() - start_time).total_seconds()

            # 4️⃣ 记录执行
            exec_result = SandboxExecutionResult(
                status="success",
                result=result,
                execution_time=execution_time,
                artifacts={"work_dir": self.work_dir, "log_file": self.work_dir / "execution.log"},
            )

            self._log_execution(code, exec_result, metadata)

            logger.info(f"[Sandbox {self.sandbox_id}] Execution succeeded ({execution_time:.2f}s)")

            return exec_result

        except TimeoutError:
            execution_time = (datetime.now() - start_time).total_seconds()
            error_msg = f"Execution timeout after {timeout}s"

            exec_result = SandboxExecutionResult(
                status="error", error=error_msg, execution_time=execution_time
            )

            logger.error(f"[Sandbox {self.sandbox_id}] {error_msg}")
            return exec_result

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()

            exec_result = SandboxExecutionResult(
                status="error",
                error=str(e),
                error_trace=traceback.format_exc(),
                execution_time=execution_time,
            )

            logger.error(f"[Sandbox {self.sandbox_id}] Execution failed: {e}", exc_info=True)

            return exec_result

    def _validate_code(self, code: str) -> None:
        """验证代码安全性"""

        dangerous_patterns = [
            "exec(",
            "eval(",
            "__import__",
            "subprocess",
            "os.system",
            "open(",  # 限制文件访问
        ]

        for pattern in dangerous_patterns:
            if pattern in code:
                # 注：某些操作实际是需要的，这里只是示例
                # 在生产环境中应该有更精细的控制
                logger.warning(f"Code contains potentially unsafe pattern: {pattern}")

    def _prepare_environment(self) -> dict[str, Any]:
        """准备代码执行环境"""

        env: dict[str, Any] = {
            # 数据库接口
            "db": self.db,
            # CLI执行器
            "cli": self.cli,
            # 网络仿真器
            "simulator": self.simulator,
            # 内置函数和模块
            "json": json,
            "datetime": __import__("datetime"),
            "math": __import__("math"),
            "itertools": __import__("itertools"),
            "collections": __import__("collections"),
            # 图计算引擎 (Section A — netutils_enhance.md)
            "networkx": __import__("networkx"),
            # 沙箱文件系统
            "file_system": SandboxFileSystem(self.work_dir),
            # 结果变量（LLM代码应该将结果赋值给_result）
            "_result": None,
        }
        # netutils is optional — degrade gracefully if not installed
        try:
            env["netutils"] = __import__("netutils")
        except ImportError:
            logger.warning("netutils not available in sandbox environment")
        return env

    async def _execute_subprocess(self, code: str, env: dict) -> Any:
        """在子进程中执行代码，确保隔离"""

        import json as json_module
        import sys

        # 创建执行脚本
        exec_script = self.work_dir / "exec_script.py"

        # 获取db_path
        db_path_str = str(self.db_path).replace("\\", "\\\\")

        # 准备db_query函数（在子进程中使用）
        db_query_code = f'''
def db_query(sql):
    """在子进程中执行数据库查询（只读）"""
    try:
        import duckdb
        import time
        db_path = r"{db_path_str}"

        # 重试策略：等待父进程释放锁
        max_retries = 5
        for attempt in range(max_retries):
            try:
                # 使用只读连接
                conn = duckdb.connect(str(db_path), read_only=True)
                result = conn.execute(sql)

                # 获取列名
                columns = [desc[0] for desc in result.description] if result.description else []
                rows = result.fetchall()

                conn.close()

                if rows:
                    # 如果没有列名，使用通用列名
                    if not columns:
                        columns = [f"col_{{i}}" for i in range(len(rows[0]))]
                    return [dict(zip(columns, row)) for row in rows]

                return []
            except Exception as e:
                if "lock" in str(e).lower() and attempt < max_retries - 1:
                    time.sleep(0.5)  # 等待后重试
                    continue
                raise

        return []
    except Exception as e:
        return {{"error": str(e), "type": type(e).__name__}}
'''

        # SimulationProxy code — injected textually (Section B — netutils_enhance.md)
        sim_proxy_code = _SIM_PROXY_TEMPLATE.replace("__DB_PATH__", db_path_str)

        # 生成执行代码
        full_code = f"""
import sys
import json
import traceback

# 数据库查询函数
{db_query_code}

# SimulationProxy — writable in-memory sandbox DB (sim.clone / sim.execute)
{sim_proxy_code}

# 图计算引擎与工具库
try:
    import networkx as nx
except ImportError:
    nx = None
try:
    import netutils
except ImportError:
    netutils = None

# 创建db对象（提供query方法）
class DatabaseProxy:
    def query(self, sql):
        return db_query(sql)

db = DatabaseProxy()

# 其他环境
cli = None
simulator = None
datetime = __import__("datetime")
math = __import__("math")
itertools = __import__("itertools")
collections = __import__("collections")

# LLM代码段
_result = None
try:
{self._indent_code(code, 4)}
    result = _result
except Exception as e:
    result = {{"error": str(e), "trace": traceback.format_exc()}}

# 输出结果
print(json.dumps(result, default=str))
"""

        exec_script.write_text(full_code)

        # 在子进程中执行
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(exec_script),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.work_dir),
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode()
            logger.error(f"Subprocess stderr: {error_msg}")
            raise RuntimeError(f"Subprocess failed: {error_msg}")

        # 解析结果
        try:
            result = json_module.loads(stdout.decode())
            return result
        except json_module.JSONDecodeError as e:
            logger.error(f"Failed to parse result: {stdout.decode()}")
            return {"error": f"JSON parse failed: {str(e)}"}

    def _indent_code(self, code: str, spaces: int) -> str:
        """缩进代码"""
        indent = " " * spaces
        return indent + code.replace("\n", f"\n{indent}")

    def _log_execution(
        self, code: str, result: SandboxExecutionResult, metadata: dict | None
    ) -> None:
        """记录执行过程"""

        trace = ExecutionTrace(
            experiment_id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            code=code,
            result=result,
            metadata=metadata or {},
        )

        self.execution_log.append(trace)

        # 保存到文件
        log_file = self.work_dir / "execution.log"
        with open(log_file, "a") as f:
            f.write(f"\n{'=' * 80}\n")
            f.write(f"Timestamp: {trace.timestamp}\n")
            f.write(f"Status: {result.status}\n")
            f.write(f"Code:\n{code}\n")
            if result.error:
                f.write(f"Error: {result.error}\n")
            f.write(f"{'=' * 80}\n")


class SandboxFileSystem:
    """沙箱文件系统，限制文件访问到工作目录"""

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)

    def write(self, filename: str, content: str) -> Path:
        """写文件"""
        file_path = self.work_dir / filename
        # 安全检查：确保路径在work_dir内
        if not str(file_path.resolve()).startswith(str(self.work_dir.resolve())):
            raise PermissionError(f"Access denied: {filename}")

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return file_path

    def read(self, filename: str) -> str:
        """读文件"""
        file_path = self.work_dir / filename
        if not str(file_path.resolve()).startswith(str(self.work_dir.resolve())):
            raise PermissionError(f"Access denied: {filename}")

        return file_path.read_text()

    def list_files(self, pattern: str = "*") -> list[Path]:
        """列出文件"""
        return list(self.work_dir.glob(pattern))


class LLMExperimentSandbox:
    """
    LLM实验沙箱 - 为LLM提供完全隔离的实验环境
    """

    def __init__(self, db_path: str, work_dir: str | None = None):
        self.sandbox_id = str(uuid.uuid4())[:8]
        self.db_path = db_path
        self.base_work_dir = Path(work_dir or f"/tmp/llm_sandbox/{self.sandbox_id}")
        self.base_work_dir.mkdir(parents=True, exist_ok=True)

        # 初始化沙箱工具
        self.db_interface = DatabaseInterface(db_path)
        self.cli_executor = CLIExecutor()
        self.simulator_engine = SimulatorEngine(db_path)

        self.execution_history = []

        logger.info(f"[LLMSandbox {self.sandbox_id}] Initialized")

    async def execute_experiment(
        self,
        experiment_code: str,
        experiment_name: str = "unnamed",
        timeout: int = 600,
        metadata: dict | None = None,
    ) -> SandboxExecutionResult:
        """
        执行一个实验

        Args:
            experiment_code: LLM生成的实验代码
            experiment_name: 实验名称
            timeout: 超时时间
            metadata: 元数据

        Returns:
            SandboxExecutionResult
        """

        # 为每个实验创建独立环境
        exp_work_dir = self.base_work_dir / experiment_name

        sandbox_env = SandboxEnvironment(
            sandbox_id=self.sandbox_id,
            db_interface=self.db_interface,
            cli_executor=self.cli_executor,
            simulator_engine=self.simulator_engine,
            work_dir=str(exp_work_dir),
            db_path=Path(self.db_path),
        )

        # 执行实验
        result = await sandbox_env.execute(code=experiment_code, timeout=timeout, metadata=metadata)

        # 记录到历史
        self.execution_history.append(
            {
                "experiment_name": experiment_name,
                "timestamp": datetime.now(),
                "result": result.to_dict(),
                "work_dir": str(exp_work_dir),
            }
        )

        return result

    def get_execution_history(self) -> list[dict]:
        """获取执行历史"""
        return self.execution_history


class DatabaseInterface:
    """只读数据库接口"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def query(self, sql: str) -> list[dict]:
        """
        执行SQL查询（只读）

        Args:
            sql: SQL查询语句

        Returns:
            查询结果列表
        """
        from olav.core.database import get_database

        try:
            db = get_database()
            results = db.conn.execute(sql).fetchall()

            # 转换为字典列表
            if results:
                # 获取列名
                columns = [desc[0] for desc in db.conn.description]
                return [dict(zip(columns, row, strict=False)) for row in results]
            return []

        except Exception as e:
            logger.error(f"Database query failed: {e}")
            raise


class CLIExecutor:
    """CLI命令执行器"""

    async def execute(self, device: str, command: str, timeout: int = 30) -> dict[str, Any]:
        """
        在设备上执行CLI命令

        Args:
            device: 设备名称
            command: CLI命令
            timeout: 超时时间

        Returns:
            {
                "device": device,
                "command": command,
                "output": raw_output,
                "status": "success" or "error"
            }
        """

        logger.info(f"Executing CLI on {device}: {command}")

        # 这是一个存根实现
        # 实际实现应该使用Nornir或类似的工具
        return {
            "device": device,
            "command": command,
            "output": "(CLI execution not implemented)",
            "status": "success",
        }


class SimulatorEngine:
    """网络仿真引擎"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def simulate(self, scenario: dict[str, Any]) -> dict[str, Any]:
        """
        运行网络仿真

        Args:
            scenario: 仿真场景定义

        Returns:
            仿真结果
        """

        from olav.core.database import get_database
        from olav.core.simulation.engine import NetworkSimulator

        try:
            db = get_database()
            simulator = NetworkSimulator(conn=db.conn)

            # 根据场景类型执行不同的仿真
            scenario_type = scenario.get("type", "unknown")

            if scenario_type == "topology_change":
                # 拓扑变更仿真
                changes = scenario.get("changes", [])
                results = []

                for change in changes:
                    result = simulator.simulate_change(
                        device=change.get("device"), config_delta=change
                    )
                    results.append(result)

                return {"scenario_type": scenario_type, "results": results, "status": "success"}

            elif scenario_type == "impact_analysis":
                # 影响分析
                changes = scenario.get("changes", [])
                impact = simulator.analyze_impact(changes)

                return {"scenario_type": scenario_type, "impact": impact, "status": "success"}

            else:
                return {"status": "error", "message": f"Unknown scenario type: {scenario_type}"}

        except Exception as e:
            logger.error(f"Simulation failed: {e}")
            return {"status": "error", "message": str(e)}
