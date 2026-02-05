"""
OLAV Prompt Session - Using Native prompt-toolkit with async support

Features:
- Native FileHistory for command persistence
- nest_asyncio for async context compatibility
- Auto-completion from whitelist
- Multi-line input support
"""

import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

import nest_asyncio

from config.paths import USER_HISTORY_PATH, USER_SESSION_DIR

logger = logging.getLogger(__name__)

# Apply nest_asyncio globally to allow prompt-toolkit in async contexts
nest_asyncio.apply()


class OlavPromptSession:
    """OLAV prompt session using native prompt-toolkit."""

    def __init__(
        self,
        enable_completion: bool = False,  # 禁用TAB补全（有问题），仅保留历史记录
        multiline: bool = True,
    ) -> None:
        """Initialize OlavPromptSession.

        Args:
            enable_completion: Enable auto-completion from whitelist (DISABLED - 功能有问题)
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
        whitelist_file = Path(".olav/skills/guard/whitelist.yaml")

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
            from prompt_toolkit.history import FileHistory

            # Create FileHistory (native persistence)
            history = FileHistory(str(USER_HISTORY_PATH))

            # TAB补全已禁用（功能有问题），仅保留历史记录
            completer = None

            # Create prompt session
            self._session = PromptSession(
                history=history,
                auto_suggest=AutoSuggestFromHistory(),
                completer=completer,
                complete_while_typing=True,  # Enable real-time completion
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
            "timestamp": self.timestamp.isoformat()
            if isinstance(self.timestamp, object)
            else str(self.timestamp),
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

    def __init__(
        self, context_window: int = 10, persist: bool = False, user_id: str | None = None
    ) -> None:
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
        self._session_id: str | None = None
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
            "session_id": self._session_id,
            "user_id": self.user_id,
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

    def save(self, session_id: str | None = None, path: Path | None = None) -> Path:
        """Persist session to disk as JSON.

        Args:
            session_id: Optional session ID to use (auto-generated if None)
            path: Optional explicit path (overrides session directory)

        Returns:
            Path to the saved session file
        """
        if path is None:
            USER_SESSION_DIR.mkdir(parents=True, exist_ok=True)
            self._session_id = session_id or self._session_id or str(uuid.uuid4())
            path = USER_SESSION_DIR / f"{self._session_id}.json"
        else:
            self._session_id = session_id or self._session_id or path.stem

        payload = {
            "session_id": self._session_id,
            "user_id": self.user_id,
            "context_window": self.context_window,
            "persist": self.persist,
            "context": self.context,
            "storage": self._storage,
            "messages": [msg.to_dict() for msg in self.messages],
            "updated_at": datetime.utcnow().isoformat(),
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        return path

    @classmethod
    def load(cls, session_id: str | None = None, path: Path | None = None) -> "Session | None":
        """Load session from disk.

        Args:
            session_id: Session ID to load (used with default session dir)
            path: Explicit path to session file

        Returns:
            Session instance or None if not found
        """
        if path is None:
            if session_id is None:
                return None
            path = USER_SESSION_DIR / f"{session_id}.json"

        if not path.exists():
            return None

        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load session from {path}: {e}")
            return None

        session = cls(
            context_window=payload.get("context_window", 10),
            persist=payload.get("persist", False),
            user_id=payload.get("user_id"),
        )
        session._session_id = payload.get("session_id") or session_id
        session.context = payload.get("context", {})
        session._storage = payload.get("storage", {})

        messages = payload.get("messages", [])
        for item in messages:
            timestamp = item.get("timestamp")
            parsed_ts = None
            if timestamp:
                try:
                    parsed_ts = datetime.fromisoformat(timestamp)
                except Exception:
                    parsed_ts = None
            session.messages.append(
                Message(item.get("role", ""), item.get("content", ""), parsed_ts)
            )

        return session

    def auto_save(self, interval: float = 30.0) -> None:
        """Enable automatic periodic session saving (background task context).

        Args:
            interval: Save interval in seconds (default: 30s)

        Note:
            This method should be called with a background task scheduler.
            For actual periodic saving, use in combination with asyncio.create_task().
            Example:
                session = Session(persist=True)
                asyncio.create_task(session._auto_save_background(interval=30))

        Returns:
            None (saves in-place, updates file on disk)
        """
        if self.persist and self._session_id:
            try:
                self.save()
                logger.debug(f"Auto-saved session {self._session_id}")
            except Exception as e:
                logger.warning(f"Failed to auto-save session: {e}")

    async def auto_save_background(self, interval: float = 30.0) -> None:
        """Run background auto-save task (async version).

        Args:
            interval: Save interval in seconds (default: 30s)

        Example:
            session = Session(persist=True)
            await session.auto_save_background(interval=30)
        """
        import asyncio

        while self.persist and self._session_id:
            try:
                await asyncio.sleep(interval)
                self.save()
                logger.debug(f"Auto-saved session {self._session_id}")
            except Exception as e:
                logger.warning(f"Failed to auto-save session in background: {e}")
                break

    @classmethod
    def recover(cls, session_id: str) -> "Session | None":
        """Recover session from crash (alias for load for clarity).

        Args:
            session_id: Session ID to recover

        Returns:
            Recovered Session instance or None if not found

        Note:
            Identical to load() but semantically indicates recovery from crash.
        """
        return cls.load(session_id)

    @classmethod
    def get_recovery_options(cls) -> dict[str, dict]:
        """List available sessions that can be recovered.

        Returns:
            Dictionary mapping session_id → metadata (user_id, message_count, updated_at)

        Example:
            options = Session.get_recovery_options()
            for session_id, meta in options.items():
                print(f"{session_id}: {meta['message_count']} messages, "
                      f"user={meta['user_id']}, updated={meta['updated_at']}")
        """
        recovery_options = {}

        if not USER_SESSION_DIR.exists():
            return recovery_options

        try:
            for session_file in USER_SESSION_DIR.glob("*.json"):
                try:
                    with open(session_file, encoding="utf-8") as f:
                        payload = json.load(f)

                    session_id = payload.get("session_id", session_file.stem)
                    recovery_options[session_id] = {
                        "user_id": payload.get("user_id"),
                        "message_count": len(payload.get("messages", [])),
                        "updated_at": payload.get("updated_at"),
                        "path": str(session_file),
                    }
                except Exception as e:
                    logger.debug(f"Failed to read recovery option {session_file}: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Failed to list recovery options from {USER_SESSION_DIR}: {e}")

        return recovery_options

    def get_recovery_info(self) -> dict:
        """Get recovery information for current session.

        Returns:
            Dictionary with recovery metadata including path and state
        """
        return {
            "session_id": self._session_id,
            "user_id": self.user_id,
            "message_count": len(self.messages),
            "context_keys": list(self.context.keys()),
            "storage_keys": list(self._storage.keys()),
            "persisted": bool(
                self._session_id and (USER_SESSION_DIR / f"{self._session_id}.json").exists()
            ),
        }

    # ==================== Context Window Tracking ====================

    def get_context_usage(self) -> dict:
        """Get context window usage statistics.

        Returns:
            Dictionary with context usage information:
            - message_count: Number of messages in context
            - context_window: Maximum context window size (0 = unlimited)
            - usage_percent: Percentage of context used (0-100, None if unlimited)
            - messages_until_limit: How many more messages fit (None if unlimited)
            - is_full: Whether context window is full
        """
        usage_percent = None
        messages_until_limit = None
        is_full = False

        if self.context_window > 0:
            usage_percent = (len(self.messages) / self.context_window) * 100
            messages_until_limit = max(0, self.context_window - len(self.messages))
            is_full = len(self.messages) >= self.context_window

        return {
            "message_count": len(self.messages),
            "context_window": self.context_window,
            "usage_percent": usage_percent,
            "messages_until_limit": messages_until_limit,
            "is_full": is_full,
        }

    def get_context_summary(self, max_length: int = 200) -> str:
        """Generate a summary of conversation context.

        Args:
            max_length: Maximum length of each message in summary

        Returns:
            Formatted string summarizing the conversation context

        Example:
            summary = session.get_context_summary()
            print(summary)  # Shows message count, window info, recent messages
        """
        usage = self.get_context_usage()

        # Build summary header
        summary_lines = []
        summary_lines.append("=== Context Summary ===")
        summary_lines.append(f"Messages: {usage['message_count']}")

        if usage["context_window"] > 0:
            summary_lines.append(
                f"Window: {usage['message_count']}/{usage['context_window']} "
                f"({usage['usage_percent']:.1f}%)"
            )
        else:
            summary_lines.append("Window: unlimited")

        # Add recent messages
        if self.messages:
            summary_lines.append("\nRecent messages:")
            for msg in self.messages[-3:]:
                # Truncate long content
                content = msg.content
                if len(content) > max_length:
                    content = content[:max_length] + "..."

                timestamp = (
                    msg.timestamp.strftime("%H:%M:%S")
                    if isinstance(msg.timestamp, object)
                    else str(msg.timestamp)
                )
                summary_lines.append(f"  [{msg.role.upper()} {timestamp}] {content}")
        else:
            summary_lines.append("\nNo messages in context")

        return "\n".join(summary_lines)

    def get_context_truncated(self, max_messages: int | None = None) -> "Session":
        """Get a truncated copy of context for display/transmission.

        Args:
            max_messages: Maximum messages to include (uses context_window if None)

        Returns:
            New Session instance with truncated message history

        Example:
            # Get summary version for transmission
            summary_session = session.get_context_truncated(max_messages=5)
        """
        max_msg = max_messages or self.context_window or len(self.messages)
        truncated = Session(
            context_window=max_msg,
            persist=False,
            user_id=self.user_id,
        )

        # Copy last max_msg messages
        truncated.messages = self.messages[-max_msg:] if self.messages else []
        truncated.context = self.context.copy()
        truncated._storage = self._storage.copy()
        truncated._session_id = self._session_id

        return truncated

    def track_context_usage(self, threshold_percent: float = 80.0) -> dict | None:
        """Track context window usage and return warning if threshold exceeded.

        Args:
            threshold_percent: Percentage threshold for warning (default 80%)

        Returns:
            Dictionary with warning info if threshold exceeded, None otherwise

        Example:
            warning = session.track_context_usage(threshold_percent=80)
            if warning:
                print(f"Warning: Context {warning['usage_percent']:.1f}% full")
                print(f"Messages until eviction: {warning['messages_until_limit']}")
        """
        if self.context_window <= 0:
            return None

        usage = self.get_context_usage()

        if usage["usage_percent"] >= threshold_percent:
            return {
                "warning": True,
                "usage_percent": usage["usage_percent"],
                "message_count": usage["message_count"],
                "context_window": usage["context_window"],
                "messages_until_limit": usage["messages_until_limit"],
                "threshold": threshold_percent,
            }

        return None

    def clear_oldest_messages(self, count: int) -> list[Message]:
        """Remove oldest messages from context.

        Args:
            count: Number of oldest messages to remove

        Returns:
            List of removed messages

        Example:
            removed = session.clear_oldest_messages(5)
            print(f"Removed {len(removed)} oldest messages")
        """
        removed = []
        for _ in range(min(count, len(self.messages))):
            if self.messages:
                removed.append(self.messages.pop(0))

        return removed

    def estimate_context_size_tokens(self) -> dict:
        """Estimate token count for context (simple estimation).

        Returns:
            Dictionary with token estimates:
            - estimated_tokens: Total estimated tokens in context
            - avg_tokens_per_message: Average tokens per message
            - messages: Number of messages

        Note:
            Uses simple estimation: ~4 characters ≈ 1 token
            For precise token counting, use tiktoken library
        """
        total_chars = 0

        for msg in self.messages:
            # Role takes roughly 4 tokens ("user", "assistant", etc.)
            total_chars += len(msg.role) + len(msg.content) + 4

        # Simple estimation: ~4 characters per token
        estimated_tokens = total_chars // 4

        avg_per_msg = estimated_tokens / len(self.messages) if self.messages else 0

        return {
            "estimated_tokens": estimated_tokens,
            "avg_tokens_per_message": int(avg_per_msg),
            "messages": len(self.messages),
        }

    def count_tokens_tiktoken(self, model: str = "gpt-3.5-turbo") -> dict | None:
        """Count tokens using tiktoken (OpenAI tokenizer).

        Args:
            model: Model name for tokenizer (default: gpt-3.5-turbo)

        Returns:
            Dictionary with token counts or None if tiktoken not available:
            - total_tokens: Total tokens in all messages
            - messages: List of dicts with per-message token counts
            - avg_tokens_per_message: Average tokens per message
            - max_tokens_single_message: Longest message in tokens

        Note:
            Requires tiktoken: `pip install tiktoken`
            Common models: gpt-3.5-turbo, gpt-4, gpt-4-turbo

        Example:
            tokens = session.count_tokens_tiktoken(model="gpt-4")
            if tokens:
                print(f"Total: {tokens['total_tokens']} tokens")
                print(f"Average: {tokens['avg_tokens_per_message']} per message")
        """
        try:
            import tiktoken
        except ImportError:
            logger.warning("tiktoken not installed, install with: pip install tiktoken")
            return None

        try:
            encoding = tiktoken.encoding_for_model(model)
        except Exception as e:
            logger.warning(f"Failed to get encoding for model {model}: {e}")
            return None

        message_tokens = []
        total_tokens = 0

        for msg in self.messages:
            # Count tokens for this message
            msg_text = f"{msg.role}: {msg.content}"
            tokens = encoding.encode(msg_text)
            count = len(tokens)

            message_tokens.append(
                {
                    "role": msg.role,
                    "content_preview": msg.content[:50] + "..."
                    if len(msg.content) > 50
                    else msg.content,
                    "token_count": count,
                }
            )
            total_tokens += count

        avg_per_msg = total_tokens / len(self.messages) if self.messages else 0
        max_tokens = max([m["token_count"] for m in message_tokens]) if message_tokens else 0

        return {
            "total_tokens": total_tokens,
            "messages": message_tokens,
            "avg_tokens_per_message": int(avg_per_msg),
            "max_tokens_single_message": max_tokens,
            "model": model,
        }

    def get_token_limit(self, model: str | None = None) -> dict:
        """Get token limit information for a model.

        Args:
            model: Model name (defaults to configured LLM model)

        Returns:
            Dictionary with token limit information:
            - model: Model name
            - context_window: Maximum context tokens
            - estimated_input_tokens: Estimated tokens used
            - available_tokens: Remaining tokens for response
            - usage_percent: Percentage of context used
        
        Note: Uses settings.llm_max_tokens as context window (no hardcoded limits).
        """
        from config.settings import settings
        
        # Use configured model if not specified
        if not model:
            model = settings.llm_model_name
        
        # Use configured context window (no hardcoded model-specific limits)
        context_limit = settings.llm_max_tokens  # 从配置读取，而非硬编码

        # Get estimated tokens
        estimate = self.estimate_context_size_tokens()
        estimated_tokens = estimate["estimated_tokens"]

        available = max(0, context_limit - estimated_tokens)
        usage_percent = (estimated_tokens / context_limit) * 100 if context_limit > 0 else 0.0

        return {
            "model": model,
            "context_window": context_limit,
            "estimated_input_tokens": estimated_tokens,
            "available_tokens": available,
            "usage_percent": usage_percent,
        }

    def check_token_limit_warning(
        self, model: str = "gpt-3.5-turbo", threshold_percent: float = 80.0
    ) -> dict | None:
        """Check if token usage exceeds threshold and return warning.

        Args:
            model: Model name
            threshold_percent: Percentage threshold for warning (default 80%)

        Returns:
            Warning dictionary if threshold exceeded, None otherwise

        Example:
            warning = session.check_token_limit_warning(model="gpt-4", threshold_percent=80)
            if warning:
                print(f"Warning: {warning['usage_percent']:.1f}% of tokens used")
                print(f"Available for response: {warning['available_tokens']} tokens")
        """
        info = self.get_token_limit(model)

        if info["usage_percent"] >= threshold_percent:
            return {
                "warning": True,
                "model": model,
                "usage_percent": info["usage_percent"],
                "estimated_tokens": info["estimated_input_tokens"],
                "context_window": info["context_window"],
                "available_tokens": info["available_tokens"],
                "threshold": threshold_percent,
                "recommendation": "Consider clearing old messages or using a model with larger context window",
            }

        return None

    # ==================== Conversation Summarization ====================

    def get_conversation_summary(self, max_messages: int = 5, max_length: int = 100) -> str:
        """Get a brief summary of the conversation.

        Args:
            max_messages: Maximum recent messages to include in summary
            max_length: Maximum length for each message in summary

        Returns:
            String summary of recent conversation

        Example:
            summary = session.get_conversation_summary(max_messages=3)
            print(f"Recent conversation:\\n{summary}")
        """
        if not self.messages:
            return "No messages in conversation"

        summary_lines = ["Recent Conversation Summary:", ""]

        # Get recent messages
        recent = (
            self.messages[-max_messages:] if len(self.messages) > max_messages else self.messages
        )

        for i, msg in enumerate(recent, 1):
            content = msg.content
            if len(content) > max_length:
                content = content[:max_length] + "..."

            timestamp = (
                msg.timestamp.strftime("%H:%M") if isinstance(msg.timestamp, object) else "unknown"
            )

            summary_lines.append(f"{i}. [{msg.role.upper()} @ {timestamp}]")
            summary_lines.append(f"   {content}")
            summary_lines.append("")

        return "\n".join(summary_lines)

    def summarize_conversation_simple(self) -> dict:
        """Generate simple statistics-based summary of conversation.

        Returns:
            Dictionary with conversation statistics:
            - total_messages: Total messages in conversation
            - user_messages: Count of user messages
            - assistant_messages: Count of assistant messages
            - avg_message_length: Average message length in characters
            - longest_message_length: Longest message length
            - shortest_message_length: Shortest message length
            - conversation_duration: Time span of conversation (if timestamps available)
            - topics: Simple word frequency analysis (most common words)
        """
        if not self.messages:
            return {
                "total_messages": 0,
                "user_messages": 0,
                "assistant_messages": 0,
                "avg_message_length": 0,
                "longest_message_length": 0,
                "shortest_message_length": 0,
                "summary": "No messages in conversation",
            }

        # Count messages by role
        user_msgs = [m for m in self.messages if m.role == "user"]
        assistant_msgs = [m for m in self.messages if m.role == "assistant"]

        # Calculate message lengths
        lengths = [len(m.content) for m in self.messages]
        avg_length = sum(lengths) / len(lengths) if lengths else 0

        # Extract common words for topic analysis (simple version)
        all_text = " ".join([m.content.lower() for m in self.messages])
        words = all_text.split()
        common_words = self._get_most_common_words(words, top_n=5)

        # Calculate conversation duration if timestamps available
        duration = None
        if len(self.messages) >= 2:
            try:
                first_ts = self.messages[0].timestamp
                last_ts = self.messages[-1].timestamp
                if isinstance(first_ts, object) and isinstance(last_ts, object):
                    duration = (last_ts - first_ts).total_seconds()
            except Exception as e:
                logger.debug(f"Failed to calculate conversation duration: {e}")

        return {
            "total_messages": len(self.messages),
            "user_messages": len(user_msgs),
            "assistant_messages": len(assistant_msgs),
            "avg_message_length": int(avg_length),
            "longest_message_length": max(lengths) if lengths else 0,
            "shortest_message_length": min(lengths) if lengths else 0,
            "conversation_duration_seconds": duration,
            "common_words": common_words,
            "first_message_time": (
                self.messages[0].timestamp.isoformat()
                if isinstance(self.messages[0].timestamp, object)
                else None
            ),
            "last_message_time": (
                self.messages[-1].timestamp.isoformat()
                if isinstance(self.messages[-1].timestamp, object)
                else None
            ),
        }

    @staticmethod
    def _get_most_common_words(words: list[str], top_n: int = 5) -> list[str]:
        """Get most common words from a word list (excluding stopwords).

        Args:
            words: List of words
            top_n: Number of top words to return

        Returns:
            List of most common words
        """
        # Simple English stopwords
        stopwords = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "can",
            "must",
            "shall",
            "if",
            "what",
            "which",
            "who",
            "when",
            "where",
            "why",
            "how",
            "i",
            "you",
            "he",
            "she",
            "it",
            "we",
            "they",
            "me",
            "him",
            "her",
            "us",
            "them",
            "my",
            "your",
            "his",
            "its",
            "our",
            "their",
            "this",
            "that",
            "these",
            "those",
        }

        # Count word frequency (excluding stopwords)
        word_freq = {}
        for word in words:
            # Clean word and filter
            clean_word = word.lower().strip(".,!?;:\"'")
            if clean_word and len(clean_word) > 2 and clean_word not in stopwords:
                word_freq[clean_word] = word_freq.get(clean_word, 0) + 1

        # Sort by frequency
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)

        return [word for word, _ in sorted_words[:top_n]]

    def get_conversation_topics(self) -> list[str]:
        """Extract potential conversation topics from messages.

        Returns:
            List of potential topic keywords

        Example:
            topics = session.get_conversation_topics()
            print(f"Conversation topics: {', '.join(topics)}")
        """
        if not self.messages:
            return []

        summary = self.summarize_conversation_simple()
        return summary.get("common_words", [])

    def create_session_transcript(self, include_timestamps: bool = True) -> str:
        """Create a full transcript of the conversation.

        Args:
            include_timestamps: Whether to include message timestamps

        Returns:
            Formatted transcript string

        Example:
            transcript = session.create_session_transcript()
            with open("conversation.txt", "w") as f:
                f.write(transcript)
        """
        if not self.messages:
            return "No conversation history"

        lines = []
        lines.append("=== Conversation Transcript ===")
        lines.append(f"Session ID: {self._session_id or 'Not saved'}")
        lines.append(f"User ID: {self.user_id or 'Anonymous'}")
        lines.append(f"Messages: {len(self.messages)}")
        lines.append("")

        for i, msg in enumerate(self.messages, 1):
            timestamp = ""
            if include_timestamps and isinstance(msg.timestamp, object):
                timestamp = f" @ {msg.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"

            lines.append(f"[{i}] {msg.role.upper()}{timestamp}")
            lines.append(msg.content)
            lines.append("")

        return "\n".join(lines)

    def export_to_json(self, include_metadata: bool = True) -> dict:
        """Export conversation to JSON-serializable format.

        Args:
            include_metadata: Whether to include session metadata

        Returns:
            Dictionary suitable for JSON serialization

        Example:
            export = session.export_to_json()
            import json
            with open("export.json", "w") as f:
                json.dump(export, f)
        """
        export_dict = {
            "messages": [msg.to_dict() for msg in self.messages],
        }

        if include_metadata:
            export_dict.update(
                {
                    "session_id": self._session_id,
                    "user_id": self.user_id,
                    "context_window": self.context_window,
                    "message_count": len(self.messages),
                    "context": self.context,
                    "summary": self.summarize_conversation_simple(),
                }
            )

        return export_dict

    # ==================== Database Query Integration ====================

    def get_cache(self, query: str):
        """Get cached database query result.

        Args:
            query: SQL query string

        Returns:
            Cached result or None if not found
        """
        from src.olav.core.database_enhancer import get_database_enhancer

        enhancer = get_database_enhancer()
        return enhancer.get_cache(query)

    def clear_cache(self) -> None:
        """Clear all cached database queries."""
        from src.olav.core.database_enhancer import get_database_enhancer

        enhancer = get_database_enhancer()
        enhancer.clear_cache()

    def execute_query(self, query: str, use_cache: bool = False, timeout: float | None = None):
        """Execute database query with optional caching and timeout.

        Args:
            query: SQL query string
            use_cache: Whether to use query cache
            timeout: Query timeout in seconds (optional)

        Returns:
            Query result

        Example:
            # Basic query
            result = session.execute_query("SELECT * FROM users")

            # With caching
            result = session.execute_query("SELECT COUNT(*) FROM devices", use_cache=True)

            # With timeout
            result = session.execute_query("SELECT * FROM large_table", timeout=30.0)
        """
        from src.olav.core.database_enhancer import get_database_enhancer

        enhancer = get_database_enhancer()

        if use_cache:
            return enhancer.execute_cached(query)
        elif timeout:
            return enhancer.execute_with_timeout(query, timeout)
        else:
            return enhancer.execute(query)

    def batch_insert(self, table: str, rows: list[dict]) -> int:
        """Execute batch insert operation.

        Args:
            table: Target table name
            rows: List of row dictionaries to insert

        Returns:
            Number of rows inserted

        Example:
            rows = [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ]
            count = session.batch_insert("users", rows)
            print(f"Inserted {count} rows")
        """
        from src.olav.core.database_enhancer import get_database_enhancer

        enhancer = get_database_enhancer()
        return enhancer.execute_batch_insert(table, rows)
