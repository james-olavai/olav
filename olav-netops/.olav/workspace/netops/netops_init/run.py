#!/usr/bin/env python3
"""
/netops_init — Full network discovery and SSH collection pipeline.

Stages:
  1. Environment check (Nornir config, nornir-netmiko installed)
  2. Device inventory load (hosts.yaml)
  3. SSH collection (discovery commands on all devices in parallel)
  4. Report (summary per device, parse rate, topology hint)

Usage:
  olav --agent netops_ops "/netops_init"             # Full collection
  olav --agent netops_ops "/netops_init --dry-run"   # Env check only, no SSH
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

# ── Bootstrap ──────────────────────────────────────────────────────────────

def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    # Fallback: look for .olav/workspace
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / ".olav" / "workspace").exists():
            return parent
    return Path.cwd()


_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _find_project_root()
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

# ── Discovery command set (ARCH-27 final, Round 77) ─────────────────────
#
# Pre-R77 this file held three hardcoded lists
# (``DISCOVERY_COMMANDS_UNIVERSAL`` / ``_IOS`` / ``_JUNOS``) mapping
# each platform to its SSH discovery command set.  A mid-refactor
# attempt at an "intent filter" replaced them with a different
# hardcoded list — same anti-pattern, different spelling.
#
# Correct design: ``netops.commands`` is the authoritative registry.
# For each device, look up its nornir ``platform`` string, then ask
# the DB what commands are available for that platform.  No code-level
# filtering.
#
# The registry itself is populated at Stage 3 start via
# ``commands_sync.sync_commands()`` from three sources:
#   * ntc-templates wheel (every shipped ``<platform>_<cmd>.textfsm``)
#   * ``.olav/templates/<platform>/*.textfsm`` custom / user-learned
#   * ``.olav/templates/parsers/<platform>/*.py`` PaC parsers
#   * user overlay YAMLs (mark commands backup_only or blacklisted)
#
# If the command set is too wide for a given environment (e.g. 143
# cisco_ios templates is more than a router needs), the user edits the
# **blacklist YAML** — still data-driven, still zero Python code change.
# New vendor support: zero code change (ntc templates + overlays
# propagate automatically).


def _discovery_commands_for(platform: str, conn) -> list[str]:
    """Return the full SSH command list for *platform* from ``netops.commands``.

    Non-blacklisted commands only.  Backup-only commands (``show
    running-config`` etc.) are appended **after** operational commands so
    they run at the end of each device's collection — keeps the config
    snapshot aligned with the state snapshot it was captured against.
    """
    try:
        # Operational commands first.
        op_rows = conn.execute(
            """
            SELECT DISTINCT command FROM netops.commands
            WHERE platform = ?
              AND COALESCE(blacklisted, FALSE) = FALSE
              AND COALESCE(backup_only, FALSE) = FALSE
            ORDER BY command
            """,
            [platform],
        ).fetchall()
        # Backup commands last.
        bak_rows = conn.execute(
            """
            SELECT DISTINCT command FROM netops.commands
            WHERE platform = ?
              AND COALESCE(blacklisted, FALSE) = FALSE
              AND COALESCE(backup_only, FALSE) = TRUE
            ORDER BY command
            """,
            [platform],
        ).fetchall()
    except Exception:
        return ["show version"]   # table missing entirely; collect the minimum

    cmds = [r[0] for r in op_rows] + [r[0] for r in bak_rows]
    if not cmds:
        return ["show version"]
    return cmds

# Platforms that are NOT Cisco IOS-compatible
def _normalise_platform(platform: str) -> str:
    """Canonicalise a nornir/netmiko platform string.

    Thin wrapper over :func:`olav_netops.core.platform_canonical.canonicalize_platform`
    (the SSOT) with one safety net — if the input is empty, default to
    ``cisco_ios`` because that's what nornir emits for unclassified hosts.
    """
    from olav_netops.core.platform_canonical import canonicalize_platform
    return canonicalize_platform(platform) or "cisco_ios"


# ── TextFSM helper ────────────────────────────────────────────────────────

def _textfsm_parse(platform: str, command: str, raw_output: str) -> list[dict] | None:
    """Delegate to :func:`olav_netops.tools.textfsm_parse.parse_output`.

    v0.21.0-rc5 (gitea #14): this function used to carry its own 3-tier
    TextFSM lookup inline (custom → ntc-templates, platform-normaliser,
    command-filename alias map).  That bypassed
    ``olav_netops.tools.textfsm_parse.parse_output`` — the canonical
    entry point that *also* runs ``field_normalizer.normalize_fields``
    on the result and adds a Tier-0 PaC (Python) parser lookup.

    Every row in ``netops.parsed_outputs`` populated by the old inline
    path had raw vendor-shape field values (``ge-0/0/0``, ``Gi1/0/1``,
    ``Estab`` vs ``Established``, FQDN-suffixed device names…), which
    downstream SQL views had to CASE around.  Delegating here finishes
    R72 ISSUE-INGEST-NORMALIZATION.

    Command-filename aliases (e.g. ``show vlan brief`` → ``show_vlan``)
    moved to ``textfsm_parse._NTC_FILENAME_ALIASES``.
    """
    from olav_netops.tools.textfsm_parse import parse_output
    return parse_output(platform, command, raw_output)


# ── Stage helpers ──────────────────────────────────────────────────────────

def _check_environment() -> tuple[bool, list[str]]:
    """Stage 1: verify nornir config and packages."""
    issues = []

    # Check nornir-netmiko
    try:
        import nornir  # noqa: F401
        import nornir_netmiko  # noqa: F401
    except ImportError as e:
        issues.append(f"Missing dependency: {e}. Run: pip install nornir nornir-netmiko")

    # Check nornir config
    try:
        from olav_netops.core.config_paths import resolve_nornir_config_path as _resolve_nornir_config_path
        cfg = _resolve_nornir_config_path()
        hosts = cfg.parent / "hosts.yaml"
        if not hosts.exists():
            issues.append(
                f"hosts.yaml not found at {hosts}. "
                f"Copy from: .olav/workspace/netops/collect/config/nornir/hosts.yaml.example"
            )
        else:
            # Count devices
            import yaml
            with open(hosts) as f:
                data = yaml.safe_load(f) or {}
            device_count = len(data)
            if device_count == 0:
                issues.append(f"hosts.yaml at {hosts} contains no devices")
            else:
                print(f"  ✓ Nornir config: {cfg}")
                print(f"  ✓ Devices found: {device_count} ({', '.join(list(data.keys())[:6])}{'...' if device_count > 6 else ''})")

            # Validate full Nornir inventory (catches group reference mismatches)
            try:
                from nornir import InitNornir
                _nr = InitNornir(config_file=str(cfg), logging={"enabled": False})
                try:
                    print(f"  ✓ Nornir inventory validated")
                finally:
                    _nr.close_connections()
            except KeyError as ke:
                issues.append(
                    f"hosts.yaml references undefined group: {ke}. "
                    f"Check groups.yaml for available group names."
                )
            except Exception as inv_err:
                issues.append(f"Nornir inventory validation failed: {inv_err}")
    except Exception as e:
        issues.append(f"Nornir config error: {e}")

    return len(issues) == 0, issues


def _load_devices() -> list[str]:
    """Stage 2: load device names from nornir inventory."""
    from olav_netops.core.config_paths import resolve_nornir_config_path as _resolve_nornir_config_path
    import yaml

    cfg = _resolve_nornir_config_path()
    hosts = cfg.parent / "hosts.yaml"
    with open(hosts) as f:
        data = yaml.safe_load(f) or {}
    return list(data.keys())


def _load_host_environments() -> dict[str, str]:
    """{hostname → environment} loader — kept for back-compat with callers
    that only need the environment field.  Prefer
    :func:`_load_host_metadata` for new code."""
    return {
        h: m.get("environment", "")
        for h, m in _load_host_metadata().items()
        if m.get("environment")
    }


# R83: Device ETL helpers extracted to ``olav_netops.core.device_etl`` so
# both ``/netops_init`` (this script) and ``take_snapshot`` can refresh
# ``netops.devices`` from the same code.  Kept aliased here for tests
# that import ``_load_host_metadata`` / ``_populate_devices`` from the
# old location (``test_populate_devices.py``).
from olav_netops.core.device_etl import (
    load_host_metadata as _load_host_metadata,
    populate_devices as _populate_devices,
)


def _run_collection(
    devices: list[str],
    commands: list[str] | None,
    checkpoint: "Checkpoint | None" = None,
) -> dict:
    """Stage 3: SSH collection via Nornir.

    NETOPS-04: when ``checkpoint`` is supplied, already-completed
    (device, command) pairs are skipped and the resumed snapshot_id is
    reused. Incremental checkpoint writes happen after every successful
    ``_collect_cmd``.
    """
    # Import inline to avoid langchain decorator at import time.
    # ``resolve_nornir_config_path`` lives in olav_netops (domain layer);
    # ``MAIN_DB_PATH`` / ``SNAPSHOTS_DIR`` / ``get_paths_config`` live in
    # ``olav.core.config`` (platform layer) — keeping the split honours the
    # ADR-0002 boundary.  A prior refactor merged the import into a single
    # line against ``olav_netops.core.config_paths`` by mistake; that module
    # never exported the latter three, so every full collection raised
    # ``ImportError``.  See DEMO_RUNSHEET Chapter 2 Step 3.
    from nornir import InitNornir
    from nornir_netmiko.tasks import netmiko_send_command
    from olav_netops.core.config_paths import resolve_nornir_config_path as _resolve_nornir_config_path
    from olav.core.config import MAIN_DB_PATH, SNAPSHOTS_DIR, get_paths_config
    from olav.core.utils import utc_now
    try:
        from .checkpoint import Checkpoint, checkpoint_path, save as save_checkpoint
    except ImportError:
        # Loaded via importlib.spec_from_file_location — no parent package.
        # Fall back to sys.path-based absolute import so the entrypoint in
        # olav-netops/scripts/netops_init.py (which execs this file directly)
        # still resolves the sibling module.
        _here = str(Path(__file__).resolve().parent)
        if _here not in sys.path:
            sys.path.insert(0, _here)
        from checkpoint import Checkpoint, checkpoint_path, save as save_checkpoint  # type: ignore
    import duckdb
    import uuid

    project_root = Path(get_paths_config().project_root)

    if checkpoint is not None:
        # Resume — reuse the IDs + accumulated state from disk.
        snapshot_id = checkpoint.snapshot_id
        snapshot_date = checkpoint.snapshot_date
        results_summary = list(checkpoint.results_summary)
        all_rows = list(checkpoint.all_rows)
        completed_set = checkpoint.completed_set()
    else:
        # NETOPS-02: snapshot_id must match first_seen/last_seen (UTC) or cross-
        # snapshot joins drift by the local offset (8h in CN).
        now = utc_now()
        snapshot_id = f"snap_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        snapshot_date = now.strftime("%Y-%m-%d")
        results_summary = []
        all_rows = []
        completed_set = set()

    nornir_cfg = str(_resolve_nornir_config_path())
    nr = InitNornir(config_file=nornir_cfg, logging={"enabled": False})

    # ── Build per-platform command sets ───────────────────────────────────
    # Group devices by normalised platform
    platform_groups: dict[str, list[str]] = {}
    for h in devices:
        host_obj = nr.inventory.hosts.get(h)
        plat = _normalise_platform(host_obj.platform if host_obj else "cisco_ios")
        platform_groups.setdefault(plat, []).append(h)

    # If caller supplied explicit commands, use them for all devices
    # Otherwise, derive per-platform command lists from netops.commands
    # (populated by sync_commands from ntc-templates + custom + PaC).
    use_explicit = commands is not None

    # ARCH-27 (Round 77): populate netops.commands if empty, then query
    # it for discovery commands per platform.  Opens a single read-write
    # connection; sync_commands is idempotent and cheap (a few hundred ms).
    platform_to_cmds: dict[str, list[str]] = {}
    if not use_explicit:
        try:
            from olav_netops.core.commands_sync import sync_commands
            with duckdb.connect(str(MAIN_DB_PATH)) as _cmds_conn:
                sync_commands(_cmds_conn)
                for plat in platform_groups:
                    platform_to_cmds[plat] = _discovery_commands_for(plat, _cmds_conn)
        except Exception as exc:  # noqa: BLE001
            # If sync_commands or the lookup fails, fall back to a
            # minimal 2-command set per platform so Device ETL still
            # has ``show version`` to extract vendor/model.
            print(f"  ⚠ sync_commands / discovery lookup failed ({exc}); "
                  "falling back to minimal [show version, show interfaces]")
            for plat in platform_groups:
                platform_to_cmds[plat] = ["show version", "show interfaces"]

        all_cmds_set: set[str] = set()
        for cmds in platform_to_cmds.values():
            all_cmds_set.update(cmds)
        commands_display = sorted(all_cmds_set)
    else:
        commands_display = commands

    # ── NETOPS-04: checkpoint bookkeeping ────────────────────────────────
    active_checkpoint = checkpoint or Checkpoint(
        snapshot_id=snapshot_id,
        snapshot_date=snapshot_date,
        stage="collecting",
        platform_groups=platform_groups,
        devices=list(devices),
        results_summary=results_summary,
        all_rows=all_rows,
    )
    cp_file = checkpoint_path(project_root, snapshot_id)

    def _persist_cp() -> None:
        """Incremental save — swallow disk errors so collection keeps going."""
        try:
            save_checkpoint(active_checkpoint, cp_file)
        except Exception as cp_err:  # noqa: BLE001
            # Don't let a disk hiccup abort a long SSH run.
            print(f"  ⚠ checkpoint save failed (non-blocking): {cp_err}")

    total_ok = 0
    total_fail = 0

    # Collect per platform
    if use_explicit:
        # Explicit commands: send to all devices
        # NETOPS-04: drop devices whose (dev, cmd) pair is already completed
        # before building the Nornir filter so SSH never touches them.
        for cmd in commands:
            pending = [d for d in devices if (d, cmd) not in completed_set]
            if not pending:
                print(f"  ⏩ {cmd} — all devices already done, skipping")
                continue
            target = nr.filter(filter_func=lambda h, _p=pending: h.name in _p)
            print(f"  → Collecting: {cmd} ... ", end="", flush=True)
            _collect_cmd(nr, target, cmd, pending, snapshot_id, snapshot_date,
                         SNAPSHOTS_DIR, all_rows, results_summary)
            ok = sum(1 for r in results_summary if r["command"] == cmd and r["status"] == "success")
            fail = sum(1 for r in results_summary if r["command"] == cmd and r["status"] == "failed")
            total_ok += ok
            total_fail += fail
            # Record successful pairs into the checkpoint and persist.
            for r in results_summary:
                if r["command"] == cmd and r["status"] == "success":
                    active_checkpoint.mark_done(r["device"], cmd)
            _persist_cp()
            print(f"✓ {ok} devices, {fail} failures")
    else:
        # Platform-aware: each platform gets its own command list
        # (pre-computed above from netops.commands via _discovery_commands_for).
        for plat, plat_devices in platform_groups.items():
            plat_cmds = platform_to_cmds.get(plat, ["show version", "show interfaces"])
            print(f"  [{plat}] {len(plat_devices)} device(s): {', '.join(plat_devices)}")
            for cmd in plat_cmds:
                pending = [d for d in plat_devices if (d, cmd) not in completed_set]
                if not pending:
                    print(f"    ⏩ {cmd} — all devices already done, skipping")
                    continue
                plat_target = nr.filter(filter_func=lambda h, _p=pending: h.name in _p)
                print(f"    → {cmd} ... ", end="", flush=True)
                _collect_cmd(nr, plat_target, cmd, pending, snapshot_id, snapshot_date,
                             SNAPSHOTS_DIR, all_rows, results_summary)
                ok = sum(1 for r in results_summary if r["command"] == cmd and r["device"] in plat_devices and r["status"] == "success")
                fail = sum(1 for r in results_summary if r["command"] == cmd and r["device"] in plat_devices and r["status"] == "failed")
                total_ok += ok
                total_fail += fail
                for r in results_summary:
                    if r["command"] == cmd and r["device"] in plat_devices and r["status"] == "success":
                        active_checkpoint.mark_done(r["device"], cmd)
                _persist_cp()
                print(f"✓ {ok}, {fail} fail")

    active_checkpoint.stage = "collection_complete"
    _persist_cp()

    # ── Persist via IngestManager pipeline ─────────────────────────────────
    if all_rows:
        from olav.core.ingest_manager import IngestManager
        from olav_netops.core.topology_engine import extract_lldp_topology
        from olav.core.config import SNAPSHOTS_STAGING_JSON

        # Register olav-netops tables and ensure ALL schemas exist in DB
        try:
            from olav_netops.core.tables import _register_all, drop_legacy_tables
            from olav.platform.ingest_base import TableRegistry
            _register_all()
            with duckdb.connect(str(MAIN_DB_PATH)) as _setup_conn:
                TableRegistry.ensure_all_schemas(_setup_conn)
                # ISSUE-DEAD-SCHEMA-R83-LEFTOVER: drop pre-R83 ETL tables that
                # no longer have any code writing to them. Their continued
                # existence misleads database_introspection (the audit profile
                # author selected the empty bgp_neighbors table over the live
                # v_bgp_neighbors_auto view in demo7 Ch6).
                _dropped = drop_legacy_tables(_setup_conn)
                if _dropped:
                    logger.info("dropped legacy dead tables: %s", _dropped)
        except ImportError:
            # Fallback DDL for skill-only installs (no pip install olav-netops)
            with duckdb.connect(str(MAIN_DB_PATH)) as _setup_conn:
                _setup_conn.execute("CREATE SCHEMA IF NOT EXISTS netops")
                _setup_conn.execute("""
                    CREATE TABLE IF NOT EXISTS netops.raw_output_store (
                        device_name  VARCHAR NOT NULL,
                        command      VARCHAR NOT NULL,
                        raw_output   TEXT,
                        snapshot_id  VARCHAR,
                        updated_at   TIMESTAMPTZ,
                        UNIQUE (device_name, command)
                    )
                """)
                _setup_conn.execute("""
                    CREATE TABLE IF NOT EXISTS netops.parsed_outputs (
                        device_name     VARCHAR NOT NULL,
                        command         VARCHAR NOT NULL,
                        parsed_data     JSON,
                        snapshot_id     VARCHAR NOT NULL,
                        raw_output      TEXT,
                        raw_output_hash VARCHAR,
                        ingested_at     TIMESTAMP,
                        UNIQUE (device_name, command, snapshot_id)
                    )
                """)
                _setup_conn.execute("""
                    CREATE TABLE IF NOT EXISTS netops.topology_links (
                        link_id              VARCHAR PRIMARY KEY,
                        source_device        VARCHAR NOT NULL,
                        source_interface     VARCHAR NOT NULL,
                        destination_device   VARCHAR NOT NULL,
                        destination_interface VARCHAR NOT NULL,
                        discovery_protocol   VARCHAR,
                        link_type            VARCHAR,
                        link_status          VARCHAR,
                        link_speed           VARCHAR,
                        first_seen           TIMESTAMP NOT NULL,
                        last_seen            TIMESTAMP NOT NULL,
                        last_verified        TIMESTAMP,
                        status_changes       INTEGER,
                        snapshot_id          VARCHAR NOT NULL,
                        platform             VARCHAR
                    )
                """)

        # ── Stage 3.5: Parse-coverage classifier ───────────────────────
        #
        # Pre-v0.21.0 this stage called ``auto_learn_failed_parses`` which
        # looped serially through every parse failure, burned 3-5 LLM
        # retries per (platform, command), and silently blocked the
        # pipeline for 10+ minutes on fresh installs (ISSUE-AUTO-LEARN-PERF).
        # Round 72 (ISSUE-LEARNER-BATCH-CUT) decided batch learning does
        # not belong in the pipeline — it's a ``/learn_cmd`` user action
        # backed by the ``command_learner`` skill, not autonomous plumbing.
        #
        # What this block does now:
        #   1. Classify every row into one of three buckets:
        #        - parsed       → TextFSM / ntc-templates produced data
        #        - raw_only     → Got CLI output, but no parser matched;
        #                         agent can still answer via raw fallback
        #                         (viewer reads ``raw_output_store`` when
        #                          ``parsed_outputs`` is empty)
        #        - unsupported  → ``should_learn()`` says this output is
        #                         an error / empty / backup-cmd dump;
        #                         a parser won't help, don't bother user
        #   2. Persist the ``raw_only`` set to ``.olav/config/unsupported.json``
        #      so the WebUI / CLI can surface an actionable list.
        #   3. Print a one-screen summary telling the operator exactly
        #      which ``(platform, command)`` pairs they'd gain structured
        #      queries for by running ``/learn_cmd``.  No LLM calls, no
        #      progress bar, ~10 ms on six devices.
        from olav_netops.core.parse_helpers import should_learn

        parsed_count = 0
        raw_only: dict[tuple[str, str], list[str]] = {}   # (platform, cmd) → [devices]
        unsupported: dict[tuple[str, str], list[str]] = {}

        for row in all_rows:
            if row.get("parsed_data") is not None:
                parsed_count += 1
                continue
            raw = row.get("raw_output") or ""
            if not raw:
                continue
            host_obj = nr.inventory.hosts.get(row["device_name"])
            plat = _normalise_platform(host_obj.platform if host_obj else "cisco_ios")
            key = (plat, row["command"])
            bucket = raw_only if should_learn(row["command"], raw) else unsupported
            bucket.setdefault(key, []).append(row["device_name"])

        total_rows = len(all_rows)
        print(f"\n📊 Stage 3.5: Parse coverage")
        print(f"  parsed    : {parsed_count} / {total_rows} rows "
              f"({parsed_count * 100 // max(total_rows, 1)}%)")

        if raw_only:
            # Write the actionable list so UI/CLI can resurface it later.
            try:
                from olav.core.config import get_paths_config
                _config_dir = Path(get_paths_config().agent_dir) / "config"
                _config_dir.mkdir(parents=True, exist_ok=True)
                _out = _config_dir / "unsupported.json"
                _out.write_text(json.dumps(
                    [
                        {
                            "platform": plat,
                            "command": cmd,
                            "devices": sorted(set(devs)),
                        }
                        for (plat, cmd), devs in sorted(raw_only.items())
                    ],
                    indent=2,
                ))
                print(f"  raw-only  : {len(raw_only)} unique (platform, command) pairs "
                      f"→ {_out.relative_to(_config_dir.parent.parent)}")
            except Exception as exc:   # pragma: no cover
                print(f"  raw-only  : {len(raw_only)} pairs (warn: could not persist list: {exc})")
            print(f"")
            print(f"    ⚡ To enable structured queries for these, run:")
            for (plat, cmd), _devs in sorted(raw_only.items())[:6]:
                print(f"        olav --agent netops_ops '/learn_cmd {plat} \"{cmd}\"'")
            if len(raw_only) > 6:
                print(f"        …and {len(raw_only) - 6} more (see .olav/config/unsupported.json)")

        if unsupported:
            print(f"  unsupported: {len(unsupported)} pair(s) — error messages / empty output, "
                  "no parser would help")

        staging_file = SNAPSHOTS_STAGING_JSON / f"{snapshot_id}.staging.json"
        SNAPSHOTS_STAGING_JSON.mkdir(parents=True, exist_ok=True)
        staging_file.write_text(json.dumps(all_rows))
        print(f"  → Staging JSON written: {staging_file.name}")

        # 2026-05-15: track ingest status so Stage 4 can fail loud
        # instead of printing ✅ over a Binder Error (see
        # ISSUE-NETOPS-INIT-MISLEADING-SUCCESS).
        ingest_status = "unknown"
        ingest_error = None
        ingest_records = 0
        try:
            ingest = IngestManager(db_path=MAIN_DB_PATH, staging_dir=SNAPSHOTS_STAGING_JSON)
            load_result = ingest.bulk_load()
            print(f"  ✓ IngestManager loaded: {load_result}")
            ingest_status = load_result.get("status", "unknown")
            ingest_error = load_result.get("message")
            ingest_records = int(load_result.get("records_inserted", 0))
        except Exception as e:
            print(f"  ✗ IngestManager ERROR: {e}")
            ingest_status = "error"
            ingest_error = str(e)

        # ── Device ETL FIRST so netops.devices is populated ────────────
        # This MUST run before Topology ETL: ``topology_engine._insert_link``
        # resolves neighbour hostnames (e.g. ``R4.local``) against
        # ``netops.devices`` via :mod:`olav_netops.core.hostname_registry`
        # so bidirectional CDP/LLDP advertisements collapse to one canonical
        # name per device.  Pre-rc6 the order was reversed — devices was
        # empty when topology writes happened, so every ``.local``-suffixed
        # neighbour stayed non-canonical and SQL dedup broke (gitea #16).
        try:
            dev_count = _populate_devices(MAIN_DB_PATH, snapshot_id)
            print(f"  ✓ Device ETL: {dev_count} device(s) registered")
        except Exception as e:
            print(f"  ✗ Device ETL ERROR: {e}")

        # ── Topology ETL (uses canonical hostnames from Device ETL above) ──
        try:
            with duckdb.connect(str(MAIN_DB_PATH)) as conn:
                topo_rows = extract_lldp_topology(conn)
                print(f"  ✓ Topology ETL: {topo_rows} link(s) extracted")
        except Exception as e:
            print(f"  ✗ Topology ETL ERROR: {e}")

        # ── R83.2 (P1): single zero-ETL entry point ───────────────────
        #
        # No more ``view_recipes`` seeding — the L1 recipe-driven views
        # (``v_bgp_neighbors_auto`` / ``v_ospf_neighbors_auto``) were
        # the same hardcoded ``(concept, command, vendor) → fields``
        # mapping R78 deleted from Python, just re-spelled in YAML.
        # State canonicalisation (``Estab`` → ``Established``) moved to
        # ingest-time ``field_normalizer.normalize_fields``;
        # ``parsed_outputs.parsed_data`` already holds RFC-canonical
        # state by the time any view reads it.  Per-command views
        # built via DuckDB ``json_structure`` + ``unnest(from_json(...))``
        # — no recipes, no field maps.  ``v_l2_links_auto`` is a thin
        # column-rename projection of ``netops.topology_links``.
        try:
            from olav_netops.core.view_builder import finalise_ingest
            with duckdb.connect(str(MAIN_DB_PATH)) as _view_conn:
                view_stats = finalise_ingest(_view_conn)
            l2_stats = view_stats.get("l2") or {}
            per_cmd_stats = view_stats.get("per_command") or {}
            if l2_stats:
                _l2 = ", ".join(f"{n}({r})" for n, r in l2_stats.items())
                print(f"  ✓ topology view: {_l2}")
            if per_cmd_stats:
                print(
                    f"  ✓ per-command auto views: {len(per_cmd_stats)} "
                    f"(e.g. v_show_ip_interface_brief_auto, …)"
                )
        except Exception as _view_err:  # noqa: BLE001
            # Build is advisory — raw parsed_outputs queries still work.
            print(f"  ⚠ view build skipped (non-blocking): {_view_err}")

        # ── Stage 3.8: Batfish snapshot export (R74, gitea #15) ────────
        # The exporter reads ``netops.raw_output_store`` and writes a
        # Batfish-compatible layout at
        # ``exports/snapshots/<YYYY-MM-DD>/batfish/{configs,manifest.json}``.
        # ``netops_init/run.py`` used to call this stage ad-hoc (R74 note
        # in dev_docs/00) but the wiring never actually landed; this
        # block finishes it.  Non-blocking: a failure here must not
        # prevent a successful IngestManager / Topology / Device ETL
        # from being reported as "complete".
        try:
            from olav_netops.export.batfish import export_configs
            with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as _bf_conn:
                _bf = export_configs(_bf_conn, snapshot_id=snapshot_id)
            if _bf["config_count"]:
                _out_dir = Path(_bf["output_dir"])
                try:
                    _rel = _out_dir.relative_to(Path.cwd())
                except ValueError:
                    _rel = _out_dir
                print(
                    f"  ✓ Batfish export: {_bf['config_count']} config(s) → {_rel}/"
                )
                # Stable ``latest-batfish`` symlink so downstream Batfish
                # loaders don't need to know today's date.
                try:
                    _latest = _out_dir.parent.parent / "latest-batfish"
                    if _latest.is_symlink() or _latest.exists():
                        _latest.unlink()
                    _latest.symlink_to(_out_dir.resolve())
                except Exception as _sym_err:   # noqa: BLE001
                    print(f"    ⚠ latest-batfish symlink failed: {_sym_err}")
                if _bf["devices_missing"]:
                    print(
                        f"    ⚠ no config captured for: {', '.join(_bf['devices_missing'])}"
                    )
            else:
                print(
                    f"  ℹ Batfish export: no config command output found "
                    f"(expected show running-config / show configuration in raw_output_store)"
                )
        except Exception as _bf_err:   # noqa: BLE001
            print(f"  ⚠ Batfish export skipped (non-blocking): {_bf_err}")

    # NETOPS-01: release Netmiko SSH sessions held by Nornir's connection pool
    # to prevent fd/vty leaks in long-running parent processes.
    try:
        nr.close_connections()
    except Exception as _close_err:  # noqa: BLE001
        print(f"  ⚠ Nornir close_connections failed (non-blocking): {_close_err}")

    return {
        "snapshot_id": snapshot_id,
        "snapshot_date": snapshot_date,
        "devices": len(devices),
        "commands": len(commands_display),
        "successful": total_ok,
        "failed": total_fail,
        "results": results_summary,
        # 2026-05-15 — let Stage 4 see whether the ingest pipeline
        # actually wrote rows.  Non-success + 0 records means devices /
        # topology / views never populated and downstream queries
        # return zero.
        "ingest_status": ingest_status,
        "ingest_error": ingest_error,
        "ingest_records": ingest_records,
    }


def _collect_cmd(nr, target, cmd, devices, snapshot_id, snapshot_date,
                 snapshots_dir, all_rows, results_summary):
    """Run a single command on target hosts, store results.

    NETOPS-06: Nornir already isolates per-host failures in `multi.failed` —
    no outer ``try/except Exception`` wrapping target.run(), which would
    otherwise mark every device as failed when a subset succeeded.
    """
    from nornir_netmiko.tasks import netmiko_send_command
    from olav_netops.core.parse_helpers import is_cli_error
    result = target.run(task=netmiko_send_command, command_string=cmd)
    for host, multi in result.items():
        if multi.failed:
            results_summary.append({"device": host, "command": cmd, "status": "failed",
                                    "error": str(multi.exception)[:100]})
            continue
        raw_output = multi[0].result or ""
        raw_dir = snapshots_dir / snapshot_date / "raw" / host
        raw_dir.mkdir(parents=True, exist_ok=True)
        # NETOPS-05: whitelist characters so CLI-supplied `--commands ".."` or
        # `cmd\x00` can't escape raw_dir via path traversal.
        safe_cmd = re.sub(r"[^a-zA-Z0-9_-]", "_", cmd)[:60]
        (raw_dir / f"{safe_cmd}.txt").write_text(raw_output)

        # Reject device CLI error responses ("% Invalid input detected
        # at '^' marker", "unknown command.", empty / near-empty
        # output) at the ingest boundary — those should never reach
        # raw_output_store / parsed_outputs.  The on-disk dump above
        # is kept for forensic debugging.
        if is_cli_error(raw_output):
            results_summary.append({"device": host, "command": cmd,
                                    "status": "rejected",
                                    "reason": "device CLI error / unsupported"})
            continue

        platform = _normalise_platform(
            nr.inventory.hosts[host].platform or "cisco_ios"
        )

        parsed_data = None
        parsed_rows = 0
        parsed = _textfsm_parse(platform, cmd, raw_output)
        if parsed:
            parsed_data = json.dumps(parsed)
            parsed_rows = len(parsed)

        all_rows.append({
            "snapshot_id": snapshot_id,
            "device_name": host,
            "command": cmd,
            "raw_output": raw_output,
            "parsed_data": parsed_data,
            "platform": platform,
        })
        results_summary.append({"device": host, "command": cmd,
                                "status": "success", "parsed_rows": parsed_rows})


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(prog="netops_init",
                                     description="Full network discovery pipeline")
    parser.add_argument("--dry-run", action="store_true",
                        help="Check environment only — no SSH connections")
    parser.add_argument("--commands", nargs="+",
                        help="Override discovery commands (default: platform-aware)")
    parser.add_argument(
        "--resume", metavar="SNAPSHOT_ID", default=None,
        help="Resume a previous run by snapshot_id; skips already-collected "
             "(device, command) pairs using the on-disk checkpoint.",
    )
    args = parser.parse_args()

    # NETOPS-04: optional resume — load checkpoint before env check so a
    # failed-mid-collection run can retry without re-running Stage 1/2.
    resume_checkpoint = None
    if args.resume:
        from olav.core.config import get_paths_config
        try:
            from .checkpoint import checkpoint_path as _cp_path, load as _cp_load
        except ImportError:
            _here = str(Path(__file__).resolve().parent)
            if _here not in sys.path:
                sys.path.insert(0, _here)
            from checkpoint import checkpoint_path as _cp_path, load as _cp_load  # type: ignore

        cp_file = _cp_path(Path(get_paths_config().project_root), args.resume)
        resume_checkpoint = _cp_load(cp_file)
        if resume_checkpoint is None:
            print(f"\n❌ --resume specified but checkpoint {cp_file} missing/invalid")
            return 1
        print(f"\n⏩ Resuming snapshot {resume_checkpoint.snapshot_id} "
              f"(stage={resume_checkpoint.stage}, "
              f"{len(resume_checkpoint.completed)} pairs already done)")

    print("\n🔍 Stage 1: Environment Check")
    t0 = time.time()
    ok, issues = _check_environment()
    if not ok:
        for issue in issues:
            print(f"  ✗ {issue}")
        print("\n❌ Environment check failed — fix issues above before running /netops_init")
        return 1
    print(f"  ✓ Environment OK ({time.time() - t0:.1f}s)")

    if args.dry_run:
        devices = _load_devices()
        print(f"\n✅ Dry-run complete:")
        print(f"  Devices  : {len(devices)} ({', '.join(devices)})")
        print(f"  Mode     : platform-aware command selection")
        print(f"  Nornir   : config loaded, SSH NOT executed (dry-run)")
        return 0

    print("\n📋 Stage 2: Loading Device Inventory")
    devices = _load_devices()
    print(f"  ✓ {len(devices)} devices: {', '.join(devices)}")

    print(f"\n🔌 Stage 3: SSH Collection (platform-aware)")
    t1 = time.time()
    explicit_cmds = args.commands if args.commands else None
    result = _run_collection(devices, explicit_cmds, checkpoint=resume_checkpoint)
    elapsed = time.time() - t1

    print(f"\n📊 Stage 4: Summary")
    print(f"  Snapshot ID    : {result['snapshot_id']}")
    print(f"  Devices        : {result['devices']}")
    print(f"  Commands       : {result['commands']}")
    print(f"  SSH collected  : {result['successful']} ok, {result['failed']} failed")
    print(f"  DB ingest      : {result.get('ingest_status', 'unknown')} "
          f"({result.get('ingest_records', 0)} records)")
    print(f"  Elapsed        : {elapsed:.1f}s")

    if result["failed"] > 0:
        print(f"\n⚠  Some collections failed — check credentials in hosts.yaml / defaults.yaml")
        for r in result["results"]:
            if r["status"] == "failed":
                print(f"  {r['device']} / {r['command']}: {r.get('error', 'unknown')[:80]}")

    # 2026-05-15: distinguish "SSH collected some rows but DB ingest
    # failed" from "everything OK".  The former used to print ✅ —
    # operator would query and get 0 rows back with no clue why.
    ingest_status = result.get("ingest_status", "unknown")
    ingest_records = result.get("ingest_records", 0)
    if ingest_status == "error" or (ingest_status != "no_files" and ingest_records == 0
                                     and result["successful"] > 0):
        print(f"\n❌ Network initialization FAILED at the ingest stage")
        if result.get("ingest_error"):
            print(f"   error: {result['ingest_error']}")
        print(f"   {result['successful']} rows were collected over SSH but only "
              f"{ingest_records} reached the DB.  Downstream queries will return 0.")
        return 2

    if result["failed"] > 0:
        return 0  # partial collection failure is not a hard error
    print(f"\n✅ Network initialization complete — DB populated, run 'olav \"show BGP status\"' to query")
    return 0


if __name__ == "__main__":
    sys.exit(main())
