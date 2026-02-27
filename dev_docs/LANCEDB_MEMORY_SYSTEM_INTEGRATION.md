# OLAV Implementation Plan: LanceDB Integration for Agentic Memory & Knowledge

**Author**: Antigravity
**Status**: Draft (Proposal)
**Inspired by**: `_legacy_archived/memory-lancedb-pro`

## 1. Objective

This proposal outlines the integration of **LanceDB** as the unified non-structured data layer (Olav Central Memory - OCM) to enhance OLAV's agentic capabilities. By moving from simple keyword logs to semantic, categorized long-term memory, OLAV can achieve self-learning, improved diagnosis, and context-aware execution while maintaining low operating costs.

## 2. Architectural Design

OLAV will adopt a "Hybrid Storage" strategy to leverage the strengths of different database engines:

| Engine | Role | Use Case |
| :--- | :--- | :--- |
| **DuckDB** | Structured Lakehouse (Bronze/Silver/Gold) | Inventory, metrics, configuration diffs, PGQ Network Topology graph analysis. |
| **LanceDB** | Semantic/Memory Layer (OCM) | Long-term memory, KB chunks, network event summaries, vector cache. |
| **SQLite** | Transactional State | LangGraph checkpoints, short-term thread states. |

### Core Components of OCM
1. **Semantic Knowledge Base (KB)**: Hybrid retrieval (Vector + BM25) for troubleshooting guides and vendor docs.
2. **Long-Term Memory (LTM)**: Categorized experience (Preference, Fact, Decision, Action Audit) with time decay.
3. **Network Event Memory**: Storing summarized network anomalies and episodes (NOT raw system logs) for root-cause analysis.
4. **Local Embedding Path**: Priority usage of `sentence-transformers` for zero-cost offline vectorization.

## 3. Implementation Blueprint

### A. Core Engine (`src/olav/core/memory/`)
Create a robust Python wrapper for LanceDB, mirroring the high-performance features of the legacy TypeScript implementation:
- **Hybrid Fusion Engine**: Implement a custom retrieval pipeline (Vector + BM25 + Reranker) instead of relying solely on baseline LangChain VectorStore wrappers. 
- **Categorization Logic**: Auto-detecting `preference`, `decision`, and `fact` tags.
- **Lifecycle Management**: Implementing time-decay weights and recency boosts to prioritize current network states.
- **Scope Isolation (Multi-tenant)**: Force scope and agent boundaries at query time (e.g. `WHERE scope IN ('global', 'RoutingAgent')`) via database-level filtering.

### B. Agentic Integration (Middleware Approach)
Integrate memory directly into the `DeepAgents` loop via middleware rather than just standalone skills:
- **Auto-Recall (Pre-processor)**: Injects relevant historical context into the prompt *before* the agent starts thinking.
- **Auto-Capture (Post-processor)**: Summarizes the conversation and extracts key takeaways (decisions/facts/audits) into LanceDB *after* a successful task execution.
- **Dynamic Guardrails**: Instead of modifying codebase files, the system uses learned past failures as guardrails inside the prompt (e.g. *"Last time you ran `show bgp`, it timed out. Use `--limit` this time."*).

### C. Data Boundary & Topological Expansion
A strict logical boundary and topological structure must be enforced to prevent hallucinations and expand capability:
- **System Logs Management**: OLAV framework traces, Python errors, and raw `logs/olav.json` are standard application logs. They NEVER enter the DuckDB lakehouse or LanceDB network memory. They remain as flat files or are shipped to external log management systems (e.g. ELK/Splunk).
- **Network Memory (LanceDB)**: Only high-level, summarized network episodes (e.g., "Datacenter-A experienced BGP flaps from 10:00 to 10:15") or Agent Playbook Audits enter the semantic memory.
- **Network Topology (DuckPGQ)**: The current `topology` flat table in DuckDB will be significantly expanded using the **DuckPGQ (Property Graph Queries)** extension. This allows complex pathfinding, loop detection, and relationship analysis (e.g., `MATCH (device_a)-[link]->(device_b)`) rather than writing monolithic/nested SQL JOINs, bridging the gap between structured SQL and graph queries.

## 4. Cost and Performance Optimization

- **Zero-Cost Vectors**: Use local models (e.g., `bge-small`) to process internal logs and KB files without API fees.
- **Tiered Cache**: Use LanceDB as a **Semantic Cache** (Tier 0). If a query is 98% similar to a frequent cached request, return the cached answer immediately.
- **Hybrid Indexing**: Large logs remain in Parquet (Lance format), enabling extremely fast FTS (Full-Text Search) for exact matches like interface names or error codes.

## 5. Roadmap

1.  **Phase 1 (Foundation)**: Initialize `lancedb_store.py` (with Custom Native Pipeline for RRF/BM25) and migrate ALL existing DuckDB KB chunks to LanceDB. **Delete all legacy DuckDB `knowledge_chunks` vector code, extensions (VSS), and LangChain integrations.**
2.  **Phase 2 (Experience System)**: Implement Categorized Memory (Preference/Fact/Decision) with Scope Isolation and Auto-Recall middleware.
3.  **Phase 3 (Topological Graph Engine)**: Integrate DuckPGQ to refactor the `topology` table, and release a dedicated tool (e.g., `analyze_network_topology`) to the Ops/Config Agent, giving it property graph-traversal capabilities for intent verification and loop detection.
4.  **Phase 4 (Self-Learning Guardrails)**: Inject historical successful/failed patterns stored in LanceDB dynamically into Agent context, avoiding brittle modification of static YAML/Python files.

---
**Development Note**: This architecture follows the *Skill-Centric Platform-Agnostic* philosophy of Olav v0.10.0, ensuring the memory layer is native and highly performant.
