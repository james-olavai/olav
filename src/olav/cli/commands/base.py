"""Base command class for unified OLAV CLI command framework.

All commands inherit from this to ensure consistent:
- Parameter parsing
- Error handling
- Output formatting
- Async execution
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseCommand(ABC):
    """Abstract base class for all OLAV CLI commands.
    
    Defines the interface that all commands must implement
    for consistent behavior across the CLI.
    """

    def __init__(self, name: str, description: str = ""):
        """Initialize command.
        
        Args:
            name: Command name (e.g., "devices", "query", "help")
            description: Short description of command
        """
        self.name = name
        self.description = description
        self.aliases: list[str] = []

    @abstractmethod
    async def execute(self, args: str = "") -> str:
        """Execute the command with given arguments.
        
        Args:
            args: Command arguments as string
            
        Returns:
            Command output as string
            
        Raises:
            Exception: Command execution errors
        """
        pass

    def parse_args(self, args: str) -> dict[str, Any]:
        """Parse command arguments.
        
        Override this in subclasses for custom argument parsing.
        
        Args:
            args: Raw argument string
            
        Returns:
            Parsed arguments as dictionary
        """
        # Simple default: space-separated arguments
        if not args.strip():
            return {}

        parts = args.strip().split()
        return {"args": parts}

    def format_output(self, result: Any) -> str:
        """Format command output.
        
        Override this in subclasses for custom formatting.
        
        Args:
            result: Command result
            
        Returns:
            Formatted output string
        """
        if isinstance(result, str):
            return result
        return str(result)

    async def validate_prerequisites(self) -> bool:
        """Validate that command can be executed.
        
        Override in subclasses to check preconditions.
        
        Returns:
            True if command can execute, False otherwise
        """
        return True
