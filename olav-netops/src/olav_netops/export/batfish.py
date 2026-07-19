"""Batfish-compatible snapshot exporter (R74).

Reads the latest ``netops.raw_output_store`` rows and writes each
device's configuration to a filesystem layout Batfish can analyze
directly::

    exports/snapshots/<YYYY-MM-DD>/batfish/
    └── configs/
        ├── R1.cfg
        ├── R2.cfg
        ├── R3.cfg
        ├── R4.cfg
        ├── SW1.cfg
        └── SW2.cfg

Platform → preferred backup command mapping (configurable via
``user_commands.yaml``; the defaults here match the shipped workspace
user_commands.yaml):

    cisco_ios/xe/xr/nxos  → show running-config
    arista_eos            → show running-config
    juniper_junos         → show configuration | display set  ← Batfish preferred
                            (falls back to `show configuration` if the set
                             form wasn't collected)
    nokia_sros            → admin display-config
    huawei_vrp            → display current-configuration
    paloalto_panos        → show config running
    fortinet_fortios      → show full-configuration

Also maintains a ``latest-batfish`` symlink pointing at the most recent
export directory for convenience.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Batfish-domain preference: when multiple backup commands captured
# output for a platform, prefer formats Batfish parses best.  Substring
# test on the command string — **not** a vendor-alias table.  If the
# user adds new backup commands to ``user_commands.yaml``, simply
# including one of these tokens puts it in front.
_BATFISH_PREFERRED_TOKENS = ("display set", "formal")

# ISSUE-BATFISH-EXPORT-NEEDS-COMMANDS-WHITELIST: last-resort backup commands
# per platform when the netops.commands whitelist is absent or has no
# backup_only rows (e.g. main.duckdb wiped + only device data re-imported).
# Mirrors the shipped user_commands.yaml defaults. The DB whitelist is still
# preferred; this only prevents a cryptic "No valid configurations found"
# Batfish failure when the whitelist didn't get synced.
_DEFAULT_BACKUP_COMMANDS: dict[str, tuple[str, ...]] = {
    "cisco_ios": ("show running-config",),
    "cisco_xe": ("show running-config",),
    "cisco_nxos": ("show running-config",),
    "cisco_xr": ("show running-config formal", "show running-config"),
    "arista_eos": ("show running-config",),
    "juniper_junos": ("show configuration | display set", "show configuration"),
}


def _candidate_backup_commands(conn: Any, platform: str) -> tuple[list[str], bool]:
    """Return (candidate commands, used_fallback) for *platform*.

    Prefers the ``netops.commands`` backup_only whitelist; falls back to
    ``_DEFAULT_BACKUP_COMMANDS`` when that query yields nothing (missing
    table or unsynced whitelist), so a stripped DB can't silently starve
    the Batfish export. Never raises on a missing table."""
    rows: list[tuple[str]] = []
    try:
        rows = conn.execute(
            """
            SELECT command FROM netops.commands
            WHERE platform = ?
              AND COALESCE(backup_only, FALSE) = TRUE
              AND COALESCE(blacklisted, FALSE) = FALSE
            """,
            [platform],
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — missing table / catalog error
        logger.warning(
            "batfish export: netops.commands unavailable (%s); using default "
            "backup commands for %s", exc, platform,
        )
    candidates = [r[0] for r in rows]
    if candidates:
        return candidates, False
    fallback = list(_DEFAULT_BACKUP_COMMANDS.get(platform, ()))
    if fallback:
        logger.warning(
            "batfish export: no backup_only command in netops.commands for %s "
            "— falling back to built-in default(s) %s (run `olav skill install "
            "olav-netops` or netops_init to sync the whitelist)",
            platform, fallback,
        )
    return fallback, True


def _pick_config(
    conn: Any,
    device: str,
    platform: str,
    snapshot_id: str | None = None,
) -> tuple[str, str] | None:
    """Return ``(command_used, raw_output)`` for the device's config.

    Candidate backup commands come from ``netops.commands WHERE
    backup_only=TRUE`` — the SSOT seeded by
    :func:`commands_sync.sync_commands` from
    ``.olav/workspace/netops/netops_init/config/user_commands.yaml`` plus
    user overlays.  When that whitelist is missing/unsynced, a built-in
    per-platform default is used so the export still works (see
    :data:`_DEFAULT_BACKUP_COMMANDS`).

    Commands containing :data:`_BATFISH_PREFERRED_TOKENS` (``display
    set`` for Junos set-format, ``formal`` for IOS-XR) are tried
    first because Batfish's parser handles them best.
    """
    candidates, _ = _candidate_backup_commands(conn, platform)
    # Batfish-preferred variants first, other backup commands next.
    candidates.sort(
        key=lambda c: 0 if any(tok in c for tok in _BATFISH_PREFERRED_TOKENS) else 1,
    )

    for cmd in candidates:
        if snapshot_id:
            row = conn.execute(
                "SELECT raw_output FROM netops.raw_output_store "
                "WHERE device_name=? AND command=? AND snapshot_id=?",
                [device, cmd, snapshot_id],
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT raw_output FROM netops.raw_output_store "
                "WHERE device_name=? AND command=? "
                "ORDER BY updated_at DESC LIMIT 1",
                [device, cmd],
            ).fetchone()
        if row and row[0] and row[0].strip():
            return cmd, row[0]
    return None


def _exports_root() -> Path:
    """Resolve ``exports/snapshots/`` under the active OLAV project."""
    try:
        from olav.core.config import get_paths_config
        return Path(get_paths_config().project_root) / "exports" / "snapshots"
    except Exception:
        return Path.cwd() / "exports" / "snapshots"


def export_configs(
    conn: Any,
    snapshot_id: str | None = None,
    snapshot_date: str | None = None,
) -> dict[str, Any]:
    """Write Batfish-compatible config files for every device in the DB.

    Args:
        conn: open DuckDB connection (read-only is fine).
        snapshot_id: specific snapshot to export. ``None`` = latest
            capture per (device, command) in ``raw_output_store``.
        snapshot_date: date subdir under ``exports/snapshots/`` (e.g.
            ``2026-04-23``). ``None`` = today (UTC).

    Returns::

        {
          "output_dir": "exports/snapshots/2026-04-23/batfish/",
          "config_count": 6,
          "devices_written": ["R1", "R2", ...],
          "devices_missing": [],
          "per_device_command": {"R1": "show configuration | display set", ...}
        }
    """
    if snapshot_date is None:
        snapshot_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_base = _exports_root() / snapshot_date / "batfish"
    configs_dir = out_base / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)

    # Device list from netops.devices (authoritative: what Nornir says)
    try:
        devices = conn.execute(
            "SELECT hostname, platform FROM netops.devices "
            "WHERE hostname IS NOT NULL ORDER BY hostname"
        ).fetchall()
    except Exception as exc:
        logger.warning("export_configs: devices query failed: %s", exc)
        return {
            "output_dir": str(out_base), "config_count": 0,
            "devices_written": [], "devices_missing": [],
            "per_device_command": {},
            "error": str(exc),
        }

    written: list[str] = []
    missing: list[str] = []
    per_cmd: dict[str, str] = {}

    for host, platform in devices:
        plat = (platform or "unknown").strip()
        picked = _pick_config(conn, host, plat, snapshot_id)
        if picked is None:
            missing.append(host)
            logger.info(
                "export_configs: %s (%s) — no backup command captured, skipping",
                host, plat,
            )
            continue
        cmd, raw = picked
        per_cmd[host] = cmd
        out_file = configs_dir / f"{host}.cfg"
        out_file.write_text(raw, encoding="utf-8")
        written.append(host)
        logger.info("export_configs: wrote %s via %r", out_file, cmd)

    # Write a manifest so humans + Batfish loaders can trace provenance.
    manifest = {
        "snapshot_date": snapshot_date,
        "snapshot_id": snapshot_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "olav-netops export.batfish",
        "config_count": len(written),
        "devices_written": written,
        "devices_missing": missing,
        "per_device_command": per_cmd,
    }
    import json as _json
    (out_base / "manifest.json").write_text(
        _json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8",
    )

    # Maintain a `latest-batfish` symlink one level up pointing at this
    # snapshot_date's batfish dir. Used by CI / analysis scripts that
    # want a stable path to the most recent export.
    latest = _exports_root() / "latest-batfish"
    try:
        if latest.is_symlink() or latest.exists():
            if latest.is_symlink():
                latest.unlink()
            else:
                # Non-symlink at that path — don't clobber.
                logger.info(
                    "export_configs: %s is not a symlink; not overwriting", latest,
                )
        if not latest.exists():
            latest.symlink_to(out_base.resolve(), target_is_directory=True)
    except Exception as exc:
        logger.debug("export_configs: symlink refresh failed: %s", exc)

    return {
        "output_dir": str(out_base),
        "config_count": len(written),
        "devices_written": written,
        "devices_missing": missing,
        "per_device_command": per_cmd,
    }
