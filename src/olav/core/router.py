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
from pathlib import Path
from typing import Any

import lancedb

from olav.core.config import get_config, get_embedding_config

logger = logging.getLogger(__name__)


# Default routing threshold
DEFAULT_ROUTING_THRESHOLD = 0.85


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
            from langchain_community.embeddings import HuggingFaceEmbeddings

            emb_config = get_embedding_config()

            # Try local embedding first
            if emb_config.mode == "local":
                self._embeddings = HuggingFaceEmbeddings(
                    model_name=emb_config.local_model,
                    model_kwargs={"device": emb_config.device},
                    encode_kwargs={"normalize_embeddings": emb_config.normalize_embeddings},
                )
            else:
                # Use OpenAI or other API-based embeddings
                from langchain_openai import OpenAIEmbeddings

                self._embeddings = OpenAIEmbeddings(
                    model=emb_config.api_model,
                    api_key=emb_config.api_key,
                    base_url=emb_config.base_url or None,
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

            # Check if table has data
            count = self._table.count_rows()
            if count > 0:
                logger.info(f"Agent intent index already exists with {count} entries")
                return {"status": "exists", "count": count}

        except Exception as e:
            # Table doesn't exist or is empty - proceed to create
            logger.debug(f"No existing table or empty: {e}")

        # Prepare records for insertion
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

    def _semantic_route(self, query: str) -> dict[str, Any] | None:
        """Perform semantic routing using LanceDB.

        Returns None if no match above threshold.
        """
        if self._table is None:
            db = self._get_db()
            try:
                self._table = db.open_table("agent_intent_index")
            except Exception:
                logger.debug("Agent intent index not found, using fallback routing")
                return None

        # Check if table has data
        count = self._table.count_rows()
        if count == 0:
            logger.info("Agent intent index is empty, using fallback routing")
            return None

        # Generate query embedding
        embeddings = self._get_embeddings()
        query_vector = embeddings.embed_query(query)

        # Search for nearest match
        results = self._table.search(query_vector, "vector").limit(1).to_list()

        if not results:
            return None

        best_match = results[0]
        # LanceDB returns distance, convert to similarity
        distance = best_match.get("distance", 1.0)
        confidence = 1.0 - distance

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
                    "agent": "olav",  # Default agent
                    "confidence": 0.0,
                    "method": "default",
                }

        # Discover agents via PLATFORM.md (Tier 1) then AGENT.md fallback
        from olav.core.platform_registry import PlatformRegistry
        from olav.core.workspace import resolve_workspace_root

        ws_root = resolve_workspace_root()
        valid_agents = discover_valid_agents(ws_root if ws_root.exists() else None)
        default_agent = valid_agents[0] if valid_agents else "quick"

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
                "agent": "olav",
                "confidence": 0.0,
                "method": "default",
            }


# Global router instance
_router_instance: SemanticRouter | None = None


def get_router() -> SemanticRouter:
    """Get or create the global SemanticRouter instance."""
    global _router_instance
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
      1. PLATFORM.md ``agents:`` list  — explicit Tier-1 registration
      2. Workspace subdirs with AGENT.md — filesystem fallback
      3. ["quick"]                      — last-resort default

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
        return ["quick"]

    # Tier 1 — PLATFORM.md explicit list
    registry = PlatformRegistry.load(workspace_root)
    if registry.agents:
        return registry.agents

    # Tier 2 fallback — any workspace subdir that has an AGENT.md
    names = [
        d.name
        for d in sorted(workspace_root.iterdir())
        if d.is_dir() and (d / "AGENT.md").exists()
    ]
    return names if names else ["quick"]


def _load_agents_from_workspace() -> list[dict[str, Any]]:
    """Load agent definitions for the LanceDB semantic routing index.

    Uses PLATFORM.md agents list (Tier 1) to enumerate agents, then reads
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
                except Exception:
                    pass

        agents.append({
            "name": name,
            "description": description,
            "skills": [{"name": name, "description": description}],
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
