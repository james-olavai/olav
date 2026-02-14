# 网络故障注入详细方案 - 命令级细化

**版本**: v1.0.0 (2026-02-11)  
**目标**: 为Expert Agent诊断框架提供真实故障场景，验证诊断准确性  
**设计原则**: 基于实际网络配置快照，每个故障场景都有注入命令→验证命令→恢复命令三段式

---

## 🎯 故障场景总览

| #  | 故障类型 | 难度 | 诊断时间 | 涉及设备 | 验证命令 |
|----|---------|------|---------|---------|---------|
| 1  | BGP邻接断裂（接口层）| 简单 | 30-60s | R1-R2  | `show ip bgp summary` |
| 2  | BGP邻接断裂（配置层）| 中等 | 1-2min | R1-R3  | `show ip bgp neighbors` |
| 3  | OSPF邻接断裂 | 中等 | 1-2min | R1-R2  | `show ip ospf neighbor` |
| 4  | 接口CRC错误激增 | 复杂 | 2-3min | R1-R2  | `show interface` |
| 5  | 配置不匹配 | 复杂 | 2-3min | R2-R3  | `show run \| i bgp` |
| 6  | 路由黑洞（BGP） | 复杂 | 3-5min | R1-R4  | `show ip route bgp` |
| 7  | 路由黑洞（OSPF） | 复杂 | 3-5min | R1-R4  | `show ip route ospf` |

---

## 📋 场景1: BGP邻接断裂 - 接口层故障 (简单)

**故障现象**:
```
R1 的 Gi1 接口与 R2 断开，导致BGP邻接中断
Expected diagnosis: "Link disconnected at Layer1"
Expected root_cause: "GigabitEthernet1 physically down or misconfigured"
```

### 1.1 故障注入

**命令**: 关闭 R1 上的 Gi1 接口

```bash
# 在 R1 上执行
configure terminal
interface GigabitEthernet1
 shutdown
exit
exit
```

### 1.2 验证故障已注入

运行这些命令验证故障状态：

```bash
# R1 上执行 - 验证接口状态
show interface GigabitEthernet1
# 期望: "GigabitEthernet1 is administratively down, line protocol is down"

# R1 上执行 - 验证BGP状态
show ip bgp summary
# 期望: BGP邻接 10.1.12.2 消失或变为Down

# R2 上执行 - 验证从对端看
show ip bgp neighbors 10.1.12.1
# 期望: BGP state = Connect/Idle (未建立连接)

# R1 上执行 - 详细邻接检查
show ip bgp neighbors 10.1.12.2
# 期望: "BGP state = Idle" 或显示连接失败
```

### 1.3 故障诊断工作流

**Expert Agent应该执行的诊断步骤**:

```
Phase 1: 意图识别
├─ 检测到: "bgp neighbor down" (含有BGP关键词)
├─ 位置: 10.1.12.2
└─ 信心度: 0.85

Phase 2: 初始数据收集
├─ Command: show ip bgp summary
├─ Result: 邻接 10.1.12.2 不在列表中 ❌
├─ Command: show interface Gi1
├─ Result: "administratively down" ❌
└─ Command: show ip bgp neighbors | i 10.1.12.2
   Result: 无输出 ❌

Phase 3: 决策树分析 (BGP邻接诊断树)
├─ 节点1: 邻接状态检查
│  ├─ 是否在 show ip bgp summary 中?
│  └─ 答案: NO → 移动到节点2
│
├─ 节点2: 物理连接检查
│  ├─ 本端接口是否UP?
│  │  ├─ Command: show ip interface Gi1
│  │  └─ 答案: NO (administratively down) → 根因找到! ✓
│  │
│  └─ 根因: "Interface administratively shutdown"
│
└─ 信心度: 0.95 (明确证据)

Phase 4: 解决方案生成
├─ 根因: Interface shutdown
├─ 建议步骤:
│  ├─ Step 1: configure terminal
│  ├─ Step 2: interface GigabitEthernet1
│  ├─ Step 3: no shutdown
│  ├─ Step 4: exit / exit
│  └─ Step 5: 验证命令 (见1.4节)
│
└─ 预期结果: BGP邻接快速恢复

Phase 5: 验证报告
├─ 验证规则1: 证据有效性 (0.35权重)
│  ├─ ✓ CLI命令有效
│  ├─ ✓ 输出非空
│  ├─ ✓ 输出可解析
│  └─ 分数: 1.0
│
├─ 验证规则2: RCA逻辑 (0.40权重)
│  ├─ ✓ 无模糊术语 ("也许", "可能" NOT FOUND)
│  ├─ ✓ 由证据支持 (接口确实是shutdown状态)
│  ├─ ✓ 单一清晰根因 (就是接口shutdown)
│  └─ 分数: 0.98
│
├─ 验证规则3: 解决方案可行性 (0.15权重)
│  ├─ ✓ 命令在Cisco IOS中存在
│  ├─ ✓ 有验证步骤
│  ├─ ✓ 无前置条件限制
│  └─ 分数: 1.0
│
├─ 验证规则4: KB相关性 (0.10权重)
│  ├─ 相似案例匹配: BGP interface down (相似度0.95)
│  └─ 分数: 0.95
│
└─ 最终信心分数: 
   0.35×1.0 + 0.40×0.98 + 0.15×1.0 + 0.10×0.95 = 0.987 ✅
```

### 1.4 恢复命令

```bash
# 在 R1 上执行
configure terminal
interface GigabitEthernet1
 no shutdown
exit
exit
```

### 1.5 验证恢复成功

```bash
# R1 上执行 - 验证接口恢复
show interface GigabitEthernet1
# 期望: "GigabitEthernet1 is up, line protocol is up"

# R1 上执行 - 验证BGP邻接恢复
show ip bgp summary
# 期望: 邻接 10.1.12.2 重新出现，State为 Established
# 示例:
# Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down State/PfxRcd
# 10.1.12.2       4 65001     ...     ...       ... 0    0  00:00:42 1

# R1 上执行 - 详细验证
show ip bgp neighbors 10.1.12.2
# 期望: "BGP state = Established" 且 "up for 00:00:XX"
```

### 1.6 幻觉风险评估

**低幻觉风险** ✅

为什么这个场景诊断准确?
- ✓ 物理状态非常明确 (UP/DOWN)
- ✓ 命令输出无歧义 (administratively down)
- ✓ 解决方案直接反向 (shutdown → no shutdown)
- ✓ 验证非常快速 (<5秒)

---

## 📋 场景2: BGP邻接断裂 - 配置层故障 (中等难度)

**故障现象**:
```
R1 与 R3 的BGP会话建立成功，但突然配置了peer-as-override，导致邻接中断
Expected diagnosis: "BGP configuration mismatch - AS number verification failed"
```

### 2.1 故障注入

在 R1 上修改BGP配置，引入配置不匹配：

```bash
# 在 R1 上执行
configure terminal
router bgp 65000
 neighbor 3.3.3.3 remote-as 65001
 # 本意是改为65000但误配为65001
exit
exit

# 验证配置已改
show run | i bgp -A 5
```

### 2.2 验证故障已注入

```bash
# R1 上执行 - BGP邻接状态
show ip bgp summary
# 期望: R3 (3.3.3.3) 邻接消失或进入不稳定状态

# R1 上执行 - 邻接详情
show ip bgp neighbors 3.3.3.3
# 期望: "BGP state = Connect/Idle" 或 "Invalid OPEN packet received"

# R3 上执行 - 从对端看
show ip bgp neighbors 1.1.1.1  
# 期望: 状态为Idle/Connect (未建立)

# 日志检查 - 查看错误
show log | i bgp
# 期望包含: "OPEN message error" 或 "Remote AS" 相关错误
```

### 2.3 故障诊断工作流

**Expert Agent应该执行的诊断步骤**:

```
Phase 1: 意图识别
├─ 检测到: "bgp neighbor down" 
├─ 邻接地址: 3.3.3.3
└─ 信心度: 0.85

Phase 2: 初始数据收集
├─ Command: show ip bgp summary
├─ Result: 邻接3.3.3.3不在Established状态
├─ Command: show ip bgp neighbors 3.3.3.3
├─ Result: BGP state = Idle
├─ Command: show run | i bgp neighbor 3.3.3.3
// Result: "neighbor 3.3.3.3 remote-as 65001" (WRONG! Should be 65000)
└─ Command: show log | i bgp | i 3.3.3.3
   Result: "Invalid remote AS" 错误日志

Phase 3: 决策树分析 (BGP邻接诊断树)
├─ 节点1: 邻接状态
│  ├─ 在summary中? NO → 节点2
│
├─ 节点2: 接口连通性
│  ├─ Command: ping 3.3.3.3
│  └─ Result: 可通 ✓ → 节点3
│
├─ 节点3: BGP配置检查
│  ├─ 本端remote-as: show run | i neighbor 3.3.3.3
│  │  Result: remote-as 65001 (WRONG!)
│  ├─ 对端remote-as: 应该配置为本端AS号(65000)
│  │  但本端配置的是65001 → 不匹配!
│  └─ 根因发现: AS号配置不匹配 ✓
│
├─ 节点4: 配置验证
│  ├─ 本端AS: 65000 ✓
│  ├─ 邻接3.3.3.3应该的remote-as: 65000 (与对端相同)
│  ├─ 实际配置: 65001 (WRONG!)
│  └─ 信心度: 0.92
│
└─ 根因确认: "BGP neighbor AS mismatch: configured 65001 but should be 65000"

Phase 4: 解决方案
├─ 识别错误配置
│  └─ "neighbor 3.3.3.3 remote-as 65001" 错误
│
├─ 生成修正步骤
│  ├─ Step 1: configure terminal
│  ├─ Step 2: router bgp 65000
│  ├─ Step 3: neighbor 3.3.3.3 remote-as 65000
│  ├─ Step 4: exit / exit
│  └─ Step 5: 验证
│
└─ 预期结果: BGP邻接立即恢复

Phase 5: 验证报告
├─ 验证规则1: 证据有效性 (0.35)
│  ├─ ✓ 配置命令显示存在
│  ├─ ✓ 日志有错误记录
│  └─ 分数: 0.95
│
├─ 验证规则2: RCA逻辑 (0.40)
│  ├─ ✓ 无模糊术语
│  ├─ ✓ 配置错误是直接原因
│  ├─ ✓ 单一根因: AS号不匹配
│  └─ 分数: 0.98
│
├─ 验证规则3: 解决方案可行性 (0.15)
│  ├─ ✓ 修正配置存在且有效
│  ├─ ✓ 无需重启进程
│  └─ 分数: 1.0
│
└─ 最终分数: 0.35×0.95 + 0.40×0.98 + 0.15×1.0 = 0.973 ✅
```

### 2.4 恢复命令

```bash
# 在 R1 上执行
configure terminal
router bgp 65000
 neighbor 3.3.3.3 remote-as 65000
exit
exit

# 验证修改
show run | i neighbor 3.3.3.3
# 期望: "neighbor 3.3.3.3 remote-as 65000"
```

### 2.5 验证恢复成功

```bash
# R1 上执行 - 立即验证
show ip bgp summary
# 期望: 邻接3.3.3.3恢复到 Established，几秒内生效

# R1 上执行 - 邻接细节
show ip bgp neighbors 3.3.3.3
# 期望: BGP state = Established

# 双向验证
show ip bgp neighbors 3.3.3.3 | i "BGP state"
show ip bgp neighbors 3.3.3.3 | i "up for"
```

---

## 📋 场景3: OSPF邻接断裂 (中等难度)

**故障现象**:
```
R1 与 R2 通过OSPF相连，但因网络参数不匹配导致邻接断裂
Expected diagnosis: "OSPF configuration mismatch - parameters don't match"
```

### 3.1 故障注入

修改 R1 上的OSPF网络参数：

```bash
# 在 R1 上执行
configure terminal
interface GigabitEthernet1
 ip ospf hello-interval 20
 # 原来是10秒，改为20秒会导致不匹配
exit
exit

# 验证
show int Gi1 | i ospf
```

### 3.2 验证故障已注入

```bash
# R1 上执行 - OSPF邻接列表
show ip ospf neighbor
# 期望: Gi1 上的邻接 10.1.12.2 消失或进入 INIT/EXSTART 状态

# R1 上执行 - 邻接详情
show ip ospf neighbor detail
# 期望: 看到下列消息之一
# - "State = INIT" (初始化，等待Hello)
# - "State is INIT" (卡在初始化阶段)
# - "Dead timer expires in ...sec" (计时器异常)

# R1 上执行 - Hello参数验证
show int Gi1 | i "ospf"
# 期望: "ospf hello-interval 20"

# 日志检查
show log | i ospf | i hello
# 期望: "hello interval mismatch" 或类似消息
```

### 3.3 故障诊断工作流

```
Phase 1: 意图识别
├─ 检测到: "ospf neighbor down"
├─ 设备/接口: R1 Gi1
└─ 信心度: 0.80

Phase 2: 数据收集
├─ Command: show ip ospf neighbor
├─ Result: Gi1邻接消失或Init状态
├─ Command: show ip ospf neighbor detail
├─ Result: 显示INIT状态，Dead timer异常
├─ Command: show interface Gi1 | i ospf
├─ Result: ospf hello-interval 20
├─ Command: show ip ospf int Gi1 | i interval
└─ Result: hello interval 20, dead interval 80

Phase 3: 决策树分析
├─ 节点1: OSPF邻接存在?
│  ├─ Command: show ip ospf neighbor | i 10.1.12.2
│  └─ Result: NO → 节点2
│
├─ 节点2: 接口UP?
│  ├─ Result: YES (Gi1 up/up) → 节点3
│
├─ 节点3: OSPF配置检查
│  ├─ 本接口Hello: 20秒
│  ├─ 对端接口Hello: 10秒 (不一致!)
│  └─ 根因初现: 参数不匹配
│
├─ 节点4: 参数验证
│  ├─ 检查Hello: 本20s vs对10s ❌
│  ├─ 检查Dead: 本80s vs对40s ❌
│  ├─ 检查Area: 都是0.0.0.0 ✓
│  ├─ 检查Auth: 都是None ✓
│  └─ 根因: "Hello interval mismatch (20 vs 10)"
│
└─ 信心度: 0.88

Phase 4: 解决方案
├─ 问题: R1的Gi1 Hello间隔为20秒，不匹配  
├─ 建议:
│  ├─ Step 1: configure terminal
│  ├─ Step 2: interface GigabitEthernet1
│  ├─ Step 3: no ip ospf hello-interval
│  │  (恢复默认10秒)
│  ├─ Step 4: exit / exit
│  └─ Step 5: 验证 (show ip ospf neighbor)
│
└─ 预期: 邻接在几秒内恢复

Phase 5: 验证
├─ 证据有效性: 0.92
├─ RCA逻辑: 0.95
├─ 解决方案可行: 1.0
└─ 最终分数: 0.35×0.92 + 0.40×0.95 + 0.15×1.0 = 0.953 ✅
```

### 3.4 恢复命令

```bash
# 在 R1 上执行
configure terminal
interface GigabitEthernet1
 no ip ospf hello-interval
exit
exit

# 验证恢复
show ip ospf neighbor detail
# 期望: 邻接迅速转为FULL状态
```

---

## 📋 场景4: 接口CRC错误激增 (复杂)

**故障现象**:
```
R1 的 Gi1 接口CRC错误快速增长，导致BGP邻接不稳定
Expected diagnosis: "Physical layer issue - high CRC error rate"
```

### 4.1 故障注入

模拟CRC错误增长：

```bash
# 在 R1 上执行（需要nornir/netmiko支持）
# 这里代表通过配置或脚本增加CRC错误计数
# 实际操作需要网络模拟器或真实硬件

# 对于纯命令演示：
configure terminal
interface GigabitEthernet1
 # 注入流量噪声（实际需要硬件支持）
 # 或通过脚本模拟：增加接口计数器
exit
exit
```

### 4.2 验证故障已注入

```bash
# R1 上执行 - 查看接口统计
show interface GigabitEthernet1
# 期望输出变化:
# 原来:   "0 CRC"
# 现在:   "128 CRC" 或更高

# R1 上执行 - 继续监控
show interface Gi1 | i "CRC"
# 期望: 数字持续增长

# 对端R2也会受影响
# R2 上执行
show interface GigabitEthernet1 | i CRC
# 期望: 也会看到CRC错误
```

### 4.3 故障诊断工作流

```
Phase 1: 意图识别
├─ 检测到: 接口错误、BGP不稳定
├─ 诊断类型: 物理层故障
└─ 信心度: 0.75 (需要更多证据)

Phase 2: 数据收集
├─ Command: show interface Gi1
├─ Result: CRC errors: 128
├─ Command: show ip bgp summary
├─ Result: BGP邻接在Established和Connect之间闪跳
├─ Command: show interfaces Gi1 | i "error|drop"
├─ Result: 多种错误类型出现
│  - 0 runts
│  - 0 giants
│  - 0 CRC ✓ (我们注入的!)
│  - 0 frame
│  └─ 0 overrun
└─ Command: show processes cpu
   Result: CPU正常，不是软件问题

Phase 3: 决策树分析
├─ 节点1: BGP邻接状态
│  ├─ Command: show ip bgp summary
│  └─ Result: 邻接时Up时Down (flapping) → 节点2
│
├─ 节点2: 接口物理状态
│  ├─ Command: show interface Gi1
│  ├─ Status: "up, line protocol is up" ✓
│  ├─ 但错误计数异常高 → 节点3
│
├─ 节点3: 错误类型分析
│  ├─ 命令: show int Gi1
│  ├─ CRC errors: 128 ❌ (异常!)
│  ├─ Input errors: 相应增加
│  ├─ 其他: runts/giants/frame都为0 ✓
│  └─ 诊断: "Likely CRC/physical issue" → 节点4
│
├─ 节点4: 源头确认
│  ├─ 检查对端: show int Gi1 on R2
│  │  也显示CRC errors ❌
│  ├─ 检查CPU/进程: 正常 ✓
│  ├─ 检查协议状态: Down/Up闪跳
│  └─ 根因: "High CRC error rate on physical link"
│
└─ 信心度: 0.82

Phase 4: 解决方案
├─ 根因: 物理链路质量下降，CRC错误增多
├─ 建议:
│  ├─ 立即检查:
│  │  ├─ 光模块信号强度 (SFP optical power)
│  │  ├─ 光纤连接器清洁度
│  │  └─ 网线连接是否松动
│  ├─ 临时改进:
│  │  ├─ Step 1: 重启接口
│  │  │  # shutdown → no shutdown
│  │  ├─ Step 2: 检查link质量
│  │  │  # show int Gi1
│  │  └─ Step 3: 续监控
│  │
│  └─ 长期解决:
│     ├─ 更换光模块/网线
│     ├─ 清洁光纤连接器
│     └─ 检查对端设备
│
└─ 预期: 如果是硬件问题，重启可能临时改善

Phase 5: 验证
├─ 证据有效性: 0.88
│  ├─ ✓ 接口计数器显示
│  ├─ ✓ 影响是对称的 (R1和R2都看到)
│  └─ ✓ 其他错误类型无异常
│
├─ RCA逻辑: 0.80
│  ├─ ⚠️ 物理层问题有多种可能
│  │  (光模块、网线、连接器)
│  ├─ ✓ 但确实指向物理链路
│  └─ ✓ 消除了软件故障
│
├─ 解决方案可行性: 0.75
│  ├─ ⚠️ 可能需要现场操作
│  ├─ ✓ 但有明确的检查步骤
│  └─ ✓ 临时重启可以尝试
│
└─ 最终分数: 0.35×0.88 + 0.40×0.80 + 0.15×0.75 = 0.829 ✅
   (此类物理故障的信心度通常较低，0.83可接受)
```

### 4.4 恢复命令

```bash
# 在 R1 上执行 - 尝试重启接口
configure terminal
interface GigabitEthernet1
 shutdown
 no shutdown
exit
exit

# 监控恢复过程
show interface Gi1 | i "CRC|input errors"
# 期望: CRC错误不再增长（已连接，可能保留老的计数)

# 查看BGP恢复状态
show ip bgp summary
# 期望: 邻接稳定回到 Established
```

---

## 📋 场景5: 配置不匹配导致的路由黑洞 (复杂)

**故障现象**:
```
R2 配置了错误的BGP网络声明，导致某些路由消失
Expected diagnosis: "BGP network statement missing correct AFI/SAFI"
```

### 5.1 故障注入

```bash
# 在 R2 上执行
configure terminal
router bgp 65001
 # 删除正确的网络声明
 no network 2.2.2.0 mask 255.255.255.0
 # 改为错误的
 network 2.2.2.0 mask 255.255.255.128
exit
exit

# 或者完全删除导出某个网络
router bgp 65001
 no network 192.168.0.0 mask 255.255.0.0
exit
exit
```

### 5.2 验证故障已注入

```bash
# R2 上执行 - 查看BGP宣告
show ip bgp
# 期望: 某些网络消失

# R2 上执行 - 查看本地宣告
show ip bgp summary
# 期望: "2 network entries" 而不是原来的 "3 network entries"

# R1 上执行 - 从对端看
show ip bgp neighbors 10.1.12.1 advertised-routes
# 期望: 看不到 2.2.2.0 或看到错误的前缀

# R4 上执行 - 如果依赖这个路由
show ip route bgp
# 期望: 相关路由消失
```

### 5.3 恢复命令

```bash
# 在 R2 上执行
configure terminal
router bgp 65001
 # 恢复正确的宣告
 network 2.2.2.0 mask 255.255.255.0
 no network 2.2.2.0 mask 255.255.255.128
exit
exit

# 验证
show ip bgp | i 2.2.2
# 期望: 网络重新出现
```

---

## 📋 场景6: BGP路由黑洞 - 无效下一跳 (复杂)

**故障现象**:
```
R1 学习到通过R4来的某个路由，但R4的下一跳地址无效
Expected diagnosis: "BGP route learned with invalid next-hop"
```

### 6.1 故障注入

```bash
# 在 R4 上执行
configure terminal
router bgp 65001
 neighbor 1.1.1.1 route-map POISON-NEXTHOP out
exit

route-map POISON-NEXTHOP permit 10
 set ip next-hop 255.255.255.255
 # 设置无效的下一跳地址
exit

# 或者配置本身错误的邻接宣告
router bgp 65001
 # 宣告一个不存在的网络
 network 172.31.0.0 mask 255.255.0.0
exit
```

### 6.2 验证故障已注入

```bash
# R1 上执行 - 查看学习到的路由
show ip bgp
# 期望: 看到来自R4的路由，但下一跳异常

# R1 上执行 - 查看路由表
show ip route bgp
# 期望: 不显示该路由 (因为下一跳无效)

# R1 上执行 - 检查邻接宣告
show ip bgp neighbors 4.4.4.4 received-routes
# 期望: 看到异常路由

# ping测试
ping {destination_from_withdrawn_route}
# 期望: 不可达
```

### 6.3 恢复命令

```bash
# 在 R4 上执行
configure terminal
router bgp 65001
 no neighbor 1.1.1.1 route-map POISON-NEXTHOP out
 no network 172.31.0.0 mask 255.255.0.0
exit

no route-map POISON-NEXTHOP
exit

# 或使用route-map来修复
route-map POISON-NEXTHOP permit 10
 set ip next-hop 4.4.4.4
 # 将下一跳改为有效地址
exit
```

---

## 📋 场景7: OSPF路由黑洞 - 成本错误配置 (复杂)

**故障现象**:
```
R1 到达某个通过OSPF学习的网络的路由成本异常高，导致选路错误
Expected diagnosis: "OSPF interface cost misconfiguration"
```

### 7.1 故障注入

```bash
# 在 R2 上执行
configure terminal
interface GigabitEthernet1
 # 原来成本是1，改为非常高
 ip ospf cost 65535
 # OSPF成本最高为65535，设置为max会导致该路由不被选择
exit
exit

# 查看接口配置
show run | i ospf cost
```

### 7.2 验证故障已注入

```bash
# R2 上执行 - 查看接口成本
show ip ospf interface Gi1 | i Cost
# 期望: "Process ID 1, Router ID 2.2.2.2, Network Type BROADCAST, Cost: 65535"

# R1 上执行 - 查看到达R4的路由
show ip route ospf
# 期望: 通过R2到R4的路由的metric变得异常高
# 或可能显示通过R3的备用路由

# 追踪路由
traceroute 4.4.4.4
# 期望: 显示备用路径 (通过R3而不是R2)
```

### 7.3 故障诊断工作流

```
Phase 1: 意图识别
├─ 检测到: 路由不优化/选路异常
├─ 网络: OSPF域
└─ 信心度: 0.80

Phase 2: 数据收集
├─ Command: show ip route ospf
├─ Result: 通往某个网络的成本很高
├─ Command: traceroute {destination}
├─ Result: 路由不经过预期的短路径
├─ Command: show ip ospf database
├─ Result: 显示路由计算结果
└─ Command: show interface details
   Result: 某个接口成本设置异常

Phase 3: 决策树分析
├─ 节点1: 邻接状态
│  ├─ Command: show ip ospf neighbor
│  └─ Result: 所有邻接都是FULL ✓ → 节点2
│
├─ 节点2: 路由学习状态
│  ├─ Routes learned: YES ✓
│  ├─ 但某些成本异常 → 节点3
│
├─ 节点3: 成本计算检查
│  ├─ 通过R2到R4: 成本 = 65535 + X (WRONG!)
│  ├─ 通过R3到R4: 成本 = 1 + Y (正常)
│  └─ 选择: R3路由 (成本更低) → 节点4
│
├─ 节点4: R2成本来源
│  ├─ 查看R2接口Gi1配置:
│  │  ip ospf cost 65535 (WRONG!)
│  ├─ 应该的成本: 1
│  └─ 根因: "Interface cost misconfigured on R2 Gi1"
│
└─ 信心度: 0.89

Phase 4: 解决方案
├─ 问题: R2的Gi1 OSPF成本设置为65535
├─ 建议:
│  ├─ Step 1: configure terminal
│  ├─ Step 2: interface GigabitEthernet1
│  ├─ Step 3: no ip ospf cost
│  │  (恢复自动计算)
│  ├─ Step 4: exit / exit
│  └─ Step 5: 验证
│
└─ 预期: 路由自动重新计算，选路改善

Phase 5: 验证 (scores)
├─ 证据有效性: 0.93
├─ RCA逻辑: 0.91
├─ 解决方案可行: 0.95
└─ 最终: 0.35×0.93 + 0.40×0.91 + 0.15×0.95 = 0.922 ✅
```

### 7.4 恢复命令

```bash
# 在 R2 上执行
configure terminal
interface GigabitEthernet1
 no ip ospf cost
 # 恢复自动计算
exit
exit

# 验证OSPF重新计算路由
show ip ospf interface Gi1 | i Cost
# 期望: Cost恢复到正常值 (通常 100000 / bandwidth)

# 验证R1的路由选择改善
show ip route ospf
# 期望: 路由重新优化

# 追踪验证
traceroute 4.4.4.4
# 期望: 通过R2而不是R3
```

---

## 🎯 故障注入执行清单

### 快速参考表

| 故障 | 注入命令位置 | 验证命令 | 恢复命令 | 时间 |
|------|-----------|---------|---------|------|
| **1. BGP接口Down** | R1 Gi1 shutdown | show int Gi1 | no shutdown | 30s |
| **2. BGP AS配置错** | R1 neighbor AS | show run \| i bgp | 改正remote-as | 60s |
| **3. OSPF参数不匹 | R1 Gi1 hello-interval | show int Gi1 \| i ospf | no ip ospf hello | 60s |
| **4. CRC错误激增** | R1-R2 物理层 | show int Gi1 \| i CRC | shutdown/no shutdown | 90s |
| **5. BGP网络错 | R2 router bgp | show ip bgp | no network/network | 60s |
| **6. BGP下一跳坏** | R4 route-map | show ip bgp neighbors | 改正route-map | 90s |
| **7. OSPF成本崁** | R2 Gi1 cost | show ip ospf int Gi1                | no ip ospf cost | 60s |

---

## 📊 幻觉风险分析

### 红旗标志 🚩 (高幻觉风险)

这些故障SCENARIO中LLM容易幻觉：
- ❌ 场景5/6/7: 多跳路由问题（难精确诊断）
- ❌ 场景4: 物理层问题（可能多个根因）
- ❌ 混合故障：多个问题同时出现

### 绿旗标志 ✅ (低幻觉风险)

这些故障中诊断准确：
- ✅ 场景1: 接口状态（binary: up/down）
  - 证据：接口状态显示非常明确
  - 解决：直接反向操作
  - 验证：立即见效

- ✅ 场景2: BGP配置（binary: 匹配/不匹配）
  - 证据：配置命令显示
  - 解决：修正配置
  - 验证：快速恢复

- ✅ 场景3: OSPF参数（可数值状态）
  - 证据：参数值清晰对比
  - 解决：同步参数
  - 验证：邻接快速回到Full

---

## 🔗 与Expert Agent诊断框架集成

这些故障场景直接对应于 `SKILL_DIAGNOSTIC_WORKFLOW.md` 中定义的：

### 决策树映射

```
Scenario 1 (BGP-接口Down)
  → diagnostic_trees.bgp_neighbor_down
  → 节点1: State check
  → 节点2: Layer3检查
  → 节点3: Interface检查 ← 在这里诊断
  
Scenario 2 (BGP-配置错)
  → diagnostic_trees.bgp_neighbor_down
  → 节点1: State check
  → 节点3: Interface检查 ✓
  → 节点4: 配置诊断树 ← 定位问题
  
Scenario 3 (OSPF参数)
  → diagnostic_trees.ospf_neighbor_down
  → 节点1: Neighbor状态
  → 节点2: Parameter comparison ← 诊断
  → 节点3: 同步参数
```

### 约束验证映射

```
所有Scenario都应该通过 ExpertConstraints 验证：

✓ 信心度检查: ≥0.80
✓ 证据检查: ≥2个来源
✓ 禁用词检查: 无"也许"/"可能"
✓ 解决方案检查: 包含验证步骤

预期结果：
├─ Scenario 1: 信心度0.95 (非常准确)
├─ Scenario 2: 信心度0.93 (准确)
├─ Scenario 3: 信心度0.88 (可信)
├─ Scenario 4: 信心度0.82 (可接受)
├─ Scenario 5: 信心度0.85 (可接受)
├─ Scenario 6: 信心度0.80 (边界)
└─ Scenario 7: 信心度0.92 (准确)

目标: 所有Scenario信心度 ≥ 0.80 ✅
```

---

## 🧪 执行步骤

### 测试一个完整故障周期：

```bash
# 1. 选择故障（例如Scenario 1）
# 2. 运行注入命令
#    configure terminal
#    interface GigabitEthernet1
#    shutdown
#    exit
#    exit

# 3. 验证故障已现
#    show interface GigabitEthernet1
#    show ip bgp summary

# 4. 运行Expert Agent诊断
#    olav ask "R1和R2之间的BGP邻接不工作，请诊断"

# 5. 记录Expert返回的诊断报告
#    ├─ Root cause identified?
#    ├─ Confidence score?
#    ├─ Solution suggested?
#    └─ Vague terms present? (检查幻觉)

# 6. 运行恢复命令
#    configure terminal
#    interface GigabitEthernet1
#    no shutdown
#    exit
#    exit

# 7. 验证恢复完整
#    show interface GigabitEthernet1
#    show ip bgp summary
```

---

## 📈 验收标准

对于每个故障Scenario，Expert Agent诊断应该满足：

| 标准 | Scenario 1-3 | Scenario 4-7 | 检查方法 |
|------|------------|------------|---------|
| **诊断准确度** | ≥90% | ≥85% | 与实际根因对比 |
| **根因识别** | 准确 | 可接受 | 检查诊断报告 |
| **信心度得分** | ≥0.90 | ≥0.80 | 从DiagnosisReport读取 |
| **无幻觉词** | ✅ 不含 | ✅ 不含 | 检查"也许"/"可能" |
| **有解决方案** | ✅ 具体 | ✅ 具体 | 检查建议步骤 |
| **可验证** | ✅ 能<10s | ✅ 能<30s | 手工验证 |

---

**版本历史**

- v1.0.0 (2026-02-11): 初版7个故障场景，细化到命令和恢复步骤
