"""Generate Python skill code from API schema."""

from typing import Any, Dict, Optional

from langchain_core.tools import tool


@tool
def write_skill_code(
    schema_data: dict,
    skill_name: str,
    template: str = "basic",
    output_dir: str = ".olav/skills",
) -> dict:
    """Generate skill code from parsed API schema.

    Args:
        schema_data: Parsed schema from read_api_schema tool
        skill_name: Name for the new skill (e.g., 'netbox', 'servicenow')
        template: Template type (basic, network_inventory, itsm_workflow)
        output_dir: Directory to write skill files

    Returns:
        dict with generated file paths and status
    """
    from pathlib import Path

    skill_dir = Path(output_dir) / skill_name
    tools_dir = skill_dir / "tools"
    prompts_dir = skill_dir / "prompts"

    result = {
        "skill_name": skill_name,
        "status": "success",
        "files_created": [],
    }

    try:
        # Create directories
        tools_dir.mkdir(parents=True, exist_ok=True)
        prompts_dir.mkdir(parents=True, exist_ok=True)

        # Generate SKILL.md
        skill_md = f"""---
name: {skill_name}
description: "Auto-generated skill for {schema_data.get('title', skill_name)} API"
metadata:
  version: 1.0.0
  author: SkillBuilder
  type: agent
  category: integration
  tools:
    - api_call
  system: $ref:./prompts/system.md
---

Auto-generated skill for {schema_data.get('title', skill_name)} API v{schema_data.get('version', '1.0.0')}.
"""
        (skill_dir / "SKILL.md").write_text(skill_md)
        result["files_created"].append(str(skill_dir / "SKILL.md"))

        # Generate tool wrapper
        endpoints = schema_data.get("endpoints", [])

        tool_code = f'''"""Auto-generated API tool for {skill_name}."""

from typing import Optional
from langchain_core.tools import tool


@tool
def api_call(
    endpoint: str,
    method: str = "GET",
    params: Optional[dict] = None,
    data: Optional[dict] = None,
) -> dict:
    """Call {skill_name} API endpoint.
    
    Available endpoints:
'''
        for ep in endpoints[:10]:  # Limit to first 10
            tool_code += f'''    - {ep['method']} {ep['path']}: {ep.get('summary', '')}
'''

        tool_code += """    """
        tool_code += '''
    Args:
        endpoint: API endpoint path
        method: HTTP method (GET, POST, PUT, DELETE)
        params: Query parameters
        data: Request body (for POST/PUT)

    Returns:
        dict with API response
    """
    import requests
    
    base_url = "{base_url}"  # Configure this
    url = f"{{base_url}}{{endpoint}}"
    
    try:
        response = requests.request(
            method=method,
            url=url,
            params=params,
            json=data,
            timeout=30,
        )
        return {{
            "status": "success",
            "status_code": response.status_code,
            "data": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text,
        }}
    except Exception as e:
        return {{
            "status": "error",
            "error": str(e),
        }}
'''
        (tools_dir / "api_call.py").write_text(tool_code)
        result["files_created"].append(str(tools_dir / "api_call.py"))

        # Generate system prompt
        system_prompt = f"""# {skill_name.title()} API Skill

Auto-generated skill for interacting with {schema_data.get('title', skill_name)} API.

## Available Endpoints

"""
        for ep in endpoints:
            system_prompt += f"- **{ep['method']}** `{ep['path']}`: {ep.get('summary', '')}\n"

        system_prompt += """

## Usage

Use the `api_call` tool to interact with the API. Always specify:
- endpoint: The API path
- method: HTTP method
- params: Query parameters (optional)
- data: Request body (optional)

## Authentication

Configure API credentials in your environment.
"""
        (prompts_dir / "system.md").write_text(system_prompt)
        result["files_created"].append(str(prompts_dir / "system.md"))

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result
