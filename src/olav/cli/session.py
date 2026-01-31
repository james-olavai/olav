"""
OLAV Prompt Session - Enhanced with Command History and Auto-Completion

Features:
- Command history tracking with frequency counting
- Auto-completion for commands using whitelist
- Tab completion support for historical commands
- Multi-line input support
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Dict, List

if TYPE_CHECKING:
    from olav.cli.command_history import CommandHistory
else:
    CommandHistory = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


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
        if history_file is None:
            from config.settings import settings
            history_file = Path(settings.agent_dir) / "cli_history"

        self.history_file = Path(history_file)
        self.enable_completion = enable_completion
        self.enable_history = enable_history
        self.multiline = multiline

        # Ensure data directory exists
        self.history_file.parent.mkdir(parents=True, exist_ok=True)

        # Load command whitelist
        self.whitelist = self._load_whitelist()

        # Initialize CommandHistory module
        if CommandHistory:
            self.command_history = CommandHistory(history_file=self.history_file)
        else:
            logger.warning("CommandHistory module not available, history disabled")
            self.command_history = None

        self._session = None  # type: ignore[assignment]

        # Try to initialize prompt-toolkit session
        self._init_session()

    def _load_whitelist(self) -> Dict[str, str]:
        """Load command whitelist for auto-completion."""
        whitelist_file = Path(".olav/config/command_whitelist.yaml")

        if not whitelist_file.exists():
            logger.warning("Command whitelist file not found")
            return {}

        try:
            import yaml
            with open(whitelist_file, 'r', encoding='utf-8') as f:
                whitelist_config = yaml.safe_load(f)
                return whitelist_config.get('command_whitelist', {})
        except Exception as e:
            logger.error(f"Failed to load command whitelist: {e}")
            return {}

    def _init_session(self) -> None:
        """Initialize prompt-toolkit session with history completion."""
        try:
            # Import prompt-toolkit modules
            from prompt_toolkit import PromptSession, Prompt, FileHistory
            from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
            from prompt_toolkit.completion import WordCompleter
            from prompt_toolkit.formatted_text import HTML
            from prompt_toolkit.key_binding import KeyBindings

            # Create prompt session
            session = PromptSession()

            # Setup history persistence
            if self.enable_history and self.history_file:
                try:
                    history = FileHistory(self.history_file)
                    session.history.load_history()
                    logger.info(f"Loaded command history from {self.history_file}")
                except Exception as e:
                    logger.error(f"Failed to load history: {e}")

            # Setup auto-completion from command history
            if self.enable_completion and self.command_history:
                try:
                    # Get recent commands for auto-completion
                    recent_commands = self.command_history.get_recent_commands(limit=50)

                    # Create completer from history
                    completer = AutoSuggestFromHistory(
                        lambda: recent_commands,
                        max_suggestions=5
                    )

                    # Create word completer for commands
                    command_words = list(set(cmd.get('command', '') for cmd in recent_commands))
                    word_completer = WordCompleter(words=command_words, ignore_case=True)

                    # Add completers to session
                    session.completer = completer
                    session.completer = word_completer
                except Exception as e:
                    logger.error(f"Failed to setup auto-completion: {e}")
                    session = None

            # Setup key bindings
            kb = KeyBindings()
            kb.add("c-c")
            kb.add("c-d")
            kb.add("ctrl-r")  # History search

            # Setup multiline
            if self.multiline:
                session.multiline = True

            self._session = session

        except Exception as e:
            logger.warning(f"Failed to initialize prompt-toolkit session: {e}")
            self._session = None

    def _get_completion_suggestions(self, text: str, limit: int = 10) -> List[str]:
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
                    cmd = entry.get('command', '')
                    if cmd and cmd not in [s.strip('/') for s in suggestions]:
                        suggestions.append(f"/{cmd}")
                        if len(suggestions) >= limit:
                            break

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
        if self._session is None:
            return input(message)

        try:
            # Use plain string prompt to avoid XML parsing issues
            result = self._session.prompt(message)
            return result
        except (EOFError, KeyboardInterrupt):
            raise EOFError from None

    def record_query(self, query: str, command_used: str = "",
                   device: str = "", sql_query: str = "") -> None:
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
                query=query,
                command_used=command_used,
                device=device,
                sql_query=sql_query
            )

    def get_completions(self, prefix: str, limit: int = 10) -> List[str]:
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
            completions = self._session.completer.get_completions(prefix, limit)
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

    def get_stats(self) -> Dict[str, Any]:
        """Get usage statistics.

        Returns:
            Dictionary with total queries, unique commands, top commands
        """
        if self.command_history:
            return self.command_history.get_stats()
        return {}
