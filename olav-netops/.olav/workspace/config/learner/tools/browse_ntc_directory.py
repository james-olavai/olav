#!/usr/bin/env python3
"""
Tool 5: Browse NTC Directory (NEW)

Browse NTC-templates directory structure to explore available templates.
"""

import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def find_ntc_templates_path() -> Path | None:
    """Locate ntc-templates installation directory."""
    try:
        import ntc_templates
        return Path(ntc_templates.__file__).parent / "templates"
    except ImportError:
        logger.error("ntc-templates not installed")
        return None


@tool
def browse_ntc_directory(platform: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Browse NTC-templates directory structure.
    
    Args:
        platform: Filter by platform (optional, e.g., "cisco_ios")
        limit: Maximum entries to return (default: 20)
    
    Returns:
        dict: {
            "ntc_path": str,
            "total_templates": int,
            "platforms": list[str],  # Unique platforms found
            "templates": list[dict]  # Template summaries
        }
    
    Template format:
        {
            "name": str,
            "size_bytes": int,
            "platform": str,
            "commands": list[str],  # Inferred from filename
            "last_modified": str
        }
    
    Purpose: Let agent explore NTC templates before searching
    
    Example:
        >>> browse_ntc_directory("cisco_ios", limit=10)
        {"total_templates": 856, "platforms": ["cisco_ios", ...], "templates": [...]}
    """
    # Find NTC path
    ntc_path = find_ntc_templates_path()
    if not ntc_path or not ntc_path.exists():
        return {
            "ntc_path": None,
            "total_templates": 0,
            "platforms": [],
            "templates": [],
            "error": "NTC-templates not found"
        }

    # Get all templates
    all_templates = list(ntc_path.glob("*.textfsm"))

    # Extract unique platforms
    platforms = set()
    for template_path in all_templates:
        # Platform is usually first part of filename: cisco_ios_show_version.textfsm
        parts = template_path.stem.split("_")
        if len(parts) >= 2:
            platform_name = "_".join(parts[:2])  # cisco_ios
            platforms.add(platform_name)

    # Filter by platform if specified
    if platform:
        filtered_templates = [
            t for t in all_templates
            if platform.lower() in t.name.lower()
        ]
    else:
        filtered_templates = all_templates

    # Limit results
    filtered_templates = filtered_templates[:limit]

    # Build template summaries
    templates = []
    for template_path in filtered_templates:
        # Infer commands from filename
        # Example: cisco_ios_show_ip_bgp_summary.textfsm → ["show", "ip", "bgp", "summary"]
        parts = template_path.stem.split("_")
        if len(parts) >= 3:
            # Skip platform prefix (e.g., cisco_ios)
            platform_name = "_".join(parts[:2])
            command_parts = parts[2:]
            commands = [" ".join(command_parts)]
        else:
            platform_name = "unknown"
            commands = []

        templates.append({
            "name": template_path.name,
            "size_bytes": template_path.stat().st_size,
            "platform": platform_name,
            "commands": commands,
            "last_modified": template_path.stat().st_mtime.__str__()
        })

    logger.info(f"Browsed NTC directory: {len(templates)}/{len(all_templates)} templates")

    return {
        "ntc_path": str(ntc_path),
        "total_templates": len(all_templates),
        "platforms": sorted(platforms),
        "templates": templates
    }
