# DB Federation E2E Testing Guide

## 测试环境准备

确保已运行快照采集：
```bash
cd /home/yhvh/Olav
uv run olav snapshot
```

## 测试场景

### 1. IP定位查询

**测试问题 (自然语言)**:
- "Where is IP 10.1.12.1?"
- "Find 10.1.12.1"
- "10.1.12.1在哪个设备上?"

**预期行为**:
- Agent应该调用 `find_ip_location_tool("10.1.12.1")`
- 直接从数据库返回结果 (<5ms)
- 不应该执行设备命令

**预期输出**:
```
IP 10.1.12.1 Location
├─ Device: R2
├─ Interface: GigabitEthernet1
└─ MAC: 5000.000a.0000
```

**验证指标**:
- ✅ 响应时间 < 2秒 (包含LLM推理)
- ✅ 没有执行nornir_execute
- ✅ 结果准确

---

### 2. 设备健康查询

**测试问题 (自然语言)**:
- "How is R1 doing?"
- "R1 health status"
- "R1的健康状态如何?"

**预期行为**:
- Agent应该调用 `get_device_health_tool("R1")`
- 关联多表数据 (devices, arp_table, routes, topology_links, capabilities)
- 返回综合健康指标

**预期输出**:
```
R1 Health Summary
├─ Platform: cisco_ios (border)
├─ ARP Entries: 9
├─ Routes: 4
├─ Neighbors: 6
└─ Commands Available: 64
```

**验证指标**:
- ✅ 响应时间 < 3秒
- ✅ 跨库JOIN查询成功
- ✅ 所有指标正确

---

### 3. 网络概览查询

**测试问题 (自然语言)**:
- "Network summary"
- "Give me a network overview"
- "网络整体情况"

**预期行为**:
- Agent应该调用 `get_network_summary_tool()`
- 聚合全网统计数据

**预期输出**:
```
Network Overview
├─ Total Devices: 6
├─ Total Links: 22
├─ Total ARP Entries: 36
├─ Total Routes: 18
└─ Platforms: cisco_ios
```

**验证指标**:
- ✅ 响应时间 < 2秒
- ✅ 统计数字准确
- ✅ 所有平台列出

---

### 4. IP模式搜索

**测试问题 (自然语言)**:
- "Find all IPs starting with 10.1"
- "Show me all 10.1.% IPs"
- "搜索10.1开头的所有IP"

**预期行为**:
- Agent应该调用 `search_ip_across_network_tool("10.1%")`
- SQL LIKE模式匹配
- 返回多个结果

**预期输出**:
```
IPs matching '10.1%'
├─ 10.1.12.1 → R2/GigabitEthernet1
├─ 10.1.12.2 → R1/GigabitEthernet2
└─ ... (多条记录)
```

**验证指标**:
- ✅ 模式匹配正确
- ✅ 所有匹配项返回
- ✅ 查询速度 < 10ms

---

### 5. 网络健康分析 (高级)

**测试问题 (自然语言)**:
- "Analyze network health"
- "Are there any problems?"
- "网络健康分析"

**预期行为**:
- Agent应该调用 `analyze_network_health_tool()`
- 执行L1-L4分层评分
- 检测异常 (路由缺失、ARP异常等)
- 生成Markdown报告

**预期输出**:
```
Network Health Report

Overall: 100/100 (HEALTHY)

Layer Scores:
├─ L3 Network: 100/100 🟢

Device Health:
├─ R1: 9 ARP, 4 routes, 6 neighbors
├─ R2: 9 ARP, 4 routes, 6 neighbors
...

Anomalies: None detected ✓
```

**验证指标**:
- ✅ 评分算法正确
- ✅ 异常检测工作
- ✅ Markdown格式优美
- ✅ 生成时间 < 100ms

---

## OLAV CLI测试方法

### 方法1: 交互式测试

```bash
cd /home/yhvh/Olav
uv run olav
```

然后在Agent交互中输入测试问题 (见上方"测试问题")。

### 方法2: 监控Agent行为

观察Agent日志，确认：
1. 是否正确选择了database_tools (而不是nornir_execute)
2. 工具调用参数是否正确
3. 返回结果是否被正确解释

### 方法3: 性能基准测试

```bash
time uv run python << 'EOF'
from olav.tools.database_tools import find_ip_location_tool
print(find_ip_location_tool("10.1.12.1"))
EOF
```

预期: `real < 0.100s` (首次查询), `real < 0.050s` (后续查询)

---

## 预期vs实际对比表

| 测试场景 | 预期行为 | 预期响应时间 | 预期输出格式 |
|---------|---------|------------|------------|
| IP定位 | 调用find_ip_location_tool | < 2s | 结构化位置信息 |
| 设备健康 | 调用get_device_health_tool | < 3s | 多维度健康指标 |
| 网络概览 | 调用get_network_summary_tool | < 2s | 统计汇总 |
| IP搜索 | 调用search_ip_across_network_tool | < 3s | 匹配列表 |
| 健康分析 | 调用analyze_network_health_tool | < 5s | 分层评分+报告 |

---

## 成功标准

✅ **功能性**:
- 所有工具正确调用
- 返回数据准确无误
- 错误处理正确 (不存在的IP/设备)

✅ **性能**:
- 数据库查询 < 10ms
- 端到端响应 < 5s (含LLM)
- 无超时错误

✅ **可读性**:
- Agent输出清晰易懂
- Markdown格式正确
- 图标/表格优美

✅ **稳定性**:
- 连续查询无错误
- 内存无泄漏
- 数据库连接正常关闭

---

## 故障排查

### 问题: Agent没有调用database_tools

**原因**: Skill没有被正确加载或Agent没有理解意图

**解决**:
1. 检查 `.olav/skills/quick-query/SKILL.md` 是否存在
2. 重启OLAV: `uv run olav`
3. 更明确的提问: "Use database to find IP 10.1.12.1"

### 问题: 数据库返回空结果

**原因**: 数据未导入或导入失败

**解决**:
```bash
# 重新运行快照
uv run olav snapshot

# 检查数据库
uv run python -c "
from olav.core.unified_database import UnifiedDatabase
with UnifiedDatabase() as udb:
    print(udb.query('SELECT COUNT(*) FROM snapshot.arp_table')[0][0])
"
```

### 问题: 查询速度慢

**原因**: 数据库未建立索引或JOIN条件不优化

**解决**: 参考 `unified_database.py` 中的查询优化建议

---

## 下一步行动

1. **手动E2E验证** (必须):
   - 运行 `uv run olav`
   - 逐个测试5个场景
   - 记录实际表现

2. **性能基准** (推荐):
   - 测试100次查询的平均响应时间
   - 确保无内存泄漏

3. **边界测试** (可选):
   - 不存在的IP/设备
   - 超大网络 (100+ devices)
   - 并发查询

4. **Agent适应性测试** (关键):
   - 用不同表述问同一个问题
   - 观察Agent是否始终选择正确工具
   - 评估自然语言理解能力

---

## 成功案例示例

```
User: Where is IP 10.1.12.1?

Agent: I'll query the database to locate that IP.

[Calls find_ip_location_tool("10.1.12.1")]

Agent: IP 10.1.12.1 is located on:
- Device: R2
- Interface: GigabitEthernet1
- MAC Address: 5000.000a.0000

This was a database query, so the result is instant (4ms).
```

**评价**: ✅ 完美 - 快速、准确、清晰

---

EOF
