"""Shared SentenceTransformer singleton for the whole OLAV process.

All components that need text embeddings should call ``get_embedder()``
instead of constructing their own ``SentenceTransformer`` instance.
This keeps peak memory at one model load (~90 MB) regardless of how
many middleware/plugin/tool modules are imported.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_embedder = None


def get_embedder(model: str = "BAAI/bge-small-en-v1.5"):
    """Return the process-wide SentenceTransformer singleton.

    Returns ``None`` (never raises) when ``sentence_transformers`` is
    not installed or the model fails to load, so callers can degrade
    gracefully.
    """
    global _embedder
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import]

            _embedder = SentenceTransformer(model)
            logger.info("Shared embedder loaded: %s", model)
        except Exception as exc:  # pragma: no cover – environment-specific
            logger.warning("Embedder unavailable (%s); memory features disabled.", exc)
            _embedder = False  # sentinel: do not retry
    return _embedder if _embedder else None
