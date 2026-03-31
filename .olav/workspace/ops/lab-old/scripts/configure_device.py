from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from string import Template

from models import (
    DEFAULT_API_SERVER,
    ConfigureResult,
    DeployResult,
    ExecutionPlan,
    NodeConfigStatus,
    get_auth_headers,
)


def _render_template(template_path: Path, variables: dict) -> str:
    content = template_path.read_text()
    return Template(content).safe_substitute(variables)


def _build_node_variables(node_name: str, deploy: DeployResult) -> dict:
    node = deploy.nodes[node_name]
    return {
        "hostname": node_name,
        "mgmt_ip": node.mgmt_cloud_ip,
        "mgmt_port": str(node.mgmt_cloud_port),
        "platform": node.platform,
    }


async def configure_device(
    plan: ExecutionPlan,
    deploy: DeployResult,
    config_dir: Path,
    dry_run: bool = True,
    api_server: str | None = None,
    output_dir: Path | None = None,
    oc_configs: dict[str, str] | None = None,
) -> ConfigureResult:
    """Configure nodes in the deployed lab.

    Config source priority:
      1. oc_configs  — pre-rendered SRL set/... strings from CABConfigExtractor
      2. config_dir  — Jinja2 template files (default/legacy path)

    Args:
        plan:       ExecutionPlan from compile_scenario (contains config_source, nodes).
        deploy:     DeployResult with lab_name, api_server, node IPs.
        config_dir: Directory for Jinja2 template configs (used when oc_configs is None).
        dry_run:    If True, write config preview to output_dir; do not exec.
        api_server: Override CLAB API server URL.
        output_dir: Evidence output directory.
        oc_configs: Pre-rendered per-node SRL configs from CABConfigExtractor.
                    Keys must match node names in deploy.nodes.
    """
    from clab_client import CLabClient, CLABAPIError

    server = api_server or deploy.api_server or DEFAULT_API_SERVER
    out_dir = output_dir or Path(f".agent/skills/containerlab-e2e/evidence/{deploy.test_run_id}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Render / collect per-node config strings ───────────────────────────
    node_scripts: dict[str, list[str]] = {}
    node_statuses: dict[str, NodeConfigStatus] = {}
    overall_ok = True

    for node_name, node_info in deploy.nodes.items():

        # --- OC agent path: use pre-rendered SRL config ---
        if oc_configs is not None:
            cfg = oc_configs.get(node_name, "")
            if not cfg or cfg.startswith("# no renderable"):
                node_statuses[node_name] = NodeConfigStatus(
                    name=node_name,
                    status="skipped",
                    error="oc_agent: no renderable config for this node",
                )
                continue
            lines = [line for line in cfg.splitlines() if line.strip()]
            node_scripts[node_name] = lines
            node_statuses[node_name] = NodeConfigStatus(
                name=node_name,
                status="success",
                commands_sent=len(lines),
            )
            continue

        # --- Template path: read from config_dir ---
        node_config_dir = config_dir / node_info.platform / node_name
        if not node_config_dir.exists():
            node_config_dir = config_dir / node_name

        if not node_config_dir.exists():
            node_statuses[node_name] = NodeConfigStatus(
                name=node_name,
                status="skipped",
                error=f"No config directory found for {node_name}",
            )
            continue

        variables = _build_node_variables(node_name, deploy)
        templates = sorted(node_config_dir.glob("*.cfg")) + sorted(node_config_dir.glob("*.conf"))
        if not templates:
            templates = sorted(node_config_dir.glob("*"))
            templates = [t for t in templates if t.is_file()]

        rendered: list[str] = [_render_template(tpl, variables) for tpl in templates]
        node_scripts[node_name] = rendered
        node_statuses[node_name] = NodeConfigStatus(
            name=node_name,
            status="success",
            commands_sent=len(rendered),
        )

    # ── Dry-run: write previews only, no exec ─────────────────────────────
    if dry_run:
        for node_name, lines in node_scripts.items():
            preview_dir = out_dir / "config-preview" / node_name
            preview_dir.mkdir(parents=True, exist_ok=True)
            for i, cmd in enumerate(lines):
                (preview_dir / f"step_{i:03d}.txt").write_text(cmd)

        result = ConfigureResult(
            test_run_id=deploy.test_run_id,
            nodes=node_statuses,
            dry_run=True,
            timestamp=datetime.now(UTC).isoformat(),
            status="success",
        )
        (out_dir / "configure.json").write_text(json.dumps(result.model_dump(), indent=2))
        return result

    # ── Apply: hostname-conditional exec ──────────────────────────────────
    apply_dir = out_dir / "config-apply"
    apply_dir.mkdir(parents=True, exist_ok=True)

    tmp_prefix = f"/tmp/olav_{deploy.test_run_id[:8]}"
    node_tmp_paths: dict[str, str] = {}
    write_parts: list[str] = []

    for node_name, lines in node_scripts.items():
        full_script = "\n".join(lines)
        b64 = base64.b64encode(full_script.encode()).decode()
        tmp_path = f"{tmp_prefix}_{node_name}.cfg"
        node_tmp_paths[node_name] = tmp_path
        write_parts.append(f"echo {b64} | base64 -d > {tmp_path}")
        (apply_dir / f"{node_name}_script.txt").write_text(full_script)

    # Single exec call writes all node config files to every container
    write_cmd = "bash -c '" + " && ".join(write_parts) + "'"

    # Hostname-conditional: each container applies its own config by hostname.
    # Echoes CFG_RC=$? so the caller can detect success (CFG_RC=0) vs failure.
    apply_cmd = (
        f"bash -c 'H=$(hostname); cfg={tmp_prefix}_${{H}}.cfg; "
        f'[ -f "$cfg" ] && (sr_cli < "$cfg" 2>&1; echo CFG_RC=$?) || echo SKIP_$H\''
    )

    final_statuses: dict[str, NodeConfigStatus] = dict(node_statuses)

    # Extract Bearer token
    auth_headers = get_auth_headers()
    auth_header_value = auth_headers.get("Authorization", "")
    token = auth_header_value.removeprefix("Bearer ").strip()

    try:
        client = await CLabClient.build(server, token)

        # Step 1: write all config files to all nodes
        write_response = await client.exec_command(deploy.lab_name, write_cmd, timeout=30.0)
        (apply_dir / "write_response.json").write_text(json.dumps(write_response, indent=2))

        # Step 2: apply hostname-conditional
        apply_body = await client.exec_command(deploy.lab_name, apply_cmd, timeout=60.0)
        (apply_dir / "apply_response.json").write_text(json.dumps(apply_body, indent=2))

        for node_name in node_scripts:
            node_results = apply_body.get(node_name, [{}])
            node_result = node_results[0] if node_results else {}
            rc = node_result.get("return-code", 0)
            stderr = node_result.get("stderr", "")
            stdout = node_result.get("stdout", "")

            if f"SKIP_{node_name}" in stdout:
                final_statuses[node_name] = NodeConfigStatus(
                    name=node_name,
                    status="skipped",
                    commands_sent=node_statuses.get(
                        node_name,
                        NodeConfigStatus(name=node_name, status="skipped", commands_sent=0),
                    ).commands_sent,
                    error="hostname-conditional: no config file matched",
                )
            elif (
                rc != 0
                or ("CFG_RC=" in stdout and "CFG_RC=0" not in stdout)
                or ("error" in stderr.lower() and "warning" not in stderr.lower())
            ):
                overall_ok = False
                final_statuses[node_name] = NodeConfigStatus(
                    name=node_name,
                    status="failed",
                    commands_sent=node_statuses.get(
                        node_name,
                        NodeConfigStatus(name=node_name, status="failed", commands_sent=0),
                    ).commands_sent,
                    error=f"rc={rc}: {(stderr or stdout)[:300]}",
                )
            else:
                final_statuses[node_name] = NodeConfigStatus(
                    name=node_name,
                    status="success",
                    commands_sent=node_statuses.get(
                        node_name,
                        NodeConfigStatus(name=node_name, status="success", commands_sent=0),
                    ).commands_sent,
                )

    except Exception as exc:
        overall_ok = False
        for node_name in node_scripts:
            final_statuses[node_name] = NodeConfigStatus(
                name=node_name,
                status="failed",
                commands_sent=node_statuses.get(
                    node_name, NodeConfigStatus(name=node_name, status="failed", commands_sent=0)
                ).commands_sent,
                error=str(exc),
            )

    result = ConfigureResult(
        test_run_id=deploy.test_run_id,
        nodes=final_statuses,
        dry_run=False,
        timestamp=datetime.now(UTC).isoformat(),
        status="success" if overall_ok else "failed",
    )
    (out_dir / "configure.json").write_text(json.dumps(result.model_dump(), indent=2))
    return result
