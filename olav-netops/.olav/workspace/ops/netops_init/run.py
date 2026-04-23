#!/usr/bin/env python3
"""
/netops_init — Full network discovery and SSH collection pipeline.

Stages:
  1. Environment check (Nornir config, nornir-netmiko installed)
  2. Device inventory load (via Nornir — any inventory backend)
  3. SSH collection (discovery commands on all devices in parallel)
  4. Report (summary per device, parse rate, topology hint)

Usage:
  olav --agent ops "/netops_init"             # Full collection
  olav --agent ops "/netops_init --dry-run"   # Env check only, no SSH
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

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

# ── Platform normalization ───────────────────────────────────────────────
#
# R73: per-platform command lists come from ``netops.commands`` table,
# populated by :func:`olav_netops.core.commands_sync.sync_commands` at
# netops_init Stage 0. No more `discovery_commands.yaml` hardcoding.


def _normalise_platform(platform: str) -> str:
    """Back-compat shim. Returns canonical form; empty → "cisco_ios"
    default is REMOVED (GLUE-AUDIT G11 — unknown platform must be
    handled explicitly by the caller, not silently defaulted)."""
    from olav_netops.core.platform_canonical import canonicalize_platform
    result = canonicalize_platform(platform)
    return result or ""


# ── TextFSM helper ────────────────────────────────────────────────────────
# ARCH-27 / GLUE-AUDIT G7/P3: delegate to the shared universal parser.
# The old local copy (with its own _CMD_ALIASES + silent except) has been
# removed — parsing logic lives in ``olav_netops.tools.textfsm_parse``.

def _textfsm_parse(platform: str, command: str, raw_output: str) -> list[dict] | None:
    """Back-compat alias for the shared parser.

    Priority chain (see :func:`olav_netops.tools.textfsm_parse.parse_output`):
      0. PaC Python parser from ``.olav/templates/parsers/``
      1. Custom TextFSM from ``.olav/templates/<platform>/``
      2. ntc-templates built-in
    """
    from olav_netops.tools.textfsm_parse import parse_output
    return parse_output(platform, command, raw_output)


# ── Stage helpers ──────────────────────────────────────────────────────────

def _init_nornir():
    """Initialise Nornir from the configured inventory backend.

    Whichever inventory plugin is wired in nornir's ``config.yaml`` is what
    gets used — SimpleInventory (YAML), NetBoxInventory, AnsibleInventory,
    DictInventory, ... We never touch the underlying inventory files
    directly so swapping backends is a pure configuration change.
    """
    from nornir import InitNornir
    from olav_netops.core.config_paths import resolve_nornir_config_path as _resolve_nornir_config_path
    cfg = _resolve_nornir_config_path()
    return InitNornir(config_file=str(cfg), logging={"enabled": False})


def _check_environment() -> tuple[bool, list[str]]:
    """Stage 1: verify Nornir config + packages are available.

    Inventory-agnostic: initialises Nornir via whatever plugin is
    configured and counts hosts through ``nr.inventory.hosts``. Works
    identically for SimpleInventory (YAML), NetBox, Ansible, Dict, etc.
    """
    issues = []

    try:
        import nornir  # noqa: F401
        import nornir_netmiko  # noqa: F401
    except ImportError as e:
        issues.append(f"Missing dependency: {e}. Run: pip install nornir nornir-netmiko")

    try:
        from olav_netops.core.config_paths import resolve_nornir_config_path as _resolve_nornir_config_path
        cfg = _resolve_nornir_config_path()
        try:
            nr = _init_nornir()
        except KeyError as ke:
            issues.append(
                f"Nornir inventory references undefined group: {ke}. "
                f"Check your inventory plugin's group definitions."
            )
            return len(issues) == 0, issues
        except Exception as inv_err:
            issues.append(f"Nornir inventory initialisation failed: {inv_err}")
            return len(issues) == 0, issues
        try:
            host_names = list(nr.inventory.hosts.keys())
            device_count = len(host_names)
            if device_count == 0:
                issues.append(
                    "Nornir inventory contains no hosts — check inventory plugin config. "
                    "For SimpleInventory, copy .olav/workspace/ops/collect/config/nornir/hosts.yaml.example."
                )
            else:
                print(f"  ✓ Nornir config: {cfg}")
                preview = ", ".join(host_names[:6]) + ("..." if device_count > 6 else "")
                print(f"  ✓ Hosts discovered: {device_count} ({preview})")
                print(f"  ✓ Nornir inventory validated")
        finally:
            nr.close_connections()
    except Exception as e:
        issues.append(f"Nornir config error: {e}")

    return len(issues) == 0, issues


def _load_devices(nr=None) -> list[str]:
    """Stage 2: return device names from the Nornir inventory (any backend)."""
    close_after = nr is None
    if nr is None:
        nr = _init_nornir()
    try:
        return list(nr.inventory.hosts.keys())
    finally:
        if close_after:
            nr.close_connections()


def _load_host_inventory(nr=None) -> dict[str, dict[str, str]]:
    """Return {device_name → {platform, hostname, environment}} via Nornir.

    Reads through ``nr.inventory.hosts`` so this works with any Nornir
    inventory backend (SimpleInventory / NetBox / Ansible / Dict / …).
    ``hostname``, ``platform`` and ``data`` are standard Nornir Host
    attributes that every backend populates.
    """
    close_after = nr is None
    if nr is None:
        try:
            nr = _init_nornir()
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ _load_host_inventory: Nornir init failed ({exc}); falling back to empty map")
            return {}
    try:
        out: dict[str, dict[str, str]] = {}
        for name, host in nr.inventory.hosts.items():
            entry: dict[str, str] = {}
            if host.platform:
                entry["platform"] = str(host.platform).strip()
            if host.hostname:
                entry["hostname"] = str(host.hostname).strip()
            # ``host.data`` is a MutableMapping across every Nornir inventory
            # backend. ARCH-08 Phase 2 Item 2 (Round 48) stores the env tag.
            env = None
            try:
                env = host.data.get("environment") if host.data else None
            except Exception:
                env = None
            if isinstance(env, str) and env.strip():
                entry["environment"] = env.strip()
            if entry:
                out[name] = entry
        return out
    finally:
        if close_after:
            try:
                nr.close_connections()
            except Exception:
                pass


def _run_collection(
    devices: list[str],
    commands: list[str] | None,
    checkpoint: "Checkpoint | None" = None,
    *,
    skip_auto_learn: bool = False,
    auto_learn_retries: int = 5,
) -> dict:
    """Stage 3: SSH collection via Nornir.

    NETOPS-04: when ``checkpoint`` is supplied, already-completed
    (device, command) pairs are skipped and the resumed snapshot_id is
    reused. Incremental checkpoint writes happen after every successful
    ``_collect_cmd``.
    """
    # Import inline to avoid langchain decorator at import time
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
    # GLUE-AUDIT G11: do NOT silently default to cisco_ios when platform
    # is missing. Skip the device and log a warning instead — sending IOS
    # commands to an Arista/Juniper host causes cryptic failures.
    platform_groups: dict[str, list[str]] = {}
    for h in devices:
        host_obj = nr.inventory.hosts.get(h)
        raw_platform = host_obj.platform if host_obj and host_obj.platform else None
        plat = _normalise_platform(raw_platform) if raw_platform else ""
        if not plat:
            print(f"  ⚠ skipping {h}: no platform in Nornir inventory")
            continue
        platform_groups.setdefault(plat, []).append(h)

    # If caller supplied explicit commands, use them for all devices
    # Otherwise, defer list construction — `commands_display` is filled
    # from the commands table later (R73) per-platform inside the loop.
    use_explicit = commands is not None
    commands_display = commands if commands is not None else []

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
        # R73: Per-platform command list comes from ``netops.commands``
        # table, populated by sync_commands(). Sources:
        #   1. ntc-templates wheel (hundreds of commands per platform)
        #   2. .olav/templates/<platform>/*.textfsm  (custom TextFSM)
        #   3. .olav/templates/parsers/<platform>/*.py  (PaC Python parsers)
        #   4. user_commands.yaml  (backup-only raw commands)
        #   5. blacklisted_commands.yaml  (sets blacklisted=true flag)
        # No hardcoded fallback — if sync fails, SSH stage produces no
        # commands and user sees a clear error.
        platform_cmds_map: dict[str, list[str]] = {}
        from olav_netops.core.commands_sync import sync_commands, get_discovery_commands
        with duckdb.connect(str(MAIN_DB_PATH)) as _sync_conn:
            sync_stats = sync_commands(_sync_conn)
            print(f"  ✓ commands SSOT synced: "
                  f"ntc={sync_stats['ntc']} custom={sync_stats['custom']} "
                  f"pac={sync_stats['pac']} user={sync_stats['user']} "
                  f"blacklisted={sync_stats['blacklisted']} total={sync_stats['total']}")
            for plat in platform_groups:
                platform_cmds_map[plat] = get_discovery_commands(_sync_conn, plat)
        # Fill commands_display for Stage 4 summary counter.
        _union = set()
        for _v in platform_cmds_map.values():
            _union.update(_v)
        commands_display = sorted(_union)
        # R72: load device-unsupported list so we don't re-SSH for known rejects.
        _unsup_path = project_root / ".olav" / "config" / "unsupported.json"
        unsupported_pairs: set[tuple[str, str, str]] = set()
        if _unsup_path.exists():
            try:
                _unsup_data = json.loads(_unsup_path.read_text(encoding="utf-8"))
                for k, v in _unsup_data.items():
                    if "/" not in k:
                        continue
                    u_plat, u_cmd = k.split("/", 1)
                    for u_dev in (v.get("devices") or []):
                        unsupported_pairs.add((u_dev, u_plat, u_cmd))
            except Exception as _unsup_err:  # noqa: BLE001
                logger.debug("unsupported.json load failed: %s", _unsup_err)
        for plat, plat_devices in platform_groups.items():
            plat_cmds = platform_cmds_map.get(plat, [])
            if not plat_cmds:
                print(f"  ⚠ no discovery commands configured for platform {plat!r}; skipping")
                continue
            print(f"  [{plat}] {len(plat_devices)} device(s): {', '.join(plat_devices)}")
            for cmd in plat_cmds:
                pending = [
                    d for d in plat_devices
                    if (d, cmd) not in completed_set
                    and (d, plat, cmd) not in unsupported_pairs
                ]
                if not pending:
                    print(f"    ⏩ {cmd} — all devices already done or unsupported, skipping")
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
            from olav_netops.core.tables import _register_all
            from olav.platform.ingest_base import TableRegistry
            _register_all()
            with duckdb.connect(str(MAIN_DB_PATH)) as _setup_conn:
                TableRegistry.ensure_all_schemas(_setup_conn)
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

        # ── Stage 3.5: parse coverage report (R72, LEARNER-BATCH-CUT) ───
        # The pipeline no longer auto-invokes the learner. Instead we
        # classify each (device, command) into:
        #   • parsed          — structured data ready
        #   • raw-only        — raw exists, parser could unlock structure
        #   • feature-unconfigured — command ran, but feature absent
        #                       (`% BGP not active`, `No OSPF neighbors`)
        #   • device-unsupported  — device rejected command outright
        #                       (`% Invalid input`, `Unknown command`)
        # Unsupported pairs are persisted so future runs skip at SSH time.
        # feature-unconfigured is informational — don't suggest /learn_cmd.
        _INVALID_MARKERS = (
            "% invalid", "% unknown command", "% ambiguous",
            "syntax error", "unknown command", "permission denied",
            "no such command", "invalid input",
        )
        _NO_DATA_MARKERS = (
            "% bgp not active",
            "no bgp peers",
            "no ospf neighbors",
            "% ospf not active",
            "no cdp neighbors",
            "no lldp neighbors",
            "no entries",
            "0 entries found",
            "no matching entries",
            "mpls not enabled",
        )

        def _classify(raw: str) -> str:
            low = (raw or "").lower().strip()
            if not low:
                return "empty"
            head = low[:200]
            for marker in _INVALID_MARKERS:
                if marker in head:
                    return "unsupported"
            for marker in _NO_DATA_MARKERS:
                if marker in head:
                    return "unconfigured"
            # Raw text is actual data but parser didn't handle it
            return "raw"

        parsed_ok: int = 0
        raw_only: dict[tuple[str, str], list[str]] = {}
        unconfigured: dict[tuple[str, str], list[str]] = {}
        unsupported: dict[tuple[str, str], list[str]] = {}

        _unsup_config_path = _PROJECT_ROOT / ".olav" / "config" / "unsupported.json"
        try:
            _existing_unsup = (
                json.loads(_unsup_config_path.read_text(encoding="utf-8"))
                if _unsup_config_path.exists() else {}
            )
        except Exception:
            _existing_unsup = {}

        for row in all_rows:
            dev = row.get("device_name") or "?"
            cmd = row.get("command") or ""
            raw = row.get("raw_output") or ""
            host_obj = nr.inventory.hosts.get(dev)
            raw_platform = host_obj.platform if host_obj and host_obj.platform else None
            plat = _normalise_platform(raw_platform) if raw_platform else "unknown"
            key = (plat, cmd)

            if row.get("parsed_data") is not None:
                parsed_ok += 1
                continue

            cls = _classify(raw)
            if cls == "unsupported":
                unsupported.setdefault(key, []).append(dev)
            elif cls == "unconfigured":
                unconfigured.setdefault(key, []).append(dev)
            elif cls == "raw":
                raw_only.setdefault(key, []).append(dev)

        total = len(all_rows)
        coverage_pct = (parsed_ok * 100 // total) if total else 0
        print(f"\n📊 Stage 3.5: Parse coverage  {parsed_ok}/{total} ({coverage_pct}%)")

        if raw_only:
            print(f"\n  ⚠ raw-only ({sum(len(v) for v in raw_only.values())} command-samples, "
                  f"{len(raw_only)} unique commands — accessible via raw_output_store):")
            for (plat, cmd), devs in sorted(raw_only.items()):
                devs_str = ", ".join(devs[:3]) + ("…" if len(devs) > 3 else "")
                print(f"    {plat}/{cmd}  ({len(devs)} device(s): {devs_str})")

        if unconfigured:
            print(f"\n  ℹ feature-unconfigured ({sum(len(v) for v in unconfigured.values())} "
                  f"command-samples — device ran command but feature absent):")
            for (plat, cmd), devs in sorted(unconfigured.items()):
                devs_str = ", ".join(devs[:3]) + ("…" if len(devs) > 3 else "")
                print(f"    {plat}/{cmd}  ({len(devs)} device(s): {devs_str})")
            print(f"    → no parser would help here; raw already conveys the absence")

        if unsupported:
            print(f"\n  ✗ device-unsupported ({sum(len(v) for v in unsupported.values())} command-samples, "
                  f"{len(unsupported)} unique commands — device rejected):")
            for (plat, cmd), devs in sorted(unsupported.items()):
                devs_str = ", ".join(devs[:3]) + ("…" if len(devs) > 3 else "")
                print(f"    {plat}/{cmd}  ({len(devs)} device(s): {devs_str})")
            # Persist to unsupported.json so future runs skip at SSH time.
            merged = dict(_existing_unsup)
            for (plat, cmd), devs in unsupported.items():
                k = f"{plat}/{cmd}"
                entry = merged.get(k, {"devices": [], "first_seen": None})
                entry["devices"] = sorted(set(entry.get("devices", []) + devs))
                if not entry.get("first_seen"):
                    from datetime import datetime as _dt, timezone as _tz
                    entry["first_seen"] = _dt.now(_tz.utc).isoformat(timespec="seconds")
                merged[k] = entry
            _unsup_config_path.parent.mkdir(parents=True, exist_ok=True)
            _unsup_config_path.write_text(
                json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8",
            )
            print(f"    → persisted to {_unsup_config_path.name}")

        # Sim/lab-critical commands the user should consider /learn_cmd'ing
        # if they remain raw-only. (Unconfigured devices are excluded —
        # those can't produce BGP/OSPF data no matter what parser runs.)
        _CRITICAL_FOR_SIM = {
            "show ip bgp summary",
            "show bgp summary",
            "show ip ospf neighbor",
            "show ospf neighbor",
        }
        sim_gaps = [
            (plat, cmd, devs) for (plat, cmd), devs in raw_only.items()
            if cmd in _CRITICAL_FOR_SIM
        ]
        if sim_gaps:
            print(f"\n  💡 For sim/lab (BGP/OSPF structured queries), consider:")
            for (plat, cmd, devs) in sim_gaps:
                print(f'       olav --agent ops \'/learn_cmd "{cmd}" --device {devs[0]}\'')
            print(f"     (one call per platform × core concept; frozen parser cached for re-use)")

        staging_file = SNAPSHOTS_STAGING_JSON / f"{snapshot_id}.staging.json"
        SNAPSHOTS_STAGING_JSON.mkdir(parents=True, exist_ok=True)
        staging_file.write_text(json.dumps(all_rows))
        print(f"  → Staging JSON written: {staging_file.name}")

        try:
            ingest = IngestManager(db_path=MAIN_DB_PATH, staging_dir=SNAPSHOTS_STAGING_JSON)
            load_result = ingest.bulk_load()
            print(f"  ✓ IngestManager loaded: {load_result}")
        except Exception as e:
            print(f"  ✗ IngestManager ERROR: {e}")

        try:
            with duckdb.connect(str(MAIN_DB_PATH)) as conn:
                topo_rows = extract_lldp_topology(conn)
                print(f"  ✓ Topology ETL: {topo_rows} link(s) extracted")
        except Exception as e:
            print(f"  ✗ Topology ETL ERROR: {e}")

        # ── Device ETL: nornir inventory + show version → netops.devices ──
        try:
            dev_count = _populate_devices(MAIN_DB_PATH, snapshot_id, nr=nr)
            print(f"  ✓ Device ETL: {dev_count} device(s) registered")
        except Exception as e:
            print(f"  ✗ Device ETL ERROR: {e}")

        # ── ARCH-06 / ARCH-29: seed view_recipes from builtin + user YAML ──
        try:
            from olav_netops.core.recipe_seeds import load_recipe_seeds
            with duckdb.connect(str(MAIN_DB_PATH)) as _seed_conn:
                seed_stats = load_recipe_seeds(_seed_conn)
            print(
                f"  ✓ view_recipes: {seed_stats['inserted_or_updated']} "
                f"row(s) upserted from {len(seed_stats.get('source_files', []))} file(s)"
            )
        except Exception as _seed_err:  # noqa: BLE001
            print(f"  ⚠ recipe seeds skipped (non-blocking): {_seed_err}")

        # ── Stage 3.6 (ARCH-29): topology intent coverage check ────────
        # Read ~/.olav/config/topology.yaml; WARN for each (protocol, vendor)
        # pair declared by the user whose view_recipes row is missing. This
        # does NOT auto-discover — the topology agent runs discovery on
        # demand. Missing recipes just surface so user knows to invoke it.
        try:
            from olav_netops.core.topology_intent import (
                effective_intent, missing_recipes,
            )
            with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as _intent_conn:
                intent = effective_intent()
                gaps = missing_recipes(_intent_conn, intent)
            if gaps:
                gaps_fmt = ", ".join(f"{p}×{v}" for p, v in gaps)
                print(f"  ⚠ topology intent gaps ({len(gaps)}): {gaps_fmt}")
                print(f"    Run `olav --agent topology \"discover bfd\"` "
                      "or similar to draft recipes.")
            else:
                print(f"  ✓ topology intent: {', '.join(intent)} — all recipes present")
        except Exception as _intent_err:  # noqa: BLE001
            print(f"  ⚠ topology intent check skipped (non-blocking): {_intent_err}")

        # ── Stage 3.7 (ARCH-28): build_all_views (pure SQL, zero LLM) ──
        try:
            from olav_netops.core.view_builder import build_all_views
            with duckdb.connect(str(MAIN_DB_PATH)) as _view_conn:
                view_counts = build_all_views(_view_conn)
            view_summary = " ".join(f"{k}={v}" for k, v in sorted(view_counts.items()))
            print(f"  ✓ Topology views: {view_summary}")
        except Exception as _view_err:  # noqa: BLE001
            print(f"  ⚠ Stage 3.7 view builder failed (non-blocking): {_view_err}")

        # ── Stage 3.8 (R74): Batfish-compatible config export ─────────
        # Writes exports/snapshots/<YYYY-MM-DD>/batfish/configs/<host>.cfg
        # from `netops.raw_output_store` using per-platform backup commands.
        # Unlocks future Batfish analysis without any runtime coupling.
        try:
            from olav_netops.export.batfish import export_configs
            with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as _exp_conn:
                exp = export_configs(
                    _exp_conn,
                    snapshot_id=snapshot_id,
                    snapshot_date=snapshot_date,
                )
            if exp["config_count"]:
                print(
                    f"  ✓ Batfish export: {exp['config_count']} config(s) → "
                    f"{exp['output_dir']}"
                )
                if exp["devices_missing"]:
                    miss = ", ".join(exp["devices_missing"])
                    print(f"    (missing backup for: {miss})")
            else:
                print("  ℹ Batfish export: no backup configs captured yet — "
                      "check user_commands.yaml / device access")
        except Exception as _exp_err:  # noqa: BLE001
            print(f"  ⚠ Stage 3.8 Batfish export failed (non-blocking): {_exp_err}")

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
    }


def _populate_devices(db_path, snapshot_id: str, nr=None) -> int:
    """Device ETL: write Nornir inventory + show-version fingerprints into netops.devices.

    Nornir is the authoritative source of truth for ``platform`` and
    ``hostname`` (management IP) — read via ``nr.inventory.hosts`` so the
    ETL is agnostic to the inventory backend (SimpleInventory / NetBox /
    Ansible / Dict / …). We never re-extract those from CLI output.
    ``show version`` is only consulted to enrich ``model`` / ``os_version``
    via ``platform_profiles`` fingerprint fields — missing profile means
    those columns stay NULL (non-fatal).
    """
    import duckdb as _ddb
    from olav_netops.core.platform_profiles import (
        extract_model, extract_os_version, get_vendor,
    )

    inventory = _load_host_inventory(nr)

    count = 0
    with _ddb.connect(str(db_path)) as conn:
        # ARCH-08 Phase 2 Item 2 (Round 48): add environment column to
        # existing tables. DuckDB's IF NOT EXISTS is a no-op when the
        # column already sits at the schema declared by DevicesTable.
        try:
            conn.execute(
                "ALTER TABLE netops.devices ADD COLUMN IF NOT EXISTS environment VARCHAR"
            )
        except Exception as _alter_err:  # noqa: BLE001
            logger.debug("devices.environment migration skipped: %s", _alter_err)

        # Union of (Nornir-declared hosts) + (devices seen in raw_output_store).
        # Nornir hosts are primary; extras in the DB are usually LLDP neighbors
        # discovered without an inventory entry — they still get a row with
        # NULL platform / ip.
        db_devices = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT device_name FROM netops.raw_output_store"
            ).fetchall()
        }
        all_devices = sorted(db_devices | inventory.keys())

        for device_name in all_devices:
            inv = inventory.get(device_name, {})
            plat = inv.get("platform")           # Nornir-declared, authoritative
            mgmt_ip = inv.get("hostname")        # Nornir-declared, authoritative
            env_tag = inv.get("environment")     # ARCH-08 Phase 2 Item 2
            model = os_ver = None

            # show version → model / os_version (profile-driven, optional)
            if plat:
                try:
                    row = conn.execute(
                        "SELECT parsed_data::VARCHAR FROM netops.parsed_outputs "
                        "WHERE device_name=? AND command='show version' "
                        "ORDER BY snapshot_id DESC LIMIT 1",
                        [device_name],
                    ).fetchone()
                    if row and row[0]:
                        entries = json.loads(row[0])
                        if entries and isinstance(entries, list):
                            v = entries[0]
                            model = extract_model(plat, v)
                            os_ver = extract_os_version(plat, v)
                except Exception as exc:
                    logger.warning("Device ETL show-version parse failed for %s: %s", device_name, exc)

            vendor = get_vendor(plat) if plat else ""
            db_plat = plat or "unknown"

            conn.execute("""
                INSERT INTO netops.devices
                    (hostname, ip_address, platform, site, role, vendor, model, os_version, environment, last_seen, metadata)
                VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, ?, NOW(), NULL)
                ON CONFLICT (hostname) DO UPDATE SET
                    ip_address=COALESCE(EXCLUDED.ip_address, netops.devices.ip_address),
                    platform=COALESCE(EXCLUDED.platform, netops.devices.platform),
                    vendor=COALESCE(EXCLUDED.vendor, netops.devices.vendor),
                    model=COALESCE(EXCLUDED.model, netops.devices.model),
                    os_version=COALESCE(EXCLUDED.os_version, netops.devices.os_version),
                    environment=COALESCE(EXCLUDED.environment, netops.devices.environment),
                    last_seen=NOW()
            """, [device_name, mgmt_ip, db_plat, vendor, model, os_ver, env_tag])
            count += 1
    return count


def _collect_cmd(nr, target, cmd, devices, snapshot_id, snapshot_date,
                 snapshots_dir, all_rows, results_summary):
    """Run a single command on target hosts, store results.

    NETOPS-06: Nornir already isolates per-host failures in `multi.failed` —
    no outer ``try/except Exception`` wrapping target.run(), which would
    otherwise mark every device as failed when a subset succeeded.
    """
    from nornir_netmiko.tasks import netmiko_send_command
    result = target.run(task=netmiko_send_command, command_string=cmd)

    # R73: classify-before-ingest filters. Empty / device-unsupported output
    # is DROPPED from raw_output_store (don't pollute the DB with noise).
    # Feature-unconfigured (`% BGP not active` etc.) is KEPT — it carries
    # meaningful negative information the agent may query.
    _INVALID_SNIPPETS = (
        "% invalid input", "% unknown command", "% ambiguous",
        "syntax error", "permission denied",
    )

    def _should_ingest(text: str) -> tuple[bool, str]:
        low = text.lower().strip()
        if not low:
            return False, "empty output"
        head = low[:200]
        for marker in _INVALID_SNIPPETS:
            if marker in head:
                return False, "device-unsupported"
        return True, ""

    for host, multi in result.items():
        if multi.failed:
            results_summary.append({"device": host, "command": cmd, "status": "failed",
                                    "error": str(multi.exception)[:100]})
            continue
        raw_output = multi[0].result or ""

        keep, drop_reason = _should_ingest(raw_output)
        if not keep:
            results_summary.append({
                "device": host, "command": cmd,
                "status": "dropped", "reason": drop_reason,
            })
            continue

        raw_dir = snapshots_dir / snapshot_date / "raw" / host
        raw_dir.mkdir(parents=True, exist_ok=True)
        # NETOPS-05: whitelist characters so CLI-supplied `--commands ".."` or
        # `cmd\x00` can't escape raw_dir via path traversal.
        safe_cmd = re.sub(r"[^a-zA-Z0-9_-]", "_", cmd)[:60]
        (raw_dir / f"{safe_cmd}.txt").write_text(raw_output)

        parsed_data = None
        parsed_rows = 0
        # GLUE-AUDIT G11: never silently default to cisco_ios — a missing
        # platform means parsing is skipped (raw output still ingested).
        host_platform = nr.inventory.hosts[host].platform
        parsed = _textfsm_parse(host_platform, cmd, raw_output) if host_platform else None
        if parsed:
            parsed_data = json.dumps(parsed)
            parsed_rows = len(parsed)

        all_rows.append({
            "snapshot_id": snapshot_id,
            "device_name": host,
            "command": cmd,
            "raw_output": raw_output,
            "parsed_data": parsed_data,
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
    parser.add_argument(
        "--skip-auto-learn", action="store_true",
        help="Skip Stage 3.5 TextFSM auto-learn (AUTO-LEARN-PERF: each failure "
             "costs up to N LLM calls; for demo/CI set this flag).",
    )
    parser.add_argument(
        "--auto-learn-retries", type=int, default=5, metavar="N",
        help="Max LLM retries per unparseable command in Stage 3.5 (default 5).",
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
    result = _run_collection(
        devices, explicit_cmds,
        checkpoint=resume_checkpoint,
        skip_auto_learn=args.skip_auto_learn,
        auto_learn_retries=args.auto_learn_retries,
    )
    elapsed = time.time() - t1

    print(f"\n📊 Stage 4: Summary")
    print(f"  Snapshot ID : {result['snapshot_id']}")
    print(f"  Devices     : {result['devices']}")
    print(f"  Commands    : {result['commands']}")
    print(f"  Successful  : {result['successful']}")
    print(f"  Failed      : {result['failed']}")
    print(f"  Elapsed     : {elapsed:.1f}s")

    if result["failed"] > 0:
        print(f"\n⚠  Some collections failed — check credentials in hosts.yaml / defaults.yaml")
        for r in result["results"]:
            if r["status"] == "failed":
                print(f"  {r['device']} / {r['command']}: {r.get('error', 'unknown')[:80]}")
        return 0  # partial success is not a hard error
    else:
        print(f"\n✅ Network initialization complete — DB populated, run 'olav \"show BGP status\"' to query")
        return 0


if __name__ == "__main__":
    sys.exit(main())
