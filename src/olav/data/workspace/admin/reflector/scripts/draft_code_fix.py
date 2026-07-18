#!/usr/bin/env python3
"""draft_code_fix — write a code-fix PROPOSAL for human review (no git ops).

The "code" lane of the reflector agent. When an error signature points at a
real code defect (not something a KB guide can steer around), the reflector
does NOT touch source. It writes a proposal a human can act on:

  * ``exports/reflections/<date>-<slug>.md`` — root cause, the evidence
    (error signature + count from the daily scan), the affected file(s), and a
    concrete suggested fix.
  * optionally ``exports/reflections/<date>-<slug>.patch`` — a best-effort
    unified diff, IF the agent produced one. Small models don't reliably write
    correct patches, so the diff is a starting point, never auto-applied.

Nothing is committed, pushed, or written to source. A human reads the proposal
and implements/merges it. This is the deliberate, safe form of "local PR".
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_SLUG = re.compile(r"[^a-z0-9]+")


def _slugify(s: str) -> str:
    return _SLUG.sub("-", s.lower()).strip("-")[:50] or "proposal"


def draft_code_fix(
    title: str,
    root_cause: str,
    suggested_fix: str,
    affected_files: list[str] | str | None = None,
    evidence: str = "",
    severity: str = "medium",
    patch: str | None = None,
) -> dict[str, Any]:
    """Write a code-fix proposal (+ optional patch) under exports/reflections/.

    Args:
        title:          one-line summary of the defect.
        root_cause:     why it happens (grounded in the error evidence).
        suggested_fix:  the concrete change to make.
        affected_files: file path(s) the fix touches.
        evidence:       the error signature + count from scan_error_signatures.
        severity:       low / medium / high.
        patch:          optional best-effort unified diff.

    Returns:
        ``{"status", "report_path", "patch_path"}``.
    """
    title = (title or "").strip()
    if not title or not root_cause.strip() or not suggested_fix.strip():
        return {"status": "error",
                "message": "title, root_cause and suggested_fix are required"}
    if isinstance(affected_files, str):
        affected_files = [affected_files]
    affected_files = [f for f in (affected_files or []) if f]

    try:
        from olav.core.config import get_paths_config
        root = get_paths_config().project_root
    except Exception:  # noqa: BLE001
        root = Path.cwd()
    out_dir = Path(root) / "exports" / "reflections"
    out_dir.mkdir(parents=True, exist_ok=True)

    date = datetime.now().strftime("%Y-%m-%d")
    slug = _slugify(title)
    base = f"{date}-{slug}"

    report = (
        f"# Code-fix proposal: {title}\n\n"
        f"_Auto-drafted by admin/reflector on {date}. NOT applied — human review._\n\n"
        f"- **Severity**: {severity}\n"
        f"- **Affected files**: {', '.join(f'`{f}`' for f in affected_files) or '(unspecified)'}\n\n"
        f"## Evidence\n\n{evidence or '(from the daily error scan)'}\n\n"
        f"## Root cause\n\n{root_cause.strip()}\n\n"
        f"## Suggested fix\n\n{suggested_fix.strip()}\n"
    )
    report_path = out_dir / f"{base}.md"
    report_path.write_text(report, encoding="utf-8")

    patch_path = None
    if patch and patch.strip():
        report += "\n## Draft patch (best-effort — verify before applying)\n\n```diff\n" \
            + patch.strip() + "\n```\n"
        report_path.write_text(report, encoding="utf-8")
        pp = out_dir / f"{base}.patch"
        pp.write_text(patch.strip() + "\n", encoding="utf-8")
        patch_path = str(pp)

    return {
        "status": "ok",
        "report_path": str(report_path),
        "patch_path": patch_path,
        "note": "proposal written; nothing applied to source. Human reviews "
                + str(report_path) + (f" + applies {patch_path}" if patch_path else ""),
    }


if __name__ == "__main__":
    args = json.loads(sys.stdin.read() or "{}")
    print(json.dumps(draft_code_fix(**args), default=str))
