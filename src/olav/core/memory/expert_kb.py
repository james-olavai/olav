"""Per-agent expert knowledge — vendor / platform-specific corrective
content.  Sibling to :mod:`olav.core.memory.guide_kb` and
:mod:`olav.core.memory.format_kb`.

Where ``usage_guide`` answers "what should the agent DO" (workflow)
and ``format_guide`` answers "if your output is shape X, how to call
format_and_export" — ``expert_knowledge`` answers "given this
vendor / platform, what's the correct way to interpret protocol
state / failure modes / quirks the LLM might miss".

The motivating case (R87): a small model sees ``bgp neighbor
state = active`` on an SR Linux container and reports CAB PASS,
because the LLM's training data is overwhelmingly Cisco where
``active`` means "trying".  In SRL, ``active`` means **TCP failed**.
A ``bgp_state_decoder_srl.expert.yaml`` entry corrects this prior.

**Per-agent scoping** — each ``*.expert.yaml`` declares its own
``scope`` (``global`` OR ``<agent_name>``).  Recall middleware
filters: an agent only sees expert entries scoped to itself or
``global``.  This keeps SRL knowledge out of the writer / core
agent's recall surface (it's noise there) but front-and-centre
for ops-lab.

Schema (``*.expert.yaml``)::

    schema_version: 1
    topic: bgp_state_decoder_srl
    scope: ops-lab
    vendor: srl                  # optional
    platform_family: nokia       # optional
    keywords: [srl, bgp, established, active, ...]
    body: |
      ...

Required: ``topic``, ``scope``, ``keywords``, ``body``.

Memory contract:
* id              = ``expert_<scope>_<topic>``  (idempotent upsert)
* category        = ``expert_knowledge``
* scope           = the YAML's ``scope`` field (NOT ``global``
                    unless explicitly declared so)
* text            = body (no chunking)
* vector          = embedding of ``topic + keywords + body``
* tags            = JSON ``[topic, scope, vendor, *keywords]``
* origin          = ``config``
* confidence      = ``1.0``

User-facing CLI: ``olav kb import-experts <dir>``.
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
class ExpertKnowledge:
    """One ``*.expert.yaml`` entry."""

    topic: str
    scope: str
    keywords: list[str]
    body: str
    schema_version: int = 1
    vendor: str | None = None
    platform_family: str | None = None
    source_path: Path | None = None

    @classmethod
    def from_yaml(cls, path: Path) -> "ExpertKnowledge":
        """Load + validate one file.  Raises ``KeyError`` for missing
        required fields, ``ValueError`` for type mismatches.
        """
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for required in ("topic", "scope", "keywords", "body"):
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
            topic=str(data["topic"]),
            scope=str(data["scope"]),
            keywords=[str(k) for k in keywords],
            body=str(data["body"]).strip(),
            schema_version=int(data.get("schema_version", 1)),
            vendor=(
                str(data["vendor"]) if data.get("vendor") is not None else None
            ),
            platform_family=(
                str(data["platform_family"])
                if data.get("platform_family") is not None
                else None
            ),
            source_path=path,
        )

    @property
    def memory_id(self) -> str:
        """Deterministic ID — ``expert_<scope>_<topic>`` for idempotent
        upserts.
        """
        return f"expert_{self.scope}_{self.topic}"


def discover_experts(workspace_root: Path) -> list[ExpertKnowledge]:
    """Glob every ``*.expert.yaml`` under
    ``workspace_root/<agent>/expertise/``.

    Skips invalid files with a warning rather than aborting.
    """
    experts: list[ExpertKnowledge] = []
    if not workspace_root.exists():
        logger.debug(
            "expert_kb: workspace_root %s missing — no experts loaded",
            workspace_root,
        )
        return experts
    for path in sorted(workspace_root.rglob("expertise/*.expert.yaml")):
        try:
            experts.append(ExpertKnowledge.from_yaml(path))
        except (KeyError, ValueError, yaml.YAMLError) as exc:
            logger.warning("expert_kb: failed to load %s — %s", path, exc)
    return experts


def _embed(text: str) -> list[float] | None:
    """Wrap embedder; returns ``None`` on failure."""
    try:
        from olav.core.embedder import embed_text
        return embed_text(text)
    except Exception as exc:  # noqa: BLE001
        logger.debug("expert_kb: embed failed: %s", exc)
        return None


def prime_experts_from_dir(
    workspace_root: Path,
    *,
    store: Any | None = None,
) -> dict[str, int]:
    """Bridge ``*.expert.yaml`` files into the LanceDB
    ``expert_knowledge`` memory category.

    Mirrors :func:`guide_kb.prime_guides_from_dir` but with one
    critical difference — each entry's ``scope`` field comes from
    the YAML, NOT ``global``.  This is what enables per-agent
    recall filtering downstream.

    Returns ``{"expert_entries": N, "skipped": K}``.
    """
    if store is None:
        try:
            from olav.core.memory import get_store
            store = get_store()
        except Exception as exc:  # noqa: BLE001
            logger.info("expert_kb: store unavailable, skipping: %s", exc)
            return {"expert_entries": 0, "skipped": -1}
    if store is None:
        return {"expert_entries": 0, "skipped": -1}

    experts = discover_experts(workspace_root)
    if not experts:
        return {"expert_entries": 0, "skipped": 0}

    count = 0
    skipped = 0
    for expert in experts:
        embed_input = (
            f"{expert.topic}\n"
            f"keywords: {', '.join(expert.keywords)}\n\n"
            f"{expert.body}"
        )
        vec = _embed(embed_input)
        if not vec:
            skipped += 1
            continue

        mem_id = expert.memory_id
        try:
            store.delete_memory(id=mem_id)
        except Exception:
            pass

        # Tags: topic + scope + vendor + all keywords.  Tag-FTS index
        # (future Phase 3 work) lights up cleanly on these.
        tag_list = [expert.topic, expert.scope] + list(expert.keywords)
        if expert.vendor:
            tag_list.append(expert.vendor)

        metadata = {
            "topic": expert.topic,
            "scope": expert.scope,
            "schema_version": expert.schema_version,
            "n_keywords": len(expert.keywords),
        }
        if expert.vendor:
            metadata["vendor"] = expert.vendor
        if expert.platform_family:
            metadata["platform_family"] = expert.platform_family

        try:
            store.add_memory(
                id=mem_id,
                text=expert.body,
                vector=vec,
                category="expert_knowledge",
                scope=expert.scope,  # ← per-agent scoping happens here
                metadata=metadata,
                origin="config",
                confidence=1.0,
                tags=json.dumps(tag_list, ensure_ascii=False),
            )
            count += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("expert_kb: %s upsert failed: %s", mem_id, exc)
            skipped += 1

    logger.info(
        "expert_kb: %d entries from %s (%d skipped)",
        count, workspace_root, skipped,
    )
    return {"expert_entries": count, "skipped": skipped}


__all__ = [
    "ExpertKnowledge",
    "discover_experts",
    "prime_experts_from_dir",
]
