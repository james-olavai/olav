# 数据管道详细问题诊断

## 🔍 问题确认

### 当前数据流缺口

```
┌─────────────────────────────────────────────────────────────┐
│                    CURRENT ARCHITECTURE                      │
└─────────────────────────────────────────────────────────────┘

网络设备
  ↓ (命令执行)
Raw数据 (data/sync/2026-01-13/raw/*.txt)
  ├→ sync_tools.py::_parse_with_textfsm()
  │    ↓
  │    ✅ Parsed JSON 已生成 (data/sync/2026-01-13/parsed/*.json)
  │         - show-cdp-neighbors.json
  │         - show-ospf-neighbors.json
  │         - show-bgp-summary.json
  │         - 等等...
  │
  └→ ❌ DEAD END: Parsed数据没有被导入数据库!
  
topology_tools.py::discover_topology()
  ├→ 执行 show cdp neighbors 命令 (重复!)
  │    ↓
  ├→ 调用 _parse_cdp_lldp_output() (用不同的解析器!)
  │    ↓
  └→ INSERT INTO topology_links (直接从命令输出)
       
数据库 (.olav/data/topology.db)
  └→ 收到的数据格式不标准:
     - remote_device: "Neighbor" 或 "3.3.3.3" ❌
     - 缺少 local_port, remote_port
     - 重复的数据
```

## 📊 数据质量问题详情

### 问题1: 重复的命令执行

**流程**:
1. sync_tools.py 执行 `show cdp neighbors` → raw/R1/show-cdp-neighbors.txt
2. sync_tools.py 解析 → parsed/R1/show-cdp-neighbors.json ✅
3. topology_tools.py **再次执行** `show cdp neighbors` ❌
4. topology_tools.py 再次解析 → INSERT数据库

**后果**:
- 📈 网络流量浪费 (重复查询)
- ⚠️ 数据不一致风险
- ⏱️ 性能降低

### 问题2: 两个不兼容的解析器

#### sync_tools.py 的解析器输出:
```json
{
  "device_id": "R3.local",      // ← 字段名
  "local_intrfce": "Gig 2",     // ← 拼写
  "port_id": "Eth 0/0",
  "capability": "R S I"
}
```

#### topology_tools.py 的解析器输出:
```python
{
    "remote_device": "R3.local",   # ← 不同的字段名
    "local_port": "Gig 2",         # ← 不同的字段名
    "remote_port": "Eth 0/0",
    "protocol": "CDP",
    "metadata": {"raw_line": "..."}
}
```

**SQL Schema期望**:
```sql
CREATE TABLE topology_links (
    local_device VARCHAR NOT NULL,    -- 如: "R1"
    remote_device VARCHAR NOT NULL,   -- 如: "R3" ⚠️ 现在是IP或"Neighbor"
    local_port VARCHAR,               -- 如: "Gi0/0"
    remote_port VARCHAR,              -- 如: "Gi0/1"
    layer VARCHAR,                    -- "L1", "L3"
    protocol VARCHAR,                 -- "CDP", "OSPF", "BGP"
    metadata VARCHAR,
    discovered_at TIMESTAMP
)
```

### 问题3: 数据库中的格式错误

**当前数据库中的OSPF链接**:
```
local_device → "R1"
remote_device → "Neighbor"     ❌ 应该是 "R3"
local_port → NULL             ❌ 应该有值
remote_port → NULL            ❌ 应该有值
protocol → "OSPF"
layer → "L3"
```

**错误原因** - 查看 topology_tools.py:275行:
```python
neighbors = _parse_ospf_output(result.output, platform)

for neighbor in neighbors:
    conn.execute(
        """INSERT INTO topology_links
        (local_device, local_port, remote_device, remote_port,
         layer, protocol, metadata, discovered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            device,
            neighbor.get("local_port"),        # ← 通常是None
            neighbor.get("remote_device"),     # ← 可能是IP,不是设备名
            None,                              # ← remote_port 总是None
            "L3",
            "OSPF",
            json.dumps(neighbor.get("metadata", {})),
            datetime.now(),
        ],
    )
```

## 🎯 三个关键问题的根本原因

### 问题1: Parsed JSON没有被导入数据库

**根本原因**: 
- sync_tools.py 生成 parsed/*.json (✅)
- 但没有代码读取这些文件 (❌)
- topology_tools.py 有自己的发现逻辑，不依赖parsed数据

**应该的行为**:
```python
# 应该存在的代码 (现在不存在!)
def import_parsed_topology_data(sync_dir: Path):
    """从sync的parsed目录导入已解析的拓扑数据"""
    for device_dir in sync_dir.glob("parsed/*/"):
        # 读取 show-cdp-neighbors.json
        # 读取 show-ospf-neighbors.json
        # 读取 show-bgp-summary.json
        # INSERT到topology_links表
```

### 问题2: 没有双引擎验证

**现状**:
- 只有一个TextFSM/正则表达式解析器
- 没有LLM验证
- 没有交叉检查

**应该的架构**:
```python
def parse_with_validation(raw_output: str):
    # Engine 1: 规则/TextFSM解析
    rules_result = parse_with_rules(raw_output)
    
    # Engine 2: LLM解析
    llm_result = parse_with_llm(raw_output)
    
    # Engine 3: 验证和合并
    if are_compatible(rules_result, llm_result):
        return rules_result  # 或 llm_result
    else:
        log_warning(f"解析结果不一致!")
        return choose_more_reliable(rules_result, llm_result)
```

### 问题3: 数据格式问题

**根本原因**:
- OSPF/BGP解析器的输出不标准
- `remote_device` 有时是IP地址，不是设备名
- 缺少接口信息

## 💡 推荐解决方案优先级

### 🔴 第1阶段 - 立即修复 (1-2天)

创建 `src/olav/tools/topology_importer.py`:

```python
from pathlib import Path
import json
import duckdb

class TopologyImporter:
    """从已解析的JSON导入拓扑数据到数据库"""
    
    def import_from_sync_dir(self, sync_dir: Path):
        """从sync目录导入parsed拓扑数据"""
        conn = init_topology_db()
        
        for device_dir in sync_dir.glob("parsed/*/"):
            device_name = device_dir.name
            
            # 导入CDP/LLDP数据
            cdp_file = device_dir / "show-cdp-neighbors.json"
            if cdp_file.exists():
                self._import_cdp_data(conn, device_name, cdp_file)
            
            # 导入OSPF数据
            ospf_file = device_dir / "show-ip-ospf-neighbors.json"
            if ospf_file.exists():
                self._import_ospf_data(conn, device_name, ospf_file)
            
            # 导入BGP数据
            bgp_file = device_dir / "show-ip-bgp-summary.json"
            if bgp_file.exists():
                self._import_bgp_data(conn, device_name, bgp_file)
        
        conn.close()
    
    def _import_cdp_data(self, conn, device_name: str, json_file: Path):
        """导入CDP邻接数据"""
        data = json.loads(json_file.read_text())
        
        for neighbor in data.get("data", []):
            # 规范化数据
            remote_device = self._extract_device_name(neighbor["device_id"])
            
            conn.execute(
                """INSERT INTO topology_links
                (local_device, remote_device, local_port, remote_port, 
                 layer, protocol, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    device_name,
                    remote_device,  # ✅ 使用设备名，不是IP
                    neighbor["local_intrfce"],
                    neighbor["port_id"],
                    "L1",
                    "CDP",
                    datetime.now(),
                ]
            )
    
    @staticmethod
    def _extract_device_name(device_id: str) -> str:
        """从device_id提取规范的设备名"""
        # "R3.local" → "R3"
        return device_id.split(".")[0]
```

### 🟠 第2阶段 - 数据质量改进 (2-3天)

添加验证和清理:

```python
class TopologyValidator:
    """拓扑数据验证器"""
    
    def validate_link(self, link: dict) -> tuple[bool, list[str]]:
        """验证单个链接的完整性"""
        errors = []
        
        # 检查必需字段
        if not link.get("local_device"):
            errors.append("缺少local_device")
        if not link.get("remote_device"):
            errors.append("缺少remote_device")
        if not link.get("protocol"):
            errors.append("缺少protocol")
        
        # 检查设备名格式 (应该是字母+数字，不是IP)
        if self._is_ip_address(link.get("remote_device", "")):
            errors.append(f"remote_device是IP地址: {link['remote_device']}")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def _is_ip_address(s: str) -> bool:
        """检查是否是IP地址"""
        parts = s.split(".")
        if len(parts) != 4:
            return False
        return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)
```

### 🟡 第3阶段 - 双引擎验证 (1周)

实现LLM + 规则验证:

```python
class DualEngineParser:
    """双引擎拓扑解析器"""
    
    def parse_cdp_output(self, raw_output: str) -> dict:
        """使用两个引擎解析CDP输出"""
        
        # Engine 1: 规则解析
        rules_result = self._parse_with_rules(raw_output)
        
        # Engine 2: LLM解析
        llm_result = self._parse_with_llm(raw_output)
        
        # 验证
        if self._results_match(rules_result, llm_result):
            return rules_result
        else:
            # 记录不一致
            logger.warning(f"解析结果不一致: {rules_result} vs {llm_result}")
            # 返回规则结果 (更快更可靠)
            return rules_result
```

## 📈 预期改进

| 方面 | 当前 | 改进后 |
|-----|------|--------|
| 数据来源 | 双重查询 | 单一来源 (Parsed) |
| 命令执行 | 重复执行 | 一次执行 + 导入 |
| 解析验证 | 无 | 双引擎验证 |
| 数据质量 | 低 (格式错误) | 高 (规范格式) |
| 更新延迟 | 实时 | 准实时 |
| 代码重复 | 高 (两个解析器) | 低 (统一) |

---
**下一步**: 实施第1阶段 (TopologyImporter) 可以立即改进数据质量和系统效率。
