"""List all services registered in the platform (services.yaml)."""

from pathlib import Path

from langchain_core.tools import tool


@tool
def list_platform_services() -> dict:
    """List all services registered in .olav/config/services.yaml.

    Returns service names, endpoints, auth types, registered tag groups,
    and paths to any already-generated tool files.

    Use this first to understand what is already onboarded before creating
    a new service or extending an existing one.

    Returns:
        dict with 'services' list and 'generated_tools' map
    """
    import yaml

    config_path = Path(".olav/config/services.yaml")
    if not config_path.exists():
        return {"status": "error", "error": f"services.yaml not found at {config_path}"}

    try:
        data = yaml.safe_load(config_path.read_text())
    except Exception as exc:
        return {"status": "error", "error": f"Failed to parse services.yaml: {exc}"}

    services_raw = data.get("services", {})
    result: list[dict] = []

    for name, cfg in services_raw.items():
        groups = []
        tg = cfg.get("tool_generation", {})
        output_dir = tg.get("output_dir", "")
        for grp in tg.get("groups", []):
            tag = grp.get("tag", "")
            prefix = grp.get("tool_prefix", "")
            tool_file = Path(output_dir) / f"{prefix}.py" if output_dir and prefix else None
            groups.append({
                "tag": tag,
                "tool_prefix": prefix,
                "description": grp.get("description", ""),
                "tool_file": str(tool_file) if tool_file else None,
                "tool_file_exists": tool_file.exists() if tool_file else False,
            })

        result.append({
            "name": name,
            "display_name": cfg.get("display_name", name),
            "description": cfg.get("description", ""),
            "endpoint": cfg.get("endpoint", ""),
            "schema_url": cfg.get("schema_url", ""),
            "auth_type": cfg.get("auth", {}).get("type", "none"),
            "readonly_only": cfg.get("readonly_only", True),
            "tag_groups": groups,
            "output_dir": output_dir,
        })

    return {"status": "ok", "services": result, "total": len(result)}
