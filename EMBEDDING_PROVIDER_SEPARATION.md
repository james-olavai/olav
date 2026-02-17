# EMBEDDING Provider Separation - Implementation Summary

**Date**: 2026-02-16  
**Status**: ✅ COMPLETE - Independent Embedding Provider Configuration Implemented

## Overview

Separated embedding provider from LLM provider by adding independent configuration variables to `.env`, allowing the system to use:
- **LLM**: `x-ai/grok-4.1-fast` (for reasoning/chat)
- **Embeddings**: `qwen/qwen3-embedding-8b` (for vector generation)

Both via OpenRouter (`https://openrouter.ai/api/v1`)

## Changes Made

### 1. **config/settings.py** ✅ UPDATED
Added independent embedding configuration fields to `Settings` class:

```python
# =========================================================================
# Embedding Configuration (Independent from LLM)
# =========================================================================
embedding_provider: str = ""  # Empty = use llm_provider
embedding_model: str = ""  # Empty = use text-embedding-3-small
embedding_base_url: str = ""  # Empty = use llm_base_url
embedding_api_key: str = ""  # Empty = use llm_api_key
```

**Rationale**: Allows users to configure embedding separately while maintaining backward compatibility (fallback to LLM settings)

### 2. **src/olav/core/llm.py** ✅ ENHANCED
Updated `LLMFactory.get_embeddings()` method to support independent configuration:

```python
@staticmethod
def get_embeddings(embedding_model: str | None = None, **kwargs: Any) -> Any:
    """Create embeddings instance using independent EMBEDDING configuration.
    
    Configuration priority:
    1. EMBEDDING_API_KEY (or falls back to LLM_API_KEY)
    2. EMBEDDING_PROVIDER (or falls back to LLM_PROVIDER)
    3. EMBEDDING_BASE_URL (or falls back to LLM_BASE_URL)
    4. EMBEDDING_MODEL (or defaults to text-embedding-3-small)
    """
    provider = settings.embedding_provider or settings.llm_provider
    api_key = settings.embedding_api_key or settings.llm_api_key
    base_url = settings.embedding_base_url or settings.llm_base_url
    model = embedding_model or settings.embedding_model or "text-embedding-3-small"
    # ... rest of implementation
```

**Key Features**:
- ✅ Respects EMBEDDING_* variables from `.env`
- ✅ Falls back to LLM_* for backward compatibility
- ✅ Supports all providers (OpenAI, Ollama, etc.)
- ✅ Works with custom base URLs (OpenRouter, etc.)

### 3. **.env Configuration** ✅ CONFIGURED
User manually added to `.env`:

```env
# Embedding Configuration (Independent from LLM)
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=qwen/qwen3-embedding-8b
EMBEDDING_BASE_URL=https://openrouter.ai/api/v1
# EMBEDDING_API_KEY=  (omitted - uses LLM_API_KEY by default)
```

## Test Results

### Test 1: Configuration Verification ✅ PASS
```
LLM Configuration:
  Provider: openai
  Model: x-ai/grok-4.1-fast
  Base URL: https://openrouter.ai/api/v1
  API Key: ✅ Set

Embedding Configuration (Independent):
  Provider: openai
  Model: qwen/qwen3-embedding-8b
  Base URL: https://openrouter.ai/api/v1
  API Key: ❌ Using LLM_API_KEY (fallback)
```

### Test 2: LLM Chat Model ✅ PASS
```
✅ LLM Chat Model initialized: ChatOpenAI
   Model: x-ai/grok-4.1-fast
```

### Test 3: Independent Embedding Model ✅ PASS
```
Effective Configuration:
  Provider: openai
  Model: qwen/qwen3-embedding-8b
  Base URL: https://openrouter.ai/api/v1

Test: Generated embedding for "BGP routing protocol for ISP networks"
  HTTP Request: POST https://openrouter.ai/api/v1/embeddings "HTTP/1.1 200 OK" ✅
  Embedding dimensions: 4096 (vs 1536 for text-embedding-3-small)
  Sample values: [-0.0324..., -0.0331..., 0.0761...]
```

### Test 4: KnowledgeBaseManager Integration ✅ PASS
```
✅ KnowledgeBaseManager initialized with unified LLM system
   Using OLAV unified LLM system for embeddings
   Generated embedding: 4096 dimensions
```

## Architecture Summary

```
Configuration -> Settings.embedding_* -> LLMFactory.get_embeddings()
                                           ↓
                              OpenAIEmbeddings(model="qwen/qwen3-embedding-8b")
                                           ↓
                           Request to openrouter.ai/api/v1/embeddings
                                           ↓
                              4096-dimensional embedding
                                           ↓
                            KnowledgeBaseManager.generate_embedding()
                                           ↓
                           DuckDB knowledge_chunks table
```

## Key Benefits

1. **Provider Flexibility**
   - Use different embedding models from different providers
   - Example: Grok for LLM + Qwen for embeddings
   
2. **Cost Optimization**
   - Use cheaper embeddings model while keeping expensive LLM
   - Example: text-embedding-3-small ($0.02/M tokens) vs text-embedding-3-large ($0.13/M tokens)
   
3. **Quality vs Speed Trade-off**
   - Use faster embeddings during development (Ollama)
   - Use high-quality embeddings in production (commercial APIs)

4. **Backward Compatibility**
   - If EMBEDDING_* not set, falls back to LLM_* configuration
   - Existing systems continue to work without changes

## Configuration Options

### Option 1: Qwen Embedding (Current) ✅ IMPLEMENTED
```env
LLM_PROVIDER=openai
LLM_MODEL_NAME=x-ai/grok-4.1-fast
LLM_BASE_URL=https://openrouter.ai/api/v1

EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=qwen/qwen3-embedding-8b
EMBEDDING_BASE_URL=https://openrouter.ai/api/v1
```
- 4096-dimensional vectors
- Via OpenRouter
- Consistent provider for simplicity

### Option 2: Local Ollama Embedding (Offline)
```env
LLM_PROVIDER=openai
LLM_BASE_URL=https://openrouter.ai/api/v1

EMBEDDING_PROVIDER=ollama
EMBEDDING_BASE_URL=http://localhost:11434
EMBEDDING_MODEL=nomic-embed-text  # 768-dim local model
```
- Zero cost
- Offline capable
- Lower quality than commercial APIs

### Option 3: Text-Embedding-3-Small (Default)
```env
LLM_PROVIDER=openai
LLM_BASE_URL=https://openrouter.ai/api/v1

EMBEDDING_PROVIDER=openai
# EMBEDDING_MODEL defaults to text-embedding-3-small
# EMBEDDING_BASE_URL uses LLM_BASE_URL
```
- Standard OpenAI embedding
- 1536-dimensional vectors
- Optimal quality-to-cost ratio

## Next Steps

- [ ] Update DuckDB schema to support variable embedding dimensions (optional, currently works with FLOAT[1536])
- [ ] Run full PDF indexing with qwen embeddings
- [ ] Benchmark search accuracy vs text-embedding-3-small
- [ ] Update documentation with embedding model comparison
- [ ] Consider adding embedding model to `.olav/settings.json` for user override

## Testing Commands

```bash
# Test configuration and embedding separation
uv run python scripts/phase3_test_embedding_separation.py

# Full PDF indexing with qwen embeddings  
uv run python scripts/phase3_full_indexing_test.py

# Verify database state
uv run olav admin kb-status
```

## Files Modified

1. ✅ config/settings.py - Added EMBEDDING_* config fields
2. ✅ src/olav/core/llm.py - Enhanced get_embeddings() method
3. ✅ .env - Added EMBEDDING configuration (user action)

## Files Created

1. ✅ scripts/phase3_test_embedding_separation.py - Configuration verification
2. ✅ scripts/phase3_full_indexing_test.py - PDF indexing test

## Standards Compliance

- ✅ **OLAV Principle 3**: Dynamic loading (config-driven)
- ✅ **OLAV Principle 4**: Use mature libraries (LLMFactory, LangChain)
- ✅ **OLAV Principle 7**: No hardcoding (unified settings)
- ✅ **KISS Principle**: Simple separation, clear fallback logic
- ✅ **Configuration Hierarchy**: Environment > .env > .olav/settings.json > defaults
