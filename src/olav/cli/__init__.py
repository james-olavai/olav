"""OLAV v0.9 CLI Module - Native LangGraph Components.

This module provides an enhanced CLI experience using prompt-toolkit:
- Persistent command history (FileHistory)
- Slash commands for quick actions
- File references (@file.txt)
- Shell command execution (!command)
- Session state via DuckDBSaver
- Customizable banners
"""

from olav.cli.cli_main import main
from olav.cli.commands.builtin import (
    SLASH_COMMANDS,
    execute_command,
    register_command,
)
from olav.cli.display import (
    display_banner,
    get_banner,
    load_banner_from_config,
    print_error,
    print_success,
    print_welcome,
)

__all__ = [
    "main",
    "SLASH_COMMANDS",
    "SLASH_COMMANDS",
    "register_command",
    "execute_command",
    "display_banner",
    "get_banner",
    "load_banner_from_config",
    "print_welcome",
    "print_error",
    "print_success",
]
