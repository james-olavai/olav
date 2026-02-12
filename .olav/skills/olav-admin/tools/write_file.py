"""Write or modify any file in workspace - system-admin tool"""

from pathlib import Path
from langchain_core.tools import tool


def _find_project_root():
    """Find project root by traversing up to find .olav/OLAV.md"""
    current = Path(__file__).parent
    for _ in range(10):
        if (current / ".olav" / "OLAV.md").exists():
            return current
        current = current.parent
    return Path(__file__).parent.parent.parent.parent


WORKSPACE_ROOT = _find_project_root()
# system-admin权限严格限制到.olav/目录（DIY区域）
# 这确保system-admin是配置和技能管理，而不是源代码修改
ADMIN_DIR = WORKSPACE_ROOT / ".olav"


def _is_safe_path(path: Path, for_write: bool = False) -> bool:
    """Check if path is safe to access - restricted to .olav/ only"""
    try:
        resolved = path.resolve()
        admin_path = ADMIN_DIR.resolve()
        
        # 必须在.olav/目录内
        if not str(resolved).startswith(str(admin_path)):
            return False
        
        return True
    except (OSError, ValueError):
        return False


@tool
def write_file(path: str, content: str) -> dict:
    """Write or modify any file in workspace (HITL protected).
    
    ⚠️  THIS TOOL REQUIRES HUMAN-IN-THE-LOOP CONFIRMATION
    
    Used for:
    - Modifying code in src/
    - Updating SKILL.md files
    - Creating new agent skills
    - Editing configuration
    - Modifying test files
    
    Args:
        path: Relative path from workspace root
        content: File content to write
    
    Returns:
        Dict with success status or error
    """
    try:
        file_path = WORKSPACE_ROOT / path
        
        if not _is_safe_path(file_path, for_write=True):
            return {
                "error": f"Write denied: {path}",
                "reason": "Path not in writable directories",
                "safe_dirs": [str(d.relative_to(WORKSPACE_ROOT)) for d in SAFE_WRITE_DIRS]
            }
        
        # Create parent directories if needed
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_path.write_text(content, encoding="utf-8")
        lines = len(content.splitlines())
        
        return {
            "success": True,
            "path": path,
            "lines": lines,
            "size_bytes": len(content.encode("utf-8")),
            "action": "created" if not file_path.exists() else "modified"
        }
    
    except Exception as e:
        return {"error": str(e)}
