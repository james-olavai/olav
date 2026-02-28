"""Core module

Re-exports from unified config.
Also exports core infrastructure components.
"""

# Re-export settings from unified config
from olav.core.config import Settings, get_settings, settings
from olav.core.config import settings, Settings, get_settings


# Script Engine (Task 12.1-12.3)
try:
    from olav.core.script_engine import (
        ScriptExecutor,  # noqa: F401
        ScriptLoader,  # noqa: F401
        ScriptMetadata,  # noqa: F401
        create_script_tool,  # noqa: F401
        get_script_tools,  # noqa: F401
        load_script_tool,  # noqa: F401
        parse_skill_file,  # noqa: F401
    )

    _script_engine_available = True
except ImportError:
    _script_engine_available = False


__all__ = [
    # Settings
    "Settings",
    "get_settings",
    "settings",
]

# Script Engine exports
if _script_engine_available:
    __all__.extend(
        [
            "ScriptExecutor",
            "ScriptLoader",
            "ScriptMetadata",
            "create_script_tool",
            "get_script_tools",
            "load_script_tool",
            "parse_skill_file",
        ]
    )
