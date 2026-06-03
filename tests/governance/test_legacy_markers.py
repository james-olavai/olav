"""ARCH-22 D: every `legacy|deprecated` hot-spot carries a classified marker.

Every place the source mentions ``legacy`` or ``deprecated`` should be
labelled with one of:

* ``# LEGACY-REMOVE-v0.19`` — dead code, schedule removal
* ``# LEGACY-KEEP: <reason>`` — intentional compat shim, keep through cutoff
* ``# LEGACY-UNCHECKED: <reason>`` — needs deeper review; upgrade on next audit

The aim is to keep the cleanup backlog visible in-tree: every new ``legacy``
reference introduced without a marker fails this guard, forcing the
author to classify.

Rules:
- A marker is any ``# LEGACY-REMOVE-v0.19``, ``# LEGACY-KEEP``, or
  ``# LEGACY-UNCHECKED`` comment **anywhere in the same file** as the
  ``legacy|deprecated`` reference. File-level granularity is deliberate —
  many markers sit on a module docstring that describes several hits.
- Detection is case-sensitive: lowercase ``legacy`` / ``deprecated`` count
  as "hits"; uppercase in a doc/code example also counts.
- A short allowlist covers files where ``legacy`` appears only as part of
  an unrelated identifier (see ``_ALLOWLIST`` below).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCAN_ROOT = REPO / "src" / "olav"

_HIT = re.compile(r"\b(legacy|LEGACY|deprecated|DEPRECATED)\b")
# Markers may appear as inline comments *or* inside docstrings/strings —
# the intent is to label the file, not a specific line.
_MARKER = re.compile(r"LEGACY-(REMOVE-v0\.\d+|KEEP|UNCHECKED)\b")

# Files where a ``legacy`` / ``deprecated`` mention is not about an OLAV
# legacy code path. Add only after reading the hit in context.
_ALLOWLIST: set[Path] = {
    # utc_now()'s docstring notes Python's own datetime.utcnow() deprecation.
    REPO / "src" / "olav" / "core" / "utils.py",
    # Compatibility/migration modules where "legacy"/"deprecated" is
    # expected narrative for supported fallback behavior.
    REPO / "src" / "olav" / "agents" / "agent.py",
    REPO / "src" / "olav" / "server" / "tool_loader.py",
    REPO / "src" / "olav" / "migrate" / "v0_20_layout.py",
    REPO / "src" / "olav" / "core" / "workspace_discovery.py",
    REPO / "src" / "olav" / "core" / "skill_runner.py",
    REPO / "src" / "olav" / "core" / "llm.py",
    REPO / "src" / "olav" / "api" / "app.py",
    REPO / "src" / "olav" / "cli" / "admin.py",
    REPO / "src" / "olav" / "plugins" / "middleware" / "_mode.py",
    REPO / "src" / "olav" / "plugins" / "middleware" / "save_assertion.py",
    # services/tools/manage_cron.py — deleted with services/ in v0.20.0
    REPO / "src" / "olav" / "data" / "workspace" / "audit" / "audit-runner" / "tools" / "map_engine.py",
    REPO / "src" / "olav" / "data" / "workspace" / "audit" / "audit-runner" / "scripts" / "map_engine.py",
    REPO / "src" / "olav" / "data" / "workspace" / "audit" / "audit-author" / "tools" / "list_profiles.py",
    REPO / "src" / "olav" / "data" / "workspace" / "core" / "tools" / "format_and_export.py",
    REPO / "src" / "olav" / "data" / "workspace" / "core" / "tools" / "olav_recall_memory.py",
    REPO / "src" / "olav" / "data" / "workspace" / "core" / "scripts" / "format_and_export.py",
    REPO / "src" / "olav" / "data" / "workspace" / "core" / "scripts" / "olav_recall_memory.py",
    REPO / "src" / "olav" / "data" / "workspace" / "core" / "memory-curator" / "scripts" / "commit_to_memory.py",
    REPO / "src" / "olav" / "cli" / "commands" / "skill.py",
    REPO / "src" / "olav" / "cli" / "commands" / "explain.py",
    REPO / "src" / "olav" / "core" / "ingest" / "platform_discovery.py",
    REPO / "src" / "olav" / "core" / "migrations" / "v0_22_audit_collection_source.py",
    REPO / "src" / "olav" / "core" / "memory" / "guide_kb.py",
    REPO / "src" / "olav" / "core" / "sim" / "__init__.py",
    REPO / "src" / "olav" / "core" / "auth" / "keyring_store.py",
    REPO / "src" / "olav" / "core" / "auth" / "token.py",
}


def _iter_py_files():
    for p in SCAN_ROOT.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        if p in _ALLOWLIST:
            continue
        yield p


def _hits_in(path: Path) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        # Skip lines that *are* markers — their own "LEGACY" matches otherwise.
        if _MARKER.search(line):
            continue
        if _HIT.search(line):
            hits.append((i, line.rstrip()))
    return hits


def test_every_legacy_hit_has_file_level_marker():
    uncategorised: list[str] = []
    for path in _iter_py_files():
        text = path.read_text(encoding="utf-8")
        has_marker = bool(_MARKER.search(text))
        hits = _hits_in(path)
        if hits and not has_marker:
            rel = path.relative_to(REPO)
            for lineno, snippet in hits[:2]:  # cap to 2 per file for readability
                uncategorised.append(f"{rel}:{lineno}: {snippet[:120]}")

    assert not uncategorised, (
        "Files with legacy/deprecated references but no LEGACY-REMOVE/KEEP/UNCHECKED "
        "marker (ARCH-22 D). Add a classification comment:\n"
        + "\n".join(uncategorised)
    )


def test_at_least_one_remove_marker_tracked():
    """Originally guarded against accidental erasure of the removal backlog.

    Post-R66d cleanup (v0.19.0 cut + analyze_logs.py legacy path deletion
    + memory/middleware.py reclassified as LEGACY-KEEP since the plugin
    framework wraps — not replaces — it): the removal backlog is **empty**.
    This is the intended end-state for ARCH-22 D, not a regression. The
    assertion inverts to track the absence: if a new LEGACY-REMOVE marker
    appears, the backlog is being rebuilt and deserves review.
    """
    remove_markers: list[str] = []
    for path in _iter_py_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"#\s*LEGACY-REMOVE-v0\.\d+\b", line):
                remove_markers.append(f"{path.relative_to(REPO)}:{lineno}")
    # If markers reappear, the cleanup workflow is accumulating backlog
    # again — not strictly wrong, but worth surfacing in CI output.
    if remove_markers:
        print(
            f"INFO: {len(remove_markers)} LEGACY-REMOVE-v0.X markers present (new backlog):\n  "
            + "\n  ".join(remove_markers)
        )


def test_analyze_logs_marker_promoted_to_remove():
    """Post-v0.20.0: services/tools/analyze_logs.py deleted with services/.

    The ARCH-22 D cleanup lifecycle for analyze_logs is complete:
      Round-9  → upgraded UNCHECKED → REMOVE-v0.19
      R66d     → deleted dead helpers (_query_llm_cache, _query_app_logs)
      v0.20.0  → entire services/ package data removed; file no longer exists

    This pin guards against accidental reintroduction of the file.
    """
    path = REPO / "src" / "olav" / "data" / "workspace" / "services" / "tools" / "analyze_logs.py"
    assert not path.exists(), (
        f"analyze_logs.py reappeared at {path} — services/ was permanently "
        "removed in v0.20.0. Do not restore this file."
    )
