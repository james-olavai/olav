"""@tool ``promote_finding_to_audit`` — bridge explorer findings to audit profiles.

Thin wrapper around ``olav.core.explorer.promote.promote_finding_to_audit``.

Default ``dry_run=True``: the LLM proposes a profile; the operator
reviews the YAML and runs `dry_run=False` (or runs the platform CLI
helper) to actually write the file.  This preserves human-in-the-loop
on the discovery → monitoring graduation gate.

See dev_docs/83 §13a-b for the full lifecycle.
"""
from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool


@tool
def promote_finding_to_audit(
    finding_id: str,
    profile_name: str,
    cron_schedule: str = "0 6 * * *",
    alert_threshold: str = "row_count > 0",
    severity: str | None = None,
    dry_run: bool = True,
) -> dict:
    """Graduate an explorer finding into a recurring audit profile.

    Args:
        finding_id:       From record_finding's return value.
        profile_name:     Filesystem-safe identifier (becomes
                          ``audit/profiles/<profile_name>.md``).
        cron_schedule:    Cron expression for the audit check
                          (default ``"0 6 * * *"`` = 06:00 daily).
        alert_threshold:  SQL boolean condition on the check's
                          result rows that triggers an alert
                          (default ``"row_count > 0"``).
        severity:         Override the audit profile's severity;
                          default = the finding's recorded severity.
        dry_run:          ``True`` (default) — return the YAML
                          preview without writing.  ``False`` —
                          write the file (operator can then
                          ``git add`` + commit).

    Returns:
        ``{
          "profile_path": str,
          "yaml_preview": "<the YAML body>",
          "source_run_id":     "...",
          "source_finding_id": "...",
          "next_step": "...",
        }``

    Refuses to promote when:
      * finding's ``confidence == "not_applicable"``
        (data gaps aren't monitorable conditions)
      * profile_name contains path-traversal characters
      * profile already exists and ``force=False``
    """
    from olav.core.config import MAIN_DB_PATH, get_paths_config
    from olav.core.explorer.promote import promote_finding_to_audit as _promote

    paths = get_paths_config()
    audit_profiles_dir = paths.project_root / ".olav" / "workspace" / "audit" / "profiles"

    return _promote(
        db_path=MAIN_DB_PATH,
        finding_id=finding_id,
        profile_name=profile_name,
        audit_profiles_dir=audit_profiles_dir,
        cron_schedule=cron_schedule,
        alert_threshold=alert_threshold,
        severity=severity,
        promoted_by="netops-explorer",
        force=False,
        dry_run=dry_run,
    )
