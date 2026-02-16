"""Knowledge Base Configuration - Single Source of Truth

All KB parameters consolidated in one place for easy maintenance and configuration.
"""

from pydantic import Field, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class KnowledgeSettings(BaseSettings):
    """Knowledge base configuration - all KB parameters in one class.
    
    Can be configured via:
    1. Environment variables: KNOWLEDGE_*
    2. .olav/settings.json: {"knowledge": {...}}
    3. Defaults below
    
    Priority: env vars > settings.json > defaults
    """
    
    model_config = SettingsConfigDict(
        env_prefix="KNOWLEDGE_",
        case_sensitive=False,
        extra="ignore",  # Ignore extra environment variables
    )
    
    # ========== Text Processing ==========
    chunk_size: int = Field(
        default=1000,
        ge=100,
        le=4000,
        description="Characters per chunk (1000 ≈ 200-300 tokens)"
    )
    chunk_overlap: int = Field(
        default=200,
        ge=0,
        le=1000,
        description="Overlap between chunks (typically 20% of chunk_size)"
    )
    
    # ========== Embedding & Vector DB ==========
    embedding_mode: Literal["local", "openai", "ollama"] = Field(
        default="local",
        description="Embedding backend: local (BAAI), openai, or ollama"
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model (for remote embeddings)"
    )
    embedding_local_model: str = Field(
        default="BAAI/bge-small-zh-v1.5",
        description="Local embedding model (HuggingFace)"
    )
    embedding_fallback_dim: int = Field(
        default=512,
        description="Fallback embedding dimension if detection fails"
    )
    
    # ========== Vector Search ==========
    similarity_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score (0-1) for search results"
    )
    max_results: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum knowledge chunks to return per query"
    )
    
    # ========== Database ==========
    batch_size: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Rows per batch during bulk insert (transaction size)"
    )
