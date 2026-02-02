"""
OLAV Prompt Session - Enhanced with Command History and Auto-Completion

Features:
- Command history tracking with frequency counting
- Auto-completion for commands using whitelist
- Tab completion support for historical commands
- Multi-line input support
"""

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Try to import CommandHistory, but don't fail if it doesn't exist
try:
    from olav.cli.command_history import CommandHistory
except (ImportError, ModuleNotFoundError):
    CommandHistory = None  # type: ignore[assignment]
    logger.debug("CommandHistory module not available, using in-memory history")


class OlavPromptSession:
    """Enhanced OLAV prompt session with command history."""

    def __init__(
        self,
        history_file: str | Path | None = None,
        enable_completion: bool = True,
        enable_history: bool = True,
        multiline: bool = True,
    ) -> None:
        """Initialize OlavPromptSession.

        Args:
            history_file: Path to history file. Default: .olav/data/command_history.json
            enable_completion: Enable auto-completion
            enable_history: Enable history persistence
            multiline: Enable multi-line input
        """
        import sys
        
        if history_file is None:
            from config.settings import settings

            history_file = Path(settings.agent_dir) / "cli_history"

        self.history_file = Path(history_file)
        self.enable_completion = enable_completion
        self.enable_history = enable_history
        self.multiline = multiline
        self.is_tty = sys.stdin.isatty()

        # Ensure data directory exists
        self.history_file.parent.mkdir(parents=True, exist_ok=True)

        # Load command whitelist
        self.whitelist = self._load_whitelist()

        # Initialize CommandHistory module
        if CommandHistory:
            self.command_history = CommandHistory(history_file=self.history_file)
        else:
            logger.debug("CommandHistory module not available, history disabled")
            self.command_history = None

        self._session = None  # type: ignore[assignment]

        # Only initialize prompt-toolkit in TTY mode
        if self.is_tty:
            self._init_session()
        else:
            logger.debug("Non-TTY mode detected, using basic input")

    def _load_whitelist(self) -> dict[str, str]:
        """Load command whitelist for auto-completion."""
        whitelist_file = Path(".olav/config/command_whitelist.yaml")

        if not whitelist_file.exists():
            logger.warning("Command whitelist file not found")
            return {}

        try:
            import yaml

            with open(whitelist_file, encoding="utf-8") as f:
                whitelist_config = yaml.safe_load(f)
                return whitelist_config.get("command_whitelist", {})
        except Exception as e:
            logger.error(f"Failed to load command whitelist: {e}")
            return {}

    def _init_session(self) -> None:
        """Initialize prompt-toolkit session with history completion."""
        logger.debug("Initializing prompt-toolkit session in TTY mode...")
        try:
            # Import prompt-toolkit modules
            from prompt_toolkit import PromptSession
            from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
            from prompt_toolkit.completion import WordCompleter
            from prompt_toolkit.history import FileHistory
            from prompt_toolkit.key_binding import KeyBindings

            # Create file history for persistence
            history = None
            if self.enable_history and self.history_file:
                try:
                    # Create FileHistory object
                    history = FileHistory(str(self.history_file))
                    logger.debug(f"Initialized history file: {self.history_file}")
                except Exception as e:
                    logger.debug(f"Failed to create FileHistory: {e}")
                    history = None

            # Create prompt session with history
            logger.debug("Creating PromptSession...")
            session = PromptSession(history=history)
            logger.debug("PromptSession created successfully")

            # Setup auto-completion from command history
            if self.enable_completion and self.command_history:
                try:
                    # Get recent commands for auto-completion
                    recent_commands = self.command_history.get_recent_commands(limit=50)

                    if recent_commands:
                        # Create word completer for commands
                        command_words = list(set(cmd.get("command", "") for cmd in recent_commands))
                        if command_words:
                            word_completer = WordCompleter(words=command_words, ignore_case=True)
                            session.completer = word_completer
                            logger.debug(f"Loaded {len(command_words)} commands for completion")
                except Exception as e:
                    logger.debug(f"Failed to setup auto-completion: {e}")

            # Setup multiline
            if self.multiline:
                session.multiline = True

            self._session = session
            logger.debug("Prompt-toolkit session initialized successfully")

        except Exception as e:
            logger.warning(f"Failed to initialize prompt-toolkit session: {e}")
            self._session = None

    def _get_completion_suggestions(self, text: str, limit: int = 10) -> list[str]:
        """Get auto-completion suggestions based on input.

        Args:
            text: Current input text
            limit: Maximum number of suggestions

        Returns:
            List of completion suggestions
        """
        suggestions = []

        if not self._session:
            return suggestions

        # Get current prompt content
        try:
            # Extract text after "olav> " prefix
            if "olav>" in text:
                current_text = text.split("olav>")[-1].strip()
            else:
                current_text = text.strip()

            # Check whitelist for exact matches
            for pattern in self.whitelist:
                if re.search(pattern, current_text, re.IGNORECASE):
                    suggestions.append(f"/{pattern.split('.')[0]}")
                    if len(suggestions) >= limit:
                        break

            # Check command history for frequent commands
            if len(suggestions) < limit and self.command_history:
                recent_commands = self.command_history.get_recent_commands(limit=10)
                for entry in recent_commands:
                    cmd = entry.get("command", "")
                    if cmd and cmd not in [s.strip("/") for s in suggestions]:
                        suggestions.append(f"/{cmd}")
                        if len(suggestions) >= limit:
                            break
        except Exception as e:
            logger.debug(f"Completion error: {e}")  # Ignore errors in completion

        return suggestions

    async def prompt(self, message: str = "olav> ") -> str:
        """Get user input asynchronously.

        Args:
            message: Prompt message to display

        Returns:
            User input string
        """
        if self._session is None:
            # Fallback to basic input
            logger.warning("Prompt session not initialized, using basic input")
            return input(message)

        try:
            # Use plain string prompt to avoid XML parsing issues
            result = await self._session.prompt_async(message)
            return result
        except (EOFError, KeyboardInterrupt):
            raise EOFError from None

    def prompt_sync(self, message: str = "olav> ") -> str:
        """Get user input synchronously.

        Args:
            message: Prompt message to display

        Returns:
            User input string
        """
        import warnings

        # In non-TTY mode, always use basic input to avoid hanging
        if not self.is_tty or self._session is None:
            # Suppress RuntimeWarning when using input() in async context
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=RuntimeWarning)
                return input(message)

        try:
            # Use plain string prompt to avoid XML parsing issues
            result = self._session.prompt(message)
            return result
        except (EOFError, KeyboardInterrupt):
            raise EOFError from None
        except Exception as e:
            # If prompt-toolkit fails, fall back to basic input
            # This should be rare and indicates prompt-toolkit issues
            logger.warning(f"Prompt session error: {e}, falling back to input()")
            # Suppress RuntimeWarning when using input() in async context
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=RuntimeWarning)
                return input(message)

    def record_query(
        self, query: str, command_used: str = "", device: str = "", sql_query: str = ""
    ) -> None:
        """Record a query in command history.

        Args:
            query: User's input query
            command_used: The command that was executed (for tracking)
            device: Device queried (for context)
            sql_query: SQL query executed (for caching)

        Returns:
            None
        """
        if self.command_history:
            self.command_history.record_query(
                query=query, command_used=command_used, device=device, sql_query=sql_query
            )

    def get_completions(self, prefix: str, limit: int = 10) -> list[str]:
        """Get command completions for tab completion.

        Args:
            prefix: The prefix typed by user (e.g., "/sh", "/disp")
            limit: Maximum number of completions

        Returns:
            List of command completions
        """
        if not self._session:
            return []

        # Get completions from session
        try:
            # Import prompt_toolkit types for runtime use
            from prompt_toolkit.completion import CompleteEvent
            from prompt_toolkit.document import Document

            # Create Document and CompleteEvent for the completer
            document = Document(prefix, cursor_position=len(prefix))
            complete_event = CompleteEvent()

            completions = self._session.completer.get_completions(document, complete_event)
            # Apply limit
            if limit:
                completions = list(completions)[:limit]
            # Format completions
            formatted = [c.text for c in completions]
            return formatted
        except Exception as e:
            logger.error(f"Failed to get completions: {e}")
            return []

    def clear_history(self) -> None:
        """Clear all command history."""
        if self.command_history:
            self.command_history.clear_history()
        if self._session:
            self._session.history.clear()
        logger.info("Command history cleared")

    def get_stats(self) -> dict[str, Any]:
        """Get usage statistics.

        Returns:
            Dictionary with total queries, unique commands, top commands
        """
        if self.command_history:
            return self.command_history.get_stats()
        return {}
