"""trace_review.py — /trace-review slash command business logic.

Extracted from cli/main.py so it can be unit-tested without the package's
relative-import chain.

Entry point used by main.py interactive loop:

    from olav.cli.commands.trace_review import _handle_trace_review, print_trace_review
    result = _handle_trace_review(hours=168, limit=50)
    print_trace_review(result, console)
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_default_audit_db() -> Path:
    try:
        from olav.core.config import DATABASES_DIR

        return DATABASES_DIR / "audit.duckdb"
    except Exception:
        return Path.cwd() / ".olav" / "databases" / "audit.duckdb"


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
