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
        "reload-commands": _fast_reload,  # Hot-reload templates and commands
        "reload": _fast_reload,  # Alias
        # Knowledge Base Management (NEW - Phase 3)
        "kb-status": _kb_status,
        "kb-index": _kb_index,
        "kb-search": _kb_search,
        "kb-reload": _kb_reload,
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
        from olav.agents.admin_agent_v3 import AdminAgent
        
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


async def _fast_reload(args: str) -> dict:
    """Hot-reload TextFSM templates and command definitions.
    
    Reloads:
    1. TextFSM templates (.olav/templates/*)
    2. Command whitelist (.olav/config/allowed_commands.json)
    3. Command blacklist (.olav/config/blacklisted_commands.json)
    
    Returns:
        Status with reload statistics
    """
    try:
        from olav.core.command_registry import CommandRegistry
        
        result = CommandRegistry.reload()
        
        reloaded = result.get("reloaded", {})
        new_templates = result.get("new_templates", [])
        errors = result.get("errors", [])
        
        message = f"✅ Reloaded {reloaded.get('templates', 0)} templates, " \
                  f"{reloaded.get('whitelisted_commands', 0)} commands, " \
                  f"{reloaded.get('blacklisted_patterns', 0)} blacklist patterns"
        
        if new_templates:
            message += f"\n\n🆕 New templates:\n   - " + "\n   - ".join(new_templates)
        
        if errors:
            message += f"\n\n⚠️  Errors:\n   - " + "\n   - ".join(errors)
        
        return {
            "status": "success",
            "message": message,
            "reloaded": reloaded,
            "new_templates": new_templates,
            "errors": errors
        }
    
    except Exception as e:
        logger.error(f"Reload failed: {e}", exc_info=True)
        return {"status": "error", "message": f"Reload failed: {e}"}


# ============================================================================
# Knowledge Base Management (Phase 3)
# ============================================================================

async def _kb_status(args: str) -> dict:
    """Get knowledge base statistics and status."""
    try:
        from src.olav.lib.kb_manager import KnowledgeBaseManager
        
        manager = KnowledgeBaseManager()
        status = manager.get_status()
        
        message = "📚 Knowledge Base Status\n"
        message += f"  Directory: {status['knowledge_dir']}\n"
        message += f"  Files: {status['file_count']}\n"
        message += f"  Chunks: {status['total_chunks']}\n"
        message += f"  Indexed: {status['indexed_chunks']} ({status['indexed_percentage']:.1f}%)\n"
        
        return {
            "status": "success",
            "message": message,
            "statistics": status
        }
    except Exception as e:
        logger.error(f"KB status failed: {e}")
        return {"status": "error", "message": f"KB status failed: {e}"}


async def _kb_index(args: str) -> dict:
    """Index knowledge files. Usage: /admin kb-index or /admin kb-index rebuild"""
    try:
        from src.olav.lib.kb_manager import reload_knowledge_base
        
        rebuild = "rebuild" in args.lower() or "force" in args.lower()
        
        message = "🔍 Indexing knowledge base...\n"
        
        result = reload_knowledge_base(force=rebuild, incremental=not rebuild)
        
        if result['success']:
            stats = result['stats']
            message += f"✅ Indexed {stats['total_indexed']} chunks\n"
            message += f"   Files: {stats['files_processed']}\n"
            if rebuild:
                message += f"   Rebuild: All files reindexed\n"
            else:
                message += f"   Skipped: {stats.get('files_skipped', 0)} (unchanged)\n"
                message += f"   Modified: {stats.get('files_modified', 0)}\n"
        else:
            message += f"❌ Error: {result.get('error', 'Unknown')}\n"
        
        return {
            "status": "success" if result['success'] else "error",
            "message": message,
            "result": result
        }
    except ValueError as e:
        if "LLM_API_KEY" in str(e) or "api_key" in str(e):
            return {
                "status": "error",
                "message": "❌ LLM API key not configured. Set LLM_API_KEY environment variable or in settings.json"
            }
        raise
    except Exception as e:
        logger.error(f"KB index failed: {e}")
        return {"status": "error", "message": f"KB index failed: {e}"}


async def _kb_search(args: str) -> dict:
    """Search knowledge base. Usage: /admin kb-search 'your query'"""
    try:
        if not args or args.strip() in ['--help', '-h', '?']:
            return {
                "status": "error",
                "message": "Usage: /admin kb-search 'search query'\nExample: /admin kb-search 'BGP troubleshooting'"
            }
        
        query = args.strip().strip("'\"")
        limit = 3
        message = f"🔍 Search results for: '{query}'\n\n"
        
        try:
            from langchain_community.vectorstores import DuckDB
            from config.paths import MAIN_DB_PATH
            from olav.core.llm import LLMFactory
            from pathlib import Path
            import duckdb
            
            # Check if database exists
            db_path = Path(MAIN_DB_PATH)
            if not db_path.exists():
                return {
                    "status": "error",
                    "message": f"❌ Knowledge base database not found. Run: olav admin kb-index"
                }
            
            # Use LLMFactory for unified provider support (local/openai/other)
            embeddings = LLMFactory.get_embeddings()
            
            # Create persistent connection for vectorstore
            db_conn = duckdb.connect(str(db_path), read_only=False)
            vectorstore = DuckDB(
                connection=db_conn,
                embedding=embeddings,
                table_name="knowledge_chunks"
            )
            
            # Perform search
            results = vectorstore.similarity_search(query, k=limit)
            
            if not results:
                message += "⚠️  No relevant results found"
            else:
                for i, doc in enumerate(results, 1):
                    source = doc.metadata.get('source_file', 'Unknown')
                    content = doc.page_content[:150]
                    
                    message += f"[{i}] - {source}\n"
                    message += f"    {content}...\n\n"
            
            db_conn.close()
            
            return {
                "status": "success",
                "message": message,
                "results": len(results) if results else 0
            }
        
        except ImportError as e:
            return {
                "status": "error",
                "message": f"❌ Missing dependency: {str(e)}"
            }
    
    except Exception as e:
        logger.error(f"KB search failed: {e}", exc_info=True)
        return {"status": "error", "message": f"KB search failed: {str(e)}"}


async def _kb_reload(args: str) -> dict:
    """Reload knowledge base (rebuild all indexes). Usage: /admin kb-reload"""
    try:
        from src.olav.lib.kb_manager import reload_knowledge_base
        
        message = "🔄 Reloading knowledge base...\n"
        
        result = reload_knowledge_base(force=True, incremental=False)
        
        if result['success']:
            stats = result['stats']
            message += f"✅ Reloaded {stats['total_indexed']} chunks\n"
            message += f"   Files: {stats['files_processed']}\n"
        else:
            message += f"❌ Error: {result.get('error', 'Unknown')}\n"
        
        return {
            "status": "success" if result['success'] else "error",
            "message": message,
            "result": result
        }
    except ValueError as e:
        if "api_key" in str(e).lower():
            return {
                "status": "error",
                "message": "❌ LLM API key not configured"
            }
        raise
    except Exception as e:
        logger.error(f"KB reload failed: {e}")
        return {"status": "error", "message": f"KB reload failed: {e}"}


if __name__ == "__main__":
    import asyncio

    async def main():
        result = await admin_handler("/admin status")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    asyncio.run(main())

