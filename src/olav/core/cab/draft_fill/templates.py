"""YAML template loader for staged-fill prompts.

Reads prompt + per-intent S4 specs from ``src/olav/data/draft_fill_templates/``.
Adding a new intent = drop a new ``<intent>.yaml`` next to the
existing files; no Python change required (D2 from dev_docs/76 §design 4).

Template schema (per file):
    section:        S<n>_<name>          # e.g. "S4_intent_args"
    intent:         <intent>              # only for per-intent S4 files
    description:    <human-readable>
    prompt:         |
                    <multi-line jinja-style {var} placeholders>
    required_keys:  [<key>, ...]          # optional, for generic per-intent validator
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@lru_cache(maxsize=1)
def _templates_dir() -> Path:
    """Locate the templates dir relative to the installed olav package.

    __file__ is at olav/core/cab/draft_fill/templates.py → parents[3] = olav.
    Templates live at olav/data/draft_fill_templates/.
    """
    return Path(__file__).resolve().parents[3] / "data" / "draft_fill_templates"


def _load_yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


@lru_cache(maxsize=16)
def load_common(name: str) -> dict:
    """Load a _common template (scope / facts / intent / review)."""
    p = _templates_dir() / "_common" / f"{name}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"template _common/{name}.yaml not found at {p}")
    return _load_yaml(p)


@lru_cache(maxsize=16)
def load_intent(intent: str) -> dict | None:
    """Load a per-intent S4 template. Returns None if intent has no template
    (e.g. unknown intent, or one not yet ported to YAML)."""
    p = _templates_dir() / f"{intent}.yaml"
    if not p.exists():
        return None
    return _load_yaml(p)


def intent_required_keys(intent: str) -> list[str]:
    """Return the ``required_keys`` list from a per-intent template, or []."""
    t = load_intent(intent)
    if not t:
        return []
    return list(t.get("required_keys") or [])


def has_intent_template(intent: str) -> bool:
    return load_intent(intent) is not None


__all__ = [
    "load_common", "load_intent",
    "intent_required_keys", "has_intent_template",
]
