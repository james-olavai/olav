#!/usr/bin/env python3
"""sync_netops_workspace.py — mirror the vendored netops workspace.

Both ``.olav/workspace/ops/`` (platform-vendored copy, fast dev loop)
and ``olav-netops/.olav/workspace/ops/`` (authoritative source for the
olav-netops package) must stay in sync; the SSOT guard at
``tests/governance/test_workspace_ops_ssot.py`` fails CI when metadata
drifts between the two.

The platform copy is marked ``transitional`` in
``ownership_manifest.yaml`` (rule line 446-452) and exists purely so
the root dev loop can iterate on netops tools without ``pip install
-e olav-netops/`` round-trips.  Once you've finished editing in the
root copy, run this script to push every change over to the
authoritative ``olav-netops/`` tree.

Default direction: **root → olav-netops** ("把改动覆盖到 olav-netops").
Use ``--reverse`` to pull the other way.

Example
-------
::

    # Preview what would change, no writes
    uv run python scripts/sync_netops_workspace.py --dry-run

    # Push everything from root to olav-netops, overwriting
    uv run python scripts/sync_netops_workspace.py

    # Reverse: copy olav-netops → root (e.g. after pulling upstream)
    uv run python scripts/sync_netops_workspace.py --reverse

    # Restrict to metadata only (matches the SSOT drift guard's scope)
    uv run python scripts/sync_netops_workspace.py --metadata-only

Exit codes
----------
* 0 — no diff (or dry-run found no changes)
* 0 — wrote N files (default)
* 1 — write error / missing source dir
* 2 — `--check` mode found drift (used in CI)
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROOT_OPS = REPO / ".olav" / "workspace" / "ops"
NETOPS_OPS = REPO / "olav-netops" / ".olav" / "workspace" / "ops"

# Filenames / dir parts that should never be copied either way —
# they're tooling artefacts, not workspace content.
_SKIP_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache"}
_SKIP_SUFFIXES = {".pyc", ".pyo"}

# Metadata = drift-guarded files (also the set the SSOT test enforces).
_METADATA_SUFFIXES = {".md", ".yaml", ".yml"}


@dataclass
class SyncReport:
    """Aggregated stats for the human summary at the end."""

    direction: str
    src: Path
    dst: Path
    copied: list[Path] = field(default_factory=list)
    new: list[Path] = field(default_factory=list)
    unchanged: int = 0
    skipped: list[Path] = field(default_factory=list)
    errors: list[tuple[Path, Exception]] = field(default_factory=list)

    @property
    def changed(self) -> int:
        return len(self.copied) + len(self.new)


def _is_skipped(path: Path) -> bool:
    """Filter directories/files we never sync (build artefacts)."""
    if any(part in _SKIP_PARTS for part in path.parts):
        return True
    if path.suffix in _SKIP_SUFFIXES:
        return True
    return False


def _walk(src: Path, *, metadata_only: bool) -> list[Path]:
    """Yield every relative file path under *src* that we'd consider syncing."""
    out: list[Path] = []
    if not src.exists():
        return out
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        if _is_skipped(rel):
            continue
        if metadata_only and p.suffix not in _METADATA_SUFFIXES:
            continue
        out.append(rel)
    return out


def _sync_one(
    rel: Path,
    src_root: Path,
    dst_root: Path,
    *,
    dry_run: bool,
    report: SyncReport,
) -> None:
    """Copy a single file from ``src_root/rel`` to ``dst_root/rel``."""
    src = src_root / rel
    dst = dst_root / rel

    if dst.exists() and filecmp.cmp(src, dst, shallow=False):
        report.unchanged += 1
        return

    is_new = not dst.exists()
    if dry_run:
        (report.new if is_new else report.copied).append(rel)
        return

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    except OSError as exc:
        report.errors.append((rel, exc))
        return

    (report.new if is_new else report.copied).append(rel)


def _sync_deletes(
    src_root: Path,
    dst_root: Path,
    src_files: set[Path],
    *,
    metadata_only: bool,
    dry_run: bool,
    report: SyncReport,
) -> list[Path]:
    """Find files present only on the destination side; report (and
    optionally remove) them so the two trees converge.

    Returns the list of relative paths that are dst-only (pre-deletion).
    """
    dst_files = set(_walk(dst_root, metadata_only=metadata_only))
    extras = sorted(dst_files - src_files)
    if not extras:
        return []

    # We don't auto-delete by default — surprise removals are too easy
    # to ship by accident.  Surface them so the user can decide.
    return extras


def sync(
    *,
    reverse: bool,
    metadata_only: bool,
    dry_run: bool,
    delete_extras: bool,
) -> SyncReport:
    """Run the sync end-to-end and return a populated :class:`SyncReport`."""
    src_root, dst_root = (NETOPS_OPS, ROOT_OPS) if reverse else (ROOT_OPS, NETOPS_OPS)
    direction = (
        f"olav-netops/.olav/workspace/ops/  →  .olav/workspace/ops/"
        if reverse
        else f".olav/workspace/ops/  →  olav-netops/.olav/workspace/ops/"
    )

    report = SyncReport(direction=direction, src=src_root, dst=dst_root)

    if not src_root.exists():
        print(f"ERROR: source path missing: {src_root}", file=sys.stderr)
        raise SystemExit(1)

    src_files = _walk(src_root, metadata_only=metadata_only)
    for rel in src_files:
        _sync_one(
            rel,
            src_root,
            dst_root,
            dry_run=dry_run,
            report=report,
        )

    extras = _sync_deletes(
        src_root,
        dst_root,
        set(src_files),
        metadata_only=metadata_only,
        dry_run=dry_run,
        report=report,
    )
    if extras:
        if delete_extras and not dry_run:
            for rel in extras:
                try:
                    (dst_root / rel).unlink()
                    report.copied.append(Path(f"DELETE {rel}"))
                except OSError as exc:
                    report.errors.append((rel, exc))
        else:
            for rel in extras:
                report.skipped.append(rel)

    return report


def _print_report(report: SyncReport, *, dry_run: bool, check_mode: bool) -> int:
    print(f"Direction:  {report.direction}")
    print(f"Source:     {report.src}")
    print(f"Destination:{report.dst}")
    print()

    label = "WOULD update" if dry_run else "Updated"
    if report.copied:
        print(f"{label} ({len(report.copied)}):")
        for rel in report.copied:
            print(f"  ~ {rel}")
    if report.new:
        new_label = "WOULD create" if dry_run else "Created"
        print(f"{new_label} ({len(report.new)}):")
        for rel in report.new:
            print(f"  + {rel}")
    if report.skipped:
        print(
            f"Destination-only files ({len(report.skipped)}) — "
            "left alone (use --delete-extras to remove):"
        )
        for rel in report.skipped:
            print(f"  ! {rel}")
    if report.errors:
        print(f"Errors ({len(report.errors)}):", file=sys.stderr)
        for rel, exc in report.errors:
            print(f"  x {rel}: {exc}", file=sys.stderr)

    print()
    print(f"Summary:  changed={report.changed}  unchanged={report.unchanged}  "
          f"dst-only={len(report.skipped)}  errors={len(report.errors)}")

    if report.errors:
        return 1
    if check_mode and (report.changed or report.skipped):
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sync the platform-vendored netops workspace at "
            ".olav/workspace/ops/ with the authoritative source at "
            "olav-netops/.olav/workspace/ops/.  Default direction: "
            "root → olav-netops (push your local edits out)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Sync olav-netops → root instead of root → olav-netops.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing.",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help=(
            "Only sync metadata (.md/.yaml/.yml) — the same scope the "
            "SSOT drift guard enforces.  Skip tool source code."
        ),
    )
    parser.add_argument(
        "--delete-extras",
        action="store_true",
        help=(
            "Also delete files that exist on the destination but not "
            "on the source.  Off by default to prevent accidental "
            "removal — review the reported 'destination-only' list "
            "before enabling."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "CI mode: exit 2 if any divergence is found.  Implies "
            "--dry-run.  Useful as a pre-commit / lint check."
        ),
    )
    args = parser.parse_args(argv)

    dry_run = args.dry_run or args.check

    report = sync(
        reverse=args.reverse,
        metadata_only=args.metadata_only,
        dry_run=dry_run,
        delete_extras=args.delete_extras,
    )
    return _print_report(report, dry_run=dry_run, check_mode=args.check)


if __name__ == "__main__":
    sys.exit(main())
