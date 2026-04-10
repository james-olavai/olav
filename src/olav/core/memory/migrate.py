"""UKS Data Migration Utilities.

Provides one-time migration functions for upgrading existing LanceDB tables
to the Unified Knowledge Store schema (M3).

Functions:
    migrate_memory_table(store): Backfill origin/confidence/tags on existing memory rows.
    migrate_kb_chunks(store):    Move kb_chunks rows into the unified memory table
                                 (Phase 4, called from `olav kb migrate`).
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

    Iterates over all rows in the memory table and writes inferred values
    for the three new UKS columns based on the existing metadata.source field.

    This function is idempotent — rows that already have a non-default origin
    are still re-evaluated (idempotency holds because the inference is
    deterministic given the same metadata).

    Args:
        store:      LanceDBStore instance.
        table_name: Optional table name override (defaults to MEMORY_TABLE).
        batch_size: Not currently used (reserved for future chunking).

    Returns:
        Summary dict with keys ``updated``, ``skipped``, ``errors``.
    """
    from olav.core.memory import MEMORY_TABLE

    tname = table_name or MEMORY_TABLE

    if not store.table_exists(tname):
        logger.info(f"migrate_memory_table: table '{tname}' does not exist — skipping.")
        return {"updated": 0, "skipped": 0, "errors": 0}

    try:
        memories = store.get_memories(limit=100_000, table_name=tname)
    except Exception as e:
        logger.error(f"migrate_memory_table: failed to fetch rows: {e}")
        return {"updated": 0, "skipped": 0, "errors": 1}

    updated = skipped = errors = 0

    for mem in memories:
        mem_id = mem.get("id")
        if not mem_id:
            skipped += 1
            continue

        origin, confidence = _infer_origin_confidence(mem)

        result = store.update_memory(
            mem_id,
            table_name=tname,
            origin=origin,
            confidence=confidence,
            tags="[]",
        )

        if result.get("status") in ("success", "noop"):
            updated += 1
        else:
            errors += 1
            logger.warning(f"migrate_memory_table: failed to update {mem_id}: {result}")

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
