"""AuditEventRecorder — DuckDB-backed structured audit log.

Schema (audit.v1):
  audit_runs       — one row per agent invocation
  audit_events     — one row per LangChain/tool event within a run
  audit_tool_calls — structured tool call records (tool_name, args, result)
  audit_messages   — structured message records (role, content)
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

# ---------------------------------------------------------------------------
# GAP-1: Audit log redaction (ISO 27001 A.10 / NIST SC-28)
# Patterns match common network credential keywords followed by a value token.
# ---------------------------------------------------------------------------
_REDACT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)(\bpassword\s+)\S+"),
    re.compile(r"(?i)(\bcommunity\s+)\S+"),
    re.compile(r"(?i)(\bsecret\s+(?:\d+\s+)?)\S+"),
    re.compile(r"(?i)(\bkey-string\s+)\S+"),
    re.compile(r"(?i)(\bpre-shared-key\s+)\S+"),
]


def redact_sensitive(content: str) -> str:
    """Replace credential values in *content* with [REDACTED]."""
    for pattern in _REDACT_PATTERNS:
        content = pattern.sub(lambda m: m.group(1) + "[REDACTED]", content)
    return content


# ---------------------------------------------------------------------------
# GAP-2: Audit manifest (NIST AU-9 / SOC2 CC7.3)
# Append a sha256 digest line to a manifest file for tamper-evidence.
# ---------------------------------------------------------------------------


def write_audit_manifest(
    db_path: str | Path,
    manifest_path: str | Path | None = None,
) -> Path:
    """Append a ``date sha256hex`` line to *manifest_path* for *db_path*.

    Both paths are resolved relative to the caller.  If *manifest_path* is
    omitted it defaults to ``<db_path>.manifest`` next to the database file.

    Returns the manifest ``Path``.
    """
    db_path = Path(db_path)
    if manifest_path is None:
        manifest_path = db_path.with_suffix(db_path.suffix + ".manifest")
    manifest_path = Path(manifest_path)

    digest = hashlib.sha256(db_path.read_bytes()).hexdigest()
    timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{timestamp}  {digest}\n")
    return manifest_path


def verify_audit_integrity(
    db_path: str | Path,
    manifest_path: str | Path | None = None,
) -> bool:
    """Check the last manifest entry against the current DB hash.

    Returns ``True`` if no manifest exists or the hash matches.
    """
    db_path = Path(db_path)
    if manifest_path is None:
        manifest_path = db_path.with_suffix(db_path.suffix + ".manifest")
    manifest_path = Path(manifest_path)

    if not manifest_path.exists():
        return True

    lines = manifest_path.read_text(encoding="utf-8").strip().splitlines()
    if not lines:
        return True

    last_hash = lines[-1].split()[-1]
    current_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
    return current_hash == last_hash


_DDL = """
CREATE TABLE IF NOT EXISTS audit_runs (
    run_id        VARCHAR PRIMARY KEY,
    start_time    TIMESTAMP,
    end_time      TIMESTAMP,
    status        VARCHAR,
    agent_id      VARCHAR,
    session_id    VARCHAR,
    thread_id     VARCHAR,
    user_id       VARCHAR,
    source_channel VARCHAR
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id     VARCHAR PRIMARY KEY,
    event_type   VARCHAR NOT NULL,
    timestamp    TIMESTAMP NOT NULL,
    sequence_no  INTEGER,
    run_id       VARCHAR,
    session_id   VARCHAR,
    agent_id     VARCHAR,
    payload      VARCHAR,   -- JSON string
    redaction    VARCHAR
);

CREATE TABLE IF NOT EXISTS audit_tool_calls (
    call_id      VARCHAR PRIMARY KEY,
    run_id       VARCHAR,
    timestamp    TIMESTAMP NOT NULL,
    tool_name    VARCHAR NOT NULL,
    input_args   VARCHAR,   -- JSON string
    output       VARCHAR,   -- JSON string or plain text
    status       VARCHAR,   -- started / completed / failed
    error        VARCHAR,
    duration_ms  DOUBLE
);

CREATE TABLE IF NOT EXISTS audit_messages (
    message_id   VARCHAR PRIMARY KEY,
    run_id       VARCHAR,
    timestamp    TIMESTAMP NOT NULL,
    sequence_no  INTEGER,
    role         VARCHAR NOT NULL,   -- user / assistant / system / tool
    content      VARCHAR,
    tool_call_id VARCHAR   -- links to audit_tool_calls.call_id when role=tool
);
"""


class AuditEventRecorder:
    """Writes audit events to a DuckDB file.

    Usage::

        recorder = AuditEventRecorder(db_path="/path/to/audit.duckdb")
        run_id = str(uuid.uuid4())
        recorder.record_run_start(run_id=run_id, agent_id="ops")
        recorder.record(event_type="user_input_received", run_id=run_id, payload={...})
        recorder.record_run_end(run_id=run_id, status="completed")
        recorder.close()

    If *db_path* is omitted, defaults to ``AUDIT_DB_PATH`` from
    ``olav.core.config``.

    When the DuckDB file is locked by another process, the recorder
    gracefully degrades: audit is disabled for this instance (no crash).
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            from olav.core.config import AUDIT_DB_PATH

            db_path = AUDIT_DB_PATH
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None
        try:
            self._conn = duckdb.connect(str(self._db_path))
            self._conn.execute(_DDL)
        except Exception as _exc:
            import logging as _logging

            _logging.getLogger(__name__).warning(
                "audit.duckdb unavailable (lock contention or error) — audit disabled: %s", _exc
            )
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
            self._conn = None
        self._sequence: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_run_start(
        self,
        run_id: str,
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
        thread_id: str | None = None,
        user_id: str | None = None,
        source_channel: str | None = None,
    ) -> None:
        """Insert a row into *audit_runs* marking the start of an invocation."""
        if self._conn is None:
            return
        self._conn.execute(
            """
            INSERT INTO audit_runs
                (run_id, start_time, status, agent_id, session_id,
                 thread_id, user_id, source_channel)
            VALUES (?, ?, 'running', ?, ?, ?, ?, ?)
            """,
            [
                run_id,
                _now(),
                agent_id,
                session_id,
                thread_id,
                user_id,
                source_channel,
            ],
        )

    def record_run_end(self, run_id: str, *, status: str = "completed") -> None:
        """Update the *audit_runs* row with an end timestamp and final status."""
        if self._conn is None:
            return
        self._conn.execute(
            "UPDATE audit_runs SET end_time = ?, status = ? WHERE run_id = ?",
            [_now(), status, run_id],
        )

    def record(
        self,
        event_type: str,
        run_id: str | None = None,
        *,
        session_id: str | None = None,
        agent_id: str | None = None,
        payload: Any = None,
        redaction: str | None = None,
    ) -> str:
        """Insert a row into *audit_events* and return the new event_id."""
        self._sequence += 1
        event_id = str(uuid.uuid4())
        if self._conn is None:
            return event_id
        payload_str = json.dumps(payload) if payload is not None else None
        self._conn.execute(
            """
            INSERT INTO audit_events
                (event_id, event_type, timestamp, sequence_no, run_id,
                 session_id, agent_id, payload, redaction)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                event_id,
                event_type,
                _now(),
                self._sequence,
                run_id,
                session_id,
                agent_id,
                payload_str,
                redaction,
            ],
        )
        return event_id

    def record_tool_call(
        self,
        run_id: str | None = None,
        *,
        tool_name: str,
        input_args: Any = None,
        output: Any = None,
        status: str = "started",
        error: str | None = None,
        duration_ms: float | None = None,
    ) -> str:
        """Insert a row into *audit_tool_calls* and return the new call_id."""
        call_id = str(uuid.uuid4())
        if self._conn is None:
            return call_id
        self._conn.execute(
            """
            INSERT INTO audit_tool_calls
                (call_id, run_id, timestamp, tool_name, input_args,
                 output, status, error, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                call_id,
                run_id,
                _now(),
                tool_name,
                json.dumps(input_args) if input_args is not None else None,
                json.dumps(output) if output is not None else None,
                status,
                error,
                duration_ms,
            ],
        )
        return call_id

    def record_message(
        self,
        run_id: str | None = None,
        *,
        role: str,
        content: str,
        tool_call_id: str | None = None,
    ) -> str:
        """Insert a row into *audit_messages* and return the new message_id."""
        self._sequence += 1
        message_id = str(uuid.uuid4())
        safe_content = redact_sensitive(content)
        if self._conn is None:
            return message_id
        self._conn.execute(
            """
            INSERT INTO audit_messages
                (message_id, run_id, timestamp, sequence_no, role, content, tool_call_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                message_id,
                run_id,
                _now(),
                self._sequence,
                role,
                safe_content,
                tool_call_id,
            ],
        )
        return message_id

    def record_hitl_requested(
        self,
        run_id: str,
        interrupt_id: str,
        action_requests: list[Any],
        *,
        agent_id: str | None = None,
    ) -> str:
        """Emit a *hitl_requested* audit event.

        Args:
            run_id:          Active run identifier.
            interrupt_id:    Unique ID for this interrupt (from LangGraph).
            action_requests: List of action descriptors that require approval.
            agent_id:        Optional agent identifier.

        Returns:
            The new event_id string.
        """
        return self.record(
            event_type="hitl_requested",
            run_id=run_id,
            agent_id=agent_id,
            payload={"interrupt_id": interrupt_id, "action_requests": action_requests},
        )

    def record_hitl_decision(
        self,
        run_id: str,
        interrupt_id: str,
        decision: str,
        *,
        agent_id: str | None = None,
        auto_approve_enabled: bool = False,
    ) -> str:
        """Emit a *hitl_decision* audit event.

        Args:
            run_id:               Active run identifier.
            interrupt_id:         Same ID used in the matching *hitl_requested* event.
            decision:             "approve" or "reject" (plus "auto_approve_all").
            agent_id:             Optional agent identifier.
            auto_approve_enabled: Whether auto-approve mode was toggled on.

        Returns:
            The new event_id string.
        """
        return self.record(
            event_type="hitl_decision",
            run_id=run_id,
            agent_id=agent_id,
            payload={
                "interrupt_id": interrupt_id,
                "decision": decision,
                "auto_approve_enabled": auto_approve_enabled,
            },
        )

    def close(self) -> None:
        """Flush and close the DuckDB connection, writing a tamper-evidence manifest."""
        if self._conn is None:
            return
        try:
            self._conn.close()
        except Exception:
            pass
        try:
            write_audit_manifest(self._db_path)
        except Exception:
            pass


def audit_retention(db_path: str | Path, max_age_days: int = 90) -> int:
    """Delete audit records older than *max_age_days*. Returns total deleted rows."""
    import duckdb

    db_path = Path(db_path)
    threshold = datetime.now(UTC) - timedelta(days=max_age_days)
    total = 0

    with duckdb.connect(str(db_path)) as conn:
        for table, ts_col in [
            ("audit_runs", "start_time"),
            ("audit_events", "timestamp"),
            ("audit_tool_calls", "timestamp"),
            ("audit_messages", "timestamp"),
        ]:
            try:
                before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                conn.execute(f"DELETE FROM {table} WHERE {ts_col} < ?", [threshold])
                after = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                total += before - after
            except Exception:
                pass

    return total


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)
