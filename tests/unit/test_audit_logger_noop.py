"""Test that AuditLogger.log() no longer writes to the filesystem."""
from __future__ import annotations

from pathlib import Path


def test_log_does_not_create_file(tmp_path):
    """log() must be a no-op — no file should be written."""
    from olav.core.audit_logger import AuditLogger

    log_file = tmp_path / "audit.log"
    al = AuditLogger(log_path=log_file)
    al.log("SELECT * FROM devices")
    assert not log_file.exists(), "log() must not write to disk"


def test_log_command_does_not_create_file(tmp_path, monkeypatch):
    """log_command() convenience wrapper must also be a no-op."""
    import olav.core.audit_logger as _mod

    # Reset global so we get a fresh instance using our path
    monkeypatch.setattr(_mod, "_audit_logger", None)

    log_file = tmp_path / "noop.log"
    monkeypatch.setattr(_mod, "USER_HISTORY_PATH", log_file)

    from olav.core.audit_logger import log_command

    log_command("test command")
    assert not log_file.exists(), "log_command() must not write to disk"


def test_get_history_returns_list(tmp_path):
    """get_history() must return a list (empty is fine) without crashing."""
    from olav.core.audit_logger import AuditLogger

    al = AuditLogger(log_path=tmp_path / "h.log")
    result = al.get_history()
    assert isinstance(result, list)
