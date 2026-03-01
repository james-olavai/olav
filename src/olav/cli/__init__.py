"""OLAV CLI Module.

Provides CLI components: display, session, slash commands.
Entry point: olav.cli.main:cli_main (see pyproject.toml).
"""

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
from olav.cli.main import cli_main

__all__ = [
    "cli_main",
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
