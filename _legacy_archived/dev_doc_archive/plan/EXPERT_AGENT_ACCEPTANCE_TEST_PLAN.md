# Expert Agent 验收测试方案

**文档版本**: v1.0.0  
**创建日期**: 2026年2月11日  
**最后更新**: 2026年2月11日  
**状态**: 📋 规划中  
**优先级**: ⭐⭐⭐ (高)  
**职责**: CCIE级网络专家 - 复杂故障诊断与根本原因分析

---

## 📋 文档概述

本文档定义了 Expert Agent 的完整验收测试方案，涵盖以下核心功能：

### 核心测试域

| 域 | 覆盖范围 | 优先级 |
|----|---------|--------|
| **复杂问题解决** | 多层故障、级联故障、设计缺陷 | ⭐⭐⭐ |
| **故障注入与验证** | 触发真实故障、执行诊断、验证解决方案 | ⭐⭐⭐ |
| **知识库集成** | 案例库调用、解决方案匹配、学习反馈 | ⭐⭐ |
| **工具链调用** | CLI命令、网络查询、数据分析、报告生成 | ⭐⭐⭐ |
| **多域专业能力** | R&S/DC/SP/Security各域问题诊断 | ⭐⭐ |
| **报告生成** | 诊断报告、建议方案、执行步骤 | ⭐⭐ |

### 验收准则

- ✅ 所有8个主要测试场景通过
- ✅ 无关键缺陷残留 (P0/P1)
- ✅ 诊断准确率 ≥ 85%
- ✅ 解决方案可执行性 ≥ 90%
- ✅ 知识库命中率 ≥ 70%
- ✅ 工具链成功率 ≥ 95%

---

## 🎯 测试场景总览

| # | 场景 | 类型 | 复杂度 | 优先级 | 状态 |
|---|------|------|--------|--------|------|
| 1 | BGP 故障诊断 | 单点故障+诊断 | 中 | ⭐⭐⭐ | 📋 规划 |
| 2 | 级联故障分析 | 多点故障+关联分析 | 高 | ⭐⭐⭐ | 📋 规划 |
| 3 | OSPF邻接互联故障 | 链路故障+协议分析 | 中 | ⭐⭐⭐ | 📋 规划 |
| 4 | 网络设计缺陷 | 设计分析+性能优化 | 高 | ⭐⭐ | 📋 规划 |
| 5 | 安全策略问题 | ACL/NAT/防火墙综合分析 | 中 | ⭐⭐⭐ | 📋 规划 |
| 6 | 知识库集成 | 案例库调用+自学习 | 中 | ⭐⭐ | 📋 规划 |
| 7 | 工具链完整性 | 全工具链调用验证 | 中 | ⭐⭐ | 📋 规划 |
| 8 | 多域交叉问题 | R&S+DC+SP混合故障 | 很高 | ⭐⭐ | 📋 规划 |

---

## 📌 场景 1: BGP 故障诊断与解决

### 1.1 功能描述

Expert Agent 能够诊断 BGP 相关故障（邻接不稳定、路由表异常、AS路径问题），依次执行诊断步骤，调用知识库，提供解决方案。

### 1.2 测试流程

```
Phase 1: 故障注入
├─ 触发BGP邻接DOWN (修改邻接地址)
├─ 记录故障时间戳
└─ 验证故障已生成

Phase 2: 诊断执行
├─ Expert Agent 收到查询: "BGP邻接不稳定，无法建立"
├─ 执行诊断步骤:
│  ├─ Step 1: show ip bgp summary (获取BGP状态)
│  ├─ Step 2: show ip bgp neighbors (获取邻接详情)
│  ├─ Step 3: show ip route bgp (检查路由)
│  ├─ Step 4: show access-list (检查ACL)
│  └─ Step 5: ping邻接地址 (测试L3连通性)
└─ 收集诊断数据

Phase 3: 根本原因分析 (RCA)
├─ 分析BGP配置
├─ 检查网络连通性
├─ 查询案例库 (.olav/knowledge/solutions/)
├─ 匹配已知问题
└─ 生成根本原因

Phase 4: 解决方案执行
├─ 调用知识库解决方案
├─ 在设备上执行配置命令
├─ 验证BGP邻接恢复
└─ 记录解决过程

Phase 5: 验证与学习
├─ 验证BGP状态为UP
├─ 验证路由表恢复
├─ 保存解决方案到案例库
└─ 生成诊断报告
```

### 1.3 测试用例

#### 测试用例 1.1: 诊断BGP邻接DOWN

**前置条件**:
```bash
# 故障场景设置
设备: R1 (BGP AS 65000)
邻接: R2 (BGP AS 65001)
当前状态: BGP邻接已建立 (Established)

# 故障注入命令
R1# conf t
R1# router bgp 65000
R1# neighbor 10.0.0.2 remote-as 65001
! 修改邻接地址使其无法连接
R1# neighbor 10.0.0.99 remote-as 65001
R1# exit
R1# exit
! 提交更改
R1# wr mem
```

**测试步骤**:
```
1. 诊断查询: "BGP邻接不稳定，状态一直是Idle"
2. Expert Agent 执行诊断步骤
3. 获取以下命令输出:
   - show ip bgp summary
   - show ip bgp neighbors
   - show ip route bgp
   - show access-list (检查ACL拒绝)
   - ping 10.0.0.99
4. 分析数据
5. 调用知识库查询已知案例
6. 生成RCA报告
```

**预期结果**:
```
✅ 诊断准确: "邻接地址配置错误 - 无法建立TCP连接"
✅ 根本原因: "R1和R2的BGP邻接IP不匹配"
✅ 解决方案: "修改邻接地址为10.0.0.2"
✅ 知识库命中: 至少1条相关案例
✅ 工具调用: 5条命令全部成功执行
✅ 时间: < 30秒完成诊断
```

**验收标准**:
| 标准 | 要求 | 检验方法 |
|------|------|----------|
| 诊断准确性 | ≥ 90% | 对比RCA与实际故障原因 |
| 知识库命中 | ≥ 1条相关案例 | 检查调用记录 |
| 工具链成功率 | 100% (5/5命令) | 验证命令执行日志 |
| 建议方案可执行性 | 实际测试修复成功 | 执行建议命令后验证BGP状态 |
| 时间性能 | < 30秒 | 计时测试 |

#### 测试用例 1.2: BGP 路由黑洞

**故障场景**:
```
拓扑: R1 (AS 65000) -- R2 (AS 65001) -- R3 (AS 65002)
问题: 从R1发往192.168.3.0/24 (在R3) 的流量丢失
原因: R2的BGP导出策略有误，没有正确发布路由

故障模拟:
R2# conf t
R2# route-map NO_EXPORT deny 10
R2# match ip address prefix-list BGP_ROUTES
R2# route-map NO_EXPORT permit 20
R2# !
R2# route-map EXPORT sequence 20
R2# set as-path prepend 65001 65001 65001  (增加AS跳数使路由不可达)
R2# router bgp 65001
R2# neighbor 10.0.0.1 route-map EXPORT out
R2# exit
```

**测试步骤**:
```
1. 诊断查询: "无法访问192.168.3.0/24，流量丢失"
2. Expert Agent诊断:
   - Step 1: tracert 192.168.3.1 (检查路径)
   - Step 2: show ip bgp 192.168.3.0 (检查BGP路由)
   - Step 3: show ip bgp summary (检查邻接)
   - Step 4: show ip route 192.168.3.0 (检查路由表)
   - Step 5: show ip bgp neighbors 10.0.0.2 routes (R1查看)
3. 分析根本原因
4. 查询案例库
5. 提出修复方案
```

**预期结果**:
```
✅ 诊断: "BGP路由未发布 - 导出策略阻止"
✅ RCA: "R2的route-map配置不正确"
✅ 方案可执行: 修改route-map策略
✅ 验证: 修复后BGP路由可达
```

---

## 📌 场景 2: 级联故障分析

### 2.1 功能描述

Expert Agent 能够识别并分析涉及多个网络层级的级联故障，进行关联分析，找出单点故障的真正根因。

### 2.2 测试场景

**复杂拓扑**:
```
              Core Router
                   |
        +----------+----------+
        |                     |
    Distribution1        Distribution2
        |                     |
    +---+---+            +----+----+
    |       |            |         |
   Access1 Access2     Access3   Access4
   (SW)    (SW)        (SW)      (SW)
    |       |            |         |
  End-1  End-2        End-3    End-4
```

### 2.3 故障注入场景

#### 故障场景 2.1: 链路故障导致的级联重新收敛

**故障注入**:
```
1. 关闭 Core - Distribution2 链路
   Device Core# conf t
   Device Core# int Eth0/3
   Device Core# shutdown
   Device Core# wr mem

2. 监察现象:
   - Distribution2 失去上行连接
   - Distribution2 上的设备重新路由到Distribution1
   - 可能导致Distribution1过载
   - OSPF/BGP重新收敛
   - 某些路由可能出现黑洞
```

**测试步骤**:
```
1. 查询1 (User): "为什么 End-3 无法访问外网？"
   → Expert 诊断 Access3 无上行链路

2. 查询2: "为什么这个链路DOWN了？"
   → Expert 发现 Core - Distribution2 链路故障

3. 查询3: "这会影响其他设备吗？"
   → Expert 分析级联影响，生成影响范围图

4. 查询4: "应该怎么解决？"
   → Expert 提出备份方案、重新路由、恢复步骤

5. 执行恢复: 启用链路
   Device Core# conf t
   Device Core# int Eth0/3
   Device Core# no shutdown
   Device Core# wr mem

6. 验证: 所有服务恢复
```

**验收标准**:
| 标准 | 要求 | 检验方法 |
|------|------|----------|
| 故障识别 | 正确找到断链 | show interface + CDP/LLDP |
| 影响分析 | 正确分析级联影响 | 对比实际受影响设备 |
| 方案完整性 | 包含绕路/备份/恢复 | 检查提议的步骤 |
| 知识库命中 | 命中级联故障案例 | 检查参考的案例 |
| 验证成功 | 恢复后所有服务正常 | 功能验证 |

---

## 📌 场景 3: OSPF邻接互联故障

### 3.1 功能描述

Expert Agent 能够诊断 OSPF 邻接问题、链路状态数据库异常、SPF计算错误。

### 3.2 故障场景

#### 测试用例 3.1: OSPF邻接无法建立

**故障类型**: Mismatch (不匹配)
- Area ID 不同
- Network Type 不同 (点到点 vs 广播)
- 认证密钥不同
- Hello/Dead Interval 不同

**故障注入**:
```
# 在R2上修改Area ID
R2# conf t
R2# router ospf 1
R2# network 10.0.0.2 0.0.0.0 area 2   (改为Area 2, 原为Area 0)
R2# exit
R2# exit
R2# wr mem

# 观察现象: R1-R2 OSPF邻接从Establish变为Down
```

**诊断步骤**:
```
1. 查询: "为什么OSPF邻接一直无法建立？"
2. Expert 执行诊断:
   - show ip ospf neighbor detail (检查邻接状态)
   - show ip ospf interface (检查接口参数)
   - show ip ospf database (检查LSA)
   - show debug ospf adjacency (查看邻接日志)
3. 通过日志识别 "mismatch in area id"
4. 建议修改Area ID
5. 测试修复
```

**验收标准**:
| 标准 | 要求 | 检验方法 |
|------|------|----------|
| 故障诊断 | 正确识别Area ID不匹配 | 检查RCA |
| 参数分析 | 对比两端OSPF参数差异 | 输出两端 show ip ospf interface |
| 知识库 | 命中OSPF参数mismatch案例 | 检查参考案例 |
| 解决方案 | 提供正确的配置修改 | 手动执行后验证邻接Establish |
| 时间 | < 25秒完成诊断 | 计时 |

#### 测试用例 3.2: SPF黑洞问题

**场景**: OSPF能建邻接，但路由表异常
```
拓扑: R1 -- R2 -- R3
问题: 从R1发往R3的流量经R2转发，但R2没有转往R3的路由
根因: R2的LSA有误，SPF计算错误
```

**故障注入与诊断流程**: 类似上面

---

## 📌 场景 4: 网络设计缺陷发现

### 4.1 功能描述

Expert Agent 能够发现设计中的问题：
- 单点故障
- 带宽瓶颈
- 冗余性差
- 性能不足

### 4.2 测试场景

#### 测试用例 4.1: 单点故障诊断

**场景分析查询**:
```
用户: "我们的网络设计是否有问题？"
Expert分析:
1. 获取网络拓扑 (CDP/LLDP)
2. 分析链接关系
3. 识别单点故障:
   ├─ 哪些设备DOWN会导致网络分割
   ├─ 哪些链路DOWN会导致性能严重下降
   └─ 关键业务是否有备份路由
4. 生成设计风险报告
```

**验收标准**:
| 标准 | 要求 | 检验方法 |
|------|------|----------|
| 拓扑采集 | 完整获取网络拓扑 | 对比LLDP数据 |
| 单点故障识别 | 找出所有单点故障 | 人工设备验证 |
| 风险等级 | 正确分级P0/P1/P2 | 业务咨询 |
| 建议方案 | 给出具体改进方案 | 技术审核 |

---

## 📌 场景 5: 安全策略问题诊断

### 5.1 功能描述

Expert Agent 能够诊断 ACL、NAT、防火墙等安全策略问题。

### 5.2 测试场景

#### 测试用例 5.1: ACL阻断问题

**故障注入**:
```
Router# conf t
Router# access-list 101 deny icmp any any
Router# int Eth0/1
Router# ip access-group 101 in
Router# exit
Router# exit
Router# wr mem
```

**症状**: ping 无法通过接口

**诊断查询**: "为什么ping无法通过？"

**Expert诊断步骤**:
```
1. show access-list 101
2. show ip interface Eth0/1 | include access list
3. 分析ACL规则
4. 识别问题: ICMP被拒绝
5. 提议修复: deny改为permit
```

#### 测试用例 5.2: NAT翻译问题

类似流程...

---

## 📌 场景 6: 知识库集成与学习

### 6.1 功能描述

Expert Agent 能够：
1. 查询 `.olav/knowledge/solutions/` 中的已知案例
2. 匹配当前问题与历史案例
3. 提出参考解决方案
4. 保存新的诊断案例到知识库

### 6.2 测试用例

#### 测试用例 6.1: 案例库查询与匹配

**预置案例库**:
```
.olav/knowledge/solutions/
├── bgp-flapping-20260101.md
├── ospf-area-mismatch-20260105.md
├── acl-blocking-20260108.md
└── interface-down-20260110.md
```

**测试步骤**:
```
1. Expert Agent 受到诊断任务
2. 执行基本诊断后
3. 查询知识库:
   - 读取 .olav/knowledge/solutions/ 目录
   - 基于关键词（BGP, OSPF, ACL等）检索案例
   - 计算相似度
   - 返回Top 3匹配案例
4. 在报告中引用相关案例
5. 用户验证: 案例确实有帮助
```

**验收标准**:
| 标准 | 要求 | 检验方法 |
|------|------|----------|
| 知识库访问 | 成功读取 solutions/ | 检查文件I/O日志 |
| 案例匹配 | 至少命中1条相关案例 | 比对诊断问题与案例 |
| 相关性 | Top 1相关性 ≥ 70% | 人工评分 |
| 引用 | 报告中正确引用案例 | 查看生成的报告 |
| 学习反馈 | 保存新案例成功 | 验证文件写入 |

#### 测试用例 6.2: 自动学习与保存

**流程**:
```
1. Expert 完成一次诊断与解决
2. 生成解决方案文档
3. 提出保存到知识库: "这个问题的解决方案应该保存为案例"
4. 保存文件: .olav/knowledge/solutions/bgp-route-black-hole-20260211.md
5. 后续查询时可以调用这个案例
```

**验收标准**:
| 标准 | 要求 | 检验方法 |
|------|------|----------|
| 自动保存 | 诊断完成后自动提出保存 | 检查是否提示 |
| 文件生成 | 成功写入 solutions/ | 验证文件存在 |
| 内容完整 | 包含问题/原因/方案/验证 | 查看文件内容 |
| 可检索性 | 后续查询能找到这个案例 | 新查询测试 |

---

## 📌 场景 7: 工具链完整性

### 7.1 功能描述

Expert Agent 需要调用各类工具完成诊断任务。

### 7.2 工具清单

| 工具 | 功能 | 调用方式 |
|------|------|----------|
| **nornir_execute** | 执行CLI命令 | `nornir_execute(device, "show ip bgp summary")` |
| **list_devices** | 列出可用设备 | `list_devices()` 或 `list_devices(filter="role:core")` |
| **search_capabilities** | 搜索命令/能力 | `search_capabilities("BGP", platform="iosxe")` |
| **smart_query** | 智能查询 | `smart_query("R1", "bgp")` → 自动选择命令 |
| **batch_query** | 批量查询 | `batch_query("R1,R2,R3", "bgp")` |
| **research_problem** | 研究问题（知识库+网络搜索） | `research_problem("BGP flapping causes")` |
| **write_file** | 保存诊断文件 | `write_file(".olav/knowledge/solutions/xxx.md", content)` |
| **read_file** | 读取知识库文件 | `read_file(".olav/knowledge/solutions/bgp-flapping.md")` |
| **api_call** | 调用外部API | `api_call("netbox", "get_devices")` |
| **generate_report** | 生成报告 | `generate_report(title, sections)` |

### 7.3 测试用例 7.1: 工具链完整验证

**测试查询**:
```
"诊断为什么R1和R2的BGP邻接不稳定，
并检查这会影响哪些其他设备的路由"
```

**预期工具调用序列**:
```
1. ✅ list_devices() 
   → 获取网络设备列表

2. ✅ smart_query("R1", "bgp")
   → 执行 show ip bgp summary

3. ✅ smart_query("R2", "bgp")
   → 执行 show ip bgp summary

4. ✅ search_capabilities("bgp neighbor", "iosxe")
   → 搜索BGP诊断命令

5. ✅ nornir_execute("R1", "show ip bgp neighbors detail")
   → 获取邻接详情

6. ✅ batch_query("R1,R2,R3,R4", "bgp")
   → 批量查询所有设备BGP状态

7. ✅ research_problem("BGP flapping root causes")
   → 研究BGP颤动的根本原因

8. ✅ write_file("diagnostic_report.md", content)
   → 保存诊断报告

9. ✅ generate_report("BGP诊断报告", sections=[...])
   → 生成格式化报告
```

**验收标准**:
| 标准 | 要求 | 检验方法 |
|------|------|----------|
| 工具调用率 | ≥ 80% 的预期工具被调用 | 检查执行日志 |
| 调用成功率 | 100% 的调用成功 | 检查返回值 |
| 参数正确性 | 参数传递正确 | 验证命令格式 |
| 返回值处理 | 正确使用返回的数据 | 检查后续分析步骤 |
| 错误处理 | 工具失败时有优雅降级 | 测试工具异常场景 |

#### 测试用例 7.2: 工具异常降级

**测试场景**: 某工具调用失败
```
当 nornir_execute 失败时:
- Expert 应尝试备选方法
- 如果无法完全诊断，应告知用户限制
- 不应完全失败或崩溃
```

**验收**: 各工具异常时都有正当的降级处理

---

## 📌 场景 8: 多域交叉问题

### 8.1 功能描述

Expert Agent 能够处理涉及多个网络域的复杂问题（R&S + DC + SP + Security）。

### 8.2 测试场景

#### 测试用例 8.1: 跨域流量问题

**场景**:
```
拓扑: ISP边界 -- 企业边界路由 -- Data Center -- Branch

问题: 从 Branch 访问 DC 数据库速度慢

可能根因（多域）:
1. ISP侧: BGP流量黑洞
2. 企业侧: ACL阻断
3. DC侧: 防火墙限流
4. Security: DDoS防御误判
```

**诊断流程**:
```
1. 初始症状: 远程访问DC数据库慢
2. Expert 分层诊断:
   - Layer 1 (域): 确认问题在哪个域
   - Layer 2 (设备): 在哪个设备
   - Layer 3 (配置): 由什么配置引起
3. 执行跨域查询:
   - show ip route (传输域)
   - show access-list (安全域)
   - show firewall policy (防火墙域)
4. 关联分析
5. 提出综合解决方案
```

**验收标准**:
| 标准 | 要求 | 检验方法 |
|------|------|----------|
| 域识别 | 正确定位问题所在域 | 对比实际问题位置 |
| 分层诊断 | 系统地逐层诊断 | 查看诊断步骤 |
| 跨域关联 | 分析域之间的影响 | 查看关联分析 |
| 综合方案 | 提出涉及多域的解决方案 | 方案覆盖所有相关域 |
| 优先级排序 | 按问题影响程度排序 | 人工评审优先级 |

---

## 📊 验收矩阵

### 场景验收状态

| 场景 | 测试项 | 预期结果 | 实际结果 | 缺陷数 | 状态 |
|------|--------|----------|----------|--------|------|
| 1 | BGP诊断 | PASS | — | — | 📋 |
| 2 | 级联故障 | PASS | — | — | 📋 |
| 3 | OSPF故障 | PASS | — | — | 📋 |
| 4 | 设计缺陷 | PASS | — | — | 📋 |
| 5 | 安全策略 | PASS | — | — | 📋 |
| 6 | 知识库 | PASS | — | — | 📋 |
| 7 | 工具链 | PASS | — | — | 📋 |
| 8 | 多域交叉 | PASS | — | — | 📋 |

### 关键指标

**诊断准确率**:
```
目标: ≥ 85%
计算: 正确诊断的场景数 / 总场景数 × 100
```

**解决方案可执行性**:
```
目标: ≥ 90%
计算: 按建议方案成功解决的场景数 / 建议方案总数 × 100
```

**知识库命中率**:
```
目标: ≥ 70%
计算: 成功匹配案例的诊断数 / 诊断总数 × 100
```

**工具链成功率**:
```
目标: ≥ 95%
计算: 工具调用成功数 / 工具调用总数 × 100
```

**平均诊断时间**:
```
目标: < 45 秒/场景
```

---

## 🛠️ 测试工具与环境

### 测试网络拓扑

```
建议使用:
- GNS3 / EVE-NG 网络模拟环境
- 最少 8 台虚拟设备 (Cisco IOS XE/XR)
- 或使用现有测试网络 (非生产!)

设备推荐配置:
- 2 个核心路由器 (AS 65000, 65001)
- 3 个分发路由器
- 3 个接入交换机
- OSPF Area 0, 1, 2 (测试Area mismatch)
- 各种BGP邻接类型 (iBGP/eBGP)
```

### 测试数据采集

```
需要记录:
1. 每个诊断的执行时间
2. 工具调用序列
3. 知识库命中情况
4. 是否正确调用 write_file 保存案例
5. 生成的报告内容
6. 建议方案的实际执行结果
```

### 诊断验证方法

```
手动验证步骤:
1. 记录故障注入前的网络状态
2. 完成故障注入
3. 对比 Expert 诊断结果与实际故障
4. 执行 Expert 建议的解决方案
5. 验证故障是否真的解决
6. 记录恢复时间
```

---

## 📝 执行计划

### Phase 1: 环境准备 (Week 1)

- [ ] 搭建GNS3/EVE-NG测试网络
- [ ] 配置8个网络设备
- [ ] 验证网络连通性
- [ ] 预置知识库案例库

### Phase 2: 单场景测试 (Week 2-3)

- [ ] 场景1: BGP故障诊断
- [ ] 场景2: 级联故障
- [ ] 场景3: OSPF故障
- [ ] 场景4-5: 设计/安全

### Phase 3: 综合测试 (Week 4)

- [ ] 场景6: 知识库集成
- [ ] 场景7: 工具链完整性
- [ ] 场景8: 多域交叉问题

### Phase 4: 报告与优化 (Week 5)

- [ ] 汇总测试结果
- [ ] 修复发现的缺陷
- [ ] 性能优化
- [ ] 最终验收

---

## 📋 问题跟踪

### 缺陷模板

```
缺陷ID: EXP-001
场景: 场景1 - BGP诊断
症状: Expert 无法识别邻接地址不匹配
严重程度: P1 (阻碍性)
状态: 开放
分配给: [工程师]
```

### 优化建议模板

```
建议ID: EXP-SUG-001
类别: 性能
描述: 诊断时间过长 (> 45秒)
改进方向: 并行执行部分命令
优先级: P2
```

---

## ✅ 验收签字

| 角色 | 姓名 | 日期 | 签字 |
|------|------|------|------|
| 测试负责人 | — | — | — |
| 开发负责人 | — | — | — |
| 产品经理 | — | — | — |
| QA主管 | — | — | — |

---

**文档版本**: v1.0.0  
**创建日期**: 2026年2月11日  
**下一步**: 启动Phase 1 - 环境准备  
**相关文档**: EXPERT_AGENT_TECHNICAL_DESIGN.md, KNOWLEDGE_BASE_INTEGRATION.md
