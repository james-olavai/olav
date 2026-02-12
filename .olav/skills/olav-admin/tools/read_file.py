"""Read any file in workspace - system-admin tool"""

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
        
        # 写操作也限制在.olav/内（实际上已经被上面的check限制了）
        if for_write:
            return str(resolved).startswith(str(admin_path))
        
        return True
    except (OSError, ValueError):
        return False


@tool
def read_file(path: str) -> dict:
    """Read any file in workspace.
    
    Args:
        path: Relative path from workspace root (e.g., 'src/core/agent.py' 
              or '.olav/skills/query-engine/SKILL.md')
    
    Returns:
        Dict with 'content' and 'lines' count, or error message
    """
    try:
        file_path = WORKSPACE_ROOT / path
        
        if not _is_safe_path(file_path):
            return {
                "error": f"Access denied: {path}",
                "reason": "Path outside workspace or security restricted"
            }
        
        if not file_path.exists():
            return {"error": f"File not found: {path}"}
        
        if not file_path.is_file():
            return {"error": f"Not a file: {path}"}
        
        content = file_path.read_text(encoding="utf-8")
        lines = len(content.splitlines())
        
        return {
            "success": True,
            "path": path,
            "lines": lines,
            "content": content,
            "size_bytes": len(content.encode("utf-8"))
        }
    
    except Exception as e:
        return {"error": str(e)}
