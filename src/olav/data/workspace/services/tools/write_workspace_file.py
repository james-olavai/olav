#!/usr/bin/env python3
"""
write_workspace_file — Write files within the project workspace.

Intended for: docker-compose.yml, skill files, config snippets, reports.
Writes are restricted to paths within the project root (no /etc, /usr, etc.).

Workflow:
  1. write_workspace_file("docker-compose.yml", content) → create compose file
  2. write_workspace_file(".olav/workspace/netops/netbox/SKILL.md", content) → create skill
  3. write_workspace_file(".olav/workspace/netops/netbox/prompts/system.md", content)
"""

import json
import sys
from pathlib import Path

from langchain_core.tools import tool


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()

# Paths the agent is NOT allowed to write to
_BLOCKED_PREFIXES = [
    "/etc", "/usr", "/bin", "/sbin", "/lib", "/boot", "/sys", "/proc",
    "/dev", "/run", "/snap",
]


def _is_safe_path(path: Path) -> tuple[bool, str]:
    try:
        resolved = path.resolve()
        # Must be within project root
        resolved.relative_to(PROJECT_ROOT.resolve())
        # Double-check against blocked system paths
        path_str = str(resolved)
        for blocked in _BLOCKED_PREFIXES:
            if path_str.startswith(blocked):
                return False, f"Path is in blocked system directory: {blocked}"
        return True, ""
    except ValueError:
        return False, f"Path must be within project root ({PROJECT_ROOT})"


@tool
def write_workspace_file(
    path: str,
    content: str,
    create_parents: bool = True,
) -> dict:
    """Write a file within the project workspace.

    Use for creating docker-compose.yml, SKILL.md, system prompts, config files.
    Paths are restricted to within the project root for safety.

    Args:
        path:           File path relative to project root (e.g. "docker-compose.yml"
                        or ".olav/workspace/netops/netbox/SKILL.md")
        content:        Full file content to write.
        create_parents: Create parent directories if they don't exist (default True).

    Returns:
        {
          "success": true,
          "path": "/absolute/path/to/file",
          "bytes_written": 1234
        }
    """
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = PROJECT_ROOT / file_path

    safe, reason = _is_safe_path(file_path)
    if not safe:
        return {"success": False, "error": reason, "path": str(file_path)}

    try:
        if create_parents:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return {
            "success": True,
            "path": str(file_path),
            "bytes_written": len(content.encode("utf-8")),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "path": str(file_path)}


if __name__ == "__main__":
    try:
        params = json.loads(sys.stdin.read()) if sys.stdin.read().strip() else {}
        print(json.dumps(write_workspace_file.func(**params), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}), file=sys.stderr)
        sys.exit(1)
