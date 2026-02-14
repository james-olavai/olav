# Query Agent Issues - 修复完整性检查

**日期**: 2026-02-09  
**文档来源**: `docs/plan/QUERY_AGENT_ISSUES_AND_FIXES.md`  
**状态**: ⚠️ 部分完成

---

## 📊 三大问题修复状态

### ✅ 问题1：数据库配置硬编码 - 50% 完成

#### Phase 1.0: 数据迁移 ✅ 完成
- [x] 创建数据导入脚本 (`scripts/import_network_data.py`)
- [x] 创建快速复制脚本 (`scripts/copy_test_to_prod.py`)
- [x] 执行数据迁移 (test_network → olav.duckdb)
- [x] 验证 Agent 查询生产数据库
- [x] 现状: olav.duckdb 有 80 devices + 1200 interfaces + 106K stats

**成果**: Agent 现在查询正确的数据库 ✅

---

#### Phase 1.1-1.6: 配置分层架构 ❌ 未启动

| Phase | 任务 | 文件 | 状态 |
|-------|------|------|------|
| 1.1 | 扩展 settings.py | `config/settings.py` | ❌ 未做 |
| 1.2 | 修改 paths.py | `config/paths.py` | ❌ 未做 |
| 1.3 | 修改 data_gateway.py | `src/olav/lib/data_gateway.py` | ❌ 未做 |
| 1.4 | 增强 query_database tool | `src/olav/tools/react_query.py` | ❌ 未做 |
| 1.5 | 更新 .env.example | `.env.example` | ❌ 未做 |
| 1.6 | 更新测试脚本 | `quick_l1_test.py`, `run_l2_tests.py` | ❌ 未做 |

**预期完成时间**: 1 天 (4 小时代码 + 4 小时测试)

**预期改善**:
- L1: 67% (6/9) → 89% (8/9)
- L2: 67% (10/15) → 93% (14/15)
- 整体: 67% (16/24) → 92% (22/24)

---

### ❌ 问题2：LLM SQL 生成准确率低 - 0% 完成

#### Phase 2.1: 增强 SKILL.md ❌ 未启动

**任务**: 更新 `.olav/skills/network-query/SKILL.md`

**需要完成的内容**:
- [ ] 添加 "常见字段名错误映射表"
  - device_type → device_role
  - interface → interface_name
  - speed → speed_gbps 或 speed_bps
  - timestamp → created_at 等

- [ ] 添加 "错误恢复协议" 
- [ ] 添加 "Query 构造规则"
- [ ] 添加完整的工作流示例

**参考文档**: QUERY_AGENT_ISSUES_AND_FIXES.md 第 400-600 行

**预期完成时间**: 3 小时

**预期改善**:
- SQL 字段错误: 3 → 0
- SQL 超时失败: 3 → 1
- L1: 89% → 100% (9/9)
- L2: 93% → 100% (15/15)

---

#### Phase 2.2: SQL Validator Middleware ❌ 未启动 (可选)

**任务**: 创建 `src/olav/middleware/sql_validator.py`

**用途**: 执行前验证 SQL，提前捕获字段名错误

**难度**: 中等  
**优先级**: 可选 (Phase 2.1 通常已足够)

**预期完成时间**: 5 小时 (如需实现)

---

### ❌ 问题3：查询缓存未生效 - 0% 完成

#### Phase 0: 诊断调查 ❌ 未启动

**任务**: 检测缓存问题原因

```bash
# 需要运行的诊断命令
uv run python << 'EOF'
# 1. 检查缓存表是否存在
# 2. 检查查询是否写入缓存
# 3. 检查缓存是否被读取
# ...
EOF
```

**三种可能的情况**:
- **情况 A** (50%概率): SemanticQueryCache 代码存在但未集成到 query_database tool
  - 修复: 20 分钟代码修改

- **情况 B** (30%概率): SemanticQueryCache 代码存在但有 Bug
  - 修复: 1-2 小时调试修复

- **情况 C** (20%概率): SemanticQueryCache 根本没实现，只定义了 schema
  - 修复: 3-4 小时完整实现

**参考文档**: QUERY_AGENT_ISSUES_AND_FIXES.md 第 1000-1400 行

**预期完成时间**: 30 分钟 (诊断) + 1-4 小时 (修复)

**预期改善**:
- 首次查询: 32s(不变) 
- 重复查询: 32s → <5s
- 性能: 平均 32s → 15s (50% 改进)
- 缓存命中率: 0% → 60%

---

## 📋 完整实施路径

### 推荐策略：优先级排序

```
优先级1 (必做): 问题1 Phase 1.1-1.6 配置重构
  ├─ 时间: 1 天
  ├─ 预期改获: 67% → 92% (+25%)
  └─ 理由: 是导致 P2 测试失败的根本原因

优先级2 (应做): 问题2 Phase 2.1 SKILL 增强
  ├─ 时间: 3-5 小时
  ├─ 预期改进: 92% → 100% (+8%)
  └─ 理由: 简单且能达到完美通过率

优先级3 (可做): 问题3 缓存修复
  ├─ 时间: 30 分钟 + 1-4 小时
  ├─ 预期改进: 性能 32s → 15s (user experience, not test pass rate)
  └─ 理由: 不影响功能，但能大幅改善用户体验

可选 (如时间充足): 问题2 Phase 2.2 SQL Validator
  ├─ 时间: 5 小时
  ├─ 预期效果: 更强的 error prevention
  └─ 理由: 作为 Phase 2.1 的强化，可选
```

---

## 📅 建议实施计划

### 今天 (2026-02-09)
- [ ] 运行 Phase 1.1-1.6 的代码修改 (1 小时 core, 1 小时测试)
- [ ] 验证 L1/L2 测试通过率改善

### 明天 (2026-02-10)  
- [ ] 实施 Phase 2.1 SKILL.md 增强 (3 小时)
- [ ] 验证 L1/L2/L3 测试通过率达到目标

### 后天 (2026-02-11)
- [ ] Phase 0 缓存诊断 (30 分钟)
- [ ] 根据诊断结果实施缓存修复 (1-4 小时)
- [ ] 性能测试和优化

---

## 🎯 成功标准

### 功能验收 (Phase 1 + 2)
```
✅ L1 通过: 9/9 (100%)
✅ L2 通过: 15/15 (100%)
✅ 整体通过: 24/24 (100%)
```

### 性能验收 (Phase 3)
```
✅ 首次查询: < 35 秒
✅ 重复查询: < 5 秒
✅ 平均响应: < 20 秒 (可选)
```

### 配置验收 (Phase 1)
```
✅ 环境变量 OLAV_DB_PATH 可覆盖
✅ settings.py 支持自定义路径
✅ 生产/测试环境隔离
```

---

## 复核清单

### 数据库问题（问题1）
- [x] 数据迁移完成
- [x] Agent 查询正确数据库
- [ ] **配置分层完整实现** ← **需要启动**
- [ ] 环境变量支持
- [ ] 文档更新

### SQL 准确性（问题2）
- [ ] **SKILL.md 增强字段映射** ← **需要启动**
- [ ] 错误恢复协议
- [ ] (可选) SQL Validator middleware

### 查询缓存（问题3）
- [ ] **缓存诊断** ← **需要启动**
- [ ] 缓存集成修复
- [ ] 性能基线测试

---

## 文档位置

| 文档 | 位置 | 用途 |
|------|------|------|
| 完整问题分析 | `docs/plan/QUERY_AGENT_ISSUES_AND_FIXES.md` | Phase 1-3 详细设计 |
| 数据库分析 | `docs/plan/DATABASE_ARCHITECTURE_ANALYSIS.md` | 为什么数据在两个不同 DB |
| 迁移总结 | `docs/plan/PRODUCTION_DATABASE_MIGRATION.md` | Phase 1.0 执行总结 |
| 清理计划 | `docs/plan/TEST_CLEANUP_AND_NEXT_STEPS.md` | 后续清理和生产准备 |

---

## 核心建议

### ✅ 立即启动
1. **Phase 1.1-1.6** (配置分层) - 今天完成
   - 最高优先级，能带来最大改进 (25%)
   - 内容清晰，实施直接
   - 预计 1 天完成

2. **Phase 2.1** (SKILL.md) - 明天完成
   - 简单有效，补完 L1/L2 缺口 (8%)
   - 预计 3 小时完成

### ⏳ 后续启动
3. **Phase 0 + Phase 3** (缓存修复) - 后天
   - 不影响功能，但改善性能 (32s → 15s)
   - 需要先诊断确定修复方案

### ℹ️ 可选项
- **Phase 2.2** (SQL Validator) - 仅在时间充足且需要加固

---

**总体评估**: 文档设计完整，但实施尚未开始 (除了数据迁移部分)。三个问题都需要代码修改，建议按优先级顺序依次完成。

**预计总工作量**: 2-3 天可完全解决所有问题，达到 100% 通过率 + 性能优化。
