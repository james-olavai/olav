"""
olav.platform.execution — 命令执行后端抽象层

提供统一接口在不同环境中执行命令，无需修改上层工具代码。

支持的后端:
  - LocalBackend:        本地 subprocess 执行（默认）
  - SSHBackend:          远程 SSH 执行（ContainerLab 宿主机等）
  - DockerComposeBackend: Docker Compose 生命周期管理（M5）
"""

from olav.platform.execution.base import (
    ExecutionBackend,
    ExecutionConfig,
    ExecutionResult,
)
from olav.platform.execution.local import LocalBackend
from olav.platform.execution.ssh import SSHBackend

__all__ = [
    "ExecutionBackend",
    "ExecutionConfig",
    "ExecutionResult",
    "LocalBackend",
    "SSHBackend",
]
