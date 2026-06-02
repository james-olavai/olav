#!/usr/bin/env python3
"""Web Search — Search the internet for network troubleshooting info.

This script enables the Agent to search the web for:
- Latest vendor advisories and CVEs
- Community discussions (Reddit, forums, StackOverflow)
- Official documentation updates
- Specific error messages and solutions
- Recent incident reports

Uses DuckDuckGo API for privacy-preserving searches without requiring API keys.
"""

import logging

try:
    from langchain_community.tools import DuckDuckGoSearchRun
except ImportError:
    DuckDuckGoSearchRun = None

logger = logging.getLogger(__name__)

# Lazy-loaded search engine
_search_engine = None


def _get_search_engine():
    """Get or initialize web search engine (lazy loading).

    Initializes DuckDuckGo search on first call. Subsequent calls reuse
    the same instance to avoid repeated initialization.

    Returns:
        DuckDuckGoSearchRun: Search engine instance

    Raises:
        RuntimeError: If DuckDuckGo search is not available
    """
    global _search_engine

    if _search_engine is None:
        if DuckDuckGoSearchRun is None:
            raise RuntimeError(
                "LangChain DuckDuckGo integration not available. "
                "Install: pip install duckduckgo-search"
            )

        try:
            _search_engine = DuckDuckGoSearchRun()
        except Exception as e:
            logger.error(f"Failed to initialize DuckDuckGo search: {e}")
            raise RuntimeError(
                f"Failed to initialize web search: {e}. "
                "Check your internet connection."
            )

    return _search_engine


def web_search(query: str) -> str:
    """Search the web for network troubleshooting information.

    Use this tool when ``recall_memory()`` (unified KB + long-term memory
    + captured facts) finds no relevant internal documentation. Common
    use cases:

    - Latest CVEs and vendor advisories (e.g., "Cisco IOS BGP CVE 2026")
    - Community solutions (e.g., "VXLAN control plane timeout Reddit")
    - Official documentation updates (e.g., "Arista EOS BGP best practices 2026")
    - Error message explanations (e.g., "OSPF neighbor stuck in INIT")
    - Recent incident reports (e.g., "BGP route leak incident 2026")

    Search results are from DuckDuckGo, optimized for privacy without
    requiring API keys. Results include top relevant sources and summaries.

    Args:
        query: Web search query. For best results:
            - Include vendor names (Cisco, Arista, Juniper, etc.)
            - Include protocol/technology (BGP, OSPF, VXLAN, etc.)
            - Include symptom or problem (timeout, flapping, down, etc.)
            - Include timeframe if recent (2026, latest, recent, etc.)
            - 3-6 words is optimal

    Returns:
        str: Top search results with titles, snippets, and URLs.
             Returns error message if search fails.
    """

    # Validate input
    if not query or not isinstance(query, str):
        return "Error: query must be a non-empty string"

    query = query.strip()

    if len(query) < 2:
        return "Error: query too short (minimum 2 characters)"

    if len(query) > 200:
        return "Error: query too long (maximum 200 characters)"

    try:
        logger.debug(f"Web search query: {query}")

        # Get search engine
        search_engine = _get_search_engine()

        # Execute search (timeout built into DuckDuckGo)
        logger.debug("Executing DuckDuckGo search...")
        results = search_engine.run(query)

        if not results or len(results.strip()) == 0:
            return (
                f"No web search results found for '{query}'. "
                "Try a more specific query or different keywords."
            )

        logger.debug(f"Web search returned {len(results)} characters of results")
        return results

    except ValueError as e:
        logger.error(f"Invalid query for web_search: {e}")
        return f"Error: Invalid query - {e}"

    except RuntimeError as e:
        logger.error(f"Runtime error in web_search: {e}")
        return f"Error: {e}"

    except Exception as e:
        logger.error(f"Unexpected error in web_search: {e}", exc_info=True)
        return (
            f"Web search failed: {type(e).__name__}: {e}. "
            "Check your internet connection or try again later."
        )


if __name__ == "__main__":
    import json as _json, sys as _sys
    _args = _json.loads(_sys.stdin.read() or "{}")
    action = _args.pop("action", "search")
    fn = {"search": web_search, "ddg": web_search}.get(action, web_search)
    result = fn(**_args)
    print(_json.dumps(result, default=str))
