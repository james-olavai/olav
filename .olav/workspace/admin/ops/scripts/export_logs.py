#!/usr/bin/env python3
"""export_logs.py — Pack OLAV logs and audit DB rows into a .tar.gz bundle.

Includes:
  - .olav/logs/*.log files filtered by time range
  - audit.duckdb CSV exports (runs, tool_calls, events) for the same range
  - A manifest.json with export metadata

Output: exports/admin_logs/<YYYY-MM-DD>_olav_logs.tar.gz
"""

from __future__ import annotations

import gzip
import json
import os
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


_PROJECT_ROOT = _find_project_root()
_OLAV_DIR = _PROJECT_ROOT / ".olav"


def _parse_hours(window: str) -> int:
    """Convert '24h', '7d', '1h' → integer hours."""
    window = window.strip().lower()
    if window.endswith("d"):
        return int(window[:-1]) * 24
    if window.endswith("h"):
        return int(window[:-1])
    return int(window)  # assume hours if bare number


def _export_audit_tables(db_path: Path, since: datetime, tmp_dir: Path) -> list[str]:
    """Export audit DB tables to CSV in tmp_dir. Returns list of written paths."""
    try:
        import duckdb
    except ImportError:
        return []

    if not db_path.exists():
        return []

    written: list[str] = []
    try:
        con = duckdb.connect(str(db_path), read_only=True)
        tables = {
            "audit_runs": "started_at",
            "audit_tool_calls": "called_at",
            "audit_events": "created_at",
        }
        for table, ts_col in tables.items():
            try:
                out = tmp_dir / f"{table}.csv"
                since_iso = since.strftime("%Y-%m-%d %H:%M:%S")
                con.execute(
                    f"COPY (SELECT * FROM audit.{table} WHERE {ts_col} >= '{since_iso}') "
                    f"TO '{out}' (HEADER, DELIMITER ',')"
                )
                written.append(str(out))
            except Exception:  # noqa: BLE001
                pass
        con.close()
    except Exception:  # noqa: BLE001
        pass
    return written


def export_logs(
    window: str = "24h",
    output_dir: str = "exports/admin_logs",
    include_audit_db: bool = True,
) -> str:
    """Pack OLAV application logs and audit DB records into a .tar.gz bundle.

    Args:
        window: Time window to export — e.g. "24h", "7d", "48h". Default "24h".
        output_dir: Destination directory for the archive (relative to project root).
        include_audit_db: If True, also export audit.duckdb tables as CSV.

    Returns:
        Path to the generated .tar.gz file, plus a summary of what was included.
    """
    hours = _parse_hours(window)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    since_ts = since.timestamp()

    out_dir = _PROJECT_ROOT / output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    date_tag = datetime.now().strftime("%Y-%m-%d_%H%M")
    archive_name = f"{date_tag}_olav_logs_{window}.tar.gz"
    archive_path = out_dir / archive_name

    logs_dir = _OLAV_DIR / "logs"
    db_path = _OLAV_DIR / "databases" / "audit.duckdb"

    included: list[str] = []
    skipped: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # 1. Collect log files modified within the window
        log_files: list[Path] = []
        if logs_dir.exists():
            for f in sorted(logs_dir.glob("*.log")):
                try:
                    if f.stat().st_mtime >= since_ts:
                        log_files.append(f)
                except OSError:
                    pass

        # 2. Export audit DB tables if requested
        db_csvs: list[str] = []
        if include_audit_db:
            db_csvs = _export_audit_tables(db_path, since, tmp_dir)

        # 3. Write manifest
        manifest = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "window": window,
            "since": since.isoformat(),
            "log_files": [f.name for f in log_files],
            "audit_db_csvs": [Path(p).name for p in db_csvs],
            "project_root": str(_PROJECT_ROOT),
        }
        manifest_path = tmp_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))

        # 4. Pack everything into tar.gz
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(manifest_path, arcname="manifest.json")
            for f in log_files:
                tar.add(f, arcname=f"logs/{f.name}")
                included.append(f"logs/{f.name}")
            for csv_path in db_csvs:
                p = Path(csv_path)
                tar.add(p, arcname=f"audit/{p.name}")
                included.append(f"audit/{p.name}")

    size_kb = archive_path.stat().st_size // 1024
    summary_lines = [
        f"Archive: {archive_path.relative_to(_PROJECT_ROOT)}  ({size_kb} KB)",
        f"Window: last {window} (since {since.strftime('%Y-%m-%d %H:%M UTC')})",
        f"Log files: {len(log_files)}",
        f"Audit CSV tables: {len(db_csvs)}",
    ]
    if included:
        summary_lines.append("Contents: " + ", ".join(included[:8])
                             + (f" … +{len(included)-8} more" if len(included) > 8 else ""))
    return "\n".join(summary_lines)


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = export_logs(**_args)
    print(_json.dumps(result, default=str))
