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

    # Complex tasks → OLAVAgent (AI-powered, natural language)
    # Routes to olav-config SubAgent which handles writes/scheduling with HITL
    # Examples:
    #   /admin "create monitoring skill"
    #   /admin "search for execute_sql usage"
    #   /admin "backup and test new feature"
    try:
        from olav.agents.agent import create_olav_agent

        agent = create_olav_agent()

        # Reconstruct user query (remove /admin prefix)
        user_query = cmd_name if not cmd_args else f"{cmd_name} {cmd_args}"

        logger.info(f"Invoking OLAVAgent for admin task: {user_query}")

        result = await agent.invoke(user_query, thread_id="admin")

        return {
            "status": result.get("status", "error"),
            "response": result.get("response", result.get("message", "")),
            "message": "OLAVAgent completed task"
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
            "agents_count": 0,
            "tools_count": 0,
        }
        
        # Database info
        if db_path.exists():
            for db in ["main.duckdb", "agent.duckdb", "llm_cache.db"]:
                db_file = db_path / db
                if db_file.exists():
                    size_mb = db_file.stat().st_size / (1024 * 1024)
                    status_info["databases"][db] = f"{size_mb:.2f} MB"
        
        # Agents count (workspace)
        workspace_path = base_path / "workspace"
        if workspace_path.exists():
            status_info["agents_count"] = len(list(workspace_path.glob("*/AGENT.md")))
        
        # Tools count (shared/tools if exists, or scan workspace)
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
    """List all available agents/skills in workspace.

    Your agents and their skills are defined in: `.olav/workspace/`
    """
    try:
        base_path = Path(".olav")
        workspace_path = base_path / "workspace"
        
        agents = []
        if workspace_path.exists():
            for agent_dir in workspace_path.iterdir():
                if agent_dir.is_dir():
                    agent_md = agent_dir / "AGENT.md"
                    if agent_md.exists():
                        agents.append({
                            "name": agent_dir.name,
                            "path": str(agent_dir),
                            "file_size": agent_md.stat().st_size
                        })
        
        return {"status": "success", "agents": agents, "count": len(agents)}
    
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
        import importlib.util
        from pathlib import Path as _Path
        # Use workspace-centric knowledge management tools
        path = _Path(".olav/workspace/config/knowledge/tools/get_knowledge_status.py")
        spec = importlib.util.spec_from_file_location("_olav_skill_kb_status", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # The new tool follows @tool pattern, so we call .invoke() or just the function
        # For direct Python call, we use the function itself
        status_func = getattr(mod, "get_kb_status", None)
        if not status_func:
             # Fallback to search standard function names if tool wrapper is used
             status_func = mod.get_knowledge_status
             
        status = status_func()

        message = "📚 Knowledge Base Status\n"
        message += f"  Status: {status.get('status', 'unknown')}\n"
        message += f"  Chunks: {status.get('total_chunks', 0)}\n"
        if status.get('last_updated'):
            message += f"  Last updated: {status['last_updated']}\n"
        if status.get('message'):
            message += f"  {status['message']}\n"

        return {"status": "success", "message": message, "statistics": status}
    except Exception as e:
        logger.error(f"KB status failed: {e}")
        return {"status": "error", "message": f"KB status failed: {e}"}


async def _kb_index(args: str) -> dict:
    """Index knowledge files. Usage: /admin kb-index or /admin kb-index rebuild"""
    try:
        import importlib.util
        from pathlib import Path as _Path
        path = _Path(".olav/workspace/config/knowledge/tools/index_knowledge_files.py")
        spec = importlib.util.spec_from_file_location("_olav_skill_kb_index", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        rebuild = "rebuild" in args.lower() or "force" in args.lower()
        message = "🔍 Indexing knowledge base...\n"

        # The new tool uses index_knowledge_files
        index_func = mod.index_knowledge_files
        
        # Invoke with parameters
        result_str = index_func(force_reindex=rebuild, incremental=not rebuild)
        return {"status": "success", "message": result_str}
    except ValueError as e:
        if "LLM_API_KEY" in str(e) or "api_key" in str(e).lower():
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
            from olav.core.config import MAIN_DB_PATH
            from olav.core.llm import LLMFactory
            from pathlib import Path
            import duckdb
            
            # Check if database exists
            from pathlib import Path
            import duckdb
            
            # Check if database exists
            db_path = Path(MAIN_DB_PATH)
            if not db_path.exists():
                return {
                    "status": "error",
                    "message": f"❌ Knowledge base database not found. Run: olav config kb-index"
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
        import importlib.util
        from pathlib import Path as _Path
        path = _Path(".olav/workspace/config/knowledge/tools/index_knowledge_files.py")
        spec = importlib.util.spec_from_file_location("_olav_skill_kb_reload", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        message = "🔄 Reloading knowledge base...\n"
        index_func = mod.index_knowledge_files
        result_str = index_func(force_reindex=True, incremental=False)

        return {"status": "success", "message": result_str}
    except ValueError as e:
        if "api_key" in str(e).lower():
            return {"status": "error", "message": "❌ LLM API key not configured"}
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

