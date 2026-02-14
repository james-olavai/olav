"""
JSON Metadata Extractor - Generate dynamic field mappings from actual database

Principle: Schema should be derived from actual data, not hardcoded
"""

import json
from pathlib import Path
from typing import Any


def analyze_database_json_schema(conn: Any) -> dict[str, list[str]]:
    """Analyze actual JSON structure in parsed_outputs to generate field mappings.
    
    This function examines the actual data in the database and extracts the
    real field names present, rather than relying on hardcoded assumptions.
    
    Args:
        conn: DuckDB connection
    
    Returns:
        Dictionary mapping commands to their JSON field names
    """
    command_fields = {}
    
    try:
        # Get distinct commands
        commands = conn.execute("""
            SELECT DISTINCT command FROM parsed_outputs 
            ORDER BY command
        """).fetchall()
        
        for (cmd,) in commands:
            # Get a sample of parsed_data for this command
            sample = conn.execute("""
                SELECT parsed_data FROM parsed_outputs 
                WHERE command = ? LIMIT 1
            """, [cmd]).fetchone()
            
            if sample:
                try:
                    data_str = sample[0]
                    parsed = json.loads(data_str)
                    
                    # Extract field names from first array element if it's a dict
                    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                        fields = list(parsed[0].keys())
                        command_fields[cmd] = fields
                except Exception:
                    pass  # Skip if JSON parsing fails
    
    except Exception as e:
        print(f"Warning: Failed to analyze JSON schema: {e}")
    
    return command_fields


def generate_json_field_reference(command_fields: dict[str, list[str]]) -> str:
    """Generate markdown reference guide from analyzed command fields.
    
    Args:
        command_fields: Dictionary mapping commands to their fields
    
    Returns:
        Formatted markdown string for system prompt injection
    """
    if not command_fields:
        return ""
    
    lines = ["## Real JSON Fields (From Actual Database)\n"]
    
    # Categorize commands by type
    categories = {
        "interface": [],
        "ip": [],
        "arp": [],
        "neighbor": [],
        "status": [],
        "config": [],
        "other": [],
    }
    
    for cmd, fields in sorted(command_fields.items()):
        cmd_lower = cmd.lower()
        
        # Categorize
        if "interface" in cmd_lower:
            categories["interface"].append((cmd, fields))
        elif "ip" in cmd_lower:
            categories["ip"].append((cmd, fields))
        elif "arp" in cmd_lower:
            categories["arp"].append((cmd, fields))
        elif "neighbor" in cmd_lower or "cdp" in cmd_lower or "lldp" in cmd_lower:
            categories["neighbor"].append((cmd, fields))
        elif "status" in cmd_lower:
            categories["status"].append((cmd, fields))
        elif "config" in cmd_lower or "running" in cmd_lower:
            categories["config"].append((cmd, fields))
        else:
            categories["other"].append((cmd, fields))
    
    # Generate output
    for cat_name in ["interface", "ip", "arp", "neighbor", "status", "config"]:
        commands = categories[cat_name]
        if commands:
            cat_display = cat_name.replace("_", " ").title()
            lines.append(f"### {cat_display} Commands\n")
            for cmd, fields in commands:
                lines.append(f"- `{cmd}` → Fields: {', '.join(f'`{f}`' for f in fields[:8])}")
                if len(fields) > 8:
                    lines.append(f"  (and {len(fields) - 8} more)")
            lines.append("")
    
    if categories["other"]:
        lines.append("### Other Commands\n")
        for cmd, fields in categories["other"]:
            lines.append(f"- `{cmd}` → Fields: {', '.join(f'`{f}`' for f in fields[:8])}")
            if len(fields) > 8:
                lines.append(f"  (and {len(fields) - 8} more)")
    
    return "\n".join(lines)


def inject_json_reference_into_prompt(base_prompt: str, json_reference: str) -> str:
    """Inject dynamic JSON field reference into system prompt.
    
    Args:
        base_prompt: Original system prompt template
        json_reference: Generated markdown reference guide
    
    Returns:
        System prompt with injected reference
    """
    # Find where to insert the reference (after JSON Handling section)
    insertion_marker = "## SQL Best Practices"
    
    if insertion_marker in base_prompt:
        return base_prompt.replace(
            insertion_marker,
            json_reference + "\n\n" + insertion_marker
        )
    else:
        # If marker not found, insert after schema
        return base_prompt.replace(
            "{warnings}",
            "{warnings}\n\n" + json_reference
        )
