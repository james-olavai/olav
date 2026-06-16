"""
base.py — Execution Backend Protocol

统一的命令执行抽象层，支持 local / SSH 后端无缝切换。
服务注册（M4）和 ops/lab、ops/probe 工具通过此协议调用底层执行引擎。

参考: dev_docs/30. HERMES_ANALYSIS.md §3.1, dev_docs/archive/19. SERVICE_REGISTRY_DESIGN.md §7.1
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ExecutionResult:
    """命令执行结果（不可变值对象）。"""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        """Return True if the command exited with code 0."""
        return self.returncode == 0

    @property
    def output(self) -> str:
        """Convenience: stdout if success, stderr if failure."""
        return self.stdout if self.ok else self.stderr

    def __str__(self) -> str:
        status = "ok" if self.ok else f"exit={self.returncode}"
        preview = (self.stdout or self.stderr)[:80].replace("\n", "↵")
        return f"ExecutionResult({status}, {preview!r})"


@dataclass
class ExecutionConfig:
    """命令执行的可选配置（超时、工作目录、环境变量等）。"""

    timeout: int = 30
    """命令超时秒数（默认 30 秒）。"""

    cwd: str | None = None
    """工作目录；None 表示使用后端默认。"""

    env: dict[str, str] = field(default_factory=dict)
    """额外环境变量（在现有环境之上叠加）。"""

    shell: bool = False
    """是否通过 shell 执行（True 时 command 按 shell 语法解析）。"""


@runtime_checkable
class ExecutionBackend(Protocol):
    """执行后端 Protocol — 所有后端必须实现此接口。

    实现类: LocalBackend, SSHBackend, DockerComposeBackend (M5)

    Example::

        backend: ExecutionBackend = LocalBackend()
        result = backend.execute("echo hello")
        assert result.ok
        assert "hello" in result.stdout
    """

    def execute(
        self,
        command: str,
        config: ExecutionConfig | None = None,
    ) -> ExecutionResult:
        """执行命令并返回结果。

        Args:
            command:  要执行的命令字符串
            config:   可选执行配置（超时、工作目录等）

        Returns:
            ExecutionResult 包含 returncode/stdout/stderr
        """
        ...

    def is_available(self) -> bool:
        """检查后端是否可用（连接正常、工具存在等）。

        Returns:
            True 表示可以接受执行请求
        """
        ...


def split_command(command: str, shell: bool = False) -> list[str] | str:
    """将命令字符串拆分为 subprocess 参数列表（或保持字符串用于 shell=True）。"""
    if shell:
        return command
    return shlex.split(command)
