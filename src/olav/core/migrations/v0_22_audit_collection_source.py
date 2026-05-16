"""Migration v0.22: audit_runs.collection_source column.

Backs the portable-snapshot-ingest design (``dev_docs/80``) — every
``audit_runs`` row now records *how* the data was acquired, so a query
can tell "live SSH at 14:32" apart from "ingested bundle from R1 at 11:08".

Values written by callers:

  - ``live_ssh``                      —  legacy / classic SSH collection
  - ``bundle:<collector>:<version>``  —  offline bundle (olav-collector etc.)
  - ``ingest:rancid``                 —  rancid backup adapter
  - ``ingest:dump``                   —  loose vendor dump adapter

The column is nullable; the backfill below stamps pre-existing rows as
``live_ssh`` because that was the only acquisition path before v0.22.
"""
from __future__ import annotations


def apply_migration(conn) -> None:
    """Idempotently add ``collection_source`` to ``audit_runs`` + backfill."""
    conn.execute(
        "ALTER TABLE audit_runs ADD COLUMN IF NOT EXISTS collection_source VARCHAR"
    )
    # Backfill any rows that predate this column.  IS NULL guards re-runs.
    conn.execute(
        "UPDATE audit_runs SET collection_source = 'live_ssh' "
        "WHERE collection_source IS NULL"
    )
