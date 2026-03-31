"""
local.py — 本地执行后端

通过 subprocess 在本机直接执行命令。
是最低延迟的后端，适合 ops-probe 和本地 ContainerLab 场景。

参考: dev_docs/15. hermes.md §3.1
"""

from __future__ import annotations

import logging
import os
import subprocess

from olav.platform.execution.base import (
    ExecutionBackend,
    ExecutionConfig,
    ExecutionResult,
    split_command,
)

logger = logging.getLogger(__name__)


class LocalBackend:
    """在本地进程中执行命令。

    Example::

        backend = LocalBackend()
        result = backend.execute("echo hello", ExecutionConfig(timeout=5))
        assert result.ok
        assert result.stdout.strip() == "hello"
    """

    def execute(
        self,
        command: str,
        config: ExecutionConfig | None = None,
    ) -> ExecutionResult:
        cfg = config or ExecutionConfig()
        cmd = split_command(command, shell=cfg.shell)

        env = None
        if cfg.env:
            env = {**os.environ, **cfg.env}

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=cfg.timeout,
                cwd=cfg.cwd,
                env=env,
                shell=cfg.shell,
            )
            return ExecutionResult(
                returncode=proc.returncode,
                stdout=proc.stdout.decode(errors="replace"),
                stderr=proc.stderr.decode(errors="replace"),
            )
        except subprocess.TimeoutExpired:
            logger.warning("LocalBackend: command timed out after %ds: %s", cfg.timeout, command)
            return ExecutionResult(
                returncode=124,
                stdout="",
                stderr=f"Command timed out after {cfg.timeout}s",
            )
        except FileNotFoundError as e:
            return ExecutionResult(returncode=127, stdout="", stderr=str(e))
        except Exception as e:
            logger.error("LocalBackend: unexpected error: %s", e)
            return ExecutionResult(returncode=1, stdout="", stderr=str(e))

    def is_available(self) -> bool:
        """Local backend is always available."""
        return True


# 确认类型检查
assert isinstance(LocalBackend(), ExecutionBackend)
