"""Knowledge Base Search Tool - Search internal troubleshooting guides and cases.

This tool enables the Agent to search the internal knowledge base for:
- Troubleshooting guides (e.g., BGP neighbor down)
- Historical cases (e.g., past CPU spike incidents)
- Best practices (e.g., VXLAN design)
- Vendor documentation (e.g., Cisco BGP commands)

Knowledge is stored in .olav/knowledge/ as markdown files and indexed
to DuckDB with vector embeddings for similarity search.

Uses LangChain's VectorStore abstraction for consistent ecosystem integration.
"""

import logging
from typing import Optional
from pathlib import Path

try:
    from langchain_core.tools import tool
    from langchain_community.vectorstores import DuckDB
except ImportError:
    # Fallback for missing imports
    DuckDB = None
    tool = lambda f: f

from config.paths import MAIN_DB_PATH
from olav.core.llm import LLMFactory

logger = logging.getLogger(__name__)

# Lazy-loaded vectorstore
_vectorstore = None


def _get_vectorstore():
    """Get or initialize vectorstore using LangChain's DuckDB wrapper.
    
    Uses LangChain's VectorStore abstraction instead of raw DuckDB for:
    - Consistent ecosystem integration
    - Automatic embedding management
    - Better error handling
    - Reduced custom code
    
    Returns:
        DuckDB: LangChain DuckDB vectorstore
        
    Raises:
        RuntimeError: If vectorstore initialization fails
    """
    global _vectorstore
    
    if _vectorstore is None:
        if DuckDB is None:
            raise RuntimeError(
                "LangChain DuckDB integration not available. "
                "Install: pip install langchain-community"
            )
        
        db_path = Path(MAIN_DB_PATH)
        
        if not db_path.exists():
            raise RuntimeError(
                f"Knowledge base database not found at {db_path}. "
                "Run 'olav admin kb-index' to create it."
            )
        
        # Import duckdb for connection
        try:
            import duckdb
        except ImportError:
            raise RuntimeError("duckdb not installed. Install: pip install duckdb")
        
        # Use LLMFactory for unified provider support (local/openai/other)
        embeddings = LLMFactory.get_embeddings()
        
        # Create persistent connection for VectorStore (need write access for initialization)
        try:
            import duckdb
        except ImportError:
            raise RuntimeError("duckdb not installed. Install: pip install duckdb")
        
        db_conn = duckdb.connect(str(db_path), read_only=False)
        _vectorstore = DuckDB(
            connection=db_conn,
            embedding=embeddings,
            table_name="knowledge_chunks"
        )
    
    return _vectorstore


@tool
def search_knowledge(query: str, limit: int = 3) -> str:
    """Search knowledge base for troubleshooting guides, cases, and docs.
    
    Searches the internal knowledge base for domain expertise. Use when you need:
    - Troubleshooting guides (e.g., "BGP neighbor down")
    - Historical cases (e.g., "past CPU spike incidents")  
    - Best practices (e.g., "VXLAN design")
    - Vendor documentation (e.g., "Cisco BGP commands")
    
    This tool performs vector similarity search on indexed markdown files,
    finding semantically similar content even if exact keywords don't match.
    
    Args:
        query: Natural language search query. Be specific about:
            - Protocol or technology (BGP, OSPF, VXLAN)
            - Problem or symptom (neighbor down, flapping, timeout)
            - Optional: vendor (Cisco, Arista, Juniper)
        
        limit: Maximum number of results to return (default=3, max=5).
            More results give broader context but may include less relevant items.
    
    Returns:
        str: Formatted list of relevant knowledge chunks with source file names
             and similarity scores. Returns "No relevant knowledge found" if no
             matches exceed the similarity threshold.
    
    Examples:
        >>> search_knowledge("BGP neighbor flapping troubleshooting", limit=3)
        **[1] bgp_troubleshooting.md** (相似度: 0.92)
        When a BGP neighbor continuously transitions between Up and Down states...
        
        >>> search_knowledge("VXLAN EVPN design best practices")
        **[1] vxlan_design.md** (相似度: 0.88)
        VXLAN with EVPN provides several advantages...
    
    Raises:
        RuntimeError: If database not found or embeddings API unavailable
        ValueError: If query is empty
    
    Notes:
        - Requires knowledge base to be indexed first: olav admin kb-index
        - OpenAI API key must be configured in settings
        - Results are ranked by cosine similarity (0.0 to 1.0)
        - Only results with similarity > 0.7 are returned
        - Uses LangChain's VectorStore abstraction for seamless integration
    """
    try:
        # Ensure limit is reasonable
        limit = min(int(limit), 10)
        
        # Get vectorstore and perform similarity search
        vectorstore = _get_vectorstore()
        docs = vectorstore.similarity_search(
            query,
            k=limit
        )
        
        if not docs:
            return (
                "No relevant knowledge found in internal knowledge base. "
                "Try using web_search() to find external resources."
            )
        
        # Format results
        results = []
        for i, doc in enumerate(docs, 1):
            source = doc.metadata.get("source_file", "unknown")
            content = doc.page_content
            
            # Truncate long content (max 500 chars)
            if len(content) > 500:
                content = content[:500] + "..."
            
            results.append(
                f"**[{i}] {source}**\n{content}"
            )
        
        return "\n\n---\n\n".join(results)
    
    except RuntimeError as e:
        logger.warning(f"Knowledge search setup failed: {e}")
        return f"Knowledge search error: {e}"
    except Exception as e:
        logger.error(f"Knowledge search failed: {e}", exc_info=True)
        return f"Knowledge search failed: {e}. Try web_search() for external resources."


# For testing without @tool decorator
if __name__ == "__main__":
    # Quick test
    import sys
    
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        result = search_knowledge.invoke({"query": query, "limit": 3})
        print(result)
    else:
        print("Usage: python knowledge_search.py '<query>'")
        print("Example: python knowledge_search.py 'BGP troubleshooting'")
