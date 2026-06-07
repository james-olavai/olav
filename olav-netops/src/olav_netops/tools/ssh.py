"""olav_netops.tools.ssh — SSH command execution via Nornir (platform-agnostic).

Core SSH execution logic used by the `execute_cli` workspace tool.
Can be used standalone::

    from olav_netops.tools.ssh import execute_on_device, parallel_collect

    result = execute_on_device("R1", "show version")
    results = parallel_collect(["R1", "R2"], ["show version", "show interfaces"])
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _resolve_nornir_config() -> Path:
    """Find the Nornir config.yaml path."""
    try:
        from olav_netops.core.config_paths import resolve_nornir_config_path
        return resolve_nornir_config_path()
    except Exception:
        # Fallback: search common locations
        candidates = [
            Path(".olav/workspace/netops/collector/config/nornir/config.yaml"),
            Path(".olav/workspace/netops/collect/config/nornir/config.yaml"),  # pre-rename fallback
            Path(".olav/workspace/netops/probe/config/nornir/config.yaml"),
            Path("nornir/config.yaml"),
        ]
        for c in candidates:
            if c.exists():
                return c
        raise FileNotFoundError("Nornir config.yaml not found")


def execute_on_device(
    device: str,
    command: str,
    platform: str | None = None,
    timeout: int = 60,
    nornir_config: str | Path | None = None,
) -> dict[str, Any]:
    """Execute a single CLI command on a network device via SSH.

    Args:
        device: Device hostname (must exist in Nornir inventory).
        command: CLI command to execute.
        platform: Override device platform (optional).
        timeout: Command timeout in seconds.
        nornir_config: Path to Nornir config.yaml. Auto-resolved if None.

    Returns:
        Dict with keys: device, command, raw_output, status, error (if any).

    Example::

        from olav_netops.tools.ssh import execute_on_device
        result = execute_on_device("R1", "show version")
        print(result["raw_output"])
    """
    from nornir import InitNornir
    from nornir_netmiko.tasks import netmiko_send_command

    cfg_path = str(nornir_config or _resolve_nornir_config())
    nr = InitNornir(config_file=cfg_path, logging={"enabled": False})
    try:
        target = nr.filter(filter_func=lambda h: h.name == device)
        if not target.inventory.hosts:
            return {"device": device, "command": command, "status": "error",
                    "error": f"Device '{device}' not found in Nornir inventory"}

        result = target.run(task=netmiko_send_command, command_string=command)

        for host, multi in result.items():
            if multi.failed:
                return {"device": host, "command": command, "status": "error",
                        "error": str(multi.exception)[:200]}
            return {"device": host, "command": command, "status": "success",
                    "raw_output": multi[0].result or ""}

        return {"device": device, "command": command, "status": "error",
                "error": "No result returned"}
    finally:
        nr.close_connections()


def parallel_collect(
    devices: list[str],
    commands: list[str],
    nornir_config: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Execute commands on multiple devices in parallel.

    Args:
        devices: List of device hostnames.
        commands: List of CLI commands to execute on each device.
        nornir_config: Path to Nornir config.yaml.

    Returns:
        List of result dicts (one per device-command pair).

    Example::

        from olav_netops.tools.ssh import parallel_collect
        results = parallel_collect(["R1", "R2"], ["show version", "show interfaces"])
        for r in results:
            print(f"{r['device']} {r['command']}: {r['status']}")
    """
    from nornir import InitNornir
    from nornir_netmiko.tasks import netmiko_send_command

    cfg_path = str(nornir_config or _resolve_nornir_config())
    nr = InitNornir(config_file=cfg_path, logging={"enabled": False})
    try:
        target = nr.filter(filter_func=lambda h: h.name in devices)
        results = []

        for cmd in commands:
            nornir_result = target.run(task=netmiko_send_command, command_string=cmd)
            for host, multi in nornir_result.items():
                if multi.failed:
                    results.append({"device": host, "command": cmd, "status": "error",
                                    "error": str(multi.exception)[:200]})
                else:
                    results.append({"device": host, "command": cmd, "status": "success",
                                    "raw_output": multi[0].result or ""})

        return results
    finally:
        nr.close_connections()
