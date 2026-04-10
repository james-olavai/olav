"""Web Search Tool - Search the internet for network troubleshooting info.

This tool enables the Agent to search the web for:
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
    from langchain_core.tools import tool
except ImportError:
    # Fallback for missing imports
    DuckDuckGoSearchRun = None
    def tool(f):
        return f

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


@tool
def web_search(query: str) -> str:
    """Search the web for network troubleshooting information.

    Use this tool when search_knowledge() finds no relevant internal
    documentation. Common use cases:

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

    Examples:
        >>> web_search("Cisco IOS BGP neighbor stuck in Active state 2026")
        Returns: Top 3-5 results from community forums, blogs, documentation

        >>> web_search("VXLAN control plane timeout troubleshooting")
        Returns: Results from vendor docs, technical discussions

        >>> web_search("Arista EOS OSPF neighbor flapping causes")
        Returns: Vendor documentation, incident reports, solutions

    Raises:
        RuntimeError: If web search engine is not available
        ValueError: If query is empty or invalid

    Notes:
        - Uses DuckDuckGo (no API key required, privacy-friendly)
        - Timeout: 10 seconds per search
        - Results: Top 5-10 most relevant sources
        - No ad results or tracking
        - If results seem outdated, try a more specific query with year
        - For implementation details, see vendor official docs instead

    Common Query Patterns:
        - Troubleshooting: "<protocol> <symptom> troubleshooting"
          Example: "BGP neighbor down troubleshooting"

        - Error messages: "<error message> <vendor>"
          Example: "OSPF neighbor stuck in INIT Cisco"

        - CVEs: "<vendor> <product> CVE <symptom>"
          Example: "Cisco IOS BGP CVE 2026"

        - Best practices: "<vendor> <protocol> best practices <year>"
          Example: "Arista EOS VXLAN best practices 2026"

        - Recent incidents: "<technology> incident <year>"
          Example: "BGP route leak incident 2026"
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


# For testing without @tool decorator
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        result = web_search.invoke({"query": query})
        print(result)
    else:
        print("Usage: python web_search.py '<query>'")
        print("Example: python web_search.py 'Cisco IOS BGP troubleshooting'")
