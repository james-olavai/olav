"""collect_exec.py — Schema-aware CLI collection via ContainerLab exec API.

Architecture:
    ContainerLab exec API  (POST /api/v1/labs/{lab}/exec)
        ↓ raw CLI stdout per node per command
    Store raw text as [{"raw_text": stdout}] in parsed_data
        ↓
    {device}.staging.json  (IngestManager schema)
        ↓
    DuckDB INSERT (same SQL as IngestManager.bulk_load)
        ↓
    test_{run_id}.duckdb  netops.parsed_outputs + topology_links

Constraints:
    - No direct import of src/olav/* modules
    - staging.json must match IngestManager schema exactly:
        [{device_name, command, parsed_data, snapshot_id, raw_output}]
    - Must use ON CONFLICT upsert — safe to re-run after partial failure
    - topology_links inserted from plan.links
    - staging files written to evidence_dir/staging/

Usage:
    import asyncio
    from collect_exec import collect_exec
    ok = asyncio.run(collect_exec(deploy_result, plan, db_path=".olav/databases/test_xyz.duckdb"))
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_HERE = Path(__file__).parent.resolve()
_SKILL_ROOT = _HERE.parent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Platform CLI invocation registry
# ---------------------------------------------------------------------------

_PLATFORM_CLI: dict[str, str] = {
    "srl":            "bash -c 'echo \"{cmd}\" | sr_cli 2>/dev/null; true'",
    "nokia_srl":      "bash -c 'echo \"{cmd}\" | sr_cli 2>/dev/null; true'",
    "arista_eos":     'Cli -c "{cmd}"',
    "arista_ceos":    'Cli -c "{cmd}"',
    "cisco_ios":      "bash -c '{cmd} 2>/dev/null'",
    "cisco_iol":      "bash -c '{cmd} 2>/dev/null'",
    "cisco_iosxe":    "bash -c '{cmd} 2>/dev/null'",
    "cisco_iosxr":    "bash -c '{cmd} 2>/dev/null'",
    "juniper_junos":  "bash -c '{cmd} 2>/dev/null'",
}


def _build_exec_cmd(platform: str, cmd: str) -> str:
    """Build the platform-specific exec command string."""
    key = platform.lower().replace("-", "_").replace(" ", "_")
    # Try exact match, then prefix matches
    template = _PLATFORM_CLI.get(key)
    if template is None:
        for k, tmpl in _PLATFORM_CLI.items():
            if key.startswith(k) or k.startswith(key.split("_")[0]):
                template = tmpl
                break
    if template is None:
        # Generic fallback: bare bash
        template = "bash -c '{cmd} 2>/dev/null'"
    return template.replace("{cmd}", cmd)


# ---------------------------------------------------------------------------
# Platform → command list
# ---------------------------------------------------------------------------

def _get_commands_for_platform(platform: str) -> list[str]:
    """Return command list for the platform, reading from config/clab.yaml."""
    try:
        from models import get_config
        cfg = get_config()
        cmds = cfg.get("collection", {}).get("commands", {})
        key = platform.lower().replace("-", "_").replace(" ", "_")
        for candidate in (key, key.split("_")[-1], key.replace("nokia_", "")):
            if candidate in cmds:
                return cmds[candidate]
    except Exception:
        pass

    if "srl" in platform.lower() or "nokia" in platform.lower():
        return [
            "show network-instance default protocols bgp neighbor",
            "show network-instance default route-table",
            "show system lldp neighbor",
        ]
    if "eos" in platform.lower() or "arista" in platform.lower():
        return [
            "show ip bgp summary",
            "show ip route",
            "show lldp neighbors detail",
        ]
    if "xr" in platform.lower():
        return ["show bgp summary", "show route", "show ospf neighbor detail"]
    if "ios" in platform.lower() or "cisco" in platform.lower():
        return [
            "show ip bgp summary",
            "show ip route",
            "show ip ospf neighbor detail",
            "show lldp neighbors detail",
        ]
    if "junos" in platform.lower() or "juniper" in platform.lower():
        return ["show bgp summary", "show route", "show ospf neighbor detail"]

    return ["show version"]


# ---------------------------------------------------------------------------
# Topology links from plan
# ---------------------------------------------------------------------------

def _insert_topology_links(
    con,
    plan_links: list[Any],
    plan_nodes: dict[str, Any],
    snapshot_id: str,
) -> int:
    """Insert topology links from ExecutionPlan into topology_links table."""
    rows = 0
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS topology_links (
                source_device VARCHAR,
                destination_device VARCHAR,
                source_interface VARCHAR,
                destination_interface VARCHAR,
                discovery_protocol VARCHAR DEFAULT 'clab_topology',
                link_type VARCHAR DEFAULT 'L3',
                snapshot_id VARCHAR,
                PRIMARY KEY (source_device, destination_device, source_interface, snapshot_id)
            )
        """)
    except Exception:
        pass  # table exists

    for link in plan_links:
        eps = getattr(link, "endpoints", None) or link.get("endpoints", [])
        if len(eps) < 2:
            continue

        def _split(ep: str):
            parts = ep.split(":")
            return parts[0], parts[1] if len(parts) > 1 else "eth1"

        src_node, src_iface = _split(str(eps[0]))
        dst_node, dst_iface = _split(str(eps[1]))
        try:
            con.execute("""
                INSERT INTO topology_links
                    (source_device, destination_device, source_interface,
                     destination_interface, discovery_protocol, link_type, snapshot_id)
                VALUES (?, ?, ?, ?, 'clab_topology', 'L3', ?)
                ON CONFLICT DO UPDATE SET
                    destination_interface = EXCLUDED.destination_interface,
                    snapshot_id = EXCLUDED.snapshot_id
            """, (src_node, dst_node, src_iface, dst_iface, snapshot_id))
            rows += 1
        except Exception as exc:
            logger.debug("topology_links insert failed: %s", exc)

    return rows


# ---------------------------------------------------------------------------
# DuckDB schema bootstrap — no fallback, always netops
# ---------------------------------------------------------------------------

def _ensure_parsed_outputs(con) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS netops")
    con.execute("""
        CREATE TABLE IF NOT EXISTS netops.parsed_outputs (
            device_name VARCHAR NOT NULL,
            command     VARCHAR NOT NULL,
            parsed_data JSON,
            snapshot_id VARCHAR NOT NULL,
            raw_output  VARCHAR,
            PRIMARY KEY (device_name, command, snapshot_id)
        )
    """)


# ---------------------------------------------------------------------------
# Main collect_exec entry point
# ---------------------------------------------------------------------------

async def collect_exec(
    deploy,              # DeployResult
    plan,                # ExecutionPlan
    db_path: str,
    evidence_dir: Path | None = None,
    base_dir: Path | None = None,
) -> bool:
    """Schema-aware collection via ContainerLab exec API.

    Steps:
        1. For each node × command: call exec API via CLabClient, get raw stdout
        2. Store as [{"raw_text": stdout}] in parsed_data
        3. Write {device}.staging.json (IngestManager schema)
        4. Bulk-load staging files into isolated test DuckDB
        5. Insert topology links from plan.links (ground truth)

    Args:
        deploy:       DeployResult with lab_name + api_server + nodes
        plan:         ExecutionPlan with links + nodes
        db_path:      Path to isolated test DuckDB file
        evidence_dir: Where to write staging.json files
        base_dir:     Project root (unused, kept for API compatibility)

    Returns:
        True on success, False if critical failure.
    """
    from models import get_auth_headers, get_config
    from clab_client import CLabClient

    cfg = get_config()
    snapshot_id = f"clab_{deploy.test_run_id}"
    api_server = deploy.api_server

    # Staging dir
    if evidence_dir is None:
        evidence_dir = _SKILL_ROOT / "evidence" / deploy.test_run_id
    evidence_dir = Path(evidence_dir)
    staging_dir = evidence_dir / cfg.get("collection", {}).get("staging_subdir", "staging")
    staging_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "collect_exec: lab=%s nodes=%d snapshot_id=%s staging=%s",
        deploy.lab_name, len(deploy.nodes), snapshot_id, staging_dir,
    )

    # Extract Bearer token from auth headers
    auth_headers = get_auth_headers()
    auth_header_value = auth_headers.get("Authorization", "")
    token = auth_header_value.removeprefix("Bearer ").strip()
    if not token:
        logger.error("collect_exec: CLAB_API_TOKEN not set — cannot authenticate")
        return False

    # Build schema-aware client (fetches and verifies schema on init)
    try:
        client = await CLabClient.build(api_server, token)
    except Exception as exc:
        logger.error("collect_exec: failed to build CLabClient: %s", exc)
        return False

    exec_timeout = float(cfg.get("api", {}).get("timeout_exec", 30))
    staging_records: dict[str, list[dict]] = {n: [] for n in deploy.nodes}

    for node_name, node_info in deploy.nodes.items():
        platform = node_info.platform
        commands = _get_commands_for_platform(platform)
        logger.info("  node=%s platform=%s commands=%d", node_name, platform, len(commands))

        for command in commands:
            platform_cmd = _build_exec_cmd(platform, command)

            try:
                raw_response = await client.exec_command(
                    deploy.lab_name,
                    platform_cmd,
                    timeout=exec_timeout,
                )
            except Exception as exc:
                logger.warning("  %s / %s: exec failed: %s", node_name, command[:40], exc)
                continue

            # ExecResponse: {node_name: [ClabExecInternalResult]}
            # When topology uses prefix:"" → short name (r1).
            # Default prefix → full name (clab-{lab}-r1).
            node_results = raw_response.get(node_name)
            if not node_results:
                # Try prefixed form: clab-{lab_name}-{node_name}
                prefixed = f"clab-{deploy.lab_name}-{node_name}"
                node_results = raw_response.get(prefixed)
            if not node_results:
                logger.debug("  %s / %s: no output in response", node_name, command)
                continue

            result = node_results[0]  # always a list per schema
            stdout = result.get("stdout", "")
            rc = result.get("return-code", 0)

            if not stdout or not stdout.strip():
                logger.debug("  %s / %s: empty stdout (rc=%s)", node_name, command, rc)
                continue

            staging_records[node_name].append({
                "device_name": node_name,
                "command": command,
                "parsed_data": [{"raw_text": stdout}],
                "snapshot_id": snapshot_id,
                "raw_output": stdout,
            })

            logger.info("  %s / %s → rc=%s, %d chars", node_name, command[:50], rc, len(stdout))

    # Write staging.json per device
    total_records = 0
    written_files: list[Path] = []
    for node_name, records in staging_records.items():
        if not records:
            logger.debug("  %s: no records to stage", node_name)
            continue
        staging_file = staging_dir / f"{node_name}.staging.json"
        staging_file.write_text(json.dumps(records, indent=2, default=str))
        written_files.append(staging_file)
        total_records += len(records)
        logger.info("  staged %s: %d commands → %s", node_name, len(records), staging_file.name)

    if not written_files:
        logger.warning("collect_exec: no staging files written — check auth + lab state")
        return False

    # Bulk-load staging files into DuckDB
    staging_pattern = (staging_dir / "*.staging.json").as_posix()
    try:
        import duckdb

        with duckdb.connect(str(db_path), read_only=False) as con:
            _ensure_parsed_outputs(con)

            con.execute(f"""
                INSERT INTO netops.parsed_outputs
                    (device_name, command, parsed_data, snapshot_id, raw_output)
                SELECT
                    device_name,
                    command,
                    parsed_data::JSON,
                    snapshot_id,
                    TRY_CAST(raw_output AS VARCHAR)
                FROM read_json_auto('{staging_pattern}', format='array', ignore_errors=true)
                WHERE parsed_data IS NOT NULL
                ON CONFLICT (device_name, command, snapshot_id)
                DO UPDATE SET
                    parsed_data = EXCLUDED.parsed_data,
                    raw_output  = EXCLUDED.raw_output
            """)

            inserted = con.execute(
                "SELECT COUNT(*) FROM netops.parsed_outputs WHERE snapshot_id = ?",
                [snapshot_id],
            ).fetchone()[0]

            # Insert topology links from plan
            plan_links = getattr(plan, "links", []) or []
            plan_nodes = getattr(plan, "nodes", {}) or {}
            topo_rows = _insert_topology_links(con, plan_links, plan_nodes, snapshot_id)

        logger.info(
            "collect_exec: %d staging files → %d rows in netops.parsed_outputs, %d topology_links",
            len(written_files), inserted, topo_rows,
        )

    except Exception as exc:
        logger.error("collect_exec: DuckDB bulk-load failed: %s", exc)
        return False

    # Write collection manifest
    manifest = {
        "test_run_id": deploy.test_run_id,
        "snapshot_id": snapshot_id,
        "lab_name": deploy.lab_name,
        "staging_dir": str(staging_dir),
        "staging_files": [str(f) for f in written_files],
        "total_staging_records": total_records,
        "db_path": str(db_path),
        "target_table": "netops.parsed_outputs",
        "timestamp": datetime.now(UTC).isoformat(),
        "status": "success",
    }
    (evidence_dir / "collect_exec.json").write_text(json.dumps(manifest, indent=2))

    return True


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import asyncio
    import sys

    _HERE_SCRIPTS = Path(__file__).parent.resolve()
    if str(_HERE_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_HERE_SCRIPTS))

    parser = argparse.ArgumentParser(description="Schema-aware CLI collection via CLAB exec API")
    parser.add_argument("--deploy-json", type=Path, required=True, help="Path to deploy.json")
    parser.add_argument("--plan-json", type=Path, required=True, help="Path to execution-plan.json")
    parser.add_argument("--db-path", type=Path, required=True, help="Target DuckDB path")
    parser.add_argument("--evidence-dir", type=Path, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    from models import DeployResult, ExecutionPlan

    deploy_result = DeployResult.model_validate_json(args.deploy_json.read_text())
    plan_obj = ExecutionPlan.model_validate_json(args.plan_json.read_text())

    ok = asyncio.run(
        collect_exec(
            deploy=deploy_result,
            plan=plan_obj,
            db_path=str(args.db_path),
            evidence_dir=args.evidence_dir,
        )
    )
    sys.exit(0 if ok else 1)
