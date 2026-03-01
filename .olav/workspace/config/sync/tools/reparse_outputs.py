"""Reparse local raw outputs with current TextFSM templates.

Used after template repairs to validate parsing without SSH re-collection.

Process:
  1. Find raw file in exports/snapshots/latest/raw/{device}/{command}.txt
  2. Load current TextFSM template for {device.platform, command}
  3. Parse raw output with new template
  4. Update parsed_outputs table with new results (same snapshot_id)
  5. Return: success, record_count, errors

No SSH connection required.
"""

from __future__ import annotations

import io as _io
import json as _json
import logging
import sys
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# ==================== Module-level utilities ====================

def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()

# Make same-directory tools importable
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


# ==================== Core Logic ====================

def _find_raw_file(device: str, command: str) -> Path | None:
    """Find raw output file for device/command.
    
    Looks in:
      1. exports/snapshots/latest/raw/{device}/{command_slug}.txt
      2. Falls back to most recent dated snapshot
    
    Returns:
        Path if found, None otherwise.
    """
    from sync_tools import get_latest_sync_dir, get_sync_base_dir
    
    # Try latest symlink first
    latest_dir = get_latest_sync_dir()
    if latest_dir:
        raw_dir = latest_dir / "raw" / device
        if raw_dir.exists():
            cmd_slug = command.replace(" ", "_")
            raw_file = raw_dir / f"{cmd_slug}.txt"
            if raw_file.exists():
                return raw_file
    
    # Fallback: search all snapshots (most recent first)
    base = get_sync_base_dir()
    if base.exists():
        for snap_dir in sorted(base.glob("[0-9]*"), reverse=True):
            raw_dir = snap_dir / "raw" / device
            if raw_dir.exists():
                cmd_slug = command.replace(" ", "_")
                raw_file = raw_dir / f"{cmd_slug}.txt"
                if raw_file.exists():
                    return raw_file
    
    return None


def _find_textfsm_template(platform: str, command: str) -> tuple[Path | None, str | None]:
    """Find and load TextFSM template for platform/command.
    
    Priority:
      1. .olav/templates/custom/{platform}_{cmd}.textfsm
      2. .olav/templates/{platform}_{cmd}.textfsm
      3. NTC-templates (if available)
    
    Returns:
        (template_path, template_content) or (None, None) if not found.
    """
    template_dirs = [
        PROJECT_ROOT / ".olav" / "templates" / "custom",
        PROJECT_ROOT / ".olav" / "templates",
    ]
    
    cmd_slug = command.replace(" ", "_")
    template_name = f"{platform}_{cmd_slug}.textfsm"
    
    for tmpl_dir in template_dirs:
        if tmpl_dir.exists():
            tmpl_path = tmpl_dir / template_name
            if tmpl_path.exists():
                try:
                    content = tmpl_path.read_text(encoding="utf-8")
                    return tmpl_path, content
                except Exception as e:
                    logger.warning(f"Failed to read template {tmpl_path}: {e}")
    
    # NTC-templates fallback (optional)
    try:
        from ntc_templates.get_template import get_template
        # e.g., "arista_eos" -> "show_version.textfsm"
        tmpl_content = get_template(
            platform=platform,
            command=command,
            netmiko=False  # Use textfsm format
        )
        if tmpl_content:
            return None, tmpl_content  # No file path, just content
    except Exception:
        pass
    
    return None, None


def _get_device_platform(device: str) -> str:
    """Query device platform from DuckDB."""
    try:
        from olav.core.database import get_database
        db = get_database()
        result = db.conn.execute(
            "SELECT platform FROM devices WHERE name = ?",
            [device]
        ).fetchone()
        return result[0] if result else ""
    except Exception:
        return ""


# ==================== Main Tool ====================

@tool
def reparse_outputs(device: str, command: str) -> dict:
    """Re-parse local raw output files using current TextFSM template.
    
    Args:
        device: Device name (e.g. "R1")
        command: Command name (e.g. "show interfaces terse")
    
    Returns:
        dict with keys:
        - success: bool
        - snapshot_id: str (updated snapshot_id)
        - records: int (number of records parsed)
        - error: str|None (error message if any)
    
    Process:
        1. Find raw file from latest snapshot
        2. Load current template for this device's platform
        3. Parse with TextFSM
        4. Update parsed_outputs table (same snapshot_id, new parsed_data)
        5. Report results
    
    No SSH required!
    """
    try:
        from olav.core.database import get_database
        
        # Step 1: Find raw file
        raw_file = _find_raw_file(device, command)
        if not raw_file:
            return {
                "success": False,
                "snapshot_id": None,
                "records": 0,
                "error": f"No raw file found for {device}/{command}",
            }
        
        # Extract snapshot_id from path (e.g., "2026-03-01_0945")
        snapshot_id = raw_file.parent.parent.parent.name
        
        # Step 2: Read raw output
        try:
            raw_output = raw_file.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {
                "success": False,
                "snapshot_id": snapshot_id,
                "records": 0,
                "error": f"Failed to read raw file: {e}",
            }
        
        if not raw_output.strip():
            return {
                "success": False,
                "snapshot_id": snapshot_id,
                "records": 0,
                "error": "Raw file is empty",
            }
        
        # Step 3: Get device platform and find template
        platform = _get_device_platform(device)
        if not platform:
            return {
                "success": False,
                "snapshot_id": snapshot_id,
                "records": 0,
                "error": f"Device {device} not found in database (no platform)",
            }
        
        tmpl_path, tmpl_content = _find_textfsm_template(platform, command)
        if tmpl_content is None:
            return {
                "success": False,
                "snapshot_id": snapshot_id,
                "records": 0,
                "error": f"No TextFSM template found for {platform}/{command}",
            }
        
        if not tmpl_content.strip():
            # Empty template = intentional raw-only collection
            return {
                "success": True,
                "snapshot_id": snapshot_id,
                "records": 0,
                "note": "Empty template (raw-only collection) — no update needed",
            }
        
        # Step 4: Parse with TextFSM
        try:
            import textfsm
            fsm = textfsm.TextFSM(_io.StringIO(tmpl_content))
            fsm_rows = fsm.ParseText(raw_output)
            
            if fsm_rows:
                headers = [h.lower() for h in fsm.header]
                records = [
                    dict(zip(headers, row, strict=False)) for row in fsm_rows
                ]
                parsed_data = _json.dumps(records)
            else:
                # No match but template exists
                parsed_data = _json.dumps([])
        except Exception as e:
            return {
                "success": False,
                "snapshot_id": snapshot_id,
                "records": 0,
                "error": f"TextFSM parse failed: {e}",
            }
        
        # Step 5: Update database
        try:
            db = get_database()
            
            # Upsert: if record exists, update parsed_data
            db.conn.execute(
                """
                INSERT INTO parsed_outputs (device_name, command, parsed_data, snapshot_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (device_name, command, snapshot_id)
                DO UPDATE SET parsed_data = EXCLUDED.parsed_data
                """,
                [device, command, parsed_data, snapshot_id]
            )
            
            record_count = len(records) if fsm_rows else 0
            
            logger.info(
                "reparse_outputs: %s/%s updated with %d records from %s",
                device, command, record_count, raw_file.name
            )
            
            return {
                "success": True,
                "snapshot_id": snapshot_id,
                "records": record_count,
                "raw_file": str(raw_file),
                "template_file": str(tmpl_path) if tmpl_path else "NTC-templates",
            }
        
        except Exception as e:
            return {
                "success": False,
                "snapshot_id": snapshot_id,
                "records": 0,
                "error": f"Failed to update database: {e}",
            }
    
    except Exception as e:
        logger.error(f"reparse_outputs exception: {e}", exc_info=True)
        return {
            "success": False,
            "snapshot_id": None,
            "records": 0,
            "error": f"Unexpected error: {e}",
        }


# ==================== For direct invocation ====================

def reparse_outputs_func(device: str, command: str) -> dict:
    """Direct function wrapper (for non-LLM contexts)."""
    return reparse_outputs(device=device, command=command)


if __name__ == "__main__":
    # Example: python reparse_outputs.py R1 "show ip bgp"
    import sys
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <device> <command>")
        sys.exit(1)
    
    device = sys.argv[1]
    command = sys.argv[2]
    result = reparse_outputs_func(device, command)
    print(_json.dumps(result, indent=2))
