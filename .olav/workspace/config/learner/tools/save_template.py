#!/usr/bin/env python3
"""
Tool 7: Save Template (with auto-reload)

Saves TextFSM template and triggers hot-reload.
"""

import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from olav.core.config import TEXTFSM_TEMPLATES_DIR

logger = logging.getLogger(__name__)


def update_index_file(template_path: Path, platform: str, command: str):
    """Update TextFSM index file."""
    index_path = template_path.parent / "index"

    # Read existing index
    if index_path.exists():
        existing_lines = index_path.read_text().splitlines()
    else:
        # Create new index with header
        existing_lines = ["# First line is the header fields for columns and is mandatory."]
        existing_lines.append("# ")
        existing_lines.append("# Template, Hostname, Platform, Command")

    # Check if entry already exists
    new_entry = f"{template_path.name}, , {platform}, {command}"

    # Remove old entry for same template if exists
    filtered_lines = [
        line for line in existing_lines
        if not line.startswith(template_path.name)
    ]

    # Add new entry
    filtered_lines.append(new_entry)

    # Write back
    index_path.write_text("\n".join(filtered_lines) + "\n")
    logger.info(f"Updated index file: {index_path}")


@tool
def save_template(
    template: str,
    filename: str,
    metadata: dict,
    trigger_reload: bool = True,
    templates_dir: str = "",
) -> dict[str, Any]:
    """Save template and trigger reload.
    
    Args:
        template: TextFSM template content
        filename: Template filename (e.g., cisco_ios_show_ip_bgp_summary.textfsm)
        metadata: Metadata dict (command, platform, fields, etc.)
        trigger_reload: Trigger hot-reload (default: True)
        templates_dir: Directory to save custom templates.
                       Default: TEXTFSM_TEMPLATES_DIR/custom (.olav/templates/custom/).
                       Declared in SKILL.md under config.template_dir.
    
    Returns:
        dict: {
            "saved_path": str,
            "metadata_path": str,
            "index_updated": bool,
            "reload_triggered": bool
        }
    
    Side effects:
    1. Save template to .olav/templates/custom/
    2. Save metadata.json
    3. Update index file
    4. Trigger reload_commands() (if enabled)
    
    Example:
        >>> save_template(template_content, "cisco_ios_show_version.textfsm", metadata)
        {"saved_path": ".olav/templates/custom/cisco_ios_show_version.textfsm", ...}
    """
    # Create custom directory if not exists
    custom_dir = Path(templates_dir) if templates_dir else TEXTFSM_TEMPLATES_DIR / "custom"
    custom_dir.mkdir(parents=True, exist_ok=True)

    # Save template file
    template_path = custom_dir / filename
    template_path.write_text(template)
    logger.info(f"Saved template: {template_path}")

    # Save metadata
    metadata_path = custom_dir / f"{filename}.metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2))
    logger.info(f"Saved metadata: {metadata_path}")

    # Update index file
    try:
        update_index_file(
            template_path,
            metadata.get("platform", ""),
            metadata.get("command", "")
        )
        index_updated = True
    except Exception as e:
        logger.error(f"Failed to update index: {e}")
        index_updated = False

    # Trigger reload (if enabled)
    reload_triggered = False
    if trigger_reload:
        try:
            # Import reload function
            from olav.core.command_registry import CommandRegistry
            CommandRegistry.reload()
            reload_triggered = True
            logger.info(f"✅ Auto-reloaded templates (new: {filename})")
        except ImportError:
            logger.warning("CommandRegistry not available - reload skipped")
        except Exception as e:
            logger.error(f"Failed to reload: {e}")

    return {
        "saved_path": str(template_path),
        "metadata_path": str(metadata_path),
        "index_updated": index_updated,
        "reload_triggered": reload_triggered
    }
