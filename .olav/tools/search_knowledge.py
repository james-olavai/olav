"""Search Knowledge Base Tool - Vector Similarity Search

Returns semantically relevant knowledge chunks for answering user queries.
"""

import logging
from typing import Any

from langchain.tools import tool

from config.settings import settings
from src.olav.lib.kb_manager import KnowledgeBaseManager
from src.olav.lib.knowledge_gateway import get_knowledge_gateway

logger = logging.getLogger(__name__)


@tool
def search_knowledge(query: str, limit: int | None = None, threshold: float | None = None) -> str:
    """Search knowledge base for relevant information.
    
    Uses vector similarity to find chunks most relevant to the query.
    
    Args:
        query: Search query (e.g., "network troubleshooting BGP")
        limit: Number of results to return (default from settings)
        threshold: Minimum similarity score (0-1), default from settings
    
    Returns:
        Formatted string with relevant knowledge chunks
    
    Examples:
        >>> search_knowledge("OSPF authentication")
        # Returns: [[SOURCE: routing.md]] OSPF uses MD5 authentication...
    """
    # Use config defaults if not provided
    if limit is None:
        limit = settings.knowledge.max_results
    if threshold is None:
        threshold = settings.knowledge.similarity_threshold
    try:
        # Generate embedding for query
        logger.info(f"Searching knowledge base for: {query}")
        
        manager = KnowledgeBaseManager()
        query_embedding = manager.generate_embedding(query)
        
        # Search
        gateway = get_knowledge_gateway(read_only=True)
        results = gateway.vector_search(
            query_embedding,
            limit=limit,
            threshold=threshold
        )
        
        if not results:
            return f"⚠️  No relevant knowledge found for: {query}"
        
        # Format results
        output_lines = [f"📚 Found {len(results)} relevant knowledge chunks:\n"]
        
        for i, result in enumerate(results, 1):
            similarity = result.get('similarity', 0)
            source = result.get('source_file', 'Unknown')
            content = result.get('content', '')
            
            # Truncate long content
            if len(content) > 300:
                content = content[:300] + "..."
            
            output_lines.append(f"[{i}] Similarity: {similarity:.2%} | Source: {source}")
            output_lines.append(f"    {content}\n")
        
        return "\n".join(output_lines)
    
    except ValueError as e:
        if "LLM_API_KEY" in str(e) or "not set" in str(e):
            return "⚠️  Error: LLM API key not configured in OLAV settings. Set LLM_API_KEY environment variable or .olav/settings.json"
        raise
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return f"❌ Search failed: {str(e)}"


@tool
def get_knowledge_stats() -> str:
    """Get current knowledge base statistics.
    
    Returns:
        Status information about indexed content
    
    Examples:
        >>> get_knowledge_stats()
        # Returns: Total chunks: 125, Indexed: 125, Sources: 3
    """
    try:
        manager = KnowledgeBaseManager()
        status = manager.get_status()
        
        output_lines = [
            "📊 Knowledge Base Statistics:",
            f"  Total chunks: {status.get('total_chunks', 0)}",
            f"  Indexed chunks: {status.get('indexed_chunks', 0)}",
            f"  Coverage: {status.get('indexed_percentage', 0):.1f}%",
            f"  Knowledge directory: {status.get('knowledge_dir')}",
        ]
        
        sources = status.get('sources', [])
        if sources:
            output_lines.append("  Source files:")
            for source in sources:
                output_lines.append(f"    • {source['file']}: {source['count']} chunks")
        
        return "\n".join(output_lines)
    
    except Exception as e:
        logger.error(f"Statistics retrieval failed: {e}")
        return f"❌ Failed to get statistics: {str(e)}"


# Aliases for compatibility with different import styles
search_knowledge_base = search_knowledge
get_kb_stats = get_knowledge_stats
