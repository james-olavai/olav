# Expert Agent 测试计划文档索引

**创建日期**: 2026年2月11日  
**文档体系版本**: v1.0.0  
**状态**: 📋 规划中  

---

## 📚 文档导航

本索引提供 Expert Agent 完整测试计划的快速导航和文档概览。

### 文档列表

| # | 文档 | 版本 | 大小 | 说明 |
|----|------|------|------|------|
| 1️⃣ | [EXPERT_AGENT_ACCEPTANCE_TEST_PLAN.md](#1-验收测试方案) | v1.0.0 | 12KB | 8个主要测试场景定义,验收标准与指标 |
| 2️⃣ | [EXPERT_AGENT_TECHNICAL_DESIGN.md](#2-技术设计文档) | v1.0.0 | 18KB | 诊断流程架构,诊断树,工具链设计 |
| 3️⃣ | [EXPERT_AGENT_FAULT_INJECTION_GUIDE.md](#3-故障注入与知识库指南) | v1.0.0 | 16KB | 故障注入工具,知识库初始化,诊断验证 |
| 4️⃣ | [EXPERT_AGENT_IMPLEMENTATION_ROADMAP.md](#4-实施计划与路线图) | v1.0.0 | 14KB | 5周项目计划,资源分配,风险管理 |
| 📍 | **本文档** (INDEX) | v1.0.0 | 本文件 | 文档导航与使用指南 |

---

## 📖 详细文档说明

### 1️⃣ 验收测试方案

**[EXPERT_AGENT_ACCEPTANCE_TEST_PLAN.md](./EXPERT_AGENT_ACCEPTANCE_TEST_PLAN.md)**

#### 内容覆盖

```
✓ 8个主要测试场景
  1. BGP故障诊断      2. 级联故障分析
  3. OSPF邻接故障    4. 网络设计缺陷
  5. 安全策略问题    6. 知识库集成
  7. 工具链完整性    8. 多域交叉问题

✓ 每个场景包含:
  - 功能描述
  - 测试流程 (5-7个Phase)
  - 多个测试用例
  - 具体故障注入命令
  - 预期结果与验收标准

✓ 关键指标:
  - 诊断准确率 ≥ 85%
  - 知识库命中率 ≥ 70%
  - 工具成功率 ≥ 95%
  - 平均诊断时间 < 45秒
```

#### 适用场景

- 📋 **QA工程师**: 用于编写测试脚本和执行测试
- 🔍 **测试分析**: 用于诊断结果验证
- ✅ **验收评审**: 用于项目最终验收
- 📊 **数据收集**: 用于性能基准测试

#### 关键章节

- 📌 **场景1**: BGP邻接故障诊断与解决 (4个测试用例)
- 📌 **场景2**: 级联故障分析 (链路级联重收敛)
- 📌 **场景3**: OSPF邻接互联故障 (2个测试用例)
- 📌 **场景4-8**: 其他5个场景

---

### 2️⃣ 技术设计文档

**[EXPERT_AGENT_TECHNICAL_DESIGN.md](./EXPERT_AGENT_TECHNICAL_DESIGN.md)**

#### 内容覆盖

```
✓ 核心流程架构
  5个诊断阶段 + 7个执行Phase
  
✓ 诊断策略框架
  - BGP诊断树 (6大分支,20+ leaf nodes)
  - OSPF诊断树 (3大分支,15+ leaf nodes)
  
✓ 工具链架构
  - 数据采集层 (4个工具)
  - 知识层 (3个工具)
  - 分析层 (LLM+规则)
  - 生成层 (报告生成)
  - 学习层 (自学习)

✓ 知识库架构
  - 目录结构 (bgp/ospf/acl/infrastructure/design)
  - 案例模板 (元数据+问题描述+RCA+方案)
  - 查询流程 (关键词提取→标签匹配→相似度计算)

✓ 性能优化
  - 并行化诊断执行
  - 诊断结果缓存
  - 错误处理与降级

✓ 监控指标
  - 诊断准确率
  - 知识库命中率
  - 工具成功率
  - 诊断平均时间
```

#### 适用场景

- 👨‍💻 **开发工程师**: 用于理解诊断流程和架构
- 🏗️ **架构师**: 用于系统设计评审
- 📚 **知识库管理**: 用于案例库建设
- 🔧 **工具集成**: 用于工具链开发

#### 关键章节

- 🔍 **诊断流程图** (7个Phase的执行流)
- 🌳 **BGP诊断树** (递归诊断决策树)
- 🌳 **OSPF诊断树** (递归诊断决策树)
- 🔗 **工具链架构** (5层工具栈)
- 💾 **知识库设计** (目录+索引+查询)

---

### 3️⃣ 故障注入与知识库指南

**[EXPERT_AGENT_FAULT_INJECTION_GUIDE.md](./EXPERT_AGENT_FAULT_INJECTION_GUIDE.md)**

#### 内容覆盖

```
✓ 故障注入工具框架
  - FaultInjector 类 (7个故障类型)
  - 故障注入方法 (支持GNS3/EVE-NG/真实网络)
  - 故障恢复方法 (自动rollback)

✓ 故障场景脚本
  - 场景1: BGP邻接DOWN (完整脚本)
  - 场景2: OSPF Area不匹配 (完整脚本)
  - 其他6个场景 (伪代码)

✓ 知识库初始化
  - 目录结构创建脚本
  - 预置案例库清单
  - 案例模板与格式
  - 知识库索引更新工具

✓ 诊断验证工具
  - DiagnosisVerifier 类
  - 验证检查表
  - 自动化验证脚本

✓ 执行指南
  - 环境准备步骤
  - 单个/批量场景执行
  - 结果验证方法
```

#### 适用场景

- 🔧 **测试工程师**: 用于构建故障场景和执行测试
- 📝 **知识库管理**: 用于初始化和维护案例库
- ✅ **质量保证**: 用于验证诊断结果的正确性
- 🚀 **演示与培训**: 用于展示Expert能力

#### 关键章节

- ⚙️ **FaultInjector类** (故障注入框架)
- 🔴 **故障场景脚本** (2个完整脚本)
- 📚 **知识库初始化** (案例库预置方法)
- 🧪 **诊断验证工具** (自动化验证框架)

---

### 4️⃣ 实施计划与路线图

**[EXPERT_AGENT_IMPLEMENTATION_ROADMAP.md](./EXPERT_AGENT_IMPLEMENTATION_ROADMAP.md)**

#### 内容覆盖

```
✓ 5周项目计划
  Week 1: 环境准备 (GNS3/故障注入工具/知识库初始化)
  Week 2: 单场景测试 (BGP/OSPF/ACL - 基础协议)
  Week 3: 复杂场景 (级联故障/设计缺陷/知识库集成)
  Week 4: 工具链与多域 (工具完整性/多域交叉)
  Week 5: 整合优化 (缺陷修复/性能优化/最终验收)

✓ 详细任务分解
  - 每周具体任务清单
  - 完成标准与交付物
  - 风险识别与缓解

✓ 资源分配
  - 人员组织结构 (5人团队)
  - 工时预估 (~200小时)
  - 角色职责明确

✓ 成功标准 (Go/No-Go)
  - 必需指标 (诊断准确率/知识库命中等)
  - 性能指标 (时间/成本)
  - 决策点检查 (Week2/Week4)

✓ 风险管理
  - 6大高风险项识别
  - 预防和应急策略
  - 缓解计划

✓ 交付物清单
  - 类别化交付物列表
  - 最终验收标准
```

#### 适用场景

- 📅 **项目经理**: 用于制定项目计划和跟踪进展
- 👥 **团队负责人**: 用于资源分配和任务分解
- ⚠️ **风险管理**: 用于识别和缓解项目风险
- ✅ **验收评审**: 用于最终项目验收

#### 关键章节

- 🗓️ **周项目计划** (5周详细任务)
- 👥 **资源分配** (人员组织+工时预估)
- 📊 **成功标准** (Go/No-Go决策点)
- 🚨 **风险管理** (6大风险+缓解方案)

---

## 🎯 快速导航

### 按角色查找

**👨‍💼 项目经理**
- 📋 Start: [实施计划](./EXPERT_AGENT_IMPLEMENTATION_ROADMAP.md#周项目计划)
- 📊 Reference: [成功标准](./EXPERT_AGENT_IMPLEMENTATION_ROADMAP.md#成功标准-go-no-go)
- ⚠️ Risk: [风险管理](./EXPERT_AGENT_IMPLEMENTATION_ROADMAP.md#风险管理)

**👨‍💻 开发工程师**
- 🏗️ Start: [技术设计](./EXPERT_AGENT_TECHNICAL_DESIGN.md)
- 🔗 Reference: [工具链架构](./EXPERT_AGENT_TECHNICAL_DESIGN.md#工具链架构)
- 📚 KB: [知识库集成](./EXPERT_AGENT_TECHNICAL_DESIGN.md#知识库架构)

**🧪 测试工程师**
- 📋 Start: [验收测试方案](./EXPERT_AGENT_ACCEPTANCE_TEST_PLAN.md)
- 🔴 Scenarios: [8个测试场景](./EXPERT_AGENT_ACCEPTANCE_TEST_PLAN.md#测试场景总览)
- 🔧 Tools: [故障注入指南](./EXPERT_AGENT_FAULT_INJECTION_GUIDE.md)

**🔧 网络工程师**
- 🌐 Start: [故障注入指南](./EXPERT_AGENT_FAULT_INJECTION_GUIDE.md#故障注入工具集)
- 📝 Scenarios: [单个场景脚本](./EXPERT_AGENT_FAULT_INJECTION_GUIDE.md#故障场景脚本)
- ✅ Verify: [诊断验证](./EXPERT_AGENT_FAULT_INJECTION_GUIDE.md#诊断流程验证)

**📚 知识库管理**
- 💾 Start: [知识库初始化](./EXPERT_AGENT_FAULT_INJECTION_GUIDE.md#知识库初始化)
- 📄 Template: [案例模板](./EXPERT_AGENT_FAULT_INJECTION_GUIDE.md#预置案例库)
- 🔍 Search: [查询流程](./EXPERT_AGENT_TECHNICAL_DESIGN.md#知识库质询流程)

### 按任务查找

**🚀 快速启动**
1. 阅读: [实施计划 - Week 1](./EXPERT_AGENT_IMPLEMENTATION_ROADMAP.md#week-1-环境准备与基础设置)
2. 准备: [环境搭建指南](#)
3. 执行: [故障注入工具](./EXPERT_AGENT_FAULT_INJECTION_GUIDE.md)

**📋 编写测试**
1. 参考: [验收测试方案](./EXPERT_AGENT_ACCEPTANCE_TEST_PLAN.md)
2. 选择场景: [8个测试场景](./EXPERT_AGENT_ACCEPTANCE_TEST_PLAN.md#测试场景总览)
3. 工具支持: [故障注入脚本](./EXPERT_AGENT_FAULT_INJECTION_GUIDE.md#故障场景脚本)
4. 验证结果: [诊断验证工具](./EXPERT_AGENT_FAULT_INJECTION_GUIDE.md#自动化验证脚本)

**🏗️ 系统实现**
1. 理解: [诊断流程架构](./EXPERT_AGENT_TECHNICAL_DESIGN.md#核心流程架构)
2. 设计: [工具链架构](./EXPERT_AGENT_TECHNICAL_DESIGN.md#工具链架构)
3. 优化: [性能优化](./EXPERT_AGENT_TECHNICAL_DESIGN.md#性能优化)

**📚 知识库建设**
1. 初始化: [知识库结构](./EXPERT_AGENT_FAULT_INJECTION_GUIDE.md#知识库初始化)
2. 预置案例: [案例库清单](./EXPERT_AGENT_FAULT_INJECTION_GUIDE.md#预置案例库列表)
3. 维护管理: [索引更新](./EXPERT_AGENT_FAULT_INJECTION_GUIDE.md#知识库索引更新)

---

## 📊 文档统计

```
总页数:      ~60 页
总字数:      ~40,000 字
总代码行:    ~1,500 行
测试场景:    8 个
测试用例:    30+ 个
知识库案例:  50+ 个预置
工具数:      10+ 个
诊断树节点:  50+ 个
```

---

## 🔄 文档更新历史

| 版本 | 日期 | 变更 | 作者 |
|------|------|------|------|
| v1.0.0 | 2026-02-11 | 初始版本,4个主要文档 | Expert Agent Team |

---

## 📞 相关资源

### 内部项目

- `.olav/OLAV.md` - Expert Agent 定义
- `.olav/skills/expert/SKILL.md` - Expert Skill配置
- `src/olav/agents/expert.py` - Expert Agent 实现
- `tests/e2e/test_expert_diagnostics.py` - E2E测试

### 外部参考

- [RFC 4271 - BGP Protocol](https://tools.ietf.org/html/rfc4271)
- [RFC 2328 - OSPF Protocol](https://tools.ietf.org/html/rfc2328)
- [Cisco Documentation](https://www.cisco.com/c/en/us/support/docs/)

### 相继项目

- 🔄 Query Agent 测试计划 (已完成)
- 🔄 CLI Agent 测试计划 (已完成)
- 📅 Analysis Agent 测试计划 (后续)
- 📅 Inspection Agent 测试计划 (后续)

---

## ✅ 使用检查表

```
阅读本索引后:

- [ ] 理解Expert Agent的8个测试场景
- [ ] 知道各个文档的用途和内容
- [ ] 根据角色找到对应的文档章节
- [ ] 熟悉5周项目计划的整体安排
- [ ] 理解工具链架构和诊断流程
- [ ] 知道如何进行故障注入和验证
- [ ] 准备阅读详细文档
```

---

## 🎓 推荐阅读顺序

### 快速了解 (30分钟)
1. 本文 (索引文档) - 5分钟
2. [实施计划简介](./EXPERT_AGENT_IMPLEMENTATION_ROADMAP.md) - 10分钟
3. [验收测试场景概览](./EXPERT_AGENT_ACCEPTANCE_TEST_PLAN.md#测试场景总览) - 10分钟
4. [技术架构图](./EXPERT_AGENT_TECHNICAL_DESIGN.md#核心流程架构) - 5分钟

### 充分理解 (2小时)
1. 验收测试方案 (完整) - 45分钟
2. 技术设计文档 (核心章节) - 45分钟
3. 实施计划 (关键章节) - 20分钟
4. 故障注入指南 (快速扫读) - 10分钟

### 深入学习 (4小时)
1. 按上述顺序完整阅读所有4个文档
2. 查看代码示例和脚本
3. 理解诊断树和工具链架构
4. 准备执行第一个测试场景

---

## 💡 使用建议

### 📋 团队协作

1. **项目启动会**: 
   - 项目经理介绍实施计划 (10分钟)
   - 各角色确认职责和交付物 (10分钟)

2. **技术预研**:
   - 开发和架构师共同评审技术设计 (1小时)

3. **测试协调**:
   - 测试工程师和网络工程师协调故障场景 (30分钟)

### 📝 文档维护

- Week 2/4 时更新 Go/No-Go 决策状态
- 每周更新进度表和风险清单
- 月末更新文档版本号

### 🔄 迭代改进

- 每个场景完成后收集反馈
- 修订诊断树和工具链逻辑
- 积累知识库案例

---

**文档体系版本**: v1.0.0  
**最后更新**: 2026年2月11日  
**维护者**: Expert Agent Team  
**下一步**: 启动Week 1环境准备

---

## 快速链接

| 快速导航 | 链接 |
|----------|------|
| 📋 验收测试方案 | [EXPERT_AGENT_ACCEPTANCE_TEST_PLAN.md](./EXPERT_AGENT_ACCEPTANCE_TEST_PLAN.md) |
| 🏗️ 技术设计 | [EXPERT_AGENT_TECHNICAL_DESIGN.md](./EXPERT_AGENT_TECHNICAL_DESIGN.md) |
| 🔧 故障注入指南 | [EXPERT_AGENT_FAULT_INJECTION_GUIDE.md](./EXPERT_AGENT_FAULT_INJECTION_GUIDE.md) |
| 🗓️ 实施路线图 | [EXPERT_AGENT_IMPLEMENTATION_ROADMAP.md](./EXPERT_AGENT_IMPLEMENTATION_ROADMAP.md) |
| 🚀 开始阅读 | [点击开始](./EXPERT_AGENT_ACCEPTANCE_TEST_PLAN.md) |
