"""Search knowledge base - delegates to config agent tools."""

from langchain_core.tools import tool


@tool
def search_knowledge(
    query: str,
    limit: int = 5,
) -> str:
    """Search the knowledge base using semantic similarity.

    This tool delegates to the main implementation in config/tools.

    Args:
        query: Natural language search query
        limit: Maximum number of results (default: 5, max=10)

    Returns:
        str: Formatted search results with sources and relevance scores
    """
    # Import from config/tools (unified implementation)
    try:
        from olav.workspace.config.tools.search_knowledge_lancedb import (
            search_knowledge as _search,
        )

        return _search.invoke({"query": query, "limit": limit})
    except Exception as e:
        return f"❌ KB search failed: {e}"

