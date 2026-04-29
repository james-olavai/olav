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
            **kwargs: Additional model parameters

        Returns:
            Configured chat model instance
        """
        from olav.core.config import get_llm_config

        llm_config = get_llm_config()

        # Get base parameters from config (with agent override support)
        # FIX: Direct parameter construction instead of missing to_langchain_params()
        params = {
            "model": model_name or llm_config.model,
            "temperature": temperature if temperature is not None else llm_config.temperature,
        }

        # Explicitly pass max_tokens so OpenRouter/provider doesn't default to
        # the model's full context window (e.g. 30000 for grok-4.1-fast).
        if llm_config.max_tokens:
            params["max_tokens"] = llm_config.max_tokens

        # Add API key if available
        if llm_config.api_key:
            params["api_key"] = llm_config.api_key

        # Add base_url if configured
        if llm_config.base_url:
            params["base_url"] = llm_config.base_url

        # Add model_provider if configured.
        # Always pass it explicitly – init_chat_model cannot infer the provider
        # from custom model names like "x-ai/grok-4.1-fast" or "openrouter/*".
        if llm_config.model_provider:
            params["model_provider"] = llm_config.model_provider
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

        # Disable streaming for DeepAgents async compatibility
        params["streaming"] = False

        # Apply HTTP request timeout from shared config
        params["timeout"] = llm_config.timeout

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
        if os.environ.get("OLAV_DISABLE_THINKING") == "1":
            mkw = params.setdefault("model_kwargs", {})
            extra = mkw.setdefault("extra_body", {})
            ctk = extra.setdefault("chat_template_kwargs", {})
            ctk.setdefault("enable_thinking", False)
            # Also try the OpenAI-style reasoning_effort knob for
            # endpoints that honour it (e.g. some OpenRouter/proxy
            # passthroughs to o1-class models).  Unknown keys are
            # ignored by OpenAI-compat servers.
            extra.setdefault("reasoning_effort", "minimal")

        # Log identification for debugging
        model = params.get("model", "unknown")
        base_url = params.get("base_url", "")
        logger.debug(f"Initializing ChatModel: {model} base_url={base_url} (agent={agent_id})")

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

        # Use init_chat_model - LangChain handles provider detection
        try:
            return init_chat_model(**params)
        except Exception as e:
            logger.error(f"Failed to initialize chat model: {e}")
            raise

    @staticmethod
    def test_connectivity() -> bool:
        """Test LLM connectivity by attempting a simple prompt.

        Returns:
            True if connectivity is successful, False otherwise.
        """
        try:
            llm = LLMFactory.get_chat_model(temperature=0)
            from langchain_core.messages import HumanMessage

            llm.invoke([HumanMessage(content="Connectivity test. Respond with OK.")])
            return True
        except Exception as e:
            logger.error(f"LLM Connectivity test failed: {e}")
            return False

    @staticmethod
    def get_embeddings(embedding_model: str | None = None, **kwargs: Any) -> Any:
        """Create embeddings instance using configured mode (Local/API)."""
        from olav.core.config import get_embedding_config

        config = get_embedding_config()
        mode = config.mode

        # Select model based on mode
        if mode == "api":
            model = embedding_model or config.openai_model
        else:
            model = embedding_model or config.local_model

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

                return OpenAIEmbeddings(
                    model=model, api_key=config.api_key, base_url=config.base_url or None, **kwargs
                )
            else:
                st_model = get_embedder(model)
                if st_model is None:
                    raise RuntimeError(
                        "sentence-transformers unavailable; cannot create local embeddings"
                    )
                return SentenceTransformerEmbeddings(st_model)
        except Exception as e:
            logger.warning(f"Embedding initialization failed ({mode}/{model}): {e}")
            if mode == "api" and config.fallback_enabled:
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
