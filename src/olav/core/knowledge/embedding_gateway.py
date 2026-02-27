"""Embedding Generation Framework

Provides generic embedding interface using OLAV unified LLM system.
"""

import logging
from typing import Any

from olav.core.llm import LLMFactory

logger = logging.getLogger(__name__)


class EmbeddingGateway:
    """Generic embedding generation interface.
    
    Uses OLAV unified LLM system (supports OpenAI, Ollama, etc).
    This is framework code - no business logic.
    """

    def __init__(self):
        """Initialize embedding gateway.
        
        Raises:
            ValueError: If LLM_API_KEY not configured
        """
        try:
            self.embeddings = LLMFactory.get_embeddings()
            logger.info("✓ Using OLAV unified LLM system for embeddings")
        except ValueError as e:
            logger.error(f"Embeddings initialization failed: {e}")
            raise
        
        # Get embedding dimension
        try:
            test_embedding = self.embeddings.embed_query("test")
            self.embedding_dim = len(test_embedding)
            logger.info(f"✓ Detected embedding dimension: {self.embedding_dim}")
        except Exception as e:
            logger.error(f"Could not determine embedding dimension: {e}")
            # Fallback to OpenAI default if can't determine
            self.embedding_dim = 1536
            logger.warning(f"Using fallback embedding dimension: {self.embedding_dim}")
    
    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for text.
        
        Args:
            text: Text to embed
        
        Returns:
            Embedding vector (float list)
        
        Raises:
            Exception: If embedding generation fails
        """
        try:
            embedding = self.embeddings.embed_query(text)
            return embedding
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            raise
    
    def embed_batch(self, texts: list[str], batch_size: int = 100) -> list[list[float]]:
        """Generate embeddings for multiple texts.
        
        Args:
            texts: List of texts to embed
            batch_size: Process this many at once
        
        Returns:
            List of embedding vectors
        """
        embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            try:
                batch_embeddings = self.embeddings.embed_documents(batch)
                embeddings.extend(batch_embeddings)
                logger.debug(f"Embedded batch {i//batch_size + 1}: {len(batch)} texts")
            except Exception as e:
                logger.error(f"Failed to embed batch starting at {i}: {e}")
                raise
        
        return embeddings
    
    def get_embedding_config(self) -> dict[str, Any]:
        """Get embedding configuration for metadata/tracking.
        
        Returns:
            Dict with embedding_mode, embedding_model, embedding_dim
        """
        from olav.core.config import settings
        
        embedding_mode = settings.embedding_mode
        embedding_model = (
            settings.embedding_local_model 
            if embedding_mode == "local" 
            else settings.embedding_model
        )
        
        return {
            'embedding_mode': embedding_mode,
            'embedding_model': embedding_model,
            'embedding_dim': self.embedding_dim
        }
