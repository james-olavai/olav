"""Search knowledge base - delegates to config-Infrastructure tools."""

from typing import Optional

from langchain_core.tools import tool


# This is a reference wrapper - actual implementation is in config-Infrastructure
# The skill loading system will discover the real tool from config-Infrastructure


@tool
def search_knowledge(
    query: str,
    limit: int = 5,
    threshold: float = 0.0,
) -> dict:
    """Search the knowledge base using semantic similarity.

    This tool delegates to the implementation in config-Infrastructure.

    Args:
        query: Natural language search query
        limit: Maximum number of results (default: 5)
        threshold: Similarity threshold (default: 0.0)

    Returns:
        dict with search results and relevance scores
    """
    # Import from config-Infrastructure
    try:
        from olav.skills.config_Infrastructure.tools.search_knowledge_lancedb import (
            search_knowledge as _search,
        )

        return _search.invoke({"query": query, "limit": limit, "threshold": threshold})
    except ImportError:
        return {
            "status": "error",
            "error": "search_knowledge tool not found in config-Infrastructure",
            "query": query,
        }
