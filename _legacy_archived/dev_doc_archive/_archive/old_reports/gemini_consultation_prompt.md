# OLAV v0.9.0 Fast Path Architecture Consultation

## Context
You are being consulted as an expert architecture reviewer for the OLAV v0.9.0 Fast Path implementation.

## Current Implementation
The current Fast Path architecture uses a multi-level confidence-based strategy:
- Semantic Cache (Tier 0) with 0.90 threshold
- Intent Cache (Tier 0) with 0.95 threshold
- Multi-tier decision routing (Action → Plan → Execution)

## User Feedback (Critical Requirements)
The user has provided explicit feedback that the current design is "over-engineered" and requires:

1. **Simple true/false cache hits** - Do not use complex confidence scoring (0.90/0.95/0.97)
2. **Per-agent isolation** - Each agent (database, cli, bgp, routing, etc.) must have its own independent DuckDB cache
3. **Router agent cache** - The routing agent also needs its own cache
4. **No IP address fuzzy matching** - Network operations queries are sensitive to IP addresses. Do NOT tolerate IP address differences. Use exact string matching only.
5. **Fast cache decisions** - Do not introduce latency in the cache lookup stage. Should be <10ms.
6. **Don't cache results, only execution methods** - Only cache how to query (SQL, CLI commands), not the actual results.
7. **Don't use file-based caching** - Use DuckDB for all caching, no file-based storage.

## Requirements Summary
- Stop over-engineering
- Use simple exact string matching for cache keys
- Strict isolation between agents (one DuckDB file per agent)
- Network ops precision: exact match only, NO fuzzy IP matching
- Fast cache decisions (<10ms)
- DuckDB-based caching for all agents
- No file-based caching

## Specific Questions
Please provide your expert evaluation on the following:

1. **Architecture Simplification**
   - Is the user's requirement for "simple true/false cache hits without complex confidence scoring" architecturally sound?
   - What are the pros and cons of removing multi-level confidence?
   - What is the recommended simplified caching strategy?

2. **Per-Agent Isolation**
   - How should we implement strict per-agent isolation using DuckDB?
   - File structure: `.olav/agent_cache/{agent_name}.duckdb`?
   - Or unified database with per-agent tables?
   - What's the best approach for DuckDB file management?

3. **Network Ops Precision**
   - How do we ensure exact string matching for network operations (IP addresses, routes, etc.)?
   - Should network ops queries bypass all fuzzy matching and use only exact string comparison?
   - How do we prevent "192.168.1.5" matching "192.168.1.6" in the cache?

4. **Router Agent Caching**
   - Does the routing agent need its own separate cache?
   - What should be cached in the router's cache (routing decisions, expert selection)?
   - How does this integrate with the per-agent caches?

5. **Implementation Strategy**
   - Should we migrate existing `semantic_cache` and `intent_cache` to the new simplified structure?
   - What's the recommended migration path?
   - How to ensure zero downtime during migration?

6. **Code Complexity Reduction**
   - What's the simplest way to implement the new caching logic?
   - Estimated lines of code to write/change?
   - Can we achieve the <1s response time for common queries with the simplified design?

7. **Testing Strategy**
   - What's the best way to test the simplified architecture?
   - How to verify cache isolation?
   - How to measure cache hit performance?

## Expected Output Format
Please provide:
1. Your evaluation of the current architecture (pros/cons)
2. Your recommended simplified architecture
3. Step-by-step implementation guide
4. Estimated development time for each phase
5. Risk assessment for the proposed changes
6. Testing recommendations
7. Any alternative approaches we should consider

Please be specific and practical. Focus on "stupid simple" design that meets all user requirements.
