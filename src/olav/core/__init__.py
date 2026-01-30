"""Core module

Re-exports from config package for backward compatibility.
Also exports core infrastructure components.
"""

# Re-export settings from config package
from config.settings import DiagnosisSettings, ExecutionSettings, Settings, get_settings

# Command Registry (Task 1.1)
try:
    from olav.core.registry import (
        CommandRegistry,  # noqa: F401
        get_command_registry,  # noqa: F401
        parse_command_output,  # noqa: F401
    )

    _registry_available = True
except ImportError:
    _registry_available = False

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
    "ExecutionSettings",
    "DiagnosisSettings",
]

# Command Registry exports
if _registry_available:
    __all__.extend(
        [
            "CommandRegistry",
            "get_command_registry",
            "parse_command_output",
        ]
    )

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
