#!/usr/bin/env python3
"""
Tool 3: Search NTC Templates (Enhanced - Metadata Only)

Searches NTC-templates for similar commands, returns metadata + paths.
Use read_template_file() to get full content of selected templates.
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
        logger.error("ntc-templates not installed. Install with: pip install ntc-templates")
        return None


def score_template_match(
    template_name: str,
    template_fields: list[str],
    platform: str,
    command: str,
    approved_fields: list[str]
) -> float:
    """
    Calculate relevance score for a template.
    
    Scoring factors:
    - Command keyword matches (30%)
    - Field coverage (50%)
    - Platform match (20%)
    
    Returns:
        float: Score between 0.0 and 1.0
    """
    score = 0.0

    # Command keyword match (30%)
    command_keywords = set(command.lower().split())
    template_keywords = set(template_name.lower().replace("_", " ").split())
    if command_keywords and template_keywords:
        keyword_match = len(command_keywords & template_keywords) / len(command_keywords)
        score += keyword_match * 0.3

    # Field coverage (50%)
    if approved_fields and template_fields:
        approved_set = set(f.lower() for f in approved_fields)
        template_set = set(f.lower() for f in template_fields)
        coverage = len(approved_set & template_set) / len(approved_set)
        score += coverage * 0.5

    # Platform match (20%)
    if platform.lower() in template_name.lower():
        score += 0.2

    return round(score, 3)


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
                fields.append(field_name.lower())
    return fields


@tool
def search_ntc_templates(
    platform: str,
    command: str,
    approved_fields: list[str],
    limit: int = 5
) -> dict[str, Any]:
    """Search NTC-templates for similar commands (metadata only).
    
    Args:
        platform: Device platform (e.g., cisco_ios)
        command: Command to search for
        approved_fields: Fields user wants to extract
        limit: Maximum number of results (default: 5)
    
    Returns:
        dict: {
            "ntc_path": str,
            "results": list[dict],  # Template metadata + path (NO full content)
            "total_found": int,
            "search_time": float
        }
    
    Results format:
        [{
            "template_name": str,
            "template_path": str,  # Full path for read_template_file()
            "score": float,
            "command_match": list[str],
            "field_coverage": float,
            "fields_found": list[str],
            "fields_missing": list[str],
            "platform_match": bool,
            "file_size": int
        }]
    
    Example:
        >>> search_ntc_templates("cisco_ios", "show ip bgp summary", ["router_id", "neighbor"])
        {"results": [{"template_name": "cisco_ios_show_ip_bgp_summary.textfsm", "score": 0.85, ...}]}
    """
    import time

    start_time = time.time()

    # Find NTC path
    ntc_path = find_ntc_templates_path()
    if not ntc_path or not ntc_path.exists():
        return {
            "ntc_path": None,
            "results": [],
            "total_found": 0,
            "search_time": 0.0,
            "error": "NTC-templates not found"
        }

    # Search templates
    all_templates = list(ntc_path.glob("*.textfsm"))
    scored_templates = []

    for template_path in all_templates:
        # Read template to extract fields (ONLY field names, not full content)
        try:
            content = template_path.read_text()
            template_fields = extract_textfsm_fields(content)
        except Exception as e:
            logger.warning(f"Failed to read {template_path.name}: {e}")
            continue

        # Score template
        score = score_template_match(
            template_path.name,
            template_fields,
            platform,
            command,
            approved_fields
        )

        # Only include if score > 0
        if score > 0:
            # Calculate field coverage details
            approved_set = set(f.lower() for f in approved_fields)
            template_set = set(template_fields)
            fields_found = list(approved_set & template_set)
            fields_missing = list(approved_set - template_set)

            # Command keyword match
            command_keywords = set(command.lower().split())
            template_keywords = set(template_path.stem.lower().replace("_", " ").split())
            command_match = list(command_keywords & template_keywords)

            scored_templates.append({
                "template_name": template_path.name,
                "template_path": str(template_path),  # Full path for read_template_file()
                "score": score,
                "command_match": command_match,
                "field_coverage": round(len(fields_found) / len(approved_fields), 2) if approved_fields else 0.0,
                "fields_found": fields_found,
                "fields_missing": fields_missing,
                "platform_match": platform.lower() in template_path.name.lower(),
                "file_size": template_path.stat().st_size
            })

    # Sort by score
    scored_templates.sort(key=lambda x: x["score"], reverse=True)

    # Limit results
    results = scored_templates[:limit]

    search_time = time.time() - start_time

    logger.info(f"NTC search: {len(results)}/{len(all_templates)} templates matched (platform={platform}, command={command})")

    return {
        "ntc_path": str(ntc_path),
        "results": results,
        "total_found": len(scored_templates),
        "search_time": round(search_time, 2)
    }
