"""Agent Memory - Session persistence for OLAV agent.

Provides persistent storage for conversation history using DuckDB.
"""

import json
import logging

from olav.core.unified_database import UnifiedDatabase

logger = logging.getLogger(__name__)


class AgentMemory:
    """Session memory persistence using User-Local DuckDB."""

    def __init__(self, max_messages: int = 100, memory_file: str | None = None) -> None:
        """Initialize agent memory (memory_file arg is deprecated but kept for compat)."""
        self.max_messages = max_messages
        self.session_id = None  # Could be generated per session if needed
        # Ensure schema exists by triggering UDB init
        with UnifiedDatabase():
            pass

    def add(self, role: str, content: str, **kwargs: object) -> None:
        """Add a message to memory."""
        try:
            metadata_json = json.dumps(kwargs)
            with UnifiedDatabase() as db:
                db.conn.execute(
                    """
                    INSERT INTO commands.main.session_history (role, content, metadata)
                    VALUES (?, ?, ?)
                """,
                    [role, content, metadata_json],
                )
        except Exception as e:
            logger.debug(f"Failed to save message to database: {e}")

    def get_context(self, max_messages: int | None = None) -> list[dict[str, object]]:
        """Get conversation context."""
        limit = max_messages if max_messages else self.max_messages
        try:
            with UnifiedDatabase() as db:
                # Get recent messages (use parameterized query to avoid SQL injection)
                rows = db.conn.execute(
                    """
                    SELECT role, content, metadata
                    FROM commands.main.session_history
                    ORDER BY created_at DESC
                    LIMIT ?
                """,
                    [limit],
                ).fetchall()

                messages = []
                for row in reversed(rows):  # Reverse to get chronological order
                    metadata = json.loads(row[2]) if row[2] else {}
                    messages.append(
                        {
                            "role": row[0],
                            "content": row[1],
                            **metadata,
                        }
                    )
                return messages
        except Exception as e:
            logger.debug(f"Failed to get context from database: {e}")
            return []

    def clear(self) -> None:
        """Clear all messages."""
        try:
            with UnifiedDatabase() as db:
                db.conn.execute("DELETE FROM commands.main.session_history")
        except Exception as e:
            logger.debug(f"Failed to clear session history: {e}")

    def save(self) -> None:
        """No-op for DuckDB implementation (auto-saved)."""
        pass

    def get_stats(self) -> dict[str, object]:
        """Get memory statistics."""
        try:
            with UnifiedDatabase() as db:
                total = db.conn.execute(
                    "SELECT COUNT(*) FROM commands.main.session_history"
                ).fetchone()[0]
                return {
                    "total_messages": total,
                    "storage": "DuckDB (User-Local)",
                }
        except Exception:
            return {"error": "DB Unreachable"}

    def get_conversation_messages(
        self, max_turns: int = 10, max_chars: int = 8000
    ) -> list[tuple[str, str]]:
        """Get recent conversation messages formatted for LangChain."""
        messages = self.get_context(max_messages=max_turns * 2)

        result = []
        total_chars = 0

        for msg in messages:
            role = str(msg.get("role", "user"))
            content = str(msg.get("content", ""))

            # Skip tool messages (not useful for context)
            if role == "tool":
                continue

            # Truncate long messages
            if len(content) > 2000:
                content = content[:1800] + "\n... [truncated]"

            # Check total character limit
            if total_chars + len(content) > max_chars:
                if result:
                    result.insert(0, ("system", "[Earlier conversation context was truncated]"))
                break

            result.append((role, content))
            total_chars += len(content)

        return result
