# OLAV 重构文档索引

**版本**: v0.11 → v2.0  
**日期**: 2026-02-14  
**状态**: 设计阶段 → 实施准备中

---

## 📖 文档阅读顺序

### 第一阶段：问题诊断（已完成）

#### 1. [CODE_AUDIT_2026_02_14.md](CODE_AUDIT_2026_02_14.md) 
**代码审计报告**

- **目的**: 全面诊断现有架构问题
- **范围**: 67 个文件，22,750 行代码
- **关键发现**:
  - ❌ DeepAgents 被完全绕过（1,077 行正则路由）
  - ❌ 5 个 SubAgent 过度设计（单领域仅 3 个工具）
  - ❌ 1,500+ 行死代码（optimizer, enhancer）
  - ❌ SQL 注入风险（api/v1/devices.py）
  - ⚠️ 175 个 YAML 定时任务（920KB）
- **核心结论**: 需要重构回 DeepAgents 原生架构

**受众**: 所有开发者（必读，理解重构动机）  
**阅读时间**: 15-20 分钟

---

### 第二阶段：架构设计（已完成）

#### 2. [DEEPAGENTS_SIMPLIFICATION_PLAN.md](DEEPAGENTS_SIMPLIFICATION_PLAN.md) ⭐
**DeepAgents 原生架构精简方案**

- **架构演进**: 5 SubAgents → **1 Agent + Skills**
- **核心理念**: 
  - 零路由：Agent 直接访问 3 个 tools
  - Skills 热加载：按用户问题动态提供领域知识
  - DuckDB 统一数据层：90% 新集成无需新工具
- **关键设计**:
  - 4 层数据库架构（main/agent/cache/knowledge）
  - 2 层 Schema 缓存（内存+文件）
  - Admin/Command-Learner → /COMMAND 模式
  - Inspection Tool → python-crontab 管理
- **实施路线**: 4 个阶段，预计 2 周

**受众**: 架构师、核心开发者（核心文档）  
**阅读时间**: 40-50 分钟  
**依赖**: 阅读完 CODE_AUDIT 后阅读

---

#### 3. [TOOLS_LOCATION_RATIONALE.md](TOOLS_LOCATION_RATIONALE.md)
**工具位置选择理由**

- **决策**: Tools 放在 `.olav/tools/`（不是 `src/olav/tools/`）
- **理由**:
  - ✅ MCP 标准兼容
  - ✅ 跨平台迁移（复制 .olav/ 即可）
  - ✅ 业务/框架分离
  - ✅ 动态加载机制
- **影响**: 
  - 现有 `.olav/shared/tools/` → `.olav/tools/`
  - 6 个工具 → 3 个工具（-55% 代码）

**受众**: 架构师、工具开发者  
**阅读时间**: 10 分钟  
**依赖**: 理解 DEEPAGENTS_SIMPLIFICATION_PLAN 后阅读

---

#### 4. [OLAV_DIRECTORY_REFACTOR_ANALYSIS.md](OLAV_DIRECTORY_REFACTOR_ANALYSIS.md)
**.olav/ 目录重构分析**

- **当前状态**: 70.4MB（47M db, 22M skills, 920K tasks）
- **删除内容**:
  - cache/ (100K) - 迁移到 DuckDB
  - tasks/scheduled/ (920K, 175 YAML) - 废弃
  - 3 个冗余工具（query_database, inspect_schema, discover_data）
  - 3 个废弃 Skills（guard, orchestrator, agent-router）
- **保留内容**:
  - olav-admin skill（备份、架构查询、176KB 文档）
  - knowledge/ 向量库
  - workflows/ 工作流定义
- **工具重构**: 6 → 3 文件，1,376 → 620 行（-55%）
- **数据库合并**: network.duckdb → main.duckdb

**受众**: 实施开发者、DevOps  
**阅读时间**: 25-30 分钟  
**依赖**: 理解 DEEPAGENTS_SIMPLIFICATION_PLAN 后阅读

---

#### 5. [ADMIN_AND_CRON_DESIGN_v2.md](ADMIN_AND_CRON_DESIGN_v2.md)
**Admin 管理与 Cron 机制设计**

- **Admin 双模式**:
  - CLI 快捷命令（< 1秒，确定性）
  - 对话式管理（3-5秒，智能化）
- **Cron 简化方案**: python-crontab Tool
  - 替代方案：bash 脚本（已废弃）、APScheduler（过度工程）
  - 优势：编程式管理、Agent 可控、架构统一
- **Inspection Tool 实现**:
  - 6 个 Actions: schedule, unschedule, list, run, status, logs
  - 双模式：LangChain tool + stdin JSON
  - Lock file、超时、日志、Webhook 通知

**受众**: 实施开发者、运维  
**阅读时间**: 20 分钟  
**依赖**: 理解 OLAV_DIRECTORY_REFACTOR_ANALYSIS 后阅读

---

### 第三阶段：实施追踪（进行中）

#### 6. [REFACTOR_TRACKING.md](REFACTOR_TRACKING.md) 📊
**重构进度追踪**

- **当前阶段**: Phase 0 准备中
- **完成度**: 设计 100%，实施 0%
- **关键里程碑**:
  - Phase 0: 安全与清理（1 天）
  - Phase 1: 工具重构（3-5 天）
  - Phase 2: 数据库整合（1 天）
  - Phase 3: Agent 切换（2 天）
- **风险与阻塞项**: 实时更新

**受众**: 项目管理、全体开发者  
**阅读时间**: 5-10 分钟  
**更新频率**: 每日

---

## 🗂️ 文档关系图

```
CODE_AUDIT_2026_02_14.md (诊断)
         ↓
DEEPAGENTS_SIMPLIFICATION_PLAN.md (核心架构) ⭐
         ↓
         ├─→ TOOLS_LOCATION_RATIONALE.md (工具位置)
         ↓
         └─→ OLAV_DIRECTORY_REFACTOR_ANALYSIS.md (目录重构)
                    ↓
                    └─→ ADMIN_AND_CRON_DESIGN_v2.md (Admin & Cron)
                              ↓
                    REFACTOR_TRACKING.md (进度追踪) 📊
```

---

## 🎯 快速导航

### 我是新加入的开发者
**阅读顺序**: CODE_AUDIT → DEEPAGENTS_SIMPLIFICATION_PLAN → REFACTOR_TRACKING

### 我要实施工具重构
**阅读顺序**: DEEPAGENTS_SIMPLIFICATION_PLAN → TOOLS_LOCATION_RATIONALE → OLAV_DIRECTORY_REFACTOR_ANALYSIS

### 我要实施 Admin 功能
**阅读顺序**: DEEPAGENTS_SIMPLIFICATION_PLAN → ADMIN_AND_CRON_DESIGN_v2 → REFACTOR_TRACKING

### 我要了解进度
**直接查看**: REFACTOR_TRACKING.md

### 我要了解完整架构
**核心文档**: DEEPAGENTS_SIMPLIFICATION_PLAN.md（40-50 分钟，必读）

---

## 📚 补充文档

### 用户文档（docs/ 目录）
- `docs/reference/QUICK_START_DEVELOPER.md` - 5 分钟上手
- `docs/reference/ARCHITECTURE.md` - 系统架构
- `docs/reference/SUB_AGENT_DEVELOPMENT_GUIDE.md` - Agent 开发
- `docs/reference/SKILL_AUTHORING_GUIDE.md` - Skill 编写
- `docs/reference/TESTING_QUICK_REFERENCE.md` - 测试规范

### 根目录文档
- `.github/copilot-instructions.md` - GitHub Copilot 指令
- `README.md` - 项目概述
- `STRUCTURE.md` - 目录结构说明

---

## 🔄 文档更新规则

### 更新频率
- **CODE_AUDIT**: 不再更新（历史快照）
- **DEEPAGENTS_SIMPLIFICATION_PLAN**: 重大架构变更时更新
- **TOOLS_LOCATION_RATIONALE**: 稳定（无需更新）
- **OLAV_DIRECTORY_REFACTOR_ANALYSIS**: 实施阶段调整时更新
- **ADMIN_AND_CRON_DESIGN_v2**: 实施细节调整时更新
- **REFACTOR_TRACKING**: **每日更新**

### 更新原则
1. **向后兼容**: 使用版本号（v1.0, v2.0, v2.1）
2. **时间戳**: 每个更新标注日期
3. **变更日志**: 重大修改在顶部添加 CHANGELOG
4. **交叉引用**: 文档间使用相对路径链接

### 新增文档命名规范
- 诊断类: `*_AUDIT_*.md`
- 设计类: `*_DESIGN_*.md`, `*_PLAN_*.md`
- 分析类: `*_ANALYSIS_*.md`
- 理由类: `*_RATIONALE_*.md`
- 追踪类: `*_TRACKING_*.md`

---

## ❓ 常见问题

### Q: 为什么要重构？
A: 阅读 [CODE_AUDIT_2026_02_14.md](CODE_AUDIT_2026_02_14.md) 第 2 节"关键问题"

### Q: 重构会影响现有功能吗？
A: 不会。所有 10 个功能场景保持兼容（见 DEEPAGENTS_SIMPLIFICATION_PLAN.md 第 14 节）

### Q: 重构需要多久？
A: 预计 2 周（见 REFACTOR_TRACKING.md）

### Q: 我可以参与吗？
A: 可以！查看 REFACTOR_TRACKING.md 中的"待认领任务"

### Q: 重构后性能会提升吗？
A: 会。预计响应时间从 8-15 秒降至 3-5 秒（见 DEEPAGENTS_SIMPLIFICATION_PLAN.md）

---

## 📞 联系方式

- **架构问题**: 查阅 DEEPAGENTS_SIMPLIFICATION_PLAN.md 第 12 节"关键架构问题"
- **实施问题**: 在 REFACTOR_TRACKING.md 添加阻塞项
- **文档更新**: 遵循本文档"文档更新规则"

---

**最后更新**: 2026-02-14  
**维护者**: OLAV Team  
**文档版本**: v1.0
