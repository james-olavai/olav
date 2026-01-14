# OLAV Database Federation Design

**设计日期**: 2026-01-14  
**版本**: v0.8.4 Development Plan  
**目标**: 完善数据库设计，实现三库联合查询，提升宏观分析能力  
**状态**: 🟢 准备开发

---

## 0. 开发准备度评估 ✅

### 0.1 当前系统状态 (2026-01-14)

| 组件 | 状态 | 详情 |
|------|------|------|
| **数据库基础设施** | ✅ 就绪 | 3个 DuckDB 文件正常运行 |
| **快照采集 (Stage 1)** | ✅ 正常 | 108 条命令，6 设备 × 18 命令 |
| **解析处理 (Stage 2)** | ✅ 正常 | 112 个 Parsed JSON 文件 |
| **拓扑数据** | ✅ 完整 | 6 设备，22 链路 |
| **CLI 工具** | ✅ 正常 | `olav snapshot`, `olav query` |

### 0.2 可用的 Parsed 数据源

```
exports/snapshots/2026-01-14/parsed/
├── R1/
│   ├── show-ip-route.json         → routes 表
│   ├── show-arp.json              → arp_table 表
│   ├── show-interface*.json       → interfaces 表
│   ├── show-ip-bgp-summary.json   → bgp_neighbors 表
│   ├── show-ip-ospf-neighbor.json → ospf_neighbors 表
│   ├── show-vlan.json             → vlans 表
│   ├── show-spanning-tree.json    → stp_status 表
│   └── ...
├── R2/
└── ...
```

### 0.3 阻塞问题

| 问题 | 状态 | 影响 |
|------|------|------|
| 结构化数据表未创建 | ❌ 待开发 | Phase 1 主要任务 |
| JSON→Table 导入逻辑 | ❌ 待开发 | Phase 1 主要任务 |
| 联邦查询层 | ❌ 待开发 | Phase 2 任务 |

---

## 1. 开发计划总览

### 1.1 时间线

```
Week 1 (Jan 14-17)
├── Day 1: Phase 1.1 - 表结构设计与创建 ✨
├── Day 2: Phase 1.2 - 数据导入逻辑实现
├── Day 3: Phase 1.3 - Stage 2 集成与测试
└── Day 4: Phase 2.1 - 联邦查询层实现

Week 2 (Jan 20-22)
├── Day 5: Phase 2.2 - SQL 查询工具
├── Day 6: Phase 3.1 - 宏观分析引擎
└── Day 7: Phase 3.2 - 健康评分系统

Week 3 (Jan 23-24)
├── Day 8: Phase 4.1 - 知识库关联
└── Day 9: Phase 4.2 - 测试与文档
```

### 1.2 交付物清单

| Phase | 交付物 | 文件路径 |
|-------|-------|---------|
| 1.1 | 结构化表定义 | `src/olav/core/database.py` |
| 1.2 | 数据导入器 | `src/olav/tools/data_importer.py` |
| 1.3 | Stage 2 集成 | `src/olav/tools/sync_tools.py` |
| 2.1 | 联邦查询层 | `src/olav/core/unified_database.py` |
| 2.2 | SQL 查询工具 | `src/olav/tools/query_tools.py` |
| 3.1 | 宏观分析引擎 | `src/olav/analysis/macro_analyzer.py` |
| 3.2 | 健康评分系统 | `src/olav/analysis/health_score.py` |
| 4.1 | 知识关联 | `src/olav/analysis/knowledge_correlator.py` |

---

## 2. Phase 1: 结构化数据表 (3天)

#### 1.1 新增表设计 (network_snapshot.duckdb)

```sql
-- =============================================================================
-- 接口表: 存储解析后的接口状态
-- =============================================================================
CREATE TABLE interfaces (
    id INTEGER PRIMARY KEY,
    snapshot_date DATE NOT NULL,           -- 快照日期
    device_name VARCHAR NOT NULL,          -- 设备名
    interface_name VARCHAR NOT NULL,       -- 接口名
    ip_address VARCHAR,                    -- IP地址
    subnet_mask VARCHAR,                   -- 子网掩码
    admin_status VARCHAR,                  -- 管理状态 (up/down)
    oper_status VARCHAR,                   -- 操作状态 (up/down)
    protocol_status VARCHAR,               -- 协议状态
    description VARCHAR,                   -- 接口描述
    mtu INTEGER,                           -- MTU
    speed VARCHAR,                         -- 速率
    duplex VARCHAR,                        -- 双工模式
    input_errors INTEGER DEFAULT 0,        -- 输入错误
    output_errors INTEGER DEFAULT 0,       -- 输出错误
    crc_errors INTEGER DEFAULT 0,          -- CRC错误
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snapshot_date, device_name, interface_name)
);

CREATE INDEX idx_interfaces_ip ON interfaces(ip_address);
CREATE INDEX idx_interfaces_device ON interfaces(device_name);
CREATE INDEX idx_interfaces_status ON interfaces(oper_status);

-- =============================================================================
-- 路由表: 存储路由信息
-- =============================================================================
CREATE TABLE routes (
    id INTEGER PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    device_name VARCHAR NOT NULL,
    network VARCHAR NOT NULL,              -- 目标网络
    mask VARCHAR,                          -- 掩码
    next_hop VARCHAR,                      -- 下一跳
    interface VARCHAR,                     -- 出接口
    protocol VARCHAR,                      -- 路由协议 (C/S/O/B/R)
    metric INTEGER,                        -- 度量值
    admin_distance INTEGER,                -- 管理距离
    age VARCHAR,                           -- 路由年龄
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snapshot_date, device_name, network, next_hop)
);

CREATE INDEX idx_routes_network ON routes(network);
CREATE INDEX idx_routes_protocol ON routes(protocol);

-- =============================================================================
-- BGP邻居表: 存储BGP会话信息
-- =============================================================================
CREATE TABLE bgp_neighbors (
    id INTEGER PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    device_name VARCHAR NOT NULL,
    neighbor_ip VARCHAR NOT NULL,          -- 邻居IP
    remote_as INTEGER,                     -- 远端AS号
    local_as INTEGER,                      -- 本地AS号
    state VARCHAR,                         -- 状态 (Established/Idle/Active)
    uptime VARCHAR,                        -- 会话时长
    prefixes_received INTEGER DEFAULT 0,   -- 收到的前缀数
    prefixes_sent INTEGER DEFAULT 0,       -- 发送的前缀数
    state_changes INTEGER DEFAULT 0,       -- 状态变化次数
    last_error VARCHAR,                    -- 最后错误
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snapshot_date, device_name, neighbor_ip)
);

CREATE INDEX idx_bgp_neighbor_ip ON bgp_neighbors(neighbor_ip);
CREATE INDEX idx_bgp_state ON bgp_neighbors(state);

-- =============================================================================
-- OSPF邻居表
-- =============================================================================
CREATE TABLE ospf_neighbors (
    id INTEGER PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    device_name VARCHAR NOT NULL,
    neighbor_id VARCHAR NOT NULL,          -- 邻居Router ID
    neighbor_ip VARCHAR,                   -- 邻居IP
    interface VARCHAR,                     -- 接口
    area VARCHAR,                          -- 区域
    state VARCHAR,                         -- 状态 (FULL/2WAY/DOWN)
    priority INTEGER,                      -- 优先级
    dr_status VARCHAR,                     -- DR/BDR/DROTHER
    uptime VARCHAR,
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snapshot_date, device_name, neighbor_id, interface)
);

-- =============================================================================
-- VLAN表
-- =============================================================================
CREATE TABLE vlans (
    id INTEGER PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    device_name VARCHAR NOT NULL,
    vlan_id INTEGER NOT NULL,
    vlan_name VARCHAR,
    status VARCHAR,                        -- active/act/lshut/suspended
    ports TEXT,                            -- 端口列表 (JSON array)
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snapshot_date, device_name, vlan_id)
);

-- =============================================================================
-- 系统信息表
-- =============================================================================
CREATE TABLE system_info (
    id INTEGER PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    device_name VARCHAR NOT NULL,
    hostname VARCHAR,
    platform VARCHAR,                      -- 平台型号
    software_version VARCHAR,              -- 软件版本
    serial_number VARCHAR,                 -- 序列号
    uptime VARCHAR,                        -- 运行时间
    cpu_usage FLOAT,                       -- CPU使用率
    memory_usage FLOAT,                    -- 内存使用率
    config_register VARCHAR,
    last_reload_reason VARCHAR,
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snapshot_date, device_name)
);

-- =============================================================================
-- 历史健康评分表 (用于趋势分析)
-- =============================================================================
CREATE TABLE health_scores (
    id INTEGER PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    layer VARCHAR NOT NULL,                -- L1/L2/L3/L4/Overall
    score INTEGER NOT NULL,                -- 0-100
    ok_count INTEGER DEFAULT 0,
    warning_count INTEGER DEFAULT 0,
    critical_count INTEGER DEFAULT 0,
    details TEXT,                          -- JSON详情
    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snapshot_date, layer)
);
```

#### 1.2 实现路径

```python
# src/olav/tools/sync_tools.py - 修改 _process_sync_stage2()

def _write_parsed_data_to_db(sync_dir: Path, sync_date: str) -> None:
    """将解析后的数据写入DuckDB."""
    import duckdb
    from config.paths import NETWORK_SNAPSHOT_PATH
    
    conn = duckdb.connect(str(NETWORK_SNAPSHOT_PATH))
    
    # 确保表存在
    _ensure_parsed_tables_exist(conn)
    
    # 遍历parsed目录，写入数据
    parsed_dir = sync_dir / "parsed"
    for device_dir in parsed_dir.iterdir():
        if not device_dir.is_dir():
            continue
        
        device_name = device_dir.name
        
        # 写入接口数据
        interfaces_file = device_dir / "show_ip_interface_brief.json"
        if interfaces_file.exists():
            _insert_interfaces(conn, sync_date, device_name, interfaces_file)
        
        # 写入路由数据
        routes_file = device_dir / "show_ip_route.json"
        if routes_file.exists():
            _insert_routes(conn, sync_date, device_name, routes_file)
        
        # 写入BGP数据
        bgp_file = device_dir / "show_ip_bgp_summary.json"
        if bgp_file.exists():
            _insert_bgp_neighbors(conn, sync_date, device_name, bgp_file)
    
    conn.commit()
    conn.close()
```

---

### Phase 2: 联合查询架构 (1天)

#### 2.1 DuckDB ATTACH机制

DuckDB支持ATTACH多个数据库文件，实现跨库查询：

```python
# src/olav/core/unified_database.py

class UnifiedDatabase:
    """统一数据库访问层 - 支持三库联合查询."""
    
    def __init__(self):
        import duckdb
        from config.paths import (
            NETWORK_SNAPSHOT_PATH,
            NETWORK_COMMANDS_PATH, 
            KNOWLEDGE_PATH,
        )
        
        # 创建内存连接作为主连接
        self.conn = duckdb.connect(":memory:")
        
        # ATTACH三个数据库
        self.conn.execute(f"ATTACH '{NETWORK_SNAPSHOT_PATH}' AS snapshot")
        self.conn.execute(f"ATTACH '{NETWORK_COMMANDS_PATH}' AS commands")
        self.conn.execute(f"ATTACH '{KNOWLEDGE_PATH}' AS knowledge")
    
    def query(self, sql: str) -> list:
        """执行跨库查询."""
        return self.conn.execute(sql).fetchall()
    
    def close(self):
        self.conn.close()
```

#### 2.2 联合查询示例

```sql
-- 示例1: 查找设备接口问题 + 匹配知识库解决方案
SELECT 
    i.device_name,
    i.interface_name,
    i.oper_status,
    i.input_errors,
    k.content as solution
FROM snapshot.interfaces i
LEFT JOIN knowledge.documents k 
    ON k.content LIKE '%interface down%' 
    OR k.content LIKE '%CRC error%'
WHERE i.oper_status = 'down' 
   OR i.input_errors > 100;

-- 示例2: 检查命令是否在白名单中 + 执行审计
SELECT 
    a.device,
    a.command,
    a.timestamp,
    CASE WHEN c.name IS NOT NULL THEN '✅ Whitelisted' ELSE '⚠️ Not in registry' END as status
FROM commands.audit_logs a
LEFT JOIN commands.capabilities c 
    ON a.command LIKE '%' || c.name || '%'
WHERE a.timestamp > NOW() - INTERVAL 24 HOUR;

-- 示例3: 设备健康 + 拓扑 + 命令能力综合分析
SELECT 
    d.name as device,
    d.platform,
    d.mgmt_ip,
    COUNT(DISTINCT l.id) as neighbor_count,
    COUNT(DISTINCT c.id) as supported_commands,
    (SELECT COUNT(*) FROM snapshot.interfaces WHERE device_name = d.name AND oper_status = 'up') as up_interfaces
FROM snapshot.topology_devices d
LEFT JOIN snapshot.topology_links l ON d.name = l.local_device
LEFT JOIN commands.capabilities c ON c.platform = d.platform
GROUP BY d.name, d.platform, d.mgmt_ip;
```

---

### Phase 3: 宏观分析增强 (2天)

#### 3.1 分析维度设计

```
┌─────────────────────────────────────────────────────────────────────┐
│                     OLAV Macro Analysis Framework                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐    │
│  │ L1 物理层  │   │ L2 链路层  │   │ L3 网络层  │   │ L4 传输层  │    │
│  │           │   │           │   │           │   │           │    │
│  │ •接口状态  │   │ •VLAN配置  │   │ •路由一致性 │   │ •BGP状态  │    │
│  │ •错误计数  │   │ •STP状态   │   │ •OSPF邻居  │   │ •会话稳定  │    │
│  │ •光功率   │   │ •MAC表     │   │ •路由条数  │   │ •前缀数量  │    │
│  └─────┬─────┘   └─────┬─────┘   └─────┬─────┘   └─────┬─────┘    │
│        │               │               │               │          │
│        └───────────────┴───────────────┴───────────────┘          │
│                              │                                     │
│                              ▼                                     │
│                    ┌─────────────────┐                             │
│                    │  Health Score   │                             │
│                    │   Calculation   │                             │
│                    └────────┬────────┘                             │
│                             │                                      │
│              ┌──────────────┼──────────────┐                       │
│              ▼              ▼              ▼                       │
│   ┌────────────────┐ ┌────────────┐ ┌────────────────┐            │
│   │ Trend Analysis │ │ Anomaly    │ │ Knowledge      │            │
│   │ (历史对比)      │ │ Detection  │ │ Correlation    │            │
│   │                │ │ (异常检测)  │ │ (知识关联)     │            │
│   └────────────────┘ └────────────┘ └────────────────┘            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

#### 3.2 宏观分析SQL查询集

```python
# src/olav/analysis/macro_queries.py

MACRO_ANALYSIS_QUERIES = {
    # =========================================================================
    # 1. 全网健康评分
    # =========================================================================
    "network_health_summary": """
        SELECT 
            'L1' as layer,
            COUNT(*) as total_checks,
            SUM(CASE WHEN oper_status = 'up' THEN 1 ELSE 0 END) as ok_count,
            SUM(CASE WHEN oper_status = 'down' AND admin_status = 'up' THEN 1 ELSE 0 END) as critical_count,
            ROUND(100.0 * SUM(CASE WHEN oper_status = 'up' THEN 1 ELSE 0 END) / COUNT(*), 1) as health_score
        FROM snapshot.interfaces
        WHERE snapshot_date = ?
        
        UNION ALL
        
        SELECT 
            'L3' as layer,
            COUNT(*) as total_checks,
            SUM(CASE WHEN state = 'Established' THEN 1 ELSE 0 END) as ok_count,
            SUM(CASE WHEN state != 'Established' THEN 1 ELSE 0 END) as critical_count,
            ROUND(100.0 * SUM(CASE WHEN state = 'Established' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) as health_score
        FROM snapshot.bgp_neighbors
        WHERE snapshot_date = ?
    """,
    
    # =========================================================================
    # 2. 跨设备一致性检查
    # =========================================================================
    "config_consistency_check": """
        -- 检查所有设备的BGP AS号是否一致
        SELECT 
            'BGP AS Consistency' as check_type,
            COUNT(DISTINCT local_as) as distinct_values,
            CASE WHEN COUNT(DISTINCT local_as) = 1 THEN '✅ Consistent' ELSE '⚠️ Inconsistent' END as status,
            GROUP_CONCAT(DISTINCT device_name || ':' || local_as) as details
        FROM snapshot.bgp_neighbors
        WHERE snapshot_date = ?
        
        UNION ALL
        
        -- 检查OSPF区域配置
        SELECT 
            'OSPF Area Consistency' as check_type,
            COUNT(DISTINCT area) as distinct_values,
            CASE WHEN COUNT(DISTINCT area) <= 3 THEN '✅ Normal' ELSE '⚠️ Too many areas' END as status,
            GROUP_CONCAT(DISTINCT area) as details
        FROM snapshot.ospf_neighbors
        WHERE snapshot_date = ?
    """,
    
    # =========================================================================
    # 3. 异常检测
    # =========================================================================
    "anomaly_detection": """
        -- 接口错误异常
        SELECT 
            'Interface Errors' as anomaly_type,
            device_name,
            interface_name,
            input_errors + output_errors as total_errors,
            'High error count detected' as description
        FROM snapshot.interfaces
        WHERE snapshot_date = ?
          AND (input_errors > 1000 OR output_errors > 1000 OR crc_errors > 100)
        
        UNION ALL
        
        -- BGP状态异常
        SELECT 
            'BGP Session Down' as anomaly_type,
            device_name,
            neighbor_ip as interface_name,
            state_changes as total_errors,
            'BGP neighbor not established: ' || state as description
        FROM snapshot.bgp_neighbors
        WHERE snapshot_date = ?
          AND state != 'Established'
        
        UNION ALL
        
        -- 路由数量异常
        SELECT 
            'Route Count Anomaly' as anomaly_type,
            device_name,
            protocol as interface_name,
            COUNT(*) as total_errors,
            'Unusual route count for protocol' as description
        FROM snapshot.routes
        WHERE snapshot_date = ?
        GROUP BY device_name, protocol
        HAVING COUNT(*) > 1000 OR COUNT(*) < 5
    """,
    
    # =========================================================================
    # 4. 历史趋势分析
    # =========================================================================
    "health_trend": """
        SELECT 
            snapshot_date,
            layer,
            score,
            ok_count,
            warning_count,
            critical_count
        FROM snapshot.health_scores
        WHERE snapshot_date >= DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)
        ORDER BY snapshot_date, layer
    """,
    
    # =========================================================================
    # 5. 拓扑与状态关联分析
    # =========================================================================
    "topology_health_correlation": """
        SELECT 
            d.name as device,
            d.role,
            d.site,
            COUNT(DISTINCT l.id) as link_count,
            (SELECT COUNT(*) FROM snapshot.interfaces i 
             WHERE i.device_name = d.name AND i.oper_status = 'up') as up_interfaces,
            (SELECT COUNT(*) FROM snapshot.interfaces i 
             WHERE i.device_name = d.name AND i.oper_status = 'down' 
             AND i.admin_status = 'up') as problem_interfaces,
            (SELECT COUNT(*) FROM snapshot.bgp_neighbors b 
             WHERE b.device_name = d.name AND b.state = 'Established') as bgp_established,
            (SELECT COUNT(*) FROM snapshot.bgp_neighbors b 
             WHERE b.device_name = d.name AND b.state != 'Established') as bgp_down
        FROM snapshot.topology_devices d
        LEFT JOIN snapshot.topology_links l ON d.name = l.local_device
        GROUP BY d.name, d.role, d.site
        ORDER BY problem_interfaces DESC, bgp_down DESC
    """,
    
    # =========================================================================
    # 6. 知识库关联分析 (联合查询)
    # =========================================================================
    "problem_solution_correlation": """
        -- 将检测到的问题与知识库解决方案关联
        WITH detected_problems AS (
            SELECT 
                device_name,
                'interface_down' as problem_type,
                interface_name as problem_detail
            FROM snapshot.interfaces
            WHERE oper_status = 'down' AND admin_status = 'up'
            
            UNION ALL
            
            SELECT 
                device_name,
                'bgp_down' as problem_type,
                neighbor_ip as problem_detail
            FROM snapshot.bgp_neighbors
            WHERE state != 'Established'
        )
        SELECT 
            p.device_name,
            p.problem_type,
            p.problem_detail,
            k.title as related_knowledge,
            k.content as solution_hint
        FROM detected_problems p
        LEFT JOIN knowledge.documents k 
            ON k.content LIKE '%' || p.problem_type || '%'
            OR k.content LIKE '%troubleshoot%'
        LIMIT 20
    """,
}
```

#### 3.3 分析报告生成器

```python
# src/olav/analysis/macro_analyzer.py

from typing import Any
from pathlib import Path
import json
from datetime import datetime

from olav.core.unified_database import UnifiedDatabase
from olav.analysis.macro_queries import MACRO_ANALYSIS_QUERIES


class MacroAnalyzer:
    """宏观网络分析器 - 基于联合数据库查询."""
    
    def __init__(self):
        self.db = UnifiedDatabase()
    
    def generate_full_analysis(self, snapshot_date: str) -> dict[str, Any]:
        """生成完整的宏观分析报告."""
        report = {
            "generated_at": datetime.now().isoformat(),
            "snapshot_date": snapshot_date,
            "sections": {}
        }
        
        # 1. 网络健康评分
        report["sections"]["health_summary"] = self._analyze_health(snapshot_date)
        
        # 2. 配置一致性检查
        report["sections"]["consistency"] = self._check_consistency(snapshot_date)
        
        # 3. 异常检测
        report["sections"]["anomalies"] = self._detect_anomalies(snapshot_date)
        
        # 4. 历史趋势
        report["sections"]["trends"] = self._analyze_trends()
        
        # 5. 拓扑健康关联
        report["sections"]["topology_health"] = self._correlate_topology(snapshot_date)
        
        # 6. 知识库关联
        report["sections"]["knowledge_correlation"] = self._correlate_knowledge()
        
        return report
    
    def _analyze_health(self, snapshot_date: str) -> dict:
        """分析网络健康状态."""
        results = self.db.query(
            MACRO_ANALYSIS_QUERIES["network_health_summary"],
            [snapshot_date, snapshot_date]
        )
        
        layer_health = {}
        for row in results:
            layer, total, ok, critical, score = row
            layer_health[layer] = {
                "total_checks": total,
                "ok_count": ok,
                "critical_count": critical,
                "health_score": score or 100,
            }
        
        # 计算总体健康评分
        scores = [h["health_score"] for h in layer_health.values() if h["health_score"]]
        overall = sum(scores) / len(scores) if scores else 100
        
        return {
            "overall_score": round(overall, 1),
            "overall_status": self._score_to_status(overall),
            "layer_health": layer_health,
        }
    
    def _score_to_status(self, score: float) -> str:
        if score >= 80:
            return "🟢 Healthy"
        elif score >= 50:
            return "🟡 Warning"
        else:
            return "🔴 Critical"
    
    # ... 其他方法实现
```

---

### Phase 4: 智能分析集成 (1天)

#### 4.1 Agent集成

```python
# 在Agent中添加宏观分析能力

@tool
def macro_network_analysis(
    analysis_type: str = "full",
    snapshot_date: str | None = None,
) -> str:
    """Execute macro-level network analysis using unified database queries.
    
    This tool performs comprehensive network analysis by:
    1. Querying all three databases (snapshot, commands, knowledge)
    2. Correlating data across different sources
    3. Generating insights and recommendations
    
    Args:
        analysis_type: Type of analysis - "full", "health", "anomalies", "trends"
        snapshot_date: Optional specific date (YYYY-MM-DD), defaults to latest
    
    Returns:
        Comprehensive analysis report in markdown format
    """
    from olav.analysis.macro_analyzer import MacroAnalyzer
    
    analyzer = MacroAnalyzer()
    
    if not snapshot_date:
        # 获取最新快照日期
        snapshot_date = analyzer.get_latest_snapshot_date()
    
    if analysis_type == "full":
        report = analyzer.generate_full_analysis(snapshot_date)
    elif analysis_type == "health":
        report = {"health": analyzer._analyze_health(snapshot_date)}
    elif analysis_type == "anomalies":
        report = {"anomalies": analyzer._detect_anomalies(snapshot_date)}
    elif analysis_type == "trends":
        report = {"trends": analyzer._analyze_trends()}
    else:
        return f"Unknown analysis type: {analysis_type}"
    
    return analyzer.format_report_as_markdown(report)
```

#### 4.2 自然语言查询映射

```python
# 自然语言 -> SQL 查询映射

NL_QUERY_PATTERNS = {
    # 跨设备搜索
    r"(哪个设备|which device).*IP.*([\d\.]+)": {
        "query": "SELECT device_name, interface_name FROM snapshot.interfaces WHERE ip_address = ?",
        "params": ["ip_match"],
    },
    
    # 聚合统计
    r"(列出|list|show).*所有.*(IP|接口)": {
        "query": "SELECT device_name, interface_name, ip_address FROM snapshot.interfaces WHERE ip_address IS NOT NULL ORDER BY device_name",
        "params": [],
    },
    
    # 健康检查
    r"(网络健康|network health|全网状态)": {
        "query": MACRO_ANALYSIS_QUERIES["network_health_summary"],
        "params": ["latest_date", "latest_date"],
    },
    
    # 异常检测
    r"(异常|问题|anomal|issue|problem)": {
        "query": MACRO_ANALYSIS_QUERIES["anomaly_detection"],
        "params": ["latest_date", "latest_date", "latest_date"],
    },
    
    # 配置对比
    r"(对比|compare|一致性|consistency).*BGP": {
        "query": MACRO_ANALYSIS_QUERIES["config_consistency_check"],
        "params": ["latest_date", "latest_date"],
    },
}
```

---

## 3. 联合查询能力设计

### 3.1 三库联合查询场景

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Three-Database Federation                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   network_snapshot        network_commands        knowledge         │
│   ┌───────────────┐      ┌───────────────┐      ┌───────────────┐  │
│   │ interfaces    │      │ capabilities  │      │ documents     │  │
│   │ routes        │◄────►│ audit_logs    │◄────►│ embeddings    │  │
│   │ bgp_neighbors │      │ command_cache │      │ solutions     │  │
│   │ topology_*    │      │               │      │               │  │
│   │ health_scores │      │               │      │               │  │
│   └───────────────┘      └───────────────┘      └───────────────┘  │
│          │                      │                      │            │
│          └──────────────────────┼──────────────────────┘            │
│                                 │                                   │
│                                 ▼                                   │
│                    ┌─────────────────────────┐                      │
│                    │   Unified Query Layer   │                      │
│                    │                         │                      │
│                    │  • Cross-DB JOINs       │                      │
│                    │  • Correlation Analysis │                      │
│                    │  • Knowledge Matching   │                      │
│                    └─────────────────────────┘                      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 联合查询用例

#### 用例1: 智能故障诊断

```sql
-- 检测问题 + 匹配知识库 + 推荐命令
WITH problems AS (
    SELECT 
        device_name,
        'interface_down' as problem_type,
        interface_name as detail,
        platform
    FROM snapshot.interfaces i
    JOIN snapshot.topology_devices d ON i.device_name = d.name
    WHERE i.oper_status = 'down' AND i.admin_status = 'up'
)
SELECT 
    p.device_name,
    p.problem_type,
    p.detail,
    k.content as solution,
    c.name as debug_command
FROM problems p
LEFT JOIN knowledge.documents k 
    ON k.content LIKE '%interface%down%' 
    OR k.content LIKE '%troubleshoot%layer1%'
LEFT JOIN commands.capabilities c 
    ON c.platform = p.platform 
    AND c.name LIKE '%show interface%'
LIMIT 10;
```

#### 用例2: 安全审计分析

```sql
-- 审计日志 + 命令白名单 + 设备角色
SELECT 
    a.timestamp,
    a.device,
    d.role,
    a.command,
    CASE 
        WHEN c.id IS NOT NULL THEN '✅ Authorized'
        WHEN c.id IS NULL AND a.command LIKE 'show%' THEN '⚠️ Unknown read'
        ELSE '🔴 Unauthorized write'
    END as audit_status,
    c.is_write
FROM commands.audit_logs a
JOIN snapshot.topology_devices d ON a.device = d.name
LEFT JOIN commands.capabilities c 
    ON a.command LIKE '%' || c.name || '%' 
    AND c.platform = d.platform
WHERE a.timestamp > NOW() - INTERVAL 24 HOUR
ORDER BY 
    CASE WHEN c.id IS NULL THEN 0 ELSE 1 END,  -- 未授权命令优先
    a.timestamp DESC;
```

#### 用例3: 容量规划分析

```sql
-- 设备能力 + 当前负载 + 知识库最佳实践
SELECT 
    d.name as device,
    d.platform,
    s.cpu_usage,
    s.memory_usage,
    COUNT(DISTINCT i.interface_name) as total_interfaces,
    SUM(CASE WHEN i.oper_status = 'up' THEN 1 ELSE 0 END) as used_interfaces,
    ROUND(100.0 * SUM(CASE WHEN i.oper_status = 'up' THEN 1 ELSE 0 END) / COUNT(*), 1) as interface_utilization,
    COUNT(DISTINCT c.id) as available_commands,
    CASE 
        WHEN s.cpu_usage > 80 OR s.memory_usage > 80 THEN '🔴 Capacity Alert'
        WHEN s.cpu_usage > 60 OR s.memory_usage > 60 THEN '🟡 Capacity Warning'
        ELSE '🟢 Capacity OK'
    END as capacity_status
FROM snapshot.topology_devices d
LEFT JOIN snapshot.system_info s ON d.name = s.device_name
LEFT JOIN snapshot.interfaces i ON d.name = i.device_name
LEFT JOIN commands.capabilities c ON c.platform = d.platform
GROUP BY d.name, d.platform, s.cpu_usage, s.memory_usage
ORDER BY capacity_status, interface_utilization DESC;
```

### 3.3 知识库增强

#### 添加故障模式表

```sql
-- knowledge.duckdb 新增表

CREATE TABLE fault_patterns (
    id INTEGER PRIMARY KEY,
    pattern_name VARCHAR NOT NULL,         -- 故障模式名称
    symptoms TEXT NOT NULL,                 -- 症状描述 (JSON array)
    root_causes TEXT,                       -- 根因列表
    solutions TEXT,                         -- 解决方案列表
    affected_layers TEXT,                   -- 影响的层级 (L1-L4)
    severity VARCHAR,                       -- 严重程度
    detection_query TEXT,                   -- 检测SQL
    embedding FLOAT[768],                   -- 向量嵌入
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 预置故障模式
INSERT INTO fault_patterns (pattern_name, symptoms, root_causes, solutions, affected_layers, severity, detection_query) VALUES
(
    'Interface Flapping',
    '["interface up/down", "UPDOWN messages in log", "CRC errors"]',
    '["cable issue", "transceiver failure", "duplex mismatch"]',
    '["check cable", "replace transceiver", "configure duplex"]',
    'L1,L2',
    'high',
    'SELECT device_name, interface_name FROM interfaces WHERE input_errors > 100 OR crc_errors > 50'
),
(
    'BGP Session Instability',
    '["BGP state changes", "session resets", "prefix withdrawal"]',
    '["MTU mismatch", "keepalive timeout", "route policy change"]',
    '["verify MTU", "adjust timers", "check route-map"]',
    'L3,L4',
    'critical',
    'SELECT device_name, neighbor_ip FROM bgp_neighbors WHERE state != ''Established'' OR state_changes > 3'
);
```

---

## 4. 实施计划

### 4.1 优先级排序

| Phase | 内容 | 工作量 | 价值 | 优先级 |
|-------|------|--------|------|--------|
| 1 | 结构化数据表 | 2天 | ⭐⭐⭐⭐⭐ | P0 |
| 2 | 联合查询架构 | 1天 | ⭐⭐⭐⭐ | P1 |
| 3 | 宏观分析增强 | 2天 | ⭐⭐⭐⭐⭐ | P0 |
| 4 | 智能分析集成 | 1天 | ⭐⭐⭐⭐ | P1 |
| **Total** | | **6天** | | |

### 4.2 里程碑

```
Week 1:
├── Day 1-2: Phase 1 - 结构化数据表
│   ├── 创建表结构
│   ├── 修改Stage 2写入逻辑
│   └── 验证数据写入
│
├── Day 3: Phase 2 - 联合查询架构
│   ├── 实现UnifiedDatabase类
│   ├── 测试ATTACH多库
│   └── 验证跨库JOIN
│
├── Day 4-5: Phase 3 - 宏观分析增强
│   ├── 实现MacroAnalyzer
│   ├── 创建分析SQL查询集
│   └── 集成到报告生成
│
└── Day 6: Phase 4 - 智能分析集成
    ├── 添加Agent工具
    ├── NL->SQL映射
    └── E2E测试
```

### 4.3 验收标准

#### Phase 1 验收
- [ ] `interfaces`表包含所有设备的接口数据
- [ ] `routes`表包含路由信息
- [ ] `bgp_neighbors`表包含BGP会话状态
- [ ] 查询 "3.3.3.3在哪个设备" 在<10ms内返回

#### Phase 2 验收
- [ ] 三库ATTACH成功
- [ ] 跨库JOIN查询正常工作
- [ ] 无性能退化

#### Phase 3 验收
- [ ] 健康评分基于SQL计算
- [ ] 异常检测返回有意义的结果
- [ ] 历史趋势分析可用

#### Phase 4 验收
- [ ] Agent可调用`macro_network_analysis`工具
- [ ] 自然语言查询正确路由到SQL

---

## 5. 详细开发任务清单

### 5.1 Phase 1: 结构化数据表 (Day 1-3)

#### Day 1: 表结构设计与创建

**任务 1.1.1: 在 database.py 添加表创建函数**
```python
# 文件: src/olav/core/database.py
# 在 init_topology_db() 之后添加

def init_structured_tables(db_path: str | None = None) -> duckdb.DuckDBPyConnection:
    """初始化结构化网络数据表."""
    # 创建: interfaces, routes, bgp_neighbors, ospf_neighbors, 
    #       vlans, arp_table, system_info, health_scores
```

**任务 1.1.2: 定义 8 个核心表**
| 表名 | 主键 | 关键字段 | 数据来源 |
|------|------|----------|---------|
| interfaces | (snapshot_date, device, interface) | ip, status, errors | show-ip-interface-brief.json |
| routes | (snapshot_date, device, network, nexthop) | protocol, metric | show-ip-route.json |
| bgp_neighbors | (snapshot_date, device, neighbor_ip) | state, prefixes | show-ip-bgp-summary.json |
| ospf_neighbors | (snapshot_date, device, neighbor_id) | state, area | show-ip-ospf-neighbor.json |
| vlans | (snapshot_date, device, vlan_id) | name, ports | show-vlan.json |
| arp_table | (snapshot_date, device, ip, mac) | interface | show-arp.json |
| system_info | (snapshot_date, device) | cpu, memory, uptime | show-version.json |
| health_scores | (snapshot_date, layer) | score, counts | 计算生成 |

**验收**: 
```bash
uv run python -c "from olav.core.database import init_structured_tables; init_structured_tables()"
# 应创建 8 个新表
```

#### Day 2: 数据导入逻辑

**任务 1.2.1: 创建 data_importer.py**
```python
# 文件: src/olav/tools/data_importer.py

class NetworkDataImporter:
    """从 Parsed JSON 导入结构化数据到 DuckDB."""
    
    def __init__(self, db_path: str):
        self.conn = duckdb.connect(db_path)
    
    def import_interfaces(self, device: str, json_path: Path) -> int:
        """导入接口数据. 返回导入行数."""
    
    def import_routes(self, device: str, json_path: Path) -> int:
        """导入路由数据."""
    
    def import_bgp_neighbors(self, device: str, json_path: Path) -> int:
        """导入 BGP 邻居数据."""
    
    def import_all_from_snapshot(self, snapshot_dir: Path) -> dict:
        """从快照目录导入所有数据. 返回统计."""
```

**任务 1.2.2: 处理 TextFSM 解析结果**
- 解析 `show-ip-interface-brief.json` → interfaces 表
- 解析 `show-ip-route.json` → routes 表
- 解析 `show-ip-bgp-summary.json` → bgp_neighbors 表
- 解析 `show-arp.json` → arp_table 表

**验收**:
```bash
uv run python -c "
from olav.tools.data_importer import NetworkDataImporter
importer = NetworkDataImporter('.olav/db/network_snapshot.duckdb')
stats = importer.import_all_from_snapshot('exports/snapshots/2026-01-14')
print(stats)
"
# 应显示每个表的导入行数
```

#### Day 3: Stage 2 集成与测试

**任务 1.3.1: 修改 sync_tools.py**
```python
# 在 _process_sync_stage2() 中添加:

print("[Stage2] Importing structured data to database...", flush=True)
from olav.tools.data_importer import NetworkDataImporter
importer = NetworkDataImporter(str(NETWORK_SNAPSHOT_PATH))
stats = importer.import_all_from_snapshot(sync_dir)
print(f"[Stage2] Imported: {stats}", flush=True)
```

**任务 1.3.2: E2E 测试**
```bash
# 1. 清理旧数据
rm -rf exports/snapshots/2026-01-14 .olav/db/network_snapshot.duckdb

# 2. 执行快照
uv run olav snapshot

# 3. 验证数据
uv run python -c "
import duckdb
conn = duckdb.connect('.olav/db/network_snapshot.duckdb')
for table in ['interfaces', 'routes', 'bgp_neighbors', 'arp_table']:
    count = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    print(f'{table}: {count} rows')
"
```

---

### 5.2 Phase 2: 联邦查询层 (Day 4)

**任务 2.1: 创建 unified_database.py**
```python
# 文件: src/olav/core/unified_database.py

class UnifiedDatabase:
    """三库联合查询层."""
    
    def __init__(self):
        self.conn = duckdb.connect(":memory:")
        self.conn.execute(f"ATTACH '{NETWORK_SNAPSHOT_PATH}' AS snapshot")
        self.conn.execute(f"ATTACH '{NETWORK_COMMANDS_PATH}' AS commands")
        self.conn.execute(f"ATTACH '{KNOWLEDGE_PATH}' AS knowledge")
    
    def query(self, sql: str, params: list = None) -> list:
        """执行跨库查询."""
    
    def find_ip_location(self, ip: str) -> dict:
        """查找 IP 所在设备和接口."""
    
    def get_device_health(self, device: str) -> dict:
        """获取设备综合健康状态."""
```

**任务 2.2: 添加 SQL 查询工具**
```python
# 文件: src/olav/tools/query_tools.py

@tool
def sql_query(query: str) -> str:
    """Execute SQL query against network database."""

@tool  
def find_ip(ip_address: str) -> str:
    """Find which device and interface has this IP."""

@tool
def network_summary() -> str:
    """Get network-wide summary statistics."""
```

---

### 5.3 Phase 3: 宏观分析引擎 (Day 5-6)

**任务 3.1: 创建 macro_analyzer.py**
```python
# 文件: src/olav/analysis/macro_analyzer.py

class MacroAnalyzer:
    """网络宏观分析引擎."""
    
    def calculate_health_scores(self, snapshot_date: str) -> dict:
        """计算各层健康评分."""
    
    def detect_anomalies(self, snapshot_date: str) -> list:
        """检测异常."""
    
    def compare_snapshots(self, date1: str, date2: str) -> dict:
        """对比两次快照."""
    
    def generate_executive_report(self, snapshot_date: str) -> str:
        """生成管理层报告."""
```

**任务 3.2: 创建 health_score.py**
```python
# 文件: src/olav/analysis/health_score.py

HEALTH_SCORING_RULES = {
    "L1": {
        "interface_up": 10,      # 接口正常 +10
        "interface_down": -20,  # 接口故障 -20
        "crc_errors": -5,       # CRC 错误 -5
    },
    "L2": {...},
    "L3": {...},
    "L4": {...},
}

def calculate_layer_score(layer: str, conn: duckdb.DuckDBPyConnection) -> int:
    """计算指定层的健康评分."""
```

---

### 5.4 Phase 4: 知识库关联 (Day 7)

**任务 4.1: 创建 knowledge_correlator.py**
```python
# 文件: src/olav/analysis/knowledge_correlator.py

class KnowledgeCorrelator:
    """将网络问题与知识库解决方案关联."""
    
    def find_solutions_for_issue(self, issue_description: str) -> list:
        """查找问题的解决方案."""
    
    def match_fault_patterns(self, anomalies: list) -> list:
        """匹配故障模式."""
```

**任务 4.2: 添加 Agent 工具**
```python
@tool
def diagnose_network_issue(issue: str) -> str:
    """Diagnose network issue and suggest solutions."""
```

---

## 6. 总结

### 6.1 完善设计的关键点

1. **结构化数据表**: 这是基础，没有它联合查询无意义
2. **联合查询架构**: DuckDB ATTACH机制实现跨库查询
3. **宏观分析框架**: SQL替代JSON文件分析，提升准确性和速度
4. **知识库关联**: 将故障检测与解决方案自动关联

### 6.2 联合查询的价值

| 单库查询 | 联合查询 | 价值提升 |
|---------|---------|---------|
| "接口down了" | "接口down + 知识库解决方案" | **自动诊断** |
| "命令执行了" | "命令 + 白名单检查" | **安全审计** |
| "设备状态" | "设备 + 拓扑 + 命令能力" | **智能运维** |
| "发现问题" | "问题 + 历史趋势 + 根因" | **预测分析** |

### 6.3 预期效果

投入 7 天开发后：
- 数据库价值: 20% → **95%**
- 查询能力: 8场景 → **100+场景**
- 分析速度: 秒级 → **毫秒级**
- 分析深度: 单设备 → **全网关联**
- 智能程度: 手动分析 → **自动诊断+建议**

这将使 OLAV 从"CLI 包装器"升级为"智能网络分析平台"。

---

## 7. 开发启动命令

```bash
# 确认当前状态
uv run python -c "
import duckdb
from pathlib import Path
print('Parsed files:', len(list(Path('exports/snapshots/2026-01-14/parsed').rglob('*.json'))))
conn = duckdb.connect('.olav/db/network_snapshot.duckdb')
print('Current tables:', [t[0] for t in conn.execute('SHOW TABLES').fetchall()])
"

# 准备开发分支
git checkout -b feature/db-federation-v0.8.4

# 开始 Phase 1 开发...
```
