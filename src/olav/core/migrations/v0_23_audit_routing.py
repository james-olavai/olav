"""Migration v0.23: audit_runs routing columns.

routed_agent  — first sub-agent the orchestrator delegated to (e.g. 'analyzer', 'sim')
workflow_type — inferred intent: 'change_plan' | 'investigation' | 'blast_radius' | 'query' | None
"""
from __future__ import annotations


def apply_migration(conn) -> None:
    conn.execute("ALTER TABLE audit_runs ADD COLUMN IF NOT EXISTS routed_agent VARCHAR")
    conn.execute("ALTER TABLE audit_runs ADD COLUMN IF NOT EXISTS workflow_type VARCHAR")
