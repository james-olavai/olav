# Expert Agent 技术设计文档

**文档版本**: v1.0.0  
**创建日期**: 2026年2月11日  
**最后更新**: 2026年2月11日  
**状态**: 📋 规划中  
**架构等级**: L3 (复杂)

---

## 📋 文档概述

本文档详细说明 Expert Agent 的技术架构、诊断流程、工具集成、知识库架构等实现细节。

---

## 🏗️ 架构设计

### 1. 核心流程架构

```
┌─────────────────────────────────────────┐
│  User Query (自然语言)                   │
│  "为什么BGP邻接不稳定？"                 │
└──────────────┬──────────────────────────┘
               │
               ▼
        ┌──────────────┐
        │  Intent识别  │
        │  • 故障类型  │
        │  • 设备范围  │
        │  • 关键字提取│
        └──────┬───────┘
               │
               ▼
    ┌──────────────────────┐
    │ Phase 1: 初始诊断    │
    │ • 快速症状识别       │
    │ • 设备可达性检查     │
    │ • 基础配置获取       │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ Phase 2: 深度分析    │
    │ • 按协议分层诊断     │
    │ • 功能组件检查       │
    │ • 参数对比分析       │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ Phase 3: RCA分析     │
    │ • 根本原因追踪       │
    │ • 影响范围评估       │
    │ • 风险等级判断       │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ Phase 4: 知识库查询  │
    │ • 历史案例匹配       │
    │ • 参考方案推荐       │
    │ • 相似度排序         │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ Phase 5: 方案生成    │
    │ • 步骤分解           │
    │ • 执行顺序优化       │
    │ • 风险说明           │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ Phase 6: 报告生成    │
    │ • 诊断报告           │
    │ • 建议方案           │
    │ • 参考资料           │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ Phase 7: 学习反馈    │
    │ • 用户验证           │
    │ • 案例保存           │
    │ • 知识库更新         │
    └──────────────────────┘
```

### 2. 诊断策略框架

#### BGP诊断树
```
BGP 问题
├─ 邻接状态异常
│  ├─ Down (Idle -> Down)
│  │  ├─ 检查: TCP连通性
│  │  ├─ 检查: 邻接地址配置
│  │  ├─ 检查: AS号配置
│  │  └─ 检查: 认证密钥
│  ├─ Connect (Idle -> Connect)
│  │  ├─ 检查: open message交换
│  │  ├─ 检查: BGP capability
│  │  └─ 检查: 计时器
│  └─ Active (邻接在Active状态)
│     ├─ 检查: 被动模式配置
│     └─ 检查: 连接状态机
│
├─ 路由表异常
│  ├─ 路由缺失
│  │  ├─ 检查: 邻接的out prefix-list
│  │  ├─ 检查: 邻接的out route-map
│  │  └─ 检查: 对端是否发布了这个路由
│  ├─ 路由黑洞
│  │  ├─ 检查: 路由的next hop
│  │  ├─ 检查: next hop的可达性
│  │  └─ 检查: 是否为0.0.0.0
│  └─ 路由优先级错误
│     ├─ 检查: AD配置
│     ├─ 检查: 本地路由优先级
│     └─ 检查: 导入优先级
│
├─ 路由颤动
│  ├─ 诊断: show ip bgp summary (检查up/down计数)
│  ├─ 诊断: show ip bgp neighbors ? (检查state changes)
│  ├─ 诊断: show ip bgp history (最近变化)
│  └─ 原因推理:
│     ├─ AS路径过长导致路由被拒绝
│     ├─ 网络拓扑不稳定 (链路/设备重启)
│     ├─ 配置在频繁修改
│     └─ 内存压力导致BGP进程重启
│
└─ 性能问题
   ├─ 诊断: BGP收敛时间过长
   ├─ 诊断: BGP占用内存过高
   └─ Tuning:
      ├─ 增加BGP进程优先级
      ├─ 调整update-delay
      └─ 启用BGP速率限制
```

#### OSPF诊断树
```
OSPF 问题
├─ 邻接不建立
│  ├─ 物理连接检查
│  │  ├─ show interface status
│  │  ├─ show cdp neighbors
│  │  └─ ping邻接IP
│  │
│  └─ OSPF参数mismatch
│     ├─ Area ID检查 (show ip ospf interface)
│     ├─ Network Type检查 (点对点/广播)
│     ├─ Hello/Dead Interval检查
│     ├─ 认证检查 (auth-type, auth-key)
│     └─ MTU检查
│
├─ 路由黑洞
│  ├─ LSA检查 (show ip ospf database)
│  ├─ SPF计算检查 (show ip ospf spf-log)
│  ├─ 路由导出检查 (如果有多进程)
│  └─ 默认路由检查
│
└─ 网络性能
   ├─ LSA洪泛检查
   ├─ SPF运行频率检查
   └─ 邻接重新收敛检查
```

### 3. 工具链架构

```
Expert Agent
├─ 数据采集层
│  ├─ nornir_execute: 直接CLI执行
│  ├─ smart_query: 智能查询 (自动命令选择)
│  ├─ batch_query: 批量查询 (多设备)
│  └─ list_devices: 设备目录获取
│
├─ 知识层
│  ├─ search_capabilities: 命令能力搜索
│  ├─ research_problem: 知识库查询 (本地+网络)
│  └─ read_file: 读取知识库案例
│
├─ 分析层
│  ├─ 本地分析逻辑 (诊断树执行)
│  ├─ LLM分析 (深度推理)
│  └─ 参数对比 (配置mismatch检测)
│
├─ 生成层
│  ├─ generate_report: 报告生成
│  ├─ write_file: 结果文件保存
│  └─ api_call: 外部系统集成
│
└─ 学习层
   ├─ write_file: 案例库保存
   └─ update_aliases: 设备名称学习
```

---

## 🔍 详细诊断流程

### BGP邻接故障诊断示例

**Step 1: 理解问题**
```python
def understand_problem(query: str) -> DiagnosisPlan:
    """解析用户查询，生成诊断计划"""
    # 提取关键信息
    problem_type = extract_problem_type(query)  # "BGP邻接"
    devices = extract_devices(query)             # ["R1", "R2"]
    intent = extract_intent(query)               # "诊断"
    
    # 生成诊断计划
    plan = DiagnosisPlan(
        problem_type="BGP邻接不稳定",
        primary_device="R1",
        related_devices=["R2"],
        stages=[
            "初始状态检查",
            "邻接参数检查",
            "网络连通性检查",
            "配置对比",
            "原因分析"
        ]
    )
    return plan
```

**Step 2: 初始状态检查**
```bash
# 执行命令
R1# show ip bgp summary
R1# show ip bgp neighbors 10.0.0.2 | include State

# 预期输出分析
Status Down:     --> 邻接完全无法建立 (可能是L3问题)
Status Connect:  --> 能建立TCP连接但BGP握手失败 (可能是BGP参数问题)
Status Active:   --> 在Active状态卡住 (可能是被动模式或连接问题)
```

**Step 3: 邻接参数检查**
```bash
# 执行命令序列
R1# show ip bgp neighbors 10.0.0.2
R2# show ip bgp neighbors 10.0.0.1

# 对比关键参数
┌─────────────────────┬────────┬────────┐
│ 参数                 │ R1     │ R2     │
├─────────────────────┼────────┼────────┤
│ Remote AS           │ 65001  │ 65000  │ ✅
│ Description         │ R2-ESW │ R1-ESW │ ℹ️
│ Local Address       │10.0.0.1│10.0.0.2│ ✅
│ Hello Interval      │ 3      │ 3      │ ✅
│ Keepalive Interval  │ 9      │ 9      │ ✅
│ Hold Time           │ 9      │ 9      │ ✅
│ BGP Version         │ 4      │ 4      │ ✅
└─────────────────────┴────────┴────────┘

# 分析结果
- 所有参数都匹配 ✅
- 下一步检查网络连通性
```

**Step 4: 网络连通性检查**
```bash
R1# ping 10.0.0.2 source 10.0.0.1
Success rate: 100%

# 结论: L3连通性正常 ✅

# 检查ACL
R1# show access-list
R1# show ip interface eth0/1 | include access list
```

**Step 5: 原因分析与知识库查询**
```python
# 如果上述检查都通过，但邻接仍然Down
# 可能原因:
possible_causes = [
    "BGP进程未启动",
    "邻接被passive mode启动",
    "route-map导出阻断",
    "BGP distribute-list过滤",
    "认证密钥不匹配 (但show时看不到)"
]

# 查询知识库
kb_queries = knowledge_base.search([
    "BGP邻接Down且参数匹配",
    "BGP Connect无法建立",
    "BGP邻接Idle状态"
])

# 返回Top 3相关案例
```

**Step 6: 生成建议方案**
```markdown
## 诊断结果

### 问题描述
- R1和R2的BGP邻接无法建立
- 邻接状态: Idle -> Connect (重复)

### 根本原因
根据诊断,最可能的原因是:
1. R1配置的邻接IP与实际邻接地址不符
   (推荐概率: 45%)
2. BGP进程在R1上未启动
   (推荐概率: 30%)
3. 认证密钥不匹配
   (推荐概率: 15%)

### 建议步骤

#### Step 1: 验证邻接地址
```
R1# show run | include neighbor
```
预期: neighbor 10.0.0.2 remote-as 65001

#### Step 2: 检查BGP进程状态
```
R1# show ip bgp summary
```
预期: 显示BGP进程运行状态

#### Step 3: 启用BGP调试
```
R1# debug ip bgp keepalives
R1# debug ip bgp updates
```

### 参考案例
- [Case: BGP邻接地址配置错误 (2026-01-15)](bgp-neighbor-config.md)
- [Case: BGP进程中断导致邻接Down (2026-01-10)](bgp-process-crash.md)
```

---

## 💾 知识库架构

### 目录结构
```
.olav/knowledge/
├── solutions/                    # 已解决的案例库
│  ├── bgp/
│  │  ├── bgp-flapping-20260101.md
│  │  ├── bgp-neighbor-down-20260105.md
│  │  ├── bgp-route-black-hole-20260108.md
│  │  └── bgp-parameter-mismatch-20260110.md
│  ├── ospf/
│  │  ├── ospf-area-mismatch-20260101.md
│  │  ├── ospf-neighbor-down-20260105.md
│  │  └── ospf-spf-loop-20260108.md
│  ├── acl/
│  │  └── acl-blocking-icmp-20260110.md
│  └── infrastructure/
│     └── interface-flapping-20260108.md
│
├── knowledge_index.json         # 快速搜索索引
├── best_practices.md             # 最佳实践指南
└── topology_templates/           # 拓扑分析模板
   ├── hub-spoke.yaml
   ├── mesh.yaml
   └── leaf-spine.yaml
```

### 案例模板

每个案例应包含以下结构:
```markdown
# [问题标题] - [案例ID]

## 元数据
- 创建日期: YYYY-MM-DD
- 最后更新: YYYY-MM-DD
- 问题类型: BGP/OSPF/ACL/etc
- 影响范围: 单点/级联/全网
- 解决时间: X分钟
- 准确率: X%

## 问题描述
[用户症状]

## 根本原因
[RCA分析]

## 解决步骤
1. Step 1
2. Step 2
...

## 验证方法
[如何验证问题已解决]

## 参考资料
- 相关RFC
- 厂商文档链接

## 标签
[#BGP, #邻接, #诊断]
```

### 知识库查询流程

```python
def search_knowledge_base(problem_description: str) -> List[CaseReference]:
    """
    查询知识库，返回相关案例
    
    Steps:
    1. 关键词提取 (BGP, OSPF, 邻接, Down, etc)
    2. 标签匹配 (从问题类型推导标签)
    3. 相似度计算 (TF-IDF或向量相似度)
    4. 重排 (按相关度排序)
    5. 返回Top N案例
    """
    
    # 示例流程
    keywords = extract_keywords(problem_description)
    # keywords = ["BGP", "邻接", "Down", "诊断"]
    
    tags = infer_tags(problem_description)
    # tags = ["#BGP", "#邻接", "#诊断"]
    
    matching_cases = []
    for case_file in knowledge_base.list_solutions():
        similarity = calculate_similarity(
            problem_description,
            case_file.content,
            keywords,
            tags
        )
        if similarity > THRESHOLD:
            matching_cases.append((case_file, similarity))
    
    # 按相似度排序
    matching_cases.sort(key=lambda x: x[1], reverse=True)
    
    # 返回Top 3
    return [case for case, _ in matching_cases[:3]]


def calculate_similarity(
    problem: str,
    case_content: str,
    keywords: List[str],
    tags: List[str]
) -> float:
    """计算问题与案例的相似度"""
    
    # 多因子相似度计算
    keyword_score = sum(1 for kw in keywords if kw.lower() in case_content.lower()) / len(keywords)
    tag_score = sum(1 for tag in tags if tag in extract_tags(case_content)) / len(tags)
    text_similarity = cosine_similarity(problem, case_content)
    
    # 加权综合
    similarity = (
        keyword_score * 0.3 +
        tag_score * 0.2 +
        text_similarity * 0.5
    )
    
    return similarity
```

---

## 📋 诊断工具详解

### 工具1: nornir_execute

**功能**: 在特定设备上执行命令

```python
# 签名
nornir_execute(device: str, command: str) -> Dict[str, Any]

# 返回示例
{
    "device": "R1",
    "command": "show ip bgp summary",
    "output": "...",  # 原始CLI输出
    "status": "success",
    "execution_time_ms": 245
}

# 调用示例
result = nornir_execute("R1", "show ip bgp neighbors detail")
neighbors = parse_output(result["output"])
```

### 工具2: smart_query

**功能**: 智能查询 - 根据意图自动选择命令

```python
# 签名
smart_query(device: str, intent: str) -> Dict[str, Any]

# 支持的intent
INTENTS = [
    "bgp",          # show ip bgp summary
    "bgp-neighbors",# show ip bgp neighbors
    "ospf",         # show ip ospf neighbor
    "interface",    # show interface brief
    "route",        # show ip route
    "mac",          # show mac address-table
    "vlan",         # show vlan brief
    "acl",          # show access-list
    "version",      # show version
]

# 调用示例
result = smart_query("R1", "bgp")  # 自动选择 show ip bgp summary
```

### 工具3: batch_query

**功能**: 在多个设备上批量查询

```python
# 签名
batch_query(devices: str, intent: str) -> Dict[str, Dict]

# devices格式:
# - "R1,R2,R3"        # 指定设备
# - "all"             # 所有设备
# - "role:core"       # 按角色过滤
# - "site:lab"        # 按站点过滤

# 调用示例
results = batch_query("role:core", "bgp")
# 返回: {"R1": {...}, "R2": {...}, "R3": {...}}
```

### 工具4: research_problem

**功能**: 研究问题 (本地知识库 + 网络搜索)

```python
# 签名
research_problem(problem_statement: str) -> Dict[str, Any]

# 返回示例
{
    "problem": "BGP flapping causes",
    "local_knowledge": [
        {
            "case": "bgp-flapping-20260101.md",
            "relevance": 0.92,
            "excerpt": "..."
        }
    ],
    "web_search": [
        {
            "title": "RFC 7196: BGP Convergence",
            "url": "https://...",
            "excerpt": "..."
        }
    ]
}

# 调用示例
research = research_problem("BGP邻接颤动的根本原因")
```

### 工具5: write_file

**功能**: 保存文件到知识库或报告

```python
# 签名
write_file(filepath: str, content: str) -> Dict[str, Any]

# 典型用途
write_file(
    ".olav/knowledge/solutions/bgp-neighbors-down-20260211.md",
    case_markdown_content
)

# 返回
{
    "filepath": "...",
    "bytes_written": 1234,
    "status": "success"
}
```

---

## 🔗 知识库整合流程

### 自动学习流程

```
Step 1: 问题诊断完成
├─ Expert 完成诊断与解决
├─ 生成诊断报告
└─ 询问用户: "是否要保存这个案例？"

Step 2: 用户确认
├─ 用户验证解决方案有效
└─ 同意保存到知识库

Step 3: 案例格式化
├─ 提取关键信息: 问题描述、RCA、方案
├─ 补充元数据: 时间、类型、影响范围
└─ 自动生成标签

Step 4: 保存到知识库
├─ 文件名: [问题-类型]-[日期].md
├─ 路径: .olav/knowledge/solutions/[category]/
└─ 更新索引: knowledge_index.json

Step 5: 后续应用
├─ 新查询可以检索到这个案例
├─ 用于相似问题的快速定位
└─ 持续改进诊断准确率
```

---

## ⚡ 性能优化

### 1. 并行化诊断

```python
def parallel_diagnostic_execution(plan: DiagnosisPlan) -> Dict:
    """并行执行不相关的诊断步骤"""
    
    # 可以并行执行 (无依赖)
    tasks = [
        smart_query("R1", "bgp"),          # Task 1
        smart_query("R2", "bgp"),          # Task 2
        search_capabilities("bgp", "iosxe"), # Task 3
        research_problem("BGP configuration") # Task 4
    ]
    
    # 并行执行
    results = asyncio.gather(*tasks)
    
    # 需要顺序执行 (有依赖)
    # 1. 获取邻接信息
    neighbor_info = results[0]
    # 2. 基于邻接信息查询参数
    neighbor_params = nornir_execute("R1", f"show ip bgp neighbors {neighbor_info.neighbor_ip}")
    # 3. 对比分析
    analysis = compare_parameters(neighbor_params, ...)
```

### 2. 缓存机制

```python
class DiagnosisCache:
    """诊断结果缓存，避免重复查询"""
    
    def __init__(self, ttl_seconds: int = 300):
        self.cache = {}
        self.ttl = ttl_seconds
    
    def get(self, key: str) -> Optional[Dict]:
        """获取缓存"""
        if key in self.cache:
            entry, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return entry
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, value: Dict) -> None:
        """设置缓存"""
        self.cache[key] = (value, time.time())

# 使用示例
cache = DiagnosisCache(ttl_seconds=300)

cached = cache.get("R1:bgp:summary")
if cached:
    result = cached
else:
    result = smart_query("R1", "bgp")
    cache.set("R1:bgp:summary", result)
```

---

## 🛡️ 错误处理与降级

### 错误分类

| 错误类型 | 影响 | 处理策略 |
|---------|------|----------|
| 设备不可达 | 无法采集数据 | 标记设备离线,继续其他设备 |
| 命令不支持 | 部分诊断失败 | 使用备选命令或跳过 |
| 权限不足 | 命令执行失败 | 告知用户,降级到可用命令 |
| 知识库查询失败 | 无法参考案例 | 继续诊断,不依赖历史案例 |
| LLM分析失败 | 无法RCA | 使用规则引擎分析 |

### 降级策略

```python
def diagnose_with_fallback(problem: str) -> DiagnosisReport:
    """带降级的诊断流程"""
    
    try:
        # 尝试完整诊断流程
        return full_diagnosis(problem)
    except LLMAnalysisError:
        # LLM分析失败,使用规则引擎
        logger.warning("LLM分析失败,使用规则引擎")
        return rule_based_diagnosis(problem)
    except KnowledgeBaseError:
        # 知识库查询失败,继续诊断
        logger.warning("知识库查询失败,继续诊断")
        report = diagnosis_without_kb(problem)
        report.note = "部分功能不可用"
        return report
    except NoDeviceReachable:
        # 所有设备不可达
        return DiagnosisReport(
            status="unreachable",
            message="无法连接到任何网络设备,请检查网络连接"
        )
```

---

## 📊 监控指标

### 关键指标

| 指标 | 目标 | 计算方法 |
|------|------|----------|
| 诊断准确率 | ≥ 85% | 正确诊断数 / 总诊断数 |
| 知识库命中率 | ≥ 70% | 命中案例的诊断数 / 总诊断数 |
| 平均诊断时间 | < 45秒 | 所有诊断的平均耗时 |
| 工具成功率 | ≥ 95% | 成功调用工具数 / 调用总数 |
| 报告生成率 | 100% | 有报告输出的诊断数 / 总诊断数 |

### 监控日志

```python
def log_diagnosis_metrics(diagnosis: DiagnosisReport) -> None:
    """记录诊断指标"""
    
    metrics = {
        "timestamp": datetime.now(),
        "problem_type": diagnosis.problem_type,
        "accuracy_score": diagnosis.confidence,
        "diagnosis_time_ms": diagnosis.duration_ms,
        "tools_called": len(diagnosis.tools_used),
        "tools_success": sum(1 for t in diagnosis.tools_used if t.status == "success"),
        "kb_hit": diagnosis.kb_hit_count > 0,
        "report_generated": diagnosis.report is not None
    }
    
    logger.info(f"诊断完成: {metrics}")
```

---

## 📚 参考资源

### 相关文档
- EXPERT_AGENT_ACCEPTANCE_TEST_PLAN.md
- KNOWLEDGE_BASE_USER_GUIDE.md
- TOOL_API_REFERENCE.md

### 外部参考
- [RFC 4271 - BGP Protocol](https://tools.ietf.org/html/rfc4271)
- [RFC 2328 - OSPF Protocol](https://tools.ietf.org/html/rfc2328)
- [Cisco IOS CLI Reference](https://www.cisco.com/c/en/us/support/docs/)

---

**文档版本**: v1.0.0  
**创建日期**: 2026年2月11日  
**下一步**: 启动环境准备与工具开发
