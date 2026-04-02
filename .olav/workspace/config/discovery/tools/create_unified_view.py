"""create_unified_view — thin tool wrapper around schema_engine.create_unified_view.

Delegates to ``olav.core.schema_engine.create_unified_view()``.
Returns the SQL string and stages a ``replace_view`` mutation request via
SchemaMutationService so the VIEW is applied atomically by the platform.
"""

from __future__ import annotations


def create_unified_view(
    command: str,
    mappings: list[dict],
    domain: str = "netops",
    auto_stage: bool = True,
) -> dict:
    """Generate a normalised DuckDB VIEW and optionally stage it for application.

    Parameters
    ----------
    command:    CLI command the VIEW covers, e.g. ``"show interfaces"``.
    mappings:   List of ``{"raw_key", "standard_name", "data_type"}`` dicts.
    domain:     Domain namespace used for staging the mutation request.
    auto_stage: If ``True`` (default), stage a ``replace_view`` request via
                SchemaMutationService so IngestManager can apply it atomically.

    Returns
    -------
    dict with keys ``sql`` (the generated SQL) and ``staged`` (bool).
    """
    from olav.core.schema_engine import create_unified_view as _gen_view, build_mutation_request
    from olav.core.schema_mutation_service import SchemaMutationService
    from olav.core.config import DATABASES_DIR
    from pathlib import Path

    sql = _gen_view(command, mappings)

    staged = False
    if auto_stage:
        staging_dir = Path(DATABASES_DIR) / "staging"
        svc = SchemaMutationService(staging_dir=staging_dir)
        view_name = "v_unified_" + command.strip().replace(" ", "_").replace("-", "_")
        req = build_mutation_request(
            domain=domain,
            mutation_type="replace_view",
            target=view_name,
            payload={"sql": sql},
        )
        svc.stage_request(req)
        staged = True

    return {"sql": sql, "staged": staged}
