"""Debug .env file loading."""

import os
from pathlib import Path

# Find project root
PROJECT_ROOT = Path(__file__).parent.parent

print(f"Script location: {Path(__file__).absolute()}")
print(f"Project root: {PROJECT_ROOT.absolute()}")
print(f".env location: {(PROJECT_ROOT / '.env').absolute()}")
print(f".env exists: {(PROJECT_ROOT / '.env').exists()}")

if (PROJECT_ROOT / '.env').exists():
    with open(PROJECT_ROOT / '.env', 'r') as f:
        for line in f:
            if 'LLM_API_KEY' in line:
                print(f"Found in .env: {line.strip()}")

print(f"\nEnvironment variable LLM_API_KEY: {os.environ.get('LLM_API_KEY', 'NOT SET')}")

# Now try importing settings
print("\n" + "="*80)
print("Importing settings...")
print("="*80)

from olav.core.settings import settings

print(f"Settings provider: {settings.llm_provider}")
print(f"Settings model: {settings.llm_model_name}")
print(f"Settings API key: {settings.llm_api_key[:20] if settings.llm_api_key else 'EMPTY'}...{settings.llm_api_key[-10:] if settings.llm_api_key else ''}")
print(f"Settings API key length: {len(settings.llm_api_key)}")
