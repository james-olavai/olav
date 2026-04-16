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
                    import os as _os
                    # Suppress C-level stdout+stderr (safetensors shard reports come on fd 2)
                    _saved1 = _os.dup(1)
                    _saved2 = _os.dup(2)
                    _null = _os.open(_os.devnull, _os.O_WRONLY)
                    _os.dup2(_null, 1)
                    _os.dup2(_null, 2)
                    try:
                        _local_embedder = SentenceTransformer(
                            resolved_model, device=device
                        )
                    finally:
                        _os.dup2(_saved1, 1)
                        _os.dup2(_saved2, 2)
                        _os.close(_null)
                        _os.close(_saved1)
                        _os.close(_saved2)
                    logger.info(
                        "Shared embedder loaded (device=%s): %s", device, resolved_model
                    )
                except Exception as _load_err:
                    logger.warning(
                        "Embedder model '%s' failed to load: %s. "
                        "Run `olav init` to download, or set "
                        "`embedding.mode = \"none\"` to disable.",
                        resolved_model, _load_err,
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


_detected_dim: int | None = None


def detect_embedding_dim() -> int:
    """Detect the actual embedding dimension by running a probe.

    Result is cached for the process lifetime.  All components that need
    the dimension (MemoryStore, SemanticRouter, AutoCapture) should call
    this instead of hardcoding a value.
    """
    global _detected_dim
    if _detected_dim is not None:
        return _detected_dim

    vec = embed_text("dimension probe")
    if vec is not None:
        _detected_dim = len(vec)
        logger.info("Detected embedding dimension: %d", _detected_dim)
        return _detected_dim

    # Fallback: ask local embedder directly
    emb = get_embedder()
    if emb is not None:
        dim_fn = getattr(emb, "get_embedding_dimension", None) or getattr(emb, "get_sentence_embedding_dimension", None)
        if dim_fn:
            _detected_dim = int(dim_fn())
            return _detected_dim

    _detected_dim = 512  # safe default for bge-small-zh-v1.5
    return _detected_dim


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
