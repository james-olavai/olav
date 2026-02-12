"""Search for patterns in codebase - system-admin tool"""

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


def _is_safe_path(path: Path) -> bool:
    """Check if path is safe to access."""
    try:
        resolved = path.resolve()
        return str(resolved).startswith(str(WORKSPACE_ROOT))
    except (OSError, ValueError):
        return False


@tool
def search_code(pattern: str, file_type: str = "*.py") -> dict:
    """Search for patterns in codebase.
    
    Args:
        pattern: Text or regex pattern to search for
        file_type: File glob pattern (default: '*.py', also '*.md', 'SKILL.md', etc.)
    
    Returns:
        Dict with matching files and contexts
    """
    try:
        matches = []
        pattern_lower = pattern.lower()
        
        search_dirs = [
            WORKSPACE_ROOT / "src",
            WORKSPACE_ROOT / ".olav",
            WORKSPACE_ROOT / "config",
        ]
        
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            
            for file_path in search_dir.rglob(file_type):
                if not _is_safe_path(file_path):
                    continue
                
                try:
                    content = file_path.read_text(encoding="utf-8")
                    lines = content.splitlines()
                    
                    for line_num, line in enumerate(lines, 1):
                        if pattern_lower in line.lower():
                            # Get context (2 lines before/after)
                            start = max(0, line_num - 3)
                            end = min(len(lines), line_num + 2)
                            context = lines[start:end]
                            
                            matches.append({
                                "file": str(file_path.relative_to(WORKSPACE_ROOT)),
                                "line": line_num,
                                "matched_text": line.strip(),
                                "context": context
                            })
                
                except (UnicodeDecodeError, PermissionError):
                    pass
        
        return {
            "success": True,
            "pattern": pattern,
            "file_type": file_type,
            "matches_found": len(matches),
            "matches": sorted(matches, key=lambda x: (x["file"], x["line"]))[:20]
        }
    
    except Exception as e:
        return {"error": str(e)}
