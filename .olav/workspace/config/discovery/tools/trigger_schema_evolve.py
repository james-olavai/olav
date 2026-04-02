"""trigger_schema_evolve — Phase 5 thin wrapper (api_discovery.md §3.5).

Runs OPTICS clustering over unclassified evolution-pool entries and stages
``propose_standard`` mutation requests for human approval.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def trigger_schema_evolve(
    domain: str = "platform",
    min_samples: int = 3,
) -> dict[str, Any]:
    """Trigger schema evolution: cluster unclassified fields and propose standard names.

    Parameters
    ----------
    domain:
        Domain namespace to scope the cluster proposals (default: ``"platform"``).
    min_samples:
        OPTICS ``min_samples`` — minimum density threshold for a cluster to be
        considered significant (default: ``3``).

    Returns
    -------
    dict with keys:
        ``clusters_found``  — number of dense clusters detected
        ``proposals``       — list of proposed standard field names staged for review
        ``skipped``         — reason string if evolution was skipped, else ``None``
    """
    import duckdb

    from olav.core.config import PathsConfig
    from olav.core.schema_engine import SchemaEngine
    from olav.core.schema_mutation_service import SchemaMutationService

    paths = PathsConfig()
    staging_dir = Path(paths.DATABASES_DIR) / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    svc = SchemaMutationService(staging_dir=staging_dir)
    engine = SchemaEngine(mutation_service=svc)

    db_path = str(Path(paths.DATABASES_DIR) / "domain.duckdb")
    conn = duckdb.connect(db_path, read_only=False)
    try:
        result = engine.evolve_trigger(conn, domain=domain, min_samples=min_samples)
    finally:
        conn.close()

    return result
