"""Convert ``network_data_backup_<YYYY-MM-DD>.tar.gz`` into a §3 bundle.

The inbox tarballs ship a command-major layout:

    home/admin.network/network_data/
      <safe_command>/
        <hostname>         # raw output, no extension, with prompt-echo header

We transpose to OLAV's device-major layout:

    <bundle>/
      manifest.yaml
      devices/<hostname>/
        _meta.yaml
        <safe_command>.txt   # with OLAV's 2-line header, prompt-echo stripped

The backup filename's date becomes the bundle's ``collected_at`` and the
``workspace_id`` is set to ``inbox_<YYYY-MM-DD>`` so each weekly slice
lands as its own snapshot.

Run on one tarball::

    uv run python scripts/build_bundle_from_inbox_tarball.py \\
        --tarball /home/yhvh/olav-demo-2026-05-15/.olav/inbox/network_data_backup_2026-02-15.tar.gz \\
        --out    /tmp/bundle_2026-02-15

Optional ``--hosts-limit N`` slices to the first N hostnames (for quick
smoke tests before processing 368 devices).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import yaml

_PROMPT_RE = re.compile(r"^[\w.-]+[#>]\s*\S")
_SESSION_LOG_RE = re.compile(r"^Session log for ")

# Map our tarball's command-dir name → canonical IOS command string.
# These are the directory names produced by the inbox tarball layout.
_DIR_TO_CMD: dict[str, str] = {
    "show_authentication_sessions":      "show authentication sessions",
    "show_cdp_neighbors":                "show cdp neighbors",
    "show_cdp_neighbors_detail":         "show cdp neighbors detail",
    "show_data_sources":                 "show data sources",
    "show_device-sensor_cache_all":      "show device-sensor cache all",
    "show_device-tracking_database":     "show device-tracking database",
    "show_environment":                  "show environment",
    "show_environment_power_all":        "show environment power all",
    "show_files":                        "show files",
    "show_file_systems":                 "show file systems",
    "show_interfaces":                   "show interfaces",
    "show_interfaces_counters":          "show interfaces counters",
    "show_interfaces_description":       "show interfaces description",
    "show_interfaces_status":            "show interfaces status",
    "show_interfaces_status_err-disabled": "show interfaces status err-disabled",
    "show_inventory":                    "show inventory",
    "show_ip_arp":                       "show ip arp",
    "show_ip_dhcp_snooping_binding":     "show ip dhcp snooping binding",
    "show_ip_igmp_snooping_group":       "show ip igmp snooping group",
    "show_ip_interface_brief":           "show ip interface brief",
    "show_ip_sla_statistics":            "show ip sla statistics",
    "show_logging":                      "show logging",
    "show_mac_address-table":            "show mac address-table",
    "show_module":                       "show module",
    "show_ntp_associations":             "show ntp associations",
    "show_power_inline":                 "show power inline",
    "show_processes_cpu_sorted":         "show processes cpu sorted",
    "show_running-config":               "show running-config",
    "show_running-config_all":           "show running-config all",
    "show_spanning-tree_detail":         "show spanning-tree detail",
    "show_stack-power_budget":           "show stack-power budget",
    "show_switch_detail":                "show switch detail",
    "show_tcam":                         "show tcam",
    "show_temp":                         "show temp",
    "show_version":                      "show version",
    "show_wireless_mobility_summary":    "show wireless mobility summary",
}


def _normalise_body(raw: str) -> str:
    """Drop the ``Session log for …`` line and the immediate ``host#cmd``
    prompt-echo line so TextFSM sees clean device output."""
    lines = raw.splitlines(keepends=True)
    out: list[str] = []
    skipped_session = False
    skipped_prompt = False
    for line in lines:
        if not skipped_session and _SESSION_LOG_RE.match(line):
            skipped_session = True
            continue
        if not skipped_prompt and _PROMPT_RE.match(line):
            skipped_prompt = True
            continue
        out.append(line)
    return "".join(out)


def _looks_like_hostname(name: str) -> bool:
    """Reject obvious non-hostnames pulled from the tarball.

    The inbox tarballs occasionally have stray files (``00-readme.txt``,
    ``1``, etc.) inside command directories — they're not real devices and
    shouldn't get a row in netops.devices.
    """
    if not name or name.startswith("."):
        return False
    if name.endswith(".txt") or name.endswith(".md") or name.endswith(".log"):
        return False
    if name in {"_", "0", "1"} or name.isdigit():
        return False
    # Real hostname has at least one letter and is at least 3 chars.
    return any(c.isalpha() for c in name) and len(name) >= 3


def _date_from_tarball(name: str) -> str:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    if not m:
        raise ValueError(f"cannot find date in {name}")
    return m.group(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tarball", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--hosts-limit", type=int, default=None,
                    help="Limit to first N hostnames (alphabetical) for smoke tests")
    ap.add_argument("--commands-limit", type=int, default=None,
                    help="Limit to first N commands (alphabetical) for smoke tests")
    args = ap.parse_args()

    if not args.tarball.is_file():
        print(f"!! tarball not found: {args.tarball}", file=sys.stderr)
        return 1

    backup_date = _date_from_tarball(args.tarball.name)
    collected_iso = f"{backup_date}T03:00:00Z"  # nominal nightly backup hour

    devices_dir = args.out / "devices"
    devices_dir.mkdir(parents=True, exist_ok=True)

    # Pass 1: load all (host, command, body) tuples from the tarball into RAM
    # — bundles are weekly, ~21 MB compressed / ~70 MB uncompressed, fine.
    per_host: dict[str, dict[str, str]] = {}    # host → {cmd: body}
    with tarfile.open(args.tarball, "r:gz") as tf:
        members = tf.getmembers()
        for m in members:
            if not m.isfile():
                continue
            parts = m.name.split("/")
            # Expected: home/admin.network/network_data/<cmd>/<host>
            if len(parts) < 5:
                continue
            cmd_dir = parts[3]
            host = parts[4]
            cmd = _DIR_TO_CMD.get(cmd_dir)
            if cmd is None:
                # Unknown command directory — skip with a note.
                continue
            if not _looks_like_hostname(host):
                continue
            f = tf.extractfile(m)
            if f is None:
                continue
            try:
                body = f.read().decode("utf-8", errors="replace")
            except Exception:
                continue
            per_host.setdefault(host, {})[cmd] = body

    if not per_host:
        print("!! tarball produced 0 (host, command) records", file=sys.stderr)
        return 1

    # Optionally truncate for smoke tests.
    hosts_sorted = sorted(per_host.keys())
    if args.hosts_limit:
        hosts_sorted = hosts_sorted[: args.hosts_limit]
    cmds_keep: set[str] | None = None
    if args.commands_limit:
        all_cmds_sorted = sorted({c for h in hosts_sorted for c in per_host.get(h, {})})
        cmds_keep = set(all_cmds_sorted[: args.commands_limit])

    # Pass 2: write the bundle tree.
    hosts_written = 0
    cmds_written = 0
    for host in hosts_sorted:
        cmd_map = per_host[host]
        if cmds_keep is not None:
            cmd_map = {c: b for c, b in cmd_map.items() if c in cmds_keep}
        if not cmd_map:
            continue
        host_dir = devices_dir / host
        host_dir.mkdir(parents=True, exist_ok=True)

        # Platform is intentionally left as "unknown" — the ingest pipeline's
        # discover_platform() runs a TextFSM cascade across vendor candidates
        # and overrides this with the correct key (and gets model + os_version
        # for free).  String-matching show_version raw text here was brittle —
        # see ADR-0007 + the v0.22 cisco_xe / cisco_ios regression.
        meta = {
            "hostname": host,
            "mgmt_ip": "0.0.0.0",          # unknown — historical backup
            "platform": "unknown",
            "vendor": "Unknown",
            "os_version": None,
            "model": None,
            "commands_attempted": len(cmd_map),
            "commands_succeeded": len(cmd_map),
            "commands_failed": 0,
            "collected_at": collected_iso,
        }
        (host_dir / "_meta.yaml").write_text(
            yaml.safe_dump(meta, sort_keys=False), encoding="utf-8",
        )

        for cmd, body in sorted(cmd_map.items()):
            cleaned = _normalise_body(body)
            safe = cmd.replace(" ", "_").replace("/", "_") + ".txt"
            content = (
                f"# command: {cmd}\n"
                f"# collected_at: {collected_iso}\n"
                f"# pre_scrubbed: false\n"
                f"\n"
                f"{cleaned}"
            )
            (host_dir / safe).write_text(content, encoding="utf-8")
            cmds_written += 1

        hosts_written += 1

    # Pass 3: compute content sha256 + write manifest.
    h = hashlib.sha256()
    for host_dir in sorted(d for d in devices_dir.iterdir() if d.is_dir()):
        for cmd_file in sorted(f for f in host_dir.iterdir() if f.is_file() and f.suffix == ".txt"):
            h.update(cmd_file.read_bytes())
    content_sha256 = h.hexdigest()

    manifest = {
        "schema_version": 1,
        "collector": {
            "name": "inbox-tarball-adapter",
            "version": "0.1.0",
            "invocation": (
                "scripts/build_bundle_from_inbox_tarball.py "
                f"--tarball {args.tarball.name}"
            ),
        },
        "collected_at": collected_iso,
        "collected_by": "historical-backup",
        "workspace_id": f"inbox_{backup_date}",
        "hosts_collected": hosts_written,
        "hosts_failed": 0,
        "redaction": {
            "pre_scrubbed": False,
            "salt_fingerprint": None,
            "netconan_version": None,
        },
        "content_sha256": content_sha256,
        "signature": None,
    }
    (args.out / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8",
    )

    print(f"✓ Bundle written: {args.out}")
    print(f"  backup_date: {backup_date}")
    print(f"  hosts: {hosts_written}")
    print(f"  commands: {cmds_written}")
    print(f"  content_sha256: {content_sha256[:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
