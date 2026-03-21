#!/usr/bin/env python3
"""Network Operations DB migration script.

Runs DuckDB schema migrations (flat tables → netops.* schema).

Usage (from project root)::

    python olav-netops/scripts/netops_migrate.py
    python olav-netops/scripts/netops_migrate.py --db .olav/databases/main.duckdb

Requires olav-netops dependencies:
    uv pip install -e olav-netops
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Make project root importable when script is run directly
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent  # olav-netops/scripts/
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent  # repo root
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))
if str(_PROJECT_ROOT / "olav-netops" / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "olav-netops" / "src"))


# ---------------------------------------------------------------------------
# Main migration function
# ---------------------------------------------------------------------------


def run_migrate(db_path: str = ".olav/databases/main.duckdb") -> int:
    """Run DB schema migrations (flat tables → netops.* schema).

    Args:
        db_path: Path to the DuckDB file.

    Returns:
        Exit code (0 = success).
    """
    import duckdb
    from olav_netops.migrations.v0_12_schema_split import migrate

    resolved = Path(db_path).resolve()
    print(f"Running migrations on: {resolved}")

    with duckdb.connect(str(resolved)) as conn:
        migrate(conn)

    print(f"Migration complete: {resolved}")
    return 0


# ---------------------------------------------------------------------------
# Script entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="netops_migrate.py",
        description="OLAV NetOps — run DB schema migrations",
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=".olav/databases/main.duckdb",
        help="Path to main.duckdb (default: .olav/databases/main.duckdb)",
    )
    _args = parser.parse_args()

    sys.exit(run_migrate(db_path=_args.db))
