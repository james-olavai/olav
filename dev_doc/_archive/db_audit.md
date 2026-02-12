# OLAV 数据库审计报告 v0.10.1

**生成时间**: 2026-02-06  
**审计人**: 自动审计工具  
**项目版本**: OLAV v0.10.1 (单一数据库架构)

---

## 📊 数据库总览

OLAV 项目采用 **单一数据库架构**（v0.10.1）：

| 分类 | 数据库 | 位置 | 类型 | 用途 |
|------|--------|------|------|------|
| **主数据库** | `olav.duckdb` | `.olav/db/` | DuckDB | 所有核心数据（设备、拓扑、审计、知识） |
| **LLM 缓存** | `olav_cache.db` | `.olav/cache/` | SQLite | LLM 调用结果缓存 + Guard 安全规则 |
| **用户缓存** | `cache_<user>.duckdb` | `~/.olav/` | DuckDB | 语义缓存（用户隔离） |
| **Raw 数据** | `exports/snapshots/{date}/` | 文件系统 | 纯文本 | CLI 原始输出（**不入库**） |

**核心变化 (v0.10.1)**:
- ✅ 合并 4 个 DuckDB 文件 → 1 个统一库（`olav.duckdb`）
- ✅ **Raw 数据仅保存在文件系统，不写入数据库**
- ✅ 保留 SQLite 缓存，支持 TTL 管理（`cache.llm_cache_ttl_hours`，默认 0 = 无限期）
- ✅ 简化并发控制，单点写入

---

## 🔍 单一数据库详解

### 1️⃣ `olav.duckdb` — 统一核心数据库

**位置**: `.olav/db/olav.duckdb`  
**访问模式**: 读写  
**用途**: 所有核心数据存储（设备、拓扑、审计、知识）

#### 表结构

**表1**: `devices` — 设备元数据  
存储网络设备的静态信息（从旧 `main.duckdb` 迁移）

```
device_id        VARCHAR   ✓ 主键（设备唯一标识符）
hostname         VARCHAR   ✓ 设备主机名
ip_address       VARCHAR   ✓ 管理 IP 地址
device_type      VARCHAR   可选 （Router/Switch/Firewall）
vendor           VARCHAR   可选 （Cisco/Juniper/Arista）
model            VARCHAR   可选 （ASR1002/EX4200）
ios_version      VARCHAR   可选 （15.6(3)M）
serial_number    VARCHAR   可选 （SN12345）
device_role      VARCHAR   可选 （Core/Distribution/Access）
site             VARCHAR   可选 （Beijing/Shanghai）
created_at       TIMESTAMP 可选 （创建时间）
last_updated     TIMESTAMP 可选 （更新时间）
is_active        BOOLEAN   可选 （是否活跃）
```

**使用场景**:
- ✅ 设备清单查询
- ✅ 单个设备详情获取
- ✅ 批量设备导出（CSV）

---

**表2**: `audit_logs` — 命令执行审计  
记录所有 CLI 命令执行历史（从旧 `olav.duckdb` 合并）

```
id               INTEGER   ✓ 自增主键
timestamp        TIMESTAMP 可选 执行时间
thread_id        VARCHAR   ✓ 线程 ID
device           VARCHAR   ✓ 设备名称
command          VARCHAR   ✓ 执行命令
output           VARCHAR   可选 命令输出
success          BOOLEAN   ✓ 执行结果（成功/失败）
duration_ms      INTEGER   可选 执行耗时（毫秒）
user             VARCHAR   可选 执行用户
```

**使用场景**:
- 🔐 命令执行审计 trail
- 📊 性能监控（耗时分析）
- ⚠️ 故障排查（查找失败命令）
- 📈 并发执行统计

---

**表3**: `device_capabilities` — 设备驱动缓存

```
hostname         VARCHAR   ✓ 主键（设备主机名）
preferred_driver VARCHAR   可选 首选驱动（platinum/gold）
last_success     TIMESTAMP 可选 最后成功时间
features         JSON      可选 支持的特性列表
```

**使用场景**:
- 🔍 驱动选择缓存（避免重复探测）
- 📋 设备能力快速查询
- ⚡ 设备连接最优化

---

**表4**: `topology_links` — 网络拓扑关系（L1/L3）

```
id               INTEGER   ✓ 自增主键
local_device     VARCHAR   ✓ 源设备名
local_port       VARCHAR   可选 源端口（如 Gig1）
remote_device    VARCHAR   ✓ 目标设备名
remote_port      VARCHAR   可选 目标端口
layer            VARCHAR   ✓ 'L1' (LLDP/CDP) 或 'L3' (BGP)
protocol         VARCHAR   可选 'lldp', 'cdp', 'bgp'
metadata         JSON      可选 其他信息
discovered_at    TIMESTAMP 可选 发现时间
```

**使用场景**:
- 🔗 网络拓扑查询
- 📊 链路变化跟踪
- 🔍 根因分析（设备间路径）

---

**表5**: `sync_metadata` — 同步历史记录  
记录每次快照同步的元数据

```
id               INTEGER   ✓ 自增主键
sync_date        DATE      ✓ 同步日期
sync_dir         VARCHAR   ✓ 同步目录
device_count     INTEGER   可选 设备数
command_count    INTEGER   可选 命令数
success_count    INTEGER   可选 成功数
failed_count     INTEGER   可选 失败数
duration_seconds FLOAT     可选 耗时
created_at       TIMESTAMP 可选 创建时间
```

**使用场景**:
- 📊 同步历史记录
- 📈 性能分析
- ⚠️ 故障趋势

---

**表6**: `knowledge_sources` — 知识库源

```
id               INTEGER   ✓ 自增主键
name             VARCHAR   ✓ 源名称
type             VARCHAR   ✓ 类型（protocol/solution/guide）
base_path        VARCHAR   可选 文件路径
version          VARCHAR   可选 版本
platform         VARCHAR   可选 平台（cisco_ios/junos）
indexed_at       TIMESTAMP 可选 索引时间
```

**使用场景**:
- 📚 知识库源追踪
- 🔄 版本管理
- 📊 索引元数据

---

**表7**: `knowledge_chunks` — 知识碎片  
支持 RAG（检索增强生成）

```
id               INTEGER   ✓ 自增主键
source_id        INTEGER   可选 源 ID（外键）
file_path        VARCHAR   ✓ 文件路径
chunk_index      INTEGER   ✓ 碎片顺序
title            VARCHAR   可选 标题
content          VARCHAR   ✓ 内容
platform         VARCHAR   可选 平台
doc_type         VARCHAR   可选 文档类型
keywords         VARCHAR[] 可选 关键词数组
file_hash        VARCHAR   ✓ 文件哈希（去重）
created_at       TIMESTAMP 可选 创建时间
```

**使用场景**:
- 🔍 知识库全文搜索
- 📚 RAG（检索增强生成）
- 🔄 重复检测（file_hash）

---

**表8**: `query_cache` — 查询结果缓存（可选）

```
cache_key        VARCHAR   ✓ 主键（查询哈希）
result_json      VARCHAR   ✓ 查询结果 JSON
created_at       TIMESTAMP 可选 创建时间
ttl_seconds      INTEGER   可选 生存期（秒）
metadata_json    VARCHAR   可选 元数据
hit_count        INTEGER   可选 命中次数
last_accessed    TIMESTAMP 可选 最后访问时间
```

**使用场景**:
- ⚡ SQL 查询结果缓存（加速重复查询）
- 📊 接口/路由/邻居数据缓存

---

**锁定机制**: ✅ DuckDB MVCC
- 多个读操作可并发执行
- 写操作自动排队
- WAL 模式已启用，改善并发性能

---

### 2️⃣ Raw 数据 — 文件系统存储（不入库）

**位置**: `exports/snapshots/{YYYY-MM-DD}/raw/{device}/`  
**格式**: 纯文本 `.txt` 文件  
**变化 (v0.10.1)**: **Raw 数据仅保存在文件系统，不写入数据库**

```
exports/snapshots/2026-02-06/
├── raw/
│   ├── R1/
│   │   ├── show-version.txt
│   │   ├── show-ip-route.txt
│   │   └── show-cdp-neighbors.txt
│   └── R2/
│       ├── show-version.txt
│       └── ...
└── latest -> 2026-02-06
```

**数据流**:
```
设备 (Nornir) → Netmiko/Scrapli 执行 CLI
  → 原始输出 (.txt 纯文本)
  → 保存到 exports/snapshots/{date}/raw/{device}/*.txt
  ❌ 不入数据库（v0.10.1 变化）
```

**好处**:
- ✅ 节省数据库空间（~11M → ~1M）
- ✅ 快速 grep/查找
- ✅ 灵活的离线分析
- ✅ 简化并发控制（无数据库锁竞争）

**解析流程**（可选）:
- Raw 文件可手动通过 TextFSM 解析 → JSON
- 解析结果可选择性地保存到外部数据库（不在核心设计中）

---

### 3️⃣ `olav_cache.db` — LLM 调用缓存 + Guard（SQLite）

**位置**: `.olav/cache/olav_cache.db`  
**类型**: SQLite（不是 DuckDB）  
**用途**: LLM 调用结果缓存 + Guard 安全规则

#### 表结构

**表1**: `llm_cache` — LangChain 自动管理
- LLM 调用请求 hash → 响应缓存
- 自动清理垃圾

**表2**: `guard_blacklist` — 静态安全黑名单
```
keyword          TEXT      ✓ 主键（危险关键词）
reason           TEXT      可选 拒绝原因
severity         TEXT      默认 'high' （critical/high/medium）
created_at       TIMESTAMP 默认 当前时间
```

**预设黑名单关键词**:
- `drop table` — SQL 注入
- `delete from` — 数据销毁
- `truncate` — 表清空
- `rm -rf` — 危险 shell 命令
- `shutdown` — 系统关闭

**表3**: `guard_rejected` — 动态拒绝缓存
```
query_hash       TEXT      ✓ 主键（查询哈希）
query_text       TEXT      可选 原始查询
reject_reason    TEXT      可选 拒绝原因
hit_count        INTEGER   默认 1 （触发次数）
created_at       TIMESTAMP 默认 当前时间
last_hit         TIMESTAMP 默认 当前时间
```

**表4**: `intent_cache` — 意图缓存
```
query_hash       TEXT      ✓ 主键（查询哈希）
query_text       TEXT      可选 原始查询
result           JSON      可选 缓存结果
hit_count        INTEGER   默认 0 （命中次数）
created_at       TIMESTAMP 默认 当前时间
```

#### 缓存 TTL 管理 (v0.10.1)

**配置** (`.olav/settings.json`):
```json
{
  "cache": {
    "llmCacheTtlHours": 0,                // 0 = 无限期保留(默认)
    "queryCacheTtlHours": 24,              // 24 小时后过期
    "cacheCleanupEnabled": true,
    "cacheCleanupIntervalHours": 24        // 每天清理一次
  }
}
```

**环境变量覆盖**:
```bash
export LLM_CACHE_TTL_HOURS=0              # 0 = 无限期
export QUERY_CACHE_TTL_HOURS=24           # 24 小时后过期
export CACHE_CLEANUP_INTERVAL_HOURS=24    # 每天清理一次
```

**自动清理** (v0.10.1):
- 启用 `cache_cleanup_enabled: true` 后，后台线程定期清理过期数据
- 删除 `created_at < NOW() - {ttl_hours}`

---

### 4️⃣ `cache_<username>.duckdb` — 用户语义缓存（DuckDB）

**位置**: `~/.olav/cache_<username>.duckdb`  
**访问模式**: 读写（用户隔离）  
**用途**: 每用户独立的查询语义缓存

**使用模式**:
```
用户 alice 使用 ~/.olav/cache_alice.duckdb
用户 bob 使用 ~/.olav/cache_bob.duckdb
```

**锁定机制**: ✅ 完全隔离
- 不同用户之间零竞争
- 同一用户内遵循 MVCC

---

## 🔒 并发控制模型

### DuckDB MVCC（Multi-Version Concurrency Control）

**特点**:
- ✅ 多读并发（多个 SELECT 同时执行）
- ✅ 读写不阻塞（MVCC 版本控制）
- ⚠️ 写互斥（同时只有一个 INSERT/UPDATE）
- ✅ WAL 模式已启用

**优化建议**:
```python
# 1. 使用连接池避免频繁重连
from olav.core.database import get_pooled_database
db = get_pooled_database()

# 2. 批量插入而不是逐行
INSERT INTO table VALUES (...), (...), (...)  # 快
# 而不是
for row in rows:
    INSERT INTO table VALUES (...)  # 慢

# 3. 使用 INSERT OR REPLACE 处理冲突
INSERT INTO table (...) VALUES (...)
ON CONFLICT (device, command, sync_date) 
DO UPDATE SET output = EXCLUDED.output

# 4. 定期 VACUUM 清理垃圾版本
VACUUM ANALYZE;
```

### SQLite 文件级锁定

**特点**:
- ⚠️ 读多个进程可并发，但有锁争用
- ⚠️ 高并发写入可能产生 `SQLITE_BUSY` 错误
- ✅ WAL 模式已启用，改善并发

**优化建议**:
```python
# 1. 启用 WAL 模式（已配置）
conn.execute("PRAGMA journal_mode = WAL")

# 2. 配置忙碌超时
conn.execute("PRAGMA busy_timeout = 3000")  # 3 秒

# 3. 减少事务持续时间
# ✅ 好
conn.execute("BEGIN")
conn.execute("INSERT INTO guard_blacklist (...)")
conn.execute("COMMIT")

# ❌ 坏（长事务锁住缓存表）
conn.execute("BEGIN")
result = expensive_operation()  # 耗时操作
conn.execute("INSERT INTO ...")
conn.execute("COMMIT")
```

---

## 📈 数据库大小与增长

| 数据库 | 大小 | 增长率 | 清理策略 |
|--------|------|--------|---------|
| `olav.duckdb` | ~12M | 高（CLI 输出日增） | 按 `sync_date` 归档 |
| `olav_cache.db` | 未量化 | 中（LLM 缓存） | TTL 自清理 |
| 用户缓存 | 每用户 ~100K | 低 | 用户隔离，无竞争 |
| Raw 文件 | ~50M 典型 | 高（日每设备 50-100MB） | 按日期保留策略 |

---

## 🚀 最佳实践

### 1. 并发写入避免争用

```python
# ✅ 推荐：异步批量插入
async def batch_insert_audit_logs(logs: List[Dict]):
    conn = get_database()
    conn.executemany(
        "INSERT INTO audit_logs (...) VALUES (...)",
        [log.values() for log in logs]
    )

# ❌ 避免：同步逐行插入
for log in logs:
    conn.execute("INSERT INTO audit_logs (...) VALUES (...)")
```

### 2. 缓存 TTL 管理

```python
# ✅ 配置默认值
settings.cache.llm_cache_ttl_hours = 0  # 无限期

# ✅ 自动清理过期数据
DELETE FROM guard_rejected 
WHERE created_at < NOW() - INTERVAL {ttl_hours} HOUR;

# ❌ 避免：缓存无限增长
```

### 3. 定期维护

```bash
# 每周清理 MVCC 版本
uv run python3 -c "
import duckdb
conn = duckdb.connect('.olav/db/olav.duckdb')
conn.execute('VACUUM ANALYZE')
"

# 监控文件大小
du -sh .olav/db/olav.duckdb

# 每月清理旧快照数据
# DELETE FROM * WHERE sync_date < DATE_ADD(CURRENT_DATE, INTERVAL -90 DAY)
```

---

## 🔬 深度分析：数据流架构

### Stage 1: 数据收集

```
Nornir + Netmiko/Scrapli
  ↓
执行 CLI 命令（show version, show ip route, ...）
  ↓
原始输出（纯文本，~1-10KB 每条命令）
  ↓
保存到 exports/snapshots/{YYYY-MM-DD}/raw/{device}/*.txt
  ✓ 不入数据库（v0.10.1）
```

### Stage 2: 可选解析

```
Raw 文件 (.txt)
  ↓
NTC Templates (TextFSM) 自动解析（如果有模板）
  ↓
结构化 JSON（如 show version → {os, version, bootloader, ...}）
  ↓
手动导入到拓扑表（需有人维护脚本）
  ✗ 当前未自动化
```

### Stage 3: 索引与缓存

```
知识库 (.olav/knowledge/)
  ↓
向量化 + 嵌入
  ↓
保存到 knowledge_chunks 表（支持 RAG 搜索）
```

---

## 📊 决策矩阵

| 方案 | 开发成本 | 运维复杂度 | 性能 | 推荐 |
|------|---------|----------|------|------|
| **v0.10.1（当前）** 单 DB + SQLite 缓存 | 低 | 低 | 中 | ✅ **生产推荐** |
| 多 DB（旧架构） | 0 | 中 | 低 | ❌ 已废弃 |
| Parquet + Iceberg | 高 | 高 | 很高 | 未来大数据 |

**当前方案优势**:
- ✅ 并发控制简单（单级锁）
- ✅ 操作复杂度低（一个数据库）
- ✅ Raw 数据不膨胀 DB 文件
- ✅ 支持 TTL 对缓存自动过期
- ✅ 用户隔离避免锁争用

---

## 🔧 调试命令

### 检查表结构
```bash
uv run python3 << 'EOF'
import duckdb
conn = duckdb.connect('.olav/db/olav.duckdb', read_only=True)
result = conn.execute("DESCRIBE devices").fetchall()
for col in result:
    print(f"{col[0]:<20} {col[1]:<15}")
EOF
```

### 查看表大小
```bash
uv run python3 << 'EOF'
import duckdb
conn = duckdb.connect('.olav/db/olav.duckdb', read_only=True)
result = conn.execute("""
    SELECT table_name, COUNT(*) as row_count
    FROM information_schema.tables t
    CROSS JOIN (
        SELECT table_schema, table_name
    ) WHERE table_schema = 'main'
""").fetchall()
for table, count in result:
    print(f"{table}: {count:,} rows")
EOF
```

### 查看缓存状态
```bash
uv run python3 << 'EOF'
import sqlite3
conn = sqlite3.connect('.olav/cache/olav_cache.db')
result = conn.execute("""
    SELECT 'llm_cache' as table_name, COUNT(*) as count 
    FROM llm_cache
    UNION ALL
    SELECT 'guard_blacklist', COUNT(*) FROM guard_blacklist
    UNION ALL
    SELECT 'guard_rejected', COUNT(*) FROM guard_rejected
""").fetchall()
for table, count in result:
    print(f"{table}: {count:,} rows")
EOF
```

---

## 📝 结论

### 现状
✅ **优秀设计**:
- 单一 DuckDB 统一存储
- SQLite 缓存与主库分离
- 用户级别隔离缓存
- Raw 数据文件系统存储，减少 DB 膨胀
- TTL 支持对缓存自动过期

⚠️ **需要改进**:
- Topology 自动构建脚本（从 raw 数据提取 CLI 输出到 topology_links）
- 定期 VACUUM 清理 MVCC 版本
- Raw 数据保留策略（多久归档）

### 后续行动

1. **立即**: 实施 raw_importer.py 停止写入数据库（改为文件系统只读）✅
2. **短期**: 添加自动 Topology 发现脚本（CDP/LLDP → topology_links）
3. **中期**: 实现后台 TTL 清理器
4. **长期**: 如果数据超过 1GB，考虑分片策略

---

**报告版本**: v0.10.1  
**下次审计**: 2026-04-06
