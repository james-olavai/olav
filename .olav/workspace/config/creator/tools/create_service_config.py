"""Add or update a service entry in .olav/config/services.yaml."""

from langchain_core.tools import tool


@tool
def create_service_config(
    service_name: str,
    endpoint: str,
    auth_type: str,
    tag_groups: list,
    schema_url: str = "",
    readonly_only: bool = True,
    token_env: str = "",
    username_env: str = "",
    password_env: str = "",
    login_path: str = "",
    output_dir: str = ".olav/workspace/ops/tools/_generated",
    display_name: str = "",
    description: str = "",
) -> dict:
    """Add or update a service entry in .olav/config/services.yaml.

    This is idempotent — if the service already exists it will be updated.
    Does NOT trigger tool generation; call register_api_service() after this.

    Args:
        service_name:   Unique key for the service (e.g. 'netbox', 'servicenow')
        endpoint:       Base URL of the API (e.g. 'http://localhost:8000')
        auth_type:      One of: 'bearer', 'jwt', 'basic', 'none'
        tag_groups:     List of dicts with keys: tag, tool_prefix, description
                        Example: [{"tag": "circuits", "tool_prefix": "netbox_circuits",
                                   "description": "Circuit and provider management"}]
        schema_url:     Full URL to OpenAPI schema. Leave empty for auto-detection.
        readonly_only:  If True, only GET tools are generated (safer default)
        token_env:      Env var name holding the bearer token (auth_type=bearer)
        username_env:   Env var name for username (auth_type=jwt or basic)
        password_env:   Env var name for password (auth_type=jwt or basic)
        login_path:     Login endpoint path for JWT auth (e.g. '/api/v1/auth/login')
        output_dir:     Where generated tool files will be written
        display_name:   Human-readable service name
        description:    One-line description of the service

    Returns:
        dict with status and the written service configuration
    """
    from pathlib import Path

    import yaml

    config_path = Path(".olav/config/services.yaml")

    # Load existing config
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text()) or {}
        except Exception as exc:
            return {"status": "error", "error": f"Failed to parse services.yaml: {exc}"}
    else:
        data = {}

    if "services" not in data:
        data["services"] = {}

    # Build auth block
    auth: dict = {"type": auth_type}
    if auth_type == "bearer" and token_env:
        auth["token_env"] = token_env
    elif auth_type == "jwt":
        if login_path:
            auth["login_path"] = login_path
        if username_env:
            auth["username_env"] = username_env
        if password_env:
            auth["password_env"] = password_env
    elif auth_type == "basic":
        if username_env:
            auth["username_env"] = username_env
        if password_env:
            auth["password_env"] = password_env

    # Build groups list
    groups = []
    for grp in tag_groups:
        if isinstance(grp, dict) and "tag" in grp:
            groups.append({
                "tag": grp["tag"],
                "tool_prefix": grp.get("tool_prefix", f"{service_name}_{grp['tag']}"),
                "description": grp.get("description", ""),
            })

    # Build service entry
    service_cfg: dict = {
        "display_name": display_name or service_name.title(),
        "description": description or f"{service_name} API",
        "endpoint": endpoint.rstrip("/"),
        "auth": auth,
        "readonly_only": readonly_only,
        "schema_url": schema_url,
        "tool_generation": {
            "output_dir": output_dir,
            "groups": groups,
        },
    }

    action = "updated" if service_name in data["services"] else "created"
    data["services"][service_name] = service_cfg

    # Write back
    try:
        config_path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
    except Exception as exc:
        return {"status": "error", "error": f"Failed to write services.yaml: {exc}"}

    return {
        "status": "ok",
        "action": action,
        "service_name": service_name,
        "config": service_cfg,
        "next_step": f"Call register_api_service('{service_name}') to generate tool files.",
    }
