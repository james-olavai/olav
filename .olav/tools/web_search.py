"""Web Search Tool - DuckDuckGo Integration

Supplements knowledge base with current web information.
No API key required - uses DuckDuckGo.
"""

import logging
from typing import Any

from langchain.tools import tool
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)


@tool
def web_search(query: str, num_results: int = 3) -> str:
    """Search the web using DuckDuckGo.
    
    Returns current information from the internet when knowledge base
    doesn't have relevant content.
    
    Args:
        query: Search query (e.g., "Cisco BGP latest features")
        num_results: Number of results to return (default: 3, max: 10)
    
    Returns:
        Formatted string with search results
    
    Examples:
        >>> web_search("OSPF RFC 2328")
        # Returns: [1] Title: RFC 2328 - OSPF...
    """
    try:
        if num_results > 10:
            num_results = 10
        
        logger.info(f"Web search: {query} (max {num_results} results)")
        
        # DuckDuckGo search
        ddgs = DDGS()
        results = ddgs.text(query, max_results=num_results)
        
        if not results:
            return f"⚠️  No web results found for: {query}"
        
        # Format results
        output_lines = [f"🌐 Web Search Results for: {query}\n"]
        
        for i, result in enumerate(results, 1):
            title = result.get('title', 'No title')
            href = result.get('href', 'No URL')
            body = result.get('body', 'No description')
            
            # Truncate long descriptions
            if len(body) > 200:
                body = body[:200] + "..."
            
            output_lines.append(f"[{i}] {title}")
            output_lines.append(f"    URL: {href}")
            output_lines.append(f"    {body}\n")
        
        return "\n".join(output_lines)
    
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        return f"❌ Web search failed: {str(e)}"


@tool
def web_search_news(query: str, num_results: int = 3) -> str:
    """Search for recent news using DuckDuckGo.
    
    Focuses on recent news and announcements.
    
    Args:
        query: News search query (e.g., "Cisco network security updates")
        num_results: Number of results to return (default: 3)
    
    Returns:
        Formatted string with news results
    """
    try:
        if num_results > 10:
            num_results = 10
        
        logger.info(f"News search: {query} (max {num_results} results)")
        
        # DuckDuckGo news search
        ddgs = DDGS()
        results = ddgs.news(query, max_results=num_results)
        
        if not results:
            return f"⚠️  No news found for: {query}"
        
        # Format results
        output_lines = [f"📰 Recent News for: {query}\n"]
        
        for i, result in enumerate(results, 1):
            title = result.get('title', 'No title')
            href = result.get('url', 'No URL')
            date = result.get('date', 'No date')
            body = result.get('body', 'No description')
            
            # Truncate
            if len(body) > 200:
                body = body[:200] + "..."
            
            output_lines.append(f"[{i}] {title} ({date})")
            output_lines.append(f"    URL: {href}")
            output_lines.append(f"    {body}\n")
        
        return "\n".join(output_lines)
    
    except Exception as e:
        logger.error(f"News search failed: {e}")
        return f"❌ News search failed: {str(e)}"


# Aliases for compatibility
web_search_quick = web_search
search_web_current = web_search_news
