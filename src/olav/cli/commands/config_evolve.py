"""olav config evolve — Human-gated schema evolution approval CLI.

Usage::

    olav config evolve --list
    olav config evolve --approve <evolution_id>

These commands surface the ``pending_schema_evolutions`` table that is
populated by ``trigger_schema_evolve`` (and any ``propose_standard`` mutation
applied via ``SchemaMutationService``).

Design constraints (api_discovery.md §3.5, §4):
  - Engineers review proposals via ``--list`` before anything is written to
    the live LanceDB field-mappings collection.
  - ``--approve`` marks the DB row as approved and writes the new standard
    field name into the ``{domain}_field_mappings`` LanceDB collection so
    future ``classify_field`` calls can match against it.
  - No direct writes to ``mapping_rules`` here — that stays with
    ``SchemaMutationService.apply_approved()``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from olav.core.auth.authz import AuthorizationError, require_permission

logger = logging.getLogger(__name__)

# Column widths for --list table output
_COL_ID = 36
_COL_DOMAIN = 12
_COL_CLUSTER = 8
_COL_PROPOSAL = 30
_COL_STATUS = 18
_COL_CREATED = 20


def _get_db_conn(db_path: str | Path):
    """Return a DuckDB connection to the domain DB (lazy import)."""
    import duckdb  # noqa: PLC0415

    return duckdb.connect(str(db_path))


def _ensure_evolutions_table(conn) -> None:
    """Idempotently create pending_schema_evolutions if absent."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_schema_evolutions (
            evolution_id  VARCHAR PRIMARY KEY,
            cluster_id    VARCHAR,
            proposal      VARCHAR,
            domain        VARCHAR,
            status        VARCHAR DEFAULT 'pending',
            created_at    TIMESTAMPTZ DEFAULT now()
        )
    """)


def cmd_evolve_list(domain_db_path: str | Path) -> dict[str, Any]:
    """List all pending schema evolution proposals.

    Returns a dict suitable for CLI display::

        {
            "status": "ok",
            "rows": [{"evolution_id": ..., "proposal": ..., ...}, ...],
            "formatted": "<table string>",
        }
    """
    conn = _get_db_conn(domain_db_path)
    try:
        _ensure_evolutions_table(conn)
        rows = conn.execute("""
            SELECT evolution_id, domain, cluster_id, proposal, status, created_at
            FROM pending_schema_evolutions
            WHERE status IN ('pending', 'pending_approval')
            ORDER BY created_at DESC
        """).fetchall()
    finally:
        conn.close()

    if not rows:
        return {
            "status": "ok",
            "rows": [],
            "formatted": "No pending schema evolution proposals.",
        }

    records = [
        {
            "evolution_id": r[0],
            "domain": r[1] or "",
            "cluster_id": str(r[2]) if r[2] is not None else "",
            "proposal": r[3] or "",
            "status": r[4] or "",
            "created_at": str(r[5])[:19] if r[5] else "",
        }
        for r in rows
    ]

    # Build a simple ASCII table
    header = (
        f"{'ID':<{_COL_ID}}  "
        f"{'DOMAIN':<{_COL_DOMAIN}}  "
        f"{'CLUSTER':<{_COL_CLUSTER}}  "
        f"{'PROPOSED NAME':<{_COL_PROPOSAL}}  "
        f"{'STATUS':<{_COL_STATUS}}  "
        f"{'CREATED':<{_COL_CREATED}}"
    )
    separator = "-" * len(header)
    lines = [header, separator]
    for rec in records:
        lines.append(
            f"{rec['evolution_id']:<{_COL_ID}}  "
            f"{rec['domain']:<{_COL_DOMAIN}}  "
            f"{rec['cluster_id']:<{_COL_CLUSTER}}  "
            f"{rec['proposal']:<{_COL_PROPOSAL}}  "
            f"{rec['status']:<{_COL_STATUS}}  "
            f"{rec['created_at']:<{_COL_CREATED}}"
        )
    lines.append(f"\n{len(records)} proposal(s) pending review.")
    lines.append("Use: olav config evolve --approve <evolution_id>  to approve.")

    return {"status": "ok", "rows": records, "formatted": "\n".join(lines)}


def cmd_evolve_approve(
    evolution_id: str,
    domain_db_path: str | Path,
    lancedb_path: str | Path | None = None,
    *,
    role: str = "admin",
) -> dict[str, Any]:
    """Approve a pending schema evolution proposal.

    Marks the row ``status='approved'`` in ``pending_schema_evolutions`` and
    writes the new standard field name into the domain's LanceDB
    ``{domain}_field_mappings`` collection so that future ``classify_field``
    calls can use it.

    Args:
        evolution_id: The UUID of the evolution row to approve.
        domain_db_path: Path to ``domain.duckdb``.
        lancedb_path: Path to the LanceDB directory.  Defaults to
            ``~/.olav/databases/memory.lancedb`` (resolved from config).
        role: Caller's role — must be ``"admin"`` to approve.

    Raises:
        AuthorizationError: If the caller's role is not permitted to approve
            schema evolutions.

    Returns:
        ``{"status": "approved", "evolution_id": ..., "lancedb_written": bool}``
    """
    # RBAC gate: only admin may approve control-plane schema changes (TD-28)
    require_permission(role, "config", "evolve", "admin")

    conn = _get_db_conn(domain_db_path)
    try:
        _ensure_evolutions_table(conn)

        # Fetch the row
        row = conn.execute(
            """
            SELECT evolution_id, domain, cluster_id, proposal, status
            FROM pending_schema_evolutions
            WHERE evolution_id = ?
            """,
            [evolution_id],
        ).fetchone()

        if row is None:
            return {
                "status": "error",
                "message": f"No evolution proposal found with id={evolution_id!r}",
            }

        ev_id, domain, cluster_id, proposal, status = row

        if status == "approved":
            return {
                "status": "already_approved",
                "evolution_id": ev_id,
                "message": "This proposal has already been approved.",
            }

        # Mark as approved in DB
        conn.execute(
            "UPDATE pending_schema_evolutions SET status = 'approved' WHERE evolution_id = ?",
            [ev_id],
        )
    finally:
        conn.close()

    # Write the new standard name into LanceDB field_mappings
    lancedb_written = False
    if proposal:
        lancedb_written = _write_to_lancedb(
            proposed_name=proposal,
            domain=domain or "platform",
            cluster_id=cluster_id,
            lancedb_path=lancedb_path,
        )

    return {
        "status": "approved",
        "evolution_id": ev_id,
        "domain": domain,
        "proposed_name": proposal,
        "lancedb_written": lancedb_written,
    }


def _write_to_lancedb(
    proposed_name: str,
    domain: str,
    cluster_id: Any,
    lancedb_path: str | Path | None,
) -> bool:
    """Write an approved standard name into the domain LanceDB collection.

    Returns True if the write succeeded, False if LanceDB / embedder is
    unavailable (graceful degradation — the DB row is still marked approved).
    """
    try:
        import lancedb  # noqa: PLC0415
        import pyarrow as pa  # noqa: PLC0415

        from olav.core.embedder import get_embedder  # noqa: PLC0415
        from olav.core.schema_engine import get_domain_collection  # noqa: PLC0415
    except ImportError as exc:
        logger.warning("LanceDB write skipped (import error): %s", exc)
        return False

    try:
        if lancedb_path is None:
            from olav.core.config import settings  # noqa: PLC0415

            lancedb_path = Path(settings.databases_dir) / "memory.lancedb"

        db = lancedb.connect(str(lancedb_path))
        collection_name = get_domain_collection(domain)

        embedder = get_embedder()
        # Build a minimal semantic summary for the proposed name
        summary = f"{proposed_name} | evolved standard field | llm_evolved"
        vector = embedder.encode(summary, normalize_embeddings=True).tolist()

        record = {
            "openconfig_path": proposed_name,
            "description": f"Evolved standard field (cluster_id={cluster_id})",
            "data_type": "VARCHAR",
            "category": "evolved",
            "vector": vector,
            "source": "llm_evolved",
        }

        # Schema for the field_mappings collection
        schema = pa.schema(
            [
                ("openconfig_path", pa.string()),
                ("description", pa.string()),
                ("data_type", pa.string()),
                ("category", pa.string()),
                ("vector", pa.list_(pa.float32(), len(vector))),
                ("source", pa.string()),
            ]
        )

        try:
            table = db.open_table(collection_name)
            table.add([record])
        except Exception:  # noqa: BLE001
            # Table does not exist yet — create it
            db.create_table(collection_name, data=[record], schema=schema)

        logger.info("Written %r to LanceDB collection %r", proposed_name, collection_name)
        return True

    except Exception as exc:  # noqa: BLE001
        logger.warning("LanceDB write failed for %r: %s", proposed_name, exc)
        return False


def run_evolve_command(
    args: list[str], domain_db_path: str | Path, lancedb_path: str | Path | None = None
) -> str:
    """Dispatch ``olav config evolve`` subcommand from CLI args list.

    Args:
        args: Remaining CLI args after ``config evolve``.
        domain_db_path: Path to ``domain.duckdb``.
        lancedb_path: Optional override for LanceDB path.

    Returns:
        Human-readable string for console output.
    """
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        prog="olav config evolve",
        description="Human-gated schema evolution approval.",
        add_help=True,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--list",
        action="store_true",
        help="List all pending schema evolution proposals.",
    )
    group.add_argument(
        "--approve",
        metavar="EVOLUTION_ID",
        help="Approve a pending proposal by its ID.",
    )

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        return parser.format_help()

    if parsed.list:
        result = cmd_evolve_list(domain_db_path)
        return result["formatted"]

    # --approve
    result = cmd_evolve_approve(
        evolution_id=parsed.approve,
        domain_db_path=domain_db_path,
        lancedb_path=lancedb_path,
    )
    if result["status"] == "error":
        return f"Error: {result['message']}"
    if result["status"] == "already_approved":
        return f"Already approved: {result['evolution_id']}"

    lancedb_msg = (
        " (LanceDB updated)"
        if result.get("lancedb_written")
        else " (LanceDB write skipped — run olav-netops init to bootstrap)"
    )
    return (
        f"Approved: {result['evolution_id']}\n"
        f"  Domain:        {result.get('domain', '')}\n"
        f"  OpenConfig path: {result.get('proposed_name', '')}\n"
        f"  {lancedb_msg.strip()}"
    )
