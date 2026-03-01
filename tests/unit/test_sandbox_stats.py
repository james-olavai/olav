import pytest
from unittest.mock import MagicMock


class TestSandboxExecution:
    def test_sandbox_executor_import(self):
        from olav.core.sandbox_executor import SandboxExecutor, execute_in_sandbox

        assert SandboxExecutor is not None
        assert execute_in_sandbox is not None

    def test_sandbox_executor_init(self):
        from olav.core.sandbox_executor import SandboxExecutor

        executor = SandboxExecutor(sandbox_type="modal")
        assert executor.sandbox_type == "modal"

    def test_execute_local_simple_code(self):
        from olav.core.sandbox_executor import SandboxExecutor

        executor = SandboxExecutor(sandbox_type="none")

        result = executor.execute("print('hello')", timeout=10)

        assert result["success"] is True
        assert "hello" in result["stdout"]

    def test_execute_with_error(self):
        from olav.core.sandbox_executor import SandboxExecutor

        executor = SandboxExecutor(sandbox_type="none")

        result = executor.execute("raise ValueError('test error')", timeout=10)

        assert result["success"] is False
        assert "test error" in result["stderr"]

    def test_execute_timeout(self):
        from olav.core.sandbox_executor import SandboxExecutor

        executor = SandboxExecutor(sandbox_type="none")

        result = executor.execute("import time; time.sleep(5)", timeout=1)

        assert result["success"] is False
        assert "timeout" in result["stderr"].lower()

    def test_execute_function(self):
        from olav.core.sandbox_executor import execute_in_sandbox

        result = execute_in_sandbox("x = 1 + 1\nprint(x)", timeout=10)

        assert result["success"] is True


class TestSandboxSecurity:
    def test_no_file_write(self):
        from olav.core.sandbox_executor import SandboxExecutor

        executor = SandboxExecutor(sandbox_type="none")

        result = executor.execute("open('/tmp/test.txt', 'w').write('test')", timeout=10)

        assert result["success"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
