"""Ping device tool for network reachability testing."""

from typing import Optional

from langchain_core.tools import tool


@tool
def ping_device(
    target: str,
    count: int = 4,
    timeout: int = 5,
    device: Optional[str] = None,
) -> dict:
    """Ping a target device to check network reachability and measure latency.

    Args:
        target: IP address or hostname to ping
        count: Number of ping packets to send (default: 4)
        timeout: Timeout in seconds (default: 5)
        device: Optional source device to ping from (for network-specific testing)

    Returns:
        dict with status, rtt_avg, packet_loss, and output details
    """
    import subprocess
    import re

    # Build ping command based on OS
    import platform

    system = platform.system().lower()

    if system == "windows":
        cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), target]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout), target]

    # If device specified, we would need to SSH to that device
    # For now, execute locally
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout * count + 5,
        )
        output = result.stdout + result.stderr

        # Parse results
        packet_loss = 100
        rtt_avg = None

        # Parse packet loss
        loss_match = re.search(r"(\d+)% packet loss", output)
        if loss_match:
            packet_loss = int(loss_match.group(1))

        # Parse RTT (Linux/macOS)
        rtt_match = re.search(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", output)
        if rtt_match:
            rtt_avg = float(rtt_match.group(2))

        # Parse RTT (Windows)
        rtt_match_win = re.search(r"Average = (\d+)ms", output)
        if rtt_match_win:
            rtt_avg = float(rtt_match_win.group(1))

        return {
            "status": "success" if packet_loss < 100 else "unreachable",
            "target": target,
            "packet_loss": packet_loss,
            "rtt_avg_ms": rtt_avg,
            "output": output,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "target": target,
            "error": f"Ping timeout after {timeout * count + 5} seconds",
        }
    except Exception as e:
        return {
            "status": "error",
            "target": target,
            "error": str(e),
        }
