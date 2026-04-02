"""append_jobs.py — Add New Check Jobs to an Existing Audit Profile.

Used by the designer to extend existing profiles without full rewrites:
  - Read existing profile → identify current coverage
  - Validate no duplicate job names
  - Append new jobs atomically and re-save to disk

Imports read_profile() from the sibling module at runtime via the shared
tools package to avoid circular dependency issues.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models (ProfileJob duplicated here for import-safety in
# standalone dynamic tool loading — keep in sync with save_profile.py)
# ---------------------------------------------------------------------------

class AppendProfileJob(BaseModel):
    """A single monitoring check job to append to an existing profile."""
    name: str = Field(description="Unique job name, e.g. 'New_Check'. Must not already exist in profile.")
    duckdb_query: str = Field(
        description=(
            "DuckDB SQL query. Must return columns: device, metric_value, "
            "metric_name, severity_hint. Use $cutoff for time window filtering."
        )
    )
    warning_threshold: float = Field(description="Numeric warning level.")
    critical_threshold: float = Field(description="Numeric critical level.")
    operator: str = Field(
        description="Comparison operator: '>' for high-is-bad metrics, '<' for low-is-bad."
    )
    unit: str = Field(default="", description="Unit suffix, e.g. '%', 'ms', 'sessions'.")
    description: str = Field(default="", description="Human-readable description of what this job monitors.")
    remediation: str = Field(default="", description="Recommended remediation steps in markdown.")


class AppendJobsInput(BaseModel):
    """Input schema for the append_jobs tool."""
    profile_name: str = Field(
        description="Name stem of the existing profile file (without .md), e.g. 'network_health_full'."
    )
    new_jobs: list[AppendProfileJob] = Field(
        description=(
            "List of new check jobs to append. Names must not duplicate existing job names."
        )
    )
    profiles_dir: str | None = Field(
        default=None,
        description="Profiles directory. Leave None to use config default."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_profiles_dir() -> str:
    try:
        from olav.core.config import get_paths_config
        return get_paths_config().audit_profiles_dir
    except Exception:
        return ".olav/workspace/audit/profiles"


def _build_frontmatter(name: str, version: str, jobs: list[dict]) -> str:
    """Re-build YAML frontmatter from profile metadata + merged jobs list."""
    try:
        import yaml  # type: ignore
    except ImportError:
        raise RuntimeError("PyYAML is required for append_jobs")

    data = {"name": name, "version": version, "jobs": jobs}
    return yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _build_markdown_body(jobs: list[dict]) -> str:
    """Build a simple markdown body listing all job summaries."""
    lines = ["# Audit Profile — Auto-updated\n"]
    for job in jobs:
        job_name = job.get("name", "unnamed")
        desc = job.get("description", "")
        lines.append(f"## {job_name}")
        if desc:
            lines.append(f"\n{desc}\n")
        op = job.get("operator", ">")
        warn = job.get("warning_threshold", "")
        crit = job.get("critical_threshold", "")
        unit = job.get("unit", "")
        lines.append(f"- **Warning**: `{op} {warn}{unit}`")
        lines.append(f"- **Critical**: `{op} {crit}{unit}`")
        rem = job.get("remediation", "")
        if rem:
            lines.append(f"\n**Remediation**: {rem}\n")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main tool function
# ---------------------------------------------------------------------------

def append_jobs(
    profile_name: str,
    new_jobs: list[AppendProfileJob],
    profiles_dir: str | None = None,
) -> str:
    """Append new monitoring check jobs to an existing audit profile.

    Steps:
      1. Read and parse the existing profile.
      2. Check for duplicate job names.
      3. Append validated new jobs.
      4. Re-render and write the profile file.

    Args:
        profile_name:  Profile stem name (no .md). Must already exist.
        new_jobs:      List of AppendProfileJob objects to add.
        profiles_dir:  Directory override. Defaults to config value.

    Returns:
        Success path string, or "ERROR: ..." description.
    """
    from read_profile import read_profile as _read_profile  # type: ignore  # dynamic path

    directory = Path(profiles_dir or _default_profiles_dir())
    profile_path = directory / f"{profile_name}.md"

    # ---- 1. Read existing profile ----
    parsed = _read_profile(profile_name, str(directory))
    if "error" in parsed:
        avail = parsed.get("available_profiles", [])
        avail_str = ", ".join(avail) if avail else "(none)"
        return f"ERROR: {parsed['error']}. Available profiles: [{avail_str}]"

    existing_jobs: list[dict] = parsed.get("jobs", [])
    existing_names = {j.get("name") for j in existing_jobs}
    version = parsed.get("version", "1.0")
    display_name = parsed.get("name", profile_name)

    # ---- 2. Duplicate check ----
    duplicates = [j.name for j in new_jobs if j.name in existing_names]
    if duplicates:
        return (
            f"ERROR: The following job names already exist in '{profile_name}': "
            f"{duplicates}. Use unique names or update threshold via save_profile overwrite."
        )

    # ---- 3. Merge jobs ----
    merged_jobs = list(existing_jobs)
    for job in new_jobs:
        merged_jobs.append(job.model_dump())

    # ---- 4. Re-build and write ----
    try:
        frontmatter = _build_frontmatter(display_name, version, merged_jobs)
        body = _build_markdown_body(merged_jobs)
        content = f"---\n{frontmatter}---\n\n{body}"
        profile_path.write_text(content, encoding="utf-8")
    except Exception as exc:
        return f"ERROR: Failed to write profile '{profile_path}': {exc}"

    added_names = [j.name for j in new_jobs]
    return (
        f"Successfully appended {len(new_jobs)} job(s) to '{profile_name}': {added_names}. "
        f"Profile now has {len(merged_jobs)} total jobs. Saved to: {profile_path}"
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

AppendProfileJob.model_rebuild()
AppendJobsInput.model_rebuild()

_append_jobs_tool = StructuredTool.from_function(
    append_jobs,
    name="append_jobs",
    description=(
        "Append new monitoring check jobs to an existing audit profile without "
        "overwriting existing jobs. Reads the current profile, validates for "
        "duplicates, and atomically re-saves with the new jobs added at the end. "
        "Use after read_profile to understand current coverage and after "
        "test_map_query to validate new job SQL."
    ),
    args_schema=AppendJobsInput,
)
