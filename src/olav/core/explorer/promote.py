"""``promote_finding_to_audit`` — graduate an explorer finding into a
recurring audit profile.

The bridge between one-shot exploration (LLM, expensive, ~20 min) and
daily monitoring (SQL only, cheap, cron).  See dev_docs/83 §13a-b for
the design rationale.

Anti-fabrication invariant: the finding's ``evidence_sql`` is copied
**verbatim** into the audit profile — no LLM rewrite, no semantic
transformation.  The query that proved the finding becomes the query
that monitors for its return.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

_VALID_PROFILE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]{0,63}$")


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_profile_name(name: str) -> None:
    if not _VALID_PROFILE_NAME.fullmatch(name):
        raise ValueError(
            f"profile_name {name!r} must match "
            f"^[A-Za-z0-9_][A-Za-z0-9_-]{{0,63}}$ "
            "(filesystem-safe identifier, no path traversal)"
        )


def _load_finding(db_path: Path, finding_id: str) -> dict[str, Any]:
    with duckdb.connect(str(db_path), read_only=True) as conn:
        row = conn.execute(
            "SELECT finding_id, run_id, recorded_at, phase, category, "
            "       severity, summary, detail, evidence_sql, confidence "
            "FROM netops.exploration_findings WHERE finding_id = ?",
            [finding_id],
        ).fetchone()
    if row is None:
        raise LookupError(
            f"finding {finding_id!r} not found in netops.exploration_findings"
        )
    cols = ("finding_id", "run_id", "recorded_at", "phase", "category",
            "severity", "summary", "detail", "evidence_sql", "confidence")
    return dict(zip(cols, row, strict=False))


def _render_yaml_body(
    *,
    profile_name: str,
    finding: dict[str, Any],
    cron_schedule: str,
    alert_threshold: str,
    severity: str,
    promoted_by: str,
) -> str:
    sql = (finding["evidence_sql"] or "").rstrip()
    summary = finding["summary"]
    detail_block = finding.get("detail") or "(no detail provided)"

    return f"""# {profile_name}
# Auto-generated from explorer finding {finding["finding_id"]}.
# Source run: {finding["run_id"]}
# Promoted: {_now_iso()} by {promoted_by}

cron: "{cron_schedule}"
description: |
  {summary}

  Discovery context:
  {detail_block}

  Originally surfaced by the netops/explorer sub-agent — the SQL
  below is copied verbatim from the finding's evidence_sql.

check_sql: |
{_indent_sql(sql, 2)}

alert_threshold: "{alert_threshold}"
severity: {severity}

# Provenance — for incident review + promotion audit (dev_docs/83 §13b)
provenance:
  source_run_id: {finding["run_id"]}
  source_finding_id: {finding["finding_id"]}
  source_finding_phase: {finding["phase"]}
  source_finding_category: {finding["category"] or "(uncategorised)"}
  source_finding_confidence: {finding["confidence"]}
  promoted_by: {promoted_by}
  promoted_at: {_now_iso()}
"""


def _indent_sql(sql: str, depth: int) -> str:
    pad = " " * depth
    return "\n".join(f"{pad}{line}" if line else "" for line in sql.splitlines())


def promote_finding_to_audit(
    *,
    db_path: str | Path,
    finding_id: str,
    profile_name: str,
    audit_profiles_dir: str | Path,
    cron_schedule: str = "0 6 * * *",
    alert_threshold: str = "row_count > 0",
    severity: str | None = None,
    promoted_by: str = "explorer-graduate",
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Read an exploration finding and emit an audit profile YAML.

    Args:
        db_path:             Path to main.duckdb (has netops.exploration_findings).
        finding_id:          Which finding to promote.
        profile_name:        Filesystem-safe name; becomes ``<name>.md``.
        audit_profiles_dir:  Where to write (typically ``audit/profiles/``).
        cron_schedule:       Cron expression for the recurring check.
        alert_threshold:     SQL boolean condition over the check's result
                             set that triggers an alert (default
                             ``"row_count > 0"``).
        severity:            Override severity; default = the finding's severity.
        promoted_by:         Audit log entry — operator's id or 'cron'.
        force:               True = allow overwrite of existing profile.
        dry_run:             True = return the YAML body, don't write to disk.

    Returns:
        ``{
          "profile_path": "<absolute-path-if-written-else-target-path>",
          "yaml_preview": "<the YAML body>",
          "source_run_id":     "...",
          "source_finding_id": "...",
          "next_step": "Review and git commit." | "Dry run only.",
        }``

    Raises:
        ValueError:      profile_name unsafe / finding is not_applicable
        LookupError:     finding_id not in DB
        FileExistsError: profile already exists and force=False
    """
    _validate_profile_name(profile_name)

    finding = _load_finding(Path(db_path), finding_id)

    if finding["confidence"] == "not_applicable":
        raise ValueError(
            f"finding {finding_id!r} has confidence='not_applicable' — "
            "data-gap notes are not promotable to recurring audit checks. "
            "Fix the data collection or pick a confirmed finding."
        )
    if not (finding.get("evidence_sql") or "").strip():
        raise ValueError(
            f"finding {finding_id!r} has empty evidence_sql — cannot promote"
        )

    profiles_dir = Path(audit_profiles_dir)
    target = profiles_dir / f"{profile_name}.md"

    if target.exists() and not force and not dry_run:
        raise FileExistsError(
            f"audit profile {target} already exists; pass force=True to overwrite"
        )

    yaml_body = _render_yaml_body(
        profile_name=profile_name,
        finding=finding,
        cron_schedule=cron_schedule,
        alert_threshold=alert_threshold,
        severity=severity or finding["severity"],
        promoted_by=promoted_by,
    )

    if not dry_run:
        profiles_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml_body, encoding="utf-8")

    return {
        "profile_path": str(target.resolve()),
        "yaml_preview": yaml_body,
        "source_run_id": finding["run_id"],
        "source_finding_id": finding["finding_id"],
        "next_step": (
            "Dry run only — no file written."
            if dry_run else
            "Review the file and `git add` + `git commit` to activate."
        ),
    }


# ── Provenance surfacing (Fix #2 — used by audit-runner) ──────────────


_PROVENANCE_RE = re.compile(
    r"^provenance:\s*\n((?:  .*\n?)+)",
    re.MULTILINE,
)


def read_audit_profile_provenance(profile_yaml_path: str | Path) -> dict | None:
    """Extract the ``provenance`` block from a promoted audit profile.

    Audit-side flows (e.g. ``render_report``) call this on each profile
    they execute.  When the profile was auto-generated by
    ``promote_finding_to_audit``, the returned dict has keys
    ``source_run_id`` / ``source_finding_id`` / ``promoted_by`` /
    ``promoted_at`` — embed those in the alert / report so the
    on-call sees "originally discovered by netops/explorer on YYYY-MM-DD,
    run explore_xxx, finding finding_yyy".

    For hand-written audit profiles (no provenance block) returns None.

    No YAML library import — the profile is a markdown file with a
    YAML-ish block; we parse the few specific lines we care about.
    """
    path = Path(profile_yaml_path)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    m = _PROVENANCE_RE.search(text)
    if not m:
        return None
    block = m.group(1)
    result: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        result[key.strip()] = val.strip()
    return result or None
