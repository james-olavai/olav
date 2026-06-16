"""``olav migrate`` command — apply the v0.20.2 layout migration.

Part of Phase B (dev_docs/53).  Surfaces
:mod:`olav.migrate.v0_20_layout` to end-users via a small CLI wrapper:

.. code-block:: shell

   olav migrate                     # backup + apply
   olav migrate --dry-run           # print plan, touch nothing
   olav migrate --dry-run --json    # machine-readable plan
   olav migrate --no-backup         # apply without tarball backup
   olav migrate --root <path>       # explicit install root (default: cwd)

All heavy lifting lives in :mod:`olav.migrate.v0_20_layout`.  This
module only parses arguments, formats output, and decides when to
call :func:`apply_migration` vs skipping it on empty plans.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from olav.cli.commands._argparse import parse_subcommand_args
from olav.cli.commands.base import BaseCommand

logger = logging.getLogger(__name__)


class MigrateCommand(BaseCommand):
    """User-facing ``olav migrate`` verb.

    Dispatches to the pure planner + applier in
    :mod:`olav.migrate.v0_20_layout`.  Preserves the ``--dry-run``
    contract: in dry-run mode, ``apply_migration`` is never invoked
    even if callers wired a subparser that allows combining flags.
    """

    def __init__(self) -> None:
        super().__init__(
            name="migrate",
            description="Migrate OLAV workspace from v0.19.x layout to v0.20.2+",
        )

    async def execute(self, args: str = "") -> str:
        parts = parse_subcommand_args(args)
        flags = self._parse_flags(parts)
        if "error" in flags:
            return flags["error"]

        root = flags["root"]
        dry_run: bool = flags["dry_run"]
        as_json: bool = flags["json"]
        backup: bool = flags["backup"]

        # Import lazily so the CLI registers without pulling tarfile /
        # shutil at module load.
        from olav.migrate.v0_20_layout import (
            apply_migration,
            plan_migration,
        )

        plan = plan_migration(root)

        # Dry-run: print summary (or JSON) and return without applying.
        if dry_run:
            if as_json:
                return json.dumps(plan.as_dict(), default=str, indent=2)
            return plan.summary()

        # Empty plan: don't bother invoking apply.
        if not plan.operations:
            return (
                "nothing to migrate — workspace is already on the new layout."
            )

        result = apply_migration(plan, backup=backup)

        lines = [
            f"✓ applied {result.applied_operations} operation(s)",
        ]
        if result.skipped_operations:
            lines.append(
                f"⚠ skipped {result.skipped_operations} operation(s) — see log"
            )
        if result.backup_path is not None:
            lines.append(f"  backup: {result.backup_path}")
        return "\n".join(lines)

    @staticmethod
    def _parse_flags(parts: list[str]) -> dict[str, Any]:
        """Parse argv-style flags into a small dict.

        Recognised:
          * ``--dry-run`` (bool)
          * ``--json`` (bool, requires ``--dry-run``)
          * ``--no-backup`` (bool, disables backup)
          * ``--root <path>`` (str → Path, default cwd)

        Unknown flags produce an ``error`` key whose value is the
        usage string.
        """
        dry_run = False
        as_json = False
        backup = True
        root = Path.cwd()

        i = 0
        while i < len(parts):
            token = parts[i]
            if token == "--dry-run":
                dry_run = True
                i += 1
            elif token == "--json":
                as_json = True
                i += 1
            elif token == "--no-backup":
                backup = False
                i += 1
            elif token == "--root":
                if i + 1 >= len(parts):
                    return {"error": "usage: olav migrate [--root PATH]"}
                root = Path(parts[i + 1]).expanduser()
                i += 2
            elif token in ("-h", "--help"):
                return {"error": MigrateCommand._usage()}
            else:
                return {"error": f"unknown flag: {token}\n{MigrateCommand._usage()}"}

        return {
            "dry_run": dry_run,
            "json": as_json,
            "backup": backup,
            "root": root,
        }

    @staticmethod
    def _usage() -> str:
        return (
            "usage: olav migrate [--dry-run] [--json] [--no-backup] [--root PATH]\n"
            "  --dry-run    Print what would change; do not touch disk\n"
            "  --json       (with --dry-run) emit plan as JSON\n"
            "  --no-backup  Skip .olav.bak/ tarball (NOT recommended)\n"
            "  --root PATH  OLAV install root (default: current dir)"
        )


__all__ = ["MigrateCommand"]
