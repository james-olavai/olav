"""read_profile.py — Load and Parse an Existing Audit Profile.

Used by the designer to:
  - Inspect current job definitions before tuning thresholds
  - Understand existing check coverage before appending new jobs
  - Show the user what is already configured (HMITL clarification step)

Two entry points:
  list_profiles()   → returns all .md files in the profiles directory
  read_profile()    → parses a named profile and returns its jobs as structured data
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ReadProfileInput(BaseModel):
    """Input schema for read_profile tool."""
    name: str = Field(
        description=(
            "Profile name stem (without .md extension), e.g. 'network_health_full'. "
            "Call list_profiles first if you are unsure of the exact name."
        )
    )
    profiles_dir: str | None = Field(
        default=None,
        description="Profiles directory. Leave None to use config default."
    )


class ListProfilesInput(BaseModel):
    """Input schema for list_profiles tool."""
    profiles_dir: str | None = Field(
        default=None,
        description="Profiles directory. Leave None to use config default."
    )


def _default_profiles_dir() -> str:
    try:
        from olav.core.config import get_paths_config
        return get_paths_config().audit_profiles_dir
    except Exception:
        return ".olav/workspace/audit/profiles"


def list_profiles(profiles_dir: str | None = None) -> dict:
    """List all available audit profiles in the profiles directory.

    Returns:
        Dict with:
          - profiles_dir: resolved directory path
          - profiles: list of profile names (without extension)
          - count: total number
    """
    directory = Path(profiles_dir or _default_profiles_dir())
    if not directory.exists():
        return {
            "profiles_dir": str(directory),
            "profiles": [],
            "count": 0,
            "message": f"Directory '{directory}' does not exist yet.",
        }

    profiles = sorted(p.stem for p in directory.glob("*.md"))
    return {
        "profiles_dir": str(directory),
        "profiles": profiles,
        "count": len(profiles),
    }


def read_profile(name: str, profiles_dir: str | None = None) -> dict:
    """Read and parse an existing audit profile, returning its job definitions.

    Args:
        name:         Profile filename stem (no .md extension).
        profiles_dir: Directory containing profiles. Defaults to config value.

    Returns:
        Dict with:
          - name, version, file_path
          - jobs: list of job dicts (with all fields)
          - job_names: quick list of job name strings
          - job_count: number of jobs
          - raw_yaml: full frontmatter text (for reference)
          - error: error message if file not found or parse failed
    """
    directory = Path(profiles_dir or _default_profiles_dir())
    profile_path = directory / f"{name}.md"

    if not profile_path.exists():
        available = [p.stem for p in directory.glob("*.md")] if directory.exists() else []
        return {
            "error": f"Profile '{name}.md' not found in '{directory}'.",
            "available_profiles": available,
            "hint": "Call list_profiles() to see all available profiles, or create one with save_profile.",
        }

    raw = profile_path.read_text(encoding="utf-8")

    # Extract YAML frontmatter (between first pair of ---)
    frontmatter_text = ""
    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            frontmatter_text = parts[1].strip()
            body = parts[2].strip()

    # Parse YAML
    metadata: dict = {}
    jobs: list[dict] = []
    try:
        import yaml  # type: ignore
        metadata = yaml.safe_load(frontmatter_text) or {}
        jobs = metadata.get("jobs", [])
    except Exception as exc:
        return {
            "name": name,
            "file_path": str(profile_path),
            "error": f"YAML parse error: {exc}",
            "raw_frontmatter": frontmatter_text[:500],
        }

    return {
        "name": metadata.get("name", name),
        "version": metadata.get("version", "unknown"),
        "file_path": str(profile_path),
        "job_count": len(jobs),
        "job_names": [j.get("name", f"job_{i}") for i, j in enumerate(jobs)],
        "jobs": jobs,
        "raw_yaml": frontmatter_text,
        "body_preview": body[:300] if body else "",
    }


# Register both as tools
ListProfilesInput.model_rebuild()
ReadProfileInput.model_rebuild()

_list_profiles_tool = StructuredTool.from_function(
    list_profiles,
    name="list_profiles",
    description=(
        "List all available audit profile files (.md) in the profiles directory. "
        "Use before read_profile when unsure of the exact profile name."
    ),
    args_schema=ListProfilesInput,
)

_read_profile_tool = StructuredTool.from_function(
    read_profile,
    name="read_profile",
    description=(
        "Read and parse an existing audit profile. Returns the full list of jobs "
        "with their queries, thresholds, and severity settings. "
        "Use before tune_thresholds or append_jobs to understand current coverage."
    ),
    args_schema=ReadProfileInput,
)
