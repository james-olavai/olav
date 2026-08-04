"""Semantic Router - LanceDB-based Agent Intent Matching.

This module implements the Semantic Router for OLAV v0.10.0.
It uses LanceDB to perform semantic matching between user queries
and agent intents, providing millisecond-level routing performance.

Key features:
- Store agent skill descriptions as vectors in LanceDB
- Use embedding models for query vectorization
- Fallback to LLM-based routing when threshold not met
"""

import logging
import threading
from pathlib import Path
from typing import Any

import lancedb

from olav.core.config import get_config, get_embedding_config

logger = logging.getLogger(__name__)


# Default routing threshold
DEFAULT_ROUTING_THRESHOLD = 0.55


class SemanticRouter:
    """Semantic Router using LanceDB for intent matching."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        threshold: float = DEFAULT_ROUTING_THRESHOLD,
    ):
        """Initialize the Semantic Router.

        Args:
            db_path: Path to LanceDB database (defaults to memory.lancedb)
            threshold: Similarity threshold for direct routing (0.0-1.0)
        """
        config = get_config()
        paths = config.paths

        if db_path is None:
            db_path = paths.agent_dir_path / "databases" / "memory.lancedb"

        self.db_path = Path(db_path)
        self.threshold = threshold
        self._db = None
        self._keyword_index: dict[str, str] = {}  # agent_name → concatenated keywords
        self._table = None
        self._embeddings = None

    def _get_db(self):
        """Get or create LanceDB connection."""
        if self._db is None:
            self._db = lancedb.connect(str(self.db_path))
        return self._db

    def _get_embeddings(self):
        """Get embedding model."""
        if self._embeddings is None:
            emb_config = get_embedding_config()

            # Try local embedding first
            if emb_config.mode == "local":
                # Imported inside the local branch, not above the mode check:
                # langchain-huggingface ships in the `[local-embed]` extra
                # (2026-08-04), so on a default install this import fails — and
                # above the check it would have failed for **api** mode too,
                # taking the semantic router down on the one path that does not
                # need it. Only local mode requires this package.
                try:
                    from langchain_huggingface import HuggingFaceEmbeddings
                except ImportError:  # older installs / extra not present
                    from langchain_community.embeddings import HuggingFaceEmbeddings

                import os as _os
                import logging as _logging
                for _n in ("sentence_transformers", "transformers", "transformers.modeling_utils", "huggingface_hub"):
                    _logging.getLogger(_n).setLevel(_logging.ERROR)
                # Suppress C-level stdout+stderr (safetensors shard reports come on fd 2)
                _saved1 = _os.dup(1)
                _saved2 = _os.dup(2)
                _null = _os.open(_os.devnull, _os.O_WRONLY)
                _os.dup2(_null, 1)
                _os.dup2(_null, 2)
                try:
                    self._embeddings = HuggingFaceEmbeddings(
                        model_name=emb_config.local_model,
                        model_kwargs={"device": emb_config.device},
                        encode_kwargs={"normalize_embeddings": emb_config.normalize_embeddings},
                    )
                finally:
                    _os.dup2(_saved1, 1)
                    _os.dup2(_saved2, 2)
                    _os.close(_null)
                    _os.close(_saved1)
                    _os.close(_saved2)
            else:
                # Use OpenAI or other API-based embeddings
                from langchain_openai import OpenAIEmbeddings

                self._embeddings = OpenAIEmbeddings(
                    model=emb_config.openai_model or emb_config.api_model,
                    api_key=emb_config.openai_api_key or emb_config.api_key,
                    base_url=emb_config.openai_base_url or None,
                    # Send raw strings, not tiktoken token-ID arrays. The
                    # default (check_embedding_ctx_length=True) makes langchain
                    # submit integer token arrays as `input`, which OpenAI
                    # accepts but local OpenAI-compat endpoints (Ollama
                    # embeddinggemma) reject with "400 invalid input type" —
                    # the router-index error seen in CI vs http://…:11434/v1.
                    check_embedding_ctx_length=False,
                )

        return self._embeddings

    def initialize_index(self, agents: list[dict[str, Any]]) -> dict:
        """Initialize the agent intent index with agent skill descriptions.

        Args:
            agents: List of agent definitions with 'name', 'description',
                   'skills' (list of skill descriptions)

        Returns:
            Dict with initialization status
        """
        db = self._get_db()

        # Create or get the agent intent table
        try:
            # Try to open existing table
            self._table = db.open_table("agent_intent_index")

            # Check vector dim — if model changed, recreate the index
            for field in self._table.schema:
                if field.name == "vector" and hasattr(field.type, "list_size"):
                    try:
                        from olav.core.embedder import detect_embedding_dim
                        current_dim = detect_embedding_dim()
                        # `None` = the probe failed, NOT "a different dimension".
                        # Without this guard `list_size != None` is always true, so
                        # a momentary embed outage would drop a perfectly good
                        # router index — and then rebuild it with an embedder that
                        # is still down. Third instance of the same destructive
                        # pattern found on 2026-08-04 (the other two were in
                        # core/memory); this one is cheaper because the index is
                        # rebuildable, but destroying it over a transient fault is
                        # still wrong.
                        if current_dim is None:
                            logger.debug(
                                "agent_intent_index dim check skipped: embedding "
                                "dimension undetectable right now"
                            )
                        elif field.type.list_size != current_dim:
                            logger.warning(
                                "agent_intent_index has vector dim %d but embedder is %d — recreating",
                                field.type.list_size, current_dim,
                            )
                            db.drop_table("agent_intent_index")
                            raise ValueError("dim mismatch — recreate")
                    except ImportError:
                        pass

            # Check if table matches current agent count
            count = self._table.count_rows()
            # Each agent contributes 1 __root__ + N skills entries
            expected = sum(1 + len(a.get("skills", [])) for a in agents)
            if count > 0 and count == expected:
                logger.info(f"Agent intent index up to date ({count} entries)")
                return {"status": "exists", "count": count}
            elif count > 0:
                # Agent/skill count changed — rebuild
                logger.info(f"Agent intent index stale ({count} entries, expected {expected}) — rebuilding")
                db.drop_table("agent_intent_index")
                raise ValueError("agent count mismatch — recreate")

        except Exception as e:
            # Table doesn't exist, empty, or dim mismatch - proceed to create
            logger.debug(f"No existing table or rebuild needed: {e}")

        # Prepare records for insertion
        # Build keyword index for fast text matching
        self._keyword_index = {}
        for agent in agents:
            _name = agent.get("name", "unknown")
            _parts = [agent.get("description", "")]
            for skill in agent.get("skills", []):
                _parts.append(skill.get("description", ""))
            self._keyword_index[_name] = " ".join(_parts)
        logger.info("Keyword index built: %s", list(self._keyword_index.keys()))

        records = []
        for agent in agents:
            agent_name = agent.get("name", "unknown")

            # Add agent description
            if "description" in agent:
                records.append(
                    {
                        "agent_name": agent_name,
                        "skill_name": "__root__",
                        "description": agent["description"],
                    }
                )

            # Add each skill
            skills = agent.get("skills", [])
            for skill in skills:
                skill_name = skill.get("name", "unknown")
                description = skill.get("description", "")

                if description:
                    records.append(
                        {
                            "agent_name": agent_name,
                            "skill_name": skill_name,
                            "description": description,
                        }
                    )

        if not records:
            return {"status": "no_data", "message": "No agent descriptions provided"}

        # Generate embeddings first
        embeddings = self._get_embeddings()
        descriptions = [r["description"] for r in records]

        logger.info(f"Generating embeddings for {len(descriptions)} agent descriptions...")
        vectors = embeddings.embed_documents(descriptions)

        # Add vectors to records
        for i, record in enumerate(records):
            record["vector"] = vectors[i]

        # Create table with data using PyArrow
        import pyarrow as pa

        schema = pa.schema(
            [
                ("vector", pa.list_(pa.float32())),  # Dynamic-size vector
                ("agent_name", pa.string()),
                ("skill_name", pa.string()),
                ("description", pa.string()),
            ]
        )

        table = pa.Table.from_pylist(records, schema=schema)
        self._table = db.create_table("agent_intent_index", table)

        logger.info(f"Initialized agent intent index with {len(records)} entries")
        return {"status": "created", "count": len(records)}

    def route(self, query: str, *, recorder=None, run_id: str | None = None) -> dict[str, Any]:
        """Route a user query to the appropriate agent.

        Args:
            query: User query string
            recorder: Optional ``AuditEventRecorder`` — when provided together
                with *run_id*, a ``routing_decision`` event is written.
            run_id: Current run identifier (required for audit recording).

        Returns:
            Dict with routing result:
            - agent: Agent name
            - skill: Skill name (if applicable)
            - confidence: Similarity score (0.0-1.0)
            - method: "semantic" or "fallback"
        """
        if not query:
            return {
                "agent": None,
                "confidence": 0.0,
                "method": "fallback",
                "reason": "Empty query",
            }

        # Try semantic routing first
        result = None
        try:
            result = self._semantic_route(query)
        except Exception as e:
            logger.warning(f"Semantic routing failed: {e}")

        if result is None:
            result = self._fallback_route(query)

        # Emit audit event when caller supplies both recorder and run_id
        if recorder is not None and run_id is not None:
            method_map = {"semantic": "semantic", "fallback": "llm_router", "default": "llm_router"}
            routing_method = method_map.get(
                result.get("method", ""), result.get("method", "unknown")
            )
            recorder.record(
                event_type="routing_decision",
                run_id=run_id,
                payload={
                    "routing_method": routing_method,
                    "matched_agent": result.get("agent"),
                    "score": result.get("confidence", 0.0),
                },
            )

        return result

    def _keyword_route(self, query: str) -> dict[str, Any] | None:
        """Fast keyword-based routing (no embedding needed).

        Scores each agent's route_keywords against the query using word overlap.
        Returns the best match if score difference is significant, else None (fall through to semantic).
        """
        # Lazy-load keyword index from workspace if not yet populated
        if not self._keyword_index:
            try:
                agents = _load_agents_from_workspace()
                for agent in agents:
                    _name = agent.get("name", "unknown")
                    _parts = [agent.get("description", "")]
                    for skill in agent.get("skills", []):
                        _parts.append(skill.get("description", ""))
                    self._keyword_index[_name] = " ".join(_parts)
            except Exception as e:
                logger.debug("keyword index lazy-load failed: %s", e)

        if not self._keyword_index:
            return None

        import re

        query_lower = query.lower()
        # Split on whitespace + individual CJK characters for Chinese support
        query_tokens = set(re.findall(r'[\u4e00-\u9fff]+|[a-z0-9_\-]+', query_lower))
        # Also add individual CJK characters as tokens (bigram-like)
        cjk_chars = set()
        for token in list(query_tokens):
            if re.match(r'^[\u4e00-\u9fff]+$', token) and len(token) > 1:
                for i in range(len(token) - 1):
                    cjk_chars.add(token[i:i+2])
                for ch in token:
                    cjk_chars.add(ch)
        query_tokens |= cjk_chars

        scores: dict[str, int] = {}
        for agent_name, keywords_text in self._keyword_index.items():
            kw_tokens = set(re.findall(r'[\u4e00-\u9fff]+|[a-z0-9_\-]+', keywords_text.lower()))
            # Exact token match
            score = len(query_tokens & kw_tokens)
            # Substring match (CJK bigrams in keywords)
            for qt in query_tokens:
                for kw in kw_tokens:
                    if len(qt) >= 2 and len(kw) >= 2 and qt != kw:
                        if qt in kw or kw in qt:
                            score += 1
            scores[agent_name] = score

        if not scores or max(scores.values()) == 0:
            return None

        sorted_agents = sorted(scores.items(), key=lambda x: -x[1])
        best_agent, best_score = sorted_agents[0]
        second_score = sorted_agents[1][1] if len(sorted_agents) > 1 else 0

        # Only route if clear winner (>= 2x the runner-up, and at least 2 keyword hits)
        if best_score >= 2 and best_score > second_score * 1.5:
            confidence = min(1.0, best_score / 5.0)  # normalize to 0-1
            return {
                "agent": best_agent,
                "confidence": confidence,
                "method": "keyword",
            }

        return None  # ambiguous — fall through to semantic

    def _semantic_route(self, query: str) -> dict[str, Any] | None:
        """Perform semantic routing using LanceDB.

        Returns None if no match above threshold.
        """
        # Try fast keyword routing first
        kw_result = self._keyword_route(query)
        if kw_result is not None:
            return kw_result

        if self._table is None:
            db = self._get_db()
            try:
                self._table = db.open_table("agent_intent_index")
            except Exception:
                logger.debug("Agent intent index not found, using fallback routing")
                return None

        count = self._table.count_rows()
        if count == 0:
            return None

        embeddings = self._get_embeddings()
        query_vector = embeddings.embed_query(query)

        results = self._table.search(query_vector, "vector").limit(1).to_list()

        if not results:
            return None

        best_match = results[0]
        # LanceDB returns _distance (with underscore); cosine distance 0=identical, 2=opposite
        distance = best_match.get("_distance", best_match.get("distance", 1.0))
        # Convert cosine distance to similarity: sim = 1 - (dist/2), range [0, 1]
        confidence = max(0.0, 1.0 - distance / 2.0)

        if confidence >= self.threshold:
            return {
                "agent": best_match.get("agent_name"),
                "skill": best_match.get("skill_name"),
                "confidence": confidence,
                "description": best_match.get("description"),
                "method": "semantic",
            }

        return None

    def _fallback_route(self, query: str) -> dict[str, Any]:
        """Fallback to LLM-based routing when semantic routing fails.

        This uses a cheap model (Tier 1) to determine the appropriate agent.
        """
        from olav.core.config import get_llm_config
        from olav.core.llm import LLMFactory

        # Use injected LLM (for testing) or create one
        llm = getattr(self, "_llm", None)
        if llm is None:
            try:
                llm_config = get_llm_config()
                llm = LLMFactory.get_chat_model(
                    model_name=llm_config.model,
                    temperature=0.0,
                    agent_id="router",
                )
            except Exception as e:
                logger.error(f"Failed to get routing LLM: {e}")
                return {
                    "agent": "core",  # Default agent
                    "confidence": 0.0,
                    "method": "default",
                }

        # Discover agents via olav.md (Tier 1) then AGENT.md fallback
        from olav.core.workspace import resolve_workspace_root

        ws_root = resolve_workspace_root()
        valid_agents = discover_valid_agents(ws_root if ws_root.exists() else None)
        default_agent = valid_agents[0] if valid_agents else "core"

        # Build routing prompt: use MANIFEST route_keywords where available
        from olav.core.agent_registry import discover_agents
        manifests = discover_agents(ws_root) if ws_root.exists() else {}

        agent_lines = []
        for name in valid_agents:
            m = manifests.get(name)
            if m and m.route_keywords:
                desc = ", ".join(m.route_keywords[:5])
            else:
                desc = name
            agent_lines.append(f"- {name}: {desc}")

        agents_text = "\n".join(agent_lines) if agent_lines else f"- {default_agent}: general agent"

        prompt = f"""Given the user query below, determine which OLAV agent should handle it.

Available agents:
{agents_text}

Query: {query}

Respond with only the agent name."""

        try:
            response = llm.invoke(prompt)
            agent = response.content.strip().lower()

            # Validate agent name
            if agent not in valid_agents:
                agent = default_agent

            return {
                "agent": agent,
                "confidence": 0.5,  # Lower confidence for fallback
                "method": "fallback",
            }
        except Exception as e:
            logger.error(f"LLM routing failed: {e}")
            return {
                    "agent": "core",
                    "confidence": 0.0,
                    "method": "default",
                }


# Global router instance
_router_instance: SemanticRouter | None = None
_router_lock = threading.Lock()


def get_router() -> SemanticRouter:
    """Get or create the global SemanticRouter instance."""
    global _router_instance
    if _router_instance is None:
        with _router_lock:
            if _router_instance is None:
                _router_instance = SemanticRouter()
    return _router_instance


def initialize_router(agents: list[dict[str, Any]] | None = None) -> dict:
    """Initialize the semantic router with agent definitions.

    Args:
        agents: List of agent definitions (if None, loads from workspace)

    Returns:
        Initialization result dict
    """
    if agents is None:
        agents = _load_agents_from_workspace()

    router = get_router()
    return router.initialize_index(agents)


def discover_valid_agents(workspace_root: "Path | None" = None) -> list[str]:
    """Return the ordered list of top-level agent names for this platform.

    Resolution order (first match wins):
      1. olav.md ``agents:`` list  — explicit Tier-1 registration
      2. Workspace subdirs with AGENT.md — filesystem fallback
      3. ["core"]                        — last-resort default (v0.15+)

    MANIFEST.yaml is no longer used at Tier 1; it is reserved for Skill
    auto-discovery (Tier 3) via :func:`olav.core.agent_registry.merge_into_config`.
    """
    from pathlib import Path

    from olav.core.platform_registry import PlatformRegistry
    from olav.core.workspace import resolve_workspace_root

    if workspace_root is None:
        workspace_root = resolve_workspace_root()
    else:
        workspace_root = Path(workspace_root)

    if not workspace_root.exists():
        return ["core"]

    # Tier 1 — olav.md explicit list
    registry = PlatformRegistry.load(workspace_root)
    if registry.agents:
        return registry.agents

    # Tier 2 fallback — any workspace subdir that has an AGENT.md
    names = [
        d.name
        for d in sorted(workspace_root.iterdir())
        if d.is_dir() and (d / "AGENT.md").exists()
    ]
    return names if names else ["core"]


def _load_agents_from_workspace() -> list[dict[str, Any]]:
    """Load agent definitions for the LanceDB semantic routing index.

    Uses olav.md agents list (Tier 1) to enumerate agents, then reads
    MANIFEST.yaml route_keywords for each to build the index entries.
    Falls back to AGENT.md description if no MANIFEST exists.
    """
    from olav.core.agent_registry import discover_agents
    from olav.core.workspace import resolve_workspace_root

    workspace_path = resolve_workspace_root()
    if not workspace_path.exists():
        logger.warning(f"Workspace not found at {workspace_path}")
        return []

    agent_names = discover_valid_agents(workspace_path)
    manifests = discover_agents(workspace_path)

    agents = []
    for name in agent_names:
        m = manifests.get(name)
        if m and m.route_keywords:
            description = " ".join(m.route_keywords)
        else:
            # Read AGENT.md description as fallback
            agent_md = workspace_path / name / "AGENT.md"
            description = name
            if agent_md.exists():
                try:
                    import frontmatter as _fm
                    post = _fm.load(str(agent_md))
                    description = post.metadata.get("description", name)
                except Exception as e:
                    logger.debug("frontmatter load failed for %s: %s", agent_md, e)

        # Also collect subagent/skill descriptions for richer embedding
        skills = [{"name": name, "description": description}]
        agent_dir = workspace_path / name
        if agent_dir.is_dir():
            for sub in sorted(agent_dir.iterdir()):
                skill_md = sub / "SKILL.md"
                if sub.is_dir() and skill_md.exists():
                    try:
                        import frontmatter as _fm
                        _post = _fm.load(str(skill_md))
                        _desc = _post.metadata.get("description", "")
                        if _desc:
                            skills.append({"name": sub.name, "description": _desc})
                    except Exception as e:
                        logger.debug("frontmatter load failed for %s: %s", skill_md, e)

        agents.append({
            "name": name,
            "description": description,
            "skills": skills,
        })

    return agents


def route_query(query: str, *, recorder=None, run_id: str | None = None) -> dict[str, Any]:
    """Route a user query to the appropriate agent.

    This is the main entry point for semantic routing.

    Args:
        query: User query string
        recorder: Optional ``AuditEventRecorder`` for routing_decision events.
        run_id: Current run identifier (required for audit recording).

    Returns:
        Routing result dict
    """
    router = get_router()
    return router.route(query, recorder=recorder, run_id=run_id)
