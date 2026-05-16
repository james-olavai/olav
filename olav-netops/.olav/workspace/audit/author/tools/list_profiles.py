"""list_profiles @tool — enumerate existing audit Profiles.

Promoted from a skill_script (author/scripts/list_profiles.py) to a
LangChain ``@tool`` in rev 261 so small LLMs don't have to guess the
``skill_name`` + ``script_name`` pair through ``execute_skill_script``.

The skill_script version is kept for backward compatibility (the logic
is identical — same _resolve_profiles_dir + _first_header helpers).
"""
from __future__ import annotations

import os
from pathlib import Path

from langchain_core.tools import tool


def _resolve_profiles_dir() -> Path:
    """Find the audit profiles dir relative to runtime workspace."""
    if env := os.environ.get("OLAV_WORKSPACE_ROOT"):
        return Path(env) / "audit" / "profiles"
    cwd_workspace = Path.cwd() / ".olav" / "workspace" / "audit" / "profiles"
    if cwd_workspace.exists():
        return cwd_workspace
    # Fallback — install-time path; walk up from this file
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "audit" / "profiles"
        if candidate.is_dir():
            return candidate
    return Path(".olav/workspace/audit/profiles")


def _first_header(path: Path) -> str:
    """Pull the first H1 (`# ...`) from a markdown file as title."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[:20]:
            line = line.strip()
            if line.startswith("# ") and not line.startswith("# !"):
                return line[2:].strip()
    except Exception:
        pass
    return ""


def _is_deprecated(path: Path) -> bool:
    """Cheap check for `deprecated: true` in YAML frontmatter — no full YAML parse."""
    try:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()[:30]
        for i, line in enumerate(lines):
            s = line.strip()
            if i > 0 and s == "---":
                break  # end of frontmatter
            if s.startswith("deprecated:"):
                val = s.split(":", 1)[1].split("#", 1)[0].strip().lower()
                if val in ("true", "yes", "1"):
                    return True
    except Exception:
        pass
    return False


@tool
def list_profiles() -> dict:
    """List every available audit Profile in the project's profiles directory.

    Use this when the user asks:
      * "list profiles" / "what profiles are available" / "show audit profiles"
      * "which profiles do I have" / "有哪些 audit profile"

    No arguments — always returns the same dict shape:

        {
          "status": "success" | "error",
          "profiles_dir": "<absolute path>",
          "count": <int>,
          "profiles": [
            {"name": "<stem>", "filename": "<stem>.md",
             "title": "<first H1 or ''>", "size_bytes": <int>}, ...
          ]
        }

    Profile ``name`` (no extension) can be passed directly to
    ``run_map_engine`` (via the runner sub-agent), ``read_profile``, or
    ``append_jobs``.
    """
    profiles_dir = _resolve_profiles_dir()
    if not profiles_dir.is_dir():
        return {
            "status": "error",
            "message": f"profiles dir not found: {profiles_dir}",
        }

    profiles: list[dict] = []
    deprecated_names: list[str] = []
    for p in sorted(profiles_dir.glob("*.md")):
        is_dep = _is_deprecated(p)
        profiles.append({
            "name": p.stem,
            "filename": p.name,
            "title": _first_header(p),
            "size_bytes": p.stat().st_size,
            "deprecated": is_dep,
        })
        if is_dep:
            deprecated_names.append(p.stem)

    return {
        "status": "success",
        "profiles_dir": str(profiles_dir),
        "count": len(profiles),
        "deprecated_count": len(deprecated_names),
        "deprecated_names": deprecated_names,
        "profiles": profiles,
    }
