"""Knowledge Base Search Tool - Semantic search over indexed knowledge.

Queries the `knowledge_chunks` vector table in DuckDB using cosine similarity
to find the most relevant chunks for a natural language query.

Mirrors the working implementation in olav-ops/tools/search_knowledge.py and
adds a `threshold` parameter to filter low-confidence results, plus an
explicit `db_path` argument so the path is never hardcoded.

Path default is declared in SKILL.md under config.knowledge.db_path.
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
                f"Knowledge database not found: {db}. "
                "Run index_knowledge_files() first."
            )

        try:
            import duckdb  # type: ignore
        except ImportError:
            raise RuntimeError("duckdb not installed. Install: pip install duckdb")

        embeddings = LLMFactory.get_embeddings()
        conn = duckdb.connect(str(db), read_only=False)

        _vectorstore_cache[db_path] = DuckDB(
            connection=conn,
            embedding=embeddings,
            table_name="knowledge_chunks",
        )

    return _vectorstore_cache[db_path]


@tool
def search_knowledge(
    query: str,
    db_path: str = "",
    limit: int = 5,
    threshold: float = 0.0,
) -> str:
    """Search the knowledge base for relevant guides, cases, and documentation.

    Performs vector similarity search against the indexed knowledge_chunks table.
    Use when you need troubleshooting guides, historical incident cases, best
    practices, or vendor documentation that was indexed into the KB.

    Args:
        query:     Natural language search query. Be specific — name the protocol
                   (BGP, OSPF, VXLAN), symptom (neighbor down, flapping), or topic
                   (design, sizing, security).
        db_path:   DuckDB file containing knowledge_chunks.
                   Default: MAIN_DB_PATH (.olav/db/olav.duckdb).
        limit:     Maximum results to return (1–10, default 5).
        threshold: Minimum relevance score to include (0.0–1.0, default 0.0).
                   Raise to 0.6–0.7 to filter low-quality matches.

    Returns:
        str: Numbered list of matching chunks with source file and score,
             or a "no results" message if nothing exceeds the threshold.

    Examples:
        >>> search_knowledge("BGP neighbor flapping troubleshooting")
        >>> search_knowledge("OSPF DR election rules", limit=3, threshold=0.65)
        >>> search_knowledge("Cisco VXLAN EVPN design", threshold=0.6)
    """
    if not query.strip():
        return "❌ query must not be empty."

    if DuckDB is None:
        return (
            "❌ Missing dependency: langchain-community. "
            "Install: pip install langchain-community"
        )

    resolved_db = str(db_path) if db_path else str(MAIN_DB_PATH)
    limit = max(1, min(int(limit), 10))

    try:
        vectorstore = _get_vectorstore(resolved_db)
    except RuntimeError as e:
        return f"⚠️  Knowledge search unavailable: {e}"

    try:
        # similarity_search_with_relevance_scores returns (Document, score) pairs
        pairs = vectorstore.similarity_search_with_relevance_scores(query, k=limit)
    except Exception as e:
        logger.warning("similarity_search_with_relevance_scores failed, falling back: %s", e)
        try:
            # Fallback: plain search without scores
            docs = vectorstore.similarity_search(query, k=limit)
            pairs = [(doc, None) for doc in docs]
        except Exception as e2:
            logger.error("Knowledge search failed: %s", e2, exc_info=True)
            return f"❌ Search failed: {e2}"

    # Apply threshold filter
    if threshold > 0.0:
        pairs = [(doc, score) for doc, score in pairs if score is None or score >= threshold]

    if not pairs:
        return (
            f"No relevant knowledge found for: {query!r}\n"
            "(Try lowering threshold or re-indexing with index_knowledge_files)"
        )

    # Format results
    chunks = []
    for i, (doc, score) in enumerate(pairs, 1):
        source = doc.metadata.get("source_file", "unknown")
        content = doc.page_content

        if len(content) > 500:
            content = content[:500] + "…"

        score_str = f"{score:.2f}" if score is not None else "n/a"
        chunks.append(f"**[{i}] {source}** (score: {score_str})\n{content}")

    return "\n\n---\n\n".join(chunks)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
        print(search_knowledge.invoke({"query": q, "limit": 3}))
    else:
        print("Usage: python search_knowledge.py '<query>'")
