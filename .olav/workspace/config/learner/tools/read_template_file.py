#!/usr/bin/env python3
"""
Tool 4: Read Template File (NEW - On-demand Content Loading)

Reads full TextFSM template content only for selected templates.
Use after search_ntc_templates() to load full content of top matches.
"""

import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def extract_textfsm_fields(template_content: str) -> list[str]:
    """Extract field names from TextFSM template content."""
    fields = []
    for line in template_content.splitlines():
        line = line.strip()
        if line.startswith("Value "):
            # Parse "Value NAME (regex)" or "Value Required NAME (regex)"
            parts = line.split()
            if len(parts) >= 3:
                # Handle "Value Required NAME" or "Value NAME"
                if parts[1].lower() in ["required", "filldown", "list"]:
                    field_name = parts[2]
                else:
                    field_name = parts[1]
                fields.append(field_name)
    return fields


@tool
def read_template_file(template_path: str) -> dict[str, Any]:
    """Read full TextFSM template content.
    
    Args:
        template_path: Full path to template file (from search_ntc_templates)
    
    Returns:
        dict: {
            "template_name": str,
            "content": str,  # Full template content
            "size_bytes": int,
            "line_count": int,
            "fields": list[str],
            "header": str  # First 5 lines preview
        }
    
    Purpose: Get full template content ONLY for selected templates.
    Avoids loading all templates in search results.
    
    Workflow:
    1. search_ntc_templates() returns 5 results with paths
    2. LLM/User selects top 1-2 most relevant
    3. read_template_file() loads only selected ones
    → Saves tokens (5 templates metadata vs 1-2 full templates)
    
    Example:
        >>> search = search_ntc_templates("cisco_ios", "show version", ["version"])
        >>> template_path = search["results"][0]["template_path"]
        >>> full_template = read_template_file(template_path)
        {"content": "Value VERSION (\\S+)\\n...", "fields": ["VERSION", ...]}
    """
    path = Path(template_path)

    if not path.exists():
        logger.error(f"Template not found: {template_path}")
        return {
            "error": f"Template not found: {template_path}",
            "template_name": None,
            "content": None
        }

    try:
        # Read full content
        content = path.read_text()

        # Extract fields
        fields = extract_textfsm_fields(content)

        # Header preview (first 5 lines)
        lines = content.splitlines()
        header = "\n".join(lines[:5])

        logger.info(f"Read template: {path.name} ({len(fields)} fields, {len(lines)} lines)")

        return {
            "template_name": path.name,
            "content": content,
            "size_bytes": path.stat().st_size,
            "line_count": len(lines),
            "fields": fields,
            "header": header
        }

    except Exception as e:
        logger.error(f"Failed to read template {path.name}: {e}")
        return {
            "error": str(e),
            "template_name": path.name,
            "content": None
        }
