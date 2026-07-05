"""
OLAV v0.19.0 - AI Operations Assistant
DeepAgents Native Framework

``__path__`` is extended so subpackages shipped by sibling
distributions (e.g. ``olav-ent`` providing ``olav.enterprise.*``)
contribute to the same logical ``olav.*`` namespace.
"""

import pkgutil
__path__ = pkgutil.extend_path(__path__, __name__)

__version__ = "0.22.0"


def __getattr__(name: str) -> object:  # noqa: ANN401
    """Lazy import for core utilities."""
    if name in ("create_olav_agent",):
        from olav.agents.agent import (  # noqa: F401
            create_olav_agent,
        )

        return locals()[name]

    if name in ("OlavDatabase", "get_database"):
        from olav.core.database import (  # noqa: F401
            OlavDatabase,
            get_database,
        )

        return locals()[name]

    raise AttributeError(f"module 'olav' has no attribute {name!r}")


__all__ = [
    # Version
    "__version__",
    # Agent
    "create_olav_agent",  # pyright: ignore [reportUnsupportedDunderAll]
    # Database
    "OlavDatabase",  # pyright: ignore [reportUnsupportedDunderAll]
    "get_database",  # pyright: ignore [reportUnsupportedDunderAll]
]
# All items above are provided via __getattr__ lazy loading
