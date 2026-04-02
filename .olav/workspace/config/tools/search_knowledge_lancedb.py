"""LanceDB Knowledge Base Search Tool - Semantic search over indexed knowledge.

Searches the Knowledge Base (KB) table in LanceDB for relevant documents.
Uses hybrid retrieval combining vector similarity with full-text search (RRF fusion).

Usage:
    search_knowledge("BGP neighbor down troubleshooting")
    search_knowledge("OSPF best practices")
"""

import json
import logging

from langchain_core.tools import tool

from olav.core.knowledge import KB_TABLE, get_knowledge_base
from olav.core.memory import get_store

logger = logging.getLogger(__name__)


@tool
def search_knowledge(query: str, limit: int = 5) -> str:
    """Search the knowledge base for relevant guides, cases, and documentation.

    Performs hybrid search combining vector similarity with full-text search.

    Args:
        query: Natural language search query (e.g., "BGP neighbor down troubleshooting").
        limit: Maximum number of results (default=5, max=10).

    Returns:
        Formatted list of relevant knowledge with sources and scores.
    """
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
