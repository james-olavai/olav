"""Platform-side usage-guide knowledge base.

Owns the ``UsageGuide`` schema and the LanceDB upsert path for guides
written as ``*.guide.yaml`` files.  Any OLAV skill (netops, audit,
lab, ent, …) that wants to ship procedural guides drops files under
``<workspace>/<agent>/guides/`` — they're discovered by ``rglob`` here
and primed into the ``usage_guide`` memory category.

This module replaces the per-skill plumbing in
``olav-netops/src/olav_netops/core/usage_guide.py`` and
``olav-netops/src/olav_netops/core/memory_primer.py:prime_usage_guides``.
The contract is preserved bit-for-bit:

* Memory ID:          ``guide_<agent>_<intent>`` (idempotent upsert)
* Category:           ``usage_guide``
* Stored ``text``:    raw guide body (no chunking, no keyword stuffing)
* Stored ``vector``:  embedding of ``intent + keywords + body``
* Stored ``tags``:    JSON ``[intent, agent, *keywords]``
* Origin:             ``config``
* Confidence:         ``1.0``

User-facing surface: ``olav kb import-guides <dir>`` — see
``src/olav/cli/commands/kb.py:cmd_import_guides``.

YAML schema (one guide per file)::

    schema_version: 1
    intent: topology_visualization
    agent: ops
    keywords: [topology, mermaid, diagram]
    body: |
      Pull L2 links, build Mermaid graph TD, delegate to writer.
    related:                            # optional
      - intent: simulation_what_if
        note: "..."

Required: ``intent``, ``agent``, ``keywords``, ``body``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    """
    guides: list[UsageGuide] = []
    if not workspace_root.exists():
        logger.debug(
            "guide_kb: workspace_root %s missing — no guides loaded",
            workspace_root,
        )
        return guides
    for path in sorted(workspace_root.rglob("guides/*.guide.yaml")):
        try:
            guides.append(UsageGuide.from_yaml(path))
        except (KeyError, ValueError, yaml.YAMLError) as exc:
            logger.warning("guide_kb: failed to load %s — %s", path, exc)
    return guides


def _embed(text: str) -> list[float] | None:
    """Wrap embedder; returns ``None`` on failure (caller skips entry)."""
    try:
        from olav.core.embedder import embed_text
        return embed_text(text)
    except Exception as exc:  # noqa: BLE001
        logger.debug("guide_kb: embed failed: %s", exc)
        return None


def prime_guides_from_dir(
    workspace_root: Path,
    *,
    store: Any | None = None,
) -> dict[str, int]:
    """Bridge ``*.guide.yaml`` files into the LanceDB ``usage_guide``
    memory category.

    Discover ``*.guide.yaml`` files under
    ``workspace_root/<agent>/guides/``, embed each one's
    ``intent + keywords + body``, and upsert as a ``usage_guide`` memory
    entry with deterministic id ``guide_<agent>_<intent>``.

    Returns ``{"guide_entries": N, "skipped": K}``.  ``skipped == -1``
    signals the store wasn't available; ``skipped >= 0`` counts
    per-guide write failures.
    """
    if store is None:
        try:
            from olav.core.memory import get_store
            store = get_store()
        except Exception as exc:  # noqa: BLE001
            logger.info("guide_kb: store unavailable, skipping: %s", exc)
            return {"guide_entries": 0, "skipped": -1}
    if store is None:
        return {"guide_entries": 0, "skipped": -1}

    guides = discover_guides(workspace_root)
    if not guides:
        return {"guide_entries": 0, "skipped": 0}

    count = 0
    skipped = 0
    for guide in guides:
        # Embed intent + keywords + body so short keyword-anchored
        # queries match the body's vector even when prose doesn't
        # repeat the keywords verbatim.
        embed_input = (
            f"{guide.intent}\n"
            f"keywords: {', '.join(guide.keywords)}\n\n"
            f"{guide.body}"
        )
        vec = _embed(embed_input)
        if not vec:
            skipped += 1
            continue

        mem_id = guide.memory_id
        try:
            store.delete_memory(id=mem_id)  # idempotent upsert
        except Exception:
            pass

        # tags: JSON list, contains agent + intent + all keywords so a
        # tag-FTS index (future Phase 3 work) can light up cleanly.
        tag_list = [guide.intent, guide.agent] + list(guide.keywords)
        try:
            store.add_memory(
                id=mem_id,
                text=guide.body,
                vector=vec,
                category="usage_guide",
                scope="global",
                metadata={
                    "intent": guide.intent,
                    "agent": guide.agent,
                    "schema_version": guide.schema_version,
                    "n_keywords": len(guide.keywords),
                },
                origin="config",
                confidence=1.0,
                tags=json.dumps(tag_list, ensure_ascii=False),
            )
            count += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("guide_kb: %s upsert failed: %s", mem_id, exc)
            skipped += 1

    logger.info(
        "guide_kb: %d entries from %s (%d skipped)",
        count, workspace_root, skipped,
    )
    return {"guide_entries": count, "skipped": skipped}


__all__ = ["UsageGuide", "discover_guides", "prime_guides_from_dir"]
