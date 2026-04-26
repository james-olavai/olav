"""Usage guide loader (Phase 1 — `dev_docs/61. MEMORY_DRIVEN_USAGE_GUIDES.md`).

Bridge between procedural reference YAML files and the LanceDB
``usage_guide`` memory category.  The YAML files are the source of
truth (git-tracked, human-readable); ``prime_usage_guides`` in
:mod:`olav_netops.core.memory_primer` reads them at ingest time and
upserts memory entries by deterministic id.

YAML schema (single document per file)::

    schema_version: 1
    intent: topology_visualization
    agent: ops
    keywords: [topology, mermaid, diagram, ...]
    body: |
      Step-by-step procedure...
    related:                          # optional
      - intent: simulation_what_if
        note: "..."

Required keys: ``intent``, ``agent``, ``keywords``, ``body``.

Discovery glob: ``workspace/<agent>/guides/*.guide.yaml`` — matches
the convention used by other workspace asset directories
(``references/``, ``tools/``, ``prompts/``).

Mirror of :class:`olav.core.workspace.WorkspaceDeclaration` —
dataclass + ``from_yaml`` classmethod, raise on missing required keys.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class UsageGuide:
    """One YAML guide entry, loaded from disk."""

    intent: str
    agent: str
    keywords: list[str]
    body: str
    schema_version: int = 1
    related: list[dict] = field(default_factory=list)
    source_path: Path | None = None

    @classmethod
    def from_yaml(cls, path: Path) -> "UsageGuide":
        """Load and validate one ``*.guide.yaml`` file.

        Raises ``KeyError`` for missing required fields and
        ``ValueError`` for type mismatches — caller decides whether to
        skip-and-log or propagate.
        """
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for required in ("intent", "agent", "keywords", "body"):
            if required not in data:
                raise KeyError(
                    f"{path}: missing required field '{required}'"
                )
        keywords = data["keywords"]
        if not isinstance(keywords, list) or not all(
            isinstance(k, str) for k in keywords
        ):
            raise ValueError(f"{path}: 'keywords' must be a list of strings")
        return cls(
            intent=str(data["intent"]),
            agent=str(data["agent"]),
            keywords=[str(k) for k in keywords],
            body=str(data["body"]).strip(),
            schema_version=int(data.get("schema_version", 1)),
            related=list(data.get("related") or []),
            source_path=path,
        )

    @property
    def memory_id(self) -> str:
        """Deterministic ID — idempotent upsert across re-prime cycles."""
        return f"guide_{self.agent}_{self.intent}"


def discover_guides(workspace_root: Path) -> list[UsageGuide]:
    """Glob every ``*.guide.yaml`` under ``workspace_root/<agent>/guides/``.

    Returns successfully-loaded guides; logs and skips invalid files
    rather than aborting (so one bad guide doesn't block ingest).
    Caller can inspect the returned list length vs ``rglob`` count to
    detect drift, but priming logs each skip too.
    """
    guides: list[UsageGuide] = []
    if not workspace_root.exists():
        logger.debug("usage_guide: workspace_root %s missing — no guides loaded",
                     workspace_root)
        return guides
    for path in sorted(workspace_root.rglob("guides/*.guide.yaml")):
        try:
            guides.append(UsageGuide.from_yaml(path))
        except (KeyError, ValueError, yaml.YAMLError) as exc:
            logger.warning("usage_guide: failed to load %s — %s", path, exc)
    return guides


__all__ = ["UsageGuide", "discover_guides"]
