#!/usr/bin/env python3
"""
/netops_init — Full network discovery and SSH collection pipeline.

Stages:
  1. Environment check (Nornir config, nornir-netmiko installed)
  2. Device inventory load (hosts.yaml)
  3. SSH collection (discovery commands on all devices in parallel)
  4. Report (summary per device, parse rate, topology hint)

Usage:
  olav --agent ops "/netops_init"             # Full collection
  olav --agent ops "/netops_init --dry-run"   # Env check only, no SSH
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

# ── Platform command mapping ──────────────────────────────────────────────

# Universal commands (work on most platforms)
DISCOVERY_COMMANDS_UNIVERSAL = [
    "show version",
    "show interfaces",
]

# Cisco IOS-specific commands
DISCOVERY_COMMANDS_IOS = [
    "show ip interface brief",
    "show cdp neighbors detail",
    "show lldp neighbors detail",
    "show bgp summary",
    "show bgp all summary",
    "show ip bgp summary",
    "show ip ospf neighbors",
    "show ip route",
    "show ip arp",
    "show vlan brief",
    "show spanning-tree",
    "show running-config",
]

# Juniper JunOS-specific commands (matched to ntc_templates availability)
DISCOVERY_COMMANDS_JUNOS = [
    "show interfaces terse",
    "show lldp neighbors",
    "show bgp summary",
    "show ospf neighbor",
    "show route summary",
    "show arp no-resolve",
    "show chassis hardware",
    "show vlans",
    "show configuration",
]

# Platform → command list mapping
_PLATFORM_COMMANDS: dict[str, list[str]] = {
    "cisco_ios": DISCOVERY_COMMANDS_UNIVERSAL + DISCOVERY_COMMANDS_IOS,
    "cisco_nxos": DISCOVERY_COMMANDS_UNIVERSAL + DISCOVERY_COMMANDS_IOS,
    "juniper_junos": DISCOVERY_COMMANDS_UNIVERSAL + DISCOVERY_COMMANDS_JUNOS,
}

# Legacy flat list used when --commands override is passed
DISCOVERY_COMMANDS = DISCOVERY_COMMANDS_UNIVERSAL + DISCOVERY_COMMANDS_IOS

# Platforms that are NOT Cisco IOS-compatible
_JUNOS_PLATFORMS = {"juniper_junos", "juniper", "junos"}


def _normalise_platform(platform: str) -> str:
    """Map various platform strings to canonical form."""
    p = (platform or "").replace("-", "_").lower()
    if p in ("ios", "cisco_ios", "cisco_ios_xe"):
        return "cisco_ios"
    if p in ("junos", "juniper_junos", "juniper"):
        return "juniper_junos"
    if p in ("nxos", "cisco_nxos"):
        return "cisco_nxos"
    return p or "cisco_ios"


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

    Command-filename aliases (``show ip ospf neighbors`` → ``…_neighbor``
    etc.) moved to ``textfsm_parse._NTC_FILENAME_ALIASES``.
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
                f"Copy from: .olav/workspace/ops/collect/config/nornir/hosts.yaml.example"
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
    """ARCH-08 Phase 2 Item 2 (Round 48): load {hostname → environment}.

    Reads the Nornir ``hosts.yaml`` and extracts the ``data.environment``
    tag for each host, skipping devices that don't declare one. Returns an
    empty dict if the inventory is missing or unparseable — caller treats
    that as "no env information available; write NULL for every device".
    """
    try:
        from olav_netops.core.config_paths import resolve_nornir_config_path as _resolve_nornir_config_path
        import yaml
        hosts = _resolve_nornir_config_path().parent / "hosts.yaml"
        if not hosts.exists():
            return {}
        with open(hosts) as f:
            data = yaml.safe_load(f) or {}
        out: dict[str, str] = {}
        for hostname, spec in data.items():
            if not isinstance(spec, dict):
                continue
            host_data = spec.get("data")
            if not isinstance(host_data, dict):
                continue
            env = host_data.get("environment")
            if isinstance(env, str) and env.strip():
                out[hostname] = env.strip()
        return out
    except Exception:
        return {}


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
    # Otherwise, use platform-specific command lists
    use_explicit = commands is not None
    if commands is None:
        # Collect the union of all platform commands for progress display
        all_cmds_set: set[str] = set()
        for plat in platform_groups:
            all_cmds_set.update(_PLATFORM_COMMANDS.get(plat, DISCOVERY_COMMANDS_UNIVERSAL))
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
        for plat, plat_devices in platform_groups.items():
            plat_cmds = _PLATFORM_COMMANDS.get(plat, DISCOVERY_COMMANDS_UNIVERSAL)
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
                print(f"        olav --agent ops '/learn_cmd {plat} \"{cmd}\"'")
            if len(raw_only) > 6:
                print(f"        …and {len(raw_only) - 6} more (see .olav/config/unsupported.json)")

        if unsupported:
            print(f"  unsupported: {len(unsupported)} pair(s) — error messages / empty output, "
                  "no parser would help")

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
            dev_count = _populate_devices(MAIN_DB_PATH, snapshot_id)
            print(f"  ✓ Device ETL: {dev_count} device(s) registered")
        except Exception as e:
            print(f"  ✗ Device ETL ERROR: {e}")

        # ── ARCH-06: seed view_recipes with hand-curated mappings ──────
        try:
            from olav_netops.core.recipe_seeds import load_recipe_seeds
            with duckdb.connect(str(MAIN_DB_PATH)) as _seed_conn:
                seed_stats = load_recipe_seeds(_seed_conn)
            print(
                f"  ✓ view_recipes seeds: {seed_stats['inserted_or_updated']} "
                f"row(s) upserted"
            )
        except Exception as _seed_err:  # noqa: BLE001
            # Seed load is advisory — LLM discovery still runs.
            print(f"  ⚠ recipe seeds skipped (non-blocking): {_seed_err}")

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


def _populate_devices(db_path, snapshot_id: str) -> int:
    """Device ETL: extract device info from parsed_outputs → netops.devices.

    Nornir-independent — reads only from DB tables populated by IngestManager.
    Sources: show version (model/os), show ip interface brief / show interfaces terse (mgmt IP).

    ARCH-08 Phase 2 Item 2 (Round 48): also joins the Nornir inventory's
    ``data.environment`` tag into ``netops.devices.environment`` so
    downstream queries can filter by lab/prod/staging. An
    ``ALTER TABLE ADD COLUMN IF NOT EXISTS`` migration keeps pre-R48
    deployments working without a data-wipe.
    """
    import duckdb as _ddb

    _PLATFORM_VENDOR = {
        "cisco_ios": "Cisco", "cisco_nxos": "Cisco", "cisco_xr": "Cisco",
        "juniper_junos": "Juniper", "arista_eos": "Arista", "huawei_vrp": "Huawei",
    }

    # Load the hostname → environment map once. Empty dict when inventory
    # is absent — every device gets NULL environment in that case.
    host_envs = _load_host_environments()

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

        devices = conn.execute(
            "SELECT DISTINCT device_name FROM netops.raw_output_store"
        ).fetchall()

        for (device_name,) in devices:
            model = os_ver = plat = mgmt_ip = None

            # ── show version → platform, model, os_version ───────────────
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
                        if v.get("JUNOS_VERSION"):
                            plat = "juniper_junos"
                        elif v.get("HARDWARE") or v.get("VERSION"):
                            plat = "cisco_ios"
                        model = v.get("MODEL") or (v.get("HARDWARE", [None]) or [None])[0]
                        os_ver = (v.get("JUNOS_VERSION") or v.get("VERSION")
                                  or v.get("ROMMON") or v.get("SOFTWARE_IMAGE") or "")
            except Exception:
                pass

            # ── show ip interface brief → management IP (IOS) ────────────
            try:
                row = conn.execute(
                    "SELECT parsed_data::VARCHAR FROM netops.parsed_outputs "
                    "WHERE device_name=? AND command='show ip interface brief' "
                    "ORDER BY snapshot_id DESC LIMIT 1",
                    [device_name],
                ).fetchone()
                if row and row[0]:
                    ifaces = json.loads(row[0])
                    if ifaces and isinstance(ifaces, list):
                        # Prefer: Loopback0 > management interface > highest non-link-local IP
                        for iface in ifaces:
                            name = (iface.get("INTF") or iface.get("INTERFACE") or "").lower()
                            ip = iface.get("IPADDR") or iface.get("IP_ADDRESS") or ""
                            status = (iface.get("STATUS") or "").lower()
                            if ip and ip != "unassigned" and "up" in status:
                                if "loopback" in name:
                                    mgmt_ip = ip
                                    break
                                if not mgmt_ip and not ip.startswith("10."):
                                    mgmt_ip = ip
                        # Fallback: any up interface with an IP
                        if not mgmt_ip:
                            for iface in ifaces:
                                ip = iface.get("IPADDR") or iface.get("IP_ADDRESS") or ""
                                if ip and ip != "unassigned":
                                    mgmt_ip = ip
                                    break
            except Exception:
                pass

            # ── show interfaces terse → management IP (Junos) ────────────
            # ntc_templates has no template for this command; parse raw output directly
            if not mgmt_ip:
                try:
                    import re
                    row = conn.execute(
                        "SELECT raw_output FROM netops.raw_output_store "
                        "WHERE device_name=? AND command='show interfaces terse' "
                        "ORDER BY snapshot_id DESC LIMIT 1",
                        [device_name],
                    ).fetchone()
                    if row and row[0]:
                        # Junos format: "fxp0.0  up  up  inet  192.168.100.101/24"
                        for line in row[0].splitlines():
                            parts = line.split()
                            if len(parts) >= 4:
                                iface_name = parts[0].lower()
                                for p in parts:
                                    m = re.match(r"(\d+\.\d+\.\d+\.\d+)(?:/\d+)?$", p)
                                    if m and ("fxp0" in iface_name or "em0" in iface_name
                                              or "me0" in iface_name):
                                        mgmt_ip = m.group(1)
                                        break
                                    if m and "lo0" in iface_name:
                                        mgmt_ip = mgmt_ip or m.group(1)
                                if mgmt_ip and "fxp" in iface_name:
                                    break  # fxp0 is preferred management interface
                except Exception:
                    pass

            plat = plat or "unknown"
            vendor = _PLATFORM_VENDOR.get(plat, "")

            env_tag = host_envs.get(device_name)  # ARCH-08 Phase 2 Item 2
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
            """, [device_name, mgmt_ip, plat, vendor, model, os_ver, env_tag])
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

        parsed_data = None
        parsed_rows = 0
        parsed = _textfsm_parse(
            nr.inventory.hosts[host].platform or "cisco_ios",
            cmd, raw_output
        )
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
