"""UKS Data Migration Utilities.

Provides one-time migration functions for upgrading existing LanceDB tables
to the Unified Knowledge Store schema (M3).

Functions:
    migrate_memory_table(store): Backfill origin/confidence/tags on existing memory rows.
    migrate_kb_chunks(store):    Move kb_chunks rows into the unified memory table
                                 (Phase 4, called from `olav kb migrate`).
    migrate_add_expires_at(store): Add expires_at column (ADR-0015, nullable, default NULL).
"""

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from olav.core.memory import LanceDBStore

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Source → origin/confidence mapping table
# ─────────────────────────────────────────────────────────────────────────────

_SOURCE_MAP = {
    "auto_capture": ("agent", None),    # confidence = importance from meta
    "failure_record": ("audit", 1.0),
    "network_event": ("agent", 0.7),
}

_DEFAULT_ORIGIN = "user"
_DEFAULT_CONFIDENCE = 0.8


def _infer_origin_confidence(mem: dict) -> tuple[str, float]:
    """Infer (origin, confidence) from a memory row's metadata."""
    try:
        meta = json.loads(mem.get("metadata") or "{}")
    except Exception:
        meta = {}

    source = meta.get("source", "")
    if source in _SOURCE_MAP:
        origin, confidence = _SOURCE_MAP[source]
        if confidence is None:
            # Use importance from metadata, fallback to 0.5
            confidence = float(meta.get("importance", 0.5))
        return origin, confidence

    return _DEFAULT_ORIGIN, _DEFAULT_CONFIDENCE


# ─────────────────────────────────────────────────────────────────────────────
# migrate_memory_table
# ─────────────────────────────────────────────────────────────────────────────


def migrate_memory_table(
    store: "LanceDBStore",
    table_name: str | None = None,
    *,
    batch_size: int = 500,
) -> dict:
    """Backfill origin, confidence, and tags for existing memory rows.

    Uses a bulk pandas-based approach to avoid per-row LanceDB update calls.
    Groups rows by inferred (origin, confidence) and issues one tbl.update()
    per distinct group via an IN (id, ...) WHERE clause.

    Args:
        store:      LanceDBStore instance.
        table_name: Optional table name override (defaults to MEMORY_TABLE).
        batch_size: Number of IDs per IN-clause batch to avoid SQL length limits.

    Returns:
        Summary dict with keys ``updated``, ``skipped``, ``errors``.
    """
    from olav.core.memory import MEMORY_TABLE

    tname = table_name or MEMORY_TABLE

    if not store.table_exists(tname):
        logger.info(f"migrate_memory_table: table '{tname}' does not exist — skipping.")
        return {"updated": 0, "skipped": 0, "errors": 0}

    # Use tbl.to_pandas() for a fast full-table scan (avoids vector search hang)
    try:
        tbl = store.get_table(tname)
        df = tbl.to_pandas()
    except Exception as e:
        logger.error(f"migrate_memory_table: failed to read table: {e}")
        return {"updated": 0, "skipped": 0, "errors": 1}

    if df.empty:
        return {"updated": 0, "skipped": 0, "errors": 0}

    # Group rows by (origin, confidence) to minimise number of UPDATE calls
    from collections import defaultdict
    groups: dict[tuple[str, float], list[str]] = defaultdict(list)
    skipped = 0

    for _, row in df.iterrows():
        row_id = row.get("id")
        if not row_id:
            skipped += 1
            continue
        origin, confidence = _infer_origin_confidence(row.to_dict())
        groups[(origin, confidence)].append(str(row_id))

    updated = errors = 0

    for (origin, confidence), ids in groups.items():
        # Batch IDs into chunks to avoid excessively long SQL
        for i in range(0, len(ids), batch_size):
            chunk = ids[i : i + batch_size]
            id_list = ", ".join(f"'{rid}'" for rid in chunk)
            where = f"id IN ({id_list})"
            try:
                tbl.update(
                    where=where,
                    values={"origin": origin, "confidence": confidence, "tags": "[]"},
                )
                updated += len(chunk)
            except Exception as e:
                logger.warning(f"migrate_memory_table: batch update failed: {e}")
                errors += len(chunk)

    summary = {"updated": updated, "skipped": skipped, "errors": errors}
    logger.info(f"migrate_memory_table: {summary}")
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# migrate_kb_chunks  (Phase 4 — called by `olav kb migrate`)
# ─────────────────────────────────────────────────────────────────────────────


def migrate_kb_chunks(
    store: "LanceDBStore",
    *,
    dry_run: bool = False,
) -> dict:
    """Move all rows from the legacy kb_chunks table into the unified memory table.

    LEGACY-KEEP: driven by ``olav kb migrate``. Remove after v0.11.0 drops
    out of the supported upgrade window (see COMPATIBILITY_CUTOFF).

    Each chunk is inserted with origin='document', confidence=1.0, and an
    empty tags list.  The source kb_chunks table is NOT dropped automatically
    to allow rollback inspection; use ``store.db.drop_table('kb_chunks')``
    manually after verifying results.

    Args:
        store:   LanceDBStore instance.
        dry_run: If True, count rows without writing anything.

    Returns:
        Summary dict with keys ``migrated``, ``skipped``, ``errors``, ``dry_run``.
    """
    if not store.table_exists("kb_chunks"):
        logger.info("migrate_kb_chunks: kb_chunks table does not exist — nothing to migrate.")
        return {"migrated": 0, "skipped": 0, "errors": 0, "dry_run": dry_run}

    try:
        kb_table = store.get_table("kb_chunks")
        rows = kb_table.search().limit(100_000).to_list()
    except Exception as e:
        logger.error(f"migrate_kb_chunks: failed to read kb_chunks: {e}")
        return {"migrated": 0, "skipped": 0, "errors": 1, "dry_run": dry_run}

    if dry_run:
        return {"migrated": len(rows), "skipped": 0, "errors": 0, "dry_run": True}

    migrated = skipped = errors = 0

    for row in rows:
        row_id = row.get("id")
        text = row.get("text", "")
        vector = row.get("vector")

        if not row_id or not text or vector is None:
            skipped += 1
            continue

        result = store.add_memory(
            id=row_id,
            text=text,
            vector=list(vector),
            category=row.get("category", "fact"),
            scope=row.get("scope", "global"),
            origin="document",
            confidence=1.0,
            tags="[]",
            metadata={"source": "kb_migration", "original_table": "kb_chunks"},
        )

        if result.get("status") in ("success", "ok"):
            migrated += 1
        elif result.get("status") == "blocked":
            skipped += 1
            logger.debug(f"migrate_kb_chunks: blocked row {row_id}: {result}")
        else:
            errors += 1
            logger.warning(f"migrate_kb_chunks: failed row {row_id}: {result}")

    summary = {"migrated": migrated, "skipped": skipped, "errors": errors, "dry_run": False}
    logger.info(f"migrate_kb_chunks: {summary}")
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# migrate_add_expires_at  (ADR-0015 — called by create_table on open)
# ─────────────────────────────────────────────────────────────────────────────


def migrate_add_expires_at(
    store: "LanceDBStore",
    table_name: str | None = None,
) -> dict:
    """Add the ``expires_at`` column (ADR-0015) to an existing memory table.

    The column is nullable with default NULL so all existing rows are
    unaffected (they will never expire).  Only ``reflection`` rows written
    after ADR-0015 will have a non-NULL value.

    This migration is idempotent — calling it on a table that already has
    ``expires_at`` is a no-op.

    Args:
        store:      LanceDBStore instance.
        table_name: Optional table name override (defaults to MEMORY_TABLE).

    Returns:
        Summary dict with keys ``added``, ``skipped``, ``message``.
    """
    from olav.core.memory import MEMORY_TABLE

    tname = table_name or MEMORY_TABLE

    if not store.table_exists(tname):
        logger.info(f"migrate_add_expires_at: table '{tname}' does not exist — skipping.")
        return {"added": 0, "skipped": 1, "message": "table missing"}

    try:
        tbl = store.get_table(tname)
        existing_names = {f.name for f in tbl.schema}
        if "expires_at" in existing_names:
            logger.debug(f"migrate_add_expires_at: '{tname}' already has expires_at — skipping.")
            return {"added": 0, "skipped": 0, "message": "already migrated"}

        tbl.add_columns({"expires_at": "cast(NULL as timestamp)"})
        logger.info(f"migrate_add_expires_at: added 'expires_at' to '{tname}' (ADR-0015)")
        return {"added": 1, "skipped": 0, "message": "ok"}
    except Exception as e:
        logger.error(f"migrate_add_expires_at: failed: {e}")
        return {"added": 0, "skipped": 0, "message": str(e)}
