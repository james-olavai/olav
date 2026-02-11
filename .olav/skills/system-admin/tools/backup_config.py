#!/usr/bin/env python3
"""
Backup Configuration Tool - Part of system-admin skill.

Creates timestamped backups of .olav/ directory configuration.

Permission Tier: 🟡 Yellow (HITL required)

Usage:
    echo '{"label": "before_device_add"}' | python3 backup_config.py
"""

import json
import shutil
from datetime import datetime
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
    """Create configuration backup.

    Creates a timestamped backup of:
    - .olav/settings.json
    - .olav/OLAV.md
    - .olav/skills/ directory

    Args:
        params: {
            "label": "before_device_add"  # optional
        }

    Returns:
        {"status": "ok", "backup_path": "...", ...}
    """
    try:
        config_dir = _get_config_dir()
        backup_dir = _get_backup_dir()
        backup_dir.mkdir(parents=True, exist_ok=True)

        label = params.get("label", "")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"config_{timestamp}"
        if label:
            backup_name += f"_{label}"

        backup_path = backup_dir / backup_name
        backup_path.mkdir(exist_ok=True)

        # Backup key files
        files_to_backup = [
            (config_dir / "settings.json", "settings.json"),
            (config_dir / "OLAV.md", "OLAV.md"),
        ]

        backed_up = 0
        for src, filename in files_to_backup:
            if src.exists():
                shutil.copy2(src, backup_path / filename)
                backed_up += 1

        # Backup skills directory
        skills_src = config_dir / "skills"
        if skills_src.exists():
            skills_dst = backup_path / "skills"
            if skills_dst.exists():
                shutil.rmtree(skills_dst)
            shutil.copytree(skills_src, skills_dst)
            backed_up += 1

        # Create manifest
        manifest = {
            "timestamp": datetime.now().isoformat(),
            "label": label,
            "files_backed_up": backed_up,
            "backup_path": str(backup_path),
        }

        with open(backup_path / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)

        return {
            "status": "ok",
            "message": f"✅ Backup created: {backup_name}",
            "backup_path": str(backup_path),
            "files": backed_up,
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
