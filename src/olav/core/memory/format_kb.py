"""Format-guide knowledge base — workflow specs for "how to save X".

Sibling to ``olav.core.memory.guide_kb``.  Where usage_guide answers
"what should the agent DO when the user asks for X" (multi-step
workflow), format_guide answers "if your output is shape X, what's
the right format_and_export call".  Both surface in the same recall
diversifier as separate categories.

This module is the platform-side host for the writer subagent's
seven historical references (``device_table.md``,
``topology_diagram.md``, …).  After R85 they live as
``*.format.yaml`` files plus their LanceDB ``format_guide`` rows;
writer is demoted to a polish/edit subagent (its original spec).

Schema (``*.format.yaml``)::

    schema_version: 1
    tag: topology_diagram
    keywords: [mermaid, topology, diagram]
    body: |
      Mermaid graph TD format.  Save:
      format_and_export(data=mermaid_text, format='mmd', subdir='diagrams')

Required: ``tag``, ``keywords``, ``body``.  ``schema_version`` defaults to 1.

Memory contract:
* id              = ``format_<tag>``   (idempotent upsert)
* category        = ``format_guide``
* text            = the YAML ``body``  (no chunking)
* vector          = embedding of ``tag\\nkeywords: ...\\n\\nbody``
* tags            = JSON ``[tag, *keywords]``
* origin          = ``config``
* confidence      = ``1.0``

User-facing CLI: ``olav kb import-formats <dir>``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class FormatGuide:
    """One ``*.format.yaml`` entry."""

    tag: str
    keywords: list[str]
    body: str
    schema_version: int = 1
    source_path: Path | None = None

    @classmethod
    def from_yaml(cls, path: Path) -> "FormatGuide":
        """Load + validate one file.  Raises ``KeyError`` for missing
        required fields, ``ValueError`` for type mismatches.
        """
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for required in ("tag", "keywords", "body"):
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
            tag=str(data["tag"]),
            keywords=[str(k) for k in keywords],
            body=str(data["body"]).strip(),
            schema_version=int(data.get("schema_version", 1)),
            source_path=path,
        )

    @property
    def memory_id(self) -> str:
        return f"format_{self.tag}"


def discover_formats(workspace_root: Path) -> list[FormatGuide]:
    """Glob every ``*.format.yaml`` under ``workspace_root/formats/``.

    Skips invalid files with a warning rather than aborting (so one
    bad file doesn't block ingest).
    """
    formats: list[FormatGuide] = []
    if not workspace_root.exists():
        logger.debug(
            "format_kb: workspace_root %s missing — no formats loaded",
            workspace_root,
        )
        return formats
    for path in sorted(workspace_root.rglob("formats/*.format.yaml")):
        try:
            formats.append(FormatGuide.from_yaml(path))
        except (KeyError, ValueError, yaml.YAMLError) as exc:
            logger.warning("format_kb: failed to load %s — %s", path, exc)
    return formats


def _embed(text: str) -> list[float] | None:
    """Wrap embedder; returns ``None`` on failure."""
    try:
        from olav.core.embedder import embed_text
        return embed_text(text)
    except Exception as exc:  # noqa: BLE001
        logger.debug("format_kb: embed failed: %s", exc)
        return None


def prime_formats_from_dir(
    workspace_root: Path,
    *,
    store: Any | None = None,
) -> dict[str, int]:
    """Bridge ``*.format.yaml`` files into the LanceDB ``format_guide``
    memory category.  Mirrors :func:`guide_kb.prime_guides_from_dir`.

    Returns ``{"format_entries": N, "skipped": K}``.  ``skipped == -1``
    signals the store was unavailable.
    """
    if store is None:
        try:
            from olav.core.memory import get_store
            store = get_store()
        except Exception as exc:  # noqa: BLE001
            logger.info("format_kb: store unavailable, skipping: %s", exc)
            return {"format_entries": 0, "skipped": -1}
    if store is None:
        return {"format_entries": 0, "skipped": -1}

    formats = discover_formats(workspace_root)
    if not formats:
        return {"format_entries": 0, "skipped": 0}

    count = 0
    skipped = 0
    for fmt in formats:
        embed_input = (
            f"{fmt.tag}\n"
            f"keywords: {', '.join(fmt.keywords)}\n\n"
            f"{fmt.body}"
        )
        vec = _embed(embed_input)
        if not vec:
            skipped += 1
            continue

        mem_id = fmt.memory_id
        try:
            store.delete_memory(id=mem_id)
        except Exception:
            pass

        tag_list = [fmt.tag] + list(fmt.keywords)
        try:
            store.add_memory(
                id=mem_id,
                text=fmt.body,
                vector=vec,
                category="format_guide",
                scope="global",
                metadata={
                    "tag": fmt.tag,
                    "schema_version": fmt.schema_version,
                    "n_keywords": len(fmt.keywords),
                },
                origin="config",
                confidence=1.0,
                tags=json.dumps(tag_list, ensure_ascii=False),
            )
            count += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("format_kb: %s upsert failed: %s", mem_id, exc)
            skipped += 1

    logger.info(
        "format_kb: %d entries from %s (%d skipped)",
        count, workspace_root, skipped,
    )
    return {"format_entries": count, "skipped": skipped}


__all__ = ["FormatGuide", "discover_formats", "prime_formats_from_dir"]
