"""Generate skill configuration (SKILL.md) from API schema."""

from typing import Any, Dict, Optional

from langchain_core.tools import tool


@tool
def generate_skill_config(
    api_name: str,
    api_version: str = "1.0.0",
    description: str = "",
    tools: list = None,
    output_path: str = ".olav/skills/{api_name}/SKILL.md",
) -> dict:
    """Generate SKILL.md configuration file.

    Args:
        api_name: Name of the API/system
        api_version: Version string
        description: Human-readable description
        tools: List of tool names this skill provides
        output_path: Where to write the config

    Returns:
        dict with status and generated content
    """
    from pathlib import Path

    if tools is None:
        tools = ["api_call"]

    output = output_path.format(api_name=api_name)
    skill_dir = Path(output).parent

    result = {
        "api_name": api_name,
        "output_path": output,
        "status": "success",
    }

    try:
        skill_dir.mkdir(parents=True, exist_ok=True)

        config = f"""---
name: {api_name}
description: "{description or f"{api_name.title()} API integration"}"
metadata:
  version: {api_version}
  author: SkillBuilder
  type: agent
  category: integration
  tools:
"""
        for tool_name in tools:
            config += f"    - {tool_name}\n"
        config += f"""  system: $ref:./prompts/system.md
---

## Overview

This skill provides integration with {api_name} API.

## Tools

"""
        for tool_name in tools:
            config += f"- `{tool_name}`: {tool_name.replace('_', ' ').title()} operations\n"

        config += """

## Configuration

Set API credentials via environment variables:
- `{API_NAME}_API_KEY`: API authentication key
- `{API_NAME}_BASE_URL`: Base URL for API endpoints
"""
        config = config.replace("{API_NAME}", api_name.upper())

        Path(output).write_text(config)
        result["content"] = config

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result
