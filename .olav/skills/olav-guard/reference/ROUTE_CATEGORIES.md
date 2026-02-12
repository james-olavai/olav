# Guard Route Categories - Detailed Reference

This document provides detailed information about each route category and classification decisions.

## REJECT - Dangerous Queries

**Description**: Dangerous, malicious, or out-of-scope queries

**Confidence Threshold**: 0.95  
**Time Budget**: <50ms  

**Detection Patterns**:
- "删除|drop|delete.*所有|all" - DELETE ALL operations
- "执行.*代码|execute.*code" - Arbitrary code execution
- "泄露|leak|exfiltrate" - Data exfiltration
- "密码|password|credential" - Password-related
- "备份|restore|backup.*without.*warning" - Unsafe restore

**Response Template**:
```
❌ **Query Rejected for Safety**

This query cannot be executed because:
{reason}

**Allowed Alternatives:**
- Query data without modification: "Show all devices"
- Controlled operations: "Update device X with Y"
- Safe exports: "Export device list to CSV"
```

---

## SIMPLE - Direct Database Queries

**Description**: Direct database queries with single table, no aggregation, no join

**Confidence Threshold**: 0.80  
**Time Budget**: 2-5s  
**Execution Path**: DirectQueryAgent

**Characteristics**:
- Single table query
- Optional WHERE clause
- Optional simple aggregation (COUNT, SUM, AVG, MIN, MAX)
- No JOIN operations
- No subqueries
- No complex GROUP BY

**Examples**:
1. "有多少个设备?" → COUNT(*) FROM devices
2. "列出所有OSPF接口" → SELECT * FROM interfaces WHERE protocol='OSPF'
3. "所有设备的名称和IP" → SELECT name, ip FROM devices

---

## CLI - Real-Time Device Execution

**Description**: Queries requiring network device CLI execution (show commands)

**Confidence Threshold**: 0.85  
**Time Budget**: 3-6s  
**Execution Path**: CLIAgent

**⚠️ ULTRA-CONSERVATIVE DESIGN**:
- Only execute CLI when user EXPLICITLY requests real-time data
- Default to SIMPLE for all database queries
- Real-time keywords MUST be present

**Real-Time Indicators**:
- Chinese: 实时, 当前, 立即, 现在, 最新, 即刻, 马上, 正在, 目前
- English: real-time, realtime, live, current, now, immediately, instant, latest, up-to-date, right now, at present

**Examples**:
1. "执行show interfaces命令" → CLI (explicit command)
2. "从设备获取实时OSPF邻居信息" → CLI (real-time keyword)
3. "检查设备R1的BGP状态" → CLI (current state query)

**TextFSM Strategy**:
- Prefers structured commands when possible
- Fallback to raw when no template available
- User can force raw with "原始|raw|未解析" keywords

---

## EXPERT - Complex Analytics

**Description**: Complex analytics: multi-table joins, aggregations, advanced analysis

**Confidence Threshold**: 0.85  
**Time Budget**: 8-12s  
**Execution Path**: ExpertQueryAgent

**Characteristics**:
- Multiple table JOINs
- Complex WHERE conditions
- GROUP BY with HAVING
- ORDER BY sorting
- Time-series or statistical analysis
- Requires schema understanding

**Examples**:
1. "哪些设备最常出现接口错误?" → Multi-table join + aggregation + sorting
2. "BGP邻居和它们的AS号对应关系" → Cross-reference data from multiple tables
3. "最后7天内设备可用性趋势" → Time-series analysis with aggregation

---

## MULTI_AGENT - Cross-System Comparison

**Description**: Cross-system comparison/validation queries (multiple data sources)

**Confidence Threshold**: 0.80  
**Time Budget**: 10-20s  
**Execution Path**: MultiAgentOrchestrator

**Characteristics**:
- Requires data from 2+ sources
- Parallel execution potential
- Data comparison/diff algorithm needed
- Requires orchestration

**Examples**:
1. "NetBox中的设备列表和数据库是否一致?" → Compare 2 sources
2. "验证DNS记录是否与实际IP地址匹配" → Cross-system verification
3. "设备B4的快照备份和当前实际配置对比" → Snapshot vs Real-time

**Detection Indicators**:
- Data sources: netbox, CMDB, DNS, snapshot, archive
- Comparison: compare, vs, verify, consistency check

---

## UNKNOWN - Ambiguous Queries

**Description**: Ambiguous queries requiring complex reasoning (Orchestrator planning)

**Confidence Threshold**: < 0.75  
**Time Budget**: 4-8s + planning  
**Execution Path**: Orchestrator (full planning)

**Characteristics**:
- Ambiguous or multi-part intent
- Confidence < 0.75 from all classifiers
- May require multi-turn clarification
- Needs human-like reasoning

**Examples**:
1. "给我一个关于网络的见解" → Vague intent
2. "网络可以优化吗?" → Open-ended question
3. "什么时候设备会失败?" → Predictive/analytical

---

## Classification Pipeline

### Stage 1: Dangerous Pattern Detection (10ms)
- Regex pattern matching
- Fast detection of obviously dangerous queries
- If match: REJECT with confidence 0.95

### Stage 2: Semantic Cache (50ms)
- DuckDB-based caching
- 1-hour TTL
- Expected hit rate: 45%

### Stage 3: Heuristic Matching (5ms)
- Regex + keyword matching
- Fast classification for obvious cases
- Check order: SIMPLE → CLI → MULTI_AGENT → EXPERT

### Stage 4: LLM Classification (1-2s)
- LLM-based fine classification
- Fallback when confidence < 0.75
- Handles ambiguous cases

---

## Confidence Routing

| Confidence | Action |
|-----------|--------|
| ≥ 0.85 | Direct routing to handler |
| 0.75-0.85 | Low-confidence zone (careful review) |
| < 0.75 | Fallback to Orchestrator |

---

## Performance Targets

- Simple query latency: <5s
- Cached latency: <100ms
- Cache hit rate: >45%
- Classification accuracy: >90%

**Expected Route Distribution**:
- SIMPLE: 65%
- EXPERT: 13%
- UNKNOWN: 12%
- MULTI_AGENT: 5%
- REJECT: <5%
- CLI: varies
