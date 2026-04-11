"""Migration v0.14: sessions table in audit.duckdb.

Tracks conversation sessions for CLI/TUI/Web session resumption (M4).
"""

from __future__ import annotations


def apply_migration(conn) -> None:
    """Create sessions table if it does not exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            thread_id     VARCHAR PRIMARY KEY,
            user_id       VARCHAR NOT NULL,
            agent_id      VARCHAR,
            title         VARCHAR,
            interface     VARCHAR,
            created_at    TIMESTAMP DEFAULT current_timestamp,
            last_active   TIMESTAMP DEFAULT current_timestamp,
            message_count INTEGER DEFAULT 0,
            is_active     BOOLEAN DEFAULT true
        )
    """)
