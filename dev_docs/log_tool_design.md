# OLAV 日志查询与智能分析引擎架构设计 (v0.13.0) - AIOps Native

## 1. 架构愿景：从“被动检索”到“主动提纯”
为了补齐 OLAV 在网络运维“诊断与排查”的最后一块短板，本项目彻底摒弃了传统的 ELK/Splunk “无脑存储检索”模式。针对 2000 台设备规模，采用 **Vector + LLM 提纯 + 双库隔离 (DuckDB & LanceDB)** 的极致 AI 原生架构（LLM-Native）。

核心目标是：不仅要解决 DuckDB 高频写入的锁问题，更要将海量噪音日志转化为高密度的 **“故障经验知识库”**。

---

## 2. 核心架构与数据流向

整个日志处理流被分为三个完全解耦的层级：采集分流层、结构化增强层、存储查询层。

### 2.1 采集层与双线分流 (Vector Fork)
使用高性能的 **Vector** 替代 Fluent Bit，通过其原生的 VRL (Vector Remap Language) 脚本进行极其高效的初步标准化（提取 `timestamp`, `host`, `severity`）。

> **⚠️ 当前实现状态**: Vector 未安装，已用 `.olav/workspace/log-analytics/syslog_receiver.py`（asyncio UDP，RFC 3164/5424）替代。功能等价，但缺少 VRL 的高性能预处理能力。

在 Vector 内部，日志流水线被分叉 (Fork)：
*   **【Route 1：全量审计流】✅ 已实现**
    *   **策略**：所有级别（包含 INFO/DEBUG 等噪音）的日志直接打包输出为 **Parquet** 格式。
    *   **位置**：持久化到 **`.olav/databases/logs/YYYY-MM-DD/`**（作为核心数据库资产）。
    *   **作用**：用于法务合规审计、精确时间线对齐，以及无锁的大范围聚合统计查询。
*   **【Route 2：高价值故障流】⏳ 待实现**
    *   **策略**：VRL 仅过滤出 `Warning/Error/Critical` 级别的日志，通过 Webhook/HTTP 发送给可被 OLAV 调用的本地 Python/API 接口，进入“增强队列”。

### 2.2 增强层 (OLAV Logic - LLM 降噪提纯) ⏳ 待实现
网络设备的原始日志充满了随时变化的变量（如动态 IP、MAC地址、随机时间），这会导致 Embedding 计算出来的向量空间极度混乱。

OLAV 的 Python 中间件将对 Route 2 收到的错误日志集执行以下处理：
1.  **资产身份关联 (Identity Mapping)**: 建立 `Host <-> IP <-> Alias` 的内存映射表。当日志来源于 IP 时，自动补全其在 `devices` 表中的标准主机名，确保检索支持模糊名称。
2.  **事件去重与聚类 (Episode Clustering)**：在 30 秒的时间窗内，将同一台设备连续产生的错误日志打包成一个事件集（Incident Episode），防止接口风暴。
3.  **多维关联分析 (Cross-Context Analysis)**: 当发现关键 Error 时，自动提取该故障窗口（前后 30s）内的所有相关事件，包括配置审计 (Audit Log) 与流量异常。
4.  **LLM 语义结构化翻译**：将打包好的故障上下文投递给大模型，提取：核心故障现象、可能引发的根因推测、受影响的具体业务模块。
5.  **向量化准备**：大模型返回的结构化 JSON 文本将被向量化并存入 LanceDB。

### 2.3 存储层与读写分离设计
我们彻底放弃了将日志写入主库（`olav.duckdb`）的想法，实现了极致的 **零读写锁冲突 (Zero Locking)**。

*   **全量日志检索 (DuckDB 内存模式)**
    *   **地址**：动态扫描 **`.olav/databases/logs/`** 目录。
    *   **实现机制**：启用一个纯粹的 **`duckdb.connect(':memory:')`**，利用 `read_parquet` 实现无锁查询。
*   **故障语义经验库 (LanceDB 向量召回)**
    *   **实现机制**：存储提纯后的“诊断卡片”及其向量。

---

## 3. 技能自动发现与注册 (Automatic Tool Discovery)

本日志系统的所有工具通过 `deepagents` 的 **SkillsMiddleware** 实现自动注册，无需在任何 Agent 代码中手动声明列表。

### 3.1 核心技能挂载规范
| 工具名称 (in SKILL.md) | 对应脚本 (in `.olav/scripts/`) | 关联子代理 (By Skill Discovery) | 状态 |
| :--- | :--- | :--- | :--- |
| `log_metrics_query` | `log_metrics.py` | **Query Agent** | ✅ 已实现 |
| `semantic_log_search`| `log_semantic.py` | **Ops Subagent** | ✅ 已实现 |
| `log_enhancer` | `log_processor.py` | **Log Processor (Background)** | ⏳ 待实现 |

### 3.2 动态绑定逻辑
1.  **扫描层**: `deepagents` 启动时遍历 `.olav/workspace/log-analytics/SKILL.md`。
2.  **解析层**: 提取工具描述、参数 JSON Schema。
3.  **分发层**: 
    *   **Fast Path**: `log_metrics_query` 自动路由至具备 DuckDB 只读权限的 Tier 1 Agent。
    *   **Deep Path**: `semantic_log_search` 自动注入到运行于 `sandbox` 环境的 Tier 2 Ops Agent。
    *   **Notification Sink**: 新增 `notify_operator` 注入到 Ops Agent 中，用于主动作出报告后推送结果。

---

## 4. 主动自检与智能预警 (Proactive Self-Diagnosis) - [实验功能]

> [!IMPORTANT]
> **本章节描述的功能为 v0.13.0 实验性特性，默认不开启。** 需在应用配置中显式激活 `experimental.proactive_mode: true`。

为了实现故障的“感知即诊断”，本方案设计了一套基于事件驱动的异步排障流水线，旨在无人值守的情况下预先完成根因分析。

### 4.1 异步任务链设计 (Event-Driven Pipeline)

1.  **本地触发 (The Trigger)**: 
    *   **Vector HTTP Sink**: 当矢量采集器过滤出 `Critical` 级日志时，向本地 **OLAV Daemon (基于 FastAPI)** 发送 JSON Payload。
2.  **任务排队 (Task Queue)**: 
    *   Daemon 接收请求后，将其投放至内部异步队列（`asyncio.Queue`），实现采集压力与分析算力的缓冲。
3.  **后台分析者 (Background Analyst)**: 
    *   **Ops Agent Worker**: 运行在 OLAV 主进程后台的持久协程。
    *   **职责**: 监听任务队列 -> 锁定故障时空切片 -> 调用工具集进行多维关联分析。
4.  **按需沙箱执行 (On-Demand Sandboxing)**:
    *   **架构准则**: 规避“沙箱套沙箱”的逻辑悖论。Ops Agent 运行在主进程中负责决策，仅在执行动态生成的统计代码时，将任务下推给专用的 **Sandbox Tool**。

### 4.2 消息触达与第三方网关 (Notification Gateway)

1.  **诊断合成**: Ops Agent 结合沙箱分析结论与 LanceDB 历史故障模式，合成高密度的 Markdown 诊断报告。
2.  **网关推送**: 通过 `notify_operator` 技能脚本，将报告推送到**第三方消息网关**（如 Slack、钉钉 Webhook 或企业统一告警平台），实现信息的精准触达与 HITL（人工干预）闭环。

---

## 5. 黄金排障闭环 (The Agentic Diagnostic Loop)
（略，保持原逻辑）

---

## 6. 生命周期管理与性能保障 (Retention)
*   **Parquet 全量持久化 (DuckDB)**：保留 **30 天**。
*   **LanceDB 经验片段提取**：仅保留最近 **7 天** 的故障卡片。

---

## 7. 开发计划 (TDD)
(略，保持原逻辑，注意将路径更新为 `.olav/databases/logs/`)

---

## 8. 架构解耦与跨平台兼容性 (Platform-Agnostic)
*   **基于文件契约**: 所有 Skill 脚本仅依赖物理文件系统。
*   **部署规范**: 非特权运行，默认监听 **UDP 5514**。
