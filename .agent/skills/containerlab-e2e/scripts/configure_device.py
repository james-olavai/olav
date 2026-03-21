from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timezone
from pathlib import Path
from string import Template

import httpx
from models import (
    DEFAULT_API_SERVER,
    ConfigureResult,
    DeployResult,
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
    deploy: DeployResult,
    config_dir: Path,
    dry_run: bool = True,
    api_server: str | None = None,
    evidence_dir: Path | None = None,
) -> ConfigureResult:
    server = api_server or deploy.api_server or DEFAULT_API_SERVER
    out_dir = evidence_dir or Path(f".agent/skills/containerlab-e2e/evidence/{deploy.test_run_id}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Render all node configs (dry-run and apply both need this) ─────────
    node_scripts: dict[str, list[str]] = {}  # node_name → list of rendered cmd blocks
    node_statuses: dict[str, NodeConfigStatus] = {}
    overall_ok = True

    for node_name, node_info in deploy.nodes.items():
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
        for node_name, rendered in node_scripts.items():
            preview_dir = out_dir / "config-preview" / node_name
            preview_dir.mkdir(parents=True, exist_ok=True)
            for i, cmd in enumerate(rendered):
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

    # ── Apply: hostname-conditional exec (NodeFilter is ignored by clab API) ─
    #
    # Strategy:
    #   1. Write EVERY node's config to a uniquely-named temp file on ALL nodes.
    #      (Because NodeFilter is ignored, all exec commands run on ALL nodes.)
    #   2. Apply with ONE exec call using `hostname` to select the right file.
    #
    apply_dir = out_dir / "config-apply"
    apply_dir.mkdir(parents=True, exist_ok=True)

    tmp_prefix = f"/tmp/olav_{deploy.test_run_id[:8]}"
    node_tmp_paths: dict[str, str] = {}
    write_parts: list[str] = []

    for node_name, rendered in node_scripts.items():
        full_script = "\n".join(rendered)
        b64 = base64.b64encode(full_script.encode()).decode()
        tmp_path = f"{tmp_prefix}_{node_name}.cfg"
        node_tmp_paths[node_name] = tmp_path
        write_parts.append(f"echo {b64} | base64 -d > {tmp_path}")
        (apply_dir / f"{node_name}_script.txt").write_text(full_script)

    # Single exec call writes all node config files to every container
    write_cmd = "bash -c '" + " && ".join(write_parts) + "'"

    # Hostname-conditional: each container applies its own config by hostname
    # f-string: ${{H}} → ${H} after Python processes the f-string braces
    apply_cmd = (
        f"bash -c 'H=$(hostname); cfg={tmp_prefix}_${{H}}.cfg; "
        f'[ -f "$cfg" ] && sr_cli < "$cfg" 2>&1 || echo SKIP_$H\''
    )

    final_statuses: dict[str, NodeConfigStatus] = dict(node_statuses)

    try:
        async with httpx.AsyncClient(headers=get_auth_headers()) as client:
            # Step 1: write all config files to all nodes
            write_resp = await client.post(
                f"{server}/labs/{deploy.lab_name}/exec",
                json={"Command": write_cmd},
                timeout=30.0,
            )
            write_resp.raise_for_status()
            (apply_dir / "write_response.json").write_text(write_resp.text)

            # Step 2: apply hostname-conditional (single call, all nodes)
            apply_resp = await client.post(
                f"{server}/labs/{deploy.lab_name}/exec",
                json={"Command": apply_cmd},
                timeout=60.0,
            )
            apply_resp.raise_for_status()
            apply_body = apply_resp.json()
            (apply_dir / "apply_response.json").write_text(apply_resp.text)
        for node_name in node_scripts:
            container = f"clab-{deploy.lab_name}-{node_name}"
            node_result = apply_body.get(container, [{}])[0]
            rc = node_result.get("return-code", 0)
            stderr = node_result.get("stderr", "")
            stdout = node_result.get("stdout", "")

            if f"SKIP_{node_name}" in stdout:
                # This hostname had no config file — unexpected but not fatal
                final_statuses[node_name] = NodeConfigStatus(
                    name=node_name,
                    status="skipped",
                    commands_sent=node_statuses.get(
                        node_name,
                        NodeConfigStatus(name=node_name, status="skipped", commands_sent=0),
                    ).commands_sent,
                    error="hostname-conditional: no config file matched",
                )
            elif rc != 0 or ("error" in stderr.lower() and "warning" not in stderr.lower()):
                overall_ok = False
                final_statuses[node_name] = NodeConfigStatus(
                    name=node_name,
                    status="failed",
                    commands_sent=node_statuses.get(
                        node_name,
                        NodeConfigStatus(name=node_name, status="failed", commands_sent=0),
                    ).commands_sent,
                    error=f"rc={rc}: {stderr[:300]}",
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

    except (httpx.HTTPError, Exception) as exc:
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
