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
      1. .olav/templates/{platform}_{cmd}.textfsm
      2. NTC-templates (if available)

    Returns:
        (template_path, template_content) or (None, None) if not found.
    """
    from olav.core.config import TEXTFSM_TEMPLATES_DIR

    template_dirs = [
        Path(TEXTFSM_TEMPLATES_DIR),
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


def _get_devices_for_platform(platform: str) -> list[str]:
    """Return all device names for a given platform from DuckDB."""
    try:
        from olav.core.database import get_database
        db = get_database()
        rows = db.conn.execute(
            "SELECT name FROM devices WHERE platform = ? ORDER BY name",
            [platform],
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


# ==================== Main Tool ====================

@tool
def reparse_outputs(device: str = "", command: str = "", platform: str = "") -> dict:
    """Re-parse local raw output files using current TextFSM template.

    Supports three calling modes:
    - ``device`` + ``command``          → single device (original behaviour)
    - ``platform`` + ``command``        → batch: all devices of that platform
    - ``command`` only (no device/plat) → batch: all devices for that command

    Args:
        device:   Device name (e.g. "R1"). Ignored when ``platform`` is given.
        command:  Command string (e.g. "show interfaces").
        platform: Platform name (e.g. "cisco_ios").  When provided, reparsing
                  runs on ALL devices of that platform.

    Returns:
        dict with keys:
        - success: bool
        - snapshot_id: str
        - records: int  (total records parsed across all devices)
        - devices_updated: list[str]
        - errors: list[str]|None
    """
    # ── Determine target device list ─────────────────────────────────────────
    if platform:
        targets = _get_devices_for_platform(platform)
        if not targets:
            return {
                "success": False,
                "snapshot_id": None,
                "records": 0,
                "devices_updated": [],
                "error": f"No devices found for platform '{platform}'",
            }
    elif device:
        targets = [device]
    else:
        return {
            "success": False,
            "snapshot_id": None,
            "records": 0,
            "devices_updated": [],
            "error": "Provide either 'device' or 'platform'",
        }

    total_records = 0
    updated: list[str] = []
    errors: list[str] = []
    snapshot_id_out: str | None = None

    for dev in targets:
        result = _reparse_single(dev, command)
        if result.get("success"):
            total_records += result.get("records", 0)
            updated.append(dev)
            if snapshot_id_out is None:
                snapshot_id_out = result.get("snapshot_id")
        else:
            errors.append(f"{dev}: {result.get('error', 'unknown')}")

    return {
        "success": len(updated) > 0,
        "snapshot_id": snapshot_id_out,
        "records": total_records,
        "devices_updated": updated,
        "errors": errors if errors else None,
    }


def _reparse_single(device: str, command: str) -> dict:
    """Reparse a single (device, command) pair — core logic, no @tool overhead."""
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

        snapshot_id = raw_file.parent.parent.parent.name

        # Step 2: Read raw output
        try:
            raw_output = raw_file.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"success": False, "snapshot_id": snapshot_id, "records": 0, "error": f"Read failed: {e}"}

        if not raw_output.strip():
            return {"success": False, "snapshot_id": snapshot_id, "records": 0, "error": "Raw file is empty"}

        # Step 3: Platform + template
        platform = _get_device_platform(device)
        if not platform:
            return {"success": False, "snapshot_id": snapshot_id, "records": 0, "error": f"No platform for {device}"}

        tmpl_path, tmpl_content = _find_textfsm_template(platform, command)
        if tmpl_content is None:
            return {
                "success": False,
                "snapshot_id": snapshot_id,
                "records": 0,
                "error": f"No template for {platform}/{command}",
            }
        if not tmpl_content.strip():
            return {"success": True, "snapshot_id": snapshot_id, "records": 0, "note": "Raw-only template"}

        # Step 4: Parse
        try:
            import textfsm
            fsm = textfsm.TextFSM(_io.StringIO(tmpl_content))
            fsm_rows = fsm.ParseText(raw_output)
            if fsm_rows:
                headers = [h.lower() for h in fsm.header]
                records_list = [dict(zip(headers, row, strict=False)) for row in fsm_rows]
                parsed_data = _json.dumps(records_list)
                record_count = len(records_list)
            else:
                parsed_data = _json.dumps([])
                record_count = 0
        except Exception as e:
            return {"success": False, "snapshot_id": snapshot_id, "records": 0, "error": f"TextFSM: {e}"}

        # Step 5: Upsert DB
        try:
            db = get_database()
            db.conn.execute(
                """
                INSERT INTO parsed_outputs (device_name, command, parsed_data, snapshot_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (device_name, command, snapshot_id)
                DO UPDATE SET parsed_data = EXCLUDED.parsed_data
                """,
                [device, command, parsed_data, snapshot_id],
            )
            logger.info("reparse_single: %s/%s → %d records", device, command, record_count)
            return {
                "success": True,
                "snapshot_id": snapshot_id,
                "records": record_count,
                "raw_file": str(raw_file),
                "template_file": str(tmpl_path) if tmpl_path else "NTC-templates",
            }
        except Exception as e:
            return {"success": False, "snapshot_id": snapshot_id, "records": 0, "error": f"DB upsert: {e}"}

    except Exception as e:
        logger.error("_reparse_single exception: %s", e, exc_info=True)
        return {"success": False, "snapshot_id": None, "records": 0, "error": str(e)}


# ==================== For direct invocation ====================

def reparse_outputs_func(device: str = "", command: str = "", platform: str = "") -> dict:
    """Direct function wrapper (for non-LLM contexts)."""
    return reparse_outputs.func(device=device, command=command, platform=platform)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <device|--platform PLATFORM> <command>")
        sys.exit(1)

    if sys.argv[1] == "--platform":
        _plat, _cmd = sys.argv[2], sys.argv[3]
        _result = reparse_outputs_func(platform=_plat, command=_cmd)
    else:
        _dev, _cmd = sys.argv[1], sys.argv[2]
        _result = reparse_outputs_func(device=_dev, command=_cmd)
    print(_json.dumps(_result, indent=2))
