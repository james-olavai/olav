"""Process-wide embedding service for OLAV.

Single entry point for all embedding operations:
  - API mode  (default): OpenAI-compatible client singleton → OpenRouter
  - Local mode:          SentenceTransformer singleton (offline/legacy)
  - None/disabled:       returns None, callers degrade to text-only search

All components call ``embed_text()`` — never construct clients themselves.
``get_embedder()`` is retained for local-mode callers that need the raw
SentenceTransformer object (e.g. dimension detection).

LEGACY-KEEP: local mode is labelled "legacy" because API mode is the
default since v0.15, but offline deployments still need it — keep it.
"""
from __future__ import annotations

import hashlib
import logging
import os
from collections import OrderedDict

logger = logging.getLogger(__name__)

# ── Local-mode SentenceTransformer singleton ──────────────────────────────────
_local_embedder = None

# ── API-mode OpenAI client singleton ─────────────────────────────────────────
_api_client = None
_api_model: str | None = None

# ── In-process embedding cache (LRU, sha256-keyed) ──────────────────────────
# Same text → same vector; multi-step agent flows often re-embed identical
# user messages 5-7× per chapter (orchestrator + sub-agents + tool decisions
# all run AutoRecallMiddleware.abefore_model). The cache turns those
# repeats into 1 real API call + N memory hits.
#
# Cap controlled by ``OLAV_EMBED_CACHE_SIZE`` env var (default 1024 entries
# ≈ ~6 MB at 1536-dim float32). Set to 0 to disable.
_EMBED_CACHE_MAX = int(os.environ.get("OLAV_EMBED_CACHE_SIZE", "1024"))
_embed_cache: "OrderedDict[str, list[float]]" = OrderedDict()
_embed_cache_stats = {"hits": 0, "misses": 0}


def _cache_get(text: str) -> "list[float] | None":
    """Return cached vector for ``text`` or ``None``. LRU bump on hit."""
    if _EMBED_CACHE_MAX <= 0:
        return None
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    vec = _embed_cache.get(key)
    if vec is not None:
        _embed_cache.move_to_end(key)
        _embed_cache_stats["hits"] += 1
        return vec
    _embed_cache_stats["misses"] += 1
    return None


def _cache_put(text: str, vec: "list[float]") -> None:
    """Store ``text → vec`` in LRU; evict oldest if at capacity."""
    if _EMBED_CACHE_MAX <= 0:
        return
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()
    _embed_cache[key] = vec
    _embed_cache.move_to_end(key)
    while len(_embed_cache) > _EMBED_CACHE_MAX:
        _embed_cache.popitem(last=False)


def get_embed_cache_stats() -> dict[str, int]:
    """Return current cache hit/miss counters + size. For diagnostics."""
    return {**_embed_cache_stats, "size": len(_embed_cache)}


def clear_embed_cache() -> None:
    """Reset cache + stats. Useful in tests or after config switch."""
    _embed_cache.clear()
    _embed_cache_stats["hits"] = 0
    _embed_cache_stats["misses"] = 0


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

    Process-wide LRU cache (configurable via ``OLAV_EMBED_CACHE_SIZE``,
    default 1024 entries) deduplicates identical text — typical multi-
    step agent flows re-embed the same user message 5-7× per chapter,
    so the cache typically converts those into 1 real API call + N
    memory hits without changing semantics.
    """
    if not text:
        return None

    # R100/S3 (2026-04-29): cap input length to protect against
    # llama-server's per-request batch_size ceiling.  When OLAV
    # AutoCapture embeds a growing conversation (system prompt + tool
    # outputs + thinking traces), the input length grows past the
    # embed server's ``--batch-size`` setting and llama-server returns
    # 500 ``input (N tokens) is too large to process``.  Demo7 Ch8
    # observed 5791 → 8650 → 11507 token inputs failing the
    # batch=4096 / 8192 server caps respectively.  Truncating to
    # ~6000 chars (≈ 1500-2000 tokens for English / SQL / mermaid
    # mixed content) is a safe upper bound that fits the typical
    # embed-server batch_size.  Override via env
    # ``OLAV_EMBED_MAX_CHARS`` (0 = no cap).
    _max_chars_env = os.environ.get("OLAV_EMBED_MAX_CHARS")
    try:
        _max_chars = int(_max_chars_env) if _max_chars_env else 6000
    except ValueError:
        _max_chars = 6000
    if _max_chars > 0 and len(text) > _max_chars:
        original_len = len(text)
        text = text[:_max_chars]
        logger.debug(
            "embed_text input truncated: %d → %d chars (cap=%d, set "
            "OLAV_EMBED_MAX_CHARS=0 to disable)",
            original_len, _max_chars, _max_chars,
        )

    cached = _cache_get(text)
    if cached is not None:
        return cached
    try:
        from olav.core.config import get_embedding_config

        cfg = get_embedding_config()
        if cfg.mode == "api":
            client, model = _get_api_client()
            # encoding_format="float" — the openai SDK defaults to "base64"
            # when not specified, which some OpenAI-compatible proxies
            # don't honour (they return plain float arrays anyway, but
            # pydantic validation in the SDK then drops the response as
            # malformed → "No embedding data received").  Forcing "float"
            # is the standards-compliant request and the cheapest fix.
            # Some providers (NVIDIA NIM) require an `input_type` field
            # in the request body (e.g. "query" or "passage").
            # Set OLAV_EMBEDDING_INPUT_TYPE to pass it via extra_body.
            _input_type = os.environ.get("OLAV_EMBEDDING_INPUT_TYPE")
            _extra = {"input_type": _input_type} if _input_type else None
            resp = client.embeddings.create(
                input=text, model=model, encoding_format="float",
                **({"extra_body": _extra} if _extra else {}),
            )
            vec = resp.data[0].embedding
        else:
            embedder = get_embedder()
            if embedder is None:
                return None
            vec = embedder.encode(text, normalize_embeddings=True).tolist()
        _cache_put(text, vec)
        return vec
    except Exception as exc:
        logger.warning("embed_text failed: %s", exc)
        return None
