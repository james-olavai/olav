"""LanceDB Knowledge Base Search Tool - Semantic search over indexed KB.

This tool queries the LanceDB Knowledge Base using hybrid retrieval
(Vector + BM25) to find the most relevant knowledge chunks.

Usage:
    search_knowledge("BGP neighbor down troubleshooting")
    search_knowledge("OSPF configuration best practices")
"""

import json
import logging

from langchain_core.tools import tool

from olav.core.knowledge import KB_TABLE, get_knowledge_base
from olav.core.memory import get_store

logger = logging.getLogger(__name__)


@tool
def search_knowledge(
    query: str,
    limit: int = 5,
) -> str:
    """Search the knowledge base for relevant documents and guides.

    Performs hybrid search combining vector similarity with full-text search
    using RRF (Reciprocal Rank Fusion) for optimal results.

    Use this when you need:
    - Troubleshooting guides (e.g., "BGP neighbor down")
    - Configuration best practices (e.g., "OSPF design")
    - Vendor documentation (e.g., "Cisco IOS commands")
    - Network concepts (e.g., "VXLAN EVPN")

    Args:
        query: Natural language search query. Be specific about:
            - Protocol or technology (BGP, OSPF, VXLAN, etc.)
            - Problem or symptom (neighbor down, timeout, flapping)
            - Optional: vendor (Cisco, Arista, Juniper)

        limit: Maximum number of results to return (default=5, max=10).

    Returns:
        Formatted list of relevant knowledge chunks with source and relevance,
        or "No relevant knowledge found" if no results.

    Examples:
        >>> search_knowledge("BGP neighbor flapping troubleshooting")
        **[1] CCNP TSHOOT Foundation** (relevance: 0.92)
        When a BGP neighbor continuously transitions between Up and Down...

        >>> search_knowledge("OSPF design best practices")
        **[1] OSPF Configuration Guide** (relevance: 0.88)
        OSPF provides several advantages in enterprise networks...
    """
    if not query or not query.strip():
        return "Error: query must not be empty."

    limit = max(1, min(int(limit), 10))

    try:
        # Get KB engine
        store = get_store()
        kb = get_knowledge_base(store)

        # Check if KB is indexed
        if not store.table_exists(KB_TABLE):
            return "Knowledge base not indexed yet. Command: olav config kb-index"

        # Perform hybrid search on KB
        results = kb.search(query, limit=limit)

        if not results:
            return "No relevant knowledge found in KB. Try web_search for external resources."

        # Format results
        output = []
        for i, result in enumerate(results, 1):
            text = result.get("text", "")
            if len(text) > 300:
                text = text[:300] + "..."

            score = result.get("rrf_score", 0.0)
            score_str = f"{score:.2f}" if isinstance(score, (float, int)) else "N/A"

            # Parse metadata
            try:
                meta = result.get("metadata", "{}")
                if isinstance(meta, str):
                    meta = json.loads(meta)
                source = meta.get("source_file", "Unknown")
            except Exception:
                source = "Unknown"

            output.append(
                f"**[{i}] {source}** (relevance: {score_str})\n"
                f"{text}\n"
            )

        return "\n---\n\n".join(output)

    except Exception as e:
        logger.error(f"KB search failed: {e}", exc_info=True)
        return f"KB search failed: {e}. Try web_search() for external resources."
