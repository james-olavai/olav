#!/usr/bin/env python3
"""
Restore Configuration Tool - Part of system-admin skill.

Restores .olav/ configuration from a previous backup.

Permission Tier: 🟡 Yellow (HITL required)

Usage:
    echo '{"backup_id": "config_20260210_143000", "dry_run": true}' | python3 restore_config.py
"""

import json
import shutil
from pathlib import Path


def _find_project_root():
    """Find project root by looking for pyproject.toml"""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


def _get_config_dir():
    """Get the .olav directory"""
    return _find_project_root() / ".olav"


def _get_backup_dir():
    """Get the config_backups directory"""
    return _find_project_root() / ".olav" / "config_backups"


def main(params: dict) -> dict:
    """Restore configuration from a backup.

    Args:
        params: {
            "backup_id": "config_20260210_143000",
            "dry_run": true  # optional, defaults to true for safety
        }

    Returns:
        {"status": "ok", "message": "...", ...}
    """
    try:
        backup_id = params.get("backup_id")
        dry_run = params.get("dry_run", True)

        if not backup_id:
            return {"status": "error", "message": "Missing 'backup_id' parameter"}

        config_dir = _get_config_dir()
        backup_dir = _get_backup_dir()
        backup_path = backup_dir / backup_id

        if not backup_path.exists():
            return {"status": "error", "message": f"Backup not found: {backup_id}"}

        if dry_run:
            return {
                "status": "ok",
                "message": f"📊 Dry run: Would restore from {backup_id}",
                "backup_path": str(backup_path),
                "dry_run": True,
            }

        # Actual restore
        restored = 0
        for file in ["settings.json", "OLAV.md"]:
            src = backup_path / file
            if src.exists():
                dst = config_dir / file
                shutil.copy2(src, dst)
                restored += 1

        # Restore skills
        skills_src = backup_path / "skills"
        if skills_src.exists():
            skills_dst = config_dir / "skills"
            if skills_dst.exists():
                shutil.rmtree(skills_dst)
            shutil.copytree(skills_src, skills_dst)
            restored += 1

        return {
            "status": "ok",
            "message": f"✅ Configuration restored from {backup_id}",
            "files_restored": restored,
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    try:
        input_str = __import__("sys").stdin.read()
        input_data = json.loads(input_str) if input_str.strip() else {}
        result = main(input_data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e), "status": "failed"}, ensure_ascii=False), file=__import__("sys").stderr)
        __import__("sys").exit(1)
