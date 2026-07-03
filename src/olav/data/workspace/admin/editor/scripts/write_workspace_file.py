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

    # Capture prior state BEFORE the write so "undo that" can restore it
    # (dev_docs/99 §7.4). Journaled only after a successful write.
    existed = file_path.exists()
    try:
        previous_content = file_path.read_text(encoding="utf-8") if existed else None
    except Exception:  # noqa: BLE001 — unreadable prior content: undo unavailable, write proceeds
        existed, previous_content = False, None

    try:
        if create_parents:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        undo_recorded = _record_undo(file_path, existed, previous_content)
        return {
            "success": True,
            "path": str(file_path),
            "bytes_written": len(content.encode("utf-8")),
            "undo_recorded": undo_recorded,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "path": str(file_path)}


def _record_undo(file_path: Path, existed: bool, previous_content: "str | None") -> bool:
    """Journal the write for undo_last_action. Soft-fails: a broken journal
    must not fail the write itself, but the ``undo_recorded`` result field
    tells the agent whether "undo" is actually available."""
    try:
        from olav.core.undo_journal import record_action

        verb = "overwrote" if existed else "created"
        return record_action(
            "file_write",
            f"{verb} {file_path}",
            {"path": str(file_path), "existed": existed, "previous_content": previous_content},
        )
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = write_workspace_file(**_args)
    print(_json.dumps(result, default=str))
