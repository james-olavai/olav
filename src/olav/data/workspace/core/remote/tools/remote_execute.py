"""remote_execute — Execute commands on remote hosts via SSH.

Uses the platform SSHBackend (system ssh command). No nornir/netmiko dependency.
For network-device-specific CLI execution, use ops agent's execute_cli instead.

Requires SSH key authentication to the target host.
"""
from __future__ import annotations

from langchain_core.tools import tool


@tool
def remote_execute(
    host: str,
    command: str,
    user: str = "",
    timeout: int = 30,
) -> dict:
    """Execute a command on a remote host via SSH.

    Uses system SSH — requires key-based authentication (no password prompt).
    For network device CLI (Cisco/Juniper/etc.), use the ops agent instead.

    Args:
        host: Remote hostname or IP address.
        command: Shell command to execute (e.g. "df -h", "docker ps", "systemctl status nginx").
        user: SSH username. If empty, uses system default (~/.ssh/config or current user).
        timeout: Command timeout in seconds (default 30).

    Returns:
        Dict with stdout, stderr, returncode.

    Examples:
        >>> remote_execute(host="server1", command="df -h")
        >>> remote_execute(host="192.168.1.10", command="docker ps", user="admin")
        >>> remote_execute(host="db-server", command="pg_isready")
    """
    from olav.platform.execution import SSHBackend, ExecutionConfig

    backend = SSHBackend(host=host, user=user or None)
    config = ExecutionConfig(timeout=timeout)
    result = backend.execute(command, config)

    return {
        "host": host,
        "command": command,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "status": "success" if result.returncode == 0 else "error",
    }
