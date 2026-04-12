"""load_reference — On-demand reference document loader for Core Agent.

Load visualization syntax guides and schema references only when needed,
keeping the system prompt lean and avoiding anti-progressive-disclosure.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

_REFS_DIR = Path(__file__).parent.parent / "references"

_AVAILABLE = {
    "mermaid": "viz_mermaid.md",
    "plantuml_network": "viz_plantuml_network.md",
    "drawio": "viz_drawio.md",
    "infographic": "viz_infographic.md",
    "schema": "SCHEMA_REFERENCE.md",
    "skill_dev": "SKILL_DEVELOPMENT.md",
    "required_info": "REQUIRED_INFO_CHECK.md",
}


@tool
def load_reference(name: str) -> str:
    """Load a reference document on demand.

    Call this tool ONLY when you are about to generate content in a
    specific format — do NOT pre-load all references at the start of a task.

    Available references:
      - mermaid            : Mermaid flowchart/sequence/state diagram syntax
      - plantuml_network   : PlantUML + Cisco stencil network topology syntax
      - drawio             : draw.io XML generation rules and Cisco shapes
      - infographic        : KPI score-card, timeline, gauge YAML templates
      - schema             : Database schema reference (tables, views, columns)
      - skill_dev          : Skill development guidelines
      - required_info      : Required information checklist

    Args:
        name: Reference name from the list above.

    Returns:
        Full text of the reference document, or an error message if not found.
    """
    key = name.strip().lower()
    filename = _AVAILABLE.get(key)
    if not filename:
        available = ", ".join(sorted(_AVAILABLE))
        return f"Reference '{name}' not found. Available: {available}"

    ref_path = _REFS_DIR / filename
    if not ref_path.exists():
        return f"Reference file '{filename}' not found on disk (expected at {ref_path})"

    return ref_path.read_text(encoding="utf-8")
