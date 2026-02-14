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

## 0.5 架构优化提案 (2026-01-14) 🆕

### 0.5.1 当前架构问题

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     当前架构 (问题重重)                                    │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Nornir/Netmiko  →  .txt 文件  →  独立解析器  →  .json 文件  →  专用表   │
│  (原始输出)         exports/raw     _parse_xxx()   parsed/       8+个表   │
│                                                                          │
│  问题:                                                                   │
│  1. 解析器与 Nornir 分离，需要维护命令→解析器映射 (~15 个函数)            │
│  2. 数据库表结构预定义，与 TextFSM 输出字段名不匹配 (PROTO vs PROTOCOL)  │
│  3. 每种命令需要单独的 import_xxx() 方法 (~8 个方法)                     │
│  4. 三层文件存储 (txt→json→db)，冗余且低效                               │
│  5. 代码量大 (~800行)，维护成本高，容易出错                               │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### 0.5.2 优化架构：Netmiko 原生 TextFSM + DuckDB JSON

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     优化架构 (推荐)                                       │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Nornir/Netmiko + use_textfsm=True  →  DuckDB (JSON列)  →  视图 (可选)   │
│  (自动匹配 ntc-templates，134个模板)     单表存储            按需创建    │
│                                                                          │
│  优势:                                                                   │
│  1. ✅ 零解析器代码 - Netmiko 原生支持 use_textfsm=True                  │
│  2. ✅ 零字段映射 - JSON 原样存储，无需转义                               │
│  3. ✅ 灵活查询 - DuckDB JSON 函数支持任意字段提取                       │
│  4. ✅ 向后兼容 - 新命令自动支持，只要 ntc-templates 有模板               │
│  5. ✅ 代码量减少 90% - 删除 _parse_xxx() 和 import_xxx() 函数           │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### 0.5.3 技术验证 ✅

| 组件 | 验证结果 | 详情 |
|------|---------|------|
| **Netmiko use_textfsm** | ✅ 支持 | `send_command(use_textfsm=True)` 原生参数 |
| **ntc-templates** | ✅ 完整 | 134 个 Cisco IOS 模板，涵盖所有关键命令 |
| **DuckDB JSON** | ✅ 支持 | `json_extract()`, `UNNEST()` 完整支持 |

**已验证模板**:
- ✅ `cisco_ios_show_ip_bgp_summary.textfsm`
- ✅ `cisco_ios_show_ip_ospf_neighbor.textfsm`
- ✅ `cisco_ios_show_vlan.textfsm`
- ✅ `cisco_ios_show_ip_interface_brief.textfsm`
- ✅ `cisco_ios_show_ip_route.textfsm`
- ✅ `cisco_ios_show_ip_arp.textfsm`
- ✅ `cisco_ios_show_version.textfsm`
- ✅ `cisco_ios_show_cdp_neighbors_detail.textfsm`

### 0.5.4 新表结构设计

```sql
-- =============================================================================
-- 统一命令输出表 (取代 8+ 个专用表)
-- =============================================================================
CREATE TABLE command_outputs (
    id INTEGER PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    device_name VARCHAR NOT NULL,
    platform VARCHAR DEFAULT 'cisco_ios',
    command VARCHAR NOT NULL,           -- 原始命令，如 'show ip bgp summary'
    raw_output TEXT,                    -- 原始输出 (仅未解析时保存)
    parsed_data JSON,                   -- TextFSM 解析结果 (原样存储!)
    row_count INTEGER DEFAULT 0,        -- 解析出的记录数
    parse_success BOOLEAN DEFAULT FALSE,
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(snapshot_date, device_name, command)
);

CREATE INDEX idx_cmd_outputs_command ON command_outputs(command);
CREATE INDEX idx_cmd_outputs_device ON command_outputs(device_name);
CREATE INDEX idx_cmd_outputs_date ON command_outputs(snapshot_date);
```

### 0.5.5 查询示例

```sql
-- 查询所有 BGP 邻居 (自动展开 JSON 数组)
WITH json_array AS (
    SELECT 
        device_name,
        snapshot_date,
        UNNEST(json_extract(parsed_data, '$[*]')::VARCHAR[]) as elem
    FROM command_outputs
    WHERE command LIKE '%bgp summary%' AND parse_success = TRUE
)
SELECT 
    device_name,
    json_extract_string(elem::JSON, '$.NEIGHBOR') as neighbor,
    json_extract_string(elem::JSON, '$.AS') as remote_as,
    json_extract_string(elem::JSON, '$.STATE') as state,
    json_extract_string(elem::JSON, '$.PFX_RCD') as prefixes
FROM json_array;

-- 查询所有 OSPF 邻居
WITH json_array AS (
    SELECT 
        device_name,
        UNNEST(json_extract(parsed_data, '$[*]')::VARCHAR[]) as elem
    FROM command_outputs
    WHERE command LIKE '%ospf neighbor%' AND parse_success = TRUE
)
SELECT 
    device_name,
    json_extract_string(elem::JSON, '$.NEIGHBOR_ID') as neighbor_id,
    json_extract_string(elem::JSON, '$.INTERFACE') as interface,
    json_extract_string(elem::JSON, '$.STATE') as state
FROM json_array;
```

### 0.5.6 迁移计划

| 步骤 | 任务 | 工作量 |
|------|------|--------|
| 1 | 修改 sync_tools.py: 添加 `use_textfsm=True` | 1 小时 |
| 2 | 创建 `command_outputs` 表 | 30 分钟 |
| 3 | 简化导入器: 单个通用 `import_command_output()` | 2 小时 |
| 4 | 创建视图 (v_bgp_neighbors 等) | 1 小时 |
| 5 | 删除冗余代码: `_parse_xxx()`, `import_xxx()` | 1 小时 |
| 6 | 更新 UnifiedDatabase 查询方法 | 2 小时 |
| **总计** | | **~8 小时** |

### 0.5.7 决策

- [x] 采用新架构 (推荐) ✅ **已选择**
- [ ] 保持当前架构，修复字段映射
- [ ] 混合方案: 新表 + 旧表并行

---

## 0.6 增强架构: 自定义模板 + LLM 自学习标准化 (2026-01-15) 🆕

### 0.6.1 问题分析

在采用 Netmiko 原生 TextFSM 的基础上，还需要解决两个关键问题：

| 问题 | 描述 | 影响 |
|------|------|------|
| **自定义模板** | 用户需要为特殊设备/命令添加 TextFSM 模板 | 扩展性受限 |
| **字段标准化** | 不同厂商 TextFSM 输出字段名不一致 | Topology/Routing 功能需要统一字段 |

**字段差异示例 (BGP Summary)**:

| 厂商 | 邻居 IP 字段 | AS 字段 | 状态字段 |
|------|-------------|---------|----------|
| Cisco IOS | `BGP_NEIGHBOR` | `NEIGHBOR_AS` | `STATE_OR_PREFIXES_RECEIVED` |
| Juniper | `PEER_ADDRESS` | `PEER_AS` | `STATE` |
| Arista EOS | `BGP_NEIGH` | `NEIGH_AS` | `STATE_PFXRCD` |

### 0.6.2 解决方案: 三层架构 + LLM 自学习

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    增强架构: 三层存储 + 智能标准化                            │
└─────────────────────────────────────────────────────────────────────────────┘

                        ┌──────────────────────┐
                        │     设备命令执行       │
                        │   (Nornir/Netmiko)    │
                        └──────────┬───────────┘
                                   │
                        ┌──────────▼───────────┐
                        │   use_textfsm=True    │
                        │  (自动匹配模板)        │
                        └──────────┬───────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
              ▼                    ▼                    ▼
    ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
    │ 解析成功 (JSON)  │  │ 解析失败 (raw)   │  │ 无模板 (raw)    │
    └────────┬────────┘  └────────┬────────┘  └────────┬────────┘
             │                    │                    │
             └────────────────────┼────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Layer 1: 原始存储层 (Raw Storage)                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  TABLE command_outputs (                                                    │
│    id           BIGINT PRIMARY KEY,                                         │
│    snapshot_id  VARCHAR,                                                    │
│    device       VARCHAR,                                                    │
│    platform     VARCHAR,      -- cisco_ios, juniper_junos, arista_eos      │
│    command      VARCHAR,      -- show ip bgp summary                        │
│    raw_output   TEXT,         -- 原始文本输出 (始终保留)                     │
│    parsed_json  JSON,         -- TextFSM 解析结果 (可为 NULL)               │
│    parse_status VARCHAR,      -- success / failed / no_template            │
│    collected_at TIMESTAMP                                                   │
│  )                                                                          │
│                                                                             │
│  特点:                                                                      │
│    ✓ 保留所有原始数据 (支持后续重新解析)                                    │
│    ✓ 无损存储 - raw + parsed 双保险                                        │
│    ✓ 单表设计 - 简单可靠                                                   │
│    ✓ 支持任意命令和平台                                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼ (功能需要时触发)
┌─────────────────────────────────────────────────────────────────────────────┐
│  Layer 2: 标准化层 (Normalization Layer) - 按需处理                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                        标准化处理器 (Normalizer)                        │ │
│  │                                                                       │ │
│  │  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐  │ │
│  │  │ 1. 映射表查找    │────▶│ 2. 映射存在?     │────▶│ 3a. 本地映射    │  │ │
│  │  │ (毫秒级)        │     │                 │  是  │  (快速路径)     │  │ │
│  │  └─────────────────┘     └────────┬────────┘     └────────┬────────┘  │ │
│  │                                   │ 否                     │          │ │
│  │                                   ▼                        │          │ │
│  │                          ┌─────────────────┐               │          │ │
│  │                          │ 3b. LLM 标准化   │               │          │ │
│  │                          │  + 规则学习      │               │          │ │
│  │                          │  (慢速路径)      │               │          │ │
│  │                          └────────┬────────┘               │          │ │
│  │                                   │                        │          │ │
│  │                                   │ 缓存新规则              │          │ │
│  │                                   ▼                        │          │ │
│  │                          ┌─────────────────┐               │          │ │
│  │                          │ 映射规则缓存     │◀──────────────┘          │ │
│  │                          │ config/mappings/│                          │ │
│  │                          └────────┬────────┘                          │ │
│  │                                   │                                   │ │
│  │                                   ▼                                   │ │
│  │                          ┌─────────────────┐                          │ │
│  │                          │ Pydantic 验证    │                          │ │
│  │                          │ (确保数据一致)   │                          │ │
│  │                          └─────────────────┘                          │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Layer 3: 标准化视图/表 (Normalized Views)                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  视图定义 (统一字段名):                                                      │
│                                                                             │
│    CREATE VIEW v_bgp_neighbors AS                                           │
│    SELECT device, neighbor_ip, remote_as, state, prefixes_received          │
│    FROM normalized_bgp_neighbors;                                           │
│                                                                             │
│    CREATE VIEW v_ospf_neighbors AS                                          │
│    SELECT device, neighbor_id, interface, state, priority                   │
│    FROM normalized_ospf_neighbors;                                          │
│                                                                             │
│    CREATE VIEW v_topology_links AS                                          │
│    SELECT local_device, local_interface, remote_device, remote_interface    │
│    FROM normalized_topology_links;                                          │
│                                                                             │
│  应用层统一接口:                                                             │
│    - Topology Builder: 查询 v_topology_links                                │
│    - Path Analyzer: 查询 v_routes                                           │
│    - Health Monitor: 查询 v_bgp_neighbors, v_ospf_neighbors                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 0.6.3 自定义 TextFSM 模板支持

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      自定义模板方案                                          │
└─────────────────────────────────────────────────────────────────────────────┘

目录结构:
  config/
  └── templates/                          # 用户自定义模板目录
      ├── index                           # 模板索引文件 (ntc-templates 格式)
      ├── cisco_ios_show_custom.textfsm   # 自定义模板
      ├── huawei_show_bgp_peer.textfsm    # 华为设备模板
      └── README.md                       # 模板编写指南

index 文件格式:
  # Template, Hostname, Platform, Command
  cisco_ios_show_custom.textfsm, .*, cisco_ios, show custom
  huawei_show_bgp_peer.textfsm, .*, huawei, show bgp peer

实现方式:
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  # 启动时自动配置 (约 10 行代码)                                          │
  │                                                                         │
  │  import os                                                              │
  │  from pathlib import Path                                               │
  │                                                                         │
  │  custom_templates = Path("config/templates")                            │
  │  if custom_templates.exists():                                          │
  │      # Netmiko 会优先搜索此目录                                          │
  │      os.environ["NET_TEXTFSM"] = str(custom_templates.absolute())       │
  │      logger.info(f"已加载自定义模板目录: {custom_templates}")            │
  │                                                                         │
  │  # 模板搜索顺序:                                                         │
  │  # 1. NET_TEXTFSM 指定的目录 (自定义模板)                                │
  │  # 2. ntc-templates 包目录 (内置模板)                                    │
  └─────────────────────────────────────────────────────────────────────────┘

用户体验:
  ✓ 放入模板文件 → 自动生效 (零代码修改)
  ✓ 支持覆盖 ntc-templates 内置模板
  ✓ 模板可 Git 版本控制
  ✓ 与 OLAV config/ 目录结构一致
```

### 0.6.4 核心 Pydantic 标准化模型

```python
# =============================================================================
# 标准化数据模型 (6 个核心模型)
# 位置: src/olav/core/normalized_models.py
# =============================================================================

from pydantic import BaseModel, Field
from typing import Optional, Literal

class TopologyLink(BaseModel):
    """用于拓扑图的标准化链路模型"""
    local_device: str = Field(..., description="本地设备名")
    local_interface: str = Field(..., description="本地接口")
    remote_device: str = Field(..., description="远端设备名")
    remote_interface: str = Field(..., description="远端接口")
    link_type: Literal["cdp", "lldp", "ospf", "bgp"] = Field(..., description="链路发现类型")
    
class BGPNeighbor(BaseModel):
    """标准化 BGP 邻居模型"""
    neighbor_ip: str = Field(..., description="邻居 IP")
    remote_as: int = Field(..., description="远端 AS 号")
    state: str = Field(..., description="BGP 状态")
    prefixes_received: int = Field(0, description="接收的前缀数")
    uptime: str = Field("", description="邻居建立时间")

class OSPFNeighbor(BaseModel):
    """标准化 OSPF 邻居模型"""
    neighbor_id: str = Field(..., description="邻居路由器 ID")
    interface: str = Field(..., description="本地接口")
    state: str = Field(..., description="OSPF 状态")
    priority: int = Field(1, description="优先级")
    ip_address: str = Field("", description="邻居 IP")

class RouteEntry(BaseModel):
    """标准化路由条目模型"""
    network: str = Field(..., description="目标网络")
    next_hop: str = Field(..., description="下一跳")
    protocol: str = Field(..., description="路由协议")
    metric: int = Field(0, description="路由度量")
    interface: str = Field("", description="出接口")

class CDPNeighbor(BaseModel):
    """标准化 CDP/LLDP 邻居模型"""
    local_interface: str = Field(..., description="本地接口")
    remote_device: str = Field(..., description="远端设备名")
    remote_interface: str = Field(..., description="远端接口")
    platform: str = Field("", description="远端设备平台")
    mgmt_address: str = Field("", description="管理地址")

class InterfaceStatus(BaseModel):
    """标准化接口状态模型"""
    interface: str = Field(..., description="接口名")
    ip_address: str = Field("", description="IP 地址")
    status: str = Field(..., description="接口状态")
    protocol: str = Field("", description="协议状态")
    description: str = Field("", description="接口描述")
```

### 0.6.5 字段映射表 (内置主流平台)

```python
# =============================================================================
# 字段映射表 - 将厂商字段名映射到标准字段名
# 位置: src/olav/core/field_mappings.py
# =============================================================================

FIELD_MAPPINGS = {
    # -------------------------------------------------------------------------
    # BGP Neighbor 映射
    # -------------------------------------------------------------------------
    "bgp_neighbor": {
        "cisco_ios": {
            "BGP_NEIGHBOR": "neighbor_ip",
            "NEIGHBOR_AS": "remote_as",
            "STATE_OR_PREFIXES_RECEIVED": "state",
            "UP_DOWN": "uptime",
        },
        "juniper_junos": {
            "PEER_ADDRESS": "neighbor_ip",
            "PEER_AS": "remote_as",
            "STATE": "state",
            "UP_DOWN": "uptime",
        },
        "arista_eos": {
            "BGP_NEIGH": "neighbor_ip",
            "NEIGH_AS": "remote_as",
            "STATE_PFXRCD": "state",
            "UP_DOWN": "uptime",
        },
    },
    
    # -------------------------------------------------------------------------
    # OSPF Neighbor 映射
    # -------------------------------------------------------------------------
    "ospf_neighbor": {
        "cisco_ios": {
            "NEIGHBOR_ID": "neighbor_id",
            "INTERFACE": "interface",
            "STATE": "state",
            "PRIORITY": "priority",
            "IP_ADDRESS": "ip_address",
        },
        "juniper_junos": {
            "NEIGHBOR_ID": "neighbor_id",
            "INTERFACE": "interface",
            "STATE": "state",
            "PRIORITY": "priority",
            "IP_ADDRESS": "ip_address",
        },
    },
    
    # -------------------------------------------------------------------------
    # CDP/LLDP Neighbor 映射
    # -------------------------------------------------------------------------
    "cdp_neighbor": {
        "cisco_ios": {
            "LOCAL_INTERFACE": "local_interface",
            "NEIGHBOR_NAME": "remote_device",
            "NEIGHBOR_INTERFACE": "remote_interface",
            "PLATFORM": "platform",
            "MGMT_ADDRESS": "mgmt_address",
        },
        "cisco_nxos": {
            "LOCAL_INTERFACE": "local_interface",
            "NEIGHBOR_NAME": "remote_device",
            "NEIGHBOR_INTERFACE": "remote_interface",
            "PLATFORM": "platform",
            "MGMT_ADDRESS": "mgmt_address",
        },
    },
    
    # -------------------------------------------------------------------------
    # Route 映射
    # -------------------------------------------------------------------------
    "route": {
        "cisco_ios": {
            "NETWORK": "network",
            "NEXTHOP_IP": "next_hop",
            "PROTOCOL": "protocol",
            "METRIC": "metric",
            "NEXTHOP_IF": "interface",
        },
    },
}
```

### 0.6.6 LLM 自学习流程

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      LLM 自学习流程                                          │
└─────────────────────────────────────────────────────────────────────────────┘

场景: 遇到未知平台 (如首次连接华为设备)

Step 1: 检测未知平台
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  platform = "huawei"                                                    │
  │  data_type = "bgp_neighbor"                                             │
  │                                                                         │
  │  if platform not in FIELD_MAPPINGS[data_type]:                          │
  │      # 触发 LLM 自学习                                                  │
  │      mapping = await learn_field_mapping(platform, data_type, sample)   │
  └─────────────────────────────────────────────────────────────────────────┘

Step 2: LLM 解析 + 规则生成
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  Prompt:                                                                │
  │  """                                                                    │
  │  You are a network data normalization expert.                           │
  │                                                                         │
  │  Task 1: Convert this {platform} TextFSM output to standard format:     │
  │  Input: {parsed_json}                                                   │
  │  Target Schema: {BGPNeighbor.model_json_schema()}                       │
  │                                                                         │
  │  Task 2: Generate field mapping rules for future use:                   │
  │  Output format:                                                         │
  │  {                                                                      │
  │    "normalized_data": [...],                                            │
  │    "field_mapping": {                                                   │
  │      "SOURCE_FIELD": "target_field",                                    │
  │      ...                                                                │
  │    }                                                                    │
  │  }                                                                      │
  │  """                                                                    │
  └─────────────────────────────────────────────────────────────────────────┘

Step 3: 缓存映射规则
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  # 保存到文件                                                            │
  │  cache_path = Path(f"config/mappings/{platform}_{data_type}.json")      │
  │  cache_path.write_text(json.dumps(llm_response["field_mapping"]))       │
  │                                                                         │
  │  # 更新内存映射表                                                        │
  │  FIELD_MAPPINGS[data_type][platform] = llm_response["field_mapping"]    │
  │                                                                         │
  │  logger.info(f"已学习新映射规则: {platform}/{data_type}")               │
  └─────────────────────────────────────────────────────────────────────────┘

Step 4: 后续直接使用缓存 (无需 LLM)
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  # 启动时加载缓存的映射规则                                               │
  │  for mapping_file in Path("config/mappings").glob("*.json"):            │
  │      platform, data_type = mapping_file.stem.split("_", 1)              │
  │      FIELD_MAPPINGS[data_type][platform] = json.loads(mapping_file...)  │
  └─────────────────────────────────────────────────────────────────────────┘

效果:
  ✓ LLM 成本只发生一次 (首次遇到新平台)
  ✓ 后续同平台使用本地映射 (毫秒级 + 免费)
  ✓ 自动适应任意新平台
  ✓ 映射规则可人工审核和修正
```

### 0.6.7 方案对比

| 维度 | 纯 LLM | 纯映射表 | 混合 + 自学习 (推荐) |
|------|--------|----------|---------------------|
| **已知平台速度** | 1-3 秒/设备 | <1 毫秒/设备 | <1 毫秒/设备 |
| **未知平台处理** | ✅ 自动 | ❌ 需手动添加 | ✅ 自动 (LLM fallback) |
| **API 成本** | ~$0.01/设备 | $0 | ~$0.001/设备 (首次) |
| **离线支持** | ❌ | ✅ | ✅ (已知平台) |
| **结果稳定性** | 可能波动 | 100% 确定 | 100% 确定 (已学习) |
| **维护成本** | 低 | 高 | 低 (自动学习) |
| **可审计性** | ❌ | ✅ | ✅ (缓存可查看) |

### 0.6.8 LLM 自学习能力扩展 (2026-01-15 新增) 🆕

**核心思想**: 不仅字段映射可以自学习，TextFSM 模板本身也可以由 LLM 生成

#### 0.6.8.1 双层自学习架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     解析流程 (优先级递减)                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1️⃣ ntc-templates (134个官方模板)          [免费 + 毫秒级]              │
│     └─> 覆盖主流设备: Cisco/Juniper/Arista/HPE/Dell/F5...               │
│                                                                         │
│  2️⃣ 用户自定义模板 (config/templates/)     [免费 + 毫秒级]              │
│     └─> 企业特定设备/自定义命令                                          │
│                                                                         │
│  ⬇ 缓存未命中 ⬇                                                         │
│                                                                         │
│  3️⃣ LLM 生成模板 (首次) + 缓存              [首次: $0.01 + 5秒]         │
│     ┌──────────────────────────────────────┐                          │
│     │ A. LLM 分析原始输出                   │ 🤖                       │
│     │    ├─ 识别表格结构                   │                          │
│     │    ├─ 提取字段名称                   │                          │
│     │    └─ 生成正则表达式                 │                          │
│     │                                       │                          │
│     │ B. 生成 TextFSM 模板                 │ 📝                       │
│     │    ├─ Value 定义                     │                          │
│     │    ├─ 正则匹配规则                   │                          │
│     │    └─ 状态机转换                     │                          │
│     │                                       │                          │
│     │ C. 验证模板质量                      │ ✅                       │
│     │    ├─ 尝试解析原始输出                │                          │
│     │    ├─ 检查提取率 (>80%)              │                          │
│     │    └─ 人工审核标记 (可选)             │                          │
│     │                                       │                          │
│     │ D. 缓存到 config/templates/         │ 💾                       │
│     │    └─> 后续使用本地模板 (免费)        │                          │
│     └──────────────────────────────────────┘                          │
│                                                                         │
│  4️⃣ LLM 直接解析 (无模板)                  [$0.02 + 3秒]               │
│     └─> 用于一次性命令/特殊输出                                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

效果:
  ✓ 第1次遇到新设备: LLM 生成模板 (~5秒 + $0.01)
  ✓ 第2次及以后: 使用缓存模板 (毫秒级 + 免费)
  ✓ 覆盖任意设备/命令组合
  ✓ 用户可审核和优化生成的模板
```

#### 0.6.8.2 LLM 生成模板示例

**输入 (华为 BGP 原始输出)**:
```
BGP peer is 10.0.0.1, remote AS 65001, external link
  BGP version 4, remote router ID 1.1.1.1
  BGP state = Established, up for 3d4h
  Received prefixes: 150
```

**LLM Prompt**:
```
根据以下网络命令输出，生成一个 TextFSM 模板。

命令: show bgp peer
平台: huawei_vrp
原始输出: [如上]

要求:
1. 识别表格结构（如果有）
2. 提取所有关键字段（IP、AS、状态等）
3. 生成 Value 定义（使用合适的数据类型）
4. 生成正则表达式规则（精确匹配）
5. 输出标准 TextFSM 格式
6. 包含注释说明每个规则的作用
```

**LLM 输出**:
```textfsm
# Huawei VRP BGP Peer Status Template
# Generated by LLM on 2026-01-15
# Command: show bgp peer

Value NEIGHBOR (\d+\.\d+\.\d+\.\d+)
Value REMOTE_AS (\d+)
Value ROUTER_ID (\d+\.\d+\.\d+\.\d+)
Value STATE (\w+)
Value UPTIME (\S+)
Value PREFIXES_RECEIVED (\d+)

Start
  ^BGP peer is ${NEIGHBOR}, remote AS ${REMOTE_AS}
  ^\s+remote router ID ${ROUTER_ID}
  ^\s+BGP state = ${STATE}, up for ${UPTIME}
  ^\s+Received prefixes: ${PREFIXES_RECEIVED} -> Record
```

**验证结果**:
```json
[{
  "NEIGHBOR": "10.0.0.1",
  "REMOTE_AS": "65001",
  "ROUTER_ID": "1.1.1.1",
  "STATE": "Established",
  "UPTIME": "3d4h",
  "PREFIXES_RECEIVED": "150"
}]
```

#### 0.6.8.3 ReAct + Pydantic 强化学习 (2026-01-15 优化) 🆕

**问题**: 一次性生成 TextFSM 模板成功率约 60-70%

**解决**: ReAct 迭代 + Pydantic 约束验证，成功率提升至 90%+

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     ReAct 强化学习流程                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  🎯 目标约束 (Pydantic 模型)                                            │
│  ──────────────────────────────────────────────────────                │
│  class BGPNeighborConstraint(BaseModel):                               │
│      neighbor_ip: IPv4Address          # 必填                          │
│      remote_as: int                    # 必填                          │
│      state: BGPState                   # 必填                          │
│      prefixes_received: Optional[int]  # 可选                          │
│                                                                         │
│  🔄 ReAct 迭代循环                                                      │
│  ──────────────────────────────────────────────────────                │
│                                                                         │
│  Iteration 1:                                                           │
│  ├─ Thought: 分析原始输出结构 (识别表格/列表/键值对)                    │
│  ├─ Action: 生成初版 TextFSM 模板                                      │
│  ├─ Observation: 模板生成完成                                          │
│  ├─ Action: 解析原始输出                                               │
│  ├─ Observation: 提取 5 条记录                                         │
│  ├─ Action: 验证 Pydantic 约束                                         │
│  └─ Observation: ❌ 缺少 remote_as 字段                                │
│                                                                         │
│  Iteration 2:                                                           │
│  ├─ Thought: remote_as 字段缺失，需修复正则表达式                       │
│  ├─ Action: 修改模板，添加 AS 字段匹配                                 │
│  ├─ Observation: 模板更新完成                                          │
│  ├─ Action: 重新解析                                                   │
│  ├─ Observation: 提取 5 条记录，字段完整                               │
│  ├─ Action: 验证 Pydantic 约束                                         │
│  └─ Observation: ✅ 所有字段通过验证                                   │
│                                                                         │
│  Final: 保存验证通过的模板 → config/templates/                         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 0.6.8.3.2 零知识自学习: 未知命令场景 (2026-01-15 新增) 🆕

**问题**: `show ip mroute` 等命令既没有 ntc-templates，也没有预定义 Pydantic 模型

**解决**: 两阶段自学习 - LLM 先发现字段，再生成模板

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     零知识自学习: 两阶段流程                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  触发条件:                                                              │
│  ──────────────────────────────────────────────                        │
│  Netmiko use_textfsm=True 返回字符串 (非 list/dict)                     │
│  → 表示没有匹配的模板，需要自学习                                        │
│                                                                         │
│  ═══════════════════════════════════════════════════════════════════   │
│  阶段 1: 字段发现 + 动态模型生成 (LLM)                                  │
│  ═══════════════════════════════════════════════════════════════════   │
│                                                                         │
│  输入: 原始命令输出 (show ip mroute)                                    │
│  ────────────────────────────────────                                  │
│  (*, 239.1.1.1), 00:05:23/00:02:36, RP 10.0.0.1, flags: SPF            │
│    Incoming interface: GigabitEthernet0/1, RPF nbr 192.168.1.1         │
│    Outgoing interface list:                                            │
│      GigabitEthernet0/2, Forward, 00:05:23                             │
│                                                                         │
│  LLM 分析 Prompt:                                                       │
│  ────────────────                                                      │
│  分析以下网络命令输出，识别应该提取的关键字段:                           │
│                                                                         │
│  命令: show ip mroute                                                   │
│  平台: cisco_ios                                                        │
│  原始输出: [如上]                                                       │
│                                                                         │
│  要求:                                                                  │
│  1. 识别输出结构 (表格/树形/混合)                                       │
│  2. 识别所有有意义的字段 (组播组、源IP、接口等)                          │
│  3. 判断每个字段的数据类型 (IPv4、字符串、整数、枚举)                    │
│  4. 标注必填和可选字段                                                  │
│  5. 输出 Pydantic 模型定义                                              │
│                                                                         │
│  LLM 输出:                                                              │
│  ─────────                                                             │
│  ```python                                                              │
│  class McastRouteEntry(BaseModel):                                     │
│      """动态生成的组播路由模型."""                                      │
│      group_address: IPv4Address         # 组播组地址 (必填)             │
│      source_address: Optional[str]      # 源地址 (*表示任意)            │
│      rp_address: Optional[IPv4Address]  # RP 地址                      │
│      incoming_interface: str            # 入接口 (必填)                 │
│      rpf_neighbor: Optional[IPv4Address]# RPF 邻居                     │
│      outgoing_interfaces: list[str]     # 出接口列表 (必填)             │
│      flags: Optional[str]               # 标志位                       │
│      uptime: Optional[str]              # 存活时间                      │
│  ```                                                                   │
│                                                                         │
│  保存到: .olav/config/models/cisco_ios_show_ip_mroute.py               │
│                                                                         │
│  ═══════════════════════════════════════════════════════════════════   │
│  阶段 2: TextFSM 模板生成 + 验证 (ReAct)                                │
│  ═══════════════════════════════════════════════════════════════════   │
│                                                                         │
│  使用阶段 1 生成的 McastRouteEntry 模型作为约束                         │
│  → 执行标准的 ReAct 迭代循环 (见 0.6.8.3)                               │
│  → 验证提取结果满足动态模型                                             │
│                                                                         │
│  保存到: .olav/config/templates/cisco_ios_show_ip_mroute.textfsm       │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**知识沉淀结构**:
```
.olav/config/
├── models/                                  # 动态生成的 Pydantic 模型 🆕
│   ├── cisco_ios_show_ip_mroute.py         # 组播路由模型
│   ├── cisco_ios_show_ip_mroute.meta       # 元数据
│   ├── huawei_display_multicast_routing.py # 华为组播路由
│   └── index.json                          # 模型索引 (命令→模型映射)
│
├── templates/                               # TextFSM 模板
│   ├── cisco_ios_show_ip_mroute.textfsm
│   └── cisco_ios_show_ip_mroute.textfsm.meta
│
└── mappings/                                # 字段映射
    └── ...
```

**动态模型索引** (`index.json`):
```json
{
  "models": {
    "cisco_ios": {
      "show ip mroute": {
        "model_file": "cisco_ios_show_ip_mroute.py",
        "class_name": "McastRouteEntry",
        "generated_at": "2026-01-15T10:30:00",
        "quality_score": 0.92,
        "reviewed": false
      }
    }
  }
}
```

**动态加载代码**:
```python
import importlib.util
from pathlib import Path

def load_dynamic_model(platform: str, command: str) -> type[BaseModel] | None:
    """加载动态生成的 Pydantic 模型.
    
    Args:
        platform: 平台标识 (cisco_ios, huawei_vrp)
        command: 命令名称 (show ip mroute)
    
    Returns:
        Pydantic 模型类，或 None (触发阶段1)
    """
    # 规范化命令名称
    cmd_normalized = command.replace(" ", "_").replace("-", "_")
    model_file = Path(f".olav/config/models/{platform}_{cmd_normalized}.py")
    
    if not model_file.exists():
        return None  # 触发阶段1: 字段发现
    
    # 动态加载模块
    spec = importlib.util.spec_from_file_location("dynamic_model", model_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    # 从索引获取类名
    index = json.loads(Path(".olav/config/models/index.json").read_text())
    class_name = index["models"][platform][command]["class_name"]
    
    return getattr(module, class_name)
```

**完整触发流程**:
```python
async def self_learning_pipeline(
    platform: str,
    command: str,
    raw_output: str
) -> dict:
    """零知识自学习完整流程.
    
    Returns:
        {
            "template_path": ".olav/config/templates/...",
            "model_path": ".olav/config/models/...",
            "parsed_data": [...],
            "quality_score": 0.92
        }
    """
    # Step 1: 尝试加载已有模型
    constraint_model = load_dynamic_model(platform, command)
    
    # Step 2: 如果没有模型，进入阶段1 (字段发现)
    if constraint_model is None:
        constraint_model = await phase1_discover_fields(
            platform=platform,
            command=command,
            raw_output=raw_output
        )
        # 保存生成的模型
        save_dynamic_model(platform, command, constraint_model)
    
    # Step 3: 进入阶段2 (ReAct 模板生成)
    template, parsed_data, quality = await phase2_generate_template(
        platform=platform,
        command=command,
        raw_output=raw_output,
        constraint_model=constraint_model
    )
    
    return {
        "template_path": save_template(platform, command, template),
        "model_path": get_model_path(platform, command),
        "parsed_data": parsed_data,
        "quality_score": quality
    }
```

**阶段1 字段发现 Skill** (`.olav/skills/self-learning/field-discovery.md`):
```markdown
---
name: Field Discovery Agent
description: 分析未知命令输出，发现字段并生成 Pydantic 模型
version: 1.0
triggers:
  - 当 load_dynamic_model() 返回 None
  - 用户明确请求 "分析 {command} 输出"
outputs:
  - .olav/config/models/{platform}_{command}.py
  - .olav/config/models/{platform}_{command}.meta
---

# 字段发现流程

## 分析策略

1. **输出结构识别**:
   - 表格式 (show ip route, show interfaces)
   - 树形/层级 (show ip mroute, show spanning-tree)
   - 键值对 (show version)
   - 混合格式

2. **字段类型推断**:
   | 模式 | 类型 | 示例 |
   |------|------|------|
   | `\d+\.\d+\.\d+\.\d+` | IPv4Address | 10.0.0.1 |
   | `\d+\.\d+\.\d+\.\d+/\d+` | str (CIDR) | 10.0.0.0/24 |
   | `[A-Fa-f0-9:]+` | str (MAC) | 00:11:22:33:44:55 |
   | `\d+` | int | 65001 |
   | `\d+:\d+:\d+` | str (time) | 01:23:45 |
   | 大写单词 | Enum | ESTABLISHED, FULL |

3. **必填/可选判断**:
   - 每条记录都出现 → 必填
   - 部分记录出现 → Optional
   - 空值/缺失 → Optional

## 输出格式

生成符合 OLAV 规范的 Pydantic 模型文件
```

**约束验证代码**:
```python
from pydantic import ValidationError

def validate_template_output(
    parsed_data: list[dict],
    constraint_model: type[BaseModel],
    min_extraction_rate: float = 0.8
) -> tuple[bool, list[str]]:
    """验证模板输出是否满足 Pydantic 约束.
    
    Args:
        parsed_data: TextFSM 解析结果
        constraint_model: Pydantic 约束模型 (预定义或动态生成)
        min_extraction_rate: 最小提取成功率 (默认 80%)
    
    Returns:
        (is_valid, errors): 验证结果和错误列表
    """
    errors = []
    valid_count = 0
    
    for i, record in enumerate(parsed_data):
        try:
            constraint_model(**record)
            valid_count += 1
        except ValidationError as e:
            errors.append(f"Record {i}: {e.errors()}")
    
    extraction_rate = valid_count / len(parsed_data) if parsed_data else 0
    is_valid = extraction_rate >= min_extraction_rate
    
    return is_valid, errors
```

**ReAct 修复 Prompt**:
```
你生成的 TextFSM 模板存在以下问题:

问题: 缺少必填字段 'remote_as'
当前正则: ^BGP peer is ${NEIGHBOR}, remote AS
期望输出: {"neighbor_ip": "10.0.0.1", "remote_as": 65001, ...}
实际输出: {"neighbor_ip": "10.0.0.1"}

请修复模板，确保能提取 remote_as 字段。
只输出修改后的模板，不要解释。
```

#### 0.6.8.4 Skill 目录管理 (DeepAgents 架构) 🆕

**设计原则**: 自学习功能作为 Skill，放在 `.olav/skills/` 目录

```
.olav/
├── skills/
│   ├── data-collection/              # 数据采集相关 Skills
│   │   └── snapshot-collection.md    # 快照采集流程
│   │
│   ├── self-learning/                # 自学习 Skills 🆕
│   │   ├── field-discovery.md        # 阶段1: 字段发现 + 动态模型生成 🆕
│   │   ├── textfsm-generator.md      # 阶段2: TextFSM 模板生成
│   │   ├── field-mapping-learner.md  # 字段映射学习 Skill
│   │   └── template-optimizer.md     # 模板优化 Skill (用户反馈)
│   │
│   └── analysis/                     # 分析类 Skills
│       ├── health-check.md
│       └── troubleshooting.md
│
├── config/
│   ├── models/                       # 动态生成的 Pydantic 模型 🆕
│   │   ├── cisco_ios_show_ip_mroute.py
│   │   ├── cisco_ios_show_ip_mroute.meta
│   │   └── index.json               # 命令→模型映射索引
│   │
│   ├── templates/                   # TextFSM 模板
│   │   └── ...
│   │
│   └── mappings/                    # 字段映射
│       └── ...
│
├── knowledge/                        # 知识库
│   ├── network-protocols.md
│   └── vendor-specifics/
│       ├── cisco-ios.md
│       ├── huawei-vrp.md             # 华为特性文档
│       └── h3c-comware.md            # H3C 特性文档
│
└── config/
    ├── templates/                    # 生成的 TextFSM 模板 (Skill 产出)
    │   ├── huawei_show_bgp.textfsm
    │   └── huawei_show_bgp.textfsm.meta
    │
    └── mappings/                     # 生成的字段映射 (Skill 产出)
        └── huawei_bgp_neighbor.json
```

**Skill 文件示例** (`.olav/skills/textfsm-generator/SKILL.md`):
```markdown
---
name: TextFSM Template Generator
description: 使用 ReAct + Pydantic 生成并验证 TextFSM 模板
version: 1.0.0
intent: self-learning
complexity: advanced

triggers:
  automatic:
    - parse_success = false AND parse_error = "No template found"
  manual:
    - User query contains: "generate template", "create parser"
    
constraints:
  max_iterations: 5              # 最多重试 5 次
  min_extraction_rate: 0.8       # 最少提取 80% 记录
  require_human_review: true     # 生成后需人工审核
  
output:
  format: textfsm
  location: .olav/config/templates/
  metadata: true
---

# TextFSM 模板生成流程

## 触发条件
1. 用户明确请求生成模板
2. Netmiko use_textfsm=True 返回空结果 (无匹配模板)
3. 解析率低于阈值

## ReAct 流程

### Step 1: 分析原始输出
- 识别输出类型 (表格/列表/键值对/混合)
- 识别分隔符和对齐方式
- 识别关键数据字段

### Step 2: 确定目标约束
根据命令类型选择 Pydantic 约束模型:
- show ip bgp summary → BGPNeighborConstraint
- show ip ospf neighbor → OSPFNeighborConstraint
- show ip route → RouteEntryConstraint

### Step 3: 迭代生成
1. 生成初版模板
2. 解析原始输出
3. 验证 Pydantic 约束
4. 如失败，分析错误并修复
5. 重复直到成功或达到 max_iterations

### Step 4: 保存并标记
- 保存模板到 config/templates/
- 生成 .meta 文件记录质量分数
- 设置 `reviewed: false` 等待人工审核

## 约束模型

详见 `src/olav/core/normalized_models.py`
```

**用户管理优势**:
1. **透明**: 用户可查看完整的自学习逻辑
2. **可修改**: 用户可调整参数 (max_iterations, min_extraction_rate)
3. **可禁用**: 删除 Skill 文件即可禁用自学习
4. **可扩展**: 用户可添加自定义 Skill

#### 0.6.8.5 与字段映射自学习的协同

```
┌──────────────────────────────────────────────────────────────┐
│              完整的双层自学习流程                              │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Step 1: TextFSM 模板自学习 (解决"如何解析"问题)              │
│  ──────────────────────────────────────────────────────────  │
│  原始文本 → LLM 生成模板 → 解析 → 厂商特定JSON                │
│  "BGP peer..."  → template  → parse → {"NEIGHBOR": "10.0.0.1"} │
│                             ↓                                 │
│                      缓存到 config/templates/                │
│                                                              │
│  Step 2: 字段映射自学习 (解决"如何标准化"问题)                │
│  ──────────────────────────────────────────────────────────  │
│  厂商JSON → LLM 学习映射 → 标准化 → Pydantic 模型             │
│  {"NEIGHBOR"}  → mapping  → normalize → BGPNeighbor(neighbor_ip=...) │
│                            ↓                                 │
│                     缓存到 config/mappings/                  │
│                                                              │
└──────────────────────────────────────────────────────────────┘

优势:
  ✓ 覆盖任意设备: 华为/H3C/锐捷/深信服...
  ✓ 成本可控: 每个新命令首次 ~$0.01，后续免费
  ✓ 持续改进: 用户可审核并手动优化生成的模板
  ✓ 知识沉淀: 所有生成的模板成为企业知识资产
```

### 0.6.9 实施计划 (更新)

| Phase | 任务 | 工作量 | 优先级 |
|-------|------|--------|--------|
| **Phase 1** | 基础设施 | | **P0** |
| 1.1 | 使用 Netmiko `use_textfsm=True` | 1 小时 | ✅ 已完成 |
| 1.2 | 创建 `command_outputs` 单表存储 | 30 分钟 | ✅ 已完成 |
| 1.3 | 实现 `config/templates/` 自定义模板支持 | 1 小时 | ✅ 已完成 |
| **Phase 2** | 标准化层 | | **P1** |
| 2.1 | 定义 6 个核心 Pydantic 模型 | 1 小时 | ✅ 已完成 |
| 2.2 | 实现主流平台字段映射 (Cisco, Juniper, Arista) | 2 小时 | ✅ 已完成 |
| 2.3 | 创建标准化处理器 (normalizer.py) | 2 小时 | ✅ 已完成 |
| 2.4 | 创建标准化视图 (normalized_views.py) | 1 小时 | ✅ 已完成 |
| **Phase 3** | 智能增强 - Skill架构 (ReAct + Pydantic) | | **P2** |
| 3.1 | 创建 Skill 目录结构 (.olav/skills/self-learning/) | 30 分钟 | ⏳ 待开始 |
| 3.2 | 实现 Pydantic 约束模型 (template_constraints.py) | 1 小时 | ⏳ 待开始 |
| 3.3 | **实现 ReAct TextFSM 生成器 (迭代验证)** 🆕 | **4 小时** | ⏳ 待开始 |
| 3.4 | 编写 textfsm-generator.md Skill | 1 小时 | ⏳ 待开始 |
| 3.5 | 实现 LLM 字段映射学习 + 缓存 | 2 小时 | ⏳ 待开始 |
| 3.6 | 编写 field-mapping-learner.md Skill | 1 小时 | ⏳ 待开始 |
| 3.7 | 实现模板质量分数和审核工作流 | 1.5 小时 | ⏳ 待开始 |
| 3.8 | 支持 raw 文本直接 LLM 解析 (兜底) | 2 小时 | ⏳ 待开始 |
| **总计** | | **~21 小时** | |

**Phase 3 核心改进**:
- ✨ ReAct 迭代: 生成→验证→修复循环，成功率从 60% → 90%+
- ✨ Pydantic 约束: 明确的目标输出结构，验证有据可依
- ✨ Skill 管理: 用户可查看/修改/禁用自学习行为
- ✨ 质量审核: 生成的模板需人工审核后才正式启用

### 0.6.10 目录结构 (更新)

```
.olav/
├── skills/
│   ├── README_SELF_LEARNING.md         # 自学习 Skills 总览文档 🆕
│   ├── textfsm-generator/              # TextFSM 模板生成器 Skill 🆕
│   │   └── SKILL.md                    # ReAct + Pydantic 自动生成
│   ├── field-mapping-learner/          # 字段映射学习器 Skill 🆕
│   │   └── SKILL.md                    # LLM 学习字段映射
│   ├── health-check/                   # 健康检查 Skill
│   │   └── SKILL.md
│   ├── network-snapshot/               # 快照采集 Skill
│   │   └── SKILL.md
│   └── ...                             # 其他 Skills
│
├── knowledge/
│   └── vendor-specifics/               # 厂商特性知识库 🆕
│       ├── cisco-ios.md
│       ├── huawei-vrp.md               # 华为命令特性
│       └── h3c-comware.md              # H3C 命令特性
│
└── config/
    ├── templates/                      # 自定义 + LLM生成的 TextFSM 模板
    │   ├── index                       # 模板索引 (ntc-templates 格式)
    │   ├── huawei_show_bgp.textfsm    # LLM 生成的模板
    │   ├── huawei_show_bgp.textfsm.meta  # 元数据 (质量分数/审核状态)
    │   └── README.md
    │
    └── mappings/                       # LLM 学习的字段映射
        ├── huawei_bgp_neighbor.json
        └── README.md

config/                                  # 项目级配置 (与 .olav 分离)
└── templates/                          # 用户手动编写的模板 (优先级最高)
    └── custom_commands.textfsm

src/olav/core/
├── normalized_models.py                # 6 个 Pydantic 标准化模型 ✅
├── field_mappings.py                   # 内置字段映射表 ✅
├── normalizer.py                       # 标准化处理器 🔄
├── json_analyzer.py                    # JSON 结构分析 (Phase 3)
└── template_constraints.py             # Pydantic 约束模型 🆕 (Phase 3)
    ├── BGPNeighborConstraint           # BGP 模板输出约束
    ├── OSPFNeighborConstraint          # OSPF 模板输出约束
    └── validate_template_output()      # 验证函数

src/olav/tools/
├── template_generator.py               # LLM TextFSM 模板生成器 🆕 (Phase 3)
│   ├── TemplateGenerator              # 主类
│   ├── generate_with_react()          # ReAct 迭代生成
│   ├── validate_against_constraint()  # Pydantic 约束验证
│   ├── fix_template()                 # 错误修复
│   └── save_with_meta()               # 保存模板 + 元数据
│
└── skill_executor.py                   # Skill 执行器 🆕
    └── load_and_execute_skill()        # 加载并执行 .olav/skills/*.md
```

### 0.6.11 模板质量分数与审核

**元数据文件格式** (`*.textfsm.meta`):
```json
{
  "generated_at": "2026-01-15T10:30:00",
  "generator": "llm",
  "model": "claude-opus-4-20250514",
  "iterations": 3,
  "quality_score": 0.95,
  "extraction_rate": 1.0,
  "records_tested": 5,
  "fields_extracted": ["NEIGHBOR", "REMOTE_AS", "STATE", "UPTIME"],
  "constraint_model": "BGPNeighborConstraint",
  "reviewed": false,
  "reviewed_by": null,
  "reviewed_at": null,
  "notes": "Auto-generated, pending human review"
}
```

**质量分数计算**:
```python
quality_score = (
    extraction_rate * 0.4 +           # 提取成功率权重 40%
    field_completeness * 0.3 +        # 字段完整度权重 30%
    constraint_pass_rate * 0.3        # Pydantic 验证通过率 30%
)
```

**审核工作流**:
```
1. LLM 生成模板 → reviewed: false, quality_score: 0.95
2. 用户运行 `olav template review` → 显示待审核模板列表
3. 用户审核并确认 → reviewed: true, reviewed_by: "admin"
4. 或用户修改模板 → 重新计算 quality_score
```

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

---

## 8. 多专家路由器架构 (Multi-Expert Router)

**设计日期**: 2026-01-14  
**版本**: v0.8.5  
**状态**: 🔵 设计中

### 8.1 架构概览

```
                         ┌─────────────────────────┐
                         │    用户输入 (CLI/API)    │
                         └───────────┬─────────────┘
                                     ▼
                    ┌────────────────────────────────────┐
                    │       🎯 Query Router              │
                    │   (Guard + 意图分类 合一)           │
                    │                                    │
                    │ 1. 规则匹配 (YAML配置, 毫秒级)      │
                    │ 2. LLM意图分类 (复杂问题fallback)   │
                    └────────────┬───────────────────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
           ┌──────────────┐ ┌─────────┐ ┌─────────────┐
           │ 🚫 拒绝/提示  │ │ 📊 DB   │ │ /命令强制   │
           │ (Guard规则)  │ │ Expert  │ │ (分析等)    │
           └──────────────┘ └────┬────┘ └─────────────┘
                                 │
                                 ▼ (DB失败或数据不完整)
                           ┌──────────┐
                           │ 🔧 CLI   │
                           │ Expert   │
                           │ (SSH)    │
                           └──────────┘
```

### 8.2 核心设计原则

| 原则 | 说明 |
|------|------|
| **Guard即意图** | 安全检查本身就是意图分类的一种，不需要分开 |
| **规则优先** | 常见模式用YAML规则快速匹配，复杂问题才用LLM |
| **DB优先** | 所有网络信息查询先查DB，失败才回落CLI(SSH) |
| **统一DB** | 拓扑、快照、命令都在同一个UnifiedDatabase，不分专家 |
| **命令极简** | 斜杠命令仅用于系统管理，查询类由Agent tools处理 |
| **自然语言优先** | IP/健康/拓扑等查询通过自然语言触发DB Agent tools |

### 8.3 路由规则配置 (YAML)

**文件路径**: `.olav/config/routing_rules.yaml`

```yaml
# OLAV Query Router Configuration
# 规则优先级: guard > slash_commands > patterns > llm_fallback

version: "1.0"

# =============================================================================
# Guard Rules (安全守卫 - 最高优先级)
# =============================================================================
guard:
  # 危险命令黑名单 - 直接拒绝
  blacklist_patterns:
    - pattern: "(reload|reboot|erase|delete|format|write erase)"
      action: reject
      message: "⛔ 危险命令被阻止: {matched}"
    
    - pattern: "(shutdown|no shutdown) (?!interface)"
      action: reject  
      message: "⛔ 全局shutdown命令被阻止"
    
    - pattern: "(copy|tftp|scp).*(startup|running)"
      action: require_approval
      message: "⚠️ 配置变更需要审批"

  # 敏感信息查询 - 需要确认
  sensitive_queries:
    - pattern: "(password|secret|key|credential)"
      action: require_approval
      message: "⚠️ 敏感信息查询需要确认"

# =============================================================================
# Slash Commands (斜杠命令 - 仅系统管理和强制工作流)
# =============================================================================
# 
# 设计原则:
# - 查询类需求通过自然语言触发DB Agent tools
# - 斜杠命令仅用于: 系统管理 + 强制触发复杂工作流
# - 不添加: /ip, /health, /summary, /topology, /path (都由DB tools处理)
#
slash_commands:
  # 故障诊断 - 触发完整诊断工作流
  "/analyze":
    expert: "analysis"
    description: "故障诊断与健康分析 (强制工作流)"
    subagents:
      - "macro-analyzer"  # 全局健康分析
      - "micro-analyzer"  # 具体故障定位
    usage: "/analyze [device|all] [--error <description>]"
    examples:
      - "/analyze R1"           # 诊断R1
      - "/analyze all"          # 全网健康分析
      - "/analyze R1 --error 'BGP down'"  # 带错误描述

# =============================================================================
# Pattern Matching (模式匹配 - 规则驱动路由)
# =============================================================================
patterns:
  # DB优先的查询模式
  database_first:
    - pattern: "(ip|地址).*(在哪|位置|where|location)"
      tool: "find_ip_location"
      extract: "ip_address"  # 从输入提取参数
    
    - pattern: "(设备|device).*(健康|状态|health|status)"
      tool: "get_device_health"
      extract: "device_name"
    
    - pattern: "(网络|network).*(概览|统计|summary|overview)"
      tool: "get_network_summary"
    
    - pattern: "(拓扑|topology|邻居|neighbor|path|路径)"
      tool: "query_topology"  # 统一拓扑查询入口
    
    - pattern: "(arp|mac|接口|interface|路由|route|bgp|ospf)"
      tool: "query_database"  # 通用DB查询
      fallback: "cli"  # DB失败后回落CLI

  # 明确需要CLI的模式 (实时数据)
  cli_required:
    - pattern: "(实时|real-?time|当前|current|now)"
      expert: "cli"
      reason: "用户明确要求实时数据"
    
    - pattern: "(执行|run|show).*(命令|command)"
      expert: "cli"
      reason: "用户要求执行特定命令"

# =============================================================================
# Fallback Strategy (回落策略)
# =============================================================================
fallback:
  # DB查询失败时的处理
  database_failure:
    action: "fallback_to_cli"
    message: "📊 数据库无结果，正在通过SSH查询设备..."
  
  # 数据不完整时的处理
  incomplete_data:
    threshold: 0.7  # 完整度阈值
    action: "supplement_with_cli"
    message: "📊 数据可能不完整，正在补充最新信息..."
  
  # 无法匹配任何规则
  no_match:
    action: "llm_classify"  # 使用LLM进行意图分类
    allowed_intents:
      - "database_query"
      - "cli_query"
      - "general_question"
    # 注意: 不允许LLM路由到analysis，必须用/命令

# =============================================================================
# Expert Definitions (专家定义)
# =============================================================================
experts:
  database:
    description: "数据库专家 - 历史数据、统计、拓扑"
    tools:
      - find_ip_location
      - get_device_health
      - get_network_summary
      - search_ip_across_network
      - analyze_network_health
      - query_database
      - show_topology
      - query_path
      - query_neighbors
    priority: 1  # 最高优先级

  cli:
    description: "CLI专家 - 实时SSH查询"
    tools:
      - smart_query       # SSH单设备查询
      - nornir_execute    # SSH批量执行
      # 注: list_devices, search_capabilities 已移至 DB 专家
      # CLI专家仅保留SSH相关工具
    priority: 2  # DB失败后使用

  analysis:
    description: "分析专家 - 故障诊断、健康分析、根因定位"
    tools:
      # 分析专家也可访问数据库工具，实现数据驱动分析
      - find_ip_location
      - get_device_health
      - get_network_summary
      - analyze_network_health
      - query_database
      - query_topology
    subagents:
      - macro-analyzer  # 全局健康评估
      - micro-analyzer  # 具体故障定位
    trigger: "slash_command_only"  # 仅通过/命令触发
    commands:
      - /analyze  # 唯一入口，合并原/diagnose功能
```

---

## 0.7 技术借鉴: PraisonAI 工具评估 (2026-01-15) 🆕

**评估日期**: 2026-01-15  
**评估对象**: PraisonAI DuckDB Tools + JSON Tools  
**结论**: 不直接使用，但可借鉴部分设计思路

### 0.7.1 评估结果摘要

| 工具 | 核心功能 | OLAV 适用性 | 推荐 |
|------|---------|------------|------|
| **DuckDB Tools** | CSV 加载 + SQL 查询 | ❌ 数据源不匹配 (CSV vs TextFSM JSON) | 不使用 |
| **JSON Tools** | 文件读写、合并、Schema验证、结构分析 | ⚠️ 部分借鉴 | 借鉴思路 |

### 0.7.2 PraisonAI DuckDB Tools - 不适用

**功能清单**:
- `execute_query(query)` - 执行 SQL 查询
- `load_csv(table, filepath)` - 加载 CSV 到表
- `export_csv(query, filepath)` - 导出查询结果

**不适用原因**:
1. **数据源差异**: PraisonAI 面向 CSV，OLAV 面向 Netmiko TextFSM → JSON
2. **缺少 JSON 列支持**: OLAV 核心是 DuckDB JSON 函数 (`json_extract`, `UNNEST`)
3. **无网络语义**: 缺少设备/快照/拓扑/平台概念

### 0.7.3 PraisonAI JSON Tools - 可借鉴

**可借鉴功能**:

#### 1. `analyze_json(data)` - 结构分析 ✅

**用途**: 自动发现未知平台的 JSON 字段结构，支持 LLM 自学习

```python
# PraisonAI 输出示例
{
  'structure': {
    'type': 'list',
    'length': 2,
    'keys': ['NEIGHBOR', 'AS', 'STATE'],  # ← 对OLAV有用!
    'sample_elements': [...]
  }
}
```

**OLAV Phase 3 应用** (LLM 自学习):
- 当遇到新平台时，自动分析 TextFSM 输出字段
- 生成字段映射建议
- 辅助 LLM 学习字段语义

**轻量级实现** (约 50 行):
```python
# src/olav/tools/json_analyzer.py (Phase 3)
def analyze_textfsm_output(data: list[dict]) -> dict:
    """分析 TextFSM 输出的字段结构，用于 LLM 自学习."""
    if not data:
        return {"fields": [], "sample": None}
    
    sample = data[0]
    return {
        "fields": list(sample.keys()),  # ['NEIGHBOR', 'AS', 'STATE', ...]
        "field_types": {k: type(v).__name__ for k, v in sample.items()},
        "row_count": len(data),
        "sample": sample
    }
```

#### 2. `validate_json(data, schema)` - Schema 验证 ✅

**用途**: 验证标准化后的数据符合 Pydantic 模型

```python
# OLAV Phase 2 应用 (标准化验证)
bgp_schema = {
    "type": "object",
    "required": ["neighbor_ip", "remote_as", "state"],
    "properties": {
        "neighbor_ip": {"type": "string", "format": "ipv4"},
        "remote_as": {"type": "integer"},
        "state": {"type": "string", "enum": ["Established", "Idle", "Active"]}
    }
}
```

**集成方式**: 在 Pydantic 模型中使用 `jsonschema` 验证

### 0.7.4 实施建议

| Phase | 借鉴内容 | 实施方式 |
|-------|---------|---------|
| **Phase 2** | Schema 验证思路 | 在 Pydantic 模型中集成验证 |
| **Phase 3** | `analyze_json()` 思路 | 实现轻量级 `json_analyzer.py` (~50行) |
| **Agent 集成** | `@tool` 装饰器模式 | 工具注册方式参考 |

### 0.7.5 不采纳的功能

| 功能 | 原因 |
|------|------|
| `read_json()` / `write_json()` | 已有 `data_importer.py` 处理 |
| `merge_json()` | 不需要合并 JSON 文件 |
| `transform_json()` | 使用 DuckDB JSON 函数在数据库层面操作 |
| 完整 PraisonAI Agent 框架 | 与 OLAV DeepAgents 架构冲突 |

---

### 8.4 实现架构

```
src/olav/core/
├── query_router.py          # 路由器核心
│   ├── QueryRouter          # 主类
│   ├── load_routing_rules() # 加载YAML规则
│   ├── match_guard()        # Guard检查
│   ├── match_pattern()      # 模式匹配
│   └── route_query()        # 路由决策
│
├── unified_database.py      # 统一数据库 (已实现)
│   └── UnifiedDatabase      # 包含拓扑、快照、命令
│
├── normalized_models.py     # Phase 2 - Pydantic模型 (待开发)
│   └── 6个标准化模型        # BGPNeighbor, OSPFNeighbor, etc.
│
├── field_mappings.py        # Phase 2 - 字段映射表 (待开发)
│   └── FIELD_MAPPINGS       # 跨厂商字段映射
│
├── json_analyzer.py         # Phase 3 - JSON结构分析 (计划)
│   └── analyze_textfsm_output()  # 借鉴PraisonAI思路
│
└── subagent_configs.py      # 专家配置 (已实现)
    ├── get_macro_analyzer()
    └── get_micro_analyzer()

.olav/config/
└── routing_rules.yaml       # 路由规则配置
```

### 8.5 路由流程

```python
class QueryRouter:
    """问题路由器 - Guard + 意图分类合一."""
    
    def route(self, user_input: str) -> RoutingDecision:
        """路由用户输入到合适的专家."""
        
        # Step 1: Guard检查 (最高优先级)
        guard_result = self.check_guard(user_input)
        if guard_result.action == "reject":
            return RoutingDecision(expert=None, action="reject", message=guard_result.message)
        if guard_result.action == "require_approval":
            return RoutingDecision(expert=None, action="approve", message=guard_result.message)
        
        # Step 2: 斜杠命令检查
        if user_input.startswith("/"):
            return self.handle_slash_command(user_input)
        
        # Step 3: 模式匹配 (规则驱动)
        pattern_match = self.match_patterns(user_input)
        if pattern_match:
            return RoutingDecision(
                expert=pattern_match.expert,
                tool=pattern_match.tool,
                params=pattern_match.extracted_params,
                fallback=pattern_match.fallback
            )
        
        # Step 4: LLM意图分类 (仅限query，不允许analysis)
        intent = self.llm_classify(user_input, allowed=["database_query", "cli_query", "general"])
        return self.route_by_intent(intent)
```

### 8.6 DB优先 + CLI回落

```python
async def execute_with_fallback(self, decision: RoutingDecision, user_input: str) -> str:
    """执行查询，DB失败时回落到CLI."""
    
    if decision.expert == "database":
        # 尝试DB查询
        try:
            result = await self.db_expert.execute(decision.tool, decision.params)
            
            # 检查数据完整性
            if self.is_data_complete(result):
                return result
            else:
                # 数据不完整，补充CLI查询
                cli_result = await self.cli_expert.supplement(decision.params)
                return self.merge_results(result, cli_result)
                
        except DatabaseError:
            # DB失败，回落到CLI
            if decision.fallback == "cli":
                return await self.cli_expert.execute(user_input)
            else:
                return "❌ 数据库查询失败，请稍后重试"
    
    elif decision.expert == "cli":
        return await self.cli_expert.execute(user_input)
```

### 8.7 斜杠命令清单 (简化版)

#### 保留的命令

| 命令 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `/devices` | 系统 | 列出设备清单 | `/devices` |
| `/skills` | 系统 | 列出可用技能 | `/skills` |
| `/analyze` | 工作流 | 故障诊断与健康分析 ⚠️ | `/analyze R1` |
| `/search` | 系统 | 搜索知识库 | `/search bgp troubleshoot` |
| `/reload` | 系统 | 重新加载配置 | `/reload` |
| `/clear` | 系统 | 清空对话历史 | `/clear` |
| `/history` | 系统 | 查看对话历史 | `/history` |
| `/help` | 系统 | 显示帮助 | `/help` |
| `/quit` | 系统 | 退出程序 | `/quit` |

> ⚠️ `/analyze` 是唯一的工作流命令，触发完整诊断流程

#### 已删除的命令

| 命令 | 原因 | 替代方案 |
|------|------|----------|
| `/inspect` | 合并到snapshot | 使用 `olav snapshot` |
| `/query` | 冗余 | 直接用自然语言提问 |
| `/backup` | 合并到snapshot | 使用 `olav snapshot` |

#### 不添加的命令

| 命令 | 原因 | 替代方案 |
|------|------|----------|
| `/ip` | DB Agent已提供 | "10.1.12.1在哪个设备?" |
| `/health` | DB Agent已提供 | "R1的健康状态如何?" |
| `/summary` | DB Agent已提供 | "网络概览" |
| `/topology` | DB Agent已提供 | "显示拓扑" |
| `/path` | DB Agent已提供 | "R1到R5的路径" |
| `/diagnose` | 合并到/analyze | `/analyze R1 --error 'xxx'` |

### 8.8 为什么这样设计

| 问题 | 解决方案 | 理由 |
|------|----------|------|
| Guard和意图分开？ | 合并 | Guard就是意图的一种，检查后直接路由 |
| 为什么YAML规则？ | 规则快速+可配置 | 毫秒级匹配，无需LLM推理，易于维护 |
| 为什么DB优先？ | 历史数据足够 | SSH耗时长，DB查询毫秒级 |
| 拓扑单独专家？ | 不需要 | 拓扑数据在同一个UnifiedDatabase |
| 为什么删除/ip等命令？ | 极简化 | DB Agent tools已提供相同功能，用自然语言更直观 |
| 为什么合并/diagnose？ | 统一入口 | /analyze一个命令覆盖健康分析+故障诊断 |
| 自然语言触发分析？ | 不允许 | 分析任务重，必须用户明确意图 |
| LLM什么时候用？ | 仅fallback | 规则无法匹配时才用LLM分类 |

### 8.9 实现计划

```
Phase 1: 基础路由 (Day 1)
├── 创建 routing_rules.yaml
├── 实现 QueryRouter 核心
└── 集成到 CLI

Phase 2: 命令清理 (Day 1)
├── 删除 /inspect, /query, /backup 命令
├── 修改 /analyze 为故障诊断入口
└── 更新 /help 帮助信息

Phase 3: DB回落机制 (Day 2)
├── 实现数据完整性检查
├── 实现CLI补充查询
└── E2E测试验证

Phase 4: 未来扩展
├── API Expert (外部系统)
├── 更多Guard规则
└── 学习型规则优化
```

### 8.10 与现有架构的关系

```
当前架构:
  CLI → Agent → tools[] → 执行

新架构:
  CLI → QueryRouter → Agent/Expert → tools[] → 执行
              │
              ├─ Guard (规则拒绝/审批)
              ├─ 斜杠命令 (直接路由)
              ├─ 模式匹配 (规则路由)
              └─ LLM分类 (fallback)
```

**兼容性**: QueryRouter 作为前置层，不影响现有 Agent 和 tools 实现。
---

## 9. 实施状态 (Implementation Status)

### 9.1 Phase 1: Nornir + TextFSM 集成 ✅

**完成日期**: 2026-01-14  
**测试状态**: 全部通过

| 组件 | 文件 | 测试 | 状态 |
|------|------|------|------|
| 网络执行器 | `src/olav/tools/network.py` | E2E | ✅ |
| 命令输出表 | `command_outputs` table | 手动 | ✅ |
| TextFSM 解析 | `use_textfsm=True` | 验证 | ✅ |

**关键成果**:
- Nornir 原生集成 TextFSM（`use_textfsm=True`）
- `command_outputs` 表统一存储原始+解析数据
- 支持 134 个 ntc-templates 模板
- 架构简化 90%，删除专用解析器

### 9.2 Phase 2: 标准化层 ✅

**完成日期**: 2026-01-14  
**测试状态**: 32/32 tests passed

| 组件 | 文件 | 行数 | 测试 | 状态 |
|------|------|------|------|------|
| 标准化模型 | `normalized_models.py` | ~400 | - | ✅ |
| 字段映射 | `field_mappings.py` | ~250 | - | ✅ |
| 标准化器 | `normalizer.py` | ~350 | 21/21 | ✅ |
| 标准化视图 | `normalized_views.py` | ~300 | 11/11 | ✅ |

**关键成果**:
- 6 个 Pydantic 标准化模型（BGP, OSPF, Route, CDP, Interface, 拓扑）
- 3 个厂商字段映射（Cisco, Juniper, Arista）
- 自动标准化引擎（验证 + 类型转换）
- 5 个标准化视图（按网络协议分类）

### 9.3 Phase 3: 智能增强层 ✅

**完成日期**: 2026-01-15  
**测试状态**: 62/62 tests passed

#### Phase 3.1: Skill 目录结构 ✅

| 组件 | 文件 | 状态 |
|------|------|------|
| TextFSM 生成器 Skill | `.olav/skills/textfsm-generator/SKILL.md` | ✅ |
| 字段映射学习器 Skill | `.olav/skills/field-mapping-learner/SKILL.md` | ✅ |
| 文档 | `.olav/skills/README_SELF_LEARNING.md` | ✅ |

#### Phase 3.2: 约束验证模型 ✅

| 组件 | 文件 | 行数 | 测试 | 状态 |
|------|------|------|------|------|
| 模板约束 | `template_constraints.py` | ~600 | 25/25 | ✅ |

**功能**:
- 6 个 Pydantic 约束模型（BGP, OSPF, Route, CDP, Interface, ARP）
- 质量评分公式：`extraction_rate * 0.4 + field_completeness * 0.3 + constraint_pass_rate * 0.3`
- 动态约束支持（未知数据类型）
- 验证引擎 + 质量计算

#### Phase 3.3: ReAct TextFSM 生成器 ✅

| 组件 | 文件 | 行数 | 测试 | 状态 |
|------|------|------|------|------|
| 模板生成器 | `template_generator.py` | ~520 | 16/16 | ✅ |

**功能**:
- ReAct 循环（推理 + 行动，最多 5 次迭代）
- 输出结构分析（列检测、位置识别）
- LLM 提示工程（初始生成 + 增量优化）
- 约束验证集成（Pydantic 验证）
- 模板保存 + 元数据（质量分数、迭代次数）

**工作流程**:
```
1. 分析输出结构 → 检测表格、列、分隔符
2. 创建初始提示 → 包含结构提示
3. LLM 生成模板 → 提取 TextFSM 代码
4. 解析测试 → TextFSM 验证
5. 约束验证 → Pydantic 检查（可选）
6. 计算质量分数 → extraction_rate, field_completeness, constraint_pass_rate
7. 未达标？→ 分析错误 + 创建优化提示 → 重复步骤 3-6
8. 达标或达到最大迭代 → 保存模板
```

#### Phase 3.4: 字段映射学习器 ✅

| 组件 | 文件 | 行数 | 测试 | 状态 |
|------|------|------|------|------|
| 字段映射器 | `field_mapper.py` | ~450 | 21/21 | ✅ |

**功能**:
- LLM 语义匹配（理解字段含义）
- 置信度评分（0.0-1.0）
- 映射缓存（避免重复调用 LLM）
- Schema 自动检测（命令 → 模型）
- 样本值支持（增强上下文）

**映射流程**:
```
1. 提取目标 Schema 字段 → 从 Pydantic 模型获取字段描述
2. 创建映射提示 → 包含命令、平台、字段列表、样本值
3. LLM 语义匹配 → 返回 JSON 映射结果
4. 解析响应 → 验证字段有效性
5. 过滤低置信度 → min_confidence 阈值（默认 0.7）
6. 缓存结果 → 避免重复调用
```

**质量保证**:
- 无效目标字段 → 置信度设为 0.0
- JSON 解析失败 → 返回空映射
- 支持 Markdown 代码块 → 提取纯 JSON
- 缓存键唯一性 → `platform:command:schema:fields`

### 9.4 测试覆盖率总结

| Phase | 组件 | 测试数 | 通过率 | 覆盖率 |
|-------|------|--------|--------|--------|
| Phase 2 | 标准化层 | 32 | 100% | 完整 |
| Phase 3.2 | 约束模型 | 25 | 100% | 完整 |
| Phase 3.3 | 模板生成器 | 16 | 100% | 完整 |
| Phase 3.4 | 字段映射器 | 21 | 100% | 完整 |
| **总计** | **Phase 2+3** | **94** | **100%** | **完整** |

### 9.5 架构集成示意图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    DB Federation v0.8.4 架构                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Layer 1: 原始数据层                                                    │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ Nornir + TextFSM → command_outputs table                       │    │
│  │ - platform, command, device_name, raw_output, parsed_output    │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                              ↓                                          │
│  Layer 2: 标准化层 (Phase 2) ✅                                         │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ Normalizer + FieldMappings                                     │    │
│  │ - 6 Pydantic 模型 (BGP, OSPF, Route, CDP, Interface, 拓扑)     │    │
│  │ - 3 厂商映射 (Cisco, Juniper, Arista)                          │    │
│  │ - 自动验证 + 类型转换                                           │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                              ↓                                          │
│  Layer 2.5: 智能增强层 (Phase 3) ✅                                     │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ 自学习能力（事件驱动）                                          │    │
│  │                                                                 │    │
│  │ 1. TextFSM 模板生成器 (template_generator.py)                  │    │
│  │    触发器: 新命令输出 && 无 TextFSM 模板                        │    │
│  │    ReAct: 分析结构 → 生成模板 → 验证 → 优化 (最多5次)          │    │
│  │    约束: Pydantic 验证 (template_constraints.py)               │    │
│  │    质量: extraction * 0.4 + completeness * 0.3 + constraint * 0.3│  │
│  │                                                                 │    │
│  │ 2. 字段映射学习器 (field_mapper.py)                             │    │
│  │    触发器: 新厂商字段 && 无映射规则                             │    │
│  │    LLM: 语义匹配 (字段名 + 样本值 → 标准化字段)                 │    │
│  │    置信度: 0.0-1.0 (min_confidence=0.7)                        │    │
│  │    缓存: platform:command:schema:fields                        │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                              ↓                                          │
│  Layer 3: 视图层                                                        │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ Normalized Views (normalized_views.py)                         │    │
│  │ - v_bgp_neighbors, v_ospf_neighbors, v_routes                  │    │
│  │ - v_interfaces, v_topology_map                                 │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 9.6 下一步计划：Phase 4 集成测试

**目标**: 端到端验证与生产就绪

#### Phase 4.1: 集成测试 (预计 1 天)

- [ ] **E2E Workflow 测试**
  - 新命令 → TextFSM 生成 → 解析 → 标准化 → 视图
  - 新厂商 → 字段映射学习 → 标准化 → 验证
  - 质量评分 → 迭代优化 → 达标/失败

- [ ] **性能测试**
  - LLM 调用延迟（template_generator, field_mapper）
  - 缓存命中率（field_mapper）
  - 大批量数据标准化（1000+ 记录）

- [ ] **容错测试**
  - LLM 返回无效 JSON → 降级处理
  - TextFSM 解析失败 → 回退原始数据
  - 约束验证失败 → 记录警告但不阻塞

#### Phase 4.2: 文档完善 (预计 0.5 天)

- [ ] 更新 `README.md` - Phase 3 功能说明
- [ ] 创建 `docs/SELF_LEARNING_GUIDE.md` - 自学习配置指南
- [ ] 更新 `docs/QUICKSTART_V0.8.md` - 包含新功能演示

#### Phase 4.3: 部署准备 (预计 0.5 天)

- [ ] CI/CD 集成 - 运行 Phase 2+3 测试（94 tests）
- [ ] 依赖锁定 - `uv.lock` 更新
- [ ] 环境变量配置 - LLM API Keys, TextFSM 路径
- [ ] Docker 镜像更新 - 包含 Phase 3 代码

### 9.7 已知限制与优化方向

#### 当前限制

1. **LLM 依赖**
   - template_generator 和 field_mapper 需要 LLM API
   - 离线环境需要预生成模板和映射

2. **质量阈值调优**
   - 默认 `min_quality_score=0.8` 可能过严或过松
   - 需要根据实际数据调整

3. **厂商覆盖**
   - 当前仅支持 Cisco, Juniper, Arista
   - 新厂商需手动添加映射或等待自学习

#### 优化方向

1. **批量生成优化**
   - 并行调用 LLM（多个命令同时生成模板）
   - 异步处理 + 结果聚合

2. **知识库持久化**
   - 将学习到的模板和映射存储到 `knowledge.db`
   - 支持版本控制和回滚

3. **质量监控仪表板**
   - 可视化模板质量分布
   - 标识需要人工优化的低质量模板

4. **主动学习**
   - 用户反馈 → 重新训练映射置信度
   - A/B 测试不同提示策略

---