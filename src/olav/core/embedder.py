"""Process-wide embedding service for OLAV.

Single entry point for all embedding operations:
  - API mode  (default): OpenAI-compatible client singleton → OpenRouter
  - Local mode:          SentenceTransformer singleton (offline/legacy)
  - None/disabled:       returns None, callers degrade to text-only search

All components call ``embed_text()`` — never construct clients themselves.
``get_embedder()`` is retained for local-mode callers that need the raw
SentenceTransformer object (e.g. dimension detection).
"""
from __future__ import annotations

import contextlib
import io
import logging

logger = logging.getLogger(__name__)

# ── Local-mode SentenceTransformer singleton ──────────────────────────────────
_local_embedder = None

# ── API-mode OpenAI client singleton ─────────────────────────────────────────
_api_client = None
_api_model: str | None = None


def get_embedder(model: str | None = None):
    """Return the process-wide SentenceTransformer singleton (local mode only).

    Configuration is read from ``EmbeddingConfig`` (`.olav/config/api.json`):

    - ``embedding.mode = "api"``  (preferred): returns ``None``; use
      ``embed_text()`` for actual embedding work — the API client is managed
      separately as ``_api_client``.
    - ``embedding.mode = "local"``: load the SentenceTransformer singleton
      specified by ``embedding.local.model`` on ``embedding.local.device``.
    - ``embedding.mode = "none"``: embedding disabled; returns ``None``.

    Returns ``None`` (never raises) on any failure so callers degrade
    gracefully.  Progress bars and verbose load reports are suppressed.
    """
    global _local_embedder
    if _local_embedder is None:
        try:
            from olav.core.config import get_embedding_config

            emb_cfg = get_embedding_config()
            mode = emb_cfg.mode  # "local" | "api" | "none"

            if mode in ("api", "none", "disabled"):
                logger.debug("Embedder skipped (mode=%s); use embed_text() for API embeddings.", mode)
                _local_embedder = False  # sentinel: do not retry
            else:
                # Local SentenceTransformer
                resolved_model = model or emb_cfg.local_model
                device = emb_cfg.device  # "cpu" | "cuda" | "mps"

                from sentence_transformers import SentenceTransformer  # type: ignore[import]

                for _noisy in ("sentence_transformers", "transformers", "transformers.modeling_utils"):
                    logging.getLogger(_noisy).setLevel(logging.ERROR)

                try:
                    with contextlib.redirect_stderr(io.StringIO()):
                        _local_embedder = SentenceTransformer(
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
                    _local_embedder = False  # sentinel: do not retry
        except Exception as exc:  # pragma: no cover – environment-specific
            logger.warning("Embedder unavailable (%s); memory features disabled.", exc)
            _local_embedder = False  # sentinel: do not retry
    return _local_embedder if _local_embedder else None


def _get_api_client():
    """Return the process-wide OpenAI-compatible API client singleton."""
    global _api_client, _api_model
    if _api_client is None:
        from olav.core.config import get_embedding_config

        cfg = get_embedding_config()
        import openai

        client_kwargs: dict = {"api_key": cfg.openai_api_key}
        if cfg.openai_base_url:
            client_kwargs["base_url"] = cfg.openai_base_url
        _api_client = openai.OpenAI(**client_kwargs)
        _api_model = cfg.openai_model
        logger.debug("API embedding client initialized (model=%s)", _api_model)
    return _api_client, _api_model


def embed_text(text: str) -> "list[float] | None":
    """Embed text using the configured embedding backend (api or local).

    In api mode, reuses the process-wide OpenAI-compatible client singleton.
    In local mode, delegates to the shared SentenceTransformer singleton.
    Returns None on any failure so callers degrade gracefully.
    """
    try:
        from olav.core.config import get_embedding_config

        cfg = get_embedding_config()
        if cfg.mode == "api":
            client, model = _get_api_client()
            resp = client.embeddings.create(input=text, model=model)
            return resp.data[0].embedding
        else:
            embedder = get_embedder()
            if embedder is None:
                return None
            return embedder.encode(text, normalize_embeddings=True).tolist()
    except Exception as exc:
        logger.warning("embed_text failed: %s", exc)
        return None
