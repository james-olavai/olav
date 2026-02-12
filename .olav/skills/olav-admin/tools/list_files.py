"""List files and directories in workspace - system-admin tool"""

from pathlib import Path
from typing import Optional
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


def _is_safe_path(path: Path) -> bool:
    """Check if path is safe to access."""
    try:
        resolved = path.resolve()
        return str(resolved).startswith(str(WORKSPACE_ROOT))
    except (OSError, ValueError):
        return False


@tool
def list_files(directory: str = "", pattern: Optional[str] = None) -> dict:
    """List files and directories in workspace.
    
    Args:
        directory: Relative path ('' for root, 'src' for src/, '.olav/skills' for skills)
        pattern: Optional glob pattern (e.g., '*.py', 'SKILL.md')
    
    Returns:
        Dict with directory structure and files
    """
    try:
        if directory == "":
            dir_path = WORKSPACE_ROOT
        else:
            dir_path = WORKSPACE_ROOT / directory
        
        if not _is_safe_path(dir_path):
            return {"error": f"Access denied: {directory}"}
        
        if not dir_path.exists():
            return {"error": f"Directory not found: {directory}"}
        
        if not dir_path.is_dir():
            return {"error": f"Not a directory: {directory}"}
        
        files = []
        dirs = []
        
        if pattern:
            items = dir_path.glob(pattern)
        else:
            items = dir_path.iterdir()
        
        for item in sorted(items):
            rel_path = str(item.relative_to(WORKSPACE_ROOT))
            if item.is_dir():
                dirs.append(rel_path + "/")
            else:
                size = item.stat().st_size if item.exists() else 0
                files.append({
                    "path": rel_path,
                    "size_bytes": size,
                    "type": item.suffix or "unknown"
                })
        
        return {
            "success": True,
            "directory": directory or "root",
            "total_files": len(files),
            "total_dirs": len(dirs),
            "files": sorted(files, key=lambda x: x["path"])[:50],
            "dirs": sorted(dirs)[:30]
        }
    
    except Exception as e:
        return {"error": str(e)}
