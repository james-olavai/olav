"""LLM Factory for creating chat models.

Uses provider-specific chat model classes for maximum compatibility with
third-party APIs (OpenRouter, Groq, etc.) and DeepAgents.

NOTE: v0.10.2 - Fixed P0 bug: Using ChatOpenAI/ChatOllama directly instead of
init_chat_model() to ensure compatibility with DeepAgents middleware.

Third-party API Support:
- OpenRouter: Automatic header injection for HTTP-Referer and X-Title
- Groq API: Explicit langchain_groq.ChatGroq support
- Mistral: Explicit langchain_mistralai.ChatMistral support
- Generic OpenAI-compatible: Via 'openai' provider + llm_base_url
"""

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from config.settings import settings

logger = logging.getLogger(__name__)


class LLMFactory:
    """Factory for creating LLM instances using provider-specific chat models."""

    @staticmethod
    def get_chat_model(
        json_mode: bool = False,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        """Create a chat model instance using provider-specific classes.

        This method directly instantiates ChatOpenAI, ChatOllama, etc. to ensure
        compatibility with third-party APIs (OpenRouter) and DeepAgents middleware.

        Args:
            json_mode: Whether to enable JSON output mode
            temperature: Override default temperature
            **kwargs: Additional model parameters

        Returns:
            Configured chat model instance
        """
        temp = temperature if temperature is not None else settings.llm_temperature
        provider = settings.llm_provider
        model_name = settings.llm_model_name

        # Common config for all providers
        config: dict[str, Any] = {
            "model": model_name,
            "temperature": temp,
            "max_tokens": settings.llm_max_tokens,
            "streaming": False,  # FIXED: Disable streaming for DeepAgents async compatibility
            **kwargs,
        }

        if provider == "ollama":
            # Ollama requires ChatOllama from langchain_ollama
            try:
                from langchain_ollama import ChatOllama
            except ImportError:
                logger.error("langchain-ollama not installed. Run: uv add langchain-ollama")
                raise

            config["base_url"] = settings.llm_base_url or "http://localhost:11434"
            if json_mode:
                config["format"] = "json"

            logger.debug(
                f"Creating Ollama chat model: model={model_name}, base_url={config['base_url']}"
            )
            return ChatOllama(**config)  # type: ignore[return-value]

        elif provider == "openai":
            # OpenAI and OpenAI-compatible APIs (OpenRouter, Together, etc.)
            config["api_key"] = settings.llm_api_key

            # Third-party OpenAI-compatible API (OpenRouter, etc.)
            if settings.llm_base_url:
                config["base_url"] = settings.llm_base_url

                # OpenRouter requires specific headers for proper routing and usage tracking
                if "openrouter" in settings.llm_base_url.lower():
                    config["default_headers"] = {
                        "HTTP-Referer": "https://olav-network.local",
                        "X-Title": "OLAV Network Intelligence System",
                    }
                    logger.debug("OpenRouter detected - adding required headers (HTTP-Referer, X-Title)")

                logger.debug(
                    f"Creating OpenAI-compatible chat model: {model_name} "
                    f"via {settings.llm_base_url}"
                )
            else:
                logger.debug(f"Creating OpenAI chat model: {model_name}")

            if json_mode:
                config["model_kwargs"] = {"response_format": {"type": "json_object"}}

            return ChatOpenAI(**config)  # type: ignore[return-value]

        elif provider == "azure":
            config["api_key"] = settings.llm_api_key
            logger.debug(f"Creating Azure chat model: {model_name}")
            return AzureChatOpenAI(**config)  # type: ignore[return-value]

        elif provider == "xai":
            # xAI (Grok) via OpenRouter - use OpenAI-compatible endpoint
            config["api_key"] = settings.llm_api_key
            config["base_url"] = settings.llm_base_url or "https://openrouter.ai/api/v1"

            if json_mode:
                config["model_kwargs"] = {"response_format": {"type": "json_object"}}

            logger.debug(
                f"Creating xAI chat model: {model_name} via {config['base_url']}"
            )
            return ChatOpenAI(**config)  # type: ignore[return-value]

        elif provider == "anthropic":
            # Claude models via Anthropic API
            try:
                from langchain_anthropic import ChatAnthropic
            except ImportError:
                logger.error("langchain-anthropic not installed. Run: uv add langchain-anthropic")
                raise

            config["api_key"] = settings.llm_api_key
            if settings.llm_base_url:
                config["base_url"] = settings.llm_base_url

            logger.debug(f"Creating Anthropic chat model: {model_name}")
            return ChatAnthropic(**config)  # type: ignore[return-value]

        elif provider == "groq":
            # Groq API - extremely fast inference
            # Models: mixtral-8x7b-32768, llama-3.1-70b-versatile, etc.
            try:
                from langchain_groq import ChatGroq
            except ImportError:
                logger.error(
                    "langchain-groq not installed. Run: uv add langchain-groq\n"
                    "Install guide: https://python.langchain.com/docs/integrations/chat/groq"
                )
                raise

            config["api_key"] = settings.llm_api_key
            if settings.llm_base_url:
                config["base_url"] = settings.llm_base_url

            logger.debug(f"Creating Groq chat model: {model_name}")
            return ChatGroq(**config)  # type: ignore[return-value]

        elif provider == "mistral":
            # Mistral AI - multi-language support
            # Models: mistral-small, mistral-medium, mistral-large, etc.
            try:
                from langchain_mistralai import ChatMistral
            except ImportError:
                logger.error(
                    "langchain-mistralai not installed. Run: uv add langchain-mistralai\n"
                    "Install guide: https://python.langchain.com/docs/integrations/chat/mistralai"
                )
                raise

            config["api_key"] = settings.llm_api_key
            if settings.llm_base_url:
                config["base_url"] = settings.llm_base_url

            logger.debug(f"Creating Mistral chat model: {model_name}")
            return ChatMistral(**config)  # type: ignore[return-value]

        else:
            logger.error(f"Unsupported LLM provider: {provider}")
            raise ValueError(
                f"Unsupported LLM provider: {provider}. "
                f"Supported: openai, ollama, azure, xai, anthropic, groq, mistral"
            )
