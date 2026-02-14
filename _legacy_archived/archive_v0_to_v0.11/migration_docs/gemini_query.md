# OLAV Fast Path Architecture Inquiry

## Current Implementation

### Core Components

#### 1. IntentAgent (src/olav/agents/intent_agent.py)
- **Responsibility**: Intent recognition and execution plan caching
- **Method**: `save_to_intent_cache(query, plan, confidence=1.0)`
- **Key Issue**: Method name mismatch with UnifiedDatabase

**UnifiedDatabase Method**: `save_semantic_cache(query, embedding, action, confidence)`
**IntentAgent Calls**: `save_to_intent_cache(query, plan, confidence)`

**Problem**: 
- IntentAgent uses the semantic cache method name
- But the method signature doesn't match (different parameters)
- This breaks the abstraction - IntentAgent should work at a higher level

---

#### 2. UnifiedDatabase (src/olav/core/unified_database.py)
**Semantic Cache Table**: `commands.main.semantic_cache`
- **Fields**:
  - `query_text` (TEXT)
  - `query_embedding` (FLOAT[768])
  - `action_json` (JSON) - stores action
  - `confidence` (FLOAT)

**Intent Cache Table**: `commands.main.intent_cache` (NEW)
- **Fields**:
  - `query_text` (TEXT)
  - `query_embedding` (FLOAT[768])
  - `execution_plan` (JSON) - stores step-by-step execution plan
  - `confidence` (FLOAT)
  - `created_at` (TIMESTAMP)
  - `last_used` (TIMESTAMP)
  - `hit_count` (INTEGER)

**Methods**:
- `save_semantic_cache()` - saves action to semantic cache (Tier 0)
- `search_semantic_cache()` - NEW: searches intent cache (Tier 0)
- `save_intent_cache()` - NEW: saves execution plan to intent cache (Fast Path)
- `search_intent_cache()` - NEW: searches execution plans (Fast Path)

---

#### 3. QueryAgentV2 (src/olav/agents/query_agent_v2.py)
**Integration Point**: Needs to call IntentAgent for Fast Path
- **Current State**: Imported IntentAgent but not yet integrated
- **Method to Call**: `intent_agent.process_query(query)`

---

## User Feedback Problem

### Issue Description
User reports that queries like "Show R1 BGP neighbors" and "Show R2 BGP neighbors" are semantically very similar (both ask about BGP neighbors), but the cached execution plan produces vastly different results (e.g., R1 optimized plan vs R2 generic plan), causing significant performance and accuracy issues.

### Root Cause Analysis

**Possible Causes**:

1. **Cosine Similarity Too Permissive**
   - Current: Using `array_cosine_similarity >= 0.90`
   - Problem: Two different queries about BGP might both match the cached plan at 0.90+ similarity
   - The cached plan might be too generic or not specific enough

2. **Lack of Query Context Differentiation**
   - Current: Only matching query text and embedding
   - Problem: Not distinguishing:
     - Which device is being queried (R1 vs R2)
     - Query intent nuances (neighbors vs route table)
     - Time/temporal aspects

3. **Cached Execution Plan Too Generic**
   - Current: Single plan stored per query
   - Problem: Plan doesn't account for device-specific configurations, routing tables, or current network state

4. **Confidence Threshold Issues**
   - Current: Fixed threshold of 0.95
   - Problem: No gradation - all cached plans treated the same
   - A 0.98 match should be prioritized over 0.91 match
   - Two queries with 0.97 similarity shouldn't both hit the same cached plan

---

## Questions for Gemini

### Architecture Evaluation

**Q1: Is the current Fast Path architecture fundamentally sound? What are the main pros and cons?**

**Q2: What is the root cause of the "R1 vs R2 semantic similarity but vastly different results" issue? Which do you think is most likely?**

**Q3: Among the proposed solutions below, which do you prioritize? Why?**

**Q4: How can we implement more precise semantic matching without over-engineering?**

**Q5: Is the current 0.95 confidence threshold too high, too low, or just right? Should we make it adaptive?**

**Q6: Can we improve the architecture incrementally without a major refactor? What are the quick wins we can implement in 1-2 days?**

**Q7: Should we completely redesign the IntentAgent/Intent Cache system, or can we improve it with targeted fixes?**

---

## Request

Based on your understanding of Fast Path architecture and semantic caching systems, please provide:

1. **Architecture Analysis**: Your evaluation of the current implementation
2. **Root Cause Diagnosis**: What you believe is causing the R1 vs R2 issue
3. **Recommended Solutions**: Prioritized list of solutions with:
   - Effort required (Low/Medium/High)
   - Expected improvement
   - Potential downsides
4. **Implementation Guidance**: Specific steps to implement the chosen solution
5. **Code Examples**: If applicable, pseudocode or Python snippets showing key improvements

**Note**: We prefer incremental improvements that maintain stability over ambitious rewrites. Don't over-engineer - give practical, production-ready solutions.
