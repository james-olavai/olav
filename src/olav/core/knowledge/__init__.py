"""Knowledge Management Framework Layer

This layer provides generic, reusable interfaces and algorithms for:
- Text processing and chunking
- Embedding generation
- Vector storage operations

It does NOT contain any business logic for specific knowledge domains.
Business implementations go in .olav/skills/shared/tools/kb_ops.py
"""

from .text_processor import TextProcessor
from .embedding_gateway import EmbeddingGateway

__all__ = ["TextProcessor", "EmbeddingGateway"]
