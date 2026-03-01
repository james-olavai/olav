"""LLM Factory for creating chat models.

Modern implementation using LangChain's init_chat_model for dynamic provider support.
This approach eliminates hardcoded provider branches and enables seamless
custom API integration (OpenRouter, Groq, etc.) via config.

NOTE: v0.11.0 - Refactored from if-elif to init_chat_model for simplicity.
"""

import logging
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from olav.core.config import settings

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

        # Add API key if available
        if llm_config.api_key:
            params["api_key"] = llm_config.api_key

        # Add base_url if configured
        if llm_config.base_url:
            params["base_url"] = llm_config.base_url

        # Add model_provider - needed for models like x-ai/grok
        # Read from config JSON directly if not available in LLMConfig
        from pathlib import Path

        api_config_path = Path(".olav/config/api.json")
        if api_config_path.exists():
            import json

            api_config = json.loads(api_config_path.read_text())
            model_provider = api_config.get("llm", {}).get("model_provider")
            if model_provider:
                params["model_provider"] = model_provider

        # Disable streaming for DeepAgents async compatibility
        params["streaming"] = False

        # Handle JSON mode
        if json_mode:
            # Add JSON output constraint based on provider hints in base_url
            url = str(params.get("base_url", "")).lower()
            if "openai" in url or "groq" in url or "openrouter" in url:
                params["model_kwargs"] = params.get("model_kwargs", {})
                params["model_kwargs"]["response_format"] = {"type": "json_object"}

        # Apply any additional kwargs
        params.update(kwargs)

        # Log identification for debugging
        model = params.get("model", "unknown")
        params.get("base_url", "")
        logger.debug(f"Initializing ChatModel: {model} (agent={agent_id})")

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
        model = embedding_model or config.model

        try:
            if mode == "api":
                from langchain_openai import OpenAIEmbeddings

                return OpenAIEmbeddings(
                    model=model, api_key=config.api_key, base_url=config.base_url or None, **kwargs
                )
            else:
                # Default to local sentence-transformers
                from langchain_huggingface import HuggingFaceEmbeddings

                return HuggingFaceEmbeddings(
                    model_name=model,
                    model_kwargs={"device": config.local_device},
                    encode_kwargs={"normalize_embeddings": config.normalize_embeddings},
                    **kwargs,
                )
        except Exception as e:
            logger.warning(f"Embedding initialization failed ({mode}/{model}): {e}")
            if mode == "api" and config.fallback_enabled:
                logger.info("Falling back to local embeddings...")
                from langchain_huggingface import HuggingFaceEmbeddings

                return HuggingFaceEmbeddings(model_name=config.local_model)
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
