from langchain_core.tools import tool

@tool
def extra_tool(query: str) -> str:
    """An extra tool added via merge-into."""
    return f"extra: {query}"
