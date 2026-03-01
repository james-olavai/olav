# OLAV AIOps 长期演进计划 (v0.14.0+) - "专家大脑"的终极闭环

## 1. 演进愿景 (Vision)
随着日志系统、自动触发诊断以及核心架构优化的完成，OLAV 已从交互式助手进化为具备感知、认知和决策能力的 AIOps 系统。本演进计划旨在对标 Juniper Marvis、Arista CloudVision 等顶级商用工具，利用 **LLM-Native** 的灵活性，实现超越传统预定义规则的“深度逻辑自愈”。

---

## 2. 核心演进支柱 (Evolutionary Pillars)

### 2.1 变更分析与预测 (What-if Analysis & Prediction)
**对标：Arista CloudVision**
*   **数字孪生验证 (Digital Twin Validation)**: 
    *   在下发配置前，Ops Subagent 在沙箱内建立基于 DuckDB 的**逻辑路由拓扑模型**。
    *   **模拟执行**: Agent 运行变更指令，通过 LLM 推导拓扑变化。
*   **故障预测**: 计算变更是否会导致路由环路、次优路径或安全策略冲突，并在执行前输出“风险评估报告”。

### 2.2 服务质量感知 (SLE - Service Level Expectations)
**对标：Juniper Mist Marvis**
*   **超越日志报错**: 不再仅仅依赖 Syslog 报错触发，引入对流量指标 (Metrics) 抖动的感知。
*   **体验基准分析**: 当检测到 CPU 突增、流量跌落或延迟波动时，即便设备未报错，也主动触发 Ops Agent 进行“隐式故障扫描”。

### 2.3 可视化路径分析 (Path Visualization)
**对标：Cisco ThousandEyes**
*   **多维拓扑渲染**: 
    *   Ops Agent 在诊断过程中，自动利用沙箱内的 Mermaid 或 Graphviz 库绘制**故障传播路径图**。
    *   **送达**: 通过通知网关推送分析结论的同时，附带可视化的故障节点地图。

### 2.4 主动闭环与自愈 (Proactive Self-Healing)
**对标：Marvis Actions**
*   **安全回滚 (Safe Rollback)**: 
    *   当 Ops Agent 确认根因为近期变更时，主动询问用户：“已确认故障源。是否允许我一键回退至快照 [YYYY-MM-DD_HHMMSS]？”
    *   **HITL (Human-in-the-Loop)**: 用户确认后，系统自动执行回滚技能。

### 2.5 运维数据科学 (Ops as Data Science)
**对标：高级时序分析与异常检测工具**
*   **按需建模 (On-Demand ML)**: Ops Subagent 调用 `sklearn` / `statsmodels` 建立针对特定接口流量的回归预测模型。
*   **预测性预警**: 虽然当前未发生故障，但通过时序分析发现流量趋势将在特定时间内耗尽带宽，实现“预防性扩容 (Predictive Capacity Planning)”。
*   **非线性异常检测**: 利用孤立森林 (Isolation Forest) 识别那些虽未触碰阈值、但具备统计特征异常的可疑流量包。

---

## 3. 差异化竞争策略 (Differentiation)

| 特性 | 商业工具 (Marvis/CloudVision) | OLAV (Our Edge) |
| :--- | :--- | :--- |
| **厂商兼容性** | 强绑定独家硬件 | **厂商无关 (LLM 动态理解私有协议)** |
| **分析模型** | 预置/固定算法模型 | **动态/按需构建 (LLM 生成 ML 脚本)** |
| **部署成本** | 高昂订阅 + 特制采集器 | **轻量化 (Vector + Python 脚本)** |
| **逻辑透明度** | 黑盒分析 (预定义模型) | **白盒决策 (LLM 链条式思维追问)** |
| **私有化** | 云端重心 | **极致本地化 (Edge First)** |

---

## 4. 阶段性路线图 (Roadmap)

### 第一阶段：质量感知器 (v0.15.0)
*   集成 Prometheus/Telegraf 或直接从 DuckDB 读取 Metrics。
*   建立“体验劣化”触发器。

### 第二阶段：全路径拓扑图 (v0.16.0)
*   实现 `draw_fault_path` 绘图工具。
*   优化通知网关的富媒体报告推送能力。

### 第三阶段：数据科学大脑 (v0.18.0)
*   在沙箱内预装科学计算全家桶 (`pandas`, `sklearn`)。
*   实现 `analyze_trend` 工具：由 LLM 驱动进行动态统计建模与异常预测。

---

## 5. 跨平台愿景
*   **技能即插件**: 所有 AIOps 能力均封装为标准的 `.olav/skills/` 架构。
*   **多平台运行**: 确保在任何能够执行本地 Python 脚本的 Agent 平台上（Claude-Code / Gemini-Agent 等）都能瞬间恢复上述所有“专家级”分析能力。
