"""Knowledge Base Configuration - Single Source of Truth

All KB parameters in one place to avoid hardcoding and support dynamic tuning.
Follows OLAV v2.0 configuration principles (configuration separation).

Configuration Priority (high to low):
1. Environment variables (export KNOWLEDGE_CHUNK_SIZE=2000)
2. .olav/settings.json ({"knowledge": {"chunk_size": 2000}})
3. Code defaults (chunk_size: int = 1000)
"""

from pydantic import BaseSettings, Field
from typing import Literal


class KnowledgeSettings(BaseSettings):
    """Knowledge Base Settings - All KB parameters centralized"""

    # =========================================================================
    # Text Processing Configuration
    # =========================================================================
    
    chunk_size: int = Field(
        default=1000,
        ge=100,
        le=5000,
        description="Characters per chunk (typically 200-300 tokens after tokenization)"
    )
    
    chunk_overlap: int = Field(
        default=200,
        ge=0,
        le=1000,
        description="Overlap between chunks (recommended: 20% of chunk_size)"
    )

    # =========================================================================
    # Embedding Configuration
    # =========================================================================
    
    embedding_mode: Literal["local", "openai"] = Field(
        default="local",
        description="Embedding mode: 'local' (BAAI/bge-small-zh-v1.5, 512 dim) or 'openai' (text-embedding-3-small, 1536 dim)"
    )
    
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model name (used when embedding_mode='openai')"
    )
    
    embedding_local_model: str = Field(
        default="BAAI/bge-small-zh-v1.5",
        description="Local embedding model name (used when embedding_mode='local')"
    )
    
    embedding_fallback_dim: int = Field(
        default=512,
        description="Fallback embedding dimension if auto-detection fails (typically 512 for local, 1536 for OpenAI)"
    )

    # =========================================================================
    # Vector Search Configuration
    # =========================================================================
    
    similarity_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score (0-1) for knowledge search results"
    )
    
    max_results: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum knowledge chunks to return per search query"
    )

    # =========================================================================
    # Database Configuration
    # =========================================================================
    
    batch_size: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Number of rows per transaction during batch insert (performance tuning)"
    )

    # =========================================================================
    # Pydantic Configuration
    # =========================================================================

    class Config:
        """Pydantic config for automatic environment variable loading"""
        env_prefix = "KNOWLEDGE_"
        case_sensitive = False
        # Allow .olav/settings.json to override via load_dotenv
        env_file = ".olav/settings.json"
        json_file_encoding = "utf-8"

    # =========================================================================
    # Validation and Documentation
    # =========================================================================
    
    def __str__(self) -> str:
        """Human-readable configuration summary"""
        lines = [
            "📚 Knowledge Base Configuration:",
            f"  Text Processing:",
            f"    - chunk_size: {self.chunk_size} characters",
            f"    - chunk_overlap: {self.chunk_overlap} characters",
            f"  Embedding:",
            f"    - mode: {self.embedding_mode}",
            f"    - model: {self.embedding_local_model if self.embedding_mode == 'local' else self.embedding_model}",
            f"    - fallback_dim: {self.embedding_fallback_dim}",
            f"  Vector Search:",
            f"    - similarity_threshold: {self.similarity_threshold}",
            f"    - max_results: {self.max_results}",
            f"  Database:",
            f"    - batch_size: {self.batch_size} rows/transaction",
        ]
        return "\n".join(lines)
