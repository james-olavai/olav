"""Pytest configuration for E2E tests.

Sets up environment variables from .env file for test execution.
"""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env file before tests
ENV_FILE = Path(__file__).parent.parent.parent / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=True)
    
    # Map LLM_API_KEY to OPENAI_API_KEY for OpenAI-compatible providers
    if os.getenv("LLM_PROVIDER") == "openai" and os.getenv("LLM_API_KEY"):
        os.environ["OPENAI_API_KEY"] = os.getenv("LLM_API_KEY")
        print(f"✅ Loaded API key from .env (provider: {os.getenv('LLM_PROVIDER')})")
    
    # Also set OpenRouter API key if available
    if os.getenv("OPENROUTER_API_KEY"):
        os.environ["OPENAI_API_KEY"] = os.getenv("OPENROUTER_API_KEY")
        print("✅ Loaded OpenRouter API key")


@pytest.fixture(scope="session")
def api_configured():
    """Check if API is configured."""
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY"))
