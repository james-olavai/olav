"""Platform-side usage-guide knowledge base.

Owns the ``UsageGuide`` schema and the LanceDB upsert path for guides
written as ``*.guide.yaml`` files.  Any OLAV skill (netops, audit,
lab, ent, …) that wants to ship procedural guides drops files under
``<workspace>/<agent>/guides/`` — they're discovered by ``rglob`` here
and primed into the ``usage_guide`` memory category.

Contract:

* Memory ID:          ``guide_<agent>_<intent>`` (idempotent upsert)
* Category:           ``usage_guide``
* Stored ``text``:    raw guide body (no chunking, no keyword stuffing)
* Stored ``vector``:  embedding of ``intent + keywords + body``
* Stored ``tags``:    JSON ``[intent, agent, *keywords]``
* Origin:             ``config``
* Confidence:         ``1.0``

User-facing surfaces:
* ``olav kb import-guides <dir>`` (declarative — see
  ``src/olav/cli/commands/kb.py:cmd_import_guides``)
* ``memory_curator`` sub-agent (conversational — R102, dev_docs/70)

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
    # 2026-05-14: priority field (optional in YAML, default 5).  Maps
    # linearly to LanceDB ``weight`` at insert time so high-priority
    # guides outrank operational_event noise in mixed recall results.
    priority: int = 5
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
            priority=int(data.get("priority", 5)),
            related=list(data.get("related") or []),
            source_path=path,
        )

    @property
    def memory_id(self) -> str:
        """Deterministic ID — idempotent upsert across re-prime cycles."""
        return f"guide_{self.agent}_{self.intent}"


def discover_guides(workspace_root: Path) -> list[UsageGuide]:
    """Glob every ``*.guide.yaml`` anywhere under ``workspace_root``.

    Pre-2026-05-14 the importer only scanned ``guides/`` directories.
    That broke when guides moved to ``<skill>/references/`` (for
    portability — see SKILL.md ``dynamic_context`` manifest).  Now
    the importer simply finds every ``*.guide.yaml`` regardless of
    parent directory name; SKILL.md ``dynamic_context`` remains the
    canonical authoritative reference for downstream agent
    frameworks, while OLAV's runtime keeps the convenient recursive
    scan.

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
    for path in sorted(workspace_root.rglob("*.guide.yaml")):
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
            from olav.core.memory import EmbeddingDimMismatchError, get_store
            store = get_store()
        except EmbeddingDimMismatchError:
            # Let the caller (prime_workspace_guides) decide whether the
            # dim mismatch is recoverable (skill-install dim swap) or
            # must surface (init / kb import-guides without --force).
            raise
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
        # 2026-05-14: derive ``weight`` from the guide's ``priority`` field.
        # Maps priority 1..10 → weight 0.5..2.0 (linear).  Default priority=5
        # → weight=1.0 (parity with pre-2026-05-14 behaviour).  This makes
        # high-priority guides (priority>=8) outrank both operational_event
        # entries (weight 0.5) and standard guides in mixed recall results.
        guide_priority = getattr(guide, "priority", None)
        if isinstance(guide_priority, (int, float)) and guide_priority > 0:
            # priority 1 → 0.5; priority 5 → 1.0; priority 10 → 2.0
            guide_weight = 0.5 + (float(guide_priority) - 1.0) * (1.5 / 9.0)
        else:
            guide_weight = 1.0
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
                    "priority": guide_priority,
                },
                origin="config",
                confidence=1.0,
                weight=guide_weight,
                tags=json.dumps(tag_list, ensure_ascii=False),
            )
            count += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("guide_kb: %s upsert failed: %s", mem_id, exc)
            skipped += 1

    # ── Prune orphans (Patch C1, 2026-05-08) ────────────────────────────
    # When a guide YAML is deleted from source, its memory entry must
    # also be removed.  Without this, AutoRecall keeps surfacing the
    # ghost entry forever and may outrank live guides (regression
    # observed 2026-05-07: cab_revise.guide leaked, broke emit_tcf
    # ranking — see ISSUE-AUTORECALL-GUIDE-COMPETITION).  We compare
    # ``guide_*`` memory IDs vs the IDs the source set just produced
    # and delete the diff.
    pruned = 0
    try:
        present_ids = {g.memory_id for g in guides}
        all_mem = store.get_memories(category="usage_guide", limit=10_000)
        for mem in all_mem:
            mid = mem.get("id", "")
            if not mid.startswith("guide_"):
                continue
            if mid in present_ids:
                continue
            origin = mem.get("origin") or (mem.get("metadata") or {}).get("origin")
            if origin != "config":
                # only auto-prune entries we ourselves primed
                continue
            try:
                store.delete_memory(mid)
                pruned += 1
                logger.info("guide_kb: pruned orphan %s", mid)
            except Exception as exc:  # noqa: BLE001
                logger.debug("guide_kb: prune %s failed: %s", mid, exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("guide_kb: prune phase skipped: %s", exc)

    logger.info(
        "guide_kb: %d entries from %s (%d skipped, %d pruned)",
        count, workspace_root, skipped, pruned,
    )
    return {"guide_entries": count, "skipped": skipped, "pruned": pruned}


def prime_workspace_guides(
    workspace_root: Path | str,
    *,
    allow_dim_swap: bool = False,
) -> str:
    """Prime every ``*.guide.yaml`` under ``workspace_root`` and return
    a one-line human-readable status string.

    Thin wrapper around :func:`prime_guides_from_dir` with exception
    swallowing — designed for ``olav init`` and ``olav agent install``
    so a memory backend hiccup (LanceDB lock, embedder timeout) doesn't
    break workspace deployment.  The guides remain on disk; user can
    re-run ``olav kb import-guides`` to retry.

    ``allow_dim_swap=True`` (skill install path): if the existing
    memory table's vector dim doesn't match the embedder, drop +
    recreate it.  Legitimate when re-priming derivative platform
    guides after user changed the embedder config; would be unsafe if
    the table held user-curated rows, but at skill-install time only
    fresh-platform guides exist.

    ``allow_dim_swap=False`` (init path, default): dim mismatch
    surfaces as ``⚠ guides not primed (...)`` — operator must run
    ``olav kb import-guides`` manually after fixing config.

    Returns a status line like ``✓ guides primed: 12`` ready for
    printing.
    """
    import os

    def _run() -> dict:
        return prime_guides_from_dir(Path(workspace_root))

    try:
        result = _run()
    except Exception as exc:  # noqa: BLE001
        # Catch the dim-mismatch error from LanceDBStore.__init__ and
        # retry with the destructive opt-in env var when caller allows.
        cls_name = type(exc).__name__
        if allow_dim_swap and cls_name == "EmbeddingDimMismatchError":
            logger.info(
                "prime_workspace_guides: dim swap detected (%s); "
                "dropping memory table and re-priming", exc,
            )
            prev = os.environ.get("OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION")
            os.environ["OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION"] = "1"
            # Reset the cached store singleton so it picks up the new
            # dim on next get_store() call.
            try:
                from olav.core.memory import reset_store
                reset_store()
            except Exception:  # noqa: BLE001
                pass
            try:
                result = _run()
                n = result.get("guide_entries", 0)
                k = result.get("skipped", 0)
                return (
                    f"✓ guides primed: {n} (memory table re-created "
                    f"after embedder dim change)"
                )
            finally:
                if prev is None:
                    os.environ.pop("OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION", None)
                else:
                    os.environ["OLAV_ALLOW_DESTRUCTIVE_DIM_MIGRATION"] = prev
        logger.warning("prime_workspace_guides failed: %s", exc)
        return f"⚠ guides not primed ({exc})"

    n = result.get("guide_entries", 0)
    k = result.get("skipped", 0)
    p = result.get("pruned", 0)
    if n == 0 and k == 0 and p == 0:
        return "✓ guides primed: 0 (no *.guide.yaml found)"
    parts = [f"✓ guides primed: {n}"]
    if k > 0:
        parts.append(f"{k} skipped")
    if p > 0:
        parts.append(f"{p} orphan(s) pruned")
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} ({', '.join(parts[1:])})"


__all__ = [
    "UsageGuide",
    "discover_guides",
    "prime_guides_from_dir",
    "prime_workspace_guides",
]
