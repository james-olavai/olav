---
name: config-knowledge
description: "Knowledge Manager — Vector-based semantic search, KB indexing, and cache management"
metadata:
  version: 1.0.0
  author: Network AI Team
  type: agent
  category: knowledge-management
  intent: semantic_search_knowledge_base
tools:
  - search_knowledge         # Dedicated: Semantic search against KB
  - index_knowledge_files    # Dedicated: Index .md/.pdf files into vector store
  - get_knowledge_status    # Dedicated: KB index health + chunk stats
system: $ref:./prompts/system.md
---

## Overview

The Knowledge Manager handles OLAV's semantic search and knowledge base operations.

## Use Cases

1. **Semantic Search**: Find relevant information using natural language
2. **KB Indexing**: Index new documents (Markdown, PDF) into the vector store
3. **Cache Management**: Manage the semantic cache for fast responses
4. **Index Health**: Monitor KB index status and statistics

## Configuration

- Knowledge directory: `.olav/knowledge/`
- Vector DB: `.olav/db/olav.duckdb`
- Default search limit: 5 results
- Default chunk size: 1024 characters

## Best Practices

1. Index new documents after adding to `.olav/knowledge/`
2. Use incremental indexing to avoid duplicates
3. Monitor index health regularly
4. Use semantic search before performing deep analysis
