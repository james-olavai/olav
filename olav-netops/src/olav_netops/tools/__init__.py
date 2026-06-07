"""olav_netops.tools — Network operations tool implementations (platform-agnostic).

This package contains the core business logic for all NetOps tools.
OLAV workspace `@tool` wrappers delegate to functions here.

Usage without OLAV workspace::

    from olav_netops.tools.ssh import execute_on_device
    result = execute_on_device("R1", "show version", platform="cisco_ios")

    from olav_netops.tools.snapshot import collect_snapshot
    snap = collect_snapshot(devices=["R1", "R2"], commands=["show version"])

    from olav_netops.tools.textfsm_parse import parse_output
    parsed = parse_output("cisco_ios", "show version", raw_text)
"""
