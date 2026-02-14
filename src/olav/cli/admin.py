#!/usr/bin/env python3
"""
Admin CLI - System administration commands for OLAV.

v2.1.0 (Ultra-Minimalist):
- Fast-path commands for common operations (status, backup, etc.)
- Admin Agent for complex tasks (AI-powered, natural language)

Usage:
    from olav.cli.admin import admin_handler
    result = await admin_handler("/admin status")
    result = await admin_handler("/admin backup")
    result = await admin_handler("/admin 'create monitoring skill'")
"""

import json
import logging
import shutil
import tarfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


async def admin_handler(command: str) -> dict:
    """Main handler for admin commands.
    
    Args:
        command: Command string (e.g., "/admin status", "/admin 'create skill'")
    
    Returns:
        Dict with status and result
    """
    # Parse command
    parts = command.split(maxsplit=2)  # Split into 3 parts: /admin, cmd, args
    if len(parts) < 2 or parts[0] != "/admin":
        return {"status": "error", "message": "Invalid command format. Use /admin <command>"}

    cmd_name = parts[1]
    cmd_args = parts[2] if len(parts) > 2 else ""

    # Fast-path commands (direct Python implementation, <100ms)
    fast_commands = {
        "status": _fast_status,
        "backup": _fast_backup,
        "restore": _fast_restore,
        "db-info": _fast_db_info,
        "skill-list": _fast_skill_list,
    }

    if cmd_name in fast_commands:
        try:
            return await fast_commands[cmd_name](cmd_args)
        except Exception as e:
            logger.error(f"Fast command failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    # Complex tasks → Admin Agent (AI-powered, natural language)
    # Examples:
    #   /admin "create monitoring skill"
    #   /admin "search for execute_sql usage"
    #   /admin "backup and test new feature"
    try:
        from olav.agents.admin_agent import AdminAgent
        
        agent = AdminAgent()
        
        # Reconstruct user query (remove /admin prefix)
        user_query = cmd_name if not cmd_args else f"{cmd_name} {cmd_args}"
        
        logger.info(f"Invoking Admin Agent: {user_query}")
        
        response = await agent.ainvoke(user_query)
        
        return {
            "status": "success",
            "response": response,
            "message": "Admin Agent completed task"
        }
    
    except Exception as e:
        logger.error(f"Admin Agent failed: {e}", exc_info=True)
        return {"status": "error", "message": f"Admin Agent error: {e}"}


# ============================================================================
# Fast-path Commands (<100ms) - Direct Python implementations
# ============================================================================

async def _fast_status(args: str) -> dict:
    """System status check."""
    try:
        base_path = Path(".olav")
        db_path = base_path / "databases"
        
        status_info = {
            "timestamp": datetime.now().isoformat(),
            "databases": {},
            "skills_count": 0,
            "tools_count": 0,
        }
        
        # Database info
        if db_path.exists():
            for db in ["main.duckdb", "agent.duckdb", "admin_agent.duckdb", "llm_cache.db"]:
                db_file = db_path / db
                if db_file.exists():
                    size_mb = db_file.stat().st_size / (1024 * 1024)
                    status_info["databases"][db] = f"{size_mb:.2f} MB"
        
        # Skills count
        skills_path = base_path / "skills"
        if skills_path.exists():
            status_info["skills_count"] = len(list(skills_path.glob("*/SKILL.md")))
        
        # Tools count
        tools_path = base_path / "tools"
        if tools_path.exists():
            status_info["tools_count"] = len(list(tools_path.glob("*.py")))
        
        return {"status": "success", "data": status_info}
    
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def _fast_backup(args: str) -> dict:
    """Export all databases as tar.gz backup."""
    try:
        base_path = Path(".olav")
        db_path = base_path / "databases"
        backup_path = base_path / "backups"
        backup_path.mkdir(parents=True, exist_ok=True)
        
        # Generate backup filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_file = backup_path / f"backup_{timestamp}.tar.gz"
        
        # Create tar.gz
        with tarfile.open(target_file, "w:gz") as tar:
            if db_path.exists():
                for db_file in db_path.glob("**/*.duckdb*"):
                    if db_file.is_file():
                        tar.add(db_file, arcname=db_file.relative_to(base_path))
                for db_file in db_path.glob("**/*.db"):
                    if db_file.is_file():
                        tar.add(db_file, arcname=db_file.relative_to(base_path))
        
        size_mb = target_file.stat().st_size / (1024 * 1024)
        
        return {
            "status": "success",
            "backup_file": str(target_file),
            "size_mb": f"{size_mb:.2f}"
        }
    
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def _fast_restore(args: str) -> dict:
    """Restore from backup tar.gz file."""
    if not args:
        return {"status": "error", "message": "Backup file path required"}
    
    try:
        backup_file = Path(args)
        if not backup_file.exists():
            return {"status": "error", "message": f"Backup file not found: {args}"}
        
        base_path = Path(".olav")
        temp_dir = base_path / ".restore_temp"
        temp_dir.mkdir(exist_ok=True)
        
        # Extract backup
        with tarfile.open(backup_file, "r:gz") as tar:
            tar.extractall(path=temp_dir)
        
        # Move files back
        db_path = base_path / "databases"
        for db_file in temp_dir.rglob("*.duckdb*"):
            target = db_path / db_file.relative_to(temp_dir / "databases")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(db_file), str(target))
        
        for db_file in temp_dir.rglob("*.db"):
            target = db_path / db_file.relative_to(temp_dir / "databases")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(db_file), str(target))
        
        # Cleanup
        shutil.rmtree(temp_dir)
        
        return {"status": "success", "message": "Restore completed"}
    
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def _fast_db_info(args: str) -> dict:
    """Database information."""
    try:
        base_path = Path(".olav")
        db_path = base_path / "databases"
        
        db_info = {}
        if db_path.exists():
            for db_file in db_path.glob("**/*"):
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


async def _fast_skill_list(args: str) -> dict:
    """List all available skills."""
    try:
        base_path = Path(".olav")
        skills_path = base_path / "skills"
        
        skills = []
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


if __name__ == "__main__":
    import asyncio

    async def main():
        result = await admin_handler("/admin status")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    asyncio.run(main())

