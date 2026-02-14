# Database Architecture Analysis: Why Test Data isn't in Production DB

**Date**: 2026-02-09  
**Status**: 📋 Analysis Complete - No Code Changes Needed  
**Impact**: Understanding → Planning for Phase 4

---

## 问题陈述

1. **test_network.duckdb** 有完整数据（80 devices, 1200 interfaces, 106K stats）
2. **olav.duckdb** 是空的（仅6 devices，多数表为0）
3. **Why?** Test data 由手工脚本生成，生产数据应来自真实设备

---

## 根本原因分析

### 1️⃣ Test Database (test_network.duckdb) - 测试脚本生成

**文件**: `scripts/generate_e2e_test_data.py` (554 lines)

**用途**: E2E测试数据生成脚本

**执行方式**:
```bash
# 默认生成到 test_network.duckdb
uv run python scripts/generate_e2e_test_data.py

# 或指定其他路径
uv run python scripts/generate_e2e_test_data.py --db ".olav/db/test.duckdb" --clear
```

**生成的数据量**:
- ✅ 80 devices (由脚本 `generate_devices()` 创建)
- ✅ 1200 interfaces (15per device: `INTERFACES_PER_DEVICE=15`)
- ✅ 106,537 interface_stats (10 days × 288 samples/day × ~80 devices)
- ✅ Link relationships (L3邻接)
- ✅ BGP routes (0 - 未实现)

**关键代码**:
```python
# Line 206-207
NUM_DEVICES = 80
INTERFACES_PER_DEVICE = 15
DAYS_OF_STATS = 10
SAMPLES_PER_DAY = 288  # 5-minute intervals

# Line 506
parser.add_argument("--db", default=".olav/db/test_network.duckdb",
                   help="DuckDB数据库路径")
```

**为什么这是测试脚本**:
- 参数化数据生成（可控）
- 支持 `--clear` 重新生成
- 生成逼真的时间序列数据（trending）
- 用于 L1/L2 测试验证

---

### 2️⃣ Production Database (olav.duckdb) - 空的原因

**架构设计** (config/paths.py):
```python
# Line 45
UNIFIED_DB = DB_DIR / "olav.duckdb"  # 单一生产数据库

# Line 48-52: 所有数据源指向同一数据库
MAIN_DB_PATH = UNIFIED_DB
SNAPSHOTS_DB = UNIFIED_DB
AUDIT_LOGS_DB = UNIFIED_DB
OLAV_DB_PATH = UNIFIED_DB
```

**初始化流程** (scripts/init.py, Line 281-291):
```python
def initialize_database(olav_dir: Path) -> bool:
    """Initialize olav.duckdb with minimal schema"""
    
    db_path = db_dir / "olav.duckdb"
    
    if db_path.exists():
        print("⏭️  olav.duckdb already exists")
        return False
    
    try:
        from olav.core.database import get_database
        
        get_database(db_path)
        print("✅ Initialized olav.duckdb (Zero-ETL: minimal tables)")
        print("   → Parsed data accessed via read_json_auto()")
        return True
```

**关键观察**: "Zero-ETL: minimal tables"
- ✅ Schema initialized (空表)
- ❌ No data loaded (需要数据导入)
- ❌ No active data ingestion pipeline

---

### 3️⃣ Network Snapshot 数据应该来自哪里？

**设计**: network-snapshot Skill (``.olav/skills/network-snapshot/SKILL.md``)

**工作流程**:
```
User Query
    ↓
CLI → Orchestrator
    ↓
Network Snapshot Agent (Skill)
    ↓
Nornir Execute Command
    ↓
SSH → Device (show int, show route, etc.)
    ↓
Parse Output
    ↓
Store to olav.duckdb (data ingestion)
    ↓
Return Results
```

**为什么数据没有被保存**:

#### 原因 #1: No Nornir Device Connection
```yaml
# .olav/config/nornir/hosts.yaml - 需要真实设备
# 在开发环境中，该文件可能：
# - 不存在
# - 指向模拟/测试设备
# - 指向真实设备但无网络连接
```

#### 原因 #2: Network Snapshot Skill是Agent定义，不是导入脚本
```
network-snapshot/SKILL.md:
  - 定义: Collect network device state
  - 工具: nornir_execute, inspect_schema, discover_data
  - 流程: 执行命令 → 存储快照 → 返回结果
  
但这需要:
  ✅ 已实现: Agent框架 (DeepAgents)
  ⚠️ 问题: Nornir必须有可连接的设备
  ❌ 缺失: 开发环境中的测试设备
```

#### 原因 #3: 没有数据导入脚本
```
Expected flow:
  Test Environment      Production Environment
  ├─ generate_e2e_test_data.py ✅  (local testing)
  │  └─ test_network.duckdb ✅
  │
  └─ [MISSING] import_to_production.py ❌
     └─ olav.duckdb (empty)
```

---

## 当前架构状态

### Database Files
```
.olav/db/
├── olav.duckdb (1.6 MB)
│   ├── devices: 6 rows ✅ (bootstrap data)
│   ├── raw_outputs: 0 rows ❌ (no parsing)
│   ├── query_cache: 0 rows ❌ (no queries logged)
│   ├── schema_version: 1 row ✅ (v1)
│   └── [other]: mostly empty
│
└── test_network.duckdb (11 MB)
    ├── devices: 80 rows ✅ (generated)
    ├── interfaces: 1200 rows ✅ (generated)
    ├── interface_stats: 106,537 rows ✅ (generated)
    └── [expected tables]: complete
```

### Data Gateway (src/olav/lib/data_gateway.py)
```python
# Line 48-78: Both query_main() and query_snapshots()
# point to UNIFIED_DB (olav.duckdb)

def query_main(self, sql: str) -> list[dict]:
    """Query olav.duckdb"""
    from config.paths import UNIFIED_DB  # Line 75
    conn = duckdb.connect(str(UNIFIED_DB))
    return result

def query_snapshots(self, sql: str) -> list[dict]:
    """Query olav.duckdb (v0.10.1: unified)"""
    from config.paths import UNIFIED_DB  # Line 97
    conn = duckdb.connect(str(UNIFIED_DB))
    return result

# Result: Agent always queries olav.duckdb (empty!)
```

### Agent Query Flow
```
Agent Query
  ↓
orchestrate_query()
  ↓
route to network-query Skill
  ↓
query_database() tool (.olav/tools/database/query_database.py)
  ↓
data_gateway.query_main() (Line 48)
  ↓
UNIFIED_DB = olav.duckdb  ← HARDCODED!
  ↓
Result: Empty (because data in test_network.duckdb)
```

---

## 为什么Snapshot没有写入正确数据库

### 根本原因链
```
1. Network Environment
   └─ No Nornir device targets
      └─ No SSH connectivity
         └─ network-snapshot Skill can't execute
            └─ No commands to parse
               └─ No data to store
                  └─ olav.duckdb remains empty

2. Data Architecture
   └─ Zero-ETL design (minimal bootstrap)
      └─ Expects data from external sources
         └─ External sources not configured
            └─ olav.duckdb has no incoming data
               └─ Test script (generate_e2e_test_data.py)
                  generated data to test_network.duckdb
                  (separate, isolated database)

3. Code Design
   └─ data_gateway.py hardcodes UNIFIED_DB
      └─ Can't switch to test_network.duckdb
         └─ Agent never sees test data
            └─ Test queries fail
               └─ But test_network.duckdb has all data!
```

### Why Snapshot Code Doesn't Write

**network-snapshot Skill** (`.olav/skills/network-snapshot/SKILL.md`):
- ✅ Defines data collection workflow
- ✅ Uses Nornir for parallel execution
- ❌ **No actual Nornir device targets** in dev environment
- ❌ **No persistent implementation** (only skill definition)

**Actual Implementation Gap**:
```
Expected:
  .olav/skills/network-snapshot/
  ├── SKILL.md (definition) ✅
  ├── agent.py (implementation) ❌ MISSING?
  └── tools.py (parsers) ❌ MISSING?

Actual:
  .olav/skills/network-snapshot/
  └── SKILL.md only
```

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                       OLAV Data Architecture                     │
└─────────────────────────────────────────────────────────────────┘

╔═══════════════════════════╗
║   Real Network Devices    ║    ← What should populate olav.duckdb
║  (R1, R2, ..., R80)       ║       (via network-snapshot Skill)
╚═════════════╤═════════════╝
              │
              │ SSH (Nornir)
              │ ❌ NO CONNECTION IN DEV
              ↓
       ┌──────────────┐
       │   Nornir     │
       │  (MISSING)   │
       └──────────────┘
              │
              ↓
       ┌──────────────────────┐
       │ network-snapshot     │
       │ Skill (SKILL.md)     │
       │ - Agent defined ✅   │
       │ - Code implemented?  │  ← Check this!
       └──────────────────────┘
              │
              ↓
       ┌──────────────────────┐
       │   olav.duckdb        │
       │ (Empty - no ingestion)
       └──────────────────────┘

════════════════════════════════════════════════════════════════════

╔═════════════════════════════════════════╗
║  FOR TESTING: Test Data Generation      ║  ← Current state
║  (scripts/generate_e2e_test_data.py)    ║
╚═════════════╤═══════════════════════════╝
              │
              │ Creates: devices, interfaces,
              │ stats, relationships, routes
              ↓
       ┌──────────────────────┐
       │ test_network.duckdb  │
       │ ✅ Fully populated   │
       │ (80 devices, 1.2k IF)│
       └──────────────────────┘

════════════════════════════════════════════════════════════════════

╔═════════════════════════════════════════╗
║     Agent Query Execution               ║
║     (CURRENT PROBLEM)                   ║
╚═════════════╤═══════════════════════════╝
              │
              ↓
       orchestrate_query()
              ↓
       network-query Skill
              ↓
       query_database() tool
              ↓
       data_gateway.query_main()
              ↓
       ┌──────────────────────┐
       │ UNIFIED_DB         ← │─ HARDCODED to olav.duckdb
       │ = olav.duckdb        │
       │ (Empty!)             │
       └──────────────────────┘
              │
              ↓
       Result: 0 rows  ❌

════════════════════════════════════════════════════════════════════
```

---

## 为什么这个设计存在

### Phase 历史

**v0.10.0-0.10.1**: "Zero-ETL" Architecture
- **目标**: 最小化bootstrap，外部数据源主导
- **假设**: 生产环境有数据导入服务
- **优点**: 灵活，支持多源数据
- **缺点**: 本地开发环境缺少数据

**决策**:
```
UNIFIED_DB = olav.duckdb  # 所有数据到一个数据库
  ↓
但 Zero-ETL 意味着:
  - 最小化初始化 ✅ (implemented)
  - 期望外部数据源 ❌ (missing in dev)
  - 不包含测试数据 ❌ (test data in separate DB)
```

### Design Constraints
```
✅ Production:
   - Real network devices via Nornir
   - Data pushed to olav.duckdb
   - Agent queries olav.duckdb
   - ✅ Works

❌ Development:
   - No real network devices
   - Test data in test_network.duckdb
   - Agent hardcoded to olav.duckdb
   - ❌ Agent sees empty database
```

---

## 当前状态总结

| Component | Status | 原因 |
|-----------|--------|------|
| **test_network.duckdb Data** | ✅ Complete | scripts/generate_e2e_test_data.py generates it |
| **olav.duckdb Data** | ❌ Empty | No ETL pipeline in dev environment |
| **Network Snapshot Skill** | ✅ Defined | SKILL.md exists |
| **Nornir Connection** | ❌ Missing | No device targets configured |
| **Data Ingestion** | ❌ Missing | No active import pipeline |
| **Query Routing** | ❌ Wrong DB | Hardcoded to olav.duckdb (empty) |

---

## 解决方案 (Phase 4 Planning)

### Option A: 重定向Agent到Test Database (快速)
**成本**: 2 hours  
**风险**: 破坏生产架构设计  
**不推荐**: 违反模块化原则

```python
# ❌ DON'T DO THIS:
# Make query_database() use test_network.duckdb

QUERY_DB = DB_DIR / "test_network.duckdb"  # 不对

# Why bad:
# - Breaks production design
# - Mixes test & prod
# - Can't scale
```

### Option B: 导入Test数据到Production DB (推荐)
**成本**: 4-6 hours  
**益处**: 保持架构纯净，全功能测试  
**推荐**: ✅

```python
# scripts/import_test_data.py (NEW)
def import_test_data_to_production():
    """
    Import all data from test_network.duckdb to olav.duckdb
    
    Usage:
        uv run python scripts/import_test_data.py --source test_network.duckdb --target olav.duckdb
    """
    
    # Copy schema + data:
    # - devices (80)
    # - interfaces (1200)
    # - interface_stats (106K)
    # - link_relationships (edges)
    # - bgp_routes (if implemented)
    
    # Verify integrity
    # - Foreign key constraints
    # - Timestamp consistency
    
    # Update metadata
    # - sync_metadata (mark as test data)
    # - device_capabilities (auto-discover)

# Enable:
# 1. Normal agent query → olav.duckdb ✅
# 2. Complete test data ✅
# 3. No hardcoding changes ✅
# 4. Production-ready architecture ✅
```

### Option C: Real Nornir Integration (长期)
**成本**: 2-3 weeks  
**益处**: 实现原设计意图  
**时间线**: Phase 5+

```
1. Configure Nornir devices
   ├─ hosts.yaml: Real/simulated device targets
   ├─ groups.yaml: Device group definitions
   └─ defaults.yaml: SSH credentials

2. Implement network-snapshot execution
   ├─ Parse command outputs
   ├─ Store to olav.duckdb
   └─ Verify data integrity

3. Enable agent to use real data
   ├─ Query Agent ✅
   ├─ Network Snapshot ✅
   └─ Production pipeline ✅
```

---

## 下一步计划

### Phase 4: Data Integration (Recommended)

**Task 1**: Create Import Script
```python
# .olav/scripts/import_test_data.py
- Copy test_network.duckdb → olav.duckdb
- Verify schema compatibility
- Validate foreign keys
- Mark as test data in metadata
```

**Task 2**: Update Documentation
- Update user guide: explain two databases
- Add data management section to architecture
- Document zero-ETL design rationale

**Task 3**: Run Full Test Suite
- L1: 20 tests with imported data
- L2: 15 tests with full dataset
- L3: 45 tests with complete network

**Expected Result**:
- L1: 9/9 (100%) ✅
- L2: 15/15 (100%) ✅
- L3: 36+/45 (80%+) ✅

---

## 关键要点

### ✅ 做对了
1. **分离 test & prod**: test_network.duckdb 隔离
2. **Zero-ETL 设计**: 最小化 bootstrap
3. **统一数据库**: UNIFIED_DB 架构清晰
4. **Skill定义**: network-snapshot 架构存在

### ❌ 当前的问题
1. **Dev环境缺数据**: 没有Nornir设备
2. **数据隔离**: Test数据未导入生产DB
3. **架构与环境不匹配**: 生产设计在dev中无法工作

### 🔧 立即修复
1. **Option B**: 创建导入脚本（推荐）- 4-6小时
2. 或 **Option A**: 临时重定向（不推荐）- 2小时，但破坏设计
3. **长期**: Option C→实现真实Nornir集成

---

## 验证检查清单

- [ ] 确认 test_network.duckdb 由 scripts/generate_e2e_test_data.py 生成
- [ ] 确认 olav.duckdb 是 Zero-ETL (空bootstrap)
- [ ] 确认 network-snapshot Skill 定义存在
- [ ] 确认 Nornir 在dev中无设备连接
- [ ] 确认 data_gateway 硬编码到 UNIFIED_DB/olav.duckdb
- [ ] 决定使用 Option B (推荐) 或其他方案
- [ ] 计划 Phase 4 import_test_data.py 实现

---

**文档完成**: 2026-02-09  
**下一步**: Phase 4 Implementation Planning
