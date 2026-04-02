# OLAV NetOps Architecture: The Intelligence Layer

**Version:** v0.13.0 (2026-03-22)  
**Status:** Canonical Foundation Established  

## 1. Overview

OLAV NetOps is the domain-specific intelligence layer of the OLAV platform. It transforms fragmented, vendor-specific network data into a unified, actionable, and deterministic semantic model. While `olav-platform` provides the orchestration and database primitives, `olav-netops` provides the **Network Knowledge**—the ability to map, reason, and simulate network behavior.

---

## 2. The Three-Layer Truth (Data Strategy)

OLAV NetOps adopts a **Tiered Alignment** strategy to balance raw accuracy with cross-platform unity:

1.  **L1 - Raw Truth (Ingestion)**:
    *   Preserves raw CLI output via TextFSM KV pairs.
    *   Performs only "value-level" normalization (MTU integers, MAC formatting).
    *   **Goal**: Absolute traceability and audit compliance.

2.  **L2 - Vendor Canonical (State Preservation)**:
    *   Retains vendor-specific semantics and performance metrics.
    *   No field renaming at the write stage, preventing "Schema-on-Write" pollution.

3.  **L3 - OpenConfig View (Canonical Query Layer)**:
    *   An LLMndriven **Schema-on-Read** projection.
    *   Maps raw fields to OpenConfig (Standard) or OLAV (Extended) namespaces.

---

## 3. The Intelligent Mapping Pipeline

The core engine of NetOps is the **5-Stage Mapping Pipeline**, which replaces traditional manual parsing with LLM-native semantic discovery:

*   **Stage 1: Cleaning**: Values are normalized by `netutils` while field names remain raw.
*   **Stage 2: Deterministic**: High-confidence cache (`mapping_cache`) and pre-defined rules are checked first.
*   **Stage 3: Semantic Retrieval**: Field names are embedded and matched against a corpus of **800+ YANG leaves** (BGP, OSPF, Interface, QoS, etc.).
*   **Stage 4: Agentic Sandbox**: LLM performs reasoning on medium-confidence matches. If a standard OC path doesn't exist, it generates a **Vendor Extension** path (e.g., `/state/vendor-extensions/...`).
*   **Stage 5: Feedback & Self-Learning**: Verified mappings are backfilled into the cache, increasing performance exponentially with every run.

---

## 4. Semantic Reasoning & Simulation

Building on top of the aligned data, NetOps provides two advanced reasoning engines:

### 4.1 Control-Plane Semantic Engine (Phase 4)
A deterministic engine that understands protocol logic:
*   **BGP Solver**: Best-path selection for prefix propagation.
*   **IGP Solver (OSPF/IS-IS)**: Shortest-path and cost calculation.
*   **Policy IR**: Evaluates route policies and filter statements in a canonical internal representation.

### 4.2 Ops NetworkX Sandbox (Phase 5)
A graph-anchored assistant for real-time investigation:
*   Builds an `nx.MultiDiGraph` from `topology_links`.
*   Calculates **Blast Radius** and performs **Hypothesis Testing**.
*   Acts as a "Hallucination-Reduction" mechanism for the Agent by anchoring reasoning in real state.

---

## 5. Security & Principles

*   **LLM-Native**: Abandoning manual review; using an **Audit Agent** for automated cross-validation of mappings.
*   **Separation of Concerns**: Platform manages the "How" (API, DB, Tools), while NetOps manages the "What" (YANG, Protocols, Network Knowledge).
*   **Advisory Only**: OLAV NetOps generates insights and plans but never executes production configuration directly. The human remains the final authority.

---
© 2026 OLAV Development Team. Confidential and Proprietary.
