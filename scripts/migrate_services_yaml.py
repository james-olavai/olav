#!/usr/bin/env python3
"""
migrate_services_yaml.py — Migrate services.yaml from tool_generation to reference_generation.

Usage:
    uv run python scripts/migrate_services_yaml.py [services.yaml]         # dry-run
    uv run python scripts/migrate_services_yaml.py --write [services.yaml] # write changes

Doc 39 §10.1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

_DEFAULT_YAML = Path(".olav/config/services.yaml")
_DEFAULT_OUTPUT_DIR = ".olav/workspace/infra/references"


def migrate(doc: dict) -> tuple[dict, list[str]]:
    """Return (migrated_doc, list_of_changed_service_names). Idempotent."""
    changed: list[str] = []
    for name, svc in doc.get("services", {}).items():
        if "tool_generation" in svc and "reference_generation" not in svc:
            tg = svc.pop("tool_generation")
            svc["reference_generation"] = {
                "output_dir": _DEFAULT_OUTPUT_DIR,
                "groups": tg.get("groups", []),
            }
            changed.append(name)
    return doc, changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=str(_DEFAULT_YAML),
                        help="Path to services.yaml (default: .olav/config/services.yaml)")
    parser.add_argument("--write", action="store_true",
                        help="Write changes to file (default: dry-run only)")
    args = parser.parse_args(argv)

    yaml_path = Path(args.path)
    if not yaml_path.exists():
        print(f"ERROR: {yaml_path} not found", file=sys.stderr)
        return 1

    raw = yaml_path.read_text(encoding="utf-8")
    doc = yaml.safe_load(raw) or {}

    _, changed = migrate(doc)

    if not changed:
        print("✅ Nothing to migrate — all services already use reference_generation.")
        return 0

    print(f"{'Would migrate' if not args.write else 'Migrating'} {len(changed)} service(s): "
          f"{', '.join(changed)}")

    if args.write:
        # Re-parse to apply in-place (migrate modifies doc in place)
        doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        migrate(doc)
        yaml_path.write_text(yaml.dump(doc, default_flow_style=False, allow_unicode=True),
                             encoding="utf-8")
        print(f"✅ Written to {yaml_path}")
    else:
        print("(dry-run) Pass --write to apply changes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
