import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class SandboxExecutor:
    def __init__(self, sandbox_type: str = "none"):
        self.sandbox_type = sandbox_type

    def execute(self, code: str, timeout: int = 30) -> dict:
        if self.sandbox_type == "none":
            return self._execute_local(code, timeout)

        logger.warning(f"Sandbox type {self.sandbox_type} not implemented, using local execution")
        return self._execute_local(code, timeout)

    def _execute_local(self, code: str, timeout: int) -> dict:
        import tempfile
        import uuid

        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / f"script_{uuid.uuid4().hex[:8]}.py"
            script_path.write_text(code)

            try:
                result = subprocess.run(
                    ["python3", str(script_path)],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )

                return {
                    "success": result.returncode == 0,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                }
            except subprocess.TimeoutExpired:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"Execution timeout after {timeout}s",
                    "returncode": -1,
                }
            except Exception as e:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": str(e),
                    "returncode": -1,
                }


def execute_in_sandbox(code: str, sandbox_type: str = "none", timeout: int = 30) -> dict:
    executor = SandboxExecutor(sandbox_type=sandbox_type)
    return executor.execute(code, timeout)
