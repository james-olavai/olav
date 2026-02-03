"""
OLAV Prompt Session - Using Native prompt-toolkit with async support

Features:
- Native FileHistory for command persistence
- nest_asyncio for async context compatibility
- Auto-completion from whitelist
- Multi-line input support
"""

import logging
import sys
from pathlib import Path

import nest_asyncio

from config.paths import USER_HISTORY_PATH

logger = logging.getLogger(__name__)

# Apply nest_asyncio globally to allow prompt-toolkit in async contexts
nest_asyncio.apply()


class OlavPromptSession:
    """OLAV prompt session using native prompt-toolkit."""

    def __init__(
        self,
        enable_completion: bool = True,
        multiline: bool = True,
    ) -> None:
        """Initialize OlavPromptSession.

        Args:
            enable_completion: Enable auto-completion from whitelist
            multiline: Enable multi-line input
        """
        self.enable_completion = enable_completion
        self.multiline = multiline
        self.is_tty = sys.stdin.isatty()

        # Ensure history directory exists
        USER_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Load command whitelist for completion
        self.whitelist = self._load_whitelist()

        self._session = None

        # Initialize prompt-toolkit session
        if self.is_tty:
            self._init_session()
        else:
            logger.debug("Non-TTY mode detected, using basic input")

    def _load_whitelist(self) -> dict[str, str]:
        """Load command whitelist for auto-completion."""
        whitelist_file = Path(".olav/config/command_whitelist.yaml")

        if not whitelist_file.exists():
            return {}

        try:
            import yaml

            with open(whitelist_file, encoding="utf-8") as f:
                whitelist_config = yaml.safe_load(f)
                return whitelist_config.get("command_whitelist", {})
        except Exception as e:
            logger.debug(f"Failed to load command whitelist: {e}")
            return {}

    def _init_session(self) -> None:
        """Initialize prompt-toolkit session with FileHistory."""
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
            from prompt_toolkit.completion import WordCompleter
            from prompt_toolkit.history import FileHistory

            # Create FileHistory (native persistence)
            history = FileHistory(str(USER_HISTORY_PATH))

            # Create word completer from whitelist
            completer = None
            if self.enable_completion and self.whitelist:
                words = [cmd.strip() for cmd in self.whitelist.keys()]
                if words:
                    completer = WordCompleter(words=words, ignore_case=True)

            # Create prompt session
            self._session = PromptSession(
                history=history,
                auto_suggest=AutoSuggestFromHistory(),
                completer=completer,
                multiline=self.multiline,
            )

            logger.debug(f"Prompt-toolkit session initialized with history: {USER_HISTORY_PATH}")

        except Exception as e:
            logger.warning(f"Failed to initialize prompt-toolkit session: {e}")
            self._session = None

    async def prompt_async(self, message: str = "olav> ", **kwargs) -> str:
        """Get user input asynchronously (for use in async context).

        Args:
            message: Prompt message
            **kwargs: Additional prompt-toolkit arguments

        Returns:
            User input string
        """
        # Use prompt-toolkit async if available, otherwise fallback to input()
        if self._session:
            try:
                return await self._session.prompt_async(message, **kwargs)
            except Exception as e:
                logger.debug(f"Prompt-toolkit async failed, using fallback: {e}")
                return input(message)
        else:
            return input(message)

    def prompt_sync(self, message: str = "olav> ", **kwargs) -> str:
        """Get user input synchronously (DEPRECATED - use prompt_async in async context).

        Args:
            message: Prompt message
            **kwargs: Additional prompt-toolkit arguments

        Returns:
            User input string
        """
        # Use prompt-toolkit if available, otherwise fallback to input()
        if self._session:
            try:
                return self._session.prompt(message, **kwargs)
            except Exception as e:
                logger.debug(f"Prompt-toolkit failed, using fallback: {e}")
                return input(message)
        else:
            return input(message)

    def add_history(self, command: str) -> None:
        """Add command to history.

        Args:
            command: Command to add to history

        Note: FileHistory automatically persists, no manual save needed
        """
        # FileHistory automatically handles persistence
        # This method is kept for API compatibility but does nothing
        pass

    def close(self) -> None:
        """Close the prompt session."""
        # FileHistory automatically saves on close
        self._session = None
