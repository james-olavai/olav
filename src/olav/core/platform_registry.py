"""platform_registry — global olav.md loader.

Tier 1 of the three-tier registration model:

  Tier 1 (Global):  olav.md → top-level agents + platform context
  Tier 2 (Agent):   AGENT.md   → sub-agents (per-agent declaration)
  Tier 3 (Dynamic): MANIFEST.yaml → Skill auto-discovery

olav.md lives at .olav/workspace/olav.md.  Its YAML frontmatter
declares which top-level agents are installed and any platform-wide context
(database paths, service endpoints, etc.).

Example::

    ---
    agents:
      - quick
      - ops
      - config
      - audit
      - core
    active: quick
    platform:
      db: .olav/databases/olav.duckdb
      memory: .olav/databases/memory.lance
      services:
        clab: http://clab-server.example.com:8080
    ---

    # My Network Lab

    SRL nodes, running ContainerLab 0.74.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

PLATFORM_MD_FILENAME = "olav.md"


@dataclass
class PlatformRegistry:
    """Parsed representation of olav.md.

    Attributes
    ----------
    agents:
        Ordered list of top-level agent names declared in olav.md.
        These are the valid routing targets for the platform router.
    active:
        The default/active agent name (``active:`` frontmatter key).
    platform:
        Free-form dict from the ``platform:`` frontmatter block.
        Typically contains ``db``, ``memory``, ``services``, etc.
    body:
        The markdown body text (everything after the frontmatter).
    description:
        Alias for ``body``.
    """

    agents: list[str] = field(default_factory=list)
    active: str | None = None
    platform: dict[str, Any] = field(default_factory=dict)
    body: str = ""

    @property
    def description(self) -> str:
        return self.body

    # ── factory ───────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, workspace_root: Path) -> "PlatformRegistry":
        """Load olav.md from *workspace_root*.

        Returns an empty registry (all defaults) if the file is missing or
        cannot be parsed — never raises.
        """
        platform_md = workspace_root / PLATFORM_MD_FILENAME
        if not platform_md.exists():
            return cls()

        try:
            text = platform_md.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)
        except Exception as exc:
            logger.warning("Failed to parse olav.md at %s: %s", platform_md, exc)
            return cls()

        agents = list(meta.get("agents") or [])
        active = meta.get("active") or (agents[0] if agents else None)
        platform = dict(meta.get("platform") or {})

        return cls(agents=agents, active=active, platform=platform, body=body.strip())

    # ── context serialisation ─────────────────────────────────────────────────

    def as_context(self) -> str:
        """Return a compact string suitable for injection into a system prompt."""
        lines: list[str] = ["## Platform Registry"]

        if self.agents:
            lines.append(f"Registered agents: {', '.join(self.agents)}")
        if self.active:
            lines.append(f"Active agent: {self.active}")

        if self.platform:
            lines.append("Platform config:")
            for key, val in self.platform.items():
                if isinstance(val, dict):
                    for k2, v2 in val.items():
                        lines.append(f"  {key}.{k2}: {v2}")
                else:
                    lines.append(f"  {key}: {val}")

        if self.body:
            lines.append("")
            lines.append(self.body)

        return "\n".join(lines)


# ── helpers ───────────────────────────────────────────────────────────────────


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from *text*.

    Returns (metadata_dict, body_string).  If no frontmatter is found,
    returns ({}, text).
    """
    if not text.startswith("---"):
        return {}, text

    # Find the closing ---
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    yaml_block = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")

    try:
        meta = yaml.safe_load(yaml_block)
        if not isinstance(meta, dict):
            return {}, body
        return meta, body
    except yaml.YAMLError:
        return {}, body
