"""
OLAV v0.9.8 - Network AI Operations Assistant
DeepAgents Native Framework
"""

__version__ = "0.9.8"


def __getattr__(name: str) -> object:  # noqa: ANN401
    """Lazy import to avoid loading deepagents when only tools are needed."""
    if name in (
        "create_olav_agent",
        "initialize_olav",
    ):
        from olav.agent import (  # noqa: F401
            create_olav_agent,
            initialize_olav,
        )

        return locals()[name]

    if name in ("OlavDatabase", "get_database"):
        from olav.core.database import (  # noqa: F401
            OlavDatabase,
            get_database,
        )

        return locals()[name]

    if name in ("list_devices", "nornir_execute"):
        # Tools are loaded from .olav/skills/ via Tool Registry
        # For backward compatibility, we provide lazy loading
        from olav.api.v1.devices import list_devices  # noqa: F401
        # nornir_execute is a dynamic tool loaded via Tool Registry
        # Access it via: from olav.core.tool_registry import get_tool
        if name == "list_devices":
            return list_devices
        else:
            from olav.core.tool_registry import get_tool
            tool = get_tool("nornir_execute")
            if tool:
                return tool
            raise AttributeError(f"Tool 'nornir_execute' not loaded from registry")

    raise AttributeError(f"module 'olav' has no attribute {name!r}")


__all__ = [
    # Version
    "__version__",
    # Agent
    "create_olav_agent",  # pyright: ignore [reportUnsupportedDunderAll]
    "initialize_olav",  # pyright: ignore [reportUnsupportedDunderAll]
    # Database
    "OlavDatabase",  # pyright: ignore [reportUnsupportedDunderAll]
    "get_database",  # pyright: ignore [reportUnsupportedDunderAll]
    # Tools
    "nornir_execute",  # pyright: ignore [reportUnsupportedDunderAll]
    "list_devices",  # pyright: ignore [reportUnsupportedDunderAll]
    "search_device_commands",  # pyright: ignore [reportUnsupportedDunderAll]
    "api_call",  # pyright: ignore [reportUnsupportedDunderAll]
]
# All items above are provided via __getattr__ lazy loading
