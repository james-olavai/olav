#!/usr/bin/env python3
"""
NTC-Templates Local Search Tool

Searches for NetworkToCode templates locally without internet access.
Provides field-aware scoring and platform-specific matching.

Usage:
    python ntc_search.py --platform cisco_ios --command "show bgp summary" --fields "router_id,neighbors,state"
"""

import sys
import json
import logging
from pathlib import Path
from typing import Any
import argparse

logger = logging.getLogger(__name__)


def find_ntc_path() -> Path | None:
    """
    Locate ntc-templates installation directory.
    
    Returns:
        Path to ntc-templates directory or None if not found
    """
    try:
        import ntc_templates
        return Path(ntc_templates.__file__).parent / "templates"
    except ImportError:
        logger.error("ntc-templates not installed. Install with: pip install ntc-templates")
        return None


def score_template_match(
    template_name: str,
    template_content: str,
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
    
    Args:
        template_name: Name of template file
        template_content: Content of template
        platform: Target platform
        command: Target command
        approved_fields: Fields user wants to extract
        
    Returns:
        Score between 0.0 and 1.0
    """
    score = 0.0
    
    # Factor 1: Command keyword matching (30%)
    cmd_keywords = command.lower().replace(" ", "_").split("_")
    template_name_lower = template_name.lower()
    keyword_matches = sum(1 for kw in cmd_keywords if kw in template_name_lower)
    keyword_score = (keyword_matches / max(len(cmd_keywords), 1)) * 0.3
    score += keyword_score
    
    # Factor 2: Field coverage (50%)
    if approved_fields:
        fields_found = 0
        for field in approved_fields:
            # Check if field is defined in template
            field_patterns = [
                f"Value {field}",  # TextFSM Value definition
                f"${{{field}}}",   # TextFSM variable
                field.lower(),      # Field name (case-insensitive)
            ]
            if any(pattern in template_content for pattern in field_patterns):
                fields_found += 1
        
        field_score = (fields_found / max(len(approved_fields), 1)) * 0.5
        score += field_score
    else:
        score += 0.5  # Default 50% if no fields specified
    
    # Factor 3: Platform match (20%)
    if platform.lower() in template_name.lower():
        score += 0.2
    
    return min(1.0, score)


def search_ntc_templates(
    platform: str,
    command: str,
    approved_fields: list[str] = None,
    limit: int = 3
) -> dict[str, Any]:
    """
    Search NTC templates locally.
    
    Args:
        platform: Device platform (e.g., "cisco_ios")
        command: Command name (e.g., "show bgp summary")
        approved_fields: Fields to match against templates
        limit: Max number of results to return
        
    Returns:
        {
            "references": [
                {
                    "template_name": "...",
                    "path": "...",
                    "relevance_score": 0.92,
                    "field_coverage": ["field1", "field2"],
                    "source": "local_ntc_package"
                },
                ...
            ],
            "source": "local_ntc_package",
            "total_found": 5,
            "search_params": {...}
        }
    """
    if approved_fields is None:
        approved_fields = []
    
    logger.info(f"Searching NTC templates for '{command}' on {platform}")
    
    # Find NTC installation
    ntc_path = find_ntc_path()
    if not ntc_path or not ntc_path.exists():
        logger.error(f"NTC templates path not found: {ntc_path}")
        return {
            "references": [],
            "source": "none",
            "error": "ntc-templates not installed. Install with: pip install ntc-templates",
            "total_found": 0
        }
    
    # Find templates directory for platform
    platform_dir = ntc_path / platform
    if not platform_dir.exists():
        logger.warning(f"Platform directory not found: {platform_dir}")
        return {
            "references": [],
            "source": "local_ntc_package",
            "error": f"No templates for platform: {platform}",
            "total_found": 0
        }
    
    matches = []
    
    # Search all templates in platform directory
    try:
        for template_file in platform_dir.glob("*.textfsm"):
            try:
                with open(template_file, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                
                # Score the template
                relevance = score_template_match(
                    template_file.name,
                    content,
                    platform,
                    command,
                    approved_fields
                )
                
                # Only include if relevance > 0.3 (at least some match)
                if relevance > 0.3:
                    # Extract field coverage
                    field_coverage = []
                    for field in approved_fields:
                        if f"Value {field}" in content or f"${{{field}}}" in content:
                            field_coverage.append(field)
                    
                    matches.append({
                        "template_name": template_file.name,
                        "path": str(template_file),
                        "relevance_score": round(relevance, 2),
                        "field_coverage": field_coverage,
                        "source": "local_ntc_package"
                    })
                    
            except Exception as e:
                logger.debug(f"Error reading template {template_file}: {e}")
                continue
    
    except Exception as e:
        logger.error(f"Error searching templates: {e}")
        return {
            "references": [],
            "source": "none",
            "error": f"Error searching templates: {str(e)}",
            "total_found": 0
        }
    
    # Sort by relevance score (descending)
    matches.sort(key=lambda x: x["relevance_score"], reverse=True)
    
    # Limit results
    results = matches[:limit]
    
    logger.info(f"Found {len(results)} matching templates (out of {len(matches)} candidates)")
    
    return {
        "references": results,
        "source": "local_ntc_package",
        "total_found": len(matches),
        "search_params": {
            "platform": platform,
            "command": command,
            "fields": approved_fields,
            "limit": limit
        }
    }


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Search NTC-Templates locally"
    )
    parser.add_argument(
        "--platform",
        required=True,
        help="Device platform (e.g., cisco_ios)"
    )
    parser.add_argument(
        "--command",
        required=True,
        help="Command name (e.g., show bgp summary)"
    )
    parser.add_argument(
        "--fields",
        default="",
        help="Comma-separated field names (e.g., router_id,neighbors)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Max number of results (default: 3)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s: %(message)s"
    )
    
    # Parse fields
    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    
    # Search
    result = search_ntc_templates(
        platform=args.platform,
        command=args.command,
        approved_fields=fields,
        limit=args.limit
    )
    
    # Output as JSON
    print(json.dumps(result, indent=2))
    
    # Exit with appropriate code
    sys.exit(0 if result["references"] else 1)


if __name__ == "__main__":
    main()
