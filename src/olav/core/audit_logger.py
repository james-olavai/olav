"""Audit Logger — Legacy Compatibility Shim (NOOP).

This module is retained solely for backward compatibility.
- ``log()`` is a no-op; all new audit events are written to ``audit.duckdb``
  via ``AuditEventRecorder``.
- ``get_history()`` reads the old ``.olav/history/{user}.log`` format for
  human-readable inspection of pre-v0.11 sessions.
- Do NOT add new callers. Route new audit events through ``AuditEventRecorder``.
"""

import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Legacy history path — kept for backward-compat read (get_history).
# No new entries are written here; all audit events go to audit.duckdb.
_username = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
USER_HISTORY_PATH = Path.home() / ".olav" / "history" / f"{_username}.log"


class AuditLogger:
    """Centralized audit logger for OLAV commands."""

    def __init__(self, log_path: Path | None = None):
        self.log_path = log_path or USER_HISTORY_PATH
        # Ensure directory exists
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._watermark_logged = False
        self._log_watermark_on_first_call()

    def _log_watermark_on_first_call(self) -> None:
        """No-op: watermark is now written to audit.duckdb by AuditEventRecorder."""
        self._watermark_logged = True

    def log(
        self, command: str, session_id: str | None = None, metadata: dict | None = None
    ) -> None:
        """Log a command to the audit file.

        Args:
            command: The command that was executed
            session_id: Optional session identifier
            metadata: Optional additional metadata
        """
        timestamp = datetime.now().isoformat()
        username = os.environ.get("USER") or os.getlogin()

        log_entry = f"[{timestamp}] USER={username}"
        if session_id:
            log_entry += f" SESSION={session_id}"
        log_entry += f" CMD={command}"

        if metadata:
            for key, value in metadata.items():
                log_entry += f" {key}={value}"

        log_entry += "\n"

        # File writing is superseded by AuditEventRecorder → audit.duckdb.
        logger.debug("audit_logger (legacy no-op): %s", log_entry.rstrip())

    def get_history(self, limit: int = 100) -> list[dict]:
        """Get recent command history.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of command entries as dicts
        """
        if not self.log_path.exists():
            return []

        history = []
        try:
            with open(self.log_path) as f:
                lines = f.readlines()

            for line in reversed(lines[-limit:]):
                line = line.strip()
                if not line:
                    continue

                entry = {"raw": line}
                # Parse the log entry
                try:
                    # Extract timestamp
                    if line.startswith("["):
                        ts_end = line.find("]")
                        if ts_end > 0:
                            entry["timestamp"] = line[1:ts_end]

                    # Extract user
                    if "USER=" in line:
                        user_start = line.find("USER=") + 5
                        user_end = line.find(" ", user_start)
                        if user_end == -1:
                            user_end = len(line)
                        entry["user"] = line[user_start:user_end]

                    # Extract command
                    if "CMD=" in line:
                        cmd_start = line.find("CMD=") + 4
                        entry["command"] = line[cmd_start:]

                    # Extract session
                    if "SESSION=" in line:
                        sess_start = line.find("SESSION=") + 8
                        sess_end = line.find(" ", sess_start)
                        if sess_end == -1:
                            sess_end = len(line)
                        entry["session_id"] = line[sess_start:sess_end]

                except Exception:
                    pass

                history.append(entry)

        except Exception as e:
            logger.warning(f"Failed to read audit log: {e}")

        return list(reversed(history))


# Global audit logger instance
_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """Get or create the global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def log_command(command: str, session_id: str | None = None, **metadata) -> None:
    """Convenience function to log a command."""
    get_audit_logger().log(command, session_id, metadata)


def get_command_history(limit: int = 100) -> list[dict]:
    """Convenience function to get command history."""
    return get_audit_logger().get_history(limit)
