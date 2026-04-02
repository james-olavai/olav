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

    # Force reload services.yaml so the singleton reflects any recent create_service_config changes
    try:
        from olav.platform.services.registry import ServiceRegistry
        ServiceRegistry.get_instance().reload()
    except Exception:
        pass

    try:
        result = register_service(service_name, force=force)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    # Normalise result
    if result.get("status") == "error":
        return result

    files = result.get("files_written", [])

    # Validate @tool decorators in all generated files
    import re as _re
    tool_counts: dict[str, int] = {}
    missing_decorators: list[str] = []
    for f in files:
        try:
            content = open(f).read()
            count = len(_re.findall(r"^@tool\b", content, _re.MULTILINE))
            tool_counts[f] = count
            if count == 0:
                missing_decorators.append(f)
        except OSError:
            tool_counts[f] = -1

    return {
        "status": "ok",
        "service_name": service_name,
        "ops_loaded": result.get("ops_loaded", 0),
        "files_written": files,
        "files_count": len(files),
        "tool_counts": tool_counts,
        "validation": (
            "✓ all files have @tool decorators"
            if not missing_decorators
            else f"⚠ MISSING @tool in: {missing_decorators}"
        ),
        "next_step": (
            f"Call create_skill_workspace() pointing to: {files}"
            if files else "No files generated — check tag_groups in services.yaml."
        ),
    }
