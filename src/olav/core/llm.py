"""LLM Factory for creating chat models.

Modern implementation using LangChain's init_chat_model for dynamic provider support.
This approach eliminates hardcoded provider branches and enables seamless
custom API integration (OpenRouter, Groq, etc.) via config.

NOTE: v0.11.0 - Refactored from if-elif to init_chat_model for simplicity.
"""

import logging
import os
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from olav.core.embedder import get_embedder

logger = logging.getLogger(__name__)


class LLMFactory:
    """Factory for creating LLM instances using LangChain's init_chat_model."""

    @staticmethod
    def get_chat_model(
        json_mode: bool = False,
        temperature: float | None = None,
        model_name: str | None = None,
        agent_id: str | None = None,
        thinking_mode: str | None = None,
        overrides: dict | None = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        """Create a chat model instance using init_chat_model.

        Uses LangChain's dynamic provider discovery to handle all API backends
        via a unified interface. Configuration-driven, no hardcoded provider logic.

        Args:
            json_mode: Whether to enable JSON output mode
            temperature: Override default temperature
            model_name: Override model name (defaults to settings.llm_model_name)
            agent_id: Optional agent ID for per-agent model selection
            overrides: Per-skill ``llm:`` block from SKILL.md frontmatter.
                Supported keys: ``model``, ``temperature``, ``max_tokens``,
                ``base_url``, ``model_provider``, ``num_ctx`` (Ollama),
                ``num_predict`` (Ollama).  Any missing key falls through to
                the global ``api.json`` ``llm.*`` default.  Beats the
                ``model_name`` / ``temperature`` positional args (so caller
                can pass the legacy args without clobbering SKILL.md intent).
            **kwargs: Additional model parameters

        Returns:
            Configured chat model instance
        """
        from olav.core.config import get_llm_config

        llm_config = get_llm_config()
        overrides = overrides or {}

        # Per-skill overrides beat positional args beat global config.
        # Single fall-through chain — no profiles indirection (YAGNI).
        _model = overrides.get("model") or model_name or llm_config.model
        _temp = (
            overrides.get("temperature")
            if "temperature" in overrides
            else (temperature if temperature is not None else llm_config.temperature)
        )

        params = {
            "model": _model,
            "temperature": _temp,
        }

        # Explicitly pass max_tokens so OpenRouter/provider doesn't default to
        # the model's full context window (e.g. 30000 for grok-4.1-fast).
        _max_tokens = overrides.get("max_tokens", llm_config.max_tokens)
        if _max_tokens:
            params["max_tokens"] = _max_tokens

        # Add API key if available (per-skill / candidate override beats global —
        # dev_docs/99 §3.4 validate-before-commit passes a candidate key here)
        _api_key = overrides.get("api_key") or llm_config.api_key
        if _api_key:
            params["api_key"] = _api_key

        # Add base_url if configured (per-skill override beats global)
        _base_url = overrides.get("base_url") or llm_config.base_url
        if _base_url:
            params["base_url"] = _base_url

        # Add model_provider if configured.
        # Always pass it explicitly – init_chat_model cannot infer the provider
        # from custom model names like "x-ai/grok-4.1-fast" or "openrouter/*".
        _model_provider = overrides.get("model_provider") or llm_config.model_provider
        if _model_provider:
            params["model_provider"] = _model_provider
        else:
            # Auto-detect provider from base_url when config leaves it blank.
            # Without this fallback langchain's init_chat_model raises
            # "Unable to infer model provider" for OpenRouter-style model
            # names like "x-ai/grok-4.1-fast".
            _url = str(params.get("base_url") or "").lower()
            if "openrouter" in _url:
                params["model_provider"] = "openrouter"
            elif "together.xyz" in _url or "together.ai" in _url:
                params["model_provider"] = "together"
            elif "groq" in _url:
                params["model_provider"] = "groq"
            elif "deepseek" in _url:
                params["model_provider"] = "deepseek"
            elif "perplexity" in _url:
                params["model_provider"] = "perplexity"
            elif "ollama" in _url or ":11434" in _url:
                # Ollama on its own native /api/chat — use langchain-ollama
                # so the `reasoning` field works (qwen3 thinking toggle).
                # OpenAI-compat /v1 also exists but doesn't surface
                # native Ollama-only flags.  Detect by port 11434 (default)
                # or "ollama" in URL.
                params["model_provider"] = "ollama"
            elif _url:
                # Unknown base_url with custom model name (e.g. local
                # llama.cpp at 192.168.x.x:11433 serving "qwen3.6-27b-dense").
                # OpenAI Chat Completions is the de-facto standard for
                # OpenAI-compatible servers — default to it so init_chat_model
                # doesn't raise.  Override via api.json llm.model_provider
                # when targeting a non-OpenAI dialect.
                params["model_provider"] = "openai"

        # Disable streaming for DeepAgents async compatibility
        params["streaming"] = False

        # Apply HTTP request timeout from shared config
        params["timeout"] = llm_config.timeout

        # ── 2026-05-13 STAGED-FILL FIX (ollama only) ─────────────────────
        # langchain-ollama (ChatOllama) accepts num_ctx / num_predict
        # as direct top-level kwargs. Ollama defaults (num_ctx=2048,
        # num_predict=128) are far too small for thinking-mode models
        # — gemma4:31b / qwen3.6:27b silently emit content_len=0 when
        # thinking eats the whole num_predict budget (done_reason=length).
        #
        # Verified 2026-05-13 in-vivo (R2-R4 OSPF staged-fill):
        #   default opts → S4 content_len=0 (empty, thinking ate budget)
        #   num_ctx=65536 + num_predict=4096 → 5/5 deterministic PASS
        #
        # Override per-model by passing num_ctx / num_predict via kwargs
        # (caller can downsize for small models on memory-constrained host).
        # Detect Ollama backend by URL even if model_provider is "openai"
        # (Ollama's OpenAI-compat /v1 endpoint is the common deploy shape).
        # Ollama on the /v1 path still honours ``options.num_ctx`` /
        # ``options.num_predict`` via extra_body — required to bump past
        # the 2048-token default when running gemma4:31b / qwen3:27b.
        _base_url_lower = str(params.get("base_url") or "").lower()
        _ollama_backed = (
            params.get("model_provider") == "ollama"
            or "ollama" in _base_url_lower
            or ":11434" in _base_url_lower
        )
        if _ollama_backed:
            _num_ctx = overrides.get("num_ctx", 65536)
            _num_predict = overrides.get("num_predict", 4096)
            if params.get("model_provider") == "ollama":
                # Native langchain-ollama path — top-level kwargs.
                params.setdefault("num_ctx", _num_ctx)
                params.setdefault("num_predict", _num_predict)
            else:
                # OpenAI-compat path to Ollama — ship as extra_body.options.*
                # so the underlying Ollama runtime sees them.
                mkw = params.setdefault("model_kwargs", {})
                extra = mkw.setdefault("extra_body", {})
                ol_opts = extra.setdefault("options", {})
                ol_opts.setdefault("num_ctx", _num_ctx)
                ol_opts.setdefault("num_predict", _num_predict)

        # Handle JSON mode
        if json_mode:
            # Add JSON output constraint based on provider hints in base_url
            url = str(params.get("base_url", "")).lower()
            if "openai" in url or "groq" in url or "openrouter" in url:
                params["model_kwargs"] = params.get("model_kwargs", {})
                params["model_kwargs"]["response_format"] = {"type": "json_object"}

        # Apply any additional kwargs
        params.update(kwargs)

        # ── ARCH-19 #B: forward backend-specific prompt-cache hints ───────
        # Local LLM backends (vLLM / llama.cpp / Ollama) recognise different
        # cache flags. OpenAI-compatible APIs silently ignore unknown keys
        # so attaching them unconditionally (when the base_url matches) is
        # safe. ``OLAV_LOCAL_CACHE_DISABLE=1`` is the debug escape hatch.
        if not os.environ.get("OLAV_LOCAL_CACHE_DISABLE"):
            base_hint = str(params.get("base_url") or "").lower()
            mkw = params.setdefault("model_kwargs", {})
            if "vllm" in base_hint:
                extra = mkw.setdefault("extra_body", {})
                extra.setdefault("enable_prefix_caching", True)
            elif "llama.cpp" in base_hint or ":8080" in base_hint:
                mkw.setdefault("cache_prompt", True)
            elif "ollama" in base_hint or ":11434" in base_hint:
                # Ollama-specific knobs go in extra_body (sent via JSON
                # body, not as Python kwargs to openai.Completions.create —
                # the latter raises TypeError on unknown args in recent
                # langchain-openai versions).
                extra = mkw.setdefault("extra_body", {})
                extra.setdefault("keep_alive", "5m")

        # ── R100/S1: qwen3 thinking-mode toggle (chat_template_kwargs) ───
        # Qwen3-class models (qwen3.6:27b dense, qwen3.6-35B-A3B, …) by
        # default emit a ``<think>...</think>`` block before the answer.
        # Disabling thinking saves 30-50% of tokens per turn (verified
        # 2026-04-29 demo7: "2+2?" → 152 → 8 tokens, 95% saving).
        #
        # BUT — empirically thinking is load-bearing for ReAct/tool-call
        # adherence on qwen3.6:27b-dense.  Demo7 Ch8 v3 (2026-04-29):
        # with thinking OFF the agent regressed from "tries
        # format_and_export" to "outputs a fake JSON dump of recalled
        # memory entries as its final answer".  The internal reasoning
        # was what powered tool selection + arg construction; without
        # it the model short-circuits to "echo retrieved context".
        #
        # Default is therefore THINKING ENABLED (env var unset, or "0"
        # to be explicit).  Set ``OLAV_DISABLE_THINKING=1`` to suppress
        # — only useful for non-agent text-generation tasks where the
        # latency saving is worth the quality loss.
        #
        # The qwen3 chat template accepts an ``enable_thinking`` kwarg
        # (Hugging Face transformers convention).  llama-server forwards
        # ``chat_template_kwargs`` from the OpenAI-compat request body
        # to the template renderer; OpenAI itself silently ignores
        # unknown body keys so this is safe to send unconditionally
        # when set.
        # Per-agent thinking_mode override beats global env var.  R-VERTICAL-
        # SLICE Phase 0 (2026-05-09, dev_docs/70): hybrid thinking — orchestrator
        # gets reasoning ON for planning, sub-agents OFF for fast tool calls.
        # ``thinking_mode`` precedence:
        #   "enabled"  → reasoning ON  (overrides env var)
        #   "disabled" → reasoning OFF (overrides env var)
        #   None       → respect OLAV_DISABLE_THINKING env var (current default)
        _disable_thinking = (
            thinking_mode == "disabled"
            if thinking_mode is not None
            else os.environ.get("OLAV_DISABLE_THINKING") == "1"
        )
        _enable_thinking_explicit = thinking_mode == "enabled"

        _base_for_thinking = str(params.get("base_url") or "").lower()
        _is_openrouter = "openrouter" in _base_for_thinking
        # Google AI Studio / Vertex AI do not support chat_template_kwargs
        # in extra_body — they reject with 400 INVALID_ARGUMENT.
        _is_google = "generativelanguage.googleapis.com" in _base_for_thinking \
            or "aiplatform.googleapis.com" in _base_for_thinking \
            or "integrate.api.nvidia.com" in _base_for_thinking
        if _disable_thinking:
            # Provider-specific thinking-off mechanism:
            # * Ollama (langchain-ollama) — native ``reasoning`` field on
            #   ChatOllama.  Set False to disable thinking entirely.
            # * llama.cpp / vLLM / local OpenAI-compat — pass
            #   ``chat_template_kwargs.enable_thinking=false`` via
            #   extra_body.  llama-server forwards to the template
            #   renderer; unknown keys ignored elsewhere.
            # * OpenRouter — DO NOT send chat_template_kwargs.  OpenRouter
            #   forwards extra_body fields to the downstream provider
            #   (e.g. deepseek-v4-flash) which does NOT support
            #   enable_thinking and responds with choices[0].message=null
            #   for conversations that contain ToolMessage entries.
            #   2026-05-31: confirmed via direct curl; 4-message tool call
            #   conversation → null content when enable_thinking=False sent.
            if params.get("model_provider") == "ollama":
                params["reasoning"] = False
            elif not _is_openrouter and not _is_google:
                # Google AI Studio (gemma-4-31b-it): thinkingBudget not supported
                # for this model — skip silently.
                mkw = params.setdefault("model_kwargs", {})
                extra = mkw.setdefault("extra_body", {})
                ctk = extra.setdefault("chat_template_kwargs", {})
                ctk.setdefault("enable_thinking", False)
                # 2026-05-15: removed ``reasoning_effort: minimal`` —
                # Ollama OpenAI-compat strictly validates that field and
                # rejects ``minimal`` with HTTP 400 (only "high"/"medium"/
                # "low"/"max"/"none" allowed).  The ``enable_thinking``
                # kwarg in chat_template_kwargs already covers qwen3 /
                # gemma4; OpenAI o1 path would need its own branch if
                # ever needed (the original comment claimed "unknown
                # keys ignored" — turned out to be wrong for Ollama).
        elif _enable_thinking_explicit:
            # Explicit ON: force reasoning=True so it isn't masked by an
            # upstream default or model preset.
            if params.get("model_provider") == "ollama":
                params["reasoning"] = True
            elif not _is_openrouter and not _is_google:
                mkw = params.setdefault("model_kwargs", {})
                extra = mkw.setdefault("extra_body", {})
                ctk = extra.setdefault("chat_template_kwargs", {})
                ctk.setdefault("enable_thinking", True)

        # Log identification for debugging
        model = params.get("model", "unknown")
        base_url = params.get("base_url", "")
        logger.debug(f"Initializing ChatModel: {model} base_url={base_url} (agent={agent_id})")
        if overrides:
            # Surface the override summary at INFO so operators can confirm
            # SKILL.md frontmatter actually reached the factory.
            _ov_summary = {k: v for k, v in overrides.items() if v is not None}
            logger.info(
                "  → agent=%s LLM overrides: %s (effective: temp=%s, "
                "max_tokens=%s, num_ctx=%s)",
                agent_id, _ov_summary, params.get("temperature"),
                params.get("max_tokens"), params.get("num_ctx"),
            )

        # ── Sprint 0a token_meter: attach TokenUsageCallback ──────────────
        # Soft-fail — if the callback / recorder is unavailable we log at
        # debug and proceed, never blocking an LLM invocation.
        try:
            from olav.core.llm_instrumentation import TokenUsageCallback

            callback = TokenUsageCallback(
                model_name=params.get("model"),
                model_tier=llm_config.model_tier,
            )
            existing = params.get("callbacks") or []
            params["callbacks"] = [*existing, callback]
        except Exception as _tm_err:
            logger.debug("token_meter attach skipped: %s", _tm_err)

        # For non-OpenAI backends (local llama.cpp, Ollama, vLLM) bump the
        # HTTP client's built-in retry counter.  The openai client retries on
        # 503 by default but stops after 2 attempts; local servers (especially
        # llama.cpp) can return "Loading model" 503s for 10-30 s while the
        # KV cache warms up — 5 attempts with exponential back-off covers it.
        # Leave the real openai.com API at its default (2) to avoid delaying
        # genuine failures.
        _base_for_retry = str(params.get("base_url") or "").lower()
        if _base_for_retry and "openai.com" not in _base_for_retry:
            params.setdefault("max_retries", 5)

        # Promote extra_body from model_kwargs to a top-level kwarg so
        # LangChain / ChatOpenAI does not emit "Parameters {'extra_body'}
        # should be specified explicitly" (UserWarning).  The warning fires
        # when extra_body is inside model_kwargs; passing it directly is the
        # supported path (ChatOpenAI and init_chat_model both accept it via
        # **kwargs → underlying openai client).  Merge with any existing
        # top-level extra_body so callers that already pass it correctly are
        # not overwritten.
        _mkw = params.get("model_kwargs") or {}
        if _eb := _mkw.pop("extra_body", None):
            existing_eb = params.get("extra_body") or {}
            params["extra_body"] = {**_eb, **existing_eb}  # caller wins
            if not _mkw:
                params.pop("model_kwargs", None)

        # Google AI Studio: use ChatGoogleGenerativeAI (native SDK)
        # instead of init_chat_model / ChatOpenAI which loses thinking_level support.
        # thinking_mode mapping:
        #   "disabled" / OLAV_DISABLE_THINKING=1  → thinking_level="minimal"  (fastest)
        #   "enabled"                              → thinking_level="high"
        #   None (default)                         → thinking_level="minimal"  (default off)
        if _is_google:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                _google_thinking = (
                    "high" if (thinking_mode == "enabled")
                    else "minimal"   # disabled / None → minimal (no thinking)
                )
                _google_params = {
                    "model": params.get("model", "gemma-4-31b-it"),
                    "google_api_key": params.get("api_key") or os.environ.get("GOOGLE_API_KEY", ""),
                    "thinking_level": _google_thinking,
                    "temperature": params.get("temperature", 0.1),
                }
                if params.get("max_tokens"):
                    _google_params["max_output_tokens"] = params["max_tokens"]
                if params.get("callbacks"):
                    _google_params["callbacks"] = params["callbacks"]
                logger.info(
                    "Google AI Studio: model=%s thinking_level=%s",
                    _google_params["model"], _google_thinking,
                )
                llm = ChatGoogleGenerativeAI(**_google_params)
            except ImportError:
                logger.warning(
                    "langchain-google-genai not installed; falling back to ChatOpenAI. "
                    "Install with: uv add langchain-google-genai"
                )
                llm = init_chat_model(**params)
            except Exception as e:
                logger.error("Google AI Studio init failed: %s", e)
                raise
        else:
            # Use init_chat_model - LangChain handles provider detection
            try:
                llm = init_chat_model(**params)
            except Exception as e:
                logger.error(f"Failed to initialize chat model: {e}")
                raise

        return llm

    @staticmethod
    def check_connectivity(overrides: dict | None = None) -> tuple[bool, str]:
        """Test LLM connectivity, returning both the outcome and a detail message.

        Single source of truth for LLM health — shared by ``olav doctor``
        (dev_docs/99 §3.1), ``test_connectivity()`` below, and the
        validate-before-commit gate in ``update_llm_config`` (§3.4). Never
        raises.

        Args:
            overrides: same shape as ``get_chat_model``'s ``overrides`` —
                pass a candidate ``model``/``api_key``/``model_provider``/
                ``base_url`` to test a not-yet-committed config instead of
                the active one. ``None`` (default) tests the active config.

        Returns:
            (True, "connected") on success, (False, <reason>) on failure.
        """
        try:
            llm = LLMFactory.get_chat_model(temperature=0, overrides=overrides)
            from langchain_core.messages import HumanMessage

            llm.invoke([HumanMessage(content="Connectivity test. Respond with OK.")])
            return True, "connected"
        except Exception as e:
            logger.error(f"LLM Connectivity test failed: {e}")
            return False, str(e)

    @staticmethod
    def test_connectivity() -> bool:
        """Test LLM connectivity by attempting a simple prompt.

        Returns:
            True if connectivity is successful, False otherwise.
        """
        return LLMFactory.check_connectivity()[0]

    @staticmethod
    def check_embedding_connectivity(
        overrides: dict | None = None, strict: bool = False
    ) -> tuple[bool, str]:
        """Test embedding connectivity, returning both the outcome and a detail message.

        Mirrors ``check_connectivity()`` for the embedding backend (local
        SentenceTransformer or API mode). Never raises.

        Args:
            overrides: candidate ``mode``/``api_key``/``model``/``base_url``
                — test a not-yet-committed config (§3.4). ``None`` tests
                the active config.
            strict: skip the local-embedding fallback so a bad candidate
                API key surfaces as a real failure instead of being masked
                by silently falling back to the local model. Runtime
                callers (doctor, check_health) want the production
                fallback behaviour and should leave this ``False``.

        Returns:
            (True, "connected") on success, (False, <reason>) on failure.
        """
        try:
            embeddings = LLMFactory.get_embeddings(overrides=overrides, strict=strict)
            embeddings.embed_query("connectivity test")
            return True, "connected"
        except Exception as e:
            logger.error(f"Embedding connectivity test failed: {e}")
            return False, str(e)

    @staticmethod
    def get_embeddings(
        embedding_model: str | None = None,
        overrides: dict | None = None,
        strict: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Create embeddings instance using configured mode (Local/API).

        Args:
            overrides: candidate ``mode``/``api_key``/``model``/``base_url``
                to test before committing (dev_docs/99 §3.4). ``None`` uses
                the active config.
            strict: when True, skip the API→local fallback below so a bad
                candidate surfaces as a real exception (used by validation;
                normal runtime calls leave this False).
        """
        from olav.core.config import get_embedding_config

        config = get_embedding_config()
        overrides = overrides or {}
        mode = overrides.get("mode") or config.mode

        # Select model based on mode
        if mode == "api":
            model = embedding_model or overrides.get("model") or config.openai_model
        else:
            model = embedding_model or overrides.get("model") or config.local_model

        class SentenceTransformerEmbeddings:
            def __init__(self, st_model):
                self.model = st_model

            def embed_documents(self, texts):
                return self.model.encode(
                    texts, normalize_embeddings=config.normalize_embeddings
                ).tolist()

            def embed_query(self, text):
                return self.model.encode(
                    text, normalize_embeddings=config.normalize_embeddings
                ).tolist()

        try:
            if mode == "api":
                from langchain_openai import OpenAIEmbeddings

                api_key = overrides.get("api_key") or config.api_key
                base_url = overrides.get("base_url") or config.base_url or None
                return OpenAIEmbeddings(model=model, api_key=api_key, base_url=base_url, **kwargs)
            else:
                st_model = get_embedder(model)
                if st_model is None:
                    raise RuntimeError(
                        "sentence-transformers unavailable; cannot create local embeddings"
                    )
                return SentenceTransformerEmbeddings(st_model)
        except Exception as e:
            logger.warning(f"Embedding initialization failed ({mode}/{model}): {e}")
            if mode == "api" and config.fallback_enabled and not strict:
                logger.info("Falling back to local embeddings...")
                st_model = get_embedder(config.local_model)
                if st_model is None:
                    raise RuntimeError(
                        "sentence-transformers unavailable; cannot create fallback embeddings"
                    ) from e
                return SentenceTransformerEmbeddings(st_model)
            raise


def get_chat_model(
    json_mode: bool = False,
    temperature: float | None = None,
    model_name: str | None = None,
    **kwargs: Any,
) -> BaseChatModel:
    """Convenience function for creating chat models."""
    return LLMFactory.get_chat_model(
        json_mode=json_mode,
        temperature=temperature,
        model_name=model_name,
        **kwargs,
    )


def get_embeddings(embedding_model: str | None = None, **kwargs: Any) -> Any:
    """Convenience function for creating embeddings."""
    return LLMFactory.get_embeddings(embedding_model=embedding_model, **kwargs)
