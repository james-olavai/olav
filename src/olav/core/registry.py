"""
Command Registry - Stub for v2.0 compatibility.

In v2.0, the registry was simplified into the DeepAgents skill system.
This module provides backward-compatible stubs for legacy code that still
references the old registry API.
"""

from typing import Any, Dict, Optional


class CommandRegistry:
    """Stub registry for backward compatibility with v0.x code."""
    
    def __init__(self):
        self._commands: Dict[str, Any] = {}
    
    def register(self, name: str, handler: Any) -> None:
        """Register a command handler."""
        self._commands[name] = handler
    
    def get(self, name: str) -> Optional[Any]:
        """Get a command handler by name."""
        return self._commands.get(name)
    
    def get_all(self) -> Dict[str, Any]:
        """Get all registered commands."""
        return self._commands.copy()
    
    def validate_command(self, command: str) -> bool:
        """Validate if a command is registered (stub for v2.0)."""
        # In v2.0, validation is done by the LLM agent
        return True


# Global registry instance
_registry: Optional[CommandRegistry] = None


def get_command_registry() -> CommandRegistry:
    """Get the global command registry instance.
    
    Returns:
        CommandRegistry instance (singleton)
    """
    global _registry
    if _registry is None:
        _registry = CommandRegistry()
    return _registry


def parse_command_output(command: str, output: str) -> Dict[str, Any]:
    """Parse command output (stub for v2.0).
    
    In v2.0, parsing is handled by the LLM agent directly.
    This function is kept for backward compatibility.
    
    Args:
        command: The command that was executed
        output: The output from the command
    
    Returns:
        Empty dict or parsed data
    """
    return {}
