"""trace_review.py — /trace-review slash command business logic.

Extracted from cli/main.py so it can be unit-tested without the package's
relative-import chain.

Entry point used by main.py interactive loop:

    from olav.cli.commands.trace_review import _handle_trace_review, print_trace_review
    result = _handle_trace_review(hours=168, limit=50)
    print_trace_review(result, console)
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_default_audit_db() -> Path:
    try:
        from olav.core.config import DATABASES_DIR

        return DATABASES_DIR / "audit.duckdb"
    except Exception:
        return Path.cwd() / ".olav" / "databases" / "audit.duckdb"


def _handle_trace_review_propose(
    hours: int = 24,
    limit: int = 50,
    db_path: Path | None = None,
    llm=None,
    drafts_dir: Path | None = None,
) -> dict:
    """HITL trace review (dev_docs/97 §5): propose per-agent lesson DRAFTS, no commit.

    Real entry point behind ``olav trace-review --propose`` (cron-friendly) and
    the ``/trace-review propose`` slash command. Drafts land in the memory-curator
    drafts dir for human review + ``commit_to_memory(from_draft=True)``.
    """
    db_path = db_path or _get_default_audit_db()
    try:
        from olav.core.curator.trace_learner import _run_review_cycle

        return _run_review_cycle(
            hours=hours, limit=limit, db_path=db_path, llm=llm, drafts_dir=drafts_dir
        )
    except Exception as exc:
        logger.exception("_handle_trace_review_propose error")
        return {"status": "error", "message": str(exc)}


def _handle_trace_review(
    hours: int = 168,
    limit: int = 50,
    db_path: Path | None = None,
    llm=None,
    store=None,
) -> dict:
    """Run the full trace-learn cycle and return structured results.

    This is the pure-logic function behind the ``/trace-review`` slash command.
    All dependencies (db_path, llm, store) are injectable for TDD.

    Args:
        hours:   Look-back window in hours (default 168 = 7 days).
        limit:   Max failed runs to process (default 50).
        db_path: audit.duckdb path override (uses config default when None).
        llm:     LangChain chat model override (lazy-loaded when None).
        store:   LanceDBStore override (lazy-loaded when None).

    Returns:
        dict — same shape as ``_run_learn_cycle`` output:
        ``{status, total_failures, total_ok, failures, window_hours,
           constraints_extracted, learn_count}``
    """
    db_path = db_path or _get_default_audit_db()

    try:
        from olav.core.curator.trace_learner import _run_learn_cycle
        return _run_learn_cycle(
            hours=hours,
            limit=limit,
            db_path=db_path,
            store=store,
            llm=llm,
        )
    except Exception as exc:
        logger.exception("_handle_trace_review error")
        return {"status": "error", "message": str(exc)}


def print_trace_review(result: dict, console=None) -> None:
    """Render a /trace-review result to the Rich console.

    Args:
        result:  Return value of _handle_trace_review().
        console: Rich Console instance (creates one if None).
    """
    from rich import box
    from rich.console import Console
    from rich.table import Table

    con = console or Console()

    if result.get("status") == "error":
        con.print(f"\n[red]✗ trace-review failed:[/red] {result.get('message', 'unknown error')}")
        return

    total_f = result.get("total_failures", 0)
    total_ok = result.get("total_ok", 0)
    learn = result.get("learn_count", 0)
    window = result.get("window_hours", 168)
    constraints = result.get("constraints_extracted", [])

    summary = Table(title=f"Trace Review — last {window}h", box=box.ROUNDED)
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", justify="right")
    summary.add_row("Completed runs", str(total_ok))
    summary.add_row("Failed / cancelled runs", str(total_f))
    summary.add_row("Constraints learned", str(learn))
    con.print(summary)

    if constraints:
        con.print("\n[bold]Extracted constraints (written to LanceDB memory):[/bold]")
        for i, c in enumerate(constraints, 1):
            con.print(f"  {i}. {c}")
    elif total_f == 0:
        con.print("\n[green]✓ No failures in the review window — nothing to learn.[/green]")
    else:
        con.print("\n[yellow]ℹ Failures found but no constraints extracted.[/yellow]")


def print_trace_review_propose(result: dict, console=None) -> None:
    """Render a propose-mode (HITL) trace-review result."""
    from rich.console import Console

    con = console or Console()
    if result.get("status") == "error":
        con.print(f"\n[red]✗ trace-review --propose failed:[/red] {result.get('message', 'unknown')}")
        return
    proposals = result.get("proposals", [])
    tf = result.get("total_failures", 0)
    window = result.get("window_hours", 24)
    if not proposals:
        if tf == 0:
            con.print(f"\n[green]✓ No failures in last {window}h — nothing to propose.[/green]")
        else:
            con.print(f"\n[yellow]ℹ {tf} failures but no lessons extracted.[/yellow]")
        return
    con.print(
        f"\n[bold]Trace review (last {window}h): {result.get('drafts_written', 0)} "
        f"lesson draft(s) proposed for review — NOT committed.[/bold]"
    )
    for p in proposals:
        con.print(
            f"  • [cyan]{p['agent']}[/cyan] → {p['constraint_count']} lesson(s) "
            f"→ {p['draft_path']}"
        )
    con.print(
        "\n[dim]Review a draft, then commit it via memory-curator "
        "(commit_to_memory from_draft=True intent=trace_lessons_<agent>).[/dim]"
    )


def handle_trace_review_command(args: argparse.Namespace) -> int:
    """``olav trace-review`` CLI verb — cron-friendly, non-interactive.

    Default (and ``--propose``) runs the HITL propose path (drafts, no commit),
    which is the safe default for scheduled runs. ``--learn`` runs the legacy
    auto-commit reflection cycle.
    """
    hours = getattr(args, "hours", None)
    limit = getattr(args, "limit", 50)
    learn = getattr(args, "learn", False)

    if learn:
        result = _handle_trace_review(hours=hours or 168, limit=limit)
        print_trace_review(result)
    else:
        result = _handle_trace_review_propose(hours=hours or 24, limit=limit)
        print_trace_review_propose(result)
    return 0 if result.get("status") != "error" else 1


def build_trace_review_parser(subparsers) -> argparse.ArgumentParser:
    """Register ``olav trace-review`` on the root CLI subparsers."""
    p = subparsers.add_parser(
        "trace-review",
        help="L4 self-improvement: review recent failures → propose lesson drafts (HITL)",
        description=(
            "Scheduled (cron-friendly) trace review. Reads recent failed runs "
            "from audit.duckdb, extracts per-agent operational lessons, and writes "
            "them as DRAFTS to the memory-curator drafts dir for human review — it "
            "does NOT auto-commit. Use --learn for the legacy auto-commit reflection "
            "cycle (global scope). dev_docs/97 §5."
        ),
    )
    p.add_argument("--hours", type=int, default=None, help="Look-back window (propose default 24, learn default 168)")
    p.add_argument("--limit", type=int, default=50, help="Max failed runs to process (default 50)")
    p.add_argument("--propose", action="store_true", help="HITL propose drafts (default behaviour)")
    p.add_argument("--learn", action="store_true", help="Legacy: auto-commit reflection constraints (no HITL)")
    return p
