"""Port scanning tool for service discovery."""

from typing import List, Optional

from langchain_core.tools import tool


@tool
def port_scan(
    target: str,
    ports: str = "22,23,80,443,3389,8080",
    timeout: int = 3,
) -> dict:
    """Scan target ports to identify open services.

    Args:
        target: IP address or hostname to scan
        ports: Comma-separated port numbers or ranges (default: common ports)
        timeout: Connection timeout per port in seconds (default: 3)

    Returns:
        dict with status, open_ports, and scan results
    """
    import socket

    # Parse ports
    port_list: List[int] = []
    for part in ports.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-")
            port_list.extend(range(int(start), int(end) + 1))
        else:
            port_list.append(int(part))

    open_ports = []
    closed_ports = []

    for port in port_list:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        try:
            result = sock.connect_ex((target, port))
            if result == 0:
                open_ports.append(port)
            else:
                closed_ports.append(port)
        except socket.timeout:
            closed_ports.append(port)
        except socket.error:
            closed_ports.append(port)
        finally:
            sock.close()

    # Map common ports to services
    port_services = {
        21: "ftp",
        22: "ssh",
        23: "telnet",
        25: "smtp",
        53: "dns",
        80: "http",
        110: "pop3",
        143: "imap",
        443: "https",
        445: "smb",
        3306: "mysql",
        3389: "rdp",
        5432: "postgres",
        8080: "http-alt",
        8443: "https-alt",
    }

    services = []
    for port in open_ports:
        services.append(
            {
                "port": port,
                "service": port_services.get(port, "unknown"),
            }
        )

    return {
        "status": "success",
        "target": target,
        "ports_scanned": len(port_list),
        "open_ports": open_ports,
        "services": services,
        "closed_count": len(closed_ports),
    }
