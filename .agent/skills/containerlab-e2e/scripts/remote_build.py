#!/usr/bin/env python3
"""
Remote build helper — runs on NAS (192.168.100.50).

Workflow:
  1. rsync lab_sessions/ → lab host (.12):/mnt/data/containerlab/lab_sessions/
  2. scp build_images.py → lab host (.12):/mnt/data/containerlab/build_images.py
  3. SSH to .12 and run: python3 /mnt/data/containerlab/build_images.py [args]

Requirements:
  - SSH key auth already configured: ssh yhvh@192.168.100.12

Usage:
  python3 scripts/remote_build.py                     # rsync + build all images
  python3 scripts/remote_build.py --only iol           # build one image
  python3 scripts/remote_build.py --check              # verify source files on .12
  python3 scripts/remote_build.py --sync-only          # rsync only, no build
"""

import argparse
import subprocess
import sys
from pathlib import Path

REMOTE_HOST = "yhvh@192.168.100.12"
REMOTE_BASE = "/mnt/data/containerlab"

SKILL_DIR    = Path(__file__).resolve().parent.parent   # .agent/skills/containerlab-e2e/
LAB_SESSIONS = SKILL_DIR / "lab_sessions"
BUILD_SCRIPT = SKILL_DIR / "scripts" / "build_images.py"


def run(cmd: list[str], check: bool = True) -> int:
    print(f"$ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd)
    if check and result.returncode != 0:
        print(f"[ERROR] command failed (exit {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)
    return result.returncode


def sync_files() -> None:
    print("\n=== Syncing lab_sessions → .12 ===")
    run([
        "rsync", "-avz", "--progress", "--delete",
        str(LAB_SESSIONS) + "/",
        f"{REMOTE_HOST}:{REMOTE_BASE}/lab_sessions/",
    ])

    print("\n=== Uploading build_images.py → .12 ===")
    run([
        "scp", str(BUILD_SCRIPT),
        f"{REMOTE_HOST}:{REMOTE_BASE}/build_images.py",
    ])


def remote_build(extra_args: list[str]) -> None:
    print(f"\n=== Running build_images.py on .12 (args: {extra_args}) ===")
    remote_cmd = f"python3 {REMOTE_BASE}/build_images.py {' '.join(extra_args)}"
    # -tt forces a pseudo-terminal so docker build progress prints live
    run(["ssh", "-tt", REMOTE_HOST, remote_cmd])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=["ceos", "iol", "vsrx", "panos", "fortios"],
                        help="Build only this specific image")
    parser.add_argument("--check", action="store_true",
                        help="Verify source files on .12 without building")
    parser.add_argument("--sync-only", action="store_true",
                        help="rsync files only, do not trigger a build")
    args = parser.parse_args()

    sync_files()

    if args.sync_only:
        print("\n[OK] Sync complete. Run without --sync-only to also build.")
        return

    extra: list[str] = []
    if args.check:
        extra = ["--check"]
    elif args.only:
        extra = ["--only", args.only]

    remote_build(extra)


if __name__ == "__main__":
    main()
