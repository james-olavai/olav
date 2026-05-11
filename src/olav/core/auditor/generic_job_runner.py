"""Generic audit job dispatcher — Phase F-Audit (rev 273, 2026-05-12).

Audit-side counterpart to ``olav.core.cab.generic_intent_handler``.
Where the CAB handler emits CLI from per-intent YAML, this module
*executes* per-job-type YAML against the runtime.

Goals:
  * Adding a new audit job type requires only:
    (1) ``src/olav/data/audit_job_schemas/<type>.job.yaml`` with
        args + executor dotted-path
    (2) the executor Python function in the location it points to

  * NO edit to map_engine.py's elif dispatch chain
  * NO edit to ProfileJob.type Literal (Pydantic) for runtime; the
    author-side strict-validation enum is a separate concern

  * Each executor is a plain Python callable with signature
    ``(args: dict, db_conn) -> list[dict]``.  Findings are
    list[dict] with the columns declared in the schema's
    ``finding_shape.required_columns``.

This module is the experimental parallel implementation — it does NOT
yet replace map_engine's elif dispatch.  Once stable, map_engine can
delegate to ``run_audit_job`` for any job whose ``type`` has a
matching schema, falling back to the elif chain for unknown ones.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)


# ── Schema discovery ────────────────────────────────────────────────


def _schemas_dir() -> Path:
    """Locate bundled audit job schemas (mirrors generic_intent_handler)."""
    return Path(__file__).resolve().parent.parent.parent / "data" / "audit_job_schemas"


def list_job_types() -> list[str]:
    """All audit job types currently declared via YAML schemas."""
    d = _schemas_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem.replace(".job", "") for p in d.glob("*.job.yaml"))


def load_job_schema(job_type: str) -> dict[str, Any]:
    """Load and return the parsed schema dict for ``job_type``."""
    p = _schemas_dir() / f"{job_type}.job.yaml"
    if not p.exists():
        raise FileNotFoundError(
            f"audit job schema not found: {p}. "
            f"Available: {list_job_types()}"
        )
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"audit job schema {p} is not a YAML mapping")
    return data


# ── Args validation + defaults ──────────────────────────────────────


def _validate_and_default_args(
    schema: dict[str, Any],
    job_dict: dict[str, Any],
) -> dict[str, Any]:
    """Merge each declared arg with the profile-supplied job entry.

    job_dict is a single entry from profile.jobs[] (post-YAML-parse).
    Returns a flat ``{arg_name: value}`` dict ready for the executor.
    """
    merged: dict[str, Any] = {}
    decls = schema.get("args", {}) or {}
    for name, decl in decls.items():
        if name in job_dict:
            merged[name] = job_dict[name]
        elif "default" in decl:
            merged[name] = decl["default"]
        elif decl.get("required", False):
            raise ValueError(
                f"audit job type {schema.get('job_type')!r}: "
                f"missing required arg {name!r}"
            )
        else:
            merged[name] = None
    return merged


# ── Executor resolution ─────────────────────────────────────────────


def _resolve_executor(dotted_path: str) -> Callable:
    """Import and return the callable at ``module.path:function_name``."""
    if ":" not in dotted_path:
        raise ValueError(
            f"executor path must be 'module:function'; got {dotted_path!r}"
        )
    mod_path, func_name = dotted_path.split(":", 1)
    try:
        mod = importlib.import_module(mod_path)
    except ImportError as exc:
        raise ImportError(
            f"executor module {mod_path!r} not importable: {exc}"
        ) from exc
    func = getattr(mod, func_name, None)
    if func is None or not callable(func):
        raise AttributeError(
            f"executor {dotted_path!r}: function {func_name!r} not found in {mod_path!r}"
        )
    return func


# ── Finding-shape validation ────────────────────────────────────────


def _check_finding_shape(
    findings: list[dict[str, Any]],
    schema: dict[str, Any],
) -> None:
    """Raise if any finding row is missing a required column."""
    required = (schema.get("finding_shape") or {}).get("required_columns", [])
    if not required:
        return
    required_set = set(required)
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            raise TypeError(
                f"finding[{i}]: executor must return list[dict]; got {type(f).__name__}"
            )
        missing = required_set - set(f.keys())
        if missing:
            raise ValueError(
                f"finding[{i}] from job_type={schema.get('job_type')!r} "
                f"missing required columns {sorted(missing)} "
                f"(got: {sorted(f.keys())})"
            )


# ── Top-level entry ─────────────────────────────────────────────────


def run_audit_job(
    job_dict: dict[str, Any],
    db_conn: Any = None,
) -> dict[str, Any]:
    """Execute a single Profile job entry through its YAML-declared executor.

    Args:
        job_dict: One entry from a Profile's ``jobs:`` list. Must have
            a ``type`` field naming a known job schema.
        db_conn: DuckDB connection (or any duck-typed object with
            ``.execute(sql, args).fetchall()``). Some executors don't
            need a DB conn (e.g. http_probe), in which case None is OK.

    Returns:
        {
          "job_type": str,
          "count": int,
          "findings": list[dict],
          "executor": str,  # dotted path that actually ran
        }
    """
    job_type = job_dict.get("type", "sql")
    schema = load_job_schema(job_type)

    args = _validate_and_default_args(schema, job_dict)
    executor = _resolve_executor(schema["executor"])

    try:
        findings = executor(args, db_conn)
    except Exception as exc:
        raise RuntimeError(
            f"audit job executor {schema['executor']!r} raised: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if not isinstance(findings, list):
        raise TypeError(
            f"executor {schema['executor']!r} must return list[dict]; "
            f"got {type(findings).__name__}"
        )

    _check_finding_shape(findings, schema)

    return {
        "job_type": job_type,
        "count": len(findings),
        "findings": findings,
        "executor": schema["executor"],
    }
