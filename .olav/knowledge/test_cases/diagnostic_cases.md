# 网络诊断测试案例库 - v0.10.0

## 案例1: CPU高使用率诊断

**症状**: 
- 设备CPU使用率 > 80%
- ping延迟高 > 100ms
- 某些接口速率受限

**根本原因**:
- 内存泄漏导致进程占用过多
- BGP路由计算占用高CPU
- CoPP配置不当导致CPU保护触发

**诊断步骤**:
1. 获取CPU历史统计：`show processes cpu | include CPU`
2. 检查内存使用：`show memory statistics`
3. 分析进程占用：`show processes cpu sorted desc`
4. 检查BGP状态：`show bgp summary`

**解决方案**:
- 升级IOS版本修复bug
- 优化BGP配置（AS路径过滤）
- 增加路由器内存
- 调整CoPP策略

**类似案例**: CPU高 → 内存泄漏 / BGP计算 / CoPP触发

---

## 案例2: 接口Flapping诊断

**症状**:
- 接口频繁up/down
- show interfaces显示error增加
- 物理层中断

**根本原因**:
- 光纤信号衰减（LOS告警）
- 线缆接头接触不良
- 对端设备故障
- MTU不匹配导致frame drop

**诊断步骤**:
1. 查看接口状态：`show interfaces Gi0/0 | include protocol`
2. 检查物理信号：`show interfaces Gi0/0 transceiver detail`
3. 查看error统计：`show interfaces Gi0/0 | include error`
4. 检查配置：`show run interface Gi0/0`

**解决方案**:
- 更换光纤线缆或SPF模块
- 清理接头
- 协调对端设备重启
- 调整MTU配置

**类似案例**: 接口up/down → 光纤问题 / 线缆问题 / 对端故障

---

## 案例3: BGP邻居断连诊断

**症状**:
- BGP邻居在down状态
- 收不到BGP更新
- route表缺少某些前缀

**根本原因**:
- TCP 179端口不通（防火墙阻止）
- 配置错误（邻居IP不对，AS号不对）
- 物理连接故障
- 邻居路由器故障或重启

**诊断步骤**:
1. 查看BGP状态：`show bgp summary`
2. 详细邻居信息：`show bgp neighbor 10.0.0.1`
3. 测试连接：`telnet 10.0.0.1 179`
4. 查看日志：`show log | include BGP`

**解决方案**:
- 修改防火墙ACL允许TCP 179
- 修正BGP配置
- 修复物理连接
- 联系对端管理员

**类似案例**: BGP邻居down → 网络不通 / 配置错 / 对端故障

---

## 案例4: OSPF邻接关系失败诊断

**症状**:
- OSPF邻居显示INIT或EXSTART状态
- 无法建立邻接关系
- 没有收到LSA

**根本原因**:
- 接口MTU配置不同
- HELLO/DEAD时间不同
- 网络类型不匹配
- OSPF认证密钥不匹配

**诊断步骤**:
1. 查看OSPF邻居：`show ip ospf neighbor`
2. 详细邻接信息：`show ip ospf neighbor detail`
3. 检查接口配置：`show ip ospf interface`
4. 审查OSPF配置：`show run | section ospf`

**解决方案**:
- 统一接口MTU
- 同步定时器配置
- 匹配网络类型（broadcast/point-to-point）
- 确认认证密钥一致

**类似案例**: OSPF邻接down → 配置不一致 / MTU不同

---

## 案例5: 路由丢失或黑洞诊断

**症状**:
- 无法ping到某个网络
- traceroute在某个hop停止
- 目标路由不在route表中

**根本原因**:
- 路由协议（BGP/OSPF）未宣告该网络
- 静态路由指向错误的下一跳
- 网络被黑洞（路由存在但无法到达）
- 邻接路由器未正确转发

**诊断步骤**:
1. 查看路由表：`show ip route 10.1.1.0`
2. 检查路由来源：`show ip route summary`
3. 验证连通性：`ping -source <local-ip> 10.1.1.1`
4. 跟踪路径：`traceroute 10.1.1.1`

**解决方案**:
- 检查BGP/OSPF宣告配置
- 修正静态路由下一跳
- 验证中间设备配置
- 添加default-information originate

**类似案例**: 路由丢失 → 协议配置 / 静态路由错 / 下一跳不可达

---

## 案例6: QoS/流控诊断

**症状**:
- 特定流量被限速
- 丢包率高
- 带宽利用率不均衡

**根本原因**:
- QoS策略应用过度限流
- 队列配置不当
- CIR/PIR设置过低
- 拥塞导致自然丢包

**诊断步骤**:
1. 查看接口速率：`show interfaces <int> | include rate`
2. 查看队列统计：`show queuing interface <int>`
3. 检查QoS策略：`show policy-map interface <int>`
4. 查看丢包：`show interfaces <int> | include drops`

**解决方案**:
- 调整QoS policy的rate限制
- 优化队列深度
- 增加链路带宽
- 优化CoS标记

**类似案例**: 流量限速 → QoS策略 / 拥塞 / CIR过低

---

## 测试用途

这个知识库用于测试：

1. **case similarity matching** 
   - 用户症状: "CPU高" 
   - 系统检索到: 案例1 (相似度 > 0.8)

2. **root cause recommendation**
   - 症状关键词: "CPU高 + ping延迟"
   - 推荐: "内存泄漏诊断步骤"

3. **diagnostic steps**
   - 用户问: "如何诊断接口flapping?"
   - 系统返回: 案例2的诊断步骤

4. **solution retrieval**
   - 问题: "接口频繁up/down"
   - 方案: "更换光纤 / 清理接头 / 重启对端"

---

## 向量化说明

运行后自动向量化：
```bash
uv run olav knowledge index
```

这样可以支持语义搜索：
- "网络不通" → 检索BGP/OSPF/路由诊断案例
- "设备缓慢" → 检索CPU/内存/QoS案例
- "连接中断" → 检索Flapping/BGP邻接案例

---

**版本**: v0.10.0  
**创建日期**: 2026-02-04  
**用途**: Unit + E2E测试知识库集成
