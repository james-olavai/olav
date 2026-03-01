"""Context Compression for OLAV.

Provides context compression using LangChain's ConversationSummaryBufferMemory
when an LLM is available, with fallback to basic compression when not.
"""

import logging
from typing import Any

from olav.core.defaults import CONTEXT_COMPRESSION_THRESHOLD

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKEN_LIMIT = 4000


class ContextCompressor:
    """Basic context compressor without LLM summarization.

    This is a fallback when no LLM is available.
    For production use with LLM, use LangChain's ConversationSummaryBufferMemory.
    """

    def __init__(
        self,
        max_token_limit: int = DEFAULT_MAX_TOKEN_LIMIT,
        llm=None,
    ):
        self.max_token_limit = max_token_limit
        self.llm = llm
        self._messages = []
        self._langchain_memory = None

        # Try to use LangChain's ConversationSummaryBufferMemory if LLM is provided
        if llm is not None:
            self._init_langchain_memory()

    def _init_langchain_memory(self):
        """Initialize LangChain's ConversationSummaryBufferMemory."""
        try:
            from langchain.memory import ConversationSummaryBufferMemory
            from langchain.schema import AIMessage, HumanMessage, SystemMessage

            self._langchain_memory = ConversationSummaryBufferMemory(
                llm=self.llm,
                max_token_limit=self.max_token_limit,
                return_messages=True,
            )
            logger.info("Initialized LangChain ConversationSummaryBufferMemory")
        except ImportError as e:
            logger.warning(f"LangChain not available, using basic compression: {e}")
            self._langchain_memory = None
        except Exception as e:
            logger.warning(f"Failed to initialize LangChain memory: {e}")
            self._langchain_memory = None

    def add_message(self, role: str, content: str):
        """Add a message to the context."""
        if self._langchain_memory is not None:
            # Use LangChain memory
            from langchain.schema import AIMessage, HumanMessage, SystemMessage

            if role == "user":
                self._langchain_memory.chat_memory.add_user_message(content)
            elif role == "assistant":
                self._langchain_memory.chat_memory.add_ai_message(content)
            elif role == "system":
                self._langchain_memory.chat_memory.add_message(SystemMessage(content))
        else:
            # Use basic memory
            self._messages.append({"role": role, "content": content})

    def add_messages(self, messages: list[dict[str, str]]):
        """Add multiple messages to the context."""
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            self.add_message(role, content)

    def get_context(self) -> str:
        """Get the current context as a string."""
        if self._langchain_memory is not None:
            # Get summary from LangChain memory
            try:
                return self._langchain_memory.load_memory_variables({}).get("history", "")
            except Exception as e:
                logger.warning(f"Failed to load LangChain memory: {e}")

        # Fallback to basic
        return "\n".join([f"{m['role']}: {m['content']}" for m in self._messages])

    def get_messages(self) -> list:
        """Get the current messages."""
        if self._langchain_memory is not None:
            try:
                return self._langchain_memory.chat_memory.messages
            except Exception:
                pass
        return self._messages

    def clear(self):
        """Clear all messages."""
        if self._langchain_memory is not None:
            self._langchain_memory.clear()
        self._messages = []

    def should_compress(self) -> bool:
        """Check if compression is needed."""
        if self._langchain_memory is not None:
            # LangChain handles this internally
            try:
                memory_vars = self._langchain_memory.load_memory_variables({})
                token_count = len(memory_vars.get("history", "").split())
                return token_count > self.max_token_limit
            except Exception:
                pass
        return len(self._messages) > CONTEXT_COMPRESSION_THRESHOLD

    def compress(self) -> str:
        """Compress the context using LLM summary if available."""
        if self._langchain_memory is not None:
            try:
                # LangChain will auto-compress based on max_token_limit
                summary = self._langchain_memory.load_memory_variables({}).get("history", "")[:200]
                logger.info("Context compressed via LangChain memory")
                return f"[Summary: {summary}...]"
            except Exception as e:
                logger.warning(f"Failed to compress via LangChain: {e}")

        # Fallback to basic compression
        if not self._messages:
            return ""

        summary = f"[Summary of {len(self._messages)} messages]"
        self._messages = [{"role": "system", "content": summary}]

        logger.info(f"Compressed context: {len(self._messages)} messages")
        return summary


def create_context_compressor(max_tokens: int = 4000, llm=None) -> ContextCompressor:
    """Create a context compressor.

    Args:
        max_tokens: Maximum token limit for context
        llm: Optional LangChain LLM instance for smart compression

    Returns:
        ContextCompressor instance
    """
    return ContextCompressor(max_token_limit=max_tokens, llm=llm)
