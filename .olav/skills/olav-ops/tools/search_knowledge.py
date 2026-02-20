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
from pathlib import Path

try:
    from langchain_core.tools import tool
    from langchain_community.vectorstores import DuckDB
except ImportError:
    DuckDB = None
    tool = lambda f: f

from config.paths import MAIN_DB_PATH
from olav.core.llm import LLMFactory

logger = logging.getLogger(__name__)

# Cache vectorstore instances keyed by resolved db_path string
_vectorstore_cache: dict = {}


def _get_vectorstore(db_path: str):
    """Return (or lazily create) a DuckDB VectorStore for the given DB path.

    Args:
        db_path: Absolute path string to the DuckDB file.

    Returns:
        DuckDB: LangChain vectorstore bound to knowledge_chunks table.

    Raises:
        RuntimeError: If DuckDB file missing or LangChain not available.
    """
    global _vectorstore_cache

    if db_path not in _vectorstore_cache:
        if DuckDB is None:
            raise RuntimeError(
                "LangChain DuckDB integration not available. "
                "Install: pip install langchain-community"
            )

        db = Path(db_path)
        if not db.exists():
            raise RuntimeError(
                f"Knowledge base database not found at {db}. "
                "Run 'olav admin kb-index' to create it."
            )

        try:
            import duckdb  # type: ignore
        except ImportError:
            raise RuntimeError("duckdb not installed. Install: pip install duckdb")

        # Use LLMFactory for unified provider support (local/openai/other)
        embeddings = LLMFactory.get_embeddings()

        db_conn = duckdb.connect(str(db), read_only=False)
        _vectorstore_cache[db_path] = DuckDB(
            connection=db_conn,
            embedding=embeddings,
            table_name="knowledge_chunks"
        )

    return _vectorstore_cache[db_path]


@tool
def search_knowledge(query: str, limit: int = 3, db_path: str = "", threshold: float = 0.0) -> str:
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
        
        limit: Maximum number of results to return (default=3, max=10).
            More results give broader context but may include less relevant items.

        db_path: DuckDB file containing knowledge_chunks.
            Default: MAIN_DB_PATH (.olav/db/olav.duckdb).

        threshold: Minimum relevance score (0.0-1.0, default 0.0 = no filter).
            Raise to 0.6-0.7 to filter low-quality matches.
    
    Returns:
        str: Formatted list of relevant knowledge chunks with source file names
             and similarity scores. Returns "No relevant knowledge found" if no
             results pass the threshold.
    
    Examples:
        >>> search_knowledge("BGP neighbor flapping troubleshooting", limit=3)
        **[1] bgp_troubleshooting.md** (相似度: 0.92)
        When a BGP neighbor continuously transitions between Up and Down states...
        
        >>> search_knowledge("VXLAN EVPN design best practices")
        **[1] vxlan_design.md** (相似度: 0.88)
        VXLAN with EVPN provides several advantages...
    
    Notes:
        - Requires knowledge base to be indexed first via index_knowledge_files()
        - LLM_API_KEY must be configured for embedding generation
        - Results ranked by cosine similarity (0.0 to 1.0)
    """
    try:
        # Ensure limit is reasonable
        limit = min(int(limit), 10)
        
        # Resolve db path
        resolved_db = str(db_path) if db_path else str(MAIN_DB_PATH)

        # Get vectorstore and perform similarity search
        vectorstore = _get_vectorstore(resolved_db)
        pairs = vectorstore.similarity_search_with_relevance_scores(query, k=limit)

        # Apply threshold filter
        if threshold > 0.0:
            pairs = [(doc, score) for doc, score in pairs if score is None or score >= threshold]
        
        if not pairs:
            return (
                "No relevant knowledge found in internal knowledge base. "
                "Try using web_search() to find external resources."
            )
        
        # Format results
        results = []
        for i, (doc, score) in enumerate(pairs, 1):
            source = doc.metadata.get("source_file", "unknown")
            content = doc.page_content
            
            # Truncate long content (max 500 chars)
            if len(content) > 500:
                content = content[:500] + "..."

            score_str = f"{score:.2f}" if score is not None else "n/a"
            results.append(
                f"**[{i}] {source}** (score: {score_str})\n{content}"
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
