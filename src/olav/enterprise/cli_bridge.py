from __future__ import annotations

import json as _json
import os as _os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

    from rich.console import Console

SUPPORTED_FORMATS: tuple[str, ...] = ("sft", "trajectory", "atif", "grant-local-train")


def dispatch_log_export(export_fmt: str, args: argparse.Namespace, console: Console) -> None:
    if export_fmt == "sft":
        from olav.enterprise.audit_dataset_export import audit_to_sft_jsonl

        hours = getattr(args, "hours", 24)
        output_dir = getattr(args, "output", None)
        min_score = getattr(args, "min_score", 0.0)
        encrypt_flag = getattr(args, "encrypt", None)
        key_ref = getattr(args, "key_ref", None)
        result = audit_to_sft_jsonl(
            conn_or_path=None,
            output_dir=output_dir,
            hours=hours,
            min_rule_score=min_score,
            encrypt=encrypt_flag,
            key_ref=key_ref,
        )
        console.print(f"[bold green]✓[/bold green] SFT export complete → {result['output_dir']}")
        console.print(f"  Runs scanned: {result.get('runs_scanned', 0)}")
        console.print(f"  Conversations exported: {result.get('conversations_exported', 0)}")
        console.print(f"  Runs rejected: {result.get('runs_rejected', 0)}")

    elif export_fmt == "trajectory":
        from olav.enterprise.audit_dataset_export import audit_to_tool_trajectory

        hours = getattr(args, "hours", 24)
        output_dir = getattr(args, "output", None)
        min_score = getattr(args, "min_score", 0.0)
        encrypt_flag = getattr(args, "encrypt", None)
        key_ref = getattr(args, "key_ref", None)
        result = audit_to_tool_trajectory(
            conn_or_path=None,
            output_dir=output_dir or "exports/audit_datasets/default",
            hours=hours,
            min_rule_score=min_score,
            encrypt=encrypt_flag,
            key_ref=key_ref,
        )
        console.print("[bold green]✓[/bold green] Trajectory export complete")
        console.print(f"  Runs scanned: {result.get('runs_scanned', 0)}")
        console.print(f"  Samples exported: {result.get('runs_exported', 0)}")
        console.print(f"  Runs rejected: {result.get('runs_rejected', 0)}")
        console.print(f"  Runs deduped: {result.get('runs_deduped', 0)}")

    elif export_fmt == "atif":
        from olav.enterprise.audit_dataset_export import audit_to_atif

        hours = getattr(args, "hours", 24)
        output_dir = getattr(args, "output", None)
        encrypt_flag = getattr(args, "encrypt", None)
        key_ref = getattr(args, "key_ref", None)
        result = audit_to_atif(
            conn_or_path=None,
            output_dir=output_dir or "exports/audit_datasets/default",
            hours=hours,
            encrypt=encrypt_flag,
            key_ref=key_ref,
        )
        console.print("[bold green]✓[/bold green] ATIF export complete")
        console.print(f"  Runs scanned: {result.get('runs_scanned', 0)}")
        console.print(f"  Samples exported: {result.get('runs_exported', 0)}")
        console.print(f"  Runs rejected: {result.get('runs_rejected', 0)}")

    elif export_fmt == "grant-local-train":
        from olav.enterprise.dataset_encryption import OneTimeTokenManager

        export_id = getattr(args, "export_id", None)
        ttl = getattr(args, "ttl_minutes", 10)
        user_id = _os.environ.get("OLAV_USER", "unknown")
        secret = _os.environ.get("OLAV_TOKEN_SECRET", "olav-dev-secret-change-in-prod")
        mgr = OneTimeTokenManager(secret=secret)
        token_result = mgr.issue(export_id=export_id, user_id=user_id, ttl_minutes=ttl)
        console.print(_json.dumps(token_result, indent=2))

    else:
        console.print(
            "[yellow]Usage: olav log export <sft|trajectory|atif|grant-local-train> "
            "[--hours N] [--output DIR][/yellow]"
        )
