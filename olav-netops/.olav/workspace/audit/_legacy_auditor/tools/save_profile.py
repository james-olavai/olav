"""save_profile.py — YAML Schema Validation + Profile File Writer.

Before writing a Profile to disk, enforces that every Job satisfies
the minimum required fields. A malformed Profile is rejected with a
descriptive error message — never silently written to disk.

Required fields per Job:
  ALL types:      name, type, severity, section_prompt
  type: sql       → also requires: query
  type: lancedb   → also requires: semantic_query
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schema — gives the LLM a proper JSON schema for each Job
# ---------------------------------------------------------------------------

class ProfileJob(BaseModel):
    """A single audit job within a Profile."""
    name: str = Field(description="Unique identifier in UPPER_SNAKE_CASE, e.g. 'CPU_High'")
    type: Literal["sql", "lancedb"] = Field(description="Job type: 'sql' for DuckDB queries, 'lancedb' for semantic search")
    severity: Literal["Critical", "Warning", "Info"] = Field(description="Alert severity level")
    section_prompt: str = Field(description="Analysis instruction for the auditor (plain text, what to look for)")
    query: str | None = Field(default=None, description="SQL query string (required when type='sql'). Use :window for time range, e.g. created_at >= NOW() - INTERVAL :window")
    semantic_query: str | None = Field(default=None, description="Semantic search string in English (required when type='lancedb'), e.g. 'critical error alert failure'")
    threshold: float | None = Field(default=None, description="Similarity threshold 0-1 for lancedb jobs (recommended 0.75-0.85)")


class SaveProfileInput(BaseModel):
    """Input schema for save_profile tool."""
    name: str = Field(description="Profile filename stem (no extension), e.g. 'network_health_full'")
    yaml_jobs: list[ProfileJob] = Field(description="List of audit jobs. Each job must have: name, type, severity, section_prompt, and either query (sql) or semantic_query (lancedb).")
    markdown_body: str = Field(description="Markdown narrative body for the profile (can be a brief description or empty string)")
    profiles_dir: str | None = Field(default=None, description="Output directory (leave None to use config default)")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _default_profiles_dir() -> str:
    try:
        from olav.core.config import get_paths_config
        return get_paths_config().audit_profiles_dir
    except Exception:
        return ".olav/workspace/audit/profiles"


def save_profile(
    name: str,
    yaml_jobs: list[dict],
    markdown_body: str,
    profiles_dir: str | None = None,
) -> str:
    """Validate and write a Profile Markdown file.

    Args:
        name:          Profile name (used as filename stem, no extension).
        yaml_jobs:     List of Job dicts. Each dict MUST contain:
                       - name (str): unique identifier, e.g. "CPU_High"
                       - type (str): "sql" or "lancedb"
                       - severity (str): "Critical", "Warning", or "Info"
                       - section_prompt (str): analysis instruction text
                       - query (str): SQL query (required when type="sql")
                       - semantic_query (str): search text (required when type="lancedb")
                       Example:
                         [{"name": "Interface_Down", "type": "sql",
                           "severity": "Critical",
                           "query": "SELECT device_name, interface FROM interfaces WHERE status = 'down'",
                           "section_prompt": "List all down interfaces"}]
        markdown_body: Markdown body of the Profile.
        profiles_dir:  Directory to write the profile into. Leave None to use config default.

    Returns:
        Absolute path to the written .md file, or a string starting with "ERROR:" if validation fails.
    """
    # Sanitize profiles_dir — reject clearly wrong absolute paths like /profiles
    if profiles_dir and (profiles_dir.startswith("/profiles") or profiles_dir == "/"):
        profiles_dir = None

    try:
        _validate_jobs(yaml_jobs)
    except ValueError as exc:
        return (
            f"ERROR: {exc}. "
            "Each job dict must have: name, type ('sql'/'lancedb'), severity, section_prompt, "
            "plus query (for sql) or semantic_query (for lancedb). "
            "Example: {\"name\": \"CPU_High\", \"type\": \"sql\", \"severity\": \"Critical\", "
            "\"query\": \"SELECT device_name FROM parsed_outputs WHERE ...\", "
            "\"section_prompt\": \"List devices with high CPU\"}. "
            "Please call save_profile again with correctly structured yaml_jobs."
        )

    content = _render_profile_md(name, yaml_jobs, markdown_body)

    out_dir = Path(profiles_dir if profiles_dir is not None else _default_profiles_dir())
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        return f"ERROR: Cannot create directory '{out_dir}': {exc}. Do not pass profiles_dir, use the default."

    profile_path = out_dir / f"{name}.md"
    profile_path.write_text(content, encoding="utf-8")

    logger.info("save_profile: wrote %s", profile_path)
    return str(profile_path)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

_REQUIRED_ALL = ("name", "type", "severity", "section_prompt")
_REQUIRED_SQL = ("query",)
_REQUIRED_LANCEDB = ("semantic_query",)


def _validate_jobs(yaml_jobs: list[dict]) -> None:
    """Raise ValueError if any Job is missing required fields."""
    for i, job in enumerate(yaml_jobs):
        label = f"Job[{i}] ({job.get('name', '<unnamed>')})"

        for field in _REQUIRED_ALL:
            if field not in job or job[field] is None or str(job[field]).strip() == "":
                raise ValueError(
                    f"{label}: missing required field '{field}'"
                )

        job_type = job.get("type", "").lower()
        if job_type == "sql":
            for field in _REQUIRED_SQL:
                if field not in job or not str(job.get(field, "")).strip():
                    raise ValueError(
                        f"{label}: type='sql' requires field '{field}'"
                    )
        elif job_type == "lancedb":
            for field in _REQUIRED_LANCEDB:
                if field not in job or not str(job.get(field, "")).strip():
                    raise ValueError(
                        f"{label}: type='lancedb' requires field '{field}'"
                    )
        else:
            raise ValueError(
                f"{label}: unknown type '{job_type}' — must be 'sql' or 'lancedb'"
            )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_profile_md(name: str, yaml_jobs: list[dict], markdown_body: str) -> str:
    """Render Profile as YAML frontmatter + Markdown body."""
    try:
        import yaml  # type: ignore
        frontmatter = yaml.dump(
            {"name": name, "version": "4.0", "persist_findings_to_db": False,
             "max_findings_per_job": 50, "jobs": yaml_jobs},
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
    except ImportError:
        # Fallback: minimal hand-rolled YAML
        jobs_yaml = "\n".join(
            f"  - name: \"{j.get('name')}\"\n"
            f"    type: \"{j.get('type')}\"\n"
            f"    severity: \"{j.get('severity')}\"\n"
            f"    section_prompt: |\n      {j.get('section_prompt', '')}"
            for j in yaml_jobs
        )
        frontmatter = f"name: \"{name}\"\nversion: \"4.0\"\njobs:\n{jobs_yaml}\n"

    return f"---\n{frontmatter}---\n\n{markdown_body.strip()}\n"


def _save_profile_validated(
    name: str,
    yaml_jobs: list[ProfileJob],
    markdown_body: str,
    profiles_dir: str | None = None,
) -> str:
    """Wrapper that receives typed ProfileJob instances and delegates to save_profile."""
    jobs_as_dicts = [j.model_dump(exclude_none=True) for j in yaml_jobs]
    return save_profile(
        name=name,
        yaml_jobs=jobs_as_dicts,
        markdown_body=markdown_body,
        profiles_dir=profiles_dir,
    )


# Resolve Pydantic forward references (required when from __future__ import annotations is active)
ProfileJob.model_rebuild()
SaveProfileInput.model_rebuild()

_save_profile_tool = StructuredTool.from_function(
    _save_profile_validated,
    name="save_profile",
    description=(
        "Validate and write an Audit Profile Markdown file to disk. "
        "Call AFTER database_introspection and test_map_query. "
        "Each job in yaml_jobs must have: name, type ('sql'/'lancedb'), "
        "severity ('Critical'/'Warning'/'Info'), section_prompt, "
        "plus query (sql jobs) or semantic_query+threshold (lancedb jobs)."
    ),
    args_schema=SaveProfileInput,
)
