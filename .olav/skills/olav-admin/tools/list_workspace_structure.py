"""List workspace structure - system-admin tool"""

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
SAFE_WRITE_DIRS = {
    WORKSPACE_ROOT / "src",
    WORKSPACE_ROOT / ".olav",
    WORKSPACE_ROOT / "config",
    WORKSPACE_ROOT / "tests",
}


@tool
def list_workspace_structure() -> dict:
    """Get overall workspace structure for navigation.
    
    Returns:
        Dict with key directories and their purposes
    """
    return {
        "workspace_root": str(WORKSPACE_ROOT),
        "structure": {
            "src/olav/tools/": "All agent tools (cache, system, config, task, code)",
            "src/olav/agents/": "Agent implementations",
            "src/olav/core/": "Core OLAV engine",
            ".olav/skills/": "Agent skill configurations (SKILL.md files)",
            ".olav/OLAV.md": "Main registry of all agents",
            "config/": "Global settings (paths, settings, logging)",
            "tests/": "Test files",
            ".olav/db/": "DuckDB database files",
            ".olav/config_backups/": "Configuration backups",
        },
        "writable_dirs": [str(d.relative_to(WORKSPACE_ROOT)) for d in SAFE_WRITE_DIRS],
        "diy_capabilities": [
            "Modify existing agent code in src/",
            "Create new agents in src/olav/agents/",
            "Create new tools in src/olav/tools/",
            "Edit SKILL.md to customize agent behavior",
            "Update config files for settings",
            "Create and register new skills"
        ]
    }
