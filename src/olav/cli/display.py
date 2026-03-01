"""CLI Display Components - Banners and UI elements.

Provides:
- Banner configuration system
- Rich-based UI rendering
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    "display_todos",
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


class StreamingDisplay:
    """Hierarchical streaming output handler for agent execution.

    Manages three levels of output:
    1. Thinking process (LLM reasoning) - shown in dim/dark color
    2. Tool calls (network execution) - shown in highlight Panel
    3. Final results (formatted output) - shown in standard color

    Supports both verbose mode (all output) and compact mode (tools + results only).
    """

    def __init__(
        self,
        console: Console | None = None,
        verbose: bool = False,
        show_spinner: bool = True,
        quiet: bool = False,
    ) -> None:
        """Initialize streaming display.

        Args:
            console: Rich Console instance (creates new if None)
            verbose: Show full thinking process if True
            show_spinner: Show spinner during processing if True
        """
        if not RICH_AVAILABLE:  # type: ignore[name-defined]
            raise ImportError("Rich library required for StreamingDisplay")

        # Create console with force_terminal and no_color for better streaming
        self.console = console or Console(force_terminal=True, force_interactive=False, width=160)
        self.verbose = verbose
        self.show_spinner = show_spinner
        self.quiet = quiet
        self._current_spinner = None

    def show_thinking(self, text: str, end: str = "") -> None:
        """Display LLM thinking/reasoning (streaming tokens).

        Args:
            text: Thinking content to display
            end: End character (empty string for delta, newline for finalized)
        """
        if not self.verbose:
            return

        # Stream tokens in normal color (not dim)
        self.console.print(text, end=end, highlight=False)
        # Force flush to show streaming tokens immediately
        self.console.file.flush()

    def show_tool_compact(self, tool_name: str, detail: str | None = None) -> None:
        """Display tool call in compact single-line format.

        Args:
            tool_name: Name of the tool being called
            detail: Optional detail (device, query, etc.)
        """
        if self.quiet:
            return

        if detail:
            self.console.print(f"[dim]  → {tool_name}[/dim] [cyan]{detail}[/cyan]")
        else:
            self.console.print(f"[dim]  → {tool_name}...[/dim]")
        self.console.file.flush()

    def show_tool_call(
        self,
        tool_name: str,
        device: str | None = None,
        command: str | None = None,
        status: str = "executing",
        compact: bool = False,
    ) -> None:
        """Display tool call in highlighted Panel format.

        Args:
            tool_name: Name of the tool being called
            device: Target device (optional)
            command: Command being executed (optional)
            status: Status string ('executing', 'completed', 'failed')
            compact: If True, use compact single-line display
        """
        if self.quiet:
            return

        # Use compact display for less important tools
        if compact:
            detail = device or command or None
            self.show_tool_compact(tool_name, detail)
            return

        from rich.panel import Panel

        # Build title with status indicator
        status_icons = {
            "executing": "⏳",
            "completed": "✅",
            "failed": "❌",
        }
        icon = status_icons.get(status, "🔧")

        title = f"{icon} {tool_name}"
        if device:
            title += f" | {device}"

        # Build content
        content = ""
        if command:
            content = f"Command: `{command}`"

        # Display as panel
        panel = Panel(
            content or "Processing...",
            title=title,
            border_style="cyan" if status == "executing" else "green",
            expand=False,
        )
        self.console.print(panel)

    def show_result(self, text: str, end: str = "", markdown: bool = False) -> None:
        """Display final result in standard format.

        Args:
            text: Result content to display
            end: End character (empty string for delta, newline for finalized)
            markdown: If True, render text as Markdown with syntax highlighting
        """
        if markdown and text.strip():
            try:
                from rich.markdown import Markdown

                # P10: Clean up Markdown that Rich doesn't handle well
                # Replace <br> with space or newline (Rich Markdown doesn't support HTML tags in tables)
                cleaned_text = text.replace("<br>", "  \n")  # Standard Markdown line break

                # 移除代码块中的markdown标记（如果存在）
                if cleaned_text.startswith("```markdown"):
                    cleaned_text = cleaned_text.replace("```markdown\n", "").replace("\n```", "")
                elif cleaned_text.startswith("```"):
                    # 移除其他代码块包装
                    lines = cleaned_text.split("\n")
                    if lines[0].startswith("```") and lines[-1].strip() == "```":
                        cleaned_text = "\n".join(lines[1:-1])

                md = Markdown(cleaned_text)
                self.console.print(md)
            except Exception as e:
                # Fallback: 如果markdown渲染失败，使用纯文本
                self.console.print(f"[dim]Warning: Markdown rendering failed: {e}[/dim]")
                self.console.print(text, end=end, highlight=False)
        else:
            self.console.print(text, end=end, highlight=False)
        # Force flush to show streaming tokens immediately
        self.console.file.flush()

    def show_processing_status(self, message: str = "Processing...") -> None:
        """Show processing status indicator.

        Args:
            message: Status message to display
        """
        if self.quiet:
            return

        if not self.show_spinner:
            self.console.print(f"🔍 {message}")
            return

        # Use rich status for animated feedback
        from rich.live import Live
        from rich.spinner import Spinner

        spinner = Spinner("dots", text=f"[bold green]{message}[/bold green]")
        self._current_spinner = Live(spinner, refresh_per_second=4)
        self._current_spinner.start()

    def stop_processing_status(self) -> None:
        """Stop and clear the processing status indicator."""
        if self._current_spinner:
            self._current_spinner.stop()
            self._current_spinner = None

    def show_error(self, message: str) -> None:
        """Display error message.

        Args:
            message: Error message to display
        """
        self.console.print(f"[bold red]❌ Error:[/] {message}")

    def show_data_source_indicator(
        self,
        source: str,  # "sql" or "cli"
        snapshot_time: str | None = None,
        device: str | None = None,
    ) -> None:
        """Display data source information.

        Args:
            source: Data source type ("sql" for database, "cli" for live command)
            snapshot_time: Snapshot timestamp (for SQL queries)
            device: Device name (optional)
        """
        if self.quiet:
            return

        if source == "sql":
            # Database source with timestamp
            time_str = f" [dim](Data time: {snapshot_time})[/dim]" if snapshot_time else ""
            self.console.print(f"[dim]📊 Data source: SQL database snapshot{time_str}[/dim]")
        elif source == "cli":
            dev_str = f" [cyan]{device}[/cyan]" if device else ""
            self.console.print(f"[dim]📡 Data source: CLI live query{dev_str}[/dim]")
        else:
            self.console.print(f"[dim]📊 Data source: {source}[/dim]")

    def show_json_table(self, json_data: Any) -> None:
        """Render JSON data as a table (if list of dicts) or pretty JSON.

        Args:
            json_data: The data to display (list of dicts, or other)
        """
        if isinstance(json_data, str):
            import json

            try:
                json_data = json.loads(json_data)
            except json.JSONDecodeError:
                # Not JSON, print as text
                self.show_result(json_data)
                return

        if isinstance(json_data, list) and json_data and isinstance(json_data[0], dict):
            # Render as table
            from rich import box
            from rich.table import Table

            # Determine common keys for columns
            all_keys = set()
            for item in json_data:
                if isinstance(item, dict):
                    all_keys.update(item.keys())

            # Smart column sorting: device first, then interface/port, then others alpha, then status last
            def sort_key(key: str) -> tuple[int, str]:
                key_lower = key.lower()
                if "device" in key_lower:
                    return (0, key)
                if "interface" in key_lower or "port" in key_lower:
                    return (1, key)
                if "status" in key_lower or "state" in key_lower:
                    return (99, key)
                return (10, key)

            sorted_cols = sorted(list(all_keys), key=sort_key)

            # Create stylish table
            table = Table(
                box=box.HEAVY_EDGE,
                show_header=True,
                header_style="bold magenta",
                border_style="cyan",
                title_style="bold",
                expand=True,
            )

            for col in sorted_cols:
                # Use ratio for some known columns to prevent squashing
                if col.lower() in ("interface", "neighbor"):
                    table.add_column(col.replace("_", " ").title(), overflow="fold", no_wrap=False)
                elif col.lower() in ("device", "proto", "state"):
                    table.add_column(col.replace("_", " ").title(), justify="center", no_wrap=True)
                else:
                    table.add_column(col.replace("_", " ").title(), overflow="fold")

            for item in json_data:
                if not isinstance(item, dict):
                    continue
                row = []
                for col in sorted_cols:
                    val = item.get(col)
                    val_str = ""

                    if val is None:
                        val_str = "-"
                    elif isinstance(val, dict | list):
                        import json

                        val_str = json.dumps(val, ensure_ascii=False)
                    else:
                        val_str = str(val)

                    # Status coloring
                    if "status" in col.lower() or "state" in col.lower() or "link" in col.lower():
                        v_lower = val_str.lower()
                        if any(x in v_lower for x in ["up", "full", "est", "ok", "connected"]):
                            val_str = f"[green]{val_str}[/green]"
                        elif any(x in v_lower for x in ["down", "fail", "err", "not"]):
                            val_str = f"[red]{val_str}[/red]"
                        elif "admin" in v_lower:
                            val_str = f"[yellow]{val_str}[/yellow]"

                    row.append(val_str)
                table.add_row(*row)

            self.console.print(table)
            # Ensure newline after table for proper prompt formatting
            self.console.print()
        else:
            # Fallback to pretty JSON
            import json

            self.show_result(json.dumps(json_data, indent=2, ensure_ascii=False), end="\n")


def display_todos(agent_graph: Any, console: Console | None = None) -> None:
    """Display todo list from agent state using Rich.

    Args:
        agent_graph: Compiled LangGraph agent with state
        console: Console instance (optional, creates new if not provided)
    """
    if console is None:
        from rich.console import Console as RichConsole

        console = RichConsole()

    try:
        from rich.panel import Panel
        from rich.table import Table

        # Get the latest state from the graph
        state = agent_graph.get_state()
        todos: list[dict[str, Any]] = (
            state.values.get("todos", []) if state and hasattr(state, "values") else []
        )

        if not todos:
            return

        table = Table(show_header=True, header_style="bold magenta", border_style="blue")
        table.add_column("ID", style="dim", width=4)
        table.add_column("Status", width=15)
        table.add_column("Task", min_width=30)

        status_icons = {"not-started": "⬜", "in-progress": "🔄", "completed": "✅"}

        for todo in todos:
            icon = status_icons.get(todo.get("status", "not-started"), "⬜")
            table.add_row(
                str(todo.get("id", "")),
                f"{icon} {todo.get('status', 'not-started')}",
                str(todo.get("title", "")),
            )

        panel = Panel(table, title="📋 Task Progress", border_style="blue")
        console.print(panel)
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.debug(f"Could not display todos: {e}")


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
