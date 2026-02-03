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


# ==================== Conversation Memory ====================


class Message:
    """Single conversation message"""

    def __init__(self, role: str, content: str, timestamp: "datetime | None" = None) -> None:
        """Initialize message.

        Args:
            role: 'user', 'assistant', 'system', etc.
            content: Message content
            timestamp: Message creation time (auto-filled if None)
        """
        from datetime import datetime

        self.role = role
        self.content = content
        self.timestamp = timestamp or datetime.now()

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() if isinstance(self.timestamp, object) else str(self.timestamp),
        }


class Session:
    """Conversation session with message history and context management.

    Features:
    - Message storage (user, assistant, system)
    - Multi-turn context tracking
    - Message history retrieval
    - Context window management
    - Optional persistence
    """

    def __init__(self, context_window: int = 10, persist: bool = False, user_id: str | None = None) -> None:
        """Initialize conversation session.

        Args:
            context_window: Max messages to keep in context (0 = unlimited)
            persist: Whether to persist session to disk
            user_id: Optional user identifier for session tracking
        """
        self.messages: list[Message] = []
        self.context_window = context_window
        self.persist = persist
        self.context: dict = {}
        self._session_id = None
        self.user_id = user_id
        self._storage: dict = {}  # Key-value storage for session data

    def add_message(self, role: str, content: str) -> None:
        """Add message to conversation.

        Args:
            role: Message role ('user', 'assistant', 'system')
            content: Message content
        """
        message = Message(role, content)
        self.messages.append(message)

        # Enforce context window limit
        if self.context_window > 0 and len(self.messages) > self.context_window:
            self.messages.pop(0)

    def get_history(self) -> list[dict] | None:
        """Get conversation history.

        Returns:
            List of message dictionaries or None if empty
        """
        if not self.messages:
            return None

        return [msg.to_dict() for msg in self.messages]

    def get_context(self) -> dict:
        """Get conversation context (enriched with metadata).

        Returns:
            Dictionary with context information
        """
        return {
            "messages": self.get_history(),
            "message_count": len(self.messages),
            "context": self.context,
            "context_window": self.context_window,
        }

    def clear(self) -> None:
        """Clear conversation history."""
        self.messages = []
        self.context = {}

    def get_last_message(self) -> Message | None:
        """Get last message in conversation.

        Returns:
            Last Message or None if empty
        """
        return self.messages[-1] if self.messages else None

    def get_messages_by_role(self, role: str) -> list[Message]:
        """Get all messages with specific role.

        Args:
            role: Role to filter by

        Returns:
            List of messages with matching role
        """
        return [msg for msg in self.messages if msg.role == role]

    def set(self, key: str, value: any) -> None:
        """Store key-value data in session.

        Args:
            key: Storage key
            value: Value to store
        """
        self._storage[key] = value

    def get(self, key: str, default: any = None) -> any:
        """Retrieve value from session storage.

        Args:
            key: Storage key
            default: Default value if key not found

        Returns:
            Stored value or default
        """
        return self._storage.get(key, default)
