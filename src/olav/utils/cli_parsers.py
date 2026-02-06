"""CLI text parsers for inspection.

Parse raw CLI output from raw_outputs table to extract metrics.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def parse_version(output: str) -> dict[str, Any]:
    """Parse 'show version' output.
    
    Extract: version, uptime, hostname, serial
    """
    result = {}
    
    # Cisco IOS version
    version_match = re.search(r"(?:Version|IOS XE Software, Version)\s+([^\s,]+)", output)
    if version_match:
        result["version"] = version_match.group(1)
    
    # Uptime
    uptime_match = re.search(r"uptime is (.+?)(?:\n|$)", output)
    if uptime_match:
        result["uptime"] = uptime_match.group(1).strip()
    
    # Hostname (from first line or prompt)
    hostname_match = re.search(r"^(\S+)\s+uptime", output, re.MULTILINE)
    if hostname_match:
        result["hostname"] = hostname_match.group(1)
    
    return result


def parse_cpu(output: str) -> dict[str, Any]:
    """Parse 'show processes cpu' output.
    
    Extract: cpu_5sec, cpu_1min, cpu_5min
    """
    result = {}
    
    # CPU utilization for five seconds: 0%/0%; one minute: 1%; five minutes: 0%
    cpu_match = re.search(
        r"CPU utilization for five seconds:\s*(\d+)%.*?one minute:\s*(\d+)%.*?five minutes:\s*(\d+)%",
        output
    )
    if cpu_match:
        result["cpu_5sec"] = float(cpu_match.group(1))
        result["cpu_1min"] = float(cpu_match.group(2))
        result["cpu_5min"] = float(cpu_match.group(3))
    
    return result


def parse_memory(output: str) -> dict[str, Any]:
    """Parse 'show processes memory' output.
    
    Extract: memory_total, memory_used, memory_free, memory_used_percent
    """
    result = {}
    
    # Processor Pool Total:  2094620960 Used:   177537568 Free:  1917083392
    mem_match = re.search(
        r"Processor.*?Total:\s*(\d+)\s+Used:\s*(\d+)\s+Free:\s*(\d+)",
        output
    )
    if mem_match:
        total = int(mem_match.group(1))
        used = int(mem_match.group(2))
        free = int(mem_match.group(3))
        
        result["memory_total"] = total
        result["memory_used"] = used
        result["memory_free"] = free
        if total > 0:
            result["memory_used_percent"] = round((used / total) * 100, 2)
    
    return result


def parse_interfaces(output: str) -> list[dict[str, Any]]:
    """Parse 'show ip interface brief' output.
    
    Extract interfaces with: interface, ip_address, status, protocol
    """
    interfaces = []
    
    for line in output.split("\n"):
        # GigabitEthernet1       10.1.12.1       YES NVRAM  up                    up
        match = re.match(
            r"^(\S+)\s+([\d.]+|unassigned)\s+\S+\s+\S+\s+(\w+)\s+(\w+)",
            line.strip()
        )
        if match:
            interfaces.append({
                "interface": match.group(1),
                "ip_address": match.group(2) if match.group(2) != "unassigned" else None,
                "status": match.group(3),
                "protocol": match.group(4),
            })
    
    return interfaces


def parse_ospf_neighbors(output: str) -> list[dict[str, Any]]:
    """Parse 'show ip ospf neighbor' output.
    
    Extract: neighbor_id, state, interface
    """
    neighbors = []
    
    for line in output.split("\n"):
        # 2.2.2.2         1   FULL/  -        00:00:31    10.1.12.2       GigabitEthernet1
        match = re.match(
            r"^([\d.]+)\s+\d+\s+(\w+)/\S*\s+[\d:]+\s+([\d.]+)\s+(\S+)",
            line.strip()
        )
        if match:
            neighbors.append({
                "neighbor_id": match.group(1),
                "state": match.group(2),
                "neighbor_ip": match.group(3),
                "interface": match.group(4),
            })
    
    return neighbors


def parse_bgp_neighbors(output: str) -> list[dict[str, Any]]:
    """Parse 'show ip bgp summary' output.
    
    Extract: neighbor, as_number, state_prefixes
    """
    neighbors = []
    
    lines = output.split("\n")
    for line in lines:
        # 10.1.23.3       4      65003      28   28   28    0    0 00:14:23        5
        match = re.match(
            r"^([\d.]+)\s+\d+\s+(\d+)\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+([\d:]+)\s+(\d+)",
            line.strip()
        )
        if match:
            neighbors.append({
                "neighbor": match.group(1),
                "as_number": match.group(2),
                "uptime": match.group(3),
                "prefixes_received": int(match.group(4)),
            })
    
    return neighbors


def parse_cdp_neighbors(output: str) -> list[dict[str, Any]]:
    """Parse 'show cdp neighbors' output.
    
    Extract: device_id, local_interface, remote_interface, platform
    """
    neighbors = []
    
    for line in output.split("\n"):
        # R2       Gig 1              150    R S I      ISR4321   Gig 1
        match = re.match(
            r"^(\S+)\s+(\S+\s+\S+)\s+\d+\s+\S+\s+\S+\s+(\S+\s+\S+)",
            line.strip()
        )
        if match:
            neighbors.append({
                "device_id": match.group(1),
                "local_interface": match.group(2),
                "remote_interface": match.group(3),
            })
    
    return neighbors


# Parser registry
PARSERS = {
    "show version": parse_version,
    "show processes cpu": parse_cpu,
    "show processes memory": parse_memory,
    "show ip interface brief": parse_interfaces,
    "show ip ospf neighbor": parse_ospf_neighbors,
    "show ip bgp summary": parse_bgp_neighbors,
    "show cdp neighbors": parse_cdp_neighbors,
}


def parse_command_output(command: str, output: str) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Parse command output using registered parser.
    
    Args:
        command: Command name (e.g., 'show version')
        output: Raw CLI output text
        
    Returns:
        Parsed data (dict or list of dicts), or None if no parser available
    """
    parser = PARSERS.get(command)
    if not parser:
        return None
    
    try:
        return parser(output)
    except Exception as e:
        logger.warning(f"Failed to parse '{command}': {e}")
        return None
