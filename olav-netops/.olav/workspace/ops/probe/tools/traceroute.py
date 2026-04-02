"""Traceroute tool for network path analysis."""

from typing import Optional

from langchain_core.tools import tool


@tool
def traceroute(
    target: str,
    max_hops: int = 30,
    timeout: int = 5,
) -> dict:
    """Trace the network path to a destination.

    Args:
        target: IP address or hostname to trace
        max_hops: Maximum number of hops (default: 30)
        timeout: Timeout per hop in seconds (default: 5)

    Returns:
        dict with status, hops list, and output details
    """
    import platform
    import re
    import subprocess

    system = platform.system().lower()

    if system == "windows":
        cmd = ["tracert", "-h", str(max_hops), "-w", str(timeout * 1000), target]
    elif system == "darwin":
        cmd = ["traceroute", "-m", str(max_hops), "-w", str(timeout), target]
    else:
        # Linux: prefer traceroute, fall back to tracepath
        import shutil
        if shutil.which("traceroute"):
            cmd = ["traceroute", "-m", str(max_hops), "-w", str(timeout), target]
        elif shutil.which("tracepath"):
            cmd = ["tracepath", "-m", str(max_hops), target]
        else:
            return {
                "status": "error",
                "target": target,
                "error": "No traceroute or tracepath binary found on this system",
            }

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max_hops * timeout + 10,
        )
        output = result.stdout + result.stderr

        # Parse hops — support both traceroute (" 1  host ...") and tracepath (" 1:  host ...")
        hops = []
        for line in output.split("\n"):
            match = re.match(r'^\s*(\d+)[:\s]\s*(.+)$', line)
            if match:
                hop_data = match.group(2).strip()
                # Skip tracepath meta-lines like "[LOCALHOST]" and "Resume:"
                if hop_data.startswith('[') or hop_data.startswith('Resume'):
                    continue
                hop_num = int(match.group(1))
                hops.append({"hop": hop_num, "data": hop_data})

        return {
            "status": "success",
            "target": target,
            "hops": hops,
            "hop_count": len(hops),
            "output": output,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "target": target,
            "error": f"Traceroute timeout after {max_hops * timeout + 10} seconds",
        }
    except Exception as e:
        return {
            "status": "error",
            "target": target,
            "error": str(e),
        }
