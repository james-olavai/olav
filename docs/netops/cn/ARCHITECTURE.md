# OLAV NetOps 架构：网络智能层

**版本：** v0.13.0 (2026-03-22)  
**状态：** 核心底座已确立 (Canonical Foundation)  

## 1. 概述

OLAV NetOps 是 OLAV 平台的特定域（Domain-Specific）智能层。它的任务是将零碎、异构的厂商特定网络数据，转化为统一、可操作且具有确定性的语义模型。如果说 `olav-platform` 提供的是编排和数据库底座，那么 `olav-netops` 提供的就是 **“网络知识” (Network Knowledge)** —— 即对网络行为的映射、推理和仿真能力。

---

## 2. 三层一致性真相 (数据战略)

OLAV NetOps 采取“分层一致性” (Tiered Alignment) 策略，在原始准确性与跨平台统一性之间取得平衡：

1.  **L1 - 原始真相层 (Ingestion)**：
    *   通过 TextFSM 解析后的原始 KV 对保留 CLI 输出的真相。
    *   仅进行“值级别”的规范化（如：MTU 整数转换、MAC 格式清洗）。
    *   **目标**：绝对的可追溯性与审计合规。

2.  **L2 - 厂商语义层 (State Preservation)**：
    *   保留厂商特有的语义和性能指标。
    *   在写入阶段禁止字段改名，防止“写时处理” (Schema-on-Write) 导致的原始语义污染。

3.  **L3 - OpenConfig 视图层 (Canonical Query Layer)**：
    *   基于 LLM 驱动的 **读时投影 (Schema-on-Read)**。
    *   将 L1/L2 字段按需映射到 OpenConfig (标准) 或 OLAV (扩展) 命名空间。

---

## 3. 智能映射流水线 (Mapping Pipeline)

NetOps 的核心引擎是 **五阶段映射流水线**，它用 LLM-native 的语义发现取代了传统的手工解析：

*   **Stage 1: 清洗 (Cleaning)**：值规范化（netutils），字段名保持原样。
*   **Stage 4: 确定性 (Deterministic)**：优先检索高效缓存 (`mapping_cache`) 和预定义规则，**零 LLM 调用**。
*   **Stage 3: 语义检索 (Semantic Retrieval)**：字段名被向量化，在包含 **800+ YANG 叶子节点** (BGP, OSPF, Interface, QoS 等) 的语料库中进行匹配。
*   **Stage 4: Agent 沙箱 (Agentic Sandbox)**：由 LLM 处理中置信度匹配。若标准 OC 路径不存在，LLM 会根据规范自动生成 **厂商扩展路径 (Vendor Extension)**（例如：`/state/vendor-extensions/...`）。
*   **Stage 5: 反馈与自学习 (Feedback)**：验证后的映射写回缓存。随着运行次数增加，Stage 2 的命中率会呈指数级上升。

---

## 4. 语义推理与仿真

在归一化数据之上，NetOps 提供了两个高级推理引擎：

### 4.1 控制平语义引擎 (Phase 4: Semantic Engine)
一个懂协议逻辑的确定性引擎：
*   **BGP Solver**：路由通告的最佳路径 (Best-Path) 选择与传播推演。
*   **IGP Solver (OSPF/IS-IS)**：基于接口 Cost 的最短路径计算。
*   **Policy IR**：将复杂的厂商策略 (Policy) 转化为中间表示 (IR)，进行确定性的模拟评估。

### 4.2 运维分析沙箱 (Phase 5: NetworkX Sandbox)
一个基于图结构的运维辅助助手：
*   从 `topology_links` 构建 `nx.MultiDiGraph` 拓扑图。
*   计算 **爆炸半径 (Blast Radius)** 并进行 **故障假设验证 (Hypothesis Testing)**。
*   充当 Agent 的“幻觉抑制器”：让所有推理都锚定在真实的网络状态上。

---

## 5. 核心原则与安全

*   **LLM-Native**：废除人工审核，引入 **LLM 审计器 (Audit Agent)** 对候选映射表进行自动化复核与交叉验证。
*   **职责分离 (Separation of Concerns)**：平台负责“如何做”（API、DB、工具），NetOps 负责“做什么”（YANG、协议、网络常识）。
*   **仅供咨询 (Advisory Only)**：OLAV NetOps 生成洞察和建议，绝不直接对生产环境下发配置。人类工程师拥有最终执行权。

---
© 2026 OLAV 开发团队。受版权保护。
