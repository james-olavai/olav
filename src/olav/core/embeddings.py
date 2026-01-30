"""Unified Embedding interface for OLAV Semantic Routing.

Supports multiple providers via LangChain and provides a singleton manager
to avoid repeated model initialization.
"""

import logging
from typing import List, Protocol, runtime_checkable

from olav.core.llm import LLMFactory

logger = logging.getLogger(__name__)

@runtime_checkable
class Embedder(Protocol):
    """Protocol for embedding models."""

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query string."""
        ...

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of document strings."""
        ...


class EmbeddingManager:
    """Singleton manager for embedding models."""

    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def model(self):
        """Lazy load the embedding model."""
        if self._model is None:
            try:
                self._model = LLMFactory.get_embedding_model()
                logger.debug("Embedding model initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize embedding model: {e}")
                raise
        return self._model

    def embed_query(self, text: str) -> List[float]:
        """Convert a query string to a vector."""
        return self.model.embed_query(text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Convert a list of documents to vectors."""
        return self.model.embed_documents(texts)


def get_embedder() -> Embedder:
    """Entry point to get the configured embedder instance."""
    return EmbeddingManager()  # type: ignore[return-value]
