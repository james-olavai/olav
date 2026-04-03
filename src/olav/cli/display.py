"""CLI Display Components - Banners and UI elements.

Provides:
- Banner configuration system
- Rich-based UI rendering
- Watermark and License notices
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console
    from rich.text import Text
else:
    try:
        from rich.console import Console
        from rich.text import Text

        RICH_AVAILABLE = True
    except ImportError:  # pragma: no cover (fallback when Rich not available)
        RICH_AVAILABLE = False
        Console = None  # type: ignore[misc,assignment]
        Text = None  # type: ignore[misc,assignment]


__all__ = [
    "get_banner",
    "load_banner_from_config",
    "display_banner",
    "print_error",
    "print_success",
    "print_welcome",
]


def get_banner(banner_name: str = "default") -> str:
    """Get banner text by name.

    Args:
        banner_name: Name of the banner from config.banners

    Returns:
        Banner text string
    """
    try:
        from config.banners import get_banner_text

        return get_banner_text(banner_name)
    except (ImportError, KeyError):
        # Fallback if config not available
        return ""


def load_banner_from_config(settings_path: str | Path | None = None) -> str:
    """Load banner text from settings configuration.

    Args:
        settings_path: Path to settings.json (default: .olav/settings.json)

    Returns:
        Banner text string
    """
    import json

    if settings_path is None:
        from olav.core.config import settings as cfg

        settings_path_obj = Path(cfg.agent_dir) / "settings.json"
    elif isinstance(settings_path, str):
        settings_path_obj = Path(settings_path)
    else:
        settings_path_obj = settings_path

    if not settings_path_obj.exists():
        return get_banner("default")

    try:
        settings = json.loads(settings_path_obj.read_text(encoding="utf-8"))
        show_banner = settings.get("cli", {}).get("showBanner", True)

        if not show_banner:
            return ""

        banner_name = settings.get("cli", {}).get("banner", "default")
        return get_banner(banner_name)

    except (json.JSONDecodeError, KeyError):
        return get_banner("default")


def display_banner(banner_text: str, console: Console | None = None) -> None:
    """Display a banner to the console.

    Args:
        banner_text: Banner text to display (supports Rich markup)
        console: Rich console instance (creates new if None)
    """
    if not banner_text:
        return

    if not RICH_AVAILABLE:  # type: ignore[name-defined]
        # Fallback without rich
        print(banner_text)
        return

    if console is None:
        console = Console()

    # Parse and display rich markup
    text = Text.from_markup(banner_text)
    console.print(text)


# =============================================================================
# Print Functions for Status Output
# =============================================================================

# Format configuration for print_* functions
_PRINT_FORMATS = {
    "error": {
        "emoji": "❌",
        "style": "bold red",
        "fallback_prefix": "ERROR:",
    },
    "success": {
        "emoji": "✅",
        "style": "bold green",
        "fallback_prefix": "SUCCESS:",
    },
    "welcome": {
        "emoji": "👋",
        "style": "bold cyan",
        "fallback_prefix": "Welcome:",
    },
}


def _format_and_print(
    message: str,
    format_key: str,
    console: "Console | None" = None,
) -> None:
    """Internal helper function for print_* functions.

    Eliminates code duplication for Rich-based printing with fallback support.

    Args:
        message: The message to print
        format_key: Key in _PRINT_FORMATS dict (error, success, welcome)
        console: Optional Rich console object
    """
    if format_key not in _PRINT_FORMATS:
        raise ValueError(f"Unknown format key: {format_key}")

    config = _PRINT_FORMATS[format_key]

    if console is None:
        if RICH_AVAILABLE:
            console = Console()
        else:
            # Fallback for when Rich is not available
            prefix = config["fallback_prefix"]
            print(f"{prefix} {message}", flush=True)
            return

    # Use Rich for formatted output
    emoji = config["emoji"]
    style = config["style"]
    formatted_msg = f"[{style}]{emoji}[/{style}] {message}"
    console.print(formatted_msg)


def print_error(message: str, console: "Console | None" = None) -> None:
    """Print an error message to console with color formatting.

    Args:
        message: The error message to print
        console: Optional Rich console object (creates one if not provided)

    Example:
        >>> print_error("Configuration failed")
        # Outputs: ❌ Configuration failed (in red)
    """
    _format_and_print(message, "error", console)


def print_success(message: str, console: "Console | None" = None) -> None:
    """Print a success message to console with color formatting.

    Args:
        message: The success message to print
        console: Optional Rich console object (creates one if not provided)

    Example:
        >>> print_success("Operation completed")
        # Outputs: ✅ Operation completed (in green)
    """
    _format_and_print(message, "success", console)


def print_welcome(message: str, console: "Console | None" = None) -> None:
    """Print a welcome message to console with color formatting.

    Args:
        message: The welcome message to print
        console: Optional Rich console object (creates one if not provided)

    Example:
        >>> print_welcome("Welcome to OLAV")
        # Outputs: 👋 Welcome to OLAV (in cyan)
    """
    _format_and_print(message, "welcome", console)
