"""Shared SentenceTransformer singleton for the whole OLAV process.

All components that need text embeddings should call ``get_embedder()``
instead of constructing their own ``SentenceTransformer`` instance.
This keeps peak memory at one model load (~90 MB) regardless of how
many middleware/plugin/tool modules are imported.
"""
from __future__ import annotations

import contextlib
import io
import logging

logger = logging.getLogger(__name__)

_embedder = None


def get_embedder(model: str | None = None):
    """Return the process-wide SentenceTransformer singleton.

    Configuration is read from ``EmbeddingConfig`` (`.olav/config/api.json`):

    - ``embedding.mode = "local"``  (default): load the SentenceTransformer
      specified by ``embedding.local.model`` on ``embedding.local.device``.
    - ``embedding.mode = "api"``: callers should use
      ``LLMFactory.get_embeddings()`` instead; returns ``None`` immediately
      so AutoRecall / SemanticRouter fall back to text-only search.
    - ``embedding.mode = "none"``: embedding disabled; returns ``None``.

    Returns ``None`` (never raises) on any failure so callers degrade
    gracefully.  Progress bars and verbose load reports are suppressed.
    """
    global _embedder
    if _embedder is None:
        try:
            from olav.core.config import get_embedding_config

            emb_cfg = get_embedding_config()
            mode = emb_cfg.mode  # "local" | "api" | "none"

            if mode in ("api", "none", "disabled"):
                # API mode: embeddings are handled by LLMFactory.get_embeddings().
                # None mode: disabled by operator choice.
                logger.debug("Embedder skipped (mode=%s); text-only memory search active.", mode)
                _embedder = False  # sentinel: do not retry
            else:
                # Local SentenceTransformer
                resolved_model = model or emb_cfg.local_model
                device = emb_cfg.device  # "cpu" | "cuda" | "mps"

                from sentence_transformers import SentenceTransformer  # type: ignore[import]

                # Silence verbose LOAD REPORT and progress bars.  These loggers
                # hold the *original* sys.stderr captured at handler-creation
                # time, so redirect_stderr alone is insufficient.
                for _noisy in ("sentence_transformers", "transformers", "transformers.modeling_utils"):
                    logging.getLogger(_noisy).setLevel(logging.ERROR)

                try:
                    with contextlib.redirect_stderr(io.StringIO()):
                        _embedder = SentenceTransformer(
                            resolved_model, local_files_only=True, device=device
                        )
                    logger.info(
                        "Shared embedder loaded (local cache, device=%s): %s", device, resolved_model
                    )
                except OSError:
                    logger.info(
                        "Embedder model '%s' not in local cache; semantic memory disabled. "
                        "Run `olav config download-embedder` to pre-fetch, or set "
                        "`embedding.mode = \"none\"` to suppress this message.",
                        resolved_model,
                    )
                    _embedder = False  # sentinel: do not retry
        except Exception as exc:  # pragma: no cover – environment-specific
            logger.warning("Embedder unavailable (%s); memory features disabled.", exc)
            _embedder = False  # sentinel: do not retry
    return _embedder if _embedder else None
