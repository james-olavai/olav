# Expert Agent 故障注入与知识库集成指南

**文档版本**: v1.0.0  
**创建日期**: 2026年2月11日  
**状态**: 📋 规划中  
**用途**: 测试环境设置、故障场景构建、知识库初始化

---

## 📋 文档概述

本文档提供 Expert Agent 测试的实际操作指南，包括：
1. 故障注入方法与脚本
2. 知识库初始化与案例编写
3. 测试场景执行步骤
4. 诊断验证方法

---

## 🔧 故障注入工具集

### 1. 故障注入框架

```python
#!/usr/bin/env python3
"""
故障注入工具 - fault_injector.py

使用方法:
  from fault_injector import FaultInjector
  
  injector = FaultInjector(device="R1", env="gns3")
  injector.inject_fault("bgp_down")
  time.sleep(10)  # 让诊断系统检测故障
  result = diagnose()
  injector.recover_fault()
"""

class FaultInjector:
    """故障注入器 - 在网络设备上注入可控的故障"""
    
    def __init__(self, device: str, env: str = "gns3"):
        """
        初始化
        - device: 设备名称 (e.g., "R1", "R2")
        - env: 环境 ("gns3", "eve-ng", "real")
        """
        self.device = device
        self.env = env
        self.connection = None
        self.original_config = {}
        
    def inject_fault(self, fault_type: str, **kwargs) -> Dict:
        """
        注入故障
        
        支持的故障类型:
        - "bgp_down": BGP邻接DOWN
        - "bgp_route_black_hole": BGP路由黑洞
        - "ospf_area_mismatch": OSPF Area不匹配
        - "ospf_neighbor_down": OSPF邻接DOWN
        - "interface_down": 物理接口DOWN
        - "acl_blocking": ACL阻断流量
        - "link_flapping": 链路颤动
        - "cpu_high": CPU高占用
        """
        
        if fault_type == "bgp_down":
            return self._inject_bgp_down(**kwargs)
        elif fault_type == "bgp_route_black_hole":
            return self._inject_bgp_route_black_hole(**kwargs)
        elif fault_type == "ospf_area_mismatch":
            return self._inject_ospf_area_mismatch(**kwargs)
        # ... 其他故障类型
        
    def _inject_bgp_down(self, neighbor_ip: str) -> Dict:
        """注入BGP邻接DOWN故障"""
        
        commands = [
            "conf t",
            "router bgp 65000",
            f"no neighbor {neighbor_ip}",  # 删除邻接
            f"neighbor 10.255.255.255 remote-as 65001",  # 配置不可达的邻接IP
            "exit",
            "exit",
            "wr mem"
        ]
        
        # 保存原始配置
        self.original_config['bgp_down'] = {
            'original_neighbor': neighbor_ip,
            'timestamp': time.time()
        }
        
        # 执行故障注入
        result = self._execute_commands(commands)
        
        return {
            "fault_type": "bgp_down",
            "device": self.device,
            "injection_time": time.time(),
            "status": "injected",
            "expected_symptom": "BGP邻接从Established变为Idle"
        }
    
    def _inject_ospf_area_mismatch(self, interface: str) -> Dict:
        """注入OSPF Area不匹配故障"""
        
        # 首先获取当前配置
        current_config = self._get_ospf_config()
        
        # 保存原始配置
        self.original_config['ospf_area_mismatch'] = current_config
        
        # 修改Area ID
        commands = [
            "conf t",
            "router ospf 1",
            f"no network {self._get_interface_ip(interface)} area {current_config['area']}",
            f"network {self._get_interface_ip(interface)} area 2",  # 改为Area 2
            "exit",
            "exit",
            "wr mem"
        ]
        
        result = self._execute_commands(commands)
        
        return {
            "fault_type": "ospf_area_mismatch",
            "device": self.device,
            "interface": interface,
            "original_area": current_config['area'],
            "modified_area": 2,
            "expected_symptom": "OSPF邻接从Establish变为Down,查看日志显示Area mismatch"
        }
    
    def _inject_interface_down(self, interface: str) -> Dict:
        """注入接口DOWN故障"""
        
        commands = [
            "conf t",
            f"int {interface}",
            "shutdown",
            "exit",
            "exit",
            "wr mem"
        ]
        
        self.original_config['interface_down'] = {
            'interface': interface,
            'timestamp': time.time()
        }
        
        result = self._execute_commands(commands)
        
        return {
            "fault_type": "interface_down",
            "device": self.device,
            "interface": interface,
            "expected_symptom": f"接口 {interface} 状态为down,BGP/OSPF邻接断开"
        }
    
    def _inject_acl_blocking(self, direction: str = "in") -> Dict:
        """注入ACL阻断故障"""
        
        commands = [
            "conf t",
            "access-list 101 deny icmp any any",
            "access-list 101 permit ip any any",
            "int Eth0/1",
            f"ip access-group 101 {direction}",
            "exit",
            "exit",
            "wr mem"
        ]
        
        self.original_config['acl_blocking'] = {
            'timestamp': time.time()
        }
        
        return {
            "fault_type": "acl_blocking",
            "device": self.device,
            "expected_symptom": "ICMP流量被阻断,ping无响应"
        }
    
    def recover_fault(self, fault_type: str = None) -> Dict:
        """
        恢复故障
        
        如果不指定fault_type,则恢复最后一次注入的故障
        """
        
        if fault_type is None:
            # 恢复最后一次
            fault_type = list(self.original_config.keys())[-1]
        
        if fault_type not in self.original_config:
            return {"status": "error", "message": f"No config found for {fault_type}"}
        
        if fault_type == "bgp_down":
            return self._recover_bgp_down()
        elif fault_type == "ospf_area_mismatch":
            return self._recover_ospf_area_mismatch()
        elif fault_type == "interface_down":
            return self._recover_interface_down()
        elif fault_type == "acl_blocking":
            return self._recover_acl_blocking()
    
    def _recover_bgp_down(self) -> Dict:
        """恢复BGP邻接"""
        
        config = self.original_config['bgp_down']
        neighbor_ip = config['original_neighbor']
        
        commands = [
            "conf t",
            "router bgp 65000",
            f"no neighbor 10.255.255.255 remote-as 65001",
            f"neighbor {neighbor_ip} remote-as 65001",
            "exit",
            "exit",
            "wr mem"
        ]
        
        result = self._execute_commands(commands)
        
        return {
            "status": "recovered",
            "fault_type": "bgp_down",
            "recovery_time": time.time() - config['timestamp']
        }
    
    def _execute_commands(self, commands: List[str]) -> str:
        """在设备上执行命令"""
        
        if self.env == "gns3":
            # 连接到GNS3设备
            return self._execute_on_gns3(commands)
        elif self.env == "eve-ng":
            return self._execute_on_eve_ng(commands)
        elif self.env == "real":
            return self._execute_on_real_device(commands)
    
    def _execute_on_gns3(self, commands: List[str]) -> str:
        """在GNS3模拟器中执行命令"""
        # 使用Netmiko连接GNS3设备
        from netmiko import ConnectHandler
        
        device = {
            'device_type': 'cisco_ios',
            'host': self._get_device_ip(),
            'username': 'admin',
            'password': 'admin',
            'secret': 'admin',
            'conn_timeout': 10
        }
        
        try:
            net_connect = ConnectHandler(**device)
            output = net_connect.send_config_set(commands)
            net_connect.disconnect()
            return output
        except Exception as e:
            logger.error(f"执行命令失败: {e}")
            return None
    
    def get_fault_status(self) -> Dict:
        """获取当前故障状态"""
        
        return {
            "device": self.device,
            "injected_faults": list(self.original_config.keys()),
            "timestamp": time.time()
        }
```

### 2. 故障场景脚本

#### 场景1: BGP邻接故障注入脚本

```python
#!/usr/bin/env python3
"""
BGP邻接故障场景 - scenario_bgp_down.py

执行: python scenario_bgp_down.py
"""

from fault_injector import FaultInjector
import time

def run_bgp_down_scenario():
    """BGP邻接DOWN故障场景"""
    
    print("=" * 60)
    print("场景: BGP邻接DOWN诊断")
    print("=" * 60)
    
    # 初始化
    injector = FaultInjector(device="R1", env="gns3")
    
    # Step 1: 获取基线数据
    print("\n[Step 1] 获取基线数据...")
    baseline = {
        "bgp_status": smart_query("R1", "bgp"),
        "neighbors": nornir_execute("R1", "show ip bgp neighbors"),
        "timestamp": time.time()
    }
    print(f"✓ BGP状态: Established")
    print(f"✓ 邻接: R1(10.0.0.1) <---> R2(10.0.0.2)")
    
    # Step 2: 注入故障
    print("\n[Step 2] 注入故障...")
    fault = injector.inject_fault("bgp_down", neighbor_ip="10.0.0.2")
    print(f"✓ 故障注入时间: {time.ctime()}")
    print(f"✓ 预期症状: BGP邻接状态变为Idle")
    
    # Step 3: 等待故障生效
    print("\n[Step 3] 等待故障生效...")
    time.sleep(5)  # 等待BGP状态机更新
    print(f"✓ 时间已过: 5秒")
    
    # Step 4: 触发诊断
    print("\n[Step 4] 触发Expert诊断...")
    diagnosis_result = orchestrate_query(
        "BGP邻接不稳定，状态一直是Idle，无法建立连接"
    )
    print(f"✓ 诊断开始时间: {time.ctime()}")
    
    # Step 5: 验证诊断结果
    print("\n[Step 5] 验证诊断结果...")
    expected_findings = [
        "邻接地址配置错误",
        "无法建立TCP连接",
        "检查show ip bgp neighbors"
    ]
    
    correct_findings = sum(
        1 for finding in expected_findings 
        if finding in diagnosis_result['analysis']
    )
    accuracy = correct_findings / len(expected_findings) * 100
    
    print(f"✓ 诊断准确度: {accuracy:.0f}%")
    print(f"✓ 知识库命中: {diagnosis_result.get('kb_hit_count', 0)} 个案例")
    
    # Step 6: 恢复故障
    print("\n[Step 6] 恢复故障...")
    recovery = injector.recover_fault("bgp_down")
    print(f"✓ 恢复时间: {recovery['recovery_time']:.2f}秒")
    
    # Step 7: 验证恢复
    print("\n[Step 7] 验证恢复...")
    time.sleep(5)
    verification = nornir_execute("R1", "show ip bgp neighbors")
    if "Established" in verification:
        print(f"✓ BGP邻接已恢复: Established")
    else:
        print(f"✗ BGP邻接未恢复!")
    
    # 保存结果
    result = {
        "scenario": "BGP邻接DOWN",
        "diagnosis_accuracy": accuracy,
        "kb_hits": diagnosis_result.get('kb_hit_count', 0),
        "diagnosis_time_seconds": diagnosis_result.get('duration_seconds'),
        "recovery_time_seconds": recovery['recovery_time'],
        "overall_status": "PASS" if accuracy >= 85 else "FAIL"
    }
    
    print("\n" + "=" * 60)
    print(f"结果: {result['overall_status']}")
    print(f"诊断准确度: {result['diagnosis_accuracy']:.0f}%")
    print(f"诊断耗时: {result['diagnosis_time_seconds']:.1f}秒")
    print("=" * 60)
    
    return result

if __name__ == "__main__":
    run_bgp_down_scenario()
```

#### 场景2: OSPF Area不匹配脚本

```python
#!/usr/bin/env python3
"""
OSPF Area不匹配故障场景 - scenario_ospf_area_mismatch.py
"""

from fault_injector import FaultInjector
import time

def run_ospf_area_mismatch_scenario():
    """OSPF Area不匹配故障场景"""
    
    print("=" * 60)
    print("场景: OSPF Area不匹配诊断")
    print("=" * 60)
    
    injector = FaultInjector(device="R2", env="gns3")
    
    # Step 1: 基线
    print("\n[Step 1] 获取基线数据...")
    baseline = nornir_execute("R2", "show ip ospf neighbor")
    print(f"✓ OSPF邻接状态: Establish (关系: {baseline})")
    
    # Step 2: 故障注入
    print("\n[Step 2] 注入OSPF Area不匹配故障...")
    fault = injector.inject_fault("ospf_area_mismatch", interface="Eth0/1")
    print(f"✓ 故障注入: 将邻接加入不同Area (Area 2)")
    
    time.sleep(5)
    
    # Step 3: 诊断
    print("\n[Step 3] 触发Expert诊断...")
    diagnosis = orchestrate_query(
        "OSPF邻接突然DOWN了，日志中出现mismatch错误"
    )
    
    # Step 4: 验证
    print("\n[Step 4] 验证诊断结果...")
    if "Area" in diagnosis['analysis'] or "mismatch" in diagnosis['analysis']:
        print(f"✓ 诊断正确识别了Area不匹配问题")
        accuracy = 95
    else:
        print(f"✗ 诊断未能识别Area问题")
        accuracy = 50
    
    # Step 5: 恢复
    print("\n[Step 5] 恢复故障...")
    injector.recover_fault("ospf_area_mismatch")
    time.sleep(5)
    
    return {
        "scenario": "OSPF Area不匹配",
        "status": "PASS" if accuracy >= 85 else "FAIL",
        "accuracy": accuracy
    }

if __name__ == "__main__":
    run_ospf_area_mismatch_scenario()
```

---

## 📚 知识库初始化

### 1. 知识库目录结构初始化

```bash
#!/bin/bash
# 初始化知识库目录结构

mkdir -p .olav/knowledge/solutions/{bgp,ospf,acl,infrastructure,design}
mkdir -p .olav/knowledge/topology_templates

# 创建索引文件
cat > .olav/knowledge/knowledge_index.json << 'EOF'
{
  "version": "1.0.0",
  "created_at": "2026-02-11",
  "total_solutions": 0,
  "categories": {
    "bgp": [],
    "ospf": [],
    "acl": [],
    "infrastructure": [],
    "design": []
  }
}
EOF

echo "✓ 知识库目录结构已初始化"
```

### 2. 预置案例库

#### 案例模板

```markdown
# [案例标题]

## 元数据
- **案例ID**: bgp-001
- **创建日期**: 2026-02-11
- **最后更新**: 2026-02-11
- **问题类型**: BGP邻接
- **影响范围**: 单设备
- **解决时间**: 5分钟
- **准确难度**: ★★☆☆☆ (2/5)
- **准确率**: 92%

## 问题描述

**用户症状**:
- BGP邻接无法建立
- 邻接状态: Idle -> Idle (卡住)
- 已尝试的操作: 无

**网络拓扑**:
```
R1 (AS 65000) -- R2 (AS 65001)
10.0.0.1/24    10.0.0.2/24
```

**观察到的现象**:
```
R1# show ip bgp summary
BGP router identifier 1.1.1.1, local AS 65000

Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
10.0.0.2        4 65001       0       0        0    0    0    never    Idle
```

## 根本原因分析 (RCA)

**问题根源**: 邻接地址配置错误

**诊断过程**:
1. 检查BGP邻接状态 → Idle (无法建立TCP)
2. Ping邻接地址 10.0.0.2 → 成功 ✓
3. Check邻接配置:
   ```
   R1# show run | include neighbor
   neighbor 10.0.0.99 remote-as 65001  ← 错误! 应该是10.0.0.2
   ```
4. 发现配置错误，邻接IP为10.0.0.99 而实际R2为10.0.0.2

**为什么会这样?**
- 人为配置错误 (typo或记录错误)
- 拓扑变更后配置未同步

## 解决步骤

### 推荐方案 (执行时间: ~2分钟)

#### Step 1: 进入配置模式
```bash
R1# conf t
```

#### Step 2: 删除错误的邻接
```bash
R1(config)# router bgp 65000
R1(config-router)# no neighbor 10.0.0.99 remote-as 65001
```

#### Step 3: 添加正确的邻接
```bash
R1(config-router)# neighbor 10.0.0.2 remote-as 65001
```

#### Step 4: 退出并保存
```bash
R1(config-router)# exit
R1(config)# exit
R1# wr mem
```

#### Step 5: 验证
```bash
R1# show ip bgp neighbors 10.0.0.2

Local host: 10.0.0.1, Local port: 54321
Foreign host: 10.0.0.2, Foreign port: 179

Flags: 0x2009
  Outbound mapping list is default_out
  Inbound mapping list is default_in
  Last reset 00:00:02

...
BGP state = Established, up for 00:00:15
```

**预期结果**: BGP state 变为 Established ✓

## 预防措施

1. **配置检查**
   - 使用 `show run` 验证配置
   - 对比设计文档和实际配置

2. **流程优化**
   - 使用配置模板,避免手工输入
   - 实施配置备审流程

3. **监控告警**
   - 监控BGP邻接状态变化
   - 邻接Down时立即告警

## 参考资料

- [Cisco BGP Configuration Guide](https://www.cisco.com/c/en/us/support/docs/ip/border-gateway-protocol-bgp/)
- [RFC 4271 - BGP Protocol](https://tools.ietf.org/html/rfc4271)
- 相关案例: bgp-parameter-mismatch.md

## 标签
#BGP #邻接 #配置错误 #Idle状态 #诊断

---

**案例ID**: bgp-001  
**贡献者**: [Expert Agent]  
**评级**: ★★★★★ (5/5) - 高度相关  
**参考价值**: 高
```

#### 预置案例库列表

```
.olav/knowledge/solutions/bgp/
├── bgp-001-neighbor-config-error.md
│   问题: 邻接地址配置错误
│   症状: Idle状态,无法建立连接
│   解决: 修正邻接IP地址
│
├── bgp-002-area-mismatch.md
│   问题: BGP区域/实例ID不匹配
│   症状: Connect状态,握手失败
│   解决: 同步区域/实例ID配置
│
├── bgp-003-authentication-failure.md
│   问题: 认证密钥不匹配
│   症状: Active/Connect状态
│   解决: 验证和修正认证密钥
│
├── bgp-004-route-black-hole.md
│   问题: 路由黑洞 (route-map阻止发布)
│   症状: 邻接正常但路由未发布
│   解决: 修改route-map策略
│
└── bgp-005-flapping.md
    问题: BGP路由颤动
    症状: 邻接频繁Up/Down
    解决: 稳定网络拓扑或增加收敛参数

.olav/knowledge/solutions/ospf/
├── ospf-001-area-mismatch.md
├── ospf-002-network-type-mismatch.md
├── ospf-003-timer-mismatch.md
├── ospf-004-authentication-failure.md
└── ospf-005-spf-loop.md

.olav/knowledge/solutions/acl/
├── acl-001-blocking-icmp.md
├── acl-002-blocking-routing-protocol.md
└── acl-003-asymmetric-filtering.md

.olav/knowledge/solutions/infrastructure/
├── interface-001-down-status.md
├── interface-002-flapping.md
└── link-001-loop-detection.md
```

### 3. 知识库索引更新

```python
#!/usr/bin/env python3
"""
知识库索引更新工具 - update_kb_index.py

用途: 扫描solutions目录,更新knowledge_index.json
执行: python update_kb_index.py
"""

import json
from pathlib import Path
from datetime import datetime

def update_kb_index():
    """扫描知识库并更新索引"""
    
    kb_path = Path(".olav/knowledge/solutions")
    index_path = Path(".olav/knowledge/knowledge_index.json")
    
    # 初始化索引
    index = {
        "version": "1.0.0",
        "updated_at": datetime.now().isoformat(),
        "total_solutions": 0,
        "categories": {}
    }
    
    # 扫描所有案例
    for category_dir in kb_path.iterdir():
        if not category_dir.is_dir():
            continue
        
        category = category_dir.name
        index["categories"][category] = []
        
        for case_file in category_dir.glob("*.md"):
            # 解析案例文件
            metadata = parse_case_metadata(case_file)
            
            index["categories"][category].append({
                "id": metadata.get("case_id"),
                "title": metadata.get("title"),
                "created_at": metadata.get("created_at"),
                "tags": metadata.get("tags", []),
                "difficulty": metadata.get("difficulty"),
                "file": str(case_file.relative_to(kb_path))
            })
            
            index["total_solutions"] += 1
    
    # 保存索引
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    
    print(f"✓ 知识库索引已更新")
    print(f"  总案例数: {index['total_solutions']}")
    print(f"  分类数: {len(index['categories'])}")

def parse_case_metadata(case_file: Path) -> dict:
    """从案例文件解析元数据"""
    
    content = case_file.read_text(encoding='utf-8')
    
    # 简单的元数据提取
    metadata = {}
    
    for line in content.split('\n')[:50]:  # 前50行
        if line.startswith('- **案例ID**'):
            metadata['case_id'] = line.split(':')[1].strip()
        elif line.startswith('- **创建日期**'):
            metadata['created_at'] = line.split(':')[1].strip()
        elif line.startswith('## '):
            metadata['title'] = line.replace('## ', '').strip()
        elif line.startswith('## 标签'):
            # 下一行是标签
            pass
    
    return metadata

if __name__ == "__main__":
    update_kb_index()
```

---

## 🔄 诊断流程验证

### 1. 诊断验证检查表

```
验证项目                          检查方法                    期望结果
────────────────────────────────────────────────────────────────────
✓ Expert接收查询                  查看日志: "Expert Agent receive query"
✓ 意图识别正确                    分析提取的Problem Type
✓ 设备定位准确                    验证提取的Primary Device
✓ 诊断步骤执行                    追踪每个诊断命令的执行
✓ 工具调用成功                    检查nornir_execute返回值
✓ 知识库查询                      验证read_file/research_problem调用
✓ 案例匹配度                      评分Top 3案例的相关性
✓ 根本原因识别                    对比RCA与实际根因
✓ 解决方案生成                    验证方案的可执行性
✓ 报告生成                        检查generate_report输出
✓ 案例保存                        验证write_file成功写入
```

### 2. 自动化验证脚本

```python
#!/usr/bin/env python3
"""
诊断验证工具 - verify_diagnosis.py

用途: 验证诊断结果是否正确、完整
"""

class DiagnosisVerifier:
    """诊断结果验证器"""
    
    def verify_diagnosis(self, diagnosis: dict, expected: dict) -> dict:
        """
        验证诊断结果
        
        Args:
            diagnosis: Expert生成的诊断结果
            expected: 预期的正确结果
        
        Returns:
            验证结果dict
        """
        
        verification = {
            "problem_type_match": False,
            "root_cause_match": False,
            "solution_valid": False,
            "overall_score": 0.0
        }
        
        # 1. 验证问题类型
        diagnosis_type = self._extract_type(diagnosis['analysis'])
        expected_type = expected['problem_type']
        
        if diagnosis_type in expected_type:
            verification["problem_type_match"] = True
        
        # 2. 验证根本原因
        diagnosis_rca = diagnosis.get('root_cause', '')
        expected_rca = expected.get('root_cause', '')
        
        similarity = self._calculate_similarity(diagnosis_rca, expected_rca)
        if similarity > 0.7:  # 70%相似度threshold
            verification["root_cause_match"] = True
        
        # 3. 验证解决方案可执行性
        solution = diagnosis.get('recommended_solution', {})
        
        if self._is_solution_executable(solution):
            verification["solution_valid"] = True
        
        # 4. 计算综合得分
        match_count = sum([
            verification["problem_type_match"],
            verification["root_cause_match"],
            verification["solution_valid"]
        ])
        
        verification["overall_score"] = (match_count / 3) * 100
        
        return verification

    def _extract_type(self, analysis: str) -> str:
        """从分析文本中提取问题类型"""
        # BGP/OSPF/ACL/Interface等
        types = ["BGP", "OSPF", "ACL", "Interface", "Routing"]
        for t in types:
            if t in analysis:
                return t
        return "Unknown"
    
    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """计算字符串相似度"""
        # 使用余弦相似度或其他算法
        from difflib import SequenceMatcher
        return SequenceMatcher(None, str1, str2).ratio()
    
    def _is_solution_executable(self, solution: dict) -> bool:
        """检查解决方案是否可执行"""
        
        required_fields = [
            'steps',
            'commands',
            'verification_method'
        ]
        
        return all(field in solution for field in required_fields)
```

---

## 🚀 执行指南

### 准备阶段

1. **环境搭建**
```bash
# GNS3环境
./setup_gns3_environment.sh

# 或EVE-NG环境
./setup_eve_ng_environment.sh
```

2. **知识库初始化**
```bash
# 创建目录
mkdir -p .olav/knowledge/solutions/{bgp,ospf,acl}

# 初始化案例
python init_kb_cases.py

# 更新索引
python update_kb_index.py
```

### 测试执行

1. **单个场景测试**
```bash
python scenario_bgp_down.py
python scenario_ospf_area_mismatch.py
```

2. **批量场景测试**
```bash
python run_all_scenarios.py
```

3. **验证诊断结果**
```bash
python verify_diagnosis.py --scenario bgp_down
```

---

**文档版本**: v1.0.0  
**创建日期**: 2026年2月11日  
**下一步**: 实施故障注入脚本和知识库初始化
