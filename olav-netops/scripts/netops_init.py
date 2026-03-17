#!/usr/bin/env python3
"""Network Operations onboarding script.

Runs the full Stage 1-5 pipeline:
  Stage 1 : SSH collect + TextFSM parse
  Stage 2 : Repair-queue analysis
  Stage 3a: Collection-wrap artifact report
  Stage 3b: LLM auto-repair P0 template gaps
  Stage 3c: Discovery-command gap check
  Stage 4 : Topology generation
  Stage 5 : Register trace_learner daily cron

Usage (from project root)::

    python olav-netops/scripts/netops_init.py
    python olav-netops/scripts/netops_init.py --dry-run   # env check only

Requires olav-netops dependencies:
    uv pip install -e olav-netops
"""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cron helper
# ---------------------------------------------------------------------------

_CRON_MARKER = "trace_learner"
_CRON_COMMENT = "# OLAV trace_learner — daily at 03:00"


def _register_trace_learner_cron(
    project_root: Path,
    cron_file: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Register a daily cron job that runs trace_learner."""
    cron_line = (
        f"{_CRON_COMMENT}\n"
        f"0 3 * * *  cd {project_root} && uv run olav --agent config "
        f'"run trace_learner()"\n'
    )

    if dry_run:
        return {"status": "dry_run", "cron_line": cron_line.strip()}

    if cron_file is None:
        cron_file = Path.home() / ".olav" / "cron.tab"

    cron_file.parent.mkdir(parents=True, exist_ok=True)

    existing = cron_file.read_text() if cron_file.exists() else ""
    if _CRON_MARKER in existing:
        return {"status": "already_registered", "cron_file": str(cron_file)}

    with open(cron_file, "a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(cron_line)

    logger.info("trace_learner cron registered in %s", cron_file)
    return {"status": "registered", "cron_file": str(cron_file)}


# ---------------------------------------------------------------------------
# Step helpers (env verification)
# ---------------------------------------------------------------------------


def _step_infra(console) -> bool:
    """Verify infrastructure prerequisites (project root, .olav dir)."""
    from rich.panel import Panel

    issues: list[str] = []

    olav_dir = _PROJECT_ROOT / ".olav"
    if not olav_dir.exists():
        issues.append(f".olav/ directory not found at {olav_dir}")

    workspace_dir = olav_dir / "workspace"
    if not workspace_dir.exists():
        issues.append(f".olav/workspace/ not found — run `olav init` first")

    if issues:
        console.print(
            Panel.fit(
                "[bold red]❌ Infrastructure check failed[/bold red]\n\n"
                + "\n".join(f"• {i}" for i in issues),
                border_style="red",
            )
        )
        return False

    console.print("[green]✅ Step 0: Infrastructure OK[/green]")
    return True


def _step_llm(console) -> bool:
    """Verify LLM connectivity."""
    try:
        from olav.core.config import get_paths_config  # noqa: PLC0415

        cfg = get_paths_config()
        _ = cfg.project_root  # force load
        console.print("[green]✅ Step 1: LLM config OK[/green]")
        return True
    except Exception as exc:
        console.print(f"[red]❌ Step 1: LLM config error — {exc}[/red]")
        return False


def _step_nornir(console) -> bool:
    """Verify nornir + inventory are importable."""
    try:
        import nornir  # noqa: F401

        console.print("[green]✅ Step 2: Nornir OK[/green]")
        return True
    except ImportError as exc:
        console.print(
            f"[red]❌ Step 2: nornir not installed — {exc}[/red]\n"
            "[dim]Install: uv pip install -e olav-netops[/dim]"
        )
        return False


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run_init(dry_run: bool = False) -> int:
    """Execute the full Stage 1-5 onboarding pipeline.

    Args:
        dry_run: If True, verify environment only without running collection.

    Returns:
        Exit code (0 = success).
    """
    try:
        from rich import box
        from rich.console import Console
        from rich.panel import Panel
        from rich.progress import Progress, SpinnerColumn, TextColumn
        from rich.prompt import Confirm
        from rich.table import Table
    except ImportError as exc:
        print(f"ERROR: rich is required — install olav-netops dependencies: {exc}", file=sys.stderr)
        return 1

    console = Console()
    console.clear()
    console.print(
        Panel.fit(
            "[bold cyan]Welcome to OLAV NetOps Onboarding[/bold cyan]\n"
            "This process will guide you through configuring your AI and synchronising your network data.",
            border_style="cyan",
        )
    )

    # ── Step 0: Infrastructure ──────────────────────────────────────────────
    if not _step_infra(console):
        return 1

    # ── Step 1: LLM ────────────────────────────────────────────────────────
    if not _step_llm(console):
        return 1

    # ── Step 2: Nornir ─────────────────────────────────────────────────────
    if not _step_nornir(console):
        return 1

    if dry_run:
        console.print("\n[green]✅ Dry run complete — environment looks good.[/green]")
        console.print("[dim]Re-run without --dry-run to execute the full pipeline.[/dim]")
        return 0

    # ── Step 3a: Sync inventory + command library ───────────────────────────
    console.print(
        Panel.fit(
            "[bold green]✅ Environment verified[/bold green]\n\n"
            "Step 3a: Syncing inventory and command library...",
            border_style="green",
        )
    )

    import asyncio

    from olav.cli.main import run_single_query  # platform dependency

    asyncio.run(
        run_single_query(
            "Run sync_inventory() then sync_commands(). "
            "DO NOT run collect_commands or generate_topology — those run next. "
            "Report device count and template count only.",
            assistant_id="config",
        )
    )

    # ── Steps 3b–5: staged pipeline ─────────────────────────────────────────
    from olav.core.config import AGENT_DIR, CONFIG_DIR

    _sync_tools = AGENT_DIR / "workspace" / "config" / "sync" / "tools"
    _learner_tools = AGENT_DIR / "workspace" / "config" / "learner" / "tools"
    _discovery_tools = AGENT_DIR / "workspace" / "config" / "discovery" / "tools"
    for _p in (_sync_tools, _learner_tools, _discovery_tools):
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))

    from collect_commands import collect_commands  # noqa: PLC0415
    from repair_template import repair_template  # noqa: PLC0415
    from run_topology_sandbox import run_topology_sandbox  # noqa: PLC0415

    # ── Stage 1: SSH Collect + TextFSM Parse ──────────────────────────────
    console.rule("[bold cyan]Stage 1: SSH Collect + Parse[/bold cyan]")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("SSH connecting to all devices...", total=None)
        collect_result = collect_commands.func(wait=True)
        progress.update(task, description="✅ Collection complete", completed=True)

    snapshot_id = collect_result.get("snapshot_id", "unknown")
    parse_errors = collect_result.get("parse_errors", [])
    devices = collect_result.get("devices", [])
    diff_records = collect_result.get("diff_records", 0)

    stage1_table = Table(title=f"Snapshot: {snapshot_id}", box=box.ROUNDED)
    stage1_table.add_column("Metric", style="cyan")
    stage1_table.add_column("Value", style="green")
    stage1_table.add_row("Devices", str(len(devices)))
    stage1_table.add_row("Total parse errors", str(len(parse_errors)))
    stage1_table.add_row("Diff records", str(diff_records))
    console.print(stage1_table)

    # ── Stage 2: Repair queue ─────────────────────────────────────────────
    repair_queue_path = Path(CONFIG_DIR / "repair_queue.json")
    queue_entries: list[dict] = []
    if repair_queue_path.exists():
        try:
            with open(repair_queue_path, encoding="utf-8") as _f:
                _rq = json.load(_f)
            queue_entries = _rq.get("queue", [])
        except Exception as _rq_err:
            console.print(f"[yellow]⚠ Could not read repair_queue.json: {_rq_err}[/yellow]")

    wrap_p0 = [
        q
        for q in queue_entries
        if q.get("error_type") == "collection_wrap" and q.get("priority") == "P0_core"
    ]
    repair_p0 = [
        q
        for q in queue_entries
        if q.get("error_type") in ("textfsm_exception", "zero_rows_semantic")
        and q.get("priority") == "P0_core"
    ]
    deferred = [q for q in queue_entries if q.get("priority") in ("P1_important", "P2_optional")]

    if queue_entries:
        q_table = Table(title="Repair Queue Summary", box=box.ROUNDED)
        q_table.add_column("Type", style="cyan")
        q_table.add_column("Count", justify="right")
        q_table.add_row("collection_wrap (P0)", str(len(wrap_p0)))
        q_table.add_row("textfsm_exception / zero_rows (P0)", str(len(repair_p0)))
        q_table.add_row("P1 / P2 deferred", str(len(deferred)))
        console.print(q_table)
    else:
        console.print("[green]✅ Stage 2: No parse gaps detected.[/green]")

    # ── Stage 3a: collection_wrap P0 ─────────────────────────────────────
    if wrap_p0:
        console.rule("[bold yellow]Stage 3a: Collection Wrap Artifacts (P0)[/bold yellow]")
        console.print(
            f"[yellow]{len(wrap_p0)} command(s) detected with terminal line-wrapping[/yellow] "
            "— raw output is truncated, so TextFSM cannot parse it.\n"
            "[dim]Cause:[/dim] Juniper CLI terminal width not fully applied "
            "([bold]set cli screen-width 0[/bold] pre-command is deployed but "
            "may not take effect on all vJunos/EVE-NG sessions).\n"
            "[dim]Action:[/dim] LLM repair is [bold]skipped[/bold] for these "
            "(LLM cannot fix broken raw data). "
            "Run [bold]python olav-netops/scripts/netops_snapshot.py[/bold] to retry collection, or check "
            "SSH session setup for Juniper screen-width.\n"
        )
        for _entry in wrap_p0:
            console.print(
                f"  • [dim]{_entry['platform']}[/dim] / [cyan]{_entry['command']}[/cyan] "
                f"({', '.join(_entry.get('affected_devices', []))})"
            )

    # ── Stage 3b: LLM Auto-Repair P0 ─────────────────────────────────────
    gaps_fixed = 0
    gaps_remaining: list[dict] = []

    if repair_p0:
        console.rule(
            f"[bold yellow]Stage 3b: LLM Auto-Repair {len(repair_p0)} P0 Template Gaps[/bold yellow]"
        )
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(
                f"Repairing 0/{len(repair_p0)} P0 gaps...", total=len(repair_p0)
            )
            for i, gap in enumerate(repair_p0, 1):
                dev = gap.get("sample_device", "")
                cmd = gap.get("command", "")
                progress.update(
                    task,
                    description=f"Repairing {i}/{len(repair_p0)}: [cyan]{dev}[/cyan] / [dim]{cmd}[/dim]",
                )
                repair_result = repair_template.func(device=dev, command=cmd)
                if repair_result.get("success") and repair_result.get("records", 0) > 0:
                    gaps_fixed += 1
                    n_devs = len(gap.get("affected_devices", [dev]))
                    console.log(
                        f"  ✅ [green]{cmd}[/green] ({gap.get('platform')}) "
                        f"→ {repair_result['records']} records × {n_devs} device(s)"
                    )
                else:
                    gaps_remaining.append(gap)
                    console.log(
                        f"  ❌ [red]{cmd}[/red] — {repair_result.get('error', 'unknown error')}"
                    )
                progress.advance(task)
    else:
        console.print("[green]✅ Stage 3b: No P0 template gaps to repair.[/green]")

    if deferred:
        console.print(
            f"\n[dim]ℹ {len(deferred)} P1/P2 gap(s) deferred — run "
            "[bold]python olav-netops/scripts/netops_snapshot.py --repair[/bold] to fix optionally.[/dim]"
        )

    # ── Stage 3c: Discovery commands check ───────────────────────────────
    discovery_critical = {
        "show cdp neighbors",
        "show cdp neighbors detail",
        "show lldp neighbors",
        "show lldp neighbors detail",
        "show bgp summary",
        "show bgp all summary",
        "show ip ospf neighbors",
        "show ospf neighbors",
    }

    discovery_p0 = [
        q
        for q in gaps_remaining
        if q.get("command", "").lower() in discovery_critical and q.get("priority") == "P0_core"
    ]

    if discovery_p0:
        console.rule("[bold yellow]⚠️  Stage 3c: Discovery Commands Still Failing[/bold yellow]")
        console.print(
            f"\n[yellow]{len(discovery_p0)} critical discovery command(s) not parsed:[/yellow]\n"
            "These commands are essential for generating network topology (CDP/LLDP/BGP/OSPF).\n"
            "Without them, topology will be incomplete or inaccurate.\n"
        )
        for _gap in discovery_p0:
            console.print(
                f"  • [cyan]{_gap.get('platform', '?')}[/cyan] / {_gap.get('command', '?')}"
            )

        console.print(
            "\n[dim]TextFSM problem details: View[/dim] [bold]" + str(repair_queue_path) + "[/bold]"
        )

        console.print("\n[bold]What would you like to do?[/bold]")
        try:
            if sys.stdin.isatty():
                choice = Confirm.ask(
                    "[A] Continue topology generation (data may be incomplete) or "
                    "[B] Pause & fix manually (recommended)",
                    default=False,
                    console=console,
                )
                use_option_b = choice is False
            else:
                use_option_b = False
        except (OSError, EOFError):
            use_option_b = False

        if use_option_b:
            console.print(
                "\n[yellow]⏸️  Onboarding paused for manual repair.[/yellow]\n"
                "[bold]Next steps:[/bold]\n"
                "  1. Review TextFSM issues: [bold]cat " + str(repair_queue_path) + "[/bold]\n"
                "  2. Fix SSH/device config (check Juniper screen-width, timeout, etc.)\n"
                "  3. Re-collect from problem devices:\n"
                "     [bold]uv run olav --agent config \"Call collect_commands(devices=['R1','R2'])\""
                "[/bold]\n"
                "  4. Or manually fix templates in: [bold].olav/templates/[/bold]\n"
                "  5. Re-parse with fixed templates:\n"
                '     [bold]uv run olav --agent config "Call reparse_outputs('
                "platform='juniper_junos', command='show cdp neighbors')\""
                "[/bold]\n"
                "  6. Then resume: [bold]python olav-netops/scripts/netops_init.py[/bold]\n"
            )
            return 0
        else:
            console.print(
                "[yellow]⚠️  Proceeding with incomplete discovery data — "
                "topology may have gaps.[/yellow]\n"
            )

    # ── Stage 4: Topology ─────────────────────────────────────────────────
    console.rule("[bold cyan]Stage 4: Generate Topology[/bold cyan]")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Building topology from CDP/LLDP/OSPF...", total=None)
        topo_result = run_topology_sandbox.func(snapshot_id=snapshot_id)
        topo_links = topo_result.get("edge_count", 0) if isinstance(topo_result, dict) else 0
        progress.update(
            task,
            description=f"✅ {topo_links} topology edges built",
            completed=True,
        )

    # ── Final summary ──────────────────────────────────────────────────────
    final_table = Table(title="🎉 Onboarding Complete", box=box.DOUBLE_EDGE)
    final_table.add_column("Stage", style="bold cyan")
    final_table.add_column("Result", style="green")
    final_table.add_row("Snapshot ID", snapshot_id)
    final_table.add_row("Devices collected", str(len(devices)))
    final_table.add_row("Diff records", str(diff_records))
    final_table.add_row("Total parse gaps", str(len(queue_entries)))
    final_table.add_row("Wrap artifacts (P0)", str(len(wrap_p0)))
    final_table.add_row("P0 gaps auto-fixed", str(gaps_fixed))
    final_table.add_row("P0 gaps remaining", str(len(gaps_remaining)))
    final_table.add_row("Topology edges", str(topo_links))
    console.print(final_table)

    if gaps_remaining:
        console.print(f"\n[yellow]⚠ {len(gaps_remaining)} P0 gaps not repaired:[/yellow]")
        for _gap in gaps_remaining:
            console.print(f"  • {_gap.get('platform', '?')} / {_gap.get('command', '?')}")

    # ── Stage 5: Register trace_learner cron ──────────────────────────────
    console.rule("[bold cyan]Stage 5: Register trace_learner cron[/bold cyan]")
    try:
        cron_result = _register_trace_learner_cron(project_root=_PROJECT_ROOT)
        if cron_result["status"] == "registered":
            console.print(
                f"  [green]✓[/green] Daily trace_learner cron registered "
                f"→ {cron_result['cron_file']}"
            )
        elif cron_result["status"] == "already_registered":
            console.print("  [dim]ℹ trace_learner cron already registered — skipped.[/dim]")
    except Exception as _cron_err:
        console.print(
            f"  [yellow]⚠ Could not register trace_learner cron (non-blocking): "
            f"{_cron_err}[/yellow]"
        )

    return 0


# ---------------------------------------------------------------------------
# Script entry point
# ---------------------------------------------------------------------------


def main(args: str = "") -> str:
    """Slash-command entry point for /netops_init.

    Accepts an optional args string (e.g. "--dry-run") and runs the
    netops init pipeline synchronously, returning a summary string.
    """
    dry_run = "--dry-run" in args
    rc = run_init(dry_run=dry_run)
    if rc == 0:
        return "✅ netops_init completed successfully."
    return f"❌ netops_init exited with code {rc}."


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="netops_init.py",
        description="OLAV NetOps onboarding — Stage 1-5 pipeline",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify environment only, do not run collection",
    )
    _args = parser.parse_args()

    sys.exit(run_init(dry_run=_args.dry_run))
