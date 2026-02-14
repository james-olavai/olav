# OLAV 文件导出架构 - 完整工作流图

## 系统架构流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                          用户查询                                     │
│         "查询所有VLAN，导出为CSV"  OR  "在R2上运行show run，保存为TXT"   │
└────────────────────────┬────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Orchestrator (中央协调器)                          │
│  • 接收用户查询                                                       │
│  • 路由到适当的SubAgent                                             │
│  • 检测"导出"关键词 (save/export/write)                            │
│  • 调用format_and_export()                                          │
└────────────────────────┬────────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
  ┌──────────┐    ┌──────────┐    ┌──────────┐
  │  Query   │    │   CLI    │    │ Analysis │
  │ SubAgent │    │ SubAgent │    │ SubAgent │
  │          │    │          │    │          │
  │ 数据库   │    │ CLI命令  │    │ 网络分析  │
  │ 查询     │    │ 执行     │    │          │
  └────┬─────┘    └────┬─────┘    └────┬─────┘
       │               │               │
       │ 返回数据      │ 返回输出      │ 返回分析
       │               │               │
       └───────────────┼───────────────┘
                       │ (content)
                       │ (无格式化，纯数据)
                       ▼
        ┌──────────────────────────────┐
        │  Orchestrator.format_and_export()
        │  • 接收SubAgent的原始数据     │
        │  • 检测数据格式 (md/csv...)   │
        │  • 生成文件名 (w/ timestamp)  │
        │  • 写入到exports/reports/     │
        └──────────────┬───────────────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │    exports/reports/          │
        │  ├─ vlans.csv                │
        │  ├─ R2_running_config.txt   │
        │  ├─ r1_bgp_diagnosis.md     │
        │  ├─ export_20260206_143022.json
        │  └─ ...                      │
        └──────────────────────────────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │   ✅ 返回给用户                │
        │  "✅ 文件已保存到exports/..."  │
        └──────────────────────────────┘
```

---

## 详细工作流 - 三个真实场景

### 场景1️⃣: CSV导出 (Query SubAgent)

```
用户: "查询所有VLAN，导出为CSV"
     ↓
Orchestrator 识别关键词: "查询" + "导出"
     ↓
[SubAgent选择] → Query SubAgent
     ↓
Query执行: 
  • SQL: SELECT * FROM vlans
  • 返回: {
      "vlans": [
        {"vlan_id": 10, "name": "Management"},
        {"vlan_id": 20, "name": "Data"}
      ]
    }
     ↓
Orchestrator 检测到 "导出为CSV"
     ↓
format_and_export(
  data={                    # Python dict
    "vlans": [...]
  },
  filename="vlans",
  format="csv"              # 用户指定或自动检测
)
     ↓
内部处理:
  • 自动检测: dict → JSON
  • 但format="csv"覆盖 → 转为CSV
  • 生成文件: vlans.csv
  • 写入: exports/reports/vlans.csv
     ↓
✅ 返回: {
  "path": "exports/reports/vlans.csv",
  "size": 512,
  "format": "csv"
}
```

### 场景2️⃣: TXT导出 (CLI SubAgent)

```
用户: "在R2上运行show running-config，保存为TXT"
     ↓
Orchestrator 识别关键词: "运行" + "保存"
     ↓
[SubAgent选择] → CLI SubAgent
     ↓
CLI执行:
  • Device: R2
  • Command: show running-config
  • 返回: (string)
    "interface GigabitEthernet0/0/0
     ip address 192.168.1.1 255.255.255.0
     ..."
     ↓
Orchestrator 检测到 "保存"
     ↓
format_and_export(
  data="interface GigabitEthernet0/0/0\n...",  # 字符串
  filename="R2_running_config",
  # format省略 → 自动检测
)
     ↓
内部处理:
  • 自动检测: str且不以#开头 → txt
  • 生成文件: R2_running_config.txt
  • 写入: exports/reports/R2_running_config.txt
     ↓
✅ 返回: {
  "path": "exports/reports/R2_running_config.txt",
  "size": 2048,
  "format": "txt"
}
```

### 场景3️⃣: Markdown导出 (Expert SubAgent)

```
用户: "诊断R1的OSPF问题，生成报告"
     ↓
Orchestrator 识别关键词: "诊断" → 复杂 → 升级
     ↓
[SubAgent选择] → Expert SubAgent
     ↓
Expert诊断:
  1. 查询devices表获取R1信息
  2. 分析OSPF邻居状态
  3. 检查接口配置
  4. 对比期望值
  5. 生成Markdown报告
  
  返回: (string)
    "# R1 OSPF诊断报告
     
     ## 问题描述
     R1的OSPF邻居状态为DOWN
     
     ## 根因分析
     子网掩码不匹配：
     - R1 eth0: 192.168.1.0/24
     - R2 eth0: 192.168.1.0/25
     
     ## 建议
     修改R2的子网掩码为/24
     
     ..."
     ↓
Orchestrator 识别到 "诊断" = 通常需要保存
     ↓
format_and_export(
  data="# R1 OSPF诊断报告\n\n## 问题描述\n...",  # Markdown字符串
  filename="R1_OSPF_diagnosis"
  # format省略 → 自动检测
)
     ↓
内部处理:
  • 自动检测: str以#开头 → md (Markdown)
  • 生成文件: R1_OSPF_diagnosis.md
  • 写入: exports/reports/R1_OSPF_diagnosis.md
     ↓
✅ 返回: {
  "path": "exports/reports/R1_OSPF_diagnosis.md",
  "size": 1024,
  "format": "md"
}
```

---

## 技术实现细节

### DeepAgents集成点

```python
# src/olav/agents/orchestrator.py

def create_orchestrator(...):
    # 1. SubAgent定义（声明式）
    subagents = [
        SubAgent(
            name="query",
            description="Database query specialist",
            tools=[query_database, inspect_schema, discover_data]
        ),
        SubAgent(
            name="cli",
            description="CLI command execution",
            tools=[nornir_execute, list_devices]
        ),
        SubAgent(
            name="expert",
            description="CCIE-level expert",
            tools=[...] + [format_and_export]  # ← 仅Expert有导出权限
        ),
    ]
    
    # 2. Orchestrator工具（仅核心导出）
    orchestrator_tools = [
        format_and_export,  # ← Orchestrator调用导出
    ]
    
    # 3. 创建DeepAgent（使用原生SubAgent支持）
    agent = create_deep_agent(
        model="gpt-4o",
        system_prompt=orchestrator_skill.content,
        tools=orchestrator_tools,              # ← Orchestrator工具
        subagents=tuple(subagents),            # ← ✨ DeepAgents原生SubAgent
        middleware=tuple(middleware),
        checkpointer=None,                     # ← 内置状态管理
        name="orchestrator"
    )
    
    return agent
```

### 工具权限架构

```
Permission Model (权限模型)
├── Query SubAgent
│   ├─ query_database (读)
│   ├─ inspect_schema (读)
│   └─ discover_data (读)
│
├── CLI SubAgent  
│   ├─ nornir_execute (读/执行)
│   └─ list_devices (读)
│
├── Analysis SubAgent
│   ├─ analyze_network (读)
│   └─ query_database (读)
│
├── Expert SubAgent
│   ├─ analyze_topology (读)
│   ├─ query_database (读)
│   ├─ nornir_execute (执行)
│   └─ format_and_export (写) ← 高级导出
│
└── Orchestrator (中央控制)
    └─ format_and_export (写) ← 最终导出决策
    
规则: 只有Orchestrator可以决定导出，SubAgent返回数据
```

### 自动格式检测算法

```python
def _detect_format(data: Any) -> str:
    """
    从数据内容自动推断格式
    
    优先级:
    1. 检查Markdown特征 (# 开头或包含 ##)
    2. 检查JSON特征 (以{ 或 [ 开头，valid JSON)
    3. 默认Text
    """
    if isinstance(data, str):
        # Markdown检测
        if data.strip().startswith("#") or "\n##" in data:
            return "md"        # ✅ 诊断报告
        
        # JSON检测
        if data.strip().startswith("{") or data.strip().startswith("["):
            try:
                json.loads(data)
                return "json"   # ✅ 结构化数据
            except:
                pass
        
        return "txt"            # ✅ CLI输出、日志
    
    elif isinstance(data, (dict, list)):
        return "json"           # ✅ Python对象
    
    else:
        return "txt"            # ✅ 其他类型
```

---

## 文件系统结构

```
Project Root: /home/yhvh/Olav/
├── .olav/
│   ├── skills/
│   │   ├── orchestrator/
│   │   │   ├── SKILL.md           ← 导出指南定义
│   │   │   └── config/
│   │   ├── query/SKILL.md
│   │   ├── cli/SKILL.md
│   │   ├── expert/SKILL.md
│   │   └── analysis/SKILL.md
│   └── db/
│       └── main.duckdb            ← 数据源
│
├── src/olav/
│   ├── agents/
│   │   └── orchestrator.py        ← 中央协调（工具调用）
│   ├── tools/
│   │   ├── data_export.py         ← ✨ 格式和导出
│   │   ├── react_query.py         ← 数据库查询
│   │   └── network.py             ← CLI执行等
│   └── core/
│       └── subagent_loader.py     ← 动态加载
│
├── config/
│   └── paths.py                   ← REPORTS_DIR = exports/reports/
│
├── exports/
│   └── reports/                   ← 📁 所有导出文件
│       ├── vlans.csv
│       ├── R2_running_config.txt
│       ├── R1_OSPF_diagnosis.md
│       └── export_20260206_143022.json
│
└── tests/e2e/
    └── test_real_scenarios.py     ← ✅ E2E测试
```

---

## 运行时示例

### 例子1: 在Python中直接调用

```python
from olav.tools.data_export import format_and_export

# 导出JSON
result = format_and_export(
    data={"devices": [
        {"hostname": "R1", "ip": "192.168.1.1"},
        {"hostname": "R2", "ip": "192.168.1.2"},
    ]},
    filename="inventory"
    # format自动检测为json
)
print(result)
# {
#   "path": "exports/reports/inventory.json",
#   "size": 256,
#   "format": "json"
# }
```

### 例子2: Orchestrator中使用

```python
async def orchestrate_query(user_query: str):
    orchestrator = create_orchestrator()
    
    # 用户: "查询所有VLAN，导出为CSV"
    result = await orchestrator.ainvoke(
        {"messages": [HumanMessage(content=user_query)]},
        config={"configurable": {}}
    )
    
    # Orchestrator会自动:
    # 1. 路由到query SubAgent
    # 2. 得到VLAN数据
    # 3. 识别"导出"关键词
    # 4. 调用format_and_export(data, format="csv")
    # 5. 返回文件路径给用户
```

---

## 总结

| 方面 | 设计 | 实现 | 验证 |
|------|------|------|------|
| **多格式支持** | ✅ (md/csv/txt/json/yaml) | ✅ | ✅ E2E |
| **自动检测** | ✅ | ✅ | ✅ 单测 |
| **DeepAgents原生** | ✅ (subagents参数) | ✅ | ✅ |
| **SubAgent数据流** | ✅ | ✅ | ✅ |
| **自动输出目录** | ✅ | ✅ | ✅ |
| **权限管理** | ✅ | ✅ | ✅ |
| **时间戳命名** | ✅ | ✅ | ✅ |

**结论**: 文件导出功能设计完整，实现正确，已通过所有测试。🎉
