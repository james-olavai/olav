#!/usr/bin/env python3
"""load_reference — On-demand reference document loader for Core Agent.

Load visualization syntax guides and schema references only when needed,
keeping the system prompt lean and avoiding anti-progressive-disclosure.

ARCH-17 (Round 38): supports ``section=`` to slice by ``##`` header —
operators can pull just the relevant subsection of a large reference
(e.g. ``load_reference("schema", section="verified sql examples")``)
instead of the full file. Pass ``section="?"`` to list available
section headings.
"""

from __future__ import annotations

import re
from pathlib import Path


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


# References live at core/references/ — compute absolute path to avoid
# breakage if this file moves within the workspace tree.
_REFS_DIR = _find_project_root() / ".olav" / "workspace" / "core" / "references"

_AVAILABLE = {
    "mermaid": "viz_mermaid.md",
    "plantuml_network": "viz_plantuml_network.md",
    # drawio moved to schema-v2 KB guide (core/guides/viz_drawio.guide.yaml)
    # — auto-recalled on drawio / mxfile / editable-diagram keywords.
    "infographic": "viz_infographic.md",
    "schema": "SCHEMA_REFERENCE.md",
    "skill_dev": "SKILL_DEVELOPMENT.md",
    "required_info": "REQUIRED_INFO_CHECK.md",
}

# Match level-2 markdown headers. Emoji + trailing whitespace are tolerated
# so "## 🗄️ Core Table & View Schema" matches section="core table & view schema".
_H2_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$", re.MULTILINE)


def _parse_sections(text: str) -> list[tuple[str, int, int]]:
    """Return ``[(heading_text, body_start, body_end), ...]`` for every ``##``."""
    matches = list(_H2_RE.finditer(text))
    sections: list[tuple[str, int, int]] = []
    for i, m in enumerate(matches):
        title = m.group("title").strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((title, body_start, body_end))
    return sections


def _normalise(heading: str) -> str:
    """Lowercase and strip emoji/punctuation so user queries match loosely."""
    return re.sub(r"[^\w\s]", "", heading).lower().strip()


def _find_section(text: str, query: str) -> tuple[str, str] | None:
    """Return ``(matched_heading, body_text)`` for a case-insensitive match."""
    sections = _parse_sections(text)
    q = _normalise(query)
    exact = [(h, text[s:e]) for h, s, e in sections if _normalise(h) == q]
    if exact:
        return exact[0]
    partial = [(h, text[s:e]) for h, s, e in sections if q in _normalise(h)]
    if partial:
        return partial[0]
    return None


def load_reference(name: str, section: str | None = None) -> str:
    """Load a reference document on demand.

    Call this tool ONLY when you are about to generate content in a
    specific format — do NOT pre-load all references at the start of a task.

    Available references:
      - mermaid            : Mermaid flowchart/sequence/state diagram syntax
      - plantuml_network   : PlantUML + Cisco stencil network topology syntax
      - (drawio retired)   : see core/guides/viz_drawio.guide.yaml (auto-recalled)
      - infographic        : KPI score-card, timeline, gauge YAML templates
      - schema             : Database schema reference (tables, views, columns)
      - skill_dev          : Skill development guidelines
      - required_info      : Required information checklist

    Args:
        name: Reference name from the list above.
        section: Optional ``##`` heading to slice out (case-insensitive,
            loose match — "verified sql" matches "Verified SQL Examples").
            Pass ``"?"`` to list section headings without loading content.
            Omit to load the full document.

    Returns:
        Full text of the reference (or the named section only, if
        ``section=`` matched). If ``section="?"`` returns a bulleted list of
        available sections. Unknown ``name`` returns an error string with
        available options; unknown ``section`` returns an error string with
        the available section headings.

    Example:
        >>> load_reference("schema", section="common mistakes")
        # returns only the "## 🚫 Common Mistakes to Avoid" section
    """
    key = name.strip().lower()
    filename = _AVAILABLE.get(key)
    if not filename:
        available = ", ".join(sorted(_AVAILABLE))
        return f"Reference '{name}' not found. Available: {available}"

    ref_path = _REFS_DIR / filename
    if not ref_path.exists():
        return f"Reference file '{filename}' not found on disk (expected at {ref_path})"

    text = ref_path.read_text(encoding="utf-8")

    if section is None or section == "":
        return text

    if section.strip() == "?":
        headings = [h for h, _s, _e in _parse_sections(text)]
        if not headings:
            return f"Reference '{name}' has no ## sections."
        return "Available sections in '{n}':\n{lst}".format(
            n=name, lst="\n".join(f"  - {h}" for h in headings)
        )

    match = _find_section(text, section)
    if match is None:
        headings = [h for h, _s, _e in _parse_sections(text)]
        return (
            f"Section '{section}' not found in '{name}'. "
            f"Available sections: {'; '.join(headings) if headings else '(none)'}"
        )
    heading, body = match
    return f"## {heading}\n{body.rstrip()}\n"


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    result = load_reference(**_args)
    print(_json.dumps(result, default=str))
