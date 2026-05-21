"""append_jobs.py — Add New Check Jobs to an Existing Audit Profile.

Used by the designer to extend existing profiles without full rewrites:
  - Read existing profile → identify current coverage
  - Validate no duplicate job names
  - Append new jobs atomically and re-save to disk

Imports read_profile() from the sibling scripts directory at runtime.

Schema note (2026-05-11, rev 257): ``AppendProfileJob`` was originally
declared with a non-canonical field set
(``duckdb_query / warning_threshold / critical_threshold / operator``).
That schema did not match what ``map_engine`` reads
(``type / severity / query / section_prompt``) — any profile produced
by ``append_jobs`` would fall through ``job.get("query", "")`` to an
empty SQL string and silently return zero findings. Designer-mode
in-vivo coverage was zero so the bug never surfaced. The schema is now
mirrored from ``save_profile.ProfileJob`` so the two authoring entry
points produce mutually compatible YAML.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, Field
from typing import Literal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models — MUST mirror save_profile.ProfileJob field-for-field so
# the two authoring tools write a single canonical schema readable by
# map_engine. Duplicated here (not imported) for import-safety in standalone
# dynamic tool loading.
# ---------------------------------------------------------------------------

class AppendProfileJob(BaseModel):
    """A single audit job to append to an existing Profile.

    Mirrors save_profile.ProfileJob so map_engine reads both shapes
    identically.
    """
    name: str = Field(description="Unique identifier in UPPER_SNAKE_CASE, e.g. 'CPU_High'. Must not duplicate existing job names in the target profile.")
    type: Literal["sql", "lancedb"] = Field(description="Job type: 'sql' for DuckDB queries, 'lancedb' for semantic search")
    severity: Literal["Critical", "Warning", "Info"] = Field(description="Alert severity level")
    section_prompt: str = Field(description="Analysis instruction for the auditor (plain text, what to look for)")
    query: str | None = Field(default=None, description="SQL query string (required when type='sql'). Use :window for time range, e.g. created_at >= NOW() - INTERVAL :window")
    semantic_query: str | None = Field(default=None, description="Semantic search string in English (required when type='lancedb'), e.g. 'critical error alert failure'")
    threshold: float | None = Field(default=None, description="Similarity threshold 0-1 for lancedb jobs (recommended 0.75-0.85)")


class AppendJobsInput(BaseModel):
    """Input schema for append_jobs."""
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


def _validate_canonical_jobs(jobs: list[AppendProfileJob]) -> None:
    """Pydantic enforces field types; this checks the SQL/LanceDB
    branch invariant that Pydantic alone cannot express
    (Literal["sql"] requires non-empty query; ["lancedb"] requires
    non-empty semantic_query)."""
    for i, j in enumerate(jobs):
        label = f"new_jobs[{i}] ({j.name})"
        if j.type == "sql" and not (j.query and j.query.strip()):
            raise ValueError(f"{label}: type='sql' requires non-empty 'query'")
        if j.type == "lancedb" and not (j.semantic_query and j.semantic_query.strip()):
            raise ValueError(
                f"{label}: type='lancedb' requires non-empty 'semantic_query'"
            )


def _build_frontmatter(name: str, version: str, jobs: list[dict],
                       persist_findings_to_db: bool = False,
                       max_findings_per_job: int = 50) -> str:
    """Re-build YAML frontmatter from profile metadata + merged jobs list."""
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyYAML is required for append_jobs") from exc

    data = {
        "name": name,
        "version": version,
        "persist_findings_to_db": persist_findings_to_db,
        "max_findings_per_job": max_findings_per_job,
        "jobs": jobs,
    }
    return yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def append_jobs(
    profile_name: str,
    new_jobs: list[AppendProfileJob],
    profiles_dir: str | None = None,
) -> str:
    """Append new audit jobs to an existing Profile.

    Steps:
      1. Read and parse the existing profile.
      2. Validate the canonical SQL/LanceDB branch invariant.
      3. Check for duplicate job names.
      4. Append validated new jobs.
      5. Re-render and write the profile file (preserving the original
         markdown body).

    Args:
        profile_name:  Profile stem name (no .md). Must already exist.
        new_jobs:      List of AppendProfileJob objects (canonical schema)
                       to add.
        profiles_dir:  Directory override. Defaults to config value.

    Returns:
        Success message + path, or "ERROR: ..." description.
    """
    import importlib.util as _iu
    from pathlib import Path as _P

    # Locate read_profile in the scripts directory sibling to this file.
    _here = _P(__file__).resolve().parent
    _rp_path = _here / "read_profile.py"
    if not _rp_path.exists():
        return f"ERROR: read_profile.py not found at {_rp_path}"
    _spec = _iu.spec_from_file_location("_append_jobs_read_profile", _rp_path)
    _mod = _iu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _read_profile = _mod.read_profile

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
    version = parsed.get("version", "4.0")
    display_name = parsed.get("name", profile_name)

    # ---- 2. Canonical-schema branch validation ----
    try:
        _validate_canonical_jobs(new_jobs)
    except ValueError as exc:
        return f"ERROR: {exc}"

    # ---- 3. Duplicate check ----
    duplicates = [j.name for j in new_jobs if j.name in existing_names]
    if duplicates:
        return (
            f"ERROR: The following job names already exist in '{profile_name}': "
            f"{duplicates}. Use unique names or update threshold via save_profile overwrite."
        )

    # ---- 4. Merge jobs ----
    merged_jobs = list(existing_jobs)
    for job in new_jobs:
        merged_jobs.append(job.model_dump(exclude_none=True))

    # ---- 5. Re-build and write — preserve original markdown body ----
    existing_body = parsed.get("body", "").strip()
    try:
        frontmatter = _build_frontmatter(
            display_name, version, merged_jobs,
            persist_findings_to_db=bool(parsed.get("persist_findings_to_db", False)),
            max_findings_per_job=int(parsed.get("max_findings_per_job", 50)),
        )
        content = f"---\n{frontmatter}---\n\n{existing_body}\n"
        profile_path.write_text(content, encoding="utf-8")
    except Exception as exc:
        return f"ERROR: Failed to write profile '{profile_path}': {exc}"

    added_names = [j.name for j in new_jobs]
    return (
        f"Successfully appended {len(new_jobs)} job(s) to '{profile_name}': {added_names}. "
        f"Profile now has {len(merged_jobs)} total jobs. Saved to: {profile_path}"
    )


# ---------------------------------------------------------------------------
# Model rebuild
# ---------------------------------------------------------------------------

AppendProfileJob.model_rebuild()
AppendJobsInput.model_rebuild()


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    # Reconstruct Pydantic objects from dicts
    if "new_jobs" in _args:
        _args["new_jobs"] = [AppendProfileJob(**j) if isinstance(j, dict) else j for j in _args["new_jobs"]]
    result = append_jobs(**_args)
    print(_json.dumps(result, default=str))
