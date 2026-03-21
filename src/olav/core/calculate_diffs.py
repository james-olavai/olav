"""OLAV Config Diff — lean replacement for diff_engine (v0.11+).

Compares two snapshots on disk and persists unified diffs to raw_diffs.

Design:
  - Reads raw .txt from disk only: <snapshots_dir>/<snap_id>/raw/<device>/<cmd>.txt
  - Config commands discovered via ``olav.config_commands`` entry-point group
  - Noise filtering via .olav/workspace/ops/diff/config/diff_strategies.yaml
  - Direct INSERT OR REPLACE INTO raw_diffs — no staging file, no fallback path
  - ≤100 lines of logic, no hidden complexity

Usage:
    from olav.core.calculate_diffs import calculate_diffs
    result = calculate_diffs(
        snapshot_id_1="2026-03-03_1940",
        snapshot_id_2="2026-03-04_0800",
        snapshots_dir="/path/to/exports/backup",
    )
"""

from __future__ import annotations

import difflib
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Interface abbreviation map — used in diff_normalized for indexed search
# ---------------------------------------------------------------------------
_IFACE_PREFIXES = {
    "gigabitethernet": "Gi",
    "fastethernet": "Fa",
    "tengigabitethernet": "Te",
    "hundredgige": "Hu",
    "loopback": "Lo",
    "tunnel": "Tu",
    "vlan": "Vl",
    "serial": "Se",
    "ethernet": "Et",
    "management": "Ma",
    "port-channel": "Po",
}
_IFACE_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _IFACE_PREFIXES) + r")(\d[\d/:.]*)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _config_commands() -> frozenset[str]:
    """Discover type=configuration commands via ``olav.config_commands`` entry points."""
    try:
        from importlib.metadata import entry_points

        eps = entry_points(group="olav.config_commands")
        for ep in eps:
            provider = ep.load()
            names = provider() if callable(provider) else []
            if names:
                return frozenset(names)
    except Exception as exc:
        logger.warning("calculate_diffs: cannot load config commands (%s), using fallback", exc)
    return frozenset(
        [
            "show running-config",
            "show running-config all",
            "display current-configuration",
            "show configuration",
        ]
    )


def _noise_patterns(platform: str | None) -> list[str]:
    """Return lowercase noise patterns for the given platform from diff_strategies.yaml."""
    if not platform:
        return []
    try:
        import yaml

        p = Path(__file__).resolve()
        while p != p.parent:
            if (p / "pyproject.toml").exists():
                break
            p = p.parent
        yaml_path = p / ".olav" / "workspace" / "ops" / "diff" / "config" / "diff_strategies.yaml"
        if not yaml_path.exists():
            return []
        strategies = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        plat_cfg = strategies.get("platforms", {}).get(platform, {})
        return [pat.lower() for pat in plat_cfg.get("metadata_patterns", [])]
    except Exception:
        return []


def _diff(raw_a: str, raw_b: str, platform: str | None) -> tuple[str, str, int, int]:
    """Return (diff_content, diff_normalized, added, removed)."""
    noise = _noise_patterns(platform)

    def clean(text: str) -> list[str]:
        return [line for line in text.splitlines() if not any(p in line.lower() for p in noise)]

    def norm(lines: list[str]) -> list[str]:
        def _r(m: re.Match) -> str:
            return _IFACE_PREFIXES.get(m.group(1).lower(), m.group(1)) + m.group(2)

        return [_IFACE_RE.sub(_r, line) for line in lines]

    ca, cb = clean(raw_a), clean(raw_b)
    diff_content = "\n".join(difflib.unified_diff(ca, cb, lineterm="", n=3))
    diff_normalized = "\n".join(difflib.unified_diff(norm(ca), norm(cb), lineterm="", n=3))

    added = removed = 0
    for line in diff_content.splitlines():
        body = line[1:] if line and line[0] in "+-" else line
        if any(p in body.lower() for p in noise):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return diff_content, diff_normalized, added, removed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def calculate_diffs(
    snapshot_id_1: str,
    snapshot_id_2: str,
    snapshots_dir: Path | str | None = None,
    db_conn=None,
    db_path: str | Path | None = None,
    platform: str | None = None,
    devices: list[str] | None = None,
    commands: list[str] | None = None,
) -> dict:
    """Compute config diffs between two snapshots and persist to raw_diffs.

    Reads raw .txt files from:
        <snapshots_dir>/<snapshot_id>/raw/<device>/<command>.txt

    Args:
        snapshot_id_1: Baseline snapshot ID.
        snapshot_id_2: Target snapshot ID.
        snapshots_dir: Base dir containing per-snapshot raw/ subdirs.
                       Defaults to SNAPSHOTS_DIR from config.
        db_conn:       Open DuckDB connection (tests / in-memory).
        db_path:       File path used if db_conn is None.
        platform:      Platform override for noise filtering.
        devices:       Restrict to these device names. None = all common devices.
        commands:      Override command list. None = type=configuration from YAML.

    Returns:
        {"status": "success"|"no_data", "records_written": int}
    """
    import duckdb

    # Resolve base dir
    if snapshots_dir is None:
        try:
            from olav.core.config import BACKUP_DIR

            snapshots_dir = BACKUP_DIR
        except Exception:
            snapshots_dir = Path("exports/backup")
    snap_base = Path(snapshots_dir)

    raw1 = snap_base / snapshot_id_1 / "raw"
    raw2 = snap_base / snapshot_id_2 / "raw"

    if not (raw1.exists() and raw2.exists()):
        logger.info("calculate_diffs: snapshot dirs absent (%s / %s)", raw1, raw2)
        return {
            "status": "no_data",
            "records_written": 0,
            "message": f"Snapshot raw dirs not found for {snapshot_id_1!r}/{snapshot_id_2!r}",
        }

    # Resolve DB connection
    _owns = False
    if db_conn is None:
        if db_path:
            db_conn = duckdb.connect(str(db_path), read_only=False)
        else:
            from olav.core.config import MAIN_DB_PATH

            db_conn = duckdb.connect(str(MAIN_DB_PATH), read_only=False)
        _owns = True

    cmds = set(commands) if commands else _config_commands()
    devs1 = {d.name for d in raw1.iterdir() if d.is_dir()}
    devs2 = {d.name for d in raw2.iterdir() if d.is_dir()}
    common = devs1 & devs2
    if devices:
        common = common & set(devices)

    records: list[dict] = []
    for device in sorted(common):
        for cmd in sorted(cmds):
            fname = cmd.replace(" ", "_") + ".txt"
            f1, f2 = raw1 / device / fname, raw2 / device / fname
            if not (f1.exists() and f2.exists()):
                continue
            raw_a = f1.read_text(encoding="utf-8", errors="replace")
            raw_b = f2.read_text(encoding="utf-8", errors="replace")
            dc, dn, added, removed = _diff(raw_a, raw_b, platform)
            records.append(
                {
                    "snapshot_id_1": snapshot_id_1,
                    "snapshot_id_2": snapshot_id_2,
                    "device_name": device,
                    "command": cmd,
                    "diff_content": dc,
                    "diff_normalized": dn,
                    "added_count": added,
                    "removed_count": removed,
                }
            )

    if not records:
        logger.info(
            "calculate_diffs: no config files matched for %r/%r", snapshot_id_1, snapshot_id_2
        )
        return {
            "status": "no_data",
            "records_written": 0,
            "message": f"No config .txt files matched for {snapshot_id_1!r}/{snapshot_id_2!r}",
        }

    try:
        db_conn.executemany(
            """INSERT OR REPLACE INTO raw_diffs
               (snapshot_id_1, snapshot_id_2, device_name, command,
                diff_content, diff_normalized, added_count, removed_count, is_pinned)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, FALSE)""",
            [
                (
                    r["snapshot_id_1"],
                    r["snapshot_id_2"],
                    r["device_name"],
                    r["command"],
                    r["diff_content"],
                    r["diff_normalized"],
                    r["added_count"],
                    r["removed_count"],
                )
                for r in records
            ],
        )
        logger.info(
            "calculate_diffs: wrote %d records (%s→%s)", len(records), snapshot_id_1, snapshot_id_2
        )
        return {"status": "success", "records_written": len(records)}
    finally:
        if _owns:
            db_conn.close()
