# LEGACY-KEEP: v0.19 cut audit re-evaluated this module — the plugin
# framework *wraps* these classes (``olav.plugins.middleware.memory_recall``
# imports AutoRecallMiddleware, ``...memory_capture`` imports
# AutoCaptureMiddleware, and ``cli/daemon.py`` imports apply_time_decay).
# The plugins don't replace this module; they register its classes as
# plugins. No removal target.
"""Memory Middleware for OLAV Agentic Memory System.

Backing implementation for the ``olav.plugins.middleware.memory_recall``
and ``olav.plugins.middleware.memory_capture`` plugins, plus the
``apply_time_decay()`` daemon hook called from ``cli/daemon.py``.

Implements Phase 2 of the LANCEDB_MEMORY_SYSTEM_INTEGRATION plan:
  - AutoRecallMiddleware:  Pre-processor — injects relevant historical context
                           into the user prompt *before* agent thinking.
  - AutoCaptureMiddleware: Post-processor — extracts key facts/decisions from
                           the conversation and stores them into LanceDB after
                           a successful task execution.
  - apply_time_decay():    Applies temporal weight decay to all memory entries.
                           Formula: weight = max(0.1, 0.5 + 0.5 * exp(-age_days / half_life))
  - schedule_time_decay(): Optional background scheduler (requires apscheduler).
"""

import json
import logging
import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from olav.core.memory import MEMORY_TABLE, hybrid_search

if TYPE_CHECKING:
    from olav.core.memory import LanceDBStore

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

RECALL_TOP_K = 3  # Max memories to inject per query
CAPTURE_MAX_ITEMS = 3  # Max fact/decision items to extract per conversation
DECAY_HALF_LIFE_DAYS = 60  # Time-decay half-life (days)
DECAY_WEIGHT_FLOOR = 0.1  # Minimum weight after full decay

_EXTRACT_PROMPT = """\
You are a precise fact extractor. Given the following conversation between a user and an AI assistant,
extract at most {max_items} key items worth remembering for future sessions.
Output ONLY a JSON array. Each item must have:
  - "text": A concise human-readable statement of the fact/decision (max 120 chars).
  - "category": One of "fact", "decision", or "preference".
  - "importance": A float 0.0–1.0 indicating how important this is to remember.
  - "tags": A list of 2-5 entity/topic tags relevant to this item.
    Tags should be specific identifiers (device names, protocol names,
    IP addresses, tool names) rather than generic words.

Rules:
- Only extract genuinely useful, non-trivial information.
- If nothing worth remembering occurred, return: []
- Do not include generic greetings or error messages.
- Do not duplicate information already covered by obvious conversation context.
- Tags must be lowercase, no spaces (use hyphens for multi-word).

Conversation:
{conversation}

JSON array only, no extra text:"""


# ─────────────────────────────────────────────────────────────────────────────
# Auto-Recall
# ─────────────────────────────────────────────────────────────────────────────


class AutoRecallMiddleware:
    """Pre-processor that injects relevant memories into the user prompt.

    Queries LanceDB with the incoming user query (vector + text hybrid) and
    prepends a ``<relevant-memories>`` XML block to the last user message,
    giving the agent historical context before it starts reasoning.

    Usage::

        recall = AutoRecallMiddleware(store)
        augmented_input = await recall.enrich(user_input, scope="ops")
    """

    def __init__(
        self,
        store: "LanceDBStore",
        top_k: int | None = None,
        min_score_threshold: float = 0.0,
        budget_monitor: Any = None,
        current_agent: str | None = None,
    ) -> None:
        self._store = store
        # ARCH-18 #3: top_k defaults to the tier-appropriate value from
        # TIER_DEFAULTS — small-context models get 1 memory, medium 2,
        # large 3. Explicit ``top_k=`` still overrides. Resolved lazily
        # via ``_resolve_top_k`` so tests / callers can change tier
        # between constructions (avoids caching an import-time value).
        self._top_k = top_k  # None ⇒ resolve from model_tier at call time
        self._min_score = min_score_threshold
        # ARCH-19 #A: optional ContextBudgetMonitor. When attached, recall
        # injection is skipped on non-first turns once the budget headroom
        # drops below the tier-specific ``recall_skip_headroom_pct`` — the
        # goal is keeping the smallest-tier run from burning its last 1-2K
        # tokens on historical hints instead of the live task.
        self._budget_monitor = budget_monitor
        # R87 Phase 1.5 (dev_docs/63): the active agent's name (e.g.
        # ``ops-lab``).  When set, expert_knowledge entries are filtered
        # by ``scope IN (current_agent, shared:<domain>, org)`` — so
        # SRL lab knowledge stays out of writer / core / audit recalls.
        # ``None`` falls back to Phase 1 behaviour (vector relevance only).
        self._current_agent = current_agent

    def _resolve_top_k(self) -> int:
        if self._top_k is not None:
            return self._top_k
        try:
            from olav.core.config import get_llm_config, tier_default
            tier = get_llm_config().model_tier
            return int(tier_default(tier, "recall_top_k", RECALL_TOP_K))
        except Exception as exc:
            logger.debug("AutoRecall tier resolution failed: %s", exc)
            return RECALL_TOP_K

    def _should_skip_for_budget(self) -> bool:
        """Return True when injecting recall would push over the per-tier
        headroom (ARCH-19 #A). First turns bypass this check — cold-start
        hints are always worth a small spend.

        A missing budget monitor is treated as unlimited budget (never skip).
        """
        monitor = self._budget_monitor
        if monitor is None:
            return False
        try:
            from olav.core.config import get_llm_config, tier_default
            tier = get_llm_config().model_tier
            headroom_pct = float(tier_default(tier, "recall_skip_headroom_pct", 0.0))
        except Exception as exc:
            logger.debug("AutoRecall headroom resolution failed: %s", exc)
            return False
        if headroom_pct <= 0:
            return False
        try:
            snap = monitor.snapshot()
            remaining_pct = 1.0 - float(snap.get("ratio", 0.0))
        except Exception as exc:
            logger.debug("AutoRecall budget snapshot failed: %s", exc)
            return False
        return remaining_pct < headroom_pct

    def _embed(self, text: str) -> list[float] | None:
        """Embed text via the configured embedding backend (api or local)."""
        from olav.core.embedder import embed_text

        return embed_text(text)

    _reranker_instance: Any = None  # lazy-cached, _CACHE_SENTINEL = "init not tried"
    _reranker_init_attempted: bool = False

    def _get_reranker(self):
        """Return a configured Reranker instance, or None if disabled.

        Reads ``reranker`` block from ``.olav/config/api.json``:

            "reranker": {
              "enabled": true,
              "model": "bbjson/bge-reranker-base",
              "base_url": "http://192.168.100.12:11434"
            }

        Disable via env: ``OLAV_RERANKER_DISABLE=1``. Failed init →
        returns None (logs at debug); falls back to current diversifier
        path with no behaviour change.
        """
        if self._reranker_init_attempted:
            return self._reranker_instance
        self._reranker_init_attempted = True

        import os
        if os.environ.get("OLAV_RERANKER_DISABLE"):
            return None

        cfg: dict = {}
        try:
            import json
            from pathlib import Path
            api_path = Path(".olav/config/api.json")
            if not api_path.exists():
                # Search upward for the config dir
                for p in [Path.cwd(), *Path.cwd().parents]:
                    cand = p / ".olav" / "config" / "api.json"
                    if cand.exists():
                        api_path = cand
                        break
            if api_path.exists():
                cfg = (json.loads(api_path.read_text()) or {}).get("reranker") or {}
        except Exception:
            cfg = {}
        if not cfg.get("enabled"):
            return None

        # Strict mode (R99/S2): every required field must be explicit in
        # api.json.  Silent fallback to the Ollama-as-bi-encoder path
        # (which doesn't yield true cross-encoder semantics — see
        # dev_docs/67) caused the "looks running but actually broken"
        # trap we hit twice.  No defaults; missing fields → log + skip.
        kind = cfg.get("kind")
        base_url = cfg.get("base_url")
        if not kind:
            logger.warning(
                "AutoRecall reranker enabled but 'kind' is not set in "
                "api.json reranker block; disabling.  Set kind to "
                "'llama_cpp' (recommended) or 'ollama' (legacy)."
            )
            return None
        if not base_url:
            logger.warning(
                "AutoRecall reranker enabled but 'base_url' is not set; "
                "disabling."
            )
            return None
        kind = kind.lower()

        try:
            if kind in ("llama_cpp", "llamacpp", "llama"):
                # llama-server with --reranking flag.  Preserves the
                # BERT cross-encoder rerank head → real relevance
                # scores via POST /rerank (NOT /v1/embeddings).
                from olav.core.memory.reranker import LlamaCppReranker
                self._reranker_instance = LlamaCppReranker(
                    base_url=base_url, column="text",
                )
            elif kind == "ollama":
                # Legacy: Ollama-served reranker model used as
                # bi-encoder over /api/embeddings.  Does NOT yield true
                # cross-encoder semantics — see dev_docs/67.  Requires
                # 'model' field.
                model_name = cfg.get("model")
                if not model_name:
                    logger.warning(
                        "reranker kind=ollama requires 'model' field; "
                        "disabling.",
                    )
                    return None
                from olav.core.memory.reranker import OllamaEmbeddingReranker
                self._reranker_instance = OllamaEmbeddingReranker(
                    model_name=model_name, base_url=base_url, column="text",
                )
            else:
                logger.warning(
                    "Unknown reranker kind=%r; expected 'llama_cpp' or "
                    "'ollama'.  Disabling.", kind,
                )
                return None
            logger.info(
                "AutoRecall reranker enabled: kind=%s model=%s base=%s",
                kind, cfg.get("model"), base_url,
            )
        except Exception as exc:
            logger.debug("AutoRecall reranker init failed: %s", exc)
            self._reranker_instance = None
        return self._reranker_instance

    def _rerank_memories(
        self, reranker, query: str, memories: list[dict],
    ) -> list[dict]:
        """Run reranker over the candidate list and return reordered list.

        Converts dict list → arrow table → reranker.rerank_vector →
        sorted dict list. Failures are silent — return original order.
        """
        if not memories:
            return memories
        try:
            import pyarrow as pa
            # Build a minimal arrow table — only the column the reranker
            # needs ("text") and an opaque index column for join-back.
            texts = [m.get("text") or "" for m in memories]
            table = pa.table({"text": texts, "_idx": list(range(len(memories)))})
            ranked = reranker.rerank_vector(query, table)
            new_order = ranked.column("_idx").to_pylist()
            return [memories[i] for i in new_order]
        except Exception as exc:
            logger.debug("AutoRecall rerank failed (non-fatal): %s", exc)
            return memories

    # Per-category hard caps — entries beyond the cap are dropped.
    # ``query_pattern`` is the noisy category: repeat-asked questions
    # accumulate near-duplicate entries that all rank near the top of
    # hybrid search.  CC-1c (dev_docs/62 § "CC-1c"): cap raised 1 → 2.
    # The original cap=1 paired with an empty quota meant captured SQL
    # never reached the agent for queries with ≥1 captured pattern;
    # cap=2 + quota=2 (below) gives the agent a reliable foothold of
    # "the 2 best historical answers" without re-introducing the
    # poisoning floor (cap protects against runaway accumulation).
    _CATEGORY_CAPS = {
        "query_pattern": 2,
        # R87 Phase 1.5: cap matches the quota so sub-quota tiers
        # (1 agent + 1 shared + 1 org) act as hard slots.  Without
        # the cap, the diversifier's leftover-fill pass would let
        # extra expert_knowledge entries past the quota — defeating
        # the "users always get 1 org slot" guarantee when many
        # agent-scope entries are present.
        "expert_knowledge": 3,
    }

    # Per-category fetch budget for the curated-category path.
    # ``_gather_candidates`` issues a vector-search per category to
    # guarantee coverage independent of cross-category RRF biases.
    # Numbers are tuned for a small fleet (≤10 platforms) — schemas
    # and value distributions are 6-8 entries on the interface concept
    # alone, so 6 per category catches the cross-platform variants.
    # ISSUE-SCHEMA-PUSH-VS-PULL (dev_docs/00, 2026-04-30):
    # ``schema_knowledge`` and ``value_distribution`` removed —
    # ``prime_memory_at_ingest`` no longer writes them by default;
    # agent uses ``describe_table`` tool to introspect on demand.
    # ``usage_guide`` over-fetch kept at 4 (matched old budget) —
    # bumping to 6 would inflate total prompt because guide bodies
    # are 3-6 KB each.  Smaller K, smaller injection.
    _CATEGORY_FETCH = {
        "query_pattern": 3,
        "usage_guide": 4,
        "expert_knowledge": 3,
    }

    # Per-category minimum quotas — reserves slots so a cross-platform
    # fleet (cisco + junos) gets schema/value entries from BOTH platforms,
    # even when vector search prefers entries from the larger platform.
    # Quotas are filled from the over-fetched ranking by category, then
    # the remainder is filled by global rank.  ``memory_primer`` writes
    # ``schema_knowledge`` (per auto-view) and ``value_distribution``
    # (per state-like column) entries that are critical for SQL accuracy.
    #
    # 5 slots each is the empirical floor for a cisco+junos mixed fleet:
    # in hybrid (vector+BM25) ranking the platform-specific view
    # (e.g. ``v_show_interfaces_terse_auto`` for Junos) routinely lands
    # at rank 4-5 within its category, so smaller quotas leave the
    # cross-platform answer incomplete.  Each entry is ~300 chars, so
    # 5 schemas + 5 values + ~3 fact/query = ~4 KB context — well under
    # 1% of a 200 K large-tier window.
    _CATEGORY_QUOTAS = {
        # ISSUE-SCHEMA-PUSH-VS-PULL (dev_docs/00, 2026-04-30):
        # schema_knowledge + value_distribution removed.  Slots:
        # was 2+2+2+3+1+3=13 → now 0+0+2+5+1+3=11 (≈18% drop in
        # recall_top_k effective load + bigger usage_guide budget).
        "query_pattern": 2,
        # ISSUE-SCHEMA-PUSH-VS-PULL: keep at 3.  Each guide body is
        # 3-6 KB so quota=5 injects 15-25 KB by itself.  Goal of the
        # whole refactor was less prompt, not redistributed slots.
        "usage_guide": 3,
        # R85 δ2 — format references (mermaid layout, CSV layout, ...)
        # primed from *.format.yaml.  Top-1 most-relevant format hits
        # the prompt; the agent uses it for the format_and_export call.
        "format_guide": 1,
        # R87 Phase 1 → 1.5 (dev_docs/63) — vendor / platform-specific
        # expert knowledge.  Per-agent scoped via the YAML's ``scope``
        # field.  Phase 1.5 grants 3 slots (was 1) so the diversifier
        # can reserve one slot for each scope tier:
        #   * 1 × agent-scope  (own-agent expertise)
        #   * 1 × shared:domain (cross-agent within the domain)
        #   * 1 × org           (user-injected universal — must always
        #                        get a slot when present, per the
        #                        business-model promise that users own
        #                        their workflow)
        # Empty tiers fall back to vector ranking; no slot wasted.
        # value_distribution dropped 4 → 2 to fund this; total
        # 2+2+2+3+1+3=13 unchanged.
        "expert_knowledge": 3,
    }

    # Phase 1.5 — sub-quota per scope tier within expert_knowledge.
    # Caps the agent / shared / org buckets so a flood of own-agent
    # entries can't crowd out user-injected ``org`` knowledge.  Used
    # by ``_diversify_by_category`` only when the category is
    # ``expert_knowledge``.
    _EXPERT_SUBQUOTAS = {"agent": 1, "shared": 1, "org": 1}

    # Per-category L2 distance thresholds — drop hits with distance
    # ABOVE this value as too weak to inject.  Empty until we have
    # confidence the gating doesn't side-effect agent behaviour.
    #
    # Phase 1.5b experiment (dev_docs/62): set ``usage_guide: 1.6`` to
    # filter Chinese-positive vs English-negative overlap (probe data
    # at tests/integration/test_recall_hit_rate.py).  N=5 bench then
    # showed C4-topo correctness flipped 100% → 0% — but a follow-up
    # bisect against pristine Phase 1.5 code reproduced the 0% even
    # WITHOUT the threshold, so the regression is environmental
    # (writer subagent path).  Threshold infra retained for future
    # Tags-FTS-driven gating; dict left empty so it's a no-op.
    _CATEGORY_DISTANCE_THRESHOLD: dict[str, float] = {}

    def _allowed_expert_scopes(self) -> set[str] | None:
        """Phase 1.5 scope filter set for ``expert_knowledge``.

        Returns a set of allowed scope strings:
          - ``current_agent``        — own-agent expertise
          - ``shared:<domain>``      — domain-shared expertise
          - ``org``                  — user-injected universal

        Domain is inferred as the part of ``current_agent`` before the
        first ``-`` (``ops-lab`` → ``ops``).

        ``None`` when ``current_agent`` is unset — caller falls back to
        no filtering (Phase 1 behaviour).
        """
        if not self._current_agent:
            return None
        domain = self._current_agent.split("-", 1)[0]
        return {self._current_agent, f"shared:{domain}", "org"}

    @staticmethod
    def _row_distance(row: dict) -> float | None:
        """Extract L2 distance from a search result row.

        ``LanceDBStore.search_by_vector`` exposes ``_distance`` as
        ``score`` in the returned dict; older callers may set
        ``_distance`` directly.  Try both.
        """
        for k in ("score", "_distance"):
            v = row.get(k)
            if v is None:
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
        return None

    def _gather_candidates(
        self,
        query_text: str,
        query_vector: list[float] | None,
        scope: str | None,
        top_k: int,
    ) -> list[dict]:
        """Gather candidates with explicit per-category coverage.

        Issues one vector-search per curated category (so the curated
        ``schema_knowledge`` / ``value_distribution`` / ``query_pattern``
        entries from ``memory_primer`` always have a fair shot), then
        runs a regular hybrid search to cover the long-tail categories
        (``fact``, ``decision``, ``preference``, ``audit``).  Returns a
        ranked list with curated entries first (in their per-category
        order) followed by the hybrid results, deduped by id.
        """
        out: list[dict] = []
        seen: set = set()

        def _add(items: list[dict]) -> None:
            for m in items:
                mid = m.get("id")
                if not mid or mid in seen:
                    continue
                out.append(m)
                seen.add(mid)

        # Curated per-category fetch — vector only, since BM25 against
        # a generic question doesn't help for short structural entries.
        if query_vector:
            allowed_expert_scopes = self._allowed_expert_scopes()
            for cat, n in self._CATEGORY_FETCH.items():
                # R87 Phase 1.5 (dev_docs/63): ``expert_knowledge`` is
                # filtered by ``scope IN (current_agent, shared:<domain>,
                # org)`` when ``current_agent`` is known.  The store API
                # takes a single scope string, so we over-fetch with no
                # scope filter and apply the IN-set filter in Python.
                # When ``current_agent`` is unset (legacy callers),
                # fall back to Phase 1 behaviour: no filter, rely on
                # vector relevance + tags for separation.
                fetch_scope = None if cat == "expert_knowledge" else scope
                fetch_limit = n
                if cat == "expert_knowledge" and allowed_expert_scopes:
                    # Over-fetch so that after the Python-side scope
                    # filter we still have ≥ ``n`` candidates ready.
                    fetch_limit = n * 4
                try:
                    rows = self._store.search_by_vector(
                        query_vector=query_vector,
                        limit=fetch_limit,
                        category=cat,
                        scope=fetch_scope,
                    )
                    if cat == "expert_knowledge" and allowed_expert_scopes:
                        rows = [
                            r for r in rows
                            if r.get("scope") in allowed_expert_scopes
                        ][:n]
                    _add(rows)
                except Exception as e:
                    logger.debug("curated fetch %s failed: %s", cat, e)

        # Long-tail hybrid pass — covers fact/decision/preference/audit
        # plus picks up any high-relevance entry the curated pass missed.
        try:
            if query_vector:
                hybrid = hybrid_search(
                    store=self._store,
                    query=query_text,
                    query_vector=query_vector,
                    limit=top_k * 2,
                    scope=scope,
                )
            else:
                hybrid = self._store.search_by_text(
                    query=query_text,
                    limit=top_k * 2,
                    scope=scope,
                )
            _add(hybrid)
        except Exception as e:
            logger.debug("long-tail hybrid fetch failed: %s", e)

        return out

    def _diversify_by_category(
        self, memories: list[dict], limit: int
    ) -> list[dict]:
        """Apply per-category caps + quotas to a ranked memory list.

        1. Drop entries whose category has hit its cap.
        2. Reserve up to ``_CATEGORY_QUOTAS[c]`` slots for each quota
           category — fill from the highest-ranked entries of that
           category present in ``memories``.
        3. Fill remaining slots from the leftover global ranking.
        4. Preserve overall rank order in the final output so the
           agent sees most-relevant first.
        """
        if not memories:
            return memories

        # Pass 1: filter caps + index by category.
        # NOTE: expert_knowledge skips the Pass-1 cap so the Pass-2
        # sub-quota selector can see ALL candidates (one of each
        # scope tier). The cap is then enforced in Pass 3 leftover
        # fill so the final output still respects ``_CATEGORY_CAPS``.
        kept: list[dict] = []
        per_cat: dict[str, list[dict]] = {}
        cap_counts: dict[str, int] = {}
        for m in memories:
            cat = m.get("category") or "fact"
            cap = self._CATEGORY_CAPS.get(cat)
            if (
                cap is not None
                and cat != "expert_knowledge"
                and cap_counts.get(cat, 0) >= cap
            ):
                continue
            kept.append(m)
            per_cat.setdefault(cat, []).append(m)
            cap_counts[cat] = cap_counts.get(cat, 0) + 1

        # Pass 2: reserve quota slots for each quota category.
        chosen_ids: set = set()
        chosen: list[dict] = []

        def _scope_tier(memory: dict) -> str:
            """Phase 1.5: classify an expert_knowledge entry's scope
            into one of the sub-quota tiers."""
            scope = (memory.get("scope") or "").strip()
            if scope == "org":
                return "org"
            if scope.startswith("shared:"):
                return "shared"
            return "agent"

        # Phase 1.5: precedence rank — override < default < advisory.
        # Lower number = higher priority within same scope tier.
        _PREC_RANK = {"override": 0, "default": 1, "advisory": 2}

        def _precedence_rank(memory: dict) -> int:
            # LanceDB stores ``metadata`` as a JSON string in many rows.
            # Decode if necessary; treat non-dict / unparseable as empty
            # (precedence falls back to "default" via the dict get default).
            md = memory.get("metadata") or {}
            if isinstance(md, str):
                try:
                    md = json.loads(md)
                except (TypeError, ValueError):
                    md = {}
            if not isinstance(md, dict):
                md = {}
            return _PREC_RANK.get(md.get("precedence"), 1)

        for cat, quota in self._CATEGORY_QUOTAS.items():
            cat_entries = per_cat.get(cat, [])
            if cat == "expert_knowledge":
                # Phase 1.5: pick at most ``_EXPERT_SUBQUOTAS[tier]``
                # entries from each scope tier (preserving rank order
                # within each tier), then if any of the 3 quota slots
                # is left over (because a tier is absent), fill it
                # with the next-best expert_knowledge entry regardless
                # of tier.
                #
                # Within a tier, ``precedence: override`` outranks
                # ``default`` (and ``advisory`` is demoted) — sort the
                # tier-eligible candidates accordingly while preserving
                # vector-rank as the secondary key.
                tier_counts: dict[str, int] = {}
                tier_picks: list[dict] = []
                # Stable-sort by precedence (then preserve original order via
                # enumerate index — vector-rank tiebreak)
                ranked_entries = sorted(
                    enumerate(cat_entries),
                    key=lambda iv: (_precedence_rank(iv[1]), iv[0]),
                )
                for _, m in ranked_entries:
                    if len(tier_picks) >= quota:
                        break
                    tier = _scope_tier(m)
                    if tier_counts.get(tier, 0) >= self._EXPERT_SUBQUOTAS.get(tier, 0):
                        continue
                    tier_picks.append(m)
                    tier_counts[tier] = tier_counts.get(tier, 0) + 1
                # Top up unused slots from leftover entries
                if len(tier_picks) < quota:
                    picked_ids = {p.get("id") for p in tier_picks}
                    for m in cat_entries:
                        if len(tier_picks) >= quota:
                            break
                        if m.get("id") in picked_ids:
                            continue
                        tier_picks.append(m)
                # Note: we deliberately don't reorder by source=user here —
                # the quota slot for ``org`` already guarantees a
                # user-injected entry is present when one exists; the
                # final Pass 4 sort by global rank then puts entries in
                # vector-relevance order across categories. If a future
                # bench shows the LLM ignores user content buried mid-block
                # we can revisit (e.g. front-load user-source within the
                # expert_knowledge group post-Pass-4).
                cat_entries_to_add = tier_picks
            else:
                cat_entries_to_add = cat_entries[:quota]

            for m in cat_entries_to_add:
                mid = m.get("id")
                if mid in chosen_ids:
                    continue
                chosen.append(m)
                chosen_ids.add(mid)
                if len(chosen) >= limit:
                    break
            if len(chosen) >= limit:
                break

        # Pass 3: fill remaining slots from the global ranking — but
        # respect per-category caps so e.g. expert_knowledge stays at
        # its 3-slot Phase 1.5 cap even when many candidates are
        # available.  Track post-quota counts per category.
        post_quota_counts: dict[str, int] = {}
        for m in chosen:
            c = m.get("category") or "fact"
            post_quota_counts[c] = post_quota_counts.get(c, 0) + 1
        for m in kept:
            if len(chosen) >= limit:
                break
            mid = m.get("id")
            if mid in chosen_ids:
                continue
            cat = m.get("category") or "fact"
            cap = self._CATEGORY_CAPS.get(cat)
            if cap is not None and post_quota_counts.get(cat, 0) >= cap:
                continue
            chosen.append(m)
            chosen_ids.add(mid)
            post_quota_counts[cat] = post_quota_counts.get(cat, 0) + 1

        # Pass 4: sort back to global rank order so highest-relevance
        # entries appear first in the prompt block.
        rank_index = {id(m): i for i, m in enumerate(memories)}
        chosen.sort(key=lambda m: rank_index.get(id(m), 1_000_000))
        return chosen

    def _format_memory_block(self, memories: list[dict]) -> str:
        """Format recalled memories as an XML context block."""
        if not memories:
            return ""
        lines = ["<relevant-memories>"]
        for i, m in enumerate(memories, 1):
            cat = m.get("category", "fact")
            text = m.get("text", "").strip()
            ts = m.get("timestamp")
            date_str = ""
            if ts:
                try:
                    if isinstance(ts, datetime):
                        date_str = f" [{ts.strftime('%Y-%m-%d')}]"
                    else:
                        date_str = f" [{str(ts)[:10]}]"
                except Exception as e:
                    logger.debug("memory timestamp format failed: %s", e)
            lines.append(f"  <memory id='{i}' category='{cat}'{date_str}>{text}</memory>")
        lines.append("</relevant-memories>")
        return "\n".join(lines)

    async def enrich(
        self,
        input_: str | dict,
        scope: str = "global",
        turn: int = 1,
    ) -> str | dict:
        """Enrich the input with recalled memories.

        Args:
            input_: The user input (str or LangGraph messages dict).
            scope: Memory scope to query (e.g. agent name or "global").
            turn: 1-indexed turn number (ARCH-19 #A). turn=1 always
                injects — the cold-start hint is too cheap to skip. From
                turn=2 onwards the caller-supplied ``budget_monitor`` can
                veto injection when the per-tier headroom drops below the
                configured threshold.

        Returns:
            Enriched input with memory context prepended to the last user message.
        """
        # ARCH-19 #A — budget guard for non-first turns.
        if turn > 1 and self._should_skip_for_budget():
            logger.debug(
                "AutoRecall skipped (turn=%d) — budget headroom below threshold",
                turn,
            )
            return input_

        try:
            # Extract query text from input
            if isinstance(input_, str):
                query_text = input_
            elif isinstance(input_, dict):
                messages = input_.get("messages", [])
                # Get the last user message content
                query_text = ""
                for m in reversed(messages):
                    content = (
                        m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
                    )
                    role = m.get("role", "") if isinstance(m, dict) else getattr(m, "type", "")
                    if role in ("human", "user") and content:
                        query_text = content
                        break
            else:
                return input_

            if not query_text:
                return input_

            # Check if memory table exists and has rows
            if not self._store.table_exists(MEMORY_TABLE):
                return input_
            try:
                if self._store.get_table(MEMORY_TABLE).count_rows() == 0:
                    return input_
            except Exception:
                return input_

            # R83.4-followup: per-category fetch + diversifier.
            #
            # A single hybrid_search with limit=top_k consistently
            # downranked ``schema_knowledge`` entries (RRF-fused vector +
            # BM25 promoted near-duplicate ``query_pattern`` rows from
            # repeat-asked questions, leaving only 1 of 6 schemas in the
            # top-24).  We instead fetch each curated category
            # explicitly and merge with a hybrid pass for the long-tail
            # categories (fact, decision, preference, audit), so the
            # agent always sees cross-platform schema + value entries
            # primed by ``memory_primer``.
            query_vector = self._embed(query_text)
            effective_top_k = self._resolve_top_k()

            raw_memories = self._gather_candidates(
                query_text, query_vector, scope, effective_top_k,
            )
            # R99 Tier 1: optional second-stage rerank.
            # When enabled, the reranker fully owns ordering — the
            # downstream `_diversify_by_category` is skipped so its
            # per-category quotas don't override the cross-encoder's
            # global relevance judgment. Without this skip, the
            # diversifier still hands 2 slots to query_patterns
            # regardless of how the reranker scored them. (Ch8 #6
            # debug 2026-04-28 surfaced this.)
            reranker = self._get_reranker()
            if reranker is not None and raw_memories:
                raw_memories = self._rerank_memories(
                    reranker, query_text, raw_memories
                )
                memories = raw_memories[:effective_top_k]
            else:
                memories = self._diversify_by_category(raw_memories, effective_top_k)

            if not memories:
                return input_

            context_block = self._format_memory_block(memories)
            if not context_block:
                return input_

            # Bump access_count for every recalled memory (non-blocking)
            for mem in memories:
                try:
                    self._store.update_memory(
                        mem["id"],
                        access_count=(mem.get("access_count") or 0) + 1,
                    )
                except Exception as e:
                    logger.debug("access_count bump failed for %s: %s", mem.get("id"), e)

            # Prepend to user message
            enriched_text = f"{context_block}\n\n{query_text}"
            logger.info(
                f"AutoRecall: injected {len(memories)} memories into prompt (scope={scope})"
            )

            if isinstance(input_, str):
                return enriched_text
            else:
                # Mutate the last user message in the messages list
                messages = list(input_.get("messages", []))
                for i in range(len(messages) - 1, -1, -1):
                    m = messages[i]
                    role = m.get("role", "") if isinstance(m, dict) else getattr(m, "type", "")
                    if role in ("human", "user"):
                        if isinstance(m, dict):
                            messages[i] = {**m, "content": enriched_text}
                        else:
                            m.content = enriched_text
                        break
                return {**input_, "messages": messages}

        except Exception as e:
            logger.warning(f"AutoRecall.enrich failed (non-fatal): {e}")
            return input_  # Always return original on error


# ─────────────────────────────────────────────────────────────────────────────
# Auto-Capture
# ─────────────────────────────────────────────────────────────────────────────


class AutoCaptureMiddleware:
    """Post-processor that extracts facts/decisions and stores them in LanceDB.

    After a successful agent invocation, this middleware:
    1. Extracts the conversation from the result.
    2. Calls a compact LLM prompt to identify ≤3 key facts/decisions.
    3. Embeds and stores each item in LanceDB (with deduplication).

    Usage::

        capture = AutoCaptureMiddleware(store, llm)
        await capture.process(original_input, agent_result, scope="ops")
    """

    def __init__(
        self,
        store: "LanceDBStore",
        llm,  # LangChain BaseChatModel
        max_items: int = CAPTURE_MAX_ITEMS,
        similarity_dedup_threshold: float | None = None,
    ) -> None:
        self._store = store
        self._llm = llm
        self._max_items = max_items
        # Read threshold from config if not explicitly provided, so it can be
        # overridden via api.json["memory"]["dedup_threshold"] or the
        # OLAV_MEMORY_DEDUP_THRESHOLD env var without touching code.
        if similarity_dedup_threshold is not None:
            self._dedup_threshold = similarity_dedup_threshold
        else:
            try:
                from olav.core.config import get_memory_config

                self._dedup_threshold = get_memory_config().dedup_threshold
            except Exception:
                self._dedup_threshold = 0.92

    def _embed(self, text: str) -> list[float] | None:
        """Embed text via the configured embedding backend (api or local)."""
        from olav.core.embedder import embed_text

        return embed_text(text)

    def _build_conversation_text(self, original_input, result: dict) -> str:
        """Build a text representation of the conversation from input + result."""
        parts = []

        # Original user message
        if isinstance(original_input, str):
            parts.append(f"User: {original_input}")
        elif isinstance(original_input, dict):
            for m in original_input.get("messages", []):
                role = (
                    m.get("role", "unknown")
                    if isinstance(m, dict)
                    else getattr(m, "type", "unknown")
                )
                content = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
                parts.append(f"{role.capitalize()}: {content}")

        # Agent result messages
        result_messages = result.get("messages", [])
        for m in result_messages[-6:]:  # Last 6 messages
            role = getattr(m, "type", None) or (
                m.get("role", "unknown") if isinstance(m, dict) else "unknown"
            )
            content = getattr(m, "content", None) or (
                m.get("content", "") if isinstance(m, dict) else ""
            )
            if content and role in ("ai", "assistant", "human", "user"):
                parts.append(f"{role.capitalize()}: {str(content)[:500]}")

        return "\n".join(parts)

    def _is_duplicate(self, text: str, scope: str) -> bool:
        """Check if a very similar memory already exists (vector similarity)."""
        vector = self._embed(text)
        if vector is None:
            return False
        try:
            existing = self._store.search_by_vector(
                query_vector=vector,
                limit=1,
                scope=scope,
            )
            if existing:
                score = existing[0].get("score")
                # LanceDB returns distance (lower = more similar)
                if score is not None and score < (1.0 - self._dedup_threshold):
                    logger.debug(f"AutoCapture: dedup hit (score={score:.3f}): {text[:60]}")
                    return True
        except Exception as e:
            logger.debug("AutoCapture dedup lookup failed: %s", e)
        return False

    async def process(
        self,
        original_input,
        result: dict,
        scope: str = "global",
    ) -> None:
        """Extract and store key facts/decisions from the conversation.

        Args:
            original_input: The original agent input (str or dict).
            result: The agent result dict (from ainvoke).
            scope: Memory scope for storage.
        """
        try:
            if not result or result.get("status") == "error":
                return  # Don't capture from failed runs

            conversation = self._build_conversation_text(original_input, result)
            if len(conversation.strip()) < 50:
                return  # Nothing to extract

            # Use LLM to extract facts/decisions
            prompt = _EXTRACT_PROMPT.format(
                max_items=self._max_items,
                conversation=conversation[:3000],  # truncate to avoid huge context
            )

            try:
                from langchain_core.messages import HumanMessage

                response = await self._llm.ainvoke([HumanMessage(content=prompt)])
                raw = response.content.strip()
            except Exception as e:
                logger.warning(f"AutoCapture: LLM extraction failed: {e}")
                return

            # Parse JSON response
            try:
                # Strip markdown code fences if any
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                items = json.loads(raw.strip())
                if not isinstance(items, list):
                    return
            except Exception as e:
                logger.debug(f"AutoCapture: JSON parse failed: {e}. Raw: {raw[:100]}")
                return

            # Store each extracted item
            stored_count = 0
            for item in items[: self._max_items]:
                text = item.get("text", "").strip()
                category = item.get("category", "fact")
                importance = float(item.get("importance", 0.5))

                if not text or len(text) < 10:
                    continue

                # Validate category
                if category not in ("fact", "decision", "preference", "audit"):
                    category = "fact"

                # Deduplicate
                if self._is_duplicate(text, scope):
                    continue

                # Embed
                vector = self._embed(text)
                if vector is None:

                    # Fallback: zero vector (will be text-searched only)
                    vector = [0.0] * self._store.embedding_dim

                # Store
                import uuid

                memory_id = f"cap-{uuid.uuid4().hex[:8]}"
                tags_list = item.get("tags", [])
                if not isinstance(tags_list, list):
                    tags_list = []
                self._store.add_memory(
                    id=memory_id,
                    text=text,
                    vector=vector,
                    category=category,
                    scope=scope,
                    origin="agent",
                    confidence=importance,
                    tags=json.dumps(tags_list),
                    metadata={
                        "source": "auto_capture",
                        "importance": importance,
                        "captured_at": datetime.now(UTC).isoformat(),
                    },
                )
                stored_count += 1
                logger.debug(f"AutoCapture: stored '{text[:60]}' (cat={category}, scope={scope})")

            if stored_count:
                logger.info(f"AutoCapture: stored {stored_count} memory items (scope={scope})")

        except Exception as e:
            logger.warning(f"AutoCapture.process failed (non-fatal): {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Time-Decay
# ─────────────────────────────────────────────────────────────────────────────


def apply_time_decay(
    store: "LanceDBStore",
    half_life_days: float = DECAY_HALF_LIFE_DAYS,
    weight_floor: float = DECAY_WEIGHT_FLOOR,
    table_name: str | None = None,
) -> dict:
    """Apply time-based weight decay to all memories in the store.

    Formula (mirrors memory-lancedb-pro TypeScript implementation):
        new_weight = max(floor, 0.5 + 0.5 * exp(-age_days / half_life))

    At half_life_days age: ~0.68×
    At 2×half_life:        ~0.59×
    At 4×half_life:        ~0.52×

    Args:
        store:           LanceDBStore instance.
        half_life_days:  Half-life period in days (default: 60).
        weight_floor:    Minimum weight value (default: 0.1).
        table_name:      Optional table name override.

    Returns:
        Summary dict: {"updated": int, "skipped": int, "errors": int}.
    """
    tname = table_name or MEMORY_TABLE

    if not store.table_exists(tname):
        logger.info(f"apply_time_decay: table '{tname}' does not exist, skipping.")
        return {"updated": 0, "skipped": 0, "errors": 0}

    try:
        memories = store.get_memories(limit=10000, table_name=tname)
    except Exception as e:
        logger.error(f"apply_time_decay: failed to fetch memories: {e}")
        return {"updated": 0, "skipped": 0, "errors": 1}

    now = datetime.now(UTC)
    updated = skipped = errors = 0

    for mem in memories:
        mem_id = mem.get("id")
        if not mem_id:
            skipped += 1
            continue

        # ── Origin-based differentiation (C-KB-06/07) ────────────────────────
        origin = mem.get("origin", "agent") or "agent"
        if origin in ("document", "user"):
            # Never decay documents or user knowledge
            skipped += 1
            continue

        if origin == "audit":
            effective_half_life = 365.0
        else:
            effective_half_life = half_life_days

        # ── access_count boost (C-KB-08): high-recall memories decay slower ──
        access_count = mem.get("access_count", 0) or 0
        if access_count >= 5:
            effective_half_life *= 2.0

        ts = mem.get("timestamp")
        if ts is None:
            skipped += 1
            continue

        # Normalize timestamp to UTC-aware datetime
        try:
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
            else:
                ts = datetime.fromisoformat(str(ts)).replace(tzinfo=UTC)
            age_days = (now - ts).total_seconds() / 86400.0
        except Exception:
            skipped += 1
            continue

        new_weight = max(weight_floor, 0.5 + 0.5 * math.exp(-age_days / effective_half_life))
        result = store.update_weight(id=mem_id, weight=new_weight, table_name=tname)

        if result.get("status") == "success":
            updated += 1
        else:
            errors += 1

    summary = {"updated": updated, "skipped": skipped, "errors": errors}
    logger.info(f"apply_time_decay: {summary} (half_life={half_life_days}d)")
    return summary


def schedule_time_decay(
    store: "LanceDBStore",
    interval_hours: float = 24.0,
    half_life_days: float = DECAY_HALF_LIFE_DAYS,
) -> object | None:
    """Start a background APScheduler job for periodic time-decay.

    Requires ``apscheduler`` to be installed (optional dependency).
    If unavailable, logs a warning and returns None.

    Args:
        store:           LanceDBStore instance.
        interval_hours:  How often to run decay (default: every 24h).
        half_life_days:  Half-life passed to apply_time_decay.

    Returns:
        APScheduler BackgroundScheduler instance, or None if unavailable.
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning(
            "schedule_time_decay: apscheduler not installed. "
            "Run `uv add apscheduler` to enable automatic time-decay scheduling. "
            "You can still call apply_time_decay() manually."
        )
        return None

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=apply_time_decay,
        trigger="interval",
        hours=interval_hours,
        args=[store],
        kwargs={"half_life_days": half_life_days},
        id="memory_time_decay",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"✓ Time-decay scheduler started: every {interval_hours}h, half_life={half_life_days}d"
    )
    return scheduler
