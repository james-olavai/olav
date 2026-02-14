#!/usr/bin/env python3
"""
Admin CLI - System administration commands for OLAV.

Fast-path commands (<100ms):
- /admin backup      - Export all databases
- /admin restore     - Restore from backup  
- /admin status      - System status check
- /admin db-info     - Database info
- /admin skill-list  - List loaded skills
- /admin skill-reload - Reload skill
- /admin schema-sync - Sync schema to DuckDB
- /admin cron-list   - List scheduled tasks
- /admin cron-add    - Add scheduled task

Usage:
    from olav.cli.admin import admin_handler
    result = await admin_handler("/admin status")
"""

import json
import logging
import shutil
import tarfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class AdminCommand:
    """Handler for admin commands."""

    def __init__(self, base_path: Path | str = ".olav"):
        self.base_path = Path(base_path)
        self.db_path = self.base_path / "databases"
        self.backup_path = self.base_path / "backups"
        self.backup_path.mkdir(parents=True, exist_ok=True)

    async def status(self) -> dict:
        """System status check."""
        try:
            status_info = {
                "timestamp": datetime.now().isoformat(),
                "databases": {
                    "main": self.db_path / "main.duckdb" if (self.db_path / "main.duckdb").exists() else None,
                    "agent": self.db_path / "agent.duckdb" if (self.db_path / "agent.duckdb").exists() else None,
                    "llm_cache": self.db_path / "llm_cache.db" if (self.db_path / "llm_cache.db").exists() else None,
                },
                "skills_count": len(list((self.base_path / "skills").glob("*/SKILL.md"))) if (self.base_path / "skills").exists() else 0,
                "tools_count": len(list((self.base_path / "tools").glob("*.py"))) if (self.base_path / "tools").exists() else 0,
            }
            return {"status": "success", "data": status_info}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def backup(self, target_path: str | None = None) -> dict:
        """Export all databases as tar.gz backup."""
        try:
            if not target_path:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                target_path = str(self.backup_path / f"backup_{timestamp}.tar.gz")

            target_file = Path(target_path)
            target_file.parent.mkdir(parents=True, exist_ok=True)

            with tarfile.open(target_file, "w:gz") as tar:
                for db_file in self.db_path.glob("**/*.duckdb*"):
                    if db_file.is_file():
                        tar.add(db_file, arcname=db_file.relative_to(self.base_path))
                for db_file in self.db_path.glob("**/*.db"):
                    if db_file.is_file():
                        tar.add(db_file, arcname=db_file.relative_to(self.base_path))

            return {
                "status": "success",
                "backup_file": str(target_file),
                "size_bytes": target_file.stat().st_size
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def restore(self, backup_path: str) -> dict:
        """Restore from backup tar.gz file."""
        try:
            backup_file = Path(backup_path)
            if not backup_file.exists():
                return {"status": "error", "message": f"Backup file not found: {backup_path}"}

            # Create temporary directory for extraction
            temp_dir = self.base_path / ".restore_temp"
            temp_dir.mkdir(exist_ok=True)

            with tarfile.open(backup_file, "r:gz") as tar:
                tar.extractall(path=temp_dir)

            # Copy restored databases back
            for db_file in temp_dir.rglob("*.duckdb*"):
                target = self.db_path / db_file.relative_to(temp_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(db_file), str(target))

            for db_file in temp_dir.rglob("*.db"):
                target = self.db_path / db_file.relative_to(temp_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(db_file), str(target))

            # Cleanup temp directory
            shutil.rmtree(temp_dir)

            return {"status": "success", "message": "Restore completed"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def db_info(self) -> dict:
        """Database information."""
        try:
            db_info = {}
            for db_file in self.db_path.glob("**/*"):
                if db_file.is_file() and db_file.suffix in [".duckdb", ".db"]:
                    size_mb = db_file.stat().st_size / (1024 * 1024)
                    db_info[db_file.name] = {
                        "path": str(db_file),
                        "size_mb": round(size_mb, 2),
                        "modified": datetime.fromtimestamp(db_file.stat().st_mtime).isoformat()
                    }

            return {"status": "success", "databases": db_info}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def skill_list(self) -> dict:
        """List all available skills."""
        try:
            skills = []
            skills_path = self.base_path / "skills"
            if skills_path.exists():
                for skill_dir in skills_path.iterdir():
                    if skill_dir.is_dir():
                        skill_md = skill_dir / "SKILL.md"
                        if skill_md.exists():
                            skills.append({
                                "name": skill_dir.name,
                                "path": str(skill_dir),
                                "file_size": skill_md.stat().st_size
                            })

            return {"status": "success", "skills": skills, "count": len(skills)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def skill_reload(self, skill_name: str) -> dict:
        """Reload a specific skill (not yet implemented)."""
        return {
            "status": "error",
            "message": "Not Implemented: skill_reload requires dynamic skill loading mechanism"
        }

    async def schema_sync(self) -> dict:
        """Sync schema to DuckDB (not yet implemented)."""
        return {
            "status": "error",
            "message": "Not Implemented: schema_sync requires schema introspection and DuckDB sync logic"
        }

    async def cron_list(self) -> dict:
        """List scheduled cron tasks."""
        try:
            cron_tasks = []
            cron_path = self.base_path / "cron"
            if cron_path.exists():
                for task_file in cron_path.glob("*.txt"):
                    cron_tasks.append({
                        "task": task_file.stem,
                        "file": str(task_file)
                    })

            return {"status": "success", "tasks": cron_tasks, "count": len(cron_tasks)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def cron_add(self, schedule: str, command: str) -> dict:
        """Add a cron task (not yet implemented)."""
        return {
            "status": "error",
            "message": "Not Implemented: cron_add requires python-crontab integration"
        }


async def admin_handler(command: str) -> dict:
    """Main handler for admin commands."""
    admin = AdminCommand()

    # Parse command
    parts = command.split()
    if len(parts) < 2 or parts[0] != "/admin":
        return {"status": "error", "message": "Invalid command format. Use /admin <command>"}

    cmd_name = parts[1]
    cmd_args = parts[2:] if len(parts) > 2 else []

    # Dispatch to appropriate handler
    handlers = {
        "status": admin.status,
        "backup": admin.backup,
        "restore": lambda: admin.restore(cmd_args[0]) if cmd_args else admin.restore(None),
        "db-info": admin.db_info,
        "skill-list": admin.skill_list,
        "skill-reload": lambda: admin.skill_reload(cmd_args[0]) if cmd_args else {"status": "error", "message": "Skill name required"},
        "schema-sync": admin.schema_sync,
        "cron-list": admin.cron_list,
        "cron-add": lambda: admin.cron_add(cmd_args[0], " ".join(cmd_args[1:])) if len(cmd_args) > 1 else {"status": "error", "message": "Schedule and command required"},
    }

    if cmd_name not in handlers:
        return {"status": "error", "message": f"Unknown command: {cmd_name}"}

    try:
        result = await handlers[cmd_name]()
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import asyncio

    async def main():
        result = await admin_handler("/admin status")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    asyncio.run(main())
