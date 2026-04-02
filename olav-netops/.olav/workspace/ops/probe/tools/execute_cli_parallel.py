"""Execute CLI commands on multiple devices in parallel."""

from typing import List, Optional

from langchain_core.tools import tool


@tool
def execute_cli_parallel(
    devices: list[str],
    command: str,
    timeout: int = 30,
) -> dict:
    """Execute a CLI command on multiple devices in parallel.

    This tool enables batch operations across multiple network devices
    for efficient probing and data collection.

    Args:
        devices: List of device names or IPs to execute the command on
        command: The CLI command to execute
        timeout: Timeout in seconds (default: 30)

    Returns:
        dict with success count, results per device, and summary
    """
    import concurrent.futures
    import subprocess

    def execute_on_device(device: str) -> dict:
        """Execute command on a single device."""
        try:
            # This would normally use Nornir for network devices
            # For now, simulate with local execution
            result = subprocess.run(
                ["echo", f"Would execute '{command}' on device {device}"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "device": device,
                "status": "success",
                "output": result.stdout,
            }
        except Exception as e:
            return {
                "device": device,
                "status": "error",
                "error": str(e),
            }

    results = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {executor.submit(execute_on_device, d): d for d in devices}
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    success_count = sum(1 for r in results if r["status"] == "success")

    return {
        "status": "success",
        "total_devices": len(devices),
        "successful": success_count,
        "failed": len(devices) - success_count,
        "results": results,
    }
