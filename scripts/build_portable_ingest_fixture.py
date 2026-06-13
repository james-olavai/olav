"""One-shot script: capture a snapshot tree → produce a §3-compliant bundle.

Reads ``exports/snapshots/<date>/raw/<host>/<safe_cmd>.txt`` (the on-disk
artefacts from a real ``netops_init`` run) and emits a bundle laid out
per ``dev_docs/80. PORTABLE_SNAPSHOT_INGEST.md §3``::

    <out>/
    ├── manifest.yaml
    ├── devices/
    │   ├── <hostname>/
    │   │   ├── _meta.yaml
    │   │   └── <safe_cmd>.txt   (with 2-line header)

The header re-establishes the original spaced command name (we cannot
recover it from the safe filename alone, so we use a small known map +
fall back to ``s/_/ /``).

Run once per fixture flavor:

    uv run python scripts/build_portable_ingest_fixture.py \
        --src exports/snapshots/2026-05-15/raw \
        --out tests/fixtures/portable_ingest/real_clab_capture \
        --hosts-yaml .olav/config/nornir/hosts.yaml \
        --workspace-id real_clab_capture

    uv run python scripts/build_portable_ingest_fixture.py \
        --src exports/snapshots/2026-05-15/raw \
        --out tests/fixtures/portable_ingest/synthetic_2host_bundle \
        --hosts-yaml .olav/config/nornir/hosts.yaml \
        --workspace-id synthetic_2host \
        --keep R1,R2
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

# Map safe-filename → original spaced command. Anything not in this map
# falls back to ``s/_/ /``.  Keep small; this is fixture-build only.
_SAFE_TO_CMD = {
    "show_version": "show version",
    "show_ip_interface_brief": "show ip interface brief",
    "show_ip_bgp_summary": "show ip bgp summary",
    "show_ip_route": "show ip route",
    "show_configuration": "show configuration",
    "show_running_config": "show running-config",
    "show_interfaces_terse": "show interfaces terse",
    "show_bgp_summary": "show bgp summary",
    "show_route": "show route",
    "show_lldp_neighbors": "show lldp neighbors",
}


def _cmd_from_safe(safe: str) -> str:
    if safe in _SAFE_TO_CMD:
        return _SAFE_TO_CMD[safe]
    # Generic fallback — replace underscores with spaces.
    return safe.replace("_", " ")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _platform_for_host(hosts: dict, host: str) -> tuple[str, str]:
    """Return (platform, mgmt_ip) from the inventory.  Best-effort."""
    entry = hosts.get(host) or {}
    return (
        entry.get("platform", "unknown"),
        entry.get("hostname", "0.0.0.0"),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, type=Path,
                    help="Snapshot raw dir (exports/snapshots/<date>/raw)")
    ap.add_argument("--out", required=True, type=Path,
                    help="Destination bundle directory")
    ap.add_argument("--hosts-yaml", required=True, type=Path,
                    help="Nornir hosts.yaml for platform/ip lookup")
    ap.add_argument("--workspace-id", default="fixture",
                    help="Goes into manifest.workspace_id")
    ap.add_argument("--keep",
                    help="Comma-separated subset of hosts to include (default: all)")
    args = ap.parse_args()

    if not args.src.is_dir():
        print(f"!! src not found: {args.src}", file=sys.stderr)
        return 1

    hosts = yaml.safe_load(args.hosts_yaml.read_text(encoding="utf-8")) or {}
    keep = set(args.keep.split(",")) if args.keep else None

    devices_dir = args.out / "devices"
    devices_dir.mkdir(parents=True, exist_ok=True)

    hosts_collected = 0
    cmds_total = 0
    files_for_hash: list[bytes] = []

    src_hosts = sorted(p for p in args.src.iterdir() if p.is_dir())
    for host_dir in src_hosts:
        host = host_dir.name
        if keep is not None and host not in keep:
            continue
        platform, mgmt_ip = _platform_for_host(hosts, host)
        dest_host = devices_dir / host
        dest_host.mkdir(exist_ok=True)

        cmd_files = sorted(host_dir.glob("*.txt"))
        if not cmd_files:
            continue
        hosts_collected += 1

        # Best-effort: per-host meta — we don't have model/os_version here,
        # so they go in as null; ingest pipeline tolerates.
        meta = {
            "hostname": host,
            "mgmt_ip": mgmt_ip,
            "platform": platform,
            "vendor": platform.split("_")[0].capitalize() if "_" in platform else platform,
            "os_version": None,
            "model": None,
            "commands_attempted": len(cmd_files),
            "commands_succeeded": len(cmd_files),
            "commands_failed": 0,
            "collected_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        (dest_host / "_meta.yaml").write_text(
            yaml.safe_dump(meta, sort_keys=False), encoding="utf-8",
        )

        for f in cmd_files:
            safe = f.stem
            cmd = _cmd_from_safe(safe)
            raw = f.read_text(encoding="utf-8", errors="replace")
            header = (
                f"# command: {cmd}\n"
                f"# collected_at: {meta['collected_at']}\n"
                f"# pre_scrubbed: true\n"
                f"\n"
            )
            content = header + raw
            (dest_host / f.name).write_text(content, encoding="utf-8")
            files_for_hash.append(content.encode("utf-8"))
            cmds_total += 1

    if hosts_collected == 0:
        print("!! no hosts matched --keep filter", file=sys.stderr)
        return 1

    # Content hash over concatenated bytes of all command files (stable
    # ordering = host dir name asc, then file name asc above).
    content_hash = hashlib.sha256(b"".join(files_for_hash)).hexdigest()

    manifest = {
        "schema_version": 1,
        "collector": {
            "name": "olav-collector",
            "version": "0.0.0-fixture",
            "invocation": "scripts/build_portable_ingest_fixture.py (one-off)",
        },
        "collected_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "collected_by": "fixture-build@local",
        "workspace_id": args.workspace_id,
        "hosts_collected": hosts_collected,
        "hosts_failed": 0,
        "redaction": {
            "pre_scrubbed": True,
            "salt_fingerprint": "fixture0",
            "netconan_version": "0.13.0",
        },
        "content_sha256": content_hash,
        "signature": None,
    }
    (args.out / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8",
    )

    print(f"✓ Bundle written: {args.out}")
    print(f"  hosts: {hosts_collected}")
    print(f"  commands: {cmds_total}")
    print(f"  content_sha256: {content_hash[:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
