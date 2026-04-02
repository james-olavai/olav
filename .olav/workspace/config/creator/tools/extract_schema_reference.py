"""Extract query params from api_registry and write schema_reference.json to a workspace."""

import json
from pathlib import Path

from langchain_core.tools import tool


@tool
def extract_schema_reference(
    service_name: str,
    workspace_path: str,
    tag: str = "",
) -> dict:
    """Extract per-endpoint query params from the api_registry and write schema_reference.json.

    The schema_reference.json is placed inside the workspace directory so it can be
    declared as static_context in SKILL.md — making the using agent schema-aware at
    load time without any hardcoded parameter lists.

    Call this AFTER register_api_service() (schema must be in the registry) and
    BEFORE create_skill_workspace() so you can pass the returned path as
    static_context_paths.

    Args:
        service_name:    Key in services.yaml (e.g. 'netbox')
        workspace_path:  Target workspace directory (e.g. '.olav/workspace/netbox-circuits')
                         The file will be written to <workspace_path>/schema_reference.json
        tag:             Optional tag filter (e.g. 'circuits') — omit for all operations

    Returns:
        dict with status, path to schema_reference.json, and operation/param counts
    """
    try:
        from olav.platform.services.tool_generator import generate_schema_reference
    except ImportError as exc:
        return {"status": "error", "error": f"Cannot import tool_generator: {exc}"}

    try:
        ref = generate_schema_reference(service_name, tag=tag or None)
    except Exception as exc:
        return {"status": "error", "error": f"generate_schema_reference failed: {exc}"}

    ws_dir = Path(workspace_path)
    ws_dir.mkdir(parents=True, exist_ok=True)
    out_path = ws_dir / "schema_reference.json"

    try:
        out_path.write_text(json.dumps(ref, indent=2))
    except Exception as exc:
        return {"status": "error", "error": f"Failed to write schema_reference.json: {exc}"}

    # Count how many endpoints have at least one query param
    ops = ref.get("operations", {})
    total_ops = len(ops)
    ops_with_params = sum(1 for v in ops.values() if v.get("query_params"))
    total_params = sum(len(v.get("query_params", [])) for v in ops.values())

    return {
        "status": "ok",
        "path": str(out_path),
        "service": service_name,
        "tag_filter": tag or None,
        "total_operations": total_ops,
        "operations_with_query_params": ops_with_params,
        "total_query_params": total_params,
        "next_step": (
            f"Pass static_context_paths=['{out_path}'] to create_skill_workspace() "
            "so the agent loads schema context at startup."
        ),
    }
