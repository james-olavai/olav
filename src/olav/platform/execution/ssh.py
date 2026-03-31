"""
ssh.py — SSH 远程执行后端

通过系统 ssh 客户端在远程主机上执行命令。
用于 ops-lab 场景（ContainerLab 宿主机上的特权操作）和
ops-probe 场景（在远端节点执行诊断命令）。

不依赖 paramiko，使用系统 ssh —— 在有 ~/.ssh/config 和密钥的环境中零配置。

参考: dev_docs/15. hermes.md §3.1, dev_docs/16. SERVICE_REGISTRY_DESIGN.md §7.1
"""

from __future__ import annotations

import logging
import subprocess

from olav.platform.execution.base import (
    ExecutionBackend,
    ExecutionConfig,
    ExecutionResult,
)

logger = logging.getLogger(__name__)

# ssh 连接选项（禁用 host key 交互提示，适合自动化）
_SSH_BASE_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=10",
]


class SSHBackend:
    """通过 ssh 在远程主机上执行命令。

    Args:
        host:     远程主机名或 IP
        user:     SSH 用户名（默认使用系统默认）
        port:     SSH 端口（默认 22）
        key_file: 私钥路径（None 表示使用 ssh-agent 或默认密钥）

    Example::

        backend = SSHBackend(host="192.168.100.12", user="olav")
        result = backend.execute("docker ps")
        if result.ok:
            print(result.stdout)
    """

    def __init__(
        self,
        host: str,
        user: str | None = None,
        port: int = 22,
        key_file: str | None = None,
    ) -> None:
        self.host = host
        self.user = user
        self.port = port
        self.key_file = key_file

    def _build_ssh_cmd(self, remote_command: str, config: ExecutionConfig) -> list[str]:
        """构建完整的 ssh 命令列表。"""
        cmd: list[str] = ["ssh"]
        cmd.extend(_SSH_BASE_OPTS)

        if self.port != 22:
            cmd.extend(["-p", str(self.port)])

        if self.key_file:
            cmd.extend(["-i", self.key_file])

        target = f"{self.user}@{self.host}" if self.user else self.host
        cmd.append(target)

        # 传递环境变量（通过 env VAR=value cmd 前缀）
        if config.env:
            env_prefix = " ".join(f"{k}={v!r}" for k, v in config.env.items())
            remote_command = f"{env_prefix} {remote_command}"

        # cwd 支持（在远端 cd 后执行）
        if config.cwd:
            remote_command = f"cd {config.cwd!r} && {remote_command}"

        cmd.append(remote_command)
        return cmd

    def execute(
        self,
        command: str,
        config: ExecutionConfig | None = None,
    ) -> ExecutionResult:
        cfg = config or ExecutionConfig()
        ssh_cmd = self._build_ssh_cmd(command, cfg)

        logger.debug("SSHBackend: %s@%s $ %s", self.user or "", self.host, command)

        try:
            proc = subprocess.run(
                ssh_cmd,
                capture_output=True,
                timeout=cfg.timeout,
            )
            return ExecutionResult(
                returncode=proc.returncode,
                stdout=proc.stdout.decode(errors="replace"),
                stderr=proc.stderr.decode(errors="replace"),
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "SSHBackend: command timed out after %ds on %s: %s",
                cfg.timeout, self.host, command,
            )
            return ExecutionResult(
                returncode=124,
                stdout="",
                stderr=f"SSH command timed out after {cfg.timeout}s on {self.host}",
            )
        except FileNotFoundError:
            return ExecutionResult(
                returncode=127,
                stdout="",
                stderr="ssh binary not found — is OpenSSH client installed?",
            )
        except Exception as e:
            logger.error("SSHBackend: unexpected error on %s: %s", self.host, e)
            return ExecutionResult(returncode=1, stdout="", stderr=str(e))

    def is_available(self) -> bool:
        """快速探测 SSH 连通性（无命令执行，仅测试连接）。"""
        result = self.execute("true", ExecutionConfig(timeout=5))
        return result.ok

    def __repr__(self) -> str:
        user_str = f"{self.user}@" if self.user else ""
        return f"SSHBackend({user_str}{self.host}:{self.port})"


# 确认类型检查
assert isinstance(SSHBackend(host="localhost"), ExecutionBackend)
