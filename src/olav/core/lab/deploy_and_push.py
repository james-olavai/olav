"""Deploy a ContainerLab topology AND push SR Linux config in one atomic operation.

Use this tool to deploy + configure in a single call instead of calling deploy_lab
and push_node_config separately. This avoids multi-step retry loops.

Internally calls deploy_lab (which handles mgmt network injection, fix_srl_topology,
and create_srl_links), then pushes all node configs atomically.

Tool: deploy_and_push_lab

Args (JSON):
    lab_name:     str                  — Lab name (e.g. "r1-r4-ebgp-direct")
    yaml_content: str                  — ContainerLab topology YAML (full content)
    configs:      dict[str, list[str]] — {node_name: [sr_cli set commands]}
                                         REQUIRED — must include ALL nodes
                                         e.g. {"r1": ["set / interface ...", "set / network-instance ..."],
                                               "r4": ["set / interface ...", "set / network-instance ..."]}
    wait_seconds: int | None           — Seconds to wait after deploy before pushing (default: 40)

Returns: JSON string
    {
      "deployed": true,
      "committed": true,
      "nodes": {"r1": "All changes committed successfully.", "r4": "All changes committed successfully."},
      "lab_name": "r1-r4-ebgp-direct"
    }
    or on error:
    {
      "deployed": false,
      "error": "...",
      "stage": "deploy" | "push" | "auth"
    }

IMPORTANT: Call this tool ONCE with both yaml_content AND configs populated.
Do NOT call with empty configs={} — all node configs must be ready before calling.
"""

from __future__ import annotations

import base64
import importlib
import json
import sys
import time
from pathlib import Path

from ._paths import lab_config_path, lab_workspace_tools_dir


def _load_ws_module(name: str):
    """Load a workspace tools/ helper by spec (avoids polluting sys.path)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, lab_workspace_tools_dir() / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"workspace helper {name} not found at {lab_workspace_tools_dir()}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_cfg() -> dict:
    return json.loads(lab_config_path().read_text())


def _get_token(cfg: dict) -> str:
    import httpx
    r = httpx.post(
        f"{cfg['base_url']}/login",
        json={"username": cfg["username"], "password": cfg["password"]},
        verify=False,
        timeout=15.0,
    )
    r.raise_for_status()
    return r.json()["token"]


def deploy_and_push_lab(
    lab_name: str,
    yaml_content: str,
    configs: dict,
    wait_seconds: int = 40,
    post_commit_wait_seconds: int = 30,
) -> dict:
    """Deploy ContainerLab topology AND push SR Linux configuration in one atomic call.

    This tool handles the complete deploy + configure lifecycle:
    1. Checks if lab already exists — if yes, SKIPS deploy and only pushes config
    2. If lab does not exist, deploys via deploy_lab (includes mgmt network, fix_srl_topology, links)
    3. Pushes all node configs atomically via sr_cli
    4. Waits ``post_commit_wait_seconds`` after the last commit so callers
       can verify protocol state immediately on return (BGP/OSPF
       convergence on a small lab is typically 15-25s; 30s is safe
       margin).  Set to 0 to skip if you only configured static state.

    This means it is SAFE to call repeatedly for config fixes — it will NOT redeploy if lab is running.

    IMPORTANT: Provide ALL node configs in a single call. Do NOT call with empty configs.
    Use save_lab_config first to build configs, then call this with configs={} to auto-load.

    Args:
        lab_name:     Lab name (e.g. "r1-r4-ebgp-direct")
        yaml_content: Full ContainerLab YAML topology string (needed for first deploy; ignored if lab exists)
        configs:      Dict of {node_name: [list of SRL "set /" commands]} for ALL nodes.
                      Example: {"r1": ["set / interface ethernet-1/1 ...", ...],
                                "r4": ["set / interface ethernet-1/1 ...", ...]}
                      Pass {} to auto-load from save_lab_config temp files.
        wait_seconds: Seconds to wait after FIRST deploy before pushing configs (default: 40, ignored if lab exists)

    Returns:
        JSON with deployed, committed, lab_reused, per-node stdout results
    """
    import httpx

    # ── Auto-load configs from saved drop-box if configs is empty ─────────
    # R86 follow-up: read from exports/lab/<lab_name>/<node>.json (the
    # location save_lab_config writes to).  Backward-compat: also fall
    # back to the legacy /tmp/clab_config_<lab_name>_*.json path so an
    # in-flight lab session that started before the upgrade still works.
    if not configs:
        loaded = {}
        try:
            from olav.core.config import EXPORTS_DIR
            lab_dir = EXPORTS_DIR / "lab" / lab_name
            if lab_dir.is_dir():
                for fpath in lab_dir.glob("*.json"):
                    node_part = fpath.stem
                    if node_part:
                        loaded[node_part] = json.loads(fpath.read_text())
        except Exception:
            pass

        if not loaded:
            try:
                import glob as _glob
                pattern = f"/tmp/clab_config_{lab_name}_*.json"
                for fpath in _glob.glob(pattern):
                    stem = Path(fpath).stem
                    node_part = stem[len(f"clab_config_{lab_name}_"):]
                    if node_part:
                        loaded[node_part] = json.loads(Path(fpath).read_text())
            except Exception:
                pass

        if loaded:
            configs = loaded
        else:
            return {
                "deployed": False,
                "committed": False,
                "error": (
                    "configs is empty and no saved configs found for this lab. "
                    "Call save_lab_config(lab_name, node, config_lines) for each node first, "
                    "then call deploy_and_push_lab. "
                    "OR include configs inline in this call."
                ),
                "example": {
                    "save_lab_config": {
                        "lab_name": lab_name,
                        "node": "r1",
                        "config_lines": [
                            "set / interface ethernet-1/1 admin-state enable",
                            "set / interface ethernet-1/1 subinterface 0 ipv4 address 10.0.0.1/30",
                            "set / interface system0 subinterface 0 ipv4 address 1.1.1.1/32",
                            "... (all 20 set commands)"
                        ]
                    }
                }
            }

    # ── Step 1: Check if lab already exists — skip deploy if so ────────────────
    cfg = _load_cfg()
    try:
        token = _get_token(cfg)
    except Exception as e:
        return {"deployed": False, "committed": False, "error": f"Auth failed: {e}", "stage": "auth"}

    headers = {"Authorization": f"Bearer {token}"}
    base_url = cfg["base_url"].rstrip("/")

    lab_already_running = False
    try:
        check_resp = httpx.get(f"{base_url}/api/v1/labs", headers=headers, verify=False, timeout=10.0)
        if check_resp.status_code == 200:
            existing_labs = check_resp.json()
            if isinstance(existing_labs, dict) and lab_name in existing_labs:
                lab_already_running = True
    except Exception:
        pass

    if not lab_already_running:
        # ── Deploy via olav.core.lab.deploy_lab (sibling Python helper) ──
        from olav.core.lab.deploy_lab import deploy_lab as _deploy_lab
        deploy_result = _deploy_lab(
            yaml_content=yaml_content,
            wait_seconds=wait_seconds,
        )

        if deploy_result.get("status") == "error":
            return {
                "deployed": False,
                "committed": False,
                "error": deploy_result.get("error", "deploy_lab failed"),
                "stage": "deploy",
                "deploy_detail": deploy_result,
            }

        # Refresh token after deploy wait
        try:
            token = _get_token(cfg)
        except Exception as e:
            return {
                "deployed": True,
                "committed": False,
                "error": f"Auth refresh failed after deploy: {e}",
                "stage": "auth",
            }
        headers = {"Authorization": f"Bearer {token}"}
    # else: lab already running — skip deploy, reuse existing token

    # ── Step 3: Push config to each node (two-phase: dry-run then commit) ───────
    node_results: dict[str, str] = {}
    push_errors: dict[str, str] = {}
    dry_run_failures: dict[str, str] = {}

    error_indicators = ["Commit failed", "Error in /", "Parsing error", "error:", "Validate failed", "Error:"]

    def _exec_on_node(node: str, script: str) -> str:
        """Execute sr_cli script on a node via CLAB exec API. Returns stdout."""
        container_name = f"clab-{lab_name}-{node}"
        b64 = base64.b64encode(script.encode()).decode()
        cmd = f"bash -c 'echo {b64} | base64 -d | sr_cli 2>&1'"
        r = httpx.post(
            f"{base_url}/api/v1/labs/{lab_name}/exec",
            params={"nodeFilter": container_name},
            json={"command": cmd},
            headers=headers,
            verify=False,
            timeout=60.0,
        )
        body = r.json()
        node_data = body.get(container_name, body.get(node, [{}]))
        return node_data[0].get("stdout", "") if isinstance(node_data, list) and node_data else ""

    for node, config_lines in configs.items():
        try:
            # Fix #4 (2026-05-07): be defensive — accept either list[str]
            # (the documented contract) or str (what generate_srl_lab_config
            # returned pre-fix).  If it's a str, splitlines first to avoid
            # iterating per-character which produces a script whose line 2
            # is the bare char "s" → SRL YANG parser rejects.
            if isinstance(config_lines, str):
                config_lines = config_lines.splitlines()
            config_body = "\n".join(str(l) for l in config_lines)

            # Phase 1: commit validate (YANG validation — SRL v24.10.1: use "commit validate" NOT "commit dry-run")
            dry_script = f"enter candidate\n{config_body.strip()}\ncommit validate\n"
            dry_stdout = _exec_on_node(node, dry_script)

            has_dry_error = any(ind in dry_stdout for ind in error_indicators)
            if has_dry_error:
                dry_run_failures[node] = dry_stdout[:500]
                continue  # skip commit for this node, collect all errors first

            # Phase 2: commit now
            commit_script = f"enter candidate\n{config_body.strip()}\ncommit now\n"
            stdout = _exec_on_node(node, commit_script)

            has_commit_error = any(ind in stdout for ind in error_indicators)
            if has_commit_error:
                push_errors[node] = stdout[:400]
            else:
                node_results[node] = stdout.strip() or "All changes committed successfully."
        except Exception as e:
            push_errors[node] = str(e)

    if dry_run_failures:
        return {
            "deployed": True,
            "committed": False,
            "stage": "dry_run",
            "nodes": node_results,
            "dry_run_failures": dry_run_failures,
            "errors": push_errors,
            "hint": "SRL YANG validation rejected config for listed nodes. Fix the commands and retry with push_node_config.",
        }

    if push_errors:
        return {
            "deployed": True,
            "committed": False,
            "nodes": node_results,
            "errors": push_errors,
            "lab_name": lab_name,
        }

    # ── Cleanup config drop-box (R86 location + legacy /tmp) ──────────────
    try:
        from olav.core.config import EXPORTS_DIR
        lab_dir = EXPORTS_DIR / "lab" / lab_name
        if lab_dir.is_dir():
            for fpath in lab_dir.glob("*.json"):
                fpath.unlink(missing_ok=True)
            try:
                lab_dir.rmdir()  # remove if empty
            except OSError:
                pass
    except Exception:
        pass
    try:
        import glob as _glob2
        for fpath in _glob2.glob(f"/tmp/clab_config_{lab_name}_*.json"):
            Path(fpath).unlink(missing_ok=True)
    except Exception:
        pass

    # ── Post-commit convergence wait ────────────────────────────────────
    # SRL config commit returns immediately, but the data plane needs
    # extra time before BGP/OSPF reach Established/Full:
    #   * sr_device_mgr restart (from create_srl_links) finishing
    #   * ARP resolution via the new veth pair
    #   * BGP TCP connect + open + keepalive handshake
    # Without this wait, the caller's next exec_on_node sees BGP "active"
    # / OSPF "init" and mis-reports CAB FAIL on a spec that would in fact
    # converge a few seconds later (R88-B v3 → v4).
    converged_wait = max(0, int(post_commit_wait_seconds))
    if converged_wait > 0 and node_results:
        time.sleep(converged_wait)

    return {
        "deployed": True,
        "committed": True,
        "lab_reused": lab_already_running,
        "nodes": node_results,
        "lab_name": lab_name,
        "post_commit_wait_seconds": converged_wait,
        "message": (
            f"Lab '{lab_name}' "
            f"{'ALREADY RUNNING — DO NOT redeploy. Config pushed' if lab_already_running else 'deployed and configured'} "
            f"— {len(node_results)} nodes committed successfully"
            f"{f'; waited {converged_wait}s for BGP/OSPF convergence' if converged_wait else ''}."
        ),
    }


