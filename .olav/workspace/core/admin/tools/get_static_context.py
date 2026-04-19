#!/usr/bin/env python3
"""ARCH-17 P1 — pull static reference bundles on demand.

Companion to the ``static_context_mode`` mechanism. When an agent runs
in ``"lazy"`` mode the init prompt carries only a one-liner; the agent
calls this tool once it decides a given reference is worth the tokens.

The name input maps to the file basename (or stem) declared in
AGENT.md / SKILL.md ``static_context`` entries — e.g. passing
``"BASELINE_SCHEMA"`` returns the content of the referenced
``BASELINE_SCHEMA.md`` file.

Failure modes are soft: unknown names return ``{error: ..., available: [...]}``
so the calling model can retry with the right spelling.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


_PROJECT_ROOT = _find_project_root()
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))


# Candidate agent directories — look in each until we find the skill's
# frontmatter entries. Order reflects the v0.18 agent layout.
_AGENT_DIRS = [
    _PROJECT_ROOT / ".olav" / "workspace" / "core",
    _PROJECT_ROOT / ".olav" / "workspace" / "ops",
    _PROJECT_ROOT / ".olav" / "workspace" / "audit",
]


def _iter_static_context_entries() -> list[tuple[Path, str]]:
    """Yield (absolute_path, label) for every entry in every AGENT.md /
    SKILL.md ``static_context`` list under the known agent trees."""
    import yaml

    entries: list[tuple[Path, str]] = []
    for agent_dir in _AGENT_DIRS:
        if not agent_dir.exists():
            continue
        for md in agent_dir.rglob("*.md"):
            if md.name not in {"AGENT.md", "SKILL.md"}:
                continue
            try:
                text = md.read_text(encoding="utf-8")
            except OSError:
                continue
            if not text.startswith("---"):
                continue
            parts = text.split("---", 2)
            if len(parts) < 2:
                continue
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                continue
            sc = meta.get("static_context") or []
            base = md.parent
            for entry in sc:
                rel = entry.get("path", entry) if isinstance(entry, dict) else entry
                rel = str(rel).removeprefix("$ref:")
                full = (base / rel).resolve()
                label = full.stem  # e.g. "BASELINE_SCHEMA"
                entries.append((full, label))
    return entries


@tool
def get_static_context(name: str) -> dict[str, Any]:
    """Return a static reference bundle by name (lazy-mode pull).

    Args:
        name: Reference identifier. Matches the stem of the file declared
            under ``static_context:`` in any AGENT.md / SKILL.md
            (e.g. ``"BASELINE_SCHEMA"`` for ``BASELINE_SCHEMA.md``).

    Returns:
        ``{name, path, content}`` on hit, or
        ``{error, available: [...]}`` when the name is unknown.
    """
    if not name or not isinstance(name, str):
        return {"error": "get_static_context requires a non-empty name"}

    entries = _iter_static_context_entries()
    by_label: dict[str, Path] = {}
    for path, label in entries:
        by_label.setdefault(label, path)
        # Also index by full filename (e.g. "BASELINE_SCHEMA.md")
        by_label.setdefault(path.name, path)

    target = by_label.get(name) or by_label.get(name.replace(" ", "_"))
    if target is None:
        return {
            "error": f"unknown static_context name: {name!r}",
            "available": sorted(set(label for _, label in entries)),
        }

    try:
        content = target.read_text(encoding="utf-8")
    except OSError as exc:
        return {"error": f"cannot read {target}: {exc}"}

    return {
        "name": name,
        "path": str(target.relative_to(_PROJECT_ROOT)),
        "content": content,
    }
