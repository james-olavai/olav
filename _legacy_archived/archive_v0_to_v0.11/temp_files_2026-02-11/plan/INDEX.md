# Phase 4.1 Query Agent 能力摸底 - 完整文档索引（自然语言驱动版）

**组织**: OLAV Development Team  
**日期**: 2026-02-08  
**版本**: v2.0 - 自然语言驱动E2E测试  
**核心理念**: 用户说自然语言 → Query Agent理解执行 → 生成CSV/MD文件 → 验证结果  

---

## � 文档完整清单（自然语言驱动版）

### 必读文档（优先级P1）

1. **[WHY_NATURAL_LANGUAGE_DRIVEN.md](./WHY_NATURAL_LANGUAGE_DRIVEN.md)** 
   - 📍 **先读这个** - 理解为什么要做这个改变
   - 从SQL导向到自然语言驱动的演进
   - 方法论对比和优势分析

2. **[QUERY_AGENT_E2E_NL_DRIVEN.md](./QUERY_AGENT_E2E_NL_DRIVEN.md)**
   - 📍 **核心文档** - 完整的NL驱动E2E测试规范
   - 100+个具体的测试用例
   - 5大网络运维真实场景
   - 每个Level(1/2/3)的详细说明

3. **[QUERY_AGENT_QUICK_START.md](./QUERY_AGENT_QUICK_START.md)**
   - 📍 **快速开始** - 5分钟让你跑起第一个测试
   - NL查询示例
   - 常见陷阱

### 参考文档（优先级P2）

4. **[QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md](./QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md)**
   - 📍 数据库设计参考
   - 5大场景的SQL逻辑（学习用）
   - 测试框架代码示例

---

## 🗺️ 推荐阅读顺序

**情景1: 我是新人（1小时）**
```
WHY_NATURAL_LANGUAGE_DRIVEN.md (20分钟)
  ↓
QUERY_AGENT_QUICK_START.md (15分钟)
  ↓
QUERY_AGENT_E2E_NL_DRIVEN.md Level 1部分 (25分钟)
  ↓
准备好开始编写第一个测试
```

**情景2: 我需要完全理解设计（3小时）**
```
WHY_NATURAL_LANGUAGE_DRIVEN.md (30分钟)
  ↓
QUERY_AGENT_E2E_NL_DRIVEN.md 全部 (90分钟)
  ↓
QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md (数据模型部分) (30分钟)
  ↓
QUERY_AGENT_QUICK_START.md (15分钟)
  ↓
准备好指导团队实施
```

**情景3: 我在写测试（立即参考）**
```
快速查询 QUERY_AGENT_E2E_NL_DRIVEN.md → Level 1/2/3对应部分
  ↓
参考SQL逻辑 QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md
  ↓
复制CSV验证代码片段 QUERY_AGENT_QUICK_START.md
```

---

## ✨ 文件统计

| 文件 | 大小 | 重要性 | 用途 |
|------|------|--------|------|
| WHY_NATURAL_LANGUAGE_DRIVEN.md | 8KB | ⭐⭐⭐⭐⭐ | 理解为什么 |
| QUERY_AGENT_E2E_NL_DRIVEN.md | 12KB | ⭐⭐⭐⭐⭐ | 核心规范 |
| QUERY_AGENT_QUICK_START.md | 8KB | ⭐⭐⭐⭐ | 快速开始 |
| QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md | 15KB | ⭐⭐⭐ | 技术参考 |
| QUERY_AGENT_CAPABILITY_ASSESSMENT_PLAN.md | 15KB | ⭐⭐ | 已过时 |
| **总计** | **58KB** | - | **完整Phase 4.1体系** |

---

## 🎯 立即可做的事

### 核心规划文档

#### 0️⃣ [QUERY_AGENT_E2E_NL_DRIVEN.md](./QUERY_AGENT_E2E_NL_DRIVEN.md)
**📌 新的自然语言驱动版本** - 真正的E2E测试  
**大小**: 800+ 行  
**内容**:
- ✅ 自然语言驱动的E2E测试方法论
- ✅ 测试流程：NL → Agent理解 → 执行 → 文件输出 → 验证
- ✅ Level 1 (20测试): "列出所有设备", "接口有多少个"等
- ✅ Level 2 (40测试): "过去10天流量TOP 10", "启用但无流量的接口"等
- ✅ Level 3 + 5场景 (40测试): 5大网络运维场景详细测试用例
  1. 容量规划 - TOP 10流量接口
  2. 异常检测 - 无流量接口
  3. 关系验证 - 邻接对称性
  4. 趋势分析 - 周环比
  5. 多维分析 - 设备×协议×流量
- ✅ 每个测试的验收标准（4个维度）
- ✅ 执行计划（2周）

**使用场景**:
- π **开发者必读** - 理解新的测试方法
- π 测试工程师 - 100+个具体的测试用例
- π 项目经理 - 完整的工作量预估

**快速导航**:
- 什么是自然语言驱动: "🎯 测试方法论"
- Level 1-3各20测, 40, 40: "📋 Level X"
- 5大场景详细说明: "#### 场景 1-5"

**关键优势**:
- 明确的测试用例（3×level共100+）
- 可直接使用的代码示例
- 每个Level都有详细的SQL逻辑说明（学习用）
- 验收标准清晰（4维度检查）
#### 1️⃣ [QUERY_AGENT_CAPABILITY_ASSESSMENT_PLAN.md](./QUERY_AGENT_CAPABILITY_ASSESSMENT_PLAN.md)
**📌 原始SQL导向计划** - 用于参考（已升级）  
**大小**: 500+ 行  
**状态**: ⚠️ 已被NL_DRIVEN版本取代（保留作为参考）
**内容**（参考价值）:
- 原始的测试架构（现已改为NL驱动）
- 测试数据量要求
- 性能目标

**何时使用**:
- π 理解从SQL到自然语言的演变过程
- π 参考数据模型设计

---

#### 2️⃣ [QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md](./QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md)
**📌 技术实施指南** - 仍然有价值（需更新用自然语言）  
**大小**: 600+ 行  
**部分适用**:
- ✅ 数据库表结构（全部适用）
- ✅ 数据生成脚本说明（全部适用）
- ⚠️ SQL示例（参考价值，但应用时要用自然语言描述）
- ⚠️ 测试代码示例（需转换为NL驱动）

**使用场景**:
- π 理解数据库设计
- π 参考SQL实现细节
- π **更新建议**: 把SQL示例改成NL描述 + CSV验证

---

#### 3️⃣ [QUERY_AGENT_QUICK_START.md](./QUERY_AGENT_QUICK_START.md)
**📌 快速入门指南** - 已更新为NL驱动版  
**大小**: 300+ 行  
**内容**:
- ✅ 5分钟快速开始（新的NL版）
- ✅ 自然语言查询示例（按难度分级）
- ✅ 测试用例编写检查清单
- ✅ 常见陷阱和最佳实践
- ✅ 调试技巧

**使用场景**:
- π **第一次使用时**（快速启动）
- π 需要快速查看SQL技巧时（仍有参考价值）
- π 性能问题紧急排查时

---

### 工具和脚本

#### 4️⃣ [scripts/generate_e2e_test_data.py](../../scripts/generate_e2e_test_data.py)
**📌 测试数据生成脚本** - 自动化数据准备  
**大小**: 400+ 行可执行Python  
**功能**:
- ✅ 创建6个核心表（完整schema）
- ✅ 生成网络拓扑数据
  - 80个设备（Router/Switch/Firewall混合）
  - 1200个接口（多种速率）
  - 3.4M条流量统计记录（10天数据）
  - 60条邻接关系
  - 240条BGP路由
- ✅ 支持参数自定义
- ✅ 创建性能优化索引

**使用**:
```bash
# 基础使用
uv run python scripts/generate_e2e_test_data.py

# 清空后重新生成
uv run python scripts/generate_e2e_test_data.py --clear

# 自定义数据库路径
uv run python scripts/generate_e2e_test_data.py --db ./custom_path.duckdb
```

**输出**:
```
✅ 设备数量: 80
✅ 接口数量: 1200
✅ 流量统计记录: 3,456,000
✅ 邻接关系: 60
✅ BGP路由: 240
```

---

## 🗺️ 文档关联关系

```
QUERY_AGENT_CAPABILITY_ASSESSMENT_PLAN.md (§3: 100+测试用例)
    ↓
    ├→ QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md (§2: 5大场景详解)
    │   ↓
    │   ├→ SQL查询模板（可直接运行）
    │   └→ 测试框架代码示例
    │
    └→ QUERY_AGENT_QUICK_START.md (§2: 场景速查)
        ↓
        ├→ 核心SQL技巧引用
        ├→ 性能基线对比表
        └→ 常见问题解决
```

---

## 📊 文档内容分布

### 按难度等级

| 等级 | 文档 | 小节 | 说明 |
|------|------|------|------|
| ⭐ 入门 | QUICK_START | "5分钟快速开始" | 零基础也能跑 |
| ⭐⭐ 基础 | PLAN | "测试架构" | 理解3层金字塔 |
| ⭐⭐ 基础 | IMPLEMENTATION | "表结构" | 数据schema设计 |
| ⭐⭐⭐ 中级 | QUICK_START | "SQL技巧" | 学习常用模式 |
| ⭐⭐⭐ 中级 | IMPLEMENTATION | "5大场景" | 实施具体查询 |
| ⭐⭐⭐⭐ 高级 | PLAN | "100+测试用例" | 完整测试设计 |
| ⭐⭐⭐⭐⭐ 专家 | IMPLEMENTATION | Section 4 | 测试框架代码 |

### 按工作角色

```
📋 项目经理:
   └→ PLAN.md (Section 1: 时间表和目标)

🧑‍💻 QA/测试工程师:
   ├→ PLAN.md (Section 3: 100+测试用例)
   └→ QUICK_START.md (Section 3: 测试编写检查清单)

🔧 后端开发者:
   ├→ IMPLEMENTATION.md (Section 1: 表结构)
   ├→ IMPLEMENTATION.md (Section 2: 5大场景)
   └→ IMPLEMENTATION.md (Section 4: 框架代码)

📊 数据分析师:
   ├→ QUICK_START.md (Section 2: 场景速查)
   ├→ IMPLEMENTATION.md (Section 2-3: SQL详解)
   └→ IMPLEMENTATION.md (Section 5: SQL技巧)

🚀 DevOps/基础设施:
   └→ generate_e2e_test_data.py (设置测试环境)
```

---

## 🎯 使用场景 - 你会问

### Q1: "我是新开发者，不知道从哪开始？"
**答**: 
1. 读 [QUICK_START.md](./QUERY_AGENT_QUICK_START.md) - "⚡ 5分钟快速开始"
2. 运行数据生成脚本 → `python scripts/generate_e2e_test_data.py --clear`
3. 验证数据 → `uv run pytest ...`

### Q2: "我需要写一个关于流量的查询测试，不知道怎么写？"
**答**:
1. 查看 [IMPLEMENTATION.md](./QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md) - "场景1: 容量规划"
2. 复制SQL模板
3. 参考 [QUICK_START.md](./QUERY_AGENT_QUICK_START.md) - "SQL技巧"完善

### Q3: "我的查询太慢，怎么优化？"
**答**:
1. 对比 [QUICK_START.md](./QUERY_AGENT_QUICK_START.md) - "📊 性能基线"
2. 查看 [QUICK_START.md](./QUERY_AGENT_QUICK_START.md) - "🛠️ 常用SQL技巧" Section 4
3. 运行调试命令 - "🐛 调试技巧"

### Q4: "我需要理解完整的测试覆盖范围？"
**答**: 查看 [PLAN.md](./QUERY_AGENT_CAPABILITY_ASSESSMENT_PLAN.md) - "Section 3"，看100+测试用例列表

### Q5: "我需要编写框架代码或fixtures？"
**答**: 查看 [IMPLEMENTATION.md](./QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md) - "Section 4: 测试框架基础代码"

---

## 📈 学习路径建议

### 路径 A: 我要快速跑一个测试（30分钟）
```
QUICK_START.md (5分钟)
    ↓
运行脚本生成数据 (5分钟)
    ↓
阅读"场景速查"选一个 (5分钟)
    ↓
写简单的pytest用例 (10分钟)
    ↓
运行测试 (5分钟)
```

### 路径 B: 我要系统地理解摸底计划（2小时）
```
QUICK_START.md - 快速了解概念 (20分钟)
    ↓
PLAN.md - 全部阅读 (50分钟)
    ↓
IMPLEMENTATION.md - 5大场景详解 (40分钟)
    ↓
自己动手写一个Level 1和Level 2的测试 (30分钟)
```

### 路径 C: 我要成为Query Agent测试专家（1周）
```
所有文档 (2小时)
    ↓
生成测试数据并 explore (1小时)
    ↓
实现Level 1-3所有100+测试 (30小时)
    ↓
性能分析和优化 (10小时)
    ↓
写摸底报告 (5小时)
```

---

## 🔍 快速参考 - 常用链接

### 我需要...
- 快速启动 → [QUICK_START.md](./QUERY_AGENT_QUICK_START.md)
- 生成测试数据 → [generate_e2e_test_data.py](../../scripts/generate_e2e_test_data.py)
- 理解完整计划 → [PLAN.md](./QUERY_AGENT_CAPABILITY_ASSESSMENT_PLAN.md)
- 5个场景的SQL → [IMPLEMENTATION.md](./QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md) Section 2
- SQL优化建议 → [QUICK_START.md](./QUERY_AGENT_QUICK_START.md) "技巧4"
- 性能基线 → [QUICK_START.md](./QUERY_AGENT_QUICK_START.md) "📊 性能基线"
- 测试框架代码 → [IMPLEMENTATION.md](./QUERY_AGENT_E2E_TEST_IMPLEMENTATION.md) Section 4
- 调试技巧 → [QUICK_START.md](./QUERY_AGENT_QUICK_START.md) "🐛 调试技巧"

---

## 📚 文档统计

| 文档 | 大小 | 字数 | 代码块 | 表格 |
|------|------|------|--------|------|
| PLAN.md | 500+ lines | ~15K | 30+ | 5+ |
| IMPLEMENTATION.md | 600+ lines | ~18K | 40+ | 3+ |
| QUICK_START.md | 300+ lines | ~9K | 20+ | 2+ |
| generate_e2e_test_data.py | 400+ lines | - | - | - |
| **总计** | **1800+ lines** | **~42K** | **90+** | **10+** |

**覆盖范围**:
- ✅ 架构设计: 100%
- ✅ 测试用例: 100+ 具体规范
- ✅ SQL示例: 20+ 完整查询
- ✅ 代码示例: 15+ functional code snippets
- ✅ 最佳实践: 50+ tips and patterns

---

## 🚀 后续工作

### 立即可做
- [ ] 生成测试数据 → `scripts/generate_e2e_test_data.py --clear`
- [ ] 实现Level 1测试 → `tests/e2e/level1/test_basic_queries.py`
- [ ] 实现Level 2测试 → `tests/e2e/level2/test_intermediate_queries.py`
- [ ] 实现Level 3 + 5个场景 → `tests/e2e/level3/test_advanced_queries.py`

### 一周内
- [ ] 运行完整测试套件
- [ ] 收集性能指标
- [ ] 生成摸底报告

### 两周内
- [ ] 识别Query Agent能力缺陷
- [ ] 列出优化建议
- [ ] 规划Phase 4.2（Query Agent优化）

---

**Version**: 1.0.0-planning  
**Last Updated**: 2026-02-08  
**Maintainer**: OLAV Development Team  
**Status**: 📋 Planning Complete, Ready for Implementation
