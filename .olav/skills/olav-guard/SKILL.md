---
# Guard Skill - Fast Query Classification and Routing
# Version: 1.0.0
# Purpose: Classify queries into 6 execution paths (REJECT, SIMPLE, CLI, EXPERT, MULTI_AGENT, UNKNOWN)
# Author: OLAV Core Team
# Last Updated: 2026-02-12

name: "Guard"
version: "1.0.0"
category: "Core Routing"
enabled: true

# Classification System Prompt (provides detailed classification rules)
classification_system_prompt: !include ./prompts/classifier_system_prompt.md

# Route Category Definitions (see reference/ROUTE_CATEGORIES.md for detailed info)
route_categories:
  
  REJECT:
    description: "Dangerous, malicious, or out-of-scope queries"
    confidence_threshold: 0.95
    time_budget: "<50ms"
    execution_path: "SafeRejectionHandler"
    patterns_file: "./patterns/dangerous_patterns.txt"
  
  SIMPLE:
    description: "Direct database queries (single table, optional simple aggregation)"
    confidence_threshold: 0.80
    time_budget: "2-5s"
    execution_path: "DirectQueryAgent"
    patterns_file: "./patterns/simple_patterns.txt"
  
  CLI:
    description: "Real-time device CLI execution (show commands with explicit real-time keywords)"
    confidence_threshold: 0.85
    time_budget: "3-6s"
    execution_path: "CLIAgent"
    patterns_file: "./patterns/cli_patterns.txt"
  
  EXPERT:
    description: "Complex analytics (multi-table joins, aggregations, advanced analysis)"
    confidence_threshold: 0.85
    time_budget: "8-12s"
    execution_path: "ExpertQueryAgent"
    patterns_file: "./patterns/expert_patterns.txt"
  
  MULTI_AGENT:
    description: "Cross-system comparison/validation (multiple data sources)"
    confidence_threshold: 0.80
    time_budget: "10-20s"
    execution_path: "MultiAgentOrchestrator"
    patterns_file: "./patterns/multi_agent_patterns.txt"
  
  UNKNOWN:
    description: "Ambiguous queries requiring complex reasoning"
    confidence_threshold: "<0.75"
    time_budget: "4-8s + planning"
    execution_path: "Orchestrator"

# Classification Pipeline Configuration
classification_pipeline:
  
  stage_1_dangerous_detection:
    name: "Dangerous Pattern Detection"
    type: "regex"
    latency_budget: "10ms"
    enabled: true
    patterns_file: "./patterns/dangerous_patterns.txt"
  
  stage_2_semantic_cache:
    name: "Semantic Cache Lookup"
    type: "duckdb"
    latency_budget: "50ms"
    enabled: true
    ttl_seconds: 3600  # 1 hour
    hit_rate_expected: "45%"
    location: ".olav/skills/olav-guard/db/guard_cache.duckdb"
  
  stage_3_heuristic_matching:
    name: "Fast Heuristic Classification"
    type: "regex + keyword_matching"
    latency_budget: "5ms"
    enabled: true
    matching_order: ["SIMPLE", "CLI", "MULTI_AGENT", "EXPERT"]
  
  stage_4_llm_classification:
    name: "LLM Fine Classification"
    type: "llm"
    latency_budget: "1000-2000ms"
    enabled: true
    fallback_condition: "confidence < 0.75"
    temperature: 0.3
    max_tokens: 300

# Confidence Thresholds
confidence_routing:
  direct_route_threshold: 0.85        # confidence >= 0.85 → direct execution
  orchestrator_fallback_threshold: 0.75  # confidence < 0.75 → Orchestrator planning
  boundary_zone: "0.75-0.85"          # low-confidence zone

# Multi-Agent Detection
multi_agent_detection:
  enabled: true
  priority: "BEFORE EXPERT classification"
  data_source_keywords:
    - "netbox|cmdb|inventory_system"
    - "dns_server|dns|name_resolution"
    - "snapshot|archive|backup|historical"
  comparison_keywords:
    - "对比|compare|vs|verify"
    - "一致性|consistency|match"

# Feature Flags
feature_flags:
  enable_guard_routing: true              # Main toggle
  enable_cache: true
  enable_multi_agent_detection: true
  enable_statistics: true
  rollout_percentage: 100                 # 100% for Phase 1

# Performance Targets
performance_targets:
  simple_query_latency: "<5s"
  cached_latency: "<100ms"
  cache_hit_rate: ">45%"
  classification_accuracy: ">90%"
  
  route_distribution_targets:
    SIMPLE: "65%"
    EXPERT: "13%"
    UNKNOWN: "12%"
    MULTI_AGENT: "5%"
    REJECT: "<5%"
    CLI: "varies"

# Integration Points
integration:
  agents:
    - direct_query: "src/olav/agents/query_agent.py"
    - cli_agent: "src/olav/agents/cli_agent.py"
    - expert_agent: "src/olav/agents/expert_query_agent.py"
    - multi_agent: "src/olav/agents/orchestrator_v2.py"
    - fallback: "src/olav/agents/orchestrator.py"
  
  databases:
    - guard_cache: ".olav/skills/olav-guard/db/guard_cache.duckdb"
    - main: ".olav/db/main.duckdb"

# Monitoring & Debugging
monitoring:
  debug_mode_env: "GUARD_DEBUG=1"
  log_classification_decisions: true
  log_cache_operations: true
  export_metrics: true

# Version History
version_history:
  v1.0.0:
    date: "2026-02-09"
    status: "Initial implementation"
    features:
      - 6-route classification system
      - 4-stage pipeline (dangerous → cache → heuristic → LLM)
      - DuckDB caching with 1-hour TTL
      - Multi-agent detection
      - Feature flag support
  
  v1.1.0:
    date: "2026-02-12"
    status: "Refactored to reference-based structure"
    changes:
      - Extracted system prompt to prompts/classifier_system_prompt.md
      - Extracted patterns to patterns/*.txt
      - Created reference/ROUTE_CATEGORIES.md for detailed documentation
      - Reduced SKILL.md from 596 to ~150 lines

---

## Quick Reference

**See Also**:
- 📖 [Route Categories](./reference/ROUTE_CATEGORIES.md) - Detailed classification guide
- 📝 [Classifier Prompt](./prompts/classifier_system_prompt.md) - LLM system prompt
- 🎯 [Pattern Files](./patterns/) - Classification patterns for each route

**For Implementation**:
- Classification code: `src/olav/agents/guard.py`
- Cache location: `.olav/skills/olav-guard/db/guard_cache.duckdb`
- Dangerous patterns: `./patterns/dangerous_patterns.txt`

**Configuration**:
- Enable/disable: `settings.agent.enable_guard_routing`
- Cache TTL: `settings.agent.guard_cache_ttl` (default: 3600s)
- Confidence threshold: `settings.agent.guard_confidence_threshold` (default: 0.85)
