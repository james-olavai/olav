"""Temporary injection of ContainerLab nodes into OLAV's nornir inventory."""

from __future__ import annotations

from pathlib import Path

import yaml
from models import DeployResult


def inject_hosts(deploy_result: DeployResult, backup: bool = True) -> str:
    """Inject ContainerLab lab nodes into .olav/config/nornir/hosts.yaml.

    Allows OLAV's execute_cli tool to reach lab nodes via their management IPs.
    Returns backup of original file content for restoration.

    Args:
        deploy_result: Deployed lab nodes with management IPs
        backup: If True, saves original to .orig (default True, unused here)

    Returns:
        Original file content (for restore_hosts())
    """
    hosts_file = Path(".olav/config/nornir/hosts.yaml")
    if not hosts_file.exists():
        raise FileNotFoundError(f"Nornir inventory not found: {hosts_file}")

    # Read original
    original_text = hosts_file.read_text(encoding="utf-8")
    original_data = yaml.safe_load(original_text) or {}

    # Build lab node entries (append to existing inventory)
    lab_entries = {}
    for node_name, node_info in deploy_result.nodes.items():
        lab_entries[node_name] = {
            "hostname": node_info.mgmt_cloud_ip,
            "platform": "nokia_srl",  # hardcoded for now (bgp_2node uses SRL)
            "groups": ["lab"],
            "data": {
                "role": "lab_node",
                "site": "containerlab",
            },
        }

    # Merge and update
    updated_data = {**original_data, **lab_entries}

    # Write back as YAML
    hosts_file.write_text(
        yaml.dump(updated_data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )

    print(f"  ✓ injected {len(lab_entries)} lab nodes into {hosts_file.name}")
    return original_text


def restore_hosts(original_content: str) -> None:
    """Restore original nornir inventory from backup.

    Args:
        original_content: The content returned by inject_hosts()
    """
    hosts_file = Path(".olav/config/nornir/hosts.yaml")
    hosts_file.write_text(original_content, encoding="utf-8")
    print(f"  ✓ restored {hosts_file.name} to original state")


def cleanup_hosts(test_run_id: str) -> None:
    """Remove lab data from DuckDB after test completes."""
    import duckdb

    from olav.core.config import MAIN_DB_PATH

    try:
        with duckdb.connect(str(MAIN_DB_PATH)) as conn:
            # Delete test data by snapshot_id
            conn.execute(
                "DELETE FROM netops.parsed_outputs WHERE snapshot_id = ?",
                [test_run_id],
            )
            conn.execute(
                "DELETE FROM netops.topology_links WHERE snapshot_id = ?",
                [test_run_id],
            )
        print(f"  ✓ cleaned up test data (snapshot_id={test_run_id})")
    except Exception as exc:
        print(f"  ⚠ cleanup failed (non-fatal): {exc}")
