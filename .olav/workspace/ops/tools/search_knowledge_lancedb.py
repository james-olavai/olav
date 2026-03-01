"""LanceDB Knowledge Base Search Tool - Semantic search over indexed knowledge.

This tool queries the LanceDB memory store using hybrid retrieval (Vector + BM25)
to find the most relevant knowledge chunks for a natural language query.

This replaces the legacy DuckDB VSS search_knowledge.py tool.

Usage:
    search_knowledge("BGP neighbor down troubleshooting")
    search_knowledge("OSPF best practices", category="fact")
"""

import logging

from langchain_core.tools import tool

from olav.core.memory import (
    get_store,
    hybrid_search,
    MEMORY_TABLE,
)

logger = logging.getLogger(__name__)

# Default embedding dimension (bge-small)
DEFAULT_EMBEDDING_DIM = 384


@tool
def search_knowledge(
    query: str,
    limit: int = 5,
    category: str | None = None,
    scope: str | None = "global",
) -> str:
    """Search the knowledge base for relevant guides, cases, and documentation.

    Performs hybrid search combining vector similarity with full-text search
    using RRF (Reciprocal Rank Fusion) for optimal results.

    Use this when you need:
    - Troubleshooting guides (e.g., "BGP neighbor down")
    - Historical cases (e.g., "past CPU spike incidents")
    - Best practices (e.g., "VXLAN design")
    - Vendor documentation (e.g., "Cisco BGP commands")

    Args:
        query: Natural language search query. Be specific about:
            - Protocol or technology (BGP, OSPF, VXLAN)
            - Problem or symptom (neighbor down, flapping, timeout)
            - Optional: vendor (Cisco, Arista, Juniper)

        limit: Maximum number of results to return (default=5, max=10).

        category: Optional filter by memory category:
            - fact: Factual information about network state
            - decision: Past decisions and their rationale
            - preference: Agent preferences and learned behaviors
            - audit: Configuration and command audit trails

        scope: Scope filter for memory isolation (default="global").
            Use "global" for system-wide knowledge, or specify agent name
            for agent-specific knowledge.

    Returns:
        Formatted list of relevant knowledge with source and scores,
        or "No relevant knowledge found" if no results.

    Examples:
        >>> search_knowledge("BGP neighbor flapping troubleshooting")
        **[1] bgp_troubleshooting.md** (score: 0.92)
        When a BGP neighbor continuously transitions between Up and Down states...

        >>> search_knowledge("VXLAN EVPN design best practices", category="fact")
        **[1] vxlan_design.md** (score: 0.88)
        VXLAN with EVPN provides several advantages...
    """
    if not query or not query.strip():
        return "Error: query must not be empty."

    # Validate limit
    limit = max(1, min(int(limit), 10))

    try:
        # Get or create store
        store = get_store(embedding_dim=DEFAULT_EMBEDDING_DIM)

        # Ensure table exists
        if not store.table_exists(MEMORY_TABLE):
            store.create_table(MEMORY_TABLE)

        # Get embeddings for the query
        try:
            from olav.core.llm import LLMFactory
            embeddings = LLMFactory.get_embeddings()
            query_vector = embeddings.embed_query(query)

            # Ensure vector matches expected dimension
            if len(query_vector) < DEFAULT_EMBEDDING_DIM:
                query_vector = list(query_vector) + [0.0] * (DEFAULT_EMBEDDING_DIM - len(query_vector))
            elif len(query_vector) > DEFAULT_EMBEDDING_DIM:
                query_vector = list(query_vector)[:DEFAULT_EMBEDDING_DIM]

        except Exception as e:
            logger.warning(f"Failed to get embeddings: {e}. Using random vector for testing.")
            import random

            query_vector = [random.random() for _ in range(DEFAULT_EMBEDDING_DIM)]

        # Perform hybrid search
        results = hybrid_search(
            store=store,
            query=query,
            query_vector=query_vector,
            limit=limit,
            category=category,
            scope=scope,
        )

        if not results:
            return (
                "No relevant knowledge found in internal knowledge base. "
                "Try using web_search() to find external resources."
            )

        # Format results
        output = []
        for i, result in enumerate(results, 1):
            text = result.get("text", "")
            if len(text) > 500:
                text = text[:500] + "..."

            score = result.get("rrf_score", result.get("score", "N/A"))
            score_str = f"{score:.2f}" if isinstance(score, float) else str(score)

            category = result.get("category", "unknown")
            scope = result.get("scope", "global")
            metadata = result.get("metadata", "{}")

            output.append(
                f"**[{i}]** (score: {score_str}, category: {category}, scope: {scope})\n"
                f"{text}\n"
                f"_Metadata: {metadata}_"
            )

        return "\n\n---\n\n".join(output)

    except Exception as e:
        logger.error(f"Knowledge search failed: {e}", exc_info=True)
        return f"Knowledge search failed: {e}. Try web_search() for external resources."
