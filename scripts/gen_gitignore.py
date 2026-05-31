#!/usr/bin/env python3
"""gen_gitignore.py — Generate .gitignore from ownership_manifest.yaml.

Single source of truth: ownership_manifest.yaml defines which paths are
tracked, ignored, or secret. This script converts those declarations into
a .gitignore file.

Usage:
    uv run python scripts/gen_gitignore.py           # preview to stdout
    uv run python scripts/gen_gitignore.py --write   # overwrite .gitignore
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "ownership_manifest.yaml"

HEADER = """\
# ══════════════════════════════════════════════════════════════════════════════
# OLAV Platform .gitignore
#
# AUTO-GENERATED from ownership_manifest.yaml
# Do not edit manually — run: uv run python scripts/gen_gitignore.py --write
# ══════════════════════════════════════════════════════════════════════════════
"""


def pattern_to_gitignore(pattern: str) -> str:
    """Convert manifest glob pattern to gitignore entry.

    Manifest uses fnmatch-style globs (src/olav/**).
    Gitignore uses its own pattern syntax (src/olav/).

    Bare names (no '/' in the base, e.g. ``scripts/**``) are root-anchored
    with a leading '/' so they only match the top-level directory and not
    nested directories of the same name (e.g. workspace agent scripts/).
    """
    # foo/** → foo/
    if pattern.endswith("/**"):
        base = pattern[:-3]
    # foo/* → foo/ (covers top-level files in dir)
    elif pattern.endswith("/*"):
        base = pattern[:-2]
    else:
        return pattern
    # Root-anchor bare names to prevent matching nested dirs of the same name.
    if "/" not in base:
        return f"/{base}/"
    return f"{base}/"


def pattern_to_gitignore_negation(pattern: str) -> str:
    """Convert a tracked pattern inside an ignored parent to a negation."""
    entry = pattern_to_gitignore(pattern)
    return f"!{entry}"


def generate(manifest: dict) -> str:
    lines: list[str] = [HEADER]

    # ── File-type patterns ───────────────────────────────────────
    file_patterns = manifest.get("gitignore_file_patterns", {})
    if file_patterns:
        for section, patterns in file_patterns.items():
            lines.append(f"# ── {section} ──")
            for p in patterns:
                lines.append(p)
            lines.append("")

    rules = manifest.get("rules", [])

    # Separate rules by git policy
    ignore_rules: list[dict] = []
    secret_rules: list[dict] = []
    # Track rules that are children of ignored parents (need negation)
    track_rules: list[dict] = []

    for rule in rules:
        git = rule.get("git", "track")
        if git == "ignore":
            ignore_rules.append(rule)
        elif git == "secret":
            secret_rules.append(rule)
        elif git == "track":
            track_rules.append(rule)

    # ── Ignored paths (non-release, generated, sub-repos) ────────
    # Group by class for readability
    class_order = [
        "platform", "testing", "generated", "legacy",
        "netops", "enterprise", "docs", "website",
        "runtime-workspace",
    ]
    by_class: dict[str, list[dict]] = {}
    for rule in ignore_rules:
        cls = rule.get("class", "other")
        by_class.setdefault(cls, []).append(rule)

    lines.append("# ── Paths ignored by manifest rules ──")
    lines.append("")
    for cls in class_order:
        rules_in_class = by_class.pop(cls, [])
        if not rules_in_class:
            continue
        lines.append(f"# {cls}")
        for rule in rules_in_class:
            entry = pattern_to_gitignore(rule["pattern"])
            lines.append(entry)
        lines.append("")

    # remaining classes not in order
    for cls, rules_in_class in sorted(by_class.items()):
        lines.append(f"# {cls}")
        for rule in rules_in_class:
            entry = pattern_to_gitignore(rule["pattern"])
            lines.append(entry)
        lines.append("")

    # ── Tracked negations (.olav/ whitelist model) ───────────────
    # Find track rules whose parent is ignored
    ignored_prefixes = []
    for rule in ignore_rules:
        p = rule["pattern"]
        if p.endswith("/**") or p.endswith("/*"):
            ignored_prefixes.append(p.rsplit("/", 1)[0] + "/")
        elif p.endswith("/"):
            ignored_prefixes.append(p)

    negations = []
    for rule in track_rules:
        p = rule["pattern"]
        if any(p.startswith(prefix) for prefix in ignored_prefixes):
            negations.append(rule)

    if negations:
        lines.append("# ── Whitelist (tracked paths inside ignored parents) ──")
        emitted_lines: set[str] = set()
        for rule in negations:
            p = rule["pattern"]
            parts = Path(p).parts
            # Emit intermediate parent negations + re-ignore wildcards
            for i in range(1, len(parts)):
                parent = "/".join(parts[:i]) + "/"
                neg_line = f"!{parent}"
                if neg_line in emitted_lines:
                    continue
                if not any(parent.startswith(pfx) or pfx.startswith(parent) for pfx in ignored_prefixes):
                    continue
                lines.append(neg_line)
                emitted_lines.add(neg_line)
                # Re-ignore contents so only explicitly whitelisted paths survive
                if i < len(parts) - 1:
                    wild = "/".join(parts[:i]) + "/*"
                    if wild not in emitted_lines:
                        lines.append(wild)
                        emitted_lines.add(wild)
            # Emit the actual negation (skip if already emitted as intermediate)
            entry = pattern_to_gitignore_negation(p)
            if entry not in emitted_lines:
                lines.append(entry)
                emitted_lines.add(entry)
        lines.append("")

    # ── Secrets ──────────────────────────────────────────────────
    if secret_rules:
        lines.append("# ── Secrets (NEVER commit) ──")
        for rule in secret_rules:
            entry = pattern_to_gitignore(rule["pattern"])
            lines.append(entry)
        # Also add common secret file patterns
        lines.append(".env.local")
        lines.append(".env.*.local")
        lines.append("*.token")
        lines.append("*.key")
        lines.append("*.pem")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate .gitignore from ownership manifest")
    parser.add_argument("--write", action="store_true", help="Overwrite .gitignore")
    args = parser.parse_args()

    manifest = yaml.safe_load(MANIFEST_PATH.read_text())
    output = generate(manifest)

    if args.write:
        gitignore_path = REPO_ROOT / ".gitignore"
        gitignore_path.write_text(output)
        print(f"Wrote {gitignore_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
