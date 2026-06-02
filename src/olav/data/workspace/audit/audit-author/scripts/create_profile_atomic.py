"""create_profile_atomic.py — single-call Profile creation.

Rev 261 fix for A1 timeout root cause (gemma4 + multi-step LLM
decisions in audit Author Mode 1).

The Mode 1 workflow (Create) was 3 LLM tool calls:
  1. execute_skill_script(database_introspection)
  2. execute_skill_script(test_map_query) — once per job
  3. save_profile(yaml_jobs=[ProfileJob, ...])

gemma4 31B nothink repeatedly miscounted step 1 (4× database_
introspection in rev 260 A1), prolonging the LLM tool-call cycle
past the 480s budget. The atomic version collapses all three into
one tool call — same Pydantic-typed ``ProfileJob`` schema as
``save_profile``, but the server side runs introspection + per-job
SQL validation + the write in one shot.

Pattern matches rev 247 Patch L (``validate_tcf_in_lab``) which
solved the same "small LLM repeats tool calls" failure for the lab
flow.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# Re-use ProfileJob schema from the existing save_profile.py — Pydantic
# v2's model_rebuild handles the duplicated class definition.
class _AtomicProfileJob(BaseModel):
    """Same canonical schema as save_profile.ProfileJob."""
    name: str = Field(description="Unique identifier in UPPER_SNAKE_CASE, e.g. 'CPU_High'")
    type: str = Field(description="Job type: 'sql' for DuckDB queries, 'lancedb' for semantic search. Must be exactly 'sql' or 'lancedb'.")
    severity: str = Field(description="Alert severity. Must be exactly 'Critical', 'Warning', or 'Info'.")
    section_prompt: str = Field(description="Analysis instruction for the auditor — plain text describing what to look for in the data.")
    query: str | None = Field(default=None, description="SQL query (required when type='sql'). Use `INTERVAL :window` for time range. Must return columns: device, metric_value, metric_name, severity_hint.")
    semantic_query: str | None = Field(default=None, description="Semantic search string (required when type='lancedb').")
    threshold: float | None = Field(default=None, description="Similarity threshold 0-1 for lancedb jobs.")


class _CreateProfileAtomicInput(BaseModel):
    name: str = Field(description="Profile filename stem (no .md), e.g. 'bgp_neighbor_count'")
    jobs: list[_AtomicProfileJob] = Field(description="List of audit jobs (canonical schema). All SQL queries are validated server-side before the file is written; if any fails, no file is written and a detailed error is returned.")
    markdown_body: str = Field(default="", description="Markdown narrative body for the profile (brief description or empty string).")
    profiles_dir: str | None = Field(default=None, description="Output directory. Leave None to use the project default (.olav/workspace/audit/profiles).")
    skip_introspection: bool = Field(default=False, description="Set True to skip schema discovery — only use when you already know table/column names are valid.")


# ── Server-side helpers (no LLM) ────────────────────────────────────


def _default_profiles_dir() -> str:
    try:
        from olav.core.config import get_paths_config
        return get_paths_config().audit_profiles_dir
    except Exception:
        return ".olav/workspace/audit/profiles"


def _introspect_db() -> dict[str, Any]:
    """Mirror of database_introspection skill_script logic, server-side."""
    try:
        import duckdb
        from olav.core.config import get_paths_config
    except Exception as exc:
        return {"ok": False, "error": f"duckdb / config import failed: {exc}"}

    try:
        db_path = get_paths_config().main_db
    except Exception as exc:
        return {"ok": False, "error": f"db_path resolve failed: {exc}"}

    try:
        with duckdb.connect(str(db_path), read_only=True) as conn:
            tables = conn.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema NOT IN ('pg_catalog','information_schema') "
                "ORDER BY table_schema, table_name"
            ).fetchall()
            return {
                "ok": True,
                "tables": [f"{ts}.{tn}" if ts != "main" else tn for ts, tn in tables],
            }
    except Exception as exc:
        return {"ok": False, "error": f"DB query failed: {exc}"}


_INTERVAL_RE = re.compile(r":window\b", re.IGNORECASE)


def _validate_sql_job(query: str, db_path: str | Path) -> tuple[bool, str]:
    """Run the query under LIMIT 0 to validate syntax + table/column refs.

    Returns (ok, error_message).
    """
    import duckdb

    # Substitute :window with a real interval string so DuckDB parses
    # the parameterised form.
    sql = _INTERVAL_RE.sub("'1 hours'::INTERVAL", query)
    test_sql = f"SELECT * FROM ({sql.rstrip().rstrip(';')}) __q LIMIT 0"
    try:
        with duckdb.connect(str(db_path), read_only=True) as conn:
            conn.execute(test_sql)
        return True, ""
    except Exception as exc:
        return False, f"SQL validation failed: {type(exc).__name__}: {exc}"


def _render_profile_md(name: str, jobs: list[dict], body: str) -> str:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML required") from exc
    front = yaml.dump({
        "name": name,
        "version": "4.0",
        "persist_findings_to_db": False,
        "max_findings_per_job": 50,
        "jobs": jobs,
    }, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return f"---\n{front}---\n\n{body.strip()}\n"


# ── Public function ──────────────────────────────────────────────────


def create_profile_atomic(
    name: str,
    jobs: list[_AtomicProfileJob],
    markdown_body: str = "",
    profiles_dir: str | None = None,
    skip_introspection: bool = False,
) -> dict[str, Any]:
    """Server-side atomic create: introspect + validate + write."""
    out: dict[str, Any] = {"name": name}

    # 1. Validate canonical-schema branch invariant.
    for i, j in enumerate(jobs):
        if j.type not in ("sql", "lancedb"):
            return {**out, "ok": False,
                    "error": f"jobs[{i}].type must be 'sql' or 'lancedb', got {j.type!r}"}
        if j.severity not in ("Critical", "Warning", "Info"):
            return {**out, "ok": False,
                    "error": f"jobs[{i}].severity must be Critical/Warning/Info, got {j.severity!r}"}
        if j.type == "sql" and not (j.query and j.query.strip()):
            return {**out, "ok": False,
                    "error": f"jobs[{i}] type='sql' requires non-empty query"}
        if j.type == "lancedb" and not (j.semantic_query and j.semantic_query.strip()):
            return {**out, "ok": False,
                    "error": f"jobs[{i}] type='lancedb' requires non-empty semantic_query"}

    # 2. Optional DB introspection (skipped when caller knows schema).
    introspection: dict[str, Any] | None = None
    if not skip_introspection:
        introspection = _introspect_db()
        # Soft failure — introspection is informational; if it fails,
        # we still try to validate each SQL job below.

    # 3. Validate each SQL job against the DB (skip lancedb).
    db_path = None
    try:
        from olav.core.config import get_paths_config
        db_path = str(get_paths_config().main_db)
    except Exception:
        pass

    validation_errors: list[dict[str, str]] = []
    if db_path:
        for j in jobs:
            if j.type != "sql":
                continue
            ok, err = _validate_sql_job(j.query or "", db_path)
            if not ok:
                validation_errors.append({"job": j.name, "error": err})

    if validation_errors:
        return {
            **out, "ok": False,
            "error": "one or more SQL jobs failed validation; profile NOT written",
            "validation_errors": validation_errors,
            "introspection": introspection,
            "hint": "Fix the offending SQL (table/column references) and retry. Use the introspection output to find real table names.",
        }

    # 4. Write the profile.
    out_dir = Path(profiles_dir or _default_profiles_dir())
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        return {**out, "ok": False,
                "error": f"cannot create dir {out_dir}: {exc}"}

    jobs_as_dicts = [j.model_dump(exclude_none=True) for j in jobs]
    profile_path = out_dir / f"{name}.md"
    try:
        profile_path.write_text(
            _render_profile_md(name, jobs_as_dicts, markdown_body),
            encoding="utf-8",
        )
    except Exception as exc:
        return {**out, "ok": False, "error": f"write failed: {exc}"}

    return {
        **out,
        "ok": True,
        "profile_path": str(profile_path),
        "job_count": len(jobs),
        "validated_sql_jobs": len([j for j in jobs if j.type == "sql"]),
        "introspection_used": introspection is not None and introspection.get("ok"),
        "message": (
            f"Profile '{name}' created successfully at {profile_path}. "
            f"{len(jobs)} job(s) written; all SQL queries validated against the live DB."
        ),
    }


_AtomicProfileJob.model_rebuild()
_CreateProfileAtomicInput.model_rebuild()


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    # Reconstruct Pydantic objects from dicts
    if "jobs" in _args:
        _args["jobs"] = [_AtomicProfileJob(**j) if isinstance(j, dict) else j for j in _args["jobs"]]
    result = create_profile_atomic(**_args)
    print(_json.dumps(result, default=str))
