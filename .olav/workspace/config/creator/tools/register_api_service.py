"""Trigger platform-native tool generation for a registered service."""

from langchain_core.tools import tool


@tool
def register_api_service(
    service_name: str,
    force: bool = True,
) -> dict:
    """Trigger platform tool generation for a service registered in services.yaml.

    This calls the platform's register_service() pipeline which:
    1. Fetches the OpenAPI schema from the service endpoint
    2. Generates one Python file per tag group under the configured output_dir
    3. Each file contains one function per API endpoint, using service_call()
       for unified auth/retry/approval handling

    The generated tools are production-quality: they use the platform's
    service_call() abstraction and are automatically discoverable by agents.

    Args:
        service_name: Key in services.yaml (e.g. 'netbox', 'servicenow')
        force:        Re-fetch schema and overwrite existing tool files (default: True)

    Returns:
        dict with status, generated file paths, and ops_loaded count
    """
    try:
        from olav.platform.services.tool_generator import register_service
    except ImportError as exc:
        return {
            "status": "error",
            "error": f"Cannot import platform tool_generator: {exc}",
        }

    try:
        result = register_service(service_name, force=force)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    # Normalise result
    if result.get("status") == "error":
        return result

    files = result.get("files_written", [])
    return {
        "status": "ok",
        "service_name": service_name,
        "ops_loaded": result.get("ops_loaded", 0),
        "files_written": files,
        "files_count": len(files),
        "next_step": (
            f"Call create_skill_workspace() pointing to: {files}"
            if files else "No files generated — check tag_groups in services.yaml."
        ),
    }
