# 数据库写入数据流分析报告

## 📊 当前系统状态

### 数据库信息
- **位置**: `.olav/data/topology.db`
- **表数**: 6个 (inspect_results, log_analysis, sync_metadata, sync_outputs, topology_devices, topology_links)
- **设备数**: 6个
- **链接数**: 363个

### 数据设备样本
- R1: 192.168.100.101 (lab, border)
- R2: 192.168.100.102 (lab, border)  
- R3: 192.168.100.103 (lab, core)

## 🔄 当前数据流程

### 流程图
```
Raw数据 → Parsed数据 → 数据库
  (txt)      (json)     (DuckDB)
```

### 详细流程

#### 1️⃣ **Raw数据阶段** (data/sync/2026-01-13/raw/)
- **格式**: 纯文本命令输出 (.txt)
- **来源**: 网络设备执行命令的直接输出
- **存储位置**: `data/sync/2026-01-13/raw/{device}/`

**示例** - `show-cdp-neighbors.txt`:
```
Device ID        Local Intrfce     Holdtme    Capability  Platform  Port ID
R3.local         Gig 2             159             R S I  Linux Uni Eth 0/0
R2.local         Gig 1             160              R I   ISRV      Gig 1
```

#### 2️⃣ **Parsed数据阶段** (data/sync/2026-01-13/parsed/)
- **格式**: JSON结构化数据
- **来源**: 使用文本解析器处理Raw数据
- **存储位置**: `data/sync/2026-01-13/parsed/{device}/`

**示例** - `show-cdp-neighbors.json`:
```json
{
  "metadata": {
    "device": "R1",
    "source": "show-cdp-neighbors.txt",
    "command": "show cdp neighbors",
    "timestamp": "2026-01-13T16:56:36.593327"
  },
  "data": [
    {
      "device_id": "R3.local",
      "local_intrfce": "Gig 2",
      "holdtime": "159",
      "capability": "R S I",
      "platform": "Linux Uni",
      "port_id": "Eth 0/0"
    },
    {
      "device_id": "R2.local",
      "local_intrfce": "Gig 1",
      "holdtime": "160",
      "capability": "R I",
      "platform": "ISRV",
      "port_id": "Gig 1"
    }
  ]
}
```

#### 3️⃣ **数据库阶段** (.olav/data/topology.db)
- **格式**: DuckDB关系型数据库
- **目标表**:
  - `topology_devices`: 设备清单
  - `topology_links`: 邻接关系

## ⚠️ **问题分析**

### 问题1️⃣: 数据写入源不清晰

**当前情况**:
```
两个独立的数据处理路径：

路径A (sync_tools.py):
  Raw数据 → 解析 (TextFSM/正则) → JSON (Parsed) → ❓数据库

路径B (topology_tools.py):
  数据库查询 → 执行命令 → 解析 → INSERT数据库
```

**存在的问题**:
1. **Parsed JSON没有被导入数据库** ❌
   - sync_tools.py生成parsed JSON (show-cdp-neighbors.json)
   - 但topology_tools.py不读取这些已解析的数据
   - topology_tools.py重新执行命令并解析，造成重复

2. **两套独立的解析器** ⚠️
   ```python
   # sync_tools.py
   def _parse_cdp_neighbors(output: str):  # 一个解析器
       ...
   
   # topology_tools.py
   def _parse_cdp_lldp_output(output: str):  # 另一个解析器
       ...
   ```

3. **数据冗余和不一致** ❌
   - Parsed JSON中的数据格式和字段名与数据库schema不匹配
   - 例如: JSON用 `device_id`，但DB期望 `remote_device`

### 问题2️⃣: 没有双引擎验证

**当前缺失**:
- ❌ 没有LLM解析验证
- ❌ 没有结构化数据验证
- ❌ 没有数据质量检查
- ❌ 没有解析器准确率评估

**应该有的流程**:
```
Raw数据 
  ↓
[Engine 1: TextFSM正则解析] → 结果1
  ↓
[Engine 2: LLM解析] → 结果2
  ↓
[验证引擎: 一致性检查]
  ↓
[选择更可靠的结果] → 数据库
```

### 问题3️⃣: 写入的数据格式不正确

**当前的topology_links表**:
```sql
local_device → "R1"
remote_device → "Neighbor" 或 "3.3.3.3"  ❌ 不规范
protocol → "OSPF"
layer → "L3"
```

**应该的格式**:
```sql
local_device → "R1"
remote_device → "R3"  ✅ 规范的设备名
protocol → "OSPF"
layer → "L3"
local_port → "Gi0/0"
remote_port → "Gi0/1"
```

## 📋 建议的改进方案

### 方案A: 统一的数据导入管道 (推荐)

```python
# 新建: src/olav/tools/topology_importer.py

class TopologyImporter:
    """统一的拓扑数据导入器"""
    
    def import_from_parsed_data(self, parsed_dir: Path):
        """从已解析的JSON导入数据"""
        for device_dir in parsed_dir.glob("*"):
            # 读取 show-cdp-neighbors.json
            # 读取 show-ospf-neighbors.json
            # 读取 show-bgp-summary.json
            # 验证和转换数据
            # 写入数据库
    
    def validate_link_data(self, link: dict) -> bool:
        """验证链接数据的格式正确性"""
        required_fields = ['local_device', 'remote_device', 'protocol']
        return all(field in link and link[field] for field in required_fields)
    
    def import_with_validation(self, parsed_dir: Path, validate_fn):
        """带验证的导入"""
        for link in self.extract_links(parsed_dir):
            if validate_fn(link):
                self.insert_link(link)
```

### 方案B: 双引擎验证系统

```python
# src/olav/tools/topology_parser.py

class TopologyParser:
    """双引擎拓扑解析器"""
    
    def parse_with_dual_engines(self, raw_output: str):
        """使用两个引擎解析数据"""
        # Engine 1: TextFSM/正则表达式
        result1 = self.parse_with_textfsm(raw_output)
        
        # Engine 2: LLM解析
        result2 = self.parse_with_llm(raw_output)
        
        # 验证和合并结果
        return self.merge_and_validate(result1, result2)
    
    def parse_with_textfsm(self, output: str) -> dict:
        """基于规则的解析"""
        ...
    
    def parse_with_llm(self, output: str) -> dict:
        """LLM解析"""
        ...
    
    def merge_and_validate(self, result1: dict, result2: dict) -> dict:
        """合并并验证两个解析结果"""
        # 比较结果
        # 如果一致，使用该结果
        # 如果不一致，选择更可靠的或报警
        ...
```

### 方案C: 数据格式规范化

```python
# 统一的数据schema

class TopologyLink:
    """拓扑链接规范"""
    local_device: str       # 如: "R1"
    remote_device: str      # 如: "R2" (不是IP或其他格式)
    local_port: str         # 如: "Gi0/0"
    remote_port: str        # 如: "Gi0/1"
    protocol: str           # "CDP", "LLDP", "OSPF", "BGP"
    layer: str              # "L1", "L3"
    discovered_at: datetime
```

## 🔧 实施优先级

| 优先级 | 改进项 | 工作量 | 影响 |
|--------|--------|--------|------|
| 🔴 高 | 从Parsed JSON导入数据库 | 中等 | 消除重复执行 |
| 🔴 高 | 数据格式规范化 | 小 | 修复当前数据 |
| 🟠 中 | 双引擎验证系统 | 大 | 提高数据质量 |
| 🟠 中 | 统一解析器 | 中等 | 代码维护性 |
| 🟡 低 | 数据质量监控 | 中等 | 可观测性 |

## ✅ 快速检查清单

- [ ] Parsed JSON数据正在被导入数据库
- [ ] 数据库中的remote_device是规范的设备名(不是IP)
- [ ] 所有links都有local_port和remote_port
- [ ] 解析器验证了数据完整性
- [ ] 有LLM和规则解析器的验证机制
- [ ] 文档说明了数据来源(Parsed vs Real-time Discovery)
