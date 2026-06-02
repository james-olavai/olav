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

**What belongs in expert_knowledge vs SKILL.md** (R92.7 / ADR-0008
follow-up; see ``dev_docs/00 § ISSUE-SKILL-MEMORY-DUPLICATE-CONTRACT``):

* SKILL.md / references/ = the **author's contract** — workflow steps,
  mandatory tool sequence, safety rails. Always reachable via
  ``static_context``; with R92.6 SkillsMiddleware via progressive
  disclosure.
* expert_knowledge memory = the **user's wisdom** — vendor quirks,
  cross-skill patterns, project preferences, ``trace_learner`` output.
  Surfaced via semantic recall when keywords match.

Decision rule before writing ``*.expert.yaml``:

1. Is it a踩坑 lesson ("v1 hit X bug, identify by Y, fix is Z")? → memory
2. A cross-skill pattern ("when ops-lab FAILs, ops-analyze can run X")? → memory
3. A user / project preference? → memory
4. Output of ``trace_learner``? → memory
5. **Just paraphrasing SKILL.md / references workflow?** → **NO** — put it
   in SKILL.md instead. Duplicating content here causes drift +
   double-injection at recall time.

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
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ---- Phase 1.5 scope vocabulary -------------------------------------------

# Three valid scope forms (see dev_docs/63):
#   - "<agent_name>"          e.g. "ops-lab", "ops-analyze"
#   - "shared:<domain>"       e.g. "shared:ops", "shared:audit"
#   - "org"                   user-injected universal knowledge
_AGENT_SCOPE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
_SHARED_SCOPE_PATTERN = re.compile(r"^shared:[a-z][a-z0-9_-]*$")
_ORG_SCOPE = "org"

# Phase 1.5: precedence vocabulary — controls ordering when multiple
# expert entries with the same scope tier compete for a quota slot.
# ``override`` wins over ``default`` (the implicit value); ``advisory``
# loses to ``default``. Surfaces as ``metadata.precedence`` for the
# diversifier to read.
_PRECEDENCE_VALUES = {"override", "default", "advisory"}
_PRECEDENCE_RANK = {"override": 0, "default": 1, "advisory": 2}


def _validate_scope(scope: str, *, source_hint: str = "") -> None:
    """Raise ValueError if ``scope`` is not one of the three valid forms.

    The error message names the file (when ``source_hint`` is provided)
    so YAML authors can find the offending entry quickly.
    """
    if scope == _ORG_SCOPE:
        return
    if _SHARED_SCOPE_PATTERN.match(scope):
        return
    if _AGENT_SCOPE_PATTERN.match(scope):
        return
    where = f"{source_hint}: " if source_hint else ""
    raise ValueError(
        f"{where}scope {scope!r} is invalid. Must be one of: "
        f"<agent_name> (e.g. 'ops-lab'), "
        f"'shared:<domain>' (e.g. 'shared:ops'), "
        f"or 'org' (user-injected, universal). "
        f"See dev_docs/63 § Phase 1.5."
    )


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
    # Phase 1.5: who authored this — auto-populated by discover_experts
    # based on which directory the file was found in. ``shipped`` =
    # came with a plugin; ``user`` = added via ~/.olav/expertise/ or
    # <project>/.olav/expertise/. NOT authored in the YAML.
    source: str = "shipped"
    # Phase 1.5: explicit ordering preference within the same scope
    # tier. Authored in the YAML as ``precedence: override|default|advisory``.
    # ``override`` wins over ``default``; ``advisory`` loses. Default is
    # ``default``. Used for cases where a user's `org` knowledge needs
    # to clearly outrank shipped `shared` knowledge on the same topic.
    precedence: str = "default"

    @classmethod
    def from_yaml(cls, path: Path) -> "ExpertKnowledge":
        """Load + validate one file.  Raises ``KeyError`` for missing
        required fields, ``ValueError`` for type mismatches or invalid
        ``scope`` form (Phase 1.5 — see ``_validate_scope``).
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
        scope = str(data["scope"])
        _validate_scope(scope, source_hint=str(path))
        precedence = str(data.get("precedence", "default")).strip() or "default"
        if precedence not in _PRECEDENCE_VALUES:
            raise ValueError(
                f"{path}: precedence {precedence!r} is invalid. "
                f"Must be one of: {sorted(_PRECEDENCE_VALUES)}."
            )
        return cls(
            topic=str(data["topic"]),
            scope=scope,
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
            precedence=precedence,
        )

    @property
    def memory_id(self) -> str:
        """Deterministic ID — ``expert_<scope>_<topic>`` for idempotent
        upserts.
        """
        return f"expert_{self.scope}_{self.topic}"


def _infer_scope_from_path(path: Path, workspace_root: Path) -> str | None:
    """Infer scope from a file's path under ``workspace_root``.

    The inference adapts to whether ``workspace_root`` points at a
    plugin-level directory (containing skills) or at a single skill
    (containing subagents). The skill name comes either from
    ``rel_parts[0]`` (plugin-level root) or from ``workspace_root.name``
    (skill-level root).

    Recognised relative layouts under ``workspace_root``:

    Plugin-level root (``rel_parts`` includes the skill name):
      - ``shared/<domain>/expertise/...``       → ``shared:<domain>``
      - ``<skill>/shared/expertise/...``        → ``shared:<skill>``
      - ``<skill>/<subagent>/expertise/...``    → ``<skill>-<subagent>``
      - ``<skill>/expertise/...``               → ``<skill>``

    Skill-level root (``workspace_root.name`` is the skill):
      - ``shared/expertise/...``                → ``shared:<workspace_root.name>``
      - ``<subagent>/expertise/...``            → ``<workspace_root.name>-<subagent>``
      - ``expertise/...``                       → ``<workspace_root.name>``

    User-injection layouts:
      - ``expertise/...`` directly under user's ``~/.olav/`` or
        ``<project>/.olav/``                    → ``org``

    The YAML's explicit ``scope`` field is authoritative; this
    inference is used to (a) sanity-check the YAML, (b) auto-default
    when the YAML doesn't declare scope.

    Returns ``None`` when no pattern matches.
    """
    try:
        rel_parts = path.relative_to(workspace_root).parts
    except ValueError:
        return None
    if not rel_parts:
        return None
    skill = workspace_root.name  # may be empty for root-level

    # Skill-level root: rel_parts starts with subagent / "shared" / "expertise"
    # We can't always tell which form we're in; try both, prefer the
    # one that produces a valid scope.

    # Form: shared/<domain>/expertise/...       (plugin-level root)
    if (
        len(rel_parts) >= 4
        and rel_parts[0] == "shared"
        and rel_parts[2] == "expertise"
    ):
        return f"shared:{rel_parts[1]}"

    # Form: <skill>/shared/expertise/...        (plugin-level root)
    if (
        len(rel_parts) >= 4
        and rel_parts[1] == "shared"
        and rel_parts[2] == "expertise"
    ):
        return f"shared:{rel_parts[0]}"

    # Form: <skill>/<subagent>/expertise/...    (plugin-level root)
    if (
        len(rel_parts) >= 4
        and rel_parts[2] == "expertise"
        and rel_parts[0] != "shared"
        and rel_parts[1] != "shared"
    ):
        return f"{rel_parts[0]}-{rel_parts[1]}"

    # Form: shared/expertise/...                (skill-level root)
    if (
        len(rel_parts) >= 3
        and rel_parts[0] == "shared"
        and rel_parts[1] == "expertise"
        and skill
    ):
        return f"shared:{skill}"

    # Form: <subagent>/expertise/...            (skill-level root)
    if (
        len(rel_parts) >= 3
        and rel_parts[1] == "expertise"
        and rel_parts[0] != "shared"
        and skill
    ):
        return f"{skill}-{rel_parts[0]}"

    # Form: expertise/...                       (root-level)
    if rel_parts[0] == "expertise":
        # If we're under a skill-named root, treat as skill-scope; else org
        return skill if skill and skill != ".olav" else _ORG_SCOPE

    return None


def discover_experts(
    workspace_root: Path,
    *,
    user_dirs: list[Path] | None = None,
) -> list[ExpertKnowledge]:
    """Glob every ``*.expert.yaml`` under known expertise layouts.

    Layouts scanned under ``workspace_root`` (treated as ``shipped``):
      - ``<root>/<agent>/expertise/*.expert.yaml``
      - ``<root>/shared/<domain>/expertise/*.expert.yaml``

    User-injection paths (treated as ``source=user``) — scanned when
    they exist on disk:
      - ``~/.olav/expertise/*.expert.yaml``
      - ``<project>/.olav/expertise/*.expert.yaml``

    The YAML's explicit ``scope`` field is authoritative. When it
    matches the path-inferred scope, both agree (sanity confirmed).
    When the YAML omits scope, the inferred value populates it.

    Skips invalid files with a warning rather than aborting.
    """
    experts: list[ExpertKnowledge] = []

    def _load(path: Path, source: str, root_for_inference: Path) -> None:
        try:
            expert = ExpertKnowledge.from_yaml(path)
            expert.source = source
            # Sanity: YAML scope vs path-inferred — log a warning when
            # they disagree (often indicates a misplaced YAML).
            inferred = _infer_scope_from_path(path, root_for_inference)
            if inferred and inferred != expert.scope:
                logger.warning(
                    "expert_kb: %s declares scope=%r but its path "
                    "implies scope=%r — using YAML's value, but "
                    "consider moving the file or fixing the field",
                    path, expert.scope, inferred,
                )
            experts.append(expert)
        except (KeyError, ValueError, yaml.YAMLError) as exc:
            logger.warning("expert_kb: failed to load %s — %s", path, exc)

    # ── shipped paths under workspace_root ────────────────────────────
    if workspace_root.exists():
        for path in sorted(workspace_root.rglob("expertise/*.expert.yaml")):
            _load(path, source="shipped", root_for_inference=workspace_root)
    else:
        logger.debug(
            "expert_kb: workspace_root %s missing — skipping shipped scan",
            workspace_root,
        )

    # ── user-injection paths ──────────────────────────────────────────
    candidate_dirs: list[Path] = []
    if user_dirs is not None:
        candidate_dirs.extend(user_dirs)
    else:
        # Default user dirs: ~/.olav/expertise + <cwd>/.olav/expertise
        home = Path.home() / ".olav" / "expertise"
        proj = Path.cwd() / ".olav" / "expertise"
        for d in (home, proj):
            if d.exists() and d.is_dir() and d not in candidate_dirs:
                candidate_dirs.append(d)

    for udir in candidate_dirs:
        if not udir.exists():
            continue
        # User dirs are flat: every *.expert.yaml is org-scope by default
        for path in sorted(udir.rglob("*.expert.yaml")):
            _load(path, source="user", root_for_inference=udir.parent)

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
            "source": expert.source,
            "precedence": expert.precedence,
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
