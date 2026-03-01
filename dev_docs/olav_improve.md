# OLAV LLM-Native 进化与工作流优化方案 (v0.12.0)

## 1. 核心愿景 (Vision)
将 OLAV 从传统的“工具调用框架”升级为**深度大模型原生 (LLM-Native)** 的智能自愈系统。利用 `deepagents` 的沙箱机制和 `langchain` 的高级内存管理，在现有 LanceDB 与 DuckDB 架构之上，实现路由极简化、纠错自动化、以及海量数据处理的逻辑下推。

---

## 2. 语义路由层 (Semantic Router)
**目标**：消除 Intent Router 的 LLM 调用延迟 (1-3s)，实现毫秒级 Agent 分发。

*   **技术实现**：
    *   **存储**：在全局 **LanceDB** 中维护 `agent_intent_index` 表，存储各 Specialist Agent 的 `Skill.md` 语义向量。
    *   **深度集成**：利用 `langchain-core` 的 `Embeddings` 接口对 User Query 进行预处理。
    *   **逻辑**：
        1.  用户输入 -> 向量化 -> LanceDB 语义匹配。
        2.  命中阈值 (>0.85) -> 直接分发。
        3.  未命中 -> 降级调用廉价模型 (DeepAgents Tier 1) 进行 Routing。
*   **收益**：路由性能提升 95%，显著降低首包延迟。

## 3. 语义安全护栏 (Semantic Guardrails) - Policies as Code
**目标**：将安全规则从硬编码升级为“可配置、可审计、可同步”的资产，通过意图识别预防高危操作。

*   **技术实现**：
    *   **配置化资产**：定义 `.olav/workspace/config/sync/config/security_policies.yaml`，按类别（Destructive, High Risk）和级别（BLOCK, CONFIRM）声明危险意图模板。
    *   **同步注册**：将 `sync_security_rules` 工具分配给 **Config Agent**，负责将配置同步并泛化至向量库。
    *   **前置碰撞校验**：在任何 Agent 逻辑执行前，对 User Query 进行向量化并与 `security_denylist` 进行相似度匹配。
*   **收益**：建立起一层超越正则、具备语义泛化能力的防火墙，确保 2000 台设备集群的安全边界。

## 4. SQL 纠错反思环 (Reflection & Self-Correction)
**目标**：彻底解决 Tier 1 SQL 翻译 Agent 生成无效 SQL 导致的报错体验。

*   **技术实现**：
    *   **LangGraph 节点设计**：在 `QueryAgent` 的 LangGraph 中，将 `ExecuteSQL` 与 `ReviewSQL` 形成闭环。
    *   **流程**：`生成 SQL -> 执行 -> (若失败) 捕获 Error -> LLM 修正 -> 重试`。
*   **收益**：自然语言查库成功率从 70% 提升至 95% 以上。

## 5. 动态上下文记忆压缩 (Context Compression)
**目标**：保持 `checkpoints.duckdb` 原子性的同时，防止长对话导致的 Token 爆炸与模型幻觉。

*   **技术实现**：
    *   **语义缓存 (Semantic Cache)**：在 `llm_cache.db` 中引入“模板匹配”机制。
    *   **摘要机制**：当消息流过长时，调用异步节点生成对话摘要，仅保留 Summary + 最近对话。
*   **优势**：确保持续的响应速度与低成本，且不丢失排障背景。

## 6. 运维计算子代理 (Ops Subagent: Computational Sandbox)
**目标**：将复杂的统计分析、拓扑关联计算与变更风险模拟隔离在专用的沙箱子代理中，实现“计算与决策分离”。

*   **技术实现**：
    *   **权限沙盒化**：该 Subagent 强制在 `deepagents.sandbox` 中执行，仅拥有对主库与日志目录的 `READ_ONLY` 挂载权限。
    *   **职责**：负责大规模数据的离线计算、一致性检查及变更模拟。
*   **应用场景**：丢包率方差趋势分析、复杂拓扑闭环验证。

## 7. 工具自动注册与发现机制 (Automatic Skill Registration)
**目标**：消除硬编码工具列表，利用 `deepagents` 原生的动态发现机制实现 1:1 技能绑定。

*   **技术实现**：
    *   **SkillsMiddleware**: 利用深层代理自带的 `SkillsMiddleware` 自动扫描 `.olav/workspace/` 下的所有 `SKILL.md` 文件。
    *   **动态加载**: Agent 启动时，根据其所属的 `category` 或指定的 `skill_id`，中间件自动解析并注入 `.olav/scripts/` 下对应的 Python 脚本。
    *   **元数据契约**: `SKILL.md` 提供唯一的 Tool Spec（含 JSON Schema 校验），脚本提供执行逻辑，由 `deepagents` 负责统一调度（subprocess 调用与结果合成）。
*   **收益**: 极简的扩展路径，新增技能只需添加 Markdown + Python 脚本，无需修改 Agent 核心代码。

## 8. 三层配置解耦体系 (Three-Tier Config Decoupling)
**目标**：消除源码中的硬编码（端口、路径、阈值），支持多用户环境隔离与零修改移植。

*   **技术实现**：
    *   **Tier 1: Defaults (Blueprint)**: `src/olav/core/defaults.py` 定义系统逻辑骨架与出厂设置（如默认端口 5514）。
    *   **Tier 2: Project Config (State)**: `.olav/config/settings.yaml` 存储当前工作空间的个性化设置，随项目分发。
    *   **Tier 3: User/Env Config (Secrets)**: `~/.olav/config.json` 或环境变量存储 API Keys 与私有的端口覆盖，实现用户间物理冲突隔离。
    *   **加载逻辑**: 优先级为 `Env > User > Project > Blueprint`。
*   **收益**: 源码与环境彻底解耦，极大提升系统的安全性与多机部署能力。

## 9. 工具与库规范
为确保架构整洁，必须严格遵循以下库的使用规范：

1.  **Orchestration**: 优先使用 `DeepAgents` (LangGraph 子集)，复用其 Middleware 机制。
2.  **Sandbox**: 强制使用 `deepagents.sandbox` 隔离执行。
3.  **Vector**: 统一通过 `langchain-community` 的 LanceDB 适配器进行操作。
4.  **CLI**: 扩展 `deepagents-cli` 风格的 Slash Commands，所有输出由底层 `Universal Synthesis` 统一格式化。

---

## 10. 实施路线图 (TDD)

### Phase 0: 基础设施与引导启动 (Bootstrapping & Config Loader)
- **目标**：实现系统的“冷启动”能力，验证三层配置解耦的级联优先级。
- **Test (TDD)**: `tests/unit/test_config_loader.py`
    - 验证 `Env > User (~/.olav/) > Project (.olav/) > Blueprint (src/defaults.py)` 的覆盖逻辑。
    - 确认 `PathsConfig` 能从三层配置中推导出正确的绝对路径。
- **Test (TDD)**: `tests/unit/test_workspace_initialization.py`
    - 运行 `uv run olav onboard` (Step 0)。
    - 验证 `.olav/` 及其子目录（databases, scripts, workspace）被正确创建。
    - 验证 `olav.duckdb` 和 `memory.lancedb` 的基础表空间已就绪。
- **Action**: 
    - 实现 `src/olav/core/config_loader.py`。
    - 实现 `src/olav/cli/commands/onboard.py` (取代旧的 init)。
    - 封装 `src/olav/core/path_resolver.py` 为全平台提供统一路径契约。

### Phase 1: 基础建设 (Semantic Cache & Router)
- **Test (TDD)**: `tests/unit/test_semantic_router.py`
    - 向 LanceDB 注册两个 Agent。
    - 验证模糊查询（例如“帮我比一比配置”）能否正确路由到 Config Agent。
- **Action**: 实现 `src/olav/core/router.py`，集成 LanceDB 语义匹配逻辑。

### Phase 2: 安全防御与同步 (Security Sync & Guardrails)
- **Test (TDD)**: `tests/unit/test_security_sync.py`
    - 准备包含“delete configs”意图的 `security_policies.yaml`。
    - 执行 `sync_security_rules` 工具。
    - 验证 `security_denylist` 表中已存入对应的向量。
    - 输入变体指令（如“清空这台盒子的所有设置”），验证 `SecurityViolationError` 触发。
- **Action**: 
    - 创建 `src/olav/tools/sync_security_rules.py`。
    - 实现 `src/olav/core/security.py` 前置校验 Middleware。

### Phase 3: 诊断闭环 (SQL Reflection)
- **Test (TDD)**: `tests/unit/test_sql_reflection.py`
    - 模拟 Tier 1 生成一个错误的 SQL（如字段名错误）。
    - 验证 LangGraph 能够自动捕获 DuckDB 报错并生成第 2 版修正 SQL。
- **Action**: 在 `QueryAgent` 中重构 LangGraph 节点，加入反思循环。

### Phase 4: 上下文优化 (Context Compress)
- **Test (TDD)**: `tests/unit/test_context_compression.py`
    - 模拟一个极长的 Message 序列。
    - 验证进入 Agent 的最终 Payload 是否包含了 Summary 且长度符合阈值。
- **Action**: 接入 `ConversationSummaryBufferMemory` 压缩机制。

### Phase 5: 沙箱统计 (Sandbox Execution)
- **Test (TDD)**: `tests/unit/test_sandbox_stats.py`
    - 准备 1000 条 CSV 数据。
    - 模型生成绘制方差直方图的代码。
    - 验证代码在 `deepagents.sandbox` 中成功执行且未触碰写权限。
- **Action**: 在 Tier 2 Agent 中集成 `SandboxTool`。

### Phase 6: 配置变更预测与数孪模拟 (Change Simulation)
- **目标**：实现“数孪模拟”引擎，验证变更对路由连通性与策略的影响。
- **Test (TDD)**: `tests/unit/test_network_simulator.py`
    - 注入一段 BGP Neighbor 属性修改的配置片段。
    - 验证 `simulate_change` 工具能通过 SQL 从 DuckDB 提取拓扑事实。
    - 验证沙箱内的 NetworkX 脚本能输出变更后的推演路由表。
    - 断言模型能正确解释连通性丢失的原因。
- **Action**: 
    - 实现 `src/olav/core/simulation/engine.py` (整合 DuckDB 事实提取与 NetworkX 逻辑)。
    - 开发 `.olav/workspace/ops/simulation/tools/simulate_change.py`。
    - 为 `ops-simulation` 注册 `execute_sql` 与 `analyze_network_topology` 复合工具链。
    - 为 LLM 提供“拓扑感知”推理 Prompt。
