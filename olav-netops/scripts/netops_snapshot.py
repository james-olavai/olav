#!/usr/bin/env python3
"""Network Operations snapshot script.

Triggers a manual network snapshot (Stage 1: SSH collect + TextFSM parse).

Usage (from project root)::

    python olav-netops/scripts/netops_snapshot.py
    python olav-netops/scripts/netops_snapshot.py --repair   # auto-repair parse errors

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
# Main snapshot function
# ---------------------------------------------------------------------------


def run_snapshot(repair: bool = False) -> int:
    """Trigger a manual network snapshot (Stage 1 collect + parse).

    Args:
        repair: If True, attempt auto-repair of parse errors after collection.

    Returns:
        Exit code (0 = success).
    """
    try:
        from rich.console import Console
        from rich.progress import Progress, SpinnerColumn, TextColumn
    except ImportError as exc:
        print(f"ERROR: rich is required: {exc}", file=sys.stderr)
        return 1

    from olav.core.config import AGENT_DIR

    console = Console()
    # olav-netops ships its own workspace — prefer package-local paths.
    _netops_dir = _SCRIPT_DIR.parent  # olav-netops/
    _netops_sync_tools    = _netops_dir / ".olav" / "workspace" / "config" / "sync" / "tools"
    _netops_learner_tools = _netops_dir / ".olav" / "workspace" / "config" / "learner" / "tools"
    _sync_tools    = AGENT_DIR / "workspace" / "config" / "sync" / "tools"
    _learner_tools = AGENT_DIR / "workspace" / "config" / "learner" / "tools"
    for _p in (_netops_sync_tools, _netops_learner_tools, _sync_tools, _learner_tools):
        if _p.exists() and str(_p) not in sys.path:
            sys.path.insert(0, str(_p))

    try:
        from collect_commands import collect_commands  # noqa: PLC0415
    except ImportError as exc:
        console.print(f"[red]ERROR: collect_commands tool not found: {exc}[/red]")
        return 1

    console.rule("[bold cyan]Network Snapshot[/bold cyan]")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("SSH collecting from all devices...", total=None)
        result = collect_commands.func(wait=True)
        progress.update(task, description="✅ Snapshot complete", completed=True)

    snapshot_id = result.get("snapshot_id", "unknown")
    devices = result.get("devices", [])
    parse_errors = result.get("parse_errors", [])
    console.print(
        f"[green]✓[/green] Snapshot [bold]{snapshot_id}[/bold]: "
        f"{len(devices)} device(s), {len(parse_errors)} parse error(s)."
    )

    if repair and parse_errors:
        console.print("[dim]--repair: attempting auto-repair of parse errors...[/dim]")
        try:
            from repair_template import repair_template  # noqa: PLC0415
        except ImportError as exc:
            console.print(f"[yellow]⚠ repair_template tool not found: {exc}[/yellow]")
            return 0

        fixed = 0
        for gap in parse_errors:
            dev = gap.get("sample_device", "")
            cmd = gap.get("command", "")
            repair_result = repair_template.func(device=dev, command=cmd)
            if repair_result.get("success"):
                fixed += 1
        console.print(f"[green]✓[/green] Auto-repaired {fixed}/{len(parse_errors)} parse error(s).")

    return 0


# ---------------------------------------------------------------------------
# Script entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="netops_snapshot.py",
        description="OLAV NetOps — trigger a manual network snapshot",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Auto-repair parse errors after collection",
    )
    _args = parser.parse_args()

    sys.exit(run_snapshot(repair=_args.repair))
