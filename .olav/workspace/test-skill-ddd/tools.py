from langchain_core.tools import tool

@tool
def hello_world(name: str) -> str:
    """Say hello to the given name."""
    return f"Hello, {name}!"
