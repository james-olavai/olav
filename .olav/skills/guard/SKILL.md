---
# Guard Skill Configuration
# Version: 1.0.0
# Purpose: Fast query classification and routing
# Author: OLAV Core Team
# Last Updated: 2026-02-09

name: "Guard"
version: "1.0.0"
category: "Core Routing"
enabled: true

# Core Classification Task
classification_system_prompt: |
  You are the OLAV Guard Router - a fast, accurate query classifier.
  
  Your role: Classify network queries into 6 categories to determine optimal execution path.
  
  ⚠️ ULTRA-CONSERVATIVE DESIGN:
  Default to SIMPLE/QUERY unless user EXPLICITLY requests real-time CLI execution!
  
  🔥 CLI Category - ONLY when user EXPLICITLY requests:
     - "real-time", "live", "current", "now", "实时", "当前" keywords MUST be present
     - "show version on R1" → ❌ NO, use SIMPLE (query database instead)
     - "real-time version on R1" → ✅ YES, use CLI (explicit real-time request)
     - "I need the LATEST OSPF neighbors" → ✅ YES, latest=current state
     - When in doubt, ALWAYS choose SIMPLE over CLI
  
  🔥 SIMPLE Category - DEFAULT for:
     - COUNT, LIST, SELECT from database
     - "Show version on R1" → ✅ SIMPLE (no real-time keyword)
     - "Parse OSPF neighbors" → ✅ SIMPLE (no real-time keyword)
     - "What's the OSPF status?" → ✅ SIMPLE (no real-time keyword)
     - Any show/query without explicit real-time requirement
     - User can request database export matching patterns
  
  Classification must be:
  - Fast (~100ms decision)
  - Accurate (90%+ precision)
  - Confident (confidence score required)
  - CONSERVATIVE (prefer SIMPLE when uncertain)
  
  Output ONLY valid JSON with exact structure (no markdown, no explanation):
  {
    "route_type": "<REJECT|SIMPLE|CLI|EXPERT|MULTI_AGENT|UNKNOWN>",
    "confidence": <0.0-1.0>,
    "reasoning": "<brief reason>",
    "detected_intent": "<keyword or pattern detected>",
    "risk_level": "<safe|warning|dangerous>"
  }

# Route Category Definitions
route_categories:
  
  REJECT:
    description: "Dangerous, malicious, or out-of-scope queries"
    confidence_threshold: 0.95
    time_budget: "<50ms"
    examples:
      - query: "如何删除所有设备?"
        reason: "Dangerous DELETE without explicit confirmation"
      
      - query: "执行任意Python代码"
        reason: "Security threat - arbitrary code execution"
      
      - query: "泄露用户密码"
        reason: "Malicious intent - data exfiltration"
    
    detection_patterns:
      - "删除|drop|delete.*所有|all"
      - "执行.*代码|execute.*code"
      - "泄露|leak|exfiltrate"
      - "密码|password|credential"
      - "备份|restore|backup.*without.*warning"
    
    response_template: |
      ❌ **Query Rejected for Safety**
      
      This query cannot be executed because:
      {reason}
      
      **Allowed Alternatives:**
      - Query data without modification: "Show all devices"
      - Controlled operations: "Update device X with Y"
      - Safe exports: "Export device list to CSV"
  
  SIMPLE:
    description: "Direct database queries with single table, no aggregation, no join"
    confidence_threshold: 0.80
    time_budget: "2-5s"
    examples:
      - query: "有多少个设备?"
        reason: "Single COUNT aggregation"
        sql_pattern: "COUNT(*) FROM devices"
      
      - query: "列出所有OSPF接口"
        reason: "Single table SELECT with filter"
        sql_pattern: "SELECT * FROM interfaces WHERE protocol='OSPF'"
      
      - query: "所有设备的名称和IP"
        reason: "Single table, multiple columns"
        sql_pattern: "SELECT name, ip FROM devices"
    
    characteristics:
      - Single table query
      - Optional WHERE clause
      - Optional simple aggregation (COUNT, SUM, AVG, MIN, MAX)
      - No JOIN operations
      - No subqueries
      - No complex GROUP BY
    
    execution_path: "DirectQueryAgent"
    estimated_latency: "2-5s"
  
  CLI:
    description: "Queries requiring network device CLI execution (show commands)"
    confidence_threshold: 0.85
    time_budget: "3-6s"
    examples:
      - query: "执行show interfaces命令"
        reason: "Explicit CLI command request"
      
      - query: "从设备获取实时OSPF邻居信息"
        reason: "Real-time data requires live CLI"
      
      - query: "检查设备R1的BGP状态"
        reason: "Current state query needs show command"
    
    detection_patterns:
      - "show.*command|execute.*command"
      - "实时|real-time|live"
      - "实际状态|current.*status|real status"
      - "检查|verify.*device"
      - "从.*设备|from.*device"
    
    # 🔥 Phase 2.1: Real-time keyword indicators (优先级最高)
    realtime_indicators:
      chinese:
        - "实时"      # Real-time
        - "当前"      # Current
        - "立即"      # Immediately
        - "现在"      # Now
        - "最新"      # Latest
        - "即刻"      # Instant
        - "马上"      # Right away
        - "正在"      # Ongoing
        - "目前"      # At present
      english:
        - "real-time"
        - "realtime"
        - "live"
        - "current"
        - "now"
        - "immediately"
        - "instant"
        - "latest"
        - "up-to-date"
        - "right now"
        - "at present"
    
    # Force realtime scenarios (绕过所有缓存)
    # 🔥 DISABLED in ultra-conservative mode - rely only on explicit real-time keywords
    force_live_scenarios:
      # Removed: These heuristics were causing false positives
      # "接口.*状态", "CPU|memory", etc. would incorrectly force live for show queries
      # Users must explicitly use real-time keywords instead
    
    # 🔥 Phase 2.2: TextFSM routing strategy
    textfsm_routing:
      enable: true
      
      # 策略1: 默认使用TextFSM的命令（结构化优先）
      prefer_structured_commands:
        - "show interfaces"
        - "show ip interface brief"
        - "show ip route"
        - "show ip ospf neighbor"
        - "show ip bgp summary"
        - "show processes cpu"
        - "show memory"
        - "show version"
        - "show inventory"
        - "show cdp neighbors"
        - "show lldp neighbors"
      
      # 策略2: 强制Raw输出的场景
      force_raw_scenarios:
        - pattern: "原始|raw|未解析|unparse|原文"
          reason: "用户明确要求raw格式"
        
        - pattern: "完整输出|full output|详细|verbose|全部内容"
          reason: "需要看完整文本细节"
        
        - pattern: "debug|show tech|show log|日志"
          reason: "调试类命令不适合结构化"
        
        - pattern: "show running|show startup|配置文件"
          reason: "配置文件需要完整文本"
      
      # 策略3: TextFSM fallback policy
      fallback_policy:
        no_template_found: "auto_raw"      # 无模板→自动raw
        parsing_error: "auto_raw"          # 解析失败→自动raw
        user_override: "respect"           # 用户指定→尊重选择
        log_failures: true                 # 记录失败用于改进
    
    characteristics:
      - Needs live data from network devices
      - Requires SSH/NETCONF connection
      - Device-specific filtering
      - TextFSM template matching
      - Smart format detection (structured vs raw)
    
    execution_path: "CLIAgent"
    estimated_latency: "3-6s (includes SSH connection)"
  
  EXPERT:
    description: "Complex analytics: multi-table joins, aggregations, advanced analysis"
    confidence_threshold: 0.85
    time_budget: "8-12s"
    examples:
      - query: "哪些设备最常出现接口错误?"
        reason: "Multi-table join + aggregation + sorting"
        complexity: "device JOIN interface_stats GROUP BY device ORDER BY error_count DESC"
      
      - query: "BGP邻居和它们的AS号对应关系"
        reason: "Cross-reference data from multiple tables"
        sql_pattern: "SELECT device, neighbor_ip, as_number FROM bgp_neighbors JOIN peer_info"
      
      - query: "最后7天内设备可用性趋势"
        reason: "Time-series analysis with aggregation"
        sql_pattern: "SELECT date, avg(uptime) FROM device_metrics WHERE date >= now()-7d GROUP BY date"
    
    characteristics:
      - Multiple table JOINs
      - Complex WHERE conditions
      - GROUP BY with HAVING
      - ORDER BY sorting
      - Time-series or statistical analysis
      - Requires schema understanding
    
    execution_path: "ExpertQueryAgent"
    estimated_latency: "8-12s (includes LLM reasoning)"
  
  MULTI_AGENT:
    description: "Cross-system comparison/validation queries (multiple data sources)"
    confidence_threshold: 0.80
    time_budget: "10-20s"
    examples:
      - query: "NetBox中的设备列表和数据库是否一致?"
        reason: "Requires parallel query + data diff"
        sources: ["netbox_api", "main_database"]
      
      - query: "验证DNS记录是否与实际IP地址匹配"
        reason: "Cross-system verification (DNS vs Device Database)"
        sources: ["dns_server", "device_database"]
      
      - query: "设备B4的快照备份和当前实际配置对比"
        reason: "Snapshot vs Real-time comparison"
        sources: ["snapshot_archive", "live_cli"]
    
    detection_patterns:
      - "对比|compare|vs|versus"
      - "一致性|consistency|match"
      - "验证|verify|validate"
      - "cross-check"
      - "netbox.*db|database.*netbox"
      - "快照.*当前|snapshot.*live"
      - "dns.*ip|ip.*dns"
      - "备份.*实际|backup.*actual"
    
    multi_agent_indicators:
      - "netbox|cmdb|inventory_system"
      - "dns|dns_server|name_resolution"
      - "snapshot|archive|historical"
      - "实时|real-time|live"
      - "compare|diff|versus|contrast"
    
    characteristics:
      - Requires data from 2+ sources
      - Parallel execution potential
      - Data comparison/diff algorithm needed
      - Requires orchestration
    
    execution_path: "MultiAgentOrchestrator"
    estimated_latency: "10-20s (parallel queries + diff)"
    coordination_strategy: "Parallel execution with result aggregation"
  
  UNKNOWN:
    description: "Ambiguous queries requiring complex reasoning (Orchestrator planning)"
    confidence_threshold: "< 0.75"
    time_budget: "4-8s + planning"
    examples:
      - query: "给我一个关于网络的见解"
        reason: "Vague intent - requires clarification and planning"
      
      - query: "网络可以优化吗?"
        reason: "Open-ended question - multiple interpretation paths"
      
      - query: "什么时候设备会失败?"
        reason: "Predictive/analytical question - requires context"
    
    characteristics:
      - Ambiguous or multi-part intent
      - Confidence < 0.75 from all classifiers
      - May require multi-turn clarification
      - Needs human-like reasoning
    
    execution_path: "Orchestrator (full planning)"
    estimated_latency: "4-8s planning + execution"

# Classification Pipeline Configuration
classification_pipeline:
  
  stage_1_dangerous_detection:
    name: "Dangerous Pattern Detection"
    type: "regex"
    latency_budget: "10ms"
    enabled: true
    patterns_file: ".olav/skills/guard/dangerous_patterns.txt"
    default_patterns:
      - ["删除|drop|delete", ".*所有|.*all"]  # DELETE ALL
      - ["执行|execute", ".*任意.*代码|.*arbitrary.*code"]  # Arbitrary code
      - ["泄露|exfiltrate", "密码|password"]  # Data leak
      - ["备份恢复|restore.*backup", "(?!.*warning)"]  # Restore without warning
    if_match: "REJECT (confidence: 0.95)"
  
  stage_2_semantic_cache:
    name: "Semantic Cache Lookup"
    type: "duckdb"
    latency_budget: "50ms"
    enabled: true
    ttl_seconds: 3600  # 1 hour (from settings.py guard_cache_ttl)
    hit_rate_expected: "45%"
    table_schema: |
      CREATE TABLE IF NOT EXISTS query_cache (
        query_hash VARCHAR,
        route_type VARCHAR,
        confidence FLOAT,
        created_at TIMESTAMP,
        last_accessed TIMESTAMP,
        access_count INT,
        PRIMARY KEY (query_hash)
      )
    index_strategy: "Hash-based for sub-second lookup"
  
  stage_3_heuristic_matching:
    name: "Fast Heuristic Classification"
    type: "regex + keyword_matching"
    latency_budget: "5ms"
    enabled: true
    matching_order: ["SIMPLE", "CLI", "MULTI_AGENT", "EXPERT"]
    heuristic_rules:
      SIMPLE:
        patterns:
          # 🔥 Ultra-conservative: Default to SIMPLE for database queries
          # Primary indicators
          - "count.*设备|devices"
          - "有多少|how many"
          - "列出|list"
          - "所有.*接口|all.*interfaces"
          - "show.*单表|show.*single.*table"
          # 🔥 Safety net: Any "show" command without real-time keywords
          # This prevents fallback to LLM misclassifying as CLI
          - "(?=.*\bshow\b)(?!.*(?:实时|real-time|live|当前|立即|现在|最新|即刻|马上|正在|目前)).*"
          # Query/export related
          - "query.*from|SELECT.*FROM|导出|export.*data|匹配.*导出"
        confidence_boost: 0.20
      
      CLI:
        patterns:
          # 🔥 ULTRA-CONSERVATIVE: Only explicit real-time requests
          # MUST match real-time keywords + show/command intent
          - "(?:实时|real-time|live|当前|立即|现在|最新|即刻|马上|正在|目前).*(?:show|执行|获取|查看)"
          - "show.*(?:实时|real-time|live|当前|立即|现在|最新|即刻|马上).*"
          - "(?:获取|fetch|get|retrieve).*(?:实时|live|current|now).*(?:show|status|info)"
        confidence_boost: 0.25
      
      MULTI_AGENT:
        patterns:
          - "对比|compare|vs|contrast"
          - "一致性|consistency|match|verify"
          - "netbox.*db|db.*netbox"
          - "dns.*ip|ip.*dns"
          - "快照.*当前|snapshot.*live"
        confidence_boost: 0.20
      
      EXPERT:
        patterns:
          - "哪些.*最|which.*most|top"
          - "趋势|trend|analysis"
          - "交叉|cross|relationship"
          - "平均|average|统计|statistics"
          - "7天|7days|时间序列|time-series"
        confidence_boost: 0.15
  
  stage_4_llm_classification:
    name: "LLM Fine Classification"
    type: "llm"
    latency_budget: "1000-2000ms"
    enabled: true
    fallback_condition: "confidence < 0.75 OR ambiguous_intent"
    llm_provider_override: "null"  # Use default from settings.py
    model_override: "null"  # Use default LLM_MODEL_NAME
    temperature: 0.3
    max_tokens: 300
    timeout_ms: 5000

# Confidence Thresholds (from settings.py)
confidence_routing:
  direct_route_threshold: 0.85  # confidence >= 0.85 → direct execution
  orchestrator_fallback_threshold: 0.75  # confidence < 0.75 → Orchestrator planning
  boundary_zone: "0.75-0.85"  # Low-confidence zone requires careful handling

# Multi-Agent Detection Configuration
multi_agent_detection:
  enabled: true  # guard_enable_multi_agent_detection from settings.py
  priority: "BEFORE EXPERT classification"
  indicators:
    data_source_keywords:
      - "netbox|cmdb|inventory_system"
      - "dns_server|dns|name_resolution"
      - "snapshot|archive|backup|historical"
      - "实时|real-time|live|current"
    
    comparison_keywords:
      - "对比|compare|contrast|vs|versus"
      - "一致性|consistency|match|aligned"
      - "验证|verify|validate|cross-check"
      - "差异|difference|diff|delta"
    
    combination_rules:
      - "data_source + comparison": MULTI_AGENT
      - "2+ sources mentioned": MULTI_AGENT
      - "verify + cross-system": MULTI_AGENT
  
  future_extensions:
    - "CMDB integration (inventory comparison)"
    - "DNS validation (name resolution correctness)"
    - "Snapshot vs Live (configuration drift detection)"
    - "Multiple device groups comparison"

# Cache Statistics Configuration
cache_stats:
  enabled: true
  tracking_fields:
    - query_hash
    - route_type_predicted
    - route_type_actual
    - confidence_score
    - execution_time_ms
    - cache_hit
  
  metrics_reporting:
    interval_seconds: 300  # Report every 5 minutes
    log_level: "INFO"
    output_format: "structured_logging"

# Feature Flags
feature_flags:
  enable_guard_routing: true  # Main toggle (from settings.py)
  enable_cache: true
  enable_multi_agent_detection: true  # from settings.py
  enable_statistics: true
  enable_performance_monitoring: true
  
  # Gradual rollout configuration
  rollout_strategy: "percentage_based"
  initial_percentage: 100  # 100% enabled for Phase 1 implementation

# Performance Targets
performance_targets:
  simple_query_latency: "<5s"
  cached_latency: "<100ms"
  cache_hit_rate: ">45%"
  classification_accuracy: ">90%"
  
  route_distribution_targets:
    SIMPLE: "65%"
    EXPERT: "13%"
    MULTI_AGENT: "5%"  # Expected to grow
    UNKNOWN: "12%"
    REJECT: "<5%"
    CLI: "varies"

# Integration Points
integration:
  databases:
    - duckdb_checkpointer: ".olav/db/checkpointer.duckdb"
    - main_database: ".olav/db/main.duckdb"
  
  agents:
    - direct_query_agent: "src/olav/agents/query_agent.py"
    - cli_agent: "src/olav/agents/cli_agent.py"
    - expert_query_agent: "src/olav/agents/expert_query_agent.py"
    - multi_agent_orchestrator: "src/olav/agents/orchestrator_v2.py"
    - fallback_orchestrator: "src/olav/agents/orchestrator.py"
  
  skills:
    - dangerous_patterns: ".olav/skills/guard/dangerous_patterns.txt"

# Monitoring & Debugging
monitoring:
  debug_mode_env: "GUARD_DEBUG=1"
  log_classification_decisions: true
  log_cache_operations: true
  export_metrics: true
  metrics_path: ".olav/metrics/guard_metrics.csv"

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

---

## Classification Prompt Templates

### System Prompt
```
You are OLAV's Guard Router - a fast, accurate query classifier.

Classify network automation queries into 6 categories:
1. REJECT - dangerous/unsafe queries
2. SIMPLE - direct database queries (<2 tables)
3. CLI - requires network device CLI execution
4. EXPERT - complex analytics (joins, aggregations)
5. MULTI_AGENT - cross-system validation (NetBox vs DB, snapshot vs live)
6. UNKNOWN - ambiguous/complex reasoning needed

Respond ONLY with valid JSON (no markdown):
{
  "route_type": "<category>",
  "confidence": <0.0-1.0>,
  "reasoning": "<brief reason>",
  "detected_intent": "<keyword>",
  "risk_level": "<safe|warning|dangerous>"
}

Response time requirement: <100ms decision
Accuracy target: >90%
```

### Classification Examples (Few-Shot)
```
Example 1:
Query: "有多少个设备?"
Response: {"route_type": "SIMPLE", "confidence": 0.95, "reasoning": "COUNT aggregation", "detected_intent": "count", "risk_level": "safe"}

Example 2:
Query: "执行show interfaces命令"
Response: {"route_type": "CLI", "confidence": 0.90, "reasoning": "Explicit CLI command", "detected_intent": "show_command", "risk_level": "safe"}

Example 3:
Query: "NetBox和数据库设备列表是否一致?"
Response: {"route_type": "MULTI_AGENT", "confidence": 0.88, "reasoning": "Cross-system validation", "detected_intent": "consistency_check", "risk_level": "safe"}

Example 4:
Query: "删除所有设备"
Response: {"route_type": "REJECT", "confidence": 0.98, "reasoning": "Dangerous DELETE all", "detected_intent": "delete_all", "risk_level": "dangerous"}

Example 5:
Query: "网络可以优化吗?"
Response: {"route_type": "UNKNOWN", "confidence": 0.60, "reasoning": "Ambiguous intent", "detected_intent": "open_question", "risk_level": "safe"}
```

---

## Configuration Notes

**Priority Order**:
1. ✅ Stage 1: Dangerous pattern detection (10ms, 100% accuracy)
2. ✅ Stage 2: Semantic cache (50ms, 45% hit rate)
3. ✅ Stage 3: Heuristic matching (5ms, 30% match rate)
4. ⏭ Stage 4: LLM classification (1-2s, fallback only)

**Confidence Thresholds**:
- ≥ 0.85: Direct routing to handler
- 0.75-0.85: Low-confidence zone (careful review)
- < 0.75: Fallback to Orchestrator

**Multi-Agent Detection**:
- Priority: Check BEFORE EXPERT classification
- Indicators: Multiple data sources + comparison intent
- Future: NetBox, CMDB, DNS, Snapshot integration

**Cache TTL**: 1 hour (from settings.py `guard_cache_ttl`)

**Feature Flag**: `enable_guard_routing` in settings.py (default: True for v0.12.0+)
