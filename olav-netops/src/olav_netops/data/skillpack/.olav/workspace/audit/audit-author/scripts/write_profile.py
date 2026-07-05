"""write_profile — create or extend an audit profile.

Merges the former ``save_profile`` (create/overwrite) and ``append_jobs``
(extend) into a single entry point selected by the ``mode`` parameter.

  mode="create"  → validate + write a full profile from scratch (or overwrite)
  mode="append"  → read existing, validate no duplicates, append, re-write

The ``jobs`` parameter always uses the same canonical ProfileJob schema
so map_engine reads both modes identically.

Required Job fields (all modes):
  name, type ("sql"|"lancedb"), severity ("Critical"|"Warning"|"Info"), section_prompt
  type="sql"     → also requires: query
  type="lancedb" → also requires: semantic_query
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical Pydantic schema — single source of truth for both modes
# ---------------------------------------------------------------------------

class ProfileJob(BaseModel):
    """A single audit job. Schema shared by create + append modes."""
    name: str = Field(description="Unique identifier in UPPER_SNAKE_CASE, e.g. 'CPU_High'")
    type: Literal["sql", "lancedb"] = Field(
        description="Job type: 'sql' for DuckDB queries, 'lancedb' for semantic search"
    )
    severity: Literal["Critical", "Warning", "Info"] = Field(description="Alert severity level")
    section_prompt: str = Field(
        description="Analysis instruction for the auditor (plain text, what to look for)"
    )
    query: str | None = Field(
        default=None,
        description="SQL query (required when type='sql'). Use :window for time range.",
    )
    semantic_query: str | None = Field(
        default=None,
        description="Semantic search string (required when type='lancedb').",
    )
    threshold: float | None = Field(
        default=None,
        description="Similarity threshold 0-1 for lancedb jobs (recommended 0.75-0.85).",
    )


ProfileJob.model_rebuild()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_profiles_dir() -> str:
    try:
        from olav.core.config import get_paths_config
        return get_paths_config().audit_profiles_dir
    except Exception:
        return ".olav/workspace/audit/profiles"


def _validate_jobs(jobs: list[dict]) -> None:
    """Raise ValueError on schema violations."""
    required_all = ("name", "type", "severity", "section_prompt")
    for i, job in enumerate(jobs):
        label = f"jobs[{i}] ({job.get('name', '<unnamed>')})"
        for field in required_all:
            if field not in job or job[field] is None or str(job[field]).strip() == "":
                raise ValueError(f"{label}: missing required field '{field}'")
        jtype = str(job.get("type", "")).lower()
        if jtype == "sql":
            if not str(job.get("query", "")).strip():
                raise ValueError(f"{label}: type='sql' requires non-empty 'query'")
        elif jtype == "lancedb":
            if not str(job.get("semantic_query", "")).strip():
                raise ValueError(f"{label}: type='lancedb' requires non-empty 'semantic_query'")
        else:
            raise ValueError(f"{label}: unknown type '{jtype}' — must be 'sql' or 'lancedb'")


def _render_profile_md(
    name: str,
    jobs: list[dict],
    markdown_body: str,
    persist_findings_to_db: bool = False,
    max_findings_per_job: int = 50,
    version: str = "4.0",
) -> str:
    try:
        import yaml  # type: ignore
        frontmatter = yaml.dump(
            {
                "name": name,
                "version": version,
                "persist_findings_to_db": persist_findings_to_db,
                "max_findings_per_job": max_findings_per_job,
                "jobs": jobs,
            },
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
    except ImportError:
        jobs_yaml = "\n".join(
            f"  - name: \"{j.get('name')}\"\n"
            f"    type: \"{j.get('type')}\"\n"
            f"    severity: \"{j.get('severity')}\"\n"
            f"    section_prompt: |\n      {j.get('section_prompt', '')}"
            for j in jobs
        )
        frontmatter = f"name: \"{name}\"\nversion: \"{version}\"\njobs:\n{jobs_yaml}\n"
    return f"---\n{frontmatter}---\n\n{markdown_body.strip()}\n"


def _try_selftest(profile_path: str) -> str:
    """Run map_engine.selftest_profile — advisory, never blocks write."""
    try:
        import importlib.util as _iu
        _here = Path(__file__).resolve()
        candidates = [
            _here.parent.parent.parent / "audit-runner" / "scripts" / "map_engine.py",
        ]
        me_path = next((p for p in candidates if p.exists()), None)
        if me_path is None:
            return ""
        spec = _iu.spec_from_file_location("_write_profile_selftest_me", me_path)
        mod = _iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.selftest_profile(profile_path)
        if result.get("ok"):
            return ""
        failures = [
            f"  • {j['name']}: {j['error']}"
            for j in result.get("jobs", [])
            if j.get("status") != "ok"
        ]
        if not failures:
            return ""
        return (
            "⚠️ selftest: profile written but " + str(len(failures))
            + " job(s) failed schema check against the live DB:\n"
            + "\n".join(failures)
            + "\nEdit the profile + re-run write_profile, OR fix the SQL "
              "in place and verify with map_engine.selftest_profile()."
        )
    except Exception as exc:
        logger.debug("write_profile: selftest skipped: %s: %s", type(exc).__name__, exc)
        return ""


def _read_existing(name: str, directory: Path) -> dict:
    """Load an existing profile for append mode."""
    profile_path = directory / f"{name}.md"
    if not profile_path.exists():
        available = [p.stem for p in directory.glob("*.md")] if directory.exists() else []
        return {
            "error": f"Profile '{name}.md' not found in '{directory}'.",
            "available_profiles": available,
        }
    raw = profile_path.read_text(encoding="utf-8")
    frontmatter_text = ""
    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            frontmatter_text = parts[1].strip()
            body = parts[2].strip()
    try:
        import yaml  # type: ignore
        meta = yaml.safe_load(frontmatter_text) or {}
    except Exception as exc:
        return {"error": f"YAML parse error in existing profile: {exc}"}
    return {
        "name": meta.get("name", name),
        "version": meta.get("version", "4.0"),
        "jobs": meta.get("jobs", []),
        "body": body,
        "persist_findings_to_db": meta.get("persist_findings_to_db", False),
        "max_findings_per_job": meta.get("max_findings_per_job", 50),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def write_profile(
    name: str,
    jobs: list[dict],
    mode: Literal["create", "append"] = "create",
    markdown_body: str = "",
    profiles_dir: str | None = None,
) -> str:
    """Create or extend an audit Profile.

    Args:
        name:          Profile stem (no .md extension).
        jobs:          List of Job dicts with canonical schema.
                       mode=create → full job list for the new profile.
                       mode=append → jobs to ADD to the existing profile.
        mode:          "create" overwrites (or creates) the profile.
                       "append" reads existing, checks for duplicates, adds.
        markdown_body: Narrative markdown body (used by mode=create only;
                       mode=append preserves the existing body).
        profiles_dir:  Directory override. Defaults to config value.

    Returns:
        Absolute path to the written .md file (with optional selftest warning),
        or "ERROR: ..." description on failure.
    """
    if profiles_dir and (profiles_dir.startswith("/profiles") or profiles_dir == "/"):
        profiles_dir = None

    out_dir = Path(profiles_dir or _default_profiles_dir())

    if mode == "create":
        try:
            _validate_jobs(jobs)
        except ValueError as exc:
            return (
                f"ERROR: {exc}. "
                "Each job must have: name, type ('sql'/'lancedb'), severity, section_prompt, "
                "plus query (sql) or semantic_query (lancedb). "
                "Call write_profile again with corrected jobs."
            )
        content = _render_profile_md(name, jobs, markdown_body)

    elif mode == "append":
        existing = _read_existing(name, out_dir)
        if "error" in existing:
            avail = existing.get("available_profiles", [])
            return f"ERROR: {existing['error']}. Available: [{', '.join(avail)}]"

        existing_names = {j.get("name") for j in existing["jobs"]}
        duplicates = [j.get("name") for j in jobs if j.get("name") in existing_names]
        if duplicates:
            return (
                f"ERROR: job names already exist in '{name}': {duplicates}. "
                "Use unique names or overwrite with mode='create'."
            )

        # Validate incoming jobs with Pydantic
        try:
            typed_jobs = [ProfileJob(**j) for j in jobs]
            _validate_jobs([j.model_dump(exclude_none=True) for j in typed_jobs])
        except (ValueError, Exception) as exc:
            return f"ERROR: {exc}"

        merged = list(existing["jobs"]) + [j.model_dump(exclude_none=True) for j in typed_jobs]
        content = _render_profile_md(
            existing["name"],
            merged,
            existing["body"],
            persist_findings_to_db=existing["persist_findings_to_db"],
            max_findings_per_job=existing["max_findings_per_job"],
            version=str(existing["version"]),
        )
        name = existing["name"]  # use canonical name from existing profile

    else:
        return f"ERROR: unknown mode {mode!r} — use 'create' or 'append'"

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        return f"ERROR: cannot create directory '{out_dir}': {exc}"

    profile_path = out_dir / f"{name}.md"
    profile_path.write_text(content, encoding="utf-8")
    logger.info("write_profile: wrote %s (mode=%s)", profile_path, mode)

    selftest_msg = _try_selftest(str(profile_path))
    if selftest_msg:
        return f"{profile_path}\n\n{selftest_msg}"
    return str(profile_path)


# ---------------------------------------------------------------------------
# Test-compatibility alias — kept so existing unit tests that call
# _save_profile_validated(name, yaml_jobs, markdown_body, profiles_dir)
# continue to pass without modification.
# ---------------------------------------------------------------------------

def _save_profile_validated(
    name: str,
    yaml_jobs: list[ProfileJob],
    markdown_body: str,
    profiles_dir: str | None = None,
) -> str:
    jobs_as_dicts = [j.model_dump(exclude_none=True) for j in yaml_jobs]
    return write_profile(name=name, jobs=jobs_as_dicts, mode="create",
                         markdown_body=markdown_body, profiles_dir=profiles_dir)


if __name__ == "__main__":
    _args = json.loads(sys.stdin.read() or "{}")
    print(json.dumps(write_profile(**_args), default=str))
