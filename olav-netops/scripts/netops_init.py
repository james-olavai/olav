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
_DEFAULT_CRON_SCHEDULE = "0 3 * * *"


def _load_cron_schedule() -> str:
    """Load cron schedule from config YAML, with hardcoded fallback."""
    try:
        import yaml

        try:
            from olav.core.config import get_domain_config_dir

            domain_dir = get_domain_config_dir("netops")
        except (ImportError, AttributeError):
            domain_dir = _PROJECT_ROOT / ".olav" / "config" / "domains" / "netops"

        schedules_path = Path(domain_dir) / "cron_schedules.yaml" if domain_dir else None
        if schedules_path and schedules_path.exists():
            data = yaml.safe_load(schedules_path.read_text(encoding="utf-8")) or {}
            return data.get("schedules", {}).get("trace_learner", {}).get("cron", _DEFAULT_CRON_SCHEDULE)
    except (ImportError, OSError, KeyError, TypeError) as e:
        logger.debug("Could not load cron_schedules.yaml, using default: %s", e)
    return _DEFAULT_CRON_SCHEDULE


def _register_trace_learner_cron(
    project_root: Path,
    cron_file: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Register a daily cron job that runs trace_learner.

    Uses ``fcntl.flock(LOCK_EX)`` to make the read-check-write sequence atomic,
    preventing duplicate entries when called concurrently (e.g., two parallel
    ``netops_init`` runs or a systemd unit + manual invocation).
    """
    import fcntl

    cron_schedule = _load_cron_schedule()
    cron_line = (
        f"{_CRON_COMMENT}\n"
        f"{cron_schedule}  cd {project_root} && uv run olav --agent config "
        f'"run trace_learner()"\n'
    )

    if dry_run:
        return {"status": "dry_run", "cron_line": cron_line.strip()}

    if cron_file is None:
        cron_file = Path.home() / ".olav" / "cron.tab"

    cron_file.parent.mkdir(parents=True, exist_ok=True)

    # Atomic read-check-write via exclusive file lock
    with open(cron_file, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            existing = f.read()
            if _CRON_MARKER in existing:
                return {"status": "already_registered", "cron_file": str(cron_file)}
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(cron_line)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

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
        issues.append(".olav/workspace/ not found — run `olav init` first")

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

    console.print(
        Panel.fit(
            "[bold green]✅ Environment verified[/bold green]\n\n"
            "Launching SSH collection pipeline...",
            border_style="green",
        )
    )

    # ── Pipeline: delegate to run.py (the authoritative nornir implementation) ──
    # run.py lives in the workspace alongside agent tools and contains the full
    # SSH collect → TextFSM parse → IngestManager → topology ETL pipeline.
    _run_py = _SCRIPT_DIR.parent / ".olav" / "workspace" / "ops" / "netops_init" / "run.py"
    if not _run_py.exists():
        console.print(f"[red]❌ Pipeline script not found: {_run_py}[/red]")
        return 1

    import importlib.util as _ilu

    _spec = _ilu.spec_from_file_location("_netops_run", str(_run_py))
    _mod = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
    _spec.loader.exec_module(_mod)  # type: ignore[union-attr]

    console.rule("[bold cyan]Stage 1: Loading Device Inventory[/bold cyan]")
    try:
        _devices = _mod._load_devices()
        console.print(f"  ✓ {len(_devices)} device(s): {', '.join(_devices)}")
    except Exception as _inv_err:
        console.print(f"[red]❌ Could not load device inventory: {_inv_err}[/red]")
        return 1

    if dry_run:
        console.print("\n[green]✅ Dry run complete — environment looks good.[/green]")
        console.print("[dim]Re-run without --dry-run to execute the full pipeline.[/dim]")
        return 0

    console.rule("[bold cyan]Stage 2: SSH Collection (platform-aware)[/bold cyan]")
    try:
        _result = _mod._run_collection(_devices, None)
    except Exception as _coll_err:
        console.print(f"[red]❌ SSH collection failed: {_coll_err}[/red]")
        return 1

    _snap_id   = _result.get("snapshot_id", "unknown")
    _n_devices = _result.get("devices", 0)
    _n_success = _result.get("successful", 0)
    _n_failed  = _result.get("failed", 0)

    final_table = Table(title="🎉 Onboarding Complete", box=box.DOUBLE_EDGE)
    final_table.add_column("Stage", style="bold cyan")
    final_table.add_column("Result", style="green")
    final_table.add_row("Snapshot ID", _snap_id)
    final_table.add_row("Devices", str(_n_devices))
    final_table.add_row("Successful", str(_n_success))
    final_table.add_row("Failed", str(_n_failed))
    console.print(final_table)

    if _n_failed > 0:
        console.print(
            f"\n[yellow]⚠ {_n_failed} collection failure(s) — "
            "check credentials in hosts.yaml / defaults.yaml[/yellow]"
        )
        for _r in _result.get("results", []):
            if _r.get("status") == "failed":
                console.print(
                    f"  • {_r['device']} / {_r['command']}: "
                    f"{str(_r.get('error', 'unknown'))[:80]}"
                )

    # ── Stage 3: Register cron ────────────────────────────────────────────
    console.rule("[bold cyan]Stage 3: Register Cron[/bold cyan]")
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

    console.print(
        f"\n[bold green]✅ Network initialization complete[/bold green] — "
        f"DB populated (snapshot: {_snap_id}), "
        f"Failed: {_n_failed}"
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
