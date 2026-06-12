#!/usr/bin/env python3
"""scan_ownership.py — Walk repo and validate paths against ownership_manifest.yaml.

Output:
  OK    — path matches an authoritative or generated rule
  WARN  — path matches a transitional/externalized rule, or is generated
  ERROR — path matches misplaced, or no rule matched at all

Usage:
    python scripts/scan_ownership.py                  # default: repo root
    python scripts/scan_ownership.py --summary        # counts only
    python scripts/scan_ownership.py --errors-only    # show only WARN + ERROR
"""
from __future__ import annotations

import argparse
import fnmatch
import sys
from collections import Counter
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "node_modules",
    ".agent",
    ".olav/databases",
    ".olav/logs",
}

SKIP_FILES = {
    ".coverage",
}


def load_manifest(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def collect_paths(root: Path) -> list[str]:
    """Collect all file paths relative to repo root, skipping ephemeral dirs."""
    paths: list[str] = []
    for item in sorted(root.rglob("*")):
        rel = item.relative_to(root)
        parts = rel.parts

        # skip hidden/ephemeral dirs (check both individual parts and joined prefixes)
        rel_str = str(rel)
        if any(p in SKIP_DIRS for p in parts) or any(rel_str.startswith(sd) for sd in SKIP_DIRS):
            continue

        # only files
        if not item.is_file():
            continue

        paths.append(str(rel))
    return paths


def match_rules(rel_path: str, rules: list[dict]) -> dict | None:
    """Last-match-wins against rule patterns."""
    matched = None
    for rule in rules:
        pattern = rule["pattern"]
        if fnmatch.fnmatch(rel_path, pattern):
            matched = rule
    return matched


def classify(rule: dict | None, default_owner: str) -> tuple[str, str, str, str]:
    """Return (level, owner, cls, status)."""
    if rule is None:
        return ("ERROR", default_owner, "unknown", "unmatched")

    status = rule.get("status", "unknown")
    owner = rule.get("owner", default_owner)
    cls = rule.get("class", "unknown")

    if status == "authoritative":
        return ("OK", owner, cls, status)
    elif status == "generated":
        return ("OK", owner, cls, status)
    elif status in ("transitional", "externalized"):
        return ("WARN", owner, cls, status)
    elif status == "misplaced":
        return ("ERROR", owner, cls, status)
    else:
        return ("ERROR", owner, cls, status)


def main():
    parser = argparse.ArgumentParser(description="Scan repo against ownership manifest")
    parser.add_argument("--summary", action="store_true", help="Show counts only")
    parser.add_argument("--errors-only", action="store_true", help="Show WARN + ERROR only")
    args = parser.parse_args()

    manifest_path = REPO_ROOT / "ownership_manifest.yaml"
    if not manifest_path.exists():
        print(f"ERROR: {manifest_path} not found", file=sys.stderr)
        sys.exit(1)

    manifest = load_manifest(manifest_path)
    rules = manifest.get("rules", [])
    default_owner = manifest.get("default_owner", "unknown")

    paths = collect_paths(REPO_ROOT)
    counts: Counter = Counter()
    lines: list[str] = []

    for rel_path in paths:
        rule = match_rules(rel_path, rules)
        level, owner, cls, status = classify(rule, default_owner)
        counts[level] += 1

        target = ""
        if rule and rule.get("target_repo"):
            target = f" -> {rule['target_repo']}"

        line = f"  {level:<5}  {owner:<14} {cls:<20} {status:<14} {rel_path}{target}"

        if args.errors_only and level == "OK":
            continue
        lines.append(line)

    # Print results
    if not args.summary:
        for line in lines:
            print(line)

    # Summary
    total = sum(counts.values())
    print()
    print("=" * 70)
    print(f"  TOTAL: {total}  |  OK: {counts['OK']}  |  WARN: {counts['WARN']}  |  ERROR: {counts['ERROR']}")
    print("=" * 70)

    # Breakdown by owner × status
    owner_status: Counter = Counter()
    for rel_path in paths:
        rule = match_rules(rel_path, rules)
        _, owner, _, status = classify(rule, default_owner)
        owner_status[(owner, status)] += 1

    print()
    print("  Breakdown by owner:")
    by_owner: dict[str, Counter] = {}
    for (owner, status), cnt in sorted(owner_status.items()):
        by_owner.setdefault(owner, Counter())[status] = cnt
    for owner in sorted(by_owner):
        parts_str = ", ".join(f"{s}={c}" for s, c in sorted(by_owner[owner].items()))
        total_owner = sum(by_owner[owner].values())
        print(f"    {owner:<16} {total_owner:>6}  ({parts_str})")
    print()

    if counts["ERROR"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
